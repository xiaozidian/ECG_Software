const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
async function run(scenario){
  let resolve;const pending=new Promise(r=>{resolve=r});
  const editor={value:'local'},state={caseId:'A',caseRequestId:1,report:{version:1,review_revision:1},reportDirty:true,reportStale:true,reportSaving:false,
    reportComposition:{selected_events:[{event_id:'selected'}]}};
  let renders=0,refreshes=0;
  const ctx=vm.createContext({state,qs:()=>editor,endpoint:()=>pending,composition:()=>state.reportComposition,
    copy:x=>JSON.parse(JSON.stringify(x)),reportVersion:1,renderReportShell:()=>{renders++},refreshReport:async()=>{refreshes++}});
  vm.runInContext(fs.readFileSync('static/js/report-consistency.js','utf8'),ctx);
  vm.runInContext(fs.readFileSync('static/js/report-range-editor.js','utf8'),ctx);
  const source=fs.readFileSync('static/js/clinical-ui.js','utf8');
  vm.runInContext(source.slice(source.indexOf('  async function reloadReport('),source.indexOf('  async function renderReportBody(')),ctx);
  const task=ctx.reloadReport(true);
  if(scenario==='typed')editor.value='new typing';
  if(scenario==='selection')state.reportComposition.selected_events.push({event_id:'new'});
  if(scenario==='saving')state.reportSaving=true;
  if(scenario==='new-base')state.report={version:3,review_revision:3};
  if(scenario==='case-switch')state.caseId='B';
  if(scenario==='case-reopen')state.caseRequestId++;
  const before=JSON.stringify(state.reportComposition),base=state.report;
  resolve({version:2,review_revision:2,conclusion:'remote',composition:{selected_events:[]}});
  if(['typed','selection','saving','new-base'].includes(scenario)){
    await assert.rejects(task,/本窗口有新修改/);assert.equal(state.report,base);
    assert.equal(JSON.stringify(state.reportComposition),before);assert.equal(state.reportDirty,true);assert.equal(renders,1);assert.equal(refreshes,0);
  }else if(scenario==='case-switch'||scenario==='case-reopen'){
    await task;assert.equal(state.report,base);assert.equal(state.reportDirty,true);assert.equal(refreshes,0);
  }else{
    await task;assert.equal(state.report.version,2);assert.equal(state.reportDirty,false);assert.equal(state.reportStale,false);assert.equal(refreshes,1);
  }
}
run(process.argv[2]).catch(error=>{console.error(error);process.exitCode=1});
