const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('static/js/clinical-ui.js','utf8');
async function refresh(scenario){
  const old={event_id:'removed',basis_version:'old',category:'V',subtype:'single',label:'old'};
  const state={caseId:'A',report:{version:1,review_revision:1},reportDirty:true,reportComposition:{
    selected_events:[{event_id:'removed',basis_version:'old'}],diagnosis_blocks:[]}};
  const host={innerHTML:'',contains:()=>false},snapshots=[];
  const ctx=vm.createContext({state,reportCase:'A',reportVersion:1,reportToken:0,waveToken:0,reportRenderToken:0,
    category:'V',reportMode:'all',reportOffset:0,reportSort:'hr_desc',reportSpacing:60,pauseBand:'all',reportTimeRange:null,
    reportData:null,selectedLookup:new Map([[old.event_id,old]]),reportWaveCache:new Map(),
    qs:s=>s==='.report-conclusion-dock'||s==='#reportRetry'?null:host,
    A:{categories:[['V','V']]},copy:x=>JSON.parse(JSON.stringify(x)),esc:String,
    selected:()=>state.reportComposition.selected_events,composition:()=>state.reportComposition,
    syncText(){},dirty(){},renderReportShell(){},syncWaveEvidence(){},
    async renderReportBody(){snapshots.push([...ctx.selectedLookup.keys()]);},
    async endpoint(kind,params){
      if(kind==='report')return {version:2,review_revision:2,current_analysis_basis:{digest:'source'}};
      if(params.ids){
        if(scenario==='failure')throw Error('network failure');
        return {items:[],data_version:scenario==='mixed'?'different':'current',analysis_basis:scenario==='mixed_source'?'different':'source',analysis_revision:scenario==='mixed_revision'?3:2};
      }
      assert.equal(params.candidate_spacing_s,scenario==='focus'?0:60,'focused return must reveal hidden candidates');
      return {items:[{event_id:'fresh',basis_version:'current'}],data_version:'current',analysis_basis:'source',analysis_revision:2};
    }});
  vm.runInContext(fs.readFileSync('static/js/report-consistency.js','utf8'),ctx);
  vm.runInContext(source.slice(source.indexOf('  function sameEvidence('),source.indexOf('  let reportCase=')),ctx);
  vm.runInContext(source.slice(source.indexOf('  async function refreshReport('),source.indexOf('  function syncText(')),ctx);
  if(scenario.startsWith('mixed')||scenario==='failure'){
    await assert.rejects(ctx.refreshReport());assert.equal(snapshots.length,0);
    assert.equal(ctx.selectedLookup.size,0,'failed fetch retained old evidence');
    assert.equal(ctx.reportData,null,'failed fetch published partial data');
  }else{
    await ctx.refreshReport(scenario==='focus'?{focusEvent:{event_id:'fresh',basis_version:'current'}}:{});assert.equal(ctx.selectedLookup.has('removed'),false,'removed event still appears valid');
    assert.equal(ctx.selectedLookup.has('fresh'),true);assert.equal(snapshots.length,1);
  }
  assert.equal(state.reportDirty,true);assert.equal(state.report.version,1);
  assert.equal(state.reportComposition.selected_events[0].event_id,'removed','curated pick was silently deleted');
}
async function loader(){
  const {create}=require('../static/js/waveform-loader.js');let release;const calls=[];
  const q=create(async(group,values)=>{calls.push(values);if(calls.length===1)return new Promise(r=>release=r);return values.map(v=>'new:'+v);},{concurrency:1});
  const old=q.get('same','g','old');const settled=old.then(v=>({value:v}),e=>({error:e.message}));
  while(!release)await new Promise(r=>setTimeout(r,1));
  q.clear();const fresh=q.get('same','g','fresh');release(['old:old']);
  assert.match((await settled).error||'',/变化/,'old generation should be rejected');
  assert.equal(await fresh,'new:fresh','fresh request reused old pending promise');
  assert.equal(await q.get('same','g','cached'),'new:fresh','late response restored stale cache');
  assert.equal(calls.length,2);
}
async function stripCache(){
  const setup=source.slice(source.indexOf('  const reportWaveCache='),source.indexOf('  let reportCase='));
  const reader=source.slice(source.indexOf('  async function reportStrip('),source.indexOf('  async function selectedReportWaves('));
  let release,reads=0;const params=[];
  const ctx=vm.createContext({ECGWaveformLoader:require('../static/js/waveform-loader.js'),ECGReportEngine:{settings:x=>x},state:{caseId:'A'},setTimeout,
    endpoint:async(kind,p)=>{params.push(p);reads++;if(reads===1)return new Promise(r=>release=r);return {sequence:reads};}});
  vm.runInContext(setup+reader,ctx);
  const event={event_id:'unchanged',basis_version:'beats-unchanged',label:'candidate'},spec={leads:['II'],duration_s:7};
  ctx.syncWaveEvidence('A',{data_version:'beats',analysis_basis:'old-raw',analysis_revision:1});
  const old=ctx.reportStrip(event,spec).then(value=>({value}),error=>({error:error.message}));
  ctx.syncWaveEvidence('A',{data_version:'beats',analysis_basis:'new-raw',analysis_revision:1});
  assert.equal((await ctx.reportStrip(event,spec)).sequence,2);
  release({sequence:1});assert.match((await old).error,/变化/);
  assert.equal((await ctx.reportStrip(event,spec)).sequence,2,'old response disturbed fresh cache');
  ctx.syncWaveEvidence('A',{data_version:'beats',analysis_basis:'new-raw',analysis_revision:2});
  assert.equal((await ctx.reportStrip(event,spec)).sequence,3);
  assert.equal(params[1].analysis_basis,'new-raw');assert.equal(params[2].analysis_revision,2);
}
async function remove(){
  const picks=[{event_id:'removed'}];let shell=0,body=0;
  const ctx=vm.createContext({state:{reportComposition:{selected_events:picks}},selected:()=>picks,selectedLookup:new Map(),syncText(){},dirty(){},renderReportShell(){shell++},renderReportBody(){body++},run:fn=>fn()});
  vm.runInContext(source.slice(source.indexOf('  function removeReportSelection('),source.indexOf('  function enableReportDraftSelections(')),ctx);
  ctx.removeReportSelection(0);assert.equal(picks.length,0);assert.equal(shell,1);assert.equal(body,1);
}
(process.argv[2]==='loader'?loader():process.argv[2]==='strip_cache'?stripCache():process.argv[2]==='remove'?remove():refresh(process.argv[2])).catch(error=>{console.error(error);process.exitCode=1});
