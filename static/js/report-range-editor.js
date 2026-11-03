"use strict";
/* Explicit range drafts: moving a handle never silently saves a report. */

const ECGUnsavedNavigation=(()=>{
 let open=false;
 async function resolve({title,detail,stayLabel='继续编辑',saveLabel='保存并继续',discardLabel='放弃修改并继续',save,discard,isCurrent=()=>true}){
  if(open)return false;open=true;
  const focus=document.activeElement,dialog=document.createElement('dialog');
  dialog.id='unsavedChangesDialog';dialog.className='modal unsaved-changes-dialog';
  dialog.setAttribute('aria-labelledby','unsavedChangesTitle');
  dialog.setAttribute('aria-describedby','unsavedChangesDetail');
  dialog.innerHTML='<header class="modal-header"><h2 id="unsavedChangesTitle"></h2></header><p id="unsavedChangesDetail"></p><p data-unsaved-error role="alert"></p><footer class="modal-actions"><button type="button" class="button secondary" data-unsaved-stay autofocus>继续编辑</button><button type="button" class="button secondary" data-unsaved-discard></button><button type="button" class="button primary" data-unsaved-save></button></footer>';
  dialog.querySelector('h2').textContent=title;dialog.querySelector('#unsavedChangesDetail').textContent=detail;
  const saveButton=dialog.querySelector('[data-unsaved-save]');saveButton.textContent=saveLabel;saveButton.hidden=!save;
  dialog.querySelector('[data-unsaved-stay]').textContent=stayLabel;dialog.querySelector('[data-unsaved-discard]').textContent=discardLabel;dialog.querySelector('[data-unsaved-discard]').hidden=!discard;document.body.append(dialog);
  return new Promise(resolve=>{
   let busy=false,done=false;
   function finish(value){if(done)return;done=true;open=false;dialog.close();dialog.remove();if(focus?.isConnected)focus.focus({preventScroll:true});resolve(value);}
   dialog.addEventListener('cancel',e=>{e.preventDefault();if(!busy)finish(false);});
   dialog.querySelector('[data-unsaved-stay]').onclick=()=>finish(false);
   async function act(fn){if(busy)return;if(!isCurrent()){finish(false);return;}busy=true;dialog.querySelectorAll('button').forEach(b=>b.disabled=true);
    try{await fn();if(!isCurrent()){finish(false);return;}finish(true);}
    catch(error){dialog.querySelector('[data-unsaved-error]').textContent=error.message;}
    finally{busy=false;if(!done)dialog.querySelectorAll('button').forEach(b=>b.disabled=false);}
   }
   saveButton.onclick=()=>act(save);dialog.querySelector('[data-unsaved-discard]').onclick=()=>act(discard);dialog.showModal();
  });
 }
 return {resolve,isOpen:()=>open};
})();
globalThis.ECGUnsavedNavigation=ECGUnsavedNavigation;

(()=>{
 let context=null;const drafts=new Map();
 const notify=()=>{if(typeof document!=='undefined')document.dispatchEvent(new CustomEvent('ecg-report-range-change'));};
 function setContext(value){if(context!==value){context=value;drafts.clear();notify();}}
 const pending=()=>Array.from(drafts.values());
 function clear(){drafts.clear();notify();}
 function forget(key){drafts.delete(key);notify();}
 function assertApplied(){if(drafts.size)throw Error('当前区间尚未应用，请先应用或取消修改。');}
 async function resolveLeave(){
  const items=pending(),owner=context;if(!items.length)return true;
  const first=items[0],current=()=>context===owner;
  return ECGUnsavedNavigation.resolve({title:'离开前处理区间修改',detail:`${first.event?.label||'当前图条'} · ${stamp(first.a)} — ${stamp(first.b)}${items.length>1?' · 共 '+items.length+' 处':''}`,
   saveLabel:first.applied?.inReport?'应用区间并继续':'应用区间、加入报告并继续',isCurrent:current,
   save:items.every(d=>d.isCurrent?.())?async()=>{for(const d of items){if(!current()||drafts.get(d.event.event_id)!==d)throw Error('区间已变化，请继续编辑');await d.apply();}}:null,
   discard:()=>{for(const d of items){if(drafts.get(d.event?.event_id)===d){if(d.isCurrent?.())d.discard();else forget(d.event.event_id);}}}
  });
 }
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
  const restored=draft&&draft.basis===options.basis&&draft.baseline===baseline;if(restored){a=draft.a;b=draft.b;}
  function remember(){if(!key||!current())return;const changed=Math.abs(a-entry.strip.start_s)>.001||Math.abs(b-entry.strip.end_s)>.001;if(changed)drafts.set(key,{...options,baseline,a,b,isCurrent:current,apply:async()=>{if(!await commit(false))throw Error(host.querySelector('.range-error')?.textContent||'区间尚未应用');},discard:cancel,applied:{a:entry.strip.start_s,b:entry.strip.end_s,inReport:entry.inReport}});else drafts.delete(key);notify();}
  const columns=1; // Full-width shared clock; never split twelve leads.
  // One desktop row geometry and locked gain across report categories. Only a
  // genuine out-of-domain signal may grow the rows; never hide source samples.
  const profile=options.displayProfile||null,fitToFrame=!!options.fitToFrame&&!!profile,sourceNames=Object.keys(wave.leads||{}),compact=options.compactRows&&sourceNames.length>6&&Number.isFinite(options.domain)&&options.domain>0;
  let displayMode=options.displayState?.mode===12?12:3,gainFactor=options.displayState?.gain||1,count=sourceNames.length,pixelGain=compact?20/(2*options.domain):null,rowHeight=compact?ECGReviewTools.lockedWaveRows(Object.values(wave.leads),{rowHeight:32,domain:options.domain,scale:pixelGain}).rowHeight:64;
  function displayWave(){if(!profile||displayMode===12)return wave;const preferred=(options.displayLeads||['II','V1','V5']).filter(name=>Object.hasOwn(wave.leads,name)),names=preferred.length?preferred:sourceNames.slice(0,3);return {...wave,leads:Object.fromEntries(names.map(name=>[name,wave.leads[name]]))};}
  function measureDisplay(frameHeight=300){const shown=displayWave();count=Object.keys(shown.leads).length;if(profile){const base=fitToFrame?Math.max(32,(frameHeight-60)/Math.max(1,count)):displayMode===12?64:(options.rowHeight||112),fit=ECGReviewTools.reportWaveGeometry(shown,profile,base,(base-12)/(2*profile.domain)*gainFactor);rowHeight=fit.rowHeight;pixelGain=fit.pixelGain;}return shown;}
  function plot(w=1000,h=300){const shown=measureDisplay(h);return ECGOccurrenceCard.svg(shown,options.event||entry,{width:w,height:h,rowHeight,pixelGain,timeAxis:true,inset:0,columns,domain:options.domain,displayProfile:profile,fitHeight:fitToFrame,recordStart:options.recordStart});}
  host.className='report-range-editor';host.innerHTML=`<header><strong>人工入报区间</strong><span>拖动波形框选，或拖动橘色边界；应用后才写入报告</span></header><div class="report-range-stage">${plot()}<div class="report-range-selection" aria-hidden="true"></div><button type="button" class="report-range-handle" data-range-drag="start" aria-label="主波形入报起点，左右方向键微调"></button><button type="button" class="report-range-handle" data-range-drag="end" aria-label="主波形入报终点，左右方向键微调"></button></div><output aria-live="polite"></output><div class="range-actions"><button type="button" data-range-apply>应用区间${entry.inReport?'':'并加入报告'}</button><button type="button" data-range-cancel disabled>取消区间修改</button><button type="button" data-range-reset>恢复自动区间</button></div><details class="range-precision"><summary>精确起止</summary><div class="range-fields"><label>起点（秒）<input type="number" data-bound="start" step="0.005" min="0"></label><label>终点（秒）<input type="number" data-bound="end" step="0.005" min="0"></label></div></details><p class="range-error" role="status"></p>`;
  if(profile){host._reportDisplayProfile=profile;host.querySelector('header').insertAdjacentHTML('afterend','<div class="report-display-controls" aria-label="候选波形查看方式"><button type="button" data-display-leads="3" aria-pressed="true">3L · II / V1 / V5</button><button type="button" data-display-leads="12" aria-pressed="false">12L</button><button type="button" data-display-factor="0.5" aria-label="减小波形显示幅度">−</button><button type="button" data-display-factor="2" aria-label="增大波形显示幅度">＋</button><button type="button" data-display-fit>适应幅度</button><small data-display-units></small></div>');}
  if(fitToFrame)host.dataset.fitToFrame='true';else host.style.setProperty('--range-wave-height',(count*rowHeight+(profile?60:48))+'px');
  const stage=host.querySelector('.report-range-stage');if(host.dataset)host.dataset.waveColumns=String(columns);if(columns===2){for(const node of [...stage.querySelectorAll('.report-range-selection,[data-range-drag]')]){node.dataset.rangeColumn='0';const clone=node.cloneNode(true);clone.dataset.rangeColumn='1';stage.append(clone);}}let plotSize='';
  function resizePlot(){if(!current())return;
    const rect=stage.getBoundingClientRect();measureDisplay(rect.height);if(!fitToFrame)host.style.setProperty('--range-wave-height',(count*rowHeight+(profile?60:48))+'px');
    if(profile)host.querySelectorAll('[data-display-leads]').forEach(b=>b.setAttribute('aria-pressed',String(Number(b.dataset.displayLeads)===displayMode)));
    if(rect.width<=0||rect.height<=0)return;const size=rect.width+'|'+rect.height;if(size===plotSize)return;plotSize=size;stage.querySelector('svg').outerHTML=plot(rect.width,rect.height);
    if(profile){const actualGain=Number(stage.querySelector('svg').dataset.displayGain)||pixelGain;host.dataset.displayLeads=String(count);host.dataset.displayGain=String(actualGain);host.querySelector('[data-display-units]').textContent=`${fitToFrame?'显示 '+gainFactor+'× · ':''}${Number(actualGain.toPrecision(4))} px/u · 电压未校准`;}
    if(host._rangeReady)render();}
  // Resize only the retained source plot; drafts, handles and input focus stay alive.
  host._rangePlotObserver?.disconnect();
  if(typeof ResizeObserver!=='undefined'){const observer=new ResizeObserver(()=>{if(!host.isConnected){observer.disconnect();return;}resizePlot();});host._rangePlotObserver=observer;observer.observe(stage);}
  if(stage.getBoundingClientRect)resizePlot();
  if(profile){host.querySelectorAll('[data-display-leads]').forEach(b=>b.onclick=()=>{displayMode=Number(b.dataset.displayLeads);plotSize='';resizePlot();});host.querySelectorAll('[data-display-factor]').forEach(b=>b.onclick=()=>{gainFactor=Math.max(.125,Math.min(8,gainFactor*Number(b.dataset.displayFactor)));plotSize='';resizePlot();});host.querySelector('[data-display-fit]').onclick=()=>{gainFactor=1;plotSize='';resizePlot();};}
  const clamp=(x,min,max)=>Math.max(min,Math.min(max,Math.round(x*200)/200));
  function render(){if(!current())return;const left=(a-lo)/(hi-lo),right=(b-lo)/(hi-lo),w=stage.getBoundingClientRect?.().width||1000,gap=columns===2?24:0,panel=(w-gap)/columns;
    if(columns===1){host.querySelectorAll('[data-range-drag=start]').forEach(h=>h.style.left=left*100+'%');host.querySelectorAll('[data-range-drag=end]').forEach(h=>h.style.left=right*100+'%');const shade=host.querySelector('.report-range-selection');if(shade){shade.style.left=left*100+'%';shade.style.width=(right-left)*100+'%';}}
    else for(const node of stage.querySelectorAll('[data-range-drag],.report-range-selection')){const col=Number(node.dataset.rangeColumn)||0,origin=col*(panel+gap);node.style.left=(origin+(node.dataset.rangeDrag==='end'?right:left)*panel)+'px';if(node.classList.contains('report-range-selection'))node.style.width=((right-left)*panel)+'px';}
    host.querySelector('[data-bound=start]').value=a.toFixed(3);host.querySelector('[data-bound=end]').value=b.toFixed(3);const changed=Math.abs(a-entry.strip.start_s)>.001||Math.abs(b-entry.strip.end_s)>.001,count=(a<lo||b>hi)?(options.rangeEvidence&&Math.abs(options.rangeEvidence.start-a)<.001&&Math.abs(options.rangeEvidence.end-b)<.001?options.rangeEvidence.count:!changed?entry.strip.visible_beat_count:null):(wave.beats||[]).filter(r=>!['X','O','Y','T'].includes(r.class_code)&&r.sample_index/(wave.sample_rate_hz||200)>=a&&r.sample_index/(wave.sample_rate_hz||200)<b).length;if(host.dataset)host.dataset.rangeVisible=String(a<hi&&b>lo);options.onRangeChange?.({start:a,end:b,count,changed,inReport:entry.inReport});host.querySelector('[data-range-cancel]').disabled=busy||!changed;if(host.dataset)host.dataset.rangeStatus=changed?'pending':entry.inReport?'applied':'candidate';host.querySelector('output').innerHTML=`<span data-range-current-status><strong>${changed?'待应用区间':options.candidateOnly?'候选区间（是否入报请见报告编排）':entry.inReport?'当前已应用区间':'候选区间（尚未入报）'}</strong> ${stamp(a)} — ${stamp(b)} · ${(b-a).toFixed(3)} 秒 · ${count==null?'搏数待核对':count+' 搏'}${changed?' · 当前窗口暂存':''}</span>${changed?`<span data-range-applied-status><strong>${options.candidateOnly?'原候选区间':'当前已应用区间'}</strong> ${options.candidateOnly||entry.inReport?stamp(entry.strip.start_s)+' — '+stamp(entry.strip.end_s):'此事件尚未入报'}</span>`:''}`;}
  host._rangeDisplayState=()=>({mode:displayMode,gain:gainFactor});host._rangeChooseRange=range=>{if(busy||!current())return false;a=clamp(range.range_start_s,lo,hi-1);b=clamp(range.range_end_s,a+1,Math.min(hi,a+120));render();remember();return true;};host._rangeRead=()=>({start:a,end:b});
  host._rangeEventId=key;host._rangeSetMembership=inReport=>{if(!current())return;entry.inReport=inReport;host.querySelector('[data-range-apply]').textContent='应用区间'+(inReport?'':'并加入报告');render();remember();};
  listen('pointerdown',e=>{if(busy||e.button!==0||!current())return;const target=e.target.closest('[data-range-drag]'),surface=e.target.closest('.report-range-stage');if(!target&&!surface)return;if(!target&&e.target.closest('button,input,select,textarea'))return;const box=stage.getBoundingClientRect();if(box.width<=0)return;e.preventDefault();e.stopPropagation();const panel=(box.width-(columns===2?24:0))/columns,col=target?Number(target.dataset.rangeColumn)||0:Math.min(columns-1,Math.floor((e.clientX-box.left)/(panel+24)));drag={id:e.pointerId,kind:target?.dataset.rangeDrag||'select',a,b,x:e.clientX,left:box.left+col*(panel+24),width:panel,moved:false};if(target)target.setPointerCapture(e.pointerId)});
  listen('pointermove',e=>{if(!drag||drag.id!==e.pointerId||!current())return;const delta=(e.clientX-drag.x)/drag.width*(hi-lo);if(drag.kind==='select'){if(!drag.moved&&Math.abs(e.clientX-drag.x)<5)return;if(!drag.moved)stage.setPointerCapture(e.pointerId);drag.moved=true;const origin=clamp(lo+(drag.x-drag.left)/drag.width*(hi-lo),lo,hi-1),point=clamp(lo+(e.clientX-drag.left)/drag.width*(hi-lo),lo,hi);a=clamp(Math.min(origin,point),lo,hi-1);b=clamp(Math.max(origin,point),a+1,Math.min(hi,a+120));}else if(drag.kind==='start')a=clamp(drag.a+delta,Math.max(lo,b-120),b-1);else if(drag.kind==='end')b=clamp(drag.b+delta,a+1,Math.min(hi,a+120));render();remember()});
  listen('pointerup',()=>{drag=null});listen('lostpointercapture',()=>{drag=null});
  listen('pointercancel',()=>{if(drag){a=drag.a;b=drag.b;drag=null;render();remember();}});
  listen('keydown',e=>{const h=e.target.closest('[data-range-drag]');if(busy||!current()||!h||!['ArrowLeft','ArrowRight'].includes(e.key))return;e.preventDefault();e.stopPropagation();const d=(e.key==='ArrowLeft'?-1:1)*(e.shiftKey?.5:.005);if(h.dataset.rangeDrag==='start')a=clamp(a+d,Math.max(lo,b-120),b-1);else b=clamp(b+d,a+1,Math.min(hi,a+120));render();remember()});
  host.querySelectorAll('[data-bound]').forEach(input=>input.onchange=()=>{if(busy||!current())return;const x=input.value===''?NaN:Number(input.value);if(Number.isFinite(x)){if(input.dataset.bound==='start')a=clamp(x,Math.max(lo,b-120),b-1);else b=clamp(x,a+1,Math.min(hi,a+120))}render();remember()});
  // Reconcile numeric drafts on blur as well as change (including autofill).
  host.querySelectorAll('[data-bound]').forEach(input=>input.addEventListener('blur',()=>input.onchange()));
  async function commit(reset){if(busy||!current())return;busy=true;const error=host.querySelector('.range-error');error.textContent='正在校验区间与心搏数…';host.querySelectorAll('button,input').forEach(x=>x.disabled=true);const saved=key&&drafts.get(key);try{await(reset?onReset():onApply({range_start_s:a,range_end_s:b}));if(current()){error.textContent='';if(drafts.get(key)===saved)forget(key);}return true;}catch(e){if(current())error.textContent=e.message;return false;}finally{busy=false;if(current()){host.querySelectorAll('button,input').forEach(x=>x.disabled=false);render();}}}
  function cancel(){if(busy||!current())return;a=entry.strip.start_s;b=entry.strip.end_s;drag=null;host.querySelector('.range-error').textContent='';render();remember();}host.querySelector('[data-range-cancel]').onclick=cancel;host.querySelector('[data-range-reset]').title='重新校验自动 7 秒 / 至少 5 个可用心搏；不改诊断确认';
  host.querySelector('[data-range-apply]').onclick=()=>commit(false);host.querySelector('[data-range-reset]').onclick=()=>commit(true);host._rangeReady=true;render();if(restored)remember();
 }
 globalThis.ECGReportRange={mount,setContext,pending,clear,forget,assertApplied,resolveLeave,formatTime:stamp};
})();
