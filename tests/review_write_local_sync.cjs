'use strict';
// Shipped adapter/save synchronizer, disposable protocol data, no clinical I/O.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const C=require('../static/js/analysis-consistency.js'),source=fs.readFileSync(process.env.ECG_APP_SOURCE||'static/js/app.js','utf8');
const declarations=[...source.matchAll(/^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(/gm)];
function actual(name){const i=declarations.findIndex(x=>x[1]===name);assert(i>=0,name);return source.slice(declarations[i].index,declarations[i+1]?.index??source.length);}
const clone=x=>JSON.parse(JSON.stringify(x)),tick=()=>new Promise(resolve=>setImmediate(resolve));
const gate=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {resolve,reject,promise};};
const uuid='00000000-0000-4000-8000-000000000001',scope={case_id:'engineering-A',analysis_basis:'source-A',analysis_revision:7,beat_revision:2};
const sttBody=()=>({sample_index:200,details:{kind:'ST',reviewed:true,submission_id:uuid,review_scope:{...scope}}});
const rhythmBody=()=>({...scope,request_id:uuid,revision:3,confirmed:true,operation:'save',document:{episodes:[],bookmarks:{}}});
function adapter(){
  const held=gate(),events=[],fetches=[],state={caseId:scope.case_id,caseRequestId:9,workspaceEpoch:'engineering',currentPage:'stt',report:{version:2},reportEvidenceEpoch:0};
  const ctx=vm.createContext({state,fetch:(path,options)=>{events.push('fetch');fetches.push({path,options});return held.promise;},
    ECGReadRequests:{clear(){events.push('clear-reads');},read:(_,__,reader)=>reader()},ECGChartInspection:{clearRenderers(){events.push('clear-pixels');}},ECGFullRecordRetain:{invalidate(){events.push('invalidate-retain');}},
    overviewWorkbench:{invalidateAfterWrite(){events.push('invalidate-overview');}},clinicalWorkflow:{refresh:async()=>events.push('workflow')},toast(){}});
  vm.runInContext(actual('api'),ctx);
  const response=(body={ok:true},status=200)=>({ok:status<400,status,headers:{get:()=> 'application/json'},json:async()=>body});
  return {ctx,state,events,fetches,resolve:(body,status)=>held.resolve(response(body,status)),reject:held.reject};
}
async function knownAdapter(){
  for(const [kind,method,suffix,body] of [['stt','POST','annotations',sttBody()],['stt','PUT','annotations/21',sttBody()],['rhythm','PUT','rhythm-review',rhythmBody()]]){
    const f=adapter(),pending=f.ctx.api('/api/cases/'+scope.case_id+'/'+suffix,{method,body:JSON.stringify(body),reviewWrite:kind});
    assert.deepEqual(f.events,['fetch'],'known review save erased signal before commit');assert.equal('reviewWrite' in f.fetches[0].options,false,'private option leaked into fetch');f.resolve();await pending;
    assert.deepEqual(f.events,['fetch','clear-reads'],'success must cancel old reads without erasing pixels');assert.equal(f.state.reportStale,true);assert.equal(f.state.reportEvidenceEpoch,1);
  }
}
async function unknownAdapter(){
  const variants=[['annotations',{method:'POST',body:JSON.stringify(sttBody())}],['beat-overrides',{method:'POST',body:JSON.stringify(sttBody()),reviewWrite:'stt'}],['annotations/21',{method:'DELETE',body:JSON.stringify(sttBody()),reviewWrite:'stt'}],['annotations/x',{method:'PUT',body:JSON.stringify(sttBody()),reviewWrite:'stt'}],['annotations',{method:'POST',body:'{',reviewWrite:'stt'}],
    ['annotations',{method:'POST',body:JSON.stringify({...sttBody(),details:{...sttBody().details,reviewed:false}}),reviewWrite:'stt'}],['annotations',{method:'POST',body:JSON.stringify({...sttBody(),details:{...sttBody().details,review_scope:{...scope,case_id:'other'}}}),reviewWrite:'stt'}],
    ['rhythm-review',{method:'PUT',body:JSON.stringify({...rhythmBody(),request_id:'bad'}),reviewWrite:'rhythm'}],['rhythm-review',{method:'PUT',body:JSON.stringify({...rhythmBody(),beat_revision:-1}),reviewWrite:'rhythm'}],['rhythm-review',{method:'PUT',body:JSON.stringify({...rhythmBody(),confirmed:false}),reviewWrite:'rhythm'}]];
  for(const [suffix,options] of variants){const f=adapter(),pending=f.ctx.api('/api/cases/'+scope.case_id+'/'+suffix,options);assert(f.events.includes('clear-pixels'));f.resolve();await pending;assert(f.events.includes('invalidate-overview'));}
}
async function failedAdapter(){for(const http of [false,true]){const f=adapter(),pending=f.ctx.api('/api/cases/'+scope.case_id+'/annotations',{method:'POST',body:JSON.stringify(sttBody()),reviewWrite:'stt'});assert.deepEqual(f.events,['fetch']);if(http)f.resolve({error:'conflict'},409);else f.reject(Error('response lost'));await assert.rejects(pending);assert(f.events.includes('clear-pixels'));assert(f.events.includes('invalidate-overview'));}}
function synchronizer(config={}){
  const old={analysis_basis:scope.analysis_basis,analysis_revision:7},fresh={analysis_basis:scope.analysis_basis,analysis_revision:8},events=[],requests=[],waveGate=gate();
  const receipt={event_id:'annotation:21',annotation_id:21,record_version:1,basis_version:'record-current',review_state:'reviewed',report_eligibility:{table:true,text:true,strip:true}};
  const annotation={id:21,details:{kind:'ST',submission_id:uuid,review_scope:{...scope}},stt_review_receipt:receipt};
  const oldCase={case_id:scope.case_id,clinical_identity:{...old}},oldTrend={...old,points:[{time_s:0,hr:70}]},oldReview={case_id:scope.case_id,...old,beat_revision:2,analysis:{trends:{leads:{II:[{time_s:0,deviation_units:1}]}}},automatic_candidates:{items:[{id:'candidate-A'}]},review_records:[]};
  const oldWave={...old,start_s:10,duration_s:7,sample_rate_hz:200,leads:{II:[1,2,3]}};
  const state={caseId:scope.case_id,caseRequestId:9,workspaceEpoch:'engineering',currentPage:'stt',privacyRequestId:0,sttRequestId:1,sttStart:10,sttDuration:7,caseData:oldCase,trend:oldTrend,sttReview:oldReview,sttWaveform:oldWave,sttWaveformSelection:{},sttRangeBridge:{sync(){events.push('range');}}};
  state.sttEvidence={caseId:scope.case_id,caseToken:9,workspaceEpoch:'engineering',includePhi:false,basis:{...old},caseData:oldCase,trend:oldTrend,review:oldReview};
  const selection={caseId:scope.case_id,caseToken:9,workspaceEpoch:'engineering',start:10,duration:7,leads:'II'},saved=clone(annotation);let owned=true,basisCalls=0;
  const caseData={case_id:scope.case_id,clinical_identity:{...fresh},beat_editor_history:{revision:2},review_workflow:{revision:8},report_workflow:{version:3,review_revision:8}},waveform={...fresh,start_s:10,duration_s:7,sample_rate_hz:200,leads:{II:[3,4,5]}};
  const api=async raw=>{
    const url=new URL(raw,'http://engineering'),kind=url.pathname.split('/').slice(4).join('/');requests.push(kind);
    if(kind==='analysis-basis'){basisCalls++;if(config.sourceChanged)return {...fresh,analysis_basis:'changed'};if(config.concurrent||config.endRace&&basisCalls>1)return {...fresh,analysis_revision:9};return {...fresh};}
    if(kind===''){if(config.beatChanged)caseData.beat_editor_history.revision=3;return caseData;}
    if(kind==='annotations'){const row=clone(annotation);if(config.badReceipt)row.stt_review_receipt.review_state='stale';if(config.badUuid)row.details.submission_id='another-intent';return {items:[{id:1,details:{kind:'ST'},stt_review_receipt:{review_state:'stale',report_eligibility:{table:false,text:false,strip:false}}},row]};}
    if(kind==='waveform'){await waveGate.promise;if(config.badWindow)return {...waveform,start_s:20};if(config.badLeads)return {...waveform,leads:{V1:[1,2,3]}};return waveform;}
    throw Error('Unexpected whole-case endpoint '+kind);
  };
  const ctx=vm.createContext({state,ECGAnalysisConsistency:C,api,URLSearchParams,withPhi:x=>x,sttSelectionMatches:s=>owned&&state.currentPage==='stt'&&s.caseId===state.caseId&&s.caseToken===state.caseRequestId&&s.start===state.sttStart&&s.duration===state.sttDuration,
    sttSelectionSnapshot:()=>({...selection}),preserveCurrentIdentity:()=>events.push('privacy'),ECGReportConsistency:{receive:(_,value)=>events.push(['report',value.version])},clinicalWorkflow:{receive:value=>events.push(['workflow',value.revision])},renderSttOverview:()=>events.push('overview'),renderSttWaveform:()=>events.push('wave')});
  vm.runInContext(actual('sttReceiptsForSnapshot')+actual('syncSavedSttReview'),ctx);
  return {ctx,state,selection,old,oldCase,oldReview,oldTrend,oldWave,receipt,annotation,events,requests,waveGate,context:{selection,basis:old,savedAnnotation:saved},run:()=>ctx.syncSavedSttReview({selection,basis:old,savedAnnotation:saved},()=>owned),depart(){owned=false;},caseData};
}
async function snapshotReceipts(){
  const refused=['changedNote','unknownSibling','reportUseChanged','legacySelection'];
  for(const scenario of ['first','withSibling',...refused]){
    const f=synchronizer();
    const baseUse=(event_id,basis_version)=>({event_id,basis_version,table:false,text:false,strip:false});
    f.context.savedAnnotation.stt_review_receipt.report_use=baseUse('annotation:21','record-current');
    const raw=clone(f.context.savedAnnotation);delete raw.stt_review_receipt;
    const sib={id:3,details:{kind:'ST',physician_note:'prior'}},sibling={...sib,stt_review_receipt:{event_id:'annotation:3',basis_version:'prior-basis',review_state:'stale',report_use:baseUse('annotation:3','prior-basis')}};
    f.caseData.report_workflow.composition={stt_report_use:[]};f.caseData.annotations=[raw];
    if(scenario!=='first'){f.caseData.annotations.push(clone(sib));if(scenario!=='unknownSibling')f.oldReview.review_records.push(sibling);}
    if(scenario==='changedNote')f.caseData.annotations[1].details.physician_note='external change';
    if(scenario==='reportUseChanged')f.caseData.report_workflow.composition.stt_report_use.push({...baseUse('annotation:3','prior-basis'),text:true});
    if(scenario==='legacySelection')f.caseData.report_workflow.composition={selected_events:[{event_id:'annotation:3'}]};
    const pending=f.run();f.waveGate.resolve();assert.equal(await pending,true,scenario);
    assert.equal(f.requests.includes('annotations'),refused.includes(scenario),scenario);
    if(scenario==='withSibling')assert.equal(f.state.sttReview.review_records[1].stt_review_receipt.review_state,'stale');
  }
}
async function incrementalSuccess(){
  const f=synchronizer(),oldInputs=clone({review:f.oldReview,trend:f.oldTrend,wave:f.oldWave,case:f.oldCase}),pending=f.run();await tick();
  assert.equal(f.state.sttWaveform,f.oldWave);assert.equal(f.state.sttReview,f.oldReview);assert.deepEqual(f.events,[],'in-flight sync cleared or repainted evidence');f.waveGate.resolve();assert.equal(await pending,true);
  assert.equal(f.state.sttReview.analysis,f.oldReview.analysis,'automatic analysis was recomputed/copied');assert.equal(f.state.trend.points,f.oldTrend.points);assert.notEqual(f.state.sttReview,f.oldReview);assert.notEqual(f.state.trend,f.oldTrend);assert.notEqual(f.state.sttWaveform,f.oldWave);
  assert.equal(f.state.sttReview.analysis_revision,8);assert.equal(f.state.sttReview.review_records.length,2);assert.equal(f.state.sttReview.review_records[0].stt_review_receipt.review_state,'stale','old review silently re-signed');assert.deepEqual(clone({review:f.oldReview,trend:f.oldTrend,wave:f.oldWave,case:f.oldCase}),oldInputs,'old server response was relabelled');
  assert.equal(f.requests.filter(x=>x==='analysis-basis').length,2);assert.deepEqual(f.requests.filter(x=>x!=='analysis-basis').sort(),['','annotations','waveform']);assert(f.events.some(x=>Array.isArray(x)&&x[0]==='report'&&x[1]===3));
}
async function rejectTransition(scenario){const f=synchronizer({[scenario]:true}),pending=f.run();f.waveGate.resolve();if(scenario==='endRace')await assert.rejects(pending,/依据已变化/);else assert.equal(await pending,false);assert.equal(f.state.sttReview,f.oldReview);assert.equal(f.state.sttWaveform,f.oldWave);assert.deepEqual(f.events,[],'rejected transition published retained evidence as current');}
async function departed(){const f=synchronizer(),pending=f.run();await tick();f.depart();f.waveGate.resolve();await assert.rejects(pending,/已取消/);assert.equal(f.state.sttReview,f.oldReview);assert.deepEqual(f.events,[]);}
async function finishFallback(){for(const mode of ['normal','uncertain','reconciled','rejected']){
  const events=[],state={sttDraftRevision:0,sttRangeReviewed:null,sttLastSavedEvent:null,sttSelectedCandidate:null,sttEditingRecord:null};
  const ctx=vm.createContext({state,$:()=>({value:''}),sttSubmittedDraftIsUnchanged:()=>true,sttSelectionMatches:()=>true,sttDraftState:()=>({}),syncSavedSttReview:async()=>{events.push('incremental');return mode!=='rejected';},clinicalWorkflow:{refresh:async()=>events.push('refresh')},clearSttEvidence:()=>events.push('clear'),setSttWindowState:()=>events.push('loading'),loadStt:async()=>events.push('full-read'),renderSttCandidateSelection(){},renderSttRecordList(){},toast(){}});
  vm.runInContext(actual('finishSttReviewSave'),ctx);await ctx.finishSttReviewSave({selection:{caseId:'engineering-A'},draft:{},uncertainSave:mode==='uncertain'},()=>true,mode==='reconciled');if(mode==='normal')assert.deepEqual(events,['incremental']);else{assert(events.includes('full-read'));assert(events.includes('clear'));if(mode!=='rejected')assert(!events.includes('incremental'));}
}}
async function finishReadFailure(){
  const events=[],state={sttDraftRevision:0,sttLastSavedEvent:null,sttSelectedCandidate:null,sttEditingRecord:null};let retry;
  const ctx=vm.createContext({state,$:()=>({value:'unsaved later note'}),sttSubmittedDraftIsUnchanged:()=>false,sttSelectionMatches:()=>true,
    syncSavedSttReview:async()=>{throw Error('display offline');},clearSttEvidence:()=>events.push('clear'),setSttWindowState:status=>events.push(status),
    clinicalWorkflow:{refresh:async()=>events.push('refresh')},loadStt:async()=>events.push('full-read'),analysisReadStatus:(_,message,fn)=>{assert.match(message,/已保存/);retry=fn;}});
  vm.runInContext(actual('finishSttReviewSave'),ctx);
  await assert.rejects(ctx.finishSttReviewSave({selection:{caseId:'engineering-A'},draft:{}},()=>true),/复核已保存.*display offline/);
  assert.deepEqual(events,['clear','error'],'a display failure automatically repeated the whole read');assert.equal(typeof retry,'function');await retry();assert.deepEqual(events,['clear','error','full-read']);
}
async function savedBaseOrder(){
  for(const later of [false,true]){
    const nodes=new Map(),node=key=>{if(!nodes.has(key))nodes.set(key,{value:'',checked:false});return nodes.get(key);};
    node('#sttReviewNote').value=later?'newer unsaved note':'submitted note';node('#sttEpisodeStart').value='100';node('#sttEpisodeEnd').value='180';
    const target={item:{id:'first',start_s:100,end_s:180,leads:['I']},scope:{...scope}},next={id:'second',start_s:220,end_s:320,leads:['V2'],kind:'t_low_flat'};
    const state={caseId:scope.case_id,sttDraftRevision:later?2:1,sttDraftDirty:later,sttSelectedCandidate:target,sttEditingRecord:null,sttDuration:10,sttReview:{...scope},sttSaving:null};
    let confirms=0;
    const ctx=vm.createContext({state,$:node,ALL_LEADS:['I','II','V1','V2','V5'],window:{confirm(){confirms++;return false;}},
      sttDraftState:()=>({note:node('#sttReviewNote').value,start:node('#sttEpisodeStart').value,end:node('#sttEpisodeEnd').value}),
      sttSubmittedDraftIsUnchanged:()=>!later,sttSelectionMatches:()=>true,syncSavedSttReview:async()=>true,
      renderSttCandidateSelection(){const item=state.sttSelectedCandidate?.item;node('#sttEpisodeStart').value=item?String(item.start_s):'';node('#sttEpisodeEnd').value=item?String(item.end_s):'';},
      renderSttRecordList(){},renderSttCapability(){},sttSetResultCodes:codes=>{state.codes=codes;},setSttStart:value=>{state.sttStart=value;},
      ECGSttReviewLayout:{receiptText:()=> 'saved',candidateKind:item=>item?.kind},clinicalWorkflow:{refresh:async()=>{}},toast(){}});
    vm.runInContext([actual('sttReviewHasUnsavedNote'),actual('sttSetReviewTarget'),actual('finishSttReviewSave')].join('\n'),ctx);
    state.sttSaving={};ctx.sttSetReviewTarget(next);assert.equal(state.sttSelectedCandidate,target,'pending save accepted another candidate');assert.equal(confirms,0);state.sttSaving=null;
    await ctx.finishSttReviewSave({selection:{caseId:scope.case_id},draft:{},target,savedAnnotation:{stt_review_receipt:{event_id:'annotation:1'}}},()=>true);
    if(later){assert.equal(node('#sttReviewNote').value,'newer unsaved note');assert.equal(state.sttSelectedCandidate,target);assert.equal(state.sttDraftDirty,true);assert.equal(ctx.sttReviewHasUnsavedNote(),true);}
    else{assert.equal(state.sttDraftBase,JSON.stringify(ctx.sttDraftState()),'saved baseline captured bounds before acknowledged target was cleared');assert.equal(ctx.sttReviewHasUnsavedNote(),false);ctx.sttSetReviewTarget(next);assert.equal(confirms,0,'next candidate was mistaken for an unsaved edit');assert.equal(state.sttSelectedCandidate.item.id,'second');assert.deepEqual(JSON.parse(JSON.stringify(state.codes)),['t_low_flat']);assert.equal(node('#sttEpisodeStart').value,'220');}
  }
}
const cases={'snapshot-receipts':snapshotReceipts,'known-adapter':knownAdapter,'unknown-adapter':unknownAdapter,'failed-adapter':failedAdapter,'incremental-success':incrementalSuccess,'departed':departed,'finish-fallback':finishFallback,'finish-read-failure':finishReadFailure,'save-base-order':savedBaseOrder,...Object.fromEntries(['sourceChanged','concurrent','endRace','beatChanged','badReceipt','badUuid','badWindow','badLeads'].map(name=>[name,()=>rejectTransition(name)]))};
(async()=>{const scenario=process.argv[2];if(scenario){assert(cases[scenario],scenario);await cases[scenario]();}else for(const run of Object.values(cases))await run();process.stdout.write('review-write local synchronization checks passed\n');})().catch(error=>{console.error(error);process.exitCode=1;});
