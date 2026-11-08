'use strict';
// Actual app.api code; controlled mathematical acknowledgements, no API service.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../static/js/app.js'),'utf8');
const start=source.indexOf('async function api('),end=source.indexOf('\nfunction toast(',start);
assert(start>=0&&end>start,'Actual app API function must be available');
function fixture(){
  const events=[],pending=[],state={caseId:'math-A',caseRequestId:1,currentPage:'review',workspaceEpoch:'original-math',editReadCache:{source:'old-math'},reportEvidenceEpoch:0};
  const box={state,fetch:(url,options)=>new Promise(resolve=>pending.push({url,options,resolve})),
    ECGChartInspection:{clearRenderers:()=>events.push(['renderers',state.caseId,state.caseRequestId])},
    ECGFullRecordRetain:{invalidate:()=>events.push(['retain',state.caseId,state.caseRequestId])},
    ECGReadRequests:{clear:()=>events.push(['reads',state.caseId,state.caseRequestId]),read:(_scope,_key,read)=>read()},
    overviewWorkbench:{invalidateAfterWrite:(id,token)=>events.push(['overview',id,token])},
    clinicalWorkflow:{refresh:async id=>events.push(['workflow',id]),receive:()=>assert.fail('Unexpected workflow read failure')},
    toast:()=>assert.fail('Unexpected toast')};
  vm.createContext(box);vm.runInContext(source.slice(start,end)+'\nglobalThis.actualApi=api;',box);
  function acknowledge(value={ok:true},status=200){const request=pending.shift();assert(request);request.resolve({ok:status<400,status,headers:{get:()=> 'application/json'},json:async()=>value});return request;}
  return {state,box,events,pending,acknowledge};
}
async function main(){
  const checked=[];
  for(const changed of [{caseId:'math-B',caseRequestId:2},{caseId:'math-A',caseRequestId:2}]){
    const h=fixture(),write=h.box.actualApi('/api/cases/math-A/rhythm-review',{method:'PUT',body:'{"mathematics":true}'});
    assert.deepEqual(h.events,[['renderers','math-A',1],['retain','math-A',1],['reads','math-A',1]],'Pre-write invalidation remains owned by the original current workspace');
    Object.assign(h.state,changed);h.state.editReadCache={source:'new-math'};h.events.length=0;
    const request=h.acknowledge({saved_case:'math-A'});assert.match(request.url,/analysis=edited/);
    assert.deepEqual(await write,{saved_case:'math-A'});
    assert.deepEqual(h.events,[],'A late old-case or old-token acknowledgement must not clear new renderers, retain drawer, reads or overview');
    assert.deepEqual(h.state.editReadCache,{source:'new-math'});assert.equal(h.state.reportEvidenceEpoch,0);
    checked.push(changed.caseId==='math-B'?'late-other-case-ack-preserves-current-view':'late-same-case-old-token-ack-preserves-reopened-view');
  }
  {
    const h=fixture(),write=h.box.actualApi('/api/cases/math-A/rhythm-review',{method:'PUT'});h.events.length=0;h.acknowledge();await write;
    assert.deepEqual(h.events,[['renderers','math-A',1],['retain','math-A',1],['reads','math-A',1],['overview','math-A',1]],'A current clinical write still invalidates exactly its current visual/read evidence');
    checked.push('current-write-ack-invalidates-current-evidence');
  }
  for(const action of ['report','evidence-candidates']){
    const h=fixture(),write=h.box.actualApi('/api/cases/math-A/'+action,{method:'POST'});assert.deepEqual(h.events,[]);h.acknowledge();await write;
    assert.deepEqual(h.events,[],'Report/candidate writes do not change clinical raw waveforms');assert.equal(h.state.reportEvidenceEpoch,1);
    const old=fixture(),late=old.box.actualApi('/api/cases/math-A/'+action,{method:'POST'});old.state.caseRequestId++;old.acknowledge();await late;
    assert.deepEqual(old.events,[]);assert.equal(old.state.reportEvidenceEpoch,0,'Late metadata save must not bump the reopened report view');
    checked.push(action+'-save-preserves-clinical-renders-and-scopes-metadata-epoch');
  }
  {
    const h=fixture(),read=h.box.actualApi('/api/cases/math-A/waveform');h.acknowledge({mathematical_values:[-2,5,-1]});await read;
    assert.deepEqual(h.events,[]);checked.push('ordinary-read-has-no-write-invalidation');
  }
  console.log(JSON.stringify({passed:true,checks:checked,patient_inputs:false,services_started:false,browser_ui:false}));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
