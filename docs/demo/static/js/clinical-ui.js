"use strict";
/* Shared workstation UI. Selection for editing and selection for reporting are independent. */
const clinicalUI=(()=>{
  const A=ECGClinicalAnalysis,esc=escapeHtml,qs=s=>document.querySelector(s);
  const copy=x=>JSON.parse(JSON.stringify(x));
  const tabs=[...A.categories,['tables','数据表格'],['strips','报告图条'],['final','报告']];
  let occurrenceToken=0,reportToken=0,waveToken=0,editCase=null,occurrence=null,editMode='all',template='all',type='N',pageCache=new Map(),waveCache=new Map(),tileWidth=150;
  let reportCase=null,reportVersion=null,category='fastest',reportOffset=0,reportMode='all',reportData=null,selectedLookup=new Map(),active=null,hrv=null,hrvToken=0;
  const run=fn=>Promise.resolve().then(fn).catch(handleError);
  const endpoint=(kind,params={},id=state.caseId)=>api(`/api/cases/${id}/${kind}?${new URLSearchParams(params)}`);
  const selected=()=>state.reportComposition?.selected_events||[];
  function composition(){
    const source=state.reportComposition||state.report?.composition||{};
    return {...source,schema_version:2,selected_events:source.selected_events||[],category_reviews:source.category_reviews||{},diagnosis_blocks:source.diagnosis_blocks||[],fast_slow_mode:source.fast_slow_mode||'rr',paper:source.paper||{size:'A4',orientation:'portrait'}};
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
    qs('#editMorphologyCount').textContent=`当前批次 ${result.items.length} 搏`;
  }
  function renderOccurrences(){
    const host=qs('#editTemplateGallery');if(!host||!occurrence)return;
    host.classList.add('occurrence-viewport');const total=occurrence.total;const previousWidth=tileWidth;tileWidth=Math.max(90,host.clientWidth/6);if(previousWidth!==tileWidth&&host.scrollLeft)host.scrollLeft=Math.floor((host.scrollLeft+1)/previousWidth)*tileWidth;
    const first=Math.max(0,Math.floor((host.scrollLeft+1)/tileWidth)*2),last=Math.min(total,first+14),token=occurrenceToken,id=state.caseId;
    if(qs('#v2EditTime')){qs('#v2EditTime').max=state.caseData.technical.duration_seconds_raw;qs('#v2EditTime').value=state.editStart;}
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
      const data=await endpoint('report-events',{category:A.categories.some(([k])=>k===category)?category:'all',mode:reportMode,offset:reportOffset,limit:50,fast_slow_mode:composition().fast_slow_mode},id);
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
    if(checked)c.selected_events.push({event_id:e.event_id,basis_version:e.basis_version,caption:e.label});
    delete c.category_reviews[e.category];c.diagnosis_blocks.forEach(b=>{if(b.key===e.category+':'+e.subtype)b.acknowledged=false});syncText();dirty();renderReportShell();run(renderReportBody);
  }
  function renderReportShell(){
    if(!qs('#reportV2'))return;
    qs('#reportV2Nav').innerHTML=tabs.map(([key,label])=>{const count=reportData?.category_counts[key],countSelected=selected().filter(s=>selectedLookup.get(s.event_id)?.category===key).length;return `<button type="button" data-category="${key}" class="${category===key?'active':''}" aria-current="${category===key?'page':'false'}">${label}${count===undefined?'':`<small>${countSelected} / ${count}</small>`}</button>`}).join('');
    qs('#reportStatus').textContent=STATUS_TEXT[state.report.status]||state.report.status;qs('#reportVersion').textContent='v'+state.report.version;
    if(!state.reportDirty){qs('#conclusionEditor').value=state.report.conclusion||'';qs('#reportSaveState').textContent=state.report.updated_at?'已保存 '+state.report.updated_at:'尚未保存';updateConclusionCount();}
    qs('.report-conclusion-dock').hidden=category!=='final';
    const stale=selected().filter(s=>!selectedLookup.has(s.event_id)||selectedLookup.get(s.event_id).basis_version!==s.basis_version).length;
    qs('#reportV2Notice').textContent=`已选 ${selected().length} 条图条 · 统计包含当前全部结果${clinicalWorkflow.readiness()?"（已诊断确认）":"（诊断待确认）"}${stale?' · '+stale+'条已失效，请移除后重新筛选':''}`;
    if(qs('#approveReport'))qs('#approveReport').disabled=state.reportDirty||!clinicalWorkflow.readiness();
  }
  async function renderReportBody(){
    const host=qs('#reportV2Content');if(!host||!reportData)return;
    if(category==='tables'){host.innerHTML=statsTable()+'<div id="reportHrvV2"></div>';await loadHrv('#reportHrvV2');return;}
    if(category==='strips'||category==='final'){
      host.innerHTML=(category==='final'?`<div class="v2-paper-settings"><label>纸张<select id="v2Paper"><option>A4</option><option>A3</option></select></label><label>方向<select id="v2Orientation"><option value="portrait">纵向</option><option value="landscape">横向</option></select></label><span>保存草稿后审核。图条使用完整事件范围，幅度自适应显示。</span></div>`+statsTable()+'<div id="finalHrvV2"></div>':'' )+`<div id="v2TextBlocks">${composition().diagnosis_blocks.map((b,i)=>`<label class="v2-text-block">${esc(b.key)}${b.needs_review?' · 依据已移除，请核对':''}<textarea data-block="${i}" rows="2">${esc(b.text)}</textarea>${b.needs_review?`<button data-ack="${i}" type="button">已核对，保留人工文字</button>`:''}</label>`).join('')}</div><div class="v2-strip-list">${selected().map((s,i)=>{const e=selectedLookup.get(s.event_id),valid=e&&e.basis_version===s.basis_version;return `<article class="card v2-strip"><header><strong>${i+1}. ${esc(e?.label||s.event_id)} ${valid?'':'（已失效）'}</strong><div><button data-back-event="${i}">回看</button><button data-move="${i}" data-delta="-1" ${i===0?'disabled':''}>↑</button><button data-move="${i}" data-delta="1" ${i===selected().length-1?'disabled':''}>↓</button><button data-remove="${i}">移除</button></div></header><label>图注<input data-caption="${i}" value="${esc(s.caption)}" maxlength="500"></label><div data-selected-wave="${i}">${valid?'读取波形…':'请重新筛选'}</div><small>${e?formatElapsed(e.time_s)+'–'+formatElapsed(e.end_s):''} · 设备波形，自适应幅度</small></article>`}).join('')||'<p class="empty-state">尚未选择报告图条。可逐类查看后选择，也可确认本类全部不选。</p>'}</div>`;
      if(category==='final'){qs('#v2Paper').value=composition().paper.size||'A4';qs('#v2Orientation').value=composition().paper.orientation||'portrait';qs('#v2Paper').onchange=e=>{state.reportComposition.paper.size=e.target.value;dirty()};qs('#v2Orientation').onchange=e=>{state.reportComposition.paper.orientation=e.target.value;dirty()};}
      if(category==='final')await loadHrv('#finalHrvV2');
      const token=reportToken,id=state.caseId;await Promise.all(selected().map(async(s,i)=>{const e=selectedLookup.get(s.event_id),target=host.querySelector(`[data-selected-wave="${i}"]`);if(!e||e.basis_version!==s.basis_version)return;try{const wave=await eventWave(e,id);if(token===reportToken&&target?.isConnected)target.innerHTML=svg(wave,e)}catch(error){if(target?.isConnected)target.textContent='读取失败：'+error.message}}));return;
    }
    const complete=composition().category_reviews[category]===reportData.basis_versions[category],items=reportData.items;
    host.innerHTML=`<div class="v2-category-bar"><strong>${Object.fromEntries(tabs)[category]} · ${reportData.total} 条</strong><label>亚型<select id="v2Subtype"><option value="all">全部（不叠加模式计数）</option>${Object.entries(reportData.subtype_counts).map(([k,n])=>`<option value="${k}" ${reportMode===k?'selected':''}>${esc(Object.fromEntries(A.patterns)[k]||k)} · ${n}</option>`).join('')}</select></label>${['fastest','slowest'].includes(category)?`<label>计算序列<select id="v2Fast"><option value="rr">RR</option><option value="nn">NN</option><option value="both">RR 与 NN</option></select></label>`:''}<button class="button ${complete?'secondary':'primary'}" id="v2Complete" ${!reportData.category_counts[category]?'disabled':''}>${complete?'本类筛选已完成':'本类筛选完成（可全部不选）'}</button></div><div class="v2-event-layout"><div class="v2-event-list"><table><thead><tr><th>时间</th><th>模板 / 亚型</th><th>入报</th></tr></thead><tbody>${items.map((e,i)=>`<tr><td><button data-locate="${i}">${formatElapsed(e.time_s)}</button></td><td>${esc(e.templates.map(t=>t.name).join('/')||'—')}<br>${esc(e.label)}<small>${e.beat_count} 搏 · ${e.diagnosis_status==='confirmed'?'已确认':'待诊断确认'}</small></td><td><input type="checkbox" data-include="${i}" aria-label="${formatElapsed(e.time_s)} ${esc(e.label)}入报" ${selected().some(s=>s.event_id===e.event_id&&s.basis_version===e.basis_version)?'checked':''} ${e.diagnosis_status!=='confirmed'?'disabled':''}></td></tr>`).join('')||'<tr><td colspan="3">0 条匹配记录</td></tr>'}</tbody></table><footer><button id="v2Prev" ${reportOffset===0?'disabled':''}>上一页</button><span>${reportData.total?reportOffset+1:0}–${reportOffset+items.length} / ${reportData.total}</span><button id="v2Next" ${reportOffset+items.length>=reportData.total?'disabled':''}>下一页</button></footer></div><div class="v2-event-detail"><div class="v2-distribution">${Object.entries(reportData.subtype_counts).map(([k,n])=>`<span>${esc(Object.fromEntries(A.patterns)[k]||k)} <b>${n}</b></span>`).join('')}<small>连续搏数与重复节律为重叠标签，不能相加</small></div><div id="v2TimeDistribution"></div><div id="v2EventWave"><p class="empty-state">点击左侧事件查看完整波形</p></div><input id="v2Time" type="range" min="0" max="${state.caseData.technical.duration_seconds_raw}" step=".1" aria-label="事件连续波形时间导航"><small id="v2WaveLabel"></small></div></div>`;
    qs('#v2Subtype').onchange=e=>{reportMode=e.target.value;reportOffset=0;run(refreshReport)};
    if(qs('#v2Fast')){qs('#v2Fast').value=composition().fast_slow_mode;qs('#v2Fast').onchange=e=>{state.reportComposition.fast_slow_mode=e.target.value;state.reportComposition.selected_events=selected().filter(s=>{const item=selectedLookup.get(s.event_id);return !item||!['fastest','slowest'].includes(item.category)||e.target.value==='both'||item.subtype===e.target.value.toUpperCase()});syncText();delete state.reportComposition.category_reviews.fastest;delete state.reportComposition.category_reviews.slowest;dirty();run(refreshReport)}}
    qs('#v2Complete').onclick=()=>{state.reportComposition.category_reviews[category]=reportData.basis_versions[category];dirty();renderReportBody().catch(handleError)};
    qs('#v2Prev').onclick=()=>{reportOffset=Math.max(0,reportOffset-50);run(refreshReport)};qs('#v2Next').onclick=()=>{reportOffset+=50;run(refreshReport)};
    qs('#v2Time').oninput=e=>run(()=>detailWindow(Number(e.target.value)));
    const bins=reportData.time_counts||{},max=Math.max(1,...Object.values(bins));qs("#v2TimeDistribution").innerHTML=Array.from({length:Math.max(1,Math.ceil(state.caseData.technical.duration_seconds_raw/3600))},(_,i)=>`<span style="height:${(bins[i]||0)/max*50}px" title="记录第 ${i+1} 小时：${bins[i]||0} 次"></span>`).join("");
    if(items.length)await locate(items.find(e=>e.event_id===active?.event_id)||items[0]);
  }
  async function locate(e){active=e;const token=++waveToken,id=state.caseId;qs('#v2EventWave').textContent='读取完整事件…';const wave=await eventWave(e,id);if(token!==waveToken||id!==state.caseId||!qs('#v2EventWave'))return;qs('#v2EventWave').innerHTML=svg(wave,e);qs('#v2Time').value=e.time_s;qs('#v2WaveLabel').textContent=`${e.label} · ${formatElapsed(wave.start_s)}–${formatElapsed(wave.start_s+wave.duration_s)} · 目标 ${e.beat_count} 搏 · 完整事件概览`;}
  async function detailWindow(start){const token=++waveToken,id=state.caseId,wave=await endpoint('waveform',{start,duration:10,leads:'II,V1,V5',max_points:2400},id);if(token!==waveToken||id!==state.caseId||!qs('#v2EventWave'))return;qs('#v2EventWave').innerHTML=svg(wave,active);qs('#v2WaveLabel').textContent=`连续波形 ${formatElapsed(wave.start_s)} · 10 秒`;}
  function statsTable(){return `<table class="v2-stats"><caption>全部已确认结果统计（图条选择不改变统计）</caption><thead><tr><th>分类</th><th>事件次数</th><th>心搏数量</th></tr></thead><tbody>${A.categories.map(([k,label])=>`<tr><td>${label}</td><td>${reportData?.confirmed_category_counts[k]??'—'}</td><td>${reportData?.confirmed_beat_counts[k]??'—'}</td></tr>`).join('')}</tbody></table><details class="v2-source-summary"><summary>源报告独立对照</summary><p>有效心搏 ${state.caseData.summary.total_beats??'—'} · 平均心率 ${state.caseData.summary.avg_hr??'—'} bpm · SDNN ${state.caseData.summary.sdnn_ms??'—'} ms</p></details>`;}
  function hrvHtml(data){const rows=[...Object.values(data.periods),...data.hourly];return `<p>${esc(data.method)} · 实际覆盖 ${(data.actual_duration_s/3600).toFixed(2)} 小时</p><label>24 小时窗口<select class="v2-hrv-window">${Array.from({length:data.window_count},(_,i)=>`<option value="${i}" ${i===data.window_index?'selected':''}>第 ${i+1} 窗口</option>`).join('')}</select></label><svg class="v2-hrv-trend" viewBox="0 0 800 120" role="img" aria-label="逐小时SDNN趋势，空缺不连接">${data.hourly.map((r,i)=>{if(r.sdnn_ms===null)return '';const max=Math.max(1,...data.hourly.map(x=>x.sdnn_ms||0)),x=30+i*740/Math.max(1,data.hourly.length-1),y=100-r.sdnn_ms/max*80,prev=data.hourly[i-1];return (prev?.sdnn_ms!=null?`<path d="M${30+(i-1)*740/Math.max(1,data.hourly.length-1)} ${100-prev.sdnn_ms/max*80} L${x} ${y}" stroke="#0b7d7b"/>`:'')+`<circle cx="${x}" cy="${y}" r="3" fill="#0b7d7b"><title>${r.label} SDNN ${r.sdnn_ms} ms</title></circle>`}).join('')}</svg><table class="v2-stats"><thead><tr><th>时段</th><th>SDNN ms</th><th>RMSSD ms</th><th>pNN50 %</th><th>平均NN ms</th><th>有效 NN</th><th>覆盖 / 有效NN 秒</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.label)}</td>${['sdnn_ms','rmssd_ms','pnn50_pct','mean_nn_ms','nn_count'].map(k=>`<td>${r[k]??'—'}</td>`).join('')}<td>${r.coverage_s} / ${r.valid_nn_s}</td></tr>`).join('')}</tbody></table>`;}
  async function loadHrv(selector,windowIndex=composition().hrv_window||0){const token=++hrvToken,id=state.caseId,data=await endpoint('hrv-windows',{window:windowIndex},id);if(token!==hrvToken||id!==state.caseId||!qs(selector))return;hrv=data;qs(selector).innerHTML=hrvHtml(data);qs(selector).querySelector('select').onchange=e=>{state.reportComposition=composition();state.reportComposition.hrv_window=Number(e.target.value);if(state.currentPage==='report')dirty();run(()=>loadHrv(selector,Number(e.target.value)))};}
  async function save(status='draft'){
    if(!clinicalWorkflow.writable())throw Error('当前服务为只读');
    if(status==='reviewed'&&state.reportDirty)throw Error('请先保存草稿，再审核当前版本');
    const id=state.caseId,result=await api(`/api/cases/${id}/report`,{method:'PUT',body:JSON.stringify({status,expected_version:state.report.version,conclusion:qs('#conclusionEditor').value,composition:composition()})});
    if(id!==state.caseId)return;state.report=result;state.caseData.report_workflow=result;state.reportDirty=false;reportVersion=result.version;await clinicalWorkflow.refresh(id);await refreshReport();toast('报告'+(status==='reviewed'?'已审核':'已保存'));
  }
  async function print(){
    if(state.reportDirty)throw Error('请先保存草稿再导出');
    const id=state.caseId,c=copy(composition()),entries=selected().map(s=>{const e=selectedLookup.get(s.event_id);if(!e||e.basis_version!==s.basis_version)throw Error('请处理失效图条后再导出');return {...e,caption:s.caption}});
    const data=await endpoint('hrv-windows',{window:c.hrv_window||0},id),waves=await Promise.all(entries.map(e=>eventWave(e,id)));if(id!==state.caseId)return;
    let frame=qs('#v2PrintFrame');if(frame)frame.remove();frame=document.createElement('iframe');frame.id='v2PrintFrame';frame.title='报告打印预览';document.body.appendChild(frame);const doc=frame.contentDocument;doc.open();doc.write(`<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>${esc(id)} 心电报告</title><style>@page{size:${c.paper.size||'A4'} ${c.paper.orientation||'portrait'};margin:15mm}body{font:12px sans-serif;color:#16323c}table{border-collapse:collapse;width:100%;margin:12px 0}td,th{border:1px solid #ccd9dc;padding:5px}svg{width:100%;height:auto}article{break-inside:avoid;margin:20px 0}h1{font-size:22px}.v2-hrv-trend{height:100px}select{display:none}</style></head><body><h1>动态心电分析报告</h1><p>${esc(id)} · ${esc(state.caseData.metadata.start_time||'')} · ${esc(state.report.status)} v${state.report.version}</p><p style="white-space:pre-wrap">${esc(state.report.conclusion||'')}</p>${c.diagnosis_blocks.map(b=>`<p>${esc(b.text)}</p>`).join('')}${statsTable()}${hrvHtml(data)}${entries.map((e,i)=>`<article><h3>${i+1}. ${esc(e.caption)}</h3>${svg(waves[i],e)}<p>${formatElapsed(waves[i].start_s)}–${formatElapsed(waves[i].start_s+waves[i].duration_s)} · 原始设备波形，自适应幅度</p></article>`).join('')}</body></html>`);doc.close();await new Promise(resolve=>setTimeout(resolve,200));frame.contentWindow.focus();frame.contentWindow.print();
  }
  function bind(){
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
    root.addEventListener('change',event=>{const el=event.target;if(el.dataset.include!==undefined)selectEvent(reportData.items[Number(el.dataset.include)],el.checked)});
    root.addEventListener('input',event=>{const el=event.target;if(el.dataset.caption!==undefined){selected()[Number(el.dataset.caption)].caption=el.value;dirty()}if(el.dataset.block!==undefined){Object.assign(state.reportComposition.diagnosis_blocks[Number(el.dataset.block)],{text:el.value,manual:true,acknowledged:false});dirty()}});
    qs('#downloadReport').addEventListener('click',event=>{event.preventDefault();event.stopImmediatePropagation();run(async()=>{if(state.demoReadonly)return print();if(state.reportDirty)throw Error('请先保存草稿再导出');window.location.href=`/api/cases/${state.caseId}/report.pdf`})},true);
    const timebar=document.createElement('input');timebar.type='range';timebar.id='v2EditTime';timebar.min='0';timebar.step='.1';timebar.setAttribute('aria-label','编辑连续波形时间导航');qs('#editWaveCanvasWrap').after(timebar);timebar.oninput=()=>setEditStart(Number(timebar.value));
    const overviewTime=qs('#timeSlider');if(overviewTime)qs('#waveformCanvas').parentElement.after(overviewTime);
    const h=document.createElement('article');h.id='hrvWindowPanel';h.className='card';qs('#page-trends').prepend(h);
    document.querySelectorAll('[data-page="events"],[data-workflow-page="events"]').forEach(el=>el.hidden=true);
    if(state.caseId&&state.currentPage==='edit')run(loadOccurrences);
  }
  document.addEventListener('DOMContentLoaded',bind);
  return {loadOccurrences,renderOccurrences,refreshReport,renderReportShell,loadHrv,save,print};
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
