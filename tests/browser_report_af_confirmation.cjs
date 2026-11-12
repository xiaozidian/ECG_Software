'use strict';
// Real whole-episode confirmation and AF append handlers; isolated mathematical
// revision ledger, including an intentionally lost committed reply.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('static/js/clinical-ui.js','utf8'),engine=require('../static/js/report-engine.js');
const region=(a,b)=>{const i=source.indexOf(a),j=source.indexOf(b,i);assert(i>=0&&j>i);return source.slice(i,j);};
const e={event_id:'annotation:af:math',category:'AF',subtype:'AF',basis_version:'before-confirm',rhythm_episode_id:'math',rhythm_status:'pending',start_sample:20000,end_s:400,label:'房颤'},fresh={...e,basis_version:'after-confirm',rhythm_status:'confirmed'};
const first={event_id:e.event_id,basis_version:e.basis_version,strip_id:'first',caption:'原首图',leads:['V1'],duration_s:7,range_start_s:100,range_end_s:107,notes:'首图备注',print_enabled:false},middle={...first,strip_id:'middle',caption:'原中图',leads:['II','V1','V5'],range_start_s:200,range_end_s:207,print_enabled:true},stale={...first,strip_id:'old-stale',basis_version:'older',caption:'旧依据保留'};
const state={caseId:'math',caseRequestId:1,currentPage:'report',report:{version:3},caseData:{metadata:{start_time:'2026-01-01 00:00:00'}},reportComposition:{selected_events:structuredClone([first,middle,stale]),strip_defaults:{leads:['II','V1','V5'],duration_s:7},category_reviews:{},diagnosis_blocks:[]}};
let writes=0,receipts=0,dialogs=0,saves=0,committed=null;const forgotten=[],pending={event:e,basis:'scope',stripKey:'af-new-choice',a:250,b:257};
const choice={event_id:e.event_id,basis_version:e.basis_version,draftKey:pending.stripKey,replaceKey:null,role:'custom',settings:{leads:engine.leads,duration_s:7,range_start_s:250,range_end_s:257}},target={dataset:{afStripKey:pending.stripKey},_afCurrentStrip:()=>choice};
const lookup=new Map([[e.event_id,e]]);
const ctx=vm.createContext({state,A:{categories:[['AF','房颤']]},active:e,reportData:{analysis_basis:'math-source',analysis_revision:1},reportWaveReady:true,waveEvidenceScope:'scope',rhythmOpening:false,ECGReportEngine:engine,ECGReportRange:{pending:()=>[pending],forget:key=>forgotten.push(key),resolveLeave(){throw Error('extra range dialog');}},selected:()=>state.reportComposition.selected_events,selectedLookup:lookup,composition:()=>state.reportComposition,copy:x=>structuredClone(x),qs:selector=>selector==='#v2EventWave'?target:null,clinicalWorkflow:{writable:()=>true,refresh:async()=>{}},ECGAnalysisConsistency:{identity:x=>x,assertSame(){}},ECGRhythmRangeEditor:{boundaryClock:String},crypto:{randomUUID:()=> 'single-confirmation'},globalThis:null,
 reportStrip:async(event,s)=>({strip:{start_s:s.range_start_s??100,end_s:s.range_end_s??107,actual_duration_s:s.duration_s||7,visible_beat_count:8}}),
 endpoint:async(kind)=>{if(kind==='rhythm-review'){if(committed)receipts++;return {revision:committed?4:3,beat_revision:0,last_operation:committed?{request_id:committed.request_id,operation:'save',revision:4}:null,document:{episodes:[{id:'math',kind:'AF',status:committed?'confirmed':'pending',start_s:100,end_s:400}]}};}if(kind==='report-events')return {items:[fresh]};throw Error(kind);},
 api:async(_,options)=>{writes++;committed=JSON.parse(options.body);throw Error('intentional lost committed response');},
 ECGUnsavedNavigation:{resolve:async options=>{dialogs++;options={...options,...await options.prepare(options.isCurrent)};assert.match(options.detail,/整段候选：[\s\S]*300.000 秒[\s\S]*本次图条：[\s\S]*250 — 257/);await options.save();return true;}},
 flushReportAutosave:async()=>{saves++;},overviewWorkbench:{invalidateAfterWrite(){}},refreshHrvCase:async()=>{},refreshReport:async()=>{if(committed){lookup.set(e.event_id,fresh);ctx.reportData={analysis_basis:'math-source',analysis_revision:2};}},ECGReportStripEditor:{curation:()=>({})},syncText(){},dirty(){},renderReportShell(){},syncReportMembership(){},toast(){},locate:async()=>{},renderReportBody:async()=>{}});
delete ctx.globalThis;
vm.runInContext(region('  const reportCategories=','  function projectRRSelections('),ctx);vm.runInContext(region('  function enableSTTStripUse(','  function sttNarrative('),ctx);vm.runInContext(region('  async function addAFStrip(','  function selectEvent('),ctx);vm.runInContext(region('  async function confirmReportRhythm(','  function hasRhythmReturn('),ctx);
(async()=>{
 await ctx.confirmReportRhythm(e);assert.equal(writes,1);assert.equal(receipts,1);assert.equal(dialogs,1);assert(saves>=2);assert.deepEqual(forgotten,['af-new-choice']);
 const picks=state.reportComposition.selected_events;assert.equal(picks.length,4);for(const old of [first,middle]){const next=picks.find(s=>s.strip_id===old.strip_id);assert.deepEqual({...next,basis_version:old.basis_version},old);assert.equal(next.basis_version,fresh.basis_version);}assert.deepEqual(picks.find(s=>s.strip_id==='old-stale'),stale,'whole confirmation revived an earlier stale sibling');const added=picks.find(s=>!['first','middle','old-stale'].includes(s.strip_id));assert.equal(added.range_start_s,250);assert.equal(added.range_end_s,257);assert.equal(added.leads.length,12);assert.equal(committed.document.episodes[0].start_s,100);assert.equal(committed.document.episodes[0].end_s,400);
 console.log('AF confirmation: one dialog/write, lost receipt recovery, all current siblings rebased without changing curation, stale sibling retained and new middle range independent passed');
 for(const initial of [[first,middle,stale],[]]){
  writes=0;receipts=0;dialogs=0;committed=null;forgotten.length=0;state.reportComposition.selected_events=structuredClone(initial);lookup.set(e.event_id,e);ctx.reportData={analysis_basis:'math-source',analysis_revision:1};
  ctx.ECGUnsavedNavigation.resolve=async options=>{dialogs++;options={...options,...await options.prepare(options.isCurrent)};assert.equal(options.title,'确认整段房颤');assert(!options.detail.includes('本次图条'));await options.save();return true;};
  await ctx.confirmReportRhythm(e,null,{adopt:false});assert.equal(writes,1);assert.equal(dialogs,1);assert.equal(state.reportComposition.selected_events.length,initial.length,'whole confirmation adopted another strip');
  for(const old of initial){const next=state.reportComposition.selected_events.find(s=>s.strip_id===old.strip_id);assert.deepEqual({...next,basis_version:old.basis_version},old);assert.equal(next.basis_version,old.basis_version==='before-confirm'?'after-confirm':old.basis_version);}
  assert.deepEqual(forgotten,[],'whole-only confirmation discarded a range choice');
 }
 console.log('Whole-only AF confirmation: zero stays zero, three siblings stay three with original IDs/curation, no per-strip adoption and no discarded range passed');

})().catch(error=>{console.error(error);process.exitCode=1;});
