'use strict';
// Actual app save functions, synthetic native/math receipts. No clinical I/O.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const C=require('../static/js/analysis-consistency.js');
const source=fs.readFileSync('static/js/app.js','utf8');
const section=source.slice(source.indexOf('const sttMeanSubmissionIntents ='),source.indexOf('function setEditMode('));
const copy=x=>JSON.parse(JSON.stringify(x)),tick=()=>new Promise(r=>setImmediate(r));
const gate=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {resolve,promise};};
function fixture(config={}){
  const nodes=new Map(),node=()=>({value:'',checked:false,focus(){}}),$=key=>{if(!nodes.has(key))nodes.set(key,node());return nodes.get(key)};
  $('#sttFinding').value='无法判读';$('#sttReviewNote').value='synthetic mean receipt';
  const scope={case_id:'math-a',analysis_basis:'source-math',analysis_revision:4,beat_revision:2,client_case_token:7,workspace_epoch:'math-workspace'};
  const result={schema_version:'stt-range-mean-v1',scope,server_identity:{case_id:scope.case_id,analysis_basis:scope.analysis_basis,analysis_revision:4,beat_revision:2},
    range:{start_sample:1200,end_sample:25200,start_s:6,end_s:126,duration_s:120,half_open:true},
    method_profile:{id:'raw-200hz-fixed16s-st-perbeat-mean-v1',sample_rate_hz:200,measurement_ms:60,
      unit_label:'u',calibration_verified:false,aggregate:'arithmetic_mean_of_used_per_beat_st_minus_baseline'},
    counts:{detected_count:120,used_count:112,excluded_count:6,missing_count:2},
    leads:[{lead:'II',mean_units:-12.25,used_count:112,excluded_count:6,missing_count:2}],
    coverage:{coverage_is_signal_quality:false},result_digest:'synthetic-digest',
    provenance:{release:config.receipt||'compiled-math',source_sha:'synthetic-frozen-source'},
    blocks:[{private_detail:'must-not-be-stored'}]};
  const state={caseId:'math-a',caseRequestId:7,workspaceEpoch:'math-workspace',currentPage:'stt',
    sttStart:0,sttDuration:10,sttMeasurementMs:60,sttIsoFraction:.34,sttJFraction:.52,sttRequestId:1,
    leads:['II'],sttRangeSubmission:null,sttSaving:null,caseData:{technical:{duration_seconds_raw:640}},
    sttWaveform:{sample_rate_hz:200},sttEvidence:{basis:{analysis_basis:'source-math',analysis_revision:4}},
    sttRangeReviewed:{generation:1}};
  let accepted=state.sttRangeReviewed,snapshot=result,snapshots=0,uuids=0,postAttempts=0,postFailure=true;
  const calls=[],cleared=[],notices=[],rows=[];
  const server={case_id:'math-a',analysis_basis:'source-math',analysis_revision:4,beat_revision:2};
  let sourceFault=false,readFault=false,current=true,basisFault=false;
  const api=async(path,options={})=>{
    const u=new URL(path,'http://math'),kind=u.pathname.split('/').at(-1),call={path,kind,...options};calls.push(call);
    if(config.intercept)await config.intercept(call,state,server);
    if(kind==='analysis-basis'){
      if(basisFault)throw Error('basis read offline');
      if(u.searchParams.has('analysis_revision')&&Number(u.searchParams.get('analysis_revision'))!==server.analysis_revision)throw Error('分析依据已变化 409');
      return {analysis_basis:server.analysis_basis,analysis_revision:server.analysis_revision};
    }
    if(kind==='rhythm-review'){
      if(readFault)throw Error('reconcile offline');
      if(sourceFault||u.searchParams.get('analysis_basis')!==server.analysis_basis||Number(u.searchParams.get('beat_revision'))!==server.beat_revision)throw Error('来源或心搏版本已变化 409');
      if(u.searchParams.has('analysis_revision')&&Number(u.searchParams.get('analysis_revision'))!==server.analysis_revision)throw Error('读取期间依据已变化 409');
      return {...server,revision:0,document:{episodes:[],bookmarks:{}}};
    }
    if(kind==='annotations'&&options.method==='POST'){
      postAttempts++;const payload=JSON.parse(options.body);
      if(config.neverCommitted&&postFailure){postFailure=false;throw Error('POST connection lost');}
      const row={id:rows.length+1,case_id:state.caseId,...payload};rows.push(copy(row));server.analysis_revision++;
      if(config.mutateStored)config.mutateStored(rows[0]);
      if(config.postGate)await config.postGate.promise;
      if(config.afterCommit)config.afterCommit(state,server);
      if(config.responseLost&&postFailure){postFailure=false;throw Error('POST response lost');}
      return config.badResponse?{id:row.id}:copy(row);
    }
    if(kind==='annotations'){
      if(readFault)throw Error('annotation read offline');
      return {items:copy(rows)};
    }
    throw Error('unexpected '+kind);
  };
  const bridge={snapshotForSave(){snapshots++;if(config.snapshotThrows&&snapshots>1)throw Error('snapshot stale');return config.pointOnly?null:snapshot;},
    clearAfterSave(value){cleared.push(value);if(state.sttRangeReviewed!==accepted)return false;state.sttRangeReviewed=null;return true;}};
  state.sttRangeBridge=bridge;
  const ctx=vm.createContext({state,$,URLSearchParams,ECGAnalysisConsistency:C,api,
    crypto:{randomUUID:()=>`00000000-0000-4000-8000-${String(++uuids).padStart(12,'0')}`},
    clinicalWorkflow:{writable:()=>true,refresh:async()=>{if(config.refreshFail)throw Error('refresh failed');}},
    toast:text=>notices.push(text),updateSttSaveState:()=>{},
    sttWaveformIsCurrent:()=>current,sttSelectionSnapshot:()=>({caseId:state.caseId,caseToken:state.caseRequestId,workspaceEpoch:state.workspaceEpoch,start:state.sttStart,duration:state.sttDuration,leads:'II'}),
    sttSelectionMatches:s=>s.caseId===state.caseId&&s.caseToken===state.caseRequestId&&s.workspaceEpoch===state.workspaceEpoch&&s.start===state.sttStart&&s.duration===state.sttDuration&&state.currentPage==='stt',
    sttSubmittedDraftIsUnchanged:d=>d.note===$('#sttReviewNote').value&&d.finding===$('#sttFinding').value&&d.qualityChecked===$('#sttSignalChecked').checked,
    sttMeasurementValues:()=>[{lead:'II',delta:-10}],sttVisibleLeads:()=>['II'],sttLandmarkFractions:()=>({j:.52}),
    clearSttEvidence:()=>{},setSttWindowState:()=>{},analysisReadStatus:()=>{},loadStt:async()=>{current=true;}});
  vm.runInContext(section,ctx);
  return {ctx,state,$,calls,cleared,notices,rows,server,result,
    save:()=>ctx.saveSttReviewAnnotation(),posts:()=>postAttempts,snapshots:()=>snapshots,uuids:()=>uuids,
    setReadFault:value=>readFault=value,setCurrent:value=>current=value,setBasisFault:value=>basisFault=value,
    setSourceFault:value=>sourceFault=value,newMean:()=>{state.sttRangeReviewed={generation:2};snapshot=copy(result);},
    currentSnapshot:()=>snapshot};
}
const cases={
  'complete-compact-grid-and-receipt':async()=>{
    for(const receipt of ['compiled-native','static-math']){
      const f=fixture({receipt});await f.save();const p=JSON.parse(f.calls.find(x=>x.method==='POST').body);
      assert.equal(p.sample_index,1200);assert.equal(p.details.end_sample,25199);assert.equal(p.details.point_measurement_sample_index,1040);
      assert.equal(p.details.range_statistics.blocks,undefined);assert.equal(p.details.range_statistics.provenance.release,receipt);
      const expected=copy(f.result);delete expected.blocks;assert.deepEqual(p.details.range_statistics,expected);
      assert.match(p.details.submission_id,/^00000000-0000-4000-8000-/);assert.strictEqual(f.cleared[0],f.result);
    }
  },
  'response-lost-read-only-ack':async()=>{
    const f=fixture({responseLost:true});await f.save();assert.equal(f.posts(),1);assert.equal(f.rows.length,1);
    assert.equal(f.state.sttRangeSubmission.saved,true);assert.equal(f.state.sttRangeSubmission.uncertain,false);
    assert.equal(f.$('#sttReviewNote').value,'');assert.strictEqual(f.cleared[0],f.result);
    const reads=f.calls.filter(x=>x.kind==='rhythm-review');assert.equal(reads.length,2);
    assert.equal(new URL(reads[0].path,'http://math').searchParams.has('analysis_revision'),false);
    assert.equal(new URL(reads[1].path,'http://math').searchParams.get('analysis_revision'),'5');
    assert.equal(f.rows[0].details.range_statistics.scope.analysis_revision,4);
  },
  'reconciliation-offline-keeps-uuid-draft':async()=>{
    const f=fixture({responseLost:true});f.setReadFault(true);
    await assert.rejects(f.save(),/未重复提交/);assert.equal(f.posts(),1);
    assert.equal(f.$('#sttReviewNote').value,'synthetic mean receipt');assert.equal(f.state.sttRangeSubmission.uncertain,true);
    assert.equal(f.state.sttSaving,null);assert.equal(f.cleared.length,0);
    const id=f.state.sttRangeSubmission.id;f.setReadFault(false);f.setCurrent(false);
    await f.save();assert.equal(f.posts(),1);assert.equal(f.state.sttRangeSubmission.id,id);
    assert.equal(f.snapshots(),1,'resume used a fresh or stale mean snapshot instead of the submitted object');
    assert.strictEqual(f.cleared[0],f.result);
  },
  'second-explicit-save-checks-before-repost':async()=>{
    const f=fixture({neverCommitted:true});await assert.rejects(f.save(),/未重复提交/);
    const id=f.state.sttRangeSubmission.id,index=f.calls.length;assert.equal(f.posts(),1);
    await f.save();assert.equal(f.posts(),2);assert.equal(f.rows.length,1);assert.equal(f.rows[0].details.submission_id,id);
    const after=f.calls.slice(index);assert.deepEqual(after.slice(0,3).map(x=>x.kind),['rhythm-review','annotations','rhythm-review']);
    assert.ok(after.findIndex(x=>x.kind==='analysis-basis')<after.findIndex(x=>x.method==='POST'));
  },
  'absent-id-old-revision-cannot-rebase':async()=>{
    const f=fixture({neverCommitted:true});await assert.rejects(f.save());f.server.analysis_revision=5;
    await assert.rejects(f.save(),/未重复提交/);assert.equal(f.posts(),1);assert.equal(f.state.sttRangeSubmission.uncertain,true);
    assert.equal(f.$('#sttReviewNote').value,'synthetic mean receipt');
  },
  'stored-full-field-mismatch-never-ack':async()=>{
    for(const change of [r=>r.note+=' changed',r=>r.lead='V1',r=>r.sample_index++,r=>r.details.end_sample++,
      r=>r.details.range_statistics.counts.used_count++,r=>r.details.status='confirmed']){
      const f=fixture({responseLost:true,mutateStored:change});await assert.rejects(f.save(),/不同内容/);
      assert.equal(f.posts(),1);assert.equal(f.cleared.length,0);assert.equal(f.state.sttRangeSubmission.uncertain,true);
    }
  },
  'duplicate-uuid-records-never-ack':async()=>{
    const f=fixture({responseLost:true,afterCommit:()=>{}});f.setReadFault(true);await assert.rejects(f.save());
    f.rows.push(copy(f.rows[0]));f.setReadFault(false);await assert.rejects(f.save(),/不同内容/);
    assert.equal(f.posts(),1);assert.equal(f.cleared.length,0);
  },
  'changed-source-or-beats-never-ack':async()=>{
    for(const key of ['analysis_basis','beat_revision']){
      const f=fixture({responseLost:true,afterCommit:(_,server)=>{server[key]=key==='beat_revision'?3:'changed-source';}});
      await assert.rejects(f.save(),/来源或心搏/);assert.equal(f.cleared.length,0);assert.equal(f.posts(),1);
      assert.equal(f.$('#sttReviewNote').value,'synthetic mean receipt');
    }
  },
  'fresh-global-changes-during-read-reject':async()=>{
    const f=fixture({responseLost:true,intercept:call=>{
      if(call.kind==='annotations'&&call.method!=='POST')f.server.analysis_revision++;
    }});await assert.rejects(f.save(),/读取期间依据/);assert.equal(f.cleared.length,0);assert.equal(f.posts(),1);
  },
  'extra-global-mutation-never-ack-or-repost':async()=>{
    const f=fixture({responseLost:true});f.setReadFault(true);await assert.rejects(f.save());
    const existing=copy(f.rows[0]),id=f.state.sttRangeSubmission.id;
    f.server.analysis_revision++;f.setReadFault(false);
    await assert.rejects(f.save(),/已有其他复核修改/);
    assert.equal(f.posts(),1);assert.equal(f.cleared.length,0);assert.equal(f.state.sttRangeSubmission.id,id);
    assert.equal(f.state.sttRangeSubmission.uncertain,true);assert.deepEqual(f.rows,[existing]);
    assert.equal(f.$('#sttReviewNote').value,'synthetic mean receipt');
  },
  'bad-post-response-reconciles-once':async()=>{
    const f=fixture({badResponse:true});await f.save();assert.equal(f.posts(),1);assert.equal(f.rows.length,1);assert.equal(f.cleared.length,1);
  },
  'fixed-intent-uuid-across-A-B-A':async()=>{
    const f=fixture();f.setBasisFault(true);
    await assert.rejects(f.save());const first=f.state.sttRangeSubmission.id;
    f.$('#sttReviewNote').value='intent B';await assert.rejects(f.save());const second=f.state.sttRangeSubmission.id;
    f.$('#sttReviewNote').value='synthetic mean receipt';await assert.rejects(f.save());
    assert.equal(f.state.sttRangeSubmission.id,first);assert.notEqual(first,second);assert.equal(f.uuids(),2);assert.equal(f.posts(),0);
  },
  'new-typed-note-is-retained':async()=>{
    const postGate=gate(),f=fixture({postGate});const p=f.save();await tick();
    f.$('#sttReviewNote').value='new doctor draft';postGate.resolve();await p;
    assert.equal(f.$('#sttReviewNote').value,'new doctor draft');assert.strictEqual(f.cleared[0],f.result);
  },
  'new-accepted-mean-same-note-is-retained':async()=>{
    const postGate=gate(),f=fixture({postGate});const p=f.save();await tick();
    f.newMean();const newAccepted=f.state.sttRangeReviewed;postGate.resolve();await p;
    assert.strictEqual(f.state.sttRangeReviewed,newAccepted);assert.equal(f.$('#sttReviewNote').value,'synthetic mean receipt');
    assert.strictEqual(f.cleared[0],f.result);
  },
  'uncertain-old-save-does-not-clear-new-mean':async()=>{
    const f=fixture({responseLost:true});f.setReadFault(true);await assert.rejects(f.save());f.setReadFault(false);
    f.newMean();f.$('#sttReviewNote').value='new mean and note';const newer=f.state.sttRangeReviewed;
    await f.save();assert.equal(f.posts(),1);assert.strictEqual(f.state.sttRangeReviewed,newer);
    assert.equal(f.$('#sttReviewNote').value,'new mean and note');assert.strictEqual(f.cleared[0],f.result);
  },
  'late-case-token-epoch-never-clear':async()=>{
    for(const key of ['caseId','caseRequestId','workspaceEpoch']){
      const wait=gate();let held=false;
      const f=fixture({responseLost:true,intercept:async call=>{
        if(call.kind==='annotations'&&call.method!=='POST'&&!held){held=true;await wait.promise;}
      }});const p=f.save();await tick();f.state[key]=key==='caseRequestId'?8:'changed';wait.resolve();await p;
      assert.equal(f.cleared.length,0);assert.equal(f.posts(),1);assert.equal(f.$('#sttReviewNote').value,'synthetic mean receipt');
    }
  },
  'late-old-save-never-release-new-saving':async()=>{
    const postGate=gate(),f=fixture({postGate});const p=f.save();await tick();
    f.state.caseId='math-b';const newer={caseId:'math-b',caseToken:8,workspaceEpoch:'new'};f.state.sttSaving=newer;
    postGate.resolve();await p;assert.strictEqual(f.state.sttSaving,newer);assert.equal(f.cleared.length,0);
  },
  'duplicate-click-during-read-or-post-suppressed':async()=>{
    const postGate=gate(),f=fixture({postGate});const p=f.save();await tick();await f.save();assert.equal(f.posts(),1);
    postGate.resolve();await p;
  },
  'known-saved-refresh-failure-never-new-post':async()=>{
    const f=fixture({refreshFail:true});await assert.rejects(f.save(),/refresh failed/);
    assert.equal(f.state.sttRangeSubmission.saved,true);assert.equal(f.state.sttRangeSubmission.uncertain,false);
    await assert.rejects(f.save(),/refresh failed/);assert.equal(f.posts(),1);
  },
  'plain-point-has-no-uuid-or-mean-fields':async()=>{
    const f=fixture({pointOnly:true});await f.save();const p=JSON.parse(f.calls.find(x=>x.method==='POST').body);
    assert.equal(p.details.submission_id,undefined);assert.equal(p.details.range_statistics,undefined);
    assert.equal(f.calls.filter(x=>x.kind==='rhythm-review').length,0);assert.equal(f.cleared.length,0);
  },
};
(async()=>{
  for(const [name,run]of Object.entries(cases))await run();
  console.log(JSON.stringify({passed:Object.keys(cases).length,scenarios:Object.keys(cases)}));
})().catch(error=>{console.error(error);process.exitCode=1;});
