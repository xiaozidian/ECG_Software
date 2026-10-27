'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const engine = require('../static/js/report-engine.js');
const source = fs.readFileSync('static/js/clinical-ui.js', 'utf8');

function production(context, name, asynchronous = false) {
  const start = source.indexOf(`  ${asynchronous ? 'async ' : ''}function ${name}(`);
  assert(start >= 0, `Missing production function ${name}`);
  const end = source.indexOf('\n  }', start) + 4;
  vm.runInContext(source.slice(start, end), context);
}

function host() {
  const nodes = new Map();
  const node = selector => {
    if (!nodes.has(selector)) {
      nodes.set(selector, {
        value: '', textContent: '', innerHTML: '', style: {}, disabled: false,
        dataset: {bound: selector.includes('start') ? 'start' : 'end'},
        addEventListener() {}
      });
    }
    return nodes.get(selector);
  };
  return {
    isConnected: true, style: {setProperty() {}}, addEventListener() {},
    querySelector: node,
    querySelectorAll: selector => selector === '[data-bound]'
      ? [node('[data-bound=start]'), node('[data-bound=end]')]
      : selector === 'button,input'
        ? [node('[data-range-apply]'), node('[data-range-reset]'), node('[data-bound=start]'), node('[data-bound=end]')]
        : [node(selector)]
  };
}

const tick = () => new Promise(resolve => setImmediate(resolve));

(async () => {
  const event = {
    event_id: 'synthetic-first-apply', basis_version: 'synthetic-v1',
    category: 'fastest', label: 'Synthetic event', start_sample: 2000, end_sample: 2001
  };
  const wave = {
    start_s: 0, duration_s: 30, sample_rate_hz: 200,
    leads: {II: [0, 1, 0]},
    beats: Array.from({length: 6}, (_, index) => ({sample_index: (7 + index) * 200, class_code: 'N'}))
  };
  const state = {
    caseId: 'synthetic-A', caseRequestId: 1, currentPage: 'report',
    reportDisplayedCategory: 'fastest', caseData: {technical: {duration_seconds_raw: 30}},
    reportComposition: {
      selected_events: [], category_reviews: {}, diagnosis_blocks: [],
      strip_defaults: {leads: ['II'], duration_s: 7}
    }
  };
  let editor, rendered = 0, validated, finishValidation;
  const requests = [];
  const validation = new Promise(resolve => { finishValidation = resolve; });
  const target = {
    isConnected: true,
    replaceChildren(next) {
      if (editor) editor.isConnected = false;
      editor = next;
    }
  };
  const context = vm.createContext({
    state, CustomEvent: class { constructor(type) { this.type = type; } },
    document: {
      dispatchEvent() {}, createElement: () => host(),
      querySelectorAll: selector => selector === '.report-range-editor' ? [editor] : []
    },
    waveToken: 1, reportRenderToken: 1, category: 'fastest',
    waveEvidenceScope: 'synthetic-r1', waveEvidence: {}, reportWaveCache: new Map(),
    reportData: {items: [event]}, A: {categories: [['fastest', 'Fastest']]},
    active: event, reportWaveReady: true, ECGReviewTools: {markSvg: () => ''},
    ECGReportEngine: engine,
    endpoint: async (kind, params, id) => {
      assert.equal(id, state.caseId);
      if (kind === 'waveform') return wave;
      assert.equal(kind, 'report-strip');
      assert.equal(params.event_id, event.event_id);
      assert.equal(params.basis_version, event.basis_version);
      assert.equal(params.range_end_s, 14);
      requests.push({...params});
      const strip = engine.resolve({duration_s: 30, rows: wave.beats}, event, {
        leads: params.leads.split(','), duration_s: Number(params.duration),
        range_start_s: params.range_start_s, range_end_s: params.range_end_s
      });
      assert.equal(params.range_start_s, 8);
      assert.equal(strip.visible_beat_count, 5, 'The submitted custom interval must pass the five-beat validation');
      validated = {params: {...params}, strip};
      await validation;
      return {sample_index: event.start_sample, strip, waveform: wave};
    },
    selected: () => state.reportComposition.selected_events, selectedLookup: new Map(),
    returnedRhythmSelection: () => false, qs: () => null,
    copy: value => JSON.parse(JSON.stringify(value)),
    syncText() {}, dirty() {}, renderReportShell() {}, renderEventNavigation() {},
    run: callback => Promise.resolve().then(callback),
    renderReportBody: async () => {
      rendered++;
      // The rebuilt body mounts an editor against the validated, applied range.
      context.waveToken++;
      context.reportRenderToken++;
      const entry = await context.reportStrip(event, state.reportComposition.selected_events[0], state.caseId);
      await context.mountRange(target, event, entry, state.caseId);
    }
  });
  context.document.addEventListener=()=>{};
  vm.runInContext(fs.readFileSync('static/js/report-strip-editor.js','utf8'),context);
  context.ECGOccurrenceCard=require('../static/js/occurrence-card.js');
  vm.runInContext(fs.readFileSync('static/js/report-range-editor.js', 'utf8'), context);
  production(context, 'selectEvent');
  production(context, 'reportStrip', true);
  production(context, 'mountRange', true);
  await context.mountRange(target, event, {
    sample_index: 2000,
    strip: {start_s: 7, end_s: 14, actual_duration_s: 7, duration_s: 7, leads: ['II']}
  }, state.caseId);
  const oldEditor = editor;
  editor.querySelector('[data-bound=start]').value = '9';
  editor.querySelector('[data-bound=start]').onchange();
  await editor.querySelector('[data-range-apply]').onclick();
  assert.equal(requests[0].range_start_s, 9);
  assert.equal(requests[0].range_end_s, 14);
  assert.match(editor.querySelector('.range-error').textContent, /至少包含 5 个可用心搏/);
  assert.equal(rendered, 0, 'A rejected interval must keep the editor and its temporary bounds');
  assert.equal(context.ECGReportRange.pending().length, 1);
  assert.equal(context.ECGReportRange.pending()[0].a, 9);
  assert.equal(state.reportComposition.selected_events.length, 0);
  assert.throws(() => context.ECGReportRange.assertApplied(), /尚未应用/);

  editor.querySelector('[data-bound=start]').value = '8';
  editor.querySelector('[data-bound=start]').onchange();
  assert.equal(context.ECGReportRange.pending().length, 1);
  assert.equal(state.reportComposition.selected_events.length, 0);
  assert.throws(() => context.ECGReportRange.assertApplied(), /尚未应用/);

  const applying = editor.querySelector('[data-range-apply]').onclick();
  await tick();
  assert(validated, 'Applying must remotely revalidate the actual custom interval');
  assert.equal(context.ECGReportRange.pending().length, 1);
  assert.equal(state.reportComposition.selected_events.length, 0);
  assert.throws(() => context.ECGReportRange.assertApplied(), /尚未应用/);
  finishValidation();
  await applying;

  assert.equal(rendered, 1, 'Explicit interval application must rebuild the editor baseline');
  assert.notStrictEqual(editor, oldEditor);
  const selection = state.reportComposition.selected_events[0];
  assert.equal(selection.event_id, event.event_id);
  assert.equal(selection.basis_version, event.basis_version);
  assert.equal(selection.caption, event.label);
  assert.equal(selection.range_start_s, 8);
  assert.equal(selection.range_end_s, 14);
  assert.equal(context.ECGReportRange.pending().length, 0, 'A successful first application must clear its temporary interval');
  assert.doesNotThrow(() => context.ECGReportRange.assertApplied());
  const status = editor.querySelector('output').innerHTML;
  assert.match(status, /当前已应用区间.*00:00:08\.000.*00:00:14\.000/);
  assert.doesNotMatch(status, /待应用区间/);
  assert.doesNotMatch(status, /00:00:07\.000/, 'The editor must no longer report the old seven-second baseline');
  console.log('First custom interval inclusion: five-beat validation, pending-write blocking, editor baseline rebuild and save allowance passed');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
