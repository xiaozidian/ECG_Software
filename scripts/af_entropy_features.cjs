"use strict";
// Offline development experiment only; never imported by the application.
const E = require('../static/js/overview-engine.js');
const Q = require('../static/js/rr-quality.js');

function cosen12(rr) {
  if (!Array.isArray(rr) || rr.length !== 12 || rr.some(v => !Number.isFinite(v) || v < 300 || v > 2000)) {
    throw Error('Expected twelve finite RR intervals in milliseconds, 300–2000');
  }
  const d1 = [], d2 = [];
  // Eleven templates at both dimensions. No self-matches, each pair once.
  for (let i = 0; i < 11; i++) for (let j = i + 1; j < 11; j++) {
    const d = Math.abs(rr[i] - rr[j]);
    d1.push(d); d2.push(Math.max(d, Math.abs(rr[i + 1] - rr[j + 1])));
  }
  const fifth = [...d2].sort((a, b) => a - b)[4];
  // Equivalent to a 30,31,... ms search with strict distance < r.
  const r = Math.max(30, Math.floor(fifth) + 1);
  const a = d2.filter(d => d < r).length, b = d1.filter(d => d < r).length;
  const mean = rr.reduce((s, v) => s + v, 0) / rr.length;
  return {value: -Math.log(a / b) + Math.log(2 * r / mean), r_ms: r, a, b};
}

function features(rows, duration) {
  const baseline = E.screenAFResult(rows, duration);
  const qrs = Q.qrsRows(rows), valid = Q.intervalMask(qrs);
  const buckets = baseline.windows.map(() => []);
  qrs.forEach((r, i) => {
    const time = r.sample_index / 200;
    if (!Number.isFinite(time) || time < 0 || time >= duration) return;
    const k = Math.floor(time / 30), start = baseline.windows[k].start_s;
    if (valid[i] && r.rr_valid !== false && E.code(r) === 'N' && E.code(qrs[i - 1]) === 'N' &&
        r.rr_ms >= 300 && r.rr_ms <= 2000 && qrs[i - 1].sample_index / 200 >= start) {
      buckets[k].push({index: i, rr: r.rr_ms});
    }
  });
  return baseline.windows.map((w, k) => {
    const good = buckets[k], coverage = good.reduce((s, x) => s + x.rr / 1000, 0);
    if (good.length !== w.valid_intervals || Math.abs(coverage - w.coverage_s) > 1e-9) throw Error('Quality contract drift');
    const values = [];
    if (w.evaluated) for (let i = 11; i < good.length; i++) {
      if (good[i].index - good[i - 11].index !== 11) continue;
      values.push(cosen12(good.slice(i - 11, i + 1).map(x => x.rr)).value);
    }
    values.sort((a, b) => a - b);
    const n = values.length;
    return {...w, entropy: n ? (values[(n - 1) >> 1] + values[n >> 1]) / 2 : null,
      entropy_blocks: n, entropy_reason: w.reason || (n ? null : 'no_contiguous_twelve')};
  });
}

module.exports = {cosen12, features};
if (require.main === module) {
  const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
  process.stdout.write(JSON.stringify(features(input.rows, input.duration)));
}
