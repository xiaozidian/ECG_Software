"use strict";
/* Explicit range drafts: moving a handle never silently saves a report. */
(()=>{
 const esc=x=>String(x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function mount(host,entry,wave,onApply,onReset){
  const lo=wave.start_s,hi=lo+wave.duration_s;let a=entry.strip.start_s,b=entry.strip.end_s,drag=null,busy=false;
  const stamp=s=>{const n=Math.floor(s),ms=Math.round((s-n)*1000);return `D${Math.floor(n/86400)+1} ${String(Math.floor(n%86400/3600)).padStart(2,'0')}:${String(Math.floor(n%3600/60)).padStart(2,'0')}:${String(n%60).padStart(2,'0')}.${String(ms).padStart(3,'0')}`};
  function plot(){const leads=Object.entries(wave.leads),h=300,row=h/Math.max(1,leads.length),w=1000;let out=`<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-label="入报区间游标波形">`;
   for(const [j,[lead,v]] of leads.entries()){const amp=Math.max(50,...v.map(Math.abs)),mid=(j+.55)*row;out+=`<path d="M0 ${mid}H1000" stroke="#dce5e8"/><text x="4" y="${j*row+22}" font-size="16">${esc(lead)}</text><polyline fill="none" stroke="#244650" stroke-width="1.2" points="${v.map((x,i)=>`${(i/Math.max(1,v.length-1)*w).toFixed(2)},${(mid-x/amp*row*.36).toFixed(2)}`).join(' ')}"/>`}
   const beat=(wave.beats||[]).reduce((best,r)=>!best||Math.abs(r.sample_index-entry.sample_index)<Math.abs(best.sample_index-entry.sample_index)?r:best,null);if(beat){const x=(beat.sample_index/200-lo)/wave.duration_s*w;if(x>=0&&x<=w)out+=ECGReviewTools.markSvg(x,h,beat.class_code)}return out+'</svg>';
  }
  host.className='report-range-editor';host.innerHTML=`<header><strong>橘色游标 · 人工入报区间</strong><span>拖动左右游标调整范围，也可输入起止时间</span></header><div class="report-range-stage">${plot()}<button type="button" class="report-range-handle" data-range-drag="start" aria-label="主波形入报起点，左右方向键微调"></button><button type="button" class="report-range-handle" data-range-drag="end" aria-label="主波形入报终点，左右方向键微调"></button></div><output aria-live="polite"></output><div class="range-fields"><label>起点（秒）<input type="number" data-bound="start" step="0.005" min="0"></label><label>终点（秒）<input type="number" data-bound="end" step="0.005" min="0"></label><button type="button" data-range-apply>应用区间${entry.inReport?'':'并加入报告'}</button><button type="button" data-range-reset>恢复自动 7 秒 / 至少 5 搏</button></div><p class="range-error" role="status"></p>`;
  host.style.setProperty('--range-wave-height',Math.max(210,Object.keys(wave.leads).length*70)+'px');
  const clamp=(x,min,max)=>Math.max(min,Math.min(max,Math.round(x*200)/200));
  function render(){const left=(a-lo)/(hi-lo)*100,right=(b-lo)/(hi-lo)*100;host.querySelectorAll('[data-range-drag=start]').forEach(h=>h.style.left=left+'%');host.querySelectorAll('[data-range-drag=end]').forEach(h=>h.style.left=right+'%');host.querySelector('[data-bound=start]').value=a.toFixed(3);host.querySelector('[data-bound=end]').value=b.toFixed(3);const count=(wave.beats||[]).filter(r=>!['X','O','Y','T'].includes(r.class_code)&&r.sample_index/200>=a&&r.sample_index/200<b).length,changed=Math.abs(a-entry.strip.start_s)>.001||Math.abs(b-entry.strip.end_s)>.001;host.querySelector('output').textContent=`${stamp(a)} — ${stamp(b)} · ${(b-a).toFixed(3)} 秒 · ${count} 搏 · ${changed?'尚未应用的游标范围':entry.inReport?'当前入报范围':'候选范围（尚未入报）'}`;}
  host.addEventListener('pointerdown',e=>{const target=e.target.closest('[data-range-drag]');if(!target||busy||e.button!==0)return;e.preventDefault();e.stopPropagation();drag={id:e.pointerId,kind:target.dataset.rangeDrag,a,b,x:e.clientX,width:target.parentElement.getBoundingClientRect().width};target.setPointerCapture(e.pointerId)});
  host.addEventListener('pointermove',e=>{if(!drag||drag.id!==e.pointerId)return;const delta=(e.clientX-drag.x)/drag.width*(hi-lo);if(drag.kind==='start')a=clamp(drag.a+delta,Math.max(lo,b-120),b-1);else if(drag.kind==='end')b=clamp(drag.b+delta,a+1,Math.min(hi,a+120));render()});
  for(const name of ['pointerup','pointercancel','lostpointercapture'])host.addEventListener(name,()=>{drag=null});
  host.addEventListener('keydown',e=>{const h=e.target.closest('[data-range-drag]');if(!h||!['ArrowLeft','ArrowRight'].includes(e.key))return;e.preventDefault();e.stopPropagation();const d=(e.key==='ArrowLeft'?-1:1)*(e.shiftKey?.5:.005);if(h.dataset.rangeDrag==='start')a=clamp(a+d,Math.max(lo,b-120),b-1);else b=clamp(b+d,a+1,Math.min(hi,a+120));render()});
  host.querySelectorAll('[data-bound]').forEach(input=>input.onchange=()=>{const x=Number(input.value);if(Number.isFinite(x)){if(input.dataset.bound==='start')a=clamp(x,Math.max(lo,b-120),b-1);else b=clamp(x,a+1,Math.min(hi,a+120))}render()});
  // Reconcile numeric drafts on blur as well as change (including autofill).
  host.querySelectorAll('[data-bound]').forEach(input=>input.addEventListener('blur',()=>input.onchange()));
  async function commit(reset){if(busy)return;busy=true;const error=host.querySelector('.range-error');error.textContent='正在校验区间与心搏数…';host.querySelectorAll('button,input').forEach(x=>x.disabled=true);try{await(reset?onReset():onApply({range_start_s:a,range_end_s:b}));}catch(e){error.textContent=e.message;}finally{busy=false;host.querySelectorAll('button,input').forEach(x=>x.disabled=false)}}
  host.querySelector('[data-range-apply]').onclick=()=>commit(false);host.querySelector('[data-range-reset]').onclick=()=>commit(true);render();
 }
 globalThis.ECGReportRange={mount};
})();
