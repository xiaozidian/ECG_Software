'use strict';
// Actual in-memory mathematical Demo fetch/storage adapter; no patient/network/PDF.
const assert=require('node:assert/strict');
const {randomUUID}=require('node:crypto');
const {harness}=require('./browser_demo_feedback_api.cjs');
const scope=x=>Object.fromEntries(['case_id','analysis_basis','analysis_revision','beat_revision'].map(k=>[k,x[k]]));
const episode=(id,start,end,kind='AF',status='confirmed')=>({id,start_s:start,end_s:end,kind,status,source:'manual',note:''});
async function save(h,episodes,operation='save',expected=200){const current=await h.call('rhythm-review');return h.call('rhythm-review','PUT',{...scope(current),revision:current.revision,confirmed:true,operation,request_id:randomUUID(),document:{episodes,bookmarks:{}}},expected);}
async function report(h,picks,status='draft'){
  const value=await h.call('report');
  return h.call('report','PUT',{status,expected_version:value.version,expected_review_revision:value.review_revision,conclusion:'Mathematical AF linkage fixture',composition:{...value.composition,include_hrv:false,included_pages:['event_strips'],selected_events:picks,diagnosis_blocks:[{key:'AF:AF',text:'Preserved physician text',manual:true,needs_review:false,acknowledged:true}]}});
}
(async()=>{
  const h=harness(),a=episode('keep',10,20),b=episode('change',30,40,'AFL');
  const first=await save(h,[a,b]);
  assert.equal(first.last_operation.operation,'save');assert.equal(first.last_operation.revision,first.revision);
  assert.deepEqual((await h.call('rhythm-review')).last_operation,first.last_operation);
  for(const step of ['edit','stt']){const value=await h.call('review-workflow');await h.call('review-workflow','PUT',{step,revision:value.revision,confirmed:true,note:'Synthetic review'});}
  const initial=await h.call('report-events?category=AF');
  const picks=initial.items.map(e=>({event_id:e.event_id,basis_version:e.basis_version,caption:'Preserved figure caption'}));
  await report(h,picks);
  const changed=await save(h,[a,{...b,status:'pending'}]);
  assert.equal((await h.call('review-workflow')).pending_steps.length,0);
  const next=await h.call('report-events?category=AF');
  assert.equal(next.items.find(x=>x.rhythm_episode_id==='keep').basis_version,initial.items.find(x=>x.rhythm_episode_id==='keep').basis_version);
  assert.equal(next.items.find(x=>x.rhythm_episode_id==='keep').diagnosis_status,'confirmed');
  assert.notEqual(next.items.find(x=>x.rhythm_episode_id==='change').basis_version,initial.items.find(x=>x.rhythm_episode_id==='change').basis_version);
  const old=await h.call('report'),removed=await save(h,[a]);
  assert.deepEqual(removed.removed_report_events,['annotation:af:change']);
  const pruned=await h.call('report');
  assert.equal(pruned.version,old.version+1);
  assert.deepEqual(pruned.composition.selected_events.map(x=>x.event_id),['annotation:af:keep']);
  assert.equal(pruned.composition.diagnosis_blocks[0].text,'Preserved physician text');
  assert.equal(pruned.composition.diagnosis_blocks[0].needs_review,true);
  const undone=await save(h,[], 'undo');
  assert.equal(undone.last_operation.operation,'undo');assert.deepEqual((await h.call('rhythm-review')).last_operation,undone.last_operation);
  assert.deepEqual((await h.call('report')).composition.selected_events.map(x=>x.event_id),['annotation:af:keep']);
  const before=h.localStorage.getItem('cardioinsight-public-math-4314-v2');
  h.localStorage.failNextWrite();
  await save(h,[], 'save',[400,503]);
  assert.equal(h.localStorage.getItem('cardioinsight-public-math-4314-v2'),before);
  const reopened=harness(h.source,h.localStorage.values);
  assert.deepEqual((await reopened.call('report')).composition.selected_events.map(x=>x.event_id),['annotation:af:keep']);
  const active=await reopened.call('rhythm-review');
  const excluded=await save(reopened,active.document.episodes.map(x=>x.id==='keep'?{...x,status:'excluded'}:x));
  assert.deepEqual(excluded.removed_report_events,['annotation:af:keep']);
  assert.deepEqual((await reopened.call('report')).composition.selected_events,[]);
  assert.deepEqual(h.nativeRequests.filter(x=>!x.endsWith('case.json')&&!x.endsWith('waveform.bin')),[]);
  console.log(JSON.stringify({passed:true,checks:['per-episode-basis','qrs-st-preserved','atomic-delete','single-report-version','prose-preserved','undo-unselected','failed-storage-rollback','reopen','exclude-removes-pick'],patient_inputs:false,pdf_operations:0}));
})().catch(error=>{console.error(error);process.exitCode=1;});
