const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const C=require('../static/js/analysis-consistency.js'),basis={analysis_basis:'synthetic',analysis_revision:1};
const gate=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}};
const tick=()=>new Promise(r=>setImmediate(r));
const app=fs.readFileSync('static/js/app.js','utf8'),ui=fs.readFileSync('static/js/clinical-ui.js','utf8');
async function protocol(which){
  if(which==='missing-metrics'){
    const host={innerHTML:''},ctx=vm.createContext({state:{caseData:{summary:{avg_hr:null,min_hr:null,max_hr:null,longest_rr_s:null},calculated:{avg_hr_from_rr:null,longest_rr_ms:null}}},$:()=>host,fmtNumber:x=>x??'—'});
    vm.runInContext(app.slice(app.indexOf('function renderTrendMetrics('),app.indexOf('function drawAxes(')),ctx);ctx.renderTrendMetrics();assert.doesNotMatch(host.innerHTML,/null|undefined|NaN|0\.000/);assert.match(host.innerHTML,/—/);return;
  }
  if(which==='missing'){assert.throws(()=>C.identity({}),/缺失/);return;}
  if(which==='nested'){assert.deepEqual(C.identity({analysis_revision:99,clinical_identity:basis}),basis);return;}
  let reads=0;
  const api=async()=>{reads++;return which==='final'&&reads===2?{...basis,analysis_revision:2}:basis};
  const readers=[async b=>({...b}),async b=>which==='mixed'?{...b,analysis_basis:'other'}:which==='absent'?{}:({...b})];
  if(['final','mixed','absent'].includes(which))await assert.rejects(C.read(api,'A',readers),/变化|缺失/);
  else{const result=await C.read(api,'A',[...readers,async()=>null]);assert.equal(result.length,3);assert.equal(reads,2);}
}
async function panel(which){
  const stt=which.startsWith('stt'),g=gate(),calls=[],renders=[],nodes=new Map();let failing=which.endsWith('failure');
  const state={caseId:'A',caseRequestId:1,trendsRequestId:0,sttRequestId:0,sttStart:0,sttDuration:10,leads:['II'],caseData:{technical:{duration_seconds_raw:90}},sttReview:{...basis,analysis_revision:which.endsWith('cache')?0:1},sttWaveform:{old:true},rr:{old:true},hrv:{old:true}};
  const $=s=>{if(!nodes.has(s))nodes.set(s,{textContent:'old',width:500,height:200,getContext:()=>({clearRect(){}})});return nodes.get(s)};
  const response=kind=>kind===''?{clinical_identity:basis,technical:{duration_seconds_raw:90}}:{...basis,start_s:0};
  const api=async raw=>{const u=new URL(raw,'http://test'),kind=u.pathname.split('/').slice(4).join('/');calls.push({kind,query:u.searchParams});if(kind==='analysis-basis')return basis;
    assert.equal(u.searchParams.get('analysis_basis'),basis.analysis_basis);
    if(kind===(stt?'waveform':'hrv-analysis')){await g.promise;if(failing)throw Error('offline');if(which.endsWith('mixed'))return {...basis,analysis_revision:2};}
    return response(kind);
  };
  const ctx=vm.createContext({state,$,api,ECGAnalysisConsistency:C,URLSearchParams,withPhi:x=>x,ECGReportConsistency:{receive(){}},clinicalWorkflow:{receive(){}},
    analysisReadStatus:(s,m,retry)=>Object.assign($(s),{textContent:m,retry}),clearWaveformSurface:key=>{state[key]=null},
    renderTrendMetrics:()=>renders.push('trends'),renderTrendChart(){},renderHistogram(){},renderPoincare(){},renderHrv(){},renderSttCapability:()=>renders.push('stt'),renderSttOverview(){},renderSttTrendRows(){},renderSttWaveform(){}});
  vm.runInContext(app.slice(app.indexOf('function clearTrendEvidence('),app.indexOf('function renderTrendMetrics(')),ctx);
  vm.runInContext(app.slice(app.indexOf('async function loadStt('),app.indexOf('function setSttStart(')),ctx);
  const invoke=()=>stt?ctx.loadStt():ctx.loadTrends(),pending=invoke();await tick();
  assert.equal(renders.length,0,'partial batch rendered before slow evidence finished');
  assert.equal(stt?state.sttWaveform:state.hrv,null);
  if(stt){assert.match($('#sttMeasurementList').textContent,/读取/);assert.equal($('#sttCandidateCount').textContent,'—');}
  if(which.endsWith('case')){state.caseRequestId++;state.caseData={replacement:true};}
  g.resolve();
  if(failing||which.endsWith('mixed')){await assert.rejects(pending,/offline|变化/);assert.equal(renders.length,0);assert.equal(stt?state.sttWaveform:state.hrv,null);assert.equal(typeof $(stt?'#sttAnalysisStatus':'#trendsAnalysisStatus').retry,'function');
    if(stt){assert.match($('#sttMeasurementList').textContent,/未取得/);assert.equal($('#sttCandidateCount').textContent,'—');}
    failing=false;if(which.endsWith('failure')){await invoke();assert.equal(renders.length,1);}
  }else{await pending;if(which.endsWith('case')){assert.equal(renders.length,0);assert.equal(state.caseData.replacement,true);}else assert.equal(renders.length,1);}
  if(which.endsWith('cache'))assert.equal(calls.filter(c=>c.kind==='stt-review').length,1,'old cached candidates were reused');
  if(which==='stt-success')assert.equal(calls.filter(c=>c.kind==='stt-review').length,0,'valid cache needlessly recomputed');
}
async function hrv(which){
  const g=gate(),children=new Map(),state={caseId:'A',caseRequestId:1,reportComposition:{},demoReadonly:false};let exports=0,rendered=0;
  const target={isConnected:true,innerHTML:'old',querySelector:s=>{if(!children.has(s))children.set(s,{addEventListener(){}});return children.get(s)}};
  const ctx=vm.createContext({state,reportCase:'A',hrvToken:0,hrv:null,copy:x=>x,composition:()=>({hrv_window:0}),qs:()=>target,api:async()=>basis,
    ECGAnalysisConsistency:C,endpoint:()=>g.promise,ECGHrvReport:{ui:()=>{rendered++;return 'new'}},ECGReportPaper:{number(){}},paperModel:()=>({report:{}}),esc:String,run:f=>f(),
    fetch:async url=>{exports++;assert.equal(new URL(url,'http://test').searchParams.get('analysis_revision'),'1');return {ok:false,json:async()=>({error:'依据已变化'})};}});
  vm.runInContext(ui.slice(ui.indexOf('  async function loadHrv('),ui.indexOf('  async function save(')),ctx);
  const pending=ctx.loadHrv('#hrvWindowPanel',0);await tick();
  if(which==='hrv-late-error'){state.caseRequestId++;target.innerHTML='replacement';g.reject(Error('late'));await pending;assert.equal(target.innerHTML,'replacement');return;}
  g.resolve({...basis,window_index:0});await pending;assert.equal(rendered,1);
  if(which==='hrv-old-controls'){state.caseRequestId++;await target.querySelector('[data-hrv-export]').onclick();assert.equal(exports,0);}
  else{await assert.rejects(target.querySelector('[data-hrv-export]').onclick(),/依据已变化/);assert.equal(exports,1);}
}
async function demo(which){
  const demo=fs.readFileSync('demo/static/js/demo-api.js','utf8');let stored='{}';
  const response=(x,status=200)=>new Response(JSON.stringify(x),{status});
  const ctx=vm.createContext({URL,Response,STORE_KEY:'synthetic-store',caseId:'A',savedDefault:{},saved:{},localStorage:{getItem:()=>stored},workflow:()=>({revision:1}),
    requestBody:o=>JSON.parse(o.body||'{}'),failure:(e,s)=>response({error:e},s),response,
    route:async()=>{if(which==='demo-race')stored='changed';return response(which==='demo-batch'?{items:[{}]}:{analysis_revision:99});}});
  vm.runInContext(demo.slice(demo.indexOf('  const clinicalReads='),demo.indexOf('  window.fetch=')),ctx);
  const suffix=which==='demo-batch'?'/event-waveforms':which==='demo-overview'?'/overview':which==='demo-rhythm'?'/rhythm-review':'',q=which==='demo-stale'?'?analysis_revision=0':'';
  const result=await ctx.clinicalRoute(new URL('http://test/api/cases/A'+suffix+q),which==='demo-batch'?{method:'POST',body:'{}'}:{});
  if(['demo-race','demo-stale'].includes(which))assert.equal(result.status,409);
  else{const data=await result.json();if(which==='demo-batch')assert.equal(data.items[0].analysis_revision,1);else if(suffix){assert.equal(data.analysis_revision,1);assert.equal(data.analysis_basis,'static-demo-local-v1:A');}else{assert.equal(data.clinical_identity.analysis_revision,1);assert.equal(data.analysis_revision,99);}}
}
const which=process.argv[2];
(which.startsWith('demo')?demo(which):which.startsWith('hrv-')?hrv(which):/^(stt|trends)-/.test(which)?panel(which):protocol(which)).catch(e=>{console.error(e);process.exitCode=1});
