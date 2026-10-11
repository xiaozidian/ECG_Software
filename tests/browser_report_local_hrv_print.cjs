'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const consistency = require('../static/js/analysis-consistency.js');
const source = fs.readFileSync('static/js/clinical-ui.js', 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
const changes = ['case', 'reopen', 'window', 'revision', 'basis', 'disconnect', 'replace', 'none'];

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

function panel() {
  const nodes = new Map();
  return {
    id: 'hrvWindowPanel', isConnected: true, innerHTML: '',
    querySelector(selector) {
      if (!nodes.has(selector)) nodes.set(selector, {addEventListener() {}});
      return nodes.get(selector);
    }
  };
}

async function scenario(demoReadonly, phase, change) {
  const fonts = gate(), response = gate(), blob = gate();
  const styleLink = {sheet: phase !== 'styles'};
  const data = {analysis_basis: 'synthetic-r1', analysis_revision: 1, window_index: 0};
  const state = {
    caseId: 'synthetic-A', caseRequestId: 1, demoReadonly,
    // Case payloads expose the clinical identity separately from the editor
    // revision. Both export branches must use the actual displayed basis.
    caseData: {clinical_identity: {...data}, analysis_revision: 99},
    report: {version: 1}, reportComposition: {hrv_window: 0, included_pages: []}
  };
  let target = panel(), frame, printed = 0, focused = 0, fetched = 0;
  let clicked = 0, objects = 0, numberedPrint = 0, printedHtml = '';
  const doc = {
    open() {}, write(html) { printedHtml = html; }, close() {},
    querySelector(selector) { assert.equal(selector, 'link'); return styleLink; },
    fonts: {ready: fonts.promise}, body: {}
  };
  class TestURL extends URL {
    static createObjectURL(value) {
      assert.equal(value, 'synthetic-HRV-PDF');
      objects++;
      return 'blob:synthetic-hrv';
    }
    static revokeObjectURL() {}
  }
  const context = vm.createContext({
    state, reportCase: state.caseId, reportVersion: 1, hrvToken: 0, hrv: null, hrvLegacyWeb: null,
    copy: value => JSON.parse(JSON.stringify(value)),
    composition: () => state.reportComposition,
    qs: selector => selector === '#hrvWindowPanel' ? target : selector === '#v2PrintFrame' ? frame : null,
    ECGAnalysisConsistency: consistency,
    ECGHrvReport: {ui: () => 'synthetic HRV controls', pages: () => '<p>synthetic HRV paper</p>'},
    ECGReportPaper: {number(node) { if (node === doc.body) numberedPrint++; }},
    paperModel: () => ({report: {status: 'draft'}}),
    endpoint: async (kind, basis, id) => {
      assert.equal(kind, 'analysis-basis');
      assert.equal(id, 'synthetic-A');
      consistency.assertSame(data, basis);
      return {...basis};
    },
    run: callback => Promise.resolve().then(callback), esc: String,
    URL: TestURL, location: {href: 'http://synthetic.test/'}, setTimeout() {},
    fetch: url => {
      fetched++;
      const query = new URL(url, 'http://synthetic.test/');
      assert.equal(query.pathname, '/api/cases/synthetic-A/hrv-report.pdf');
      assert.equal(query.searchParams.get('window'), '0');
      assert.equal(query.searchParams.get('analysis_revision'), '1');
      return response.promise;
    },
    document: {
      createElement(tag) {
        if (tag === 'a') return {click() { clicked++; }};
        assert.equal(tag, 'iframe');
        return {
          contentDocument: doc,
          contentWindow: {focus() { focused++; }, print() { printed++; }},
          remove() { frame = null; }
        };
      },
      body: {appendChild(next) { frame = next; }}
    }
  });
  // Exercise the production renderer as well as the export hook when running
  // this CJS directly; no pytest bootstrap or replacement renderer is needed.
  production(context, 'renderHrvTarget', false);
  production(context, 'loadHrv');
  production(context, 'printHtml');
  await context.loadHrv('#hrvWindowPanel', 0, data);
  const exporting = target.querySelector('[data-hrv-export]').onclick();
  await tick();

  if (demoReadonly) {
    assert(frame, 'The production export hook must reach the production print frame');
    assert.match(printedHtml, /synthetic HRV paper/);
    assert.equal(typeof styleLink.onload, 'function');
  } else {
    assert.equal(fetched, 1);
    assert.equal(frame, undefined);
    if (phase === 'blob') {
      response.resolve({ok: true, blob: () => blob.promise});
      await tick();
    }
  }
  assert.equal(printed, 0);
  assert.equal(clicked, 0);

  if (change === 'case') state.caseId = 'synthetic-B';
  if (change === 'reopen') state.caseRequestId++;
  if (change === 'window') {
    const previousToken = context.hrvToken;
    await context.loadHrv('#hrvWindowPanel', 1, {...data, window_index: 1});
    assert.equal(context.hrvToken, previousToken + 1, 'A real HRV window reload must invalidate the previous export');
  }
  if (change === 'disconnect') target.isConnected = false;
  if (change === 'replace') target = panel();
  if (change === 'revision') state.caseData.clinical_identity.analysis_revision++;
  if (change === 'basis') state.caseData.clinical_identity.analysis_basis = 'synthetic-r2';

  if (demoReadonly) {
    const result = change === 'none'
      ? exporting
      : assert.rejects(exporting, /HRV .*已变化/);
    if (phase === 'styles') styleLink.onload();
    fonts.resolve();
    await result;
    assert.equal(printed, change === 'none' ? 1 : 0, `${phase}/${change}: stale HRV reached print()`);
    assert.equal(focused, change === 'none' ? 1 : 0);
    assert.equal(numberedPrint, change === 'none' ? 1 : 0);
    assert.equal(clicked, 0);
  } else {
    response.resolve({ok: true, blob: () => blob.promise});
    blob.resolve('synthetic-HRV-PDF');
    await exporting;
    assert.equal(clicked, change === 'none' ? 1 : 0, `${phase}/${change}: stale HRV PDF downloaded`);
    assert.equal(objects, change === 'none' ? 1 : 0);
    assert.equal(printed, 0);
  }
}

(async () => {
  for (const phase of ['styles', 'fonts']) {
    for (const change of changes) await scenario(true, phase, change);
  }
  for (const phase of ['response', 'blob']) {
    for (const change of changes) await scenario(false, phase, change);
  }
  console.log('HRV output races: 16 production print scenarios and 16 PDF scenarios guard case, reopen, window, clinical revision/basis and target changes; unchanged output succeeds once');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
