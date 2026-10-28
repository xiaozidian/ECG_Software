"use strict";
/* Explicit range drafts: moving a handle never silently saves a report. */
(()=>{
 let context=null;const drafts=new Map();
 const notify=()=>{if(typeof document!=='undefined')document.dispatchEvent(new CustomEvent('ecg-report-range-change'));};
 function setContext(value){if(context!==value){context=value;drafts.clear();notify();}}
 const pending=()=>Array.from(drafts.values());
 function clear(){drafts.clear();notify();}
 function forget(key){drafts.delete(key);notify();}
 function assertApplied(){if(drafts.size)throw Error(`还有 ${drafts.size} 处游标修改尚未应用，请返回处理或明确放弃后再保存、预览或导出。`);}
 const esc=x=>String(x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const stamp=s=>{const n=Math.round(s*1000),ms=n%1000,sec=Math.floor(n/1000);return `D${Math.floor(sec/86400)+1} ${String(Math.floor(sec%86400/3600)).padStart(2,'0')}:${String(Math.floor(sec%3600/60)).padStart(2,'0')}:${String(sec%60).padStart(2,'0')}.${String(ms).padStart(3,'0')}`};
 function mount(host,entry,wave,onApply,onReset,options={}){
  host._rangeDispose?.();
  const mountToken={};host._rangeMountToken=mountToken;const listeners=[];
  const listen=(name,fn)=>{host.addEventListener(name,fn);listeners.push([name,fn]);};
  host._rangeDispose=()=>{for(const [name,fn] of listeners)host.removeEventListener?.(name,fn);host._rangePlotObserver?.disconnect();};
  const lo=wave.start_s,hi=lo+wave.duration_s;let a=entry.strip.start_s,b=entry.strip.end_s,drag=null,busy=false;
  if(options.context!==undefined)setContext(options.context);
  const key=options.event?.event_id,ownContext=context,baseline=JSON.stringify([entry.strip.start_s,entry.strip.end_s]),draft=key&&drafts.get(key);
  const current=()=>host._rangeMountToken===mountToken&&host.isConnected!==false&&host.querySelector('.report-range-stage')===stage&&context===ownContext;
  if(draft&&draft.basis===options.basis&&draft.baseline===baseline){a=draft.a;b=draft.b;}
  function remember(){if(!key||!current())return;const changed=Math.abs(a-entry.strip.start_s)>.001||Math.abs(b-entry.strip.end_s)>.001;if(changed)drafts.set(key,{...options,baseline,a,b,applied:{a:entry.strip.start_s,b:entry.strip.end_s,inReport:entry.inReport}});else drafts.delete(key);notify();}
  const columns=1; // Full-width shared clock; never split twelve leads.
  function plot(w=1000,h=300){return ECGOccurrenceCard.svg(wave,entry,{width:w,height:h,rowHeight:64,timeAxis:true,inset:0,columns,domain:options.domain,recordStart:options.recordStart});}
  host.className='report-range-editor';host.innerHTML=`<header><strong>人工入报区间</strong><span>拖动波形框选，或拖动橘色边界；应用后才写入报告</span></header><div class="report-range-stage">${plot()}<div class="report-range-selection" aria-hidden="true"></div><button type="button" class="report-range-handle" data-range-drag="start" aria-label="主波形入报起点，左右方向键微调"></button><button type="button" class="report-range-handle" data-range-drag="end" aria-label="主波形入报终点，左右方向键微调"></button></div><output aria-live="polite"></output><div class="range-actions"><button type="button" data-range-apply>应用区间${entry.inReport?'':'并加入报告'}</button><button type="button" data-range-cancel disabled>取消区间修改</button><button type="button" data-range-reset>恢复自动区间</button></div><details class="range-precision"><summary>精确起止</summary><div class="range-fields"><label>起点（秒）<input type="number" data-bound="start" step="0.005" min="0"></label><label>终点（秒）<input type="number" data-bound="end" step="0.005" min="0"></label></div></details><p class="range-error" role="status"></p>`;
  host.style.setProperty('--range-wave-height',((globalThis.ECGChartInspection?.names(wave.leads)||Object.keys(wave.leads)).length*64+48)+'px');
  const stage=host.querySelector('.report-range-stage');if(host.dataset)host.dataset.waveColumns=String(columns);if(columns===2){for(const node of [...stage.querySelectorAll('.report-range-selection,[data-range-drag]')]){node.dataset.rangeColumn='0';const clone=node.cloneNode(true);clone.dataset.rangeColumn='1';stage.append(clone);}}let plotSize='';
  function resizePlot(){if(!current())return;
    const container=host.closest('#v2EventWave'),count=Object.keys(wave.leads||{}).length;
    host.style.setProperty('--range-wave-height',(count*64+48)+'px');
    const rect=stage.getBoundingClientRect();if(rect.width<=0||rect.height<=0)return;const size=rect.width+'|'+rect.height;if(size===plotSize)return;plotSize=size;stage.querySelector('svg').outerHTML=plot(rect.width,rect.height);if(host._rangeReady)render();}
  // Resize only the retained source plot; drafts, handles and input focus stay alive.
  host._rangePlotObserver?.disconnect();
  if(typeof ResizeObserver!=='undefined'){const observer=new ResizeObserver(()=>{if(!host.isConnected){observer.disconnect();return;}resizePlot();});host._rangePlotObserver=observer;observer.observe(stage);}
  if(stage.getBoundingClientRect)resizePlot();
  const clamp=(x,min,max)=>Math.max(min,Math.min(max,Math.round(x*200)/200));
  function render(){if(!current())return;const left=(a-lo)/(hi-lo),right=(b-lo)/(hi-lo),w=stage.getBoundingClientRect?.().width||1000,gap=columns===2?24:0,panel=(w-gap)/columns;
    if(columns===1){host.querySelectorAll('[data-range-drag=start]').forEach(h=>h.style.left=left*100+'%');host.querySelectorAll('[data-range-drag=end]').forEach(h=>h.style.left=right*100+'%');const shade=host.querySelector('.report-range-selection');if(shade){shade.style.left=left*100+'%';shade.style.width=(right-left)*100+'%';}}
    else for(const node of stage.querySelectorAll('[data-range-drag],.report-range-selection')){const col=Number(node.dataset.rangeColumn)||0,origin=col*(panel+gap);node.style.left=(origin+(node.dataset.rangeDrag==='end'?right:left)*panel)+'px';if(node.classList.contains('report-range-selection'))node.style.width=((right-left)*panel)+'px';}
    host.querySelector('[data-bound=start]').value=a.toFixed(3);host.querySelector('[data-bound=end]').value=b.toFixed(3);const count=(wave.beats||[]).filter(r=>!['X','O','Y','T'].includes(r.class_code)&&r.sample_index/(wave.sample_rate_hz||200)>=a&&r.sample_index/(wave.sample_rate_hz||200)<b).length,changed=Math.abs(a-entry.strip.start_s)>.001||Math.abs(b-entry.strip.end_s)>.001;host.querySelector('[data-range-cancel]').disabled=busy||!changed;if(host.dataset)host.dataset.rangeStatus=changed?'pending':entry.inReport?'applied':'candidate';host.querySelector('output').innerHTML=`<span data-range-current-status><strong>${changed?'待应用区间':options.candidateOnly?'候选区间（是否入报请见报告编排）':entry.inReport?'当前已应用区间':'候选区间（尚未入报）'}</strong> ${stamp(a)} — ${stamp(b)} · ${(b-a).toFixed(3)} 秒 · ${count} 搏${changed?' · 当前窗口暂存':''}</span>${changed?`<span data-range-applied-status><strong>${options.candidateOnly?'原候选区间':'当前已应用区间'}</strong> ${options.candidateOnly||entry.inReport?stamp(entry.strip.start_s)+' — '+stamp(entry.strip.end_s):'此事件尚未入报'}</span>`:''}`;}
  host._rangeEventId=key;host._rangeSetMembership=inReport=>{if(!current())return;entry.inReport=inReport;host.querySelector('[data-range-apply]').textContent='应用区间'+(inReport?'':'并加入报告');render();remember();};
  listen('pointerdown',e=>{if(busy||e.button!==0||!current())return;const target=e.target.closest('[data-range-drag]'),surface=e.target.closest('.report-range-stage');if(!target&&!surface)return;if(!target&&e.target.closest('button,input,select,textarea'))return;const box=stage.getBoundingClientRect();if(box.width<=0)return;e.preventDefault();e.stopPropagation();const panel=(box.width-(columns===2?24:0))/columns,col=target?Number(target.dataset.rangeColumn)||0:Math.min(columns-1,Math.floor((e.clientX-box.left)/(panel+24)));drag={id:e.pointerId,kind:target?.dataset.rangeDrag||'select',a,b,x:e.clientX,left:box.left+col*(panel+24),width:panel,moved:false};if(target)target.setPointerCapture(e.pointerId)});
  listen('pointermove',e=>{if(!drag||drag.id!==e.pointerId||!current())return;const delta=(e.clientX-drag.x)/drag.width*(hi-lo);if(drag.kind==='select'){if(!drag.moved&&Math.abs(e.clientX-drag.x)<5)return;if(!drag.moved)stage.setPointerCapture(e.pointerId);drag.moved=true;const origin=clamp(lo+(drag.x-drag.left)/drag.width*(hi-lo),lo,hi-1),point=clamp(lo+(e.clientX-drag.left)/drag.width*(hi-lo),lo,hi);a=clamp(Math.min(origin,point),lo,hi-1);b=clamp(Math.max(origin,point),a+1,Math.min(hi,a+120));}else if(drag.kind==='start')a=clamp(drag.a+delta,Math.max(lo,b-120),b-1);else if(drag.kind==='end')b=clamp(drag.b+delta,a+1,Math.min(hi,a+120));render();remember()});
  listen('pointerup',()=>{drag=null});listen('lostpointercapture',()=>{drag=null});
  listen('pointercancel',()=>{if(drag){a=drag.a;b=drag.b;drag=null;render();remember();}});
  listen('keydown',e=>{const h=e.target.closest('[data-range-drag]');if(busy||!current()||!h||!['ArrowLeft','ArrowRight'].includes(e.key))return;e.preventDefault();e.stopPropagation();const d=(e.key==='ArrowLeft'?-1:1)*(e.shiftKey?.5:.005);if(h.dataset.rangeDrag==='start')a=clamp(a+d,Math.max(lo,b-120),b-1);else b=clamp(b+d,a+1,Math.min(hi,a+120));render();remember()});
  host.querySelectorAll('[data-bound]').forEach(input=>input.onchange=()=>{if(busy||!current())return;const x=input.value===''?NaN:Number(input.value);if(Number.isFinite(x)){if(input.dataset.bound==='start')a=clamp(x,Math.max(lo,b-120),b-1);else b=clamp(x,a+1,Math.min(hi,a+120))}render();remember()});
  // Reconcile numeric drafts on blur as well as change (including autofill).
  host.querySelectorAll('[data-bound]').forEach(input=>input.addEventListener('blur',()=>input.onchange()));
  async function commit(reset){if(busy||!current())return;busy=true;const error=host.querySelector('.range-error');error.textContent='正在校验区间与心搏数…';host.querySelectorAll('button,input').forEach(x=>x.disabled=true);const saved=key&&drafts.get(key);try{await(reset?onReset():onApply({range_start_s:a,range_end_s:b}));if(current()){error.textContent='';if(drafts.get(key)===saved)forget(key);}}catch(e){if(current())error.textContent=e.message;}finally{busy=false;if(current()){host.querySelectorAll('button,input').forEach(x=>x.disabled=false);render();}}}
  host.querySelector('[data-range-cancel]').onclick=()=>{if(busy||!current())return;a=entry.strip.start_s;b=entry.strip.end_s;drag=null;host.querySelector('.range-error').textContent='';render();remember();};host.querySelector('[data-range-reset]').title='重新校验自动 7 秒 / 至少 5 个可用心搏；不改诊断确认';
  host.querySelector('[data-range-apply]').onclick=()=>commit(false);host.querySelector('[data-range-reset]').onclick=()=>commit(true);host._rangeReady=true;render();
 }
 globalThis.ECGReportRange={mount,setContext,pending,clear,forget,assertApplied,formatTime:stamp};
})();
