'use strict';
const assert=require('node:assert/strict');
const E=require('../static/js/rhythm-range-editor.js');
let checks=0;
function roundtrip(start,seconds,expected,duration=200000){
  assert.equal(E.boundaryClock(seconds,start),expected);checks++;
  assert.equal(E.parseBoundaryClock(expected,start,duration),seconds);checks++;
}
roundtrip('2026-11-02 08:16:26',0,'2026-11-02 08:16:26.000');
roundtrip('2026-11-02T23:59:59.995+08:00',0.01,'2026-11-03 00:00:00.005');
roundtrip('2026-12-31 23:59:59',1,'2027-01-01 00:00:00.000');
roundtrip('2024-02-28 23:59:59',1,'2024-02-29 00:00:00.000');
roundtrip('2024-02-29 23:59:59',1,'2024-03-01 00:00:00.000');
roundtrip('2026-11-02 08:16:26.123',3600.005,'2026-11-02 09:16:26.128');
for(const source of [null,undefined,'','unknown','2026-02-30 08:00:00','2025-02-29 08:00:00','2026-13-01 00:00:00','2026-11-02 24:00:00']){
  roundtrip(source,12.345,'+12.345');
  assert.equal(E.parseBoundaryClock('12.345',source,100),12.345);checks++;
}
const base='2026-11-02 08:00:00';
for(const invalid of ['','2026-11-02 07:59:59.995','2026-11-02 08:01:40.005','2026-02-30 08:00:00','2026-11-02 24:00:00','2026-11-02 08:60:00','2026-11-02 08:00:60','2026-11-02','08:00:01','NaN']){
  assert.throws(()=>E.parseBoundaryClock(invalid,base,100));checks++;
}
for(const invalid of ['', '-0.005','100.005','NaN','Infinity','12:00:00']){
  assert.throws(()=>E.parseBoundaryClock(invalid,null,100));checks++;
}
assert.equal(E.parseBoundaryClock('2026-11-02 08:00:00.002',base,100),0);checks++;
assert.equal(E.parseBoundaryClock('2026-11-02 08:00:00.003',base,100),0.005);checks++;
assert.equal(E.parseBoundaryClock('2026-11-02 08:01:40.000',base,100),100);checks++;
for(const timezone of ['UTC','Asia/Shanghai','America/New_York']){
  process.env.TZ=timezone;
  roundtrip('2026-11-01 01:59:59-04:00',2,'2026-11-01 02:00:01.000');
}
console.log(JSON.stringify({passed:true,checks,scope:'wall-clock-midnight-calendar-validation-relative-fallback-timezone-independence',patient_inputs:false}));
