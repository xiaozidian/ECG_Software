'use strict';
// Execute shipped ST report handlers with disposable mathematical DTOs and DOM
// command probes. No services, user workspace, browser storage or PDF exports.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('static/js/clinical-ui.js','utf8'),A=require('../static/js/clinical-analysis.js'),R=require('../static/js/report-engine.js'),S=require('../static/js/report-sections.js');
const between=(a,b)=>{const i=source.indexOf(a),j=source.indexOf(b,i+1);assert(i>=0&&j>i,`Shipped source boundary: ${a}`);return source.slice(i,j);};
const copy=x=>JSON.parse(JSON.stringify(x)),plain=x=>JSON.parse(JSON.stringify(x));
const resultCodes=['st_depression','st_elevation','t_change','nonspecific','no_change','artifact','indeterminate'];
const event=(code,n=1,extra={})=>({event_id:'annotation:'+n,basis_version:'record-'+n,category:'ST',subtype:'ST',label:code,time_s:n*100,end_s:n*100+120,lead:'II',stt_result_code:code,stt_review_state:'reviewed',stt_report_group:n<=2?'ST':code==='t_change'?'T':'ST_NOTE',diagnosis_status:['st_depression','st_elevation','t_change','nonspecific'].includes(code)?'confirmed':'pending',stt_report_eligibility:{table:['st_depression','st_elevation','t_change'].includes(code),text:true,strip:true},stt_review_receipt:{leads:['II']},stt_physician_note:'医生原文 '+n,...extra});
class NodeProbe{
 constructor(tag='DIV',dataset={}){this.tagName=tag;this.dataset=dataset;this.isConnected=true;this.value='医生结论';this.checked=false;this.disabled=false;this.hidden=false;this.style={};this.children=[];this.nodes=new Map();this.classList={toggle(){}};}
 setAttribute(k,v){this[k]=v;}addEventListener(k,f){this[k]=f;}append(...x){this.children.push(...x);}after(n){this.afterNode=n;}before(){}remove(){this.isConnected=false;}contains(){return false;}focus(){}replaceChildren(...x){this.children=x;}
 set innerHTML(text){this.html=text;this.nodes=new Map();this.inputs=[];this.rows=[];
  for(const match of text.matchAll(/<input\b[^>]*data-stt-use="([^"]+)"[^>]*data-stt-index="(\d+)"[^>]*>/g)){const n=new NodeProbe('INPUT',{sttUse:match[1],sttIndex:match[2]});n.checked=/\bchecked\b/.test(match[0]);n.disabled=/\bdisabled\b/.test(match[0]);this.inputs.push(n);}
  for(const match of text.matchAll(/<tr data-preview="false">/g))this.rows.push(new NodeProbe('TR'));
 }
 get innerHTML(){return this.html||'';}
 querySelector(s){if(!this.nodes.has(s))this.nodes.set(s,new NodeProbe());return this.nodes.get(s);}
 querySelectorAll(s){return s==='[data-stt-use]'?this.inputs||[]:s==='tr[data-preview]'?this.rows||[]:[];}
}
function setup(events=resultCodes.map((code,i)=>event(code,i+1))){
 const nodes=new Map(),node=s=>{if(!nodes.has(s))nodes.set(s,new NodeProbe());return nodes.get(s);},host=node('#reportV2Content'),calls={dirty:0,locates:[],renders:0,navigation:[],writes:[],requests:[],tasks:[]};
 const c={schema_version:3,page_selection_version:1,included_pages:['summary'],selected_events:[],stt_report_use:[],diagnosis_blocks:[],category_reviews:{}};
 const state={caseId:'math-ST-adoption',caseRequestId:4,currentPage:'report',caseData:{metadata:{},summary:{}},report:{status:'draft',version:1,composition:c},reportComposition:c,reportDirty:false};
 const ctx=vm.createContext({state,A,ECGReportEngine:R,ECGReportSections:S,reportCategories:A.reportCategories||A.categories,tabs:[],copy,esc:String,formatElapsed:s=>String(s),document:{querySelector:node,querySelectorAll:s=>s==='[data-stt-use]'?host.querySelectorAll(s):[],createElement:tag=>new NodeProbe(tag.toUpperCase()),createTextNode:text=>({textContent:text})},qs:node,
  reportData:{items:events,total:events.length,stt_counts:{ST:2,T:1,ST_NOTE:4},confirmed_category_counts:{ST:4}},selectedLookup:new Map(events.map(e=>[e.event_id,e])),active:null,activeStripKey:null,category:'ST',sttGroup:'all',reportMode:'all',reportOffset:0,reportSort:'hr_desc',reportSpacing:0,pauseBand:'all',rrSource:'all',reportTimeRange:null,sttReportFocus:null,reportWaveReady:true,reportRenderToken:0,reportSavePromise:null,waveEvidenceScope:'math-scope',waveEvidence:{},removedReportStrip:null,reportCase:'math-ST-adoption',reportVersion:1,
  selected:()=>state.reportComposition.selected_events,stripKey:s=>s?.strip_id||s?.event_id,eventAliases:e=>[{event_id:e.event_id,basis_version:e.basis_version}],newStripSettings:(e,s)=>R.settingsForEvent(e,s||{}),
  dirty:()=>{calls.dirty++;state.reportDirty=true;},renderReportShell:()=>{calls.renders++;},renderReportBody:async()=>{},changeReportView:async f=>f(),locate:async e=>{calls.locates.push(e.event_id);ctx.active=e;},renderEventNavigation(){},
  run:f=>{const p=Promise.resolve().then(f);calls.tasks.push(p);return p;},resolveWorkstationLeave:async()=>true,goPage:name=>{calls.navigation.push(name);state.currentPage=name;},
  ECGReportRange:{pending:()=>[],forget:key=>calls.forgot=key},ECGChartInspection:{bindSelection:(n,f)=>n.selection=f},ECGReportWorkspace:{releaseTerminology(){},compose:(h,options)=>calls.compose=options},ECGReportPaper:{},api:()=>{calls.writes.push('unexpected');throw Error('View must not write');},toast:(...args)=>calls.toast=args,handleError:e=>{throw e;}
 });
 vm.runInContext(between('  function composition(){','  let reportAutosaveTimer='),ctx);
 vm.runInContext(between('  function selectionsForEvent(','  function newStripSettings('),ctx);
 vm.runInContext(between('  function syncText(){','  function selectionUndoCurrent('),ctx);
 vm.runInContext(between('  function renderStripUndo(){','  function enableReportDraftSelections('),ctx);
 vm.runInContext(between('  function bindReportSelection(','  function updateReportPaper('),ctx);
 vm.runInContext(between('  async function renderSTTReportBody(','  async function renderReportBody('),ctx);
 return {ctx,state,host,node,calls,events,settle:async()=>{for(let i=0;i<3;i++){const pending=calls.tasks.splice(0);if(pending.length)await Promise.all(pending);}}};
}
async function readOnlyRows(){
 const x=setup(),before=JSON.stringify(x.state.reportComposition);await x.ctx.renderSTTReportBody(x.host,()=>true);
 for(const code of resultCodes)assert(x.host.innerHTML.includes(x.ctx.sttOutcomes?.[code]||({st_depression:'ST段压低',st_elevation:'ST段抬高',t_change:'T波改变',nonspecific:'非特异性ST-T改变',no_change:'本段未见明确ST-T改变',artifact:'伪差或体位改变',indeterminate:'本段无法判读'})[code]));
 assert.equal(x.host.querySelectorAll('[data-stt-use]').length,21);assert.equal(x.calls.dirty,0);assert.equal(JSON.stringify(x.state.reportComposition),before);
 const row=x.host.rows[5];row.selection();await x.settle();assert.equal(x.ctx.active.event_id,x.events[5].event_id);assert.equal(x.calls.dirty,0);assert.equal(JSON.stringify(x.state.reportComposition),before);assert.deepEqual(x.calls.writes,[]);
 x.host.querySelector('#v2STGroup').onchange({target:{value:'ST_NOTE'}}); // shipped filtering handler; no adoption
 await x.settle();assert.equal(x.ctx.sttGroup,'ST_NOTE');assert.equal(x.calls.dirty,0);assert.equal(JSON.stringify(x.state.reportComposition),before);
}
async function independentAdoption(){
 const x=setup(),e=x.events[0];x.ctx.active=e;
 await x.ctx.setSTTUse(e,'table',true);let c=x.state.reportComposition;
 assert.deepEqual(plain(c.stt_report_use),[{event_id:e.event_id,basis_version:e.basis_version,table:true,text:false,strip:false}]);assert.equal(c.selected_events.length,0);assert(c.included_pages.includes('st_events'));assert.equal(c.diagnosis_blocks.length,0);
 await x.ctx.setSTTUse(e,'text',true);c=x.state.reportComposition;assert.equal(c.selected_events.length,0);assert.equal(c.diagnosis_blocks[0].key,'ST:review:'+e.event_id);assert.match(c.diagnosis_blocks[0].text,/医生原文/);
 await x.ctx.setSTTUse(e,'strip',true);c=x.state.reportComposition;assert.equal(c.selected_events.length,1);assert.equal(c.selected_events[0].leads.length,12);assert.equal(c.selected_events[0].referenced_in_report,false);assert(c.included_pages.includes('event_strips'));
 await x.ctx.setSTTUse(e,'table',false);c=x.state.reportComposition;assert.equal(c.stt_report_use[0].text,true);assert.equal(c.stt_report_use[0].strip,true);assert.equal(c.selected_events.length,1);
 await x.ctx.setSTTUse(e,'strip',false);c=x.state.reportComposition;assert.equal(c.selected_events.length,0);assert.equal(c.stt_report_use[0].text,true);assert.equal(c.diagnosis_blocks.length,1);
 assert(x.calls.locates.every(id=>id===e.event_id),'Adoption may refresh the current editor but must not advance to another row');assert.equal(x.ctx.active.event_id,e.event_id);
 const normal=x.events[4];await x.ctx.setSTTUse(normal,'text',true);assert(x.state.reportComposition.stt_report_use.find(u=>u.event_id===normal.event_id).text);await assert.rejects(x.ctx.setSTTUse(normal,'table',true),/不支持|尚未/);
}
async function staleWithdrawal(){
 const x=setup(),e=x.events[0];x.ctx.active=e;x.state.reportComposition.stt_report_use=[{event_id:e.event_id,basis_version:'old-basis',table:true,text:true,strip:false}];
 await x.ctx.setSTTUse(e,'table',false);
 const use=x.state.reportComposition.stt_report_use[0];assert.equal(use.text,true);assert.equal(use.table,false);assert.equal(use.basis_version,'old-basis','Withdrawing one stale purpose must not silently rebind the remaining purpose');
 await assert.rejects(x.ctx.setSTTUse(e,'strip',true),/旧复核/);
}
async function removeUndoPreservesLaterChoices(){
 const x=setup(),e=x.events[0],other=x.events[1];x.ctx.active=e;
 await x.ctx.setSTTUse(e,'table',true);await x.ctx.setSTTUse(e,'strip',true);x.ctx.removeReportSelection(0);await x.settle();assert.equal(x.state.reportComposition.stt_report_use[0].strip,false);
 await x.ctx.setSTTUse(e,'text',true);await x.ctx.setSTTUse(other,'text',true);x.ctx.renderStripUndo();const undo=x.node('#reportV2Notice').afterNode.children.find(n=>n.tagName==='BUTTON');assert(undo);undo.onclick();await x.settle();
 assert.equal(x.state.reportComposition.selected_events.length,1);const uses=x.state.reportComposition.stt_report_use;assert.equal(uses.find(u=>u.event_id===e.event_id).strip,true);assert.equal(uses.find(u=>u.event_id===e.event_id).text,true,'Undo must preserve later text choice');assert.equal(uses.find(u=>u.event_id===other.event_id).text,true,'Undo must preserve another record choice');
 x.ctx.removeReportSelection(0);await x.settle();x.ctx.selectedLookup.set(e.event_id,{...e,basis_version:'new-record'});x.ctx.renderStripUndo();x.node('#reportV2Notice').afterNode.children.find(n=>n.tagName==='BUTTON').onclick();assert.equal(x.state.reportComposition.selected_events.length,0,'Old strip cannot be restored after its record changes');assert.match(x.calls.toast[0],/依据已变化/);
}
async function printAndPagesCallbacks(){
 const x=setup(),e=x.events[0];x.ctx.active=e;await x.ctx.setSTTUse(e,'text',true);await x.ctx.setSTTUse(e,'strip',true);
 vm.runInContext(between('  function gainHtml(){','  function changePaperSettings('),x.ctx);
 x.ctx.category='strips';vm.runInContext(between('  async function renderReportBody(){','  function mountSavedSTNote('),x.ctx);
 await x.ctx.renderReportBody();let options=x.calls.compose;assert(options);options.onStripPrint(0,false);await x.settle();assert.equal(x.state.reportComposition.selected_events[0].print_enabled,false);assert.equal(x.state.reportComposition.stt_report_use[0].strip,false);assert.equal(x.state.reportComposition.stt_report_use[0].text,true);
 options=x.calls.compose;options.onStripPrint(0,true);await x.settle();assert.equal(x.state.reportComposition.selected_events[0].print_enabled,true);assert.equal(x.state.reportComposition.stt_report_use[0].strip,true);
 const uses=JSON.stringify(x.state.reportComposition.stt_report_use);x.calls.compose.onPages(['summary','st_trend','t_trend']);assert.equal(JSON.stringify(x.state.reportComposition.stt_report_use),uses,'Page choices do not alter event adoption');assert.deepEqual(plain(x.state.reportComposition.included_pages),['summary','st_trend','t_trend']);
}
async function exactSavedReceiptFocus(){
 const x=setup(),target=x.events[5];x.state.reportComposition=x.ctx.composition();const before=JSON.stringify(x.state.reportComposition);
 Object.assign(x.ctx,{AbortController,reportToken:0,waveToken:0,reportReturn:null,reportSequence:()=> 'rr',syncWaveEvidence(){},projectRRSelections(){},rememberReportView(){},ECGReportConsistency:{receive:(state,remote)=>state.report=remote},sameEvidence:(a,b)=>a.analysis_basis===b.analysis_basis&&a.analysis_revision===b.analysis_revision});
 const dto=items=>({items,total:items.length,offset:0,analysis_basis:'math-source',analysis_revision:3,data_version:'math-events'});
 x.ctx.endpoint=async(kind,params)=>{x.calls.requests.push({kind,params});if(kind==='report')return {version:1,review_revision:3,current_analysis_basis:{digest:'math-source'},composition:copy(x.state.reportComposition)};return dto(params.ids?[target]:[x.events[0],target]);};
 vm.runInContext(between('  async function refreshReport(navigation={}){','  // A saved NN strip'),x.ctx);
 const method=between('async showSTReport(receipt=null){','},showAFCandidates');vm.runInContext('async function '+method.slice(6)+'}',x.ctx);
 x.state.currentPage='stt';await x.ctx.showSTReport({event_id:target.event_id,record_version:4});assert.equal(x.ctx.sttReportFocus.eventId,target.event_id);assert.equal(x.state.currentPage,'report');await x.ctx.refreshReport();
 assert.equal(x.ctx.active.event_id,target.event_id);assert.equal(x.ctx.sttGroup,'ST_NOTE');const list=x.calls.requests.find(r=>r.kind==='report-events'&&r.params.locate_event);assert.equal(list.params.locate_event,target.event_id);assert.equal(list.params.locate_basis,target.basis_version);assert.equal(x.ctx.sttReportFocus,null);assert.equal(x.calls.dirty,0);assert.equal(JSON.stringify(x.state.reportComposition),before);
 // A deleted requested receipt must fail explicitly, without falling back to
 // the first other event or writing an adoption or diagnosis.
 x.ctx.endpoint=async(kind,params)=>kind==='report'?{version:1,review_revision:3,composition:copy(x.state.reportComposition)}:dto(params.ids?[]:[x.events[0]]);
 await assert.rejects(x.ctx.showSTReport({event_id:'annotation:deleted'}),/未找到刚保存/);assert.equal(x.calls.dirty,0);assert.equal(JSON.stringify(x.state.reportComposition),before);
}
function actualUseGate(){
 const pending=event('indeterminate',90,{stt_review_state:'unreviewed',stt_report_eligibility:{table:false,text:false,strip:false}}),review={steps:{edit:{status:'done'},stt:{status:'pending'}}},valid=event('no_change',91),index={rows:[],events:[pending,valid],duration_s:1000};
 const c={page_selection_version:1,included_pages:['summary'],selected_events:[],stt_report_use:[],diagnosis_blocks:[]};
 assert.doesNotThrow(()=>A.validateReport(index,c,review,true),'Unadopted ST records and global unfinished ST step must not gate report');
 c.stt_report_use=[{event_id:valid.event_id,basis_version:valid.basis_version,table:false,text:true,strip:false}];assert.doesNotThrow(()=>A.validateReport(index,c,review,true));
 c.stt_report_use[0].basis_version='old';assert.throws(()=>A.validateReport(index,c,review,true),/ST-T.*依据/);
 c.stt_report_use=[{event_id:pending.event_id,basis_version:pending.basis_version,table:false,text:false,strip:true}];assert.doesNotThrow(()=>A.validateReport(index,c,review,true),'Excluded strip page must not create a gate');
 c.included_pages.push('event_strips');assert.throws(()=>A.validateReport(index,c,review,true),/ST-T.*依据/);
 c.stt_report_use=[{event_id:valid.event_id,basis_version:valid.basis_version,table:false,text:false,strip:true}];assert.throws(()=>A.validateReport(index,c,review,true),/代表图条尚未选择/);
}
(async()=>{const checks=[];await readOnlyRows();checks.push('seven-results-and-view-only-row-handlers');await independentAdoption();checks.push('independent-three-purpose-adoption-and-no-auto-advance');await staleWithdrawal();checks.push('withdrawal-keeps-other-stale-purpose-bound');await removeUndoPreservesLaterChoices();checks.push('strip-remove-undo-preserves-later-purpose-choices');await printAndPagesCallbacks();checks.push('actual-print-and-page-callbacks-preserve-independent-flags');await exactSavedReceiptFocus();checks.push('exact-saved-record-focus-and-missing-receipt-no-fallback');actualUseGate();checks.push('only-actually-used-ST-records-gate-approval');console.log(JSON.stringify({passed:checks.length,math_only:true,actual_handlers:true,checks}));})().catch(error=>{console.error(error.stack);process.exitCode=1;});
