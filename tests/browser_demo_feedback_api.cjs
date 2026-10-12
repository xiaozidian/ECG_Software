'use strict';
// The real browser adapters and the real native scalar calculator consume the
// same original mathematical int16 bytes. No server, patient file or network.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const {spawnSync} = require('node:child_process');

const root = path.resolve(process.env.ECG_DEMO_SOURCE || path.join(__dirname, '..'));
const evidenceRoot = path.resolve(process.env.ECG_DEMO_FEEDBACK_EVIDENCE || '/tmp/ecg-demo-feedback-mean-save-case-id-fix-v2-evidence');
const python = process.env.ECG_DEMO_PYTHON || 'python3';
const STORE_KEY = 'cardioinsight-public-math-4314-v2';
const CASE_ID = 'math-4314-001';
const LEADS = ['I', 'II', 'III', 'aVR', 'aVL', 'aVF', 'V1', 'V2', 'V3', 'V4', 'V5', 'V6'];
const CHANNEL_WEIGHTS = [1, 2, 3, 4, 5, 6, 7, 8];
const LEAD_WEIGHTS = [1, 2, 1, -1.5, 0, 1.5, 3, 4, 5, 6, 7, 8];
const SCOPE_FIELDS = ['case_id', 'analysis_basis', 'analysis_revision', 'beat_revision'];
const SCOPE6_FIELDS = ['case_id', 'source_digest', 'data_version', 'analysis_basis', 'beat_revision', 'analysis_revision'];
const clone = value => JSON.parse(JSON.stringify(value));
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const record = (sample, group = 1, rr = 1000) => ({sample_index: sample, group, rr_ms: rr});
const mask = (start, end, reason, extra = {}) => ({start_sample: start, end_sample: end, reason, ...extra});
const report = {
  scope: 'actual-demo-feedback-adapters-and-native-scalar-original-int16-mathematics-only',
  started: new Date().toISOString(), patientInputsRead: false, serversStarted: false,
  externalNetworkRequests: [], checks: [], nativeAssetRequests: [], oracle: {interpreter: python},
  crossRuntimeComparisons: [],
};

function near(actual, expected, label, tolerance = 1e-6) {
  assert(Number.isFinite(actual) && Math.abs(actual - expected) <= tolerance,
    `${label}: ${actual} != ${expected}; maximum absolute error ${tolerance} source units`);
}
function exactNumericTree(actual, expected, label = 'result', metrics = null) {
  if (typeof expected === 'number') {
    if (metrics) {
      const error = Math.abs(actual - expected);
      metrics.numericFieldComparisons++;
      metrics.maximumAbsoluteNumericError = Math.max(metrics.maximumAbsoluteNumericError, error);
      if (/\.mean_units$/.test(label)) metrics.maximumAbsoluteMeanErrorUnits = Math.max(metrics.maximumAbsoluteMeanErrorUnits, error);
      if (/\.(j_offset_samples|j_offset_ms|landmark_confidence|j_representative_samples)(\[\d+\])?$/.test(label)) metrics.maximumAbsoluteJError = Math.max(metrics.maximumAbsoluteJError, error);
      if (/\.(quality_score|normal_beat_ratio)$/.test(label)) metrics.maximumAbsoluteQualityError = Math.max(metrics.maximumAbsoluteQualityError, error);
      if (/\.coverage\./.test(label)) metrics.maximumAbsoluteCoverageError = Math.max(metrics.maximumAbsoluteCoverageError, error);
    }
    if (Number.isInteger(expected)) assert.equal(actual, expected, label);
    else near(actual, expected, label);
  } else if (Array.isArray(expected)) {
    assert(Array.isArray(actual), label + ' is not an array');
    assert.equal(actual.length, expected.length, label + '.length');
    expected.forEach((value, i) => exactNumericTree(actual[i], value, `${label}[${i}]`, metrics));
  } else if (expected && typeof expected === 'object') {
    assert(actual && typeof actual === 'object', label + ' is not an object');
    assert.deepEqual(Object.keys(actual).sort(), Object.keys(expected).sort(), label + ' keys');
    for (const [field, value] of Object.entries(expected)) exactNumericTree(actual[field], value, label + '.' + field, metrics);
  } else assert.equal(actual, expected, label);
}
function compareST(actual, expected, label, {compact = false} = {}) {
  // Runtime/source digests carry an additional browser mathematics declaration.
  // The selected samples, method, observations and availability remain exact.
  const metrics = {name: label, numericFieldComparisons: 0, maximumAbsoluteNumericError: 0,
    maximumAbsoluteMeanErrorUnits: 0, maximumAbsoluteJError: 0, maximumAbsoluteQualityError: 0, maximumAbsoluteCoverageError: 0};
  for (const field of ['schema_version', 'scope', 'method_profile', 'range', 'counts',
    'coverage', 'mask_reason_counts', 'count_definition', 'leads',
    ...(compact ? [] : ['blocks']), 'review_status', 'interpretation'])
    exactNumericTree(actual[field], expected[field], label + '.' + field, metrics);
  if (compact) assert.equal(Object.hasOwn(actual, 'blocks'), false, label + ': API must return a compact result');
  exactNumericTree(actual.exclusions.intervals, expected.exclusions.intervals, label + '.exclusions.intervals', metrics);
  assert.equal(actual.binding.source_sample_count, expected.binding.source_sample_count, label + '.source_sample_count');
  metrics.methodProfileExact = true; metrics.scopeExact = true; metrics.countsExact = true;
  metrics.sampleSelectionAndJRepresentativesExact = true;
  report.crossRuntimeComparisons.push(metrics);
  return metrics;
}
function rawSource(count = 16000) {return Buffer.alloc(count * 16);}
function setFrame(raw, sample, channel, value) {raw.writeInt16LE(value, sample * 16 + channel * 2);}
function frameAdd(raw, sample, channel, value) {setFrame(raw, sample, channel, raw.readInt16LE(sample * 16 + channel * 2) + value);}
function paintBeat(raw, sample, delta, weights = CHANNEL_WEIGHTS) {
  for (let channel = 0; channel < 8; channel++) {
    [1000, 500, 200, 0].forEach((value, offset) => setFrame(raw, sample + offset, channel, value * weights[channel]));
    for (let offset = 18; offset <= 30; offset++) setFrame(raw, sample + offset, channel, delta * weights[channel]);
  }
}
function handFixture() {
  const raw = rawSource();
  const anchors = [400, 800, 1200, 1600, 2000, 2400, 2800, 3400,
    ...Array.from({length: 14}, (_, i) => 3600 + i * 200)];
  anchors.forEach(sample => paintBeat(raw, sample, sample < 3200 ? 10 : 30));
  const rows = anchors.map((sample, i) => record(sample, 1, i ? (sample - anchors[i - 1]) * 5 : 0));
  return {raw, rows};
}
function denseFixture() {
  const raw = rawSource(), rows = [];
  for (let second = 1; second < 80; second++) {
    const sample = second * 200;
    paintBeat(raw, sample, (second % 5 - 2) * 7);
    rows.push(record(sample));
  }
  return {raw, rows};
}
function qualityFixture(variation) {
  const raw = rawSource(12000), anchors = [200, 400, 600], bases = [-variation, 0, variation];
  anchors.forEach((sample, i) => {
    for (let offset = -60; offset < 140; offset++)
      for (let channel = 0; channel < 8; channel++) setFrame(raw, sample + offset, channel, bases[i]);
    for (let channel = 0; channel < 8; channel++) frameAdd(raw, sample, channel, 10000);
  });
  return {raw, rows: anchors.map(sample => record(sample))};
}
function derivativeFixture(overrides) {
  const raw = rawSource(12000), rows = [200, 400, 600].map(sample => record(sample));
  rows.forEach((row, representative) => {
    for (let channel = 0; channel < 8; channel++) {
      let value = 0;
      for (let offset = 0; offset < 140; offset++) {
        const replacement = overrides[representative]?.[offset];
        const derivative = replacement === undefined ? (offset === 0 ? 100 : 0) :
          Array.isArray(replacement) ? replacement[[1, 2, 6].indexOf(channel)] ?? 0 : replacement;
        value += derivative;
        setFrame(raw, row.sample_index + offset, channel, value);
      }
    }
  });
  return {raw, rows};
}
function fixtures() {
  const hand = handFixture(), dense = denseFixture(), scope = {
    case_id: CASE_ID, analysis_basis: 'pure-mathematical-cross-runtime-v1', analysis_revision: 0, beat_revision: 0,
  };
  const base = {start_sample: 0, end_sample: 12000, leads: LEADS, measurement_ms: 60, exclusions: [], basis: scope};
  const make = (name, source, changes = {}, inspect = null) => ({name, ...source, options: {...base, ...changes}, inspect});
  const zero = {raw: rawSource(12000), rows: [200, 400, 600].map(sample => record(sample))};
  const fallback = {raw: rawSource(12000), rows: [200, 400, 600].map(sample => record(sample))};
  for (const row of fallback.rows) for (let offset = 8; offset <= 32; offset++)
    for (let channel = 0; channel < 8; channel++) setFrame(fallback.raw, row.sample_index + offset, channel, 1000 * (1 + Math.floor((offset - 8) / 4)));
  const ratio = n => ({raw: rawSource(12000), rows: Array.from({length: 1000}, (_, i) => record(50 + i * 3, i < n ? 1 : 2))});
  const weighted = (value, {compact = false} = {}) => {
    assert.equal(value.counts.detected_count, 22); assert.equal(value.counts.used_count, 20);
    if (compact) assert.equal(Object.hasOwn(value, 'blocks'), false);
    else assert.deepEqual(value.blocks.slice(0, 2).map(block => [block.counts.used_count, block.j_offset_samples]), [[6, 8], [14, 8]]);
    LEAD_WEIGHTS.forEach((weight, i) => near(value.leads[i].mean_units, 24 * weight, 'closed-form weighted ' + value.leads[i].lead));
    assert.notEqual(value.leads[0].mean_units, 20, 'unequal populations cannot be averaged as two block means');
    assert.equal(value.leads[4].mean_units, 0, 'actual zero from derived aVL must remain zero');
  };
  return [
    make('weighted-all-20-observations-6-at-10-plus-14-at-30', hand, {}, weighted),
    make('J-only-point-0ms-same-full-source', hand, {measurement_ms: 0}),
    make('J-plus-80ms-same-full-source', hand, {measurement_ms: 80}),
    make('single-baseline-support-exclusion', hand, {exclusions: [mask(3561, 3562, 'one baseline support sample')]}, value => {
      assert.equal(value.counts.used_count, 19); assert.equal(value.counts.excluded_count, 3);
      near(value.leads[0].mean_units, 450 / 19, 'closed-form baseline support mean');
    }),
    make('single-ST-support-exclusion', hand, {exclusions: [mask(3618, 3619, 'one ST support sample')]}, value => {
      assert.equal(value.counts.used_count, 19); near(value.leads[0].mean_units, 450 / 19, 'closed-form ST support mean');
    }),
    make('known-missing-baseline-support', hand, {exclusions: [mask(3561, 3562, 'known baseline gap', {kind: 'missing'})]}, value => {
      assert.equal(value.counts.missing_count, 1); assert.equal(value.counts.reason_counts.explicit_missing_support, 1);
    }),
    make('known-missing-ST-support', hand, {exclusions: [mask(3618, 3619, 'known ST gap', {kind: 'missing'})]}, value => {
      assert.equal(value.counts.missing_count, 1); assert.equal(value.counts.reason_counts.explicit_missing_support, 1);
    }),
    make('known-missing-anchor', hand, {exclusions: [mask(3600, 3601, 'known missing frame', {kind: 'missing'})]}, value => {
      assert.equal(value.counts.missing_count, 1); near(value.coverage.source_coverage_s, 59.995, 'known missing source duration');
    }),
    make('mask-union-overlap-and-flags', dense, {exclusions: [mask(2000, 2400, 'AF candidate', {origin: 'rhythm_review'}),
      mask(2200, 2600, 'manual artifact'), mask(2400, 2800, 'known gap', {kind: 'missing'})]}, value => {
      assert.equal(value.coverage.explicit_excluded_s, 2); assert.equal(value.coverage.explicit_missing_s, 2);
      assert.equal(sum(value.mask_reason_counts.map(row => row.beat_count)), 9);
      assert.equal(value.counts.excluded_count + value.counts.missing_count, 5);
      assert.equal(value.coverage.source_coverage_s, 58); assert.equal(value.coverage.engineering_eligible_block_coverage_s, 56);
    }),
    make('half-open-touch-removes-J-representative-only', dense, {exclusions: [mask(1977, 1978, 'between support samples')]}, value => {
      assert.equal(value.counts.used_count, 59); assert.equal(value.counts.excluded_count, 0);
      assert(!value.blocks[0].j_representative_samples.includes(2000));
    }),
    make('full-explicit-mask-null-is-not-zero', hand, {exclusions: [mask(0, 6400, 'mathematical AF mask')]}, value => {
      assert.equal(value.counts.used_count, 0); assert(value.leads.every(lead => lead.mean_units === null));
    }),
    make('zero-signal-low-J-confidence-still-eligible', zero, {}, value => {
      assert.equal(value.blocks[0].landmark_confidence, 0); assert.equal(value.blocks[0].eligible, true);
      assert.equal(value.blocks[0].j_offset_samples, 8); assert.equal(value.leads[1].mean_units, 0);
    }),
    make('empty-detected-population-remains-null', {...zero, rows: []}, {}, value => {
      assert.equal(value.counts.detected_count, 0); assert(value.leads.every(lead => lead.mean_units === null));
      assert.equal(value.coverage.used_anchor_span_s, null); assert.equal(value.coverage.max_used_anchor_gap_s, null);
    }),
    make('machine-J-fallback-is-18-samples', fallback, {}, value => {
      assert.equal(value.blocks[0].j_offset_samples, 18); assert.equal(value.blocks[0].eligible, true);
      assert.equal(value.leads[1].mean_units, 6000);
    }),
    make('J-energy-flattens-all-nine-beat-lead-observations', derivativeFixture([
      {8: [0, 0, 1000]}, {8: [10, 10, 1000]}, {8: [20, 20, 20]},
    ]), {}, value => {assert.equal(value.blocks[0].j_offset_samples, 9);}),
    make('J-equal-energy-peaks-use-first-peak', derivativeFixture([{20: 100}, {20: 100}, {20: 100}]), {}, value => {
      assert.equal(value.blocks[0].j_offset_samples, 8);
    }),
    make('J-quiet-threshold-is-inclusive-at-12', derivativeFixture([{8: 12}, {8: 12}, {8: 12}]), {}, value => {
      assert.equal(value.blocks[0].j_offset_samples, 8);
    }),
    make('J-energy-13-is-above-quiet-threshold-12', derivativeFixture([{8: 13}, {8: 13}, {8: 13}]), {}, value => {
      assert.equal(value.blocks[0].j_offset_samples, 9);
    }),
    make('normal-ratio-exact-0.35-is-eligible', ratio(350), {}, value => {
      assert.equal(value.blocks[0].normal_beat_ratio, 0.35); assert.equal(value.blocks[0].eligible, true); assert.equal(value.counts.used_count, 350);
    }),
    make('normal-ratio-0.349-is-ineligible', ratio(349), {}, value => {
      assert.equal(value.blocks[0].normal_beat_ratio, 0.349); assert.equal(value.blocks[0].eligible, false); assert.equal(value.counts.used_count, 0);
    }),
    make('quality-exact-0.42-is-eligible', qualityFixture(5800), {}, value => {
      assert.equal(value.blocks[0].quality_score, 0.42); assert.equal(value.blocks[0].eligible, true); assert.equal(value.counts.used_count, 3);
    }),
    make('quality-0.4199-rounded-0.42-is-ineligible', qualityFixture(5801), {}, value => {
      assert.equal(value.blocks[0].quality_score, 0.42); assert.equal(value.blocks[0].eligible, false); assert.equal(value.counts.used_count, 0);
      assert(value.leads.every(lead => lead.mean_units === null));
    }),
    make('range-anchor-half-open-fixed-grid-representatives', dense, {start_sample: 201, end_sample: 12201}, value => {
      assert.equal(value.counts.detected_count, 60); assert.equal(value.blocks[0].start_sample, 0);
      assert.equal(value.blocks[0].j_representative_samples[0], 200);
    }),
    make('source-tail-guard-counted-missing-not-clipped', {raw: rawSource(12000), rows: [200, 400, 600, 11950].map(sample => record(sample))}, {}, value => {
      assert.equal(value.counts.missing_count, 1); assert.equal(value.counts.reason_counts.source_edge_guard_unavailable, 1);
    }),
    make('only-two-J-representatives-counted-missing', {raw: rawSource(12000), rows: [200, 400].map(sample => record(sample))}, {}, value => {
      assert.equal(value.counts.missing_count, 2); assert.equal(value.counts.reason_counts.j_unavailable, 2);
    }),
    make('representative-selection-matches-Python-half-ties-to-even', {raw: rawSource(12000),
      rows: Array.from({length: 16}, (_, i) => record(200 + i * 100))}, {}, value => {
      assert.deepEqual(value.blocks[0].j_representative_samples, [200, 400, 700, 1000, 1200, 1400, 1700]);
    }),
    make('11999-sample-range-is-invalid', hand, {end_sample: 11999}, null),
    make('out-of-source-range-is-invalid', hand, {end_sample: 16001}, null),
  ];
}
function sum(values) {return values.reduce((total, value) => total + value, 0);}
function nativeOracle(cases) {
  const sources = Object.fromEntries(cases.map(value => [sha(value.raw), value.raw.toString('base64')]));
  const request = {sources, cases: cases.map(value => ({name: value.name, source: sha(value.raw), rows: value.rows, options: value.options}))};
  const script = `import base64,json,sys\nfrom ecg_core.stt_range import calculate_stt_range,STTRangeError\nrequest=json.load(sys.stdin)\nsources={key:base64.b64decode(value) for key,value in request['sources'].items()}\nresults=[]\nfor item in request['cases']:\n try:\n  result=calculate_stt_range(sources[item['source']],item['rows'],**item['options'],source_digest=item['source'])\n  results.append({'name':item['name'],'result':result})\n except STTRangeError as error:\n  results.append({'name':item['name'],'error':str(error),'exception':type(error).__name__})\nprint(json.dumps(results,ensure_ascii=False,allow_nan=False))\n`;
  const run = spawnSync(python, ['-c', script], {cwd: root, input: JSON.stringify(request), encoding: 'utf8', timeout: 30000,
    maxBuffer: 32 * 1024 * 1024, env: {...process.env, PYTHONPATH: root, PYTHONDONTWRITEBYTECODE: '1'}});
  assert.equal(run.error, undefined, String(run.error)); assert.equal(run.status, 0, run.stderr);
  report.oracle = {...report.oracle, nativeModuleSha256: sha(fs.readFileSync(path.join(root, 'ecg_core/stt_range.py'))),
    mathematicalCases: (report.oracle.mathematicalCases || 0) + cases.length,
    rawSourceSha256: [...new Set([...(report.oracle.rawSourceSha256 || []), ...Object.keys(sources)])], sameBytes: true};
  return JSON.parse(run.stdout);
}
function mathCase(source = handFixture()) {
  return {software_release_id: 'original-mathematical-feedback-test', case_id: CASE_ID, display_case_id: 'M01', active: true, phi_masked: true,
    metadata: {name: 'Mathematical software test', start_iso: '2026-01-02T08:00:00', start_time: '2026-01-02 08:00:00'},
    technical: {duration_seconds_raw: source.raw.length / 16 / 200, sample_rate_hz: 200}, summary: {total_beats: source.rows.length},
    source_report_summary: {}, conclusion: 'Mathematics only; no clinical diagnosis.',
    beats: source.rows.map(row => ({...row, time_s: row.sample_index / 200, label: ({1: 'N', 2: 'S', 3: 'V', 34: 'X'})[row.group] || 'OTHER', hr: row.rr_ms ? 60000 / row.rr_ms : null})),
    integrity: {mathematical_fixture: true, raw_patient_data: false},
    simulation_profile: {real_patient_inputs_read: false, source_waveform_copied: false, rhythm_candidate_windows_s: []}};
}
function storage(values = new Map()) {
  let failNext = false, writes = 0;
  return {values, get writes() {return writes;}, getItem: key => values.get(key) ?? null,
    setItem(key, value) {if (failNext) {failNext = false; throw new DOMException('Mathematical quota failure', 'QuotaExceededError');} writes++; values.set(key, String(value));},
    removeItem(key) {values.delete(key);}, failNextWrite() {failNext = true;}};
}
function harness(source = handFixture(), values) {
  const input = mathCase(source), localStorage = storage(values), nativeRequests = [], apiRequests = [];
  let holdWaveform = false, releaseWaveform = null;
  let holdDigest = false, releaseDigest = null;
  const builtin = JSON.parse(fs.readFileSync(path.join(root, 'static/terminology/builtin-draft-v1.json'), 'utf8'));
  const nativeFetch = async raw => {
    const url = new URL(typeof raw === 'string' ? raw : raw.url, 'http://original-math.invalid/');
    nativeRequests.push(url.pathname); report.nativeAssetRequests.push(url.pathname);
    if (url.pathname.includes('builtin-draft-v1.json')) return new Response(JSON.stringify(builtin), {status: 200});
    if (url.pathname.endsWith('/waveform.bin')) {
      if (holdWaveform) {holdWaveform = false; await new Promise(resolve => {releaseWaveform = resolve;});}
      return new Response(new Uint8Array(source.raw), {status: 200});
    }
    report.externalNetworkRequests.push(url.href); throw Error('Unexpected network request: ' + url.href);
  };
  let lockTail = Promise.resolve();
  const actualCrypto = {randomUUID: () => crypto.webcrypto.randomUUID(), getRandomValues: value => crypto.webcrypto.getRandomValues(value),
    subtle: {digest: async (...args) => {
      if (holdDigest) {holdDigest = false; await new Promise(resolve => {releaseDigest = resolve;});}
      return crypto.webcrypto.subtle.digest(...args);
    }}};
  const context = vm.createContext({console, Response, Request, Headers, URL, URLSearchParams, AbortController, DOMException,
    TextEncoder, TextDecoder, ArrayBuffer, DataView, Uint8Array, Int16Array, Float64Array, crypto: actualCrypto,
    localStorage, location: {href: 'http://original-math.invalid/'}, setTimeout, clearTimeout,
    navigator: {locks: {request: (_key, _options, run) => {const value = lockTail.then(run, run); lockTail = value.catch(() => {}); return value;}}}});
  context.window = context; context.self = context; context.fetch = nativeFetch;
  context.__CARDIOINSIGHT_MATHEMATICAL_CASE__ = clone(input);
  const scripts = ['static/js/rr-quality.js', 'static/js/report-engine.js', 'static/js/overview-engine.js',
    'static/js/clinical-analysis.js', 'static/js/hrv-analysis.js', 'static/js/beat-engine.js',
    'demo/static/js/stt-range-math.js', 'demo/static/js/demo-review-api.js', 'demo/static/js/demo-api.js'];
  for (const relative of scripts) vm.runInContext(fs.readFileSync(path.join(root, relative), 'utf8'), context, {filename: relative});
  const call = async (route, method = 'GET', body, expected = 200) => {
    const actualRoute = route.startsWith('/api/') ? route : `/api/cases/${CASE_ID}/${route}`;
    apiRequests.push({route: actualRoute, method});
    const response = await context.fetch(actualRoute,
      {method, ...(body === undefined ? {} : {body: JSON.stringify(body)})});
    const value = await response.json();
    assert((Array.isArray(expected) ? expected : [expected]).includes(response.status), `${method} ${route}: status=${response.status}, ${JSON.stringify(value)}`);
    return clone(value);
  };
  return {context, source, input, localStorage, nativeRequests, apiRequests, call,
    holdWaveform() {holdWaveform = true;}, releaseWaveform() {assert(releaseWaveform); releaseWaveform(); releaseWaveform = null;},
    async waitWaveformHeld() {for (let i = 0; i < 100 && !releaseWaveform; i++) await new Promise(resolve => setTimeout(resolve, 1)); assert(releaseWaveform, 'actual waveform asset fetch was not held');},
    holdNextDigest() {holdDigest = true;}, releaseDigest() {assert(releaseDigest); releaseDigest(); releaseDigest = null;},
    async waitDigestHeld() {for (let i = 0; i < 100 && !releaseDigest; i++) await new Promise(resolve => setTimeout(resolve, 1)); assert(releaseDigest, 'actual WebCrypto digest was not held');}};
}
function scope(value, fields = SCOPE_FIELDS) {return Object.fromEntries(fields.map(field => {assert(Object.hasOwn(value, field), 'missing scope field ' + field); return [field, value[field]];}));}
function afEpisode(status = 'pending', extra = {}) {return {id: 'math-af-episode-1', start_s: 10, end_s: 20, kind: 'AF', status, source: 'manual', note: 'Original mathematical episode', ...extra};}
function afPayload(current, document, operation = 'save') {
  return {...scope(current), revision: current.revision, confirmed: true, operation, ...(document ? {document} : {})};
}
function sortedJSON(value) {
  const ordered = item => Array.isArray(item) ? item.map(ordered) : item && typeof item === 'object' ?
    Object.fromEntries(Object.keys(item).sort().map(key => [key, ordered(item[key])])) : item;
  return JSON.stringify(ordered(value));
}
function receiptDigest(statistics) {const value = clone(statistics); delete value.save_receipt; return sha(Buffer.from(sortedJSON(value), 'utf8'));}
function verifyReceipt(statistics) {
  assert.equal(Object.hasOwn(statistics, 'blocks'), false, 'saveable API statistics are compact');
  assert.deepEqual(Object.keys(statistics.save_receipt).sort(), ['digest', 'kind']);
  assert.equal(statistics.save_receipt.kind, 'browser-math-content-digest-v1');
  assert.match(statistics.save_receipt.digest, /^[a-f0-9]{64}$/);
  assert.equal(statistics.save_receipt.digest, receiptDigest(statistics), 'independent Node SHA256 covers the whole API result except receipt');
  assert.notEqual(statistics.save_receipt.kind, 'native-stt-range-hmac-v1', 'browser content digest is not a private native attestation');
}
async function rangeForSave(h) {
  const basis = scope(await h.call('analysis-basis'));
  const value = await h.call('stt-range', 'POST', {scope: {...basis, client_case_token: 9, workspace_epoch: 'math-mean-workspace'},
    start_sample: 0, end_sample: 12000, leads: ['I', 'II', 'aVL'], measurement_ms: 60});
  verifyReceipt(value);
  assert.deepEqual(value.leads.map(row => [row.lead, row.mean_units]), [['I', 24], ['II', 48], ['aVL', 0]]);
  assert.deepEqual(value.counts, {detected_count: 22, used_count: 20, excluded_count: 2, missing_count: 0, reason_counts: {rr_outside_legacy_bounds: 2}});
  return value;
}
function meanPayload(statistics) {
  return {sample_index: statistics.range.start_sample, lead: '全部', category: 'note', label: 'ST-T 数学范围复核',
    note: '医生原文保留；数学统计 I 24 u、II 48 u、aVL 0 u，不构成临床结论。',
    details: {kind: 'ST', status: 'pending', finding: '数学范围人工核对', end_sample: statistics.range.end_sample - 1,
      point_measurement_sample_index: 400, range_statistics: clone(statistics)}};
}
function scalarPaths(value, path = []) {
  if (Array.isArray(value)) return value.length ? value.flatMap((item, i) => scalarPaths(item, [...path, i])) : [path];
  if (value && typeof value === 'object') return Object.entries(value).flatMap(([key, item]) => scalarPaths(item, [...path, key]));
  return [path];
}
function alterAt(value, path) {
  let parent = value; for (const key of path.slice(0, -1)) parent = parent[key];
  const key = path.at(-1), current = parent[key];
  parent[key] = current === null ? 0 : Array.isArray(current) ? [mask(1, 2, 'tampered mathematical mask')] :
    typeof current === 'boolean' ? !current : typeof current === 'number' ? current + 1 :
      typeof current === 'string' && /^[a-f0-9]{64}$/.test(current) ? (current[0] === '0' ? '1' : '0') + current.slice(1) : String(current) + '-tampered';
}
async function seedDraft(h) {
  const value = await h.call('report');
  return h.call('report', 'PUT', {status: 'draft', expected_version: value.version, expected_review_revision: value.review_revision,
    conclusion: '原有医生草稿保持；数学测试。', composition: {...value.composition, include_hrv: false, included_pages: ['summary'],
      selected_events: [], diagnosis_blocks: [], category_reviews: {}}});
}
async function check(name, run) {
  try {const detail = await run(); report.checks.push({name, passed: true, ...(detail === undefined ? {} : {detail})}); console.log('PASS ' + name);}
  catch (error) {report.checks.push({name, passed: false, error: String(error), stack: error.stack}); throw error;}
  finally {fs.mkdirSync(evidenceRoot, {recursive: true}); fs.writeFileSync(path.join(evidenceRoot, 'results.json'), JSON.stringify(report, null, 2) + '\n');}
}

async function runMath() {
  report.scriptHashes = Object.fromEntries(['demo/static/js/stt-range-math.js', 'demo/static/js/demo-review-api.js', 'demo/static/js/demo-api.js']
    .map(relative => [relative, sha(fs.readFileSync(path.join(root, relative)))]));
  const cases = fixtures(), expected = nativeOracle(cases), direct = harness();
  assert.equal(typeof direct.context.ECGSTTRangeMath?.calculate, 'function', 'load the actual pure-memory Demo ST calculator');
  for (const [i, fixture] of cases.entries()) await check('native-cross-runtime:' + fixture.name, async () => {
    const before = sha(fixture.raw), bytes = Uint8Array.from(fixture.raw).buffer;
    if (expected[i].error) await assert.rejects(Promise.resolve().then(() => direct.context.ECGSTTRangeMath.calculate(bytes, clone(fixture.rows), clone(fixture.options))));
    else {
      const actual = clone(await direct.context.ECGSTTRangeMath.calculate(bytes, clone(fixture.rows), clone(fixture.options)));
      const metrics = compareST(actual, expected[i].result, fixture.name); fixture.inspect?.(actual);
      assert(metrics.numericFieldComparisons > 0);
    }
    assert.equal(sha(fixture.raw), before, 'the raw source bytes remain unchanged');
    assert.equal(sha(Buffer.from(bytes)), before, 'the module cannot mutate its input raw buffer');
    return {rawSha256: before, detectedRows: fixture.rows.length, rejected: !!expected[i].error};
  });
  report.mathComparisonSummary = {
    comparedCases: report.crossRuntimeComparisons.length,
    numericFieldComparisons: sum(report.crossRuntimeComparisons.map(value => value.numericFieldComparisons)),
    maximumAbsoluteMeanErrorUnits: Math.max(...report.crossRuntimeComparisons.map(value => value.maximumAbsoluteMeanErrorUnits)),
    maximumAbsoluteJError: Math.max(...report.crossRuntimeComparisons.map(value => value.maximumAbsoluteJError)),
    maximumAbsoluteQualityError: Math.max(...report.crossRuntimeComparisons.map(value => value.maximumAbsoluteQualityError)),
    maximumAbsoluteCoverageError: Math.max(...report.crossRuntimeComparisons.map(value => value.maximumAbsoluteCoverageError)),
    methodProfileExact: true, scopeExact: true, countsExact: true, sampleSelectionAndJRepresentativesExact: true,
    absoluteMeanErrorGateUnits: 1e-6, gateIsClinicalTolerance: false,
  };
  return cases;
}
async function run() {
  const cases = await runMath();
  if (process.argv.includes('--math-only')) {
    report.completed = new Date().toISOString(); report.passed = true; report.adapterApiExecuted = false;
    fs.writeFileSync(path.join(evidenceRoot, 'results.json'), JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify(report.mathComparisonSummary)); return;
  }
  report.adapterApiExecuted = true;
  await check('ST fetch route uses actual full raw int16 source and exact four/six-field request scope', async () => {
    const h = harness(), basis4 = scope(await h.call('analysis-basis'));
    const persistedBefore = h.localStorage.getItem(STORE_KEY), writesBefore = h.localStorage.writes;
    const request = {...cases[0].options}; delete request.basis; delete request.exclusions;
    const four = await h.call('stt-range', 'POST', {scope: basis4, ...request});
    const fourExpected = nativeOracle([{...cases[0], options: {...cases[0].options, basis: basis4}}])[0].result;
    compareST(four, fourExpected, 'stt-fetch-four-scope', {compact: true}); cases[0].inspect(four, {compact: true}); verifyReceipt(four); assert.deepEqual(four.scope, basis4);
    const basis6 = scope(four.server_identity, SCOPE6_FIELDS);
    const six = await h.call('stt-range', 'POST', {scope: basis6, ...request});
    const sixExpected = nativeOracle([{...cases[0], options: {...cases[0].options, basis: basis6}}])[0].result;
    compareST(six, sixExpected, 'stt-fetch-six-scope', {compact: true}); verifyReceipt(six); assert.deepEqual(six.scope, basis6);
    const decoratedScope = {...basis6, caseToken: 7, client_case_token: 3, workspace_epoch: 'original-math-workspace'};
    const decorated = await h.call('stt-range', 'POST', {scope: decoratedScope, ...request});
    const decoratedExpected = nativeOracle([{...cases[0], options: {...cases[0].options, basis: decoratedScope}}])[0].result;
    compareST(decorated, decoratedExpected, 'stt-fetch-client-workspace-tokens', {compact: true}); verifyReceipt(decorated); assert.deepEqual(decorated.scope, decoratedScope);
    assert.equal(h.nativeRequests.filter(name => name.endsWith('/waveform.bin')).length, 1, 'same complete mathematical asset is reused');
    await h.call('stt-range', 'POST', {scope: basis4, ...request, end_sample: 11999}, 400);
    await h.call('stt-range', 'POST', {scope: basis4, ...request, exclusions: []}, 400);
    for (const field of ['source_digest', 'data_version'])
      await h.call('stt-range', 'POST', {scope: {...basis6, [field]: basis6[field] + '-stale'}, ...request}, 409);
    for (const field of ['analysis_revision', 'beat_revision']) for (const invalid of [String(basis4[field]), true, false, 0.5, -1])
      await h.call('stt-range', 'POST', {scope: {...basis4, [field]: invalid}, ...request}, 400);
    assert.equal(h.localStorage.getItem(STORE_KEY), persistedBefore); assert.equal(h.localStorage.writes, writesBefore, 'ST calculation is read-only');
    return {scopeFieldCounts: [4, 6, 9], clientTokensEchoedExactly: true, strictTypedRevisionRejections: 10,
      rejectedRevisionTypes: ['numeric-string', 'boolean', 'fraction', 'negative'], weightedMeanI: four.leads[0].mean_units, rawSourceSha256: sha(h.source.raw)};
  });
  for (const kind of ['AF', 'AFL']) for (const status of ['pending', 'confirmed', 'excluded'])
    await check(`ST saved-${kind}-${status}-authoritative-mask-matches-native-annotations`, async () => {
      const h = harness(), current = await h.call('rhythm-review');
      const document = {episodes: [afEpisode(status, {kind})], bookmarks: {}};
      const saved = await h.call('rhythm-review', 'PUT', afPayload(current, document)), currentScope = scope(saved);
      const stable = h.localStorage.getItem(STORE_KEY), writes = h.localStorage.writes;
      const options = {...cases[0].options, basis: currentScope,
        exclusions: status === 'excluded' ? [] : [mask(2000, 4000, 'rhythm_' + kind, {origin: 'stored_annotation', review_status: status})]};
      const expectedValue = nativeOracle([{...cases[0], options}])[0].result;
      const actual = await h.call('stt-range', 'POST', {scope: currentScope, start_sample: 0, end_sample: 12000, leads: LEADS, measurement_ms: 60});
      compareST(actual, expectedValue, `saved-${kind}-${status}`, {compact: true}); verifyReceipt(actual);
      assert.equal(h.localStorage.getItem(STORE_KEY), stable); assert.equal(h.localStorage.writes, writes);
      assert.equal((await h.call('rhythm-review')).document.episodes[0].status, status, 'ST calculation cannot promote or modify an AF review state');
      if (status === 'excluded') assert.deepEqual(actual.exclusions.intervals, []);
      else assert(actual.mask_reason_counts.some(value => value.reason === 'rhythm_' + kind && value.review_status === status));
      return {kind, status, nativeCounts: expectedValue.counts, meanI: actual.leads[0].mean_units};
    });
  await check('AF GET is read-only, save preserves pending status and reload preserves exact full identity/document', async () => {
    const h = harness(), before = h.localStorage.getItem(STORE_KEY), writes = h.localStorage.writes;
    const current = await h.call('rhythm-review'); scope(current);
    assert.equal(h.localStorage.getItem(STORE_KEY), before); assert.equal(h.localStorage.writes, writes, 'AF GET cannot persist');
    const document = {episodes: [afEpisode()], bookmarks: {fastest: 12.5}};
    const saved = await h.call('rhythm-review', 'PUT', afPayload(current, document));
    assert.deepEqual(saved.document, document); assert.equal(saved.document.episodes[0].status, 'pending');
    assert.equal(saved.revision, current.revision + 1); assert.equal(saved.analysis_revision, current.analysis_revision + 1);
    assert.equal(saved.beat_revision, current.beat_revision);
    const reopened = harness(h.source, h.localStorage.values), reloaded = await reopened.call('rhythm-review');
    assert.deepEqual(reloaded.document, document); assert.deepEqual(scope(reloaded), scope(saved)); assert.equal(reloaded.revision, saved.revision);
    assert.deepEqual(scope(reloaded, SCOPE6_FIELDS), scope(saved, SCOPE6_FIELDS));
    return {revision: saved.revision, analysisRevision: saved.analysis_revision, status: saved.document.episodes[0].status};
  });
  await check('AF stale/malformed/cross-case full-scope requests never save', async () => {
    const h = harness(), current = await h.call('rhythm-review'), document = {episodes: [afEpisode()], bookmarks: {}};
    const saved = await h.call('rhythm-review', 'PUT', afPayload(current, document)), stable = h.localStorage.getItem(STORE_KEY);
    await h.call('rhythm-review', 'PUT', afPayload(current, {episodes: [], bookmarks: {}}), 409);
    for (const confirmed of [false, null, 'true'])
      await h.call('rhythm-review', 'PUT', {...afPayload(saved, document), confirmed}, 400);
    // The native rhythm endpoint permits optional case/global basis fields for
    // existing clients, but requires valid beat and document revisions.
    for (const field of ['beat_revision', 'revision']) {
      const absent = afPayload(saved, document); delete absent[field];
      await h.call('rhythm-review', 'PUT', absent, 400);
    }
    for (const field of SCOPE_FIELDS) {
      const stale = {...afPayload(saved, document), [field]: typeof saved[field] === 'number' ? saved[field] + 1 : saved[field] + '-other'};
      await h.call('rhythm-review', 'PUT', stale, 409);
    }
    for (const field of ['source_digest', 'data_version'])
      await h.call('rhythm-review', 'PUT', {...afPayload(saved, document), ...scope(saved, SCOPE6_FIELDS), [field]: saved[field] + '-stale'}, 409);
    await h.call('rhythm-review', 'PUT', {...afPayload(saved, document), revision: current.revision}, 409);
    assert.equal(h.localStorage.getItem(STORE_KEY), stable);
    assert.deepEqual((await h.call('rhythm-review')).document, document);
  });
  await check('AF unknown write response reconciles stable episode UUID with a fresh read only', async () => {
    const h = harness(), current = await h.call('rhythm-review');
    const episode = afEpisode('pending', {id: '2f9f65ce-3053-4bba-9c07-c565ea75c371'}), document = {episodes: [episode], bookmarks: {}};
    const request = afPayload(current, document);
    // The adapter really commits. A lost caller acknowledgement must be resolved
    // by observing this stable identity, never by silently repeating the PUT.
    await h.call('rhythm-review', 'PUT', request);
    const stable = h.localStorage.getItem(STORE_KEY), writes = h.localStorage.writes;
    const query = new URLSearchParams({case_id: current.case_id, analysis_basis: current.analysis_basis, beat_revision: current.beat_revision});
    const fresh = await h.call('rhythm-review?' + query);
    assert.deepEqual(fresh.document.episodes.find(value => value.id === episode.id), episode);
    assert.equal(fresh.analysis_revision, current.analysis_revision + 1);
    assert.equal(h.localStorage.getItem(STORE_KEY), stable); assert.equal(h.localStorage.writes, writes, 'reconciliation is a GET without another saved mutation');
    await h.call('rhythm-review', 'PUT', request, 409);
    assert.equal(h.localStorage.getItem(STORE_KEY), stable); assert.equal(h.localStorage.writes, writes);
  });
  await check('AF quota failure rolls back document/global revision and undo/redo survives reload', async () => {
    const h = harness(), initial = await h.call('rhythm-review'), first = {episodes: [afEpisode()], bookmarks: {}};
    const saved = await h.call('rhythm-review', 'PUT', afPayload(initial, first)), stable = h.localStorage.getItem(STORE_KEY);
    h.localStorage.failNextWrite();
    const problem = await h.call('rhythm-review', 'PUT', afPayload(saved, {episodes: [afEpisode('confirmed')], bookmarks: {}}), [400, 503]);
    assert.match(problem.error, /存储|保存|space|storage/i); assert.equal(h.localStorage.getItem(STORE_KEY), stable);
    const afterFailure = await h.call('rhythm-review'); assert.deepEqual(scope(afterFailure), scope(saved)); assert.equal(afterFailure.revision, saved.revision);
    const second = await h.call('rhythm-review', 'PUT', afPayload(afterFailure, {episodes: [afEpisode('confirmed')], bookmarks: {}}));
    const undone = await h.call('rhythm-review', 'PUT', afPayload(second, null, 'undo'));
    assert.deepEqual(undone.document, first); assert.equal(undone.analysis_revision, second.analysis_revision + 1); assert.equal(undone.revision, second.revision + 1);
    const reopened = harness(h.source, h.localStorage.values), undoReload = await reopened.call('rhythm-review');
    assert.deepEqual(undoReload.document, first); assert.equal(undoReload.can_redo, true);
    const redone = await reopened.call('rhythm-review', 'PUT', afPayload(undoReload, null, 'redo'));
    assert.equal(redone.document.episodes[0].status, 'confirmed'); assert.equal(redone.analysis_revision, undone.analysis_revision + 1);
  });
  await check('unknown case UUID and wrong method cannot fabricate an AF workspace', async () => {
    const h = harness(), before = h.localStorage.getItem(STORE_KEY);
    await h.call('/api/cases/00000000-0000-4000-8000-000000000000/rhythm-review', 'GET', undefined, 404);
    await h.call('rhythm-review', 'POST', {}, 405);
    assert.equal(h.localStorage.getItem(STORE_KEY), before);
  });
  await check('ST stale scope rejects before read and a changed persistent scope during raw read rejects late results', async () => {
    const h = harness(), basis = scope(await h.call('analysis-basis')), request = {scope: basis, start_sample: 0, end_sample: 12000, leads: ['II'], measurement_ms: 60};
    await h.call('stt-range', 'POST', {...request, scope: {...basis, analysis_revision: basis.analysis_revision + 1}}, 409);
    assert.equal(h.nativeRequests.filter(name => name.endsWith('/waveform.bin')).length, 0, 'stale scope must reject before waveform I/O');
    h.holdWaveform(); const pending = h.call('stt-range', 'POST', request, 409); await h.waitWaveformHeld();
    const otherTab = harness(h.source, h.localStorage.values), current = await otherTab.call('rhythm-review');
    await otherTab.call('rhythm-review', 'PUT', afPayload(current, {episodes: [afEpisode()], bookmarks: {}}));
    h.releaseWaveform(); const rejected = await pending; assert.match(rejected.error, /变化|scope|依据|revision/i);
  });
  await check('mean-save:actual compact receipt/values survive annotation GET and browser reopen', async () => {
    const h = harness(), statistics = await rangeForSave(h), payload = meanPayload(statistics);
    const writes = h.localStorage.writes, before = scope(await h.call('analysis-basis'));
    const created = await h.call('annotations', 'POST', payload, 201);
    assert.equal(created.case_id, CASE_ID, 'mean POST row must identify its actual case');
    assert.deepEqual(created.details.range_statistics, statistics); assert.equal(created.note, payload.note);
    assert.equal(created.sample_index, 0); assert.equal(created.details.end_sample, 11999);
    assert.equal(created.details.point_measurement_sample_index, 400); assert.equal(created.details.status, 'pending');
    assert.equal(h.localStorage.writes, writes + 1, 'annotation/audit/revision use one storage commit');
    const items = (await h.call('annotations')).items;
    assert.equal(items.find(item => item.id === created.id).case_id, CASE_ID);
    assert.deepEqual(items.find(item => item.id === created.id).details.range_statistics, statistics);
    const reopened = harness(h.source, h.localStorage.values), item = (await reopened.call('annotations')).items.find(value => value.id === created.id);
    assert.equal(item.case_id, CASE_ID, 'saved case identity survives browser reopen');
    assert.deepEqual(item.details.range_statistics, statistics); verifyReceipt(item.details.range_statistics);
    assert.equal((await reopened.call('analysis-basis')).analysis_revision, before.analysis_revision + 1);
    const stored = h.localStorage.getItem(STORE_KEY);
    await h.call('annotations', 'POST', payload, 409);
    assert.equal(h.localStorage.getItem(STORE_KEY), stored, 'a previously saved receipt cannot silently submit again at an older revision');
    return {receiptKind: statistics.save_receipt.kind, independentDigest: receiptDigest(statistics), exactMeans: statistics.leads.map(row => [row.lead, row.mean_units])};
  });
  await check('mean-save:changing every compact scalar/empty-array field or removing receipt never writes', async () => {
    const h = harness(), statistics = await rangeForSave(h), payload = meanPayload(statistics);
    const stored = h.localStorage.getItem(STORE_KEY), writes = h.localStorage.writes, paths = scalarPaths(statistics);
    for (const path of paths) {
      const changed = clone(payload); alterAt(changed.details.range_statistics, path);
      await h.call('annotations', 'POST', changed, [400, 409]);
      assert.equal(h.localStorage.getItem(STORE_KEY), stored, 'tamper wrote ' + path.join('.'));
      assert.equal(h.localStorage.writes, writes, 'tamper persisted ' + path.join('.'));
    }
    const missing = clone(payload); delete missing.details.range_statistics.save_receipt;
    await h.call('annotations', 'POST', missing, 400);
    const expanded = clone(payload); expanded.details.range_statistics.blocks = [];
    await h.call('annotations', 'POST', expanded, 400);
    const wrongKind = clone(payload); wrongKind.details.range_statistics.save_receipt.kind = 'native-stt-range-hmac-v1';
    await h.call('annotations', 'POST', wrongKind, 400);
    assert.equal(h.localStorage.getItem(STORE_KEY), stored); assert.deepEqual((await h.call('annotations')).items, []);
    return {alteredCriticalLeafFields: paths.length, alteredFieldPaths: paths.map(path => path.join('.')), originalReceiptRetained: true};
  });
  await check('mean-save:actual four-field scope/range/inclusive-end/point boundaries are enforced before write', async () => {
    const h = harness(), statistics = await rangeForSave(h), payload = meanPayload(statistics), stored = h.localStorage.getItem(STORE_KEY);
    for (const field of SCOPE_FIELDS) {
      const changed = clone(payload), value = statistics.scope[field];
      changed.details.range_statistics.scope[field] = typeof value === 'number' ? value + 1 : value + '-other';
      changed.details.range_statistics.save_receipt.digest = receiptDigest(changed.details.range_statistics);
      await h.call('annotations', 'POST', changed, 409);
    }
    for (const changes of [value => value.sample_index++, value => value.details.end_sample++,
      value => {value.details.kind = 'AF';}, value => {value.details.status = 'unclassified';}]) {
      const changed = clone(payload); changes(changed); await h.call('annotations', 'POST', changed, 400);
    }
    for (const point of [-1, 400.5, true, 16000]) {
      const changed = clone(payload); changed.details.point_measurement_sample_index = point;
      await h.call('annotations', 'POST', changed, 400);
    }
    assert.equal(h.localStorage.getItem(STORE_KEY), stored);
    const valid = clone(payload); valid.details.point_measurement_sample_index = 15999;
    const created = await h.call('annotations', 'POST', valid, 201);
    assert.equal(created.details.point_measurement_sample_index, 15999, 'point validation uses full source bounds, without silently clamping to the mean range');
  });
  await check('mean-save:cross-window revision change during real asynchronous receipt digest rejects without writing', async () => {
    const h = harness(), statistics = await rangeForSave(h), payload = meanPayload(statistics);
    h.holdNextDigest(); const pending = h.call('annotations', 'POST', payload, 409); await h.waitDigestHeld();
    const other = harness(h.source, h.localStorage.values);
    const legacy = {sample_index: 500, lead: 'II', category: 'note', label: 'other-window original note', note: 'Separate saved mathematical annotation.'};
    const saved = await other.call('annotations', 'POST', legacy, 201), stored = other.localStorage.getItem(STORE_KEY);
    h.releaseDigest(); const problem = await pending; assert.match(problem.error, /变化|scope|依据|revision/i);
    assert.equal(h.localStorage.getItem(STORE_KEY), stored, 'failed old mean write must preserve the other window commit exactly');
    const items = (await h.call('annotations')).items; assert.equal(items.length, 1); assert.equal(items[0].id, saved.id);
    assert.equal(items[0].details?.range_statistics, undefined);
  });
  await check('mean-save:quota failure preserves complete saved/audit/report/version and the same receipt remains retryable', async () => {
    const h = harness(); await seedDraft(h);
    const statistics = await rangeForSave(h), payload = meanPayload(statistics);
    const stored = h.localStorage.getItem(STORE_KEY), writes = h.localStorage.writes;
    const oldAudit = await h.call('/api/audit'), oldReport = await h.call('report'), oldBasis = await h.call('analysis-basis');
    h.localStorage.failNextWrite();
    const failure = await h.call('annotations', 'POST', payload, [400, 503]); assert.match(failure.error, /存储|保存|space|storage/i);
    assert.equal(h.localStorage.getItem(STORE_KEY), stored); assert.equal(h.localStorage.writes, writes);
    assert.deepEqual(await h.call('/api/audit'), oldAudit); assert.deepEqual(await h.call('report'), oldReport);
    assert.deepEqual(await h.call('analysis-basis'), oldBasis); assert.deepEqual((await h.call('annotations')).items, []);
    const created = await h.call('annotations', 'POST', payload, 201); assert.deepEqual(created.details.range_statistics, statistics);
    assert.equal(h.localStorage.writes, writes + 1); assert.equal((await h.call('report')).version, oldReport.version + 1);
    assert.equal((await h.call('analysis-basis')).analysis_revision, oldBasis.analysis_revision + 1);
    assert.equal((await h.call('/api/audit')).items.length, oldAudit.items.length + 1);
  });
  await check('mean-save:legacy plain and manual ST annotations remain readable/reopenable without a receipt', async () => {
    const h = harness(), values = [
      {sample_index: 700, lead: 'II', category: 'note', label: '原有普通标注', note: 'Original free text.'},
      {sample_index: 1000, lead: 'V1', category: 'note', label: '原有人工 ST 点复核', note: 'Manual ISO/J statement preserved.',
        details: {kind: 'ST', status: 'pending', end_sample: 1200, finding: '无法判读'}},
    ];
    for (const value of values) {
      const created = await h.call('annotations', 'POST', value, 201);
      for (const [field, expected] of Object.entries(value)) assert.deepEqual(created[field], expected);
      assert.equal(created.details?.range_statistics, undefined);
    }
    const before = h.localStorage.getItem(STORE_KEY), writes = h.localStorage.writes, reopened = harness(h.source, h.localStorage.values);
    const items = (await reopened.call('annotations')).items; assert.equal(items.length, 2);
    for (const value of values) {
      const item = items.find(item => item.label === value.label);
      for (const [field, expected] of Object.entries(value)) assert.deepEqual(item[field], expected);
    }
    assert.equal(h.localStorage.getItem(STORE_KEY), before); assert.equal(h.localStorage.writes, writes);
  });
  await check('mean-UUID:valid submission identity persists exact computed values through GET and reopen', async () => {
    const h = harness(), statistics = await rangeForSave(h), payload = meanPayload(statistics);
    payload.details.submission_id = 'd704aa40-4f16-4db9-b6dd-7ec8edfb4028';
    const invalid = clone(payload); invalid.details.submission_id = 'not-a-valid-UUID';
    await h.call('annotations', 'POST', invalid, 400); assert.deepEqual((await h.call('annotations')).items, []);
    const created = await h.call('annotations', 'POST', payload, 201);
    assert.equal(created.case_id, CASE_ID);
    assert.equal(created.details.submission_id, payload.details.submission_id);
    assert.deepEqual(created.details.range_statistics, statistics);
    const reopened = harness(h.source, h.localStorage.values), found = (await reopened.call('annotations')).items.find(item => item.details?.submission_id === payload.details.submission_id);
    assert.equal(found.case_id, CASE_ID);
    assert.deepEqual(found, created); verifyReceipt(found.details.range_statistics);
  });
  await check('mean-UUID:lost response acknowledgement reuses saved identity despite old scope without another write', async () => {
    const h = harness(), statistics = await rangeForSave(h), payload = meanPayload(statistics);
    payload.details.submission_id = '82cba6a3-1dfd-4502-9c13-5f05d2f881a7';
    const created = await h.call('annotations', 'POST', payload, 201), persisted = h.localStorage.getItem(STORE_KEY), writes = h.localStorage.writes;
    const basis = await h.call('analysis-basis'), audit = await h.call('/api/audit');
    assert.equal(basis.analysis_revision, statistics.scope.analysis_revision + 1);
    const acknowledgement = await h.call('annotations', 'POST', clone(payload), 201);
    assert.equal(acknowledgement.case_id, CASE_ID);
    assert.deepEqual(acknowledgement, created); assert.equal(h.localStorage.getItem(STORE_KEY), persisted); assert.equal(h.localStorage.writes, writes);
    assert.deepEqual(await h.call('analysis-basis'), basis); assert.deepEqual(await h.call('/api/audit'), audit);
    const reopened = harness(h.source, h.localStorage.values), oldScopeAck = await reopened.call('annotations', 'POST', clone(payload), 201);
    assert.equal(oldScopeAck.case_id, CASE_ID);
    assert.deepEqual(oldScopeAck, created); assert.equal(reopened.localStorage.writes, 0);
    assert.equal(h.localStorage.getItem(STORE_KEY), persisted); assert.equal((await reopened.call('annotations')).items.length, 1);
    // Lose only the caller acknowledgement after a real 201/commit. Recover
    // through one authoritative GET, retaining strict case and UUID identity.
    const lost = harness(), lostStatistics = await rangeForSave(lost), lostPayload = meanPayload(lostStatistics);
    lostPayload.details.submission_id = 'ebd5bcb1-a907-4b0c-9c35-7787d146fb29';
    await assert.rejects(lost.call('annotations', 'POST', clone(lostPayload), 201).then(() => {
      throw Error('Injected lost acknowledgement after the real mean POST committed');
    }), /lost acknowledgement/);
    const afterLostCommit = lost.localStorage.getItem(STORE_KEY), afterLostWrites = lost.localStorage.writes, requestIndex = lost.apiRequests.length;
    const reconciled = (await lost.call('annotations')).items.filter(item => item.details?.submission_id === lostPayload.details.submission_id);
    assert.equal(reconciled.length, 1); assert.equal(reconciled[0].case_id, CASE_ID);
    for (const [field, expected] of Object.entries(lostPayload)) assert.deepEqual(reconciled[0][field], expected);
    assert.deepEqual(lost.apiRequests.slice(requestIndex), [{route: `/api/cases/${CASE_ID}/annotations`, method: 'GET'}]);
    assert.equal(lost.apiRequests.filter(value => value.route === `/api/cases/${CASE_ID}/annotations` && value.method === 'POST').length, 1);
    assert.equal(lost.localStorage.getItem(STORE_KEY), afterLostCommit); assert.equal(lost.localStorage.writes, afterLostWrites);
    // The real digest awaits interleave two actual requests. Disable Web Locks
    // in this context to exercise the adapter's own saved-identity reconciliation.
    const concurrent = harness(); concurrent.context.navigator = {};
    const concurrentStatistics = await rangeForSave(concurrent), concurrentPayload = meanPayload(concurrentStatistics);
    concurrentPayload.details.submission_id = 'a7a621fa-f644-4c5d-b904-3f7707da904e';
    const beforeBasis = await concurrent.call('analysis-basis'), beforeAudit = await concurrent.call('/api/audit'), beforeWrites = concurrent.localStorage.writes;
    const responses = await Promise.all([
      concurrent.call('annotations', 'POST', clone(concurrentPayload), 201),
      concurrent.call('annotations', 'POST', clone(concurrentPayload), 201),
    ]);
    assert.deepEqual(responses[0], responses[1]);
    assert.equal(responses[0].case_id, CASE_ID);
    assert.equal(concurrent.localStorage.writes, beforeWrites + 1, 'concurrent exact intent must commit once');
    assert.deepEqual((await concurrent.call('annotations')).items, [responses[0]]);
    assert.equal((await concurrent.call('/api/audit')).items.length, beforeAudit.items.length + 1);
    assert.equal((await concurrent.call('analysis-basis')).analysis_revision, beforeBasis.analysis_revision + 1);
    await concurrent.call('beat-editor', 'PUT', {operation: 'relabel', revision: 0, confirmed: true,
      selection: {samples: [800]}, class_code: 'V'});
    const afterBeat = await concurrent.call('analysis-basis'), persistedAfterBeat = concurrent.localStorage.getItem(STORE_KEY), writesAfterBeat = concurrent.localStorage.writes;
    assert.equal(afterBeat.beat_revision, concurrentStatistics.scope.beat_revision + 1);
    await concurrent.call('annotations', 'POST', clone(concurrentPayload), 409);
    assert.equal(concurrent.localStorage.getItem(STORE_KEY), persistedAfterBeat); assert.equal(concurrent.localStorage.writes, writesAfterBeat);
    assert.deepEqual((await concurrent.call('annotations')).items, [responses[0]]);
    return {concurrentRealPosts: 2, concurrentAcknowledgements: 2, committedAnnotations: 1,
      storageCommitCount: 1, auditIncrement: 1, globalRevisionIncrement: 1, changedBeatAcknowledgementRejected: true,
      lostResponseCoordinationOnlyGET: true, lostResponseAnnotationPOSTs: 1, lostResponseSavedCaseId: CASE_ID};
  });
  await check('mean-UUID:reusing one saved identity for a different range/mean/note/status returns conflict', async () => {
    const h = harness(), statistics = await rangeForSave(h), payload = meanPayload(statistics);
    payload.details.submission_id = '8a7cef98-c2d6-40f7-a40e-4ba58ac0e506';
    const created = await h.call('annotations', 'POST', payload, 201), persisted = h.localStorage.getItem(STORE_KEY), writes = h.localStorage.writes;
    const mutations = {
      range: value => {value.sample_index = 200; value.details.end_sample = 12199; Object.assign(value.details.range_statistics.range,
        {start_sample: 200, end_sample: 12200, start_s: 1, end_s: 61, duration_s: 60});},
      mean: value => {value.details.range_statistics.leads[0].mean_units = 25;},
      note: value => {value.note += ' Different physician intent.';},
      status: value => {value.details.status = 'confirmed';},
    };
    for (const [name, change] of Object.entries(mutations)) {
      const changed = clone(payload); change(changed); await h.call('annotations', 'POST', changed, 409);
      assert.equal(h.localStorage.getItem(STORE_KEY), persisted, name + ' conflict cannot write'); assert.equal(h.localStorage.writes, writes);
    }
    assert.deepEqual((await h.call('annotations')).items, [created]);
  });
  await check('mean-UUID:quota failure leaves submission identity uncommitted and exact same intent retries once', async () => {
    const h = harness(); await seedDraft(h);
    const statistics = await rangeForSave(h), payload = meanPayload(statistics);
    payload.details.submission_id = 'b31b7ee2-17ce-4e59-baa4-6f163df80d5a';
    const persisted = h.localStorage.getItem(STORE_KEY), writes = h.localStorage.writes, audit = await h.call('/api/audit'), basis = await h.call('analysis-basis'), oldReport = await h.call('report');
    h.localStorage.failNextWrite(); await h.call('annotations', 'POST', payload, [400, 503]);
    assert.equal(h.localStorage.getItem(STORE_KEY), persisted); assert.equal(h.localStorage.writes, writes);
    assert.deepEqual(await h.call('/api/audit'), audit); assert.deepEqual(await h.call('analysis-basis'), basis); assert.deepEqual(await h.call('report'), oldReport);
    assert.deepEqual((await h.call('annotations')).items, []);
    const created = await h.call('annotations', 'POST', clone(payload), 201);
    assert.equal(created.details.submission_id, payload.details.submission_id); assert.equal(h.localStorage.writes, writes + 1);
    assert.equal((await h.call('/api/audit')).items.length, audit.items.length + 1);
    assert.equal((await h.call('analysis-basis')).analysis_revision, basis.analysis_revision + 1);
    assert.equal((await h.call('report')).version, oldReport.version + 1);
    const afterRetry = h.localStorage.getItem(STORE_KEY);
    assert.deepEqual(await h.call('annotations', 'POST', clone(payload), 201), created);
    assert.equal(h.localStorage.getItem(STORE_KEY), afterRetry); assert.equal(h.localStorage.writes, writes + 1);
  });
  await check('mean-UUID:unrelated actual review revision rejects early and async existing acknowledgements while preserving saved work', async () => {
    const h = harness(); await seedDraft(h);
    const statistics = await rangeForSave(h), payload = meanPayload(statistics);
    payload.details.submission_id = 'bde563b4-4f2e-4a13-8a0a-43314f49caed';
    const created = await h.call('annotations', 'POST', payload, 201), workflow = await h.call('review-workflow');
    assert.equal(workflow.revision, statistics.scope.analysis_revision + 1);
    await h.call('review-workflow', 'PUT', {step: 'edit', confirmed: true, revision: workflow.revision, note: 'Independent actual review after the mean save.'});
    const reviewed = await h.call('review-workflow'); assert.equal(reviewed.revision, statistics.scope.analysis_revision + 2);
    const persisted = h.localStorage.getItem(STORE_KEY), writes = h.localStorage.writes, audit = await h.call('/api/audit'), oldReport = await h.call('report');
    await h.call('annotations', 'POST', clone(payload), 409);
    assert.equal(h.localStorage.getItem(STORE_KEY), persisted); assert.equal(h.localStorage.writes, writes);
    assert.deepEqual((await h.call('annotations')).items, [created]); assert.deepEqual(await h.call('/api/audit'), audit);
    assert.deepEqual(await h.call('review-workflow'), reviewed); assert.deepEqual(await h.call('report'), oldReport);

    // A previously uncommitted request starts receipt validation. Another real
    // window saves that exact UUID, then completes an unrelated review before
    // validation resumes. The fresh existing lookup must apply the same guard.
    const asynchronous = harness(), asynchronousStatistics = await rangeForSave(asynchronous), asynchronousPayload = meanPayload(asynchronousStatistics);
    asynchronousPayload.details.submission_id = '5ce47380-0d69-44e4-bf8b-2122a6bf6b53';
    asynchronous.holdNextDigest(); const pending = asynchronous.call('annotations', 'POST', clone(asynchronousPayload), 409); await asynchronous.waitDigestHeld();
    const other = harness(asynchronous.source, asynchronous.localStorage.values);
    const asynchronouslyCreated = await other.call('annotations', 'POST', clone(asynchronousPayload), 201), otherWorkflow = await other.call('review-workflow');
    await other.call('review-workflow', 'PUT', {step: 'edit', confirmed: true, revision: otherWorkflow.revision, note: 'Actual unrelated review while the receipt digest waits.'});
    const asyncWorkflow = await other.call('review-workflow'); assert.equal(asyncWorkflow.revision, asynchronousStatistics.scope.analysis_revision + 2);
    const asyncPersisted = other.localStorage.getItem(STORE_KEY), asyncAudit = await other.call('/api/audit');
    asynchronous.releaseDigest(); await pending;
    assert.equal(asynchronous.localStorage.getItem(STORE_KEY), asyncPersisted); assert.equal(asynchronous.localStorage.writes, 0);
    assert.deepEqual((await asynchronous.call('annotations')).items, [asynchronouslyCreated]);
    assert.deepEqual(await asynchronous.call('/api/audit'), asyncAudit); assert.deepEqual(await asynchronous.call('review-workflow'), asyncWorkflow);

    return {ownSaveRevisionAdvance: 1, unrelatedReviewTotalAdvance: 2, earlyExistingStatus: 409,
      asynchronousFreshExistingStatus: 409, rejectedAcknowledgementWrites: 0, originalDocumentPreserved: true};
  });
  assert.deepEqual(report.externalNetworkRequests, []);
  report.comparisonSummary = {
    comparedCalculations: report.crossRuntimeComparisons.length,
    numericFieldComparisons: sum(report.crossRuntimeComparisons.map(value => value.numericFieldComparisons)),
    maximumAbsoluteMeanErrorUnits: Math.max(...report.crossRuntimeComparisons.map(value => value.maximumAbsoluteMeanErrorUnits)),
    maximumAbsoluteJError: Math.max(...report.crossRuntimeComparisons.map(value => value.maximumAbsoluteJError)),
    maximumAbsoluteQualityError: Math.max(...report.crossRuntimeComparisons.map(value => value.maximumAbsoluteQualityError)),
    maximumAbsoluteCoverageError: Math.max(...report.crossRuntimeComparisons.map(value => value.maximumAbsoluteCoverageError)),
    methodProfileExact: true, scopeExact: true, countsExact: true, sampleSelectionAndJRepresentativesExact: true,
  };
  report.completed = new Date().toISOString(); report.passed = true;
  fs.writeFileSync(path.join(evidenceRoot, 'results.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(`Demo feedback API: ${report.checks.length} independent checks passed; all raw bytes mathematical, no server/network/patient inputs.`);
}
if (require.main === module) run().catch(error => {report.passed = false; console.error(error); process.exitCode = 1;});
module.exports = {fixtures, handFixture, denseFixture, harness, nativeOracle, compareST, runMath, run};
