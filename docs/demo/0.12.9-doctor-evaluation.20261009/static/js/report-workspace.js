"use strict";
/* Web-only composition and linked distribution controls, separate from paper geometry. */
globalThis.ECGReportWorkspace=(()=>{
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let filter='all',reviewFilter='all',caseId=null;
  let view={expanded:new Set(),active:null,position:null,pageOpen:new Map(),waveHeights:new Map(),termState:{}},previewToken=0;
  const boundHosts=new WeakSet();
  const positionSelectors=['.rw-selected-strips','.rw-strip-index nav','.rw-rail nav','.rw-page-options','.rw-wave-scroll','.v2-event-list'];
  let waveSvgId=0;
  // Render only the channel arrays supplied by the source. No missing lead is synthesized here.
  function reviewWaveSvg(wave,event=null){
    const entries=globalThis.ECGChartInspection?.entries(wave.leads||{})||Object.entries(wave.leads||{}),width=1000,row=30,plotHeight=entries.length*row,height=plotHeight+24,id='rwReviewGrid'+(++waveSvgId),fs=wave.sample_rate_hz||200,stride=wave.stride||1,duration=Number(wave.duration_s);
    const ticks=Array.from({length:6},(_,i)=>i*duration/5);
    return `<svg class="rw-twelve-wave" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${esc(event?.label||'事件复核')}，${entries.length} 导联，同一真实时间范围 ${esc(formatElapsed(wave.start_s))} 至 ${esc(formatElapsed(wave.start_s+duration))}" data-review-lead-count="${entries.length}"><defs><pattern id="${id}" width="20" height="10" patternUnits="userSpaceOnUse"><path d="M20 0H0V10" fill="none" stroke="#ead9c8" stroke-width=".5"/></pattern></defs><rect width="1000" height="${plotHeight}" fill="#fffdfa"/><rect width="1000" height="${plotHeight}" fill="url(#${id})"/>${entries.map(([name,values],j)=>{const mid=(j+.5)*row,max=Math.max(50,...values.map(Math.abs)),scale=row*.38/max;return `<path d="M42 ${mid}H1000" stroke="#cdd7d9" stroke-width=".5"/><text x="3" y="${mid+5}" font-size="16" fill="#24424c">${esc(name)}</text><polyline data-lead="${esc(name)}" fill="none" stroke="#172126" stroke-width="1" vector-effect="non-scaling-stroke" points="${values.map((value,i)=>`${(42+Math.min(1,i*stride/fs/duration)*958).toFixed(3)},${(mid-value*scale).toFixed(3)}`).join(' ')}"/>`;}).join('')}<path d="M42 ${plotHeight}H1000" stroke="#8b9c9f"/>${ticks.map((t,i)=>`<text x="${42+i*958/5}" y="${height-5}" font-size="16" fill="#536b75" text-anchor="${i===0?'start':i===5?'end':'middle'}">${t.toFixed(2)} s</text>`).join('')}</svg>`;
  }
  // Pointer enlargement belongs only to the visible SVG. Table inclusion stays immediate.
  function bindWavePreview(host,open,isCurrent=()=>true){
    host._rwWaveOpen=open;host._rwWaveCurrent=isCurrent;
    host.setAttribute('aria-description','波形只读复核；双击具体波形或 Shift+Enter 查看 12 导联。左侧列表单击或勾选入报。');
    if(host._rwWaveBound)return;host._rwWaveBound=true;
    host.addEventListener('click',event=>{if(event.target.closest?.('svg')&&host.contains(event.target)){event.stopPropagation();if(host._rwWaveCurrent())host.focus({preventScroll:true});}},true);
    host.addEventListener('dblclick',event=>{if(event.button!==0||!event.target.closest?.('svg')||!host.contains(event.target)||!host._rwWaveCurrent())return;event.preventDefault();event.stopPropagation();host._rwWaveOpen?.();},true);
  }
  function capturePosition(root){
    const scroll=[];positionSelectors.forEach(selector=>root.querySelectorAll(selector).forEach((node,index)=>scroll.push({selector,index,top:node.scrollTop,left:node.scrollLeft})));
    const ancestors=[];for(let node=root;node;node=node.parentElement)ancestors.push({node,top:node.scrollTop,left:node.scrollLeft});
    const focus=document.activeElement;
    const attribute=root.contains(focus)&&['data-rw-toggle','data-caption','data-back-event','data-rw-index','data-strip-filter','data-review-filter','data-report-page','data-rw-conclusion','data-rw-evidence'].find(a=>focus?.hasAttribute?.(a));
    const selection=typeof focus?.selectionStart==='number'?{start:focus.selectionStart,end:focus.selectionEnd,direction:focus.selectionDirection,top:focus.scrollTop,left:focus.scrollLeft}:null;
    return {root,scroll,ancestors,focus:root.contains(focus)?focus:null,selection,attribute,value:attribute?focus.getAttribute(attribute):null,key:focus?.closest?.('[data-rw-key]')?.dataset.rwKey,windowX:globalThis.scrollX||0,windowY:globalThis.scrollY||0};
  }
  function restorePosition(position,root=position?.root){
    if(!position||!root?.isConnected)return;
    position.scroll.forEach(p=>{const node=root.querySelectorAll(p.selector)[p.index];if(node){node.scrollTop=p.top;node.scrollLeft=p.left;}});
    position.ancestors?.forEach(p=>{if(p.node.isConnected){p.node.scrollTop=p.top;p.node.scrollLeft=p.left;}});
    let focus=position.focus;
    if(!focus?.isConnected&&position.attribute){
      const owner=position.key?[...root.querySelectorAll('[data-rw-key]')].find(n=>n.dataset.rwKey===position.key):root;
      focus=[...(owner?.querySelectorAll(`[${position.attribute}]`)||[])].find(n=>position.key||n.getAttribute(position.attribute)===position.value);
    }
    focus?.focus({preventScroll:true});
    if(position.selection&&focus?.setSelectionRange){focus.setSelectionRange(position.selection.start,position.selection.end,position.selection.direction);focus.scrollTop=position.selection.top;focus.scrollLeft=position.selection.left;}
    globalThis.scrollTo?.(position.windowX,position.windowY);
  }
  // A read-only dialog keeps the event list, filters and range drafts alive underneath.
  function mountEventPreview(host,{event,loadWave,renderWave,isCurrent=()=>true}){
    host.querySelector('[data-rw-event-preview]')?.remove();
    const open=()=>{
      if(!isCurrent()||!host.isConnected||document.querySelector('dialog[open]'))return;
      const root=host.closest('#reportV2Content')||host,position=capturePosition(root),token=++previewToken;
      position.focus=host;
      const dialog=document.createElement('dialog');dialog.className='rw-event-preview-dialog';dialog.setAttribute('aria-labelledby','rwEventPreviewTitle');
      dialog.innerHTML=`<header><div><h2 id="rwEventPreviewTitle">12 导联事件复核</h2><p>${esc(event?.label||'连续波形')}${event?.time_s!==undefined?' · '+esc(formatElapsed(event.time_s)):''}</p></div><button type="button" data-rw-close>返回事件列表</button></header><p class="rw-hint">只读放大当前范围；关闭后返回原事件、筛选与位置。入报、诊断确认与报告审核分别操作。</p><div data-rw-preview-wave role="status">正在读取 12 导联…</div>`;
      document.body.append(dialog);dialog.querySelector('[data-rw-close]').onclick=()=>dialog.close();
      dialog.addEventListener('close',()=>{if(token===previewToken)previewToken++;dialog.remove();if(isCurrent())restorePosition(position);},{once:true});
      dialog.showModal();
      const target=dialog.querySelector('[data-rw-preview-wave]');
      function load(){
        target.textContent='正在读取 12 导联…';
        Promise.resolve().then(loadWave).then(wave=>{
          if(!dialog.open||token!==previewToken)return;
          if(!isCurrent()){target.textContent='当前病例或依据已变化，请关闭后重新选择事件。';return;}
          target.removeAttribute('role');target.innerHTML=waveContext({waveform:wave},renderWave(wave));
        }).catch(error=>{
          if(!dialog.open||token!==previewToken)return;
          target.textContent=isCurrent()?'读取失败：'+error.message:'当前病例或依据已变化，请关闭后重新选择事件。';
          if(isCurrent()){const retry=document.createElement('button');retry.type='button';retry.textContent='重试 12 导联';retry.onclick=load;target.append(retry);}
        });
      }
      load();
    };
    host._rwOpenPreview=open;
    globalThis.ECGChartInspection?.bindSurface(host,open,{isCurrent,title:'当前事件 12 导联'});
    return open;
  }
  function pageGroups(sections){
    const groups=[{name:'基础报告',items:[]},{name:'事件与趋势',items:[]},{name:'HRV 与研究测量',items:[]}];
    sections.forEach(s=>groups[['cover','summary','hourly'].includes(s.key)?0:s.key.startsWith('hrv_')||['hrt','dc','qtd','vcg','twa','vlp','sap'].includes(s.key)?2:1].items.push(s));
    return groups.filter(g=>g.items.length);
  }
  function insertSelectedText(editor,text){
    if(!text||editor.readOnly||editor.disabled)return null;
    const before=editor.value,start=editor.selectionStart??before.length,end=editor.selectionEnd??start;
    // Keep every character written by the doctor, including selected text.
    if(editor.maxLength>=0&&before.length+text.length>editor.maxLength)return null;
    editor.setRangeText(text,end,end,'end');editor.dispatchEvent(new Event('input',{bubbles:true}));editor.focus({preventScroll:true});
    return {before,after:editor.value,start,end};
  }
  function undoInsertedText(editor,insertion){
    if(!insertion||editor.value!==insertion.after||editor.readOnly||editor.disabled)return false;
    editor.value=insertion.before;editor.setSelectionRange(insertion.start,insertion.end);editor.dispatchEvent(new Event('input',{bubbles:true}));editor.focus({preventScroll:true});return true;
  }
  const reviewLabels={all:'全部状态',stale:'依据失效',pending:'待完成诊断确认',confirmed:'事件已确认'};
  function stripReviewState(selection,event){
    if(!event||event.event_id!==selection.event_id||!selection.basis_version||event.basis_version!==selection.basis_version)return 'stale';
    return event.diagnosis_status==='confirmed'&&(event.category!=='AF'||event.rhythm_status==='confirmed')?'confirmed':'pending';
  }
  function reviewExplanation(status,event){
    if(status==='stale')return '须重新核对，不能导出';
    if(status==='confirmed')return '不代表报告已审核';
    if(event?.category==='AF')return event.rhythm_status==='confirmed'?'片段已确认，编辑环节仍待确认；报告未审核':'节律片段仍待复核，不能视为确诊';
    return `${event?.category==='ST'?'ST-T':'编辑'}环节仍待确认，入草稿不代表确诊`;
  }
  function reviewQueue(selected,lookup,type='all',status='all'){
    const rows=selected.map((s,i)=>{const e=lookup.get(s.event_id);return {s,i,e,key:e?e.category+':'+e.subtype:'stale',status:stripReviewState(s,e)}});
    const counts={all:rows.length,stale:0,pending:0,confirmed:0};rows.forEach(r=>counts[r.status]++);
    return {counts,visible:rows.filter(r=>(type==='all'||r.key===type)&&(status==='all'||r.status===status))};
  }
  // Printing eligibility never mutates the physician's saved curation.
  const withRateMode=(composition,mode)=>({...composition,fast_slow_mode:mode});
  const printEligible=(event,mode)=>!event||!['fastest','slowest'].includes(event.category)||mode==='both'||event.subtype===mode.toUpperCase();
  function waveContext(entry,waveSvg=''){
    const wave=entry.waveform,spec=entry.strip||{},duration=Number(wave.duration_s),count=spec.visible_beat_count??wave.beats?.length??0;
    const reviewNote=(globalThis.ECGReportEngine||(typeof require==='function'?require('./report-engine.js'):null))?.reviewNote(entry)||'';
    const ticks=Array.from({length:8},(_,i)=>i*duration/7);
    return `${reviewNote?`<p class="rw-wave-context" data-rhythm-review-note><strong>${esc(reviewNote)}</strong></p>`:''}<p class="rw-wave-context">实际范围 ${esc(formatElapsed(wave.start_s))}–${esc(formatElapsed(wave.start_s+duration))}（记录起点后） · ${duration.toFixed(3)} 秒 · ${count} 搏${spec.warning?' · '+esc(spec.warning):count<5?' · 不足 5 搏，请核对区间':''}</p><p class="rw-hint">逐导联自适应幅度 · 设备单位，电压未校准。横向滚动查看完整波形；下方标尺为该图条内的秒数。</p><div class="rw-wave-scroll" tabindex="0" role="region" aria-label="图条波形，可左右滚动"><div class="rw-wave-canvas">${waveSvg}<svg class="rw-time-axis" viewBox="0 0 1000 28" role="img" aria-label="时间标尺，0 至 ${duration.toFixed(3)} 秒"><path d="M0 1H1000" stroke="currentColor"/>${ticks.map((t,i)=>`<path d="M${i*1000/7} 1v5" stroke="currentColor"/><text x="${i*1000/7}" y="21" font-size="12" text-anchor="${i===0?'start':i===7?'end':'middle'}">${t.toFixed(2)} s</text>`).join('')}</svg></div></div>`;
  }
  function bars(title,rows,selected,attribute){
    const max=Math.max(1,...rows.map(x=>x.count));
    return `<section class="rw-distribution"><header><strong>${title}</strong><span>次数 · 最大 ${max}</span></header><div class="rw-bars" style="--bar-count:${rows.length}">${rows.map((r,i)=>`<button type="button" ${attribute}="${esc(r.key??i)}" aria-pressed="${String(selected===String(r.key??i))}" aria-label="${esc(r.label)}：${r.count} 次，${r.count?'点击筛选':'没有候选'}" title="${esc(r.label)} · ${r.count} 次 · ${r.count?'仅筛选显示，不改变已选图条':'此分箱没有候选事件'}" ${r.count?'':'disabled'}><span class="rw-bar-count">${r.count}</span><i style="height:${r.count/max*64}px;--rw-bar-size:${r.count/max*64}px"></i><span class="rw-bar-label${attribute==='data-hour-bin'&&i%Math.max(1,Math.ceil(rows.length/7))!==0&&i!==rows.length-1?' rw-sparse-tick':''}">${attribute==='data-hour-bin'?r.label.split(' ').map(part=>`<span class="rw-clock-part">${esc(part)}</span>`).join(''):esc(r.label)}</span></button>`).join('')}</div></section>`;
  }
  function distributions(host,data,{mode,range,pauseBand,category,labels,change}){
    const rows=category==='pause'?Object.entries(data.pause_counts).map(([key,count])=>({key,count,label:{all:'全部 >2.5s',over3:'其中 >3s','2.5to3':'2.5–3s'}[key]})):Object.entries(data.subtype_counts).map(([key,count])=>({key,count,label:labels[key]||key}));
    const time=data.time_bins||[],active=time.findIndex(b=>range&&b.start_s===range[0]&&b.end_s===range[1]);
    host.innerHTML=bars('事件数量分布',rows,category==='pause'?pauseBand:mode,'data-pattern-bin')+bars('时间分布 · 按记录时钟逐小时',time,String(active),'data-hour-bin')+`<div class="rw-filter-status"><span role="status">${mode==='all'?'全部亚型':esc(labels[mode]||mode)} · ${active>=0?esc(time[active].label)+' 时段':'全部时间'} · ${data.total} 条${data.candidate_spacing_s?` · 定位点间隔 ≥${data.candidate_spacing_s} 秒`:''}</span><button type="button" data-clear-bins ${mode==='all'&&!range&&pauseBand==='all'&&!data.candidate_spacing_s?'disabled':''}>清除筛选</button></div><p class="rw-hint">点击柱形筛选左侧事件；亚型与小时可组合。柱图为实际日期和钟点；左表 D1 为记录起点后的时长。跨时段事件按起点归属；模式可能重叠，不相加。</p>`;
    host.onclick=e=>{const b=e.target.closest('button');if(!b||b.disabled)return;if(b.hasAttribute('data-clear-bins'))change({mode:'all',range:null,pauseBand:'all',spacing:0});if(b.dataset.patternBin!==undefined)change(category==='pause'?{pauseBand:b.dataset.patternBin}:{mode:b.dataset.patternBin});if(b.dataset.hourBin!==undefined){const bin=time[Number(b.dataset.hourBin)];change({range:[bin.start_s,bin.end_s]})}};
    const clear=host.querySelector('[data-clear-bins]');if(clear)clear.title=clear.disabled?'当前没有亚型、时段或间隔筛选':'仅清除显示筛选，保留已选图条与诊断复核';
  }
  function compose(host,{id,composition,selected,lookup,sections,onPages,onMode,onPreview,renderWave,loadWave,renderAdvanced,terms=[],overview=null,isCurrent=()=>true}){
    view.miniObserver?.disconnect();
    if(caseId===id&&host.querySelector('.rw-workspace')){
      view.position=capturePosition(host);
      host.querySelectorAll('[data-rw-page-group]').forEach(n=>view.pageOpen.set(n.dataset.rwPageGroup,n.open));
      view.indexOpen=host.querySelector('.rw-strip-index')?.open;
      view.outputOpen=host.querySelector('.rw-output-options')?.open;
      host.querySelectorAll('.rw-strip').forEach(n=>{const wave=n.querySelector('[data-rw-wave]');if(wave?.dataset.loaded==='ready'&&wave.getBoundingClientRect().height>0)view.waveHeights.set(n.dataset.rwKey,wave.getBoundingClientRect().height);});
    }
    const oldDock=document.querySelector('.report-conclusion-dock');if(oldDock&&host.contains(oldDock))host.before(oldDock);
    if(caseId!==id){view.saveObserver?.disconnect();caseId=id;filter='all';reviewFilter='all';view={expanded:new Set(),active:selected[0]?.event_id||null,position:null,pageOpen:new Map(),waveHeights:new Map(),termState:{open:globalThis.matchMedia?.('(min-width:1100px)').matches===true},indexOpen:false,outputOpen:false}}
    const groups=new Map();selected.forEach(s=>{const e=lookup.get(s.event_id),key=e?e.category+':'+e.subtype:'stale';const g=groups.get(key)||{name:e?.category==='AF'?(e.subtype==='AFL'?'房扑':'房颤'):e?.label||'原事件不可用',count:0};g.count++;groups.set(key,g)});
    if(filter!=='all'&&!groups.has(filter))filter='all';
    const {visible,counts}=reviewQueue(selected,lookup,filter,reviewFilter);
    if(!view.active&&selected.length)view.active=selected[0].event_id;
    host.innerHTML=`<div class="rw-workspace">
      <aside class="rw-rail">
        <section><h3>图条类型</h3><nav aria-label="已入报图条筛选"><button data-strip-filter="all" aria-pressed="${filter==='all'}">全部 <b>${selected.length}</b></button>${[...groups].map(([k,g])=>`<button data-strip-filter="${esc(k)}" aria-pressed="${filter===k}">${esc(g.name)} <b>${g.count}</b></button>`).join('')}</nav></section>
        <details class="rw-output-options" ${view.outputOpen?'open':''}><summary>报告内容与输出 <span>${composition.included_pages.length} 类页</span></summary>
          <fieldset><legend>最快 / 最慢图条</legend>${[['rr','仅 RR'],['nn','仅 NN'],['both','RR 与 NN']].map(([v,l])=>`<label><input type="radio" name="rwRateMode" value="${v}" ${composition.fast_slow_mode===v?'checked':''}>${l}</label>`).join('')}</fieldset>
          <section><h3>报告页</h3><div class="rw-page-options">${pageGroups(sections).map(g=>`<details ${g.name==='基础报告'?'open':''} data-rw-page-group="${esc(g.name)}"><summary>${g.name} · ${g.items.filter(s=>composition.included_pages.includes(s.key)).length} / ${g.items.length}</summary>${g.items.map(s=>`<label title="${esc(s.reason||'')}"><input type="checkbox" data-report-page="${s.key}" ${composition.included_pages.includes(s.key)?'checked':''} ${s.available?'':'disabled'}><span>${esc(s.title)}${s.available?'':`<small>${esc(s.reason)}</small>`}</span></label>`).join('')}</details>`).join('')}</div></section>
        </details>
      </aside>
      <div class="rw-main">
        <header class="rw-heading"><div><h2>报告编排</h2><p><span data-rw-visible-count>${visible.length}</span> 条图条 · <span data-rw-page-count>${composition.included_pages.length}</span> 类报告页</p></div><button type="button" data-paper-preview>预览 A4</button></header>
        <div class="rw-columns">
          <section class="rw-evidence" aria-label="已入报证据"><header class="rw-evidence-heading"><h3>入报图条</h3><span>共 ${selected.length} 条</span></header>
            <div class="rw-selected-strips">${visible.map(({s,i,e,status})=>`<article class="rw-strip" data-rw-key="${esc(s.event_id)}"><header><strong>${i+1}. ${esc(s.caption||e?.label||'已失效图条')}</strong><span>${e?formatElapsed(e.time_s):'需重新选择'}</span></header><div class="rw-mini-wave" data-rw-mini="${i}" aria-label="图条 ${i+1} 的完整 12 导联复核">${status==='stale'?'依据已失效，须重新核对':'可见时读取真实 12 导联…'}</div><small class="rw-mini-range" data-rw-mini-range="${i}">复核显示 12 导联 · 入报 ${esc((s.leads||composition.strip_defaults?.leads||['II','V1','V5']).join(' / '))}</small><div class="rw-strip-actions"><button type="button" data-rw-toggle="${i}" aria-expanded="${view.expanded.has(s.event_id)}" aria-controls="rwStripBody${i}">${view.expanded.has(s.event_id)?'折叠波形':'展开波形'}</button><button type="button" data-back-event="${i}">回看事件</button><button type="button" data-category="strips">导联 / 区间</button><button type="button" data-remove="${i}">移除</button></div><div id="rwStripBody${i}" class="rw-strip-body" ${view.expanded.has(s.event_id)?'':'hidden'}><div data-rw-wave="${i}">${e?'读取波形…':'依据已变化，请移除后重新选择'}</div><label>图注<input data-caption="${i}" maxlength="500" value="${esc(s.caption)}"></label></div></article>`).join('')||'<div class="rw-empty"><strong>尚无入报图条</strong><p>在事件选图中核对波形，再加入报告草稿。</p><button type="button" data-category="fastest">前往事件选图</button></div>'}</div>
          </section>
          <section id="rwConclusionSlot" class="rw-conclusion-pane" aria-label="报告结论编辑"></section>
        </div>
      </div>
    </div>`;
    if(overview){const panel=document.createElement('aside');panel.className='rw-overview';panel.setAttribute('aria-label','全记录统计总览');panel.innerHTML=`<h3>全记录统计总览</h3><p>当前依据 r${esc(overview.revision??'—')} · 已确认结果</p><table><thead><tr><th>分类</th><th>次数</th><th>搏数</th></tr></thead><tbody>${overview.categories.map(row=>`<tr><th>${esc(row.label)}</th><td>${esc(row.events??'—')}</td><td>${esc(row.beats??'—')}</td></tr>`).join('')}</tbody></table><p>统计独立于选图。未确认候选不计作确诊。</p><section><h4>源报告独立对照</h4><dl><div><dt>有效心搏</dt><dd>${esc(overview.source.total_beats??'—')}</dd></div><div><dt>平均心率</dt><dd>${esc(overview.source.avg_hr??'—')} bpm</dd></div><div><dt>SDNN</dt><dd>${esc(overview.source.sdnn_ms??'—')} ms</dd></div></dl><p>保留源报告摘要；不改写为当前修订统计或诊断。</p></section>`;host.querySelector('.rw-main').append(panel);}
    host.querySelector('.rw-rail fieldset').insertAdjacentHTML('beforeend','<p class="rw-hint">仅影响本次输出，保留所有选图、图注和区间。</p>');
    host.querySelector('.rw-evidence-heading').insertAdjacentHTML('afterend',`<section class="rw-review-queue" aria-label="入报图条复核状态"><nav aria-label="按复核状态筛选">${Object.entries(reviewLabels).map(([key,label])=>`<button type="button" data-review-filter="${key}" aria-pressed="${reviewFilter===key}">${label} <b>${counts[key]}</b></button>`).join('')}</nav><p role="status">${esc(filter==='all'?'全部类型':groups.get(filter).name)} · ${reviewLabels[reviewFilter]} · 显示 ${visible.length} / ${selected.length} 条</p><details class="rw-review-help"><summary>状态说明</summary><p>计数涵盖全部已选图条；筛选不移除选图，事件确认不代表报告已审核。</p></details>${filter!=='all'||reviewFilter!=='all'?'<button type="button" data-clear-strip-filters>显示全部已选图条</button>':''}</section>`);
    if(!visible.length&&selected.length)host.querySelector('.rw-selected-strips').innerHTML='<p class="empty-state">当前组合没有匹配图条；其他已选图条仍保留。可切换状态或显示全部已选图条。</p>';
    if(composition.paper?.voltage_estimate)host.querySelector('.rw-heading').insertAdjacentHTML('afterend',`<p class="rw-hint">导出图条使用独立保存的${esc(ECGVoltage.note(composition.paper.voltage_estimate))}网页预览仍为自适应幅度；请在“导联 / 区间”调整导出增益，并用 A4 预览核对。</p>`);
    visible.forEach(({i,e,status})=>{
      const node=host.querySelector(`[data-rw-wave="${i}"]`),included=printEligible(e,composition.fast_slow_mode),back=host.querySelector(`[data-back-event="${i}"]`);
      node.closest('.rw-strip').querySelector('header').insertAdjacentHTML('afterend',`<p class="rw-print-status" data-review-status="${status}" title="${esc(reviewExplanation(status,e))}">${reviewLabels[status]}${status==='stale'?' · 须重新核对，不能导出':''}${included?'':' · 本次不输出，选图仍保留'}</p>`);
      back.disabled=status==='stale';back.title=status==='stale'?'旧依据无法回看；有对应节律片段时请使用复核片段入口，否则重新筛选':'回看此图条对应的事件';
    });
    visible.forEach(({i,e})=>{if(e?.category==='AF'&&e.rhythm_episode_id)host.querySelector(`[data-back-event="${i}"]`).insertAdjacentHTML('afterend',`<button type="button" data-review-rhythm="${i}">保存草稿并复核片段</button>`);});
    if(renderAdvanced){const panel=document.createElement('div');panel.className='rw-research';host.querySelector('.rw-workspace').append(panel);renderAdvanced(panel);}
    function redraw(selector){
      compose(host,{id,composition,selected,lookup,sections,onPages,onMode,onPreview,renderWave,loadWave,renderAdvanced,terms,overview,isCurrent});
      host.querySelector(selector)?.focus({preventScroll:true});
    }
    host.querySelectorAll('[data-strip-filter]').forEach(b=>b.onclick=()=>{filter=b.dataset.stripFilter;redraw('[data-strip-filter][aria-pressed="true"]')});
    host.querySelectorAll('[data-review-filter]').forEach(b=>b.onclick=()=>{reviewFilter=b.dataset.reviewFilter;redraw('[data-review-filter][aria-pressed="true"]')});
    host.querySelector('[data-clear-strip-filters]')?.addEventListener('click',()=>{filter='all';reviewFilter='all';redraw('[data-review-filter="all"]')});
    host.querySelectorAll('[data-report-page]').forEach(el=>el.onchange=()=>{
      composition.included_pages=[...host.querySelectorAll('[data-report-page]:checked')].map(x=>x.dataset.reportPage);
      host.querySelector('[data-rw-page-count]').textContent=composition.included_pages.length;host.querySelector('.rw-output-options summary span').textContent=composition.included_pages.length+' 类页';
      host.querySelectorAll('[data-rw-page-group]').forEach(group=>{group.querySelector('summary').textContent=`${group.dataset.rwPageGroup} · ${group.querySelectorAll('input:checked').length} / ${group.querySelectorAll('input').length}`;});
      onPages(composition.included_pages);
    });
    host.querySelectorAll('[name=rwRateMode]').forEach(el=>el.onchange=()=>onMode(el.value));
    host.querySelector('[data-paper-preview]').onclick=onPreview;
    // The conclusion editor is a live node: move, never recreate its unsaved text.
    const dock=document.querySelector('.report-conclusion-dock');if(dock){host.querySelector('#rwConclusionSlot').append(dock);dock.hidden=false;}
    const index=document.createElement('details');index.className='rw-strip-index';index.open=!!view.indexOpen;
    index.innerHTML=`<summary>按编号定位 · ${visible.length} / ${selected.length} 条</summary><nav aria-label="按原编号定位图条">${visible.map(({s,i,e,status})=>`<button type="button" data-rw-index="${i}" aria-current="${s.event_id===view.active}"><strong>原图条 ${i+1}</strong><span>${esc(s.caption||e?.label||'已失效图条')} · ${e?esc(formatElapsed(e.time_s)):'原事件不可用'} · ${reviewLabels[status]}</span></button>`).join('')}</nav>`;
    host.querySelector('.rw-selected-strips').before(index);
    const jump=document.createElement('nav');jump.className='rw-locations';jump.setAttribute('aria-label','证据与结论定位');
    jump.innerHTML='<button type="button" data-rw-evidence>定位当前证据</button><button type="button" data-rw-conclusion>编辑报告结论</button><span data-rw-save-state></span>';
    host.querySelector('.rw-heading').after(jump);
    function focusStrip(row){
      view.active=row.s.event_id;expand(row,true);
      host.querySelectorAll('[data-rw-index]').forEach(b=>b.setAttribute('aria-current',String(Number(b.dataset.rwIndex)===row.i)));
      const button=host.querySelector(`[data-rw-toggle="${row.i}"]`);button.scrollIntoView({block:'nearest'});button.focus({preventScroll:true});
    }
    const rowWaves=new Map();
    function readRow(row){if(!rowWaves.has(row.s.event_id))rowWaves.set(row.s.event_id,Promise.resolve().then(()=>{if(!isCurrent())throw Error('报告视图已变化');return loadWave(row.e,row.s);}).catch(error=>{rowWaves.delete(row.s.event_id);throw error;}));return rowWaves.get(row.s.event_id);}
    function loadMini(row){
      const {s,i,status}=row,node=host.querySelector(`[data-rw-mini="${i}"]`);if(!node||node.dataset.loaded||status==='stale'||!isCurrent())return;
      node.dataset.loaded='loading';node.textContent='正在读取真实 12 导联…';
      readRow(row).then(entry=>{if(!node.isConnected||caseId!==id||!isCurrent())return;node.innerHTML=renderWave(entry)+`<div class="rw-mini-labels" aria-hidden="true">${(globalThis.ECGChartInspection?.names(entry.waveform.leads)||Object.keys(entry.waveform.leads)).map(name=>`<span>${esc(name)}</span>`).join('')}</div>`;node.dataset.loaded='ready';host.querySelector(`[data-rw-mini-range="${i}"]`).textContent=`${formatElapsed(entry.waveform.start_s)} — ${formatElapsed(entry.waveform.start_s+entry.waveform.duration_s)} · ${entry.strip.visible_beat_count} 搏 · 复核 12 导联 / 入报 ${entry.strip.leads.join(' / ')} · 设备单位 u，未校准`;const open=mountEventPreview(node,{event:row.e,loadWave:()=>Promise.resolve(entry.waveform),renderWave:wave=>reviewWaveSvg(wave,row.e),isCurrent:()=>node.isConnected&&caseId===id&&isCurrent()});bindWavePreview(node,open,()=>node.isConnected&&caseId===id&&isCurrent());}).catch(error=>{if(!node.isConnected||caseId!==id||!isCurrent())return;delete node.dataset.loaded;node.textContent='12 导联读取失败：'+error.message;const retry=document.createElement('button');retry.type='button';retry.textContent='重试 12 导联';retry.onclick=()=>loadMini(row);node.append(retry);});
    }
    if(typeof IntersectionObserver!=='undefined'){view.miniObserver=new IntersectionObserver(entries=>entries.forEach(entry=>{if(entry.isIntersecting){const row=visible.find(r=>String(r.i)===entry.target.dataset.rwMini);if(row)loadMini(row);}}),{root:host.querySelector('.rw-selected-strips'),rootMargin:'0px'});host.querySelectorAll('[data-rw-mini]').forEach(node=>view.miniObserver.observe(node));}else visible.forEach(loadMini);
    function loadRow(row){
      const {s,i,e,status}=row,node=host.querySelector(`[data-rw-wave="${i}"]`);
      if(node.dataset.loaded)return;
      if(status==='stale'){node.dataset.loaded='stale';node.textContent=e?.category==='AF'&&e.rhythm_episode_id?'图条依据已失效。请保存草稿并复核片段，返回后核对并替换原图条；导联和图注保留。':'原事件已不存在或依据已失效。请重新筛选事件；移除前可保留人工图注。';return;}
      if(view.waveHeights.has(s.event_id))node.style.minHeight=view.waveHeights.get(s.event_id)+'px';
      node.dataset.loaded='loading';node.textContent='读取波形…';
      readRow(row).then(entry=>{if(node.isConnected&&caseId===id&&isCurrent()){node.innerHTML=waveContext(entry,renderWave(entry));node.dataset.loaded='ready';node.style.minHeight='';}}).catch(error=>{
        if(!node.isConnected||caseId!==id||!isCurrent())return;delete node.dataset.loaded;node.style.minHeight='';node.textContent='读取失败：'+error.message;
        const retry=document.createElement('button');retry.type='button';retry.textContent='重试图条波形';retry.onclick=()=>loadRow(row);node.append(retry);
      });
    }
    function expand(row,open){
      const {s,i}=row,button=host.querySelector(`[data-rw-toggle="${i}"]`);host.querySelector(`#rwStripBody${i}`).hidden=!open;
      if(open){view.expanded.add(s.event_id);view.active=s.event_id;loadRow(row);}else view.expanded.delete(s.event_id);
      button.setAttribute('aria-expanded',String(open));button.textContent=open?'折叠波形':'展开波形';
    }
    visible.forEach(row=>{host.querySelector(`[data-rw-toggle="${row.i}"]`).onclick=()=>expand(row,!view.expanded.has(row.s.event_id));if(view.expanded.has(row.s.event_id))loadRow(row);});
    host.querySelectorAll('[data-rw-index]').forEach(b=>b.onclick=()=>focusStrip(visible.find(r=>r.i===Number(b.dataset.rwIndex))));
    host.querySelector('[data-rw-evidence]').onclick=()=>{const row=visible.find(r=>r.s.event_id===view.active)||visible[0];if(row)focusStrip(row);};
    host.querySelector('[data-rw-evidence]').disabled=!visible.length;
    const editor=dock?.querySelector('#conclusionEditor');
    host.querySelector('[data-rw-conclusion]').disabled=!editor;
    host.querySelector('[data-rw-conclusion]').onclick=()=>{editor?.scrollIntoView({block:'center'});editor?.focus({preventScroll:true});};
    const save=document.querySelector('#reportSaveState');host.querySelector('[data-rw-save-state]').textContent=save?.textContent||'';
    if(save){view.saveObserver?.disconnect();view.saveObserver=new MutationObserver(()=>{const target=host.querySelector('[data-rw-save-state]');if(target)target.textContent=save.textContent;});view.saveObserver.observe(save,{childList:true,characterData:true,subtree:true});}
    if(editor){
      const oldTerms=dock.querySelector('[data-rw-terms]');if(oldTerms){if(oldTerms.dataset.rwCase===String(id)){view.termState.open=oldTerms.open;view.termState.choice=oldTerms.querySelector('[data-rw-term]')?.value;}oldTerms.remove();}
      const assistant=document.createElement('details');assistant.dataset.rwTerms='';assistant.dataset.rwCase=String(id);assistant.className='rw-terms';
      const options=terms.length?terms:[...new Set([...groups].filter(([key])=>key!=='stale').map(([,g])=>g.name))];
      assistant.innerHTML=`<summary>术语助手 · 选择后插入</summary><p class="rw-hint">候选名称不等于诊断。只插入你选择的文字，插在光标或选区末尾，保留医生正文。</p><label>选择文字<select data-rw-term><option value="">请选择</option>${options.map(t=>`<option value="${esc(typeof t==='string'?t:t.text)}">${esc(typeof t==='string'?t:t.label)}</option>`).join('')}</select></label><div><button type="button" data-rw-insert disabled>插入所选文字</button><button type="button" data-rw-undo disabled>撤销本次插入</button></div><p role="status" data-rw-term-status></p>`;
      editor.after(assistant);
      const picker=assistant.querySelector('[data-rw-term]'),insert=assistant.querySelector('[data-rw-insert]'),undo=assistant.querySelector('[data-rw-undo]'),status=assistant.querySelector('[data-rw-term-status]');let insertion=view.termState.insertion||null;assistant.open=!!view.termState.open;picker.value=view.termState.choice||'';insert.disabled=!picker.value||editor.readOnly||editor.disabled;undo.disabled=!insertion;
      assistant.ontoggle=()=>{if(assistant.isConnected&&caseId===id&&isCurrent())view.termState.open=assistant.open;};
      picker.onchange=()=>{view.termState.choice=picker.value;insert.disabled=!picker.value||editor.readOnly||editor.disabled;};
      insert.onclick=()=>{insertion=insertSelectedText(editor,picker.value);view.termState.insertion=insertion;undo.disabled=!insertion;status.textContent=insertion?'已插入所选文字，原正文保留；需保存草稿。':'无法插入：请检查编辑权限、选择文字及正文长度。';};
      undo.onclick=()=>{if(!undoInsertedText(editor,insertion)){status.textContent='正文已有后续修改，保留当前文字；可在正文中手动撤销。';undo.disabled=true;return;}insertion=null;view.termState.insertion=null;undo.disabled=true;status.textContent='已撤销本次插入，原正文恢复；需保存草稿。';};
      if(!boundHosts.has(host)){
        boundHosts.add(host);host.addEventListener('scroll',()=>{if(host.querySelector('.rw-workspace'))view.position=capturePosition(host);},true);
        host.addEventListener('focusin',()=>{if(host.querySelector('.rw-workspace'))view.position=capturePosition(host);});
      }
    }
    host.querySelectorAll('[data-rw-page-group]').forEach(n=>{if(view.pageOpen.has(n.dataset.rwPageGroup))n.open=view.pageOpen.get(n.dataset.rwPageGroup);n.ontoggle=()=>view.pageOpen.set(n.dataset.rwPageGroup,n.open);});
    index.ontoggle=()=>{view.indexOpen=index.open;};
    const output=host.querySelector('.rw-output-options');output.ontoggle=()=>{view.outputOpen=output.open;};
    restorePosition(view.position,host);
  }
  return {distributions,compose,withRateMode,printEligible,waveContext,stripReviewState,reviewQueue,reviewExplanation,mountEventPreview,capturePosition,restorePosition,pageGroups,insertSelectedText,undoInsertedText,reviewWaveSvg,bindWavePreview};
})();
