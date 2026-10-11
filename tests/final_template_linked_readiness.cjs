'use strict';
// Execute the production lifecycle functions with deferred, synthetic density reads.
// No browser, service, patient file, or database is involved.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),source=fs.readFileSync(path.join(root,'static/js/morphology-workbench.js'),'utf8');
const G=require(path.join(root,'static/js/morphology-groups.js'));
const Linked=require(path.join(root,'static/js/linked-selection.js'));
function actual(name){const match=source.match(new RegExp('  (?:async )?function '+name+'\\([^]*?\\n  }'));assert(match,'production function '+name+' exists');return match[0];}
function declaration(name){const match=source.match(new RegExp('^  const '+name+'=.*$','m'));assert(match);return match[0];}
const functions=['context','sourceCanvas','clearSelection','request','controls','drawAll','refresh','choose','undo','refreshLinked','linkedPopulation','notifyLinked','privateSnapshot'];
for(const optional of ['sourceDensity','sourceReady','selectionUnavailable'])if(source.includes('function '+optional+'('))functions.push(optional);
const declarations=['key','isCurrent','available','linkedViewKey','status'];
const subscriber=source.match(/ECGLinkedSelection\.subscribe\((\(snap,detail\)=>\{.*\})\);/);assert(subscriber,'production selection subscriber exists');
const checks=[];
async function check(name,fn){await fn();checks.push(name);}
function fixture(){
  const nodes=new Map(),node=id=>{
    if(!nodes.has(id))nodes.set(id,{id,dataset:{},value:id==='#morphRangeLead'?'top':'',disabled:false,title:'',textContent:'',hidden:true,
      setAttribute(name,value){this[name]=value},querySelector(selector){return node(id+' '+selector)},querySelectorAll(){return []},contains(){return false},getClientRects(){return [{}]}});
    return nodes.get(id);
  };
  const calls=[],pending=[];
  const box={ECGMorphologyGroups:G,ECGLinkedSelection:Linked.create(),AbortController,URLSearchParams,Promise,Map,Set,Object,JSON,Number,console,
    state:{caseId:'synthetic-readiness',caseRequestId:1,currentPage:'edit',editMode:'cluster',caseData:{analysis_revision:2},editSelectedClass:'source-N',editReadIdentity:{id:'synthetic-readiness',caseToken:1,analysis_basis:'synthetic-basis',analysis_revision:4}},
    document:{querySelector:node,querySelectorAll:()=>[],activeElement:null},fmtNumber:n=>String(n),editClassLabel:()=> 'synthetic source',calls,pending,
    api:async(url,opts)=>{
      const body=JSON.parse(opts.body),query=new URL(url,'https://synthetic.invalid').searchParams,lead=query.get('lead');calls.push({body,gate:query.get('gate')});
      const samples=(body.samples||[200,400,600]).filter(s=>!(body.exclude_samples||[]).includes(s));
      const data={revision:2,beat_revision:2,analysis_basis:'synthetic-basis',analysis_revision:4,lead,population_samples:samples,total:samples.length,included:samples.length,sample_indices:samples,amplitude_limit:100,skipped_edges:0};
      if(JSON.stringify(body.samples)==='[200,400]'&&!query.has('gate'))return new Promise((resolve,reject)=>pending.push({resolve:()=>resolve(data),reject}));
      return data;
    }};
  vm.createContext(box);
  vm.runInContext(`
    const G=ECGMorphologyGroups,qs=s=>document.querySelector(s),view={top:'II',bottom:'V1',groups:'II'},sourceIds={top:'editDensityPrimary',bottom:'editDensitySelection'};
    const sessions=new Map(),plots=new Map(),linkedListeners=new Set();let linkedNotifyQueued=false;
    let current=null,requestToken=0,selectionToken=0,busy=false,selecting=false,saving=false,selection=null,box=null,drag=null,activeSlot=6,formSlot=null,formContext=null,saveReload=null,leadPickerOwner=null;
    const closeForm=()=>{},closeLeadPicker=()=>{},ownSaveTransition=()=>false,scheduleDraw=()=>drawAll();
    function draw(canvas,data){if(data)plots.set(canvas,{limit:data.amplitude_limit,data});else plots.delete(canvas);}
    ${declarations.map(declaration).join('\n')}
    ${functions.map(actual).join('\n')}
    const c=context();current={...c,key:key(c),phase:'ready',groups:new G.Groups([200,400,600]),saved:{},limits:{II:100,V1:100},base:{},data:{},pending:new Map(),partitionGeneration:2,viewedScope:{kind:'remainder'}};
    current.groups.move(7,[600]);current.groups.move(6,[200,400]);
    for(const lead of ['II','V1'])current.base[lead]={revision:2,beat_revision:2,analysis_basis:'synthetic-basis',analysis_revision:4,lead,population_samples:[200,400,600],total:3,included:3,sample_indices:[200,400,600],amplitude_limit:100,skipped_edges:0};
    current.data={top:current.base.II,bottom:current.base.V1};sessions.set(current.key,current);
    ECGLinkedSelection.setScope({caseId:c.id,caseToken:c.caseToken,analysis_basis:c.basis,analysis_revision:c.analysisRevision,beatRevision:c.revision});
    ECGLinkedSelection.select({samples:[200,400],origin:'template.density-gate'},{expectedScope:ECGLinkedSelection.snapshot().scope});
    let generation=null;ECGLinkedSelection.subscribe(${subscriber[1]});
    controls();drawAll();
    globalThis.subject={undo,choose,refresh,refreshLinked,controls,snapshot:()=>({applyDisabled:qs('#applyEditRange').disabled,impact:qs('#morphImpact').textContent,status:qs('#morphStatus').textContent,linkedPhase:current.linked?.phase||null,groupSix:[...current.groups.slots[6]],groupSeven:[...current.groups.slots[7]],remainder:current.groups.remaining(),selection:selection?.samples||null,sourcePlot:plots.has(sourceCanvas('top')),templateDisabled:qs('#morphGroupTemplate').disabled,undoDisabled:qs('#morphUndo').disabled}),activeGroup:n=>{activeSlot=n;controls()},dropPlot:()=>plots.delete(sourceCanvas('top')),changeRevision:()=>{state.editReadIdentity.analysis_revision++;ECGLinkedSelection.setScope({...ECGLinkedSelection.snapshot().scope,analysis_revision:state.editReadIdentity.analysis_revision})},changeCase:()=>{state.caseRequestId++;ECGLinkedSelection.snapshot()},viewGroup:n=>{current.viewedScope={kind:'group',slot:n}},rangeSlot:slot=>{qs('#morphRangeLead').value=slot;controls()}};
  `,box);
  const tick=async()=>{for(let i=0;i<8;i++)await Promise.resolve()};
  const complete=async()=>{const reads=pending.splice(0);assert.equal(reads.length,2);reads.forEach(r=>r.resolve());await tick()};
  const reject=async()=>{const reads=pending.splice(0);assert.equal(reads.length,2);reads.forEach(r=>r.reject(Error('synthetic density failure')));await tick()};
  return {box,subject:box.subject,calls,pending,tick,complete,reject};
}
(async()=>{
  await check('actual-undo-keeps-range-disabled-until-linked-plots-are-ready-without-blocking-group-work',async()=>{
    const f=fixture();await f.subject.undo();const loading=f.subject.snapshot();assert.equal(loading.linkedPhase,'loading');assert.equal(loading.sourcePlot,false);assert.equal(loading.applyDisabled,true);assert.equal(loading.undoDisabled,false);f.subject.activeGroup(7);assert.equal(f.subject.snapshot().templateDisabled,false);assert.deepEqual(Array.from(loading.groupSix),[]);assert.deepEqual(Array.from(loading.groupSeven),[600]);assert.deepEqual(Array.from(loading.remainder),[200,400]);
    const calls=f.calls.length;await f.subject.choose('top',{x:.4,y:.1},{x:.62,y:.42});assert.equal(f.calls.length,calls);assert.match(f.subject.snapshot().status,/读取.*密度|密度.*读取/);assert.equal(f.subject.snapshot().selection,null);
    await f.complete();assert.equal(f.subject.snapshot().applyDisabled,false);assert.equal(f.subject.snapshot().sourcePlot,true);await f.subject.choose('top',{x:.4,y:.1},{x:.62,y:.42});assert.deepEqual(Array.from(f.subject.snapshot().selection),[200,400]);const gate=f.calls.filter(c=>c.gate).at(-1);assert.deepEqual(gate.body.samples,[200,400]);assert.deepEqual(gate.body.exclude_samples,[600]);
  });
  await check('actual-linked-error-updates-feedback-and-retry-enables-range-after-fresh-data',async()=>{
    const f=fixture();await f.subject.undo();f.subject.activeGroup(7);await f.reject();const failed=f.subject.snapshot();assert.equal(failed.linkedPhase,'error');assert.equal(failed.applyDisabled,true);assert.equal(failed.templateDisabled,false);assert.match(failed.impact,/失败|重试|重新读取/);await f.subject.choose('top',{x:.4,y:.1},{x:.62,y:.42});assert.match(f.subject.snapshot().status,/失败|重新读取/);await f.subject.refresh(true);assert.equal(f.subject.snapshot().linkedPhase,'loading');assert.equal(f.subject.snapshot().applyDisabled,true);await f.complete();assert.equal(f.subject.snapshot().applyDisabled,false);assert.deepEqual(Array.from(f.subject.snapshot().groupSeven),[600]);
  });
  await check('actual-clear-cancels-pending-linked-read-and-late-result-cannot-replace-remainder',async()=>{
    const f=fixture();await f.subject.undo();f.box.ECGLinkedSelection.clear({origin:'synthetic-cancel'});await f.tick();assert.equal(f.subject.snapshot().linkedPhase,null);assert.equal(f.subject.snapshot().applyDisabled,false);await f.complete();assert.equal(f.subject.snapshot().linkedPhase,null);assert.deepEqual(Array.from(f.subject.snapshot().remainder),[200,400]);assert.deepEqual(Array.from(f.subject.snapshot().groupSeven),[600]);
  });
  for(const change of ['changeCase','changeRevision'])await check('actual-'+change+'-rejects-late-density-and-never-enables-old-range',async()=>{
    const f=fixture();await f.subject.undo();f.subject[change]();await f.tick();await f.complete();assert.equal(f.subject.snapshot().applyDisabled,true);const calls=f.calls.length;await f.subject.choose('top',{x:.4,y:.1},{x:.62,y:.42});assert.equal(f.calls.length,calls);assert.equal(f.subject.snapshot().selection,null);assert.match(f.subject.snapshot().status,/病例|版本|依据/);
  });
  await check('actual-missing-plot-and-viewed-group-produce-feedback-without-changing-members',async()=>{
    const f=fixture();await f.subject.undo();await f.complete();f.subject.dropPlot();await f.subject.choose('top',{x:.4,y:.1},{x:.62,y:.42});assert.match(f.subject.snapshot().status,/密度|绘图/);assert.equal(f.subject.snapshot().selection,null);f.subject.controls();await f.subject.refreshLinked();f.subject.viewGroup(7);await f.subject.choose('top',{x:.4,y:.1},{x:.62,y:.42});assert.match(f.subject.snapshot().status,/查看剩余/);assert.deepEqual(Array.from(f.subject.snapshot().groupSeven),[600]);
  });
  console.log(JSON.stringify({passed:true,actual_check_count:checks.length,checks}));
})().catch(error=>{console.error(error.stack);process.exitCode=1});
