'use strict';
// Exercise shipped handlers: looking at a candidate, selecting a strip and
// confirming a whole episode are deliberately separate operations.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const ui=fs.readFileSync('static/js/clinical-ui.js','utf8');
const region=(start,end)=>{const a=ui.indexOf(start),b=ui.indexOf(end,a);assert(a>=0&&b>a);return ui.slice(a,b);};
const helpers=region('  const reportCategories=','  const tabs=');
const engine=require('../static/js/report-engine.js');
function node(tag='TR'){
 const handlers={},attrs={};return {tagName:tag,isConnected:true,dataset:{},setAttribute:(k,v)=>attrs[k]=v,addEventListener:(k,v)=>handlers[k]=v,
  fire:(kind,event)=>handlers[kind]?.({button:0,target:{closest:()=>null},clientX:10,clientY:10,preventDefault(){},stopPropagation(){},...event}),attrs};
}
async function rowsOnlyView(){
 for(const category of ['AF','rr_interval','V']){
  let views=0,picks=0;const e={event_id:'row',basis_version:'basis',category:category==='rr_interval'?'pause':category},row=node();
  const ctx=vm.createContext({A:{categories:[]},state:{caseId:'math',caseRequestId:1,currentPage:'report'},category,waveEvidenceScope:'scope',reportData:{items:[e]},selected:()=>[],selectedLookup:new Map(),document:{activeElement:null,querySelectorAll:()=>[{dataset:{include:'0'},disabled:false}]},run:fn=>fn(),locate:async()=>views++,selectEvent:async()=>picks++});
  vm.runInContext(helpers,ctx);vm.runInContext(fs.readFileSync('static/js/chart-inspection.js','utf8'),ctx);vm.runInContext(region('  function bindReportSelection(','  function updateReportPaper('),ctx);
  ctx.bindReportSelection(row,e);row.fire('click');row.fire('keydown',{target:row,key:'Enter'});
  assert.deepEqual([views,picks],category==='V'?[0,2]:[2,0]);
  row.fire('click',{target:{closest:()=>({tagName:'BUTTON'})}});assert.equal(views+picks,2,'internal controls also triggered row action');
 }
}
function memberContext(category,entries=[]){
 const composition={selected_events:entries,category_reviews:{},diagnosis_blocks:[]},state={caseId:'math',caseRequestId:1,currentPage:'report',reportDisplayedCategory:category,reportComposition:composition},counts={dirty:0,confirmed:0};
 const ctx=vm.createContext({A:{categories:[['AF','房颤'],['pause','长RR'],['rr_candidate','自选RR']]},state,category,selected:()=>composition.selected_events,selectedLookup:new Map(),ECGReportEngine:engine,ECGReportRange:{pending:()=>[]},returnedRhythmSelection:()=>null,reportData:{items:[],total:0},reportWaveReady:true,reportOffset:0,waveEvidenceScope:'scope',active:null,copy:x=>JSON.parse(JSON.stringify(x)),syncText(){},dirty(){counts.dirty++;},renderReportShell(){},renderEventNavigation(){},renderReportBody:async()=>{},document:{querySelectorAll:()=>[]},qs:()=>null,run:f=>f(),toast(){},locate:async()=>{},syncReportMembership(){},confirmReportRhythm(){counts.confirmed++;}});
 vm.runInContext(helpers,ctx);vm.runInContext(region('  function selectEvent(','  let removedReportStrip='),ctx);return {ctx,composition,counts,state};
}
async function selections(){
 const x=memberContext('AF'),e={event_id:'af',basis_version:'af-b',category:'AF',rhythm_status:'pending',subtype:'AF',label:'候选'};x.ctx.reportData={items:[e],total:1};x.ctx.active=e;
 await x.ctx.selectEvent(e,true);assert.equal(x.counts.confirmed,0);assert.equal(x.composition.selected_events.length,1);await x.ctx.selectEvent(e,false);assert.equal(x.composition.selected_events.length,0);
 const first={event_id:'auto',basis_version:'a-b',caption:'保留图注',leads:['V1'],duration_s:10,range_start_s:1,range_end_s:11,notes:'保留备注'},canonical={event_id:'manual',basis_version:'m-b',category:'rr_candidate',rr_semantic_key:'pair',rr_alias_event_ids:['manual','auto'],rr_aliases:[{event_id:'manual',basis_version:'m-b',category:'rr_candidate'},{event_id:'auto',basis_version:'a-b',category:'pause'}]};
 const y=memberContext('rr_interval',[{...first}]);y.ctx.active=canonical;await y.ctx.selectEvent(canonical,true);assert.deepEqual(y.composition.selected_events,[first]);assert.equal(y.counts.dirty,0);
 y.composition.selected_events.push({event_id:'manual',basis_version:'m-b',caption:'第二来源'});await y.ctx.selectEvent(canonical,false);assert.equal(y.composition.selected_events.length,0);
 const z=memberContext('rr_interval',[{...first},{event_id:'manual',basis_version:'m-b'},{event_id:'auto',basis_version:'stale',caption:'旧依据保留'}]);z.ctx.selectedLookup=new Map([['auto',{...canonical,event_id:'auto',basis_version:'a-b',category:'pause',subtype:'long',label:'自动长RR'}],['manual',{...canonical,subtype:'manual',label:'自选RR'}]]);
 const manual={key:'rr_candidate:manual',manual:true,text:'人工文字逐字保留',acknowledged:true,needs_review:false},other={key:'V:single',manual:false,text:'其它自动文字保留'};z.composition.diagnosis_blocks=[{key:'pause:long',manual:false,text:'首条自动文字'},{key:'pause:long',manual:false,text:'同类旧重复自动文字'},{key:'rr_candidate:manual',manual:false,text:'第二来源自动文字'},manual,other];
 z.ctx.projectRRSelections();assert.equal(z.composition.selected_events.length,2);assert.equal(z.composition.selected_events[0].caption,'保留图注');assert.equal(z.composition.selected_events[1].basis_version,'stale');assert.equal(z.counts.dirty,0,'view projection caused a report write');assert.deepEqual(Array.from(z.composition.diagnosis_blocks,b=>b.text),['首条自动文字','人工文字逐字保留','其它自动文字保留']);assert.equal(z.composition.diagnosis_blocks[1],manual,'view projection changed a handwritten block');assert.equal(z.composition.diagnosis_blocks[2],other,'RR projection changed another category');
}
async function confirmationUsesPendingWithoutApplying(){
 const e={event_id:'annotation:af:one',category:'AF',rhythm_episode_id:'one',rhythm_status:'pending',start_sample:200000,end_s:7500},pending={event:e,basis:'scope',a:4200,b:4207},state={caseId:'math',caseRequestId:1,currentPage:'report',reportComposition:{strip_defaults:{leads:['II','V1','V5'],duration_s:7}},caseData:{metadata:{start_time:'2026-01-01 00:00:00'}}};let decision,reads=0,writes=0;
 const ctx=vm.createContext({state,rhythmOpening:false,active:e,reportData:{analysis_basis:'basis'},reportWaveReady:true,waveEvidenceScope:'scope',ECGReportRange:{pending:()=>[pending],resolveLeave(){throw Error('Unexpected extra apply confirmation');}},ECGReportEngine:engine,ECGAnalysisConsistency:{identity:x=>x},ECGRhythmRangeEditor:{boundaryClock:String},clinicalWorkflow:{writable:()=>true},copy:x=>JSON.parse(JSON.stringify(x)),selected:()=>[],composition:()=>state.reportComposition,flushReportAutosave:async()=>{},reportStrip:async(_,spec)=>{reads++;assert.equal(spec.range_start_s,4200);assert.equal(spec.range_end_s,4207);return {strip:{start_s:4200,end_s:4207,actual_duration_s:7,visible_beat_count:8}};},endpoint:async()=>({revision:1,beat_revision:0,document:{episodes:[{id:'one',kind:'AF',status:'pending',start_s:1000,end_s:7500}]}}),ECGUnsavedNavigation:{resolve:async options=>{decision=options;return false;}},crypto:{randomUUID:()=> 'math-only'},api:async()=>writes++,syncReportMembership(){},renderReportShell(){}});
 vm.runInContext('const eventAliases=e=>[{event_id:e.event_id,basis_version:e.basis_version}];function selectionForEvent(){return null;}',ctx);vm.runInContext(region('  async function confirmReportRhythm(','  function hasRhythmReturn('),ctx);await ctx.confirmReportRhythm(e);
 assert.equal(reads,1);assert.equal(writes,0);assert.equal(pending.a,4200);assert.match(decision.detail,/6500.000 秒/);assert.match(decision.detail,/4200 — 4207 · 7.000 秒 · 8 搏/);assert.match(decision.saveLabel,/确认整段/);
}
async function browseKeepsSelectionAndRejectsLateReads(){
 const e={event_id:'af',category:'AF',rhythm_episode_id:'one',start_sample:200000,end_s:7500,rhythm_status:'pending'},draft={a:4200,b:4207},entry={strip:{start_s:1000,end_s:1007,actual_duration_s:7,duration_s:7,visible_beat_count:8,leads:['II','V1','V5']}},wave={start_s:4196,duration_s:15};
 const controls=new Map(),buttons=['start','middle','end','strip','previous','next'].map(kind=>({dataset:{afBrowse:kind}})),nav={setAttribute(){},querySelectorAll:()=>buttons,querySelector:selector=>{if(!controls.has(selector))controls.set(selector,{value:selector==='[data-af-strip-duration]'?'7':'',innerHTML:''});return controls.get(selector);}};
 const target={dataset:{},isConnected:true,querySelector:()=>null},holder={before(){},_rangeDisplayState:()=>({mode:12,gain:1}),_rangeRead:()=>({start:draft.a,end:draft.b})},tasks=[],mounts=[];
 const ctx=vm.createContext({A:{categories:[]},active:e,waveEvidenceScope:'scope',state:{caseId:'math',caseRequestId:1,caseData:{metadata:{start_time:'math'},technical:{duration_seconds_raw:10000}}},document:{createElement:()=>nav},ECGRhythmRangeEditor:{boundaryClock:String},ECGReportRange:{resolveLeave(){throw Error('Same-candidate browsing must not resolve an unapplied selection');}},ECGReportEngine:engine,esc:String,selected:()=>[],selectedLookup:new Map(),run:fn=>{const task=fn();tasks.push(task);return task;},reportStrip:async()=>entry,mountRange:async(_target,_event,_entry,_id,view)=>{mounts.push(view);return wave;},beatEditor:{bindWaveSurface(){}}});
 vm.runInContext(helpers,ctx);vm.runInContext(region('  function mountRhythmBrowser(','  async function mountRange('),ctx);ctx.mountRhythmBrowser(target,holder,e,entry,wave,'math',()=>true,{});
 buttons.find(b=>b.dataset.afBrowse==='end').onclick();await Promise.all(tasks);assert.equal(mounts.at(-1).start,7492.5);assert.deepEqual(draft,{a:4200,b:4207});assert.equal(mounts.at(-1).displayState.mode,12);
 let first,second;ctx.reportStrip=()=>new Promise(resolve=>{if(!first)first=resolve;else second=resolve;});
 buttons.find(b=>b.dataset.afBrowse==='middle').onclick();buttons.find(b=>b.dataset.afBrowse==='start').onclick();second(entry);await tasks.at(-1);first(entry);await tasks.at(-2);assert.equal(mounts.length,2,'late browse read remounted an older position');assert.equal(mounts.at(-1).start,992.5);assert.deepEqual(draft,{a:4200,b:4207});
 controls.get('[data-af-strip-duration]').value='30';ctx.reportStrip=async()=>entry;controls.get('[data-af-use-view]').onclick();await tasks.at(-1);assert.equal(mounts.at(-1).length,32);assert.equal(mounts.at(-1).chooseRange.range_end_s-mounts.at(-1).chooseRange.range_start_s,30);
}
(async()=>{await browseKeepsSelectionAndRejectsLateReads();await rowsOnlyView();await selections();await confirmationUsesPendingWithoutApplying();console.log('Candidate handlers: AF/RR pure viewing, explicit draft selection, current RR alias preservation/removal/projection and single-dialog pending-range confirmation passed');})().catch(e=>{console.error(e);process.exitCode=1;});
