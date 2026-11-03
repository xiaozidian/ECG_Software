const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const ctx=vm.createContext({document:{dispatchEvent(){}},CustomEvent:class{},ECGOccurrenceCard:{svg:()=>'<svg></svg>'}});
vm.runInContext(fs.readFileSync('static/js/report-range-editor.js','utf8'),ctx);
const R=ctx.ECGReportRange;
function host(){
  const nodes=new Map(),listeners=new Map();let html='';
  const node=s=>{if(!nodes.has(s))nodes.set(s,{value:'',textContent:'',style:{},disabled:false,dataset:{bound:s.includes('start')?'start':'end'},addEventListener(){}});return nodes.get(s);};
  return {
    isConnected:true,dataset:{},style:{setProperty(){}},listeners,
    get innerHTML(){return html;},set innerHTML(value){html=value;nodes.clear();},
    querySelector:node,
    querySelectorAll:s=>s==='[data-bound]'?[node('[data-bound=start]'),node('[data-bound=end]')]:s==='button,input'?[node('[data-range-apply]'),node('[data-range-cancel]'),node('[data-range-reset]'),node('[data-bound=start]'),node('[data-bound=end]')]:[node(s)],
    addEventListener(name,fn){if(!listeners.has(name))listeners.set(name,new Set());listeners.get(name).add(fn);},
    removeEventListener(name,fn){listeners.get(name)?.delete(fn);},
    dispatch(name,e){for(const fn of [...(listeners.get(name)||[])])fn(e);},
  };
}
const wave={start_s:0,duration_s:30,leads:{II:[0,1,0]},beats:[]};
const options={context:'same-case',basis:'same-source',event:{event_id:'same-candidate'},candidateOnly:true};
const entry=()=>({strip:{start_s:7,end_s:14},inReport:false});
function change(h,value){const n=h.querySelector('[data-bound=start]');n.value=String(value);n.onchange();}
function right(h){h.dispatch('keydown',{target:{closest:()=>({dataset:{rangeDrag:'start'}})},key:'ArrowRight',preventDefault(){},stopPropagation(){}});}
(async()=>{
  // Real reset flow: onReset reloads and remounts the SAME host, then old commit finishes.
  let h=host();
  const mountFresh=()=>R.mount(h,entry(),wave,async()=>{},async()=>{R.forget(options.event.event_id);mountFresh();},options);
  mountFresh();change(h,8);await h.querySelector('[data-range-reset]').onclick();
  assert.equal(h.querySelector('[data-bound=start]').value,'7.000','old reset callback overwrote new boundary');
  assert(!h.querySelector('output').innerHTML.includes('待应用区间'),'reset left stale pending output');
  assert.equal(h.querySelector('[data-range-cancel]').disabled,true);
  assert.equal(R.pending().length,0);
  for(let i=0;i<3;i++){change(h,8+i/10);await h.querySelector('[data-range-reset]').onclick();}
  for(const [name,set] of h.listeners)assert.equal(set.size,1,`duplicate ${name} listeners after reset`);
  right(h);assert.equal(h.querySelector('[data-bound=start]').value,'7.005','one key must move one sample');

  // Old in-flight validation cannot clear a newer draft or unlock its pending write.
  R.clear();h=host();let finishOld,finishNew,newWrite;
  R.mount(h,entry(),wave,async()=>{},async()=>{
    R.forget(options.event.event_id);
    R.mount(h,entry(),wave,()=>new Promise(resolve=>finishNew=resolve),async()=>{},options);
    change(h,9);newWrite=h.querySelector('[data-range-apply]').onclick();
    await new Promise(resolve=>finishOld=resolve);
  },options);
  change(h,8);const oldReset=h.querySelector('[data-range-reset]').onclick();
  assert.equal(h.querySelector('[data-range-apply]').disabled,true);
  finishOld();await oldReset;
  assert.equal(h.querySelector('[data-bound=start]').value,'9.000');
  assert.equal(R.pending()[0].a,9,'old reset cleared newer draft');
  assert.equal(h.querySelector('[data-range-apply]').disabled,true,'old finally unlocked newer validation');
  finishNew();await newWrite;

  // A failed reload may replace all controls without creating another editor.
  R.clear();h=host();R.mount(h,entry(),wave,async()=>{},async()=>{R.forget(options.event.event_id);h.innerHTML='局部波形未取得，未保留图条。';},options);
  change(h,8);await h.querySelector('[data-range-reset]').onclick();
  assert.equal(h.innerHTML,'局部波形未取得，未保留图条。');
  assert.equal(R.pending().length,0);
  console.log('Range remount: reset, repeated listeners, stale completion, busy write and failed reload passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
