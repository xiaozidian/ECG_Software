// Exercise the shipped workbench with synthetic populations and delayed reads.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
async function settle(){for(let i=0;i<8;i++)await tick();}
function setup(){
  const nodes=new Map(),listeners={},calls=[],errors=[];
  const state={caseId:'synthetic-A',caseRequestId:1,currentPage:'edit',editMode:'cluster',caseData:{analysis_revision:3},editSelectedClass:'source-N',editTemplates:[]};
  let mode='ready',population=[200,400,600],hold=null;
  function node(){
    const ownListeners={},children=new Map(),attrs={};
    const ctx=new Proxy({createImageData:(w,h)=>({data:new Uint8ClampedArray(w*h*4)})},{get:(o,k)=>o[k]||(()=>{})});
    return {hidden:true,disabled:false,value:'',textContent:'',dataset:{},attrs,children,listeners:ownListeners,
      getClientRects:()=>[1],getBoundingClientRect:()=>({left:0,top:0,width:300,height:130}),getContext:()=>ctx,
      setAttribute:(k,v)=>attrs[k]=v,querySelector(s){if(!children.has(s))children.set(s,node());return children.get(s)},querySelectorAll:()=>[],
      contains(target){return target===this||[...children.values()].some(child=>child.contains(target))},
      addEventListener:(name,fn)=>ownListeners[name]=fn,focus(){},closest:()=>null,
      before(el){nodes.set('#'+el.id,el)},after(el){nodes.set('#'+el.id,el)}};
  }
  const qs=s=>{if(!nodes.has(s))nodes.set(s,node());return nodes.get(s)};
  nodes.set('#morphScope',null);nodes.set('#morphImpact',null);nodes.set('dialog[open]',null);
  qs('#occTemplate').value='all';
  for(const [id,value] of Object.entries({editRangeStart:'10',editRangeEnd:'70',editRangeTop:'10',editRangeBottom:'70',morphRangeLead:'top'}))qs('#'+id).value=value;
  qs('#editDensityPrimary').dataset.morphSource='top';qs('#editDensitySelection').dataset.morphSource='bottom';
  const api=async(url,opts)=>{
    const payload=JSON.parse(opts.body);calls.push({url,payload});
    if(url.includes('/beat-templates'))return {id:'synthetic-template',name:payload.name,rhythm_family:payload.rhythm_family};
    const localMode=mode,localPopulation=population.slice(),localHold=hold;if(localHold)await localHold;
    if(localMode==='error')throw Error('synthetic read failure');
    const query=new URL(url,'http://synthetic.invalid').searchParams;
    const samples=(payload.samples||localPopulation).filter(s=>!(payload.exclude_samples||[]).includes(s));
    const included=localMode==='edges'?0:samples.length;
    return {revision:localMode==='stale'?payload.revision+1:payload.revision,lead:query.get('lead'),width:1,height:1,bins:[included],amplitude_limit:100,
      population_samples:samples,total:samples.length,included,skipped_edges:samples.length-included,sample_indices:query.has('gate')?samples.slice(0,2):samples};
  };
  const context=vm.createContext({state,api,ECGMorphologyGroups:require('../static/js/morphology-groups.js'),URLSearchParams,
    escapeHtml:String,fmtNumber:String,editClassLabel:source=>source==='source-N'?'N · 正常心搏':source,UI_FONT:'sans-serif',
    document:{querySelector:qs,querySelectorAll:()=>[],createElement:node,addEventListener:(name,fn)=>listeners[name]=fn,
      removeEventListener:(name,fn)=>{if(listeners[name]===fn)delete listeners[name]},activeElement:node()},
    requestAnimationFrame:()=>1,devicePixelRatio:1,ResizeObserver:class{observe(){}},renderEditDensity(){},
    renderEditClasses(){},handleError:e=>errors.push(e.message)});
  vm.runInContext(fs.readFileSync('static/js/morphology-workbench.js','utf8')+'\nglobalThis.workbench=morphologyWorkbench;',context);
  listeners.DOMContentLoaded();
  const clickRange=()=>qs('#applyEditRange').listeners.click({preventDefault(){},stopImmediatePropagation(){}});
  const key=(value,target={closest:()=>null})=>listeners.keydown({key:value,target,preventDefault(){},stopImmediatePropagation(){}});
  return {state,qs,calls,errors,clickRange,key,workbench:context.workbench,refresh:force=>context.workbench.refresh(force),setMode:value=>{mode=value},setPopulation:value=>{population=value},setHold:value=>{hold=value}};
}
async function run(){
  const h=setup();await settle();
  assert.match(h.qs('#morphScope').textContent,/整组 3 搏.*r3.*II \/ V1/);
  assert.equal(h.qs('#morphScope').dataset.state,'ready');
  assert.match(h.qs('#morphActiveGroup').textContent,/0 搏.*空组/);
  h.clickRange();await settle();assert.match(h.qs('#morphImpact').textContent,/框选的 2 搏.*r3.*心搏分类不变/);
  h.key('7',{closest:s=>s.includes('input')?{}:null});await settle();
  assert.match(h.qs('#editMorphologyCount').textContent,/剩余 3/,'input focus grouped beats');
  h.key('7');await settle();
  assert.match(h.qs('#morphScope').textContent,/未保存分组 7 组（2 搏）/);
  assert.match(h.qs('#editMorphologyCount').textContent,/剩余 1 \/ 3/);
  h.qs('#morphGroupTemplate').onclick();h.qs('#morphTemplateName').value='synthetic morphology';
  assert.match(h.qs('#morphTemplateTitle').textContent,/7 组 · 2 搏 · II · r3/);
  h.setMode('error');await h.refresh(true);
  assert.equal(h.qs('#morphScope').dataset.state,'error');
  assert.equal(h.qs('#morphTemplateName').value,'synthetic morphology');
  assert.equal(h.qs('#morphGroupRestore').disabled,true);
  assert.match(h.qs('#morphSlot7').attrs['aria-description'],/读取失败/);
  const writes=h.calls.filter(c=>c.url.includes('beat-templates')).length;
  await h.qs('#morphTemplateForm').onsubmit({preventDefault(){}});
  assert.equal(h.calls.filter(c=>c.url.includes('beat-templates')).length,writes,'unavailable density saved a template');
  h.setMode('ready');h.qs('#morphRetry').onclick();await settle();
  await h.qs('#morphTemplateForm').onsubmit({preventDefault(){}});
  assert.match(h.qs('#morphScope').textContent,/未保存分组 无/);
  const saved=h.calls.find(c=>c.url.includes('beat-templates'));
  assert.deepEqual(saved.payload.sample_indices,[200,400]);
  assert.equal(saved.payload.revision,3);assert.equal(saved.payload.lead,'II');
  assert.match(saved.payload.note,/形态分组，未修改心搏分类/);
  h.qs('#morphUndo').onclick();await settle();assert.match(h.qs('#editMorphologyCount').textContent,/剩余 3 \/ 3/);
  assert.equal(h.calls.filter(c=>c.url.includes('beat-templates')).length,1,'undo deleted a saved template');
  assert.ok(h.calls.every(c=>!c.url.includes('beat-editor')),'group operation wrote beat classifications');
  assert.deepEqual(h.errors,[]);

  for(const [mode,population,phase,pattern] of [['ready',[],'empty',/来源集合没有心搏/],['edges',[200,400],'insufficient',/缺少完整边界/],['stale',[200],'stale',/依据失效/]]){
    const s=setup();await settle();s.setMode(mode);s.setPopulation(population);s.state.caseData.analysis_revision++;s.qs('#morphRetry').onclick();await settle();
    assert.equal(s.qs('#morphScope').dataset.state,phase);assert.match(s.qs('#morphStatus').textContent,pattern);
    if(mode==='stale'){assert.equal(s.qs('#applyEditRange').disabled,true);assert.match(s.qs('#editDensityPrimary').attrs['aria-description'],/依据失效/);}
  }
  const race=setup();await settle();let release;race.setHold(new Promise(resolve=>release=resolve));
  race.setMode('error');race.qs('#morphRetry').onclick();const old=race.refresh(true);assert.match(race.qs('#morphImpact').textContent,/正在读取/);
  race.state.caseRequestId++;race.setMode('ready');race.setHold(null);await race.refresh(true);release();await old;
  assert.equal(race.qs('#morphScope').dataset.state,'ready','old lifecycle read replaced current state');
  assert.doesNotMatch(race.qs('#morphStatus').textContent,/failure|失败/);
  const tabs=setup();await settle();tabs.clickRange();await settle();tabs.key('7');await settle();
  tabs.qs('#morphGroupTemplate').onclick();tabs.qs('#morphTemplateName').value='tab draft';
  const mark=tabs.workbench.captureView();tabs.state.editMode='library';tabs.state.editSelectedClass='source-V';await tabs.refresh();
  tabs.key('8');await settle();assert.match(tabs.qs('#morphScope').textContent,/未保存分组 无/,'hidden density shortcut changed a library group');
  tabs.state.editMode='cluster';tabs.state.editSelectedClass='source-N';await tabs.workbench.restoreView(mark);
  assert.match(tabs.qs('#morphScope').textContent,/7 组（2 搏）/);assert.equal(tabs.qs('#morphTemplateName').value,'tab draft');assert.equal(tabs.qs('#morphTemplateForm').hidden,false);
  tabs.state.caseData.analysis_revision++;await tabs.workbench.restoreView(mark);
  assert.equal(tabs.qs('#morphTemplateForm').hidden,true);assert.match(tabs.qs('#morphScope').textContent,/未保存分组 无/,'old revision resurrected a group');
  tabs.state.caseId='synthetic-B';tabs.state.caseRequestId++;tabs.workbench.resetView();await tabs.refresh();
  assert.equal(tabs.qs('#morphTemplateName').value,'');assert.equal(tabs.qs('#morphTemplateForm').hidden,true);
  console.log('morphology scope, grouping, save guards, empty/edge/error/stale states, tab drafts and lifecycle races passed');
}
run().catch(error=>{console.error(error);process.exitCode=1});
