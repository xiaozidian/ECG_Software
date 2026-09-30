"use strict";
// Offline, pre-specified aggregation experiment. Not loaded by the application.
const F = require('./af_entropy_features.cjs');
const E = require('../static/js/overview-engine.js');
const Q = require('../static/js/rr-quality.js');

function quantile(sorted, p) {
  if (!Array.isArray(sorted) || !Number.isFinite(p) || p < 0 || p > 1 ||
      sorted.some((v, i) => !Number.isFinite(v) || (i && v < sorted[i - 1]))) {
    throw Error('Expected sorted finite values and a probability');
  }
  if (!sorted.length) return null;
  const index = (sorted.length - 1) * p, lo = Math.floor(index), hi = Math.ceil(index);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (index - lo);
}

function features(rows, duration) {
  const old = F.features(rows, duration), qrs = Q.qrsRows(rows), mask = Q.intervalMask(qrs);
  const buckets = old.map(() => []);
  qrs.forEach((row, i) => {
    const t = row.sample_index / 200;
    if (!Number.isFinite(t) || t < 0 || t >= duration) return;
    const k = Math.floor(t / 30);
    if (mask[i] && row.rr_valid !== false && E.code(row) === 'N' && E.code(qrs[i - 1]) === 'N' &&
        row.rr_ms >= 300 && row.rr_ms <= 2000 && qrs[i - 1].sample_index / 200 >= old[k].start_s) {
      buckets[k].push({i, rr: row.rr_ms});
    }
  });
  return old.map((w, k) => {
    const good = buckets[k], values = [];
    if (good.length !== w.valid_intervals ||
        Math.abs(good.reduce((a, r) => a + r.rr / 1000, 0) - w.coverage_s) > 1e-9) {
      throw Error('Quality contract drift');
    }
    if (w.evaluated) for (let j = 11; j < good.length; j++) {
      if (good[j].i - good[j - 11].i === 11) {
        values.push(F.cosen12(good.slice(j - 11, j + 1).map(r => r.rr)).value);
      }
    }
    values.sort((a, b) => a - b);
    const median = quantile(values, .5);
    if (values.length !== w.entropy_blocks || (median === null) !== (w.entropy === null) ||
        (median !== null && Math.abs(median - w.entropy) > 1e-12)) {
      throw Error('Frozen median contract drift');
    }
    return {...w, upper_quartile: quantile(values, .75), maximum: quantile(values, 1)};
  });
}

module.exports = {quantile, features};
if (require.main === module) {
  const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
  process.stdout.write(JSON.stringify(features(input.rows, input.duration)));
}
