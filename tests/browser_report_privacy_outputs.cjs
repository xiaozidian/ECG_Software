'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const consistency = require('../static/js/analysis-consistency.js');
const source = fs.readFileSync('static/js/clinical-ui.js', 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
const mutations = ['epoch', 'saving', 'identity-pending', 'aba', 'none'];
const privacyError = /身份|隐私|更新|变化/;

function gate() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return {promise, resolve};
}

function production(context, name, asynchronous = true) {
  const start = source.indexOf(`  ${asynchronous ? 'async ' : ''}function ${name}(`);
  assert(start >= 0, `Missing production function ${name}`);
  const end = source.indexOf('\n  }', start) + 4;
  vm.runInContext(source.slice(start, end), context);
}

function element(tag = 'div') {
  return {
    tagName: tag.toUpperCase(), isConnected: true, open: false, textContent: '',
    innerHTML: '', value: '', disabled: false, hidden: false, title: '', attrs: {}, dataset: {},
    setAttribute(key, value) { this.attrs[key] = String(value); },
    removeAttribute(key) { delete this.attrs[key]; },
    addEventListener() {}, append(node) { this.appended = node; },
    showModal() { this.open = true; }, close() { this.open = false; },
    remove() { this.isConnected = false; this.removed = true; }
  };
}

function initialState() {
  return {
    caseId: 'synthetic-A', caseRequestId: 7, privacyRequestId: 3, privacySaving: false,
    includePhi: true, demoReadonly: true,
    caseData: {case_id: 'synthetic-A', metadata: {name: 'SYNTHETIC_VISIBLE', patient_id: 'SYNTHETIC_ID'}},
    report: {version: 2, review_revision: 1, conclusion: 'synthetic conclusion'},
    reportComposition: {included_pages: ['cover'], selected_events: [], hrv_window: 1}
  };
}

function mutate(state, kind) {
  if (kind === 'epoch') { state.privacyRequestId++; state.includePhi = false; }
  if (kind === 'saving') state.privacySaving = true;
  if (kind === 'identity-pending') state.privacyIdentityPending = true;
  if (kind === 'aba') {
    state.includePhi = false; state.privacyRequestId++;
    state.includePhi = true; state.privacyRequestId++;
  }
}

function printFixture(phase) {
  const state = initialState(), fonts = gate(), nodes = new Map();
  const events = new EventTarget();
  let listeners = 0;
  const style = {sheet: phase !== 'styles'};
  let printed = 0, focused = 0, numbered = 0, html = '', frame;
  const doc = {
    open() {}, write(value) { html = value; }, close() {},
    querySelector(selector) { assert.equal(selector, 'link'); return style; },
    fonts: {ready: fonts.promise}, body: {}
  };
  const context = vm.createContext({
    state, URL, Event, location: {href: 'http://synthetic.test/'}, esc: String,
    qs: selector => selector === '#v2PrintFrame' ? frame?.isConnected ? frame : null : nodes.get(selector) || null,
    ECGReportPaper: {number(node) { if (node === doc.body) numbered++; }},
    document: {
      addEventListener(type, callback) { listeners++; events.addEventListener(type, callback); },
      removeEventListener(type, callback) { listeners--; events.removeEventListener(type, callback); },
      dispatchEvent: event => events.dispatchEvent(event),
      querySelectorAll: () => [],
      createElement(tag) {
        assert.equal(tag, 'iframe');
        frame = element(tag); frame.contentDocument = doc;
        frame.contentWindow = {focus() { focused++; }, print() { printed++; }};
        return frame;
      },
      body: {appendChild() {}}
    }
  });
  production(context, 'printHtml');
  return {
    context, state, fonts, style, nodes,
    get frame() { return frame; }, get printed() { return printed; },
    get focused() { return focused; }, get numbered() { return numbered; },
    get listeners() { return listeners; },
    get html() { return html; },
    release() { if (phase === 'styles') style.onload(); fonts.resolve(); }
  };
}

async function hrv() {
  for (const phase of ['styles', 'fonts']) for (const change of mutations) {
    const fixture = printFixture(phase), {context, state} = fixture;
    const children = new Map(), panel = element();
    panel.querySelector = selector => {
      if (!children.has(selector)) children.set(selector, element());
      return children.get(selector);
    };
    fixture.nodes.set('#hrvWindowPanel', panel);
    const data = {analysis_basis: 'synthetic-basis', analysis_revision: 1, window_index: 1};
    Object.assign(context, {
      reportCase: state.caseId, reportVersion: state.report.version, hrvToken: 0, hrv: null,
      copy: value => JSON.parse(JSON.stringify(value)), composition: () => state.reportComposition,
      ECGAnalysisConsistency: consistency,
      ECGHrvReport: {ui: () => 'synthetic HRV controls', pages: () => '<p>SYNTHETIC_VISIBLE HRV paper</p>'},
      paperModel: () => ({case: state.caseData, report: {status: 'draft'}}),
      endpoint: async () => ({...data}), run: callback => Promise.resolve().then(callback)
    });
    production(context, 'loadHrv');
    await context.loadHrv('#hrvWindowPanel', 1, data);
    const task = panel.querySelector('[data-hrv-export]').onclick();
    await tick();
    assert(fixture.frame, 'The real HRV export hook must reach the real printHtml function');
    assert.match(fixture.html, /SYNTHETIC_VISIBLE/);
    assert.equal(fixture.printed, 0);
    mutate(state, change);
    const result = change === 'none' ? task : assert.rejects(task, privacyError);
    fixture.release();
    await result;
    assert.equal(fixture.printed, change === 'none' ? 1 : 0, `${phase}/${change}: old HRV identity printed`);
    assert.equal(fixture.focused, change === 'none' ? 1 : 0);
    if (change !== 'none') assert(fixture.frame.removed, 'Failed HRV printing must remove its identity snapshot');
    assert.equal(state.caseRequestId, 7, 'Privacy protection must not invalidate the clinical case token');
    if (change === 'none') {
      state.privacyIdentityPending = true;
      await assert.rejects(panel.querySelector('[data-hrv-export]').onclick(), privacyError);
      state.privacyIdentityPending = false; state.privacySaving = true;
      await assert.rejects(panel.querySelector('[data-hrv-export]').onclick(), privacyError);
      assert.equal(fixture.printed, 1, 'Busy or pending identity must reject a new HRV output before creating a second print');
    }
  }
  console.log('Privacy HRV: styles/font waits reject epoch, busy and ABA changes; unchanged print succeeds once');
}

async function preview() {
  for (const change of mutations) {
    const state = initialState(), caseRead = gate(), dialog = element('dialog');
    const body = element(), close = element('button'), conclusion = {value: state.report.conclusion};
    dialog.querySelector = selector => selector === 'button' ? close : body;
    let rendered = 0, reads = 0;
    const basis = {analysis_basis: 'synthetic-basis', analysis_revision: 1};
    const context = vm.createContext({
      state, URLSearchParams, reportRenderToken: 0, qs: selector => selector === '#rwPaperPreview' ? dialog : conclusion,
      composition: () => state.reportComposition, selected: () => [],
      copy: value => JSON.parse(JSON.stringify(value)),
      ECGAnalysisConsistency: consistency, ECGReportRange: {assertApplied() {}},
      ECGAdvancedAnalysis: {assertApplied() {}}, ECGReportSections: {validate() {}},
      ECGReportConsistency: {content: (text, composition) => JSON.stringify([text, composition])},
      ECGReportPaper: {render(model) { rendered++; return `<p>${model.case.metadata.name}</p>`; }, number() {}},
      api: async path => {
        if (path.includes('/analysis-basis')) return {...basis};
        assert.match(path, /include_phi=1/);
        reads++;
        return caseRead.promise;
      },
      withPhi: path => path + '&include_phi=' + (state.includePhi ? '1' : '0'),
      endpoint: async () => ({...basis}),
      document: {createElement: tag => element(tag)}, run: callback => Promise.resolve().then(callback)
    });
    for (const name of ['selectedReportWaves', 'sectionsForReport', 'readPaperEvidence', 'previewPaper']) production(context, name);
    production(context, 'hrvForReport', false);
    production(context, 'paperModel', false);
    const task = context.previewPaper();
    await tick();
    assert.equal(reads, 1, 'The real paper-evidence chain must request identity metadata');
    assert.equal(rendered, 0);
    mutate(state, change);
    caseRead.resolve({...basis, case_id: state.caseId, metadata: {name: 'SYNTHETIC_VISIBLE', patient_id: 'SYNTHETIC_ID'}});
    let failure;
    try { await task; } catch (error) { failure = error; }
    if (failure) assert.match(failure.message, privacyError);
    assert.equal(rendered, change === 'none' ? 1 : 0, `${change}: late identity metadata reached preview rendering`);
    if (change === 'none') assert.match(body.innerHTML, /SYNTHETIC_VISIBLE/);
    else assert.doesNotMatch(body.innerHTML + body.textContent, /SYNTHETIC_VISIBLE/);
    assert.equal(state.caseRequestId, 7);
    if (change === 'none') {
      state.privacyIdentityPending = true;
      await assert.rejects(context.previewPaper(), privacyError);
      assert.equal(reads, 1, 'Pending identity must reject a new preview before reading metadata');
    }
  }
  console.log('Privacy preview: real metadata read chain prevents late epoch, busy and ABA identity rendering');
}

async function frame() {
  for (const phase of ['styles', 'fonts']) {
    const fixture = printFixture(phase);
    let failed = false;
    const task = fixture.context.printHtml('<p>SYNTHETIC_VISIBLE</p>', 'synthetic paper', () => { if (failed) throw Error('synthetic output guard failed'); });
    await tick();
    failed = true;
    const result = assert.rejects(task, /synthetic output guard failed/);
    fixture.release();
    await result;
    assert.equal(fixture.printed, 0); assert.equal(fixture.focused, 0); assert.equal(fixture.numbered, 0);
    assert(fixture.frame.removed, 'Guard rejection must remove the frame containing the old identity');
    assert.equal(fixture.listeners, 0, 'A failed print must remove its privacy listener');
  }
  const pending = printFixture('fonts'); pending.state.privacyIdentityPending = true;
  await assert.rejects(pending.context.printHtml('synthetic paper', 'synthetic title'), privacyError);
  assert.equal(pending.frame, undefined, 'Identity pending must reject printing before making an identity iframe');
  const fixture = printFixture('styles');
  const task = fixture.context.printHtml('<p>SYNTHETIC_VISIBLE</p>', 'synthetic paper');
  await tick();
  const result = assert.rejects(task, /打印样式读取失败/);
  fixture.style.onerror();
  await result;
  assert.equal(fixture.printed, 0); assert(fixture.frame.removed, 'Stylesheet failure must remove the identity snapshot');
  assert.equal(fixture.listeners, 0);
  for (const phase of ['styles', 'fonts']) {
    const interrupted = printFixture(phase);
    for (const name of ['renderExportState', 'cancelReportExport', 'refreshPrivacyViews']) production(interrupted.context, name, false);
    const printing = interrupted.context.printHtml('<p>SYNTHETIC_VISIBLE</p>', 'synthetic paper');
    await tick();
    interrupted.state.privacyRequestId++;
    const rejected = assert.rejects(printing, privacyError);
    interrupted.context.refreshPrivacyViews('pending');
    let timeout;
    try {
      await Promise.race([rejected, new Promise((_, reject) => { timeout = setTimeout(() => reject(Error('Privacy refresh did not immediately interrupt printing')), 500); })]);
    } finally { clearTimeout(timeout); }
    assert.equal(interrupted.printed, 0); assert(interrupted.frame.removed);
    assert.equal(interrupted.listeners, 0);
    // No stylesheet or font completion was needed to remove the old identity.
  }
  console.log('Privacy print frames: guard and stylesheet failures never print and remove their iframe');
}

async function views() {
  const state = initialState(), nodes = new Map(), buttons = [element('button'), element('button')];
  state.privacySaving = true; state.includePhi = false;
  state.caseData.report_image_urls = ['synthetic://old-report'];
  const range = {a: 8, b: 14}, advanced = {pending: 'synthetic options'};
  const headers = Array.from({length: 2}, () => {
    const spans = [element('span'), element('span'), element('span')];
    spans[0].textContent = '患者 ID：SYNTHETIC_ID'; spans[1].textContent = '姓名：SYNTHETIC_VISIBLE'; spans[2].textContent = '未审核 · 草稿';
    return {spans, querySelectorAll: () => spans};
  });
  const overviewDialog = element('dialog'); overviewDialog.open = true;
  for (const selector of ['#rwPaperPreview', '#v2PrintFrame', '#reportPreviewBody', '#ovPrintSheet', '#sourceReportDialog', '#sourceReportImage', '#sourceReportPrivacy', '#openSourceReport', '#downloadReport', '#cancelReportExport']) nodes.set(selector, element());
  nodes.get('#rwPaperPreview').open = true; nodes.get('#rwPaperPreview').textContent = 'SYNTHETIC_VISIBLE';
  nodes.get('#sourceReportDialog').open = true;
  nodes.get('#ovPrintSheet').closest = () => overviewDialog;
  const image = nodes.get('#sourceReportImage'); image.attrs.src = 'synthetic://old-report'; image.dataset.url = 'synthetic://old-report';
  nodes.get('#downloadReport').after = node => nodes.set('#' + node.id, node);
  const controller = new AbortController(); state.reportExportJob = {controller};
  const selectedHour = {value: '1'}, clinicalStatistics = {textContent: 'synthetic SDNN 42.0 ms'};
  const hrvPanels = [element(), element()];
  hrvPanels.forEach(panel => { panel.innerHTML = 'synthetic continuous HRV statistics'; panel.querySelector = selector => selector === '.v2-hrv-window' ? selectedHour : clinicalStatistics; });
  nodes.set('#reportHrvV2', hrvPanels[0]); nodes.set('#hrvWindowPanel', hrvPanels[1]);
  nodes.set('#reportPageSelect', {value: '2'});
  const composition = state.reportComposition, caseData = state.caseData;
  const context = vm.createContext({
    state, Event, qs: selector => nodes.get(selector) || null,
    dirty() { throw Error('Identity-only refresh dirtied the report'); },
    ECGReportRange: {pending: () => [range], clear() { throw Error('Privacy refresh cleared a range draft'); }, setContext() { throw Error('Identity-only refresh changed range context'); }},
    ECGAdvancedAnalysis: {pending: () => advanced, clear() { throw Error('Privacy refresh cleared measurement parameters'); }},
    document: {
      createElement: tag => element(tag),
      querySelectorAll: selector => selector.includes('.rp-running') ? headers : buttons
    }
  });
  for (const name of ['renderExportState', 'cancelReportExport', 'refreshPrivacyViews']) production(context, name, false);
  context.refreshPrivacyViews('pending');
  assert(controller.signal.aborted); assert.equal(state.reportExportJob, null);
  assert.equal(nodes.get('#rwPaperPreview').open, false); assert.equal(nodes.get('#rwPaperPreview').textContent, '');
  assert(nodes.get('#v2PrintFrame').removed); assert.equal(nodes.get('#sourceReportDialog').open, false);
  assert.equal(image.hidden, true); assert.equal(image.attrs.src, undefined); assert.equal(image.dataset.url, '');
  assert.equal(overviewDialog.open, false); assert(nodes.get('#ovPrintSheet').removed);
  for (const header of headers) assert.doesNotMatch(header.spans.slice(0, 2).map(span => span.textContent).join(' '), /SYNTHETIC_VISIBLE|SYNTHETIC_ID/);
  for (const button of buttons) assert.equal(button.disabled, true);
  assert.equal(nodes.get('#downloadReport').disabled, true, 'Privacy updates must keep the main export disabled');

  state.privacySaving = false; state.caseData.phi_masked = true;
  state.caseData.metadata = {name: 'SYNTHETIC_MASKED', patient_id: 'SYNTHETIC_ALIAS'};
  state.privacyIdentityPending = true;
  context.refreshPrivacyViews('ready');
  for (const button of buttons) assert.equal(button.disabled, true, 'A ready hook must not reopen output while identity metadata is pending');
  assert.equal(nodes.get('#downloadReport').disabled, true);
  for (const header of headers) assert.doesNotMatch(header.spans.slice(0, 2).map(span => span.textContent).join(' '), /SYNTHETIC_ALIAS|SYNTHETIC_MASKED/);
  state.privacyIdentityPending = false;
  context.refreshPrivacyViews('ready');
  for (const header of headers) {
    assert.equal(header.spans[0].textContent, '患者 ID：SYNTHETIC_ALIAS');
    assert.equal(header.spans[1].textContent, '姓名：SYNTHETIC_MASKED');
    assert.equal(header.spans[2].textContent, '未审核 · 草稿');
  }
  for (const button of buttons) assert.equal(button.disabled, false);
  assert.equal(nodes.get('#downloadReport').disabled, false);
  assert.equal(nodes.get('#openSourceReport').textContent, '原报告说明');
  assert.equal(selectedHour.value, '1'); assert.equal(clinicalStatistics.textContent, 'synthetic SDNN 42.0 ms');
  assert.strictEqual(nodes.get('#reportHrvV2'), hrvPanels[0]); assert.strictEqual(nodes.get('#hrvWindowPanel'), hrvPanels[1]);
  hrvPanels.forEach(panel => assert.equal(panel.innerHTML, 'synthetic continuous HRV statistics'));
  assert.equal(nodes.get('#reportPageSelect').value, '2', 'Identity refresh must preserve the selected source report page');
  assert.strictEqual(state.caseData, caseData); assert.strictEqual(state.reportComposition, composition);
  assert.strictEqual(context.ECGReportRange.pending()[0], range); assert.strictEqual(context.ECGAdvancedAnalysis.pending(), advanced);
  assert.equal(state.caseRequestId, 7);
  console.log('Privacy views: pending clears identity snapshots and outputs; ready updates both HRV headers without changing clinical state');
}

async function download() {
  for (const phase of ['remote', 'blob', 'error-json']) for (const change of [...mutations, 'abort']) {
    const state = initialState(); state.demoReadonly = false;
    state.reportDirty = state.reportSaving = state.reportStale = false;
    const remote = gate(), response = gate(), blob = gate(), errorJson = gate();
    let clicked = 0, objects = 0, conflicts = 0;
    class TestURL extends URL {
      static createObjectURL() { objects++; return 'blob:synthetic-PDF'; }
      static revokeObjectURL() {}
    }
    const context = vm.createContext({
      state, URLSearchParams, AbortController, URL: TestURL, setTimeout() {},
      ECGAdvancedAnalysis: {assertApplied() {}}, ECGReportRange: {assertApplied() {}},
      ECGReportConsistency: {sameBase: (a, b) => a.version === b.version && a.review_revision === b.review_revision},
      renderExportState() {}, renderReportShell() { conflicts++; },
      api: () => remote.promise, fetch: () => response.promise,
      document: {createElement: () => ({click() { clicked++; }})}
    });
    production(context, 'downloadReport'); production(context, 'cancelReportExport', false);
    const task = context.downloadReport();
    if (phase !== 'remote') {
      remote.resolve({...state.report}); await tick();
      response.resolve(phase === 'blob' ? {ok: true, blob: () => blob.promise} : {ok: false, status: 409, json: () => errorJson.promise});
      await tick();
    }
    if (change === 'abort') context.cancelReportExport(); else mutate(state, change);
    remote.resolve({version: 2, review_revision: 1});
    response.resolve({ok: true, blob: () => blob.promise});
    blob.resolve('synthetic-PDF'); errorJson.resolve({error: 'synthetic server conflict'});
    let failure;
    try { await task; } catch (error) { failure = error; }
    if (change === 'none' && phase === 'error-json') {
      assert.match(failure?.message || '', /synthetic server conflict/);
      assert.equal(state.reportStale, true); assert.equal(conflicts, 1);
    } else {
      if (!['none', 'abort'].includes(change)) assert.match(failure?.message || '', privacyError);
      else assert.equal(failure, undefined);
      assert.equal(state.reportStale, false, `${phase}/${change}: a cancelled identity output polluted report conflict state`);
      assert.equal(conflicts, 0);
    }
    const success = change === 'none' && phase !== 'error-json';
    assert.equal(clicked, success ? 1 : 0); assert.equal(objects, success ? 1 : 0);
    assert.equal(state.reportExportJob, null);
    assert.equal(state.caseRequestId, 7);
  }
  console.log('Privacy PDF: late metadata/blob/error JSON and cancellation cannot output or pollute report conflict state');
}

const groups = {hrv, preview, frame, views, download};
(async () => {
  const requested = process.argv[2];
  if (requested) { assert(groups[requested], `Unknown test group ${requested}`); await groups[requested](); }
  else for (const run of Object.values(groups)) await run();
})().catch(error => { console.error(error); process.exitCode = 1; });
