const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const gate=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}};
const tick=()=>new Promise(r=>setImmediate(r));
const source=fs.readFileSync('static/js/clinical-ui.js','utf8');
async function range(which){
  const pending=[],mounted=[],saved=[];
  const target={children:[],appendChild(n){n.isConnected=true;this.children.push(n)},replaceChildren(n){this.children.forEach(x=>x.isConnected=false);n.isConnected=true;this.children=[n]},setAttribute(){},textContent:''};
  const state={caseId:'A',caseRequestId:1,caseData:{technical:{duration_seconds_raw:90}}};
  const entry=k=>({sample_index:2000,event_id:k,analysis_basis:'source',analysis_revision:1,strip:{start_s:7,end_s:14,actual_duration_s:7,leads:['II']}});
  const ctx=vm.createContext({state,waveToken:1,reportToken:1,reportRenderToken:1,waveEvidenceScope:'one',waveEvidence:{analysis_basis:'source',analysis_revision:1},
    copy:x=>JSON.parse(JSON.stringify(x)),document:{createElement:()=>({isConnected:false,textContent:'',setAttribute(){}})},
    endpoint:(kind,params)=>{const g=gate();pending.push({kind,params,...g});return g.promise},
    ECGReportRange:{mount:(host,e,w,apply)=>mounted.push({host,e,w,apply})},ECGReportEngine:{settings:x=>({...x})},
    returnedRhythmSelection:()=>null,
    reportStrip:async(e,s,id,fresh)=>{assert.equal(fresh,true,'applying a range reused cached validation');saved.push(s);return entry(e.event_id)},selected:()=>[],selectEvent:(e)=>saved.push(e.event_id),dirty(){},renderReportBody(){}});
  vm.runInContext(source.slice(source.indexOf('  async function mountRange('),source.indexOf('  function hrvForReport(')),ctx);
  const first=ctx.mountRange(target,{event_id:'old'},entry('old'));
  if(which==='range-order'){
    ctx.waveToken++;const second=ctx.mountRange(target,{event_id:'new'},entry('new'));
    pending[0].resolve({analysis_basis:'source',analysis_revision:1});await first;
    pending[1].resolve({analysis_basis:'source',analysis_revision:1});await second;
    assert.equal(mounted.length,1,'late old event mounted over current selection');assert.equal(mounted[0].e.event_id,'new');
  }else{
    assert.equal(pending[0].params.analysis_basis,'source','range context did not bind to preview basis');
    pending[0].resolve({analysis_basis:'source',analysis_revision:1});await first;
    if(which==='range-valid'){await mounted[0].apply({range_start_s:6,range_end_s:14});assert.equal(saved[0].range_start_s,6);assert.equal(saved[1],'old');return;}
    if(which==='range-refresh')ctx.waveEvidenceScope='two';else {state.caseId='B';state.caseRequestId++}
    await assert.rejects(mounted[0].apply({range_start_s:6,range_end_s:14}),/变化|切换|重新/);
    assert.equal(saved.length,0,'stale range modified a different report');
  }
}
async function detail(){
  const g=gate(),host={innerHTML:'old range',textContent:'',setAttribute(){}},label={textContent:''};
  let navigationInvalidated=false;
  const ctx=vm.createContext({state:{caseId:'A',caseRequestId:1},waveToken:0,waveEvidenceScope:'one',waveEvidence:{},active:null,renderEventNavigation(ready){assert.notEqual(ready,true);navigationInvalidated=true;},qs:s=>s==='#v2EventWave'?host:label,endpoint:()=>g.promise,svg:()=>'',formatElapsed:String});
  vm.runInContext(source.slice(source.indexOf('  async function detailWindow('),source.indexOf('  function statsTable(')),ctx);
  const result=ctx.detailWindow(20);assert.notEqual(host.textContent,'','old range remains actionable while loading');
  assert.equal(navigationInvalidated,true,'continuous browsing must disable candidate inclusion');
  g.reject(Error('offline'));await assert.rejects(result,/offline/);assert.match(host.textContent,/失败|重试/);
}
async function wave(which){
  const source=fs.readFileSync('static/js/app.js','utf8'),g=gate(),nodes=new Map(),renders=[];
  const field=which.startsWith('edit')?'editWaveform':which.startsWith('stt')?'sttWaveform':'waveform',meta=field==='waveform'?'waveMeta':field==='editWaveform'?'editWaveMeta':'sttWaveMeta';
  const state={caseId:'A',caseRequestId:1,start:0,duration:10,filter:'raw',[field]:{old:true},waveformRequestId:0,editRequestId:0,sttRequestId:0,caseData:{technical:{duration_seconds_raw:90}},editStart:0,editDuration:20,editLead:'II',sttStart:0,sttDuration:10,leads:['II'],sttReview:{}};
  const $=s=>{if(!nodes.has(s))nodes.set(s,{textContent:'',value:0,setAttribute(){},getContext:()=>({clearRect(){},fillRect(){},fillText(){}}),width:500,height:200});return nodes.get(s)};
  const ctx=vm.createContext({state,$,api:()=>g.promise,URLSearchParams,ECGAnalysisConsistency:require('../static/js/analysis-consistency.js'),withPhi:x=>x,analysisReadStatus(){},DEFAULT_PREVIEW_LEADS:['II','V1','V5'],waveformRequestLeads:()=>['II'],formatElapsed:String,
    updateZoomControls(){},renderWaveform(){renders.push(state.waveform)},renderVisibleEvents(){},renderAnnotations(){},renderOverview(){},syncHourScatter(){}});
  vm.runInContext(source.slice(source.indexOf('async function loadWaveform('),source.indexOf('function canvasContext(')),ctx);
  vm.runInContext(source.slice(source.indexOf('async function loadEditWaveform('),source.indexOf('function setEditStart(')),ctx);
  vm.runInContext(source.slice(source.indexOf('async function loadStt('),source.indexOf('function setSttStart(')),ctx);
  const result=which.startsWith('edit-load')?ctx.loadEdit():field==='editWaveform'?ctx.loadEditWaveform():field==='sttWaveform'?ctx.loadStt():ctx.loadWaveform();
  assert.equal(state[field],null,'old waveform remains editable under new cursor');
  if(which.endsWith('failure')){g.reject(Error('offline'));await assert.rejects(result,/offline/);assert.match($('#'+meta).textContent,/失败|重试/);}
  else {state.caseId='B';state.caseRequestId++;g.resolve({start_s:20,duration_s:10,leads:{II:[]}});await result;assert.equal(state[field],null);assert.equal(renders.length,0);}
}
const which=process.argv[2];(which.startsWith('range-')?range(which):which==='detail-loading'?detail():wave(which)).catch(e=>{console.error(e);process.exitCode=1});
