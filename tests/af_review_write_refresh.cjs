'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const C=require('../static/js/analysis-consistency.js');
const source=fs.readFileSync('static/js/overview-workbench.js','utf8');
const fn=source.slice(source.indexOf('  async function refreshRhythmWrite('),source.indexOf('  async function reconcileRhythmWrite('));
function fixture(){
  const identity={analysis_basis:'raw-and-method',analysis_revision:10},next={...identity,analysis_revision:11};
  const oldWave={...identity,start_s:20,duration_s:10,sample_rate_hz:200,leads:{II:[0,1,0]}};
  const wave={...oldWave,...next},caseData={case_id:'math',clinical_identity:next,beat_editor_history:{revision:2},annotations:[],review_workflow:{revision:11},report_workflow:{version:2}};
  const base={revision:4,document:{episodes:[]}},payload={request_id:'one',operation:'save'};
  const value={...next,case_id:'math',beat_revision:2,revision:5,document:{episodes:[]},last_operation:{...payload,revision:5}};
  const requests=[],received=[],loads=[],ui={identity,revision:2,rows:[{sample_index:100}],rhythm:base};
  const state={caseId:'math',cases:[{case_id:'math'}],caseRequestId:7,privacyRequestId:0,waveformRequestId:0,start:20,duration:10,filter:'raw',waveform:oldWave};
  const sandbox={ECGAnalysisConsistency:C,ui,state,overviewReady:true,episodeDrafts:new Map(),episodeEditor:null,coverage:null,
    linked:{advanceReview:(scope,rows)=>{received.push(['linked',scope,rows]);return true;}},
    async api(path){requests.push(path);const p=new URL(path,'http://localhost');
      if(p.pathname.endsWith('/analysis-basis'))return next;
      if(p.pathname.endsWith('/waveform'))return wave;
      if(p.pathname==='/api/cases/math')return caseData;
      throw Error('Unexpected broad read: '+path);},
    load:async force=>loads.push(force),waveformRequestLeads:()=>['II'],withPhi:p=>p,
    rememberEpisodeForm(){},preserveCurrentIdentity(){},
    ECGReportConsistency:{receive:(_,v)=>received.push(['report',v])},clinicalWorkflow:{receive:v=>received.push(['workflow',v])},
    renderEpisodes(){},renderCoverage(){},draw(){},renderWaveform(){},renderAnnotations(){},
  };
  vm.createContext(sandbox);vm.runInContext(fn+';this.refresh=refreshRhythmWrite;',sandbox);
  return {sandbox,identity,next,wave,caseData,value,base,payload,requests,received,loads,ui,state,
    run:()=>sandbox.refresh(value,{identity,base,payload,current:()=>true})};
}
(async()=>{
  const a=fixture(),rows=a.ui.rows;await a.run();
  assert.equal(a.loads.length,0);assert.equal(a.ui.rows,rows);assert.equal(a.state.waveform,a.wave);
  assert.equal(a.received.filter(x=>x[0]==='linked').length,1);
  assert.equal(a.requests.filter(p=>p.includes('/waveform?')).length,1);
  assert.ok(a.requests.every(p=>!/(overview|stt-review|trend)\?/.test(p)));
  assert.equal(a.state.caseData,a.caseData);assert.equal(a.ui.rhythm,a.value);
  assert.equal(a.state.cases[0].review_workflow,a.caseData.review_workflow);
  for(const change of [v=>v.analysis_revision++,v=>v.analysis_basis='new-source',v=>v.beat_revision++,v=>v.last_operation.request_id='someone-else']){
    const b=fixture();change(b.value);await b.run();assert.deepEqual(b.loads,[true]);assert.equal(b.received.length,0);
  }
  const badWave=fixture();badWave.wave.start_s=22;
  await assert.rejects(badWave.run(),/窗口不一致/);assert.equal(badWave.ui.identity,badWave.identity);
  assert.equal(badWave.received.length,0);
  const badBeat=fixture();badBeat.caseData.beat_editor_history.revision++;
  await assert.rejects(badBeat.run(),/窗口不一致/);assert.equal(badBeat.ui.identity,badBeat.identity);
  const race=fixture();race.sandbox.api=async path=>{race.requests.push(path);if(path.includes('analysis-basis'))throw Error('basis conflict');return path.includes('/waveform?')?race.wave:race.caseData;};
  await assert.rejects(race.run(),/basis conflict/);assert.equal(race.ui.identity,race.identity);
  console.log(JSON.stringify({passed:true,metadataOnlyKeepsQRS:true,noBroadReads:true,sourceBeatConcurrentAndWrongResponseFailClosed:true}));
})().catch(e=>{console.error(e);process.exitCode=1;});
