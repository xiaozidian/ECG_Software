'use strict';
// Execute the shipped view reader against delayed, cancelled and changed evidence.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('static/js/clinical-ui.js','utf8');
const gate=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject};};
const tick=()=>new Promise(r=>setImmediate(r));
const event=(category,n=0)=>({event_id:category+n,basis_version:'event-v1',category,subtype:'single',label:'单发室早',time_s:n,templates:[]});
function data(category,basis='raw-A',revision=4){return {data_version:'events-'+revision,analysis_basis:basis,analysis_revision:revision,offset:0,total:200,items:[event(category)],category_counts:{fastest:200,S:0,V:200},basis_versions:{fastest:'rate-v1',S:'event-v1',V:'event-v1'},subtype_counts:{single:1}};}
function setup(){
  const selectedEvent={...event('V',3),event_id:'curated'},composition={selected_events:[{event_id:'curated',basis_version:'event-v1',caption:'人工图注',leads:['II'],duration_s:7}],diagnosis_blocks:[{key:'V:single',text:'人工结论',manual:true}],category_reviews:{},fast_slow_mode:'rr'};
  const state={caseId:'A',caseRequestId:2,report:{version:1,review_revision:4,composition},reportComposition:composition,reportDirty:true,reportViews:new Map(),reportBookmarks:new Map(),reportDisplayedCategory:'fastest'};
  const focus={id:'v2RateSort'},host={innerHTML:'retained waveform',inert:false,contains:n=>n===focus,querySelectorAll:()=>[]},list={scrollTop:83},status={querySelector:()=>({addEventListener(){}})};
  const requests=[],bodies=[],shells=[],focusRestored=[];let reader;
  const ctx=vm.createContext({state,AbortController,document:{activeElement:focus},category:'fastest',reportCase:'A',reportVersion:1,reportToken:1,waveToken:1,reportRenderToken:1,reportMode:'all',reportSort:'hr_desc',reportOffset:0,reportSpacing:0,pauseBand:'all',reportTimeRange:null,reportReturn:null,active:event('fastest'),reportData:data('fastest'),selectedLookup:new Map([['curated',selectedEvent]]),
    A:{categories:[['fastest','最快心率'],['S','房早'],['V','室早']]},selected:()=>composition.selected_events,composition:()=>composition,copy:x=>JSON.parse(JSON.stringify(x)),esc:String,
    qs:s=>s==='.report-conclusion-dock'?null:s==='.v2-event-list'?list:s==='#reportViewStatus'?status:s==='#v2RateSort'?{focus:()=>focusRestored.push(s)}:host,
    endpoint:(kind,params,id,options)=>{requests.push({kind,params,id,signal:options?.signal});return reader(kind,params,id,options);},
    renderReportShell(){shells.push({loading:state.reportEvidenceLoading,counts:ctx.reportData?.category_counts,viewLoading:state.reportViewLoading});},
    async renderReportBody(){ctx.reportRenderToken++;list.scrollTop=0;bodies.push({category:ctx.category,data:ctx.reportData,active:ctx.active});},syncWaveEvidence(){},syncText(){},dirty(){},run:f=>f()});
  vm.runInContext(fs.readFileSync('static/js/report-consistency.js','utf8'),ctx);
  vm.runInContext(source.slice(source.indexOf('  function sameEvidence('),source.indexOf('  let reportCase=')),ctx);
  vm.runInContext(source.slice(source.indexOf('  async function refreshReport('),source.indexOf('  // A saved NN strip')),ctx);
  vm.runInContext(source.slice(source.indexOf('  function reportSequence('),source.indexOf('  let rhythmReturn=')),ctx);
  state.reportViewContext=ctx.reportViewContext(ctx.reportData);
  return {ctx,state,host,list,requests,bodies,shells,composition,focusRestored,setReader:f=>reader=f};
}
async function localRace(){
  const x=setup(),old=gate(),fresh=gate();x.setReader((kind,p)=>{assert.equal(kind,'report-events');return p.category==='S'?old.promise:fresh.promise;});
  const lookup=x.ctx.selectedLookup,counts=x.ctx.reportData.category_counts;
  x.ctx.category='S';const first=x.ctx.refreshReport({viewOnly:true});
  assert.equal(x.ctx.reportData.category_counts,counts);assert.equal(x.ctx.selectedLookup,lookup);assert.equal(x.host.innerHTML,'retained waveform');assert.equal(x.host.inert,true);
  assert.equal(x.state.reportEvidenceLoading,undefined,'a category request must not start complete evidence verification');
  x.ctx.category='V';const second=x.ctx.refreshReport({viewOnly:true});assert.equal(x.requests[0].signal.aborted,true);
  assert.equal(x.requests[1].params.analysis_basis,'raw-A');assert.equal(x.requests[1].params.analysis_revision,4);
  fresh.resolve(data('V'));await second;old.resolve(data('S'));await first;
  assert.equal(x.ctx.reportData.items[0].category,'V');assert.equal(x.state.reportDisplayedCategory,'V');assert.equal(x.bodies.length,1);
  assert.equal(x.ctx.selectedLookup.has('S0'),false,'cancelled response leaked into evidence lookup');assert.equal(x.ctx.selectedLookup.has('curated'),true);
  assert.equal(x.composition.diagnosis_blocks[0].text,'人工结论');assert.equal(x.composition.selected_events[0].caption,'人工图注');assert.equal(x.host.inert,false);
  assert.equal(x.shells.every(s=>s.counts?.fastest===200&&s.counts?.S===0),true,'valid zero and 200 counts disappeared');
}
async function restoreAndFocus(){
  const x=setup();x.setReader((kind,p)=>Promise.resolve(data(p.category)));
  x.ctx.reportMode='single';x.ctx.reportSort='hr_asc';x.ctx.reportSpacing=30;x.ctx.reportTimeRange=[10,70];x.ctx.reportOffset=0;
  await x.ctx.chooseReportCategory('V');await x.ctx.chooseReportCategory('fastest');
  assert.equal(x.ctx.reportMode,'single');assert.equal(x.ctx.reportSort,'hr_asc');assert.equal(x.ctx.reportSpacing,30);assert.deepEqual(x.ctx.reportTimeRange,[10,70]);
  assert.equal(x.list.scrollTop,83);assert.equal(x.ctx.active.event_id,'fastest0');
  x.list.scrollTop=41;const before=x.focusRestored.length;await x.ctx.refreshReport({viewOnly:true});assert.equal(x.focusRestored.length,before+1);assert.equal(x.list.scrollTop,41);
  const accepted=x.ctx.reportData;await x.ctx.refreshReport({viewOnly:true});assert.equal(x.ctx.reportData,accepted,'identical evidence lost cached event identity');
  const context=x.state.reportViewContext;x.state.caseRequestId++;assert.notEqual(x.ctx.reportViewContext(accepted),context,'reopening the same case reused a view context');
  assert.notEqual(x.ctx.reportViewKey({...x.requests.at(-1).params,sort:'hr_desc'},accepted),x.ctx.reportViewKey({...x.requests.at(-1).params,sort:'hr_asc'},accepted));
}
async function failureAndInvalidation(){
  const x=setup();x.ctx.category='V';x.setReader(()=>Promise.reject(Error('offline')));const original=x.ctx.reportData;
  await x.ctx.refreshReport({viewOnly:true});assert.equal(x.ctx.reportData,original);assert.equal(x.state.reportViewError.category,'V');assert.equal(x.host.inert,true);assert.equal(x.state.reportEvidenceError,undefined);
  x.setReader((kind,p)=>Promise.resolve(data(p.category)));await x.ctx.refreshReport({viewOnly:true});assert.equal(x.state.reportViewError,null);assert.equal(x.host.inert,false);
  x.setReader(()=>Promise.resolve(data('V','new-raw',5)));await x.ctx.refreshReport({viewOnly:true});assert.match(x.state.reportViewError.message,/依据/);assert.equal(x.ctx.reportData.analysis_revision,4);assert.equal(x.state.reportStale,true);assert.equal(x.state.reportViews.size,0,'changed evidence retained an actionable view cache');
  const remote=gate();x.setReader((kind,p)=>kind==='report'?remote.promise:Promise.resolve(p.ids?{...data('V','new-raw',5),items:[event('V',3)]}:data('V','new-raw',5)));
  const full=x.ctx.refreshReport();assert.equal(x.state.reportEvidenceLoading,true);assert.equal(x.ctx.reportData.category_counts.V,200,'full refresh blanked previously observed counts');
  remote.resolve({version:2,review_revision:5,current_analysis_basis:{digest:'new-raw'}});await full;
  assert.equal(x.ctx.reportData.analysis_revision,5);assert.equal(x.state.reportViews.size,1);assert.equal(x.state.reportBookmarks.has('fastest'),false);assert.equal(x.state.reportStale,true,'new remote revision silently replaced a dirty report base');
  assert.equal(x.composition.diagnosis_blocks[0].text,'人工结论');assert.equal(x.ctx.selectedLookup.has('curated'),false,'deleted event survived complete evidence refresh');
}
async function caseRace(){
  for(const change of ['case','reopen']){const x=setup(),read=gate();x.setReader(()=>read.promise);x.ctx.category='V';const task=x.ctx.refreshReport({viewOnly:true});if(change==='case')x.state.caseId='B';else x.state.caseRequestId++;read.resolve(data('V'));await task;assert.equal(x.bodies.length,0);assert.equal(x.ctx.reportData.items[0].category,'fastest');}
}
function names(){
  const escape=x=>String(x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const ctx=vm.createContext({esc:escape});vm.runInContext(source.slice(source.indexOf('  function reportTemplateName('),source.indexOf('  function renderReportShell(')),ctx);
  const e={event_id:'unchanged',label:'单发室早',category:'V',templates:[{id:'17',name:'工程双页形态-muy9y1nt'},{id:'18',name:'工程双页形态-muy9a71h'}]},before=JSON.stringify(e),html=ctx.reportTemplateCell(e);
  assert.match(html,/V模板 17 \/ V模板 18/);assert.match(html,/单发室早/);assert.match(html,/<details class="v2-event-source"><summary>原模板来源<\/summary>/);assert.match(html,/工程双页形态-muy9y1nt/);assert.match(html,/工程双页形态-muy9a71h/);assert.doesNotMatch(html,/ title=/);assert.equal(JSON.stringify(e),before);
  assert.equal(ctx.reportTemplateName({id:'17',name:'V1'},e),'V1');assert.equal(ctx.reportTemplateName({id:'opaque-id',name:'很长的工程形态模板名称-muy9y1nt'},e),ctx.reportTemplateName({id:'opaque-id',name:'更名后的工程形态模板-muy9a71h'},e),'opaque template identity changed after renaming');
}
function shellNodes(){
  const buttons=['fastest','S','V','final','strips','tables'].map(key=>({dataset:{category:key},counter:{},active:false,classList:{toggle(_,value){this.active=value;}},setAttribute(k,v){this[k]=v;},querySelector(){return this.counter;}}));
  let replaced=0;const nav={querySelector:()=>buttons[0],querySelectorAll:()=>buttons,set innerHTML(_){replaced++;}},nodes=new Map([['#reportV2Nav',nav]]);
  const qs=s=>{if(!nodes.has(s))nodes.set(s,{value:'正在编写的人工结论',textContent:'',innerHTML:'',hidden:false});return nodes.get(s);};
  const composition={selected_events:[],diagnosis_blocks:[],category_reviews:{}},state={caseId:'A',caseRequestId:2,reportDirty:true,report:{version:1,status:'draft',conclusion:'旧保存文本'}};
  const ctx=vm.createContext({state,qs,tabs:[['fastest','最快'],['S','房早'],['V','室早']],A:{categories:[['fastest','最快'],['S','房早'],['V','室早']]},category:'fastest',reportData:data('fastest'),selected:()=>[],selectedLookup:new Map(),composition:()=>composition,esc:String,STATUS_TEXT:{draft:'草稿'},renderRhythmReturn(){},renderRangeDraftNotice(){},ECGReportRange:{setContext(){}},ECGReportConsistency:{canApprove:()=>false},clinicalWorkflow:{readiness:()=>true,writable:()=>true,renderPreflight(){}},updateConclusionCount(){}});
  vm.runInContext(source.slice(source.indexOf('  function renderReportShell('),source.indexOf('  async function reloadReport(')),ctx);
  ctx.renderReportShell();assert.equal(buttons[0].counter.textContent,'0 / 200');assert.equal(buttons[1].counter.textContent,'0 / 0');
  const focused=buttons[0];ctx.category='V';ctx.renderReportShell();assert.equal(replaced,0,'local shell updates replaced navigation controls');assert.equal(buttons[0],focused,'focus target was detached');assert.equal(buttons[2]['aria-current'],'page');
  state.reportEvidenceLoading=true;ctx.renderReportShell();assert.equal(buttons[0].counter.textContent,'0 / 200');assert.equal(buttons[1].counter.textContent,'0 / 0');assert.match(qs('#reportV2Notice').textContent,/计数仍为已读取依据 r4.*本次核对未完成/);assert.equal(qs('#conclusionEditor').value,'正在编写的人工结论');
}
async function cancelRestoreOwnership(){
  for(const change of ['none','category','render','host','case','reopen']){
    const read=gate(),list={scrollTop:11},nodes=new Map(),tasks=[];let cancelHandler,content={inert:true,setAttribute(){}};
    const cancel={addEventListener(_,fn){cancelHandler=fn;}};
    const qs=s=>{if(s==='.v2-event-list')return list;if(s==='#reportV2Content')return content;if(!nodes.has(s))nodes.set(s,{value:'人工结论',textContent:'',innerHTML:'',querySelector:()=>cancel,querySelectorAll:()=>[]});return nodes.get(s);};
    const saved={mode:'single',offset:0,sort:'hr_asc',spacing:0,pauseBand:'all',range:[10,70],active:'V0',scroll:73};
    const state={caseId:'A',caseRequestId:2,report:{status:'draft',version:1},reportDirty:true,reportViewLoading:true,reportDisplayedCategory:'V',reportBookmarks:new Map([['V',saved]])};
    const ctx=vm.createContext({state,qs,category:'S',reportToken:1,waveToken:1,reportRenderToken:10,reportData:data('V'),A:{categories:[['V','室早'],['S','房早']]},tabs:[['V','室早'],['S','房早']],selected:()=>[],selectedLookup:new Map(),composition:()=>({category_reviews:{}}),esc:String,STATUS_TEXT:{draft:'草稿'},ECGReportRange:{setContext(){}},ECGReportConsistency:{canApprove:()=>false},clinicalWorkflow:{readiness:()=>true,writable:()=>true,renderPreflight(){}},renderRhythmReturn(){},renderRangeDraftNotice(){},renderReportBody:()=>{ctx.reportRenderToken++;return read.promise;},run:f=>{const task=f();tasks.push(task);return task;}});
    vm.runInContext(source.slice(source.indexOf('  function renderReportShell('),source.indexOf('  async function reloadReport(')),ctx);
    ctx.renderReportShell();cancelHandler();assert.equal(ctx.category,'V');assert.equal(content.inert,false);assert.equal(ctx.reportMode,'single');assert.equal(ctx.reportSort,'hr_asc');assert.equal(ctx.active.event_id,'V0');
    list.scrollTop=29;
    if(change==='category')ctx.category='S';
    if(change==='render')ctx.reportRenderToken++;
    if(change==='host')content={inert:false,setAttribute(){}};
    if(change==='case')state.caseId='B';
    if(change==='reopen')state.caseRequestId++;
    read.resolve();await Promise.all(tasks);
    assert.equal(list.scrollTop,change==='none'?73:29,`late cancellation restored scroll after ${change} changed ownership`);
  }
}
(async()=>{await localRace();await restoreAndFocus();await failureAndInvalidation();await caseRace();names();shellNodes();await cancelRestoreOwnership();await tick();console.log('Local report views: retained zero/200 counts, stable navigation nodes, cancellation/scroll ownership, stale reads, focused filters, bookmarks, evidence invalidation, stable short names and full source disclosure passed');})().catch(e=>{console.error(e);process.exitCode=1;});
