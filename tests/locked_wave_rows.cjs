'use strict';
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const tools = require('../static/js/clinical-review-tools.js');
const low = [[-100, 0, 200], [-300, 0, 100], [-100, 0, 150]];
const high = [[-2903, 0, 3044], [-1155, 0, 647], [-1443, 0, 2061]];
const hash = x => crypto.createHash('sha256').update(JSON.stringify(x)).digest('hex');
const before = hash(high), domain = 1600;
const a = tools.lockedWaveRows(low, { top: 27, rowHeight: 90, domain });
const b = tools.lockedWaveRows(high, { top: 27, rowHeight: 90, domain, scale: a.scale });
const c = tools.lockedWaveRows(low, { top: 27, rowHeight: 90, domain, scale: b.scale });
assert.equal(a.expanded, false); assert.equal(b.expanded, true);
assert.equal(a.scale, b.scale); assert.equal(b.scale, c.scale);
assert(b.rowHeight > a.rowHeight); assert.equal(c.rowHeight, a.rowHeight);
assert.deepEqual(b.layouts.map(x => x.overflow), [true, false, true]);
for (const [i, values] of high.entries()) for (const value of values) {
  const row = b.layouts[i], y = row.baseline - value * row.scale;
  assert(y >= row.signalTop - 1e-9 && y <= row.signalBottom + 1e-9);
}
assert.equal(hash(high), before);
// A large one-sided source offset also gets space; it is never subtracted.
const offset = tools.lockedWaveRows([[31900, 32000, 32100]], { rowHeight: 90, domain, scale: a.scale });
assert.equal(offset.scale, a.scale);
assert(offset.layouts[0].baseline - 32100 * offset.scale >= offset.layouts[0].signalTop - 1e-9);
assert(offset.layouts[0].baseline - 31900 * offset.scale > offset.layouts[0].signalTop);
// Changing the number of displayed leads adds equal rows at the same gain.
const twelve = tools.lockedWaveRows(Array.from({ length: 12 }, () => high[0]), { rowHeight: 90, domain, scale: a.scale });
assert.equal(twelve.scale, a.scale); assert.equal(twelve.layouts.length, 12);
assert(twelve.layouts.every(x => x.scale === b.scale));
console.log('PASS locked gain; all extrema visible; no source normalization; row-count invariance');
