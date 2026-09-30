'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const C=require('../static/js/analysis-consistency.js'),E=require('../static/js/overview-engine.js');
const source=fs.readFileSync('static/js/overview-workbench.js','utf8'),app=fs.readFileSync('static/js/app.js','utf8');
const which=process.argv[2],basis={analysis_basis:'synthetic',analysis_revision:4};
const rows=Array.from({length:80},(_,i)=>[200*(i+1),1000,'N']);
const beat={...basis,revision:2,duration_s:90,columns:['sample_index','rr_ms','class_code'],rows,settings:{pause:2.5}};
const rhythm={...basis,revision:1,beat_revision:2,document:{episodes:[],bookmarks:{}}};
const wave={...basis,start_s:0,duration_s:10,sample_rate_hz:200,leads:{II:[0]},filter:'raw'};
const nodes=new Map(),qs=key=>{if(!nodes.has(key))nodes.set(key,{innerHTML:'old',textContent:'old',getContext:()=>({clearRect(){clears++}})});return nodes.get(key)};
let calls=[],renders=0,clears=0,preserved=0,fail=false,anchorReads=0,toasts=[],writes=0,release;
const pending=new Promise(r=>release=r);
const state={caseId:'c',caseRequestId:1,currentPage:'review',start:0,duration:10,filter:'raw',waveformRequestId:0,waveform:{...wave},caseData:{}};
const ctx={state,ui:{id:'c',revision:2,caseToken:1,identity:basis,loadToken:1,rows:[{}],rhythm},overviewReady:true,
  coverage:{old:true},coverageMessage:'',episodeEditor:{old:true},episodeNavigation:0,episodeFilter:'all',episodePage:0,
  ECGAnalysisConsistency:C,E,URLSearchParams,qs,$:qs,esc:String,fmtNumber:String,formatElapsed:String,
  button:(label,action)=>`<button data-ov="${action}">${label}</button>`,
  rememberEpisodeForm(){preserved++},geometries:new WeakMap(),document:{querySelectorAll:()=>[qs('canvas')]},
  resetCoverage(message){ctx.coverage=null;ctx.coverageMessage=message;},renderCoverage(){},renderEpisodes(){renders++},draw(){},hour:()=>0,
  updateZoomControls(){},renderWaveform(){},renderVisibleEvents(){},renderAnnotations(){},renderOverview(){},syncHourScatter(){},
  waveformRequestLeads:()=>['II'],ECGVoltage:{snapshot:()=>null},
  clinicalUI:{hasRhythmReturn:()=>false},
  api:async raw=>{
    const u=new URL(raw,'http://test'),kind=u.pathname.split('/').at(-1);calls.push({kind,query:Object.fromEntries(u.searchParams)});
    if(kind==='analysis-basis'){anchorReads++;return which==='final-change'&&anchorReads===2?{...basis,analysis_revision:5}:basis;}
    assert.equal(u.searchParams.get('analysis_basis'),basis.analysis_basis);
    assert.equal(u.searchParams.get('analysis_revision'),'4');
    if(kind==='rhythm-review'){
      if(which.startsWith('late-'))await pending;
      if(fail||which==='late-error')throw Error('offline');
      return which==='mixed'?{...rhythm,analysis_revision:5}:which==='beat-mismatch'?{...rhythm,beat_revision:3}:rhythm;
    }
    if(kind==='waveform')return which==='wave-mismatch'?{...wave,analysis_revision:5}:wave;
    return beat;
  },
  toast:(...args)=>toasts.push(args),clinicalWorkflow:{writable:()=>true,refresh:async()=>{if(which==='save-refresh-error')throw Error('refresh failed')}},
};
vm.createContext(ctx);
vm.runInContext(source.slice(source.indexOf('  async function load('),source.indexOf('  function prepare(')),ctx);
vm.runInContext(app.slice(app.indexOf('async function loadWaveform('),app.indexOf('function canvasContext(')),ctx);
ctx.overviewWorkbench={waveformBasis:ctx.waveformBasis,waveformFailed:ctx.waveformFailed};
const tick=()=>new Promise(r=>setImmediate(r));
(async()=>{
  if(which.startsWith('save-')){
    qs('#ovDialog').close=()=>{};
    ctx.request=async(kind,options)=>{writes++;assert.equal(kind,'rhythm-review');const p=JSON.parse(options.body);assert.equal(p.analysis_basis,basis.analysis_basis);assert.equal(p.analysis_revision,4);return {...rhythm,revision:2}};
    ctx.load=async()=>{if(which==='save-reload-error')throw Error('reload failed');};
    vm.runInContext(source.slice(source.indexOf('  async function saveRhythm('),source.indexOf('  const rhythmBasis=')),ctx);
    if(which==='save-not-ready'){ctx.overviewReady=false;await assert.rejects(ctx.saveRhythm({}),/尚未核对/);assert.equal(writes,0);return;}
    await ctx.saveRhythm({episodes:[],bookmarks:{}});assert.equal(writes,1);
    assert(toasts.some(x=>x[0].includes('已保存')));return;
  }
  if(which==='same-case-reload'){state.caseRequestId++;assert.equal(ctx.waveformBasis(),null);return;}
  if(which==='late-wave-failure'){ctx.ui.identity={...basis};ctx.waveformFailed(basis);assert.equal(ctx.overviewReady,true);return;}
  if(which==='wave-mismatch'){
    await assert.rejects(ctx.loadWaveform(),/变化/);assert.equal(state.waveform,null);assert.equal(ctx.overviewReady,false);assert.equal(ctx.coverage,null);assert.match(qs('#ovStatus').innerHTML,/重试载入/);return;
  }
  if(which==='wave-refresh')state.waveform={...wave,analysis_revision:3};
  if(which==='retry')fail=true;
  const job=ctx.load(true);job.catch(()=>{});await tick();
  assert(preserved>0&&clears>0);assert.equal(ctx.coverage,null);
  if(which.startsWith('late-')){
    state.caseRequestId++;ctx.overviewReady=true;qs('#ovStatus').innerHTML='new case';ctx.ui.rows=['new'];release();
    if(which==='late-error')await assert.rejects(job,/offline/);else await job;
    assert.equal(qs('#ovStatus').innerHTML,'new case');assert.deepEqual(ctx.ui.rows,['new']);return;
  }
  if(['mixed','beat-mismatch','final-change','retry'].includes(which)){
    await assert.rejects(job,/变化|不一致|offline/);assert.equal(ctx.overviewReady,false);assert.equal(ctx.ui.rows.length,0);assert.equal(ctx.ui.rhythm,null);assert.equal(renders,0);assert.match(qs('#ovStatus').innerHTML,/重试载入/);
    if(which!=='retry')return;
    fail=false;await ctx.load(true);
  }else await job;
  assert.equal(ctx.overviewReady,true);assert.equal(renders,1);assert.equal(ctx.ui.rows.length,80);assert.equal(ctx.ui.identity.analysis_revision,4);
  assert.equal(calls.filter(x=>x.kind==='waveform').length,which==='wave-refresh'?1:0);
  assert.equal(state.waveform.analysis_revision,4);
})().catch(e=>{console.error(e);process.exitCode=1});
