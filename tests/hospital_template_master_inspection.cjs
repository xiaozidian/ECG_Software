"use strict";
// Execute the production host handler with a deferred RAF and synthetic case identity.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'..'),source=fs.readFileSync(path.join(root,'static/js/desktop-workspace.js'),'utf8');
const actual=source.match(/  function bindMasterInspection\([\s\S]*?\n  }/);assert.ok(actual,'shipped binder exists');
function fixture(){
  const listeners={},frames=[],opened=[];let retries=0,stopped=0,prevented=0;
  const svg={isConnected:true},card={isConnected:true,dataset:{editClass:'source-N',masterKind:'class',populationCount:'123456'},querySelector:s=>s==='svg'?card.svg:s==='header strong'?{textContent:'N · 分类预览'}:null};card.svg=svg;
  const host={dataset:{failed:'false'},contains:node=>node===card,addEventListener:(kind,fn)=>listeners[kind]=fn};
  const box={deckKey:'synthetic-deck',deckToken:1,evidence:{id:'synthetic-case',caseToken:1,analysis_basis:'synthetic-basis',analysis_revision:4,data_version:2},
    state:{caseId:'synthetic-case',caseRequestId:1,caseData:{analysis_revision:3},editLead:'II',editSelectedClass:'source-V',currentPage:'edit',editMode:'library'},
    requestAnimationFrame:fn=>frames.push(fn),fmtNumber:String,ecgChartInspection:{open:(...args)=>opened.push(args)},renderDeck:()=>retries++};
  vm.createContext(box);vm.runInContext(actual[0]+'\nglobalThis.bind=bindMasterInspection;',box);box.bind(host);
  const event=(extra={})=>({target:{closest:s=>s==='.workspace-master-card'?card:null},detail:1,ctrlKey:false,metaKey:false,preventDefault(){prevented++},stopPropagation(){stopped++},...extra});
  return {box,card,svg,host,listeners,frames,opened,event,flush(){for(const fn of frames.splice(0))fn()},counts:()=>({retries,stopped,prevented})};
}
const checks=[];
{
 const h=fixture();h.listeners.click(h.event());assert.equal(h.opened.length,0);assert.equal(h.frames.length,1);
 h.box.state.editSelectedClass='source-N';h.flush();assert.equal(h.opened.length,1);assert.equal(h.opened[0][0],h.svg);assert.equal(h.opened[0][1],h.card);
 assert.match(h.opened[0][2],/完整集合 123456 搏.*分类预览，非形态模板/);assert.deepEqual(h.counts(),{retries:0,stopped:0,prevented:0});checks.push('ordinary-click-opens-current-vector-after-bubbling-selection-with-full-class-preview-count');
}
{
 const h=fixture();h.listeners.click(h.event({ctrlKey:true}));h.listeners.click(h.event({metaKey:true}));assert.equal(h.frames.length,0);assert.equal(h.opened.length,0);assert.deepEqual(h.counts(),{retries:0,stopped:0,prevented:0});checks.push('control-and-meta-click-retain-selection-bubbling-without-viewer');
}
{
 const h=fixture();h.listeners.keydown(h.event({key:' '}));h.listeners.click(h.event({detail:0}));h.box.state.editSelectedClass='source-N';h.flush();assert.equal(h.opened.length,0);
 h.listeners.pointerdown(h.event());h.listeners.click(h.event());h.flush();assert.equal(h.opened.length,1);checks.push('space-selection-does-not-open-and-next-ordinary-pointer-click-still-opens');
}
{
 const h=fixture();h.host.dataset.failed='true';h.listeners.click(h.event());assert.equal(h.opened.length,0);assert.equal(h.frames.length,0);assert.deepEqual(h.counts(),{retries:1,stopped:1,prevented:1});checks.push('failed-wave-click-only-retries-and-never-selects-or-opens');
}
{
 const mutations=[h=>h.box.state.caseId='other-synthetic-case',h=>h.box.state.caseRequestId++,h=>h.box.state.caseData.analysis_revision++,h=>h.box.evidence.analysis_basis='other-basis',h=>h.box.evidence.analysis_revision++,h=>h.box.evidence.data_version++,h=>h.box.state.editSelectedClass='source-V',h=>h.box.state.editLead='V1',h=>h.box.state.editMode='cluster',h=>h.box.state.currentPage='report',h=>h.box.deckKey='other-deck',h=>h.box.deckToken++,h=>h.card.svg={isConnected:true},h=>h.card.isConnected=false,h=>h.svg.isConnected=false];
 for(const mutate of mutations){const h=fixture();h.listeners.click(h.event());h.box.state.editSelectedClass='source-N';mutate(h);h.flush();assert.equal(h.opened.length,0,'stale or replacement source opened');}
 checks.push('fifteen-case-basis-revision-class-mode-lead-generation-and-source-replacement-guards-reject-late-RAF');
}
{
 const h=fixture();h.listeners.click(h.event());h.listeners.click(h.event({ctrlKey:true}));h.box.state.editSelectedClass='source-N';h.flush();assert.equal(h.opened.length,0);checks.push('newer-selection-only-gesture-cancels-an-earlier-pending-view');
}
console.log(JSON.stringify({passed:true,actual_check_count:checks.length,checks}));
