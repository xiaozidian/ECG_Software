'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const E=require('../static/js/overview-engine.js'),C=require('../static/js/af-coverage.js');
const identity={analysis_basis:'synthetic',analysis_revision:3};
const source=fs.readFileSync('static/js/overview-workbench.js','utf8'),which=process.argv[2];
const helpers=source.slice(source.indexOf('  function coverageBasis('),source.indexOf('  function screenPAC('));
const load=source.slice(source.indexOf('  async function load('),source.indexOf('  function prepare('));
const rows=Array.from({length:119},(_,i)=>({sample_index:i*160,rr_ms:i?800:0,class_code:'N'}));
let seconds=95,timers=[],seeks=[],focus=0,writes=0;
const host={innerHTML:'',querySelector:()=>({open:true}),insertAdjacentHTML:(_,html)=>host.innerHTML+=html},status={};
const wave={scrollIntoView:()=>focus++,focus:()=>focus++},nav={...wave,innerHTML:'',hidden:true};
const evidence={...wave,innerHTML:'',hidden:true},list={...wave,open:false,querySelector:()=>wave};
const c={E,ECGAFCoverage:C,overviewReady:true,coverage:null,coveragePage:0,coverageBusy:false,coverageMessage:'',coverageRun:0,coverageFocus:-1,
  ui:{id:'c',af:true,revision:2,rows,rhythm:{revision:3,document:{episodes:[],bookmarks:{}}},loadToken:1},state:{caseId:'c',caseData:{}},
  qs:key=>key==='#ovAFCoverage'?host:key==='#ovStatus'?status:key==='#ovAFGapNavigation'?nav:key==='#ovAFWindowEvidence'?evidence:key==='#ovAFWindows'?list:wave,
  duration:()=>seconds,span:()=>[60,95],esc:String,formatElapsed:x=>'D1 '+x,
  button:(label,action,attrs='')=>`<button data-ov="${action}" ${attrs}>${label}</button>`,
  setTimeout:fn=>timers.push(fn),seek:async(...args)=>seeks.push(args),confirmRhythm:()=>writes++,
  hour:()=>0,draw:()=>{},renderEpisodes:()=>{},fmtNumber:String,
  ECGAnalysisConsistency:require('../static/js/analysis-consistency.js'),rememberEpisodeForm(){},episodeEditor:null,episodeNavigation:0,
  document:{querySelectorAll:()=>[]},loadWaveform:async()=>{c.state.waveform=identity},
  clinicalUI:{hasRhythmReturn:()=>false},
};
vm.createContext(c);vm.runInContext(helpers+load,c);
const call=code=>vm.runInContext(code,c);
async function check(){const promise=call('checkCoverage()');assert.equal(c.coverageBusy,true);assert.match(host.innerHTML,/正在检查/);timers.shift()();await promise;}
(async()=>{
  if(which.startsWith('window-')){
    await check();
    if(which==='window-readonly'){
      assert.match(host.innerHTML,/逐窗提示依据/);assert.equal(c.coverage.windows.length,4);
      await call('locateCoverageWindow(0)');assert.match(evidence.innerHTML,/有效 N-N/);assert.match(evidence.innerHTML,/0<\/dd>/);assert.match(evidence.innerHTML,/不是诊断标准/);
      assert.equal(writes,0);return;
    }
    if(which==='window-empty-filter'){
      call("windowListAction('af-window-filter','candidate')");assert.match(host.innerHTML,/没有此类窗口/);assert.equal(list.open,true);
      await assert.rejects(call('locateCoverageWindow(0)'),/不在当前列表/);return;
    }
    if(which==='window-navigation'){
      await call('locateCoverageWindow(3)');assert.deepEqual(seeks,[[90,true,90,true]]);assert.equal(JSON.stringify(c.ui.range),'[90,95]');assert.match(evidence.innerHTML,/连续间期对 \/ 三元组<\/dt><dd>未计算/);assert.match(evidence.innerHTML,/不足完整 30 秒/);
      call("windowListAction('af-window-list','')");assert.equal(list.open,true);assert.equal(c.coverage.page,0);assert.equal(writes,0);return;
    }
    if(which==='window-stale'){c.ui.revision++;await assert.rejects(call('locateCoverageWindow(0)'),/失效/);assert.equal(seeks.length,0);assert.equal(evidence.hidden,true);return;}
    if(which==='window-invalid'){await assert.rejects(call('locateCoverageWindow(-1)'),/不在当前列表/);assert.throws(()=>call("windowListAction('af-window-page','99')"),/页码/);assert.equal(seeks.length,0);return;}
    if(which==='window-reset'){await call('locateCoverageWindow(0)');call("resetCoverage('changed')");assert.equal(evidence.hidden,true);assert.equal(evidence.innerHTML,'');return;}
    if(which==='window-other-location'){
      await call('locateCoverageWindow(0)');
      c.run=fn=>fn();c.loadWaveform=async()=>{};c.renderWaveform=()=>{};c.state.duration=10;
      vm.runInContext(source.slice(source.indexOf('  function seek('),source.indexOf('  function timeAt(')),c);
      await call('seek(60,true)');assert.equal(c.coverage.focus,-1);assert.equal(evidence.hidden,true);assert.equal(c.state.start,60);return;
    }
    if(which==='window-real-seek'){
      c.run=fn=>fn();c.loadWaveform=async()=>{};c.state.duration=10;
      vm.runInContext(source.slice(source.indexOf('  function seek('),source.indexOf('  function timeAt(')),c);
      await call('locateCoverageWindow(0)');assert.equal(focus,2);assert.equal(c.coverage.focus,0);
      await call('locateCoverageGap(0)');assert.equal(focus,4);assert.equal(nav.hidden,false);assert.equal(evidence.hidden,true);return;
    }
    if(which==='window-pages'){
      seconds=86405;c.result=E.screenAFResult([],seconds);call('publishCoverage(result,0,86405,coverageBasis())');
      assert.equal((host.innerHTML.match(/data-ov="af-window:/g)||[]).length,20);
      call("windowListAction('af-window-page','144')");assert.match(host.innerHTML,/af-window:2880/);await call('locateCoverageWindow(2880)');
      call("windowListAction('af-window-list','')");assert.equal(c.coverage.page,144);assert.equal(writes,0);return;
    }
    const pending=[];c.seek=()=>new Promise(resolve=>pending.push(resolve));
    const first=call('locateCoverageWindow(0)');assert.equal(evidence.hidden,false);
    if(which==='window-new-check')await check();
    if(which==='window-close')c.ui.af=false;
    if(which==='window-filter-race')call("windowListAction('af-window-filter','unassessed')");
    if(which==='window-gap-race'){
      const second=call('locateCoverageGap(0)');pending[1]();await second;assert.equal(evidence.hidden,true);assert.equal(nav.hidden,false);
    }
    if(which==='window-race'){
      const second=call('locateCoverageWindow(1)');pending[1]();await second;assert.equal(c.coverage.focus,1);
    }
    const before=focus;pending[0]();await first;assert.equal(focus,before);assert.equal(writes,0);return;
  }
  if(which==='readonly'){await check();assert.equal(writes,0);assert.equal(c.coverage.summary.assessed_s,90);assert.equal(c.coverage.summary.skipped_s,5);assert.match(host.innerHTML,/不是正常率/);assert.match(host.innerHTML,/94.7%/);return;}
  if(which==='empty'||which==='short'){c.ui.rows=[];if(which==='short')seconds=7;await check();assert.equal(writes,0);assert.equal(c.coverage.summary.assessed_s,0);assert.equal(c.coverage.summary.skipped_s,seconds);assert.match(host.innerHTML,/未评估不代表正常/);return;}
  if(which.startsWith('stale-')||which==='cancel'){
    const p=call('checkCoverage()');
    if(which==='stale-case')c.state.caseId='other';
    if(which==='stale-revision')c.ui.revision++;
    if(which==='stale-rows')c.ui.rows=[...rows];
    if(which==='stale-token')c.ui.loadToken++;
    if(which==='stale-source')c.state.caseData={};
    if(which==='cancel')call("resetCoverage('cancelled')");
    timers.shift()();await p;
    assert.equal(c.coverage,null);assert.equal(c.coverageBusy,false);assert.equal(writes,0);return;
  }
  if(which.startsWith('gap')){
    c.ui.rows=[];await check();
    if(which==='gap-stale'){c.state.caseId='other';await assert.rejects(call('locateCoverageGap(0)'),/失效/);assert.equal(seeks.length,0);return;}
    if(which==='gap-invalid'){await assert.rejects(call('locateCoverageGap(-1)'),/序号/);assert.equal(seeks.length,0);return;}
    await call('locateCoverageGap(1)');assert.deepEqual(seeks,[[90,true,90,true]]);assert.equal(JSON.stringify(c.ui.range),'[90,95]');assert.equal(focus,2);assert.equal(writes,0);
    assert.equal(nav.hidden,false);assert.match(nav.innerHTML,/返回覆盖列表/);assert.match(nav.innerHTML,/未评估 2 \/ 2/);
    call("resetCoverage('changed')");assert.equal(nav.hidden,true);return;
  }
  if(which==='screen-zero'){c.ui.rows=[];assert.throws(()=>call('screenAF()'),/未评估不代表正常/);assert.equal(c.coverage.summary.skipped_s,95);assert.equal(writes,0);return;}
  if(which==='render-pages'){
    seconds=86400;const r=E.screenAFResult([],seconds);r.windows.forEach((w,i)=>w.reason=i%2?'low_quality':'insufficient_intervals');c.result=r;
    call('publishCoverage(result,0,86400,coverageBasis())');assert.equal((host.innerHTML.match(/data-ov="af-gap:/g)||[]).length,20);
    call('coveragePage=143;renderCoverage()');assert.match(host.innerHTML,/第 144 \/ 144 页/);assert.match(host.innerHTML,/af-gap:2879/);return;
  }
  if(which.startsWith('load-')){
    await check();let finish;
    const rhythm={...c.ui.rhythm,...identity,beat_revision:4};
    c.api=path=>path.includes('/overview?')?new Promise((resolve,reject)=>finish=which==='load-failure'?reject:resolve):Promise.resolve(path.includes('/rhythm-review?')?rhythm:identity);
    // Use the actual async load body with decoding/drawing outside this test's concern.
    c.E={...E,decode:data=>data.rows,histogram:()=>[],stats:()=>({})};
    const p=call('load(true)');assert.equal(c.overviewReady,false);assert.equal(c.coverage,null);
    await assert.rejects(call('checkCoverage()'),/载入/);
    if(which==='load-failure'){finish(Error('offline'));await assert.rejects(p,/offline/);assert.equal(c.overviewReady,false);assert.match(host.innerHTML,/重试/);}
    else{finish({...identity,rows,revision:4,duration_s:seconds});await p;assert.equal(c.overviewReady,true);assert.equal(c.ui.revision,4);assert.equal(c.coverage,null);assert.match(host.innerHTML,/尚未检查/);}
    return;
  }
  throw Error('unknown test '+which);
})().catch(e=>{console.error(e);process.exitCode=1;});
