'use strict';

// Production report callbacks and preview function, with disposable metadata only.
// No services, patient inputs, browser PDF, or clinical-accuracy assertions.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/js/clinical-ui.js', 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
const clone = value => JSON.parse(JSON.stringify(value));
const gate = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
};
function production(context, name) {
  const start = source.indexOf('  async function ' + name + '(');
  const end = source.indexOf('\n  }', start);
  assert(start >= 0 && end > start, 'Missing production function ' + name);
  vm.runInContext(source.slice(start, end + 4), context);
}
class Node extends EventTarget {
  constructor(tag = 'div') {
    super();
    this.tagName = tag.toUpperCase(); this.isConnected = true;
    this.open = false; this.dataset = {}; this.attrs = {}; this.children = [];
    this.pendingCloses = []; this.deferCloseEvents = false;
    this.classList = {toggle() {}, add() {}, remove() {}};
    this.value = ''; this._html = ''; this._text = '';
  }
  set innerHTML(value) { this._html = value; this._text = ''; }
  get innerHTML() { return this._html; }
  set textContent(value) { this._text = value; this._html = ''; }
  get textContent() { return this._text; }
  append(...nodes) { this.children.push(...nodes); }
  appendChild(node) { this.append(node); return node; }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  removeAttribute(key) { delete this.attrs[key]; }
  contains() { return false; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  showModal() { this.open = true; }
  close() {
    if (!this.open) return;
    this.open = false;
    const dispatch = () => { this.dispatchEvent(new Event('close')); this.onclose?.(new Event('close')); };
    if (this.deferCloseEvents) this.pendingCloses.push(dispatch); else dispatch();
  }
  flushCloses() { for (const callback of this.pendingCloses.splice(0)) callback(); }
  escape() {
    const event = new Event('cancel', {cancelable: true});
    this.dispatchEvent(event); this.oncancel?.(event);
    if (!event.defaultPrevented) this.close();
  }
}
class Dialog extends Node {
  constructor() { super('dialog'); this.replaceContents(); }
  replaceContents() {
    if (this.body) this.body.isConnected = false;
    this.body = new Node(); this.button = new Node('button');
  }
  set innerHTML(value) { super.innerHTML = value; this.replaceContents(); }
  get innerHTML() { return super.innerHTML; }
  querySelector(selector) { return selector === 'button' ? this.button : this.body; }
}
function fixture() {
  const composition = {included_pages: ['st_trend', 't_trend', 'st_events'],
    selected_events: [], diagnosis_blocks: [], stt_trend_metric: 'st_level'};
  const state = {caseId: 'mathematical-preview', caseRequestId: 8, currentPage: 'report',
    privacyRequestId: 2, reportDirty: false, reportSaving: false, reportStale: false,
    report: {version: 3, review_revision: 4, status: 'draft'}, reportComposition: composition,
    caseData: {case_id: 'mathematical-preview', metadata: {name: 'MATHEMATICAL'},
      summary: {}, clinical_identity: {analysis_basis: 'basis-A', analysis_revision: 4}}};
  const host = new Node(), page = new Node(), editor = new Node('textarea');
  editor.value = 'Unchanged mathematical report text';
  let dialog = new Dialog(), callbacks, dirty = 0;
  const reads = [], renders = [];
  const context = vm.createContext({
    state, document: {createElement: tag => tag === 'dialog' ? (dialog = new Dialog()) : new Node(tag), body: {appendChild() {}}},
    qs: selector => selector === '#rwPaperPreview' ? dialog : selector === '#conclusionEditor' ? editor :
      selector === '#reportV2Content' ? host : selector === '#page-report' ? page : null,
    composition: () => composition, selected: () => composition.selected_events,
    selectedLookup: new Map(), category: 'final', reportCategories: [], reportRenderToken: 7,
    reportData: {analysis_basis: 'basis-A', analysis_revision: 4},
    renderStripUndo() {}, renderReportShell() {}, dirty() { dirty++; }, copy: clone,
    api() { throw Error('VM preview must not use network'); },
    resolveWorkstationLeave: async () => true,
    ECGReportRange: {assertApplied() {}}, ECGAdvancedAnalysis: {assertApplied() {}},
    ECGHRVEditor: {assertApplied() {}},
    ECGReportSections: {validate() {}, catalog: () => []},
    ECGReportConsistency: {content: (text, data) => JSON.stringify([text, data])},
    ECGReportWorkspace: {releaseTerminology() {}, compose(node, options) { assert.equal(node, host); callbacks = options; }},
    ECGReportPaper: {render(model) { renders.push(model.case.marker); return '<p>' + model.case.marker + '</p>'; }, number() {}},
    paperModel: () => ({report: state.report}),
    readPaperEvidence() { const request = gate(); reads.push(request); return request.promise; },
    run: fn => Promise.resolve().then(fn)
  });
  production(context, 'previewPaper'); production(context, 'renderReportBody');
  const result = marker => ({caseData: {marker}, statistics: {}, entries: [], hrvData: null, evidence: {}});
  return {context, state, editor, composition, host, reads, renders, result,
    get dialog() { return dialog; }, get callbacks() { return callbacks; }, get dirty() { return dirty; }};
}
async function preview(f) { const task = f.context.previewPaper(); await tick(); return {task}; }
function close(f, mode) { if (mode.includes('escape')) f.dialog.escape(); else f.dialog.button.onclick(); }

async function lifecycle() {
  for (const mode of ['close', 'escape']) {
    const f = fixture(); await f.context.renderReportBody();
    const callbacks = f.callbacks;
    callbacks.onSTTrendMetric('delta'); assert.equal(f.composition.stt_trend_metric, 'delta');
    const {task} = await preview(f); f.reads[0].resolve(f.result('current')); await task;
    close(f, mode); assert.equal(f.dialog.open, false);
    callbacks.onSTTrendMetric('st_level');
    assert.equal(f.composition.stt_trend_metric, 'st_level', mode + ': closing preview disabled the existing ST trend callback');
    assert.equal(f.dirty, 2, 'Both actual report-body callbacks must persist the selected trend metric');
    const stale = f.callbacks;
    f.context.reportRenderToken++;
    stale.onSTTrendMetric('delta');
    assert.equal(f.composition.stt_trend_metric, 'st_level', 'An actual body replacement must still invalidate its old callback');
  }
  console.log('PASS lifecycle: actual compose ST-trend callback survives preview close/ESC, and genuine body invalidation still rejects');
}
async function races() {
  for (const mode of ['close', 'escape', 'queued-close', 'queued-escape']) for (const outcome of ['old-first', 'old-last', 'old-error']) {
    const f = fixture(); f.dialog.deferCloseEvents = mode.startsWith('queued-');
    const first = await preview(f);
    assert.equal(f.reads.length, 1); assert(f.dialog.open);
    await f.context.previewPaper(); assert.equal(f.reads.length, 1, 'Duplicate open must not start an extra evidence request');
    close(f, mode); const second = await preview(f);
    assert.equal(f.reads.length, 2); assert(f.dialog.open);
    f.dialog.flushCloses();
    assert(f.dialog.open, 'A queued old close event must not close the reopened dialog');
    const newBody = f.dialog.body;
    if (outcome === 'old-first') {
      f.reads[0].resolve(f.result('obsolete-first')); await first.task;
      assert.equal(f.renders.length, 0, 'Closed request rendered into a newly opened preview');
      assert.doesNotMatch(newBody.innerHTML + newBody.textContent, /obsolete-first/);
      f.reads[1].resolve(f.result('newest')); await second.task;
    } else {
      f.reads[1].resolve(f.result('newest')); await second.task;
      if (outcome === 'old-error') f.reads[0].reject(Error('obsolete-read-error'));
      else f.reads[0].resolve(f.result('obsolete-last'));
      await first.task;
    }
    assert.deepEqual(f.renders, ['newest'], mode + '/' + outcome + ': stale request reached production paper rendering');
    assert.equal(f.dialog.body, newBody); assert.match(newBody.innerHTML, /newest/);
    assert.doesNotMatch(newBody.innerHTML + newBody.textContent, /obsolete|失败/);
  }
  console.log('PASS races: close/ESC and delayed close events, duplicate open, obsolete early/late success and late error cannot replace the newest preview');
}
async function guards() {
  const changes = {
    case: f => { f.state.caseId = 'other'; },
    reopen: f => { f.state.caseRequestId++; },
    basis: f => { f.context.reportData.analysis_basis = 'basis-B'; f.context.reportRenderToken++; },
    version: f => { f.state.report.version++; },
    revision: f => { f.state.report.review_revision++; },
    status: f => { f.state.report.status = 'reviewed'; },
    text: f => { f.editor.value += ' changed'; },
    composition: f => { f.composition.included_pages.push('summary'); },
    saving: f => { f.state.reportSaving = true; },
    stale: f => { f.state.reportStale = true; },
    privacy: f => { f.state.privacyRequestId++; },
    range: f => { f.context.ECGReportRange.assertApplied = () => { throw Error('pending-range'); }; }
  };
  for (const [name, change] of Object.entries(changes)) {
    const f = fixture(), {task} = await preview(f); change(f);
    f.reads[0].resolve(f.result('must-not-render'));
    let error; try { await task; } catch (caught) { error = caught; }
    if (error) assert.match(error.message, /变化|更新|修改|保存|pending-range/, name);
    assert.equal(f.renders.length, 0, name + ': changed evidence or report reached paper rendering');
    assert.doesNotMatch(f.dialog.body.innerHTML + f.dialog.body.textContent, /must-not-render/);
  }
  console.log('PASS guards: case/reopen/basis/report-version/revision/status/text/composition/save/stale/privacy/range changes reject late rendering');
}
const groups = {lifecycle, races, guards};
(async () => {
  const requested = process.argv[2];
  if (requested) { assert(groups[requested], 'Unknown test group ' + requested); await groups[requested](); }
  else for (const run of Object.values(groups)) await run();
})().catch(error => { console.error(error); process.exitCode = 1; });
