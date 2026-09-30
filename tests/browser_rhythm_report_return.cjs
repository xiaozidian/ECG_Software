'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('static/js/clinical-ui.js','utf8');
const basis={analysis_basis:'b',analysis_revision:1};
const old={event_id:'source-event',basis_version:'v1',caption:'doctor caption',leads:['V1','V5'],duration_s:9,range_start_s:8,range_end_s:17};
const event={...basis,event_id:old.event_id,basis_version:'v1',category:'AF',subtype:'AF',rhythm_episode_id:'episode-1'};
function setup(){
  let saves=0,opens=0,refreshes=0;
  const comp={selected_events:[structuredClone(old)],category_reviews:{AF:'v1'},diagnosis_blocks:[{key:'AF:AF',manual:true,acknowledged:true}]};
  const c={state:{caseId:'one',caseRequestId:5,currentPage:'report',reportDirty:true,reportComposition:comp},
    selected:()=>comp.selected_events,selectedLookup:new Map([[old.event_id,structuredClone(event)]]),active:structuredClone(event),
    category:'final',reportData:{...basis,items:[]},reportToken:1,reportOffset:0,reportMode:'all',reportTimeRange:null,reportReturn:null,reportWaveReady:true,
    ECGAnalysisConsistency:require('../static/js/analysis-consistency.js'),
    ECGReportRange:{assertApplied(){}},ECGReportEngine:{settings:raw=>({leads:raw.leads||['II','V1','V5'],duration_s:raw.duration_s||7})},
    save:async()=>{saves++;c.state.reportDirty=false},goPage:name=>{c.state.currentPage=name},
    overviewWorkbench:{openReportEpisode:async(id,b,idCase,token)=>{opens++;assert.equal(id,'episode-1');assert.equal(idCase,'one');assert.equal(token,5)}},
    refreshReport:async()=>{refreshes++},renderReportShell(){},renderReportBody:async()=>{},syncText(){},dirty(){c.state.reportDirty=true},toast(){},
    qs:()=>({scrollIntoView(){},focus(){}}),endpoint:async()=>({...basis,items:[{...event,event_id:'annotation:af:episode-1',basis_version:'v2'}]}),focusEventNavigation(){}
  };
  const ctx=vm.createContext(c);
  vm.runInContext(source.slice(source.indexOf('  let rhythmReturn='),source.indexOf('  async function backToReportEvent(')),ctx);
  vm.runInContext(source.slice(source.indexOf('  function selectEvent('),source.indexOf('  function removeReportSelection(')),ctx);
  return {c,call:x=>vm.runInContext(x,ctx),counts:()=>({saves,opens,refreshes}),comp};
}
(async()=>{
  let x=setup();await x.call('openRhythmReview("0")');assert.deepEqual(x.counts(),{saves:1,opens:1,refreshes:0});assert.equal(x.c.state.currentPage,'review');
  assert.deepEqual(x.comp.selected_events,[old],'navigation must preserve settings and curation');
  await x.call('returnFromRhythm()');assert.equal(x.c.state.currentPage,'report');assert.equal(x.c.category,'final');
  await x.call('viewReturnedRhythm()');assert.equal(x.c.category,'AF');
  x.c.active={...event,event_id:'annotation:af:episode-1',basis_version:'v2'};x.c.reportData.items=[x.c.active];
  assert.deepEqual(JSON.parse(x.call('JSON.stringify(returnedRhythmSettings(active))')),{leads:old.leads,duration_s:7});
  await x.call('replaceReturnedRhythm()');assert.equal(x.comp.selected_events.length,1);assert.equal(x.comp.selected_events[0].caption,old.caption);
  assert.equal(x.comp.selected_events[0].event_id,x.c.active.event_id);assert.equal(x.comp.selected_events[0].basis_version,'v2');
  assert.equal(x.comp.selected_events[0].range_start_s,undefined);assert.equal(x.comp.category_reviews.AF,undefined);
  assert.equal(x.comp.diagnosis_blocks[0].acknowledged,false);assert.equal(x.comp.diagnosis_blocks[0].needs_review,true);
  await assert.rejects(x.call('replaceReturnedRhythm()'),/读取/);
  x=setup();x.c.selectedLookup.get(old.event_id).basis_version='new-basis';
  await x.call('openRhythmReview("0")');assert.equal(x.counts().opens,1,'stale strip can review its exact current episode without upgrading the old selection');
  assert.deepEqual(x.comp.selected_events,[old]);
  x.c.active={...event,basis_version:'new-basis'};
  assert.throws(()=>x.call('selectEvent(active,true)'),/替换/);
  assert.deepEqual(x.comp.selected_events,[old],'checkbox cannot discard caption or bypass replacement');
  x=setup();await x.call('openRhythmReview("active")');x.c.active={...event,basis_version:'v2'};
  assert.ok(x.call('returnedRhythmSelection(active)'),'candidate navigation also preserves an existing selected strip');
  for(const failure of ['range','stale','saving','missing','new-edit','case','page','basis','save-failed']){
    x=setup();
    if(failure==='range')x.c.ECGReportRange.assertApplied=()=>{throw Error('range pending')};
    if(failure==='stale')x.c.state.reportStale=true;
    if(failure==='saving')x.c.state.reportSaving=true;
    if(failure==='missing')x.c.selectedLookup.clear();
    if(failure==='new-edit')x.c.save=async()=>{};
    if(failure==='case')x.c.save=async()=>{x.c.state.caseRequestId++};
    if(failure==='page')x.c.save=async()=>{x.c.state.currentPage='edit'};
    if(failure==='basis')x.c.save=async()=>{x.c.state.reportDirty=false;x.c.reportData.analysis_revision++};
    if(failure==='save-failed')x.c.save=async()=>{throw Error('network')};
    try{await x.call('openRhythmReview("0")')}catch(_){}
    assert.equal(x.counts().opens,0,failure);assert.deepEqual(x.comp.selected_events,[old],failure);
  }
  x=setup();await x.call('openRhythmReview("0")');await x.call('returnFromRhythm()');
  x.c.endpoint=async()=>({...basis,items:[]});await assert.rejects(x.call('viewReturnedRhythm()'),/已删除/);
  x.c.endpoint=async()=>({...basis,items:[event,event]});await assert.rejects(x.call('viewReturnedRhythm()'),/唯一/);
  x.c.endpoint=async()=>({...basis,analysis_revision:8,items:[event]});await assert.rejects(x.call('viewReturnedRhythm()'),/依据/);
  x.c.state.caseRequestId++;assert.equal(x.call('hasRhythmReturn()'),false);
  x=setup();await x.call('openRhythmReview("0")');x.c.active={...event,event_id:'annotation:af:episode-1',basis_version:'v2'};
  x.c.reportData.items=[x.c.active];x.c.reportWaveReady=false;await assert.rejects(x.call('replaceReturnedRhythm()'),/读取/);
  x.c.reportWaveReady=true;x.comp.selected_events.push({...x.c.active});await assert.rejects(x.call('replaceReturnedRhythm()'),/另行入报/);
  x.comp.selected_events.pop();x.call('replaceRhythmSelection(active,{leads:["V1","V5"],duration_s:7,range_start_s:11,range_end_s:20})');
  assert.equal(x.comp.selected_events.length,1);assert.equal(x.comp.selected_events[0].range_start_s,11);assert.equal(x.comp.selected_events[0].caption,old.caption);
  // Concurrent entry clicks cannot initiate a second save or navigation.
  x=setup();let release;const pending=new Promise(resolve=>release=resolve);
  x.c.save=async()=>{await pending;x.c.state.reportDirty=false};
  const opening=x.call('openRhythmReview("0")');await assert.rejects(x.call('openRhythmReview("0")'),/等待/);
  release();await opening;assert.equal(x.counts().opens,1);

  const overview=fs.readFileSync('static/js/overview-workbench.js','utf8');
  for(const mode of ['ok','case-before','case-during','page-during','unready','basis','missing','duplicate','selection-during']){
    const details={open:false},back={hidden:true},located=[];
    const c={state:{caseId:'one',caseRequestId:5,currentPage:'review'},ui:{identity:basis,rhythm:{document:{episodes:[{id:'exact'}]}},episode:null},
      overviewReady:true,ECGAnalysisConsistency:require('../static/js/analysis-consistency.js'),qs:s=>s.includes('details')?details:back,afMode(){},
      load:async()=>{if(mode==='case-during')c.state.caseRequestId++;if(mode==='page-during')c.state.currentPage='report'},
      locateEpisode:async id=>{located.push(id);c.ui.episode=mode==='selection-during'?'other':id}};
    if(mode==='case-before')c.state.caseId='two';
    if(mode==='unready')c.overviewReady=false;
    if(mode==='basis')c.ui.identity={...basis,analysis_revision:2};
    if(mode==='missing')c.ui.rhythm.document.episodes=[];
    if(mode==='duplicate')c.ui.rhythm.document.episodes.push({id:'exact'});
    const ctx=vm.createContext(c);vm.runInContext(overview.slice(overview.indexOf('  async function openReportEpisode('),overview.indexOf('  async function load(')),ctx);
    let error;try{await vm.runInContext('openReportEpisode("exact",'+JSON.stringify(basis)+',"one",5)',ctx)}catch(e){error=e}
    if(['unready','basis','missing','duplicate'].includes(mode))assert.ok(error,mode);
    assert.deepEqual(located,['ok','selection-during'].includes(mode)?['exact']:[],mode);
    assert.equal(details.open,mode==='ok',mode);
  }
  console.log('Rhythm/report roundtrip guards, preservation, exact identity and explicit replacement passed');
})().catch(e=>{console.error(e);process.exitCode=1});
