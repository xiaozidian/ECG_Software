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
  const lo=wave.start_s,hi=lo+wave.duration_s;let a=entry.strip.start_s,b=entry.strip.end_s,drag=null,busy=false;
  if(options.context!==undefined)setContext(options.context);
  const key=options.event?.event_id,ownContext=context,baseline=JSON.stringify([entry.strip.start_s,entry.strip.end_s]),draft=key&&drafts.get(key);
  if(draft&&draft.basis===options.basis&&draft.baseline===baseline){a=draft.a;b=draft.b;}
  function remember(){if(!key||context!==ownContext)return;const changed=Math.abs(a-entry.strip.start_s)>.001||Math.abs(b-entry.strip.end_s)>.001;if(changed)drafts.set(key,{...options,baseline,a,b,applied:{a:entry.strip.start_s,b:entry.strip.end_s,inReport:entry.inReport}});else drafts.delete(key);notify();}
  function plot(w=1000,h=300){const leads=(globalThis.ECGChartInspection?.entries(wave.leads)||Object.entries(wave.leads)),row=h/Math.max(1,leads.length),fs=wave.sample_rate_hz||200,stride=wave.stride||1;let out=`<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="入报区间游标波形，设备单位，各导联自适应幅度">`;
   for(const [j,[lead,v]] of leads.entries()){const amp=Math.max(50,...v.map(Math.abs)),mid=(j+.55)*row;out+=`<path d="M0 ${mid}H${w}" stroke="#dce5e8" vector-effect="non-scaling-stroke"/><text x="4" y="${j*row+16}" font-size="13">${esc(lead)}</text><polyline data-lead="${esc(lead)}" fill="none" stroke="#172126" stroke-width="1.2" vector-effect="non-scaling-stroke" points="${v.map((x,i)=>`${(i*stride/fs/wave.duration_s*w).toFixed(3)},${(mid-x/amp*row*.36).toFixed(3)}`).join(' ')}"/>`}
   const beat=(wave.beats||[]).reduce((best,r)=>!best||Math.abs(r.sample_index-entry.sample_index)<Math.abs(best.sample_index-entry.sample_index)?r:best,null);if(beat){const x=(beat.sample_index/fs-lo)/wave.duration_s*w;if(x>=0&&x<=w)out+=ECGReviewTools.markSvg(x,h,beat.class_code)}return out+'</svg>';
  }
  host.className='report-range-editor';host.innerHTML=`<header><strong>橘色游标 · 人工入报区间</strong><span>拖动左右游标调整范围，也可输入起止时间</span></header><div class="report-range-stage">${plot()}<button type="button" class="report-range-handle" data-range-drag="start" aria-label="主波形入报起点，左右方向键微调"></button><button type="button" class="report-range-handle" data-range-drag="end" aria-label="主波形入报终点，左右方向键微调"></button></div><output aria-live="polite"></output><div class="range-fields"><label>起点（秒）<input type="number" data-bound="start" step="0.005" min="0"></label><label>终点（秒）<input type="number" data-bound="end" step="0.005" min="0"></label><button type="button" data-range-apply>应用区间${entry.inReport?'':'并加入报告'}</button><button type="button" data-range-reset>恢复自动 7 秒 / 至少 5 搏</button></div><p class="range-error" role="status"></p>`;
  host.style.setProperty('--range-wave-height',Math.max(210,(globalThis.ECGChartInspection?.names(wave.leads)||Object.keys(wave.leads)).length*70)+'px');
  const stage=host.querySelector('.report-range-stage');let plotSize='';
  function resizePlot(){const rect=stage.getBoundingClientRect();if(rect.width<=0||rect.height<=0)return;const size=rect.width+'|'+rect.height;if(size===plotSize)return;plotSize=size;stage.querySelector('svg').outerHTML=plot(rect.width,rect.height);}
  // Resize only the retained source plot; drafts, handles and input focus stay alive.
  host._rangePlotObserver?.disconnect();
  if(typeof ResizeObserver!=='undefined'){const observer=new ResizeObserver(()=>{if(!host.isConnected){observer.disconnect();return;}resizePlot();});host._rangePlotObserver=observer;observer.observe(stage);}
  if(stage.getBoundingClientRect)resizePlot();
  const clamp=(x,min,max)=>Math.max(min,Math.min(max,Math.round(x*200)/200));
  function render(){const left=(a-lo)/(hi-lo)*100,right=(b-lo)/(hi-lo)*100;host.querySelectorAll('[data-range-drag=start]').forEach(h=>h.style.left=left+'%');host.querySelectorAll('[data-range-drag=end]').forEach(h=>h.style.left=right+'%');host.querySelector('[data-bound=start]').value=a.toFixed(3);host.querySelector('[data-bound=end]').value=b.toFixed(3);const count=(wave.beats||[]).filter(r=>!['X','O','Y','T'].includes(r.class_code)&&r.sample_index/200>=a&&r.sample_index/200<b).length,changed=Math.abs(a-entry.strip.start_s)>.001||Math.abs(b-entry.strip.end_s)>.001;host.querySelector('output').innerHTML=`<span data-range-current-status><strong>${changed?'待应用区间':entry.inReport?'当前已应用区间':'候选区间（尚未入报）'}</strong> ${stamp(a)} — ${stamp(b)} · ${(b-a).toFixed(3)} 秒 · ${count} 搏${changed?' · 当前窗口暂存':''}</span>${changed?`<span data-range-applied-status><strong>当前已应用区间</strong> ${entry.inReport?stamp(entry.strip.start_s)+' — '+stamp(entry.strip.end_s):'此事件尚未入报'}</span>`:''}`;}
  host._rangeEventId=key;host._rangeSetMembership=inReport=>{entry.inReport=inReport;host.querySelector('[data-range-apply]').textContent='应用区间'+(inReport?'':'并加入报告');render();remember();};
  host.addEventListener('pointerdown',e=>{const target=e.target.closest('[data-range-drag]');if(!target||busy||e.button!==0)return;e.preventDefault();e.stopPropagation();drag={id:e.pointerId,kind:target.dataset.rangeDrag,a,b,x:e.clientX,width:target.parentElement.getBoundingClientRect().width};target.setPointerCapture(e.pointerId)});
  host.addEventListener('pointermove',e=>{if(!drag||drag.id!==e.pointerId)return;const delta=(e.clientX-drag.x)/drag.width*(hi-lo);if(drag.kind==='start')a=clamp(drag.a+delta,Math.max(lo,b-120),b-1);else if(drag.kind==='end')b=clamp(drag.b+delta,a+1,Math.min(hi,a+120));render();remember()});
  for(const name of ['pointerup','pointercancel','lostpointercapture'])host.addEventListener(name,()=>{drag=null});
  host.addEventListener('keydown',e=>{const h=e.target.closest('[data-range-drag]');if(busy||!h||!['ArrowLeft','ArrowRight'].includes(e.key))return;e.preventDefault();e.stopPropagation();const d=(e.key==='ArrowLeft'?-1:1)*(e.shiftKey?.5:.005);if(h.dataset.rangeDrag==='start')a=clamp(a+d,Math.max(lo,b-120),b-1);else b=clamp(b+d,a+1,Math.min(hi,a+120));render();remember()});
  host.querySelectorAll('[data-bound]').forEach(input=>input.onchange=()=>{if(busy)return;const x=input.value===''?NaN:Number(input.value);if(Number.isFinite(x)){if(input.dataset.bound==='start')a=clamp(x,Math.max(lo,b-120),b-1);else b=clamp(x,a+1,Math.min(hi,a+120))}render();remember()});
  // Reconcile numeric drafts on blur as well as change (including autofill).
  host.querySelectorAll('[data-bound]').forEach(input=>input.addEventListener('blur',()=>input.onchange()));
  async function commit(reset){if(busy)return;busy=true;const error=host.querySelector('.range-error');error.textContent='正在校验区间与心搏数…';host.querySelectorAll('button,input').forEach(x=>x.disabled=true);const saved=key&&drafts.get(key);try{await(reset?onReset():onApply({range_start_s:a,range_end_s:b}));if(context===ownContext&&drafts.get(key)===saved)forget(key);}catch(e){error.textContent=e.message;}finally{busy=false;host.querySelectorAll('button,input').forEach(x=>x.disabled=false)}}
  host.querySelector('[data-range-apply]').onclick=()=>commit(false);host.querySelector('[data-range-reset]').onclick=()=>commit(true);render();
 }
 globalThis.ECGReportRange={mount,setContext,pending,clear,forget,assertApplied,formatTime:stamp};
})();
