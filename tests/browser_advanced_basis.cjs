// Production mounting adapter against a synthetic, version-aware second window.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const C=require('../static/js/analysis-consistency.js');
const source=fs.readFileSync('static/js/clinical-ui.js','utf8');
const start=source.indexOf('  function mountAdvanced('),end=source.indexOf('  async function sectionsForReport(',start);
const baseline={analysis_basis:'synthetic-original',analysis_revision:1};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
async function scenario(mode){
  let remote={...baseline},config,shells=0,computes=0,release;
  const wait=new Promise(resolve=>release=resolve);
  const state={caseId:'A',caseRequestId:1,reportStale:false,caseData:{technical:{duration_seconds_raw:90}},reportComposition:{advanced_options:{}}};
  const requests=[];
  async function endpoint(kind,params={}){
    requests.push({kind,params:{...params}});
    if(mode==='offline-probe')throw Error('offline');
    if(params.analysis_basis!==undefined)C.assertSame(params,remote);
    return {...remote};
  }
  const ctx=vm.createContext({state,waveEvidenceScope:'displayed-original',waveEvidence:{...baseline},reportData:{...baseline},
    composition:()=>state.reportComposition,ECGAnalysisConsistency:C,endpoint,
    api:async raw=>{const url=new URL(raw,'http://test');return endpoint(url.pathname.split('/').at(-1),Object.fromEntries(url.searchParams));},
    computeAdvanced:async(id,options,basis)=>{computes++;requests.push({kind:'compute',params:{...basis}});
      if(mode==='offline'||mode==='offline-probe')throw Error('offline');
      if(['during','case','scope'].includes(mode)){await wait;}
      C.assertSame(basis,remote);return {...remote,options};},
    ECGAdvancedAnalysis:{mountRetained:(panel,options)=>config=options},renderReportShell:()=>shells++,dirty(){},run:fn=>fn(),jumpTo(){}});
  vm.runInContext(source.slice(start,end),ctx);
  if(mode==='missing'){ctx.waveEvidence={};ctx.reportData={};assert.throws(()=>ctx.mountAdvanced({isConnected:true},'A'),/缺失/);return;}
  ctx.mountAdvanced({isConnected:true},'A');
  if(mode==='before')remote.analysis_revision++;
  const pending=config.compute({start_s:12,duration_s:45});pending.catch(()=>{});await tick();
  if(['during','case','scope'].includes(mode)){
    remote.analysis_revision++;
    if(mode==='case'){state.caseId='B';state.caseRequestId++;}
    if(mode==='scope')ctx.waveEvidenceScope='another-displayed-basis';
    release();
  }
  if(mode==='success'){
    const result=await pending;assert.equal(result.advanced.analysis_revision,1);assert.equal(computes,1);
    config.onChange(result.advanced.options);assert.equal(state.reportComposition.advanced_options.start_s,12);
  }else{
    await assert.rejects(pending,/变化|offline/);
    assert.deepEqual(state.reportComposition.advanced_options,{});
  }
  assert.equal(state.reportStale,['before','during'].includes(mode));
  assert.equal(shells,['before','during'].includes(mode)?1:0);
  for(const request of requests.filter(r=>['compute','report-sections'].includes(r.kind)))assert.deepEqual(request.params,baseline,'request must use the displayed evidence, not silently adopt the other window');
}
(async()=>{for(const mode of ['success','before','during','offline','offline-probe','case','scope','missing'])await scenario(mode);console.log('8 displayed-basis scenarios passed');})().catch(error=>{console.error(error);process.exitCode=1;});
