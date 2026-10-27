'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const app=fs.readFileSync('static/js/app.js','utf8'),ui=fs.readFileSync('static/js/clinical-ui.js','utf8');
function section(text,start,end){const a=text.indexOf(start),b=text.indexOf(end,a);assert(a>=0&&b>a);return text.slice(a,b)}
async function verify(){
  const groups={6:[300],7:[],8:[800],9:[]},selected=new Set([300,800]),wave={start_s:120,duration_s:10};
  const nodes=new Map(),scroll={isConnected:true,scrollTop:240,scrollLeft:17},root={scrollTop:0,scrollLeft:0,querySelectorAll:()=>[scroll]};
  const canvas={isConnected:true,focuses:0,focus(opts){assert.equal(opts.preventScroll,true);this.focuses++}};
  const get=s=>{if(s==='#page-edit')return root;if(!nodes.has(s))nodes.set(s,{value:'',hidden:false,classList:{remove(){}}});return nodes.get(s)};
  let pages=[],reads=0,frames=[],scrolls=[];
  const state={caseId:'CASE-A',caseRequestId:4,caseData:{technical:{sample_rate_hz:200,duration_seconds_raw:600},analysis_revision:0,review_workflow:{beat_revision:0}},editReadIdentity:{id:'CASE-A',caseToken:4,analysis_basis:'fixture',analysis_revision:0,data_version:1},currentPage:'edit',editMode:'library',editStart:120,editDuration:10,editLead:'V1',editSelectedSamples:selected,groups,editWaveform:wave,start:40,duration:20,filter:'raw',leads:['II','V1','V5'],waveformExpanded:false};
  const ctx=vm.createContext({ECGReviewTools:require('../static/js/clinical-review-tools.js'),state,$:get,window:{scrollX:0,scrollY:96,scrollTo:(...xy)=>scrolls.push(xy)},document:{body:{classList:{remove(){}}}},requestAnimationFrame:fn=>frames.push(fn),
    goPage(name,options){pages.push({name,options});state.currentPage=name},enterWaveformFullscreen:async()=>{state.waveformExpanded=true},loadWaveform:async()=>reads++,handleError(){},closeBeatRelabelMenu(){},updateWaveformModeUI(){},updateZoomControls(){},setEditMode:mode=>state.editMode=mode,
    renderEditOverview(){},renderEditScatter(){},renderEditGallery(){},renderEditWaveform(){},renderEditDensity(){},renderEditLibrary(){}});
  vm.runInContext(section(app,'function editTwelveScope()', 'async function loadWaveform()')+section(app,'function finishWaveformFullscreenExit()', 'async function enterWaveformFullscreen()'),ctx);
  await ctx.openEditTwelveLead(canvas);
  assert.equal(state.currentPage,'review');assert.equal(state.start,120);assert.equal(state.duration,10);assert.equal(state.filter,'display');assert.equal(pages[0].options.editFullscreenTransition,true);
  scroll.scrollTop=0;scroll.scrollLeft=0;state.start=999;state.duration=5;state.leads=['I'];
  ctx.finishWaveformFullscreenExit();
  assert.equal(state.currentPage,'edit');assert.equal(state.editMode,'library');assert.equal(pages[1].options.reuseEditWorkspace,true);assert.equal(pages[1].options.editFullscreenTransition,true);
  assert.equal(state.start,40);assert.equal(state.duration,20);assert.equal(state.filter,'raw');assert.deepEqual(Array.from(state.leads),['II','V1','V5']);
  assert.equal(state.editStart,120);assert.equal(state.editDuration,10);assert.equal(state.editLead,'V1');assert.equal(state.editWaveform,wave);assert.equal(state.editSelectedSamples,selected);assert.equal(state.groups,groups);assert.equal(reads,0);
  assert.equal(scroll.scrollTop,240);assert.equal(scroll.scrollLeft,17);assert.deepEqual(scrolls.at(-1),[0,96]);assert.equal(canvas.focuses,1);
  state.caseRequestId=5;const focused=canvas.focuses,scrolled=scrolls.length;frames.shift()();assert.equal(canvas.focuses,focused);assert.equal(scrolls.length,scrolled,'late return restored another lifecycle');
  state.currentPage='edit';state.editReadIdentity.caseToken=state.caseRequestId;await ctx.openEditTwelveLead(canvas);state.caseId='CASE-B';state.caseRequestId=6;const currentSelection=new Set([999]);state.editSelectedSamples=currentSelection;
  const before=pages.length;ctx.finishWaveformFullscreenExit();await Promise.resolve();assert.equal(pages.length,before,'stale fullscreen returned to a different case');assert.equal(state.editSelectedSamples,currentSelection);assert.equal(state.editFullscreenReturn,null);assert.equal(reads,1);

  let forwarded,released=0;
  const navState={caseId:'CASE',currentPage:'edit',editStart:120,editLead:'V1',start:40,leads:['II','V5']};
  const nav=vm.createContext({state:navState,goPage:(name,options)=>{forwarded={name,options};navState.currentPage=name},clinicalUI:{cancelReportExport(){},releaseOccurrenceWaves(){released++}}});
  vm.runInContext(section(ui,'const goPageLegacy=goPage;', 'const setEditModeLegacy=setEditMode;'),nav);
  nav.goPage('review',{editFullscreenTransition:true});assert.equal(navState.start,40);assert.deepEqual(navState.leads,['II','V5']);assert.equal(forwarded.options.editFullscreenTransition,true);assert.equal(released,0);
  nav.goPage('edit',{editFullscreenTransition:true,reuseEditWorkspace:true});assert.equal(navState.editStart,120);assert.equal(navState.editLead,'V1');assert.equal(forwarded.options.reuseEditWorkspace,true);
  nav.goPage('review');assert.equal(navState.start,120);assert.deepEqual(Array.from(navState.leads),['V1','II','V5']);assert.equal(released,1,'ordinary navigation stopped releasing old evidence');
  let entered=0;
  ctx.goPage=()=>{};ctx.enterWaveformFullscreen=async()=>entered++;
  Object.assign(state,{caseId:'CASE-C',caseRequestId:7,currentPage:'edit',waveformExpanded:false,start:42,duration:15,filter:'raw',leads:['II']});
  state.editReadIdentity={id:state.caseId,caseToken:state.caseRequestId,analysis_basis:'fixture',analysis_revision:0,data_version:1};await ctx.openEditTwelveLead(canvas);assert.equal(entered,0,'declined navigation still entered fullscreen');assert.equal(state.currentPage,'edit');assert.equal(state.start,42);assert.equal(state.duration,15);assert.equal(state.filter,'raw');assert.deepEqual(Array.from(state.leads),['II']);assert.equal(state.editFullscreenReturn,null);
  vm.runInContext(app.match(/^const ALL_LEADS = .*;$/m)[0]+section(app,'function sttVisibleLeads()', 'function sttSelectionSnapshot()'),ctx);
  vm.runInContext(section(app,'async function openSttTwelveLead()', 'async function saveSttReviewAnnotation()'),ctx);
  Object.assign(state,{currentPage:'stt',sttStart:120,sttDuration:16,sttIsoFraction:.25,sttJFraction:.4,sttMeasurementMs:60,sttLeads:['II','V1']});
  await ctx.openSttTwelveLead();assert.equal(entered,0,'declined ST navigation still entered fullscreen');assert.equal(state.currentPage,'stt');assert.equal(state.start,42);assert.equal(state.duration,15);assert.equal(state.filter,'raw');assert.equal(state.sttFullscreenReturn,null);assert.equal(state.sttIsoFraction,.25);assert.equal(state.sttJFraction,.4);assert.deepEqual(state.sttLeads,['II','V1'],'declined ST fullscreen changed local lead selection');assert.deepEqual(Array.from(state.leads),['II'],'declined ST fullscreen changed preview lead selection');
  console.log('Edit fullscreen: native-view routing, original preview/editor/groups/selections, scrolling, token-gated delayed return and ordinary-navigation ownership passed');
}
verify().catch(error=>{console.error(error);process.exitCode=1});
