"use strict";
/* Shared workstation UI. Selection for editing and selection for reporting are independent. */
const clinicalUI=(()=>{
  const A=ECGClinicalAnalysis,esc=escapeHtml,qs=s=>document.querySelector(s);
  const copy=x=>JSON.parse(JSON.stringify(x));
  const tabs=[...A.categories,['tables','数据表格'],['strips','报告图条'],['final','报告']];
  let occurrenceToken=0,reportToken=0,waveToken=0,editCase=null,occurrence=null,editMode='all',template='all',type='N',pageCache=new Map(),tileWidth=150,editTimeTimer=0,occurrenceReadAbort=null;
  const reportWaveCache=new Map();
  let waveEvidenceScope='',waveEvidence={};
  const thumbnailCache=ECGWaveformLoader.create(async(group,ranges)=>{
    const [id,leads,evidence={}]=JSON.parse(group);
    const result=await api(`/api/cases/${id}/event-waveforms`,{method:'POST',body:JSON.stringify({ranges,leads:leads.split(','),max_points:1200,...evidence})});
    return result.items;
  });
  function syncWaveEvidence(id,data){
    const scope=JSON.stringify([id,data.data_version,data.analysis_basis,data.analysis_revision]);
    if(scope===waveEvidenceScope)return;
    waveEvidenceScope=scope;waveEvidence={};
    for(const key of ['analysis_basis','analysis_revision'])if(data[key]!==undefined)waveEvidence[key]=data[key];
    reportWaveCache.clear();thumbnailCache.clear();reportSelectionUndo=null;
  }
  function sameEvidence(a,b){return ['data_version','analysis_basis','analysis_revision'].every(key=>a[key]===b[key]);}
  let reportCase=null,reportVersion=null,category='fastest',reportOffset=0,reportMode='all',reportSort='hr_desc',reportData=null,selectedLookup=new Map(),active=null,hrv=null,hrvToken=0;
  const run=fn=>Promise.resolve().then(fn).catch(handleError);
  const endpoint=(kind,params={},id=state.caseId,options={})=>api(`/api/cases/${id}/${kind}?${new URLSearchParams(params)}`,options);
  const selected=()=>state.reportComposition?.selected_events||[];
  let reportRenderToken=0;
  let pauseBand='all',reportTimeRange=null,reportSpacing=0;
  let reportReturn=null,reportWaveReady=false,reportSelectionUndo=null;
  let rhythmWrite=null;
  let hrvLegacyWeb=null;
  // Retain real legacy canvases/source comparison through every HRV render.
  // Their original IDs, listeners and data stay live; paper follows all web UI.
  function prepareHrvLoad(){
    const target=qs('#hrvWindowPanel');
    // The original loader clears the mount before drawing the live canvases.
    // Keep those exact nodes in the page while it reads, including retry/cancel.
    if(target&&hrvLegacyWeb)target.before(hrvLegacyWeb);
  }
  function renderHrvTarget(target,html){
    const legacy=target.id==='hrvWindowPanel'?hrvLegacyWeb:null;
    if(legacy)legacy.remove();
    target.innerHTML=html;
    if(legacy){const paper=target.querySelector('.hrv-paper-preview');if(paper)paper.before(legacy);else target.append(legacy);}
  }
  function composition(){
    const source=state.reportComposition||state.report?.composition||{};
    return {...source,schema_version:2,included_pages:ECGReportSections.selectedPages(source),page_selection_version:1,selected_events:source.selected_events||[],category_reviews:source.category_reviews||{},diagnosis_blocks:source.diagnosis_blocks||[],fast_slow_mode:source.fast_slow_mode||'rr',paper:{...(source.paper||{}),size:'A4',orientation:'portrait'},strip_defaults:ECGReportEngine.settings(source.strip_defaults)};
  }
  function dirty(){cancelReportExport();state.reportDirty=true;if(qs('#reportSaveState'))qs('#reportSaveState').textContent='有未保存修改';clinicalWorkflow.renderPreflight();}
  function svg(wave,event=null,compact=false,dimensions={}){
    if(compact)return ECGOccurrenceCard.svg(wave,event,dimensions);
    const leads=(globalThis.ECGChartInspection?.entries(wave.leads||{})||Object.entries(wave.leads||{})),width=1000,row=compact?70:125,height=Math.max(1,leads.length)*row;
    return `<svg viewBox="0 0 ${width} ${height}" ${compact?'preserveAspectRatio="none"':''} role="img" aria-label="${esc(event?.label||'心电波形')}，${wave.duration_s}秒"><rect width="100%" height="100%" fill="#fff"/>${leads.map(([name,values],j)=>{const mid=j*row+row/2,max=Math.max(50,...values.map(v=>Math.abs(v))),scale=(row*.4)/max;return `<text x="4" y="${j*row+14}" font-size="13">${esc(name)}</text><polyline fill="none" stroke="#244f59" stroke-width="1.2" points="${values.map((v,i)=>`${(i/(values.length-1||1)*width).toFixed(2)},${(mid-v*scale).toFixed(2)}`).join(' ')}"/>`}).join('')}${(wave.beats||[]).map(beat=>{const x=(beat.sample_index/200-wave.start_s)/wave.duration_s*width;if(x<0||x>width)return '';return (event?.target_samples||[]).includes(beat.sample_index)?ECGReviewTools.markSvg(x,height,beat.class_code):compact?'':`<text x="${x}" y="13" fill="#536b74" font-size="10">${esc(beat.class_code)}</text>`}).join('')}</svg>`;
  }
  function eventWaveKey(e,id,leads,centered=false){return [waveEvidenceScope,id,e.basis_version,e.event_id,leads,centered?'centered-card':'overview'].join('|');}
  function releaseOccurrenceWaves(){thumbnailCache.retain('occurrence',[]);globalThis.ECGSourceGroupEvidence?.clear();if(state.currentPage!=='edit'&&occurrenceReadAbort){occurrenceToken++;occurrenceReadAbort.abort();occurrenceReadAbort=null;}}
  async function eventWave(e,id=state.caseId,leads='II,V1,V5',options={}){
    const range=options.centeredCard?ECGOccurrenceCard.windowFor(e):{start:Math.max(0,e.start_sample/200-.8),end:e.end_sample/200+1.6};
    const {start,end}=range,key=eventWaveKey(e,id,leads,options.centeredCard);
    return thumbnailCache.get(key,JSON.stringify([id,leads,waveEvidence]),{start,end},options);
  }
  const typeNames={N:'正常搏',S:'房早',V:'室早'};
  let openType=null;
  function modeChoices(code){
    if(['S','V'].includes(code))return A.patterns.map(([key,label])=>[key,key==='tachycardia'?(code==='S'?'房速':'室速'):label]);
    if(['A','M'].includes(code))return [['all','全部心搏'],['AF','房颤事件']];
    if(['C','H'].includes(code))return [['all','全部心搏'],['AFL','房扑事件']];
    return [['all',code==='N'?'全部正常搏':'全部']];
  }
  function modeLabel(){return Object.fromEntries(modeChoices(type))[editMode]||'全部';}
  function closeTypeMenu(restoreFocus=false){
    const menu=qs('#editTypeMenu'),code=openType;openType=null;
    if(menu){try{menu.hidePopover()}catch(_){}menu.hidden=true;}
    document.querySelectorAll('[data-occ-type]').forEach(button=>button.setAttribute('aria-expanded','false'));
    if(restoreFocus&&code)qs(`[data-occ-type="${code}"]`)?.focus();
  }
  function chooseFilter(code,mode='all',templateId='all'){
    closeTypeMenu();state.editSelectedSamples=new Set();state.editSelectedSample=null;
    type=code;editMode=mode;template=String(templateId);state.editSelectedClass=template==='all'?'source-'+code:'custom-'+template;
    renderEditClasses();renderEditScatter();run(loadOccurrences);
    requestAnimationFrame(()=>qs(`[data-occ-type="${['N','S','V'].includes(code)?code:'other'}"]`)?.focus());
  }
  function openTypeMenu(button){
    const code=button.dataset.occType,menu=qs('#editTypeMenu');
    if(openType===code){closeTypeMenu(true);return;}
    closeTypeMenu();openType=code;button.setAttribute('aria-expanded','true');
    const rows=code==='other'?Object.entries(ECGBeatEngine.types).filter(([k])=>!['N','S','V'].includes(k)).flatMap(([k,t])=>modeChoices(k).map(([mode,label])=>({code:k,mode,template:'all',label:`${k} · ${mode==='all'?t.name:label}`}))):[
      ...modeChoices(code).map(([mode,label])=>({code,mode,template:'all',label})),
      ...(code==='N'?(state.editTemplates||[]).filter(t=>t.source_class==='source-N').map(t=>({code,mode:'all',template:String(t.id),label:`${t.name} · ${t.beat_count??t.sample_indices.length} 搏` })):[])
    ];
    menu.innerHTML=`<div class="edit-type-menu-title">${typeNames[code]||'其他心搏类型'}</div>${rows.map(item=>`<button type="button" role="menuitemradio" aria-checked="${type===item.code&&editMode===item.mode&&template===item.template}" data-code="${item.code}" data-mode="${item.mode}" data-template="${item.template}"><span class="edit-menu-check" aria-hidden="true"></span>${esc(item.label)}</button>`).join('')}`;
    menu.setAttribute('aria-label',`${typeNames[code]||'其他'}筛选`);menu.hidden=false;menu.showPopover();
    const rect=button.getBoundingClientRect(),availableAbove=rect.top-12,availableBelow=innerHeight-rect.bottom-12;
    menu.style.maxHeight=`${Math.max(120,Math.max(availableAbove,availableBelow))}px`;
    menu.style.left=`${Math.max(8,Math.min(rect.left,innerWidth-250))}px`;
    const height=menu.getBoundingClientRect().height;
    menu.style.top=`${availableAbove>=height||availableAbove>=availableBelow?Math.max(8,rect.top-height-6):rect.bottom+6}px`;
    (menu.querySelector('[aria-checked="true"]')||menu.querySelector('button')).focus();
  }
  function filters(){
    const host=qs('#occurrenceFilters');if(!host)return;
    const selectedTemplate=(state.editTemplates||[]).find(t=>'custom-'+t.id===state.editSelectedClass);
    if(selectedTemplate&&template!==String(selectedTemplate.id)){template=String(selectedTemplate.id);editMode='all';}
    const code=state.editSelectedClass?.startsWith('source-')?state.editSelectedClass.slice(7):type;
    if(code!==type){type=code;editMode='all';template='all';}
    const choices=Object.entries(ECGBeatEngine.types||{});
    host.innerHTML=`<div class="occurrence-template-tools"><label>搜索模板<input id="occSearch" type="search" placeholder="模板名称，如 S1"></label><label>形态模板<select id="occTemplate"></select></label></div><div class="occurrence-current-filter"><span>当前筛选</span><strong>${esc(typeNames[type]||ECGBeatEngine.types[type]?.name||type)} · ${esc(modeLabel())}</strong></div><div class="edit-type-dock" role="group" aria-label="左下角心搏类型与事件模式">${['N','S','V','other'].map(k=>`<button type="button" id="editType${k}" data-occ-type="${k}" aria-haspopup="menu" aria-expanded="false" aria-controls="editTypeMenu" aria-label="${k==='other'?'其他类型':k+' '+typeNames[k]+'类型'}" aria-pressed="${template==='all'&&(k===type||(k==='other'&&!['N','S','V'].includes(type)))}"><strong>${k==='other'?'其他':k}</strong><span>${typeNames[k]||'类型'}</span><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4"/></svg></button>`).join('')}</div><div hidden><select id="occType" aria-label="心搏类型">${choices.map(([k,t])=>`<option value="${k}" ${type===k?'selected':''}>${k} ${esc(t.name)}</option>`).join('')}</select><select id="occMode" aria-label="事件模式">${modeChoices(type).map(([k,v])=>`<option value="${k}" ${editMode===k?'selected':''}>${esc(v)}</option>`).join('')}</select></div>`;
    updateTemplates();
    host.querySelectorAll('[data-occ-type]').forEach(button=>{button.title='筛选类别与事件模式，不修改心搏分类';button.setAttribute('aria-label','筛选 '+(button.dataset.occType==='other'?'其他心搏':button.dataset.occType+' '+typeNames[button.dataset.occType]));button.onclick=()=>openTypeMenu(button);});
    qs('#occType').onchange=e=>chooseFilter(e.target.value);
    qs('#occMode').onchange=e=>chooseFilter(type,e.target.value);
    qs('#occTemplate').onchange=e=>{state.editSelectedSamples=new Set();state.editSelectedSample=null;template=e.target.value;state.editSelectedClass=template==='all'?'source-'+type:'custom-'+template;renderEditClasses();renderEditScatter();run(loadOccurrences)};
    qs('#occSearch').oninput=updateTemplates;
  }
  function updateTemplates(){
    const select=qs('#occTemplate');if(!select)return;
    const search=qs('#occSearch').value.toLowerCase();
    const matches=(state.editTemplates||[]).filter(t=>(t.source_class==='source-'+type||String(t.id)===template)&&(t.name.toLowerCase().includes(search)||String(t.id)===template));
    select.innerHTML='<option value="all">全部模板</option>'+matches.map(t=>`<option value="${t.id}" ${String(t.id)===template?'selected':''}>${esc(t.name)} · ${t.beat_count??t.sample_indices.length}</option>`).join('');
  }
  function editParams(offset=0){return {class_code:template!=='all'&&editMode==='all'?'all':type,mode:editMode,template_id:template,offset,limit:48}}
  let occurrenceLeadCount=2;
  const occurrenceGrid=(total,width,top=0)=>{
    const rows=['cluster','library'].includes(state.editMode)&&innerWidth>=1100?Number(qs('#editTemplateGallery')?.dataset.workspaceRows)||2:ECGOccurrenceCard.geometry.visibleRows;
    return ECGReviewTools.virtualGrid(total,width,top,{...ECGOccurrenceCard.geometry,visibleRows:rows});
  };
  function occurrenceViewControls(){
    const heading=qs('#editGalleryTitle')?.closest('.edit-panel-heading');if(!heading)return;
    let controls=qs('#occurrenceViewControls');
    if(!controls){
      controls=document.createElement('div');controls.id='occurrenceViewControls';controls.className='occurrence-view-controls';
      controls.innerHTML='<label>小图导联<select id="occurrenceLeadCount" aria-label="小图导联数量"><option value="2">2 导联</option><option value="3">3 导联</option></select></label><span id="occurrenceLeadNames"></span>';
      heading.after(controls);qs('#occurrenceLeadCount').onchange=e=>{occurrenceLeadCount=Number(e.target.value)===3?3:2;renderOccurrences()};
    }
    qs('#occurrenceLeadCount').value=String(occurrenceLeadCount);
    qs('#occurrenceLeadNames').textContent=ECGOccurrenceCard.leads(state.editLead||'II',occurrenceLeadCount).join(' / ')+' · 各导联自适应幅度 · 设备单位 u，未校准';
  }
  let occurrenceFocus=null;
  function occurrenceBookmark(anchor=null){
    const host=qs('#editTemplateGallery');
    if(state.currentPage!=='edit'||!host||!occurrence?.total)return null;
    const grid=occurrenceGrid(occurrence.total,host.clientWidth,host.scrollTop);
    const index=Math.max(0,grid.visibleFirst-1),item=pageCache.get(Math.floor(index/48)*48)?.[index%48];
    const sample=Number.isSafeInteger(anchor)?anchor:item?.sample_index;
    if(!Number.isSafeInteger(sample))return null;
    return {id:state.caseId,token:occurrenceToken,caseToken:state.caseRequestId,filter:JSON.stringify([type,editMode,template]),sample,scrollTop:host.scrollTop,search:qs('#occSearch')?.value||''};
  }
  function currentOccurrenceBookmark(mark){
    return mark&&mark.id===state.caseId&&mark.caseToken===state.caseRequestId&&mark.token===occurrenceToken&&state.currentPage==='edit'&&mark.filter===JSON.stringify([type,editMode,template]);
  }
  // Tab navigation owns a fresh request token, not the old bookmark token.
  function captureEditView(){
    return {id:state.caseId,caseToken:state.caseRequestId,type,mode:editMode,template,leadCount:occurrenceLeadCount,scrollTop:qs('#editTemplateGallery')?.scrollTop||0,search:qs('#occSearch')?.value||'',ordinal:qs('#occJump')?.value||'',focusIndex:occurrenceFocus?.index??null};
  }
  async function activateEditView(mark,valid=()=>true){
    if(mark&&mark.id===state.caseId&&mark.caseToken===state.caseRequestId){
      type=mark.type;editMode=mark.mode;template=mark.template;occurrenceLeadCount=mark.leadCount;
    }else{type=state.editSelectedClass?.startsWith('source-')?state.editSelectedClass.slice(7):'N';editMode='all';template='all';occurrenceLeadCount=2;}
    const loading=loadOccurrences(),token=occurrenceToken;
    await loading;
    if(token!==occurrenceToken||!valid()||!mark||mark.id!==state.caseId||mark.caseToken!==state.caseRequestId)return;
    const host=qs('#editTemplateGallery'),search=qs('#occSearch');
    if(search){search.value=mark.search;updateTemplates();}
    if(qs('#occJump')&&!qs('#occJump').disabled)qs('#occJump').value=mark.ordinal;
    if(Number.isInteger(mark.focusIndex)&&mark.focusIndex<occurrence?.total)occurrenceFocus={index:mark.focusIndex,token:occurrenceToken,id:state.caseId};
    if(host)host.scrollTop=mark.scrollTop;
    renderOccurrences();
  }
  function syncOccurrenceJump(reset=false){
    const input=qs('#occJump'),go=qs('#occGo');if(!input||!go)return;
    const total=occurrence?.total||0;
    input.disabled=go.disabled=!total;
    if(total)input.max=String(total);else input.removeAttribute('max');
    // Only a new collection resets the draft. Scrolling, resizing and lazy-page
    // responses must not overwrite an ordinal the doctor is still typing.
    if(reset){input.value=total?'1':'';input.setCustomValidity('');}
  }
  function focusOccurrence(index){
    const host=qs('#editTemplateGallery');
    if(!host||!occurrence||index<0||index>=occurrence.total)return;
    const grid=occurrenceGrid(occurrence.total,host.clientWidth);
    occurrenceFocus={index,token:occurrenceToken,id:state.caseId};
    host.focus({preventScroll:true});
    host.scrollTop=Math.floor(index/grid.columns)*grid.row;
    renderOccurrences();
  }
  function jumpOccurrence(){
    const input=qs('#occJump'),total=occurrence?.total||0;if(!total||input.disabled)return;
    const ordinal=Number(input.value);
    if(!Number.isSafeInteger(ordinal)||ordinal<1||ordinal>total){
      input.setCustomValidity(`请输入 1–${total} 之间的整数序号`);input.reportValidity();return;
    }
    input.setCustomValidity('');input.value=String(ordinal);focusOccurrence(ordinal-1);
  }
  function bindOccurrenceJump(){
    qs('#occGo').onclick=jumpOccurrence;
    const input=qs('#occJump');
    input.oninput=()=>input.setCustomValidity('');
    input.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();event.stopPropagation();jumpOccurrence();}};
    syncOccurrenceJump(true);
  }
  function occurrenceReadState(status,message,scope){
    const host=qs('#editTemplateGallery');host.dataset.readState=status;host.setAttribute('aria-busy',String(status==='loading'));
    if(message){
      const text=document.createElement('p');text.className='empty-state';text.setAttribute('role',status==='error'?'alert':'status');text.textContent=message;
      const button=document.createElement('button');button.type='button';button.className='button secondary';button.dataset.occurrenceRead=status==='loading'?'cancel':'retry';button.textContent=status==='loading'?'取消读取':'重试读取';
      button.onclick=()=>{
        if(scope.token!==occurrenceToken||scope.id!==state.caseId||scope.caseToken!==state.caseRequestId||state.currentPage!=='edit')return;
        if(status==='loading'){occurrenceReadAbort?.abort();occurrenceReadAbort=null;occurrenceToken++;releaseOccurrenceWaves();qs('#editGalleryCount').textContent='已取消';occurrenceReadState('cancelled','已取消读取。筛选与输入保留，可重试当前列表。',{...scope,token:occurrenceToken});}
        else run(()=>loadOccurrences(null,true));
      };
      host.replaceChildren(text,button);
    }
    if(qs('#occurrenceSelectionToolbar'))beatEditor.renderOccurrenceToolbar?.({sourceLabel:type+' · '+modeLabel(),code:type,totalRecords:occurrence?.total??0,totalSampleCount:editMode==='all'?occurrence?.total:null,visibleRecords:0,visibleSampleCount:0,selectedCount:state.editSelectedSamples.size,lead:state.editLead||'II',revision:occurrence?.analysis_revision??state.caseData?.analysis_revision});
  }
  function retryOccurrencePage(error,offset,token,id){
    if(token!==occurrenceToken||id!==state.caseId||state.currentPage!=='edit')return;
    pageCache.delete(offset);qs('#editGalleryCount').textContent='部分记录读取失败';
    qs('[data-occurrence-page-retry]')?.remove();
    const button=document.createElement('button');button.type='button';button.className='button secondary';button.dataset.occurrencePageRetry=String(offset);button.textContent='重试当前页';button.title='重读未取得的出现记录，保留筛选与已选心搏';
    button.onclick=()=>{if(token!==occurrenceToken||id!==state.caseId||state.currentPage!=='edit')return;button.remove();renderOccurrences();};qs('#editGalleryCount').after(button);handleError(error);
  }
  async function loadOccurrences(bookmark=null,preserveInputs=false){
    globalThis.ECGSourceGroupEvidence?.clear();
    if(!state.caseId)return;
    const resume=currentOccurrenceBookmark(bookmark)?(bookmark.scrollTop===qs('#editTemplateGallery')?.scrollTop?bookmark:occurrenceBookmark()):null,caseToken=state.caseRequestId;
    if(bookmark&&!resume)return; // A newer filter/navigation owns the list now.
    if(editCase!==state.caseId){editCase=state.caseId;editMode='all';template='all';pageCache.clear();thumbnailCache.clear();reportWaveCache.clear();}
    const draft=preserveInputs?{search:qs('#occSearch')?.value||'',ordinal:qs('#occJump')?.value||''}:null;
    occurrenceReadAbort?.abort();const controller=new AbortController();occurrenceReadAbort=controller;
    const token=++occurrenceToken,id=state.caseId;pageCache.clear();occurrence=null;filters();
    qs('[data-occurrence-page-retry]')?.remove();
    if(draft&&qs('#occSearch')){qs('#occSearch').value=draft.search;updateTemplates();}
    occurrenceFocus=null;syncOccurrenceJump(true);
    const resumeButton=qs('#occResume');if(resumeButton){resumeButton.hidden=true;resumeButton.onclick=null;}
    qs('#editGalleryCount').textContent='读取中…';
    releaseOccurrenceWaves();
    if(draft&&qs('#occJump'))qs('#occJump').value=draft.ordinal;
    occurrenceReadState('loading','正在读取当前筛选的出现记录…',{id,caseToken,token});
    // Full-population density is independent of thumbnails; do not serialize it
    // behind the occurrence index and an obsolete representative-strip request.
    if(state.editMode!=='library'||state.editReadIdentity?.id===id&&state.editReadIdentity.caseToken===caseToken)renderEditDensity();
    try{
      const params=editParams();if(resume)params.near_sample=resume.sample;
      const result=await endpoint('template-occurrences',params,id,{signal:controller.signal,readLane:'occurrence-list'});
      if(token!==occurrenceToken||id!==state.caseId||caseToken!==state.caseRequestId||state.currentPage!=='edit'||controller.signal.aborted)return;
      syncWaveEvidence(id,result);occurrence=result;syncOccurrenceJump(true);pageCache.set(result.offset||0,result.items);
      if(globalThis.ECGLinkedSelection&&result.analysis_basis!==undefined&&result.analysis_revision!==undefined&&Number.isSafeInteger(result.beat_revision)&&result.beat_revision>=0)ECGLinkedSelection.setScope({caseId:id,caseToken,analysis_basis:result.analysis_basis,analysis_revision:result.analysis_revision,beatRevision:result.beat_revision});
      occurrenceReadState('ready');
      if(typeof desktopWorkspace!=='undefined')desktopWorkspace.receiveEvidence(result);
      const host=qs('#editTemplateGallery'),index=result.resume_index;
      const grid=occurrenceGrid(result.total,host.clientWidth);
      // Restore the scroll range first: browsers clamp scrollTop to zero while
      // the short loading message is the only content in the viewport.
      host.innerHTML='<div class="occurrence-lane"></div>';
      host.firstElementChild.style.height=grid.contentHeight+'px';
      host.scrollTop=resume&&Number.isInteger(index)?Math.floor(index/grid.columns)*grid.row:0;
      if(resume){
        const search=qs('#occSearch');if(search){search.value=resume.search;updateTemplates();}
        if(resumeButton&&Number.isInteger(index)){
          qs('#occJump').value=String(index+1);resumeButton.hidden=false;
          resumeButton.textContent=`继续复核第 ${index+1} 条 · ${result.resume_exact?'原时间位置':'原位置附近，未自动勾选'}`;
          resumeButton.onclick=()=>{if(token===occurrenceToken&&id===state.caseId&&caseToken===state.caseRequestId&&state.currentPage==='edit')focusOccurrence(index);};
        }
      }
      renderOccurrences();if(typeof renderEditLibrary==='function')renderEditLibrary();if(typeof morphologyWorkbench==='undefined')await loadMorphology(result.items,token,id);
      if(draft?.ordinal&&token===occurrenceToken&&id===state.caseId&&qs('#occJump'))qs('#occJump').value=draft.ordinal;
    }
    catch(error){if(token!==occurrenceToken||id!==state.caseId||caseToken!==state.caseRequestId||state.currentPage!=='edit'||error.name==='AbortError')return;qs('#editGalleryCount').textContent='读取失败';occurrenceReadState('error','读取失败：'+error.message+'。筛选与输入保留，可重试。',{id,caseToken,token});throw error;}
    finally{if(occurrenceReadAbort===controller)occurrenceReadAbort=null;}
  }
  async function loadMorphology(items,token,id){
    if(typeof morphologyWorkbench!=='undefined')return;
    const samples=[...new Set(items.flatMap(e=>e.target_samples))].slice(0,24);
    if(!samples.length){state.editTemplateStrips=[];renderEditDensity();return;}
    const result=await api(`/api/cases/${id}/waveform-strips`,{method:'POST',body:JSON.stringify({sample_indices:samples,leads:[state.editLead||'II'],pre_s:.4,post_s:.8,max_points:240,filter:'display'})});
    if(token!==occurrenceToken||id!==state.caseId)return;
    state.editTemplateStrips=result.items;renderEditDensity();
    if(typeof overviewWorkbench==='undefined')qs('#editMorphologyCount').textContent=`当前批次 ${result.items.length} 搏`;
  }
  function renderOccurrences(){
    if(state.currentPage!=='edit'){occurrenceFocus=null;releaseOccurrenceWaves();return;}
    const host=qs('#editTemplateGallery');if(!host||!occurrence)return;
    host.classList.add('occurrence-viewport');host.tabIndex=0;host.setAttribute('aria-label','心搏出现记录，向下滚动连续浏览');host.removeAttribute('aria-live');
    const total=occurrence.total,g=occurrenceGrid(total,host.clientWidth,host.scrollTop),{first,last}=g,token=occurrenceToken,id=state.caseId;
    tileWidth=g.width;host.style.setProperty('--occ-height',g.height+'px');host.scrollLeft=0;
    const focused=host.contains(document.activeElement)?document.activeElement.closest('[data-occ-index]')?.dataset.occIndex:null,focusInput=document.activeElement?.tagName==='INPUT';
    syncEditTimeSlider();
    const templateName=(state.editTemplates||[]).find(t=>String(t.id)===template)?.name;
    const sourceLabel=templateName&&editMode==='all'?templateName+' · 完整形态模板':type+' · '+modeLabel();
    qs('#editGalleryTitle').textContent=`${sourceLabel} · 全部出现记录`;
    qs('#editGalleryDescription').textContent='点击定位；Ctrl/⌘点击或空格多选；方向键移动；右键/Shift+F10 菜单，N/S/V/X 改型须预览确认';
    occurrenceViewControls();
    qs('#editGalleryCount').textContent=`${g.visibleFirst}–${g.visibleLast} / ${total}`;
    syncOccurrenceJump();
    const visibleSamples=new Set();for(let i=g.visibleFirst-1;i<g.visibleLast;i++){const row=pageCache.get(Math.floor(i/48)*48)?.[i%48];for(const sample of row?.target_samples||[])visibleSamples.add(sample);}
    beatEditor.renderOccurrenceToolbar?.({sourceLabel,code:type,savingRhythm:rhythmWrite?.id===state.caseId&&rhythmWrite.caseToken===state.caseRequestId,totalRecords:total,totalSampleCount:editMode==='all'?total:null,visibleRecords:Math.max(0,g.visibleLast-g.visibleFirst+1),visibleSampleCount:visibleSamples.size,selectedCount:state.editSelectedSamples.size,lead:state.editLead||'II',revision:occurrence.analysis_revision??state.caseData?.analysis_revision});
    if(!total){occurrenceFocus=null;syncOccurrenceJump(true);releaseOccurrenceWaves();host.innerHTML='<p class="empty-state">0 条匹配记录</p>';return;}
    let lane=host.querySelector('.occurrence-lane');if(!lane){host.innerHTML='<div class="occurrence-lane"></div>';lane=host.firstElementChild;}
    const leads=ECGOccurrenceCard.leads(state.editLead||'II',occurrenceLeadCount).join(',');
    const evidenceScope=waveEvidenceScope,scope=JSON.stringify([token,id,evidenceScope,leads]);
    // Keep overlap mounted: scrolling within a row must not reparse every ECG
    // polyline or detach the doctor's focused control. Never reuse across evidence.
    if(lane.dataset.occScope!==scope){lane.innerHTML='';lane.dataset.occScope=scope;}
    lane.style.width='100%';lane.style.height=g.contentHeight+'px';
    const mounted=new Map();
    for(const card of lane.querySelectorAll('[data-occ-index]')){
      const index=Number(card.dataset.occIndex);
      if(index<first||index>=last)card.remove();else mounted.set(index,card);
    }
    let anchor=lane.firstElementChild;const wantedWaves=[];
    const currentGrid=()=>occurrenceGrid(occurrence.total,host.clientWidth,host.scrollTop);
    for(let n=first;n<last;n++){
      const offset=Math.floor(n/48)*48,items=pageCache.get(offset);
      if(!items){if(!pageCache.has(offset)){pageCache.set(offset,null);endpoint('template-occurrences',editParams(offset),id).then(result=>{if(token!==occurrenceToken||id!==state.caseId)return;if(!sameEvidence(result,occurrence)){loadOccurrences().catch(handleError);return;}pageCache.set(offset,result.items);renderOccurrences();loadMorphology(result.items,token,id).catch(handleError)}).catch(error=>retryOccurrencePage(error,offset,token,id));}continue;}
      const e=items[n-offset];if(!e)continue;
      wantedWaves.push(eventWaveKey(e,id,leads,true));
      let card=mounted.get(n),reused=card?.occurrenceItem===e;
      if(card&&!reused){if(anchor===card)anchor=card.nextElementSibling;card.remove();}
      if(!reused){card=document.createElement('div');card.className='occurrence-tile';card.dataset.occIndex=n;card.occurrenceItem=e;}
      card.style.cssText=`left:${n%g.columns*tileWidth}px;top:${Math.floor(n/g.columns)*g.row}px;width:${tileWidth-6}px`;
      if(card!==anchor)lane.insertBefore(card,anchor);
      anchor=card.nextElementSibling;
      const renderTileWave=w=>{
        const node=card.querySelector('.occurrence-wave'),dimensions={width:Math.max(1,tileWidth-18),height:90},size=dimensions.width+'|'+dimensions.height;
        if(card.occurrenceWave===w&&card.dataset.waveSize===size)return;
        card.occurrenceWave=w;card.dataset.waveSize=size;node.innerHTML=svg(w,e,true,dimensions);
        card.title=`${e.label} · ${e.beat_count} 搏 · ${w.duration_s} 秒 · ${leads}${w.stride>1?' · 步进 '+w.stride+' 采样的概览，请点击回看完整波形':''}`;
      };
      if(reused){ECGOccurrenceCard.syncSelection(card,e,state);if(card.occurrenceWave)renderTileWave(card.occurrenceWave);continue;}
      const code=e.class_code||type,status=e.diagnosis_status==='edited'?'已修订':e.diagnosis_status==='confirmed'?'已确认':'待审核';
      card.innerHTML=`<button type="button" class="occurrence-open" aria-label="第${n+1}条 ${esc(e.label)}，${e.beat_count}搏，${status}；点击定位，空格或Ctrl点击多选"><span class="occurrence-card-heading"><strong class="occurrence-code">${esc(code)}</strong>${e.beat_count>1?`<span class="occurrence-group-count">×${e.beat_count} 搏</span>`:''}</span><span class="occurrence-wave">读取波形…</span><span class="occurrence-card-footer"><time>${formatElapsed(e.time_s)}</time><span>${n+1}/${total}</span></span></button><input type="checkbox" hidden tabindex="-1" aria-hidden="true">`;
      ECGOccurrenceCard.syncSelection(card,e,state);
      let waveFailed=false;
      const selectCard=toggle=>{if(toggle){const all=e.target_samples.every(s=>state.editSelectedSamples.has(s));e.target_samples.forEach(s=>all?state.editSelectedSamples.delete(s):state.editSelectedSamples.add(s));}else if(!e.target_samples.every(s=>state.editSelectedSamples.has(s)))state.editSelectedSamples=new Set(e.target_samples);state.editSelectedSample=e.sample_index;beatEditor.syncOccurrenceSelection();setEditStart(Math.max(0,e.time_s-2));renderEditScatter();
        const evidenceHost=qs('#occurrenceGroupEvidence');
        if(evidenceHost)globalThis.ECGSourceGroupEvidence?.mount(evidenceHost,{item:e,
          isCurrent:()=>token===occurrenceToken&&id===state.caseId&&evidenceScope===waveEvidenceScope&&state.currentPage==='edit',
          loadWave:(params,signal)=>api(`/api/cases/${id}/waveform?${new URLSearchParams({...params,...waveEvidence})}`,{signal,readLane:'source-group'}),
          onLocate:time=>setEditStart(Math.max(0,time-2))});
      };
      card.querySelector('button').onclick=ev=>{if(waveFailed){loadTileWave();return;}selectCard(Boolean(ev?.ctrlKey||ev?.metaKey));};
      beatEditor.registerOccurrence(card,e,{code:type,samples:async visible=>{
        if(token!==occurrenceToken||id!==state.caseId)throw Error('筛选集合已变化，请重新打开菜单');
        if(visible){const view=currentGrid(),samples=[];for(let i=view.visibleFirst-1;i<view.visibleLast;i++){const row=pageCache.get(Math.floor(i/48)*48)?.[i%48];if(row)samples.push(...row.target_samples)}return [...new Set(samples)];}
        const samples=[];for(let offset=0;offset<occurrence.total;offset+=200){const result=await endpoint('template-occurrences',{...editParams(offset),limit:200},id);if(token!==occurrenceToken||!sameEvidence(result,occurrence))throw Error('心搏集合已变化，请刷新后重试');samples.push(...result.items.flatMap(x=>x.target_samples))}return [...new Set(samples)];
      }});
      card.querySelector('input').onchange=ev=>{e.target_samples.forEach(s=>ev.target.checked?state.editSelectedSamples.add(s):state.editSelectedSamples.delete(s));state.editSelectedSample=e.sample_index;beatEditor.syncOccurrenceSelection();renderEditScatter();};
      card.onkeydown=ev=>{if([' ','ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(ev.key)){ev.stopPropagation();ev.preventDefault();if(ev.key===' '){if(waveFailed)loadTileWave();else selectCard(true);}else{const view=currentGrid(),next=Math.max(0,Math.min(total-1,n+({ArrowLeft:-1,ArrowRight:1,ArrowUp:-view.columns,ArrowDown:view.columns}[ev.key])));focusOccurrence(next);}}};
      const isCurrent=()=>state.currentPage==='edit'&&token===occurrenceToken&&id===state.caseId&&lane.dataset.occScope===scope&&card.isConnected;
      const loadTileWave=()=>{
        if(!isCurrent())return;
        waveFailed=false;card.querySelector('.occurrence-wave').textContent='读取波形…';
        eventWave(e,id,leads,{owner:'occurrence',centeredCard:true}).then(w=>{if(isCurrent())renderTileWave(w)}).catch(()=>{if(isCurrent()){waveFailed=true;card.querySelector('.occurrence-wave').textContent='波形读取失败，点击重试';}});
      };
      loadTileWave();
    }
    thumbnailCache.retain('occurrence',wantedWaves);
    if(focused!==undefined&&focused!==null){const target=host.querySelector(`[data-occ-index="${focused}"] ${focusInput?'input':'button'}`);if(target&&target!==document.activeElement)target.focus({preventScroll:true});}
    if(occurrenceFocus){
      const {index,token:focusToken,id:focusId}=occurrenceFocus;
      if(focusToken!==token||focusId!==id||document.activeElement!==host||index<g.visibleFirst-1||index>=g.visibleLast)occurrenceFocus=null;
      else{const target=host.querySelector(`[data-occ-index="${index}"] button`);if(target){occurrenceFocus=null;target.focus({preventScroll:true});}}
    }
  }
  async function refreshReport(navigation={}){
    if(!state.caseId||!state.report)return;
    if(navigation.viewOnly&&reportData&&!state.reportEvidenceLoading&&!state.reportEvidenceError&&!state.reportStale&&state.reportViewContext===reportViewContext(reportData))return refreshReportView(navigation);
    const dock=qs('.report-conclusion-dock');if(dock&&qs('#reportV2Content')?.contains(dock))qs('#reportV2').after(dock);
    const id=state.caseId,caseToken=state.caseRequestId,token=++reportToken;++waveToken;++reportRenderToken;
    state.reportReadAbort?.abort();const controller=typeof AbortController==='undefined'?null:new AbortController();state.reportReadAbort=controller;
    const current=()=>token===reportToken&&id===state.caseId&&caseToken===state.caseRequestId;
    const retain=reportData&&state.reportViewContext===reportViewContext(reportData);
    if(!retain){reportData=null;selectedLookup=new Map();state.reportViews=new Map();state.reportBookmarks=new Map();}
    state.reportViewLoading=false;state.reportViewError=null;state.reportEvidenceLoading=true;state.reportEvidenceError=false;
    renderReportShell();
    const host=qs('#reportV2Content');host.inert=true;host.setAttribute?.('aria-busy','true');
    if(!retain)host.innerHTML='<p class="empty-state">读取已确认结果…</p>';
    try{
      const remote=await endpoint('report',{},id,controller?{signal:controller.signal}:{});
      if(!current())return;
      ECGReportConsistency.receive(state,remote);
      if(reportCase!==id){reportTimeRange=null;reportOffset=0;reportMode='all';pauseBand='all';reportSpacing=0;}
      if(navigation.focusEvent)reportSpacing=0;
      if(reportCase!==id||(!state.reportDirty&&reportVersion!==state.report.version)){
        state.reportComposition={...copy(state.report.composition||{}),schema_version:2};reportCase=id;reportVersion=state.report.version;
      }
      state.reportComposition=composition();
      const data=await endpoint('report-events',reportViewParams(navigation),id,controller?{signal:controller.signal}:{});
      if(!current())return;
      if((data.analysis_basis!==undefined&&remote.current_analysis_basis&&data.analysis_basis!==remote.current_analysis_basis.digest)||(data.analysis_revision!==undefined&&data.analysis_revision!==remote.review_revision))throw Error('读取期间病例依据已变化，请重新加载');
      const freshLookup=new Map(data.items.map(e=>[e.event_id,e]));
      for(let i=0;i<selected().length;i+=100){const result=await endpoint('report-events',{ids:selected().slice(i,i+100).map(e=>e.event_id).join('|'),limit:200},id,controller?{signal:controller.signal}:{});if(!current())return;if(!sameEvidence(result,data))throw Error('读取期间事件依据已变化，请重新加载');result.items.forEach(e=>freshLookup.set(e.event_id,e));}
      syncWaveEvidence(id,data);reportData=data;selectedLookup=freshLookup;state.reportEvidenceLoading=false;
      const context=reportViewContext(data);if(state.reportViewContext!==context){state.reportViews=new Map();state.reportBookmarks=new Map();}state.reportViewContext=context;state.reportDisplayedCategory=category;
      state.reportViews?.set(reportViewKey(reportViewParams(),data),data);host.inert=false;host.setAttribute?.('aria-busy','false');
      reportOffset=data.offset;
      if(navigation.focusEvent){
        active=data.items.find(e=>e.event_id===navigation.focusEvent.event_id&&e.basis_version===navigation.focusEvent.basis_version);
        if(!active)throw Error('未找到目标事件，请重新选择；未跳转到其他事件');
      }else if(navigation.edge)active=navigation.edge==='last'?data.items.at(-1):data.items[0];
      const before=JSON.stringify(composition().diagnosis_blocks);syncText();if(before!==JSON.stringify(composition().diagnosis_blocks))dirty();
      renderReportShell();await renderReportBody();if(current())rememberReportView();
    }catch(error){if(!current()||error.name==='AbortError')return;reportData=null;selectedLookup=new Map();state.reportViews=new Map();state.reportBookmarks=new Map();state.reportViewContext=null;state.reportEvidenceLoading=false;state.reportEvidenceError=true;host.inert=false;host.setAttribute?.('aria-busy','false');renderReportShell();host.innerHTML=`<p class="empty-state">加载失败：${esc(error.message)}。不能据此认定无事件。</p><button id="reportRetry" class="button secondary">重新加载</button><button id="reportRecoverList" class="button secondary">返回候选列表</button>`;qs('#reportRetry')?.addEventListener('click',()=>run(()=>refreshReport(navigation)));qs('#reportRecoverList')?.addEventListener('click',()=>{active=null;reportOffset=0;run(refreshReport)});throw error;}
  }
  function reportViewContext(data){return JSON.stringify([state.caseId,state.caseRequestId,data?.data_version,data?.analysis_basis,data?.analysis_revision]);}
  function reportViewParams(navigation={}){return {category:A.categories.some(([k])=>k===category)?category:'all',mode:reportMode,offset:reportOffset,limit:50,sort:reportSort,candidate_spacing_s:reportSpacing,pause_band:pauseBand,fast_slow_mode:reportSequence(),...(reportTimeRange?{time_start:reportTimeRange[0],time_end:reportTimeRange[1]}:{}),...(navigation.focusEvent?{locate_event:navigation.focusEvent.event_id,locate_basis:navigation.focusEvent.basis_version}:{})};}
  function reportViewKey(params,data=reportData){return JSON.stringify([reportViewContext(data),category,params]);}
  function rememberReportView(){
    if(!reportData||state.reportDisplayedCategory!==category||state.reportViewContext!==reportViewContext(reportData))return;
    const host=qs('#reportV2Content'),disclosures=Array.from(host?.querySelectorAll?.('details')||[]).filter(d=>d.open).map(d=>d.className);
    state.reportBookmarks ||=new Map();state.reportBookmarks.set(category,{mode:reportMode,offset:reportOffset,sort:reportSort,spacing:reportSpacing,pauseBand,range:reportTimeRange,active:typeof active==='undefined'?null:active?.event_id,scroll:qs('.v2-event-list')?.scrollTop||0,disclosures});
  }
  function chooseReportCategory(next){
    if(next===category&&!state.reportViewLoading&&!state.reportViewError)return;
    rememberReportView();reportReturn=null;category=next;
    const saved=state.reportBookmarks?.get(next);reportMode=saved?.mode||'all';reportOffset=saved?.offset||0;reportSort=saved?.sort||'hr_desc';reportSpacing=saved?.spacing||0;pauseBand=saved?.pauseBand||'all';reportTimeRange=saved?.range||null;
    return refreshReport({viewOnly:true,restoreView:saved});
  }
  async function refreshReportView(navigation={}){
    const id=state.caseId,caseToken=state.caseRequestId,basis=reportData,viewCategory=category,token=++reportToken;++reportRenderToken;++waveToken;
    state.reportReadAbort?.abort();const controller=new AbortController();state.reportReadAbort=controller;
    const current=()=>token===reportToken&&id===state.caseId&&caseToken===state.caseRequestId&&viewCategory===category&&state.reportViewContext===reportViewContext(basis);
    const host=qs('#reportV2Content'),previousCategory=state.reportDisplayedCategory,focused=typeof document==='undefined'?null:document.activeElement,focusId=host.contains?.(focused)?focused?.id:null;
    const viewState=navigation.restoreView||{scroll:qs('.v2-event-list')?.scrollTop||0,disclosures:Array.from(host.querySelectorAll?.('details')||[]).filter(d=>d.open).map(d=>d.className)};
    state.reportViewLoading=true;state.reportViewError=null;renderReportShell();host.inert=true;host.setAttribute?.('aria-busy','true');
    try{
      if(navigation.focusEvent)reportSpacing=0;
      if(A.categories.some(([k])=>k===viewCategory)){
        const params=reportViewParams(navigation),key=reportViewKey(params,basis),cached=state.reportViews?.get(key);
        const data=await endpoint('report-events',{...params,analysis_basis:basis.analysis_basis,analysis_revision:basis.analysis_revision},id,{signal:controller.signal});
        if(!current())return;if(!sameEvidence(data,basis))throw Error('事件依据已变化，请载入最新版本后复核');
        // An identical validated response retains event object identity and cache bindings.
        reportData=cached&&JSON.stringify(cached)===JSON.stringify(data)?cached:data;
        state.reportViews?.set(key,reportData);reportData.items.forEach(e=>selectedLookup.set(e.event_id,e));reportOffset=reportData.offset;
        if(navigation.focusEvent){active=reportData.items.find(e=>e.event_id===navigation.focusEvent.event_id&&e.basis_version===navigation.focusEvent.basis_version);if(!active)throw Error('未找到目标事件，请重新选择；未跳转到其他事件');}
        else if(navigation.edge)active=navigation.edge==='last'?reportData.items.at(-1):reportData.items[0];
        else if(navigation.restoreView)active=reportData.items.find(e=>e.event_id===navigation.restoreView.active)||null;
      }
      if(!current())return;state.reportDisplayedCategory=viewCategory;state.reportViewLoading=false;host.inert=false;host.setAttribute?.('aria-busy','false');renderReportShell();const rendered=renderReportBody();
      if(previousCategory===viewCategory&&focusId)qs('#'+focusId)?.focus({preventScroll:true});
      if(previousCategory===viewCategory||navigation.restoreView)Array.from(host.querySelectorAll?.('details')||[]).forEach(d=>{if(viewState.disclosures?.includes(d.className))d.open=true;});
      await rendered;
      if(current()&&(previousCategory===viewCategory||navigation.restoreView)&&qs('.v2-event-list'))qs('.v2-event-list').scrollTop=viewState.scroll;
      if(current())rememberReportView();
    }catch(error){
      if(!current()||error.name==='AbortError')return;
      if(/依据已变化/.test(error.message)){state.reportStale=true;state.reportViews=new Map();state.reportBookmarks=new Map();}
      state.reportViewLoading=false;state.reportViewError={category:viewCategory,message:error.message};host.inert=true;host.setAttribute?.('aria-busy','false');renderReportShell();
      const notice=qs('#reportViewStatus');notice?.querySelector('[data-report-view-retry]')?.addEventListener('click',()=>run(()=>refreshReport({viewOnly:true,...navigation})));
      notice?.querySelector('[data-report-view-reload]')?.addEventListener('click',()=>run(refreshReport));
    }
  }
  // A saved NN strip remains reviewable even when output is configured as RR.
  // Explicit sequence filtering is a view choice, never a print-mode mutation.
  function reportSequence(){return ['fastest','slowest'].includes(category)&&['RR','NN'].includes(reportMode)?reportMode.toLowerCase():composition().fast_slow_mode;}
  let rhythmReturn=null,rhythmOpening=false;
  function hasRhythmReturn(){return !!rhythmReturn&&rhythmReturn.id===state.caseId&&rhythmReturn.caseToken===state.caseRequestId;}
  function rhythmReviewButton(e,index){return e?.category==='AF'&&e.rhythm_episode_id?`<button type="button" data-review-rhythm="${index}">保存草稿并复核片段</button>`:'';}
  async function openRhythmReview(index){
    if(rhythmOpening||state.reportSaving)throw Error('正在保存或定位，请等待完成');
    ECGReportRange.assertApplied?.();
    const selection=index==='active'?selected().find(s=>s.event_id===active?.event_id):selected()[Number(index)],e=index==='active'?active:selection?selectedLookup.get(selection.event_id):null;
    if(!e?.rhythm_episode_id||e.category!=='AF')throw Error('找不到对应片段，请重新读取并选择；未跳到其他片段');
    if(state.reportStale||!reportData||state.reportEvidenceLoading||state.reportEvidenceError)throw Error('请先完整载入当前报告依据');
    const origin={id:state.caseId,caseToken:state.caseRequestId,category,event_id:e.event_id,episode_id:e.rhythm_episode_id,selection:!!selection};
    const basis=ECGAnalysisConsistency.identity(reportData);
    rhythmOpening=true;
    try{
      if(state.reportDirty)await save('draft');
      if(origin.id!==state.caseId||origin.caseToken!==state.caseRequestId||state.currentPage!=='report')return;
      ECGReportRange.assertApplied?.();
      if(state.reportDirty||state.reportSaving||state.reportStale)throw Error('仍有未保存或已变化的内容，保留在报告中；请核对后重试');
      ECGAnalysisConsistency.assertSame(basis,reportData);
      if(selection&&!selected().some(s=>s.event_id===selection.event_id&&s.basis_version===selection.basis_version))throw Error('选图已变化，请重新选择');
      rhythmReturn=origin;goPage('review');
      if(state.currentPage!=='review')return;
      await overviewWorkbench.openReportEpisode(origin.episode_id,basis,origin.id,origin.caseToken);
    }finally{rhythmOpening=false;}
  }
  async function returnFromRhythm(){
    if(!hasRhythmReturn())return;
    const origin=rhythmReturn;category=origin.category;reportOffset=0;reportMode='all';reportTimeRange=null;reportReturn=null;
    goPage('report');
    if(state.currentPage!=='report')return;
    await refreshReport();
    if(!hasRhythmReturn()||origin!==rhythmReturn||state.currentPage!=='report')return;
    const notice=qs('#reportRhythmReturn');notice?.scrollIntoView({block:'center'});notice?.focus({preventScroll:true});
  }
  function renderRhythmReturn(){
    let host=qs('#reportRhythmReturn');
    if(!host){host=document.createElement('section');host.id='reportRhythmReturn';host.className='v2-event-navigation';host.tabIndex=-1;host.setAttribute('aria-label','房颤片段复核返回');qs('#reportV2Notice').after(host);}
    host.hidden=!hasRhythmReturn();if(host.hidden)return;
    host.innerHTML='<strong>片段复核返回</strong><p>原选图、导联、图注和报告正文仍保留。片段修改后，旧图条必须重新核对；返回不代表确认或审核。</p><div class="v2-review-actions"><button type="button" data-rhythm-current>核对当前片段图条</button><button type="button" data-rhythm-dismiss>结束此次往返</button></div>';
    host.querySelector('[data-rhythm-current]').onclick=()=>run(viewReturnedRhythm);
    host.querySelector('[data-rhythm-dismiss]').onclick=()=>{rhythmReturn=null;renderRhythmReturn();};
  }
  async function viewReturnedRhythm(){
    if(!hasRhythmReturn()||!reportData||state.reportEvidenceLoading||state.reportEvidenceError)throw Error('请先载入报告依据');
    ECGReportRange.assertApplied?.();
    const origin=rhythmReturn,basis=ECGAnalysisConsistency.identity(reportData),token=reportToken;
    const data=await endpoint('report-events',{ids:[origin.event_id,'annotation:af:'+origin.episode_id].join('|'),limit:2,...basis},origin.id);
    if(!hasRhythmReturn()||origin!==rhythmReturn||token!==reportToken||state.currentPage!=='report')return;
    ECGAnalysisConsistency.assertSame(basis,data);
    const candidates=data.items.filter(e=>e.category==='AF'&&e.rhythm_episode_id===origin.episode_id);
    if(candidates.length!==1)throw Error('原片段已删除、已排除或无法唯一定位。原图条保留供核对，请手动移除；未跳到其他片段。');
    const e=candidates[0];category='AF';reportMode=e.subtype;reportOffset=0;reportTimeRange=null;
    await refreshReport({viewOnly:true,focusEvent:e});
    if(hasRhythmReturn()&&origin===rhythmReturn)focusEventNavigation();
  }
  function returnedRhythmSelection(e){
    return hasRhythmReturn()&&rhythmReturn.selection&&e?.category==='AF'&&e.rhythm_episode_id===rhythmReturn.episode_id?selected().find(s=>s.event_id===rhythmReturn.event_id&&(s.event_id!==e.event_id||s.basis_version!==e.basis_version)):null;
  }
  function returnedRhythmSettings(e){
    const old=returnedRhythmSelection(e);
    return old?ECGReportEngine.settings({leads:old.leads,duration_s:7}):null;
  }
  async function replaceReturnedRhythm(){
    ECGReportRange.assertApplied?.();
    const e=active,old=returnedRhythmSelection(e);
    if(!reportWaveReady||!old||!reportData?.items.includes(e)||state.reportStale||state.reportSaving)throw Error('请先读取当前片段波形，核对后再替换');
    replaceRhythmSelection(e,returnedRhythmSettings(e));category=rhythmReturn.category;
    renderReportShell();await renderReportBody();
    toast('已替换原图条，保留导联与图注；区间恢复自动 7 秒／至少 5 搏，请核对并保存草稿');
  }
  function replaceRhythmSelection(e,spec){
    const old=returnedRhythmSelection(e);
    if(!old)throw Error('原选图已变化，请重新核对');
    if(selected().some(s=>s!==old&&s.event_id===e.event_id))throw Error('当前片段已另行入报，请核对并移除重复的旧图条');
    const index=selected().indexOf(old);
    state.reportComposition.selected_events[index]={...spec,event_id:e.event_id,basis_version:e.basis_version,caption:old.caption};
    delete state.reportComposition.category_reviews.AF;
    state.reportComposition.diagnosis_blocks.forEach(b=>{if(b.key.startsWith('AF:')){b.acknowledged=false;if(b.manual)b.needs_review=true;}});
    rhythmReturn.event_id=e.event_id;syncText();dirty();
  }
  async function backToReportEvent(index){
    const selection=selected()[index],e=selection&&selectedLookup.get(selection.event_id);
    if(!e||e.basis_version!==selection.basis_version)throw Error('图条依据已失效，请重新选择');
    reportReturn={id:state.caseId,category,event_id:e.event_id};
    category=e.category;reportOffset=0;reportMode=e.subtype;reportTimeRange=null;pauseBand='all';
    await refreshReport({viewOnly:true,focusEvent:e});
    if(reportReturn?.id===state.caseId)focusEventNavigation();
  }
  function focusEventNavigation(){const nav=qs('#v2EventNavigation');nav?.scrollIntoView({block:'start'});nav?.focus({preventScroll:true});}
  async function returnToReport(){
    const destination=reportReturn;if(!destination||destination.id!==state.caseId)return;
    category=destination.category;reportOffset=0;reportMode='all';reportTimeRange=null;reportReturn=null;
    await refreshReport({viewOnly:true});
    if(destination.id!==state.caseId||category!==destination.category)return;
    const index=selected().findIndex(s=>s.event_id===destination.event_id);
    const button=qs(`[data-back-event="${index}"]`);button?.scrollIntoView({block:'center'});button?.focus({preventScroll:true});
  }
  function renderEventNavigation(ready=false){
    const host=qs('#v2EventNavigation');if(!host||!reportData)return;
    reportWaveReady=ready;
    const local=reportData.items.findIndex(e=>e.event_id===active?.event_id),position=local<0?-1:reportOffset+local;
    const included=selected().some(s=>s.event_id===active?.event_id&&s.basis_version===active?.basis_version);
    host.innerHTML=`<div class="v2-review-position" role="status">${position<0?'无可核查事件':`第 ${position+1} / ${reportData.total} 条 · ${formatElapsed(active.time_s)}`}</div><div class="v2-review-actions"><button type="button" data-review-step="-1" aria-label="上一条" ${position<=0?'disabled':''}>‹</button><button type="button" data-review-step="1" aria-label="下一条" ${position<0||position+1>=reportData.total?'disabled':''}>›</button><button type="button" data-review-include aria-pressed="${included}" ${!ready?'disabled':''}>${included?'移出报告草稿':'加入报告草稿'}</button><button type="button" data-review-undo ${selectionUndoCurrent()?'':'disabled'}>${reportSelectionUndo?.before?'撤销移出':'撤销入报'}</button>${reportReturn?.id===state.caseId?'<button type="button" data-review-return>返回入报图条</button>':''}</div><small>入报后自动下一条；取消不跳转。草稿需独立诊断确认，游标修改须应用。</small>`;
    host.querySelectorAll('[data-review-step]').forEach(b=>b.onclick=()=>run(()=>stepReportEvent(Number(b.dataset.reviewStep))));
    host.querySelectorAll('[data-review-step]').forEach(b=>{b.title=b.disabled?(position<0?'当前没有可核查的事件':Number(b.dataset.reviewStep)<0?'已是当前筛选的第一条':'已是当前筛选的最后一条'):'按当前筛选和排序查看'+(Number(b.dataset.reviewStep)<0?'上一条':'下一条')+'事件';});
    host.querySelector('[data-review-include]').title=!ready?'请等待当前事件波形读取完成，或在失败后重试':included?'仅移出报告草稿，保留事件和诊断复核状态':'加入报告草稿；最终审核前仍需独立诊断确认';
    host.querySelector('[data-review-include]').onclick=()=>run(async()=>{if(reportWaveReady&&active&&reportData.items.some(e=>e===active)){await selectEvent(active,!included);focusEventNavigation();}});
    host.querySelector('[data-review-undo]').title='撤销本窗口上一次入报或移出，恢复原图注、导联和已应用区间；不恢复诊断或报告审核确认';host.querySelector('[data-review-undo]').onclick=()=>run(undoReportSelection);
    host.querySelector('[data-review-return]')?.addEventListener('click',()=>run(returnToReport));
    host.querySelector('.v2-review-actions').insertAdjacentHTML('beforeend',rhythmReviewButton(active,'active'));
    if(returnedRhythmSelection(active)){
      host.querySelector('[data-review-include]').disabled=true;
      host.querySelector('[data-review-include]').title='此事件对应旧入报图条，请核对后使用“用当前片段替换原图条”';
      host.insertAdjacentHTML('beforeend','<p>替换时保留原导联和图注；原人工区间将重置为自动 7 秒／至少 5 搏。当前预览使用这一新区间。也可拖动游标后“应用区间”，以人工区间替换原图条，不重复添加。</p><div class="v2-review-actions"><button type="button" data-rhythm-replace '+(!ready?'disabled':'')+'>用当前片段替换原图条</button></div>');
    }
  }
  async function stepReportEvent(delta){
    if(!reportData||![-1,1].includes(delta))return;
    const local=reportData.items.findIndex(e=>e.event_id===active?.event_id),position=reportOffset+local+delta;
    if(local<0||position<0||position>=reportData.total)return;
    if(local+delta>=0&&local+delta<reportData.items.length)await locate(reportData.items[local+delta]);
    else{reportOffset=Math.floor(position/50)*50;await refreshReport({viewOnly:true,edge:delta<0?'last':'first'});}
    focusEventNavigation();
  }
  function syncText(){
    const c=state.reportComposition,keys=new Map();selected().forEach(s=>{const e=selectedLookup.get(s.event_id);if(e&&e.basis_version===s.basis_version)keys.set(e.category+':'+e.subtype,e.label)});
    const blocks=[];for(const b of c.diagnosis_blocks||[]){if(keys.has(b.key)){blocks.push(b);keys.delete(b.key);}else if(b.manual)blocks.push({...b,needs_review:!b.acknowledged});}
    keys.forEach((text,key)=>blocks.push({key,text,manual:false,needs_review:false,acknowledged:false}));c.diagnosis_blocks=blocks;
  }
  function selectionUndoCurrent(){const undo=reportSelectionUndo;if(!undo||undo.id!==state.caseId||undo.caseToken!==state.caseRequestId||undo.scope!==waveEvidenceScope||state.reportStale||state.reportSaving||state.reportEvidenceLoading||state.reportViewLoading||state.reportViewError)return false;const current=selected().find(s=>s.event_id===undo.event.event_id)||null;return JSON.stringify(current)===JSON.stringify(undo.after);}
  async function undoReportSelection(){
    if(!selectionUndoCurrent())return;const undo=reportSelectionUndo;reportSelectionUndo=null;const c=state.reportComposition;
    c.selected_events=c.selected_events.filter(s=>s.event_id!==undo.event.event_id);if(undo.before)c.selected_events.splice(Math.min(undo.index,c.selected_events.length),0,copy(undo.before));
    selectedLookup.set(undo.event.event_id,undo.event);delete c.category_reviews[undo.event.category];c.diagnosis_blocks.forEach(block=>{if(block.key===undo.event.category+':'+undo.event.subtype){block.acknowledged=false;if(block.manual)block.needs_review=true;}});syncText();dirty();renderReportShell();
    await renderReportBody();
  }
  function selectEvent(e,checked,settings=null){
    if(checked&&returnedRhythmSelection(e))throw Error('该片段有待替换的旧图条，请先查看当前波形并使用“用当前片段替换原图条”，保留原导联与图注');
    const undoIndex=selected().findIndex(s=>s.event_id===e.event_id),undoBefore=undoIndex<0?null:copy(selected()[undoIndex]);
    const wasIncluded=selected().some(s=>s.event_id===e.event_id&&s.basis_version===e.basis_version),advanceCase=state.caseId,advanceCaseToken=state.caseRequestId,advanceData=reportData,advanceCategory=category,advanceScope=waveEvidenceScope;
    const c=state.reportComposition;selectedLookup.set(e.event_id,e);
    c.selected_events=c.selected_events.filter(s=>s.event_id!==e.event_id);
    if(checked)c.selected_events.push({event_id:e.event_id,basis_version:e.basis_version,caption:e.label,...ECGReportEngine.settings(settings||c.strip_defaults)});
    if(settings===null&&A.categories.some(([key])=>key===category))reportSelectionUndo={id:advanceCase,caseToken:advanceCaseToken,scope:advanceScope,event:copy(e),before:undoBefore,index:Math.max(0,undoIndex),after:copy(c.selected_events.find(s=>s.event_id===e.event_id)||null)};
    delete c.category_reviews[e.category];c.diagnosis_blocks.forEach(b=>{if(b.key===e.category+':'+e.subtype){b.acknowledged=false;if(b.manual)b.needs_review=true}});syncText();dirty();renderReportShell();
    // Explicitly applied settings change the range baseline and need a new editor.
    if(settings===null&&state.reportDisplayedCategory===category&&reportData?.items&&A.categories.some(([key])=>key===category)){
      document.querySelectorAll('[data-include]').forEach(control=>{const event=reportData.items[Number(control.dataset.include)],included=selected().some(s=>s.event_id===event?.event_id&&s.basis_version===event?.basis_version);control.checked=included;control.closest('tr')?.setAttribute('aria-selected',String(included));});
      const wave=qs('#v2EventWave');if(wave)wave.dataset.reportSelected=String(selected().some(s=>s.event_id===active?.event_id&&s.basis_version===active?.basis_version));
      document.querySelectorAll('.report-range-editor').forEach(editor=>{if(editor._rangeEventId===e.event_id)editor._rangeSetMembership?.(checked);});
      renderEventNavigation(reportWaveReady);const complete=qs('#v2Complete');if(complete){const reviewed=c.category_reviews[category]===reportData.basis_versions[category];complete.setAttribute('aria-pressed',String(reviewed));complete.textContent=reviewed?'✓ 本类筛选已完成':'确认本类筛选完成';}
      if(checked&&!wasIncluded)return run(async()=>{
        const current=()=>advanceCase===state.caseId&&advanceCaseToken===state.caseRequestId&&advanceData===reportData&&advanceCategory===category&&advanceScope===waveEvidenceScope&&state.currentPage==='report'&&!state.reportViewLoading&&!state.reportViewError&&!state.reportEvidenceLoading&&selected().some(s=>s.event_id===e.event_id&&s.basis_version===e.basis_version);
        if(!current())return;const local=reportData.items.findIndex(item=>item.event_id===e.event_id);if(local<0)return;const next=reportOffset+local+1;
        if(next>=reportData.total){if(active?.event_id!==e.event_id)await locate(e);return;}
        if(local+1<reportData.items.length)await locate(reportData.items[local+1]);
        else if(current()){reportOffset=Math.floor(next/50)*50;await refreshReport({viewOnly:true,edge:'first'});}
      });
      return Promise.resolve();
    }
    return run(renderReportBody);
  }
  function removeReportSelection(index){
    const entry=selected()[index];if(!entry)return;
    const event=selectedLookup.get(entry.event_id);
    if(event){selectEvent(event,false);return;}
    state.reportComposition.selected_events.splice(index,1);
    syncText();dirty();renderReportShell();run(renderReportBody);
  }
  function enableReportDraftSelections(items){
    document.querySelectorAll('[data-include]').forEach(control=>{const e=items[Number(control.dataset.include)];if(!e)return;const confirmed=e.diagnosis_status==='confirmed',status=control.closest('tr')?.querySelector('[data-event-status]'),replacement=!!returnedRhythmSelection(e);control.disabled=replacement;control.title=replacement?'先查看当前波形，再用当前片段替换原图条，保留导联与图注':confirmed?'加入报告':'可先加入报告草稿；最终审核前需完成诊断确认';control.setAttribute('aria-label',`${formatElapsed(e.time_s)} ${e.label}${replacement?'需核对并替换旧图条':confirmed?'加入报告':'加入报告草稿（待诊断确认）'}`);if(status&&!confirmed)status.textContent=`${e.beat_count} 搏 · 待诊断确认，可先入草稿`;if(status){status.title=status.textContent;status.textContent=`${e.beat_count} 搏 · ${confirmed?'已确认':'待确认'}`;}});
  }
  function bindReportSelection(node,e){
    if(!node||!e||!globalThis.ECGChartInspection)return;
    const id=state.caseId,caseToken=state.caseRequestId,scope=waveEvidenceScope,data=reportData;
    const current=()=>node.isConnected&&id===state.caseId&&caseToken===state.caseRequestId&&scope===waveEvidenceScope&&data===reportData&&state.currentPage==='report'&&!state.reportEvidenceLoading&&!state.reportViewLoading&&!state.reportViewError;
    node.tabIndex=0;node.dataset.reportEventId=e.event_id;
    const included=selected().some(s=>s.event_id===e.event_id&&s.basis_version===e.basis_version);
    node.dataset.reportSelected=String(included);
    if(node.tagName==='TR')node.setAttribute('aria-selected',String(included));
    else{node.setAttribute('role','group');node.setAttribute('aria-label',`${e.label} · ${included?'已加入报告草稿':'未加入报告草稿'}`);}
    node.setAttribute('aria-description','单击或空格/Enter 切换入报；新入报后自动下一条，取消保持当前位置。文字拖选和内部控件分别操作。');
    const toggle=()=>{
      if(!current())return;
      const control=[...document.querySelectorAll('[data-include]')].find(n=>reportData.items[Number(n.dataset.include)]?.event_id===e.event_id);
      if(!control||control.disabled)return;
      const hadFocus=document.activeElement===node,wave=node.id==='v2EventWave';
      const task=selectEvent(e,!selected().some(s=>s.event_id===e.event_id&&s.basis_version===e.basis_version));
      if(hadFocus)task.then(()=>{if(id!==state.caseId||caseToken!==state.caseRequestId)return;const replacement=wave?qs('#v2EventWave'):[...document.querySelectorAll('tr[data-report-event-id]')].find(n=>n.dataset.reportEventId===e.event_id);replacement?.focus({preventScroll:true});});
    };
    ECGChartInspection.bindSelection(node,toggle,{isCurrent:current});
  }
  function updateReportPaper(host,paper=composition().paper){
    host.querySelectorAll('.v2-paper-sheet').forEach(page=>{page.dataset.paperSize=String(paper.size||'A4').toUpperCase();page.dataset.orientation=paper.orientation||'portrait'});
  }
  function renumberReportPapers(host){
    const pages=[...host.querySelectorAll('.v2-paper-sheet')];pages.forEach((page,index)=>{const counter=page.querySelector('[data-paper-counter]'),suffix=counter?.dataset.suffix;if(counter)counter.textContent=`第 ${index+1} / ${pages.length} 页${suffix?' · '+suffix:''}`;page.setAttribute('aria-label',`${page.querySelector('.v2-paper-heading strong')?.textContent||'报告'}，第 ${index+1} 页，共 ${pages.length} 页`)});
  }
  function paperShell(title,body,className=''){
    return `<section class="v2-paper-sheet ${className}"><header class="v2-paper-heading"><strong>${esc(title)}</strong><span data-paper-counter></span></header><div class="v2-paper-body">${body}</div></section>`;
  }
  function diagnosisBlocksHtml(){return composition().diagnosis_blocks.map((b,i)=>`<label class="v2-text-block">${esc(b.key)}${b.needs_review?' · 依据已变化，请核对':''}<textarea data-block="${i}" rows="2">${esc(b.text)}</textarea>${b.needs_review?`<button data-ack="${i}" type="button">已核对，保留人工文字</button>`:''}</label>`).join('')||'<p class="empty-state">当前没有诊断文字块。</p>'}
  function reportTemplateName(t,e){
    const name=String(t.name||'').trim();if(name.length<=12&&!/-[a-z0-9]{6,}$/i.test(name))return name||'未命名模板';
    const id=String(t.id??name);let hash=2166136261;for(const c of id)hash=Math.imul(hash^c.charCodeAt(0),16777619);
    return `${['N','S','V'].includes(e.category)?e.category:'形态'}模板 ${/^\d{1,6}$/.test(id)?id:(hash>>>0).toString(36).padStart(7,'0')}`;
  }
  function reportTemplateCell(e){
    const templates=e.templates||[],short=templates.map(t=>reportTemplateName(t,e)).join(' / ')||'—';
    return `<strong class="v2-template-short">${esc(short)}</strong><span class="v2-event-subtype">${esc(e.label)}</span>${templates.length?`<details class="v2-event-source"><summary>原模板来源</summary><ul>${templates.map(t=>`<li><strong>${esc(reportTemplateName(t,e))}</strong><span>${esc(t.name||'未命名模板')}</span><small>模板 ID：${esc(t.id??'未提供')}</small></li>`).join('')}</ul></details>`:''}`;
  }
  function refreshPrivacyViews(phase=state.privacySaving||state.privacyIdentityPending?'pending':'ready'){
    // Identity snapshots are independent of the clinical context and range drafts.
    cancelReportExport();
    const preview=qs('#rwPaperPreview');if(preview){if(preview.open)preview.close();preview.textContent='';}
    qs('#v2PrintFrame')?.remove();
    const legacy=qs('#reportPreviewBody');if(legacy)legacy.textContent='';
    const strip=qs('#ovPrintSheet');if(strip){const dialog=strip.closest('dialog');if(dialog?.open)dialog.close();strip.remove();}
    const source=qs('#sourceReportDialog');if(source?.open)source.close();
    const image=qs('#sourceReportImage');if(image){image.hidden=true;image.removeAttribute('src');image.dataset.url='';}
    const privacy=qs('#sourceReportPrivacy');if(privacy)privacy.hidden=false;
    const ready=phase==='ready'&&!state.privacyIdentityPending,meta=state.caseData?.metadata||{},safe=ready&&(state.includePhi||state.caseData?.phi_masked===true);
    const placeholder=state.includePhi?'身份更新中':'已遮蔽';
    document.querySelectorAll('#reportHrvV2 .hrv-paper-preview .rp-running, #hrvWindowPanel .hrv-paper-preview .rp-running').forEach(header=>{
      const spans=header.querySelectorAll('span');
      if(spans[0])spans[0].textContent='患者 ID：'+(safe?(meta.patient_id||'已遮蔽'):placeholder)+(/^C\d{2,}$/.test(state.caseData?.display_case_id||'')?' · 病例：'+state.caseData.display_case_id:'');
      if(spans[1])spans[1].textContent='姓名：'+(safe?(meta.name||'—'):placeholder);
    });
    const busy=Boolean(state.privacySaving||state.privacyIdentityPending),original=qs('#openSourceReport'),visibleOriginal=Boolean(!busy&&state.includePhi&&state.caseData?.report_image_urls?.length);
    if(original){original.textContent=visibleOriginal?'原报告':'原报告说明';original.title=busy?'身份信息正在更新，请稍后查看':visibleOriginal?'查看当前病例原报告影像':'查看原报告影像的隐私遮蔽说明；不解除遮蔽';original.disabled=busy;}
    document.querySelectorAll('#printReport, [data-paper-preview], [data-hrv-export]').forEach(button=>{
      button.disabled=busy;button.setAttribute('aria-busy',String(busy));
      if(busy){if(button.dataset.privacyTitle===undefined)button.dataset.privacyTitle=button.title||'';button.title='身份信息正在更新，请稍后预览或导出';}
      else if(button.dataset.privacyTitle!==undefined){button.title=button.dataset.privacyTitle;delete button.dataset.privacyTitle;}
    });
    let status=qs('#reportPrivacyOutputStatus');
    if(!status&&qs('#downloadReport')){status=document.createElement('span');status.id='reportPrivacyOutputStatus';status.setAttribute('role','status');qs('#downloadReport').after(status);}
    if(status){status.hidden=!busy;status.textContent=state.privacySaving?'身份信息正在更新，预览和导出稍后恢复':state.privacyIdentityPending?'身份资料未读取，请使用右上角身份开关重试后预览或导出':'';}
    renderExportState();
    document.dispatchEvent?.(new Event('ecg-report-privacy-change'));
  }
  function renderReportShell(){
    state.reportCategoryPending=reportData?A.categories.filter(([key])=>reportData.category_counts[key]&&composition().category_reviews[key]!==reportData.basis_versions[key]).map(([key,label])=>({key,label})):[];
    if(!qs('#reportV2'))return;
    const original=qs('#openSourceReport'),visibleOriginal=Boolean(state.includePhi&&state.caseData?.report_image_urls?.length);
    if(original){original.textContent=visibleOriginal?'原报告':'原报告说明';original.title=visibleOriginal?'查看当前病例原报告影像':'查看原报告影像的隐私遮蔽说明；不解除遮蔽';}
    renderRhythmReturn();
    ECGReportRange.setContext?.(JSON.stringify([state.caseId,state.caseRequestId]));
    renderRangeDraftNotice();
    const nav=qs('#reportV2Nav');
    const navButton=([key,label])=>{const count=reportData?.category_counts[key],countSelected=selected().filter(s=>selectedLookup.get(s.event_id)?.category===key).length;return `<button type="button" data-category="${key}" class="${category===key?'active':''}" aria-current="${category===key?'page':'false'}"><span>${label}</span><small ${count===undefined?'hidden':''}>${count===undefined?'':`${countSelected} / ${count}`}</small></button>`};
    if(!nav.querySelector?.('[data-category]'))nav.innerHTML='<div class="v2-compose-tabs" role="group" aria-label="报告操作"><span>报告操作</span>'+[['final','报告编排'],['strips','图条设置'],['tables','数据表格']].map(navButton).join('')+'</div><div class="v2-candidate-tabs" role="group" aria-label="事件分类导航"><span>事件分类</span>'+A.categories.map(navButton).join('')+'</div>';
    else nav.querySelectorAll('[data-category]').forEach(button=>{const key=button.dataset.category,count=reportData?.category_counts[key],counter=button.querySelector('small');button.classList.toggle('active',key===category);button.setAttribute('aria-current',key===category?'page':'false');counter.hidden=count===undefined;counter.textContent=count===undefined?'':`${selected().filter(s=>selectedLookup.get(s.event_id)?.category===key).length} / ${count}`;});
    qs('#reportStatus').textContent=STATUS_TEXT[state.report.status]||state.report.status;qs('#reportVersion').textContent='v'+state.report.version;
    if(!state.reportDirty){const editor=qs('#conclusionEditor'),text=state.report.conclusion||'';if(editor.value!==text)editor.value=text;qs('#reportSaveState').textContent=state.report.updated_at?'已保存 '+state.report.updated_at:'尚未保存';updateConclusionCount();}
    qs('.report-conclusion-dock').hidden=category!=='final';
    const stale=selected().filter(s=>!selectedLookup.has(s.event_id)||selectedLookup.get(s.event_id).basis_version!==s.basis_version).length;
    qs('#reportV2Notice').textContent=state.reportEvidenceLoading?`正在核对报告依据；原有选图和人工文字保留${reportData?` · 下列计数仍为已读取依据 r${reportData.analysis_revision}，本次核对未完成`:''}`:state.reportEvidenceError?'报告依据未能完整读取，请重新加载后复核；不能认定无事件':`已选 ${selected().length} 条 · 统计为全记录${reportData?.analysis_revision!==undefined?' · 依据 r'+reportData.analysis_revision:''} · ${clinicalWorkflow.readiness()?"编辑 / ST‑T 已确认":"编辑 / ST‑T 待确认"}${state.reportCategoryPending.length?' · '+state.reportCategoryPending.length+' 类报告筛选待确认':''}${stale?' · '+stale+'条已失效，须重新核对；房颤片段可复核后替换，其余移除后重新筛选':''}`;
    let viewStatus=qs('#reportViewStatus');
    if(!viewStatus&&typeof document!=='undefined'){viewStatus=document.createElement('section');viewStatus.id='reportViewStatus';viewStatus.className='v2-view-status';viewStatus.setAttribute('role','status');qs('#reportV2Content').before(viewStatus);}
    if(viewStatus){
      viewStatus.hidden=!state.reportViewLoading&&!state.reportViewError;
      if(!viewStatus.hidden){const label=Object.fromEntries(tabs)[category]||category,oldLabel=Object.fromEntries(tabs)[state.reportDisplayedCategory]||'原视图';
        viewStatus.innerHTML=state.reportViewError?`<span>${esc(label)}读取失败：${esc(state.reportViewError.message)}。下方保留${esc(oldLabel)}，暂不可操作。</span><button type="button" data-report-view-retry>重试此类别</button><button type="button" data-report-view-reload>核对最新依据</button>`:`<span>正在读取${esc(label)} · 下方保留${esc(oldLabel)}的已读取结果</span><button type="button" data-report-view-cancel>取消读取</button>`;
        viewStatus.querySelector?.('[data-report-view-cancel]')?.addEventListener('click',()=>{
          state.reportReadAbort?.abort();++reportToken;++waveToken;state.reportViewLoading=false;state.reportViewError=null;category=state.reportDisplayedCategory||category;
          const saved=state.reportBookmarks?.get(category),restoreCase=state.caseId,restoreCaseToken=state.caseRequestId,restoreCategory=category,restoreHost=qs('#reportV2Content');
          if(saved){reportMode=saved.mode;reportOffset=saved.offset;reportSort=saved.sort;reportSpacing=saved.spacing;pauseBand=saved.pauseBand;reportTimeRange=saved.range;active=reportData.items.find(e=>e.event_id===saved.active)||null;}
          restoreHost.inert=false;restoreHost.setAttribute?.('aria-busy','false');renderReportShell();
          run(async()=>{const rendered=renderReportBody(),restoreRenderToken=reportRenderToken;await rendered;
            if(saved&&state.caseId===restoreCase&&state.caseRequestId===restoreCaseToken&&category===restoreCategory&&reportRenderToken===restoreRenderToken&&qs('#reportV2Content')===restoreHost){const list=qs('.v2-event-list');if(list)list.scrollTop=saved.scroll;}
          });
        });
      }
    }
    let conflict=qs('#reportConflict');
    if(!conflict){conflict=document.createElement('p');conflict.id='reportConflict';conflict.setAttribute('role','status');conflict.innerHTML='<span>病例或报告已有新版本。当前修改仍保留，请先复制需要保留的文字，再载入最新版本核对。</span> <button type="button" class="button secondary">载入最新版本</button>';qs('#reportV2Notice').after(conflict);conflict.querySelector('button').onclick=()=>run(reloadReport);}
    conflict.hidden=!state.reportStale;
    for(const key of ['saveReport','approveReport','returnReport']){
      const button=qs('#'+key);if(button)button.disabled=key==='approveReport'
        ?Boolean(state.reportViewLoading||state.reportViewError)||!ECGReportConsistency.canApprove(state,qs('#conclusionEditor').value,clinicalWorkflow.readiness(),clinicalWorkflow.writable())
        :Boolean(!clinicalWorkflow.writable()||state.reportSaving||state.reportStale);
    }
    // Reload/conflict responses can change report state without a workflow fetch.
    clinicalWorkflow.renderPreflight();
  }
  async function reloadReport(discard=false){
    globalThis.ECGAdvancedAnalysis?.assertApplied();
    ECGReportRange.assertApplied?.();
    if(state.reportDirty&&!discard){
      let dialog=qs('#reportReloadDialog');
      if(!dialog){
        dialog=document.createElement('dialog');dialog.id='reportReloadDialog';dialog.className='modal report-reload-dialog';dialog.setAttribute('aria-labelledby','reportReloadTitle');dialog.setAttribute('aria-describedby','reportReloadDescription');
        dialog.innerHTML='<form method="dialog"><header class="modal-header"><h2 id="reportReloadTitle">载入最新报告版本？</h2></header><p id="reportReloadDescription">本窗口未保存的结论和选图将被丢弃。需要保留时，请先取消并复制文字。</p><footer class="modal-actions"><button class="button secondary" value="cancel" autofocus>取消，保留当前修改</button><button class="button primary" value="reload">丢弃本窗口修改并载入</button></footer></form>';
        dialog.addEventListener('close',()=>{if(dialog.returnValue==='reload')run(()=>reloadReport(true));else qs('#reportConflict button')?.focus();});
        document.body.appendChild(dialog);
      }
      dialog.returnValue='cancel';dialog.showModal();return;
    }
    const id=state.caseId,caseRequest=state.caseRequestId,local=ECGReportConsistency.content(qs('#conclusionEditor').value,composition()),base=state.report;
    const remote=await endpoint('report',{},id);
    if(id!==state.caseId||caseRequest!==state.caseRequestId)return;
    globalThis.ECGAdvancedAnalysis?.assertApplied();
    ECGReportRange.assertApplied?.();
    if(local!==ECGReportConsistency.content(qs('#conclusionEditor').value,composition())||!ECGReportConsistency.sameBase(base,state.report)||state.reportSaving){
      state.reportStale=true;renderReportShell();throw Error('读取期间本窗口有新修改，已保留；请核对后再次载入最新版本');
    }
    state.report=remote;state.reportDirty=false;state.reportStale=false;
    state.reportComposition=copy(remote.composition);reportVersion=null;
    await refreshReport();
  }
  async function renderReportBody(){
    const host=qs('#reportV2Content');if(!host||!reportData)return;
    const bodyCase=state.caseId,bodyCaseToken=state.caseRequestId,bodyCategory=category,bodyToken=++reportRenderToken;
    const bodyCurrent=()=>bodyCase===state.caseId&&bodyCaseToken===state.caseRequestId&&bodyCategory===category&&bodyToken===reportRenderToken&&host===qs('#reportV2Content');
    const distributionOpen=renderReportBody.distributionOpen||(renderReportBody.distributionOpen=new Map()),previousDistributions=host.querySelector('.v2-candidate-distributions'),distributionKey=JSON.stringify([bodyCase,bodyCaseToken,bodyCategory]);
    if(previousDistributions?._reportCase===bodyCase&&previousDistributions._reportCaseToken===bodyCaseToken)distributionOpen.set(previousDistributions._reportDistributionKey,previousDistributions.open);
    const candidates=!['tables','strips','final'].includes(category);
    host.classList.toggle('report-candidate-workspace',candidates);
    qs('#page-report')?.classList.toggle('report-candidate-page',candidates);
    const dock=qs('.report-conclusion-dock');if(dock&&host.contains(dock))qs('#reportV2').after(dock);
    if(category==='tables'){host.innerHTML=statsTable()+'<div id="reportHrvV2"></div>';await loadHrv('#reportHrvV2');return;}
    if(category==='strips'||category==='final'){
      const token=bodyToken,id=state.caseId;
      if(category==='final'){
        ECGReportWorkspace.compose(host,{id,composition:composition(),selected:selected(),lookup:selectedLookup,sections:ECGReportSections.catalog(),overview:{categories:A.categories.map(([key,label])=>({label,events:reportData.confirmed_category_counts?.[key]??null,beats:reportData.confirmed_beat_counts?.[key]??null})),source:{total_beats:state.caseData.summary.total_beats,avg_hr:state.caseData.summary.avg_hr,sdnn_ms:state.caseData.summary.sdnn_ms},revision:reportData.analysis_revision},isCurrent:bodyCurrent,loadWave:async(e,s)=>{const entry=await reportStrip(e,s,id);if(!bodyCurrent())throw Error('报告视图已变化');return {...entry,waveform:await reportReviewWave(entry,id)};},renderWave:entry=>ECGReportWorkspace.reviewWaveSvg(entry.waveform,entry),onPages:pages=>{state.reportComposition.included_pages=pages;state.reportComposition.page_selection_version=1;state.reportComposition.include_hrv=pages.some(k=>k.startsWith('hrv_'));dirty()},onMode:mode=>{state.reportComposition=ECGReportWorkspace.withRateMode(state.reportComposition,mode);dirty();run(()=>refreshReport({viewOnly:true}))},onPreview:()=>run(previewPaper),renderAdvanced:panel=>mountAdvanced(panel,id)});
        if(composition().diagnosis_blocks.some(b=>b.needs_review))host.querySelector('#rwConclusionSlot').insertAdjacentHTML('afterbegin','<section aria-label="人工诊断文字复核"><h3>依据变化后，请重新核对人工文字</h3><p>原文字已保留；核对当前波形及报告正文后再确认。</p>'+diagnosisBlocksHtml()+'</section>');
        return;
      }
      host.innerHTML=stripSettingsHtml(composition().strip_defaults,'default')+'<div id="v2TextBlocks">'+diagnosisBlocksHtml()+'</div>'+selected().map((s,i)=>{const e=selectedLookup.get(s.event_id),valid=e&&e.basis_version===s.basis_version;return `<article class="rp-editor-strip"><header><strong>${i+1}. ${esc(e?.label||s.event_id)}${valid?'':'（已失效）'}</strong><div><button data-back-event="${i}">回看</button><button data-move="${i}" data-delta="-1" aria-label="图条上移" ${i===0?'disabled':''}>上移</button><button data-move="${i}" data-delta="1" aria-label="图条下移" ${i===selected().length-1?'disabled':''}>下移</button><button data-remove="${i}">移除</button></div></header><label>图注<input data-caption="${i}" value="${esc(s.caption)}" maxlength="500"></label>${stripSettingsHtml(s,String(i))}<div data-selected-wave="${i}">${valid?'读取波形…':'图条已失效，请重新筛选'}</div><p class="rp-strip-status" data-strip-status="${i}" aria-live="polite"></p></article>`}).join('')+(selected().length?'':'<p class="empty-state">尚未选择图条。在事件列表设置导联后勾选“入报”；也可以在这里修改每条图的导联与时长。</p>');
      selected().forEach((s,i)=>host.querySelector(`[data-back-event="${i}"]`).insertAdjacentHTML('afterend',rhythmReviewButton(selectedLookup.get(s.event_id),i)));
      await Promise.all(selected().map(async(s,i)=>{const e=selectedLookup.get(s.event_id),target=host.querySelector(`[data-selected-wave="${i}"]`);if(!e||e.basis_version!==s.basis_version)return;try{const entry=await reportStrip(e,s,id);if(bodyCurrent()&&target?.isConnected){target.innerHTML=ECGReportPaper.stripSvg(entry,composition().paper,s.leads?.length>6?880:s.leads?.length>3?520:276);host.querySelector(`[data-strip-status="${i}"]`).textContent=`${ECGReportEngine.reviewNote(entry)?ECGReportEngine.reviewNote(entry)+' · ':''}${formatElapsed(entry.waveform.start_s)}–${formatElapsed(entry.waveform.start_s+entry.waveform.duration_s)} · ${entry.strip.visible_beat_count} 搏 · ${entry.strip.warning||'时间窗满足至少 5 搏'}`;await mountRange(target,e,entry,id);}}catch(error){if(bodyCurrent()&&target?.isConnected)target.textContent='读取失败：'+error.message;}}));return;
    }
    const complete=composition().category_reviews[category]===reportData.basis_versions[category],items=reportData.items,rateCandidates=['fastest','slowest'].includes(category);
    const pageCount=Math.max(1,Math.ceil(reportData.total/50));
    host.innerHTML=`<div class="v2-category-bar"><strong>${Object.fromEntries(tabs)[category]} · ${reportData.total} 条${rateCandidates?'候选':''}</strong>
      <label>亚型<select id="v2Subtype"><option value="all">${rateCandidates?'全部序列':'全部（不叠加模式计数）'}</option>${Object.entries(reportData.subtype_counts).map(([k,n])=>`<option value="${k}" ${reportMode===k?'selected':''}>${esc(Object.fromEntries(A.patterns)[k]||k)} · ${n}</option>`).join('')}</select></label>
      ${rateCandidates?`<label>计算序列<select id="v2Fast"><option value="rr">RR</option><option value="nn">NN</option><option value="both">RR 与 NN</option></select></label><label>心率排序<select id="v2RateSort"><option value="hr_desc" ${reportSort==='hr_desc'?'selected':''}>从快到慢</option><option value="hr_asc" ${reportSort==='hr_asc'?'selected':''}>从慢到快</option></select></label>`:''}
      <button class="button ${complete?'secondary':'primary'}" id="v2Complete" aria-pressed="${complete}" ${!reportData.category_counts[category]?'disabled':''}>${complete?'✓ 本类筛选已完成':'确认本类筛选完成'}</button></div>
      ${rateCandidates?`<div class="v2-rate-help"><p>RR / NN 单间期瞬时心率，非 7 秒平均心率。每序列最多 200 条，短记录按实显示。</p><p role="status">当前时间／序列内 ${reportData.candidate_unspaced_total} 条 · 显示 ${reportData.total} 条 · 间隔隐藏 ${reportData.candidate_hidden_count} 条。“全部候选”可恢复。</p><details><summary>间隔筛选说明</summary><p>只精简当前列表的相邻定位点，优先保留本类极值，RR / NN 分开；不保证图条无重叠，不改变统计或已选图条。柱图保留未按间隔精简的分布。回看入报图条或待应用游标时自动恢复全部候选。</p></details></div>`:''}
      <div class="v2-event-layout"><div class="v2-event-list"><table><thead><tr><th>${rateCandidates?'序号 / 时间':'时间'}</th><th>${rateCandidates?'候选心率 / RR':'模板 / 亚型'}</th><th>入报</th></tr></thead><tbody>${items.map((e,i)=>`<tr data-preview="false"><td>${rateCandidates?`<span class="v2-candidate-rank">第 ${reportOffset+i+1} 条</span>`:''}<button data-locate="${i}" aria-current="false">${formatElapsed(e.time_s)}</button></td><td>${rateCandidates?`<strong class="v2-candidate-rate">${e.hr} bpm</strong><div>${esc(e.subtype)} ${e.rr_ms}ms</div>`:reportTemplateCell(e)}<small data-event-status>${e.beat_count} 搏 · ${e.diagnosis_status==='confirmed'?'已确认':'待诊断确认'}</small></td><td><input type="checkbox" data-include="${i}" aria-label="${formatElapsed(e.time_s)} ${esc(e.label)}入报" ${selected().some(s=>s.event_id===e.event_id&&s.basis_version===e.basis_version)?'checked':''}></td></tr>`).join('')||'<tr><td colspan="3">0 条匹配记录</td></tr>'}</tbody></table>
      <footer><button id="v2Prev" ${reportOffset===0?'disabled':''}>上一页</button><span>${reportData.total?reportOffset+1:0}–${reportOffset+items.length} / ${reportData.total}</span>${rateCandidates?`<label>页码<select id="v2ReportPage" aria-label="候选页码">${Array.from({length:pageCount},(_,i)=>`<option value="${i}" ${i===Math.floor(reportOffset/50)?'selected':''}>${i+1} / ${pageCount}</option>`).join('')}</select></label>`:''}<button id="v2Next" ${reportOffset+items.length>=reportData.total?'disabled':''}>下一页</button></footer></div>
      <div class="v2-event-detail"><div class="v2-distribution">${Object.entries(reportData.subtype_counts).map(([k,n])=>`<span>${esc(Object.fromEntries(A.patterns)[k]||k)} <b>${n}</b></span>`).join('')}<small>${rateCandidates?'RR：有效相邻心搏间期；NN：连续正常心搏且在设置范围内。这里只提供选图候选，不替代医生确认。':'连续搏数与重复节律为重叠标签，不能相加'}</small></div><div id="v2TimeDistribution"></div><div id="v2EventWave"><p class="empty-state">点击左侧事件查看完整波形</p></div><input id="v2Time" type="range" min="0" max="${state.caseData.technical.duration_seconds_raw}" step=".1" aria-label="事件连续波形时间导航"><small id="v2WaveLabel"></small></div></div>`;
    qs('.v2-category-bar').insertAdjacentHTML('beforeend',`<details class="v2-candidate-settings"><summary>${defaultStripSummary()}</summary>${stripSettingsHtml(composition().strip_defaults,'default')}</details>`);
    const rateHelp=host.querySelector('.v2-rate-help');if(rateHelp){const disclosure=document.createElement('details');disclosure.className='v2-candidate-help';disclosure.innerHTML=`<summary>RR / NN 单间期候选 · 显示 ${reportData.total} 条 · 间隔隐藏 ${reportData.candidate_hidden_count} 条 · 说明</summary>`;rateHelp.before(disclosure);disclosure.append(rateHelp);}
    if(category==='pause'){
      const counts=reportData.pause_counts;
      qs('#v2Subtype').closest('label').hidden=true;
      qs('.v2-category-bar strong').textContent=`停搏事件 · 长 RR 候选 ${reportData.total} 条`;
      qs('.v2-category-bar').insertAdjacentHTML('beforeend',`<label>RR 范围<select id="v2PauseBand"><option value="all">全部 &gt;2.5 秒 · ${counts.all} 次</option><option value="over3">仅 &gt;3 秒 · ${counts.over3} 次</option><option value="2.5to3">2.5 秒&lt;RR≤3 秒 · ${counts['2.5to3']} 次</option></select></label>`);
      qs('#v2PauseBand').value=pauseBand;
      qs('#v2PauseBand').onchange=e=>{pauseBand=e.target.value;reportOffset=0;run(()=>refreshReport({viewOnly:true}))};
      qs('.v2-distribution').innerHTML=`<span>RR &gt;2.5 秒 <b>${counts.all} 次</b></span><span>其中 RR &gt;3 秒 <b>${counts.over3} 次</b></span><small>按每个有效相邻 R-R 间期计 1 次，不合并为连续事件。等于 2.5 秒不计入；等于 3 秒属于 ≤3 秒组。筛选和入图不改变全记录统计；长 RR 不等同确诊停搏。</small>`;
    }
    enableReportDraftSelections(items);
    host.querySelectorAll('tr[data-preview]').forEach((row,i)=>{const e=items[i],info=`${formatElapsed(e.time_s)} · ${e.hr?e.hr+' bpm · ':''}${e.rr_ms?e.subtype+' '+e.rr_ms+' ms · ':''}${e.beat_count} 搏 · ${e.diagnosis_status==='confirmed'?'已确认':'待诊断确认'}`;row.title=info;row.querySelector('[data-include]').setAttribute('aria-label',info+'入报');bindReportSelection(row,e);});
    qs('#v2EventWave').insertAdjacentHTML('beforebegin','<nav id="v2EventNavigation" class="v2-event-navigation" aria-label="候选事件连续核查" tabindex="-1"></nav>');
    qs('#v2Subtype').onchange=e=>{reportMode=e.target.value;reportOffset=0;run(()=>refreshReport({viewOnly:true}))};
    if(qs('#v2Fast')){qs('#v2Fast').value=reportSequence();qs('#v2Fast').onchange=e=>{reportOffset=0;reportMode='all';state.reportComposition=ECGReportWorkspace.withRateMode(state.reportComposition,e.target.value);delete state.reportComposition.category_reviews.fastest;delete state.reportComposition.category_reviews.slowest;dirty();run(()=>refreshReport({viewOnly:true}))}}
    if(qs('#v2RateSort'))qs('#v2RateSort').onchange=e=>{reportSort=e.target.value;reportOffset=0;run(()=>refreshReport({viewOnly:true}))};
    if(rateCandidates){
      qs('#v2Complete').insertAdjacentHTML('beforebegin',`<label>定位点间隔<select id="v2RateSpacing">${[[0,'全部候选'],[7,'至少 7 秒'],[30,'至少 30 秒'],[60,'至少 60 秒']].map(([v,label])=>`<option value="${v}" ${reportSpacing===v?'selected':''}>${label}</option>`).join('')}</select></label>`);
      qs('#v2RateSpacing').onchange=e=>{reportSpacing=Number(e.target.value);reportOffset=0;run(()=>refreshReport({viewOnly:true}))};
    }
    if(qs('#v2ReportPage'))qs('#v2ReportPage').onchange=e=>{reportOffset=Number(e.target.value)*50;run(()=>refreshReport({viewOnly:true}))};
    qs('#v2Complete').onclick=()=>{state.reportComposition.category_reviews[category]=reportData.basis_versions[category];dirty();renderReportShell();qs('#v2Complete').setAttribute('aria-pressed','true');qs('#v2Complete').textContent='✓ 本类筛选已完成'};
    qs('#v2Complete').title=!reportData.category_counts[category]?'当前类别没有候选，无需分类筛选确认':'独立记录当前类别筛选已完成，可全部不选；不会自动加入报告';
    qs('#v2Prev').textContent='‹';qs('#v2Prev').setAttribute('aria-label','上一页');qs('#v2Next').textContent='›';qs('#v2Next').setAttribute('aria-label','下一页');
    qs('#v2Prev').onclick=()=>{reportOffset=Math.max(0,reportOffset-50);run(()=>refreshReport({viewOnly:true}))};qs('#v2Next').onclick=()=>{reportOffset+=50;run(()=>refreshReport({viewOnly:true}))};
    qs('#v2Time').oninput=e=>run(()=>detailWindow(Number(e.target.value)));
    const distribution=qs('.v2-distribution');distribution.className='rw-distributions';qs('#v2TimeDistribution').remove();
    const distributions=document.createElement('details');distributions.className='v2-candidate-distributions';distributions.open=distributionOpen.get(distributionKey)??true;distributions._reportCase=bodyCase;distributions._reportCaseToken=bodyCaseToken;distributions._reportDistributionKey=distributionKey;const distributionState=()=>{const status=distributions.querySelector('[data-category-view-state]');if(status)status.textContent=`${Object.fromEntries(tabs)[bodyCategory]} · 本类${distributions.open?'展开':'折叠'} · 切类后恢复`;};distributions.ontoggle=()=>{if(distributions.isConnected&&bodyCurrent()){distributionOpen.set(distributionKey,distributions.open);distributionState();}};distributions.innerHTML=`<summary>分布 / 筛选 · ${reportMode==='all'?'全部亚型':esc(Object.fromEntries(A.patterns)[reportMode]||reportMode)} · ${reportTimeRange?'已限定时段':'全部时间'} · ${reportData.total} 条 <span class="v2-category-view-state" data-category-view-state></span></summary>`;distributionState();distributions.title='本窗口按事件类别保留筛选、定位、列表位置和折叠状态；不改变入报图条或报告设置。';distribution.before(distributions);distributions.append(distribution);
    const help=host.querySelector('.v2-candidate-help');if(help){help.querySelector('summary').textContent='RR / NN 候选说明';qs('.v2-category-bar').append(help);}
    ECGReportWorkspace.distributions(distribution,reportData,{mode:reportMode,range:reportTimeRange,pauseBand,category,labels:Object.fromEntries(A.patterns),change:next=>{if('mode' in next)reportMode=next.mode;if('range' in next)reportTimeRange=next.range;if('pauseBand' in next)pauseBand=next.pauseBand;if('spacing' in next)reportSpacing=next.spacing;reportOffset=0;run(()=>refreshReport({viewOnly:true}))}});
    if(items.length)await locate(items.find(e=>e.event_id===active?.event_id)||items[0]);
    else{active=null;renderEventNavigation();}
  }
  async function locate(e){
    if(!e||e.category!==category||state.reportViewLoading||state.reportViewError||state.reportEvidenceLoading)return;
    active=e;const token=++waveToken,id=state.caseId,caseToken=state.caseRequestId,renderToken=reportRenderToken,viewCategory=category,scope=waveEvidenceScope,rateCandidates=['fastest','slowest'].includes(e.category),target=qs('#v2EventWave');
    const current=()=>token===waveToken&&id===state.caseId&&caseToken===state.caseRequestId&&renderToken===reportRenderToken&&viewCategory===category&&scope===waveEvidenceScope&&target===qs('#v2EventWave');
    document.querySelectorAll('[data-locate]').forEach(button=>{const current=reportData.items[Number(button.dataset.locate)]?.event_id===e.event_id;button.setAttribute('aria-current',String(current));button.closest('tr').dataset.preview=String(current)});
    const selectedRow=qs('[data-preview="true"]'),list=qs('.v2-event-list');
    if(selectedRow&&list){const row=selectedRow.getBoundingClientRect(),box=list.getBoundingClientRect(),header=list.querySelector('thead')?.getBoundingClientRect().height||0;
      if(row.top<box.top+header)list.scrollTop+=row.top-box.top-header;
      else if(row.bottom>box.bottom)list.scrollTop+=row.bottom-box.bottom;
    }
    const retainedNavigation=qs('#v2EventNavigation');if(retainedNavigation&&typeof target.contains==='function'&&typeof target.before==='function'&&target.contains(retainedNavigation))target.before(retainedNavigation);qs('#v2EventWave').textContent='读取完整事件…';
    renderEventNavigation();
    try{
    const entry=await reportStrip(e,returnedRhythmSettings(e)||selected().find(s=>s.event_id===e.event_id)||composition().strip_defaults,id);
    const wave=entry?entry.waveform:await eventWave(e,id);
    if(!current())return;
    qs('#v2EventWave').innerHTML=svg(wave,e);qs('#v2Time').value=wave.start_s;
    qs('#v2WaveLabel').textContent=`${e.label} · ${formatElapsed(wave.start_s)}–${formatElapsed(wave.start_s+wave.duration_s)} · ${entry?`${entry.strip.visible_beat_count} 搏 · ${entry.strip.warning||'按入报导联和时长预览'}`:`目标 ${e.beat_count} 搏 · 完整事件概览`}`;
    const contextWave=await mountRange(qs('#v2EventWave'),e,entry,id);
    const host=qs('#v2EventWave');if(current()){ECGReportWorkspace.mountEventPreview(host,{event:e,loadWave:()=>Promise.resolve(contextWave||wave),renderWave:w=>ECGReportWorkspace.reviewWaveSvg(w,e),isCurrent:current});ECGReportWorkspace.bindWavePreview(host,host._rwOpenPreview,current);}
    if(current())renderEventNavigation(true);
    }catch(error){
      if(!current())return;
      qs('#v2EventWave').innerHTML='<p>事件波形读取失败，尚不能在此加入报告；可重试或继续核查下一条。</p><button type="button" id="v2RetryEventWave">重试当前波形</button>';
      qs('#v2WaveLabel').textContent=error.message;
      qs('#v2RetryEventWave').onclick=()=>run(()=>locate(e));renderEventNavigation();throw error;
    }
  }
  async function detailWindow(start){
    const token=++waveToken,id=state.caseId,caseToken=state.caseRequestId,renderToken=typeof reportRenderToken==='undefined'?0:reportRenderToken,viewCategory=typeof category==='undefined'?null:category,scope=waveEvidenceScope,host=qs('#v2EventWave');
    const current=()=>token===waveToken&&id===state.caseId&&caseToken===state.caseRequestId&&renderToken===(typeof reportRenderToken==='undefined'?0:reportRenderToken)&&viewCategory===(typeof category==='undefined'?null:category)&&scope===waveEvidenceScope&&host===qs('#v2EventWave');
    if(!host)return;
    renderEventNavigation();
    const retainedNavigation=qs('#v2EventNavigation');if(retainedNavigation&&typeof host.contains==='function'&&typeof host.before==='function'&&host.contains(retainedNavigation))host.before(retainedNavigation);host.textContent='正在读取连续波形…';
    try{
      const wave=await endpoint('waveform',{start,duration:10,leads:'I,II,III,aVR,aVL,aVF,V1,V2,V3,V4,V5,V6',max_points:2400,...waveEvidence},id);
      if(!current())return;
      host.innerHTML=ECGReportWorkspace.reviewWaveSvg(wave,active);const event=active;ECGReportWorkspace.mountEventPreview(host,{event,loadWave:()=>Promise.resolve(wave),renderWave:w=>ECGReportWorkspace.reviewWaveSvg(w,event),isCurrent:current});ECGReportWorkspace.bindWavePreview(host,host._rwOpenPreview,current);qs('#v2WaveLabel').textContent=`连续波形 ${formatElapsed(wave.start_s)} · 10 秒 · 12 导联只读复核`;
    }catch(error){
      if(!current())return;
      host.textContent='连续波形读取失败，请重新选择时间或事件后重试。';throw error;
    }
  }
  function statsTable(){return `<table class="v2-stats"><caption>全部已确认结果统计（图条选择不改变统计）</caption><thead><tr><th>分类</th><th>事件次数</th><th>心搏数量</th></tr></thead><tbody>${A.categories.map(([k,label])=>`<tr><td>${label}</td><td>${reportData?.confirmed_category_counts[k]??'—'}</td><td>${reportData?.confirmed_beat_counts[k]??'—'}</td></tr>`).join('')}</tbody></table><details class="v2-source-summary"><summary>源报告独立对照</summary><p>有效心搏 ${state.caseData.summary.total_beats??'—'} · 平均心率 ${state.caseData.summary.avg_hr??'—'} bpm · SDNN ${state.caseData.summary.sdnn_ms??'—'} ms</p></details>`;}
  function hrvTrendSvg(data){return `<svg class="v2-hrv-trend" viewBox="0 0 800 120" role="img" aria-label="逐小时SDNN趋势，空缺不连接">${data.hourly.map((r,i)=>{if(r.sdnn_ms===null)return '';const max=Math.max(1,...data.hourly.map(x=>x.sdnn_ms||0)),x=30+i*740/Math.max(1,data.hourly.length-1),y=100-r.sdnn_ms/max*80,prev=data.hourly[i-1];return (prev?.sdnn_ms!=null?`<path d="M${30+(i-1)*740/Math.max(1,data.hourly.length-1)} ${100-prev.sdnn_ms/max*80} L${x} ${y}" stroke="#0b7d7b"/>`:'')+`<circle cx="${x}" cy="${y}" r="3" fill="#0b7d7b"><title>${r.label} SDNN ${r.sdnn_ms} ms</title></circle>`}).join('')}</svg>`}
  function hrvRowsTable(rows){return `<table class="v2-stats v2-hrv-table"><thead><tr><th>时段</th><th>SDNN ms</th><th>RMSSD ms</th><th>pNN50 %</th><th>平均NN ms</th><th>有效 NN</th><th>覆盖 / 有效NN 秒</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.label)}</td>${['sdnn_ms','rmssd_ms','pnn50_pct','mean_nn_ms','nn_count'].map(k=>`<td>${r[k]??'—'}</td>`).join('')}<td>${r.coverage_s} / ${r.valid_nn_s}</td></tr>`).join('')}</tbody></table>`}
  function hrvWindowControl(data){return `<label>24 小时窗口<select class="v2-hrv-window">${Array.from({length:data.window_count},(_,i)=>`<option value="${i}" ${i===data.window_index?'selected':''}>第 ${i+1} 窗口</option>`).join('')}</select></label>`}
  function hrvHtml(data){const rows=[...Object.values(data.periods),...data.hourly];return `<p>${esc(data.method)} · 实际覆盖 ${(data.actual_duration_s/3600).toFixed(2)} 小时</p>${hrvWindowControl(data)}${hrvTrendSvg(data)}${hrvRowsTable(rows)}`;}
  function hrvReportPages(data){
    const rows=[...Object.values(data.periods),...data.hourly],paper=composition().paper||{},landscape=paper.orientation==='landscape',large=paper.size==='A3',pageCapacity=large?(landscape?15:24):(landscape?8:15),pages=[];
    for(let offset=0;offset<Math.max(1,rows.length);offset+=pageCapacity){const subset=rows.slice(offset,offset+pageCapacity),intro=offset===0?`<div class="v2-hrv-intro"><p>${esc(data.method)} · 实际覆盖 ${(data.actual_duration_s/3600).toFixed(2)} 小时</p>${hrvWindowControl(data)}</div>${hrvTrendSvg(data)}`:'';pages.push(paperShell(offset?'HRV 时域对照（续）':'HRV 时域对照',intro+hrvRowsTable(subset),'v2-hrv-paper'))}
    return pages.join('');
  }
  async function loadHrv(selector,windowIndex,preloaded=null){
    if(reportCase!==state.caseId){state.reportComposition={...copy(state.report?.composition||{}),schema_version:2};reportCase=state.caseId;reportVersion=state.report?.version;}
    windowIndex=windowIndex??composition().hrv_window??0;const token=++hrvToken,id=state.caseId,caseToken=state.caseRequestId,target=qs(selector);if(!target)return;
    const current=()=>token===hrvToken&&id===state.caseId&&caseToken===state.caseRequestId&&target.isConnected&&target===qs(selector);
    hrv=null;
    renderHrvTarget(target,'<p class="empty-state">计算 HRV 分段、频谱及趋势证据…</p>');
    try{const data=preloaded||(await ECGAnalysisConsistency.read(api,id,[basis=>endpoint('hrv-analysis',{window:windowIndex,...basis},id)]))[0];if(!current())return;hrv=data;const model=paperModel({},data);model.report.status='draft';renderHrvTarget(target,ECGHrvReport.ui(model,data,composition().include_hrv));ECGReportPaper.number(target);
      if(state.privacySaving||state.privacyIdentityPending)target.querySelectorAll?.('.hrv-paper-preview .rp-running').forEach(header=>{const spans=header.querySelectorAll('span');if(spans[0])spans[0].textContent='患者 ID：身份更新中';if(spans[1])spans[1].textContent='姓名：身份更新中';});
      if(globalThis.ECGHrvReview){const evidenceHost=document.createElement('div');evidenceHost.className='hrv-review-host';target.querySelector('.hrv-evidence-notice')?.after(evidenceHost);ECGHrvReview.mount(evidenceHost,data,{isCurrent:current,scope:JSON.stringify([id,selector,windowIndex,data.start_s,data.end_s,data.data_version,data.analysis_basis,data.analysis_revision])});}
      target.querySelector('.v2-hrv-window').onchange=e=>{if(!current())return;const next=Number(e.target.value);state.reportComposition=composition();state.reportComposition.hrv_window=next;dirty();run(()=>selector==='#hrvWindowPanel'?loadTrends(next):loadHrv(selector,next))};
      target.querySelector('[data-hrv-include]').onchange=e=>{if(!current())return;state.reportComposition=composition();state.reportComposition.include_hrv=e.target.checked;state.reportComposition.included_pages=state.reportComposition.included_pages.filter(k=>!k.startsWith('hrv_'));if(e.target.checked)state.reportComposition.included_pages.push('hrv_time','hrv_frequency','hrv_overview');dirty();toast(e.target.checked?'已加入主报告，请在报告页保存草稿':'已取消加入主报告，请保存草稿')};
      target.querySelector('[data-hrv-export]').disabled=Boolean(state.privacySaving||state.privacyIdentityPending);
      target.querySelector('[data-hrv-export]').onclick=()=>run(async()=>{
        if(!current())return;const basis=ECGAnalysisConsistency.identity(data),privacyToken=state.privacyRequestId??0;
        const privacyGuard=()=>{if(state.privacySaving||state.privacyIdentityPending)throw Error('身份信息正在更新或尚未读取，请重试身份更新后重新导出');if(privacyToken!==(state.privacyRequestId??0))throw Error('身份显示状态已变化，请重新导出');};privacyGuard();
        if(!state.demoReadonly){const response=await fetch(ECGAnalysisConsistency.url(id,'hrv-report.pdf',{window:data.window_index},basis));if(!current())return;privacyGuard();if(!response.ok){const problem=await response.json().catch(()=>({}));privacyGuard();throw Error(problem.error||'HRV 导出失败，请重新读取后重试');}const blob=await response.blob();if(!current())return;privacyGuard();const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=(typeof caseDisplayId==='function'?caseDisplayId(state.caseData):id)+'_HRV分析报告.pdf';link.click();setTimeout(()=>URL.revokeObjectURL(url),60000);return;}
        ECGAnalysisConsistency.assertSame(basis,await endpoint('analysis-basis',basis,id));if(!current())return;privacyGuard();const model=paperModel({},data);model.report.status='draft';await printHtml(ECGHrvReport.pages(model,data),'HRV 分析报告',()=>{privacyGuard();if(!current())throw Error('HRV 病例或窗口已变化，请重新读取后打印');});
      });
    }catch(error){if(!current())return;renderHrvTarget(target,`<p class="rp-load-error">HRV 读取失败：${esc(error.message)}</p><button type="button" class="button secondary" data-hrv-retry>重试</button>`);target.querySelector('[data-hrv-retry]').addEventListener('click',()=>run(()=>selector==='#hrvWindowPanel'?loadTrends(windowIndex):loadHrv(selector,windowIndex)));throw error;}
  }
  async function save(status='draft'){
    globalThis.ECGAdvancedAnalysis?.assertApplied();
    ECGReportRange.assertApplied?.();
    if(!clinicalWorkflow.writable())throw Error('当前服务为只读');
    if(state.reportSaving)return;
    if(state.reportStale)throw Error('病例或报告已有新版本，请先载入最新版本核对');
    if(status==='reviewed'&&(state.reportEvidenceLoading||state.reportEvidenceError||state.reportViewLoading||state.reportViewError))throw Error('请先完整读取当前报告依据与类别');
    if(status==='reviewed'&&state.reportDirty)throw Error('请先保存草稿，再审核当前版本');
    const id=state.caseId,payload={status,expected_version:state.report.version,expected_review_revision:state.report.review_revision,conclusion:qs('#conclusionEditor').value,composition:copy(composition())};
    const submitted=ECGReportConsistency.content(payload.conclusion,payload.composition);
    state.reportSaving=true;renderReportShell();
    try{
      const result=await api(`/api/cases/${id}/report`,{method:'PUT',body:JSON.stringify(payload)});
      if(id!==state.caseId)return;
      const changed=submitted!==ECGReportConsistency.content(qs('#conclusionEditor').value,composition());
      state.report=result;state.caseData.report_workflow=result;state.reportDirty=changed;state.reportStale=false;reportVersion=result.version;
      if(!changed)state.reportComposition=copy(result.composition);
      await clinicalWorkflow.refresh(id);await refreshReport();
      toast(globalThis.ECGAdvancedAnalysis?.pending()?'已保存提交时的版本；后续研究测量修改尚未应用':ECGReportRange.pending?.().length?'已保存提交时的版本；后续游标修改尚未应用':changed?'已保存提交时的版本；后续修改尚未保存':result.status==='reviewed'?'报告已审核':'报告已保存');
    }catch(error){
      if(id===state.caseId){const remote=await endpoint('report',{},id).catch(()=>null);if(remote&&!ECGReportConsistency.sameBase(state.report,remote))state.reportStale=true;}
      throw error;
    }finally{if(id===state.caseId){state.reportSaving=false;renderReportShell();}}
  }
  function gainHtml(){const paper=composition().paper,estimate=paper.voltage_estimate;return estimate?`<span>${esc(ECGVoltage.note(estimate))}</span><label>全报告图条导出幅度<select data-estimate-paper-gain aria-label="报告估算电压增益">${['5 mm/mV','10 mm/mV','20 mm/mV'].map(v=>`<option ${paper.gain===v?'selected':''} value="${v}">${v.replace('mV','估算mV')}</option>`).join('')}</select></label><span>增益影响所有已选及以后入报的图条；请重新预览并保存。</span>`:'<span>幅度：逐导联自适应（设备单位，电压未校准）</span>';}
  function paperSettingsHtml(){
    const paper=composition().paper,fixed=paper.time_scale==='fixed';
    return `<div class="rp-paper-settings" role="group" aria-label="全报告 A4 图条输出"><strong>全报告 A4 图条输出</strong><label>时间标尺<select data-paper-setting="time_scale" aria-label="报告时间标尺"><option value="fit" ${fixed?'':'selected'}>完整区间单图（标注实际纸速）</option><option value="fixed" ${fixed?'selected':''}>固定纸速（连续分段）</option></select></label><label>纸速<select data-paper-setting="speed" aria-label="报告固定纸速" ${fixed?'':'disabled'}>${['12.5 mm/s','25 mm/s','50 mm/s'].map(v=>`<option value="${v}" ${(paper.speed||'25 mm/s')===v?'selected':''}>${v}</option>`).join('')}</select></label><label><input type="checkbox" data-paper-setting="show_grid" ${paper.show_grid!==false?'checked':''}>显示网格</label><label><input type="checkbox" data-paper-setting="show_labels" ${paper.show_labels!==false?'checked':''}>心搏类型 / HR / RR 标注</label><p>作用于所有已选及以后入报图条的 A4 预览与 PDF。固定纸速完整保留选区，超出纸宽时连续分段；至少 5 搏要求针对整段，不是每个纸面分段。导联名称、时间与单位始终保留。修改后请重新预览并保存。</p>${gainHtml()}</div>`;
  }
  function changePaperSettings(el){
    const key=el.dataset.paperSetting;if(key===undefined)return false;
    if(!['time_scale','speed','show_grid','show_labels'].includes(key))return false;
    if(key==='time_scale'&&!['fit','fixed'].includes(el.value))return false;
    if(key==='speed'&&!['12.5 mm/s','25 mm/s','50 mm/s'].includes(el.value))return false;
    state.reportComposition=composition();
    state.reportComposition.paper[key]=key.startsWith('show_')?el.checked:el.value;
    if(key==='time_scale')el.closest('.rp-paper-settings').querySelector('[data-paper-setting="speed"]').disabled=el.value!=='fixed';
    dirty();return true;
  }
  function stripSettingsHtml(raw,scope){
    const spec=ECGReportEngine.settings(raw),mode=spec.leads.length===12?'all':spec.leads.join(',')==='II,V1,V5'?'three':'custom';
    return `<div class="rp-entry-settings" data-strip-settings="${scope}"><strong>${scope==='default'?'新入报导联与时长':'本图设置'}</strong><label>导联<select data-strip-mode="${scope}" aria-label="${scope==='default'?'新入报':'本图'}导联方案"><option value="three" ${mode==='three'?'selected':''}>常用 3 导联（II / V1 / V5）</option><option value="all" ${mode==='all'?'selected':''}>全部 12 导联</option><option value="custom" ${mode==='custom'?'selected':''}>自选导联</option></select></label><label>范围<input data-strip-duration="${scope}" type="number" min="1" max="120" step="0.5" value="${spec.duration_s}" aria-label="${scope==='default'?'新入报':'本图'}时长（秒）">秒</label><span>默认 7 秒，至少 5 个可用心搏；不足时延长。导联与时长设置仅修改${scope==='default'?'此后入报':'本条图条'}。</span>${scope==='default'&&category==='strips'?paperSettingsHtml():''}<fieldset class="rp-leads" ${mode==='custom'?'':'hidden'}><legend>选择要进入报告的导联（至少一个）</legend>${ECGReportEngine.leads.map(lead=>`<label><input type="checkbox" data-strip-lead="${scope}" value="${lead}" ${spec.leads.includes(lead)?'checked':''}>${lead}</label>`).join('')}</fieldset></div>`;
  }
  function defaultStripSummary(){const s=ECGReportEngine.settings(composition().strip_defaults);return `新入报：${s.leads.length===12?'12 导联':s.leads.join(' / ')} · ${s.duration_s} 秒`;}
  function changeStripSettings(el){
    const scope=el.dataset.stripMode??el.dataset.stripLead??el.dataset.stripDuration;if(scope===undefined)return false;
    const holder=el.closest('[data-strip-settings]'),old=scope==='default'?composition().strip_defaults:selected()[Number(scope)],spec=ECGReportEngine.settings(old);
    if(el.dataset.stripMode!==undefined){
      if(el.value==='custom'){holder.querySelector('fieldset').hidden=false;return true;}
      spec.leads=el.value==='all'?[...ECGReportEngine.leads]:[...ECGReportEngine.defaults];
    }else if(el.dataset.stripLead!==undefined)spec.leads=[...holder.querySelectorAll('[data-strip-lead]:checked')].map(x=>x.value);
    else {spec.duration_s=Number(el.value);delete spec.range_start_s;delete spec.range_end_s;}
    try{ECGReportEngine.settings(spec);}catch(error){if(el.type==='checkbox')el.checked=!el.checked;else el.value=old.duration_s||7;handleError(error);return true;}
    if(scope==='default')state.reportComposition.strip_defaults=spec;else {if(el.dataset.stripDuration!==undefined){delete old.range_start_s;delete old.range_end_s;}Object.assign(selected()[Number(scope)],spec);}
    dirty();if(scope==='default'){holder.outerHTML=stripSettingsHtml(spec,scope);const summary=qs('.v2-candidate-settings>summary');if(summary)summary.textContent=defaultStripSummary();}else run(renderReportBody);return true;
  }
  async function reportStrip(e,selection,id=state.caseId,fresh=false){
    const scope=waveEvidenceScope,spec=ECGReportEngine.settings(selection),key=['report',scope,id,e.event_id,e.basis_version,JSON.stringify(spec)].join('|');
    if(fresh)reportWaveCache.delete(key);
    if(reportWaveCache.size>200)reportWaveCache.delete(reportWaveCache.keys().next().value);
    if(!reportWaveCache.has(key))reportWaveCache.set(key,endpoint('report-strip',{event_id:e.event_id,basis_version:e.basis_version,leads:spec.leads.join(','),duration:spec.duration_s,...waveEvidence,...('range_start_s' in spec?{range_start_s:spec.range_start_s,range_end_s:spec.range_end_s}:{})},id).catch(error=>{reportWaveCache.delete(key);throw error}));
    const result=await reportWaveCache.get(key);
    if(scope!==waveEvidenceScope)throw Error('波形依据已变化，请重新加载');
    return {...result,caption:selection.caption||e.label};
  }
  async function selectedReportWaves(id){
    const picks=copy(selected()),results=[];let next=0;
    await Promise.all(Array.from({length:Math.min(4,picks.length)},async()=>{while(next<picks.length){const i=next++,s=picks[i],e=selectedLookup.get(s.event_id);if(!e||e.basis_version!==s.basis_version)throw Error('请处理失效图条后再导出');results[i]=await reportStrip(e,s,id);}}));return results;
  }
  async function reportReviewWave(entry,id=state.caseId){
    const evidence={};for(const key of ['analysis_basis','analysis_revision'])if(entry[key]!==undefined)evidence[key]=entry[key];
    const source=entry.waveform,wave=await endpoint('waveform',{start:source.start_s,duration:source.duration_s,leads:'I,II,III,aVR,aVL,aVF,V1,V2,V3,V4,V5,V6',max_points:2400,filter:'raw',...evidence},id);
    if(Object.keys(evidence).some(key=>wave[key]!==evidence[key]))throw Error('12 导联依据已变化，请重新载入事件');
    if(ECGChartInspection.names(wave.leads).join(',')!=='I,II,III,aVR,aVL,aVF,V1,V2,V3,V4,V5,V6')throw Error('来源未提供完整 12 导联，不能补绘缺失导联');
    return wave;
  }
  async function mountRange(target,e,entry,id=state.caseId){
    const holder=document.createElement('section'),token=waveToken,renderToken=reportRenderToken,viewCategory=typeof category==='undefined'?null:category,scope=waveEvidenceScope,caseToken=state.caseRequestId;
    const current=()=>holder.isConnected&&target.isConnected!==false&&state.caseId===id&&state.caseRequestId===caseToken&&token===waveToken&&renderToken===reportRenderToken&&viewCategory===(typeof category==='undefined'?null:category)&&scope===waveEvidenceScope;
    // Replace synchronously: an earlier request must never remove a newer editor.
    target.replaceChildren(holder);holder.textContent='正在读取入报区间上下文…';
    const evidence={};for(const key of ['analysis_basis','analysis_revision'])if(entry[key]!==undefined)evidence[key]=entry[key];
    const reviewTwelve=target.id==='v2EventWave',total=state.caseData.technical.duration_seconds_raw,padding=Math.max(0,Math.min(10,(120-entry.strip.actual_duration_s)/2));
    const pendingRange=reviewTwelve?ECGReportRange.pending().find(d=>d.event?.event_id===e.event_id&&d.basis===scope&&d.context===JSON.stringify([id,caseToken])):null;
    const sourceStart=Number(entry.waveform?.start_s??entry.strip.start_s),sourceEnd=entry.waveform?.duration_s!=null?sourceStart+Number(entry.waveform.duration_s):Number(entry.strip.end_s??(sourceStart+Number(entry.strip.actual_duration_s))),start=reviewTwelve?Math.max(0,Math.min(sourceStart,pendingRange?.a??sourceStart)-.5):Math.max(0,Math.min(entry.strip.start_s-padding,total-30)),duration=reviewTwelve?Math.min(total-start,Math.max(sourceEnd,pendingRange?.b??sourceEnd)+.5-start):Math.min(120,total-start,Math.max(30,entry.strip.end_s-start+padding));
    let wave;
    const reviewLeads=reviewTwelve?'I,II,III,aVR,aVL,aVF,V1,V2,V3,V4,V5,V6':entry.strip.leads.join(',');
    try{wave=await endpoint('waveform',{start,duration,leads:reviewLeads,filter:'raw',max_points:12000,...evidence},id);}
    catch(error){if(!current())return;holder.textContent='入报上下文读取失败，请重新选择此事件后重试。';throw error;}
    if(!current())return;
    if(Object.keys(evidence).some(key=>wave[key]!==evidence[key])){holder.textContent='入报依据已变化，请重新载入事件后复核。';throw Error(holder.textContent);}
    if(reviewTwelve&&ECGChartInspection.names(wave.leads).join(',')!==reviewLeads){holder.textContent='来源未提供完整 12 导联，请核对原始数据；未补绘导联。';throw Error(holder.textContent);}
    async function apply(range){
      if(!current())throw Error('事件或病例已变化，请重新选择入报区间');
      const existing=selected().find(s=>s.event_id===e.event_id),spec={...ECGReportEngine.settings(existing||entry.strip)};
      delete spec.range_start_s;delete spec.range_end_s;if(range)Object.assign(spec,range);else spec.duration_s=7;
      // Applying a clinical selection must revalidate remotely, even on a cache hit.
      await reportStrip(e,spec,id,true);if(!current())throw Error('波形已切换，区间尚未应用；请返回待应用区间重试');
      ECGReportRange.forget?.(e.event_id);
      if(returnedRhythmSelection(e)){replaceRhythmSelection(e,spec);renderReportShell();await renderReportBody();}
      else if(existing){delete existing.range_start_s;delete existing.range_end_s;Object.assign(existing,spec);dirty();await renderReportBody();}
      else await selectEvent(e,true,spec);
    }
    ECGReportRange.mount(holder,{...entry,inReport:selected().some(s=>s.event_id===e.event_id)},wave,range=>apply(range),()=>apply(null),{context:JSON.stringify([id,caseToken]),basis:scope,event:copy(e)});
    if(reviewTwelve){
      holder.classList.add('rw-twelve-range');
      const label=document.createElement('small');label.className='rw-review-lead-note';label.textContent=`12 导联 · ${formatElapsed(wave.start_s)} — ${formatElapsed(wave.start_s+wave.duration_s)} · ${wave.duration_s.toFixed(3)} 秒 · 入报 ${entry.strip.leads.join(' / ')} · 设备单位 u，未校准`;label.title='主图显示真实入报时间窗及前后各 0.5 秒上下文，便于直接拖动扩展；如有待应用游标，显示窗完整覆盖该暂存区间。';
      const toolbar=document.createElement('div');toolbar.className='rw-main-range-toolbar';const navigation=qs('#v2EventNavigation');if(navigation)toolbar.append(navigation);toolbar.append(holder.querySelector('[data-range-apply]'),holder.querySelector('[data-range-reset]'));holder.querySelector('header').after(toolbar,label);
      const stage=holder.querySelector('.report-range-stage');stage.setAttribute('aria-description','单击波形定位只读复核；双击具体波形打开 12 导联。入报使用左侧表行、勾选或加入报告草稿按钮。');
      function placeLeadLabels(){const plot=stage.querySelector('svg');if(!plot)return;const names=ECGChartInspection.names(wave.leads),row=plot.viewBox.baseVal.height/names.length;plot.querySelectorAll('text').forEach(text=>{const index=names.indexOf(text.textContent);if(index<0)return;text.setAttribute('x','-30');text.setAttribute('y',String((index+.55)*row));text.setAttribute('dominant-baseline','middle');text.setAttribute('font-size','12');text.setAttribute('data-review-lead-label',text.textContent);});}
      const axis=document.createElement('div');axis.className='rw-main-time-axis';axis.setAttribute('aria-label','当前真实时间窗的秒刻度');axis.innerHTML=Array.from({length:5},(_,i)=>`<span>${(wave.duration_s*i/4).toFixed(2)} s</span>`).join('');stage.after(axis);placeLeadLabels();const labelsObserver=new MutationObserver(()=>{if(!holder.isConnected){labelsObserver.disconnect();return;}placeLeadLabels();});labelsObserver.observe(stage,{childList:true});
    }
    return wave;
  }
  function renderRangeDraftNotice(){
    const anchor=qs('#reportV2Notice');if(!anchor)return;
    let host=qs('#reportRangeDraftNotice');if(!host){host=document.createElement('section');host.id='reportRangeDraftNotice';host.setAttribute('aria-label','待应用游标区间');anchor.after(host);}host.className='v2-range-draft-bar';
    const drafts=ECGReportRange.pending?.()||[];host.hidden=!drafts.length;if(!drafts.length)return;
    const currentSelections=typeof state!=='undefined'&&state.reportComposition?state.reportComposition.selected_events||[]:null;
    const first=drafts[0],stamp=ECGReportRange.formatTime,applied=first.applied||{},included=currentSelections?currentSelections.some(s=>s.event_id===first.event?.event_id&&s.basis_version===first.event?.basis_version):applied.inReport,pendingTime=stamp?`${stamp(first.a)} — ${stamp(first.b)}`:'',appliedTime=included&&stamp?`${stamp(applied.a)} — ${stamp(applied.b)}`:'此事件尚未入报';
    host.innerHTML=`<div class="v2-range-draft-summary" role="status"><strong>${drafts.length} 处待应用区间</strong><span>${pendingTime}</span><small>当前已应用区间：${appliedTime} · 保存、预览、导出前须处理${drafts.length>1?' · 显示第 1 处':''}</small></div><div class="v2-review-actions"><button type="button" data-range-resume>回到草稿</button><button type="button" data-range-discard>放弃修改</button></div>`;
    host.querySelector('[data-range-resume]').onclick=()=>run(async()=>{const d=ECGReportRange.pending()[0];if(!d)return;if(d.basis!==waveEvidenceScope)throw Error('待应用区间的依据已变化，不能套用旧范围；请放弃后按新波形重新选择');rememberReportView();category=d.event.category;reportMode=d.event.subtype;reportOffset=0;reportTimeRange=null;pauseBand='all';await refreshReport({viewOnly:true,focusEvent:d.event});focusEventNavigation();});
    host.querySelector('[data-range-discard]').onclick=()=>{
      host.innerHTML=`<p role="status">放弃这 ${drafts.length} 处待应用区间？已应用图条保留。</p><div class="v2-review-actions"><button type="button" data-range-keep>取消，保留修改</button><button type="button" data-range-confirm-discard>确认放弃游标修改</button></div>`;
      host.querySelector('[data-range-keep]').onclick=()=>{renderRangeDraftNotice();host.querySelector('[data-range-discard]')?.focus();};
      host.querySelector('[data-range-confirm-discard]').onclick=()=>{const current=ECGReportRange.pending();if(current.length!==drafts.length||current.some((d,i)=>d!==drafts[i])){renderRangeDraftNotice();return;}ECGReportRange.clear();run(renderReportBody);};
      host.querySelector('[data-range-keep]').focus();
    };
  }
  function hrvForReport(id,basis={}){return composition().included_pages.some(k=>k.startsWith('hrv_'))?endpoint('hrv-analysis',{window:composition().hrv_window||0,...basis},id):Promise.resolve(null)}
  function computeAdvanced(id,options,basis={}){return api(`/api/cases/${id}/advanced-analysis`,{method:'POST',body:JSON.stringify({options,...basis})});}
  function mountAdvanced(panel,id){
    const evidence=ECGAnalysisConsistency.identity(reportData);
    const caseToken=state.caseRequestId,scope=waveEvidenceScope,contextCurrent=()=>id===state.caseId&&caseToken===state.caseRequestId&&scope===waveEvidenceScope,
      current=()=>contextCurrent()&&panel.isConnected&&!state.reportStale;
    ECGAdvancedAnalysis.mountRetained(panel,{sessionKey:[id,caseToken,scope],contextCurrent,
      isCurrent:current,
      options:composition().advanced_options||{},duration:state.caseData.technical.duration_seconds_raw,
      compute:async options=>{
        try{
          // Bind to what the physician saw. Never silently adopt a newer revision.
          const [advanced,derivatives]=await ECGAnalysisConsistency.read(api,id,[basis=>computeAdvanced(id,options,basis),basis=>endpoint('report-sections',basis,id)],evidence);
          return {advanced,derivatives};
        }catch(error){
          if(contextCurrent()){
            // A failed request is not by itself proof of a conflict (e.g. offline).
            const latest=await endpoint('analysis-basis',{},id).catch(()=>null);
            if(latest&&contextCurrent()){
              let changed=false;
              try{ECGAnalysisConsistency.assertSame(evidence,latest);}catch(_){changed=true;}
              if(changed){
                state.reportStale=true;renderReportShell();
                throw Error('当前显示的分析依据已变化，本次测量未应用。请保留需要的参数，放弃未计算修改后，点击“载入最新版本”重新核对并计算');
              }
            }
          }
          throw error;
        }
      },
      onChange:options=>{if(current()){state.reportComposition.advanced_options=options;dirty();}},
      onPrint:(key,evidence)=>run(async()=>{const privacyToken=state.privacyRequestId??0,options=JSON.stringify(composition().advanced_options||{}),guard=()=>{ECGAdvancedAnalysis.assertApplied();if(options!==JSON.stringify(composition().advanced_options||{}))throw Error('研究测量参数已变化，请使用重新计算的结果打印');if(state.privacySaving||state.privacyIdentityPending)throw Error('身份信息正在更新或尚未读取，请重试身份更新后重新打印');if(privacyToken!==(state.privacyRequestId??0))throw Error('身份显示状态已变化，请重新打印');if(!current())throw Error('病例或分析依据已变化，请重新读取研究测量');};guard();const basis=ECGAnalysisConsistency.identity(evidence.advanced||evidence.derivatives||evidence);ECGAnalysisConsistency.assertSame(basis,await endpoint('analysis-basis',basis,id));guard();await printHtml(ECGReportSections.pages(paperModel(null,null,evidence),[key]),'研究测量报告',guard)}),
      onLocate:(time,{raw=false}={})=>{if(current()){if(raw){state.filter='raw';qs('#filterSelect').value='raw';state.duration=10;qs('#durationSelect').value='10';}jumpTo(time);}}
    });
  }
  async function sectionsForReport(id,basis={}){
    const result=await endpoint('report-sections',basis,id);
    if(composition().included_pages.some(k=>['qtd','vcg','twa','sap'].includes(k))){result.advanced=await computeAdvanced(id,composition().advanced_options||{},basis);ECGAnalysisConsistency.assertSame(result,result.advanced);}
    return result;
  }
  async function readPaperEvidence(id){
    const C=ECGAnalysisConsistency;
    const [caseData,statistics,waves,hrvData,evidence]=await C.read(api,id,[
      basis=>api(withPhi(C.url(id,'',{},basis))),basis=>endpoint('report-statistics',basis,id),
      async basis=>{const items=await selectedReportWaves(id);items.forEach(item=>C.assertSame(basis,item));return {...basis,items};},
      basis=>hrvForReport(id,basis),basis=>sectionsForReport(id,basis),
    ]);
    return {caseData,statistics,entries:waves.items,hrvData,evidence};
  }
  function paperModel(statistics,hrvData=null,evidence=null){return {case:state.caseData,statistics,hrv:hrvData,evidence,report:{...state.report,...(state.reportDirty?{status:'draft',reviewed_by:'',preview_unsaved:true}:{}),conclusion:qs('#conclusionEditor')?.value??state.report?.conclusion,composition:composition()}};}
  async function previewPaper(){
    globalThis.ECGAdvancedAnalysis?.assertApplied();
    ECGReportRange.assertApplied?.();
    const privacyToken=state.privacyRequestId??0,privacyGuard=()=>{if(state.privacySaving||state.privacyIdentityPending)throw Error('身份信息正在更新或尚未读取，请重试身份更新后重新预览');if(privacyToken!==(state.privacyRequestId??0))throw Error('身份显示状态已变化，请重新预览');};privacyGuard();
    if(state.reportStale||state.reportSaving)throw Error('请等待保存完成，并载入最新报告版本核对后预览');
    ECGReportSections.validate(composition());
    let dialog=qs('#rwPaperPreview');if(dialog?.open)return;if(!dialog){dialog=document.createElement('dialog');dialog.id='rwPaperPreview';dialog.className='rw-preview-dialog';document.body.append(dialog)}
    dialog.innerHTML='<header><strong>A4 导出版预览 · 未保存修改仅在本次预览显示</strong><button type="button">关闭</button></header><div class="rp-pages">读取报告数据…</div>';dialog.querySelector('button').onclick=()=>dialog.close();dialog.showModal();
    const id=state.caseId,caseToken=state.caseRequestId,token=++reportRenderToken,content=ECGReportConsistency.content(qs('#conclusionEditor')?.value,composition()),reportContext=JSON.stringify([state.report?.version,state.report?.review_revision,state.report?.status]);
    try{
      const {caseData,statistics,entries,hrvData,evidence}=await readPaperEvidence(id);
      if(id!==state.caseId||caseToken!==state.caseRequestId||token!==reportRenderToken||!dialog.open)return;
      privacyGuard();
      globalThis.ECGAdvancedAnalysis?.assertApplied();ECGReportRange.assertApplied?.();
      if(state.reportStale||state.reportSaving||reportContext!==JSON.stringify([state.report?.version,state.report?.review_revision,state.report?.status]))throw Error('预览期间报告版本或审核状态已变化，请关闭后重新预览');
      if(content!==ECGReportConsistency.content(qs('#conclusionEditor')?.value,composition()))throw Error('预览期间编排已修改，请关闭后重新预览');
      const body=dialog.querySelector('.rp-pages');body.innerHTML=ECGReportPaper.render({...paperModel(statistics,hrvData,evidence),case:caseData},entries);ECGReportPaper.number(body);
    }catch(error){if(id!==state.caseId||caseToken!==state.caseRequestId||token!==reportRenderToken||!dialog.open)return;const body=dialog.querySelector('.rp-pages');body.textContent='预览失败：'+error.message;const retry=document.createElement('button');retry.type='button';retry.textContent='重试 A4 预览';retry.onclick=()=>{dialog.close();run(previewPaper)};body.append(retry);throw error;}
  }
  async function print(){
    globalThis.ECGAdvancedAnalysis?.assertApplied();
    ECGReportRange.assertApplied?.();
    const privacyToken=state.privacyRequestId??0,privacyGuard=()=>{if(state.privacySaving||state.privacyIdentityPending)throw Error('身份信息正在更新或尚未读取，请重试身份更新后重新打印');if(privacyToken!==(state.privacyRequestId??0))throw Error('身份显示状态已变化，请重新打印');};privacyGuard();
    if(state.reportDirty)throw Error('请先保存草稿再导出');
    if(state.reportSaving||state.reportStale)throw Error('请等待保存完成，并载入最新版本核对后导出');
    ECGReportSections.validate(composition());
    const id=state.caseId,caseToken=state.caseRequestId,version=state.report.version,reviewRevision=state.report.review_revision,{caseData,statistics,entries,hrvData,evidence}=await readPaperEvidence(id);
    privacyGuard();
    if(id!==state.caseId||caseToken!==state.caseRequestId||state.reportDirty||state.reportSaving||state.reportStale||version!==state.report.version||reviewRevision!==state.report.review_revision)throw Error('报告已变化，请重新保存后打印');
    const remote=await endpoint('report',{},id);
    if(id!==state.caseId||caseToken!==state.caseRequestId)return;
    privacyGuard();
    if(state.reportDirty||state.reportSaving||state.reportStale||version!==state.report.version||reviewRevision!==state.report.review_revision)throw Error('报告已变化，请重新保存后打印');
    if(!ECGReportConsistency.sameBase(state.report,remote)){state.reportStale=true;renderReportShell();throw Error('病例或报告已有新版本，请重新载入后打印');}
    const guard=()=>{globalThis.ECGAdvancedAnalysis?.assertApplied();ECGReportRange.assertApplied?.();privacyGuard();if(id!==state.caseId||caseToken!==state.caseRequestId||state.reportDirty||state.reportSaving||state.reportStale||version!==state.report.version||reviewRevision!==state.report.review_revision)throw Error('报告已变化，请重新保存后打印');};
    guard();
    await printHtml(ECGReportPaper.render({...paperModel(statistics,hrvData,evidence),case:caseData},entries),id+' 心电报告',guard);
  }
  async function downloadReport(){
    globalThis.ECGAdvancedAnalysis?.assertApplied();
    ECGReportRange.assertApplied?.();
    const privacyToken=state.privacyRequestId??0,privacyGuard=()=>{if(state.privacySaving||state.privacyIdentityPending)throw Error('身份信息正在更新或尚未读取，请重试身份更新后重新导出');if(privacyToken!==(state.privacyRequestId??0))throw Error('身份显示状态已变化，请重新导出');};privacyGuard();
    if(state.reportExportJob)return;
    if(state.demoReadonly)return print();
    if(state.reportDirty||state.reportSaving)throw Error('请先保存草稿再导出');
    if(state.reportStale)throw Error('请先载入最新报告版本核对后导出');
    const id=state.caseId,caseToken=state.caseRequestId,version=state.report.version,reviewRevision=state.report.review_revision;
    const job={id,caseToken,controller:new AbortController()};state.reportExportJob=job;renderExportState();
    const guard=()=>{globalThis.ECGAdvancedAnalysis?.assertApplied();ECGReportRange.assertApplied?.();privacyGuard();if(id!==state.caseId||caseToken!==state.caseRequestId||state.reportDirty||state.reportSaving||state.reportStale||version!==state.report.version||reviewRevision!==state.report.review_revision)throw Error('导出期间报告已变化，请重新核对并保存后导出');};
    try{
    const remote=await api(`/api/cases/${id}/report`,{signal:job.controller.signal});
    if(job.controller.signal.aborted)return;
    guard();
    if(!ECGReportConsistency.sameBase(state.report,remote)){state.reportStale=true;renderReportShell();throw Error('病例或报告已有新版本，请重新载入后导出');}
    const params=new URLSearchParams({expected_version:version});
    if(reviewRevision!==undefined)params.set('expected_review_revision',reviewRevision);
    const response=await fetch(`/api/cases/${id}/report.pdf?${params}`,{signal:job.controller.signal});
    if(job.controller.signal.aborted)return;guard();
    if(!response.ok){
      const problem=await response.json().catch(()=>({}));
      if(job.controller.signal.aborted)return;guard();
      if(id===state.caseId&&caseToken===state.caseRequestId&&response.status===409){state.reportStale=true;renderReportShell();}
      throw Error(problem.error||`报告导出失败（${response.status}），请重试`);
    }
    const blob=await response.blob();if(job.controller.signal.aborted)return;guard();
    const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=(typeof caseDisplayId==='function'?caseDisplayId(state.caseData):id)+'_心电分析复核报告.pdf';link.click();setTimeout(()=>URL.revokeObjectURL(url),60000);
    }catch(error){if(job.controller.signal.aborted)return;throw error;}
    finally{if(state.reportExportJob===job){state.reportExportJob=null;renderExportState();}}
  }
  function renderExportState(){
    const busy=Boolean(state.reportExportJob),button=qs('#downloadReport'),cancel=qs('#cancelReportExport');
    if(button){button.disabled=busy||Boolean(state.privacySaving||state.privacyIdentityPending);button.textContent=busy?'正在导出 PDF…':'导出 PDF';button.setAttribute('aria-busy',String(busy||Boolean(state.privacySaving||state.privacyIdentityPending)));}
    if(cancel)cancel.hidden=!busy;
  }
  function cancelReportExport(notify=false){
    const job=state.reportExportJob;if(!job)return;
    job.controller.abort();state.reportExportJob=null;renderExportState();
    if(notify)toast('已取消本次导出，已保存报告保留','info');
  }
  async function printHtml(html,title,guard=()=>{}){
    const privacyState=typeof state==='undefined'?{}:state,privacyToken=privacyState.privacyRequestId??0;
    const privacyGuard=()=>{if(privacyState.privacySaving||privacyState.privacyIdentityPending)throw Error('身份信息正在更新或尚未读取，请重试身份更新后重新打印');if(privacyToken!==(privacyState.privacyRequestId??0))throw Error('身份显示状态已变化，请重新打印');};privacyGuard();guard();
    let frame=qs('#v2PrintFrame');if(frame)frame.remove();frame=document.createElement('iframe');frame.id='v2PrintFrame';frame.title='A4 报告打印预览';document.body.appendChild(frame);
    const doc=frame.contentDocument,css=new URL('static/css/report-paper.css',location.href).href;
    let rejectPrivacy;const interrupted=new Promise((_,reject)=>{rejectPrivacy=reject;});
    const cancel=()=>{try{privacyGuard();if(frame.isConnected===false)throw Error('打印预览已关闭，请重新打印');}catch(error){rejectPrivacy(error);}};document.addEventListener?.('ecg-report-privacy-change',cancel);
    try{
      doc.open();doc.write(`<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>${esc(title)}</title><link rel="stylesheet" href="${esc(css)}"></head><body><main class="rp-pages">${html}</main></body></html>`);doc.close();
      const styles=new Promise((resolve,reject)=>{const link=doc.querySelector('link');link.onload=resolve;link.onerror=()=>reject(Error('打印样式读取失败，请刷新重试'));if(link.sheet)resolve();});
      await Promise.race([styles,interrupted]);await Promise.race([doc.fonts.ready,interrupted]);privacyGuard();if(frame.isConnected===false)throw Error('打印预览已关闭，请重新打印');guard();ECGReportPaper.number(doc.body);frame.contentWindow.focus();frame.contentWindow.print();
    }catch(error){frame.remove?.();throw error;}
    finally{document.removeEventListener?.('ecg-report-privacy-change',cancel);}
  }
  function bind(){
    document.addEventListener('ecg-report-range-change',renderRangeDraftNotice);
    const more=qs('.report-more-actions');more?.addEventListener('click',event=>{if(event.target.closest('button'))more.open=false;});
    const settingsButton=qs('#openReportSettings');settingsButton.textContent='图条设置';settingsButton.addEventListener('click',event=>{event.preventDefault();event.stopImmediatePropagation();run(()=>chooseReportCategory('strips'))},true);
    const cancel=document.createElement('button');cancel.id='cancelReportExport';cancel.type='button';cancel.className='button secondary';cancel.textContent='取消导出';cancel.hidden=true;cancel.onclick=()=>cancelReportExport(true);qs('#downloadReport').after(cancel);
    const box=document.createElement('div');box.id='occurrenceFilters';box.className='occurrence-filters';
    qs('#editWorkbench .edit-left-stack').appendChild(box);qs('.edit-class-toolbar').hidden=true;
    const menu=document.createElement('div');menu.id='editTypeMenu';menu.className='edit-type-menu';menu.setAttribute('popover','auto');menu.setAttribute('role','menu');menu.hidden=true;document.body.appendChild(menu);
    menu.onclick=e=>{const button=e.target.closest('[data-code]');if(button)chooseFilter(button.dataset.code,button.dataset.mode,button.dataset.template)};
    menu.onkeydown=e=>{
      const buttons=[...menu.querySelectorAll('button')],index=buttons.indexOf(document.activeElement);
      if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();buttons[e.key==='Home'?0:e.key==='End'?buttons.length-1:(index+(e.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length].focus();}
      if(e.key==='Escape'){e.preventDefault();closeTypeMenu(true);}
    };
    menu.addEventListener('toggle',e=>{if(e.newState==='closed'&&openType)closeTypeMenu();});
    window.addEventListener('resize',()=>closeTypeMenu());
    const arrows=document.createElement('div');arrows.className='occurrence-actions';arrows.innerHTML='<label>跳至第 <input id="occJump" type="number" min="1" value="1" aria-label="跳至波形序号"></label><button id="occGo" type="button">定位</button><button id="occDisease" type="button" disabled title="请先选择 S、V、房颤或房扑目标">记录节律确认…</button><span class="occ-scroll-help">上下滚动连续浏览 · 方向键选择位置</span>';qs('#editTemplateGallery').before(arrows);
    const groupEvidence=document.createElement('section');groupEvidence.id='occurrenceGroupEvidence';groupEvidence.hidden=true;qs('#editTemplateGallery').after(groupEvidence);
    bindOccurrenceJump();
    const resumeButton=document.createElement('button');resumeButton.id='occResume';resumeButton.type='button';resumeButton.hidden=true;arrows.appendChild(resumeButton);
    qs('#occDisease').onclick=()=>run(async()=>{
      if(rhythmWrite?.id===state.caseId&&rhythmWrite.caseToken===state.caseRequestId)return;
      if(!['S','V','A','C'].includes(type)||!state.editSelectedSamples.size)throw Error('请先选择 S、V、房颤或房扑事件目标');
      const diagnosis={S:'房速',V:'室速',A:'房颤',C:'房扑'}[type],kind={S:'AT',V:'VT',A:'AF',C:'AFL'}[type];
      const samples=[...state.editSelectedSamples].sort((a,b)=>a-b),matched=[...pageCache.values()].filter(Boolean).flat().filter(e=>e.subtype!=='beat'&&e.target_samples.every(s=>state.editSelectedSamples.has(s))),start=Math.min(samples[0],...matched.map(e=>e.start_sample)),end=Math.max(samples.at(-1),...matched.map(e=>e.end_sample));
      if(!window.confirm(`将 ${samples.length} 个已选心搏所在区间确认为${diagnosis}？`))return;
      const scope={id:state.caseId,caseToken:state.caseRequestId};rhythmWrite=scope;qs('#occDisease').disabled=true;qs('#occDisease').title='正在保存当前节律确认，请等待';
      try{
        await api(`/api/cases/${scope.id}/annotations`,{method:'POST',body:JSON.stringify({sample_index:start,lead:state.editLead,category:'note',label:diagnosis,details:{kind,status:'confirmed',end_sample:end,finding:diagnosis}})});
        if(scope.id!==state.caseId||scope.caseToken!==state.caseRequestId)return;
        await clinicalWorkflow.refresh(scope.id);
        if(scope.id===state.caseId&&scope.caseToken===state.caseRequestId)await loadOccurrences();
      }finally{if(rhythmWrite===scope)rhythmWrite=null;if(scope.id===state.caseId&&scope.caseToken===state.caseRequestId)renderOccurrences();}
    });
    new ResizeObserver(()=>{if(occurrence)renderOccurrences()}).observe(qs('#editTemplateGallery'));
    let scrollFrame;qs('#editTemplateGallery').addEventListener('scroll',()=>{cancelAnimationFrame(scrollFrame);scrollFrame=requestAnimationFrame(renderOccurrences)});
    qs('#editTemplateGallery').addEventListener('keydown',e=>{if(e.key==='ArrowLeft'||e.key==='ArrowRight')e.stopPropagation()});
    const old=qs('.report-workbench'),root=document.createElement('section');root.id='reportV2';root.innerHTML='<nav id="reportV2Nav" aria-label="报告二级导航"></nav><p id="reportV2Notice"></p><div id="reportV2Content"></div>';old.before(root);old.hidden=true;root.after(qs('.report-conclusion-dock'));
    const preflight=qs('#reportPreflight');
    if(preflight){const disclosure=document.createElement('details');disclosure.id='reportPreflightDisclosure';disclosure.innerHTML='<summary>审核前检查</summary>';disclosure.append(preflight);qs('#reportV2Notice').after(disclosure);}
    root.addEventListener('click',event=>{const b=event.target.closest('button');if(!b||b.disabled)return;if(b.dataset.reviewRhythm!==undefined)run(()=>openRhythmReview(b.dataset.reviewRhythm));if(b.hasAttribute('data-rhythm-replace'))run(replaceReturnedRhythm);});
    root.addEventListener('click',event=>{const b=event.target.closest('button');if(!b||b.disabled)return;if(b.dataset.category)run(()=>chooseReportCategory(b.dataset.category));if(b.dataset.locate!==undefined)run(()=>locate(reportData.items[Number(b.dataset.locate)]));if(b.dataset.remove!==undefined)removeReportSelection(Number(b.dataset.remove));if(b.dataset.move!==undefined){const i=Number(b.dataset.move),j=i+Number(b.dataset.delta);[state.reportComposition.selected_events[i],state.reportComposition.selected_events[j]]=[selected()[j],selected()[i]];dirty();run(renderReportBody)}if(b.dataset.backEvent!==undefined)run(()=>backToReportEvent(Number(b.dataset.backEvent)));if(b.dataset.ack!==undefined){Object.assign(state.reportComposition.diagnosis_blocks[Number(b.dataset.ack)],{acknowledged:true,needs_review:false});dirty();run(renderReportBody)}});
    root.addEventListener('change',event=>{const el=event.target;if(el.hasAttribute('data-estimate-paper-gain')){state.reportComposition=composition();state.reportComposition.paper.gain=el.value;dirty();return;}if(changePaperSettings(el)||changeStripSettings(el))return;if(el.dataset.include!==undefined)selectEvent(reportData.items[Number(el.dataset.include)],el.checked)});
    root.addEventListener('input',event=>{const el=event.target;if(el.dataset.caption!==undefined){selected()[Number(el.dataset.caption)].caption=el.value;dirty()}if(el.dataset.block!==undefined){Object.assign(state.reportComposition.diagnosis_blocks[Number(el.dataset.block)],{text:el.value,manual:true,acknowledged:false});dirty()}});
    qs('#downloadReport').addEventListener('click',event=>{event.preventDefault();event.stopImmediatePropagation();run(downloadReport)},true);
    const timebar=document.createElement('input');timebar.type='range';timebar.id='v2EditTime';timebar.min='0';timebar.step='.1';timebar.setAttribute('aria-label','编辑连续波形时间导航');qs('#editWaveCanvasWrap').after(timebar);
    const requestEditTime=()=>{clearTimeout(editTimeTimer);editTimeTimer=0;run(loadEditWaveform)};
    timebar.oninput=()=>{state.editStart=Math.max(0,Math.min(Number(timebar.value)||0,Number(timebar.max)||0));renderEditOverview();qs('#editWaveMeta').textContent='松开后读取所选时间段…';clearTimeout(editTimeTimer);editTimeTimer=setTimeout(requestEditTime,120)};
    timebar.onchange=requestEditTime;syncEditTimeSlider();
    const overviewTime=qs('#timeSlider');if(overviewTime)qs('#waveformCanvas').parentElement.after(overviewTime);
    const h=document.createElement('article');h.id='hrvWindowPanel';h.className='card';
    const trends=qs('#page-trends');hrvLegacyWeb=document.createElement('section');hrvLegacyWeb.className='hrv-legacy-reference';hrvLegacyWeb.setAttribute('aria-label','全记录参考与源报告对照');
    hrvLegacyWeb.innerHTML='<h2>全记录参考与源报告对照</h2><p>以下全天趋势、N-N 分布与源报告对照覆盖全记录，不随上方 24 小时窗口切换；不替代当前窗口的统计。</p>';
    for(const node of [qs('#trendMetrics'),trends.querySelector(':scope > .chart-grid')])if(node)hrvLegacyWeb.append(node);
    h.append(hrvLegacyWeb);trends.append(h);
    document.querySelectorAll('[data-page="events"],[data-workflow-page="events"]').forEach(el=>el.hidden=true);
    if(state.caseId&&state.currentPage==='edit')run(loadOccurrences);
  }
  document.addEventListener('DOMContentLoaded',bind);
  function applyVoltageEstimate(estimate){
    if(!state.caseId||!state.report||!state.reportComposition)throw Error('请先打开病例并载入报告，再应用估算设置');
    if(state.reportSaving||state.reportStale)throw Error('请先完成保存或载入最新报告，再修改估算设置');
    state.reportComposition.paper={...composition().paper,voltage_estimate:ECGVoltage.normalize(estimate)};
    dirty();run(renderReportBody);
  }
  if(globalThis.ECGVoltage)ECGVoltage.applyToReport=applyVoltageEstimate;
  function linkedContext(){
    const identity=state.editReadIdentity;
    return Object.freeze({caseId:state.caseId,caseToken:state.caseRequestId,type,template,mode:editMode,analysis_basis:identity?.id===state.caseId&&identity.caseToken===state.caseRequestId?identity.analysis_basis:null,analysis_revision:identity?.id===state.caseId&&identity.caseToken===state.caseRequestId?identity.analysis_revision:null});
  }
  function linkedCurrent(expected){
    const scope=globalThis.ECGLinkedSelection?.snapshot().scope;
    return !!expected&&!!scope&&state.currentPage==='edit'&&scope.caseId===state.caseId&&scope.caseToken===state.caseRequestId&&['caseId','caseToken','analysis_basis','analysis_revision','beatRevision'].every(k=>String(scope[k])===String(expected[k]));
  }
  function focusLinkedBeat(sample,time,expected){
    if(!linkedCurrent(expected)||!Number.isSafeInteger(sample)||sample<0||!Number.isFinite(time))return false;
    state.editSelectedSample=sample;setEditStart(Math.max(0,time-state.editDuration*.35));renderOccurrences();
    return true;
  }
  function setLinkedChecked(sample,checked,expected){
    if(!linkedCurrent(expected)||!Number.isSafeInteger(sample)||sample<0)return false;
    if(checked)state.editSelectedSamples.add(sample);else state.editSelectedSamples.delete(sample);
    state.editSelectedSample=sample;state.editSelectionAnchor=sample;
    beatEditor.syncOccurrenceSelection?.();renderOccurrences();renderEditWaveform();if(state.editMode==='library')renderEditLibrary();
    return true;
  }
  return {linkedContext,focusLinkedBeat,setLinkedChecked,prepareHrvLoad,refreshPrivacyViews,cancelReportExport,hasRhythmReturn,returnFromRhythm,captureEditView,activateEditView,occurrenceBookmark,currentOccurrenceBookmark,loadOccurrences,renderOccurrences,releaseOccurrenceWaves,refreshReport,renderReportShell,loadHrv,save,print,applyVoltageEstimate,addStrip(e){category='strips';selectEvent(e,true)}};
})();
// Replace representative-only loaders; preserve existing continuous-waveform editor tools.
loadEditTemplateStrips=clinicalUI.loadOccurrences;
renderEditGallery=clinicalUI.renderOccurrences;
loadReport=clinicalUI.refreshReport;
renderReport=clinicalUI.renderReportShell;
saveReport=clinicalUI.save;
printReportPreview=clinicalUI.print;
const loadTrendsLegacy=loadTrends;
loadTrends=async windowIndex=>{clinicalUI.prepareHrvLoad();const loaded=await loadTrendsLegacy(windowIndex);if(loaded&&loaded.caseId===state.caseId&&loaded.caseToken===state.caseRequestId&&loaded.requestId===state.trendsRequestId)await clinicalUI.loadHrv('#hrvWindowPanel',windowIndex,loaded.data)};
const goPageLegacy=goPage;
goPage=function(name,options={}){
  const leavingReport=state.currentPage==='report'&&name!=='report'&&name!=='events';
  if(name==='events')name='report';
  if(!options.editFullscreenTransition){
    if(name==='edit'&&state.currentPage==='review'){state.editStart=state.start;state.editLead=state.leads[0]||'II';}
    else if(name==='review'&&state.currentPage==='edit'){state.start=state.editStart;state.leads=[state.editLead,...state.leads.filter(l=>l!==state.editLead)];}
  }
  const result=goPageLegacy(name,options);
  if(leavingReport&&state.currentPage!=='report')clinicalUI.cancelReportExport();
  // Navigation can be declined by the unsaved-work guard. Release only after
  // the actual page changed, not merely because another page was requested.
  if(state.currentPage!=='edit'&&!options.editFullscreenTransition)clinicalUI.releaseOccurrenceWaves();
  return result;
};

const setEditModeLegacy=setEditMode;
setEditMode=function(mode,rerender=true){
  setEditModeLegacy(mode,rerender);
  const panel=document.querySelector('.edit-gallery-panel'),library=document.querySelector('#editLibraryMatrix');
  if(!panel||!library||!document.querySelector("#occurrenceFilters"))return;
  if(mode==='library'){
    library.hidden=true;library.parentElement.appendChild(panel);panel.classList.add('v2-library-gallery');
    const filters=document.querySelector('#occurrenceFilters');panel.prepend(filters);
  }else{
    document.querySelector('#editWorkbench .edit-main-stack').insertBefore(panel,document.querySelector('#editWorkbench .edit-waveform-panel'));panel.classList.remove('v2-library-gallery');
    document.querySelector('#editWorkbench .edit-left-stack').appendChild(document.querySelector('#occurrenceFilters'));
  }
  requestAnimationFrame(clinicalUI.renderOccurrences);
};
