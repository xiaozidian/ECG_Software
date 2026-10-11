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

const controlsHtml = '<div class="hrv-evidence-toolbar"></div><select class="v2-hrv-window"></select>'
  + '<input data-hrv-include><button data-hrv-export>Export</button>';

function element(tag = 'div') {
  let connected = true;
  return {
    tagName: tag.toUpperCase(), id: '', tabIndex: -1, style: {}, dataset: {},
    parentElement: null, disabled: false, focusCalls: [], scrollCalls: [],
    get isConnected() { return connected && (!this.parentElement || this.parentElement.isConnected); },
    set isConnected(value) { connected = Boolean(value); },
    addEventListener(type, callback) { this['on' + type] = callback; },
    focus(options) { assert(this.isConnected); this.focusCalls.push(options); },
    scrollIntoView(options) { assert(this.isConnected); this.scrollCalls.push(options); },
    click() { if (!this.disabled && this.isConnected) return this.onclick?.({target: this}); }
  };
}

function panel() {
  const target = element(), nodes = new Map();
  let html = '';
  target.id = 'hrvWindowPanel';
  target.install = (selector, node) => { node.parentElement = target; nodes.set(selector, node); return node; };
  // Unknown selectors are absent, as in a real DOM; no wildcard dummy nodes.
  target.querySelector = selector => nodes.get(selector) || null;
  target.append = node => target.install('.hrv-legacy-reference', node);
  Object.defineProperty(target, 'innerHTML', {
    get() { return html; },
    set(value) {
      html = value;
      nodes.clear();
      if (value.includes('class="hrv-evidence-toolbar"')) {
        const toolbar = target.install('.hrv-evidence-toolbar', element());
        toolbar.insertAdjacentHTML = (position, markup) => {
          assert.equal(position, 'beforeend');
          for (const match of markup.matchAll(/<button\b([^>]*)>([^<]*)<\/button>/g)) {
            const attribute = match[1].match(/\bdata-([\w-]+)(?:\s|=|$)/);
            assert(attribute, 'Toolbar fixture needs an actual data-attribute button');
            const node = element('button');
            node.textContent = match[2];
            node.dataset[attribute[1].replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())] = '';
            target.install('[data-' + attribute[1] + ']', node);
          }
        };
        target.install('.v2-hrv-window', element('select'));
        target.install('[data-hrv-include]', element('input'));
        target.install('[data-hrv-export]', element('button'));
      }
      if (value.includes('data-hrv-retry')) target.install('[data-hrv-retry]', element('button'));
    }
  });
  return target;
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
    ECGHrvReport: {ui: () => controlsHtml, pages: () => '<p>synthetic HRV paper</p>'},
    ECGReportPaper: {number(node) { if (node === doc.body) numberedPrint++; }},
    paperModel: () => ({report: {status: 'draft'}}),
    endpoint: async (kind, basis, id) => {
      assert.equal(kind, 'analysis-basis');
      assert.equal(id, 'synthetic-A');
      consistency.assertSame(data, basis);
      return {...basis};
    },
    run: callback => Promise.resolve().then(callback), esc: String,
    clinicalWorkflow: {writable: () => !demoReadonly},
    beatEditor: {openSettings() { assert.fail('Printing must not open NN settings'); }},
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
  production(context, 'bindHrvNavigation', false);
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

async function navigationScenario(writable) {
  const target = panel();
  target.innerHTML = controlsHtml;
  assert.equal(target.querySelector('.not-rendered'), null);
  const review = target.install('.hrvr-review', element());
  const legacy = target.install('.hrv-legacy-reference', element('section'));
  const heading = element('h2');
  heading.parentElement = legacy;
  let back = null, current = true, opened = 0;
  legacy.querySelector = selector => selector === 'h2' ? heading
    : selector === '[data-hrv-review-return]' ? back : null;
  heading.after = node => { assert.equal(node.dataset.hrvReviewReturn, ''); node.parentElement = legacy; back = node; };
  const state = {caseId: 'synthetic-A', reportComposition: {hrv_window: 0, selected_events: []}, analysis_revision: 1};
  const beforeState = JSON.stringify(state);
  const context = vm.createContext({
    state, hrvLegacyWeb: legacy,
    clinicalWorkflow: {writable: () => writable},
    beatEditor: {openSettings() { opened++; }},
    document: {createElement: tag => element(tag)},
    run: callback => Promise.resolve().then(callback)
  });
  production(context, 'bindHrvNavigation', false);
  const isCurrent = () => current && target.isConnected;
  context.bindHrvNavigation(target, isCurrent);
  const reference = target.querySelector('[data-hrv-reference]');
  const settings = target.querySelector('[data-hrv-nn-settings]');
  assert(reference && settings && back, 'Production navigation must bind actual rendered controls');
  assert.equal(review.id, 'hrvSelectedPeriodReview');
  assert.equal(review.tabIndex, -1);
  assert.equal(review.style.scrollMarginTop, '68px');
  assert.equal(settings.disabled, !writable);
  if (!writable) assert.match(settings.title, /只读/);
  reference.click();
  assert.equal(legacy.focusCalls.length, 1);
  assert.equal(legacy.focusCalls[0].preventScroll, true);
  assert.equal(legacy.scrollCalls[0].block, 'start');
  back.click();
  assert.equal(review.focusCalls.length, 1);
  assert.equal(review.scrollCalls[0].block, 'start');
  await settings.click();
  assert.equal(opened, writable ? 1 : 0, 'Only a writable current view may open the existing NN settings');
  assert.equal(JSON.stringify(state), beforeState, 'Navigation must not revise report or analysis state');
  current = false;
  reference.click(); back.click(); await settings.click();
  assert.equal(legacy.focusCalls.length, 1, 'Stale reference navigation must be a no-op');
  assert.equal(review.focusCalls.length, 1, 'Stale review return must be a no-op');
  assert.equal(opened, writable ? 1 : 0, 'Stale NN settings navigation must be a no-op');
  current = true; target.isConnected = false;
  reference.click(); back.click(); await settings.click();
  assert.equal(legacy.focusCalls.length, 1);
  assert.equal(review.focusCalls.length, 1);
  assert.equal(opened, writable ? 1 : 0);
  assert.equal(JSON.stringify(state), beforeState);
}

(async () => {
  for (const phase of ['styles', 'fonts']) {
    for (const change of changes) await scenario(true, phase, change);
  }
  for (const phase of ['response', 'blob']) {
    for (const change of changes) await scenario(false, phase, change);
  }
  for (const writable of [false, true]) await navigationScenario(writable);
  console.log('HRV output races: 16 production print scenarios and 16 PDF scenarios guard case, reopen, window, clinical revision/basis and target changes; unchanged output succeeds once');
  console.log('HRV navigation: exact DOM selectors, read-only NN disabled, current NN opens existing settings, stale/disconnected actions do nothing and analysis/report state stays unchanged');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
