'use strict';
// Synthetic app adapters: actual source helpers, no server or patient data.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const E=require('../static/js/rhythm-range-editor.js'),C=require('../static/js/analysis-consistency.js');
const source=fs.readFileSync('static/js/app.js','utf8');
const helper=source.slice(source.indexOf('const rhythmRangePointers ='),source.indexOf('function escapeHtml('));
const clone=x=>JSON.parse(JSON.stringify(x));
function fixture(){
  const notes=[],menus=[],old=[],loads=[],callbacks=[],elements=new Map();
  const state={caseId:'math-a',caseRequestId:7,workspaceEpoch:'math-workspace',currentPage:'review',editMode:'cluster',
    caseData:{case_id:'math-a',clinical_identity:{analysis_basis:'math-source',analysis_revision:19},analysis_revision:3,
      beat_editor_history:{revision:3},technical:{duration_seconds_raw:640,sample_rate_hz:200}},
    reportDirty:true,reportComposition:{diagnosis_blocks:[{text:'unsaved'}]},waveformExpanded:false};
  for(const id of ['waveformCanvas','editWaveformCanvas','editLibraryWaveformCanvas'])elements.set('#'+id,
    {id,parentElement:{after(){}},getBoundingClientRect:()=>({left:100,top:200,width:1200,height:320}),
      addEventListener(){},setAttribute(){}});
  const node=()=>({hidden:false,id:'',append(){},querySelector(){},addEventListener(){},setAttribute(){}});
  const context=vm.createContext({state,WeakMap,ECGAnalysisConsistency:C,ECGRhythmRangeEditor:E,
    $:id=>elements.get(id),document:{createElement:node,body:{append(){}}},
    editWaveGeometry:(w,h)=>({l:50,t:27,w:w-65,h:h-51}),
    toast:(...args)=>notes.push(args),closeBeatRelabelMenu:()=>{},
    openBeatRelabelMenu:(...args)=>old.push(args),beatEditor:{open:(...args)=>callbacks.push(args)},
    clinicalWorkflow:{writable:()=>true},handleError:()=>{},api:()=>{},
    loadCase:async(...args)=>{loads.push(args);return true;},loadEdit:async()=>loads.push('edit'),
    loadScatter:async()=>loads.push('scatter'),loadTrends:async()=>loads.push('trends'),
    loadStt:async()=>loads.push('stt'),loadEvents:async()=>loads.push('events'),loadReport:async()=>loads.push('report')});
  vm.runInContext(helper,context);
  const owner=()=>context.rhythmRangeScope();
  const wave=()=>({...state.caseData.clinical_identity,sample_rate_hz:200,start_s:10,duration_s:20,
    leads:{II:[0,1],V1:[0,1],V5:[0,1]}});
  state.waveform=wave();state.waveformOwner=context.captureRhythmWaveOwner(state.waveform,owner());
  state.editWaveform=wave();state.editWaveformOwner=context.captureRhythmWaveOwner(state.editWaveform,owner());
  context.ecgRhythmRangeEditor={isSaving:()=>false,snapshot:()=>({draft:null}),sync:()=>{},closeMenu(){},openContext:(...args)=>menus.push(args)};
  return {context,state,notes,menus,old,loads,callbacks,elements,owner,wave};
}
(async()=>{
  let count=0;
  {
    const f=fixture(),s=f.owner();assert.equal(s.analysis_revision,19);assert.equal(s.beat_revision,3);
    assert.equal(s.caseToken,7);assert.equal(s.case_id,'math-a');count++;
    delete f.state.caseData.beat_editor_history;assert.equal(f.owner().beat_revision,3);count++;
    f.state.caseData.analysis_revision=true;assert.equal(f.owner(),null);count++;
  }
  {
    const f=fixture(),s=f.owner(),w=f.wave();
    assert.deepEqual(clone(f.context.captureRhythmWaveOwner(w,s)),clone(s));
    for(const bad of [{analysis_revision:20},{analysis_basis:'wrong'},{case_id:'math-b'},
      {beat_revision:4},{sample_rate_hz:250},{start_s:639,duration_s:2}])
      assert.equal(f.context.captureRhythmWaveOwner({...w,...bad},s),null);
    count++;
    for(const [key,bad] of [['caseRequestId',8],['workspaceEpoch','changed'],['caseId','math-b']]){
      const before=f.state[key];f.state[key]=bad;assert.equal(f.context.captureRhythmWaveOwner(w,s),null);f.state[key]=before;
    }count++;
    f.state.caseData.clinical_identity.analysis_revision=20;
    assert.equal(f.context.captureRhythmWaveOwner(w,s),null);count++;
  }
  {
    const f=fixture(),main=f.elements.get('#waveformCanvas'),edit=f.elements.get('#editWaveformCanvas');
    assert.deepEqual(clone(f.context.rhythmRangeSurface(main).plot),{left:0,top:0,width:1200,height:320});count++;
    f.state.currentPage='edit';assert.deepEqual(clone(f.context.rhythmRangeSurface(edit).plot),{left:50,top:27,width:1135,height:269});count++;
    assert.equal(f.context.rhythmRangeSurface(f.elements.get('#editLibraryWaveformCanvas')),null);
    f.state.editMode='library';assert.equal(f.context.rhythmRangeSurface(edit),null);
    assert.ok(f.context.rhythmRangeSurface(f.elements.get('#editLibraryWaveformCanvas')));count++;
    f.state.waveformExpanded=true;assert.equal(f.context.rhythmRangeSurface(main),null);
    assert.equal(f.context.rhythmRangeSurface(edit),null);count++;
  }
  {
    const f=fixture(),canvas=f.elements.get('#waveformCanvas'),event={type:'contextmenu',clientX:700,clientY:260,preventDefault(){}};
    f.context.openContinuousWaveMenu(event,canvas,f.state.waveform,'review');
    assert.equal(f.menus.length,0);assert.equal(f.old.length,1);count++;
    f.state.waveformOwner.caseToken=6;f.context.openContinuousWaveMenu(event,canvas,f.state.waveform,'review');
    assert.equal(f.menus.length,0);assert.equal(f.old.length,2);count++;
    f.state.waveformExpanded=true;f.context.openContinuousWaveMenu(event,canvas,f.state.waveform,'review');
    assert.equal(f.old.length,3);count++;
    f.context.ecgRhythmRangeEditor.isSaving=()=>true;
    f.context.openContinuousWaveMenu(event,canvas,f.state.waveform,'review');assert.equal(f.old.length,3);count++;
  }
  {
    const f=fixture(),canvas=f.elements.get('#waveformCanvas');
    f.context.rememberRhythmRangePointer({clientX:700},canvas);
    assert.equal(f.context.rhythmRangeSurface(canvas).cursor_sample,4000);
    f.state.waveform=f.wave();assert.equal(f.context.rhythmRangeSurface(canvas).cursor_sample,undefined);count++;
  }
  {
    const f=fixture(),owner=clone(f.owner()),composition=f.state.reportComposition;
    await f.context.rhythmRangeSaved({scope:owner,reconciled:false});
    assert.deepEqual(f.loads[0],['math-a',7]);assert.equal(f.state.caseRequestId,7);
    assert.equal(f.state.reportDirty,true);assert.strictEqual(f.state.reportComposition,composition);count++;
    f.loads.length=0;f.state.caseRequestId=8;await f.context.rhythmRangeSaved({scope:owner,reconciled:true});
    assert.equal(f.loads.length,0);count++;
  }
  {
    const f=fixture();let adapter=null;
    f.context.ECGRhythmRangeEditor={...E,mount:options=>{adapter=options;return f.context.ecgRhythmRangeEditor;}};
    f.context.ecgRhythmRangeEditor=null;f.context.initRhythmRangeEditor();
    // The fixture's mount return is irrelevant; inspect the direct QRS hook.
    assert.equal(typeof adapter.onBeatEditor,'function');
    adapter.onBeatEditor({type:'contextmenu'},f.elements.get('#waveformCanvas'));
    assert.equal(f.callbacks.length,1);assert.equal(f.old.length,0);count++;
    f.state.waveformOwner.analysis_revision=18;
    assert.throws(()=>adapter.onBeatEditor({type:'contextmenu'},f.elements.get('#waveformCanvas')),/依据已变化/);
    assert.equal(f.callbacks.length,1);count++;
  }
  {
    const f=fixture();f.context.ecgRhythmRangeEditor.isSaving=()=>true;
    const select=source.slice(source.indexOf('async function selectCase('),source.indexOf('// Identity display has its own lifetime:'));
    const go=source.slice(source.indexOf('function goPage('),source.indexOf('function waveformRequestLeads('));
    vm.runInContext(select+go,f.context);
    await f.context.selectCase('math-b');f.context.goPage('edit');
    assert.equal(f.state.caseRequestId,7);assert.equal(f.state.caseId,'math-a');assert.equal(f.state.currentPage,'review');count++;
  }
  assert.match(source,/openContinuousWaveMenu\(event,\$\("#waveformCanvas"\),state.waveform,"review",true\)/);
  assert.match(source,/openContinuousWaveMenu\(event,document.activeElement,state.editWaveform,"edit",true\)/);
  assert.match(source,/if\(typeof beatEditor!=="undefined"\)return beatEditor\.open\(event,canvas,waveform,surface,keyboard\)/);count++;
  console.log(JSON.stringify({passed:count,scope:'synthetic app adapters / original QRS strip entry unchanged'}));
})().catch(error=>{console.error(error);process.exitCode=1});
