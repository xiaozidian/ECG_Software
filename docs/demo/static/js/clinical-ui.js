"use strict";
/* Shared workstation UI. Selection for editing and selection for reporting are independent. */
const clinicalUI=(()=>{
  const A=ECGClinicalAnalysis,esc=escapeHtml,qs=s=>document.querySelector(s);
  const copy=x=>JSON.parse(JSON.stringify(x));
  const tabs=[...A.categories,['tables','数据表格'],['strips','报告图条'],['final','报告']];
  let occurrenceToken=0,reportToken=0,waveToken=0,editCase=null,occurrence=null,editMode='all',template='all',type='N',pageCache=new Map(),waveCache=new Map(),tileWidth=150,editTimeTimer=0;
  let reportCase=null,reportVersion=null,category='fastest',reportOffset=0,reportMode='all',reportSort='hr_desc',reportData=null,selectedLookup=new Map(),active=null,hrv=null,hrvToken=0;
  const run=fn=>Promise.resolve().then(fn).catch(handleError);
  const endpoint=(kind,params={},id=state.caseId)=>api(`/api/cases/${id}/${kind}?${new URLSearchParams(params)}`);
  const selected=()=>state.reportComposition?.selected_events||[];
  let reportRenderToken=0;
  function composition(){
    const source=state.reportComposition||state.report?.composition||{};
    return {...source,schema_version:2,selected_events:source.selected_events||[],category_reviews:source.category_reviews||{},diagnosis_blocks:source.diagnosis_blocks||[],fast_slow_mode:source.fast_slow_mode||'rr',paper:{...(source.paper||{}),size:'A4',orientation:'portrait'},strip_defaults:ECGReportEngine.settings(source.strip_defaults)};
  }
  function dirty(){state.reportDirty=true;if(qs('#reportSaveState'))qs('#reportSaveState').textContent='有未保存修改';}
  function svg(wave,event=null,compact=false){
    const leads=Object.entries(wave.leads||{}),width=1000,row=compact?70:125,height=Math.max(1,leads.length)*row;
    return `<svg viewBox="0 0 ${width} ${height}" ${compact?'preserveAspectRatio="none"':''} role="img" aria-label="${esc(event?.label||'心电波形')}，${wave.duration_s}秒"><defs><pattern id="grid-${compact?'s':'l'}" width="25" height="25" patternUnits="userSpaceOnUse"><path d="M 25 0 L 0 0 0 25" fill="none" stroke="#d9e4e6" stroke-width=".5"/></pattern></defs><rect width="100%" height="100%" fill="url(#grid-${compact?'s':'l'})"/>${leads.map(([name,values],j)=>{const mid=j*row+row/2,max=Math.max(50,...values.map(v=>Math.abs(v))),scale=(row*.4)/max;return `<text x="4" y="${j*row+14}" font-size="13">${esc(name)}</text><polyline fill="none" stroke="#244f59" stroke-width="1.2" points="${values.map((v,i)=>`${(i/(values.length-1||1)*width).toFixed(2)},${(mid-v*scale).toFixed(2)}`).join(' ')}"/>`}).join('')}${(event?.target_samples||[]).map(s=>{const x=(s/200-wave.start_s)/wave.duration_s*width;return x>=0&&x<=width?`<path d="M${x.toFixed(2)} 0 V${height}" stroke="#bd663d" stroke-opacity=".35"/>`:''}).join('')}</svg>`;
  }
  async function eventWave(e,id=state.caseId,leads='II,V1,V5'){
    const start=Math.max(0,e.start_sample/200-.8),end=e.end_sample/200+1.6,key=[id,e.basis_version,e.event_id,leads].join('|');
    if(waveCache.size>200)waveCache.delete(waveCache.keys().next().value);
    if(!waveCache.has(key))waveCache.set(key,endpoint('event-waveform',{start,end,leads,max_points:1200},id).catch(error=>{waveCache.delete(key);throw error}));
    return waveCache.get(key);
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
    type=code;editMode=mode;template=String(templateId);state.editSelectedClass='source-'+code;
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
    const code=state.editSelectedClass?.startsWith('source-')?state.editSelectedClass.slice(7):type;
    if(code!==type){type=code;editMode='all';template='all';}
    const choices=Object.entries(ECGBeatEngine.types||{});
    host.innerHTML=`<div class="occurrence-template-tools"><label>搜索模板<input id="occSearch" type="search" placeholder="模板名称，如 S1"></label><label>形态模板<select id="occTemplate"></select></label></div><div class="occurrence-current-filter"><span>当前筛选</span><strong>${esc(typeNames[type]||ECGBeatEngine.types[type]?.name||type)} · ${esc(modeLabel())}</strong></div><div class="edit-type-dock" role="group" aria-label="左下角心搏类型与事件模式">${['N','S','V','other'].map(k=>`<button type="button" id="editType${k}" data-occ-type="${k}" aria-haspopup="menu" aria-expanded="false" aria-controls="editTypeMenu" aria-label="${k==='other'?'其他类型':k+' '+typeNames[k]+'类型'}" aria-pressed="${k===type||(k==='other'&&!['N','S','V'].includes(type))}"><strong>${k==='other'?'其他':k}</strong><span>${typeNames[k]||'类型'}</span><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4"/></svg></button>`).join('')}</div><div hidden><select id="occType" aria-label="心搏类型">${choices.map(([k,t])=>`<option value="${k}" ${type===k?'selected':''}>${k} ${esc(t.name)}</option>`).join('')}</select><select id="occMode" aria-label="事件模式">${modeChoices(type).map(([k,v])=>`<option value="${k}" ${editMode===k?'selected':''}>${esc(v)}</option>`).join('')}</select></div>`;
    updateTemplates();
    host.querySelectorAll('[data-occ-type]').forEach(button=>button.onclick=()=>openTypeMenu(button));
    qs('#occType').onchange=e=>chooseFilter(e.target.value);
    qs('#occMode').onchange=e=>chooseFilter(type,e.target.value);
    qs('#occTemplate').onchange=e=>{state.editSelectedSamples=new Set();template=e.target.value;run(loadOccurrences)};
    qs('#occSearch').oninput=updateTemplates;
  }
  function updateTemplates(){
    const select=qs('#occTemplate');if(!select)return;
    const search=qs('#occSearch').value.toLowerCase();
    const matches=(state.editTemplates||[]).filter(t=>(t.source_class==='source-'+type||String(t.id)===template)&&(t.name.toLowerCase().includes(search)||String(t.id)===template));
    select.innerHTML='<option value="all">全部模板</option>'+matches.map(t=>`<option value="${t.id}" ${String(t.id)===template?'selected':''}>${esc(t.name)} · ${t.beat_count??t.sample_indices.length}</option>`).join('');
  }
  function editParams(offset=0){return {class_code:type,mode:editMode,template_id:template,offset,limit:48}}
  async function loadOccurrences(){
    if(!state.caseId)return;
    if(editCase!==state.caseId){editCase=state.caseId;editMode='all';template='all';pageCache.clear();waveCache.clear();}
    const token=++occurrenceToken,id=state.caseId;pageCache.clear();occurrence=null;filters();
    qs('#editTemplateGallery').innerHTML='<p class="empty-state">读取完整出现记录…</p>';
    try{const result=await endpoint('template-occurrences',editParams(),id);if(token!==occurrenceToken||id!==state.caseId)return;occurrence=result;pageCache.set(0,result.items);qs('#editTemplateGallery').scrollLeft=0;renderOccurrences();await loadMorphology(result.items,token,id);}
    catch(error){if(token===occurrenceToken)qs('#editTemplateGallery').innerHTML=`<p class="empty-state">加载失败：${esc(error.message)}。请重新选择筛选条件重试。</p>`;throw error;}
  }
  async function loadMorphology(items,token,id){
    const samples=[...new Set(items.flatMap(e=>e.target_samples))].slice(0,24);
    if(!samples.length){state.editTemplateStrips=[];renderEditDensity();return;}
    const result=await api(`/api/cases/${id}/waveform-strips`,{method:'POST',body:JSON.stringify({sample_indices:samples,leads:[state.editLead||'II'],pre_s:.4,post_s:.8,max_points:240,filter:'display'})});
    if(token!==occurrenceToken||id!==state.caseId)return;
    state.editTemplateStrips=result.items;renderEditDensity();
    if(typeof overviewWorkbench==='undefined')qs('#editMorphologyCount').textContent=`当前批次 ${result.items.length} 搏`;
  }
  function renderOccurrences(){
    const host=qs('#editTemplateGallery');if(!host||!occurrence)return;
    host.classList.add('occurrence-viewport');const total=occurrence.total;const previousWidth=tileWidth;tileWidth=Math.max(90,host.clientWidth/6);if(previousWidth!==tileWidth&&host.scrollLeft)host.scrollLeft=Math.floor((host.scrollLeft+1)/previousWidth)*tileWidth;
    const first=Math.max(0,Math.floor((host.scrollLeft+1)/tileWidth)*2),last=Math.min(total,first+14),token=occurrenceToken,id=state.caseId;
    syncEditTimeSlider();
    qs('#editGalleryTitle').textContent=`${type} · ${modeLabel()} · 全部出现记录`;
    qs('#editGalleryDescription').textContent='勾选审核目标心搏；报告入选在报告页单独完成';
    qs('#editGalleryCount').textContent=`${total?first+1:0}–${Math.min(total,Math.ceil((host.scrollLeft+host.clientWidth-1)/tileWidth)*2)} / ${total}`;
    if(!total){host.innerHTML='<p class="empty-state">0 条匹配记录</p>';return;}
    let lane=host.querySelector('.occurrence-lane');if(!lane){host.innerHTML='<div class="occurrence-lane"></div>';lane=host.firstElementChild;}
    lane.style.width=Math.ceil(total/2)*tileWidth+'px';lane.innerHTML='';
    for(let n=first;n<last;n++){
      const offset=Math.floor(n/48)*48,items=pageCache.get(offset);
      if(!items){if(!pageCache.has(offset)){pageCache.set(offset,null);endpoint('template-occurrences',editParams(offset),id).then(result=>{if(token!==occurrenceToken||id!==state.caseId)return;if(result.data_version!==occurrence.data_version){loadOccurrences().catch(handleError);return;}pageCache.set(offset,result.items);renderOccurrences();loadMorphology(result.items,token,id).catch(handleError)}).catch(error=>{if(token===occurrenceToken){pageCache.delete(offset);qs('#editGalleryCount').textContent='加载失败，请重试';handleError(error)}});}continue;}
      const e=items[n-offset];if(!e)continue;
      const card=document.createElement('div');card.className='occurrence-tile';card.style.cssText=`left:${Math.floor(n/2)*tileWidth}px;top:${n%2*126}px;width:${tileWidth-6}px`;
      card.innerHTML=`<button type="button" class="occurrence-open" aria-label="定位第${n+1}条 ${esc(e.label)}"><strong>${formatElapsed(e.time_s)}</strong><span class="occurrence-wave">读取波形…</span></button><label><input type="checkbox" aria-label="选择第${n+1}条审核目标" ${e.target_samples.every(s=>state.editSelectedSamples.has(s))?'checked':''}>${esc(e.templates.map(t=>t.name).join('/')||type)} · ${e.beat_count}搏</label><small>${esc(e.label)} · ${e.diagnosis_status==='edited'?'已修订':e.diagnosis_status==='confirmed'?'已确认':'待审核'}</small>`;
      card.querySelector('button').onclick=()=>{state.editSelectedSample=e.sample_index;setEditStart(Math.max(0,e.time_s-2));renderEditScatter();};
      card.querySelector('input').onchange=ev=>{e.target_samples.forEach(s=>ev.target.checked?state.editSelectedSamples.add(s):state.editSelectedSamples.delete(s));state.editSelectedSample=e.sample_index;renderEditScatter();};
      card.onkeydown=ev=>{if([' ','ArrowLeft','ArrowRight'].includes(ev.key)){ev.stopPropagation();if(ev.key!==' '){ev.preventDefault();host.scrollLeft+=(ev.key==='ArrowLeft'?-1:1)*tileWidth;}}};lane.appendChild(card);
      eventWave(e,id,[state.editLead||'II',...['II','V1','V5'].filter(l=>l!==(state.editLead||'II'))].slice(0,3).join(',')).then(w=>{if(token===occurrenceToken&&card.isConnected)card.querySelector('.occurrence-wave').innerHTML=svg(w,e,true)}).catch(()=>{if(card.isConnected)card.querySelector('.occurrence-wave').textContent='波形读取失败';});
    }
  }
  async function refreshReport(){
    if(!state.caseId||!state.report)return;
    const id=state.caseId,token=++reportToken;++waveToken;
    if(reportCase!==id||(!state.reportDirty&&reportVersion!==state.report.version)){
      state.reportComposition={...copy(state.report.composition||{}),schema_version:2};reportCase=id;reportVersion=state.report.version;selectedLookup.clear();
    }
    state.reportComposition=composition();renderReportShell();
    qs('#reportV2Content').innerHTML='<p class="empty-state">读取已确认结果…</p>';
    try{
      const data=await endpoint('report-events',{category:A.categories.some(([k])=>k===category)?category:'all',mode:reportMode,offset:reportOffset,limit:50,sort:reportSort,fast_slow_mode:composition().fast_slow_mode},id);
      if(token!==reportToken||id!==state.caseId)return;
      reportData=data;data.items.forEach(e=>selectedLookup.set(e.event_id,e));
      for(let i=0;i<selected().length;i+=100){const result=await endpoint('report-events',{ids:selected().slice(i,i+100).map(e=>e.event_id).join('|'),limit:200},id);if(token!==reportToken||id!==state.caseId)return;result.items.forEach(e=>selectedLookup.set(e.event_id,e));}
      const before=JSON.stringify(composition().diagnosis_blocks);syncText();if(before!==JSON.stringify(composition().diagnosis_blocks))dirty();
      renderReportShell();await renderReportBody();
    }catch(error){if(token===reportToken)qs('#reportV2Content').innerHTML=`<p class="empty-state">加载失败：${esc(error.message)}。不能据此认定无事件。</p><button id="reportRetry" class="button secondary">重新加载</button>`;qs('#reportRetry')?.addEventListener('click',()=>run(refreshReport));throw error;}
  }
  function syncText(){
    const c=state.reportComposition,keys=new Map();selected().forEach(s=>{const e=selectedLookup.get(s.event_id);if(e&&e.basis_version===s.basis_version)keys.set(e.category+':'+e.subtype,e.label)});
    const blocks=[];for(const b of c.diagnosis_blocks||[]){if(keys.has(b.key)){blocks.push(b);keys.delete(b.key);}else if(b.manual)blocks.push({...b,needs_review:!b.acknowledged});}
    keys.forEach((text,key)=>blocks.push({key,text,manual:false,needs_review:false,acknowledged:false}));c.diagnosis_blocks=blocks;
  }
  function selectEvent(e,checked){
    const c=state.reportComposition;selectedLookup.set(e.event_id,e);
    c.selected_events=c.selected_events.filter(s=>s.event_id!==e.event_id);
    if(checked)c.selected_events.push({event_id:e.event_id,basis_version:e.basis_version,caption:e.label,...ECGReportEngine.settings(c.strip_defaults)});
    delete c.category_reviews[e.category];c.diagnosis_blocks.forEach(b=>{if(b.key===e.category+':'+e.subtype)b.acknowledged=false});syncText();dirty();renderReportShell();run(renderReportBody);
  }
  function enableReportDraftSelections(items){
    document.querySelectorAll('[data-include]').forEach(control=>{const e=items[Number(control.dataset.include)];if(!e)return;const confirmed=e.diagnosis_status==='confirmed',status=control.closest('tr')?.querySelector('small');control.disabled=false;control.title=confirmed?'加入报告':'可先加入报告草稿；最终审核前需完成诊断确认';control.setAttribute('aria-label',`${formatElapsed(e.time_s)} ${e.label}${confirmed?'加入报告':'加入报告草稿（待诊断确认）'}`);if(status&&!confirmed)status.textContent=`${e.beat_count} 搏 · 待诊断确认，可先入草稿`});
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
  function diagnosisBlocksHtml(){return composition().diagnosis_blocks.map((b,i)=>`<label class="v2-text-block">${esc(b.key)}${b.needs_review?' · 依据已移除，请核对':''}<textarea data-block="${i}" rows="2">${esc(b.text)}</textarea>${b.needs_review?`<button data-ack="${i}" type="button">已核对，保留人工文字</button>`:''}</label>`).join('')||'<p class="empty-state">当前没有诊断文字块。</p>'}
  function renderReportShell(){
    if(!qs('#reportV2'))return;
    qs('#reportV2Nav').innerHTML=tabs.map(([key,label])=>{const count=reportData?.category_counts[key],countSelected=selected().filter(s=>selectedLookup.get(s.event_id)?.category===key).length;return `<button type="button" data-category="${key}" class="${category===key?'active':''}" aria-current="${category===key?'page':'false'}">${label}${count===undefined?'':`<small>${countSelected} / ${count}</small>`}</button>`}).join('');
    qs('#reportStatus').textContent=STATUS_TEXT[state.report.status]||state.report.status;qs('#reportVersion').textContent='v'+state.report.version;
    if(!state.reportDirty){qs('#conclusionEditor').value=state.report.conclusion||'';qs('#reportSaveState').textContent=state.report.updated_at?'已保存 '+state.report.updated_at:'尚未保存';updateConclusionCount();}
    qs('.report-conclusion-dock').hidden=category!=='final';
    const stale=selected().filter(s=>!selectedLookup.has(s.event_id)||selectedLookup.get(s.event_id).basis_version!==s.basis_version).length;
    qs('#reportV2Notice').textContent=`已选 ${selected().length} 条图条 · 统计包含当前全部结果${clinicalWorkflow.readiness()?"（已诊断确认）":"；待确认候选可先加入草稿，最终审核前须完成诊断确认"}${stale?' · '+stale+'条已失效，请移除后重新筛选':''}`;
    if(qs('#approveReport'))qs('#approveReport').disabled=state.reportDirty||!clinicalWorkflow.readiness();
  }
  async function renderReportBody(){
    const host=qs('#reportV2Content');if(!host||!reportData)return;
    if(category==='tables'){host.innerHTML=statsTable()+'<div id="reportHrvV2"></div>';await loadHrv('#reportHrvV2');return;}
    if(category==='strips'||category==='final'){
      const token=++reportRenderToken,id=state.caseId;
      if(category==='final'){
        host.innerHTML='<div class="rp-entry-settings"><strong>A4 纵向报告</strong>'+gainHtml()+'<span>三导联每页三张；4–6 导联占两行；7–12 导联独占一页。修改导联与时间请到“报告图条”。</span></div><div id="rpFinalPages" class="rp-pages" aria-live="polite">正在排版报告…</div>';
        try{const [statistics,entries]=await Promise.all([endpoint('report-statistics',{},id),selectedReportWaves(id)]);
          if(token!==reportRenderToken||id!==state.caseId)return;
          const target=qs('#rpFinalPages');if(!target)return;target.innerHTML=ECGReportPaper.render(paperModel(statistics),entries);ECGReportPaper.number(target);
        }catch(error){if(token===reportRenderToken&&qs('#rpFinalPages'))qs('#rpFinalPages').innerHTML='<p class="rp-load-error">报告读取失败：'+esc(error.message)+'。请重新打开报告重试，当前不可据此导出。</p>';throw error;}return;
      }
      host.innerHTML=stripSettingsHtml(composition().strip_defaults,'default')+'<div id="v2TextBlocks">'+diagnosisBlocksHtml()+'</div>'+selected().map((s,i)=>{const e=selectedLookup.get(s.event_id),valid=e&&e.basis_version===s.basis_version;return `<article class="rp-editor-strip"><header><strong>${i+1}. ${esc(e?.label||s.event_id)}${valid?'':'（已失效）'}</strong><div><button data-back-event="${i}">回看</button><button data-move="${i}" data-delta="-1" aria-label="图条上移" ${i===0?'disabled':''}>上移</button><button data-move="${i}" data-delta="1" aria-label="图条下移" ${i===selected().length-1?'disabled':''}>下移</button><button data-remove="${i}">移除</button></div></header><label>图注<input data-caption="${i}" value="${esc(s.caption)}" maxlength="500"></label>${stripSettingsHtml(s,String(i))}<div data-selected-wave="${i}">${valid?'读取波形…':'图条已失效，请重新筛选'}</div><p class="rp-strip-status" data-strip-status="${i}" aria-live="polite"></p></article>`}).join('')+(selected().length?'':'<p class="empty-state">尚未选择图条。在事件列表设置导联后勾选“入报”；也可以在这里修改每条图的导联与时长。</p>');
      await Promise.all(selected().map(async(s,i)=>{const e=selectedLookup.get(s.event_id),target=host.querySelector(`[data-selected-wave="${i}"]`);if(!e||e.basis_version!==s.basis_version)return;try{const entry=await reportStrip(e,s,id);if(token===reportRenderToken&&target?.isConnected){target.innerHTML=ECGReportPaper.stripSvg(entry,composition().paper,s.leads?.length>6?880:s.leads?.length>3?520:276);host.querySelector(`[data-strip-status="${i}"]`).textContent=`${formatElapsed(entry.waveform.start_s)}–${formatElapsed(entry.waveform.start_s+entry.waveform.duration_s)} · ${entry.strip.visible_beat_count} 搏 · ${entry.strip.warning||'时间窗满足至少 5 搏'}`;}}catch(error){if(target?.isConnected)target.textContent='读取失败：'+error.message;}}));return;
    }
    const complete=composition().category_reviews[category]===reportData.basis_versions[category],items=reportData.items,rateCandidates=['fastest','slowest'].includes(category);
    const pageCount=Math.max(1,Math.ceil(reportData.total/50));
    host.innerHTML=`<div class="v2-category-bar"><strong>${Object.fromEntries(tabs)[category]} · ${reportData.total} 条${rateCandidates?'候选':''}</strong>
      <label>亚型<select id="v2Subtype"><option value="all">${rateCandidates?'全部序列':'全部（不叠加模式计数）'}</option>${Object.entries(reportData.subtype_counts).map(([k,n])=>`<option value="${k}" ${reportMode===k?'selected':''}>${esc(Object.fromEntries(A.patterns)[k]||k)} · ${n}</option>`).join('')}</select></label>
      ${rateCandidates?`<label>计算序列<select id="v2Fast"><option value="rr">RR</option><option value="nn">NN</option><option value="both">RR 与 NN</option></select></label><label>心率排序<select id="v2RateSort"><option value="hr_desc" ${reportSort==='hr_desc'?'selected':''}>从快到慢</option><option value="hr_asc" ${reportSort==='hr_asc'?'selected':''}>从慢到快</option></select></label>`:''}
      <button class="button ${complete?'secondary':'primary'}" id="v2Complete" ${!reportData.category_counts[category]?'disabled':''}>${complete?'本类筛选已完成':'本类筛选完成（可全部不选）'}</button></div>
      ${rateCandidates?'<p class="v2-rate-help">RR / NN 单间期瞬时心率候选，非 7 秒平均心率。每序列最多 200 条，短记录按实显示；相邻候选可能重叠，请回看原始波形后入报。</p>':''}
      <div class="v2-event-layout"><div class="v2-event-list"><table><thead><tr><th>${rateCandidates?'序号 / 时间':'时间'}</th><th>${rateCandidates?'候选心率 / RR':'模板 / 亚型'}</th><th>入报</th></tr></thead><tbody>${items.map((e,i)=>`<tr data-preview="false"><td>${rateCandidates?`<span class="v2-candidate-rank">第 ${reportOffset+i+1} 条</span>`:''}<button data-locate="${i}" aria-current="false">${formatElapsed(e.time_s)}</button></td><td>${rateCandidates?`<strong class="v2-candidate-rate">${e.hr} bpm</strong><div>${esc(e.subtype)} · ${e.rr_ms} ms</div>`:`${esc(e.templates.map(t=>t.name).join('/')||'—')}<br>${esc(e.label)}`}<small>${e.beat_count} 搏 · ${e.diagnosis_status==='confirmed'?'已确认':'待诊断确认'}</small></td><td><input type="checkbox" data-include="${i}" aria-label="${formatElapsed(e.time_s)} ${esc(e.label)}入报" ${selected().some(s=>s.event_id===e.event_id&&s.basis_version===e.basis_version)?'checked':''}></td></tr>`).join('')||'<tr><td colspan="3">0 条匹配记录</td></tr>'}</tbody></table>
      <footer><button id="v2Prev" ${reportOffset===0?'disabled':''}>上一页</button><span>${reportData.total?reportOffset+1:0}–${reportOffset+items.length} / ${reportData.total}</span>${rateCandidates?`<label>页码<select id="v2ReportPage" aria-label="候选页码">${Array.from({length:pageCount},(_,i)=>`<option value="${i}" ${i===Math.floor(reportOffset/50)?'selected':''}>${i+1} / ${pageCount}</option>`).join('')}</select></label>`:''}<button id="v2Next" ${reportOffset+items.length>=reportData.total?'disabled':''}>下一页</button></footer></div>
      <div class="v2-event-detail"><div class="v2-distribution">${Object.entries(reportData.subtype_counts).map(([k,n])=>`<span>${esc(Object.fromEntries(A.patterns)[k]||k)} <b>${n}</b></span>`).join('')}<small>${rateCandidates?'RR：有效相邻心搏间期；NN：连续正常心搏且在设置范围内。这里只提供选图候选，不替代医生确认。':'连续搏数与重复节律为重叠标签，不能相加'}</small></div><div id="v2TimeDistribution"></div><div id="v2EventWave"><p class="empty-state">点击左侧事件查看完整波形</p></div><input id="v2Time" type="range" min="0" max="${state.caseData.technical.duration_seconds_raw}" step=".1" aria-label="事件连续波形时间导航"><small id="v2WaveLabel"></small></div></div>`;
    host.insertAdjacentHTML('afterbegin',stripSettingsHtml(composition().strip_defaults,'default'));
    enableReportDraftSelections(items);
    qs('#v2Subtype').onchange=e=>{reportMode=e.target.value;reportOffset=0;run(refreshReport)};
    if(qs('#v2Fast')){qs('#v2Fast').value=composition().fast_slow_mode;qs('#v2Fast').onchange=e=>{reportOffset=0;reportMode='all';state.reportComposition.fast_slow_mode=e.target.value;state.reportComposition.selected_events=selected().filter(s=>{const item=selectedLookup.get(s.event_id);return !item||!['fastest','slowest'].includes(item.category)||e.target.value==='both'||item.subtype===e.target.value.toUpperCase()});syncText();delete state.reportComposition.category_reviews.fastest;delete state.reportComposition.category_reviews.slowest;dirty();run(refreshReport)}}
    if(qs('#v2RateSort'))qs('#v2RateSort').onchange=e=>{reportSort=e.target.value;reportOffset=0;run(refreshReport)};
    if(qs('#v2ReportPage'))qs('#v2ReportPage').onchange=e=>{reportOffset=Number(e.target.value)*50;run(refreshReport)};
    qs('#v2Complete').onclick=()=>{state.reportComposition.category_reviews[category]=reportData.basis_versions[category];dirty();renderReportBody().catch(handleError)};
    qs('#v2Prev').onclick=()=>{reportOffset=Math.max(0,reportOffset-50);run(refreshReport)};qs('#v2Next').onclick=()=>{reportOffset+=50;run(refreshReport)};
    qs('#v2Time').oninput=e=>run(()=>detailWindow(Number(e.target.value)));
    const bins=reportData.time_counts||{},max=Math.max(1,...Object.values(bins));qs("#v2TimeDistribution").innerHTML=Array.from({length:Math.max(1,Math.ceil(state.caseData.technical.duration_seconds_raw/3600))},(_,i)=>`<span style="height:${(bins[i]||0)/max*50}px" title="记录第 ${i+1} 小时：${bins[i]||0} 次"></span>`).join("");
    if(items.length)await locate(items.find(e=>e.event_id===active?.event_id)||items[0]);
  }
  async function locate(e){
    active=e;const token=++waveToken,id=state.caseId,rateCandidates=['fastest','slowest'].includes(e.category);
    document.querySelectorAll('[data-locate]').forEach(button=>{const current=reportData.items[Number(button.dataset.locate)]?.event_id===e.event_id;button.setAttribute('aria-current',String(current));button.closest('tr').dataset.preview=String(current)});
    qs('#v2EventWave').textContent='读取完整事件…';
    const entry=rateCandidates?await reportStrip(e,selected().find(s=>s.event_id===e.event_id)||composition().strip_defaults,id):null;
    const wave=entry?entry.waveform:await eventWave(e,id);
    if(token!==waveToken||id!==state.caseId||!qs('#v2EventWave'))return;
    qs('#v2EventWave').innerHTML=svg(wave,e);qs('#v2Time').value=wave.start_s;
    qs('#v2WaveLabel').textContent=`${e.label} · ${formatElapsed(wave.start_s)}–${formatElapsed(wave.start_s+wave.duration_s)} · ${entry?`${entry.strip.visible_beat_count} 搏 · ${entry.strip.warning||'按入报导联和时长预览'}`:`目标 ${e.beat_count} 搏 · 完整事件概览`}`;
  }
  async function detailWindow(start){const token=++waveToken,id=state.caseId,wave=await endpoint('waveform',{start,duration:10,leads:'II,V1,V5',max_points:2400},id);if(token!==waveToken||id!==state.caseId||!qs('#v2EventWave'))return;qs('#v2EventWave').innerHTML=svg(wave,active);qs('#v2WaveLabel').textContent=`连续波形 ${formatElapsed(wave.start_s)} · 10 秒`;}
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
  async function loadHrv(selector,windowIndex=composition().hrv_window||0){const token=++hrvToken,id=state.caseId,data=await endpoint('hrv-windows',{window:windowIndex},id);if(token!==hrvToken||id!==state.caseId||!qs(selector))return;hrv=data;const target=qs(selector),paperPreview=selector==='#finalHrvV2';target.innerHTML=paperPreview?hrvReportPages(data):hrvHtml(data);target.querySelector('select').onchange=e=>{state.reportComposition=composition();state.reportComposition.hrv_window=Number(e.target.value);if(state.currentPage==='report')dirty();run(()=>loadHrv(selector,Number(e.target.value)))};if(paperPreview){updateReportPaper(qs('#reportV2Content'));renumberReportPapers(qs('#reportV2Content'))}}
  async function save(status='draft'){
    if(!clinicalWorkflow.writable())throw Error('当前服务为只读');
    if(status==='reviewed'&&state.reportDirty)throw Error('请先保存草稿，再审核当前版本');
    const id=state.caseId,result=await api(`/api/cases/${id}/report`,{method:'PUT',body:JSON.stringify({status,expected_version:state.report.version,conclusion:qs('#conclusionEditor').value,composition:composition()})});
    if(id!==state.caseId)return;state.report=result;state.caseData.report_workflow=result;state.reportDirty=false;reportVersion=result.version;await clinicalWorkflow.refresh(id);await refreshReport();toast('报告'+(status==='reviewed'?'已审核':'已保存'));
  }
  function gainHtml(){return '<span>幅度：逐导联自适应（设备单位，电压未校准）</span>';}
  function stripSettingsHtml(raw,scope){
    const spec=ECGReportEngine.settings(raw),mode=spec.leads.length===12?'all':spec.leads.join(',')==='II,V1,V5'?'three':'custom';
    return `<div class="rp-entry-settings" data-strip-settings="${scope}"><strong>${scope==='default'?'新入报图条':'本图设置'}</strong><label>导联<select data-strip-mode="${scope}" aria-label="${scope==='default'?'新入报':'本图'}导联方案"><option value="three" ${mode==='three'?'selected':''}>常用 3 导联（II / V1 / V5）</option><option value="all" ${mode==='all'?'selected':''}>全部 12 导联</option><option value="custom" ${mode==='custom'?'selected':''}>自选导联</option></select></label><label>范围<input data-strip-duration="${scope}" type="number" min="1" max="120" step="0.5" value="${spec.duration_s}" aria-label="${scope==='default'?'新入报':'本图'}时长（秒）">秒</label>${scope==='default'?gainHtml():''}<span>默认 7 秒，至少 5 个可用心搏；不足时延长。仅修改${scope==='default'?'此后入报':'本条图条'}。</span><fieldset class="rp-leads" ${mode==='custom'?'':'hidden'}><legend>选择要进入报告的导联（至少一个）</legend>${ECGReportEngine.leads.map(lead=>`<label><input type="checkbox" data-strip-lead="${scope}" value="${lead}" ${spec.leads.includes(lead)?'checked':''}>${lead}</label>`).join('')}</fieldset></div>`;
  }
  function changeStripSettings(el){
    const scope=el.dataset.stripMode??el.dataset.stripLead??el.dataset.stripDuration;if(scope===undefined)return false;
    const holder=el.closest('[data-strip-settings]'),old=scope==='default'?composition().strip_defaults:selected()[Number(scope)],spec=ECGReportEngine.settings(old);
    if(el.dataset.stripMode!==undefined){
      if(el.value==='custom'){holder.querySelector('fieldset').hidden=false;return true;}
      spec.leads=el.value==='all'?[...ECGReportEngine.leads]:[...ECGReportEngine.defaults];
    }else if(el.dataset.stripLead!==undefined)spec.leads=[...holder.querySelectorAll('[data-strip-lead]:checked')].map(x=>x.value);
    else spec.duration_s=Number(el.value);
    try{ECGReportEngine.settings(spec);}catch(error){if(el.type==='checkbox')el.checked=!el.checked;else el.value=old.duration_s||7;handleError(error);return true;}
    if(scope==='default')state.reportComposition.strip_defaults=spec;else Object.assign(selected()[Number(scope)],spec);
    dirty();if(scope==='default')holder.outerHTML=stripSettingsHtml(spec,scope);else run(renderReportBody);return true;
  }
  async function reportStrip(e,selection,id=state.caseId){
    const spec=ECGReportEngine.settings(selection),key=['report',id,e.event_id,e.basis_version,spec.leads.join(','),spec.duration_s].join('|');
    if(waveCache.size>200)waveCache.delete(waveCache.keys().next().value);
    if(!waveCache.has(key))waveCache.set(key,endpoint('report-strip',{event_id:e.event_id,basis_version:e.basis_version,leads:spec.leads.join(','),duration:spec.duration_s},id).catch(error=>{waveCache.delete(key);throw error}));
    return {...await waveCache.get(key),caption:selection.caption||e.label};
  }
  async function selectedReportWaves(id){
    const picks=copy(selected()),results=[];let next=0;
    await Promise.all(Array.from({length:Math.min(4,picks.length)},async()=>{while(next<picks.length){const i=next++,s=picks[i],e=selectedLookup.get(s.event_id);if(!e||e.basis_version!==s.basis_version)throw Error('请处理失效图条后再导出');results[i]=await reportStrip(e,s,id);}}));return results;
  }
  function paperModel(statistics){return {case:state.caseData,statistics,report:{...state.report,conclusion:qs('#conclusionEditor')?.value??state.report.conclusion,composition:composition()}};}
  async function print(){
    if(state.reportDirty)throw Error('请先保存草稿再导出');
    const id=state.caseId,version=state.report.version,[statistics,entries]=await Promise.all([endpoint('report-statistics',{},id),selectedReportWaves(id)]);
    if(id!==state.caseId||state.reportDirty||version!==state.report.version)throw Error('报告已变化，请重新保存后打印');
    let frame=qs('#v2PrintFrame');if(frame)frame.remove();frame=document.createElement('iframe');frame.id='v2PrintFrame';frame.title='A4 报告打印预览';document.body.appendChild(frame);
    const doc=frame.contentDocument,css=new URL('static/css/report-paper.css',location.href).href;
    doc.open();doc.write(`<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>${esc(id)} 心电报告</title><link rel="stylesheet" href="${esc(css)}"></head><body><main class="rp-pages">${ECGReportPaper.render(paperModel(statistics),entries)}</main></body></html>`);doc.close();
    await new Promise((resolve,reject)=>{const link=doc.querySelector('link');link.onload=resolve;link.onerror=()=>reject(Error('打印样式读取失败，请刷新重试'));if(link.sheet)resolve();});await doc.fonts.ready;ECGReportPaper.number(doc.body);frame.contentWindow.focus();frame.contentWindow.print();
  }
  function bind(){
    const settingsButton=qs('#openReportSettings');settingsButton.textContent='图条设置';settingsButton.addEventListener('click',event=>{event.preventDefault();event.stopImmediatePropagation();category='strips';run(refreshReport)},true);
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
    const arrows=document.createElement('div');arrows.className='occurrence-actions';arrows.innerHTML='<button id="occLeft" aria-label="向左浏览波形">←</button><button id="occRight" aria-label="向右浏览波形">→</button><label>跳至第 <input id="occJump" type="number" min="1" value="1" aria-label="跳至波形序号"></label><button id="occGo">定位</button><button id="occRestore">恢复选中目标</button><button id="occDisease">确认所选节律</button>';qs('#editTemplateGallery').before(arrows);
    qs('#occLeft').onclick=()=>qs('#editTemplateGallery').scrollLeft-=tileWidth*6;qs('#occRight').onclick=()=>qs('#editTemplateGallery').scrollLeft+=tileWidth*6;qs('#occGo').onclick=()=>{qs('#editTemplateGallery').scrollLeft=Math.floor(Math.max(0,Math.min((occurrence?.total||1)-1,Number(qs('#occJump').value)-1))/2)*tileWidth;renderOccurrences()};qs('#occRestore').onclick=()=>run(()=>beatEditor.restore());
    qs('#occDisease').onclick=()=>run(async()=>{if(!['S','V','A','C'].includes(type)||!state.editSelectedSamples.size)throw Error('请先选择 S、V、房颤或房扑事件目标');const diagnosis={S:'房速',V:'室速',A:'房颤',C:'房扑'}[type],kind={S:'AT',V:'VT',A:'AF',C:'AFL'}[type];const samples=[...state.editSelectedSamples].sort((a,b)=>a-b),matched=[...pageCache.values()].filter(Boolean).flat().filter(e=>e.subtype!=='beat'&&e.target_samples.every(s=>state.editSelectedSamples.has(s))),start=Math.min(samples[0],...matched.map(e=>e.start_sample)),end=Math.max(samples.at(-1),...matched.map(e=>e.end_sample));if(!window.confirm(`将 ${samples.length} 个已选心搏所在区间确认为${diagnosis}？`))return;await api(`/api/cases/${state.caseId}/annotations`,{method:'POST',body:JSON.stringify({sample_index:start,lead:state.editLead,category:'note',label:diagnosis,details:{kind,status:'confirmed',end_sample:end,finding:diagnosis}})});await clinicalWorkflow.refresh();await loadOccurrences()});
    new ResizeObserver(()=>{if(occurrence)renderOccurrences()}).observe(qs('#editTemplateGallery'));
    let scrollFrame;qs('#editTemplateGallery').addEventListener('scroll',()=>{cancelAnimationFrame(scrollFrame);scrollFrame=requestAnimationFrame(renderOccurrences)});
    qs('#editTemplateGallery').addEventListener('keydown',e=>{if(e.key==='ArrowLeft'||e.key==='ArrowRight')e.stopPropagation()});
    const old=qs('.report-workbench'),root=document.createElement('section');root.id='reportV2';root.innerHTML='<nav id="reportV2Nav" aria-label="报告二级导航"></nav><p id="reportV2Notice"></p><div id="reportV2Content"></div>';old.before(root);old.hidden=true;root.after(qs('.report-conclusion-dock'));
    root.addEventListener('click',event=>{const b=event.target.closest('button');if(!b)return;if(b.dataset.category){category=b.dataset.category;reportOffset=0;reportMode='all';run(refreshReport)}if(b.dataset.locate!==undefined)run(()=>locate(reportData.items[Number(b.dataset.locate)]));if(b.dataset.remove!==undefined){const s=selected()[Number(b.dataset.remove)],e=selectedLookup.get(s.event_id);if(e)selectEvent(e,false);else{state.reportComposition.selected_events.splice(Number(b.dataset.remove),1);syncText();dirty();run(renderReportBody)}}if(b.dataset.move!==undefined){const i=Number(b.dataset.move),j=i+Number(b.dataset.delta);[state.reportComposition.selected_events[i],state.reportComposition.selected_events[j]]=[selected()[j],selected()[i]];dirty();run(renderReportBody)}if(b.dataset.backEvent!==undefined){const e=selectedLookup.get(selected()[Number(b.dataset.backEvent)].event_id);if(e){active=e;category=e.category;reportOffset=0;reportMode=e.subtype;run(refreshReport)}}if(b.dataset.ack!==undefined){Object.assign(state.reportComposition.diagnosis_blocks[Number(b.dataset.ack)],{acknowledged:true,needs_review:false});dirty();run(renderReportBody)}});
    root.addEventListener('change',event=>{const el=event.target;if(changeStripSettings(el))return;if(el.dataset.include!==undefined)selectEvent(reportData.items[Number(el.dataset.include)],el.checked)});
    root.addEventListener('input',event=>{const el=event.target;if(el.dataset.caption!==undefined){selected()[Number(el.dataset.caption)].caption=el.value;dirty()}if(el.dataset.block!==undefined){Object.assign(state.reportComposition.diagnosis_blocks[Number(el.dataset.block)],{text:el.value,manual:true,acknowledged:false});dirty()}});
    qs('#downloadReport').addEventListener('click',event=>{event.preventDefault();event.stopImmediatePropagation();run(async()=>{if(state.demoReadonly)return print();if(state.reportDirty)throw Error('请先保存草稿再导出');window.location.href=`/api/cases/${state.caseId}/report.pdf`})},true);
    const timebar=document.createElement('input');timebar.type='range';timebar.id='v2EditTime';timebar.min='0';timebar.step='.1';timebar.setAttribute('aria-label','编辑连续波形时间导航');qs('#editWaveCanvasWrap').after(timebar);
    const requestEditTime=()=>{clearTimeout(editTimeTimer);editTimeTimer=0;run(loadEditWaveform)};
    timebar.oninput=()=>{state.editStart=Math.max(0,Math.min(Number(timebar.value)||0,Number(timebar.max)||0));renderEditOverview();qs('#editWaveMeta').textContent='松开后读取所选时间段…';clearTimeout(editTimeTimer);editTimeTimer=setTimeout(requestEditTime,120)};
    timebar.onchange=requestEditTime;syncEditTimeSlider();
    const overviewTime=qs('#timeSlider');if(overviewTime)qs('#waveformCanvas').parentElement.after(overviewTime);
    const h=document.createElement('article');h.id='hrvWindowPanel';h.className='card';qs('#page-trends').prepend(h);
    document.querySelectorAll('[data-page="events"],[data-workflow-page="events"]').forEach(el=>el.hidden=true);
    if(state.caseId&&state.currentPage==='edit')run(loadOccurrences);
  }
  document.addEventListener('DOMContentLoaded',bind);
  return {loadOccurrences,renderOccurrences,refreshReport,renderReportShell,loadHrv,save,print,addStrip(e){category='strips';selectEvent(e,true)}};
})();
// Replace representative-only loaders; preserve existing continuous-waveform editor tools.
loadEditTemplateStrips=clinicalUI.loadOccurrences;
renderEditGallery=clinicalUI.renderOccurrences;
loadReport=clinicalUI.refreshReport;
renderReport=clinicalUI.renderReportShell;
saveReport=clinicalUI.save;
printReportPreview=clinicalUI.print;
const loadTrendsLegacy=loadTrends;
loadTrends=async()=>{await loadTrendsLegacy();await clinicalUI.loadHrv('#hrvWindowPanel')};
const goPageLegacy=goPage;
goPage=function(name){if(name==='events')name='report';if(name==='edit'&&state.currentPage==='review'){state.editStart=state.start;state.editLead=state.leads[0]||'II';}else if(name==='review'&&state.currentPage==='edit'){state.start=state.editStart;state.leads=[state.editLead,...state.leads.filter(l=>l!==state.editLead)];}return goPageLegacy(name)};

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
