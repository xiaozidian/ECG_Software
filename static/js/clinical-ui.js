"use strict";
/* Shared workstation UI. Selection for editing and selection for reporting are independent. */
const clinicalUI=(()=>{
  const A=ECGClinicalAnalysis,esc=escapeHtml,qs=s=>document.querySelector(s);
  const copy=x=>JSON.parse(JSON.stringify(x));
  const reportCategories=A.reportCategories||A.categories;
  const reportCategoryOf=e=>['pause','rr_candidate'].includes(e?.category)?'rr_interval':e?.category;
  const eventAliases=e=>e?.rr_aliases||[{event_id:e?.event_id,basis_version:e?.basis_version,category:e?.category}];
  const sameReportEvent=(e,id)=>!!e&&(e.event_id===id||e.rr_alias_event_ids?.includes(id));
  const stripKey=s=>s?.strip_id||s?.event_id;
  let activeStripKey=null,stripSequence=0,rangeResume=null;
  const newStripId=()=> 'af-strip:'+(globalThis.crypto?.randomUUID?.()||Date.now()+'-'+(++stripSequence));
  function selectionsForEvent(e,valid=true){return selected().filter(s=>eventAliases(e).some(a=>a.event_id===s.event_id&&(!valid||a.basis_version===s.basis_version)));}
  function selectionForEvent(e,valid=true){const items=selectionsForEvent(e,valid);return items.find(s=>stripKey(s)===activeStripKey)||items[0];}
  function newStripSettings(e,raw=null){const c=composition();return ECGReportEngine.settingsForEvent(e,raw||e.retained_settings||c.strip_category_defaults?.[reportCategoryOf(e)]||{duration_s:c.strip_defaults.duration_s});}
  function projectRRSelections(){
    const seen=new Set(),removed=[],affected=new Set(),live=new Map();
    state.reportComposition.selected_events=selected().filter(s=>{const e=selectedLookup.get(s.event_id),key=e?.basis_version===s.basis_version?e.rr_semantic_key:null;if(!key)return true;affected.add(e.category+':'+e.subtype);if(seen.has(key)){removed.push(s.event_id);return false;}seen.add(key);live.set(e.category+':'+e.subtype,e.label);return true;});state.reportRRMerged=removed;
    if(removed.length){
      // Hydration is a view projection: only obsolete/duplicate generated RR
      // blocks follow the first retained selection; handwritten blocks stay exact.
      const blocks=[];for(const b of state.reportComposition.diagnosis_blocks||[]){if(b.manual||!affected.has(b.key))blocks.push(b);else if(live.has(b.key)){blocks.push(b);live.delete(b.key);}}
      live.forEach((text,key)=>blocks.push({key,text,manual:false,needs_review:false,acknowledged:false}));state.reportComposition.diagnosis_blocks=blocks;
    }
  }
  function selectedCategoryCount(key){if(key==='ST')return new Set(sttUses().filter(x=>x.table||x.text||x.strip).map(x=>x.event_id)).size;const keys=new Set();for(const s of selected()){const e=selectedLookup.get(s.event_id);if((key==='rr_interval'?reportCategoryOf(e):e?.category)!==key)continue;keys.add(e?.rr_semantic_key||s.event_id);}return keys.size;}
  const tabs=[...reportCategories,['tables','数据表格'],['strips','报告图条'],['final','报告']];
  let occurrenceToken=0,reportToken=0,waveToken=0,editCase=null,occurrence=null,occurrenceContext=null,editMode='all',template='all',type='N',pageCache=new Map(),tileWidth=150,editTimeTimer=0,occurrenceReadAbort=null;
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
  let pauseBand='all',rrSource='all',reportTimeRange=null,reportSpacing=0,sttGroup='all',sttReportFocus=null;
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
    target._hrvEditor?.destroy();target._hrvEditor=null;
    if(target._hrvRenderCase!==state.caseId){target._hrvPaperOpen=false;target._hrvRenderCase=state.caseId;}
    const previousPaper=target.querySelector('.hrv-paper-preview');if(previousPaper)target._hrvPaperOpen=previousPaper.open;
    const legacy=target.id==='hrvWindowPanel'?hrvLegacyWeb:null;
    if(legacy)legacy.remove();
    target.innerHTML=html;
    const nextPaper=target.querySelector('.hrv-paper-preview');if(nextPaper)nextPaper.open=Boolean(target._hrvPaperOpen);
    if(legacy){const paper=target.querySelector('.hrv-paper-preview');if(paper)paper.before(legacy);else target.append(legacy);}
  }
  function bindHrvNavigation(target,current){
    if(target.id!=='hrvWindowPanel')return;
    const toolbar=target.querySelector('.hrv-evidence-toolbar');if(!toolbar)return;
    const review=target.querySelector('.hrvr-review');
    if(review){review.id='hrvSelectedPeriodReview';review.tabIndex=-1;review.style.scrollMarginTop='68px';}
    toolbar.insertAdjacentHTML('beforeend','<button type="button" class="button secondary" data-hrv-reference>全记录 N-N 参考</button><button type="button" class="button secondary" data-hrv-nn-settings>NN纳入范围…</button>');
    const moveTo=node=>{if(!current()||!node?.isConnected)return;node.focus({preventScroll:true});node.scrollIntoView({block:'start'});};
    target.querySelector('[data-hrv-reference]').onclick=()=>moveTo(hrvLegacyWeb);
    const settings=target.querySelector('[data-hrv-nn-settings]');
    settings.disabled=!clinicalWorkflow.writable();
    settings.title=settings.disabled?'当前服务只读，不能修改分析参数':'打开当前病例分析参数（含 NN 纳入范围）；修改需预览并确认修订';
    settings.onclick=()=>run(()=>{if(!current())return;beatEditor.openSettings();});
    if(hrvLegacyWeb){
      let back=hrvLegacyWeb.querySelector('[data-hrv-review-return]');
      if(!back){back=document.createElement('button');back.type='button';back.className='button secondary';back.dataset.hrvReviewReturn='';back.textContent='返回时段复核';hrvLegacyWeb.querySelector('h2').after(back);}
      back.disabled=!review;back.onclick=()=>moveTo(review);
    }
  }
  function composition(){
    const source=state.reportComposition||state.report?.composition||{};
    return {...source,schema_version:source.schema_version===3?3:2,included_pages:ECGReportSections.selectedPages(source),page_selection_version:1,selected_events:source.selected_events||[],category_reviews:source.category_reviews||{},diagnosis_blocks:source.diagnosis_blocks||[],fast_slow_mode:source.fast_slow_mode||'rr',paper:{...(source.paper||{}),size:'A4',orientation:'portrait'},strip_defaults:ECGReportEngine.settings(source.strip_defaults)};
  }
  const sttGroups={all:'全部记录',ST:'ST事件',T:'T改变',ST_NOTE:'复核记录',pending:'待处理'};
  const sttOutcomes={st_depression:'ST段压低',st_elevation:'ST段抬高',t_change:'T波改变',nonspecific:'非特异性ST-T改变',no_change:'本段未见明确ST-T改变',artifact:'伪差或体位改变',indeterminate:'本段无法判读'};
  function sttReviewed(e){return e?.category==='ST'&&(e.stt_review_state==='reviewed'||e.stt_review_state===undefined&&e.diagnosis_status==='confirmed');}
  function sttEligibility(e){return e?.stt_report_eligibility||{table:sttReviewed(e),text:sttReviewed(e),strip:sttReviewed(e)};}
  function sttUses(c=composition()){
    if(Array.isArray(c.stt_report_use))return c.stt_report_use;
    return (c.selected_events||[]).flatMap(s=>{const e=selectedLookup.get(s.event_id);if(e?.category!=='ST')return [];const current=e.basis_version===s.basis_version,eligible=sttEligibility(e);return [{event_id:s.event_id,basis_version:s.basis_version,table:current&&eligible.table===true&&c.included_pages.includes('st_events'),text:s.referenced_in_report===true,strip:s.print_enabled!==false&&c.included_pages.includes('event_strips')}];});
  }
  function sttUse(e){return sttUses().find(x=>x.event_id===e?.event_id)||null;}
  function sttNarrative(e){const leads=e.stt_review_receipt?.leads||e.stt_event_evidence?.leads||[e.lead].filter(x=>x&&x!=='全部');return `${formatElapsed(e.time_s)}–${formatElapsed(e.end_s??e.time_s)} · ${leads.join('/')||'复核导联见记录'} · ${sttOutcomes[e.stt_result_code]||e.label}${e.stt_physician_note?'；'+e.stt_physician_note:''}`;}
  function syncSTTControls(){
    document.querySelectorAll('[data-stt-use]').forEach(input=>{const e=reportData?.items[Number(input.dataset.sttIndex)];input.checked=!!sttUse(e)?.[input.dataset.sttUse];});
    if(active?.category==='ST')renderEventNavigation(reportWaveReady);
  }
  async function setSTTUse(e,key,checked,settings=null){
    if(!e||e.category!=='ST'||!['table','text','strip'].includes(key))throw Error('ST-T采用对象无效');
    if(globalThis.ECGReportRange?.pending?.().length&&!await ECGReportRange.resolveLeave()){syncSTTControls();return;}
    if(state.reportSaving||state.reportStale||state.reportEvidenceLoading||state.reportViewLoading)throw Error('请等待报告依据核对完成后采用');
    if(checked&&(!sttReviewed(e)||sttEligibility(e)[key]!==true))throw Error('本条复核尚未完成、依据已变化或不支持此用途；请先修改复核');
    const c=composition(),uses=copy(sttUses(c));state.reportComposition=c;
    let entry=uses.find(x=>x.event_id===e.event_id);
    if(!entry){entry={event_id:e.event_id,basis_version:e.basis_version,table:false,text:false,strip:false};uses.push(entry);}
    if(entry.basis_version!==e.basis_version&&checked)throw Error('已有采用内容来自旧复核，请先核对并撤出旧用途');
    entry[key]=checked;if(checked)entry.basis_version=e.basis_version;if(checked){const page={table:'st_events',text:'summary',strip:'event_strips'}[key];if(!c.included_pages.includes(page))c.included_pages.push(page);}
    if(key==='strip'){
      const old=selectionForEvent(e,false);
      if(checked){
        if(old&&old.basis_version!==e.basis_version)throw Error('已有图条来自旧复核，请先移除或重新核对');
        if(!old)c.selected_events.push({...copy(e.retained_settings||{}),...newStripSettings(e,settings),event_id:e.event_id,basis_version:e.basis_version,caption:e.retained_settings?.caption||e.label,referenced_in_report:false,print_enabled:true});
        else {if(settings)Object.assign(old,newStripSettings(e,settings));old.print_enabled=true;}
      }else{c.selected_events=c.selected_events.filter(s=>s.event_id!==e.event_id);ECGReportRange.forget?.(e.event_id);}
    }
    c.stt_report_use=uses.filter(x=>x.table||x.text||x.strip);if(key==='text'&&!checked)c.diagnosis_blocks=c.diagnosis_blocks.filter(block=>block.key!=='ST:review:'+e.event_id);selectedLookup.set(e.event_id,e);delete c.category_reviews.ST;
    syncText();dirty();renderReportShell();syncSTTControls();
    if(active?.event_id!==e.event_id)await locate(e);
  }
  async function showSTRecord(e){
    if(!e||e.category!=='ST'||!await resolveWorkstationLeave())return;
    state.sttRequestedRecordId=e.event_id;goPage('stt');
  }
  let reportAutosaveTimer=null,reportSavePromise=null;
  function queueReportAutosave(delay=700){
    clearTimeout(reportAutosaveTimer);const id=state.caseId,token=state.caseRequestId;
    reportAutosaveTimer=setTimeout(async()=>{if(id!==state.caseId||token!==state.caseRequestId||!state.reportDirty||state.reportStale||!state.report||!clinicalWorkflow.writable())return;
      if(state.reportSaving||state.reportEvidenceLoading||state.reportViewLoading){queueReportAutosave(400);return;}
      try{await save('draft',{automatic:true});}catch(error){if(id===state.caseId&&token===state.caseRequestId){const status=qs('#reportSaveState');if(status)status.textContent='自动保存未完成：'+error.message+'；编辑仍保留';}}
    },delay);
  }
  async function flushReportAutosave(){clearTimeout(reportAutosaveTimer);const id=state.caseId,token=state.caseRequestId;if(reportSavePromise)await reportSavePromise;
    for(let i=0;i<3&&state.reportDirty;i++){if(id!==state.caseId||token!==state.caseRequestId)throw Error('病例已变化，未继续保存旧编辑');await save('draft',{automatic:true});}
    if(state.reportDirty||state.reportSaving)throw Error('报告尚未保存完成，当前编辑仍保留');
  }
  async function resolveReportLeave(){
    const id=state.caseId,token=state.caseRequestId,current=()=>id===state.caseId&&token===state.caseRequestId;
    try{await flushReportAutosave();return current();}
    catch(error){
      if(!current())return false;
      return ECGUnsavedNavigation.resolve({title:'报告草稿尚未保存',detail:error.message,saveLabel:'重试保存并继续',isCurrent:current,
        save:()=>flushReportAutosave(),discard:()=>{clearTimeout(reportAutosaveTimer);state.reportComposition=copy(state.report.composition);state.reportDirty=false;qs('#conclusionEditor').value=state.report.conclusion||'';renderReportShell();}});
    }
  }
  function dirty(){cancelReportExport();state.reportDirty=true;if(qs('#reportSaveState'))qs('#reportSaveState').textContent='正在自动保存…';clinicalWorkflow.renderPreflight();queueReportAutosave();}
  function svg(wave,event=null,compact=false,dimensions={}){
    if(compact)return ECGOccurrenceCard.svg(wave,event,{...dimensions,annotations:'none',centerSample:event?.sample_index});
    return ECGReportWorkspace.reviewWaveSvg(wave,event,{...dimensions,recordStart:state.caseData?.metadata?.start_time});
  }
  function eventWaveKey(e,id,leads,centered=false){return [waveEvidenceScope,id,e.basis_version,e.event_id,leads,centered?'centered-card':'overview'].join('|');}
  function releaseOccurrenceWaves(){thumbnailCache.retain('occurrence',[]);globalThis.ECGSourceGroupEvidence?.clear();if(state.currentPage!=='edit'&&occurrenceReadAbort){occurrenceToken++;occurrenceReadAbort.abort();occurrenceReadAbort=null;}}
  async function eventWave(e,id=state.caseId,leads='II,V1,V5',options={}){
    const range=options.centeredCard?ECGOccurrenceCard.windowFor(e):{start:Math.max(0,e.start_sample/200-.8),end:e.end_sample/200+1.6};
    const {start,end}=range,key=eventWaveKey(e,id,leads,options.centeredCard);
    return thumbnailCache.get(key,JSON.stringify([id,leads,waveEvidence]),{start,end},options);
  }
  const typeNames={N:'正常搏',S:'房早',V:'室早',other:'其他心搏'};
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
    closeTypeMenu();state.editScatterFilterActive=true;state.editSelectedSamples=new Set();state.editSelectedSample=null;state.editSelectionAnchor=null;state.editSelection=null;state.editSelectionStrips=[];state.editMorphDraft=null;globalThis.ECGLinkedSelection?.clear({origin:'category-filter'});
    type=code;editMode=mode;template=String(templateId);state.editSelectedClass=template==='all'?'source-'+code:'custom-'+template;
    renderEditClasses();renderEditScatter();run(loadOccurrences);
    requestAnimationFrame(()=>qs(`[data-occ-type="${['N','S','V'].includes(code)?code:'other'}"]`)?.focus());
  }
  function openTypeMenu(button){
    const code=button.dataset.occType,menu=qs('#editTypeMenu');
    if(openType===code){closeTypeMenu(true);return;}
    closeTypeMenu();openType=code;button.setAttribute('aria-expanded','true');
    const rows=code==='other'?[{code:'other',mode:'all',template:'all',label:'全部其他心搏'},...Object.entries(ECGBeatEngine.types).filter(([k])=>!['N','S','V'].includes(k)).flatMap(([k,t])=>modeChoices(k).map(([mode,label])=>({code:k,mode,template:'all',label:`${k} · ${mode==='all'?t.name:label}`})))]:[
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
    const choices=[['other',{name:'全部其他心搏'}],...Object.entries(ECGBeatEngine.types||{})];
    host.innerHTML=`<div class="occurrence-template-tools"><label>搜索模板<input id="occSearch" type="search" placeholder="模板名称，如 S1"></label><label>形态模板<select id="occTemplate"></select></label></div><div class="occurrence-current-filter"><span>当前筛选</span><strong>${esc(typeNames[type]||ECGBeatEngine.types[type]?.name||type)} · ${esc(modeLabel())}</strong></div><div class="edit-type-dock" role="group" aria-label="左下角心搏类型与事件模式">${['N','S','V','other'].map(k=>`<button type="button" id="editType${k}" data-occ-type="${k}" aria-haspopup="menu" aria-expanded="false" aria-controls="editTypeMenu" aria-label="${k==='other'?'其他类型':k+' '+typeNames[k]+'类型'}" aria-pressed="${template==='all'&&(k===type||(k==='other'&&!['N','S','V'].includes(type)))}"><strong>${k==='other'?'其他':k}</strong><span>${typeNames[k]||'类型'}</span><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4"/></svg></button>`).join('')}</div><div hidden><select id="occType" aria-label="心搏类型">${choices.map(([k,t])=>`<option value="${k}" ${type===k?'selected':''}>${k} ${esc(t.name)}</option>`).join('')}</select><select id="occMode" aria-label="事件模式">${modeChoices(type).map(([k,v])=>`<option value="${k}" ${editMode===k?'selected':''}>${esc(v)}</option>`).join('')}</select></div>`;
    updateTemplates();
    host.querySelectorAll('[data-occ-type]').forEach(button=>{button.title='筛选类别与事件模式，不修改心搏分类';button.setAttribute('aria-label','筛选 '+(button.dataset.occType==='other'?'其他心搏':button.dataset.occType+' '+typeNames[button.dataset.occType]));button.onclick=()=>{const code=button.dataset.occType,selected=['N','S','V'].includes(type)?type:'other';if(code!==selected||!state.editScatterFilterActive){chooseFilter(code);return;}openTypeMenu(button);};});
    qs('#occType').onchange=e=>chooseFilter(e.target.value);
    qs('#occMode').onchange=e=>chooseFilter(type,e.target.value);
    qs('#occTemplate').onchange=e=>{state.editScatterFilterActive=true;state.editSelectedSamples=new Set();state.editSelectedSample=null;template=e.target.value;state.editSelectedClass=template==='all'?'source-'+type:'custom-'+template;renderEditClasses();renderEditScatter();run(loadOccurrences)};
    qs('#occSearch').oninput=updateTemplates;
  }
  function updateTemplates(){
    const select=qs('#occTemplate');if(!select)return;
    const search=qs('#occSearch').value.toLowerCase();
    const matches=(state.editTemplates||[]).filter(t=>(t.source_class==='source-'+type||String(t.id)===template)&&(t.name.toLowerCase().includes(search)||String(t.id)===template));
    select.innerHTML='<option value="all">全部模板</option>'+matches.map(t=>`<option value="${t.id}" ${String(t.id)===template?'selected':''}>${esc(t.name)} · ${t.beat_count??t.sample_indices.length}</option>`).join('');
  }
  function editParams(offset=0){return {class_code:template!=='all'&&editMode==='all'?'all':type,mode:editMode,template_id:template,offset,limit:48}}
  let occurrenceLeadCount=3;
  const occurrenceGrid=(total,width,top=0)=>{
    const rows=['cluster','library'].includes(state.editMode)&&innerWidth>=1100?Number(qs('#editTemplateGallery')?.dataset.workspaceRows)||2:ECGOccurrenceCard.geometry.visibleRows;
    return ECGReviewTools.virtualGrid(total,width,top,{...ECGOccurrenceCard.geometry,visibleRows:rows});
  };
  function occurrenceViewControls(){
    const heading=qs('#editGalleryTitle')?.closest('.edit-panel-heading');if(!heading)return;
    let controls=qs('#occurrenceViewControls');
    if(!controls){
      controls=document.createElement('div');controls.id='occurrenceViewControls';controls.className='occurrence-view-controls';
      controls.innerHTML='<label>小图导联<select id="occurrenceLeadCount" aria-label="小图导联数量"><option value="3">3 导联 · II / V1 / V5</option><option value="1">1 导联 · II</option><option value="2">2 导联 · II / V1</option></select></label><span id="occurrenceLeadNames"></span>';
      heading.after(controls);qs('#occurrenceLeadCount').onchange=e=>{occurrenceLeadCount=Number(e.target.value)===1?1:Number(e.target.value)===2?2:3;renderOccurrences()};
    }
    qs('#occurrenceLeadCount').value=String(occurrenceLeadCount);
    qs('#occurrenceLeadNames').textContent=ECGOccurrenceCard.leads('II',occurrenceLeadCount).join(' / ')+' · 各导联自适应幅度 · 设备单位 u，未校准';
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
    }else{type=state.editSelectedClass?.startsWith('source-')?state.editSelectedClass.slice(7):'N';editMode='all';template='all';occurrenceLeadCount=3;}
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
    const token=++occurrenceToken,id=state.caseId;pageCache.clear();occurrence=null;occurrenceContext=null;filters();
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
      syncWaveEvidence(id,result);if(editMode==='all'&&template==='all')state.editFilterCount={id,code:type,total:result.total};occurrence=result;occurrenceContext={id,caseToken,evidenceScope:waveEvidenceScope};syncOccurrenceJump(true);pageCache.set(result.offset||0,result.items);
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
    // Layout callbacks can run after case selection, before its fresh list arrives.
    // Keep valid same-case DOM, but never dispatch old records under a new scope.
    const context=occurrenceContext;
    if(state.currentPage!=='edit'||!context||context.id!==state.caseId||context.caseToken!==state.caseRequestId||context.evidenceScope!==waveEvidenceScope){occurrenceFocus=null;releaseOccurrenceWaves();return;}
    const host=qs('#editTemplateGallery');if(!host||!occurrence)return;
    host.classList.add('occurrence-viewport');host.tabIndex=0;host.setAttribute('aria-label','心搏出现记录，向下滚动连续浏览');host.removeAttribute('aria-live');
    const total=occurrence.total,g=occurrenceGrid(total,host.clientWidth,host.scrollTop),{first,last}=g,token=occurrenceToken,id=context.id,caseToken=context.caseToken;
    tileWidth=g.width;host.style.setProperty('--occ-height',g.height+'px');host.scrollLeft=0;
    const focused=host.contains(document.activeElement)?document.activeElement.closest('[data-occ-index]')?.dataset.occIndex:null,focusInput=document.activeElement?.tagName==='INPUT';
    syncEditTimeSlider();
    const templateName=(state.editTemplates||[]).find(t=>String(t.id)===template)?.name;
    const sourceLabel=templateName&&editMode==='all'?templateName+' · 完整形态模板':type+' · '+modeLabel();
    qs('#editGalleryTitle').textContent=`${sourceLabel} · 全部出现记录`;
    qs('#editGalleryDescription').textContent='单击查看；Ctrl/⌘点击或空格多选；方向键定位；右键改型须预览确认';
    occurrenceViewControls();
    qs('#editGalleryCount').textContent=`${g.visibleFirst}–${g.visibleLast} / ${total}`;
    syncOccurrenceJump();
    const visibleSamples=new Set();for(let i=g.visibleFirst-1;i<g.visibleLast;i++){const row=pageCache.get(Math.floor(i/48)*48)?.[i%48];for(const sample of row?.target_samples||[])visibleSamples.add(sample);}
    beatEditor.renderOccurrenceToolbar?.({sourceLabel,code:type,savingRhythm:rhythmWrite?.id===state.caseId&&rhythmWrite.caseToken===state.caseRequestId,totalRecords:total,totalSampleCount:editMode==='all'?total:null,visibleRecords:Math.max(0,g.visibleLast-g.visibleFirst+1),visibleSampleCount:visibleSamples.size,selectedCount:state.editSelectedSamples.size,lead:state.editLead||'II',revision:occurrence.analysis_revision??state.caseData?.analysis_revision});
    if(!total){occurrenceFocus=null;syncOccurrenceJump(true);releaseOccurrenceWaves();host.innerHTML='<p class="empty-state">0 条匹配记录</p>';return;}
    let lane=host.querySelector('.occurrence-lane');if(!lane){host.innerHTML='<div class="occurrence-lane"></div>';lane=host.firstElementChild;}
    const leads=ECGOccurrenceCard.leads('II',occurrenceLeadCount).join(',');
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
        const node=card.querySelector('.occurrence-wave'),dimensions={width:Math.max(1,tileWidth-18),height:ECGOccurrenceCard.geometry.waveHeight},size=dimensions.width+'|'+dimensions.height;
        if(card.occurrenceWave===w&&card.dataset.waveSize===size)return;
        card.occurrenceWave=w;card.dataset.waveSize=size;node.innerHTML=svg(w,e,true,dimensions);
        card.title=`${e.label} · ${e.beat_count} 搏 · ${w.duration_s} 秒 · ${leads}${w.stride>1?' · 步进 '+w.stride+' 采样的概览，请点击回看完整波形':''}`;
      };
      if(reused){ECGOccurrenceCard.syncSelection(card,e,state);if(card.occurrenceWave)renderTileWave(card.occurrenceWave);continue;}
      const isCurrent=()=>state.currentPage==='edit'&&token===occurrenceToken&&id===state.caseId&&caseToken===state.caseRequestId&&context===occurrenceContext&&evidenceScope===waveEvidenceScope&&lane.dataset.occScope===scope&&card.isConnected;
      const code=e.class_code||type,status=e.diagnosis_status==='edited'?'已修订':e.diagnosis_status==='confirmed'?'已确认':'待审核';
      card.innerHTML=`<button type="button" class="occurrence-open" aria-label="第${n+1}条 ${esc(e.label)}，${e.beat_count}搏，${status}；单击选择，双击查看12导联，空格或Ctrl点击多选"><span class="occurrence-card-heading"><strong class="occurrence-code">${esc(code)}</strong>${e.beat_count>1?`<span class="occurrence-group-count">×${e.beat_count} 搏</span>`:''}</span><span class="occurrence-wave">读取波形…</span><span class="occurrence-card-footer"><time>${formatElapsed(e.time_s)}</time><span>${n+1}/${total}</span></span></button><input type="checkbox" hidden tabindex="-1" aria-hidden="true">`;
      ECGOccurrenceCard.syncSelection(card,e,state);
      let waveFailed=false;
      const selectCard=toggle=>{if(!isCurrent())return;if(toggle){const all=e.target_samples.every(s=>state.editSelectedSamples.has(s));e.target_samples.forEach(s=>all?state.editSelectedSamples.delete(s):state.editSelectedSamples.add(s));}else if(!e.target_samples.every(s=>state.editSelectedSamples.has(s)))state.editSelectedSamples=new Set(e.target_samples);state.editSelectedSample=e.sample_index;beatEditor.syncOccurrenceSelection();setEditStart(Math.max(0,e.time_s-2));renderEditScatter();
        const evidenceHost=qs('#occurrenceGroupEvidence');
        if(evidenceHost)globalThis.ECGSourceGroupEvidence?.mount(evidenceHost,{item:e,recordStart:state.caseData?.metadata?.start_time,
          isCurrent:()=>isCurrent(),
          loadWave:(params,signal)=>api(`/api/cases/${id}/waveform?${new URLSearchParams({...params,...waveEvidence})}`,{signal,readLane:'source-group'}),
          onLocate:time=>setEditStart(Math.max(0,time-2))});
      };
      card.querySelector('button').onclick=ev=>{if(waveFailed)loadTileWave();selectCard(Boolean(ev?.ctrlKey||ev?.metaKey));};
      beatEditor.registerOccurrence(card,e,{code:type,isCurrent,onLeads:leads=>{occurrenceLeadCount=leads.length;renderOccurrences();},identity:Object.fromEntries(['analysis_basis','analysis_revision','beat_revision','data_version'].map(key=>[key,occurrence[key]])),samples:async visible=>{
        if(!isCurrent())throw Error('筛选集合已变化，请重新打开菜单');
        if(visible){const view=currentGrid(),samples=[];for(let i=view.visibleFirst-1;i<view.visibleLast;i++){const row=pageCache.get(Math.floor(i/48)*48)?.[i%48];if(row)samples.push(...row.target_samples)}return [...new Set(samples)];}
        const samples=[];for(let offset=0;offset<occurrence.total;offset+=200){const result=await endpoint('template-occurrences',{...editParams(offset),limit:200},id);if(token!==occurrenceToken||!sameEvidence(result,occurrence))throw Error('心搏集合已变化，请刷新后重试');samples.push(...result.items.flatMap(x=>x.target_samples))}return [...new Set(samples)];
      }});
      card.querySelector('input').onchange=ev=>{e.target_samples.forEach(s=>ev.target.checked?state.editSelectedSamples.add(s):state.editSelectedSamples.delete(s));state.editSelectedSample=e.sample_index;beatEditor.syncOccurrenceSelection();renderEditScatter();};
      card.onkeydown=ev=>{if([' ','ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(ev.key)){ev.stopPropagation();ev.preventDefault();if(ev.key===' '){if(waveFailed)loadTileWave();else selectCard(true);}else{const view=currentGrid(),next=Math.max(0,Math.min(total-1,n+({ArrowLeft:-1,ArrowRight:1,ArrowUp:-view.columns,ArrowDown:view.columns}[ev.key])));focusOccurrence(next);}}};
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
        state.reportComposition={...copy(state.report.composition||{})};reportCase=id;reportVersion=state.report.version;
      }
      state.reportComposition=composition();
      const focus=sttReportFocus?.caseId===id&&sttReportFocus.caseToken===caseToken?sttReportFocus:null;
      if(focus){
        const result=await endpoint('report-events',{ids:focus.eventId,category:'ST',stt_group:'all',limit:1},id,controller?{signal:controller.signal}:{});
        if(!current())return;
        const event=result.items?.find(e=>e.event_id===focus.eventId&&e.category==='ST');
        if(!event)throw Error('未找到刚保存的ST-T复核记录，请核对记录后重试；未跳到其他事件');
        category='ST';sttGroup=event.stt_report_group||'all';reportMode='all';reportOffset=0;reportTimeRange=null;
        navigation={...navigation,focusEvent:event};
      }
      const data=await endpoint('report-events',reportViewParams(navigation),id,controller?{signal:controller.signal}:{});
      if(!current())return;
      if((data.analysis_basis!==undefined&&remote.current_analysis_basis&&data.analysis_basis!==remote.current_analysis_basis.digest)||(data.analysis_revision!==undefined&&data.analysis_revision!==remote.review_revision))throw Error('读取期间病例依据已变化，请重新加载');
      const freshLookup=new Map(data.items.map(e=>[e.event_id,e]));
      const referenceIds=[...new Set([...selected(),...(state.reportComposition.stt_report_use||[])].map(e=>e.event_id))];
      for(let i=0;i<referenceIds.length;i+=100){const result=await endpoint('report-events',{ids:referenceIds.slice(i,i+100).join('|'),limit:200},id,controller?{signal:controller.signal}:{});if(!current())return;if(!sameEvidence(result,data))throw Error('读取期间事件依据已变化，请重新加载');result.items.forEach(e=>freshLookup.set(e.event_id,e));}
      syncWaveEvidence(id,data);reportData=data;selectedLookup=freshLookup;projectRRSelections();state.reportEvidenceLoading=false;
      const context=reportViewContext(data);if(state.reportViewContext!==context){state.reportViews=new Map();state.reportBookmarks=new Map();}state.reportViewContext=context;state.reportDisplayedCategory=category;
      state.reportViews?.set(reportViewKey(reportViewParams(),data),data);host.inert=false;host.setAttribute?.('aria-busy','false');
      reportOffset=data.offset;
      if(navigation.focusEvent){
        active=data.items.find(e=>eventAliases(e).some(a=>a.event_id===navigation.focusEvent.event_id&&a.basis_version===navigation.focusEvent.basis_version));
        if(!active)throw Error('未找到目标事件，请重新选择；未跳转到其他事件');
      }else if(navigation.edge)active=navigation.edge==='last'?data.items.at(-1):data.items[0];
      // Reading a category or receipt never changes adoption or saved report text.
      renderReportShell();await renderReportBody();if(current()){rememberReportView();if(focus===sttReportFocus)sttReportFocus=null;}
    }catch(error){if(!current()||error.name==='AbortError')return;reportData=null;selectedLookup=new Map();state.reportViews=new Map();state.reportBookmarks=new Map();state.reportViewContext=null;state.reportEvidenceLoading=false;state.reportEvidenceError=true;host.inert=false;host.setAttribute?.('aria-busy','false');renderReportShell();host.innerHTML=`<p class="empty-state">加载失败：${esc(error.message)}。不能据此认定无事件。</p><button id="reportRetry" class="button secondary">重新加载</button><button id="reportRecoverList" class="button secondary">返回候选列表</button>`;qs('#reportRetry')?.addEventListener('click',()=>run(()=>refreshReport(navigation)));qs('#reportRecoverList')?.addEventListener('click',()=>{active=null;reportOffset=0;run(refreshReport)});throw error;}
  }
  function reportViewContext(data){return JSON.stringify([state.caseId,state.caseRequestId,data?.data_version,data?.analysis_basis,data?.analysis_revision]);}
  function reportViewParams(navigation={}){return {category:reportCategories.some(([k])=>k===category)?category:'all',mode:reportMode,offset:reportOffset,limit:50,sort:reportSort,...(category==='rr_interval'?{rr_source:rrSource}:{}),...(category==='ST'?{stt_group:sttGroup}:{}),candidate_spacing_s:reportSpacing,pause_band:pauseBand,pause_edges_ms:(composition().pause_edges_ms||[2500,3000,4000]).join(','),fast_slow_mode:reportSequence(),...(reportTimeRange?{time_start:reportTimeRange[0],time_end:reportTimeRange[1]}:{}),...(navigation.focusEvent?{locate_event:navigation.focusEvent.event_id,locate_basis:navigation.focusEvent.basis_version}:{})};}
  function reportViewKey(params,data=reportData){return JSON.stringify([reportViewContext(data),category,params]);}
  function rememberReportView(){
    if(!reportData||state.reportDisplayedCategory!==category||state.reportViewContext!==reportViewContext(reportData))return;
    const host=qs('#reportV2Content'),disclosures=Array.from(host?.querySelectorAll?.('details')||[]).filter(d=>d.open&&d.dataset?.reportSavedStNote===undefined).map(d=>d.className);
    state.reportBookmarks ||=new Map();state.reportBookmarks.set(category,{mode:reportMode,offset:reportOffset,sort:reportSort,spacing:reportSpacing,pauseBand,rrSource,sttGroup,range:reportTimeRange,active:typeof active==='undefined'?null:active?.event_id,scroll:qs('.v2-event-list')?.scrollTop||0,disclosures});
  }
  async function chooseReportCategory(next){
    const source=next==='pause'?'auto':next==='rr_candidate'?'manual':null;next=['pause','rr_candidate'].includes(next)?'rr_interval':next;
    if(next===category&&(!source||source===rrSource)&&!state.reportViewLoading&&!state.reportViewError)return;
    if(!await resolveWorkstationLeave())return;
    rememberReportView();reportReturn=null;category=next;
    const saved=state.reportBookmarks?.get(next);reportMode=saved?.mode||'all';reportOffset=saved?.offset||0;reportSort=saved?.sort||(next==='rr_interval'?'hr_asc':'hr_desc');reportSpacing=saved?.spacing||0;pauseBand=saved?.pauseBand||'all';rrSource=source||saved?.rrSource||'all';sttGroup=saved?.sttGroup||'all';reportTimeRange=saved?.range||null;
    return refreshReport({viewOnly:true,restoreView:saved});
  }
  async function changeReportView(change){
    if(!await resolveWorkstationLeave()){renderReportBody();return;}
    change();return refreshReport({viewOnly:true});
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
      if(reportCategories.some(([k])=>k===viewCategory)){
        const params=reportViewParams(navigation),key=reportViewKey(params,basis),cached=state.reportViews?.get(key);
        const data=await endpoint('report-events',{...params,analysis_basis:basis.analysis_basis,analysis_revision:basis.analysis_revision},id,{signal:controller.signal});
        if(!current())return;if(!sameEvidence(data,basis))throw Error('事件依据已变化，请载入最新版本后复核');
        // An identical validated response retains event object identity and cache bindings.
        reportData=cached&&JSON.stringify(cached)===JSON.stringify(data)?cached:data;
        state.reportViews?.set(key,reportData);reportData.items.forEach(e=>selectedLookup.set(e.event_id,e));reportOffset=reportData.offset;
        if(navigation.focusEvent){active=reportData.items.find(e=>eventAliases(e).some(a=>a.event_id===navigation.focusEvent.event_id&&a.basis_version===navigation.focusEvent.basis_version));if(!active)throw Error('未找到目标事件，请重新选择；未跳转到其他事件');}
        else if(navigation.edge)active=navigation.edge==='last'?reportData.items.at(-1):reportData.items[0];
        else if(navigation.restoreView)active=reportData.items.find(e=>e.event_id===navigation.restoreView.active)||null;
      }
      if(!current())return;state.reportDisplayedCategory=viewCategory;state.reportViewLoading=false;host.inert=false;host.setAttribute?.('aria-busy','false');renderReportShell();const rendered=renderReportBody();
      if(previousCategory===viewCategory&&focusId)qs('#'+focusId)?.focus({preventScroll:true});
      if(previousCategory===viewCategory||navigation.restoreView)Array.from(host.querySelectorAll?.('details')||[]).forEach(d=>{if(d.dataset?.reportSavedStNote===undefined&&viewState.disclosures?.includes(d.className))d.open=true;});
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
  function reportWaveSource(args){
    const wave=args.wave,id=args.case_id??wave?.case_id??state.caseId,token=args.case_token??wave?.case_token??state.caseRequestId,basis=ECGAnalysisConsistency.identity(wave),privacy=state.privacyRequestId??0;
    const current=()=>id===state.caseId&&token===state.caseRequestId;
    const guard=(printing=false)=>{if(!current())throw Error('病例或波形已变化，请重新选择');ECGAnalysisConsistency.assertSame(basis,state.caseData);if(printing&&(privacy!==(state.privacyRequestId??0)||state.privacySaving||state.privacyIdentityPending))throw Error('身份显示状态已变化，请重新打印');};
    guard();const time=args.start_s!==undefined&&args.end_s!==undefined?(Number(args.start_s)+Number(args.end_s))/2:Number(args.time);if(!Number.isFinite(time)||time<0||time>=state.caseData.technical.duration_seconds_raw)throw Error('图条位置不在当前记录中');
    const spec=ECGReportEngine.settingsForEvent({category:'other'},{leads:args.leads,duration_s:args.short?3:7,...(args.start_s!==undefined||args.end_s!==undefined?{range_start_s:args.start_s,range_end_s:args.end_s,duration_s:args.end_s-args.start_s}:{})});
    return {id,token,basis,guard,current,time,spec};
  }
  const waveStripInsertions=new Map();
  async function refreshReportAfterWaveInsert(source,scope){
    const {id,guard}=source;guard();if(state.currentPage!=='report')return;
    const viewCategory=category,previous=active?copy(active):null,oldScope=waveEvidenceScope,target=qs('#v2EventWave'),holder=target?.querySelector?.('.report-range-editor'),shown=target?._reportFullWave,displayState=holder?._rangeDisplayState?.(),rangeKey=holder?._rangeStripKey;
    const drafts=(globalThis.ECGReportRange?.pending?.()||[]).filter(d=>d.context===JSON.stringify([id,state.caseRequestId])&&d.basis===oldScope),visibleDraft=drafts.find(d=>(d.stripKey||d.event?.event_id)===rangeKey),choice=previous?.category==='AF'?target?._afCurrentStrip?.():null;
    const bounds=visibleDraft?{start:visibleDraft.applied.a,end:visibleDraft.applied.b}:holder?._rangeRead?.(),pick=previous?selectionForEvent(previous):null;
    const sourceSpec=previous&&bounds?{...ECGReportEngine.settings(choice?.settings||pick||newStripSettings(previous)),duration_s:bounds.end-bounds.start,range_start_s:bounds.start,range_end_s:bounds.end}:null;
    const scrolls=['.v2-event-list','.rw-selected-strips'].map(selector=>({selector,top:qs(selector)?.scrollTop||0}));
    // Candidate membership changes query data_version without editing the source
    // ECG. Adopt that owned version through the ordinary full guarded reload.
    await refreshReport(previous&&reportCategories.some(([key])=>key===viewCategory)?{focusEvent:previous}:{});guard();
    if(state.reportEvidenceError||!reportData)throw Error('图条已保存，报告依据刷新未完成，请重新读取');
    ECGAnalysisConsistency.assertSame(scope,reportData);
    if(drafts.length){
      const latest=await endpoint('evidence-candidates',scope,id);guard();ECGAnalysisConsistency.assertSame(scope,latest);if(latest.beat_revision!==scope.beat_revision)throw Error('心搏依据已变化，未恢复旧选区');
      const events=new Map([...selectedLookup,...reportData.items.map(e=>[e.event_id,e])]);
      const missing=[...new Set(drafts.map(d=>d.event?.event_id).filter(eventId=>eventId&&!events.has(eventId)))];
      for(let at=0;at<missing.length;at+=100){const fresh=await endpoint('report-events',{ids:missing.slice(at,at+100).join('|'),limit:200,...scope},id);guard();if(!sameEvidence(fresh,reportData))throw Error('事件依据已变化，未恢复旧选区');fresh.items.forEach(e=>events.set(e.event_id,e));}
      for(const draft of drafts){const event=events.get(draft.event?.event_id);if(event?.basis_version===draft.event?.basis_version){draft.basis=waveEvidenceScope;draft.event=copy(event);}}
    }
    if(state.currentPage!=='report'||category!==viewCategory)return;
    const fresh=previous&&reportData.items.find(e=>e.event_id===previous.event_id);
    if(fresh&&fresh.basis_version===previous.basis_version&&sourceSpec&&shown){
      const entry=await reportStrip(fresh,sourceSpec,id,true);guard();if(category!==viewCategory||active?.event_id!==fresh.event_id)return;
      const wave=await mountRange(qs('#v2EventWave'),fresh,entry,id,{start:shown.start_s,length:shown.duration_s,displayState,newStrip:choice?!choice.replaceKey:false,stripKey:choice?.replaceKey||pick&&stripKey(pick),draftKey:choice?.draftKey,role:choice?.role,stripDuration:sourceSpec.duration_s});
      if(wave&&category===viewCategory&&active?.event_id===fresh.event_id)beatEditor.bindWaveSurface(qs('#v2EventWave .report-range-stage'),{wave,readOnly:true,isCurrent:()=>source.current()&&category===viewCategory&&active?.event_id===fresh.event_id,onPreview:qs('#v2EventWave')._rwOpenPreview});
    }
    if(category===viewCategory){for(const s of scrolls){const node=qs(s.selector);if(node)node.scrollTop=s.top;}rememberReportView();}
    await flushReportAutosave();guard();
  }
  async function insertWaveStrip(args){
    const source=reportWaveSource(args),{id,basis,guard,time,spec}=source,originPage=state.currentPage;
    if(originPage!=='report'&&!await resolveWorkstationLeave())return null;guard();
    if(!clinicalWorkflow.writable())throw Error('当前服务只读，不能加入报告');
    await flushReportAutosave();guard();
    const ledger=await endpoint('evidence-candidates',basis,id);guard();ECGAnalysisConsistency.assertSame(basis,ledger);
    const scope={case_id:id,...basis,beat_revision:ledger.beat_revision},params={time_s:time,duration:spec.duration_s,leads:spec.leads.join(','),...scope,...('range_start_s' in spec?{range_start_s:spec.range_start_s,range_end_s:spec.range_end_s}:{})};
    const preview=await endpoint('report-strip-preview',params,id);guard();ECGAnalysisConsistency.assertSame(basis,preview);
    const start=Math.round(preview.strip.start_s*200),end=Math.round(preview.strip.end_s*200),key=[id,basis.analysis_basis,basis.analysis_revision,scope.beat_revision,start,end].join('|');
    if(waveStripInsertions.has(key))return waveStripInsertions.get(key);
    const sameCandidate=c=>c.kind==='strip'&&c.status==='active'&&c.scope?.case_id===id&&c.scope.analysis_basis===basis.analysis_basis&&c.scope.beat_revision===scope.beat_revision&&Math.round(c.payload?.start_s*200)===start&&Math.round(c.payload?.end_s*200)===end;
    const work=(async()=>{
      let candidate=ledger.items.find(sameCandidate);
      if(!candidate){try{const result=await api(`/api/cases/${id}/evidence-candidates`,{method:'POST',body:JSON.stringify({...scope,kind:'strip',time_s:time,settings:spec,caption:args.caption||'人工图条'})});guard();candidate=result.item;}
        catch(error){guard();const receipt=await endpoint('evidence-candidates',scope,id);guard();ECGAnalysisConsistency.assertSame(scope,receipt);candidate=receipt.items.find(sameCandidate);if(!candidate)throw error;}}
      guard();if(!candidate||!sameCandidate(candidate))throw Error('候选回执与所选图条不一致，请重新读取');
      const eventId='local-pick:'+candidate.id,data=await endpoint('report-events',{ids:eventId,limit:1,...scope},id);guard();ECGAnalysisConsistency.assertSame(scope,data);
      const event=data.items.find(e=>e.event_id===eventId&&e.category==='other');if(!event)throw Error('已保存候选，但来源已变化，请在报告中重新读取');
      const existing=selected().find(s=>s.event_id===eventId);
      if(existing){if(existing.basis_version!==event.basis_version)throw Error('已有本图依据已变化，请先核对原图条');await refreshReportAfterWaveInsert(source,scope);guard();toast('此范围已入报，保留原图注、导联和设置');return selected().find(s=>s.event_id===eventId)||existing;}
      const pick={event_id:event.event_id,basis_version:event.basis_version,caption:event.label,...newStripSettings(event,event.retained_settings)};
      selectedLookup.set(event.event_id,event);state.reportComposition.selected_events.push(pick);delete state.reportComposition.category_reviews.other;syncText();dirty();renderReportShell();syncReportMembership();
      await flushReportAutosave();guard();
      if(originPage!=='report'){category='other';reportMode='all';reportOffset=0;reportTimeRange=null;goPage('report');if(state.currentPage==='report')await refreshReport({focusEvent:event});}else await refreshReportAfterWaveInsert(source,scope);
      toast('已加入报告草稿','success');return pick;
    })();waveStripInsertions.set(key,work);try{return await work;}finally{if(waveStripInsertions.get(key)===work)waveStripInsertions.delete(key);}
  }
  async function printWaveStrip(args){
    const source=reportWaveSource(args),{id,basis,time,spec}=source,page=state.currentPage,guard=()=>{source.guard(true);if(state.currentPage!==page)throw Error('页面已变化，请重新打印图条');};guard();
    const ledger=await endpoint('evidence-candidates',basis,id);guard();ECGAnalysisConsistency.assertSame(basis,ledger);
    const scope={case_id:id,...basis,beat_revision:ledger.beat_revision},entry=await endpoint('report-strip-preview',{time_s:time,duration:spec.duration_s,leads:spec.leads.join(','),...scope,...('range_start_s' in spec?{range_start_s:spec.range_start_s,range_end_s:spec.range_end_s}:{})},id);guard();ECGAnalysisConsistency.assertSame(scope,entry);
    const record=await api(withPhi(ECGAnalysisConsistency.url(id,'',{},basis)));guard();ECGAnalysisConsistency.assertSame(basis,record);
    ECGAnalysisConsistency.assertSame(scope,await endpoint('analysis-basis',scope,id));guard();
    const original=paperModel(null),model={...original,case:record,report:{...original.report,status:'draft',reviewed_by:'',preview_unsaved:false,conclusion:'',composition:{...original.report.composition,page_selection_version:1,included_pages:['event_strips']}}};
    await printHtml(ECGReportPaper.stripPages(model,[{...entry,caption:args.caption||'人工图条'}]),'图条打印',guard);
  }
  async function includeRRCandidate(candidate,isCurrent=()=>true){
    const id=state.caseId,caseToken=state.caseRequestId,current=()=>id===state.caseId&&caseToken===state.caseRequestId&&isCurrent();
    if(!current()||candidate?.kind!=='rr'||candidate.case_id!==id)throw Error('候选或病例已变化，未加入报告');
    await flushReportAutosave();if(!current())throw Error('病例或选区已变化，未加入报告');
    await refreshReport();if(!current())throw Error('病例或选区已变化，未加入报告');
    if(!reportData||state.reportEvidenceError||state.reportStale)throw Error('报告依据尚未就绪，未加入报告');
    const eventId=`local-pick:${candidate.id}`,data=await endpoint('report-events',{ids:eventId,limit:1},id);
    if(!current()||!sameEvidence(data,reportData))throw Error('候选依据已变化，未加入报告');
    const event=data.items.find(e=>e.event_id===eventId&&e.category==='rr_candidate');
    if(!event)throw Error('当前候选已撤销或来源失效，未加入报告');
    const existing=selected().find(s=>s.event_id===eventId);
    if(existing){if(existing.basis_version!==event.basis_version)throw Error('已有图条来源已变化，请先核对原图条');return;}
    await selectEvent(event,true,event.retained_settings||composition().strip_defaults);
    await flushReportAutosave();
    if(!current())throw Error('保存期间病例或选区已变化，请返回原病例核对');
  }
  async function receiveCandidateState(result){
    if(!result.report||state.reportDirty||state.reportSaving)throw Error('报告还有未保存修改，请先保存后重新读取候选');
    state.report=copy(result.report);state.reportComposition=copy(result.report.composition);state.reportStale=false;reportVersion=null;
    if(state.caseData)state.caseData.report_workflow=copy(result.report);
    if(result.review)clinicalWorkflow.receive(result.review);
    if(state.currentPage==='report')await refreshReport();
  }
  let reportEvidenceOpening=false;
  async function reviewReportEvidence(index='active',target=null){
    if(reportEvidenceOpening||!reportData||state.reportStale||state.reportEvidenceLoading)throw Error('请先载入当前报告依据');
    if(!clinicalWorkflow.writable())throw Error('当前服务只读，不能保存核对');
    ECGReportRange.assertApplied?.();
    const id=state.caseId,caseToken=state.caseRequestId,own=()=>id===state.caseId&&caseToken===state.caseRequestId&&state.currentPage==='report';
    // The longest numeric value owns its automatic range, independently of
    // whichever printed strip is first or currently active.
    const retained=target?null:index==='active'?selectionForEvent(active):selected()[Number(index)];
    const event=target?null:retained?selectedLookup.get(retained.event_id):index==='active'?active:null;
    if(!target&&(!ECGReportEvidenceUI.eligible(event)||retained&&retained.basis_version!==event.basis_version))throw Error('本条依据已变化，请重新选择');
    const entry=retained?copy(retained):event?{...ECGReportEngine.settings(event.retained_settings||composition().strip_defaults),caption:event.label}:{};
    reportEvidenceOpening=true;
    try{
      await flushReportAutosave();if(!own())return;
      if(state.caseData?.clinical_identity?.analysis_revision!==reportData.analysis_revision){await refreshHrvCase(id,caseToken,own);if(!own())return;}
      const signature=ECGReportConsistency.content(qs('#conclusionEditor').value,composition()),version=state.report.version,identity={...reportData};
      const current=()=>own()&&!state.reportStale&&state.report.version===version&&signature===ECGReportConsistency.content(qs('#conclusionEditor').value,composition());
      await ECGReportEvidenceUI.open({api,id,identity,event,entry,target,isCurrent:current,include:!target&&!retained,
        onCorrect:preview=>{if(current())ECGReportEvidenceUI.correction({host:qs('#reportV2Content'),preview,isCurrent:()=>own()&&sameEvidence(reportData,identity)});},
        onSaved:async result=>{
          if(!current())throw Error('报告已变化，请重新载入核对结果');
          state.report=copy(result.report);state.reportComposition=copy(result.report.composition);state.reportDirty=false;state.reportStale=false;reportVersion=null;
          clinicalWorkflow.receive(result.review);await refreshHrvCase(id,caseToken,own);if(!own())return;
          await refreshReport();if(!own())return;
          if(!target&&!retained){const fresh=selectedLookup.get(event.event_id)||reportData.items.find(e=>e.event_id===event.event_id);if(!fresh)throw Error('核对已保存，候选列表已变化，请重新选择入报');await selectEvent(fresh,true,entry);await flushReportAutosave();}
          if(own())toast(target?'最长 RR 数值已核对；未增加打印图条':'本条证据已核对'+(!retained?'并加入报告草稿':''));
        }});
    }finally{reportEvidenceOpening=false;}
  }
  function reviewEvidenceButtons(){
    if(!ECGReportEvidenceUI.eligible(active))return '';
    const included=!!selectionForEvent(active);
    return `<button type="button" data-review-rr ${!reportWaveReady?'disabled':''}>${included?'核对本条':'确认并入报'}</button>`;
  }
  let rhythmReturn=null,rhythmOpening=false;
  async function showAFCandidates(episodeId=null){
    if(!await resolveWorkstationLeave())return;
    const id=state.caseId,token=state.caseRequestId;
    category='AF';reportMode='all';reportOffset=0;reportTimeRange=null;reportReturn=null;goPage('report');
    if(state.currentPage!=='report')return;
    await refreshReport();if(id!==state.caseId||token!==state.caseRequestId||!episodeId)return;
    const data=await endpoint('report-events',{category:'AF',ids:'annotation:af:'+episodeId,limit:1},id);
    if(id!==state.caseId||token!==state.caseRequestId||state.currentPage!=='report')return;
    const e=data.items.find(e=>e.rhythm_episode_id===episodeId);
    if(e)await refreshReport({viewOnly:true,focusEvent:e});
  }
  async function confirmReportRhythm(e,selection=null){
    if(rhythmOpening||!e?.rhythm_episode_id||e.category!=='AF')return;
    if(selection)activeStripKey=stripKey(selection);
    if(!reportWaveReady||active?.event_id!==e.event_id||selection&&qs('#v2EventWave')?.dataset.afStripKey!==stripKey(selection)){await locate(e);if(!reportWaveReady)return;}
    const choice=qs('#v2EventWave')?._afCurrentStrip?.(),currentChoice=choice?.event_id===e.event_id&&choice.basis_version===e.basis_version?choice:null;
    const pending=ECGReportRange.pending?.().find(d=>(currentChoice?(d.stripKey||d.event?.event_id)===currentChoice.draftKey:d.event?.event_id===e.event_id)&&d.basis===waveEvidenceScope)||null;
    if(state.reportStale||state.reportEvidenceLoading||state.reportViewLoading||!clinicalWorkflow.writable())throw Error('请先载入当前片段波形');
    const id=state.caseId,token=state.caseRequestId,identity=ECGAnalysisConsistency.identity(reportData),originalScope=waveEvidenceScope;
    const own=()=>id===state.caseId&&token===state.caseRequestId&&state.currentPage==='report';
    rhythmOpening=true;
    try{
      await flushReportAutosave();if(!own())return;
      const siblings=copy(selectionsForEvent(e)),retained=copy(selection||currentChoice?.replaceKey&&siblings.find(s=>stripKey(s)===currentChoice.replaceKey)||(!currentChoice?selectionForEvent(e):null)||null);
      const chosenSpec={...(currentChoice?.settings||newStripSettings(e,retained)),...(pending?{range_start_s:pending.a,range_end_s:pending.b,duration_s:pending.b-pending.a}:{})},chosenReplaceKey=retained&&stripKey(retained);
      const strip=await reportStrip(e,chosenSpec,id,true);if(!own())return;
      const base=await endpoint('rhythm-review',identity,id);if(!own())return;
      const episode=base.document.episodes.find(x=>x.id===e.rhythm_episode_id);
      if(!episode||episode.status==='excluded'||Math.round(episode.start_s*200)!==e.start_sample||Math.abs(episode.end_s-e.end_s)>.001)throw Error('片段已变化，请重新选择');
      const label=episode.kind==='AFL'?'房扑':'房颤',document=copy(base.document);
      document.episodes.find(x=>x.id===episode.id).status='confirmed';
      const payload={...identity,case_id:id,beat_revision:base.beat_revision,revision:base.revision,request_id:crypto.randomUUID(),operation:'save',document,confirmed:true};
      let committed=episode.status==='confirmed',submitted=false;
      async function receipt(reason=null){
        const {analysis_revision,...source}=identity;
        const latest=await endpoint('rhythm-review',source,id);
        if(latest.last_operation?.request_id===payload.request_id&&latest.last_operation.operation==='save'&&latest.last_operation.revision===latest.revision){committed=true;return;}
        if(latest.revision===base.revision){submitted=false;throw reason||Error('确认尚未写入，可重试');}
        throw Error('片段已被其他操作修改，请取消后重新读取');
      }
      await ECGUnsavedNavigation.resolve({title:'确认整段'+label+'并入报',detail:`整段候选：${ECGRhythmRangeEditor.boundaryClock(episode.start_s,state.caseData.metadata.start_time)} — ${ECGRhythmRangeEditor.boundaryClock(episode.end_s,state.caseData.metadata.start_time)} · ${(episode.end_s-episode.start_s).toFixed(3)} 秒\n本次图条：${ECGRhythmRangeEditor.boundaryClock(strip.strip.start_s,state.caseData.metadata.start_time)} — ${ECGRhythmRangeEditor.boundaryClock(strip.strip.end_s,state.caseData.metadata.start_time)} · ${strip.strip.actual_duration_s.toFixed(3)} 秒 · ${strip.strip.visible_beat_count} 搏`,stayLabel:'取消',saveLabel:'确认整段'+label+'并入报图条',isCurrent:own,
        save:async()=>{
          if(!committed){
            if(submitted)await receipt();
            else {submitted=true;try{await api(`/api/cases/${id}/rhythm-review`,{method:'PUT',body:JSON.stringify(payload)});committed=true;}catch(error){await receipt(error);}}
          }
          if(!own())return;
          // A verified receipt can recover a committed write whose HTTP reply
          // was lost. Retire the old overview identity in that path as well.
          globalThis.ECGReadRequests?.clear();overviewWorkbench.invalidateAfterWrite(id,token);
          await clinicalWorkflow.refresh(id);if(!own())return;
          await refreshHrvCase(id,token,own);if(!own())return;
          await refreshReport();if(!own())return;
          if(siblings.some(origin=>{const row=selected().find(s=>stripKey(s)===stripKey(origin));return !row||JSON.stringify(row)!==JSON.stringify(origin);}))throw Error('整段确认已保存，但报告图条已被其他操作修改；未覆盖新设置，请重新读取后核对本图');
          const data=await endpoint('report-events',{ids:['annotation:af:'+episode.id,e.event_id].join('|'),limit:2},id);
          if(!own())return;
          const fresh=data.items.find(x=>x.rhythm_episode_id===episode.id&&x.rhythm_status==='confirmed');
          if(!fresh)throw Error('确认已保存，请重试读取入报图条');
          ECGAnalysisConsistency.assertSame(reportData,data);
          if(fresh.start_sample!==e.start_sample||Math.abs(fresh.end_s-e.end_s)>.001||fresh.subtype!==e.subtype||fresh.label!==e.label||(fresh.note||'')!==(e.note||'')||(fresh.lead||'')!==(e.lead||''))throw Error('整段确认后片段又发生变化，未套用旧图条，请重新核对');
          // Only siblings valid immediately before this owned confirmation can
          // follow its new status basis. Earlier stale picks are never revived.
          for(const origin of siblings){const index=selected().findIndex(s=>stripKey(s)===stripKey(origin)&&s.event_id===origin.event_id&&s.basis_version===origin.basis_version);if(index<0)continue;await reportStrip(fresh,origin,id,true);if(!own())return;state.reportComposition.selected_events[index]={...origin,event_id:fresh.event_id,basis_version:fresh.basis_version};}
          selectedLookup.set(fresh.event_id,fresh);delete state.reportComposition.category_reviews.AF;syncText();dirty();
          const spec={...chosenSpec,caption:retained?.caption||fresh.label,...(retained?ECGReportStripEditor.curation(retained):{})};
          await addAFStrip(fresh,spec,{replaceKey:chosenReplaceKey,role:currentChoice?.role||retained?.representative_role||'custom',render:false});
          for(const draft of ECGReportRange.pending?.()||[]){if(draft===pending||draft.basis!==originalScope||draft.event?.event_id!==e.event_id||draft.event.basis_version!==e.basis_version)continue;try{await reportStrip(fresh,{...newStripSettings(fresh,selected().find(s=>stripKey(s)===draft.stripKey)),duration_s:draft.b-draft.a,range_start_s:draft.a,range_end_s:draft.b},id,true);if(!own())return;draft.basis=waveEvidenceScope;draft.event=copy(fresh);}catch(_){/* Invalid drafts retain the original stale-basis protection. */}}
          await flushReportAutosave();if(!own())return;ECGReportRange.forget?.(currentChoice?.draftKey||pending?.stripKey||e.event_id);
          await refreshReport({viewOnly:true,focusEvent:fresh});
          toast(label+'已确认并加入报告草稿','success');
        }});
    }finally{rhythmOpening=false;syncReportMembership();renderReportShell();}
  }

  function hasRhythmReturn(){return !!rhythmReturn&&rhythmReturn.id===state.caseId&&rhythmReturn.caseToken===state.caseRequestId;}
  function rhythmReviewButton(e,index){return e?.category==='AF'&&e.rhythm_episode_id?`<button type="button" data-review-rhythm="${index}">修改起终点</button>${e.rhythm_status!=='confirmed'?`<button type="button" data-confirm-rhythm="${index}" ${!reportWaveReady?'disabled':''}>确认整段并入报</button>`:''}`:'';}
  async function openRhythmReview(index){
    if(rhythmOpening||state.reportSaving)throw Error('正在保存或定位，请等待完成');
    ECGReportRange.assertApplied?.();
    const selection=index==='active'?selectionForEvent(active):selected()[Number(index)],e=index==='active'?active:selection?selectedLookup.get(selection.event_id):null;
    if(!e?.rhythm_episode_id||e.category!=='AF')throw Error('找不到对应片段，请重新读取并选择；未跳到其他片段');
    if(state.reportStale||!reportData||state.reportEvidenceLoading||state.reportEvidenceError)throw Error('请先完整载入当前报告依据');
    const origin={id:state.caseId,caseToken:state.caseRequestId,category,event_id:e.event_id,stripKey:stripKey(selection),episode_id:e.rhythm_episode_id,selection:!!selection};
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
    const origin=rhythmReturn,basis=ECGAnalysisConsistency.identity(reportData),token=reportToken;activeStripKey=origin.stripKey||origin.event_id;
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
    return hasRhythmReturn()&&rhythmReturn.selection&&e?.category==='AF'&&e.rhythm_episode_id===rhythmReturn.episode_id?selected().find(s=>stripKey(s)===(rhythmReturn.stripKey||rhythmReturn.event_id)&&(s.event_id!==e.event_id||s.basis_version!==e.basis_version)):null;
  }
  function returnedRhythmSettings(e){
    const old=returnedRhythmSelection(e);
    return old?ECGReportEngine.settings({leads:old.leads,duration_s:7}):null;
  }
  async function replaceReturnedRhythm(){
    ECGReportRange.assertApplied?.();
    const e=active,old=returnedRhythmSelection(e);
    if(!canReplaceReturnedRhythm(e))throw Error('请等待保存和当前片段波形读取完成后再替换');
    replaceRhythmSelection(e,returnedRhythmSettings(e));category=rhythmReturn.category;
    renderReportShell();await renderReportBody();
    toast('已替换原图条，保留导联与图注；区间恢复自动 7 秒／至少 5 搏，请核对并保存草稿');
  }
  function canReplaceReturnedRhythm(e=active){
    return !!(reportWaveReady&&returnedRhythmSelection(e)&&reportData?.items.includes(e)&&!state.reportStale&&!state.reportSaving);
  }
  function replaceRhythmSelection(e,spec){
    const old=returnedRhythmSelection(e);
    if(!old)throw Error('原选图已变化，请重新核对');
    const index=selected().indexOf(old);
    const next={...old,...spec,event_id:e.event_id,basis_version:e.basis_version,caption:old.caption};
    if(!Object.hasOwn(spec||{},'range_start_s')&&!Object.hasOwn(spec||{},'range_end_s')){delete next.range_start_s;delete next.range_end_s;}
    state.reportComposition.selected_events[index]=next;
    delete state.reportComposition.category_reviews.AF;
    state.reportComposition.diagnosis_blocks.forEach(b=>{if(b.key.startsWith('AF:')){b.acknowledged=false;if(b.manual)b.needs_review=true;}});
    rhythmReturn.event_id=e.event_id;syncText();dirty();
  }
  async function backToReportEvent(index){
    if(globalThis.ECGReportRange?.pending?.().length&&!await ECGReportRange.resolveLeave())return;
    const selection=selected()[index],e=selection&&selectedLookup.get(selection.event_id);
    if(!e||e.basis_version!==selection.basis_version)throw Error('图条依据已失效，请重新选择');
    activeStripKey=stripKey(selection);reportReturn={id:state.caseId,category,event_id:e.event_id,stripKey:activeStripKey};
    category=reportCategoryOf(e);reportOffset=0;reportMode=category==='rr_interval'?'all':e.subtype;reportTimeRange=null;pauseBand='all';
    await refreshReport({viewOnly:true,focusEvent:e});
    if(reportReturn?.id===state.caseId)focusEventNavigation();
  }
  function focusEventNavigation(){const nav=qs('#v2EventNavigation');nav?.scrollIntoView({block:'start'});nav?.focus({preventScroll:true});}
  async function returnToReport(){
    if(globalThis.ECGReportRange?.pending?.().length&&!await ECGReportRange.resolveLeave())return;
    const destination=reportReturn;if(!destination||destination.id!==state.caseId)return;
    category=destination.category;reportOffset=0;reportMode='all';reportTimeRange=null;reportReturn=null;
    await refreshReport({viewOnly:true});
    if(destination.id!==state.caseId||category!==destination.category)return;
    const index=selected().findIndex(s=>stripKey(s)===(destination.stripKey||destination.event_id));
    const button=qs(`[data-back-event="${index}"]`);button?.scrollIntoView({block:'center'});button?.focus({preventScroll:true});
  }
  function renderEventNavigation(ready=false){
    const host=qs('#v2EventNavigation');if(!host||!reportData)return;
    reportWaveReady=ready;
    const local=reportData.items.findIndex(e=>sameReportEvent(e,active?.event_id)),position=local<0?-1:reportOffset+local;
    if(category==='ST'){
      const e=active,eligible=sttEligibility(e),usage=sttUse(e);
      host.innerHTML=`<div class="v2-review-position" role="status">${position<0?'无匹配记录':`第 ${position+1} / ${reportData.total} 条 · ${esc(sttOutcomes[e.stt_result_code]||e.label)} · ${formatElapsed(e.time_s)}–${formatElapsed(e.end_s??e.time_s)}`}</div><div class="v2-review-actions"><button type="button" data-review-step="-1" aria-label="上一条" ${position<=0?'disabled':''}>‹</button><button type="button" data-review-step="1" aria-label="下一条" ${position<0||position+1>=reportData.total?'disabled':''}>›</button>${e?'<button type="button" data-stt-edit>修改复核</button>':''}${e?['table','text','strip'].map(key=>`<label><input type="checkbox" data-stt-active-use="${key}" ${usage?.[key]?'checked':''} ${!usage?.[key]&&(!sttReviewed(e)||!eligible[key]||key==='strip'&&!ready)?'disabled':''}>${{table:'事件表',text:'报告文字',strip:'代表图条'}[key]}</label>`).join(''):''}</div>`;
      host.querySelectorAll('[data-review-step]').forEach(b=>b.onclick=()=>run(()=>stepReportEvent(Number(b.dataset.reviewStep))));
      host.querySelector('[data-stt-edit]')?.addEventListener('click',()=>run(()=>showSTRecord(e)));
      host.querySelectorAll('[data-stt-active-use]').forEach(input=>input.onchange=()=>run(async()=>{try{await setSTTUse(e,input.dataset.sttActiveUse,input.checked);}finally{syncSTTControls();}}));
      return;
    }
    const included=!!selectionForEvent(active);
    host.innerHTML=`<div class="v2-review-position" role="status">${position<0?'无可核查事件':`第 ${position+1} / ${reportData.total} 条 · ${formatElapsed(active.time_s)}`}</div><div class="v2-review-actions"><button type="button" data-review-step="-1" aria-label="上一条" ${position<=0?'disabled':''}>‹</button><button type="button" data-review-step="1" aria-label="下一条" ${position<0||position+1>=reportData.total?'disabled':''}>›</button><button type="button" data-review-include aria-pressed="${included}" ${!ready?'disabled':''}>${included?(active?.category==='AF'?'移出本段 '+selectionsForEvent(active,false).length+' 图':'移出报告草稿'):active?.category==='AF'&&active.rhythm_status!=='confirmed'?'加入待确认草稿':'加入报告草稿'}</button><button type="button" data-review-undo ${selectionUndoCurrent()?'':'disabled'}>${reportSelectionUndo?.before?'撤销移出':'撤销入报'}</button>${reportReturn?.id===state.caseId?'<button type="button" data-review-return>返回入报图条</button>':''}</div><small>${active?.category==='AF'?'点击列表查看；勾选加入草稿。':'入报后自动下一条；取消不跳转。'}</small>`;
    host.querySelectorAll('[data-review-step]').forEach(b=>b.onclick=()=>run(()=>stepReportEvent(Number(b.dataset.reviewStep))));
    host.querySelectorAll('[data-review-step]').forEach(b=>{b.title=b.disabled?(position<0?'当前没有可核查的事件':Number(b.dataset.reviewStep)<0?'已是当前筛选的第一条':'已是当前筛选的最后一条'):'按当前筛选和排序查看'+(Number(b.dataset.reviewStep)<0?'上一条':'下一条')+'事件';});
    host.querySelector('[data-review-include]').title=!ready?'请等待当前事件波形读取完成，或在失败后重试':included?'仅移出报告草稿，保留事件和诊断复核状态':'加入报告草稿；最终审核前仍需独立诊断确认';
    host.querySelector('[data-review-include]').onclick=()=>run(async()=>{if(reportWaveReady&&active&&reportData.items.some(e=>e===active)){await selectEvent(active,!included);focusEventNavigation();}});
    host.querySelector('[data-review-undo]').title='撤销本窗口上一次入报或移出，恢复原图注、导联和已应用区间；不恢复诊断或报告审核确认';host.querySelector('[data-review-undo]').onclick=()=>run(undoReportSelection);
    host.querySelector('[data-review-return]')?.addEventListener('click',()=>run(returnToReport));
    host.querySelector('.v2-review-actions').insertAdjacentHTML('beforeend',rhythmReviewButton(active,'active'));
    host.querySelector('.v2-review-actions').insertAdjacentHTML('beforeend',reviewEvidenceButtons());
    host.querySelector('[data-review-rr]')?.addEventListener('click',()=>run(()=>reviewReportEvidence('active')));
    if(returnedRhythmSelection(active)){
      host.querySelector('[data-review-include]').disabled=true;
      host.querySelector('[data-review-include]').title='此事件对应旧入报图条，请核对后使用“用当前片段替换原图条”';
      host.insertAdjacentHTML('beforeend','<p>替换时保留原导联和图注；原人工区间将重置为自动 7 秒／至少 5 搏。当前预览使用这一新区间。也可拖动游标后“应用区间”，以人工区间替换原图条，不重复添加。</p><div class="v2-review-actions"><button type="button" data-rhythm-replace '+(!canReplaceReturnedRhythm()?'disabled':'')+'>用当前片段替换原图条</button></div>');
    }
  }
  async function stepReportEvent(delta){
    if(globalThis.ECGReportRange?.pending?.().length&&!await ECGReportRange.resolveLeave())return;
    if(!reportData||![-1,1].includes(delta))return;
    const local=reportData.items.findIndex(e=>sameReportEvent(e,active?.event_id)),position=reportOffset+local+delta;
    if(local<0||position<0||position>=reportData.total)return;
    if(local+delta>=0&&local+delta<reportData.items.length)await locate(reportData.items[local+delta]);
    else{reportOffset=Math.floor(position/50)*50;await refreshReport({viewOnly:true,edge:delta<0?'last':'first'});}
    focusEventNavigation();
  }
  function syncText(){
    const c=state.reportComposition,keys=new Map();selected().forEach(s=>{const e=selectedLookup.get(s.event_id);if(e&&e.basis_version===s.basis_version&&(e.category!=='ST'||!Array.isArray(c.stt_report_use)))keys.set(e.category+':'+e.subtype,e.label)});
    if(Array.isArray(c.stt_report_use))sttUses(c).filter(x=>x.text).forEach(s=>{const e=selectedLookup.get(s.event_id);if(e&&e.basis_version===s.basis_version&&sttReviewed(e))keys.set('ST:review:'+e.event_id,sttNarrative(e));});
    const blocks=[];for(const b of c.diagnosis_blocks||[]){if(keys.has(b.key)){blocks.push(b);keys.delete(b.key);}else if(b.manual)blocks.push({...b,needs_review:!b.acknowledged});}
    keys.forEach((text,key)=>blocks.push({key,text,manual:false,needs_review:false,acknowledged:false}));c.diagnosis_blocks=blocks;
  }
  function selectionUndoCurrent(){const undo=reportSelectionUndo;if(!undo||undo.id!==state.caseId||undo.caseToken!==state.caseRequestId||undo.scope!==waveEvidenceScope||state.reportStale||state.reportSaving||state.reportEvidenceLoading||state.reportViewLoading||state.reportViewError)return false;const current=undo.siblingsAfter?selectionsForEvent(undo.event,false):selected().find(s=>s.event_id===undo.event.event_id)||null;return JSON.stringify(current)===JSON.stringify(undo.siblingsAfter||undo.after);}
  async function undoReportSelection(){
    if(!selectionUndoCurrent())return;const undo=reportSelectionUndo;reportSelectionUndo=null;const c=state.reportComposition;
    c.selected_events=c.selected_events.filter(s=>s.event_id!==undo.event.event_id);if(undo.siblingsBefore)c.selected_events.splice(Math.min(undo.index,c.selected_events.length),0,...copy(undo.siblingsBefore));else if(undo.before)c.selected_events.splice(Math.min(undo.index,c.selected_events.length),0,copy(undo.before));
    selectedLookup.set(undo.event.event_id,undo.event);delete c.category_reviews[undo.event.category];c.diagnosis_blocks.forEach(block=>{if(block.key===undo.event.category+':'+undo.event.subtype){block.acknowledged=false;if(block.manual)block.needs_review=true;}});syncText();dirty();renderReportShell();
    await renderReportBody();
  }
  function syncReportMembership(){document.querySelectorAll('[data-include]').forEach(control=>{const e=reportData?.items[Number(control.dataset.include)];control.checked=!!selectionForEvent(e);});}
  async function addAFStrip(e,settings,{replaceKey=null,role='custom',render=true}={}){
    const id=state.caseId,token=state.caseRequestId,scope=waveEvidenceScope,current=()=>id===state.caseId&&token===state.caseRequestId&&scope===waveEvidenceScope&&state.currentPage==='report';
    const spec=newStripSettings(e,settings),entry=await reportStrip(e,spec,id,true);if(!current())throw Error('病例或报告依据已变化，未加入图条');
    const sameRange=s=>Math.round(s.start_s*200)===Math.round(entry.strip.start_s*200)&&Math.round(s.end_s*200)===Math.round(entry.strip.end_s*200);
    for(const pick of selectionsForEvent(e)){
      if(replaceKey&&stripKey(pick)===replaceKey)continue;
      const resolved='range_start_s' in pick?{start_s:pick.range_start_s,end_s:pick.range_end_s}:(await reportStrip(e,pick,id)).strip;if(!current())throw Error('报告依据已变化');
      if(sameRange(resolved)){activeStripKey=stripKey(pick);syncReportMembership();toast('本段此范围已入报，保留原图注、导联和设置');if(render)await locate(e);return pick;}
    }
    const index=replaceKey?selected().findIndex(s=>stripKey(s)===replaceKey&&s.event_id===e.event_id&&s.basis_version===e.basis_version):-1;
    if(replaceKey&&index<0)throw Error('本张图条已变化，请重新打开');
    const old=index>=0?selected()[index]:null,next={...(old||{}),...settings,...spec,...ECGReportEngine.stripIdentity(old||settings),strip_id:old?.strip_id||settings?.strip_id||newStripId(),representative_role:settings?.representative_role||role,event_id:e.event_id,basis_version:e.basis_version,caption:old?.caption||settings?.caption||(e.label+' · '+({start:'段首',middle:'段中',end:'段末',custom:'自选'}[role]||'自选')),range_start_s:entry.strip.start_s,range_end_s:entry.strip.end_s,duration_s:entry.strip.actual_duration_s};
    if(index>=0)state.reportComposition.selected_events[index]=next;else state.reportComposition.selected_events.push(next);
    state.reportComposition.schema_version=3;activeStripKey=stripKey(next);selectedLookup.set(e.event_id,e);delete state.reportComposition.category_reviews.AF;syncText();dirty();renderReportShell();if(render)await renderReportBody();return next;
  }
  function selectEvent(e,checked,settings=null){
    if(e?.category==='ST')return setSTTUse(e,'strip',checked,settings);
    if(settings===null&&globalThis.ECGReportRange?.pending?.().length)return ECGReportRange.resolveLeave().then(ok=>{if(ok)return selectEvent(e,checked,settings);syncReportMembership();});
    if(checked&&returnedRhythmSelection(e))throw Error('该片段有待替换的旧图条，请先查看当前波形并使用“用当前片段替换原图条”，保留原导联与图注');
    if(e.category==='AF'&&checked&&settings)return addAFStrip(e,settings);
    if(e.category==='AF'&&checked&&selectionForEvent(e)){syncReportMembership();return active?.event_id===e.event_id?Promise.resolve():locate(e);}
    const existingRR=['pause','rr_candidate'].includes(e.category)?selectionForEvent(e,false):null;
    if(checked&&existingRR){if(!selectionForEvent(e))throw Error('已有 RR 图条依据已变化，请先核对或移除旧图条');syncReportMembership();toast('此 RR 已入报，保留原图注、导联和区间');if(active?.event_id!==e.event_id)return locate(e);return Promise.resolve();}
    const undoIndex=selected().findIndex(s=>eventAliases(e).some(a=>a.event_id===s.event_id)),undoBefore=undoIndex<0?null:copy(selected()[undoIndex]),undoSiblings=e.category==='AF'?copy(selectionsForEvent(e,false)):null;
    const wasIncluded=!!selectionForEvent(e),advanceCase=state.caseId,advanceCaseToken=state.caseRequestId,advanceData=reportData,advanceCategory=category,advanceScope=waveEvidenceScope;
    const c=state.reportComposition;selectedLookup.set(e.event_id,e);
    c.selected_events=c.selected_events.filter(s=>!eventAliases(e).some(a=>a.event_id===s.event_id&&(e.category==='AF'||a.basis_version===s.basis_version)));
    if(checked)c.selected_events.push({event_id:e.event_id,basis_version:e.basis_version,caption:e.label,...newStripSettings(e,settings),...(e.category==='AF'?{strip_id:newStripId(),representative_role:'start'}:{})});
    if(e.category==='AF'&&checked){c.schema_version=3;activeStripKey=stripKey(c.selected_events.at(-1));}
    if(settings===null&&reportCategories.some(([key])=>key===category))reportSelectionUndo={id:advanceCase,caseToken:advanceCaseToken,scope:advanceScope,event:copy(e),before:undoBefore,siblingsBefore:undoSiblings,index:Math.max(0,undoIndex),after:copy(c.selected_events.find(s=>s.event_id===e.event_id)||null),siblingsAfter:e.category==='AF'?copy(selectionsForEvent(e,false)):null};
    delete c.category_reviews[e.category];c.diagnosis_blocks.forEach(b=>{if(b.key===e.category+':'+e.subtype){b.acknowledged=false;if(b.manual)b.needs_review=true}});syncText();dirty();renderReportShell();
    // Explicitly applied settings change the range baseline and need a new editor.
    if(settings===null&&state.reportDisplayedCategory===category&&reportData?.items&&reportCategories.some(([key])=>key===category)){
      document.querySelectorAll('[data-include]').forEach(control=>{const event=reportData.items[Number(control.dataset.include)],included=!!selectionForEvent(event);control.checked=included;control.closest('tr')?.setAttribute('aria-selected',String(included));});
      const wave=qs('#v2EventWave');if(wave)wave.dataset.reportSelected=String(!!selectionForEvent(active));
      document.querySelectorAll('.report-range-editor').forEach(editor=>{if(editor._rangeEventId===e.event_id)editor._rangeSetMembership?.(checked);});
      renderEventNavigation(reportWaveReady);const complete=qs('#v2Complete');if(complete){const reviewed=c.category_reviews[category]===reportData.basis_versions[category];complete.setAttribute('aria-pressed',String(reviewed));complete.textContent=reviewed?'✓ 本类筛选已完成':'确认本类筛选完成';}
      if(checked&&!wasIncluded)return run(async()=>{
        const current=()=>advanceCase===state.caseId&&advanceCaseToken===state.caseRequestId&&advanceData===reportData&&advanceCategory===category&&advanceScope===waveEvidenceScope&&state.currentPage==='report'&&!state.reportViewLoading&&!state.reportViewError&&!state.reportEvidenceLoading&&!!selectionForEvent(e);
        if(!current())return;const local=reportData.items.findIndex(item=>item.event_id===e.event_id);if(local<0)return;const next=reportOffset+local+1;
        if(next>=reportData.total){if(active?.event_id!==e.event_id)await locate(e);return;}
        if(local+1<reportData.items.length)await locate(reportData.items[local+1]);
        else if(current()){reportOffset=Math.floor(next/50)*50;await refreshReport({viewOnly:true,edge:'first'});}
      });
      return Promise.resolve();
    }
    return run(renderReportBody);
  }
  let removedReportStrip=null;
  function renderStripUndo(){
    document.querySelector('#rwStripUndo')?.remove();
    const x=removedReportStrip;if(!x||x.id!==state.caseId||x.caseToken!==state.caseRequestId)return;
    const node=document.createElement('div');node.id='rwStripUndo';node.className='rw-strip-undo';node.setAttribute('role','status');node.textContent='已移除图条；原始记录与候选仍保留。';
    const b=document.createElement('button');b.type='button';b.textContent='撤销移除图条';b.onclick=()=>{if(x!==removedReportStrip||x.id!==state.caseId||x.caseToken!==state.caseRequestId)return;if(!selected().some(s=>stripKey(s)===stripKey(x.entry))){const e=selectedLookup.get(x.entry.event_id),use=sttUse(e);if(e?.category==='ST'&&(e.basis_version!==x.entry.basis_version||use&&use.basis_version!==x.entry.basis_version)){toast('复核依据已变化，未恢复旧图条；请重新采用','error');return;}state.reportComposition.selected_events.splice(Math.min(x.index,selected().length),0,copy(x.entry));if(selectedLookup.get(x.entry.event_id)?.category==='ST'){const uses=copy(sttUses()),original=x.sttUses.find(use=>use.event_id===x.entry.event_id),live=uses.find(use=>use.event_id===x.entry.event_id);if(live&&live.basis_version===x.entry.basis_version)live.strip=original?.strip===true;else if(!live)uses.push({event_id:x.entry.event_id,basis_version:x.entry.basis_version,table:false,text:false,strip:original?.strip===true});state.reportComposition.stt_report_use=uses.filter(use=>use.table||use.text||use.strip);}syncText();dirty();}removedReportStrip=null;renderReportShell();run(renderReportBody);};node.append(b);qs('#reportV2Notice').after(node);
  }
  function removeReportSelection(index){
    const entry=selected()[index];if(!entry)return;
    removedReportStrip={id:state.caseId,caseToken:state.caseRequestId,index,entry:copy(entry),sttUses:copy(sttUses())};
    state.reportComposition.selected_events.splice(index,1);
    if(selectedLookup.get(entry.event_id)?.category==='ST'){state.reportComposition.stt_report_use=copy(sttUses()).map(use=>use.event_id===entry.event_id?{...use,strip:false}:use).filter(use=>use.table||use.text||use.strip);}
    ECGReportRange.forget?.(stripKey(entry));
    syncText();dirty();renderReportShell();run(renderReportBody);
  }
  function enableReportDraftSelections(items){
    document.querySelectorAll('[data-include]').forEach(control=>{const e=items[Number(control.dataset.include)];if(!e)return;const pick=selectionForEvent(e),evidence=pick?selectedLookup.get(pick.event_id)||e:e,confirmed=evidence.evidence_only?ECGReportEvidenceUI.confirmed(pick||{...e.retained_settings,caption:e.label},evidence):evidence.diagnosis_status==='confirmed',status=control.closest('tr')?.querySelector('[data-event-status]'),replacement=!!returnedRhythmSelection(e);control.disabled=replacement;control.title=replacement?'先查看当前波形，再用当前片段替换原图条，保留导联与图注':confirmed?'加入报告':'可先加入报告草稿；最终审核前需完成诊断确认';control.setAttribute('aria-label',`${formatElapsed(e.time_s)} ${e.label}${replacement?'需核对并替换旧图条':confirmed?'加入报告':'加入报告草稿（待诊断确认）'}`);if(status&&!confirmed)status.textContent=`${e.beat_count} 搏 · 待诊断确认，可先入草稿`;if(status){status.title=status.textContent;status.textContent=`${e.beat_count} 搏 · ${confirmed?'已核对':e.evidence_only?'待核对':'待确认'}`;}});
  }
  function bindReportSelection(node,e){
    if(!node||!e||!globalThis.ECGChartInspection)return;
    const id=state.caseId,caseToken=state.caseRequestId,scope=waveEvidenceScope,data=reportData;
    const current=()=>node.isConnected&&id===state.caseId&&caseToken===state.caseRequestId&&scope===waveEvidenceScope&&data===reportData&&state.currentPage==='report'&&!state.reportEvidenceLoading&&!state.reportViewLoading&&!state.reportViewError;
    node.tabIndex=0;node.dataset.reportEventId=e.event_id;
    const included=e.category==='ST'?!!sttUse(e)&&Object.values(sttUse(e)).some(x=>x===true):!!selectionForEvent(e);
    node.dataset.reportSelected=String(included);
    if(node.tagName==='TR')node.setAttribute('aria-selected',String(included));
    else{node.setAttribute('role','group');node.setAttribute('aria-label',`${e.label} · ${included?'已加入报告草稿':'未加入报告草稿'}`);}
    if(e.category==='ST'||node.tagName==='TR'&&(e.category==='AF'||category==='rr_interval')){node.setAttribute('aria-description','单击或 Enter 查看波形；入报使用勾选。');ECGChartInspection.bindSelection(node,()=>{if(current())run(()=>locate(e));},{isCurrent:current});return;}
    node.setAttribute('aria-description','单击或空格/Enter 切换入报；新入报后自动下一条，取消保持当前位置。文字拖选和内部控件分别操作。');
    const toggle=()=>{
      if(!current())return;
      const control=[...document.querySelectorAll('[data-include]')].find(n=>reportData.items[Number(n.dataset.include)]?.event_id===e.event_id);
      if(!control||control.disabled)return;
      const hadFocus=document.activeElement===node,wave=node.id==='v2EventWave';
      const task=selectEvent(e,!selectionForEvent(e));
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
    if(['pause','rr_candidate'].includes(e.category)){const p=e.candidate_context,s=e.candidate_scope;if(e.rr_sources)return `<strong>RR ${Number(e.rr_ms)} ms</strong><span class="rw-rr-sources">${e.rr_sources.map(source=>source==='auto'?'自动长 RR':'自选 RR').join(' · ')}</span>`;if(e.category==='pause')return `<strong>${esc(e.label)}</strong><span>自动长 RR</span>`;return `<strong>${esc(e.label)}</strong><span>RR ${esc(p.rr_ms)} ms · 自选候选，非全程最长</span><details><summary>原始 RR 依据</summary><p>${formatElapsedPrecise(p.start_s)} → ${formatElapsedPrecise(p.end_s)}</p><p>原采样 ${p.rr_start_sample} → ${p.rr_end_sample} · II / V1 / V5 · 逐搏 r${s.beat_revision}</p><p>记录依据 ${esc(s.analysis_basis.slice(0,12))} · ${esc(p.population.claim)}</p></details>`;}
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
  function pendingRhythmPicks(){
    const seen=new Set();return selected().flatMap((s,i)=>{const e=selectedLookup.get(s.event_id),key=e?.rhythm_episode_id||e?.event_id;if(e?.category!=='AF'||e.rhythm_status==='confirmed'||!globalThis.ECGReportEvidenceUI?.used(composition(),s,e)||seen.has(key))return [];seen.add(key);return [i];});
  }
  function renderReportShell(){
    state.reportCategoryPending=[]; // Category browsing does not require a completion attestation.
    if(!qs('#reportV2'))return;
    const original=qs('#openSourceReport'),visibleOriginal=Boolean(state.includePhi&&state.caseData?.report_image_urls?.length);
    if(original){original.textContent=visibleOriginal?'原报告':'原报告说明';original.title=visibleOriginal?'查看当前病例原报告影像':'查看原报告影像的隐私遮蔽说明；不解除遮蔽';}
    renderRhythmReturn();
    ECGReportRange.setContext?.(JSON.stringify([state.caseId,state.caseRequestId]));
    renderRangeDraftNotice();
    const nav=qs('#reportV2Nav');
    const navButton=([key,label])=>{const count=reportData?.category_counts[key],countSelected=selectedCategoryCount(key);return `<button type="button" data-category="${key}" class="${category===key?'active':''}" aria-current="${category===key?'page':'false'}"><span>${label}</span><small ${count===undefined?'hidden':''}>${count===undefined?'':`${countSelected} / ${count}`}</small></button>`};
    if(!nav.querySelector?.('[data-category]'))nav.innerHTML='<div class="v2-candidate-tabs" role="group" aria-label="事件分类导航"><span>事件分类</span>'+reportCategories.map(navButton).join('')+'</div><div class="v2-compose-tabs" role="group" aria-label="报告操作"><span>报告操作</span>'+[['tables','数据表格'],['strips','图条设置'],['final','报告编排']].map(navButton).join('')+'</div>';
    else nav.querySelectorAll('[data-category]').forEach(button=>{const key=button.dataset.category,count=reportData?.category_counts[key],counter=button.querySelector('small');button.classList.toggle('active',key===category);button.setAttribute('aria-current',key===category?'page':'false');counter.hidden=count===undefined;counter.textContent=count===undefined?'':`${selectedCategoryCount(key)} / ${count}`;});
    qs('#reportStatus').textContent=STATUS_TEXT[state.report.status]||state.report.status;qs('#reportVersion').textContent='v'+state.report.version;
    if(!state.reportDirty){const editor=qs('#conclusionEditor'),text=state.report.conclusion||'';if(editor.value!==text)editor.value=text;qs('#reportSaveState').textContent=state.report.updated_at?'已保存 '+state.report.updated_at:'尚未保存';updateConclusionCount();}
    qs('.report-conclusion-dock').hidden=category!=='final';
    const stale=selected().filter(s=>!selectedLookup.has(s.event_id)||selectedLookup.get(s.event_id).basis_version!==s.basis_version).length;
    state.reportEvidencePending=selected().flatMap((s,i)=>{const e=selectedLookup.get(s.event_id);if(!globalThis.ECGReportEvidenceUI?.used(composition(),s,e))return [];return !e||e.basis_version!==s.basis_version?[{index:i,status:'stale'}]:e.evidence_only&&!ECGReportEvidenceUI.confirmed(s,e)?[{index:i,status:'pending'}]:[];});
    state.reportSTTPending=sttUses().filter(use=>{const c=composition(),used=use.text||use.table&&c.included_pages.includes('st_events')||use.strip&&c.included_pages.includes('event_strips');if(!used)return false;const e=selectedLookup.get(use.event_id),eligible=sttEligibility(e);return !e||e.basis_version!==use.basis_version||!sttReviewed(e)||['table','text','strip'].some(key=>use[key]&&!eligible[key]);});
    state.reportRhythmPending=pendingRhythmPicks();
    let sttNotice=qs('#reportSTTPending');if(!sttNotice){sttNotice=document.createElement('div');sttNotice.id='reportSTTPending';sttNotice.className='rw-evidence-pending';qs('#reportV2Notice').after(sttNotice);}sttNotice.hidden=!state.reportSTTPending.length||state.reportEvidenceLoading;if(!sttNotice.hidden){sttNotice.replaceChildren(document.createTextNode(`${state.reportSTTPending.length} 条已采用ST-T复核依据待核对 `));const b=document.createElement('button');b.type='button';b.textContent='查看复核记录';b.onclick=()=>run(()=>chooseReportCategory('ST'));sttNotice.append(b);const remove=document.createElement('button');remove.type='button';remove.textContent='撤下这些失效用途';remove.disabled=!!(state.reportSaving||state.reportStale||state.reportEvidenceLoading);remove.onclick=()=>run(async()=>{if(!await resolveWorkstationLeave())return;const ids=new Set(state.reportSTTPending.map(use=>use.event_id));state.reportComposition=composition();state.reportComposition.stt_report_use=copy(sttUses()).filter(use=>!ids.has(use.event_id));state.reportComposition.selected_events=selected().filter(pick=>!ids.has(pick.event_id));syncText();dirty();renderReportShell();await renderReportBody();});sttNotice.append(remove);}

    let evidenceNotice=qs('#reportEvidencePending');
    if(!evidenceNotice){evidenceNotice=document.createElement('div');evidenceNotice.id='reportEvidencePending';evidenceNotice.className='rw-evidence-pending';qs('#reportV2Notice').after(evidenceNotice);}
    evidenceNotice.hidden=!state.reportEvidencePending.length||state.reportEvidenceLoading;
    if(!evidenceNotice.hidden){evidenceNotice.replaceChildren(document.createTextNode(`${state.reportEvidencePending.length} 条本次报告证据待核对或依据已变化 `));const button=document.createElement('button');button.type='button';button.textContent='查看待处理图条';button.onclick=()=>run(async()=>{ECGReportWorkspace.setReviewFilter(state.reportEvidencePending[0].status);await chooseReportCategory('strips');});evidenceNotice.append(button);}
    let rhythmNotice=qs('#reportRhythmPending');
    if(!rhythmNotice){rhythmNotice=document.createElement('div');rhythmNotice.id='reportRhythmPending';rhythmNotice.className='rw-evidence-pending';qs('#reportV2Notice').after(rhythmNotice);}
    rhythmNotice.hidden=!state.reportRhythmPending.length||state.reportEvidenceLoading;
    if(!rhythmNotice.hidden){rhythmNotice.replaceChildren(document.createTextNode(`${state.reportRhythmPending.length} 段入报房颤 / 房扑待确认 `));const button=document.createElement('button');button.type='button';button.textContent='在报告中复核';button.disabled=!!(state.reportSaving||state.reportStale||state.reportViewLoading||state.reportViewError);button.onclick=()=>run(()=>backToReportEvent(state.reportRhythmPending[0]));rhythmNotice.append(button);}
    qs('#reportV2Notice').textContent=state.reportEvidenceLoading?`正在核对报告依据；原有选图和人工文字保留${reportData?` · 下列计数仍为已读取依据 r${reportData.analysis_revision}，本次核对未完成`:''}`:state.reportEvidenceError?'报告依据未能完整读取，请重新加载后复核；不能认定无事件':`已选 ${selected().length} 条 · 统计为全记录${reportData?.analysis_revision!==undefined?' · 依据 r'+reportData.analysis_revision:''} · ${clinicalWorkflow.readiness()?"模板编辑已确认":"模板编辑待确认"}${state.reportCategoryPending.length?' · '+state.reportCategoryPending.length+' 类报告筛选待确认':''}${stale?' · '+stale+'条已失效，须重新核对；房颤片段可复核后替换，其余移除后重新筛选':''}`;
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
        ?Boolean(state.reportViewLoading||state.reportViewError||state.reportEvidencePending.length||state.reportRhythmPending.length||state.reportSTTPending.length)||!ECGReportConsistency.canApprove(state,qs('#conclusionEditor').value,clinicalWorkflow.readiness(),clinicalWorkflow.writable())
        :Boolean(!clinicalWorkflow.writable()||state.reportSaving||state.reportStale);
    }
    document.querySelectorAll('[data-rhythm-replace]').forEach(button=>{button.disabled=!canReplaceReturnedRhythm();});
    renderExportState();
    // Reload/conflict responses can change report state without a workflow fetch.
    clinicalWorkflow.renderPreflight();
  }
  async function reloadReport(discard=false){
    globalThis.ECGAdvancedAnalysis?.assertApplied();globalThis.ECGHRVEditor?.assertApplied();
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
    globalThis.ECGAdvancedAnalysis?.assertApplied();globalThis.ECGHRVEditor?.assertApplied();
    ECGReportRange.assertApplied?.();
    if(local!==ECGReportConsistency.content(qs('#conclusionEditor').value,composition())||!ECGReportConsistency.sameBase(base,state.report)||state.reportSaving){
      state.reportStale=true;renderReportShell();throw Error('读取期间本窗口有新修改，已保留；请核对后再次载入最新版本');
    }
    state.report=remote;state.reportDirty=false;state.reportStale=false;
    state.reportComposition=copy(remote.composition);reportVersion=null;
    await refreshReport();
  }
  async function renderSTTReportBody(host,bodyCurrent){
    const items=reportData.items,selectedCount=sttUses().filter(u=>u.table||u.text||u.strip).length;
    const groupCounts=reportData.stt_counts||{},full=reportData.confirmed_category_counts?.ST;
    host.innerHTML=`<div class="v2-category-bar"><strong>ST-T · ${reportData.total} 条记录</strong><label>查看<select id="v2STGroup">${Object.entries(sttGroups).map(([value,label])=>`<option value="${value}" ${sttGroup===value?'selected':''}>${label}${groupCounts[value]===undefined?'':' · '+groupCounts[value]}</option>`).join('')}</select></label><span>已采用 ${selectedCount} 条${full===undefined?'':` · 全记录已确认异常 ${full} 条`}</span><button type="button" data-stt-workbench>ST-T工作台</button></div><div class="v2-event-layout"><div class="v2-event-list"><table><thead><tr><th>时间 / 复核结果</th><th>表</th><th>文</th><th>图</th></tr></thead><tbody>${items.map((e,i)=>{const use=sttUse(e),eligible=sttEligibility(e);return `<tr data-preview="false"><td><button data-locate="${i}" aria-current="false">${formatElapsed(e.time_s)}</button><strong>${esc(sttOutcomes[e.stt_result_code]||e.label)}</strong><small>${Number.isFinite(e.end_s)?((e.end_s-e.time_s)/60).toFixed(2)+' 分钟 · ':''}${esc((e.stt_review_receipt?.leads||e.stt_event_evidence?.leads||[e.lead]).filter(Boolean).join('/'))} · ${use&&use.basis_version!==e.basis_version?'已采用内容来自旧依据':sttReviewed(e)?'已复核':e.stt_review_state==='stale'?'依据已变化':'待处理'}</small></td>${['table','text','strip'].map(key=>`<td><input type="checkbox" data-stt-use="${key}" data-stt-index="${i}" aria-label="${formatElapsed(e.time_s)} ${esc(sttOutcomes[e.stt_result_code]||e.label)}${{table:'用于事件表',text:'用于报告文字',strip:'加入代表图条'}[key]}" ${use?.[key]?'checked':''} ${!use?.[key]&&(!sttReviewed(e)||!eligible[key])?'disabled':''}></td>`).join('')}</tr>`;}).join('')||'<tr><td colspan="4">'+(sttGroup==='all'?'暂无已保存复核记录':'当前筛选无匹配记录')+'</td></tr>'}</tbody></table><footer><button id="v2Prev" aria-label="上一页" ${reportOffset===0?'disabled':''}>‹</button><span>${reportData.total?reportOffset+1:0}–${reportOffset+items.length} / ${reportData.total}</span><button id="v2Next" aria-label="下一页" ${reportOffset+items.length>=reportData.total?'disabled':''}>›</button></footer></div><div class="v2-event-detail"><nav id="v2EventNavigation" class="v2-event-navigation" aria-label="ST-T复核记录查看与采用" tabindex="-1"></nav><div id="v2EventWave"><p class="empty-state">选择记录查看原始波形</p></div><small id="v2WaveLabel"></small></div></div>`;
    host.querySelector('#v2STGroup').onchange=event=>{const value=event.target.value;run(()=>changeReportView(()=>{sttGroup=value;reportOffset=0;reportMode='all';}));};
    host.querySelector('[data-stt-workbench]').onclick=()=>run(async()=>{if(await resolveWorkstationLeave())goPage('stt');});
    host.querySelectorAll('[data-stt-use]').forEach(input=>input.onchange=()=>run(async()=>{try{await setSTTUse(items[Number(input.dataset.sttIndex)],input.dataset.sttUse,input.checked);}finally{syncSTTControls();}}));
    host.querySelectorAll('tr[data-preview]').forEach((row,i)=>bindReportSelection(row,items[i]));
    host.querySelector('#v2Prev').onclick=()=>run(()=>changeReportView(()=>{reportOffset=Math.max(0,reportOffset-50);}));
    host.querySelector('#v2Next').onclick=()=>run(()=>changeReportView(()=>{reportOffset+=50;}));
    if(items.length&&bodyCurrent())await locate(items.find(e=>e.event_id===active?.event_id)||items[0]);else {active=null;renderEventNavigation();}
  }
  async function renderReportBody(){
    renderStripUndo();
    const host=qs('#reportV2Content');if(!host||!reportData)return;
    const bodyCase=state.caseId,bodyCaseToken=state.caseRequestId,bodyCategory=category,bodyToken=++reportRenderToken;
    const bodyCurrent=()=>bodyCase===state.caseId&&bodyCaseToken===state.caseRequestId&&bodyCategory===category&&bodyToken===reportRenderToken&&host===qs('#reportV2Content');
    const distributionOpen=renderReportBody.distributionOpen||(renderReportBody.distributionOpen=new Map()),previousDistributions=host.querySelector('.v2-candidate-distributions'),distributionKey=JSON.stringify([bodyCase,bodyCaseToken,bodyCategory]);
    if(previousDistributions?._reportCase===bodyCase&&previousDistributions._reportCaseToken===bodyCaseToken)distributionOpen.set(previousDistributions._reportDistributionKey,previousDistributions.open);
    const candidates=!['tables','strips','final'].includes(category);
    host.classList.toggle('report-candidate-workspace',candidates);
    qs('#page-report')?.classList.toggle('report-candidate-page',candidates);
    globalThis.ECGReportWorkspace?.releaseTerminology(host);
    const dock=qs('.report-conclusion-dock');if(dock&&host.contains(dock))qs('#reportV2').after(dock);
    if(category==='tables'){host.innerHTML='<section id="reportHourlyStatistics" role="region" aria-label="当前修订小时统计">正在读取小时统计…</section>'+statsTable()+'<div id="reportHrvV2"></div>';await Promise.all([loadHourlyStatistics(bodyCurrent),loadHrv('#reportHrvV2')]);return;}
    if(category==='strips'||category==='final'){
      const token=bodyToken,id=state.caseId;
      if(category==='final'||category==='strips'){
        ECGReportWorkspace.compose(host,{id,inspection:category==='strips',recordStart:state.caseData?.metadata?.start_time,composition:composition(),selected:selected(),lookup:selectedLookup,sections:ECGReportSections.catalog(),overview:{categories:reportCategories.map(([key,label])=>({label,events:reportData.confirmed_category_counts?.[key]??null,beats:reportData.confirmed_beat_counts?.[key]??null})),source:{total_beats:state.caseData.summary.total_beats,avg_hr:state.caseData.summary.avg_hr,sdnn_ms:state.caseData.summary.sdnn_ms},revision:reportData.analysis_revision},isCurrent:bodyCurrent,termContext:{api,reportContext:JSON.stringify([id,state.caseRequestId,state.report?.version])},onUsages:usages=>{if(!bodyCurrent())return;state.reportComposition=composition();state.reportComposition.terminology_usages=copy(usages);dirty()},loadWave:async(e,s)=>{const entry=await reportStrip(e,s,id);if(!bodyCurrent())throw Error('报告视图已变化');return {...entry,waveform:await reportReviewWave(entry,id)};},renderWave:entry=>ECGReportPaper.stripSvg(entry,composition().paper),onStripEdit:i=>run(()=>editReportStrip(i,bodyCurrent)),onStripPrint:(i,enabled)=>{if(!bodyCurrent()||!selected()[i])return;const pick=selected()[i],e=selectedLookup.get(pick.event_id),uses=copy(sttUses());pick.print_enabled=enabled;if(e?.category==='ST'){let use=uses.find(x=>x.event_id===e.event_id);if(!use){use={event_id:e.event_id,basis_version:e.basis_version,table:false,text:false,strip:false};uses.push(use);}use.strip=enabled;state.reportComposition.stt_report_use=uses.filter(x=>x.table||x.text||x.strip);}dirty();renderReportShell();run(renderReportBody);},onStripRemove:i=>{if(bodyCurrent())removeReportSelection(i);},onStripReference:(i,checked)=>{if(!bodyCurrent()||!selected()[i])return;selected()[i].referenced_in_report=checked;dirty();run(renderReportBody);},onReviewEvidence:i=>run(()=>reviewReportEvidence(i)),onReviewLongest:()=>run(()=>reviewReportEvidence(null,'longest')),loadLongestRR:()=>endpoint('report-rr-evidence',{...waveEvidence},id),onTemplates:()=>run(()=>editNarrativeTemplates(bodyCurrent)),loadTrend:async()=>{const data=await endpoint('overview',{...waveEvidence},id);if(!bodyCurrent())throw Error('病例或依据已变化');ECGAnalysisConsistency.assertSame(reportData,data);return data;},onSTTrendMetric:metric=>{if(!bodyCurrent()||!['st_level','delta'].includes(metric))return;state.reportComposition.stt_trend_metric=metric;dirty();},onPages:pages=>{state.reportComposition.included_pages=pages;state.reportComposition.page_selection_version=1;state.reportComposition.include_hrv=pages.some(k=>k.startsWith('hrv_'));dirty();renderReportShell()},onMode:mode=>{state.reportComposition=ECGReportWorkspace.withRateMode(state.reportComposition,mode);dirty();run(()=>refreshReport({viewOnly:true}))},onPreview:()=>run(previewPaper),onStripLeads:(i,leads)=>{if(!bodyCurrent()||!selected()[i])return;selected()[i].leads=[...leads];dirty();run(renderReportBody);},onSort:order=>{if(!bodyCurrent())return;state.reportComposition.selected_events=ECGReportWorkspace.sortSelections(selected(),selectedLookup,order);dirty();run(renderReportBody);},renderAdvanced:panel=>mountAdvanced(panel,id)});
        if(composition().diagnosis_blocks.some(b=>b.needs_review))host.querySelector('#rwConclusionSlot').insertAdjacentHTML('afterbegin','<section aria-label="人工诊断文字复核"><h3>依据变化后，请重新核对人工文字</h3><p>原文字已保留；核对当前波形及报告正文后再确认。</p>'+diagnosisBlocksHtml()+'</section>');
        return;
      }
      host.innerHTML=stripSettingsHtml(composition().strip_defaults,'default')+'<div id="v2TextBlocks">'+diagnosisBlocksHtml()+'</div>'+selected().map((s,i)=>{const e=selectedLookup.get(s.event_id),valid=e&&e.basis_version===s.basis_version;return `<article class="rp-editor-strip"><header><strong>${i+1}. ${esc(e?.label||s.event_id)}${valid?'':'（已失效）'}</strong><div><button data-back-event="${i}">回看</button><button data-move="${i}" data-delta="-1" aria-label="图条上移" ${i===0?'disabled':''}>上移</button><button data-move="${i}" data-delta="1" aria-label="图条下移" ${i===selected().length-1?'disabled':''}>下移</button><button data-remove="${i}">移除</button></div></header><label>图注<input data-caption="${i}" value="${esc(s.caption)}" maxlength="500"></label>${stripSettingsHtml(s,String(i))}<div data-selected-wave="${i}">${valid?'读取波形…':'图条已失效，请重新筛选'}</div><p class="rp-strip-status" data-strip-status="${i}" aria-live="polite"></p></article>`}).join('')+(selected().length?'':'<p class="empty-state">尚未选择图条。在事件列表设置导联后勾选“入报”；也可以在这里修改每条图的导联与时长。</p>');
      selected().forEach((s,i)=>host.querySelector(`[data-back-event="${i}"]`).insertAdjacentHTML('afterend',rhythmReviewButton(selectedLookup.get(s.event_id),i)));
      await Promise.all(selected().map(async(s,i)=>{const e=selectedLookup.get(s.event_id),target=host.querySelector(`[data-selected-wave="${i}"]`);if(!e||e.basis_version!==s.basis_version)return;try{const entry=await reportStrip(e,s,id);if(bodyCurrent()&&target?.isConnected){target.innerHTML=ECGReportPaper.stripSvg(entry,composition().paper,s.leads?.length>6?880:s.leads?.length>3?520:276);const article=target.closest('.rp-editor-strip');article.tabIndex=0;const edit=document.createElement('button');edit.type='button';edit.textContent='编辑本条图条';edit.onclick=()=>run(()=>editReportStrip(i,bodyCurrent));article.querySelector('header>div').append(edit);article.oncontextmenu=ev=>{if(ev.target.closest('input,textarea,select'))return;ev.preventDefault();edit.focus();run(()=>editReportStrip(i,bodyCurrent));};host.querySelector(`[data-strip-status="${i}"]`).textContent=`${ECGReportEngine.reviewNote(entry)?ECGReportEngine.reviewNote(entry)+' · ':''}${formatElapsed(entry.waveform.start_s)}–${formatElapsed(entry.waveform.start_s+entry.waveform.duration_s)} · ${entry.strip.visible_beat_count} 搏 · ${entry.strip.warning||'时间窗满足至少 5 搏'}`;await mountRange(target,e,entry,id);}}catch(error){if(bodyCurrent()&&target?.isConnected)target.textContent='读取失败：'+error.message;}}));return;
    }
    if(category==='ST')return renderSTTReportBody(host,bodyCurrent);
    const items=reportData.items,rateCandidates=['fastest','slowest'].includes(category);
    const pageCount=Math.max(1,Math.ceil(reportData.total/50));
    host.innerHTML=`<div class="v2-category-bar"><strong>${Object.fromEntries(tabs)[category]} · ${reportData.total} 条${rateCandidates?'候选':''}</strong>
      <label>亚型<select id="v2Subtype"><option value="all">${rateCandidates?'全部序列':'全部（不叠加模式计数）'}</option>${Object.entries(reportData.subtype_counts).map(([k,n])=>`<option value="${k}" ${reportMode===k?'selected':''}>${esc(Object.fromEntries(A.patterns)[k]||k)} · ${n}</option>`).join('')}</select></label>
      ${rateCandidates?`<label>计算序列<select id="v2Fast"><option value="rr">RR</option><option value="nn">NN</option><option value="both">RR 与 NN</option></select></label><label>心率排序<select id="v2RateSort"><option value="hr_desc" ${reportSort==='hr_desc'?'selected':''}>从快到慢</option><option value="hr_asc" ${reportSort==='hr_asc'?'selected':''}>从慢到快</option></select></label>`:''}
      </div>
      ${rateCandidates?`<div class="v2-rate-help"><p>RR / NN 单间期瞬时心率，非 7 秒平均心率。每序列最多 200 条，短记录按实显示。</p><p role="status">当前时间／序列内 ${reportData.candidate_unspaced_total} 条 · 显示 ${reportData.total} 条 · 间隔隐藏 ${reportData.candidate_hidden_count} 条。“全部候选”可恢复。</p><details><summary>间隔筛选说明</summary><p>只精简当前列表的相邻定位点，优先保留本类极值，RR / NN 分开；不保证图条无重叠，不改变统计或已选图条。柱图保留未按间隔精简的分布。回看入报图条或待应用游标时自动恢复全部候选。</p></details></div>`:''}
      <div class="v2-event-layout"><div class="v2-event-list"><table><thead><tr><th>入报</th><th>${rateCandidates?'序号 / 时间':'时间'}</th><th>${rateCandidates?'候选心率 / RR':'模板 / 亚型'}</th></tr></thead><tbody>${items.map((e,i)=>`<tr data-preview="false"><td><input type="checkbox" data-include="${i}" aria-label="${formatElapsed(e.time_s)} ${esc(e.label)}入报" ${!!selectionForEvent(e)?'checked':''}></td><td>${rateCandidates?`<span class="v2-candidate-rank">第 ${reportOffset+i+1} 条</span>`:''}<button data-locate="${i}" aria-current="false">${formatElapsed(e.time_s)}</button></td><td>${rateCandidates?`<strong class="v2-candidate-rate">${ECGReviewTools.bpm(e.hr)} bpm</strong><div>${esc(e.subtype)} ${e.rr_ms}ms</div>`:reportTemplateCell(e)}<small data-event-status>${e.evidence_only?'人工留图候选 · ':''}${e.beat_count} 搏 · ${e.diagnosis_status==='confirmed'?'已确认':'待诊断确认'}</small></td></tr>`).join('')||'<tr><td colspan="3">0 条匹配记录</td></tr>'}</tbody></table>
      <footer><button id="v2Prev" ${reportOffset===0?'disabled':''}>上一页</button><span>${reportData.total?reportOffset+1:0}–${reportOffset+items.length} / ${reportData.total}</span>${rateCandidates?`<label>页码<select id="v2ReportPage" aria-label="候选页码">${Array.from({length:pageCount},(_,i)=>`<option value="${i}" ${i===Math.floor(reportOffset/50)?'selected':''}>${i+1} / ${pageCount}</option>`).join('')}</select></label>`:''}<button id="v2Next" ${reportOffset+items.length>=reportData.total?'disabled':''}>下一页</button></footer></div>
      <div class="v2-event-detail"><div class="v2-distribution">${Object.entries(reportData.subtype_counts).map(([k,n])=>`<span>${esc(Object.fromEntries(A.patterns)[k]||k)} <b>${n}</b></span>`).join('')}<small>${rateCandidates?'RR：有效相邻心搏间期；NN：连续正常心搏且在设置范围内。这里只提供选图候选，不替代医生确认。':'连续搏数与重复节律为重叠标签，不能相加'}</small></div><div id="v2TimeDistribution"></div><div id="v2EventWave"><p class="empty-state">点击左侧事件查看完整波形</p></div><small id="v2WaveLabel"></small></div></div>`;
    qs('.v2-category-bar').insertAdjacentHTML('beforeend',`<details class="v2-candidate-settings"><summary>${defaultStripSummary()}</summary>${stripSettingsHtml(defaultStripSpec(),'default')}</details>`);
    const rateHelp=host.querySelector('.v2-rate-help');if(rateHelp){const disclosure=document.createElement('details');disclosure.className='v2-candidate-help';disclosure.innerHTML=`<summary>RR / NN 单间期候选 · 显示 ${reportData.total} 条 · 间隔隐藏 ${reportData.candidate_hidden_count} 条 · 说明</summary>`;rateHelp.before(disclosure);disclosure.append(rateHelp);}
    if(category==='pause'){
      const counts=reportData.pause_counts;
      qs('#v2Subtype').closest('label').hidden=true;
      qs('.v2-category-bar strong').textContent=`长 RR 候选 ${reportData.total} 条`;
      const bins=reportData.pause_distribution.bins;
      qs('.v2-category-bar').insertAdjacentHTML('beforeend',`<label>显示范围<select id="v2PauseBand"><option value="all">原检测候选 RR &gt;2.5 秒 · ${counts.all} 次</option>${bins.map((bin,i)=>`<option value="b${i}">${bin.label}（统计 ${bin.count} 次）</option>`).join('')}</select></label>`);
      qs('#v2PauseBand').value=pauseBand;
      qs('#v2PauseBand').onchange=e=>{const value=e.target.value;run(()=>changeReportView(()=>{pauseBand=value;reportOffset=0}));};
      qs('.v2-distribution').innerHTML='<small>互斥柱图统计所有有效相邻 RR（含下界）；左侧原检测候选仍为 RR&gt;2.5秒，因此恰好2.5秒只进入统计。长 RR 不等同确诊停搏。</small>';
    }
    if(category==='rr_interval'){const bar=qs('.v2-category-bar');qs('#v2Subtype').closest('label').hidden=true;bar.insertAdjacentHTML('beforeend',`<label>来源<select id="v2RRSource"><option value="all">全部</option><option value="auto">自动长 RR（&gt;2.5秒）</option><option value="manual">自选 RR</option></select></label>`);qs('#v2RRSource').value=rrSource;qs('#v2RRSource').onchange=e=>{const source=e.target.value;run(()=>changeReportView(()=>{rrSource=source;reportMode='all';reportOffset=0}));};bar.insertAdjacentHTML('beforeend',`<label>候选排序<select id="v2RRCandidateSort"><option value="hr_asc">RR 从长到短</option><option value="time">按时间</option></select></label><span>同一 RR 合并显示，来源保留。${state.reportRRMerged?.length?'已合并 '+state.reportRRMerged.length+' 条重复图条，保存时同步。':''}</span><a class="rw-rr-help" href="static/help/af-afl.html#rr-candidates" target="_blank" rel="noopener">帮助</a>`);qs('#v2RRCandidateSort').value=reportSort;qs('#v2RRCandidateSort').onchange=e=>{const value=e.target.value;run(()=>changeReportView(()=>{reportSort=value;reportOffset=0}));};}
    enableReportDraftSelections(items);
    host.querySelectorAll('tr[data-preview]').forEach((row,i)=>{const e=items[i],info=`${formatElapsed(e.time_s)} · ${e.hr?ECGReviewTools.bpm(e.hr)+' bpm · ':''}${e.rr_ms?e.subtype+' '+e.rr_ms+' ms · ':''}${e.beat_count} 搏 · ${e.diagnosis_status==='confirmed'?'已确认':'待诊断确认'}`;row.title=info;row.querySelector('[data-include]').setAttribute('aria-label',info+'入报');bindReportSelection(row,e);});
    qs('#v2EventWave').insertAdjacentHTML('beforebegin','<nav id="v2EventNavigation" class="v2-event-navigation" aria-label="候选事件连续核查" tabindex="-1"></nav>');
    qs('#v2Subtype').onchange=e=>{const value=e.target.value;run(()=>changeReportView(()=>{reportMode=value;reportOffset=0}));};
    if(qs('#v2Fast')){qs('#v2Fast').value=reportSequence();qs('#v2Fast').onchange=e=>{const value=e.target.value;run(()=>changeReportView(()=>{reportOffset=0;reportMode='all';state.reportComposition=ECGReportWorkspace.withRateMode(state.reportComposition,value);delete state.reportComposition.category_reviews.fastest;delete state.reportComposition.category_reviews.slowest;dirty();}));}}
    if(qs('#v2RateSort'))qs('#v2RateSort').onchange=e=>{const value=e.target.value;run(()=>changeReportView(()=>{reportSort=value;reportOffset=0}));};
    if(rateCandidates){
      qs('.v2-category-bar').insertAdjacentHTML('beforeend',`<label>定位点间隔<select id="v2RateSpacing">${[[0,'全部候选'],[7,'至少 7 秒'],[30,'至少 30 秒'],[60,'至少 60 秒']].map(([v,label])=>`<option value="${v}" ${reportSpacing===v?'selected':''}>${label}</option>`).join('')}</select></label>`);
      qs('#v2RateSpacing').onchange=e=>{const value=Number(e.target.value);run(()=>changeReportView(()=>{reportSpacing=value;reportOffset=0}));};
    }
    if(qs('#v2ReportPage'))qs('#v2ReportPage').onchange=e=>{const value=Number(e.target.value)*50;run(()=>changeReportView(()=>{reportOffset=value}));};
    qs('#v2Prev').textContent='‹';qs('#v2Prev').setAttribute('aria-label','上一页');qs('#v2Next').textContent='›';qs('#v2Next').setAttribute('aria-label','下一页');
    qs('#v2Prev').onclick=()=>run(()=>changeReportView(()=>{reportOffset=Math.max(0,reportOffset-50)}));qs('#v2Next').onclick=()=>run(()=>changeReportView(()=>{reportOffset+=50}));
    const distribution=qs('.v2-distribution');distribution.className='rw-distributions';qs('#v2TimeDistribution').remove();
    const distributions=document.createElement('details');distributions.className='v2-candidate-distributions';distributions.open=distributionOpen.get(distributionKey)??(bodyCategory!=='AF');distributions._reportCase=bodyCase;distributions._reportCaseToken=bodyCaseToken;distributions._reportDistributionKey=distributionKey;const distributionState=()=>{const status=distributions.querySelector('[data-category-view-state]');if(status)status.textContent=`${Object.fromEntries(tabs)[bodyCategory]} · 本类${distributions.open?'展开':'折叠'} · 切类后恢复`;};distributions.ontoggle=()=>{if(distributions.isConnected&&bodyCurrent()){distributionOpen.set(distributionKey,distributions.open);distributionState();}};distributions.innerHTML=`<summary>分布 / 筛选 · ${reportMode==='all'?'全部亚型':esc(Object.fromEntries(A.patterns)[reportMode]||reportMode)} · ${reportTimeRange?'已限定时段':'全部时间'} · ${reportData.total} 条 <span class="v2-category-view-state" data-category-view-state></span></summary>`;distributionState();distributions.title='本窗口按事件类别保留筛选、定位、列表位置和折叠状态；不改变入报图条或报告设置。';distribution.before(distributions);distributions.append(distribution);
    const help=host.querySelector('.v2-candidate-help');if(help){help.querySelector('summary').textContent='RR / NN 候选说明';qs('.v2-category-bar').append(help);}
    ECGReportWorkspace.distributions(distribution,reportData,{mode:reportMode,range:reportTimeRange,pauseBand,category,labels:Object.fromEntries(A.patterns),change:next=>run(()=>changeReportView(()=>{if('pauseEdges' in next){state.reportComposition.pause_edges_ms=next.pauseEdges;pauseBand='all';dirty();}if('mode' in next)reportMode=next.mode;if('range' in next)reportTimeRange=next.range;if('pauseBand' in next)pauseBand=next.pauseBand;if('spacing' in next)reportSpacing=next.spacing;reportOffset=0;}))});
    if(innerWidth>=1100){const list=qs('.v2-event-list'),navigation=qs('#v2EventNavigation');if(list&&navigation)list.prepend(navigation);}
    if(items.length)await locate(items.find(e=>e.event_id===active?.event_id)||items[0]);
    else{active=null;renderEventNavigation();}
  }
  function mountSavedSTNote(target,event,isCurrent){
    target.querySelectorAll('[data-report-saved-st-note]').forEach(node=>node.remove());
    if(event?.category!=='ST'||typeof event.note!=='string'||!event.note.trim())return;
    // These are historical saved values, never a new calculation or diagnosis.
    const note=event.note,eventId=event.event_id,eventBasis=event.basis_version,editor=qs('#conclusionEditor'),
      statistics=event.range_statistics?copy(event.range_statistics):null,
      analysis=copy(waveEvidence),privacyToken=state.privacyRequestId??0;
    function statisticsCurrent(){
      if(!statistics)return true;
      const scope=statistics.scope,history=state.caseData?.beat_editor_history?.revision;
      if(!scope||scope.case_id!==state.caseId||!Number.isSafeInteger(scope.analysis_revision)||scope.analysis_revision<0||!Number.isSafeInteger(scope.beat_revision)||scope.beat_revision<0||Number.isSafeInteger(history)&&history>=0&&history!==scope.beat_revision)return false;
      try{const current=ECGAnalysisConsistency.identity(state.caseData);return scope.analysis_basis===current.analysis_basis&&scope.analysis_revision+1===current.analysis_revision&&reportData?.case_id===state.caseId&&reportData.analysis_basis===current.analysis_basis&&reportData.analysis_revision===current.analysis_revision&&reportData.beat_revision===scope.beat_revision;}catch{return false;}
    }
    const detail=document.createElement('details');detail.dataset.reportSavedStNote=eventId;
    const summary=document.createElement('summary');summary.textContent=statistics?'已保存备注 / 保存时区间统计'+(statisticsCurrent()?'':'（旧依据）'):'已保存备注';detail.append(summary);
    const original=document.createElement('p');original.style.whiteSpace='pre-wrap';original.style.overflowWrap='anywhere';original.dataset.reportSavedStOriginal='';original.textContent=note;detail.append(original);
    if(statistics){
      const saved=document.createElement('section');saved.setAttribute('aria-label','保存时区间统计');
      const title=document.createElement('strong');title.textContent='保存时区间统计';saved.append(title);
      const range=statistics.range||{},point=statistics.method_profile?.measurement_ms,
        value=x=>typeof x==='number'&&Number.isFinite(x)?String(x):'—';
      const description=document.createElement('p');description.textContent=`${Number.isFinite(range.start_s)&&Number.isFinite(range.end_s)?`记录后 ${formatElapsed(range.start_s)}–${formatElapsed(range.end_s)} · `:''}${[0,60,80].includes(point)?point===0?'J 点 · ':`J+${point} ms · `:''}事件保存时的记录，未重新计算。u 未校准。`;saved.append(description);
      if(Array.isArray(statistics.leads)){
        const table=document.createElement('table');table.innerHTML='<thead><tr><th>导联</th><th>均值（u）</th><th>有效搏数</th></tr></thead><tbody></tbody>';
        statistics.leads.forEach(row=>{const tr=document.createElement('tr');[row.lead??'—',value(row.mean_units),value(row.used_count)].forEach(text=>{const td=document.createElement('td');td.textContent=String(text);tr.append(td);});table.querySelector('tbody').append(tr);});saved.append(table);
      }
      detail.append(saved);
    }
    const button=document.createElement('button');button.type='button';button.dataset.reportAppendStNote='';button.textContent='填入报告结论';
    const status=document.createElement('p');status.setAttribute('role','status');status.dataset.reportAppendStStatus='';detail.append(button,status);target.append(detail);
    function owned(){
      if(!detail.isConnected||!target.isConnected||!isCurrent()||state.currentPage!=='report'||state.reportSaving||state.reportStale||state.reportEvidenceLoading||state.reportEvidenceError||state.reportViewLoading||state.reportViewError||state.privacySaving||state.privacyIdentityPending||privacyToken!==(state.privacyRequestId??0))return false;
      const candidate=target.id==='v2EventWave',live=candidate?active:selectedLookup.get(eventId);
      if(!live||live.category!=='ST'||live.event_id!==eventId||live.basis_version!==eventBasis||live.note!==note)return false;
      if(!candidate&&!selected().some(s=>s.event_id===eventId&&s.basis_version===eventBasis))return false;
      try{ECGAnalysisConsistency.assertSame(analysis,state.caseData);}catch{return false;}
      return true;
    }
    button.disabled=!clinicalWorkflow.writable()||!statisticsCurrent();
    if(statistics&&!statisticsCurrent())status.textContent='保存时统计来自旧依据，请重新计算后填入；历史备注仍保留。';
    button.onclick=()=>{
      if(!owned()){status.textContent='事件、病例或依据已变化，请重新读取后填入。';return;}
      if(!statisticsCurrent()){button.disabled=true;status.textContent='保存时统计来自旧依据，请重新计算后填入；历史备注仍保留。';return;}
      if(!clinicalWorkflow.writable()||!editor||qs('#conclusionEditor')!==editor||editor.readOnly||editor.disabled){status.textContent='当前报告结论不可编辑；请重新读取后填入。';return;}
      const before=editor.value,addition=(before&&!before.endsWith('\n')?'\n':'')+note,
        maximum=Math.min(12000,editor.maxLength>=0?editor.maxLength:12000);
      if(before.length+addition.length>maximum){status.textContent=`报告结论最多 ${maximum} 字；请先精简正文后再填入，原文字已保留。`;return;}
      const selection={start:editor.selectionStart,end:editor.selectionEnd,direction:editor.selectionDirection,top:editor.scrollTop,left:editor.scrollLeft};
      editor.setRangeText(addition,before.length,before.length,'preserve');
      editor.setSelectionRange(selection.start,selection.end,selection.direction);editor.scrollTop=selection.top;editor.scrollLeft=selection.left;
      editor.dispatchEvent(new Event('input',{bubbles:true}));
      status.textContent='已追加保存时备注；请核对结论并保存。';
    };
  }
  async function locate(e){
    if(active?.event_id!==e?.event_id&&globalThis.ECGReportRange?.pending?.().length&&!await ECGReportRange.resolveLeave())return;
    if(!e||reportCategoryOf(e)!==category||state.reportViewLoading||state.reportViewError||state.reportEvidenceLoading)return;
    active=e;const token=++waveToken,id=state.caseId,caseToken=state.caseRequestId,renderToken=reportRenderToken,viewCategory=category,scope=waveEvidenceScope,rateCandidates=['fastest','slowest'].includes(e.category),target=qs('#v2EventWave');
    const current=()=>token===waveToken&&id===state.caseId&&caseToken===state.caseRequestId&&renderToken===reportRenderToken&&viewCategory===category&&scope===waveEvidenceScope&&target===qs('#v2EventWave');
    document.querySelectorAll('[data-locate]').forEach(button=>{const current=reportData.items[Number(button.dataset.locate)]?.event_id===e.event_id;button.setAttribute('aria-current',String(current));button.closest('tr').dataset.preview=String(current)});
    const selectedRow=qs('[data-preview="true"]'),list=qs('.v2-event-list');
    if(selectedRow&&list){const row=selectedRow.getBoundingClientRect(),box=list.getBoundingClientRect(),header=list.querySelector('thead')?.getBoundingClientRect().height||0;
      if(row.top<box.top+header)list.scrollTop+=row.top-box.top-header;
      else if(row.bottom>box.bottom)list.scrollTop+=row.bottom-box.bottom;
    }
    const retainedNavigation=qs('#v2EventNavigation');if(retainedNavigation&&typeof target.contains==='function'&&typeof target.before==='function'&&target.contains(retainedNavigation))target.before(retainedNavigation);target._continuousObserver?.disconnect();target.classList.remove('report-continuous-readonly');qs('#v2EventWave').textContent='读取完整事件…';
    renderEventNavigation();
    try{
    const resumed=rangeResume?.event?.event_id===e.event_id&&rangeResume.basis===scope?rangeResume:null,pick=selectionForEvent(e),evidence=pick?selectedLookup.get(pick.event_id)||e:e;
    const resumeSpec=resumed?{...newStripSettings(e),duration_s:resumed.applied.b-resumed.applied.a,range_start_s:resumed.applied.a,range_end_s:resumed.applied.b}:null,entry=await reportStrip(evidence,resumeSpec||returnedRhythmSettings(e)||pick||newStripSettings(e),id);
    const wave=entry?entry.waveform:await eventWave(e,id);
    if(!current())return;
    qs('#v2EventWave').innerHTML=svg(wave,e);
    qs('#v2WaveLabel').textContent=`${e.label} · ${formatElapsed(wave.start_s)}–${formatElapsed(wave.start_s+wave.duration_s)} · ${entry?`${entry.strip.visible_beat_count} 搏 · ${entry.strip.warning||'按入报导联和时长预览'}`:`目标 ${e.beat_count} 搏 · 完整事件概览`}`;
    const savedResume=resumed&&selected().some(s=>stripKey(s)===resumed.stripKey),contextWave=await mountRange(qs('#v2EventWave'),e,entry,id,resumed?{stripKey:savedResume?resumed.stripKey:null,newStrip:!savedResume,draftKey:resumed.stripKey,role:resumed.representativeRole||'custom'}:{});if(current()&&resumed===rangeResume)rangeResume=null;
    const host=qs('#v2EventWave');if(current()){ECGReportWorkspace.mountEventPreview(host,{event:e,loadWave:()=>Promise.resolve(host._reportFullWave||contextWave||wave),renderWave:w=>ECGReportWorkspace.reviewWaveSvg(w,e,{displayProfile:host._reportDisplayProfile,pixelGain:Number(host.querySelector('.report-range-editor')?.dataset.displayGain)||null}),isCurrent:current});ECGReportWorkspace.bindWavePreview(host,host._rwOpenPreview,current);beatEditor.bindWaveSurface(host.querySelector('.report-range-stage')||host,{wave:contextWave||wave,isCurrent:current,onPreview:host._rwOpenPreview,readOnly:true});}
    if(current())renderEventNavigation(true);
    }catch(error){
      if(!current())return;
      qs('#v2EventWave').innerHTML='<p>事件波形读取失败，尚不能在此加入报告；可重试或继续核查下一条。</p><button type="button" id="v2RetryEventWave">重试当前波形</button>';
      qs('#v2WaveLabel').textContent=error.message;
      qs('#v2RetryEventWave').onclick=()=>run(()=>locate(e));renderEventNavigation();throw error;
    }
  }
  function hourlyMatrix(stats){
    const value=(row,key)=>key.split('.').reduce((item,part)=>item?.[part],row)??'—';
    const fields=['total','min_hr','max_hr','avg_hr','V.total','V.single','V.couplet','V.run','V.bigeminy','V.trigeminy','S.total','S.single','S.couplet','S.run','S.bigeminy','S.trigeminy','pause','pause_over3','af'];
    const row=(item,total=false)=>`<tr${total?' class="v2-hourly-total"':''}><th scope="row">${total?'合计':esc(item.label)}</th>${fields.map(key=>`<td>${esc(value(item,key))}</td>`).join('')}</tr>`;
    return `<div class="v2-hourly-scroll"><table class="v2-hourly-matrix"><caption>当前修订 · 全记录小时统计（心搏数／事件次数分列，选图不改变统计）</caption><thead><tr><th rowspan="2">时段</th><th rowspan="2">心搏数</th><th colspan="3">心率 bpm</th><th colspan="6">室性：总搏数／模式次数</th><th colspan="6">室上性：总搏数／模式次数</th><th colspan="2">长 RR 次数</th><th rowspan="2">已确认房颤/扑 次数</th></tr><tr>${['最低','最高','平均','总搏数','单发','成对','短阵','二联律','三联律','总搏数','单发','成对','短阵','二联律','三联律','>2.5秒','>3秒'].map(label=>`<th>${label}</th>`).join('')}</tr></thead><tbody>${(stats.hourly||[]).map(item=>row(item)).join('')}</tbody><tfoot>${row(stats.summary||{},true)}</tfoot></table></div><details class="v2-source-summary"><summary>统计口径</summary><p>${esc(stats.method||'未知统计口径')}</p><p>短记录按实际覆盖显示；未知值留空，模式可重叠，不与总搏数相加。</p></details>`;
  }
  async function loadHourlyStatistics(bodyCurrent){
    const target=qs('#reportHourlyStatistics'),id=state.caseId,scope=waveEvidenceScope;
    const current=()=>bodyCurrent()&&scope===waveEvidenceScope&&target?.isConnected&&target===qs('#reportHourlyStatistics');
    try{const stats=await endpoint('report-statistics',{...waveEvidence},id);if(!current())return;ECGAnalysisConsistency.assertSame(reportData,stats);target.innerHTML=hourlyMatrix(stats);const longest=stats.summary?.longest;if(longest){const row=document.createElement('p');row.className='rw-longest-measurement';row.textContent=`最长 RR ${longest.rr_ms} ms · ${formatElapsed(longest.time_s)} `;const b=document.createElement('button');b.type='button';b.dataset.reviewLongest='';b.textContent='查看波形 / 核对数值';b.onclick=()=>run(()=>reviewReportEvidence(null,'longest'));row.append(b);target.prepend(row);}}
    catch(error){if(!current())return;target.textContent='小时统计读取失败：'+error.message;const retry=document.createElement('button');retry.type='button';retry.textContent='重试小时统计';retry.onclick=()=>{if(current())run(()=>loadHourlyStatistics(bodyCurrent));};target.append(retry);}
  }
  function statsTable(){return `<table class="v2-stats"><caption>全部已确认结果统计（图条选择不改变统计）</caption><thead><tr><th>分类</th><th>事件次数</th><th>心搏数量</th></tr></thead><tbody>${reportCategories.map(([k,label])=>`<tr><td>${label}</td><td>${reportData?.confirmed_category_counts[k]??'—'}</td><td>${reportData?.confirmed_beat_counts[k]??'—'}</td></tr>`).join('')}</tbody></table><details class="v2-source-summary"><summary>源报告独立对照</summary><p>有效心搏 ${state.caseData.summary.total_beats??'—'} · 平均心率 ${state.caseData.summary.avg_hr??'—'} bpm · SDNN ${state.caseData.summary.sdnn_ms??'—'} ms</p></details>`;}
  function hrvTrendSvg(data){return `<svg class="v2-hrv-trend" viewBox="0 0 800 120" role="img" aria-label="逐小时SDNN趋势，空缺不连接">${data.hourly.map((r,i)=>{if(r.sdnn_ms===null)return '';const max=Math.max(1,...data.hourly.map(x=>x.sdnn_ms||0)),x=30+i*740/Math.max(1,data.hourly.length-1),y=100-r.sdnn_ms/max*80,prev=data.hourly[i-1];return (prev?.sdnn_ms!=null?`<path d="M${30+(i-1)*740/Math.max(1,data.hourly.length-1)} ${100-prev.sdnn_ms/max*80} L${x} ${y}" stroke="#0b7d7b"/>`:'')+`<circle cx="${x}" cy="${y}" r="3" fill="#0b7d7b"><title>${r.label} SDNN ${r.sdnn_ms} ms</title></circle>`}).join('')}</svg>`}
  function hrvRowsTable(rows){return `<table class="v2-stats v2-hrv-table"><thead><tr><th>时段</th><th>SDNN ms</th><th>RMSSD ms</th><th>pNN50 %</th><th>平均NN ms</th><th>有效 NN</th><th>覆盖 / 有效NN 秒</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.label)}</td>${['sdnn_ms','rmssd_ms','pnn50_pct','mean_nn_ms','nn_count'].map(k=>`<td>${r[k]??'—'}</td>`).join('')}<td>${r.coverage_s} / ${r.valid_nn_s}</td></tr>`).join('')}</tbody></table>`}
  function hrvWindowControl(data){return `<label>24 小时窗口<select class="v2-hrv-window">${Array.from({length:data.window_count},(_,i)=>`<option value="${i}" ${i===data.window_index?'selected':''}>第 ${i+1} 窗口</option>`).join('')}</select></label>`}
  function hrvHtml(data){const rows=[...Object.values(data.periods),...data.hourly];return `<p>${esc(data.method)} · 实际覆盖 ${(data.actual_duration_s/3600).toFixed(2)} 小时</p>${hrvWindowControl(data)}${hrvTrendSvg(data)}${hrvRowsTable(rows)}`;}
  function hrvReportPages(data){
    const rows=[...Object.values(data.periods),...data.hourly],paper=composition().paper||{},landscape=paper.orientation==='landscape',large=paper.size==='A3',pageCapacity=large?(landscape?15:24):(landscape?8:15),pages=[];
    for(let offset=0;offset<Math.max(1,rows.length);offset+=pageCapacity){const subset=rows.slice(offset,offset+pageCapacity),intro=offset===0?`<div class="v2-hrv-intro"><p>${esc(data.method)} · 实际覆盖 ${(data.actual_duration_s/3600).toFixed(2)} 小时</p>${hrvWindowControl(data)}</div>${hrvTrendSvg(data)}`:'';pages.push(paperShell(offset?'HRV 时域对照（续）':'HRV 时域对照',intro+hrvRowsTable(subset),'v2-hrv-paper'))}
    return pages.join('');
  }
  async function refreshHrvCase(id,caseToken,isCurrent,anchor=null){
    const privacyToken=state.privacyRequestId;
    const values=await ECGAnalysisConsistency.read(api,id,[basis=>api(withPhi(ECGAnalysisConsistency.url(id,'',{},basis)))],anchor);
    if(!isCurrent()||id!==state.caseId||caseToken!==state.caseRequestId)return false;
    const value=values[0];if(value.case_id!==id)throw Error('刷新返回的病例不一致');
    preserveCurrentIdentity(value,privacyToken);state.caseData=value;
    // These existing receivers preserve the version paired with a dirty draft.
    // Do not replace reportComposition, its window or the doctor's text here.
    ECGReportConsistency.receive(state,value.report_workflow);clinicalWorkflow.receive(value.review_workflow);
    beatEditor.refreshHistory?.();return true;
  }
  async function locateHrvBlock(block,context,id,caseToken,page){
    const valid=()=>context.isCurrent()&&id===state.caseId&&caseToken===state.caseRequestId&&page===state.currentPage;
    if(!valid())return;
    if(!Number.isSafeInteger(block.start_sample)||!Number.isSafeInteger(block.end_sample)||block.end_sample<=block.start_sample)throw Error('HRV 短段采样范围无效');
    const start=block.start_sample/200,end=block.end_sample/200;
    if(end-start<1){context.host.textContent='此末尾短段不足 1 秒，现有原始波形接口无法独立显示；未延伸或替换所选范围。';return;}
    let detailStart=start,detailToken=0;const maxStart=Math.max(start,end-10);
    const params=(a,b,points)=>({start:a,end:b,leads:'II,V1,V5',max_points:points,analysis:'edited',...context.scope});
    const validate=(wave,a,b)=>{
      ECGAnalysisConsistency.assertSame(context.scope,wave);
      if(!Number.isFinite(wave.start_s)||!Number.isFinite(wave.duration_s)||wave.duration_s<=0||wave.start_s<a-.005||wave.start_s+wave.duration_s>b+.005)throw Error('原始波形实际范围与所选 HRV 区间不一致');
      return wave;
    };
    const firstEnd=Math.min(end,start+10);
    const [overview,detail]=await ECGAnalysisConsistency.read(api,id,[basis=>endpoint('event-waveform',{...params(start,end,12000),...basis},id),basis=>endpoint('event-waveform',{...params(start,firstEnd,3000),...basis},id)],context.scope);
    if(!valid())return;validate(overview,start,end);validate(detail,start,firstEnd);
    context.host.innerHTML='<p>同一原始记录 · II / V1 / V5 · 设备单位；整段概览已抽样，逐搏复核请查看下方 10 秒细览。心搏标签来自当前修订，不自动证实窦性来源。</p><div data-hrv-wave-overview></div><div class="hrv-edit-actions"><button type="button" class="button secondary" data-hrv-wave-step="-1">前 10 秒</button><button type="button" class="button secondary" data-hrv-wave-step="1">后 10 秒</button><span data-hrv-wave-label></span></div><div data-hrv-wave-detail></div>';
    const overviewHost=context.host.querySelector('[data-hrv-wave-overview]'),detailHost=context.host.querySelector('[data-hrv-wave-detail]'),label=context.host.querySelector('[data-hrv-wave-label]');
    function paint(host,wave){
      const domain=ECGReviewTools.waveDomain(wave,JSON.stringify([id,context.scope.analysis_basis,context.scope.analysis_revision,'hrv-raw']));
      host.innerHTML=svg(wave,null,false,{domain,width:host.clientWidth||1000});
      ECGReportWorkspace.bindTwelveWave(host,{wave,domain,recordStart:state.caseData?.metadata?.start_time,isCurrent:()=>valid()&&host.isConnected,
        readWave:async()=>{const [full]=await ECGAnalysisConsistency.read(api,id,[basis=>endpoint('event-waveform',{...params(wave.start_s,wave.start_s+wave.duration_s,Math.max(3000,Object.values(wave.leads)[0].length)),leads:'I,II,III,aVR,aVL,aVF,V1,V2,V3,V4,V5,V6',...basis},id)],context.scope);return validate(full,wave.start_s,wave.start_s+wave.duration_s);}});
    }
    paint(overviewHost,overview);paint(detailHost,detail);
    const showRange=wave=>{label.textContent=`记录后 ${formatElapsedPrecise(wave.start_s)}–${formatElapsedPrecise(wave.start_s+wave.duration_s)}`;context.host.querySelectorAll('[data-hrv-wave-step]').forEach(button=>button.disabled=Number(button.dataset.hrvWaveStep)<0?detailStart<=start:detailStart>=maxStart);};showRange(detail);
    context.host.querySelectorAll('[data-hrv-wave-step]').forEach(button=>button.onclick=()=>run(async()=>{
      if(!valid()||button.disabled)return;const token=++detailToken,next=Math.max(start,Math.min(maxStart,detailStart+Number(button.dataset.hrvWaveStep)*10)),stop=Math.min(end,next+10);
      context.host.querySelectorAll('[data-hrv-wave-step]').forEach(b=>b.disabled=true);label.textContent='正在读取所选区间的原始细览…';
      try{const [wave]=await ECGAnalysisConsistency.read(api,id,[basis=>endpoint('event-waveform',{...params(next,stop,3000),...basis},id)],context.scope);if(!valid()||token!==detailToken)return;validate(wave,next,stop);detailStart=next;paint(detailHost,wave);showRange(wave);}catch(error){if(!valid()||token!==detailToken)return;detailHost.textContent='原始细览读取失败，请重新定位所选段后重试：'+error.message;label.textContent='读取未完成；未用邻近区间替代。';}
    }));
  }
  async function mountHrvReviewEditor(target,selector,windowIndex,id,caseToken,page,shellCurrent,viewCurrent,basis={}){
    if(!globalThis.ECGHRVEditor||!shellCurrent())return null;
    const host=document.createElement('section');host.className='hrv-review-editor-host';
    const legacy=selector==='#hrvWindowPanel'?hrvLegacyWeb:null,paper=target.querySelector('.hrv-paper-preview');
    if(legacy?.parentNode&&target.contains(legacy))legacy.before(host);else if(paper)paper.before(host);else target.append(host);
    const controller=ECGHRVEditor.mount(host,{id,basis,api,windowIndex,writable:clinicalWorkflow.writable(),isCurrent:()=>shellCurrent()&&viewCurrent(),
      onPendingChange:pending=>{const button=target.querySelector('[data-hrv-export]');if(button&&shellCurrent())button.disabled=Boolean(pending||state.privacySaving||state.privacyIdentityPending);},
      onLocate:(block,context)=>locateHrvBlock(block,context,id,caseToken,page),
      onSaved:async(saved)=>{
        if(!shellCurrent())return;
        try{if(!await refreshHrvCase(id,caseToken,shellCurrent,saved.scope))return;if(!shellCurrent())return;await loadHrv(selector,windowIndex);}
        catch(error){if(!shellCurrent())return;const continuous=target.querySelector('.hrv-continuous'),period=target.querySelector('.hrvr-review');if(continuous)continuous.textContent='HRV 区间修订已保存，整体证据刷新未完成。请重新读取；不能使用下列旧统计。';if(period)period.textContent='旧时段统计已停止显示，请重新读取。';const exportButton=target.querySelector('[data-hrv-export]');if(exportButton)exportButton.disabled=true;const pages=target.querySelector('.hrv-evidence-pages');if(pages)pages.textContent='HRV 修订已保存，整体证据刷新未完成；旧 A4 页面已停止显示，请重新读取。';const retry=document.createElement('button');retry.type='button';retry.className='button secondary';retry.textContent='重新读取已保存整体证据';retry.onclick=()=>run(async()=>{if(!shellCurrent())return;if(await refreshHrvCase(id,caseToken,shellCurrent))await loadHrv(selector,windowIndex)});(continuous||target).after(retry);throw error;}
      }});
    target._hrvEditor=controller;await controller.ready;return controller;
  }
  async function loadHrv(selector,windowIndex,preloaded=null){
    if(reportCase!==state.caseId){if(!state.reportDirty||!state.reportComposition)state.reportComposition={...copy(state.report?.composition||{}),schema_version:2};reportCase=state.caseId;reportVersion=state.report?.version;}
    windowIndex=windowIndex??composition().hrv_window??0;const token=++hrvToken,id=state.caseId,caseToken=state.caseRequestId,page=state.currentPage,target=qs(selector);if(!target)return;
    let loadedBasis=null;
    const shellCurrent=()=>token===hrvToken&&id===state.caseId&&caseToken===state.caseRequestId&&page===state.currentPage&&target.isConnected&&target===qs(selector);
    const current=()=>{if(!shellCurrent())return false;if(loadedBasis&&state.caseData?.clinical_identity){try{ECGAnalysisConsistency.assertSame(loadedBasis,state.caseData);}catch{return false;}}return true;};
    hrv=null;renderHrvTarget(target,'<p class="empty-state">计算 HRV 分段、频谱及趋势证据…</p>');
    try{
      const data=preloaded||(await ECGAnalysisConsistency.read(api,id,[basis=>endpoint('hrv-analysis',{window:windowIndex,...basis},id)]))[0];loadedBasis=ECGAnalysisConsistency.identity(data);if(!current())return;
      windowIndex=data.window_index;hrv=data;const model=paperModel({},data);model.report.status='draft';renderHrvTarget(target,ECGHrvReport.ui(model,data,composition().include_hrv));ECGReportPaper.number(target);
      if(state.privacySaving||state.privacyIdentityPending)target.querySelectorAll?.('.hrv-paper-preview .rp-running').forEach(header=>{const spans=header.querySelectorAll('span');if(spans[0])spans[0].textContent='患者 ID：身份更新中';if(spans[1])spans[1].textContent='姓名：身份更新中';});
      if(globalThis.ECGHrvReview){const evidenceHost=document.createElement('div');evidenceHost.className='hrv-review-host';target.querySelector('.hrv-evidence-notice')?.after(evidenceHost);ECGHrvReview.mount(evidenceHost,data,{isCurrent:current,scope:JSON.stringify([id,selector,windowIndex,data.start_s,data.end_s,data.data_version,data.analysis_basis,data.analysis_revision])});}
      bindHrvNavigation(target,current);
      target.querySelector('.v2-hrv-window').onchange=e=>run(async()=>{
        if(!current())return;const next=Number(e.target.value),editor=target._hrvEditor;
        if(editor?.pending()){if(editor.pendingDetails().busy){e.target.value=String(windowIndex);toast('HRV 正在读取或保存，请等待完成。','error');return;}if(!window.confirm('HRV 有尚未保存的区间修改。取消这些修改并切换窗口？')){e.target.value=String(windowIndex);return;}await editor.discard();if(!current())return;}
        state.reportComposition=composition();state.reportComposition.hrv_window=next;dirty();await (selector==='#hrvWindowPanel'?loadTrends(next):loadHrv(selector,next));
      });
      target.querySelector('[data-hrv-include]').onchange=e=>{if(!current())return;state.reportComposition=composition();state.reportComposition.include_hrv=e.target.checked;state.reportComposition.included_pages=state.reportComposition.included_pages.filter(k=>!k.startsWith('hrv_'));if(e.target.checked)state.reportComposition.included_pages.push('hrv_time','hrv_frequency','hrv_overview');dirty();toast(e.target.checked?'已加入主报告，请在报告页保存草稿':'已取消加入主报告，请保存草稿')};
      target.querySelector('[data-hrv-export]').disabled=Boolean(state.privacySaving||state.privacyIdentityPending);
      target.querySelector('[data-hrv-export]').onclick=()=>run(async()=>{
        if(!current())return;if(target._hrvEditor?.pending())throw Error('HRV 有尚未保存的区间修改，请先保存或取消后导出');
        const basis=ECGAnalysisConsistency.identity(data),privacyToken=state.privacyRequestId??0,review=data.hrv_review;
        const privacyGuard=()=>{if(state.privacySaving||state.privacyIdentityPending)throw Error('身份信息正在更新或尚未读取，请重试身份更新后重新导出');if(privacyToken!==(state.privacyRequestId??0))throw Error('身份显示状态已变化，请重新导出');};privacyGuard();
        if(!state.demoReadonly){const params={window:data.window_index,...(review?{expected_hrv_revision:review.hrv_revision,expected_hrv_digest:review.digest}:{})};const response=await fetch(ECGAnalysisConsistency.url(id,'hrv-report.pdf',params,basis));if(!current())return;privacyGuard();if(!response.ok){const problem=await response.json().catch(()=>({}));privacyGuard();throw Error(problem.error||'HRV 导出失败，请重新读取后重试');}const blob=await response.blob();if(!current())return;privacyGuard();const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=(typeof caseDisplayId==='function'?caseDisplayId(state.caseData):id)+'_HRV分析报告.pdf';link.click();setTimeout(()=>URL.revokeObjectURL(url),60000);return;}
        ECGAnalysisConsistency.assertSame(basis,await endpoint('analysis-basis',basis,id));if(!current())return;privacyGuard();const model=paperModel({},data);model.report.status='draft';await printHtml(ECGHrvReport.pages(model,data),'HRV 分析报告',()=>{privacyGuard();if(!current())throw Error('HRV 病例或窗口已变化，请重新读取后打印');});
      });
      await mountHrvReviewEditor(target,selector,windowIndex,id,caseToken,page,shellCurrent,current,data.hrv_review?.scope||loadedBasis);
    }catch(error){
      if(!shellCurrent())return;loadedBasis=null;
      renderHrvTarget(target,`<p class="rp-load-error">HRV 整体证据读取失败：${esc(error.message)}。可在区间复核中重新预览当前依据或重置排除范围。</p><button type="button" class="button secondary" data-hrv-retry>重新读取整体证据</button>`);
      target.querySelector('[data-hrv-retry]').addEventListener('click',()=>run(async()=>{if(!shellCurrent())return;if(await refreshHrvCase(id,caseToken,shellCurrent))await loadHrv(selector,windowIndex);}));
      await mountHrvReviewEditor(target,selector,windowIndex,id,caseToken,page,shellCurrent,shellCurrent,{});
      return {error};
    }
  }
  async function save(status='draft'){
    const options=arguments[1]||{};if(!options.automatic&&!await resolveWorkstationLeave())return;
    if(reportSavePromise)return reportSavePromise;const task=persistReport(status,options);reportSavePromise=task;
    try{return await task;}finally{if(reportSavePromise===task)reportSavePromise=null;}
  }
  async function persistReport(status,{automatic=false}={}){
    if(!automatic){globalThis.ECGAdvancedAnalysis?.assertApplied();globalThis.ECGHRVEditor?.assertApplied();ECGReportRange.assertApplied?.();}
    if(!clinicalWorkflow.writable())throw Error('当前服务为只读');
    if(state.reportSaving)return;
    if(state.reportStale)throw Error('病例或报告已有新版本，请先载入最新版本核对');
    if(status==='reviewed'&&(state.reportEvidenceLoading||state.reportEvidenceError||state.reportViewLoading||state.reportViewError))throw Error('请先完整读取当前报告依据与类别');
    if(status==='reviewed'&&state.reportDirty)throw Error('请先保存草稿，再审核当前版本');
    if(status==='reviewed'&&pendingRhythmPicks().length)throw Error('请先确认本次入报的房颤 / 房扑片段');
    const id=state.caseId,caseToken=state.caseRequestId,payload={status,expected_version:state.report.version,expected_review_revision:state.report.review_revision,conclusion:qs('#conclusionEditor').value,composition:copy(composition())};
    let submitted=ECGReportConsistency.content(payload.conclusion,payload.composition);
    state.reportSaving=true;renderReportShell();
    try{
      if(payload.composition.include_hrv||payload.composition.included_pages.some(k=>k.startsWith('hrv_'))){
        const review=await endpoint('hrv-review',{window:payload.composition.hrv_window||0,...ECGAnalysisConsistency.identity(state.caseData)},id);
        if(id!==state.caseId||caseToken!==state.caseRequestId)return;
        ECGAnalysisConsistency.assertSame(state.caseData,review.scope);
        if(review.document_stale)throw Error('HRV 排除范围来自旧依据，请先在 HRV 页面重新预览并应用');
        const reference={hrv_revision:review.hrv_revision,document_digest:review.digest,window_index:review.window_index,profile:review.profile,scope:review.scope};
        const oldReference=payload.composition.hrv_review_reference;
        if(status==='reviewed'&&(!oldReference||['hrv_revision','document_digest','window_index','profile'].some(k=>oldReference[k]!==reference[k])||Object.keys(reference.scope).some(k=>oldReference.scope?.[k]!==reference.scope[k])))throw Error('HRV 修订需要写入当前报告；请先保存草稿，再审核');
        payload.composition.hrv_review_reference=copy(reference);
        state.reportComposition=composition();state.reportComposition.hrv_review_reference=copy(reference);
        submitted=ECGReportConsistency.content(payload.conclusion,payload.composition);
      }
      if(!automatic)globalThis.ECGHRVEditor?.assertApplied();
      const result=await api(`/api/cases/${id}/report`,{method:'PUT',body:JSON.stringify(payload)});
      if(id!==state.caseId||caseToken!==state.caseRequestId)return;
      const changed=submitted!==ECGReportConsistency.content(qs('#conclusionEditor').value,composition());
      state.report=result;state.caseData.report_workflow=result;state.reportDirty=changed;state.reportStale=false;reportVersion=result.version;
      if(!changed)state.reportComposition=copy(result.composition);
      if(automatic){renderReportShell();if(qs('#reportSaveState'))qs('#reportSaveState').textContent=changed?'正在自动保存后续修改…':'已自动保存';if(changed)queueReportAutosave();return;}
      await clinicalWorkflow.refresh(id);await refreshReport();
      toast(globalThis.ECGAdvancedAnalysis?.pending()?'已保存提交时的版本；后续研究测量修改尚未应用':ECGReportRange.pending?.().length?'已保存提交时的版本；后续游标修改尚未应用':changed?'已保存提交时的版本；后续修改尚未保存':result.status==='reviewed'?'报告已审核':'报告已保存');
    }catch(error){
      if(id===state.caseId&&caseToken===state.caseRequestId){const remote=await endpoint('report',{},id).catch(()=>null);if(remote&&!ECGReportConsistency.sameBase(state.report,remote))state.reportStale=true;}
      throw error;
    }finally{if(id===state.caseId&&caseToken===state.caseRequestId){state.reportSaving=false;renderReportShell();}}
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
  function defaultStripSpec(){return reportCategories.some(([key])=>key===category)?newStripSettings({category}):ECGReportEngine.settings(composition().strip_defaults);}
  function defaultStripSummary(){const s=defaultStripSpec();return `新入报：${s.leads.length===12?'12 导联':s.leads.join(' / ')} · ${s.duration_s} 秒`;}
  function changeStripSettings(el){
    const scope=el.dataset.stripMode??el.dataset.stripLead??el.dataset.stripDuration;if(scope===undefined)return false;
    const holder=el.closest('[data-strip-settings]'),old=scope==='default'?defaultStripSpec():selected()[Number(scope)],spec=ECGReportEngine.settings(old);
    if(el.dataset.stripMode!==undefined){
      if(el.value==='custom'){holder.querySelector('fieldset').hidden=false;return true;}
      spec.leads=el.value==='all'?[...ECGReportEngine.leads]:[...ECGReportEngine.defaults];
    }else if(el.dataset.stripLead!==undefined)spec.leads=[...holder.querySelectorAll('[data-strip-lead]:checked')].map(x=>x.value);
    else {spec.duration_s=Number(el.value);delete spec.range_start_s;delete spec.range_end_s;}
    try{ECGReportEngine.settings(spec);}catch(error){if(el.type==='checkbox')el.checked=!el.checked;else el.value=old.duration_s||7;handleError(error);return true;}
    if(scope==='default'){if(reportCategories.some(([key])=>key===category)){state.reportComposition.strip_category_defaults={...(composition().strip_category_defaults||{}),[category]:spec};}else state.reportComposition.strip_defaults=spec;}else {if(el.dataset.stripDuration!==undefined){delete old.range_start_s;delete old.range_end_s;}Object.assign(selected()[Number(scope)],spec);}
    dirty();if(scope==='default'){holder.outerHTML=stripSettingsHtml(spec,scope);const summary=qs('.v2-candidate-settings>summary');if(summary)summary.textContent=defaultStripSummary();}else run(renderReportBody);return true;
  }
  async function reportStrip(e,selection,id=state.caseId,fresh=false){
    const scope=waveEvidenceScope,spec=ECGReportEngine.settings(selection),key=['report',scope,id,e.event_id,e.basis_version,JSON.stringify(spec)].join('|');
    if(fresh)reportWaveCache.delete(key);
    if(reportWaveCache.size>200)reportWaveCache.delete(reportWaveCache.keys().next().value);
    if(!reportWaveCache.has(key))reportWaveCache.set(key,endpoint('report-strip',{event_id:e.event_id,basis_version:e.basis_version,leads:spec.leads.join(','),duration:spec.duration_s,...waveEvidence,...('range_start_s' in spec?{range_start_s:spec.range_start_s,range_end_s:spec.range_end_s}:{})},id).catch(error=>{reportWaveCache.delete(key);throw error}));
    const result=await reportWaveCache.get(key);
    if(scope!==waveEvidenceScope)throw Error('波形依据已变化，请重新加载');
    return {...result,...ECGReportEngine.stripIdentity(selection),caption:selection.caption||e.label,...ECGReportStripEditor.curation(selection)};
  }
  async function editReportStrip(i,isCurrent=()=>true){
    const original=selected()[i],e=original&&selectedLookup.get(original.event_id),id=state.caseId,caseToken=state.caseRequestId;
    if(!original||!e||e.basis_version!==original.basis_version)throw Error('图条依据已失效，请重新选择');
    // An automatic save may replace equal selection objects. Match the actual
    // editable fields and source basis, while rejecting real concurrent edits.
    const signature=s=>JSON.stringify({stripKey:stripKey(s),event_id:s.event_id,basis_version:s.basis_version,caption:s.caption||e.label,...ECGReportEngine.settings(s),...ECGReportStripEditor.curation(s)}),originalSignature=signature(original);
    const liveIndex=()=>{const matches=selected().map((s,index)=>signature(s)===originalSignature?index:-1).filter(index=>index>=0);return matches.length===1?matches[0]:-1;};
    const current=()=>isCurrent()&&id===state.caseId&&caseToken===state.caseRequestId&&!state.reportStale&&liveIndex()>=0&&clinicalWorkflow.writable();
    await ECGReportStripEditor.open({selection:original,event:e,metadata:state.caseData.metadata,total:state.caseData.technical.duration_seconds_raw,isCurrent:current,
      loadWave:async(event,settings)=>{const entry=await reportStrip(event,settings,id,true);if(!current())throw Error('病例或报告已变化');return {...entry,waveform:await reportReviewWave(entry,id)};},
      onApply:async(next,{setDefaults})=>{if(!current())throw Error('报告已变化，本条未应用');const index=liveIndex();state.reportComposition.selected_events[index]=next;if(setDefaults)state.reportComposition.strip_defaults={leads:[...next.leads],duration_s:next.duration_s};dirty();await renderReportBody();}
    });
  }
  async function editNarrativeTemplates(isCurrent=()=>true){
    const id=state.caseId,caseToken=state.caseRequestId,editor=qs('#conclusionEditor');
    const current=()=>isCurrent()&&id===state.caseId&&caseToken===state.caseRequestId&&editor===qs('#conclusionEditor')&&clinicalWorkflow.writable();
    const stats=await endpoint('report-statistics',{...waveEvidence,pause_edges_ms:(composition().pause_edges_ms||[2500,3000,4000]).join(',')},id);
    if(!current())return;ECGAnalysisConsistency.assertSame(reportData,stats);
    ECGReportNarrative.open({templates:composition().narrative_templates,context:{caseData:state.caseData,statistics:stats},editor,isCurrent:current,onCommit:({templates,text,mode})=>{
      if(!current())throw Error('报告已变化，模板尚未应用');
      const next=text==null?editor.value:mode==='replace'?text:editor.value+(editor.value?'\n':'')+text;
      if(next.length>12000)throw Error('结论超过 12000 字，未写入');
      state.reportComposition=composition();state.reportComposition.narrative_templates=copy(templates);
      if(text!=null){editor.value=next;editor.dispatchEvent(new Event('input',{bubbles:true}));}dirty();
    }});
  }
  async function selectedReportWaves(id){
    const picks=copy(selected()),results=[];let next=0;
    await Promise.all(Array.from({length:Math.min(4,picks.length)},async()=>{while(next<picks.length){const i=next++,s=picks[i],e=selectedLookup.get(s.event_id);if(!e||e.basis_version!==s.basis_version)throw Error('请处理失效图条后再导出');results[i]=await reportStrip(e,s,id);}}));return results;
  }
  async function reportReviewWave(entry,id=state.caseId){
    const evidence={};for(const key of ['analysis_basis','analysis_revision'])if(entry[key]!==undefined)evidence[key]=entry[key];
    const source=entry.waveform,wave=await endpoint('waveform',{start:source.start_s,duration:source.duration_s,leads:'I,II,III,aVR,aVL,aVF,V1,V2,V3,V4,V5,V6',max_points:12000,filter:'raw',...evidence},id);
    if(Object.keys(evidence).some(key=>wave[key]!==evidence[key]))throw Error('12 导联依据已变化，请重新载入事件');
    if(ECGChartInspection.names(wave.leads).join(',')!=='I,II,III,aVR,aVL,aVF,V1,V2,V3,V4,V5,V6')throw Error('来源未提供完整 12 导联，不能补绘缺失导联');
    return wave;
  }
  function mountRhythmBrowser(target,holder,e,entry,wave,id,current,view){
    const a=e.start_sample/200,b=e.end_s,total=state.caseData.technical.duration_seconds_raw,recordStart=state.caseData.metadata.start_time;
    const clock=value=>ECGRhythmRangeEditor.boundaryClock(value,recordStart),center=Math.max(a,Math.min(b,wave.start_s+wave.duration_s/2)),span=b-a,reps=view.representatives;
    const nav=document.createElement('section');nav.className='rw-af-candidate-browse';nav.setAttribute('aria-label','房颤片段浏览与代表图条');
    const seconds=Number(view.stripDuration||entry.strip.duration_s||entry.strip.actual_duration_s||7),durations=[...new Set([7,10,15,30,60,seconds])].filter(n=>n>=1&&n<=120).sort((x,y)=>x-y);
    const count=selectionsForEvent(e).length;
    nav.innerHTML=`<div class="rw-af-whole"><strong>整段候选</strong><span>${esc(clock(a))} — ${esc(clock(b))} · ${span.toFixed(3)} 秒</span><b>${e.rhythm_status==='confirmed'?'已确认':'待确认'} · 已选 ${count} 图${reps?' · 推荐 '+reps.items.length+' 图':''}</b></div><div class="rw-af-strip" data-af-strip-summary role="status"></div><div class="rw-af-browse-controls"><button type="button" data-af-browse="start">段首</button><button type="button" data-af-browse="middle">段中${reps&&!reps.items.some(p=>p.representative_role==='middle')?' · 自选':''}</button><button type="button" data-af-browse="end">段末</button><button type="button" data-af-browse="strip">回图条</button><button type="button" data-af-browse="previous">‹ 前一屏</button><button type="button" data-af-browse="next">后一屏 ›</button><input type="range" data-af-position min="${a}" max="${b}" step="0.005" value="${center}" aria-label="在整段房颤候选内浏览"><label>图条 <select data-af-strip-duration aria-label="代表图条时长">${durations.map(n=>`<option value="${n}" ${n===seconds?'selected':''}>${n} 秒</option>`).join('')}</select></label><button type="button" data-af-use-view>自选此处</button><button type="button" data-af-include-current>${view.editPick?'保存本图':'入报本图'}</button></div><small data-af-browse-window>浏览窗口 ${esc(clock(wave.start_s))} — ${esc(clock(wave.start_s+wave.duration_s))}</small>`;
    holder.before(nav);target.dataset.afBrowseStart=String(wave.start_s);target.dataset.afEpisodeId=e.rhythm_episode_id||e.event_id;
    const caseToken=state.caseRequestId,scope=waveEvidenceScope,still=()=>state.caseId===id&&state.caseRequestId===caseToken&&scope===waveEvidenceScope&&target.isConnected&&active?.event_id===e.event_id,own=()=>current()&&still();
    async function navigate(at,role='custom',keep=false){
      if(!own())return;const displayState=holder._rangeDisplayState?.(),stripDuration=Number(nav.querySelector('[data-af-strip-duration]').value),ticket=(target._afBrowseRequest||0)+1;target._afBrowseRequest=ticket;
      let nextReps=reps;if(!keep&&(!nextReps||Number(nextReps.requested_duration_s||seconds)!==stripDuration)){nextReps=await endpoint('report-af-representatives',{event_id:e.event_id,duration:stripDuration,leads:newStripSettings(e).leads.join(','),...waveEvidence},id);if(!still()||target._afBrowseRequest!==ticket)return;}
      const position=!keep&&['start','middle','end'].includes(role)?nextReps?.positions?.[role]:null,lo=position?.start_s??Math.max(0,Math.min(total-stripDuration,at-stripDuration/2)),hi=position?.end_s??lo+stripDuration;
      const spec=keep?(view.editPick||entry.strip):{...newStripSettings(e),duration_s:hi-lo,range_start_s:lo,range_end_s:hi,representative_role:role};
      const fresh=await reportStrip(e,spec,id,true);if(!still()||target._afBrowseRequest!==ticket)return;
      const frameLength=Math.min(total,Math.max(15,hi-lo+2,stripDuration+2)),viewCenter=keep?at:(lo+hi)/2;
      const nextView={start:Math.max(0,Math.min(total-frameLength,viewCenter-frameLength/2)),length:frameLength,displayState,stripDuration,representatives:nextReps,newStrip:!keep||!view.editPick,role:keep?(view.role||entry.representative_role||'custom'):role,stripKey:keep?view.editPick&&stripKey(view.editPick):null,draftKey:keep?view.stripKey:undefined};
      const next=await mountRange(target,e,fresh,id,nextView);if(!next||!still())return;
      beatEditor.bindWaveSurface(target.querySelector('.report-range-stage')||target,{wave:next,isCurrent:still,onPreview:target._rwOpenPreview,readOnly:true});
    }
    nav.querySelectorAll('[data-af-browse]').forEach(button=>button.onclick=()=>run(()=>{const role=button.dataset.afBrowse,r=holder._rangeRead?.(),at=({start:a,middle:(a+b)/2,end:b,strip:r?(r.start+r.end)/2:center,previous:Math.max(a,center-wave.duration_s),next:Math.min(b,center+wave.duration_s)})[role];return navigate(at,role==='previous'||role==='next'?'custom':role,role==='strip');}));
    nav.querySelector('[data-af-position]').onchange=event=>run(()=>navigate(Number(event.target.value)));
    nav.querySelector('[data-af-strip-duration]').onchange=()=>run(()=>navigate(center,view.role||'custom'));
    nav.querySelector('[data-af-use-view]').onclick=()=>run(()=>navigate(center,'custom'));
    nav.querySelector('[data-af-include-current]').onclick=()=>run(async()=>{if(!own())return;const choice=target._afCurrentStrip?.();if(!choice)return;await addAFStrip(e,choice.settings,{replaceKey:choice.replaceKey,role:choice.role});if(still()){ECGReportRange.forget(choice.draftKey);await flushReportAutosave();}});
    return {update:value=>{if(!current())return;nav.querySelector('[data-af-strip-summary]').innerHTML=`<strong>本次图条</strong><span>${esc(clock(value.start))} — ${esc(clock(value.end))} · ${(value.end-value.start).toFixed(3)} 秒 · ${value.count==null?'搏数待核对':value.count+' 搏'} · 入报 ${entry.strip.leads.length} 导联</span><b>${value.changed?'待应用':value.inReport?'已入报':'尚未入报'}</b>`;}};
  }
  async function mountRange(target,e,entry,id=state.caseId,view={}){
    const holder=document.createElement('section'),token=waveToken,renderToken=reportRenderToken,viewCategory=typeof category==='undefined'?null:category,scope=waveEvidenceScope,caseToken=state.caseRequestId;
    const current=()=>holder.isConnected&&target.isConnected!==false&&state.caseId===id&&state.caseRequestId===caseToken&&token===waveToken&&renderToken===reportRenderToken&&viewCategory===(typeof category==='undefined'?null:category)&&scope===waveEvidenceScope;
    // Replace synchronously: an earlier request must never remove a newer editor.
    target.replaceChildren(holder);holder.textContent='正在读取入报区间上下文…';
    const evidence={};for(const key of ['analysis_basis','analysis_revision'])if(entry[key]!==undefined)evidence[key]=entry[key];
    const reviewTwelve=target.id==='v2EventWave',total=state.caseData.technical.duration_seconds_raw,padding=Math.max(0,Math.min(10,(120-entry.strip.actual_duration_s)/2));
    const isAF=reviewTwelve&&e.category==='AF',editPick=isAF?(view.newStrip?null:view.stripKey?selected().find(s=>stripKey(s)===view.stripKey&&s.event_id===e.event_id&&s.basis_version===e.basis_version):entry.strip_id?selected().find(s=>stripKey(s)===entry.strip_id):selectionForEvent(e)):selectionForEvent(e);
    const rangeKey=isAF?(editPick?stripKey(editPick):view.draftKey||['af-new',e.event_id,view.role||'custom',Math.round(entry.strip.start_s*200),Math.round(entry.strip.end_s*200)].join(':')):stripKey(entry)||e.event_id;
    view={...view,editPick,stripKey:rangeKey};
    const pendingRange=reviewTwelve?ECGReportRange.pending().find(d=>(d.stripKey||d.event?.event_id)===rangeKey&&d.basis===scope&&d.context===JSON.stringify([id,caseToken])):null;
    const sourceStart=Number(entry.waveform?.start_s??entry.strip.start_s),sourceEnd=entry.waveform?.duration_s!=null?sourceStart+Number(entry.waveform.duration_s):Number(entry.strip.end_s??(sourceStart+Number(entry.strip.actual_duration_s)));
    const neededStart=Math.min(sourceStart,Number(entry.strip.start_s??sourceStart),pendingRange?.a??sourceStart),neededEnd=Math.max(sourceEnd,Number(entry.strip.end_s??sourceEnd),pendingRange?.b??sourceEnd);
    const afBrowse=isAF,afCenter=pendingRange?(pendingRange.a+pendingRange.b)/2:(entry.strip.start_s+entry.strip.end_s)/2,displayLength=Math.min(total,afBrowse?Math.max(15,Number(view.length)||0,Number(view.stripDuration||entry.strip.actual_duration_s||7)+2):Math.max(15,Number(view.length)||0,neededEnd-neededStart+1)),centeredStart=Math.max(0,Math.min((afBrowse?afCenter:(neededStart+neededEnd)/2)-displayLength/2,total-displayLength)),displayStart=Number.isFinite(view.start)?afBrowse?Math.max(0,Math.min(view.start,total-displayLength)):Math.max(0,neededEnd-displayLength,Math.min(view.start,neededStart,total-displayLength)):centeredStart;
    const start=reviewTwelve?displayStart:Math.max(0,Math.min(entry.strip.start_s-padding,total-30)),duration=reviewTwelve?displayLength:Math.min(120,total-start,Math.max(30,entry.strip.end_s-start+padding));
    let wave;
    const reviewLeads=reviewTwelve?'I,II,III,aVR,aVL,aVF,V1,V2,V3,V4,V5,V6':entry.strip.leads.join(',');
    try{wave=await endpoint('waveform',{start,duration,leads:reviewLeads,filter:'raw',max_points:12000,...evidence},id);}
    catch(error){if(!current())return;holder.textContent='入报上下文读取失败，请重新选择此事件后重试。';throw error;}
    if(!current())return;
    if(Object.keys(evidence).some(key=>wave[key]!==evidence[key])){holder.textContent='入报依据已变化，请重新载入事件后复核。';throw Error(holder.textContent);}
    if(reviewTwelve&&ECGChartInspection.names(wave.leads).join(',')!==reviewLeads){holder.textContent='来源未提供完整 12 导联，请核对原始数据；未补绘导联。';throw Error(holder.textContent);}
    async function apply(range){
      if(!current())throw Error('事件或病例已变化，请重新选择入报区间');
      const existing=afBrowse?editPick:selectionForEvent(e),spec={...ECGReportEngine.settings(existing||entry.strip)};
      delete spec.range_start_s;delete spec.range_end_s;if(range){Object.assign(spec,range);if(e.category==='AF')spec.duration_s=range.range_end_s-range.range_start_s;}else spec.duration_s=7;
      // Applying a clinical selection must revalidate remotely, even on a cache hit.
      await reportStrip(e,spec,id,true);if(!current())throw Error('波形已切换，区间尚未应用；请返回待应用区间重试');
      if(afBrowse){await addAFStrip(e,spec,{replaceKey:editPick&&stripKey(editPick),role:view.role||entry.representative_role||'custom'});ECGReportRange.forget?.(rangeKey);return;}
      ECGReportRange.forget?.(rangeKey);
      if(returnedRhythmSelection(e)){replaceRhythmSelection(e,spec);renderReportShell();await renderReportBody();}
      else if(existing){delete existing.range_start_s;delete existing.range_end_s;Object.assign(existing,spec);dirty();await renderReportBody();}
      else await selectEvent(e,true,spec);
    }
    target.classList?.toggle('report-af-browser',afBrowse);target.closest?.('.v2-event-detail')?.classList.toggle('report-af-detail',afBrowse);
    let rangeEvidence=null;if(afBrowse&&pendingRange&&(pendingRange.a<wave.start_s||pendingRange.b>wave.start_s+wave.duration_s)){try{const checked=await reportStrip(e,{...ECGReportEngine.settings(entry.strip),duration_s:pendingRange.b-pendingRange.a,range_start_s:pendingRange.a,range_end_s:pendingRange.b},id,true);rangeEvidence={start:pendingRange.a,end:pendingRange.b,count:checked.strip.visible_beat_count};}catch(_){rangeEvidence={start:pendingRange.a,end:pendingRange.b,count:null};}if(!current())return;}
    if(afBrowse&&!view.representatives){view.representatives=await endpoint('report-af-representatives',{event_id:e.event_id,duration:Math.min(120,Number(view.stripDuration||entry.strip.duration_s||7)),leads:newStripSettings(e).leads.join(','),...waveEvidence},id);if(!current())return;ECGAnalysisConsistency.assertSame(entry,view.representatives);}
    const rhythmBrowser=afBrowse?mountRhythmBrowser(target,holder,e,entry,wave,id,current,view):null;
    const displayProfile=reviewTwelve?ECGReviewTools.reportAmplitude(wave):null;
    if(reviewTwelve){target._reportDisplayProfile=displayProfile;target._reportFullWave=wave;}
    ECGReportRange.mount(holder,{...entry,inReport:!!editPick},wave,range=>apply(range),()=>apply(null),{context:JSON.stringify([id,caseToken]),basis:scope,event:copy(e),stripKey:rangeKey,representativeRole:view.role||entry.representative_role||'custom',columns:1,displayProfile,fitToFrame:reviewTwelve,displayState:view.displayState,rangeEvidence,onRangeChange:rhythmBrowser?.update,rowHeight:innerHeight<800?64:112,displayLeads:['II','V1','V5'],recordStart:state.caseData?.metadata?.start_time});
    if(afBrowse){holder.querySelector('[data-range-apply]').hidden=true;holder.querySelector('[data-range-reset]').hidden=true;}
    if(afBrowse){target._afCurrentStrip=()=>{const range=holder._rangeRead?.()||{start:entry.strip.start_s,end:entry.strip.end_s};return {event_id:e.event_id,basis_version:e.basis_version,draftKey:rangeKey,replaceKey:editPick&&stripKey(editPick),role:view.role||entry.representative_role||'custom',settings:{...(editPick||newStripSettings(e)),duration_s:range.end-range.start,range_start_s:range.start,range_end_s:range.end}};};target.dataset.afStripKey=rangeKey;}
    if(view.chooseRange)holder._rangeChooseRange?.(view.chooseRange);
    if(reviewTwelve){
      holder.classList.add('rw-twelve-range');
      const label=document.createElement('small');label.className='rw-review-lead-note';label.textContent=`显示 ${wave.duration_s.toFixed(3)} 秒 · ${wave.sample_rate_hz} Hz · 步进 ${ECGReviewTools.sampleStride(wave)} · 入报 ${entry.strip.leads.join(' / ')}`;label.title='默认三导联复核；3L / 12L 只改变查看方式，不改已入报导联或时间。原始采样保持，电压未校准。';
      const toolbar=document.createElement('div');toolbar.className='rw-main-range-toolbar';toolbar.setAttribute('aria-label','入报区间操作');toolbar.append(...['.report-display-controls','[data-range-apply]','[data-range-cancel]','[data-range-reset]','.range-precision'].map(selector=>holder.querySelector(selector)).filter(Boolean));holder.querySelector('header').replaceWith(toolbar);toolbar.after(label);
      const stage=holder.querySelector('.report-range-stage');stage.setAttribute('aria-description','单击波形定位只读复核；双击具体波形打开 12 导联。入报使用左侧表行、勾选或加入报告草稿按钮。');
      if(!afBrowse){
      const contextPanel=document.createElement('section');contextPanel.className='rw-candidate-context';contextPanel.setAttribute('aria-label','连续波形定位');contextPanel.innerHTML='<header><strong>连续定位 · II</strong><span>正在读取前后波形…</span></header><div data-context-wave></div>';holder.after(contextPanel);
      async function loadContext(){
        try{
          const length=Math.min(60,total),contextStart=Math.max(0,Math.min((neededStart+neededEnd-length)/2,total-length)),key=JSON.stringify([id,scope,contextStart,length]);
          let contextWave=target._reportContextCache?.key===key?target._reportContextCache.wave:await endpoint('waveform',{start:contextStart,duration:length,leads:'II',max_points:12000,filter:'raw',...evidence},id);
          if(!current()||!contextPanel.isConnected)return;
          if(Object.keys(evidence).some(k=>contextWave[k]!==evidence[k]))throw Error('定位波形依据已变化，请重选事件');
          target._reportContextCache={key,wave:contextWave};const surface=contextPanel.querySelector('[data-context-wave]'),profile=ECGReviewTools.reportAmplitude(contextWave,['II']);
          contextPanel.querySelector('header span').textContent=`${ECGReviewTools.clockLabel(state.caseData?.metadata?.start_time,contextWave.start_s)} — ${ECGReviewTools.clockLabel(state.caseData?.metadata?.start_time,contextWave.start_s+contextWave.duration_s)}`;
          const paint=()=>{if(!current()||!surface.isConnected)return;const width=surface.clientWidth||1000;surface.innerHTML=ECGOccurrenceCard.svg(contextWave,e,{width,height:54,inset:0,annotations:'none',rowHeight:54,displayProfile:profile,reportPreview:true});const svg=surface.querySelector('svg'),box=document.createElementNS('http://www.w3.org/2000/svg','rect');for(const [k,v] of Object.entries({'data-context-window':'true',x:(wave.start_s-contextWave.start_s)/contextWave.duration_s*width,y:1,width:wave.duration_s/contextWave.duration_s*width,height:52,fill:'none',stroke:'#cb7b1c','stroke-width':1.5}))box.setAttribute(k,v);svg.append(box);};
          surface.tabIndex=0;surface.setAttribute('role','slider');surface.setAttribute('aria-label','前后波形定位；保持当前入报区间可见');surface.setAttribute('aria-valuemin',String(contextWave.start_s));surface.setAttribute('aria-valuemax',String(contextWave.start_s+contextWave.duration_s));surface.setAttribute('aria-valuenow',String(wave.start_s+wave.duration_s/2));surface.title='点击或按左右方向键调整复核窗口；已入报区间保持可见';
          let navigating=false;const navigate=async start=>{if(navigating||!current())return;navigating=true;const full=await mountRange(target,e,entry,id,{start});if(full&&target.isConnected&&state.caseId===id)beatEditor.bindWaveSurface(target.querySelector('.report-range-stage')||target,{wave:full,isCurrent:()=>target.isConnected&&state.caseId===id&&state.caseRequestId===caseToken,onPreview:target._rwOpenPreview,readOnly:true});};
          surface.onclick=event=>{const r=surface.getBoundingClientRect();run(()=>navigate(contextWave.start_s+(event.clientX-r.left)/r.width*contextWave.duration_s-wave.duration_s/2));};
          surface.onkeydown=event=>{if(['ArrowLeft','ArrowRight'].includes(event.key)){event.preventDefault();run(()=>navigate(wave.start_s+(event.key==='ArrowLeft'?-1:1)*(event.shiftKey?5:1)));}};
          paint();if(typeof ResizeObserver!=='undefined'){const observer=new ResizeObserver(()=>{if(!surface.isConnected){observer.disconnect();return;}paint();});observer.observe(surface);}
        }catch(error){if(current()&&contextPanel.isConnected){contextPanel.querySelector('header span').textContent='定位波形读取失败：'+error.message;const retry=document.createElement('button');retry.type='button';retry.textContent='重试定位波形';retry.onclick=()=>{retry.remove();loadContext();};contextPanel.append(retry);}}
      }
      loadContext();
      }
    }
    if(e.category==='ST'&&typeof e.note==='string'&&e.note.trim())mountSavedSTNote(target,e,current);
    return wave;
  }
  function renderRangeDraftNotice(){
    const anchor=qs('#reportV2Notice');if(!anchor)return;
    let host=qs('#reportRangeDraftNotice');if(!host){host=document.createElement('section');host.id='reportRangeDraftNotice';host.setAttribute('aria-label','待应用游标区间');anchor.after(host);}host.className='v2-range-draft-bar';
    const drafts=ECGReportRange.pending?.()||[];host.hidden=!drafts.length;if(!drafts.length)return;
    const currentSelections=typeof state!=='undefined'&&state.reportComposition?state.reportComposition.selected_events||[]:null;
    const first=drafts[0],stamp=ECGReportRange.formatTime,applied=first.applied||{},included=currentSelections?currentSelections.some(s=>s.event_id===first.event?.event_id&&s.basis_version===first.event?.basis_version):applied.inReport,pendingTime=stamp?`${stamp(first.a)} — ${stamp(first.b)}`:'',appliedTime=included&&stamp?`${stamp(applied.a)} — ${stamp(applied.b)}`:'此事件尚未入报';
    host.innerHTML=`<div class="v2-range-draft-summary" role="status"><strong>${drafts.length} 处待应用区间</strong><span>${pendingTime}</span><small>当前已应用区间：${appliedTime} · 切换前可应用或放弃本次修改${drafts.length>1?' · 显示第 1 处':''}</small></div><div class="v2-review-actions"><button type="button" data-range-resume>回到草稿</button><button type="button" data-range-discard>放弃修改</button></div>`;
    host.querySelector('[data-range-resume]').onclick=()=>run(async()=>{const d=ECGReportRange.pending()[0];if(!d)return;if(d.basis!==waveEvidenceScope)throw Error('待应用区间的依据已变化，不能套用旧范围；请放弃后按新波形重新选择');rememberReportView();rangeResume=d;activeStripKey=d.stripKey||d.event.event_id;category=reportCategoryOf(d.event);reportMode=d.event.subtype;reportOffset=0;reportTimeRange=null;pauseBand='all';await refreshReport({viewOnly:true,focusEvent:d.event});focusEventNavigation();});
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
      basis=>api(withPhi(C.url(id,'',{},basis))),basis=>endpoint('report-statistics',{...basis,pause_edges_ms:(composition().pause_edges_ms||[2500,3000,4000]).join(',')},id),
      async basis=>{const items=await selectedReportWaves(id);items.forEach(item=>C.assertSame(basis,item));return {...basis,items};},
      basis=>hrvForReport(id,basis),basis=>sectionsForReport(id,basis),
    ]);
    return {caseData,statistics,entries:waves.items,hrvData,evidence};
  }
  function paperModel(statistics,hrvData=null,evidence=null){return {case:state.caseData,statistics,hrv:hrvData,evidence,report:{...state.report,...(state.reportDirty?{status:'draft',reviewed_by:'',preview_unsaved:true}:{}),conclusion:qs('#conclusionEditor')?.value??state.report?.conclusion,composition:composition()}};}
  async function previewPaper(){
    if(!await resolveWorkstationLeave())return;
    globalThis.ECGAdvancedAnalysis?.assertApplied();globalThis.ECGHRVEditor?.assertApplied();
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
      globalThis.ECGAdvancedAnalysis?.assertApplied();globalThis.ECGHRVEditor?.assertApplied();ECGReportRange.assertApplied?.();
      if(state.reportStale||state.reportSaving||reportContext!==JSON.stringify([state.report?.version,state.report?.review_revision,state.report?.status]))throw Error('预览期间报告版本或审核状态已变化，请关闭后重新预览');
      if(content!==ECGReportConsistency.content(qs('#conclusionEditor')?.value,composition()))throw Error('预览期间编排已修改，请关闭后重新预览');
      const body=dialog.querySelector('.rp-pages');body.innerHTML=ECGReportPaper.render({...paperModel(statistics,hrvData,evidence),case:caseData},entries);ECGReportPaper.number(body);
    }catch(error){if(id!==state.caseId||caseToken!==state.caseRequestId||token!==reportRenderToken||!dialog.open)return;const body=dialog.querySelector('.rp-pages');body.textContent='预览失败：'+error.message;const retry=document.createElement('button');retry.type='button';retry.textContent='重试 A4 预览';retry.onclick=()=>{dialog.close();run(previewPaper)};body.append(retry);throw error;}
  }
  async function print(){
    if(!await resolveWorkstationLeave())return;
    globalThis.ECGAdvancedAnalysis?.assertApplied();globalThis.ECGHRVEditor?.assertApplied();
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
    const guard=()=>{globalThis.ECGAdvancedAnalysis?.assertApplied();globalThis.ECGHRVEditor?.assertApplied();ECGReportRange.assertApplied?.();privacyGuard();if(id!==state.caseId||caseToken!==state.caseRequestId||state.reportDirty||state.reportSaving||state.reportStale||version!==state.report.version||reviewRevision!==state.report.review_revision)throw Error('报告已变化，请重新保存后打印');};
    guard();
    await printHtml(ECGReportPaper.render({...paperModel(statistics,hrvData,evidence),case:caseData},entries),id+' 心电报告',guard);
  }
  async function downloadReport(){
    if(!await resolveWorkstationLeave())return;
    globalThis.ECGAdvancedAnalysis?.assertApplied();globalThis.ECGHRVEditor?.assertApplied();
    ECGReportRange.assertApplied?.();
    const privacyToken=state.privacyRequestId??0,privacyGuard=()=>{if(state.privacySaving||state.privacyIdentityPending)throw Error('身份信息正在更新或尚未读取，请重试身份更新后重新导出');if(privacyToken!==(state.privacyRequestId??0))throw Error('身份显示状态已变化，请重新导出');};privacyGuard();
    if(state.reportExportJob)return;
    if(state.demoReadonly)return print();
    if(state.reportDirty||state.reportSaving)throw Error('请先保存草稿再导出');
    if(state.reportStale)throw Error('请先载入最新报告版本核对后导出');
    cancelReportExport();
    const id=state.caseId,caseToken=state.caseRequestId,version=state.report.version,reviewRevision=state.report.review_revision;
    const job={id,caseToken,controller:new AbortController()};state.reportExportJob=job;renderExportState();
    const guard=()=>{globalThis.ECGAdvancedAnalysis?.assertApplied();globalThis.ECGHRVEditor?.assertApplied();ECGReportRange.assertApplied?.();privacyGuard();if(id!==state.caseId||caseToken!==state.caseRequestId||state.reportDirty||state.reportSaving||state.reportStale||version!==state.report.version||reviewRevision!==state.report.review_revision)throw Error('导出期间报告已变化，请重新核对并保存后导出');};
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
    const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=(typeof caseDisplayId==='function'?caseDisplayId(state.caseData):id)+'_心电分析复核报告.pdf';
    // WebKit can ignore a detached anchor or an async automatic download. Keep
    // an attached, guarded link so a user gesture can save the same verified PDF.
    link.className='button secondary report-file-ready';link.textContent='保存已生成 PDF';
    link.addEventListener('click',event=>{try{guard();}catch(error){event.preventDefault();cancelReportExport();handleError(error);}});
    const file={url,link};state.reportDownload=file;qs('#downloadReport').after(link);link.click();
    file.timer=setTimeout(()=>{if(state.reportDownload===file){URL.revokeObjectURL(url);link.remove();delete state.reportDownload;}},60000);
    }catch(error){if(job.controller.signal.aborted)return;throw error;}
    finally{if(state.reportExportJob===job){state.reportExportJob=null;renderExportState();}}
  }
  function renderExportState(){
    const busy=Boolean(state.reportExportJob),button=qs('#downloadReport'),cancel=qs('#cancelReportExport');
    const saving=Boolean(state.reportSaving),saveButton=qs('#saveReport');
    if(saveButton){saveButton.hidden=true;saveButton.disabled=saving||!clinicalWorkflow.writable()||Boolean(state.reportStale);saveButton.textContent=saving?'正在保存…':'保存草稿';saveButton.setAttribute('aria-busy',String(saving));}
    if(button){button.disabled=busy||saving||Boolean(state.privacySaving||state.privacyIdentityPending);button.textContent=busy?'正在导出 PDF…':'导出 PDF';button.setAttribute('aria-busy',String(busy||saving||Boolean(state.privacySaving||state.privacyIdentityPending)));button.title=saving?'草稿正在保存，完成后可导出':'';}
    if(cancel)cancel.hidden=!busy;
  }
  function cancelReportExport(notify=false){
    const file=state.reportDownload;if(file){clearTimeout(file.timer);URL.revokeObjectURL(file.url);file.link.remove();delete state.reportDownload;}
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
    qs('#conclusionEditor')?.addEventListener('input',()=>queueReportAutosave());
    document.addEventListener('ecg-report-range-change',()=>{if(state.report)renderReportShell();else renderRangeDraftNotice();});
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
    // Core report actions expose their own state; no preflight panel is mounted.
    root.addEventListener('click',event=>{const b=event.target.closest('button');if(!b||b.disabled)return;if(b.dataset.reviewRhythm!==undefined)run(()=>openRhythmReview(b.dataset.reviewRhythm));if(b.dataset.confirmRhythm!==undefined){const pick=b.dataset.confirmRhythm==='active'?null:selected()[Number(b.dataset.confirmRhythm)];run(()=>confirmReportRhythm(pick?selectedLookup.get(pick.event_id):active,pick));}if(b.hasAttribute('data-rhythm-replace'))run(replaceReturnedRhythm);});
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
    const trends=qs('#page-trends');hrvLegacyWeb=document.createElement('section');hrvLegacyWeb.id='hrvWholeRecordReference';hrvLegacyWeb.tabIndex=-1;hrvLegacyWeb.style.scrollMarginTop='68px';hrvLegacyWeb.className='hrv-legacy-reference';hrvLegacyWeb.setAttribute('aria-label','全记录参考与源报告对照');
    hrvLegacyWeb.innerHTML='<h2>全记录参考与源报告对照</h2><p>以下全天趋势、N-N 分布与源报告对照覆盖全记录，不随上方 24 小时窗口切换；不替代当前窗口的统计。</p>';
    for(const node of [qs('#trendMetrics'),trends.querySelector(':scope > .chart-grid')])if(node)hrvLegacyWeb.append(node);
    h.append(hrvLegacyWeb);trends.append(h);
    document.querySelectorAll('[data-page="events"],[data-workflow-page="events"]').forEach(el=>el.hidden=true);
    if(state.caseId&&state.currentPage==='edit')run(loadOccurrences);
  }
  document.addEventListener('ecg-evidence-candidates-changed',event=>{if(event.detail?.case_id===state.caseId&&state.currentPage==='report'&&!state.reportSaving)run(()=>refreshReport());});
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
  return {insertWaveStrip,printWaveStrip,async showSTReport(receipt=null){if(!await resolveWorkstationLeave())return;const eventId=receipt?.event_id||receipt?.record_id||(receipt?.id?'annotation:'+receipt.id:null);sttReportFocus=eventId?{caseId:state.caseId,caseToken:state.caseRequestId,eventId}:null;category='ST';sttGroup='all';reportMode='all';reportOffset=0;reportTimeRange=null;if(state.currentPage==='report')return refreshReport();goPage('report');},showAFCandidates,refreshCurrentCaseEvidence:refreshHrvCase,receiveCandidateState,showRRCandidates(){if(state.currentPage==='report')return chooseReportCategory('rr_candidate');category='rr_interval';rrSource='manual';reportSort='hr_asc';reportMode='all';reportOffset=0;reportTimeRange=null;goPage('report');},reviewReportEvidence,showReportStrips(){if(state.currentPage==='report')return chooseReportCategory('strips');category='strips';reportMode='all';reportOffset=0;ECGReportWorkspace.setReviewFilter('all');goPage('report');},setRRDestination(){category='rr_interval';rrSource='manual';reportSort='hr_asc';reportMode='all';reportOffset=0;reportTimeRange=null;},includeRRCandidate,queueReportAutosave,flushReportAutosave,resolveReportLeave,setPauseEdges(edges){state.reportComposition=composition();state.reportComposition.pause_edges_ms=ECGOverviewEngine.pauseEdges(edges);dirty();},linkedContext,focusLinkedBeat,setLinkedChecked,prepareHrvLoad,refreshPrivacyViews,cancelReportExport,hasRhythmReturn,returnFromRhythm,captureEditView,activateEditView,occurrenceBookmark,currentOccurrenceBookmark,loadOccurrences,renderOccurrences,releaseOccurrenceWaves,refreshReport,renderReportShell,loadHrv,save,print,applyVoltageEstimate,addStrip(e,settings=null){category='strips';return selectEvent(e,true,settings)}};
})();
// Replace representative-only loaders; preserve existing continuous-waveform editor tools.
loadEditTemplateStrips=clinicalUI.loadOccurrences;
renderEditGallery=clinicalUI.renderOccurrences;
loadReport=clinicalUI.refreshReport;
renderReport=clinicalUI.renderReportShell;
saveReport=clinicalUI.save;
printReportPreview=clinicalUI.print;
const loadTrendsLegacy=loadTrends;
loadTrends=async windowIndex=>{clinicalUI.prepareHrvLoad();const id=state.caseId,caseToken=state.caseRequestId,page=state.currentPage;let loaded;try{loaded=await loadTrendsLegacy(windowIndex);}catch(error){if(id===state.caseId&&caseToken===state.caseRequestId&&page===state.currentPage)await clinicalUI.loadHrv('#hrvWindowPanel',windowIndex);return;}if(loaded&&loaded.caseId===state.caseId&&loaded.caseToken===state.caseRequestId&&loaded.requestId===state.trendsRequestId)await clinicalUI.loadHrv('#hrvWindowPanel',windowIndex,loaded.data)};
const goPageLegacy=goPage;
let reportLeaveToken=0,reportLeaveBusy=false;
goPage=function(name,options={}){
  if(reportLeaveBusy||globalThis.ECGUnsavedNavigation?.isOpen())return false;
  if(!options.unsavedResolved&&name!==state.currentPage&&((globalThis.ECGReportRange?.pending().length)||globalThis.ECGAdvancedAnalysis?.pending()||globalThis.ECGHRVEditor?.pending()||overviewWorkbench.hasUnsaved?.())){
    const id=state.caseId,token=state.caseRequestId,navigation=++reportLeaveToken;
    resolveWorkstationLeave().then(ok=>{if(ok&&id===state.caseId&&token===state.caseRequestId&&navigation===reportLeaveToken)goPage(name,{...options,unsavedResolved:true});}).catch(handleError);return false;
  }
  if(name==='rr'){name='report';clinicalUI.setRRDestination();}
  if(state.currentPage==='report'&&!['report','events'].includes(name)&&(state.reportDirty||state.reportSaving)&&!options.reportAutosaveFlushed){const id=state.caseId,token=state.caseRequestId,navigation=++reportLeaveToken;reportLeaveBusy=true;clinicalUI.resolveReportLeave().then(ok=>{reportLeaveBusy=false;if(ok&&id===state.caseId&&token===state.caseRequestId&&navigation===reportLeaveToken)goPage(name,{...options,reportAutosaveFlushed:true});}).catch(handleError).finally(()=>{reportLeaveBusy=false;});return false;}
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

const markReportCompositionDirtyBeforeAutosave=markReportCompositionDirty;
markReportCompositionDirty=function(message){markReportCompositionDirtyBeforeAutosave(message);if(state.reportDirty)clinicalUI.queueReportAutosave();};
