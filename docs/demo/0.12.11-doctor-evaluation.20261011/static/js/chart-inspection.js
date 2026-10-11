"use strict";
/* Presentation only: channel arrays stay bound to their names; snapshots never edit evidence. */
globalThis.ECGChartInspection = (() => {
  const order = Object.freeze(['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6']);
  const names = leads => [...order.filter(name => Object.prototype.hasOwnProperty.call(leads || {}, name)), ...Object.keys(leads || {}).filter(name => !order.includes(name))];
  const entries = leads => names(leads).map(name => [name, leads[name]]);
  const interactive = target => target?.closest?.('button,a,input,select,textarea,label,details,summary,[contenteditable="true"]');
  // Optional read-only viewing uses the keyboard; pointer positioning and
  // selection retain their original immediate event order.
  function bindSurface(node, open, {isCurrent=()=>true,title='图形'}={}) {
    node.setAttribute('data-gesture-surface','');
    if(!node.hasAttribute('tabindex'))node.setAttribute('tabindex','0');
    node.setAttribute('aria-keyshortcuts','Shift+Enter');node.setAttribute('aria-haspopup','dialog');
    node.setAttribute('title',`${title}：Shift+Enter 查看大图；Esc 返回`);
    node._inspectionOpen=open;node._inspectionCurrent=isCurrent;
    if(node._inspectionReady)return;
    node._inspectionReady=true;
    node.addEventListener('keydown',event=>{
      if(event.key!=='Enter'||!event.shiftKey||interactive(event.target)||!node._inspectionCurrent())return;
      event.preventDefault();event.stopImmediatePropagation();node._inspectionOpen?.();
    },true);
  }
  function bindSelection(node, action, {isCurrent=()=>true}={}) {
    node.setAttribute('data-gesture-surface','');
    node._selectionAction=action;node._selectionCurrent=isCurrent;
    if(node._selectionReady)return;node._selectionReady=true;
    let point=null;
    node.addEventListener('pointerdown',event=>{point=event.button===0?{x:event.clientX,y:event.clientY,moved:false}:null;});
    node.addEventListener('pointermove',event=>{if(point&&Math.hypot(event.clientX-point.x,event.clientY-point.y)>5)point.moved=true;});
    node.addEventListener('pointercancel',()=>{point=null;});
    node.addEventListener('click',event=>{
      if(interactive(event.target)||event.button!==0||point?.moved||globalThis.getSelection?.()?.toString())return;
      if(node.isConnected&&node._selectionCurrent())node._selectionAction();
    });
    node.addEventListener('keydown',event=>{
      if(event.target!==node||event.shiftKey||![' ','Enter'].includes(event.key))return;
      event.preventDefault();event.stopPropagation();
      if(node._selectionCurrent())node._selectionAction();
    });
  }
  const paint=['fill','fill-opacity','stroke','stroke-width','stroke-opacity','stroke-dasharray','stroke-linecap','stroke-linejoin','vector-effect','font-family','font-size','font-weight','text-anchor','opacity','color'];
  function copyPaint(node,copy){
    const targets=[copy,...copy.querySelectorAll('*')];
    for(const [i,item] of [node,...node.querySelectorAll('*')].entries()){
      const target=targets[i],style=getComputedStyle(item);
      for(const name of paint)target.style.setProperty(name,style.getPropertyValue(name));
    }
  }
  function trendFrame(copy,node,width,height){
    const ns='http://www.w3.org/2000/svg',outer=document.createElementNS(ns,'svg'),l=72,t=28,w=width-96,h=height-80;
    outer.setAttribute('viewBox',`0 0 ${width} ${height}`);
    function add(tag,attrs,text){const el=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))el.setAttribute(k,String(v));if(text!==undefined)el.textContent=text;outer.append(el);return el;}
    const limit=Number(node.dataset.inspectLimit),duration=Number(node.dataset.inspectDuration);
    add('text',{x:l,y:17,fill:'#3c525f','font-size':13},'ST · 设备单位（16秒块，J+60ms）');
    for(const [fraction,value] of [[2/16,limit],[8/16,0],[14/16,-limit]]){
      const y=t+h*fraction;
      add('line',{x1:l,y1:y,x2:l+w,y2:y,stroke:'#d9e3e8','stroke-width':1});
      add('text',{x:l-8,y:y+4,'text-anchor':'end',fill:'#3c525f','font-size':13},Number(value.toFixed(1)).toString());
    }
    const ticks=Math.max(2,Math.min(6,Math.floor(w/150)));
    for(let i=0;i<=ticks;i++){
      const x=l+w*i/ticks,seconds=Math.round(duration*i/ticks),hh=Math.floor(seconds/3600),mm=Math.floor(seconds%3600/60),ss=seconds%60;
      const label=[hh,mm,ss].map(v=>String(v).padStart(2,'0')).join(':');
      add('line',{x1:x,y1:t,x2:x,y2:t+h,stroke:'#e6edf0','stroke-width':1});
      add('text',{x,y:height-30,'text-anchor':i===0?'start':i===ticks?'end':'middle',fill:'#3c525f','font-size':13},label);
    }
    add('text',{x:l+w/2,y:height-8,'text-anchor':'middle',fill:'#3c525f','font-size':13},'记录后时间 · 时:分:秒');
    // Same points and same 0..100 × 0..16 mapping; only the viewport grows.
    copy.setAttribute('x',l);copy.setAttribute('y',t);copy.setAttribute('width',w);copy.setAttribute('height',h);
    for(const line of copy.querySelectorAll('line')){line.style.setProperty('vector-effect','non-scaling-stroke');line.style.setProperty('stroke-width','1px');}
    copy.style.width='';copy.style.height='';copy.style.position='static';copy.style.inset='auto';copy.style.background='transparent';
    outer.append(copy);return outer;
  }
  const registry = {
    ovHistogram:'全程 RR 直方图', ovFullHR:'全程心率趋势', ovHourHR:'小时心率趋势',
    ovFullRR:'全程 RR 散点', ovHourRR:'小时 RR 散点', ovAFFull:'房颤复核全程 RR',
    ovAFLorenz:'房颤复核相邻 RR', ovQuarter0:'15 分钟 RR · 1', ovQuarter1:'15 分钟 RR · 2',
    ovQuarter2:'15 分钟 RR · 3', ovQuarter3:'15 分钟 RR · 4', scatterCanvas:'相邻 RR 散点',
    editScatterCanvas:'模板类别散点', editTrendCanvas:'模板全天心率', editHistogramCanvas:'模板 RR 分布',
    editDensityPrimary:'左上导联密度', editDensitySelection:'左下导联密度',
    editLibraryHistogramCanvas:'逐搏库 RR 分布', editLibraryTrendCanvas:'逐搏库心率',
    editLibraryScatterCanvas:'逐搏库相邻 RR', editLibraryDensityPrimary:'逐搏库全类密度',
    editLibraryDensitySelection:'逐搏库所选密度', sttOverviewCanvas:'ST-T 全天定位',
    trendCanvas:'全天心率趋势',
    histogramCanvas:'NN 间期分布', poincareCanvas:'相邻 NN 间期'
  };
  function mount({getScope = () => ''} = {}) {
    const existing = document.getElementById('chartInspectionDialog');
    if (existing) return existing._controller;
    const dialog = document.createElement('dialog');
    dialog.id = 'chartInspectionDialog'; dialog.className = 'chart-inspection-dialog';
    dialog.setAttribute('aria-labelledby', 'chartInspectionTitle');
    dialog.innerHTML = `<header><div><h2 id="chartInspectionTitle">图形放大查看</h2><p>只读查看；时间、单位与所选时段沿用原图。</p></div><button type="button" data-inspection-close>返回原图</button></header><div class="chart-inspection-toolbar"><button type="button" data-inspection-fit>适应宽度</button><label>显示比例 <select aria-label="图形显示放大"><option value="1" selected>100%</option><option value="1.5">150%</option><option value="2">200%</option><option value="3">300%</option></select></label><span>适应宽度为100%；拖动或滚动查看，Esc 返回。波形放大不代表电压校准。</span></div><div class="chart-inspection-scroll" tabindex="0" role="region" aria-label="放大图形，可拖动或滚动"><div class="chart-inspection-copy"></div></div>`;
    document.body.append(dialog);
    const holder = dialog.querySelector('.chart-inspection-copy'), scale = dialog.querySelector('select'),scroll=dialog.querySelector('.chart-inspection-scroll');
    let source = null, opener = null, scope = null, base = null, frame = 0, restore = true,pan=null;
    function current() { return source?.isConnected && getScope() === scope && source.getBoundingClientRect().width > 0; }
    function close(returnFocus = true) {
      restore = returnFocus && current();
      if (dialog.open) dialog.close(); else cleanup();
    }
    function cleanup() {
      const target = restore ? opener : null;
      pan=null;scroll.classList.remove('panning');
      holder.replaceChildren(); source = opener = scope = base = null;
      if (target?.isConnected && !target.disabled) target.focus({preventScroll:true});
    }
    function resizeCopy() {
      if (!base) return;
      const factor = Number(scale.value);
      holder.style.width = `${base.width * factor}px`; holder.style.height = `${base.height * factor}px`;
      const copy = holder.firstElementChild;
      copy.style.width = `${base.width * factor}px`; copy.style.height = `${base.height * factor}px`;
    }
    function open(node, button, title) {
      if (!node?.isConnected || !node.getBoundingClientRect().width || dialog.open) return false;
      if (document.querySelector('dialog[open]')) return false;
      const box = node.getBoundingClientRect();
      source = node; opener = button; scope = getScope(); restore = true;
      let copy;
      if (node.tagName.toLowerCase() === 'canvas') {
        copy = document.createElement('canvas'); copy.width = node.width; copy.height = node.height;
        copy.getContext('2d').drawImage(node, 0, 0);
      } else {copy = node.cloneNode(true);copyPaint(node,copy);}
      for (const item of [copy, ...copy.querySelectorAll('*')]) {
        item.removeAttribute('id'); item.removeAttribute('tabindex'); item.removeAttribute('data-inspect-chart');
        item.removeAttribute('data-inspect-title'); item.removeAttribute('aria-hidden');
      }
      dialog.querySelector('h2').textContent = title;
      dialog.querySelector('header p').textContent = node.dataset?.inspectNote || node.getAttribute('aria-description') || '只读等比例放大；时间、单位与所选时段沿用原图。';
      holder.replaceChildren();dialog.showModal();
      const width=Math.max(240,scroll.clientWidth||box.width),trend=node.dataset?.inspectKind==='st-trend';
      base={width,height:trend?Math.max(300,Math.min(460,scroll.clientHeight*.8)):width*box.height/box.width};
      if(trend)copy=trendFrame(copy,node,base.width,base.height);
      copy.setAttribute('role','img');copy.setAttribute('aria-label',title);
      // Canvas keeps its pixel array/aspect ratio; SVG retains every source point.
      copy.style.display='block';copy.style.maxWidth='none';copy.style.maxHeight='none';copy.style.position='static';copy.style.inset='auto';
      holder.replaceChildren(copy);scale.value='1';resizeCopy();scroll.scrollLeft=scroll.scrollTop=0;
      dialog.querySelector('[data-inspection-close]').focus();
      return true;
    }
    function scan() {
      frame = 0;
      if (dialog.open && !current()) close(false);
      const nodes = [...Object.keys(registry).map(id => document.getElementById(id)), ...document.querySelectorAll('[data-inspect-chart]')].filter(Boolean);
      for (const node of nodes) {
        if (node.closest('#chartInspectionDialog') || node._inspectionReady) continue;
        const title = node.dataset.inspectTitle || registry[node.id] || node.getAttribute('aria-label') || '图形';
        bindSurface(node,()=>open(node,node,title),{title});
      }
    }
    function schedule() { if (!frame) frame = requestAnimationFrame(scan); }
    const observer = new MutationObserver(records => {
      if (dialog.open && records.some(r => (r.target === source || source?.contains(r.target)) && !dialog.contains(r.target))) close(false);
      if (records.some(r => !dialog.contains(r.target))) schedule();
    });
    observer.observe(document.getElementById('mainContent'), {childList:true,subtree:true,attributes:true,attributeFilter:['width','height','class','hidden','data-state']});
    dialog.addEventListener('cancel', event => {event.preventDefault(); close();});
    dialog.addEventListener('close', cleanup);
    dialog.addEventListener('keydown', event => event.stopPropagation());
    dialog.querySelector('[data-inspection-close]').onclick = () => close(); scale.onchange = resizeCopy;
    dialog.querySelector('[data-inspection-fit]').onclick=()=>{scale.value='1';resizeCopy();scroll.scrollLeft=scroll.scrollTop=0;};
    scroll.addEventListener('pointerdown',event=>{if(event.button!==0||event.pointerType==='touch')return;pan={id:event.pointerId,x:event.clientX,y:event.clientY,left:scroll.scrollLeft,top:scroll.scrollTop};scroll.setPointerCapture(event.pointerId);scroll.classList.add('panning');event.preventDefault();});
    scroll.addEventListener('pointermove',event=>{if(pan?.id!==event.pointerId)return;scroll.scrollLeft=pan.left+pan.x-event.clientX;scroll.scrollTop=pan.top+pan.y-event.clientY;});
    const endPan=()=>{pan=null;scroll.classList.remove('panning');};scroll.addEventListener('pointerup',endPan);scroll.addEventListener('pointercancel',endPan);
    window.addEventListener('resize',()=>close(false));
    const controller = {invalidate:()=>close(false), open, scan}; dialog._controller = controller;
    scan(); return controller;
  }
  return Object.freeze({order,names,entries,mount,bindSurface,bindSelection});
})();
if (typeof module !== 'undefined' && module.exports) module.exports=globalThis.ECGChartInspection;
