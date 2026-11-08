"use strict";
/* Read-only source rendering: channel arrays stay bound to their names. */
globalThis.ECGChartInspection = (() => {
  const order = Object.freeze(['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6']);
  const names = leads => [...order.filter(name => Object.prototype.hasOwnProperty.call(leads || {}, name)), ...Object.keys(leads || {}).filter(name => !order.includes(name))];
  const entries = leads => names(leads).map(name => [name, leads[name]]);
  // Expanded details are chart containers; only their summary is a control.
  const interactive = target => target?.closest?.('button,a,input,select,textarea,label,summary,[contenteditable="true"]');
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
    const limit=Number(node.dataset.inspectLimit),duration=Number(node.dataset.inspectDuration),start=Number(node.dataset.inspectStart)||0;
    const metric=node.dataset.inspectMetric||'趋势',unit=node.dataset.inspectUnit||'设备单位',bin=Number(node.dataset.inspectBinSeconds);
    const interval=Number.isFinite(bin)&&bin>0?(bin>=60&&bin%60===0?`${bin/60}分钟`:`${bin}秒`):'';
    add('text',{x:l,y:17,fill:'#3c525f','font-size':13},[metric,unit,interval].filter(Boolean).join(' · '));
    for(const [fraction,value] of [[2/16,limit],[8/16,0],[14/16,-limit]]){
      const y=t+h*fraction;
      add('line',{x1:l,y1:y,x2:l+w,y2:y,stroke:'#d9e3e8','stroke-width':1});
      add('text',{x:l-8,y:y+4,'text-anchor':'end',fill:'#3c525f','font-size':13},Number(value.toFixed(1)).toString());
    }
    const ticks=Math.max(2,Math.min(6,Math.floor(w/150)));
    for(let i=0;i<=ticks;i++){
      const x=l+w*i/ticks,seconds=Math.round(start+duration*i/ticks),hh=Math.floor(seconds/3600),mm=Math.floor(seconds%3600/60),ss=seconds%60;
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
  let renderers = new WeakMap(), rendererLayouts = new WeakMap();
  const maximumBackingPixels=16_000_000, maximumBackingEdge=16_384;
  function renderingDpr(width,height) {
    const raw=Number(window.devicePixelRatio),requested=Number.isFinite(raw)&&raw>0?Math.min(raw,2):1;
    const fits=dpr=>Math.round(width*dpr)<=maximumBackingEdge&&Math.round(height*dpr)<=maximumBackingEdge&&Math.max(1,Math.round(width*dpr))*Math.max(1,Math.round(height*dpr))<=maximumBackingPixels;
    if(fits(requested))return requested;
    // Preserve logical dimensions and every source value; limit the new raster
    // allocation rather than stretching a previous bitmap or changing axes.
    let low=0,high=requested;
    for(let i=0;i<32;i++){const middle=(low+high)/2;if(fits(middle))low=middle;else high=middle;}
    return low;
  }
  function suspendManagedSurface(node) {
    if (!node?._inspectionManaged) return;
    node._inspectionCurrent = () => false;
    node._inspectionOpen = null;
    for (const [name, previous] of Object.entries(node._inspectionOriginalAttributes || {})) {
      if (previous === null) node.removeAttribute(name); else node.setAttribute(name, previous);
    }
    if (node._inspectionAddedTabindex && !node._selectionReady) node.removeAttribute('tabindex');
  }
  function unregisterRenderer(node) {
    if (!node) return;
    renderers.delete(node); rendererLayouts.delete(node);
    node.removeAttribute?.('data-inspection-source');
    suspendManagedSurface(node);
    globalThis.ecgChartInspection?.sourceChanged(node);
  }
  function clearRenderers() {
    const nodes = typeof document === 'undefined' ? [] : document.querySelectorAll('[data-inspection-source]');
    for (const node of nodes) {node.removeAttribute('data-inspection-source');suspendManagedSurface(node);}
    renderers = new WeakMap(); rendererLayouts = new WeakMap();
    globalThis.ecgChartInspection?.invalidate();
  }
  function registerRenderer(node, render, layout = null) {
    if (!node || typeof render !== 'function') return;
    if (layout !== null) {
      const margins = layout.margins;
      if (!Number.isFinite(layout.plotAspectRatio) || layout.plotAspectRatio <= 0 || !margins
        || !['l','r','t','b'].every(key => Number.isFinite(margins[key]) && margins[key] >= 0)) throw TypeError('图形坐标比例无效');
      layout = Object.freeze({plotAspectRatio:layout.plotAspectRatio,margins:Object.freeze({...margins})});
    }
    renderers.set(node, render);
    if (layout) rendererLayouts.set(node, layout); else rendererLayouts.delete(node);
    node.setAttribute?.('data-inspection-source','');
    // A repaint represents a new source/view snapshot, including selection.
    globalThis.ecgChartInspection?.sourceChanged(node);
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
    let renderer = null, layout = null;
    let source = null, opener = null, scope = null, base = null, frame = 0, restore = true,pan=null;
    function current() { return source?.isConnected && getScope() === scope && (!renderer || renderers.get(source) === renderer) && source.getBoundingClientRect().width > 0; }
    function close(returnFocus = true) {
      restore = returnFocus && current();
      if (dialog.open) dialog.close(); else cleanup();
    }
    function cleanup() {
      const target = restore ? opener : null;
      pan=null;scroll.classList.remove('panning');
      holder.replaceChildren(); renderer = layout = null; source = opener = scope = base = null;
      if (target?.isConnected && !target.disabled) target.focus({preventScroll:true});
    }
    function resizeCopy() {
      if (!base) return;
      if (!current()) {close(false); return;}
      const factor = Number(scale.value);
      const copy = holder.firstElementChild;
      if (!copy) {close(false);return false;}
      const width = Math.round(base.width * factor), margins = layout?.margins;
      const height = layout ? Math.round(Math.max(1,width-margins.l-margins.r)/layout.plotAspectRatio+margins.t+margins.b) : Math.round(base.height * factor);
      holder.style.width = `${width}px`; holder.style.height = `${height}px`;
      copy.style.width = `${width}px`; copy.style.height = `${height}px`;
      if (renderer) {
        // Never stretch old pixels: rerun the original data renderer for this geometry.
        const dpr=renderingDpr(width,height);
        try {
          renderer(copy, {width, height, dpr, readOnly:true});
          if(copy.width!==Math.round(width*dpr)||copy.height!==Math.round(height*dpr))throw Error('图形重绘尺寸与当前坐标不一致');
          copy.dataset.inspectionDpr=String(dpr);
        }
        catch (_) {unregisterRenderer(source);close(false);return false;}
      }
      return true;
    }
    function open(node, button, title) {
      if (!node?.isConnected || !node.getBoundingClientRect().width || dialog.open) return false;
      if (document.querySelector('dialog[open]')) return false;
      const isCanvas = node.tagName.toLowerCase() === 'canvas';
      if (isCanvas && !renderers.has(node)) return false;
      const box = node.getBoundingClientRect();
      source = node; opener = button; scope = getScope(); restore = true;
      let copy;
      if (isCanvas) {
        renderer = renderers.get(node);
        layout = rendererLayouts.get(node) || null;
        copy = document.createElement('canvas');
      } else {copy = node.cloneNode(true);copyPaint(node,copy);}
      for (const item of [copy, ...copy.querySelectorAll('*')]) {
        item.removeAttribute('id'); item.removeAttribute('tabindex'); item.removeAttribute('data-inspect-chart');
        item.removeAttribute('data-inspect-title'); item.removeAttribute('aria-hidden');
      }
      const fitLabel=layout?'适应窗口':'适应宽度';
      dialog.querySelector('[data-inspection-fit]').textContent=fitLabel;
      dialog.querySelector('.chart-inspection-toolbar span').textContent=fitLabel+'为100%；拖动或滚动查看，Esc 返回。波形放大不代表电压校准。';
      dialog.querySelector('h2').textContent = title;
      dialog.querySelector('header p').textContent = node.dataset?.inspectNote || (isCanvas ? '只读数据重绘；时间、单位与所选时段沿用原图，放大不增加采样信息。' : '只读矢量查看；时间、单位与所选时段沿用原图。');
      holder.replaceChildren();dialog.showModal();
      const width=Math.max(240,scroll.clientWidth||box.width),trend=node.dataset?.inspectKind==='st-trend';
      base={width,height:(trend||isCanvas)?Math.max(280,Math.min(540,scroll.clientHeight*.8)):width*box.height/box.width};
      if(layout){
        const m=layout.margins,availableWidth=Math.max(1,scroll.clientWidth||box.width),plotWidth=Math.max(1,Math.min(availableWidth-m.l-m.r,(Math.max(1,scroll.clientHeight)-m.t-m.b)*layout.plotAspectRatio));
        base={width:Math.floor(plotWidth+m.l+m.r),height:Math.floor(plotWidth/layout.plotAspectRatio+m.t+m.b)};
      }
      if(trend)copy=trendFrame(copy,node,base.width,base.height);
      copy.setAttribute('role','img');copy.setAttribute('aria-label',title);
      // Fresh canvases have no source IDs, handlers or editing attributes.
      copy.style.display='block';copy.style.maxWidth='none';copy.style.maxHeight='none';copy.style.position='static';copy.style.inset='auto';
      holder.replaceChildren(copy);scale.value='1';if(!resizeCopy())return false;scroll.scrollLeft=scroll.scrollTop=0;
      dialog.querySelector('[data-inspection-close]').focus();
      return true;
    }
    function scan() {
      frame = 0;
      if (dialog.open && !current()) close(false);
      const nodes = [...Object.keys(registry).map(id => document.getElementById(id)), ...document.querySelectorAll('[data-inspect-chart]')].filter(Boolean);
      for (const node of nodes) {
        if (node.closest('#chartInspectionDialog') || (node._inspectionReady && !node._inspectionManaged)) continue;
        if (node.tagName.toLowerCase() === 'canvas' && !renderers.has(node)) {suspendManagedSurface(node);continue;}
        const title = node.dataset.inspectTitle || registry[node.id] || node.getAttribute('aria-label') || '图形';
        if (!node._inspectionManaged) {
          node._inspectionManaged=true;
          node._inspectionOriginalAttributes=Object.fromEntries(['aria-keyshortcuts','aria-haspopup','title'].map(name=>[name,node.getAttribute(name)]));
          node._inspectionAddedTabindex=!node.hasAttribute('tabindex');
        }
        bindSurface(node,()=>open(node,node,title),{title,isCurrent:()=>node.isConnected && (node.tagName.toLowerCase() !== 'canvas' || renderers.has(node))});
      }
    }
    function schedule() { if (!frame) frame = requestAnimationFrame(scan); }
    const observer = new MutationObserver(records => {
      if (dialog.open && records.some(r => (r.target === source || source?.contains(r.target)) && !dialog.contains(r.target))) close(false);
      if (records.some(r => !dialog.contains(r.target))) schedule();
    });
    observer.observe(document.getElementById('mainContent'), {childList:true,subtree:true,attributes:true,attributeFilter:['width','height','class','hidden','style','data-state','d','points','viewBox','transform','data-inspect-metric','data-inspect-unit','data-inspect-start','data-inspect-limit','data-inspect-duration','data-inspect-bin-seconds']});
    dialog.addEventListener('cancel', event => {event.preventDefault(); close();});
    dialog.addEventListener('close', cleanup);
    dialog.addEventListener('keydown', event => event.stopPropagation());
    dialog.querySelector('[data-inspection-close]').onclick = () => close(); scale.onchange = resizeCopy;
    dialog.querySelector('[data-inspection-fit]').onclick=()=>{scale.value='1';resizeCopy();scroll.scrollLeft=scroll.scrollTop=0;};
    scroll.addEventListener('pointerdown',event=>{if(event.button!==0||event.pointerType==='touch')return;pan={id:event.pointerId,x:event.clientX,y:event.clientY,left:scroll.scrollLeft,top:scroll.scrollTop};scroll.setPointerCapture(event.pointerId);scroll.classList.add('panning');event.preventDefault();});
    scroll.addEventListener('pointermove',event=>{if(pan?.id!==event.pointerId)return;scroll.scrollLeft=pan.left+pan.x-event.clientX;scroll.scrollTop=pan.top+pan.y-event.clientY;});
    const endPan=()=>{pan=null;scroll.classList.remove('panning');};scroll.addEventListener('pointerup',endPan);scroll.addEventListener('pointercancel',endPan);
    window.addEventListener('resize',()=>close(false));
    const controller = {invalidate:()=>close(false), sourceChanged:node=>{if(source===node)close(false);schedule();}, open, scan}; dialog._controller = controller;
    scan(); return controller;
  }
  return Object.freeze({order,names,entries,mount,bindSurface,bindSelection,registerRenderer,unregisterRenderer,clearRenderers});
})();
if (typeof module !== 'undefined' && module.exports) module.exports=globalThis.ECGChartInspection;
