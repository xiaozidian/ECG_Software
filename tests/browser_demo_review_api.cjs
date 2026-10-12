'use strict';
// Actual browser Demo API scripts in a Node VM, with only original mathematical
// beats and generated zero waveforms. No server, patient input or network access.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const {spawnSync} = require('node:child_process');

const root = path.resolve(process.env.ECG_DEMO_SOURCE || path.join(__dirname, '..'));
const out = path.resolve(process.env.ECG_DEMO_REVIEW_EVIDENCE || '/tmp/ecg-demo-review-api-evidence');
const key = 'cardioinsight-public-math-4314-v2';
const builtin = JSON.parse(fs.readFileSync(path.join(root, 'static/terminology/builtin-draft-v1.json'), 'utf8'));
const results = {scope: 'actual-demo-api-original-mathematical-inputs-only', started: new Date().toISOString(), checks: [], nativeRequests: [], patientInputsRead: false};
results.scriptHashes = Object.fromEntries(['demo/static/js/demo-api.js', 'demo/static/js/demo-review-api.js', 'static/js/hrv-analysis.js', 'static/js/rr-quality.js'].map(relative => [relative, crypto.createHash('sha256').update(fs.readFileSync(path.join(root, relative))).digest('hex')]));
const clone = value => JSON.parse(JSON.stringify(value));
const near = (actual, expected, epsilon = 1e-4) => {
  if (expected === null) assert.equal(actual, null);
  else assert.ok(Number.isFinite(actual) && Math.abs(actual - expected) <= epsilon, `${actual} != ${expected} (+/- ${epsilon})`);
};
const sorted = value => Array.isArray(value) ? value.map(sorted) : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(k => [k, sorted(value[k])])) : value;
const hash = value => crypto.createHash('sha256').update(JSON.stringify(sorted(value))).digest('hex');
function catalog(version = 'v1', phrase = 'Original mathematical test phrase.') {
  const value = clone(builtin);
  value.namespace = 'original.math.tests'; value.version = version; value.title = 'Original test phrases ' + version;
  value.nodes.find(n => n.kind === 'term').text = phrase;
  delete value.sha256; value.sha256 = hash(value); return value;
}
function mathCase(intervals = Array(600).fill(1000), options = {}) {
  let sample = options.firstSample || 0;
  const codes = options.codes || Array(intervals.length + 1).fill('N');
  const groups = {N: 1, S: 2, V: 3, X: 34};
  const beats = [{sample_index: sample, time_s: sample / 200, group: groups[codes[0]] || 1, label: codes[0], rr_ms: 0, hr: null}];
  intervals.forEach((rr, i) => {
    sample += Math.round(rr / 5);
    beats.push({sample_index: sample, time_s: sample / 200, group: groups[codes[i + 1]] || 1, label: codes[i + 1], rr_ms: rr, hr: 60000 / rr});
  });
  const duration = options.duration ?? sample / 200 + 1;
  return {software_release_id: 'original-mathematical-test', case_id: 'math-4314-001', display_case_id: 'M01', active: true, phi_masked: true,
    metadata: {name: 'Original mathematical test', start_iso: '2026-01-02T08:00:00', start_time: '2026-01-02 08:00:00'},
    technical: {duration_seconds_raw: duration, sample_rate_hz: 200}, summary: {total_beats: beats.length}, source_report_summary: {}, conclusion: 'Original mathematical test only.', beats,
    integrity: {mathematical_fixture: true, raw_patient_data: false}, simulation_profile: {real_patient_inputs_read: false, source_waveform_copied: false, rhythm_candidate_windows_s: []}};
}
function storage(existing) {
  const values = existing || new Map(); let failNext = false;
  return {values, getItem: name => values.has(name) ? values.get(name) : null,
    setItem(name, value) {if (failNext) {failNext = false; throw new DOMException('Injected original-test storage failure', 'QuotaExceededError');} values.set(name, String(value));},
    removeItem: name => values.delete(name), failNextWrite() {failNext = true;}};
}
function harness(input = mathCase(), existing) {
  const localStorage = storage(existing), nativeRequests = [], count = Math.ceil(input.technical.duration_seconds_raw * 200);
  let clockOffset = 0;
  class TestDate extends Date {constructor(...args) {super(...(args.length ? args : [Date.now() + clockOffset]));} static now() {return Date.now() + clockOffset;}}
  let hold = null, heldResolve = null;
  const nativeFetch = async raw => {
    const url = new URL(typeof raw === 'string' ? raw : raw.url, 'http://original-math.invalid/');
    nativeRequests.push(url.pathname); results.nativeRequests.push(url.pathname);
    if (hold === url.pathname) {hold = null; await new Promise(resolve => {heldResolve = resolve;});}
    if (url.pathname.includes('builtin-draft-v1.json')) return new Response(JSON.stringify(builtin), {status: 200});
    if (url.pathname.endsWith('/waveform.bin')) return new Response(new Uint8Array(count * 16), {status: 200});
    throw Error('Unexpected native/network request: ' + url.href);
  };
  let lockTail = Promise.resolve();
  const ctx = vm.createContext({console, Response, Request, Headers, URL, URLSearchParams, AbortController, DOMException, TextEncoder, TextDecoder, Date: TestDate,
    crypto: crypto.webcrypto, localStorage, location: {href: 'http://original-math.invalid/'}, setTimeout, clearTimeout,
    navigator: {locks: {request: (_name, _options, run) => {const p = lockTail.then(run, run); lockTail = p.catch(() => {}); return p;}}}});
  ctx.window = ctx; ctx.self = ctx; ctx.fetch = nativeFetch; ctx.__CARDIOINSIGHT_MATHEMATICAL_CASE__ = clone(input);
  const load = relative => vm.runInContext(fs.readFileSync(path.join(root, relative), 'utf8'), ctx, {filename: relative});
  for (const relative of ['static/js/rr-quality.js', 'static/js/report-engine.js', 'static/js/overview-engine.js', 'static/js/clinical-analysis.js', 'static/js/hrv-analysis.js', 'static/js/beat-engine.js']) load(relative);
  load('demo/static/js/demo-review-api.js');
  load('demo/static/js/demo-api.js');
  const call = async (route, method = 'GET', payload, expected = 200) => {
    const response = await ctx.fetch(route.startsWith('/api/') ? route : '/api/cases/' + input.case_id + '/' + route, {method, ...(payload === undefined ? {} : {body: JSON.stringify(payload)})});
    const body = await response.json(); assert.equal(response.status, expected, `${method} ${route}: ${JSON.stringify(body)}`); return clone(body);
  };
  return {ctx, input, localStorage, nativeRequests, call, load,
    advanceMs(ms) {clockOffset += ms;},
    holdNative(name) {hold = name;}, releaseNative() {assert.ok(heldResolve); heldResolve(); heldResolve = null;},
    async waitHeld() {for (let n = 0; n < 100 && !heldResolve; n++) await new Promise(resolve => setTimeout(resolve, 1)); assert.ok(heldResolve, 'native fetch was not held');}};
}
function directFeed(intervals, codes = Array(intervals.length + 1).fill('N'), duration, firstSample = 0) {
  let sample = firstSample;
  const beats = [{id: 's:' + sample, sample_index: sample, source_sample: sample, class_code: codes[0], rr_ms: 0}];
  intervals.forEach((rr, i) => {sample += Math.round(rr / 5); beats.push({id: 's:' + sample, sample_index: sample, source_sample: sample, class_code: codes[i + 1], rr_ms: rr});});
  return {beats, markers: [], duration: duration ?? sample / 200 + 1, document: {settings: {nn_min: 300, nn_max: 2000}, changes: {}}, excluded_rhythm_intervals: []};
}
function nnOracle(input, exclusions = [], rhythm = []) {
  const values = [], beats = input.beats;
  for (let i = 1; i < beats.length; i++) {
    const a = beats[i - 1], b = beats[i], rr = (b.sample_index - a.sample_index) * 5;
    if (a.group !== 1 || b.group !== 1 || rr < 300 || rr > 2000 || b.sample_index / 200 > input.technical.duration_seconds_raw) continue;
    if (exclusions.some(x => x.start_sample < b.sample_index && x.end_sample > a.sample_index) || rhythm.some(([s, e]) => s < b.sample_index / 200 && e > a.sample_index / 200)) continue;
    values.push({ordinal: i - 1, start: a.sample_index / 200, end: b.sample_index / 200, rr});
  }
  return values;
}
function statsOracle(values) {
  const raw = values.map(r => r.rr), mean = raw.length ? raw.reduce((s, x) => s + x, 0) / raw.length : null;
  const diffs = values.slice(1).flatMap((r, i) => r.ordinal === values[i].ordinal + 1 ? [r.rr - values[i].rr] : []);
  return {nn_count: raw.length, mean_nn_ms: mean, sdnn_ms: raw.length >= 3 ? Math.sqrt(raw.reduce((s, x) => s + (x - mean) ** 2, 0) / (raw.length - 1)) : null,
    rmssd_ms: diffs.length ? Math.sqrt(diffs.reduce((s, x) => s + x * x, 0) / diffs.length) : null,
    pnn50_pct: diffs.length ? 100 * diffs.filter(x => Math.abs(x) > 50).length / diffs.length : null,
    consecutive_difference_count: diffs.length, nn50_count: diffs.filter(x => Math.abs(x) > 50).length};
}
function assertStats(actual, expected, epsilon = 0.011) {
  assert.equal(actual.nn_count, expected.nn_count);
  for (const field of ['mean_nn_ms', 'sdnn_ms', 'rmssd_ms', 'pnn50_pct']) near(actual[field], expected[field], epsilon);
}
function pythonOracle(mode, payload) {
  const script = `import json,sys
from types import SimpleNamespace
values=json.load(sys.stdin)
if sys.argv[1]=='rr':
 from ecg_core.rr_review import build_rr_index,query_rr
 result=[query_rr(build_rr_index(SimpleNamespace(**item['feed']),basis=item['scope']),item.get('query',{})) for item in values]
else:
 from ecg_core.hrv_analysis import analyze_hrv_review
 result=[analyze_hrv_review(SimpleNamespace(**item['feed']),item['start_time'],item.get('window',0),item.get('exclusions',[])) for item in values]
print(json.dumps(result,ensure_ascii=False,allow_nan=False))
`;
  const run = spawnSync(process.env.ECG_DEMO_PYTHON, ['-c', script, mode], {cwd: root, input: JSON.stringify(payload), encoding: 'utf8', timeout: 30000, maxBuffer: 16 * 1024 * 1024,
    env: {...process.env, PYTHONPATH: root, PYTHONDONTWRITEBYTECODE: '1'}});
  assert.equal(run.error, undefined, String(run.error)); assert.equal(run.status, 0, run.stderr);
  return JSON.parse(run.stdout);
}
function numericTree(actual, expected, label, epsilon = 0.00011) {
  if (typeof expected === 'number') {near(actual, expected, epsilon); return;}
  if (Array.isArray(expected)) {assert.equal(actual.length, expected.length, label); expected.forEach((value, i) => numericTree(actual[i], value, label + '[' + i + ']', epsilon)); return;}
  if (expected && typeof expected === 'object') {for (const [field, value] of Object.entries(expected)) numericTree(actual[field], value, label + '.' + field, epsilon); return;}
  assert.equal(actual, expected, label);
}
async function preview(h, current, document, operation = 'replace', window = 0) {
  return h.call('hrv-review/preview', 'POST', {scope: current.scope, expected_hrv_revision: current.hrv_revision, operation, ...(document ? {document} : {}), window});
}
async function apply(h, current, value, changes = {}, expected = 200) {
  return h.call('hrv-review', 'PUT', {scope: current.scope, expected_hrv_revision: current.hrv_revision, preview_token: value.preview_token, preview_digest: value.preview_digest, confirmed: true, ...changes}, expected);
}
const doc = exclusions => ({schema_version: 1, profile: 'fixed-300s-fft-compat-v1', exclusions});
const exclusion = (start, end, id = 'x') => ({id, start_sample: start, end_sample: end, reason: 'Original mathematical exclusion'});
async function check(name, run) {
  const started = new Date().toISOString();
  try {const detail = await run(); results.checks.push({name, passed: true, started, ...(detail === undefined ? {} : {detail})}); console.log('PASS ' + name);}
  catch (error) {results.checks.push({name, passed: false, started, error: String(error), stack: error.stack}); throw error;}
  finally {fs.mkdirSync(out, {recursive: true}); fs.writeFileSync(path.join(out, 'results.json'), JSON.stringify(results, null, 2) + '\n');}
}

(async () => {
  const h = harness(), scope = {case_id: h.input.case_id, analysis_basis: 'original-math-scope', analysis_revision: 7, beat_revision: 3};
  await check('loads actual Demo API and review adapter with zero external requests', async () => {
    assert.equal(typeof h.ctx.ECGDemoRR?.build, 'function');
    const basis = await h.call('analysis-basis');
    assert.equal(typeof basis.analysis_basis, 'string'); assert.equal(basis.beat_revision, 0);
    return {basis, sourceScripts: ['demo/static/js/demo-api.js', 'demo/static/js/demo-review-api.js']};
  });
  await check('RR full original topology determines ratio before population or range filters', () => {
    const index = h.ctx.ECGDemoRR.build(directFeed([800, 1000, 800, 1000], ['N', 'N', 'V', 'N', 'N'], undefined, 1000), scope), rows = clone(h.ctx.ECGDemoRR.query(index, {}).items);
    assert.deepEqual(rows.map(r => r.start_sample), [1000, 1160, 1360, 1520]);
    assert.deepEqual(rows.map(r => r.end_sample), [1160, 1360, 1520, 1720]);
    assert.deepEqual(rows.map(r => r.rr_ms), [800, 1000, 800, 1000]);
    assert.deepEqual(rows.map(r => r.ratio_pct), [null, 125, 80, 125]);
    assert.deepEqual(rows.map(r => r.hr_bpm), [75, 60, 75, 60]);
    assert.deepEqual(clone(h.ctx.ECGDemoRR.query(index, {population: 'normal_pair'}).items).map(r => r.ratio_pct), [null, 125]);
    for (const row of rows) assert.deepEqual(clone(h.ctx.ECGDemoRR.resolve(index, row.target)), row.target);
  });
  await check('RR separates N labels, current NN candidate rules and zero verified NN', () => {
    const feed = directFeed([800, 2200, 1000]);
    feed.nn_verification = {...scope, status: 'confirmed', sinus_verified: true, quality_verified: true, evidence_ref: 'untrusted-demo-declaration', method_version: 'rr-review-original-qrs-v1', start_s: 0, end_s: 10};
    const index = h.ctx.ECGDemoRR.build(feed, scope), all = clone(h.ctx.ECGDemoRR.query(index, {}));
    assert(all.items.every(r => r.normal_label_pair));
    assert.deepEqual(all.items.map(r => r.nn_eligible_current_rules), [true, false, true]);
    assert(all.items.every(r => r.nn_eligible_verified === false));
    assert.equal(h.ctx.ECGDemoRR.query(index, {population: 'nn_verified'}).total, 0);
    assert.equal(all.summary.nn_verified_count, 0);
  });
  await check('RR skips O/Y/T markers while preserving X, unknown and flutter boundaries', () => {
    const feed = directFeed([800, 1000, 700, 1000, 900, 900], ['N', 'N', 'S', 'X', 'N', 'N', 'N']);
    feed.beats[4].rr_ms = 0;
    feed.beats.splice(1, 0, ...['O', 'Y', 'T'].map((class_code, i) => ({id: 'marker:' + class_code, sample_index: 20 + i * 20, class_code})));
    const all = clone(h.ctx.ECGDemoRR.query(h.ctx.ECGDemoRR.build(feed, scope), {}));
    assert.equal(all.summary.qrs_count, 7); assert.equal(all.summary.non_qrs_marker_count, 3); assert.equal(all.total, 6);
    assert.deepEqual(all.items.map(r => r.rr_ms), [800, 1000, null, null, 900, 900]);
    assert.deepEqual(all.items.map(r => r.ratio_pct), [null, 125, null, null, null, 100]);
    const unknown = clone(h.ctx.ECGDemoRR.query(h.ctx.ECGDemoRR.build(directFeed([1000, 1000, 1000, 1000], ['N', 'OTHER', 'N', '!', 'N']), scope), {}));
    assert(unknown.items.every(r => !r.nn_eligible_current_rules));
    assert.equal(unknown.items[2].rr_ms, null); assert.equal(unknown.items[3].rr_ms, null);
  });
  await check('RR unbounded counts, facets, half-open measurements and tail pagination use all rows', () => {
    const index = h.ctx.ECGDemoRR.build(directFeed(Array.from({length: 257}, (_, i) => i % 2 ? 1000 : 800)), scope);
    const all = clone(h.ctx.ECGDemoRR.query(index, {limit: 200})), tail = clone(h.ctx.ECGDemoRR.query(index, {offset: 250, limit: 20}));
    assert.equal(all.total, 257); assert.equal(all.items.length, 200); assert.equal(all.histogram.measurement_count, 257);
    assert.equal(all.pair_types[0].total, 257); assert.equal(tail.items.length, 7); assert.equal(tail.has_next, false);
    const range = clone(h.ctx.ECGDemoRR.query(index, {range_min: 800, range_max: 1000}));
    assert.equal(range.total, 129); assert.equal(range.histogram.measurement_count, 257); assert.equal(range.selected_histogram.measurement_count, 129);
    const ratio = clone(h.ctx.ECGDemoRR.query(index, {mode: 'ratio'})); assert.equal(ratio.histogram.measurement_count, 256);
  });
  await check('RR exact targets reject every stale identity and endpoint instead of nearest beat', () => {
    const index = h.ctx.ECGDemoRR.build(directFeed([800, 1000, 800]), scope), target = clone(h.ctx.ECGDemoRR.query(index, {}).items[1].target);
    for (const [field, value] of Object.entries({case_id: 'other', analysis_basis: 'old', analysis_revision: 6, beat_revision: 2, index_key: 'old', beat_id: 'unknown', interval_id: 'old', interval_start_sample: 1, interval_end_sample: 1, sample_index: target.sample_index + 1}))
      assert.throws(() => h.ctx.ECGDemoRR.resolve(index, {...target, [field]: value}), undefined, field);
    for (const field of ['case_id', 'analysis_basis', 'analysis_revision', 'beat_revision', 'beat_id', 'interval_id', 'interval_start_sample', 'interval_end_sample', 'index_key']) {
      const incomplete = {...target}; delete incomplete[field]; assert.throws(() => h.ctx.ECGDemoRR.resolve(index, incomplete), undefined, field);
    }
  });

  // The remaining checks use fetch routes, persistence and revision contracts.
  await check('RR real fetch endpoint returns exact mathematical intervals and scoped location', async () => {
    const all = await h.call('rr-review?limit=200');
    assert.equal(all.total, 600); assert.equal(all.items.length, 200); assert.equal(all.summary.nn_verified_count, 0);
    const target = all.items[1].target, located = await h.call('rr-review/locate', 'POST', {target});
    assert.equal(located.located, true); assert.deepEqual(located.target, target);
    assert(located.waveform.beats.some(b => b.sample_index === target.sample_index));
    for (const field of ['analysis_basis', 'analysis_revision', 'beat_revision']) assert.equal(located.waveform[field], target[field]);
    await h.call('rr-review/locate', 'POST', {target: {...target, beat_id: 'missing'}}, 409);
    return {total: all.total, locatedSample: target.sample_index};
  });
  await check('RR actual waveform-strips response and every item carry the exact case identity', async () => {
    const all = await h.call('rr-review?limit=16'), samples = all.items.map(item => item.target.sample_index);
    const identity = {case_id: h.input.case_id, analysis_basis: all.analysis_basis, analysis_revision: all.analysis_revision, beat_revision: all.beat_revision};
    const strips = await h.call('waveform-strips', 'POST', {...identity, sample_indices: samples, leads: ['II', 'V1', 'V5'], filter: 'raw'});
    assert.equal(strips.case_id, h.input.case_id); assert.equal(strips.items.length, samples.length);
    for (const [index, item] of strips.items.entries()) {
      assert.equal(item.case_id, h.input.case_id); assert.equal(item.sample_index, samples[index]);
      assert.deepEqual(Object.keys(item.leads), ['II', 'V1', 'V5']);
      for (const field of ['analysis_basis', 'analysis_revision', 'beat_revision']) assert.equal(item[field], identity[field]);
    }
    await h.call('waveform-strips', 'POST', {...identity, case_id: 'different-mathematical-case', sample_indices: samples, leads: ['II', 'V1', 'V5'], filter: 'raw'}, 409);
    return {case_id: strips.case_id, count: strips.items.length, exact_samples: samples};
  });
  await check('HRV baseline equals same saved input JS calculations on fixed 300 second grid', async () => {
    const current = await h.call('hrv-review'), feed = h.ctx.ECGBeatEngine.materialize(h.input.beats, h.ctx.ECGBeatEngine.blank(), []);
    feed.duration = h.input.technical.duration_seconds_raw; feed.excluded_rhythm_intervals = [];
    const baseline = clone(h.ctx.ECGHrvAnalysis.analyze(feed, h.input.metadata.start_iso, 0));
    assert.deepEqual(current.evidence.baseline, baseline); assert.deepEqual(current.evidence.reviewed, baseline);
    assert.equal(current.evidence.blocks[0].start_s, 0); assert.equal(current.evidence.blocks[0].end_s, 300);
    assert.equal(current.evidence.blocks[1].start_s, 300); assert.equal(current.evidence.blocks[1].end_s, 600);
    assert.equal(current.evidence.blocks[2].complete, false); assert.equal(current.evidence.blocks[2].duration_s, 1);
    assertStats(current.evidence.reviewed.periods.full, statsOracle(nnOracle(h.input)));
  });
  await check('HRV preview keeps holes, strict pNN50 and complete-interval exclusions without mutating saved inputs', async () => {
    const t = harness(mathCase([800, 800, 1000, 1200, 1200], {duration: 10})), current = await t.call('hrv-review'), before = clone(t.input.beats), ranges = [exclusion(320, 520)];
    const value = await preview(t, current, doc(ranges));
    assertStats(value.evidence_preview.reviewed.periods.full, statsOracle(nnOracle(t.input, ranges)));
    const block = value.evidence_preview.blocks[0].reviewed;
    assert.equal(block.nn_count, 4); assert.equal(block.consecutive_difference_count, 2); assert.equal(block.rmssd_ms, 0); assert.equal(block.pnn50_pct, 0);
    assert.deepEqual((await t.call('hrv-review')).document, current.document); assert.deepEqual(t.input.beats, before);
    const exact = harness(mathCase([800, 850, 900], {duration: 10})), equal = await exact.call('hrv-review');
    assert.equal(equal.evidence.blocks[0].reviewed.nn50_count, 0); assert.equal(equal.evidence.reviewed.periods.full.pnn50_pct, 0);
    assert.equal(equal.evidence.profile.pnn50.comparison, 'strictly_greater');
  });
  await check('HRV overlapping ranges are unioned and tiny holes prevent interpolation', async () => {
    const current = await h.call('hrv-review'), ranges = [exclusion(200, 400, 'a'), exclusion(300, 500, 'b')], value = await preview(h, current, doc(ranges));
    assert.equal(value.evidence_preview.coverage.excluded_s, 1.5); assert.equal(value.evidence_preview.coverage.retained_s, 599.5);
    assertStats(value.evidence_preview.reviewed.periods.full, statsOracle(nnOracle(h.input, ranges)));
    const tiny = await preview(h, current, doc([exclusion(30000, 30001)])), block = tiny.evidence_preview.blocks[0];
    assert.equal(block.baseline.spectral_qualified, true); assert.equal(block.reviewed.qualified, true);
    assert.equal(block.reviewed.spectral_qualified, false); assert.equal(block.reviewed.spectral_reason, 'spectral_interpolation_crosses_exclusion');
    assert.deepEqual(tiny.evidence_preview.blocks[1].baseline, tiny.evidence_preview.blocks[1].reviewed);
    assert.equal(tiny.evidence_preview.reviewed.periods.full.spectral_blocks, 1);
  });
  await check('HRV review exclusions change retained NN without changing RR candidates or QRS inputs', async () => {
    const t = harness(), rrBefore = await t.call('rr-review'), current = await t.call('hrv-review');
    const saved = await apply(t, current, await preview(t, current, doc([exclusion(30000, 30001)]))), measured = await t.call('hrv-review'), rrAfter = await t.call('rr-review');
    assert.equal(measured.evidence.baseline.periods.full.nn_count, 600); assert.equal(measured.evidence.reviewed.periods.full.nn_count, 599);
    assert.deepEqual(rrAfter.summary, rrBefore.summary); assert.equal(rrAfter.summary.nn_verified_count, 0); assert.equal(rrAfter.total, rrBefore.total);
    assert.equal(saved.document.exclusions.length, 1); assert.equal((await t.call('beat-editor')).revision, 0);
  });
  await check('pending rhythm exclusions preserve ordinary RR timing and prevent NN spectral bridges', async () => {
    const t = harness();
    await t.call('annotations', 'POST', {sample_index: 29000, lead: 'II', note: 'Original mathematical rhythm exclusion', details: {kind: 'AF', status: 'pending', end_sample: 30999}}, 201);
    const current = await t.call('hrv-review'), rr = await t.call('rr-review?limit=200');
    assert.equal(current.evidence.blocks[0].baseline.nn_count, 290);
    assert.equal(current.evidence.blocks[0].baseline.spectral_reason, 'spectral_gap_over_5s');
    assert.equal(current.evidence.blocks[1].baseline.nn_count, 300);
    assert.equal(rr.summary.normal_pair_count, 600); assert.equal(rr.summary.nn_eligible_count, 590); assert.equal(rr.summary.nn_verified_count, 0);
    assert.equal(rr.items.find(r => r.end_sample === 29200).rr_ms, 1000);
    assert.equal(rr.items.find(r => r.end_sample === 29200).nn_candidate_compat, false);
  });
  await check('HRV 24 hour window preserves absolute 300 second grid and partial final block', async () => {
    const t = harness(mathCase(Array(310).fill(1000), {firstSample: 86400 * 200, duration: 86710})), current = await t.call('hrv-review?window=1');
    assert.equal(current.window_index, 1); assert.equal(current.start_sample, 86400 * 200); assert.equal(current.end_sample, 86710 * 200);
    assert.equal(current.evidence.coverage.window_start_s, 86400); assert.equal(current.evidence.coverage.window_end_s, 86710);
    assert.equal(current.evidence.blocks[0].start_s, 86400); assert.equal(current.evidence.blocks[0].end_s, 86700);
    assert.equal(current.evidence.blocks[1].duration_s, 10); assert.equal(current.evidence.blocks[1].complete, false);
    assert(current.evidence.blocks[1].reviewed.qualification_reasons.includes('incomplete_300s_block'));
    const body = state => ({scope: state.scope, expected_hrv_revision: state.hrv_revision, expected_document_digest: state.digest, confirmed: true, nn_rhythm_artifact_reviewed: true, window: state.window_index});
    const zero = await t.call('hrv-review?window=0'), first = await t.call('hrv-review/confirm', 'POST', body(zero));
    const one = await t.call('hrv-review?window=1'), second = await t.call('hrv-review/confirm', 'POST', body(one));
    assert.equal(first.confirmation.window_index, 0); assert.equal(second.confirmation.window_index, 1);
    assert.equal(second.confirmations['0'].valid, true); assert.equal(second.confirmations['1'].valid, true);
    await t.call('hrv-review?window=2', 'GET', undefined, 400);
  });
  await check('HRV validates the entire source and revision scope before preview', async () => {
    const current = await h.call('hrv-review'), payload = {scope: current.scope, expected_hrv_revision: current.hrv_revision, operation: 'replace', document: doc([exclusion(200, 400)]), window: 0};
    assert.deepEqual(Object.keys(current.scope).sort(), ['analysis_basis', 'analysis_revision', 'beat_revision', 'case_id', 'data_version', 'source_digest'].sort());
    for (const field of ['case_id', 'source_digest', 'data_version', 'analysis_basis', 'beat_revision', 'analysis_revision']) {
      const stale = clone(payload); stale.scope[field] = typeof stale.scope[field] === 'number' ? stale.scope[field] + 1 : stale.scope[field] + '-old';
      await h.call('hrv-review/preview', 'POST', stale, 409);
    }
    await h.call('hrv-review/preview', 'POST', {...payload, expected_hrv_revision: current.hrv_revision + 1}, 409);
    await h.call('hrv-review/preview', 'POST', {...payload, document: {...payload.document, unknown: true}}, 400);
    for (const bad of [exclusion(-1, 1), exclusion(200, 200), exclusion(0, 1.5), exclusion(0, 120201)])
      await h.call('hrv-review/preview', 'POST', {...payload, document: doc([bad])}, 400);
    await h.call('hrv-review?window=1', 'GET', undefined, 400);
  });
  await check('HRV cancel, preview digest, single use and immutable reopen preserve saved revisions', async () => {
    let current = await h.call('hrv-review');
    const canceled = await preview(h, current, doc([exclusion(200, 400)]));
    const response = await h.call('hrv-review/cancel', 'POST', {scope: current.scope, expected_hrv_revision: current.hrv_revision, preview_token: canceled.preview_token, window: 0});
    assert.deepEqual(response.document, current.document); assert.equal(response.hrv_revision, current.hrv_revision);
    await apply(h, current, canceled, {}, 409);
    const value = await preview(h, current, doc([exclusion(30000, 30001)]));
    await apply(h, current, value, {preview_digest: '0'.repeat(64)}, 409);
    await apply(h, current, value, {confirmed: false}, 400);
    const saved = await apply(h, current, value);
    assert.equal(saved.hrv_revision, current.hrv_revision + 1); assert.equal(saved.scope.analysis_revision, current.scope.analysis_revision + 1);
    assert.equal(saved.can_undo, true); assert.equal(saved.confirmation.valid, false);
    await apply(h, current, value, {}, 409);
    const reopened = harness(h.input, h.localStorage.values), read = await reopened.call('hrv-review');
    assert.deepEqual(read.document, saved.document); assert.deepEqual(read.scope, saved.scope); assert.equal(read.digest, saved.digest);
    assert.equal(read.evidence.reviewed.periods.full.spectral_blocks, 1);
    return {hrvRevision: saved.hrv_revision, analysisRevision: saved.scope.analysis_revision, reopened: true};
  });
  await check('HRV failed persistence is atomic and the same preview can be retried', async () => {
    const t = harness(), current = await t.call('hrv-review'), value = await preview(t, current, doc([exclusion(200, 400)])), before = t.localStorage.getItem(key);
    t.localStorage.failNextWrite(); await apply(t, current, value, {}, 400);
    assert.equal(t.localStorage.getItem(key), before);
    const failed = await t.call('hrv-review'); assert.deepEqual(failed.document, current.document); assert.deepEqual(failed.scope, current.scope); assert.equal(failed.hrv_revision, 0);
    const retry = await apply(t, current, value); assert.equal(retry.hrv_revision, 1);
  });
  await check('HRV preview expiry and later acknowledgement cannot commit a stale token', async () => {
    const t = harness(), current = await t.call('hrv-review'), expired = await preview(t, current, doc([exclusion(200, 400)]));
    t.advanceMs(900001); await apply(t, current, expired, {}, 409);
    assert.equal((await t.call('hrv-review')).hrv_revision, 0);
    const pending = await preview(t, current, doc([exclusion(400, 600)]));
    const acknowledged = await t.call('hrv-review/confirm', 'POST', {scope: current.scope, expected_hrv_revision: current.hrv_revision, expected_document_digest: current.digest, confirmed: true, nn_rhythm_artifact_reviewed: true, window: 0});
    await apply(t, current, pending, {}, 409); await apply(t, acknowledged, pending, {}, 409);
    const read = await t.call('hrv-review'); assert.equal(read.hrv_revision, 0); assert.deepEqual(read.document.exclusions, []); assert.equal(read.confirmation.valid, true);
  });
  await check('HRV undo redo reset need new preview and invalidate previous confirmations', async () => {
    const t = harness(); let current = await t.call('hrv-review');
    current = await apply(t, current, await preview(t, current, doc([exclusion(200, 400)])));
    const first = clone(current.document);
    current = await t.call('hrv-review/confirm', 'POST', {scope: current.scope, expected_hrv_revision: current.hrv_revision, expected_document_digest: current.digest, confirmed: true, nn_rhythm_artifact_reviewed: true, window: 0, note: 'Original mathematical acknowledgement'});
    assert.equal(current.confirmation.valid, true); assert.equal(current.confirmation.clinical_validation, false); assert.equal(current.confirmation.quality_status, 'unknown');
    current = await apply(t, current, await preview(t, current, null, 'undo'));
    assert.deepEqual(current.document.exclusions, []); assert.equal(current.can_redo, true); assert.equal(current.confirmation.valid, false);
    current = await apply(t, current, await preview(t, current, null, 'redo'));
    assert.deepEqual(current.document, first); assert.equal(current.can_redo, false);
    current = await apply(t, current, await preview(t, current, null, 'reset'));
    assert.deepEqual(current.document.exclusions, []); assert.equal(current.hrv_revision, 4);
  });
  await check('HRV confirmation checks digest and remains a review declaration with zero verified RR', async () => {
    const t = harness(), current = await t.call('hrv-review'), body = {scope: current.scope, expected_hrv_revision: current.hrv_revision, expected_document_digest: current.digest, confirmed: true, nn_rhythm_artifact_reviewed: true, window: 0, note: 'Original mathematical acknowledgement'};
    await t.call('hrv-review/confirm', 'POST', {...body, expected_document_digest: '0'.repeat(64)}, 409);
    await t.call('hrv-review/confirm', 'POST', {...body, nn_rhythm_artifact_reviewed: false}, 400);
    const acknowledged = await t.call('hrv-review/confirm', 'POST', body);
    assert.equal(acknowledged.confirmation.valid, true); assert.equal(acknowledged.confirmation.clinical_validation, false);
    const all = await t.call('rr-review'); assert.equal(all.summary.nn_verified_count, 0);
    assert.equal((await t.call('rr-review?population=nn_verified')).total, 0);
  });
  await check('beat edits invalidate full HRV source scope and stale RR targets without rewriting original inputs', async () => {
    const t = harness(), original = clone(t.input.beats), rr = await t.call('rr-review'), target = rr.items[2].target;
    let current = await t.call('hrv-review');
    current = await apply(t, current, await preview(t, current, doc([exclusion(200, 400)])));
    const editor = await t.call('beat-editor');
    await t.call('beat-editor', 'PUT', {revision: editor.revision, operation: 'relabel', selection: {scope: 'samples', samples: [1000]}, class_code: 'V', confirmed: true});
    const stale = await t.call('hrv-review'); assert.equal(stale.document_stale, true); assert.equal(stale.evidence.reviewed, null); assert.deepEqual(stale.document, current.document);
    await t.call('rr-review/locate', 'POST', {target}, 409);
    await t.call('hrv-review/confirm', 'POST', {scope: stale.scope, expected_hrv_revision: stale.hrv_revision, expected_document_digest: stale.digest, confirmed: true, nn_rhythm_artifact_reviewed: true, window: 0}, 409);
    const refreshed = await apply(t, stale, await preview(t, stale, stale.document));
    assert.equal(refreshed.document_stale, false); assert.deepEqual(refreshed.document, current.document); assert.deepEqual(t.input.beats, original);
  });
  await check('terminology builtin contains only original MIT drafts and declared provenance', async () => {
    const list = await h.call('/api/terminology/catalogs'); assert.equal(list.items.length, 1);
    const item = list.items[0]; assert.equal(item.builtin, true); assert.equal(item.approval, 'draft'); assert.equal(item.completeness, 'example');
    const value = await h.call('/api/terminology/catalog?' + new URLSearchParams({namespace: item.namespace, version: item.version, hash: item.sha256}));
    assert.deepEqual(value, builtin); assert.equal(value.nodes.length, 9);
    assert.equal(value.nodes.filter(n => n.kind === 'term').length, 6);
    assert(value.nodes.every(n => n.approval === 'draft' && n.source.verification === 'declared' && n.license.name === 'MIT'));
    assert.match(value.source.name, /原创/); assert.match(value.description, /示例|医院/);
  });
  await check('terminology import rejects cycles, unknown fields, unsafe URLs, HTML, status and tampered hash', async () => {
    const current = await h.call('/api/terminology/catalogs'), cases = [];
    const bad = mutate => {const value = catalog(); mutate(value); delete value.sha256; return value;};
    cases.push(bad(v => {v.nodes[0].parent_id = v.nodes[1].stable_id;}));
    cases.push(bad(v => {v.unknown = true;}));
    cases.push(bad(v => {v.nodes[1].unknown = true;}));
    cases.push(bad(v => {v.nodes[1].source.url = 'javascript:alert(1)';}));
    cases.push(bad(v => {v.nodes[1].source.url = 'https://127.0.0.1/secret';}));
    cases.push(bad(v => {v.nodes[1].text = '<img src=x onerror=alert(1)>';}));
    cases.push(bad(v => {v.nodes[1].approval = 'certified';}));
    cases.push(bad(v => {v.nodes[1].source.verification = 'verified';}));
    cases.push({...catalog(), sha256: '0'.repeat(64)});
    cases.push(bad(v => {v.nodes.push(clone(v.nodes[1]));}));
    for (const value of cases) await h.call('/api/terminology/import', 'POST', {catalog: value, expected_catalog_revision: current.catalog_revision, confirm: false}, 400);
    assert.equal((await h.call('/api/terminology/catalogs')).catalog_revision, current.catalog_revision);
    assert.equal((await h.call('/api/terminology/catalogs')).items.length, 1);
    return {rejected: cases.length};
  });
  await check('terminology import preview confirmation, SHA and namespace version are immutable across reopen', async () => {
    const t = harness(), value = catalog(), list = await t.call('/api/terminology/catalogs'), payload = {catalog: value, expected_catalog_revision: list.catalog_revision, confirm: false};
    const proposed = await t.call('/api/terminology/import', 'POST', payload); assert.equal(proposed.preview_only, true); assert.equal(proposed.preview_hash, value.sha256);
    assert.equal((await t.call('/api/terminology/catalogs')).items.length, 1);
    await t.call('/api/terminology/import', 'POST', {...payload, confirm: true, preview_hash: '0'.repeat(64)}, 400);
    const published = await t.call('/api/terminology/import', 'POST', {...payload, confirm: true, preview_hash: proposed.preview_hash});
    assert.equal(published.preview_only, false); assert.equal(published.catalog_revision, list.catalog_revision + 1);
    await t.call('/api/terminology/import', 'POST', {...payload, confirm: true, preview_hash: proposed.preview_hash}, 409);
    const replacement = catalog('v1', 'Attempted rewrite of original version.');
    await t.call('/api/terminology/import', 'POST', {catalog: replacement, expected_catalog_revision: published.catalog_revision, confirm: true, preview_hash: replacement.sha256}, 409);
    const reopened = harness(t.input, t.localStorage.values), selected = await reopened.call('/api/terminology/catalog?' + new URLSearchParams({namespace: value.namespace, version: value.version, hash: value.sha256}));
    assert.deepEqual(selected, value); assert.equal((await reopened.call('/api/terminology/catalogs')).items.length, 2);
    const before = t.localStorage.getItem(key), next = catalog('v2'); t.localStorage.failNextWrite();
    await t.call('/api/terminology/import', 'POST', {catalog: next, expected_catalog_revision: published.catalog_revision, confirm: true, preview_hash: next.sha256}, 400);
    assert.equal(t.localStorage.getItem(key), before); assert.equal((await t.call('/api/terminology/catalogs')).items.length, 2);
  });
  await check('report persists original terminology snapshots and rejects stale HRV references', async () => {
    const t = harness(); let current = await t.call('hrv-review');
    current = await apply(t, current, await preview(t, current, doc([exclusion(200, 400)])));
    const catalogList = await t.call('/api/terminology/catalogs'), item = catalogList.items[0];
    const value = await t.call('/api/terminology/catalog?' + new URLSearchParams({namespace: item.namespace, version: item.version, hash: item.sha256})), node = value.nodes.find(n => n.kind === 'term');
    const usage = {usage_id: 'term-original-math', namespace: value.namespace, version: value.version, catalog_hash: value.sha256, stable_id: node.stable_id, label: node.label,
      inserted_text: node.text, approval: node.approval, source: node.source, license: node.license, scope: node.scope, review: node.review, inserted_at: '2026-01-02T08:00:00Z'};
    let report = await t.call('report');
    const payload = {status: 'draft', expected_version: report.version, expected_review_revision: report.review_revision, conclusion: 'Doctor original draft. ' + node.text,
      composition: {...report.composition, include_hrv: true, hrv_window: 0, hrv_review_reference: report.current_hrv_reference, terminology_usages: [usage]}};
    await t.call('report', 'PUT', {...payload, composition: {...payload.composition, hrv_review_reference: {...report.current_hrv_reference, document_digest: '0'.repeat(64)}}}, 409);
    const saved = await t.call('report', 'PUT', payload); assert.deepEqual(saved.composition.terminology_usages, [usage]); assert.deepEqual(saved.composition.hrv_review_reference, report.current_hrv_reference);
    const reopened = harness(t.input, t.localStorage.values), read = await reopened.call('report'); assert.equal(read.conclusion, saved.conclusion); assert.deepEqual(read.composition.terminology_usages, [usage]);
    const newValue = catalog('v2', 'New original phrase does not replace saved text.'), list = await t.call('/api/terminology/catalogs');
    await t.call('/api/terminology/import', 'POST', {catalog: newValue, expected_catalog_revision: list.catalog_revision, confirm: true, preview_hash: newValue.sha256});
    assert.equal((await t.call('report')).conclusion, saved.conclusion); assert.deepEqual((await t.call('report')).composition.terminology_usages, [usage]);
    current = await t.call('hrv-review'); await apply(t, current, await preview(t, current, doc([exclusion(400, 600)])));
    report = await t.call('report');
    await t.call('report', 'PUT', {...payload, expected_version: report.version, expected_review_revision: report.review_revision}, 409);
    const staleRead = await reopened.call('report'); assert.equal(staleRead.conclusion, saved.conclusion); assert.deepEqual(staleRead.composition.terminology_usages, [usage]);
    assert.notDeepEqual(staleRead.current_hrv_reference, staleRead.composition.hrv_review_reference);
    return {usageHash: usage.catalog_hash, savedConclusionRetained: true, staleHrvRejected: true};
  });
  await check('API reads abort and refuse mismatched identities without native network access', async () => {
    const controller = new AbortController(); controller.abort();
    await assert.rejects(h.ctx.fetch('/api/cases/' + h.input.case_id + '/rr-review', {signal: controller.signal}), e => e.name === 'AbortError');
    const basis = await h.call('analysis-basis');
    await h.call('rr-review?' + new URLSearchParams({...basis, analysis_revision: basis.analysis_revision + 1}), 'GET', undefined, 409);
    assert(results.nativeRequests.every(name => name.endsWith('builtin-draft-v1.json') || name.endsWith('/waveform.bin')));
  });
  await check('inflight RR location rejects shared-storage source changes and honors read abort', async () => {
    const t = harness(), all = await t.call('rr-review'), target = all.items[1].target, other = harness(t.input, t.localStorage.values);
    t.holdNative('/static/demo-data/mathematical-4314/waveform.bin');
    const pending = t.call('rr-review/locate', 'POST', {target}, 409); await t.waitHeld();
    const editor = await other.call('beat-editor');
    await other.call('beat-editor', 'PUT', {revision: editor.revision, operation: 'relabel', selection: {scope: 'samples', samples: [1000]}, class_code: 'V', confirmed: true});
    t.releaseNative(); await pending;
    const a = harness(), rr = await a.call('rr-review'), controller = new AbortController();
    a.holdNative('/static/demo-data/mathematical-4314/waveform.bin');
    const aborted = a.ctx.fetch('/api/cases/' + a.input.case_id + '/rr-review/locate', {method: 'POST', body: JSON.stringify({target: rr.items[1].target}), signal: controller.signal});
    await a.waitHeld(); controller.abort(); a.releaseNative(); await assert.rejects(aborted, e => e.name === 'AbortError');
    assert.equal((await a.call('beat-editor')).revision, 0);
  });
  if (process.env.ECG_DEMO_PYTHON) {
    await check('Python RR oracle matches actual adapter measurements facets and full original filters', () => {
      const codes = ['N', 'N', 'V', 'N', 'N', 'X', 'N', 'N', '!', 'N', 'OTHER', 'N'], feed = directFeed([800, 1000, 800, 1000, 900, 900, 850, 800, 1000, 1100, 1000], codes);
      feed.beats[6].rr_ms = 0; feed.excluded_rhythm_intervals = [[1.7, 1.8]];
      feed.beats.splice(1, 0, {id: 'marker:y', sample_index: 20, class_code: 'Y'});
      const queries = [{}, {population: 'normal_pair', mode: 'ratio'}, {population: 'nn_eligible', mode: 'hr'}, {quality: 'invalid'}, {range_min: 800, range_max: 1000}, {offset: 8, limit: 2}, {pair_type: '["N","N"]'}];
      const expected = pythonOracle('rr', queries.map(query => ({feed, scope, query}))), index = h.ctx.ECGDemoRR.build(feed, scope);
      queries.forEach((query, i) => {
        const actual = clone(h.ctx.ECGDemoRR.query(index, query)), oracle = expected[i];
        for (const field of ['summary', 'query', 'total', 'offset', 'limit', 'has_previous', 'has_next', 'pair_types', 'histogram', 'selected_histogram']) numericTree(actual[field], oracle[field], field);
        assert.equal(actual.items.length, oracle.items.length);
        actual.items.forEach((row, j) => {
          for (const field of ['index', 'start_sample', 'end_sample', 'time_s', 'left_type', 'right_type', 'pair_type', 'stored_rr_ms', 'computed_rr_ms', 'rr_ms', 'ratio_pct', 'hr_bpm', 'type_known', 'quality', 'normal_pair', 'normal_label_pair', 'nn_candidate_compat', 'nn_eligible_current_rules', 'nn_reason', 'nn_rule_rr_ms', 'nn_eligible_verified', 'ratio_reason', 'match_index'])
            numericTree(row[field], oracle.items[j][field], 'items[' + j + '].' + field);
        });
      });
      return {mathematicalQueries: queries.length, interpreter: process.env.ECG_DEMO_PYTHON};
    });
    await check('Python HRV oracle matches mathematical periods blocks holes and power spectra', () => {
      const cases = [
        {input: mathCase(), exclusions: []},
        {input: mathCase(), exclusions: [exclusion(30000, 30001)]},
        {input: mathCase(Array.from({length: 670}, (_, i) => 900 + 5 * Math.round(16 * Math.sin(i * 0.17) + 4 * Math.cos(i * 0.41)))), exclusions: [exclusion(29000, 29300, 'a'), exclusion(29200, 29500, 'b')]},
        {input: mathCase([800, 800, 1000, 1200, 1200], {duration: 10}), exclusions: [exclusion(320, 520)]},
        {input: mathCase([800, 850, 900], {duration: 10}), exclusions: []},
        {input: mathCase(Array(600).fill(1000)), rhythm: [[145, 155]], exclusions: []},
        {input: mathCase(Array(310).fill(1000), {firstSample: 86400 * 200, duration: 86710}), window: 1, exclusions: []}
      ];
      const values = cases.map(item => {
        const feed = clone(h.ctx.ECGBeatEngine.materialize(item.input.beats, h.ctx.ECGBeatEngine.blank(), [])); feed.duration = item.input.technical.duration_seconds_raw; feed.excluded_rhythm_intervals = item.rhythm || [];
        return {feed, start_time: item.input.metadata.start_iso, window: item.window || 0, exclusions: item.exclusions};
      });
      const expected = pythonOracle('hrv', values);
      values.forEach((value, i) => {
        const actual = clone(h.ctx.ECGDemoReviewAPI.analyze(value.feed, value.start_time, value.window, value.exclusions)), oracle = expected[i];
        numericTree(actual.coverage, oracle.coverage, 'coverage'); assert.equal(actual.blocks.length, oracle.blocks.length);
        for (const section of ['baseline', 'reviewed']) {
          for (const period of ['full', 'day', 'night']) {
            numericTree(actual[section].periods[period], oracle[section].periods[period], section + '.' + period, 0.011);
            for (const field of ['psd', 'frequency', 'histogram', 'sdann_ms', 'sdnn_index_ms', 'triangular_index'])
              numericTree(actual[section].periods[period][field], oracle[section].periods[period][field], section + '.' + period + '.' + field);
          }
          numericTree(actual[section].hourly, oracle[section].hourly, section + '.hourly', 0.011);
          numericTree(actual[section].trend, oracle[section].trend, section + '.trend', 0.00011);
          numericTree(actual[section].rate_sdnn, oracle[section].rate_sdnn, section + '.rate_sdnn', 0.00011);
        }
        actual.blocks.forEach((block, j) => {
          numericTree(block, oracle.blocks[j], 'blocks[' + j + ']', 0.011);
          for (const section of ['baseline', 'reviewed']) for (const field of ['psd', 'frequency', 'histogram', 'sdann_ms', 'sdnn_index_ms', 'triangular_index'])
            numericTree(block[section][field], oracle.blocks[j][section][field], 'blocks[' + j + '].' + section + '.' + field);
        });
        assert(actual.blocks.every(block => block.baseline.nn_verified_count === 0 && block.reviewed.nn_verified_count === 0));
      });
      return {mathematicalCases: cases.length, compared: 'periods/hourly/trend/rate_sdnn/fixed blocks/coverage/histograms/PSD/frequency', interpreter: process.env.ECG_DEMO_PYTHON};
    });
    results.pythonOracle = {executed: true, clinicalInputsRead: false};
  } else results.pythonOracle = {executed: false, optIn: 'Set ECG_DEMO_PYTHON to an interpreter with numpy for additional cross-runtime mathematical checks.'};

  results.completed = new Date().toISOString();
  fs.writeFileSync(path.join(out, 'results.json'), JSON.stringify(results, null, 2) + '\n');
  console.log(`${results.checks.length} checks passed; evidence: ${path.join(out, 'results.json')}`);
})().catch(error => {console.error(error.stack || error); process.exitCode = 1;});
