'use strict';
// Actual ST-T adoption handler with deterministic in-flight draft saves.
// Disposable metadata only: no services, patient data, or report database.
const assert = require('node:assert/strict');
const vm = require('node:vm');
const helpers = require('./clinical_ui_report_helpers.cjs');
const engine = require('../static/js/report-engine.js');
const clone = value => JSON.parse(JSON.stringify(value));
const tick = () => new Promise(resolve => setImmediate(resolve));
const gate = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); promise.catch(() => {}); return {promise, resolve, reject}; };
function fixture() {
  const event = {event_id: 'annotation:mathematical-wait', category: 'ST', basis_version: 'record-v3',
    label: 'ST-T mathematical review', stt_review_state: 'reviewed',
    stt_report_eligibility: {table: true, text: true, strip: true}};
  const composition = {schema_version: 3, included_pages: ['summary'], category_reviews: {},
    diagnosis_blocks: [{key: 'manual', text: 'Preserved mathematical free text', manual: true}],
    selected_events: [], stt_report_use: []};
  const state = {caseId: 'mathematical-wait', caseRequestId: 5, currentPage: 'report',
    reportComposition: composition, reportSaving: false, reportStale: false};
  const calls = {dirty: 0, sync: 0, located: 0};
  const context = vm.createContext({state, category: 'ST', waveEvidenceScope: 'basis-A', reportSavePromise: null,
    active: event, selectedLookup: new Map([[event.event_id, event]]),
    composition: () => state.reportComposition, copy: clone, qs: () => null,
    selectionForEvent: e => state.reportComposition.selected_events.find(p => p.event_id === e.event_id) || null,
    newStripSettings: (e, settings) => engine.settingsForEvent(e, settings || {}),
    ECGReportRange: {pending: () => [], forget() {}},
    dirty() { calls.dirty++; }, syncText() { calls.sync++; },
    renderReportShell() {}, syncSTTControls() {}, locate: async () => { calls.located++; }
  });
  helpers.prepare(context);
  // Retain the real syncSTTControls, but no DOM exists in this narrow fixture.
  context.document = {querySelectorAll: () => []};
  context.renderEventNavigation = () => {};
  context.reportWaveReady = true;
  return {context, state, event, calls};
}
function start(x, key, checked) {
  const observed = {settled: false, error: null};
  observed.task = x.context.setSTTUse(x.event, key, checked).then(
    value => { observed.settled = true; return value; },
    error => { observed.settled = true; observed.error = error; }
  );
  return observed;
}
function saving(x) {
  const request = gate(); x.context.reportSavePromise = request.promise; x.state.reportSaving = true;
  return {request, finish({fail = false, next = null} = {}) {
    x.context.reportSavePromise = next?.promise || null; x.state.reportSaving = !!next;
    if (fail) request.reject(Error('save-transport-failed')); else request.resolve();
  }};
}
const usage = x => x.state.reportComposition.stt_report_use.find(u => u.event_id === x.event.event_id);

async function wait() {
  for (const key of ['table', 'text', 'strip']) {
    const x = fixture(), pending = saving(x), before = JSON.stringify(x.state.reportComposition);
    const intent = start(x, key, true); await tick();
    assert.equal(intent.settled, false, key + ': enabled checkbox intent was rejected rather than waiting for the existing save');
    assert.equal(JSON.stringify(x.state.reportComposition), before); assert.equal(x.calls.dirty, 0);
    // A successful autosave replaces equal composition objects in production.
    x.state.reportComposition = clone(x.state.reportComposition); pending.finish(); await intent.task;
    assert.equal(intent.error, null); assert.equal(usage(x)[key], true);
    assert.equal(x.calls.dirty, 1); assert.equal(x.state.reportComposition.selected_events.length, key === 'strip' ? 1 : 0);
    assert.equal(x.state.reportComposition.diagnosis_blocks[0].text, 'Preserved mathematical free text');
  }
  // A follow-up save that starts before the previous promise resumes must also settle.
  const x = fixture(), one = saving(x), intent = start(x, 'table', true), two = gate();
  await tick(); one.finish({next: two}); await tick();
  assert.equal(intent.settled, false); assert.equal(x.calls.dirty, 0);
  x.context.reportSavePromise = null; x.state.reportSaving = false; two.resolve(); await intent.task;
  assert.equal(intent.error, null); assert.equal(usage(x).table, true);
  console.log('PASS wait: table/text/strip choices survive current and chained save snapshots without premature writes');
}
async function intents() {
  const x = fixture(), pending = saving(x);
  const choices = [['table', true], ['text', true], ['strip', true], ['table', false]];
  const tasks = choices.map(([key, checked]) => start(x, key, checked)); await tick();
  assert(tasks.every(t => !t.settled), 'Multiple explicit purposes must wait together');
  pending.finish(); await Promise.all(tasks.map(t => t.task));
  assert(tasks.every(t => !t.error));
  assert.deepEqual(clone(usage(x)), {event_id: x.event.event_id, basis_version: x.event.basis_version,
    table: false, text: true, strip: true});
  assert.equal(x.state.reportComposition.selected_events.length, 1);
  assert.equal(x.state.reportComposition.selected_events[0].leads.length, 12);
  const removal = saving(x), cancel = start(x, 'strip', false); await tick();
  assert.equal(cancel.settled, false); removal.finish(); await cancel.task;
  assert.equal(cancel.error, null); assert.equal(usage(x).text, true); assert.equal(usage(x).strip, false);
  assert.equal(x.state.reportComposition.selected_events.length, 0);
  console.log('PASS intents: multiple purposes, last checkbox intent and graph withdrawal preserve independent text/manual content');
}
async function changed() {
  const changes = {
    case: x => { x.state.caseId = 'other'; },
    reopen: x => { x.state.caseRequestId++; },
    basis: x => { x.context.waveEvidenceScope = 'basis-B'; },
    category: x => { x.context.category = 'AF'; },
    page: x => { x.state.currentPage = 'stt'; },
    stale: x => { x.state.reportStale = true; },
    loading: x => { x.state.reportEvidenceLoading = true; },
    eligibility: x => { x.event.stt_review_state = 'stale'; x.event.stt_report_eligibility.strip = false; }
  };
  for (const [name, change] of Object.entries(changes)) {
    const x = fixture(), pending = saving(x), intent = start(x, 'strip', true); await tick();
    change(x); const before = JSON.stringify(x.state.reportComposition); pending.finish(); await intent.task;
    assert(intent.error, name + ': stale queued intent applied to a changed context');
    assert.match(intent.error.message, /变化|核对|尚未|支持|复核/, name);
    assert.equal(JSON.stringify(x.state.reportComposition), before); assert.equal(x.calls.dirty, 0);
  }
  // Saved uses can be replaced while a network save is in flight. Never rebind old proof.
  const x = fixture(), pending = saving(x), intent = start(x, 'strip', true); await tick();
  x.state.reportComposition.stt_report_use = [{event_id: x.event.event_id, basis_version: 'old-record', table: false, text: true, strip: false}];
  pending.finish(); await intent.task;
  assert.match(intent.error?.message || '', /旧复核/);
  assert.equal(usage(x).basis_version, 'old-record'); assert.equal(usage(x).text, true); assert.equal(usage(x).strip, false);
  assert.equal(x.calls.dirty, 0);
  console.log('PASS changed: case/reopen/basis/category/page/save eligibility changes and old proof prevent queued adoption');
}
async function failures() {
  const x = fixture(), pending = saving(x), before = JSON.stringify(x.state.reportComposition);
  const intent = start(x, 'table', true); await tick(); pending.finish({fail: true}); await intent.task;
  assert.match(intent.error?.message || '', /save-transport-failed/);
  assert.equal(JSON.stringify(x.state.reportComposition), before); assert.equal(x.calls.dirty, 0);
  const recovery = start(x, 'table', true); await recovery.task;
  assert.equal(recovery.error, null); assert.equal(usage(x).table, true);
  const invalid = fixture(); invalid.event.stt_review_state = 'unreviewed';
  const rejected = start(invalid, 'table', true); await rejected.task;
  assert.match(rejected.error?.message || '', /尚未|复核/); assert.equal(invalid.calls.dirty, 0);
  console.log('PASS failures: failed save does not mutate adoption, retry works, unreviewed records stay blocked');
}
const groups = {wait, intents, changed, failures};
(async () => {
  const name = process.argv[2];
  if (name) { assert(groups[name], 'Unknown scenario ' + name); await groups[name](); }
  else for (const run of Object.values(groups)) await run();
})().catch(error => { console.error(error); process.exitCode = 1; });
