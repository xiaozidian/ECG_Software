// Deterministic async lifecycle checks against the shipped functions, without a browser.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const gate=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function harness(){
  const elements=new Map(),loads=[],servers=new Map();
  function node(id=''){
    const children=new Map(),classes=new Set();
    return {id,hidden:false,value:'',textContent:'',attrs:{},
      classList:{add:k=>classes.add(k),remove:k=>classes.delete(k),toggle:(k,on)=>on?classes.add(k):classes.delete(k)},
      setAttribute(k,v){this.attrs[k]=v},append(child){elements.set('#'+child.id,child)},
      querySelector(k){if(!children.has(k))children.set(k,node());return children.get(k)}};
  }
  const $=key=>{if(key==='#caseLoadingPanel')return elements.get(key)||null;if(!elements.has(key))elements.set(key,node(key.slice(1)));return elements.get(key)};
  const pages=['dashboard','patients','edit','review','report'].map(x=>node('page-'+x));
  const state={caseRequestId:0,currentPage:'dashboard',reportDirty:false,reportSaving:false,reportStale:false,
    waveformRequestId:0,sttRequestId:0,editRequestId:0,editStripRequestId:0,trendsRequestId:0,eventsRequestId:0,
    reportRequestId:0,scatterRequestId:0,scatterSelectionRequestId:0,duration:20,sttDuration:20,report:null};
  const remote=(id,version=1)=>({case_id:id,metadata:{name:'合成病例'},calculated:{first_beat_time_s:0},summary:{},
    technical:{duration_seconds_raw:3600},report_workflow:{version,review_revision:version,conclusion:'已保存正文',composition:{selected_events:[]}},review_workflow:{}});
  const noop=()=>{},asyncLoad=key=>async()=>{loads.push(key)};
  const ctx=vm.createContext({state,$,$$:selector=>selector==='.page'?pages:[],document:{createElement:()=>node(),body:node()},
    window:{scrollTo:noop},CASE_WORKFLOW_STEPS:[{page:'report',label:'报告'},{page:'edit',label:'模板编辑'}],
    clinicalWorkflow:{allowLeave:()=>!state.reportSaving,reset:noop,receive:noop},
    ECGReviewTools:{shouldConfirmNavigation:()=>false},loadCaseWorkflow:()=>new Set(),clearScatterSelection:noop,
    renderCaseWorkflow:noop,updateZoomControls:noop,renderOverview:noop,renderReport:noop,markWorkflowVisited:noop,
    escapeHtml:String,fmtNumber:String,withPhi:x=>x,setEditMode:noop,toast:noop,handleError:e=>{throw e},
    ...Object.fromEntries(['Dashboard','Waveform','Scatter','Trends','Stt','Edit','Events','Report','Audit','Settings'].map(k=>['load'+k,asyncLoad(k)])),
    api:async path=>{const id=path.split('/')[3],server=servers.get(id);assert.ok(server,'unknown synthetic case');
      if(path.endsWith('/open'))return server.open.promise;
      if(path.includes('/trend?'))return {};
      if(path.endsWith('/beat-overrides'))return {items:[]};
      await server.data.promise;return remote(id,server.version);
    }});
  vm.runInContext(fs.readFileSync('static/js/report-consistency.js','utf8'),ctx);
  const source=fs.readFileSync('static/js/app.js','utf8');
  vm.runInContext(source.slice(source.indexOf('function renderCaseLoading()'),source.indexOf('function waveformRequestLeads()')),ctx);
  const add=id=>{const server={open:gate(),data:gate(),version:1};servers.set(id,server);return server};
  return {ctx,state,loads,elements,add};
}
async function run(which){
  const h=harness(),{ctx,state,loads,elements}=h,s=h.add('A');
  if(which==='dirty-refresh'||which==='saving-refresh'||which==='clean-refresh'){
    state.caseId='A';state.report={version:1,review_revision:1,conclusion:'original',composition:{}};
    state.reportComposition={selected_events:[{event_id:'local'}]};
    state.reportDirty=which==='dirty-refresh';state.reportSaving=which==='saving-refresh';
    const report=state.report,composition=state.reportComposition;s.version=2;s.data.resolve();
    await ctx.loadCase();
    if(which==='clean-refresh'){assert.equal(state.report.version,2);assert.equal(state.reportStale,false)}
    else{assert.equal(state.report,report);assert.equal(state.reportComposition,composition);assert.equal(state.reportStale,true);
      assert.equal(state.reportDirty,which==='dirty-refresh');assert.equal(state.reportSaving,which==='saving-refresh')}
    return;
  }
  if(which==='saving-navigation'){
    state.reportSaving=true;state.caseId='old';await ctx.selectCase('A');assert.equal(state.caseId,'old');assert.equal(state.caseLoading,undefined);return;
  }
  const first=ctx.selectCase('A','edit');assert.equal(elements.get('#caseLoadingPanel').hidden,false);
  if(which==='last-intent'){
    ctx.goPage('review');ctx.goPage('report');assert.deepEqual(loads,[]);
    assert.match(elements.get('#caseLoadingPanel').querySelector('p').textContent,/报告/);
    s.open.resolve();s.data.resolve();await first;assert.equal(state.currentPage,'report');assert.deepEqual(loads,['Report']);
  }else if(which==='cancel-before-open'||which==='cancel-after-open'){
    if(which==='cancel-after-open'){s.open.resolve();await tick()}
    ctx.goPage('dashboard');assert.equal(state.caseId,null);s.open.resolve();s.data.resolve();await first;
    assert.equal(state.currentPage,'dashboard');assert.equal(state.caseData,null);assert.deepEqual(loads,['Dashboard']);
  }else if(which==='replace-case'){
    s.open.resolve();await tick();const b=h.add('B'),second=ctx.selectCase('B','report');
    b.open.resolve();b.data.resolve();await second;s.data.resolve();await first;
    assert.equal(state.caseId,'B');assert.equal(state.caseData.case_id,'B');assert.equal(state.currentPage,'report');assert.deepEqual(loads,['Report']);
  }else if(which==='failed-load'){
    s.open.resolve();s.data.reject(Error('network failed'));await assert.rejects(first,/network failed/);
    assert.equal(state.caseId,null);assert.equal(state.currentPage,'dashboard');assert.deepEqual(loads,['Dashboard']);
  }else throw Error('unknown test '+which);
  assert.equal(elements.get('#caseLoadingPanel').hidden,true);
  assert.equal(elements.get('#mainContent').attrs['aria-busy'],'false');
}
run(process.argv[2]).catch(error=>{console.error(error);process.exitCode=1});
