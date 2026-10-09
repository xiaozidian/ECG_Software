"use strict";
/* Layout owns slots; clinical collections and explicit write guards retain ownership. */
const desktopWorkspace=(()=>{
  const q=s=>document.querySelector(s),esc=escapeHtml;
  const cache=new Map();let deckKey='',deckToken=0,controller=null,frame=0,evidence=null;
  const views=new Map(),fields=['editStart','editDuration','editLead','editSelectedClass','editLibraryFilter','editSelectionAnchor','editSelectedSample','editEditingTemplateId'];
  let viewScope='',switchToken=0;
  const originalSetMode=setEditMode;
  const identity=()=>JSON.stringify([state.caseData?.analysis_revision,state.editReadIdentity?.analysis_basis||'']);
  function syncCase(){
    const next=JSON.stringify([state.caseId,state.caseRequestId]);
    if(next===viewScope)return;
    viewScope=next;switchToken++;views.clear();if(q('#morphSlot6'))morphologyWorkbench.resetView();
  }
  function captureView(){
    return {identity:identity(),fields:Object.fromEntries(fields.map(k=>[k,state[k]])),selected:[...state.editSelectedSamples],clinical:clinicalUI.captureEditView(),morph:morphologyWorkbench.captureView(),scroll:document.scrollingElement.scrollTop};
  }
  function switchMode(mode,rerender=true){
    mode=mode==='library'?'library':'cluster';syncCase();
    if(mode===state.editMode||state.currentPage!=='edit'||!state.caseId){originalSetMode(mode,rerender);schedule();return;}
    if(!morphologyWorkbench.canSwitch()){toast('正在保存模板，请等待保存结果');return;}
    views.set(state.editMode,captureView());
    globalThis.ecgChartInspection?.invalidate();
    const mark=views.get(mode),same=mark?.identity===identity(),scope=viewScope,token=++switchToken;
    if(mark){for(const k of fields)state[k]=mark.fields[k];}
    if(state.editSelectedClass?.startsWith('custom-')&&!state.editTemplates.some(t=>'custom-'+t.id===state.editSelectedClass))state.editSelectedClass='source-N';
    state.editSelectedSamples=new Set(same?mark.selected:[]);
    if(!same){state.editSelectionAnchor=null;state.editSelectedSample=null;}
    originalSetMode(mode,false);arrange();
    const selectedClass=state.editSelectedClass;
    const valid=()=>token===switchToken&&scope===JSON.stringify([state.caseId,state.caseRequestId])&&state.currentPage==='edit'&&state.editMode===mode&&state.editSelectedClass===selectedClass;
    const loading=clinicalUI.activateEditView(mark?.clinical,valid);
    loadEditWaveform().catch(handleError);
    loading.then(async()=>{
      if(!valid())return;
      if(mode==='cluster')await morphologyWorkbench.restoreView(same?mark?.morph:null,valid);
      if(!valid())return;
      renderEditClasses();renderEditOverview();renderEditScatter();clinicalUI.renderOccurrences();
      if(mode==='library')renderLibrary();else renderEditWaveform();
      arrange();document.scrollingElement.scrollTop=mark?.scroll||0;
    }).catch(handleError);
  }
  function receiveEvidence(value){
    evidence={id:state.caseId,caseToken:state.caseRequestId,analysis_basis:value.analysis_basis,analysis_revision:value.analysis_revision,data_version:value.data_version};
    state.editReadIdentity={...evidence};
    if(state.currentPage==='edit')morphologyWorkbench.refresh();
  }
  function descriptors(){
    if(state.editTemplates.length)return state.editTemplates.map(t=>({key:'custom-'+t.id,name:t.name,kind:'template',count:t.sample_indices.length,id:t.id}));
    return EDIT_SOURCE_CLASSES.map(t=>({key:t.key,name:t.code+' · 分类预览',kind:'class',code:t.code,count:Number(state.caseData?.calculated?.group_counts?.[String(t.group)]||0)}));
  }
  function renderDeck(){
    const host=q('#editLibraryDeck');if(!host||state.currentPage!=='edit'||state.editMode!=='library')return;
    const id=state.caseId,caseToken=state.caseRequestId,revision=state.caseData?.analysis_revision,leadNames=ECGOccurrenceCard.leads(state.editLead,2),items=descriptors();
    if(evidence?.id!==id||evidence.caseToken!==caseToken){host.textContent='正在读取模板集合与当前病例依据…';q('#editLibraryDeckCount').textContent='读取中';return;}
    const basis={...evidence};
    const key=JSON.stringify([id,caseToken,revision,basis.analysis_revision,basis.analysis_basis,basis.data_version,leadNames,items.map(t=>[t.key,t.count])]);
    q('#editLibraryDeckCount').textContent=state.editTemplates.length?state.editTemplates.length+' 个形态模板':'尚无形态模板 · 下方为分类预览';
    if(key===deckKey){host.querySelectorAll('[data-edit-class]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.editClass===state.editSelectedClass)));return;}
    deckKey=key;host.dataset.failed='false';const token=++deckToken;controller?.abort();controller=new AbortController();const signal=controller.signal;
    host.innerHTML=items.map(t=>`<button type="button" class="workspace-master-card" data-edit-class="${esc(t.key)}" data-master-kind="${t.kind}" aria-pressed="${t.key===state.editSelectedClass}" title="${esc(t.name)} · ${fmtNumber(t.count)} 搏 · ${t.kind==='class'?'分类集合，未推断形态模板':'医生保存的完整成员集合'}"><header><strong>${esc(t.name)}</strong><span>${fmtNumber(t.count)} 搏</span></header><div class="workspace-master-wave">${t.count?'读取代表波形…':'该分类没有心搏'}</div><footer>${t.kind==='class'?'分类代表搏 · 非形态模板':'形态模板 · 分类独立'} · ${esc(leadNames.join(' / '))}</footer></button>`).join('');
    const current=()=>token===deckToken&&key===deckKey&&id===state.caseId&&caseToken===state.caseRequestId&&revision===state.caseData?.analysis_revision&&basis.analysis_revision===evidence?.analysis_revision&&basis.analysis_basis===evidence?.analysis_basis&&basis.data_version===evidence?.data_version&&state.currentPage==='edit';
    async function load(){
      try{
        let values=cache.get(key);
        if(!values){
          const source=await Promise.all(items.map(t=>api('/api/cases/'+encodeURIComponent(id)+'/template-occurrences?'+new URLSearchParams({class_code:t.kind==='template'?'all':t.code,template_id:t.id??'all',mode:'all',limit:1}),{signal})));
          if(!current())return;
          if(source.some(r=>['analysis_basis','analysis_revision','data_version'].some(k=>r[k]!==basis[k])))throw Error('模板与当前列表依据已变化，请刷新病例后重试');
          const records=source.map(r=>r.items[0]),ranges=records.filter(Boolean).map(r=>ECGOccurrenceCard.windowFor(r));
          const waves=[];
          for(let i=0;i<ranges.length;i+=32){const d=await api('/api/cases/'+encodeURIComponent(id)+'/event-waveforms',{method:'POST',signal,body:JSON.stringify({ranges:ranges.slice(i,i+32),leads:leadNames,max_points:1200,analysis_basis:source[0].analysis_basis,analysis_revision:source[0].analysis_revision})});if(!current())return;waves.push(...d.items);}
          let waveIndex=0;values=records.map((r,i)=>({record:r,wave:r?waves[waveIndex++]:null,total:source[i].total}));cache.set(key,values);while(cache.size>8)cache.delete(cache.keys().next().value);
        }
        if(!current())return;
        host.querySelectorAll('.workspace-master-card').forEach((card,i)=>{const v=values[i],slot=card.querySelector('.workspace-master-wave');card.querySelector('header span').textContent=fmtNumber(v.total)+' 搏';card.dataset.populationCount=String(v.total);if(v.record&&v.wave){const width=slot.clientWidth||170;slot.innerHTML=ECGOccurrenceCard.svg(v.wave,{...v.record,label:v.record.class_code||v.record.label},{width,height:90});card.dataset.representativeSample=String(v.record.sample_index);card.dataset.representativeCode=v.record.class_code||v.record.label;slot.setAttribute('aria-label','完整集合 '+v.total+' 搏；代表位置 '+formatElapsed(v.record.sample_index/200));}else slot.textContent='该集合没有心搏';});
      }catch(error){if(!current()||error.name==='AbortError')return;host.querySelectorAll('.workspace-master-wave').forEach(slot=>{slot.replaceChildren(document.createTextNode('波形读取失败 '));const retry=document.createElement('span');retry.className='workspace-master-retry';retry.textContent='点击重试';slot.append(retry);});host.dataset.failed='true';}
    }
    load();
  }
  function renderLibrary(){
    if(state.editMode!=='library')return;
    renderDeck();renderEditLibraryAnalytics();renderEditWaveform('#editLibraryWaveformCanvas','#editLibraryWaveMeta');renderEditLibraryNavigator();
    const count=q('#editLibraryFilterCount');if(count)count.textContent=state.trend?.points?state.trend.points.length+' 个时间箱':'读取心率趋势…';
    morphologyWorkbench.refresh();schedule();
  }
  function schedule(){if(!frame)frame=requestAnimationFrame(()=>{frame=0;arrange()});}
  function arrange(){
    const page=q('#page-edit'),library=state.editMode==='library';if(page?.classList.contains('workspace-library')!==library)page?.classList.toggle('workspace-library',library);
    if(state.currentPage!=='edit'&&controller&&!controller.signal.aborted){controller.abort();deckKey='';deckToken++;}
    const panel=q('.edit-gallery-panel'),filters=q('#occurrenceFilters');if(panel&&filters&&library){
      let tools=q('#workspaceOccurrenceTools');if(!tools){tools=document.createElement('div');tools.id='workspaceOccurrenceTools';panel.prepend(tools);}
      const nodes=['#occurrenceFilters','#occurrenceViewControls','.occurrence-actions'].map(q).filter(Boolean);nodes.forEach((el,i)=>{if(tools.children[i]!==el)tools.insertBefore(el,tools.children[i]||null);});
      const slider=q('#v2EditTime'),wave=q('.edit-library-wave-panel');if(slider&&wave&&slider.parentElement!==wave)wave.append(slider);
      const toolbar=q('#occurrenceSelectionToolbar');if(toolbar&&toolbar.parentElement===panel&&tools.nextSibling!==toolbar)tools.after(toolbar);
      // Reserve an integral number of unchanged 142px card rows. The rest is
      // owned by the continuous-wave slot, without cropping a card at 720px.
      if(innerWidth>=1100){const h=Math.max(142,panel.clientHeight-tools.offsetHeight-(toolbar?.offsetHeight||0)),rows=Math.floor(h/142),gallery=q('#editTemplateGallery');if(gallery.dataset.workspaceRows!==String(rows)){gallery.dataset.workspaceRows=String(rows);clinicalUI.renderOccurrences();}}
    }
    if(!library){
      const pageHeading=page?.querySelector(':scope>.page-heading');
      if(filters&&pageHeading&&filters.previousElementSibling!==pageHeading)pageHeading.after(filters);
      const slider=q('#v2EditTime'),wrap=q('#editWaveCanvasWrap');if(slider&&wrap&&slider.parentElement!==wrap.parentElement)wrap.after(slider);
      const tools=q('#workspaceOccurrenceTools'),heading=q('#editGalleryTitle')?.closest('.edit-panel-heading'),gallery=q('#editTemplateGallery');
      if(tools&&heading&&gallery){
        const controls=q('#occurrenceViewControls'),actions=q('.occurrence-actions');
        if(controls)heading.after(controls);if(actions)gallery.before(actions);tools.remove();
      }
      if(innerWidth>=1100&&gallery&&panel){
        const stack=panel.parentElement,style=getComputedStyle(panel),stackStyle=getComputedStyle(stack),gap=Number.parseFloat(stackStyle.rowGap)||0;
        // Some controls share a grid row. Budget their occupied span, rather
        // than summing both heights and starving the continuous-wave canvas.
        const controls=Math.ceil(gallery.getBoundingClientRect().top-panel.getBoundingClientRect().top+(Number.parseFloat(style.paddingBottom)||0)+(Number.parseFloat(style.borderBottomWidth)||0));
        const wave=q('.edit-waveform-panel'),canvas=q('#editWaveformCanvas');
        const canvasMinimum=Number.parseFloat(stackStyle.getPropertyValue('--cluster-wave-canvas-height'))||221;
        const waveChrome=wave&&canvas?Math.max(0,wave.getBoundingClientRect().height-canvas.getBoundingClientRect().height):0;
        const overview=stack.querySelector(':scope>.edit-overview-panel'),overviewHeight=overview?.getBoundingClientRect().height||72;
        const maximum=Math.max(controls+142,stack.clientHeight-overviewHeight-gap*2-waveChrome-canvasMinimum),available=Math.max(142,maximum-controls),rows=Math.max(1,Math.floor(available/142)),height=Math.ceil(controls+rows*142);
        if(stack.style.getPropertyValue('--cluster-gallery-height')!==height+'px')stack.style.setProperty('--cluster-gallery-height',height+'px');
        if(gallery.dataset.workspaceRows!==String(rows)){gallery.dataset.workspaceRows=String(rows);clinicalUI.renderOccurrences();}
      }
    }
    if(state.currentPage==='edit'&&!library&&state.editWaveform?.leads){
      const canvas=q('#editWaveformCanvas'),rect=canvas?.getBoundingClientRect(),dpr=window.devicePixelRatio||1;
      // Reuse the renderer after the final slot has settled so canvas pixels
      // and pointer coordinates describe the same visible surface.
      if(rect?.width>0&&rect.height>=170&&(canvas.width!==Math.round(rect.width*dpr)||canvas.height!==Math.round(rect.height*dpr)))renderEditWaveform();
    }
    morphologyWorkbench.drawAll();
  }
  function mount(){
    const page=q('#page-edit');if(!page)return;
    const boundary=q('.safety-banner>span'),details=document.createElement('details');details.className='workspace-boundary';details.innerHTML='<summary>使用与数据说明</summary><p></p>';details.querySelector('p').textContent=boundary.textContent;boundary.textContent='自动结果待复核 · 源文件只读 · 电压未校准';boundary.after(details);
    q('#editLibraryMode').textContent='模板库';q('#editClusterMode').textContent='密度分布';
    q('.edit-mode-switch').addEventListener('keydown',event=>{
      if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
      event.preventDefault();event.stopPropagation();
      const tab=q(event.key==='Home'?'#editClusterMode':event.key==='End'?'#editLibraryMode':state.editMode==='cluster'?'#editLibraryMode':'#editClusterMode');tab.click();tab.focus({preventScroll:true});
    });
    const inline=q('.edit-library-wave-wrap>.clinical-beat-toolbar');inline.hidden=true;
    const heading=q('.edit-library-deck-panel .edit-panel-heading');heading.querySelector('h2').textContent='形态主模板库';heading.querySelector('p').textContent='实际保存的形态模板；无模板时仅显示分类代表波形';
    const filter=q('.edit-library-filter-panel');filter.querySelector('h2').textContent='全天心率定位';filter.querySelector('p').textContent='HR 趋势，不是形态分布';q('#editLibraryTypeStrip').hidden=true;
    q('.edit-library-density-panel').setAttribute('aria-label','当前完整集合双导联密度');q('.edit-library-density-panel figure:first-child small').textContent='完整集合';q('.edit-library-density-panel figure:nth-of-type(2) figcaption span').textContent='完整集合';
    const retry=document.createElement('button');retry.id='workspaceDensityRetry';retry.type='button';retry.textContent='重读密度';retry.onclick=()=>morphologyWorkbench.refresh(true);const densityNote=q('.edit-library-density-panel>p');retry.title=densityNote.textContent;densityNote.remove();q('.edit-library-density-panel').append(retry);
    q('#editLibraryDeck').addEventListener('click',event=>{if(q('#editLibraryDeck').dataset.failed==='true'&&event.target.closest('.workspace-master-card')){event.preventDefault();event.stopPropagation();deckKey='';renderDeck();}});
    new MutationObserver(schedule).observe(q('.edit-gallery-panel'),{childList:true,subtree:true});
    new MutationObserver(schedule).observe(page,{attributes:true,attributeFilter:['class']});
    new ResizeObserver(()=>{schedule();if(state.currentPage==='edit'&&state.editMode==='library'){renderEditWaveform('#editLibraryWaveformCanvas','#editLibraryWaveMeta');renderEditLibraryAnalytics();}}).observe(q('#editLibraryWorkbench'));
    window.addEventListener('resize',()=>{deckKey='';renderDeck();schedule();});
    setEditMode(state.editMode||'cluster',false);mountOverview();schedule();
  }
  function mountOverview(){
    const rail=q('#page-review .review-rail'),cards=[...rail.querySelectorAll(':scope>.rail-card:not(.keyboard-card)')];
    const tabs=document.createElement('section');tabs.className='workspace-evidence-tabs';tabs.innerHTML='<nav role="tablist" aria-label="窗口证据"><button type="button" role="tab" aria-selected="true">当前窗口</button><button type="button" role="tab" aria-selected="false">人工标注</button></nav>';
    cards.forEach((card,i)=>{card.dataset.workspacePane=String(i);card.hidden=i!==0;tabs.append(card);});rail.append(tabs);
    tabs.querySelectorAll('nav button').forEach((b,i)=>b.onclick=()=>{cards.forEach((c,n)=>c.hidden=i!==n);tabs.querySelectorAll('nav button').forEach((x,n)=>x.setAttribute('aria-selected',String(i===n)));});
    const help=document.createElement('details');help.className='workspace-keyboard-help';help.innerHTML='<summary>快捷键</summary>';help.append(rail.querySelector('.keyboard-card'));q('.ov-commandbar>div:last-child').append(help);
    const range=q('.scatter-keyboard-select');range.classList.add('workspace-scatter-range');
    const mode=q('.ov-scatter-mode-picker'),controls=document.createElement('div');controls.className='workspace-scatter-controls';
    range.before(controls);if(mode)controls.append(mode);controls.append(range);
    const summary=range.querySelector('summary');summary.textContent='键盘选区';summary.setAttribute('aria-label','键盘范围选择');
  }
  document.addEventListener('DOMContentLoaded',mount);
  return {renderDeck,renderLibrary,schedule,receiveEvidence,switchMode};
})();
renderEditLibraryDeck=desktopWorkspace.renderDeck;
renderEditLibrary=desktopWorkspace.renderLibrary;
setEditMode=desktopWorkspace.switchMode;
