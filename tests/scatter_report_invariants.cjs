'use strict';
// Deterministic geometry/selection checks. No browser, patient input or output renderer.
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const canonical = path.resolve(__dirname, '..');
const source = path.resolve(process.env.ECG_UI_SOURCE_ROOT || canonical);
const baseline = process.argv.includes('--measure-baseline');
const read = name => fs.readFileSync(path.join(source, name), 'utf8');
function between(text, start, end) {
  const a = text.indexOf(start), b = text.indexOf(end, a);
  assert(a >= 0 && b > a, start); return text.slice(a, b);
}
const app = read('static/js/app.js');
const points = [
  { sample_index: 200, group: 1, class_code: 'N', x: 800, y: 810 },
  { sample_index: 400, group: 2, class_code: 'S', x: 400, y: 900 },
  { sample_index: 600, group: 3, class_code: 'V', x: 500, y: 1000 },
  { sample_index: 800, group: 34, class_code: 'X', x: 1400, y: 900 },
  { sample_index: 1000, group: 1, class_code: 'S', x: 700, y: 1000 },
];
let descriptor = { type: 'source', code: 'N', group: 1, color: '#N' };
const state = { caseId: 'mathematical-A', caseRequestId: 1, editScatterFilterActive: false };
const sandbox = {
  state, editDescriptor: () => descriptor,
  ECGLinkedSelection: { snapshot: () => ({ scope: { caseId: state.caseId, caseToken: state.caseRequestId }, kind: 'none', selectionGeneration: 1 }) },
  editSourceCode: p => ({ 1: 'N', 2: 'S', 3: 'V', 34: 'X' })[p.group] || 'OTHER',
  BEAT_COLORS: { 1: '#N', 2: '#S', 3: '#V', 34: '#X' }, editBeatType: code => ({ color: '#' + code }),
};
vm.createContext(sandbox);
vm.runInContext(between(app, 'function editSourceMatches(', 'function editDescriptor(') +
  between(app, 'function drawTemplateScatterPoints(', 'function renderEditScatter('), sandbox);
function paint() {
  const drawn = [], ctx = { globalAlpha: 1, save() {}, beginPath() {}, rect() {}, clip() {}, restore() {}, arc(x, y) { this.point = [x, y]; }, fill() { drawn.push({ color: this.fillStyle, alpha: this.globalAlpha }); } };
  sandbox.drawTemplateScatterPoints(ctx, { points, bounds: { x_min: 0, x_max: 2000, y_min: 0, y_max: 2000 } }, descriptor, { l: 0, t: 0 }, 200, 200);
  return drawn;
}
const result = { scope: 'mathematical vectors; actual shipped render functions', baseline, scatter: {}, wave: {} };
result.scatter.initial = paint();
for (const [code, group] of [['N', 1], ['S', 2], ['V', 3], ['other', 8]]) {
  state.editScatterFilterActive = true; descriptor = { type: 'source', code, group, color: '#' + code };
  const drawn = paint(); result.scatter[code] = drawn.length;
  if (!baseline) {
    const expected = points.filter(p => code === 'other' ? !['N', 'S', 'V'].includes(p.class_code) : p.class_code === code);
    assert.equal(drawn.length, expected.length, 'other categories must not be painted, even with the same original group');
    const gate = sandbox.editScatterVisibility();
    assert.deepEqual(points.filter(gate).map(p => p.sample_index), expected.map(p => p.sample_index), 'pointer/lasso gate matches painting');
  }
}
if (!baseline) {
  descriptor = { type: 'custom', sample_indices: [400, 800], color: '#template' };
  assert.equal(paint().length, 2); assert.deepEqual(points.filter(sandbox.editScatterVisibility()).map(p => p.sample_index), [400, 800]);
  const linked = read('static/js/template-linked-view.js'); let clears = 0, redraws = 0;
  const clearBox = { state, cancelGesture() {}, active: () => true, C: () => ({ snapshot: () => ({ scope: {} }), clear: () => clears++ }), redrawScatter: () => redraws++, schedule() {} };
  vm.createContext(clearBox); vm.runInContext(between(linked, '  function clear(){', '  function capturePresentation('), clearBox);
  clearBox.clear(); assert.equal(clears, 1); assert.equal(redraws, 1); assert.equal(state.editScatterFilterActive, false); assert.equal(paint().length, points.length);
  assert.equal(result.scatter.initial.length, points.length);
  assert.equal(new Set(result.scatter.initial.map(p => p.color)).size, 4, 'initial scatter retains category colors');
}

const tools = require('../static/js/clinical-review-tools.js');
const cardBox = { module: { exports: {} }, ECGReviewTools: tools };
vm.createContext(cardBox); vm.runInContext(read('static/js/occurrence-card.js'), cardBox);
const reportBox = { ECGReviewTools: tools, ECGOccurrenceCard: cardBox.ECGOccurrenceCard };
vm.createContext(reportBox); vm.runInContext(read('static/js/report-workspace.js'), reportBox);
const names = ['I', 'II', 'III', 'aVR', 'aVL', 'aVF', 'V1', 'V2', 'V3', 'V4', 'V5', 'V6'];
const wave = { start_s: 100, duration_s: 7, sample_rate_hz: 200, stride: 1, beats: [{ sample_index: 20400, class_code: 'N' }],
  leads: Object.fromEntries(names.map((n, j) => [n, Array.from({ length: 1400 }, (_, i) => Math.sin(i / 9) * (600 + j * 80))])) };
const original = JSON.stringify(wave);
for (const selected of [['II'], ['II', 'V1', 'V5'], names]) {
  const slice = { ...wave, leads: Object.fromEntries(selected.map(n => [n, wave.leads[n]])) };
  const svg = reportBox.ECGReportWorkspace.reviewWaveSvg(slice, {}, { width: 1000, domain: 2000, recordStart: '2026-01-01 12:00:00' });
  const group = [...svg.matchAll(/<g data-wave-lead="([^"]+)" data-wave-scale="([^"]+)" data-wave-baseline="([^"]+)"/g)];
  const meta = Object.fromEntries(['columns', 'sample-rate', 'stride', 'source-start', 'source-duration', 'plot-width', 'fixed-row-height'].map(k => [k, new RegExp('data-' + k + '="([^"]+)"').exec(svg)?.[1]]));
  const ii = /<polyline[^>]*data-lead="II"[^>]*points="([^"]+)"/.exec(svg)[1].split(' ').map(p => p.split(',').map(Number));
  result.wave[selected.length] = { scales: group.map(m => Number(m[2])), II_baseline: Number(group.find(m => m[1] === 'II')[3]), metadata: meta, x: ii.map(p => p[0]), height: Number(/viewBox="0 0 [0-9.]+ ([0-9.]+)"/.exec(svg)[1]) };
}
if (!baseline) {
  const one = result.wave[1];
  for (const count of [1, 3, 12]) {
    const observed = result.wave[count];
    assert(observed.scales.every(v => Math.abs(v - one.scales[0]) < 1e-12), 'gain must not depend on lead count or row position');
    assert.deepEqual(observed.x, one.x, 'every original sample keeps the same time coordinate');
    assert.equal(observed.height, count * 64 + 48, 'only the number of fixed-height rows changes');
    assert.equal(observed.metadata.columns, '1'); assert.equal(observed.metadata['source-duration'], '7');
    assert.equal(observed.metadata['sample-rate'], '200'); assert.equal(observed.metadata.stride, '1');
  }
  assert.equal(JSON.stringify(wave), original, 'source samples and annotations are unchanged');
}
result.gainInvariant = Object.values(result.wave).every(x => x.scales.every(v => Math.abs(v - result.wave[1].scales[0]) < 1e-12));
for (const x of Object.values(result.wave)) delete x.x;
result.passed = !baseline;
console.log(JSON.stringify(result));
