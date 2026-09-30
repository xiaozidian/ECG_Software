const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('static/js/clinical-ui.js','utf8');
const event=n=>({event_id:'e'+n,basis_version:'basis',category:'fastest',subtype:'NN',time_s:n,label:'候选'+n});
let requests=[],located=[],focused=0;
const node={scrollIntoView(){},focus(){focused++}};
const ctx=vm.createContext({state:{caseId:'a'},category:'final',reportMode:'all',reportOffset:0,pauseBand:'over3',reportTimeRange:[0,10],reportReturn:null,
 selected:()=>[{event_id:'e75',basis_version:'basis'}],selectedLookup:new Map([['e75',event(75)]]),
 composition:()=>({fast_slow_mode:'rr'}),qs:()=>node,
 refreshReport:async options=>{requests.push(options)},locate:async e=>{located.push(e.event_id)}});
vm.runInContext(source.slice(source.indexOf('  function reportSequence('),source.indexOf('  function renderEventNavigation(')),ctx);
vm.runInContext(source.slice(source.indexOf('  async function stepReportEvent('),source.indexOf('  function syncText(')),ctx);
(async()=>{
  await ctx.backToReportEvent(0);
  assert.equal(ctx.category,'fastest');assert.equal(ctx.reportMode,'NN');assert.equal(ctx.reportSequence(),'nn');
  assert.equal(ctx.composition().fast_slow_mode,'rr','review must not mutate output mode');
  assert.equal(requests[0].focusEvent.event_id,'e75');assert.equal(ctx.pauseBand,'all');assert.equal(ctx.reportTimeRange,null);
  await ctx.returnToReport();assert.equal(ctx.category,'final');assert.equal(ctx.reportReturn,null);assert(focused>=2);
  ctx.category='fastest';ctx.reportData={items:Array.from({length:50},(_,i)=>event(i)),total:125};ctx.active=event(49);ctx.reportOffset=0;
  await ctx.stepReportEvent(1);assert.equal(ctx.reportOffset,50);assert.equal(requests.at(-1).edge,'first');
  ctx.reportData.items=Array.from({length:50},(_,i)=>event(i+50));ctx.active=event(50);
  await ctx.stepReportEvent(-1);assert.equal(ctx.reportOffset,0);assert.equal(requests.at(-1).edge,'last');
  ctx.reportData.items=Array.from({length:50},(_,i)=>event(i));ctx.active=event(4);
  await ctx.stepReportEvent(1);assert.equal(located.at(-1),'e5');
  ctx.active=event(0);const count=requests.length,number=located.length;await ctx.stepReportEvent(-1);
  assert.equal(requests.length,count);assert.equal(located.length,number);
  ctx.reportOffset=100;ctx.reportData.items=Array.from({length:25},(_,i)=>event(100+i));ctx.active=event(124);await ctx.stepReportEvent(1);
  assert.equal(requests.length,count);assert.equal(located.length,number);
  ctx.selectedLookup.set('e75',{...event(75),basis_version:'new'});
  await assert.rejects(ctx.backToReportEvent(0),/失效/);
  ctx.reportReturn={id:'old-case',category:'final'};await ctx.returnToReport();assert.equal(ctx.category,'fastest');
  console.log('Exact report return, RR/NN separation, page boundaries and stale target guards passed');
})().catch(e=>{console.error(e);process.exitCode=1});
