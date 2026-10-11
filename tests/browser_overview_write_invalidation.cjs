'use strict';
// Production functions and controlled asynchronous responses; no browser or case storage.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const C=require('../static/js/analysis-consistency.js'),E=require('../static/js/overview-engine.js');
const app=fs.readFileSync('static/js/app.js','utf8'),overview=fs.readFileSync('static/js/overview-workbench.js','utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const gate=()=>{let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve};};
function fixture(){
 const revisions=new Map([['A',0],['B',0]]),calls=[],nodes=new Map();let writeGate=null,failWrite=false,waveGate=null,rhythmGate=null;
 const state={caseId:'A',caseRequestId:1,currentPage:'review',start:0,duration:10,filter:'raw',waveformRequestId:0,waveform:null,caseData:{case_id:'A',analysis_revision:2,clinical_identity:{analysis_basis:'math:A',analysis_revision:0}},workspaceEpoch:1};
 const qs=key=>{if(!nodes.has(key))nodes.set(key,{innerHTML:'',textContent:'',value:0,width:100,height:100,getContext:()=>({clearRect(){}})});return nodes.get(key);};
 const basis=id=>({analysis_basis:'math:'+id,analysis_revision:revisions.get(id)});
 const response=(payload,status=200)=>({ok:status<400,status,headers:{get:()=> 'application/json'},json:async()=>payload});
 const ctx={state,ui:{id:null,loadToken:0,rows:[]},overviewReady:false,episodeEditor:null,episodeNavigation:0,episodeFilter:'all',episodePage:0,coverage:null,coverageMessage:'',episodeDrafts:new Map(),renders:0,
  ECGAnalysisConsistency:C,E,URLSearchParams,qs,$:qs,esc:String,fmtNumber:String,formatElapsed:String,
  button:(text,action)=>`<button data-ov="${action}">${text}</button>`,
  geometries:new WeakMap(),document:{querySelectorAll:()=>[qs('canvas')]},
  resetCoverage(message){ctx.coverage=null;ctx.coverageMessage=message;},renderCoverage(){},renderEpisodes(){ctx.renders++;},draw(){},hour:()=>0,
  updateZoomControls(){},renderWaveform(){},renderVisibleEvents(){},renderAnnotations(){},renderOverview(){},syncHourScatter(){},
  waveformRequestLeads:()=>['II'],ECGVoltage:{snapshot:()=>null},clinicalUI:{hasRhythmReturn:()=>false},
  clinicalWorkflow:{refresh:async()=>{},receive(){}},toast(){},
  ECGReadRequests:{clear(){},read:(_scope,_path,read)=>read()},
  fetch:async(raw,options)=>{
   const url=new URL(raw,'http://test'),parts=url.pathname.split('/'),id=parts[2]==='cases'?parts[3]:state.caseId,kind=parts.at(-1),method=options.method||'GET';
   calls.push({id,kind,method,query:Object.fromEntries(url.searchParams)});
   if(method!=='GET'&&['open','event-waveforms','waveform-strips','waveform-density','scatter-selection','advanced-analysis'].includes(kind))return response({readOnly:true});
   if(method!=='GET'){
    if(writeGate)await writeGate.promise;
    if(failWrite)return response({error:'write-failed'},400);
    revisions.set(id,revisions.get(id)+1);return response({id:'template-1',case_id:id},201);
   }
   const identity=basis(id),expected=url.searchParams.get('analysis_revision');
   if(expected!==null&&expected!==String(identity.analysis_revision))return response({error:'strict-stale-basis'},409);
   if(kind==='analysis-basis')return response(identity);
   if(kind==='overview')return response({...identity,revision:2,duration_s:90,columns:['sample_index','rr_ms','class_code'],rows:Array.from({length:80},(_,i)=>[200*(i+1),1000,'N']),settings:{pause:2.5}});
   if(kind==='rhythm-review'){if(rhythmGate){const held=rhythmGate;rhythmGate=null;await held.promise;return response({error:'late-read-error'},500);}return response({...identity,revision:1,beat_revision:2,document:{episodes:[],bookmarks:{}}});}
   if(kind==='waveform'){
    const value={...identity,start_s:0,duration_s:10,sample_rate_hz:200,leads:{II:[0]},filter:'raw'};
    if(waveGate){const pending=waveGate;waveGate=null;await pending.promise;}
    return response(value);
   }
   return response({});
  }};
 vm.createContext(ctx);
 vm.runInContext(overview.slice(overview.indexOf('  async function load('),overview.indexOf('  function prepare(')),ctx);
 vm.runInContext(overview.slice(overview.indexOf('  const episodeFields='),overview.indexOf('  function episodeQueue('))+overview.slice(overview.indexOf('  function rememberEpisodeForm('),overview.indexOf('  function episodeDraftHint(')),ctx);
 vm.runInContext(app.slice(app.indexOf('async function api('),app.indexOf('function toast(')),ctx);
 vm.runInContext(app.slice(app.indexOf('async function loadWaveform('),app.indexOf('function canvasContext(')),ctx);
 ctx.overviewWorkbench={waveformBasis:ctx.waveformBasis,waveformFailed:ctx.waveformFailed,invalidateAfterWrite:ctx.invalidateAfterWrite};
 return {ctx,state,calls,revisions,writeHold:()=>writeGate=gate(),writeFail:()=>failWrite=true,waveHold:()=>waveGate=gate(),rhythmHold:()=>rhythmGate=gate()};
}

const checks={
 'template-ack':async()=>{
  const f=fixture();await f.ctx.load(true);const initial=f.ctx.waveformBasis(),token=f.ctx.ui.loadToken,readCount=f.calls.length;
  await f.ctx.load(false);assert.equal(f.calls.length,readCount,'valid same-case cache should not issue additional reads');assert.equal(f.ctx.waveformBasis(),initial);
  f.state.currentPage='edit';await f.ctx.api('/api/cases/A/beat-templates',{method:'POST',body:'{}'});
  assert.equal(f.ctx.waveformBasis(),null,'successful template ACK must retire the old overview basis');assert.equal(f.ctx.overviewReady,false);assert.equal(f.ctx.ui.loadToken,token+1);
  const afterAck=f.calls.length;f.state.currentPage='review';await Promise.all([f.ctx.loadWaveform(),f.ctx.load(false)]);
  const requests=f.calls.slice(afterAck).filter(c=>c.kind==='waveform');assert(requests.length>0);assert(requests.every(c=>c.query.analysis_revision!=='0'),'no newly-issued waveform may carry acknowledged old basis');
  assert.equal(f.state.waveform.analysis_revision,1);assert.equal(f.ctx.waveformBasis().analysis_revision,1);
 },
 'failed-write':async()=>{
  const f=fixture();await f.ctx.load(true);const identity=f.ctx.waveformBasis(),token=f.ctx.ui.loadToken,rows=f.ctx.ui.rows;
  f.writeFail();await assert.rejects(f.ctx.api('/api/cases/A/beat-templates',{method:'POST',body:'{}'}),/write-failed/);
  assert.equal(f.ctx.waveformBasis(),identity);assert.equal(f.ctx.ui.loadToken,token);assert.equal(f.ctx.ui.rows,rows);
 },
 'ordinary-reads':async()=>{
  const f=fixture();await f.ctx.load(true);const identity=f.ctx.waveformBasis(),token=f.ctx.ui.loadToken,rows=f.ctx.ui.rows;
  await f.ctx.api('/api/cases/A/trend');
  for(const action of ['open','event-waveforms','waveform-strips','waveform-density','scatter-selection','advanced-analysis'])await f.ctx.api('/api/cases/A/'+action,{method:'POST',body:'{}'});
  assert.equal(f.ctx.waveformBasis(),identity);assert.equal(f.ctx.ui.loadToken,token);assert.equal(f.ctx.ui.rows,rows);assert.equal(f.revisions.get('A'),0);
  const count=f.calls.length;await f.ctx.load(false);assert.equal(f.calls.length,count,'ordinary reads must preserve the valid same-case cache fast path');
 },
 'late-other-case':()=>lateWrite(false),
 'late-same-case-reopen':()=>lateWrite(true),
 'late-success':async()=>{
  const f=fixture();await f.ctx.load(true);const held=f.waveHold();f.state.waveform=null;const older=f.ctx.load(true);await tick();
  assert(f.calls.some(c=>c.kind==='waveform'&&c.query.analysis_revision==='0'));
  await f.ctx.api('/api/cases/A/annotations',{method:'POST',body:'{}'});await f.ctx.load(false);
  const identity=f.ctx.waveformBasis(),rows=f.ctx.ui.rows,wave=f.state.waveform,renders=f.ctx.renders;assert.equal(identity.analysis_revision,1);
  held.resolve();await older;assert.equal(f.ctx.waveformBasis(),identity);assert.equal(f.ctx.ui.rows,rows);assert.equal(f.state.waveform,wave);assert.equal(f.ctx.renders,renders);
 },
 'late-error':async()=>{
  const f=fixture();await f.ctx.load(true);const held=f.rhythmHold();const older=f.ctx.load(true);older.catch(()=>{});await tick();
  await f.ctx.api('/api/cases/A/annotations',{method:'POST',body:'{}'});await f.ctx.load(false);
  const identity=f.ctx.waveformBasis(),rows=f.ctx.ui.rows,renders=f.ctx.renders;assert.equal(identity.analysis_revision,1);const status=f.ctx.qs('#ovStatus').textContent;
  held.resolve();await assert.rejects(older,/late-read-error/);assert.equal(f.ctx.waveformBasis(),identity);assert.equal(f.ctx.ui.rows,rows);assert.equal(f.ctx.renders,renders);assert.equal(f.ctx.qs('#ovStatus').textContent,status);
 },
 'episode-draft':async()=>{
  const f=fixture();await f.ctx.load(true);const original={id:'episode-1',start_s:3,end_s:8,kind:'AF',status:'pending',note:'original'},basis={caseId:'A',rhythm:1,beats:2,identity:JSON.stringify(f.ctx.waveformBasis())};
  const values={start:'3',end:'8',kind:'AF',status:'pending',note:'unsaved-local-review'};
  f.ctx.episodeEditor={key:'A:episode-1',basis,original,form:{elements:Object.fromEntries(Object.entries(values).map(([k,value])=>[k,{value}]))}};
  await f.ctx.api('/api/cases/A/beat-templates',{method:'POST',body:'{}'});
  const draft=f.ctx.episodeDrafts.get('A:episode-1');assert(draft,'original production rememberEpisodeForm must preserve the live local draft');
  assert.equal(draft.values.note,values.note);assert.equal(draft.basis,basis);assert.equal(draft.original,original);assert.equal(f.ctx.episodeEditor,null);assert.equal(f.ctx.ui.rows.length,0);assert.equal(f.ctx.ui.identity,null);
 },
 'write-kinds':async()=>{
  for(const [method,path,body] of [['POST','/api/cases/A/beat-templates','{}'],['PATCH','/api/beat-templates/42','{}'],['PUT','/api/cases/A/beat-overrides','{}'],['POST','/api/cases/A/annotations','{}'],['PATCH','/api/cases/A/patient','{}'],['PUT','/api/cases/A/rhythm-review','{}'],['PUT','/api/cases/A/beat-editor','{"operation":"settings"}'],['PUT','/api/cases/A/review-workflow','{}'],['PUT','/api/cases/A/report','{}']]){
   const f=fixture();await f.ctx.load(true);await f.ctx.api(path,{method,body});assert.equal(f.ctx.waveformBasis(),null,method+' '+path+' must retire the old overview basis');assert.equal(f.ctx.overviewReady,false);
  }
 }
};
async function lateWrite(sameCase){
 const f=fixture();await f.ctx.load(true);const held=f.writeHold();const saving=f.ctx.api('/api/cases/A/beat-templates',{method:'POST',body:'{}'});await tick();
 f.state.caseRequestId++;if(!sameCase)f.state.caseId='B';f.state.waveform=null;await f.ctx.load(true);
 const identity=f.ctx.waveformBasis(),token=f.ctx.ui.loadToken,rows=f.ctx.ui.rows;held.resolve();await saving;
 assert.equal(f.ctx.waveformBasis(),identity);assert.equal(f.ctx.ui.loadToken,token);assert.equal(f.ctx.ui.rows,rows);
}
(async()=>{
 const selected=process.argv[2];if(selected&&!Object.hasOwn(checks,selected))throw Error('unknown scenario '+selected);
 const names=selected?[selected]:Object.keys(checks);
 for(const name of names)await checks[name]();
 console.log(JSON.stringify({passed:names,production_functions:true,actual_api_and_overview:true,browser:false,case_storage:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
