'use strict';
// Exercise the production ST loader, API adapter, consumer cancellation and
// slider/fullscreen handlers with disposable, deterministic waveform payloads.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const C=require('../static/js/analysis-consistency.js'),Reads=require('../static/js/read-requests.js');
const app=fs.readFileSync('static/js/app.js','utf8'),layout=fs.readFileSync('static/js/stt-review-layout.js','utf8');
const leads=['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6'];
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const gate=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject};};
const json=value=>JSON.parse(JSON.stringify(value));
const classes=()=>({add(){},remove(){},toggle(){}});
function node(){
  return {dataset:{},style:{setProperty(){},removeProperty(){}},classList:classes(),textContent:'',innerHTML:'',value:'',checked:false,disabled:false,
    width:800,height:438,hidden:false,listeners:new Map(),setAttribute(){},removeAttribute(){},getContext:()=>({clearRect(){}}),
    getBoundingClientRect:()=>({left:0,top:0,width:800,height:438}),addEventListener(name,fn){this.listeners.set(name,fn);},removeEventListener(){},
    querySelector(){return null;},querySelectorAll(){return [];},focus(){},contains(){return false;},prepend(child){child.parentElement=this;}};
}
function harness(){
  const h={basis:{analysis_basis:'synthetic-source-v1',analysis_revision:1},requests:[],waves:[],posts:[],basisReads:[],renders:{capability:0,trend:0,overview:0,wave:0},toasts:[],errors:[],timers:[]};
  const nodes=new Map(),$=selector=>{if(!nodes.has(selector))nodes.set(selector,node());return nodes.get(selector);},$$=()=>[];
  const root=$('#page-stt');root.querySelector=selector=>['#sttCurrentContext','#sttAnalysisStatus','.stt-waveform-card','#sttWaveCanvasWrap'].includes(selector)?$(selector):null;
  $('#sttFinding').value='无法判读';
  const card=$('.stt-waveform-card');card.insertBefore=child=>{child.parentElement=card;};
  const state=h.state={caseId:'synthetic-a',caseRequestId:1,currentPage:'stt',workspaceEpoch:'synthetic-workspace',includePhi:false,demoReadonly:false,
    sttRequestId:0,sttStart:0,sttDuration:10,sttIsoFraction:.34,sttJFraction:.52,sttMeasurementMs:60,leads:['II','V1','V5'],
    start:0,duration:10,filter:'display',caseData:{case_id:'synthetic-a',clinical_identity:{...h.basis},technical:{duration_seconds_raw:300}},sttReview:null,sttWaveform:null};
  const body=kind=>kind===''?{case_id:state.caseId,clinical_identity:{...h.basis},technical:{duration_seconds_raw:300},review_workflow:{revision:h.basis.analysis_revision}}:
    kind==='trend'?{...h.basis,points:[{time_s:0,hr:70},{time_s:300,hr:75}]}:
    {...h.basis,automatic_candidates:{enabled:true,items:[{label:'合成候选',start_s:30,end_s:90,leads:['II'],peak_deviation_units:-120}]},
      analysis:{trends:{leads:Object.fromEntries(leads.map(lead=>[lead,[{time_s:0,deviation_units:12},{time_s:300,deviation_units:-18}]]))}},
      source_report:{fragments:['合成 ST-T 文字']},calibration:{message:'合成未校准单位'},lead_system:{message:'合成导联'},measurement_protocol:{baseline:{label:'手工 ISO'}}};
  const response=(payload,status=200)=>({ok:status<400,status,headers:{get:()=> 'application/json'},json:async()=>payload});
  h.waveBody=(request,overrides={})=>{
    const q=request.url.searchParams,names=q.get('leads').split(','),basis=request.basis;
    return {...basis,start_s:Number(q.get('start')),duration_s:Number(q.get('duration')),sample_rate_hz:200,
      leads:Object.fromEntries(names.map(lead=>[lead,Array.from({length:2001},(_,i)=>Math.round((leads.indexOf(lead)+1)*10+Math.sin(i/80)*30+i/40))])),beats:[],...overrides};
  };
  const fetch=(raw,options)=>{
    const url=new URL(raw,'http://synthetic'),kind=url.pathname.startsWith('/api/cases/')?url.pathname.split('/').slice(4).join('/'):'health';
    const request={url,kind,options,basis:{...h.basis}};h.requests.push(request);
    if(kind==='waveform'||kind==='health'||kind==='annotations'&&options.method==='POST'||kind==='analysis-basis'&&h.holdNextBasis){
      const deferred=gate();Object.assign(request,{resolve:(payload,status=200)=>{
        if(payload===undefined)payload=kind==='waveform'?h.waveBody(request):kind==='analysis-basis'?request.basis:{saved:true};
        if(kind==='annotations'&&status<400)h.basis.analysis_revision++;
        deferred.resolve(response(payload,status));
      },reject:deferred.reject});
      if(kind==='waveform')h.waves.push(request);if(kind==='annotations')h.posts.push(request);
      if(kind==='analysis-basis'){h.holdNextBasis=false;h.basisReads.push(request);}
      return deferred.promise; // Deliberately ignores AbortSignal.
    }
    const q=url.searchParams,conflict=['analysis_basis','analysis_revision'].some(key=>q.has(key)&&q.get(key)!==String(h.basis[key]));
    if(conflict)return Promise.resolve(response({error:'波形或事件依据已变化，请重新加载后复核'},409));
    return Promise.resolve(response(kind==='analysis-basis'?{...h.basis}:body(kind)));
  };
  const context=h.ctx=vm.createContext({state,$,$$,fetch,ECGReadRequests:Reads.create(),ECGAnalysisConsistency:C,AbortController,URLSearchParams,
    ALL_LEADS:leads,withPhi:x=>x,escapeHtml:String,formatElapsed:v=>`D1 ${Number(v).toFixed(0)}s`,fmtNumber:String,
    document:{body:{classList:classes()}},window:{scrollTo(){}},ECGReviewTools:{shouldConfirmNavigation:()=>false},
    markWorkflowVisited(){},renderCaseWorkflow(){},updateWaveformModeUI(){},updateZoomControls(){},
    loadWaveform:async()=>{},loadScatter:async()=>{},enterWaveformFullscreen:async()=>{state.waveformExpanded=true;},
    ECGReportConsistency:{receive(){}},clinicalWorkflow:{receive(){},writable:()=>true,refresh:async()=>{},allowLeave:()=>true},
    toast:message=>h.toasts.push(message),handleError:error=>h.errors.push(error),
    setTimeout:fn=>{const timer={fn};h.timers.push(timer);return timer;},clearTimeout:timer=>{if(timer)timer.cancelled=true;},
    clearWaveformSurface:key=>{state[key]=null;},
    analysisReadStatus:(selector,message,retry,cancel)=>Object.assign($(selector),{textContent:message,retry,cancel,hidden:!message}),
  });
  const run=(from,to)=>vm.runInContext(app.slice(app.indexOf(from),app.indexOf(to)),context);
  vm.runInContext(layout,context);
  run('const CASE_IDENTITY_FIELDS =','function renderCaseIdentity(');
  run('async function api(','\nfunction toast(');
  run('function sttSubmittedDraftIsUnchanged(','function allowSttCaseSelection(');
  run('function sttReviewLayout(','function renderSttOverview(');
  run('function renderSttMeasurements(','function renderSttWaveform(');
  run('async function loadStt(','function setEditMode(');
  run('function bindSttInteraction(','function bindScatterInteraction(');
  run('function goPage(','function waveformRequestLeads(');
  run('function waveformRequestLeads(','function persistPreviewLeads(');
  run('function finishWaveformFullscreenExit(','async function enterWaveformFullscreen(');
  vm.runInContext(`
    const originalSttCapability=renderSttCapability,originalSttTrend=renderSttTrendRows;
    renderSttCapability=()=>{testRenders.capability++;originalSttCapability();};
    renderSttTrendRows=()=>{testRenders.trend++;originalSttTrend();};
    function renderSttOverview(){testRenders.overview++;}
    function renderSttWaveform(){testRenders.wave++;renderSttMeasurements();renderSttReviewContext();}
  `,Object.assign(context,{testRenders:h.renders}));
  context.bindSttInteraction();h.$=$;h.body=body;
  h.begin=async()=>{const count=h.waves.length,pending=context.loadStt();await tick();assert.equal(h.waves.length,count+1);return {pending,wave:h.waves.at(-1)};};
  h.load=async()=>{const next=await h.begin();next.wave.resolve();await next.pending;return next;};
  h.allDay=()=>Object.fromEntries(['#sttCandidateCount','#sttCandidateList','#sttTrendRows','#sttSourceNotes','#sttSafetyText'].map(key=>[key,[$(key).textContent,$(key).innerHTML]]));
  return h;
}
async function localAndEquivalent(){
  const h=harness();await h.load();
  const originalWave=json(h.state.sttWaveform),automatic=json(h.state.sttReview),allDay=h.allDay();
  const base=json(h.ctx.sttMeasurementValues());
  h.$('#sttReviewNote').value='未保存合成备注';h.$('#sttSignalChecked').checked=true;h.$('#sttFinding').value='ST 段压低候选';
  Object.assign(h.state,{sttIsoFraction:.29,sttJFraction:.56,sttMeasurementMs:80,leads:['I','III','V2']});
  const callCount=h.requests.length,next=await h.begin();
  assert.deepEqual(h.allDay(),allDay,'switching leads erased valid all-day evidence');
  assert.equal(h.state.sttWaveform,null);assert.equal(h.$('#sttReviewForm button[type="submit"]').disabled,true);
  assert.equal(h.$('#sttAnalysisStatus').parentElement,h.$('#sttWaveCanvasWrap'),'loading belongs inside the cleared waveform surface');
  assert.equal(h.$('#sttCurrentContext').dataset.state,'loading');
  assert.match(h.$('#sttCurrentContext').innerHTML,/I \/ III \/ V2/);assert.doesNotMatch(h.$('#sttCurrentContext').innerHTML,/相对差值/);
  next.wave.resolve();await next.pending;
  const kinds=h.requests.slice(callCount).map(request=>request.kind).sort();
  assert.deepEqual(kinds,['analysis-basis','analysis-basis','waveform'],'valid local refresh reread a whole-case resource');
  assert.equal(h.renders.capability,1);assert.equal(h.renders.trend,1);
  assert.deepEqual(json(h.state.sttReview),automatic);assert.deepEqual(h.allDay(),allDay);
  assert.equal(h.$('#sttReviewNote').value,'未保存合成备注');assert.equal(h.$('#sttSignalChecked').checked,true);
  assert.equal(h.$('#sttFinding').value,'ST 段压低候选');assert.equal(h.state.sttIsoFraction,.29);assert.equal(h.state.sttJFraction,.56);assert.equal(h.state.sttMeasurementMs,80);
  Object.assign(h.state,{leads:['II','V1','V5'],sttIsoFraction:.34,sttJFraction:.52,sttMeasurementMs:60});await h.load();
  assert.deepEqual(json(h.state.sttWaveform),originalWave,'roundtrip changed the raw waveform or its units');
  assert.deepEqual(json(h.ctx.sttMeasurementValues()),base,'same wave and cursors changed a manual measurement');
}
async function racesAndDebounce(){
  const h=harness();await h.load();const allDay=h.allDay();
  h.state.sttStart=10;h.state.leads=['II'];const older=await h.begin();
  h.state.sttStart=25;h.state.leads=['V1'];const newer=await h.begin();
  assert.equal(older.wave.options.signal.aborted,true);await older.pending;
  newer.wave.resolve();await newer.pending;older.wave.resolve();await tick();
  assert.equal(h.state.sttStart,25);assert.deepEqual(Object.keys(h.state.sttWaveform.leads),['V1']);assert.deepEqual(h.allDay(),allDay);
  h.state.sttStart=26;const failedOld=await h.begin();h.state.sttStart=27;const live=await h.begin();
  live.wave.resolve();await live.pending;failedOld.wave.reject(Error('late old failure'));await failedOld.pending;await tick();
  assert.equal(h.state.sttStart,27);assert.equal(h.$('#sttAnalysisStatus').textContent,'');
  const before=await h.begin();h.$('#sttTimeSlider').listeners.get('input')({target:{value:'60'}});
  assert.equal(h.state.sttStart,60);assert.equal(h.state.sttWaveform,null);assert.equal(h.$('#sttReviewForm button[type="submit"]').disabled,true);
  await h.ctx.saveSttReviewAnnotation();assert.match(h.toasts.at(-1),/尚未读取完成/);
  assert.equal(h.requests.some(request=>request.options.method==='POST'),false,'stale waveform was saved under the new time');
  before.wave.resolve();await before.pending;assert.equal(h.state.sttStart,60,'old completion won during slider debounce');
  h.timers.at(-1).fn();await tick();const newest=h.waves.at(-1);assert.equal(newest.url.searchParams.get('start'),'60.000');newest.resolve();await tick();
  assert.equal(h.ctx.sttWaveformIsCurrent(),true);assert.deepEqual(h.allDay(),allDay);
  // Even without a new load call, changes to any selection invalidate saves.
  h.state.leads=['V5'];assert.equal(h.ctx.sttWaveformIsCurrent(),false);
}
async function cancelRetryAndOtherConsumer(){
  const h=harness();await h.load();const allDay=h.allDay();h.state.sttStart=100;
  const old=await h.begin(),unrelated=h.ctx.api('/api/health',{readLane:'other-panel'});await tick();
  const other=h.requests.findLast(request=>request.kind==='health'),cancel=h.$('#sttAnalysisStatus').cancel;
  cancel();assert.equal(old.wave.options.signal.aborted,true);assert.equal(other.options.signal.aborted,false,'ST cancel aborted another reader');
  assert.match(h.$('#sttAnalysisStatus').textContent,/已取消/);assert.equal(h.$('#sttCurrentContext').dataset.state,'cancelled');
  assert.deepEqual(h.allDay(),allDay);const retry=h.$('#sttAnalysisStatus').retry,pending=retry();await tick();
  const fresh=h.waves.at(-1);assert.notEqual(fresh,old.wave);fresh.resolve();await pending;old.wave.resolve();await old.pending;await tick();
  assert.equal(h.state.sttStart,100);assert.equal(h.ctx.sttWaveformIsCurrent(),true);assert.equal(h.$('#sttAnalysisStatus').textContent,'');
  cancel();await retry();assert.equal(h.$('#sttAnalysisStatus').textContent,'','old controls overwrote the current result');
  other.resolve({ok:true});assert.equal((await unrelated).ok,true);
}
async function errorAndRetry(){
  const h=harness();await h.load();const allDay=h.allDay();h.state.sttStart=80;const failed=await h.begin();
  failed.wave.reject(Error('synthetic offline'));await assert.rejects(failed.pending,/offline/);
  assert.equal(h.state.sttWaveform,null);assert.deepEqual(h.allDay(),allDay);assert.equal(typeof h.$('#sttAnalysisStatus').retry,'function');
  const retry=h.$('#sttAnalysisStatus').retry();await tick();h.waves.at(-1).resolve();await retry;assert.equal(h.ctx.sttWaveformIsCurrent(),true);
  h.state.sttStart=81;const wrong=await h.begin();wrong.wave.resolve(h.waveBody(wrong.wave,{start_s:12}));await assert.rejects(wrong.pending,/时间窗或导联/);
  assert.equal(h.state.sttWaveform,null);assert.deepEqual(h.allDay(),allDay);
  const wrongLead=await h.begin();wrongLead.wave.resolve(h.waveBody(wrongLead.wave,{leads:{I:[0,2]}}));await assert.rejects(wrongLead.pending,/时间窗或导联/);
  assert.equal(h.state.sttWaveform,null);
  const incomplete=await h.begin();incomplete.wave.resolve({...h.basis,start_s:81});await incomplete.pending;
  assert.equal(h.ctx.sttWaveformIsCurrent(),false);assert.equal(h.state.sttWaveform,null);assert.equal(h.$('#sttReviewForm button[type="submit"]').disabled,true);
  assert.equal(typeof h.$('#sttAnalysisStatus').retry,'function');
}
async function savedBasisGuard(){
  const h=harness();await h.load();h.$('#sttReviewNote').value='draft kept after revision conflict';h.$('#sttSignalChecked').checked=true;
  h.basis.analysis_revision++;
  await assert.rejects(h.ctx.saveSttReviewAnnotation(),/依据.*变化/);
  assert.equal(h.requests.some(request=>request.kind==='annotations'&&request.options.method==='POST'),false,'stale analysis was saved');
  assert.equal(h.state.sttWaveform,null);assert.equal(h.state.sttEvidence,null);assert.equal(h.$('#sttReviewNote').value,'draft kept after revision conflict');
  assert.equal(h.$('#sttSignalChecked').checked,true);
}
async function saveBusyAndDrafts(){
  const h=harness();await h.load();h.$('#sttReviewNote').value='submitted note';h.$('#sttFinding').value='ST 段压低候选';h.$('#sttSignalChecked').checked=true;
  const original=json(h.ctx.sttMeasurementValues()),button=h.$('#sttReviewForm button[type="submit"]');
  h.holdNextBasis=true;const pending=h.ctx.saveSttReviewAnnotation();
  assert.equal(button.disabled,true);assert.equal(button.dataset.sttSaveState,'saving');assert.equal(button.textContent,'正在保存…');
  await h.ctx.saveSttReviewAnnotation();await tick();assert.equal(h.basisReads.length,1);assert.equal(h.posts.length,0,'basis check had not completed');
  h.$('#sttReviewNote').value='edited while checking basis';h.$('#sttFinding').value='T 波形态异常候选';h.$('#sttSignalChecked').checked=false;
  h.state.sttMeasurementMs=80;h.state.sttIsoFraction=.27;
  h.basisReads[0].resolve();await tick();assert.equal(h.posts.length,1);
  const payload=JSON.parse(h.posts[0].options.body);
  assert.equal(payload.label,'ST-T 人工复核：ST 段压低候选');assert.equal(payload.details.finding,'ST 段压低候选');
  assert.match(payload.note,/J\+60 ms/);assert.match(payload.note,/信号质量核对：已核对/);assert.match(payload.note,/submitted note/);
  assert.doesNotMatch(payload.note,/edited while checking basis/);
  for(const value of original)assert.match(payload.note,new RegExp(`${value.lead} ${value.delta>=0?'\\+':''}${value.delta.toFixed(0)}`));
  await h.ctx.saveSttReviewAnnotation();assert.equal(h.posts.length,1,'duplicate submit during POST was not suppressed');
  const otherLoad=await h.begin();otherLoad.wave.resolve();await otherLoad.pending;assert.equal(button.disabled,true,'parallel waveform completion enabled a saving button');
  h.$('#sttReviewNote').value='edited during POST';h.posts[0].resolve();await tick();
  assert.equal(button.disabled,true,'refresh reenabled a saving button');assert.equal(h.$('#sttReviewNote').value,'edited during POST');
  h.waves.at(-1).resolve();await pending;
  assert.equal(h.state.sttSaving,null);assert.equal(button.disabled,false);assert.equal(button.dataset.sttSaveState,'idle');
  assert.equal(h.$('#sttReviewNote').value,'edited during POST');assert.equal(h.$('#sttFinding').value,'T 波形态异常候选');assert.equal(h.$('#sttSignalChecked').checked,false);
  assert.equal(h.state.sttIsoFraction,.27);assert.equal(h.state.sttMeasurementMs,80);
  // A finding/checkbox change alone keeps the note too, so it remains a draft.
  h.$('#sttSignalChecked').checked=true;const changed=h.ctx.saveSttReviewAnnotation();await tick();h.$('#sttFinding').value='非特异性 ST-T 改变';h.posts.at(-1).resolve();await tick();h.waves.at(-1).resolve();await changed;
  assert.equal(h.$('#sttReviewNote').value,'edited during POST');
  const unchanged=h.ctx.saveSttReviewAnnotation();await tick();h.posts.at(-1).resolve();await tick();h.waves.at(-1).resolve();await unchanged;
  assert.equal(h.$('#sttReviewNote').value,'','unchanged submitted note was not cleared');
}
async function savedDraftAfterSameCasePageChange(){
  for(const mode of ['unchanged','later-note','later-measurement','different-window']){
    const h=harness();await h.load();h.$('#sttReviewNote').value='submitted before same-case page change';
    const waveCount=h.waves.length,pending=h.ctx.saveSttReviewAnnotation();await tick();
    assert.equal(h.posts.length,1);h.state.currentPage='dashboard'; // Synthetic page-state fixture only.
    if(mode==='later-note')h.$('#sttReviewNote').value='newer unsaved note';
    if(mode==='later-measurement')h.state.sttMeasurementMs=80;
    if(mode==='different-window')h.state.sttStart=40;
    h.posts[0].resolve();await pending;
    assert.equal(h.state.sttSaving,null);assert.equal(h.state.currentPage,'dashboard');
    assert.equal(h.waves.length,waveCount,'successful hidden-page acknowledgement read a hidden waveform');
    assert.match(JSON.parse(h.posts[0].options.body).note,/submitted before same-case page change/);
    const expected=mode==='unchanged'?'':mode==='later-note'?'newer unsaved note':'submitted before same-case page change';
    assert.equal(h.$('#sttReviewNote').value,expected,'saved acknowledgement consumed a later draft or missed its unchanged submission');
    if(mode==='unchanged')assert.match(h.toasts.at(-1),/已保存/);
    if(mode==='later-note'||mode==='later-measurement')assert.match(h.toasts.at(-1),/后续草稿已保留/);
  }
}
async function saveFailureAndCaseSwitch(){
  const h=harness();await h.load();h.$('#sttReviewNote').value='retry draft';
  const failed=h.ctx.saveSttReviewAnnotation();await tick();h.posts[0].reject(Error('synthetic POST offline'));await assert.rejects(failed,/POST offline/);
  assert.equal(h.state.sttSaving,null);assert.equal(h.$('#sttReviewNote').value,'retry draft');assert.equal(h.$('#sttReviewForm button[type="submit"]').disabled,false);
  const retry=h.ctx.saveSttReviewAnnotation();await tick();assert.equal(h.posts.length,2);h.posts[1].resolve();await tick();h.waves.at(-1).resolve();await retry;
  assert.equal(h.$('#sttReviewNote').value,'');
  const reread=h.ctx.saveSttReviewAnnotation();await tick();h.posts.at(-1).resolve();await tick();h.waves.at(-1).reject(Error('saved but reload offline'));await assert.rejects(reread,/reload offline/);
  assert.equal(h.state.sttSaving,null);assert.equal(h.$('#sttReviewNote').value,'','empty submitted note changed after a failed read');
  const reload=h.$('#sttAnalysisStatus').retry();await tick();h.waves.at(-1).resolve();await reload;
  h.$('#sttReviewNote').value='keep note on reread failure';const save=h.ctx.saveSttReviewAnnotation();await tick();h.posts.at(-1).resolve();await tick();h.waves.at(-1).reject(Error('saved but reread offline'));await assert.rejects(save,/reread offline/);
  assert.equal(h.state.sttSaving,null);assert.equal(h.$('#sttReviewNote').value,'keep note on reread failure');
  for(const phase of ['basis','post','refresh']){
    const old=harness();await old.load();old.$('#sttReviewNote').value='old case';if(phase==='basis')old.holdNextBasis=true;
    const pending=old.ctx.saveSttReviewAnnotation();await tick();
    const refresh=gate();if(phase==='refresh'){old.ctx.clinicalWorkflow.refresh=()=>refresh.promise;old.posts[0].resolve();await tick();}
    old.state.caseId='synthetic-b';old.state.caseRequestId++;old.state.sttSaving={caseId:'synthetic-b',caseToken:old.state.caseRequestId};
    const button=old.$('#sttReviewForm button[type="submit"]');button.disabled=true;button.textContent='new case saving';button.dataset.sttSaveState='saving';
    old.$('#sttReviewNote').value='new case draft';
    if(phase==='basis')old.basisReads[0].resolve();else if(phase==='post')old.posts[0].resolve();else refresh.resolve();await pending;
    assert.equal(button.disabled,true);assert.equal(button.textContent,'new case saving');assert.equal(button.dataset.sttSaveState,'saving');
    assert.equal(old.$('#sttReviewNote').value,'new case draft');assert.equal(old.state.sttSaving.caseId,'synthetic-b');
    if(phase==='basis')assert.equal(old.posts.length,0,'late basis check posted to a different case');
  }
}
async function basisInvalidation(){
  for(const mode of ['initial','child','final','missing']){
    const h=harness();await h.load();const old=h.state.sttEvidence;h.state.sttStart=40;
    if(mode==='initial')h.basis.analysis_revision++;
    if(mode==='missing')h.basis={};
    if(mode==='missing'){
      await assert.rejects(h.ctx.loadStt(),/依据缺失/);assert.equal(h.state.sttEvidence,null);continue;
    }
    const next=await h.begin();
    if(mode==='initial'){
      assert.equal(h.state.sttEvidence,null);assert.equal(h.$('#sttCandidateCount').textContent,'—');
      next.wave.resolve();await next.pending;assert.equal(h.renders.capability,2);assert.notEqual(h.state.sttEvidence,old);
    }else{
      if(mode==='final')h.basis.analysis_revision++;
      next.wave.resolve(h.waveBody(next.wave,mode==='child'?{analysis_revision:9}:{}));await assert.rejects(next.pending,/依据.*变化/);
      assert.equal(h.state.sttWaveform,null);assert.equal(h.state.sttEvidence,null);assert.equal(h.state.sttReview,null);assert.equal(h.$('#sttCandidateCount').textContent,'—');
    }
  }
}
async function detachedCallbacks(){
  for(const mode of ['case','page','workspace']){
    for(const failed of [false,true]){
      const h=harness();await h.load();h.state.sttStart=45;const pending=await h.begin(),cancel=h.$('#sttAnalysisStatus').cancel;
      if(mode==='case'){h.state.caseId='synthetic-b';h.state.caseRequestId++;h.state.caseData={replacement:true};}
      if(mode==='page')h.state.currentPage='review';
      if(mode==='workspace')h.state.workspaceEpoch='new-workspace';
      h.$('#sttAnalysisStatus').textContent='new page status';
      if(failed)pending.wave.reject(Error('late detached failure'));else pending.wave.resolve();
      await pending.pending;cancel();assert.equal(h.$('#sttAnalysisStatus').textContent,'new page status');
      assert.equal(h.state.sttStart,45);assert.equal(h.state.sttWaveform,null);
    }
  }
}
async function fullscreenReturn(){
  const h=harness();await h.load();h.$('#sttReviewNote').value='return draft';h.$('#sttSignalChecked').checked=true;
  Object.assign(h.state,{sttIsoFraction:.27,sttJFraction:.62,sttMeasurementMs:80,start:12,duration:20,filter:'display'});
  const original=json(h.ctx.sttMeasurementValues()),chosen=json(h.state.leads),allDay=h.allDay();
  await h.ctx.openSttTwelveLead();assert.equal(h.state.currentPage,'review');assert.equal(h.ctx.waveformRequestLeads().length,12);
  h.state.start=90;h.state.leads=['I'];h.ctx.finishWaveformFullscreenExit();await tick();
  assert.equal(h.state.currentPage,'stt');assert.deepEqual(json(h.state.leads),chosen);assert.equal(h.state.sttMeasurementMs,80);
  assert.equal(h.state.start,12);assert.equal(h.state.duration,20);assert.equal(h.state.filter,'display');
  h.waves.at(-1).resolve();await tick();
  assert.equal(h.ctx.waveformRequestLeads().length,3);assert.deepEqual(json(h.ctx.sttMeasurementValues()),original);
  assert.equal(h.$('#sttReviewNote').value,'return draft');assert.equal(h.$('#sttSignalChecked').checked,true);assert.deepEqual(h.allDay(),allDay);
}
async function pendingTrendNavigation(){
  const environment=vm.createContext({});vm.runInContext(layout,environment);
  const attrs=new Map(),navigations=[],track={parentElement:{querySelector:()=>({textContent:'V1'})},getAttribute:key=>attrs.get(key),
    setAttribute:(key,value)=>attrs.set(key,value),removeAttribute:key=>attrs.delete(key),getBoundingClientRect:()=>({left:0,width:300})};
  track.closest=()=>track;const host=node(),listeners=new Map(),root={querySelector:selector=>selector==='#sttCurrentContext'?host:null,
    querySelectorAll:()=>[track],contains:()=>true,classList:classes(),addEventListener:(name,fn)=>listeners.set(name,fn)};
  const mounted=environment.ECGSttReviewLayout.mount({root,onLocate:value=>navigations.push(value)});
  mounted.render({caseId:'synthetic',status:'loading',message:'正在读取',navigation:{start_s:30,duration_s:10,total_s:300},leadNames:['V1'],measurementMs:80});
  assert.equal(attrs.get('role'),'button');listeners.get('click')({target:track,clientX:150});assert.equal(navigations[0].time_s,150,'single click waited for the pending waveform');
  mounted.clear('分析依据已变化');listeners.get('click')({target:track,clientX:150});assert.equal(navigations.length,1,'invalid-basis trend remained active');
}
(async()=>{
  await localAndEquivalent();await racesAndDebounce();await cancelRetryAndOtherConsumer();await errorAndRetry();await savedBasisGuard();await saveBusyAndDrafts();await savedDraftAfterSameCasePageChange();await saveFailureAndCaseSwitch();await basisInvalidation();
  await detachedCallbacks();await fullscreenReturn();await pendingTrendNavigation();
  console.log('ST local updates: equivalent raw output, retained all-day DOM/drafts, lead/time races, slider/save guard, scoped cancel/retry, duplicate-save suppression, slow-basis content snapshot, changed-draft preservation, POST/reload retry and 3 detached save phases, incomplete-wave and pre-save basis guards, 4 identity failures, 6 detached callbacks, 3→12→3 return and immediate trend click passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
