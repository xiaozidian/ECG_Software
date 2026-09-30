// Exercise the actual dashboard renderer, not a second implementation.
const assert=require('node:assert/strict');
const {harness,caseRow}=require('./browser_dashboard_arrival.cjs');
const {ctx,$,ready}=harness(),issues=[{case_id:'bad-case',error:'<script>invalid</script>'}];
(async()=>{
  assert.equal(ctx.fmtNumber(null),'—');assert.equal(ctx.fmtNumber(undefined),'—');assert.equal(ctx.fmtNumber(0),'0');
  await ready([caseRow()],issues);
  assert.equal($('#qualityStatus').textContent,'1 / 2 可读');
  assert.equal($('#qualityPercent').textContent,'50%');
  assert.equal($('#sourceIssues').hidden,false);assert.equal($('#openFirstCase').disabled,false);
  assert.match($('#sourceIssuesList').innerHTML,/&lt;script&gt;/);assert.doesNotMatch($('#sourceIssuesList').innerHTML,/<script>/);
  await ready([],issues);
  assert.equal($('#qualityPercent').textContent,'0%');assert.equal($('#openFirstCase').disabled,true);
  await ready();assert.equal($('#sourceIssues').hidden,true);assert.equal($('#sourceIssuesList').innerHTML,'');
  assert.equal($('#qualityStatus').textContent,'1 / 1 可读');assert.equal($('#openFirstCase').disabled,false);
})().catch(error=>{console.error(error);process.exitCode=1});
