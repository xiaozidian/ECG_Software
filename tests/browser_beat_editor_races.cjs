const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const scenario=process.argv[2],calls=[],errors=[],listeners={},nodes=new Map();
const gate=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve}};
const pending=gate(),tick=()=>new Promise(r=>setImmediate(r));
function node(){return {hidden:true,open:false,innerHTML:'',textContent:'',disabled:false,dataset:{},classList:{add(){}},setAttribute(){},removeAttribute(){},focus(){},matches:()=>false,showPopover(){},getBoundingClientRect:()=>({left:0,top:0,width:500,height:100}),closest:()=>null,querySelector(s){return $(s)},querySelectorAll:()=>[],addEventListener(){},showModal(){this.open=true},close(){this.open=false}}}
const $=s=>{if(!nodes.has(s))nodes.set(s,node());return nodes.get(s)};
let dialog,reloads=0,refreshes=0,editBookmark=null;
const state={caseId:'A',caseRequestId:1,currentPage:'edit',editSelectedSamples:new Set([200]),editStart:0,scatterStripCache:new Map()};
const info={revision:1,settings:{},can_undo:true,can_redo:false};
const preview={affected:2,before:{metrics:{valid_beats:5},hrv:{},markers:[]},after:{metrics:{valid_beats:5},hrv:{},markers:[]}};
const stages={read:'GET',preview:'POST',put:'PUT',invoke:'GET',menu:'GET',undo:'PUT'};
const stage=scenario.split('-')[0];let waited=false;
const api=async(url,opts={})=>{
  const method=opts.method||'GET',body=opts.body?JSON.parse(opts.body):null;calls.push({url,method,body});
  if(!waited&&method===(stages[stage]||'NONE')){waited=true;await pending.promise;}
  if(url.endsWith('/beats'))return {items:[{sample_index:200,time_s:1,class_code:'N'}],markers:[]};
  return method==='POST'?preview:{...info};
};
const ctx=vm.createContext({state,$,api,escapeHtml:String,ECGBeatEngine:require('../static/js/beat-engine.js'),
  document:{createElement(){dialog=node();return dialog},body:{appendChild(){}},querySelectorAll:()=>[],addEventListener:(name,fn)=>listeners[name]=fn,activeElement:{tagName:'BODY'}},
  clinicalWorkflow:{writable:()=>true,refresh:async()=>refreshes++},handleError:e=>errors.push(e.message),formatElapsedPrecise:String,
  clinicalUI:{occurrenceBookmark:()=>({id:'A',caseToken:1,sample:20000})},
  closeBeatRelabelMenu(){ctx.editor.invalidate();$('#beatRelabelMenu').hidden=true},refreshBeatOverrideViews(){},renderEditScatter(){},positionBeatRelabelMenu(){},
  loadCase:async()=>{reloads++;state.caseRequestId++;return true},loadEdit:async bookmark=>{editBookmark=bookmark},loadScatter:async()=>{},clearScatterSelection(){},toast(){},ALL_LEADS:['II'],
  FormData:class{},devicePixelRatio:1});
vm.runInContext(fs.readFileSync('static/js/beat-editor-ui.js','utf8')+'\nglobalThis.editor=beatEditor;',ctx);
// Bind without adding history bars; those canvases are irrelevant to this harness.
for(const s of ['#waveformCanvas','#editWaveformCanvas','#editLibraryWaveformCanvas'])nodes.set(s,null);
listeners.DOMContentLoaded();
const writes=()=>calls.filter(c=>c.method==='PUT');
async function run(){
  if(scenario.startsWith('confirm')){
    await ctx.editor.quickEdit('OTHER',[200,400]);assert.equal(dialog.open,true);
    const submit=$('form').onsubmit;
    if(scenario==='confirm-case'){state.caseId='B';state.caseRequestId++;}
    if(scenario==='confirm-lifecycle')state.caseRequestId++;
    if(scenario==='confirm-cancel')dialog.close();
    if(scenario==='confirm-selection')state.editSelectedSamples=new Set([600]);
    if(scenario==='confirm-focus')state.editSelectedSample=600;
    if(scenario==='confirm-replaced')await ctx.editor.quickEdit('OTHER',[600,800]);
    await submit({preventDefault(){},target:{}});
    if(scenario==='confirm-success'){assert.equal(writes().length,1);assert.equal(writes()[0].url,'/api/cases/A/beat-editor');}
    else assert.equal(writes().length,0,'stale/cancelled confirmation wrote a beat edit');
    return;
  }
  const card=node();ctx.editor.registerOccurrence(card,{sample_index:200,time_s:1,class_code:'N'},{code:'N',samples:async()=>[200,400]});
  const operation=()=>stage==='menu'?ctx.editor.occurrenceMenu(card):stage==='undo'?ctx.editor.invoke('undo'):stage==='invoke'?ctx.editor.invoke('relabel',{samples:[200],code:'V'}):ctx.editor.quickEdit('V',[200]);
  const task=operation().then(()=>null,e=>e);
  await tick();
  if(scenario.endsWith('-case')){state.caseId='B';state.caseRequestId++;}
  if(scenario.endsWith('-lifecycle'))state.caseRequestId++;
  if(scenario.endsWith('-page'))state.currentPage='report';
  if(scenario.endsWith('-selection'))state.editSelectedSamples=new Set([600]);
  if(scenario.endsWith('-focus'))state.editSelectedSample=600;
  if(scenario.endsWith('-cancel'))ctx.editor.invalidate();
  if(scenario.endsWith('-second'))await ctx.editor.quickEdit('S',[400]);
  pending.resolve();const result=await task;
  if(stage==='menu'){if(scenario.endsWith('-success'))assert.equal(result,null,result?.message);assert.equal(writes().length,0);assert.equal($('#beatRelabelMenu').hidden,!scenario.endsWith('-success'));return;}
  if(stage==='undo'){assert.equal(writes().length,1);assert.equal(writes()[0].body.operation,'undo');assert.equal(reloads,scenario.endsWith('-success')?1:0);return;}
  if(scenario.endsWith('-success')||scenario.endsWith('-second')){
    assert.equal(result,null,result?.message);assert.equal(writes().length,1);
    assert.deepEqual(writes()[0].body.selection.samples,[200]);assert.equal(writes()[0].body.class_code,'V');
    assert.equal(reloads,1);assert.equal(editBookmark.sample,20000);assert.equal(editBookmark.caseToken,2);return;
  }
  if(stage==='put'){assert.equal(writes().length,1);assert.equal(writes()[0].url,'/api/cases/A/beat-editor');assert.equal(reloads,0);assert.equal(refreshes,0);}
  else {assert.equal(writes().length,0,'operation wrote after its case/target was invalidated');assert.equal(dialog.open,false);}
  assert.ok(!calls.some(c=>c.url.includes('/cases/B/')),'old operation accessed the newly selected case');
}
run().catch(e=>{console.error(e);process.exitCode=1});
