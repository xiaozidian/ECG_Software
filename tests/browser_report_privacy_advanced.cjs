'use strict';
// Synthetic evidence only. Exercise production callbacks and the real identity checker.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const ECGAnalysisConsistency = require('../static/js/analysis-consistency.js');
const source = fs.readFileSync(path.join(__dirname, '../static/js/clinical-ui.js'), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
const gate = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return {promise, resolve};
};

function production(context, name, asynchronous = false) {
  const marker = `  ${asynchronous ? 'async ' : ''}function ${name}(`;
  const start = source.indexOf(marker);
  assert(start >= 0, `production function missing: ${name}`);
  const end = name === 'paperModel' ? source.indexOf('\n', start) : source.indexOf('\n  }', start) + 4;
  assert(end > start, `production function incomplete: ${name}`);
  vm.runInContext(source.slice(start, end), context, {filename: `clinical-ui.js:${name}`});
}

function harness() {
  const basis = {analysis_basis: 'synthetic-mathematical-basis', analysis_revision: 7};
  const evidence = {advanced: {...basis, documents: {qtd: []}}};
  const state = {
    caseId: 'SYNTHETIC_CASE', caseRequestId: 11, privacyRequestId: 3,
    privacySaving: false, privacyIdentityPending: false, includePhi: true,
    reportStale: false, report: {version: 2, status: 'draft'},
    reportComposition: {advanced_options: {duration_s: 30}},
    caseData: {case_id: 'SYNTHETIC_CASE', metadata: {name: 'Synthetic fixture'},
      technical: {duration_seconds_raw: 120}},
  };
  const remote = gate(), fonts = gate(), listeners = new Map();
  const counts = {basis: 0, sections: 0, created: 0, removed: 0, numbered: 0, focused: 0, printed: 0};
  const panel = {isConnected: true}, editor = {value: 'Synthetic validation text'};
  let config, advancedPending = false, mountedFrame = null;
  const link = {sheet: true}, written = [];
  const doc = {
    open() {}, write(html) { written.push(html); }, close() {},
    querySelector(selector) { assert.equal(selector, 'link'); return link; },
    fonts: {ready: fonts.promise}, body: {},
  };
  const frame = {
    isConnected: false, contentDocument: doc,
    contentWindow: {focus() { counts.focused++; }, print() { counts.printed++; }},
    remove() {
      if (this.isConnected) counts.removed++;
      this.isConnected = false;
      if (mountedFrame === this) mountedFrame = null;
    },
  };
  const document = {
    createElement(kind) { assert.equal(kind, 'iframe'); counts.created++; return frame; },
    body: {appendChild(node) { assert.equal(node, frame); node.isConnected = true; mountedFrame = node; }},
    addEventListener(kind, handler) {
      if (!listeners.has(kind)) listeners.set(kind, new Set());
      listeners.get(kind).add(handler);
    },
    removeEventListener(kind, handler) { listeners.get(kind)?.delete(handler); },
    dispatchEvent(event) { for (const handler of [...(listeners.get(event.type) || [])]) handler(event); },
  };
  const context = vm.createContext({
    state, document, URL, location: {href: 'http://synthetic.invalid/'}, esc: value => String(value),
    reportData: {...basis}, waveEvidenceScope: 'synthetic-wave-scope', ECGAnalysisConsistency,
    composition: () => state.reportComposition,
    qs: selector => selector === '#v2PrintFrame' ? mountedFrame : selector === '#conclusionEditor' ? editor : null,
    // Expose callback rejection to the test; the UI's run helper reports it as a toast.
    run: callback => Promise.resolve().then(callback),
    ECGAdvancedAnalysis: {
      mountRetained(host, options) { assert.equal(host, panel); config = options; },
      assertApplied() { if (advancedPending) throw Error('pending-advanced'); },
    },
    endpoint(kind, expected, id) {
      assert.equal(kind, 'analysis-basis'); assert.equal(id, 'SYNTHETIC_CASE');
      ECGAnalysisConsistency.assertSame(basis, expected); counts.basis++;
      return remote.promise;
    },
    ECGReportSections: {pages(model, keys) {
      assert.equal(model.case, state.caseData); assert.equal(model.evidence, evidence);
      assert.deepEqual(Array.from(keys), ['qtd']); counts.sections++;
      return '<p>Synthetic mathematical research evidence</p>';
    }},
    ECGReportPaper: {number(body) { assert.equal(body, doc.body); counts.numbered++; }},
  });
  production(context, 'mountAdvanced');
  production(context, 'paperModel');
  production(context, 'printHtml', true);
  context.mountAdvanced(panel, state.caseId);
  assert(config && typeof config.onPrint === 'function');
  return {
    state, basis, remote, fonts, frame, counts, written, listeners,
    pending(value) { advancedPending = value; },
    privacyEvent() { document.dispatchEvent({type: 'ecg-report-privacy-change'}); },
    start() { return config.onPrint('qtd', evidence).then(() => ({ok: true}), error => ({error})); },
  };
}

function unchangedClinicalContext(h) {
  assert.equal(h.state.caseId, 'SYNTHETIC_CASE');
  assert.equal(h.state.caseRequestId, 11, 'privacy changes must retain the clinical case token');
  assert.equal(h.state.reportStale, false);
  assert.equal(h.state.reportComposition.advanced_options.duration_s, 30);
  assert.equal(h.counts.printed, 0);
}

async function rejected(outcome, pattern, label) {
  let timer;
  try {
    const result = await Promise.race([outcome, new Promise((_, reject) => {
      timer = setTimeout(() => reject(Error(`${label}: pending output did not cancel`)), 1500);
    })]);
    assert(result.error, `${label}: output unexpectedly succeeded`);
    assert.match(result.error.message, pattern, label);
  } finally { clearTimeout(timer); }
}

async function entry(label, mutate, pattern) {
  const h = harness(); mutate(h);
  await rejected(h.start(), pattern, label);
  unchangedClinicalContext(h);
  assert.equal(h.counts.basis, 0, `${label}: blocked output requested evidence`);
  assert.equal(h.counts.sections, 0); assert.equal(h.counts.created, 0);
}

async function duringBasis(label, mutate, pattern, conflict = false) {
  const h = harness(), outcome = h.start(); await tick();
  assert.equal(h.counts.basis, 1); assert.equal(h.counts.created, 0);
  mutate(h); h.remote.resolve(conflict ? {...h.basis, analysis_revision: 8} : {...h.basis});
  await rejected(outcome, pattern, label);
  unchangedClinicalContext(h);
  assert.equal(h.counts.sections, 0, `${label}: stale output reached page generation`);
  assert.equal(h.counts.created, 0);
}

async function duringFonts(label, mutate, pattern, event) {
  const h = harness(), outcome = h.start(); await tick();
  h.remote.resolve({...h.basis}); await tick();
  assert.equal(h.counts.sections, 1); assert.equal(h.counts.created, 1);
  assert.equal(h.frame.isConnected, true); assert.equal(h.written.length, 1);
  mutate(h);
  if (event) h.privacyEvent(); else h.fonts.resolve();
  await rejected(outcome, pattern, label);
  unchangedClinicalContext(h);
  assert.equal(h.counts.numbered, 0); assert.equal(h.frame.isConnected, false);
  assert.equal(h.counts.removed, 1);
  assert.equal(h.listeners.get('ecg-report-privacy-change')?.size, 0);
  h.fonts.resolve();
}

async function unchanged() {
  const h = harness(), outcome = h.start(); await tick();
  h.remote.resolve({...h.basis}); await tick(); h.fonts.resolve();
  assert.deepEqual(await outcome, {ok: true});
  assert.equal(h.counts.basis, 1); assert.equal(h.counts.sections, 1);
  assert.equal(h.counts.printed, 1); assert.equal(h.counts.numbered, 1); assert.equal(h.counts.focused, 1);
  assert.equal(h.listeners.get('ecg-report-privacy-change')?.size, 0);
  h.state.privacyRequestId++; h.privacyEvent();
  assert.equal(h.counts.printed, 1, 'completed output must not leave a live cancellation listener');
}

(async () => {
  const identity = /身份信息/, changed = /身份显示状态/, pending = /pending-advanced/;
  const busy = h => { h.state.privacySaving = true; };
  const unread = h => { h.state.privacyIdentityPending = true; };
  const advanced = h => h.pending(true);
  const epoch = h => { h.state.privacyRequestId++; h.state.includePhi = false; };
  const aba = h => { h.state.includePhi = false; h.state.privacyRequestId++; h.state.includePhi = true; h.state.privacyRequestId++; };
  await entry('entry privacy update', busy, identity);
  await entry('entry identity not ready', unread, identity);
  await entry('entry unapplied measurement', advanced, pending);
  await duringBasis('basis privacy epoch', epoch, changed);
  await duringBasis('basis privacy ABA', aba, changed);
  await duringBasis('basis privacy update', busy, identity);
  await duringBasis('basis identity not ready', unread, identity);
  await duringBasis('basis unapplied measurement', advanced, pending);
  await duringBasis('basis analysis conflict', () => {}, /依据.*变化/, true);
  await duringFonts('fonts privacy epoch event', epoch, changed, true);
  await duringFonts('fonts privacy ABA event', aba, changed, true);
  await duringFonts('fonts privacy update event', busy, identity, true);
  await duringFonts('fonts identity not ready event', unread, identity, true);
  await duringFonts('fonts unapplied measurement', advanced, pending, false);
  await unchanged();
  console.log('Research print privacy: 15 production callback scenarios passed (entry, basis, ABA, fonts, pending measurements, unchanged print).');
})().catch(error => { console.error(error); process.exitCode = 1; });
