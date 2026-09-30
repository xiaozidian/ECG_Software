const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const events=[];
const ctx=vm.createContext({document:{dispatchEvent:e=>events.push(e.type)},CustomEvent:class{constructor(type){this.type=type}},ECGReviewTools:{markSvg:()=>''}});
vm.runInContext(fs.readFileSync('static/js/report-range-editor.js','utf8'),ctx);
const R=ctx.ECGReportRange;
function host(){
 const nodes=new Map(),handlers={};
 const node=s=>{if(!nodes.has(s))nodes.set(s,{value:'',textContent:'',style:{},disabled:false,dataset:{bound:s.includes('start')?'start':'end'},addEventListener(){}});return nodes.get(s)};
 return {style:{setProperty(){}},addEventListener:(k,v)=>handlers[k]=v,querySelector:node,
 querySelectorAll:s=>s==='[data-bound]'?[node('[data-bound=start]'),node('[data-bound=end]')]:s==='button,input'?[node('[data-range-apply]'),node('[data-range-reset]'),node('[data-bound=start]'),node('[data-bound=end]')]:[node(s)],handlers};
}
const entry={sample_index:2000,strip:{start_s:7,end_s:14},inReport:true};
const wave={start_s:0,duration_s:30,leads:{II:[0,1,0]},beats:[]};
const options=(event='one',basis='source',context='case-A')=>({event:{event_id:event},basis,context});
function mount(opts=options(),apply=async()=>{},reset=async()=>{}){const h=host();R.mount(h,entry,wave,apply,reset,opts);return h;}
function change(h,value){const n=h.querySelector('[data-bound=start]');n.value=String(value);n.onchange();}
(async()=>{
 let h=mount();assert.equal(R.pending().length,0);change(h,8);assert.equal(R.pending()[0].a,8);assert.throws(()=>R.assertApplied(),/尚未应用/);
 mount(options('two'));assert.equal(R.pending().length,1,'another event erased the range');
 h=mount();assert.equal(h.querySelector('[data-bound=start]').value,'8.000','return did not restore');
 change(h,7);assert.equal(R.pending().length,0,'original boundary must remove temporary state');
 h=mount(options(),async()=>{throw Error('offline')});change(h,8);await h.querySelector('[data-range-apply]').onclick();assert.equal(R.pending().length,1);assert.equal(h.querySelector('.range-error').textContent,'offline');
 let resolve;h=mount(options(),()=>new Promise(r=>resolve=r));const pending=h.querySelector('[data-range-apply]').onclick();assert.throws(()=>R.assertApplied(),/尚未应用/,'pending validation must not unblock saving');resolve();await pending;assert.equal(R.pending().length,0);
 h=mount();change(h,8);const stale=mount(options('one','new-source'));assert.equal(stale.querySelector('[data-bound=start]').value,'7.000','stale basis restored draft');assert.equal(R.pending().length,1,'stale draft must remain explicit until discarded');
 R.clear();R.assertApplied();h=mount();change(h,8);R.setContext('case-B');assert.equal(R.pending().length,0,'case scope leaked');
 h=mount();change(h,8);const other=mount(options('two'));change(other,9);assert.equal(R.pending().length,2);R.forget('one');assert.equal(R.pending().length,1);assert.equal(R.pending()[0].event.event_id,'two');
 R.clear();h=mount();h.handlers.keydown({target:{closest:()=>({dataset:{rangeDrag:'start'}})},key:'ArrowRight',shiftKey:false,preventDefault(){},stopPropagation(){}});assert.equal(R.pending()[0].a,7.005);
 assert(events.length>0);
 // Real production write/export entry points must check temporary drafts before work.
 const ui=fs.readFileSync('static/js/clinical-ui.js','utf8');
 const notice=host();notice.querySelector('[data-range-keep]').focus=()=>{};notice.querySelector('[data-range-discard]').focus=()=>{};
 ctx.qs=s=>s==='#reportRangeDraftNotice'?notice:{};ctx.run=f=>f();let rendered=0;ctx.renderReportBody=()=>{rendered++};
 vm.runInContext(ui.slice(ui.indexOf('  function renderRangeDraftNotice('),ui.indexOf('  function hrvForReport(')),ctx);
 ctx.renderRangeDraftNotice();assert.match(notice.innerHTML,/1 处/);
 notice.querySelector('[data-range-discard]').onclick();assert.match(notice.innerHTML,/确认放弃/);
 notice.querySelector('[data-range-keep]').onclick();assert.equal(R.pending().length,1,'cancel discarded range');
 notice.querySelector('[data-range-discard]').onclick();const staleConfirm=notice.querySelector('[data-range-confirm-discard]').onclick;
 change(h,8);staleConfirm();assert.equal(R.pending().length,1,'stale confirmation discarded newer edit');
 notice.querySelector('[data-range-discard]').onclick();notice.querySelector('[data-range-confirm-discard]').onclick();assert.equal(R.pending().length,0);assert.equal(rendered,1);
 // Existing case-leave confirmation must include temporary ranges, even with a clean report.
 h=mount();change(h,8);ctx.state={reportSaving:false,reportDirty:false,report:{composition:{}}};let accepted=false,prompt='';
 ctx.window={confirm:text=>{prompt=text;return accepted}};ctx.normalizedReportComposition=x=>x;
 const workflow=fs.readFileSync('static/js/clinical-workflow.js','utf8');vm.runInContext(workflow.slice(workflow.indexOf('  function allowLeave('),workflow.indexOf('  function bind(')),ctx);
 assert.equal(ctx.allowLeave(),false);assert.equal(R.pending().length,1);assert.match(prompt,/尚未应用/);
 accepted=true;assert.equal(ctx.allowLeave(),true);assert.equal(R.pending().length,0);
 for(const name of ['save','previewPaper','print','reloadReport','downloadReport']){
   const start=ui.indexOf('  async function '+name+'(');assert(start>=0);
   const end=ui.indexOf('\n  }',start)+4;const blocked=vm.createContext({ECGReportRange:{assertApplied(){throw Error('pending-range')}}});
   vm.runInContext(ui.slice(start,end),blocked);await assert.rejects(blocked[name](),/pending-range/);
 }
 assert(ui.slice(ui.indexOf("qs('#downloadReport').addEventListener")).includes('run(downloadReport)'));
 console.log('Temporary ranges: restore, failure, pending writes, basis/case isolation, discard and keyboard passed');
})().catch(e=>{console.error(e);process.exitCode=1});
