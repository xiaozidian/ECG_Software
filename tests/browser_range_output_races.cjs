const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('static/js/clinical-ui.js','utf8');
const gate=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve}};
const tick=()=>new Promise(r=>setImmediate(r));
function production(ctx,name){const start=source.indexOf('  async function '+name+'('),end=source.indexOf('\n  }',start)+4;assert(start>=0);vm.runInContext(source.slice(start,end),ctx);}
async function download(phase,change){
 const remote=gate(),response=gate(),blob=gate();let pending=false,advanced=false,clicked=0,requested=0,objects=0;
 const state={caseId:'A',caseRequestId:1,report:{version:2,review_revision:3},reportDirty:false,reportSaving:false,reportStale:false};
 const ctx=vm.createContext({state,URLSearchParams,setTimeout:()=>{},
   ECGReportRange:{assertApplied(){if(pending)throw Error('pending-range')}},
   ECGAdvancedAnalysis:{assertApplied(){if(advanced)throw Error('pending-advanced')}},
   ECGReportConsistency:{sameBase:(a,b)=>a.version===b.version&&a.review_revision===b.review_revision},
   endpoint:()=>remote.promise,fetch:()=>{requested++;return response.promise},renderReportShell(){},
   document:{createElement:()=>({click:()=>clicked++})},URL:{createObjectURL:()=>{objects++;return 'blob:qa'},revokeObjectURL(){}}});
 production(ctx,'downloadReport');const task=ctx.downloadReport();
 if(phase!=='remote'){remote.resolve({...state.report});await tick();}
 if(phase==='blob'){response.resolve({ok:true,blob:()=>blob.promise});await tick();}
 if(change==='range')pending=true;
 if(change==='advanced')advanced=true;
 if(change==='dirty')state.reportDirty=true;
 if(change==='saving')state.reportSaving=true;
 if(change==='reopen')state.caseRequestId++;
 if(change==='case')state.caseId='B';
 if(change==='version')state.report.version++;
 if(change==='revision')state.report.review_revision++;
 remote.resolve({version:2,review_revision:3});response.resolve({ok:true,blob:()=>blob.promise});blob.resolve('PDF');
 if(change==='none'){await task;assert.equal(clicked,1);assert.equal(objects,1);}
 else {await assert.rejects(task,/pending-range|pending-advanced|变化/);assert.equal(clicked,0);assert.equal(objects,0);if(phase==='remote')assert.equal(requested,0);}
}
async function preview(advanced=false){
 const data=gate(),body={textContent:''};let pending=false,rendered=0;
 const dialog={open:true,querySelector:s=>s==='button'?{}:body,showModal(){},close(){}};
 const ctx=vm.createContext({state:{caseId:'A',caseRequestId:1},reportRenderToken:0,
   ECGReportRange:{assertApplied(){if(pending&&!advanced)throw Error('pending-range')}},
   ECGAdvancedAnalysis:{assertApplied(){if(pending&&advanced)throw Error('pending-advanced')}},ECGReportSections:{validate(){}},
   ECGReportConsistency:{content:()=>''},composition:()=>({}),qs:s=>s==='#rwPaperPreview'?dialog:{value:''},
   readPaperEvidence:()=>data.promise,ECGReportPaper:{render:()=>{rendered++;return ''},number(){}}});
 production(ctx,'previewPaper');const task=ctx.previewPaper();pending=true;data.resolve({});
 await assert.rejects(task,/pending-range|pending-advanced/);assert.equal(rendered,0);assert.match(body.textContent,/预览失败.*pending-/);
}
async function printDuringFonts(){
 const fonts=gate();let pending=false,printed=0;
 const doc={open(){},write(){},close(){},querySelector:()=>({sheet:true}),fonts:{ready:fonts.promise},body:{}};
 const frame={contentDocument:doc,contentWindow:{focus(){},print(){printed++}}};
 const ctx=vm.createContext({URL,location:{href:'http://localhost/'},esc:x=>x,qs:()=>null,
   document:{createElement:()=>frame,body:{appendChild(){}}},ECGReportPaper:{number(){}}});
 production(ctx,'printHtml');const task=ctx.printHtml('synthetic','qa',()=>{if(pending)throw Error('pending-range')});
 await tick();pending=true;fonts.resolve();await assert.rejects(task,/pending-range/);assert.equal(printed,0);
}
async function printDuringRead(){
 const data=gate();let pending=false,printed=0;
 const state={caseId:'A',caseRequestId:1,report:{version:2,review_revision:3}};
 const ctx=vm.createContext({state,ECGReportRange:{assertApplied(){if(pending)throw Error('pending-range')}},
   ECGReportSections:{validate(){}},composition:()=>({}),readPaperEvidence:()=>data.promise,endpoint:async()=>state.report,
   ECGReportConsistency:{sameBase:()=>true},ECGReportPaper:{render:()=>''},paperModel:()=>({}),printHtml:()=>printed++});
 production(ctx,'print');const task=ctx.print();pending=true;data.resolve({});await assert.rejects(task,/pending-range/);assert.equal(printed,0);
}
async function reloadDuringRead(advanced=false){
 const data=gate();let pending=false,refreshed=0;
 const state={caseId:'A',caseRequestId:1,report:{version:2},reportDirty:false};
 const ctx=vm.createContext({state,ECGReportRange:{assertApplied(){if(pending&&!advanced)throw Error('pending-range')}},
   ECGAdvancedAnalysis:{assertApplied(){if(pending&&advanced)throw Error('pending-advanced')}},
   ECGReportConsistency:{content:()=>''},qs:()=>({value:''}),composition:()=>({}),endpoint:()=>data.promise,refreshReport:()=>refreshed++});
 production(ctx,'reloadReport');const task=ctx.reloadReport();pending=true;data.resolve({version:3});
 await assert.rejects(task,/pending-range|pending-advanced/);assert.equal(state.report.version,2);assert.equal(refreshed,0);
}
(async()=>{
 for(const phase of ['remote','response','blob'])for(const change of ['range','advanced','dirty','saving','case','reopen','version','revision','none'])await download(phase,change);
 await preview();await preview(true);await printDuringFonts();await printDuringRead();await reloadDuringRead();await reloadDuringRead(true);
 console.log('Output races: 27 PDF scenarios; preview, print evidence/fonts and reload preserve newer range and measurement edits');
})().catch(e=>{console.error(e);process.exitCode=1});
