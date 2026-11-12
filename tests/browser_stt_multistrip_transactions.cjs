'use strict';
// Actual shipped handlers in a narrow DOM/transport/clock fixture. No mirrored
// transaction implementation, real service, browser automation or patient data.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),crypto=require('node:crypto');
require('../static/js/rr-quality.js');
const engine=require('../static/js/report-engine.js'),analysis=require('../static/js/clinical-analysis.js');
const source=fs.readFileSync('static/js/clinical-ui.js','utf8');
const region=(a,b)=>{const i=source.indexOf(a),j=source.indexOf(b,i+1);assert(i>=0&&j>i,'Production boundary changed: '+a);return source.slice(i,j);};
function production(ctx,name,async=false){
 const begin=source.indexOf(`\n  ${async?'async ':''}function ${name}(`)+1;assert(begin>0,'Missing '+name);
 const firstEnd=source.indexOf('\n',begin),line=source.slice(begin,firstEnd);
 const end=line.endsWith('}')?firstEnd:source.indexOf('\n  }',firstEnd)+4;
 assert(end>begin,'Missing function end '+name);vm.runInContext(source.slice(begin,end),ctx);
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const clone=x=>JSON.parse(JSON.stringify(x));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
class Clock{
 constructor(){this.next=0;this.jobs=new Map();this.delays=[];}
 set(fn,delay){const id=++this.next;this.jobs.set(id,fn);this.delays.push(delay);return id;}
 clear(id){this.jobs.delete(id);}
 fire(){const [id,fn]=this.jobs.entries().next().value||[];assert(fn,'No production autosave scheduled');this.jobs.delete(id);return fn();}
}
function fixture(){
 const e={event_id:'annotation:math',basis_version:'math-basis',category:'ST',subtype:'ST',label:'数学ST/T',
   start_sample:4000,end_sample:63999,time_s:20,end_s:320,stt_review_state:'reviewed',
   stt_report_eligibility:{table:true,text:true,strip:true},stt_review_receipt:{result_codes:['st_depression','t_low_flat'],leads:['II','V5']}};
 const clock=new Clock(),nodes=new Map(),created=[],validations=[],puts=[],tasks=[],toasts=[],forgotten=[];
 const comp={schema_version:3,included_pages:['st_events','event_strips'],selected_events:[],category_reviews:{},diagnosis_blocks:[],
   strip_defaults:{duration_s:7},stt_report_use:[{event_id:e.event_id,basis_version:e.basis_version,table:true,text:true,strip:false}]};
 const state={caseId:'math',caseRequestId:1,currentPage:'report',report:{version:1,review_revision:0,composition:clone(comp)},reportComposition:comp,
   caseData:{metadata:{start_time:'2026-01-01 08:00:00'},technical:{duration_seconds_raw:360},summary:{}},reportDirty:false};
 const index={events:[e],rows:Array.from({length:359},(_,i)=>({sample_index:(i+1)*200,class_code:'N',rr_ms:1000,hr:60})),duration_s:360};
 function node(tag='div'){
  const controls=new Map(),handlers=new Map(),children=[];
  const item={tagName:tag.toUpperCase(),dataset:{},isConnected:true,disabled:false,value:'7',textContent:'',innerHTML:'',style:{},children,
   setAttribute(){},append(child){children.push(child);},after(){},before(){},remove(){item.isConnected=false;},
   addEventListener(k,fn){handlers.set(k,fn);},fire(k){return handlers.get(k)?.();},
   querySelector(sel){if(!controls.has(sel))controls.set(sel,node(sel==='[data-stt-include-recommended]'?'button':'input'));return controls.get(sel);},
   querySelectorAll(){return []},_controls:controls};created.push(item);return item;
 }
 const document={createElement:node,querySelectorAll:()=>[],querySelector:sel=>nodes.get(sel)||null};
 nodes.set('#conclusionEditor',{value:'数学测试原文'});nodes.set('#reportSaveState',{textContent:''});nodes.set('#reportV2Notice',node());
 const ctx=vm.createContext({state,A:analysis,ECGReportEngine:engine,ECGReportSections:require('../static/js/report-sections.js'),
   copy:clone,selected:()=>state.reportComposition.selected_events,selectedLookup:new Map([[e.event_id,e]]),active:e,
   waveEvidenceScope:'scope',waveEvidence:{},category:'ST',reportData:{items:[e]},reportVersion:1,reportWaveReady:true,document,
   qs:sel=>nodes.get(sel)||null,clinicalWorkflow:{writable:()=>true,renderPreflight(){}},
   setTimeout:(fn,delay)=>clock.set(fn,delay),clearTimeout:id=>clock.clear(id),
   syncText(){},cancelReportExport(){},renderReportShell(){},renderEventNavigation(){},renderReportBody:async()=>{},
   bodyCurrent:()=>true,locate:async()=>{},syncReportMembership(){},formatElapsed:String,esc:String,
   toast:(...args)=>toasts.push(args),ECGRhythmRangeEditor:{boundaryClock:String},
   ECGReportRange:{pending:()=>[],forget:key=>forgotten.push(key)},
   run:fn=>{const task=Promise.resolve().then(fn);tasks.push(task);return task;},
   reportStrip:async(event,spec)=>{const gate=deferred();validations.push({gate,event,spec:clone(spec)});await gate.promise;return {strip:engine.resolve(index,event,spec)};},
   endpoint:async(kind)=>{assert.equal(kind,'report');return state.report;},
   api:async(url,options)=>{
    assert.equal(url,'/api/cases/math/report');assert.equal(options.method,'PUT');
    const payload=JSON.parse(options.body),gate=deferred();puts.push({payload,gate});await gate.promise;
    // Use the actual production Pages/native-parity normalizer. The separate
    // Python API test owns native SQL persistence validation.
    const normalized={...payload.composition,selected_events:analysis.normalizeReportSelections(index,payload.composition.selected_events)};
    return {version:payload.expected_version+1,review_revision:0,status:payload.status,conclusion:payload.conclusion,composition:normalized};
   }});
 vm.runInContext(fs.readFileSync('static/js/report-consistency.js','utf8'),ctx);
 vm.runInContext(region('  const reportCategories=','  const tabs='),ctx);
 require('./clinical_ui_report_helpers.cjs').prepare(ctx);
 vm.runInContext(region('  let reportAutosaveTimer=','  async function resolveReportLeave('),ctx);
 for(const [name,async] of [['dirty',false],['save',true],['persistReport',true],['addAFStrip',true]])production(ctx,name,async);
 vm.runInContext(region('  let removedReportStrip=','  function enableReportDraftSelections('),ctx);
 production(ctx,'mountRhythmBrowser');
 const printStart=source.indexOf('onStripPrint:'),printEnd=source.indexOf(',onStripRemove:',printStart);
 assert(printStart>=0&&printEnd>printStart);vm.runInContext('globalThis.onStripPrint='+source.slice(printStart+'onStripPrint:'.length,printEnd),ctx);
 const target={dataset:{},isConnected:true,querySelector:()=>null},holder={before(nav){fixtureNav=nav;}};let fixtureNav;
 const reps={requested_duration_s:7,items:[{representative_role:'start',start_s:20,end_s:27,label:'段首'},
   {representative_role:'middle',start_s:160,end_s:167,label:'极值'}, {representative_role:'end',start_s:313,end_s:320,label:'段末'}],positions:{}};
 ctx.mountRhythmBrowser(target,holder,e,{strip:{start_s:20,end_s:27,duration_s:7,leads:engine.leads}},
   {start_s:16,duration_s:15},'math',()=>true,{representatives:reps,stripDuration:7});
 const button=fixtureNav.querySelector('[data-stt-include-recommended]');
 function pick(start,role,enabled=true){return {event_id:e.event_id,basis_version:e.basis_version,strip_id:'math:'+role,representative_role:role,
   range_start_s:start,range_end_s:start+7,duration_s:7,leads:['II'],caption:'原图注'+role,notes:'原备注'+role,print_enabled:enabled};}
 function undoButton(){return created.filter(x=>x.tagName==='BUTTON'&&x.textContent==='撤销移除图条').at(-1);}
 return {ctx,state,e,index,clock,validations,puts,tasks,button,pick,undoButton,toasts,forgotten};
}
async function resolveWave(x,n){assert(x.validations[n],'Missing real waveform validation '+n);x.validations[n].gate.resolve();await tick();}
async function resolvePut(x,n){assert(x.puts[n],'Missing actual persistReport PUT '+n);x.puts[n].gate.resolve();await tick();}

async function atomicBulk(){
 const x=fixture(),adding=x.button.fire('click');await tick();assert(x.state.sttReportAdding);assert.equal(x.validations.length,1);
 await resolveWave(x,0);assert.equal(x.state.reportComposition.selected_events.length,1);assert.equal(x.validations.length,2);
 await x.clock.fire();assert.equal(x.puts.length,0,'Batch must defer a700ms intermediate snapshot, not claim it alone caused prior truncation');assert(x.clock.delays.includes(400));
 await resolveWave(x,1);assert.equal(x.state.reportComposition.selected_events.length,2);await x.clock.fire();assert.equal(x.puts.length,0);
 await resolveWave(x,2);assert.equal(x.state.reportComposition.selected_events.length,3);assert.equal(x.puts.length,1);
 assert.equal(x.puts[0].payload.composition.selected_events.length,3,'Final transport snapshot must include all3');
 await resolvePut(x,0);await adding;
 assert.equal(x.state.reportComposition.selected_events.length,3,'Actual normalizer and autosave response must retain3 distinct same-parent ranges');
 assert.equal(new Set(x.state.reportComposition.selected_events.map(s=>s.strip_id)).size,3);
 assert.equal(x.state.reportDirty,false);assert.equal(x.state.sttReportAdding,null);assert.equal(x.button.disabled,false);
 return 'bulk defers intermediate saves and final actual normalization preserves3';
}
async function waitsForExistingSave(){
 const x=fixture();x.ctx.dirty();const saving=x.clock.fire();await tick();assert.equal(x.puts.length,1);
 const adding=x.button.fire('click');await tick();assert(x.state.sttReportAdding);assert.equal(x.validations.length,0,'Must await an in-flight save before snapshot-sensitive additions');
 await resolvePut(x,0);await saving;await tick();assert.equal(x.validations.length,1);
 for(let i=0;i<3;i++)await resolveWave(x,i);
 assert.equal(x.puts.length,2);assert.equal(x.puts[1].payload.composition.selected_events.length,3);
 await resolvePut(x,1);await adding;assert.equal(x.state.reportComposition.selected_events.length,3);assert.equal(x.state.reportDirty,false);
 return 'existing save settled before all3 additions';
}
async function doubleClickAndFailure(){
 const x=fixture(),first=x.button.fire('click');await tick();const duplicate=x.button.fire('click');await duplicate;
 assert.equal(x.validations.length,1,'Owner guard prevents overlapping duplicate batches');
 await resolveWave(x,0);x.validations[1].gate.reject(new Error('controlled waveform transport failure'));
 await assert.rejects(first,/controlled waveform/);assert.equal(x.state.sttReportAdding,null);assert.equal(x.button.disabled,false);
 assert.equal(x.state.reportComposition.selected_events.length,1,'Already validated first pick is retained on later failure');
 const saving=x.clock.fire();await tick();assert.equal(x.puts.length,1);assert.equal(x.puts[0].payload.composition.selected_events.length,1);
 await resolvePut(x,0);await saving;
 return 'double click rejected, failure releases owner and retains validated curation';
}
async function printingAndUndo(){
 const x=fixture();x.state.reportComposition.selected_events=[x.pick(20,'start'),x.pick(160,'middle'),x.pick(313,'end')];
 x.state.reportComposition.stt_report_use[0].strip=true;
 x.ctx.onStripPrint(0,false);assert.equal(x.state.reportComposition.stt_report_use[0].strip,true,'Disabling one must not suppress2 printable siblings');
 x.ctx.onStripPrint(1,false);assert.equal(x.state.reportComposition.stt_report_use[0].strip,true);
 x.ctx.onStripPrint(2,false);assert.equal(x.state.reportComposition.stt_report_use[0].strip,false);
 x.ctx.onStripPrint(2,true);assert.equal(x.state.reportComposition.stt_report_use[0].strip,true);
 const oldText=clone(x.state.reportComposition.stt_report_use[0]);
 x.ctx.removeReportSelection(2);assert.equal(x.state.reportComposition.stt_report_use[0].strip,false,'Remaining disabled siblings do not reenable parent strip use');
 assert.equal(x.state.reportComposition.stt_report_use[0].table,oldText.table);assert.equal(x.state.reportComposition.stt_report_use[0].text,oldText.text);
 x.ctx.onStripPrint(0,true);x.ctx.renderStripUndo();x.undoButton().onclick();
 assert.equal(x.state.reportComposition.selected_events.length,3);assert.equal(x.state.reportComposition.stt_report_use[0].strip,true);
 assert.equal(x.state.reportComposition.selected_events[2].caption,'原图注end');
 // Undoing a nonprinting pick must not restore the old parent true flag when
 // all current siblings have since been disabled.
 x.ctx.removeReportSelection(1);x.ctx.onStripPrint(0,false);x.ctx.onStripPrint(1,false);x.ctx.renderStripUndo();x.undoButton().onclick();
 assert.equal(x.state.reportComposition.selected_events.length,3);assert.equal(x.state.reportComposition.stt_report_use[0].strip,false);
 return 'one-strip print toggles and delete/undo aggregate current siblings while preserving table/text';
}
async function staleUndoBlocked(){
 const x=fixture();x.state.reportComposition.selected_events=[x.pick(20,'start')];x.state.reportComposition.stt_report_use[0].strip=true;
 x.ctx.removeReportSelection(0);x.e.stt_review_state='stale';x.e.stt_report_eligibility.strip=false;x.ctx.renderStripUndo();x.undoButton().onclick();
 assert.equal(x.state.reportComposition.selected_events.length,0,'Equal historical basis string does not authorize stale adoption');
 assert(x.toasts.some(t=>String(t[0]).includes('复核依据已变化')));
 return 'stale review blocks undo even when basis string unchanged';
}
async function cancellationOwnsDraftKeys(){
 const x=fixture();x.state.reportComposition.selected_events=[x.pick(20,'start'),x.pick(160,'middle')];x.state.reportComposition.stt_report_use[0].strip=true;
 // A resolved navigation may expose newly queued owner drafts. Exercise the
 // branch's exact ownership cleanup without asserting the old path reachable.
 let reads=0;const drafts=[{event:{event_id:x.e.event_id},stripKey:'math:start'}, {event:{event_id:x.e.event_id},stripKey:'af-new:math'}, {event:{event_id:'another'},stripKey:'other'}];
 x.ctx.ECGReportRange.pending=()=>++reads===1?[]:drafts;
 await x.ctx.setSTTUse(x.e,'strip',false);
 assert.equal(x.state.reportComposition.selected_events.length,0);assert.equal(x.state.reportComposition.stt_report_use[0].strip,false);
 assert(x.forgotten.includes('math:start')&&x.forgotten.includes('af-new:math'));assert(!x.forgotten.includes('other'));
 return 'parent cancellation only clears its own keyed drafts and keeps table/text';
}
async function duplicateReenablePreservesCuration(){
 const x=fixture(),original=x.pick(20,'start',false);x.state.reportComposition.selected_events=[original];
 const adding=x.ctx.addAFStrip(x.e,{...x.ctx.newStripSettings(x.e),duration_s:7,range_start_s:20,range_end_s:27,caption:'不能覆盖原图注'},{role:'start',render:false});
 await tick();await resolveWave(x,0);await adding;
 assert.equal(x.state.reportComposition.selected_events.length,1);assert.equal(x.state.reportComposition.selected_events[0],original);
 assert.equal(original.print_enabled,true);assert.equal(original.caption,'原图注start');assert.equal(original.notes,'原备注start');
 assert.deepEqual(original.leads,['II']);assert.equal(x.state.reportComposition.stt_report_use[0].strip,true);
 assert.equal(x.state.reportComposition.stt_report_use[0].table,true);assert.equal(x.state.reportComposition.stt_report_use[0].text,true);
 return 'explicit same-range re-add reenables printing without duplicate or curation overwrite';
}
const scenarios={atomicBulk,waitsForExistingSave,doubleClickAndFailure,printingAndUndo,staleUndoBlocked,cancellationOwnsDraftKeys,duplicateReenablePreservesCuration};
(async()=>{
 const name=process.argv[2];assert(name in scenarios,'Unknown transaction scenario');const outcome=await scenarios[name]();
 process.stdout.write(JSON.stringify({scenario:name,status:'passed',outcome,source_sha256:crypto.createHash('sha256').update(source).digest('hex'),actual_function_extraction:true,transport_and_DOM_fixture:true})+'\n');
})().catch(e=>{console.error(e);process.exitCode=1;});
