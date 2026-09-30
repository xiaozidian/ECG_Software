"use strict";
/* Web-only composition and linked distribution controls, separate from paper geometry. */
globalThis.ECGReportWorkspace=(()=>{
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let filter='all',reviewFilter='all',caseId=null;
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
    return `<section class="rw-distribution"><header><strong>${title}</strong><span>次数 · 最大 ${max}</span></header><div class="rw-bars" style="--bar-count:${rows.length}">${rows.map((r,i)=>`<button type="button" ${attribute}="${esc(r.key??i)}" aria-pressed="${String(selected===String(r.key??i))}" aria-label="${esc(r.label)}：${r.count} 次，点击筛选" ${r.count?'':'disabled'}><span class="rw-bar-count">${r.count}</span><i style="height:${r.count/max*64}px"></i><span class="rw-bar-label">${attribute==='data-hour-bin'?r.label.split(' ').map(part=>`<span class="rw-clock-part">${esc(part)}</span>`).join(''):esc(r.label)}</span></button>`).join('')}</div></section>`;
  }
  function distributions(host,data,{mode,range,pauseBand,category,labels,change}){
    const rows=category==='pause'?Object.entries(data.pause_counts).map(([key,count])=>({key,count,label:{all:'全部 >2.5s',over3:'其中 >3s','2.5to3':'2.5–3s'}[key]})):Object.entries(data.subtype_counts).map(([key,count])=>({key,count,label:labels[key]||key}));
    const time=data.time_bins||[],active=time.findIndex(b=>range&&b.start_s===range[0]&&b.end_s===range[1]);
    host.innerHTML=bars('事件数量分布',rows,category==='pause'?pauseBand:mode,'data-pattern-bin')+bars('时间分布 · 按记录时钟逐小时',time,String(active),'data-hour-bin')+`<div class="rw-filter-status"><span role="status">${mode==='all'?'全部亚型':esc(labels[mode]||mode)} · ${active>=0?esc(time[active].label)+' 时段':'全部时间'} · ${data.total} 条${data.candidate_spacing_s?` · 定位点间隔 ≥${data.candidate_spacing_s} 秒`:''}</span><button type="button" data-clear-bins ${mode==='all'&&!range&&pauseBand==='all'&&!data.candidate_spacing_s?'disabled':''}>清除筛选</button></div><p class="rw-hint">点击柱形筛选左侧事件；亚型与小时可组合。柱图为实际日期和钟点；左表 D1 为记录起点后的时长。跨时段事件按起点归属；模式可能重叠，不相加。</p>`;
    host.onclick=e=>{const b=e.target.closest('button');if(!b||b.disabled)return;if(b.hasAttribute('data-clear-bins'))change({mode:'all',range:null,pauseBand:'all',spacing:0});if(b.dataset.patternBin!==undefined)change(category==='pause'?{pauseBand:b.dataset.patternBin}:{mode:b.dataset.patternBin});if(b.dataset.hourBin!==undefined){const bin=time[Number(b.dataset.hourBin)];change({range:[bin.start_s,bin.end_s]})}};
  }
  function compose(host,{id,composition,selected,lookup,sections,onPages,onMode,onPreview,renderWave,loadWave,renderAdvanced}){
    const oldDock=document.querySelector('.report-conclusion-dock');if(oldDock&&host.contains(oldDock))host.before(oldDock);
    if(caseId!==id){caseId=id;filter='all';reviewFilter='all'}
    const groups=new Map();selected.forEach(s=>{const e=lookup.get(s.event_id),key=e?e.category+':'+e.subtype:'stale';const g=groups.get(key)||{name:e?.category==='AF'?(e.subtype==='AFL'?'房扑':'房颤'):e?.label||'原事件不可用',count:0};g.count++;groups.set(key,g)});
    if(filter!=='all'&&!groups.has(filter))filter='all';
    const {visible,counts}=reviewQueue(selected,lookup,filter,reviewFilter);
    host.innerHTML=`<div class="rw-workspace"><aside class="rw-rail"><section><h3>图条类型</h3><nav aria-label="已入报图条筛选"><button data-strip-filter="all" aria-pressed="${filter==='all'}">全部 <b>${selected.length}</b></button>${[...groups].map(([k,g])=>`<button data-strip-filter="${esc(k)}" aria-pressed="${filter===k}">${esc(g.name)} <b>${g.count}</b></button>`).join('')}</nav></section><fieldset><legend>最快 / 最慢心率图条打印模式</legend>${[['rr','仅 RR'],['nn','仅 NN'],['both','RR 与 NN']].map(([v,l])=>`<label><input type="radio" name="rwRateMode" value="${v}" ${composition.fast_slow_mode===v?'checked':''}>${l} 最快 / 最慢心率</label>`).join('')}</fieldset><section><h3>报告页</h3><p class="rw-hint">按本次检查需要勾选。未满足条件的项目不生成诊断页。</p><div class="rw-page-options">${sections.map(s=>`<label title="${esc(s.reason||'')}"><input type="checkbox" data-report-page="${s.key}" ${composition.included_pages.includes(s.key)?'checked':''} ${s.available?'':'disabled'}><span>${esc(s.title)}${s.available?'':`<small>${esc(s.reason)}</small>`}</span></label>`).join('')}</div></section></aside><div class="rw-main"><header class="rw-heading"><div><h2>入报图条复核</h2><p>网页筛选与编排 · ${visible.length} 条图条 · ${composition.included_pages.length} 类报告页</p></div><button type="button" data-paper-preview>预览 A4 导出版</button></header><div class="rw-selected-strips">${visible.map(({s,i,e})=>`<article class="rw-strip"><header><strong>${esc(s.caption||e?.label||'已失效图条')}</strong><span>${e?formatElapsed(e.time_s):'需重新选择'}</span><button type="button" data-back-event="${i}">回看事件</button><button type="button" data-category="strips">导联 / 区间</button><button type="button" data-remove="${i}">移除</button></header><div data-rw-wave="${i}">${e?'读取波形…':'依据已变化，请移除后重新选择'}</div><label>图注<input data-caption="${i}" maxlength="500" value="${esc(s.caption)}"></label></article>`).join('')||'<p class="empty-state">尚无入报图条。请在事件页核对波形后勾选“入报”。</p>'}</div><div id="rwConclusionSlot"></div></div></div>`;
    host.querySelector('.rw-rail fieldset').insertAdjacentHTML('beforeend','<p class="rw-hint">只控制最快 / 最慢图条的输出，不删除已选图条或已编辑内容。</p>');
    host.querySelector('.rw-heading').insertAdjacentHTML('afterend',`<section class="rw-review-queue" aria-label="入报图条复核状态"><nav aria-label="按复核状态筛选">${Object.entries(reviewLabels).map(([key,label])=>`<button type="button" data-review-filter="${key}" aria-pressed="${reviewFilter===key}">${label} <b>${counts[key]}</b></button>`).join('')}</nav><p role="status">${esc(filter==='all'?'全部类型':groups.get(filter).name)} · ${reviewLabels[reviewFilter]} · 显示 ${visible.length} / ${selected.length} 条</p><p class="rw-hint">状态计数涵盖全部已选图条，可与左侧类型组合；仅筛选显示，不移除选图。事件确认不代表报告已审核。</p>${filter!=='all'||reviewFilter!=='all'?'<button type="button" data-clear-strip-filters>显示全部已选图条</button>':''}</section>`);
    if(!visible.length&&selected.length)host.querySelector('.rw-selected-strips').innerHTML='<p class="empty-state">当前组合没有匹配图条；其他已选图条仍保留。可切换状态或显示全部已选图条。</p>';
    if(composition.paper?.voltage_estimate)host.querySelector('.rw-heading').insertAdjacentHTML('afterend',`<p class="rw-hint">导出图条使用独立保存的${esc(ECGVoltage.note(composition.paper.voltage_estimate))}网页预览仍为自适应幅度；请在“导联 / 区间”调整导出增益，并用 A4 预览核对。</p>`);
    visible.forEach(({i,e,status})=>{
      const node=host.querySelector(`[data-rw-wave="${i}"]`),included=printEligible(e,composition.fast_slow_mode),back=host.querySelector(`[data-back-event="${i}"]`);
      node.insertAdjacentHTML('beforebegin',`<p class="rw-print-status">原图条 ${i+1} · ${reviewLabels[status]}，${reviewExplanation(status,e)}。${included?'本次打印模式保留此图条':'本次打印模式不输出此图条；选图、图注和区间仍保留'}</p>`);
      back.disabled=status==='stale';back.title=status==='stale'?'旧依据无法回看；有对应节律片段时请使用复核片段入口，否则重新筛选':'回看此图条对应的事件';
    });
    visible.forEach(({i,e})=>{if(e?.category==='AF'&&e.rhythm_episode_id)host.querySelector(`[data-back-event="${i}"]`).insertAdjacentHTML('afterend',`<button type="button" data-review-rhythm="${i}">保存草稿并复核片段</button>`);});
    if(renderAdvanced){const panel=document.createElement('div');host.querySelector('.rw-heading').after(panel);renderAdvanced(panel);}
    function redraw(selector){
      compose(host,{id,composition,selected,lookup,sections,onPages,onMode,onPreview,renderWave,loadWave,renderAdvanced});
      host.querySelector(selector)?.focus({preventScroll:true});
    }
    host.querySelectorAll('[data-strip-filter]').forEach(b=>b.onclick=()=>{filter=b.dataset.stripFilter;redraw('[data-strip-filter][aria-pressed="true"]')});
    host.querySelectorAll('[data-review-filter]').forEach(b=>b.onclick=()=>{reviewFilter=b.dataset.reviewFilter;redraw('[data-review-filter][aria-pressed="true"]')});
    host.querySelector('[data-clear-strip-filters]')?.addEventListener('click',()=>{filter='all';reviewFilter='all';redraw('[data-review-filter="all"]')});
    host.querySelectorAll('[data-report-page]').forEach(el=>el.onchange=()=>{
      composition.included_pages=[...host.querySelectorAll('[data-report-page]:checked')].map(x=>x.dataset.reportPage);
      host.querySelector('.rw-heading p').textContent=`网页筛选与编排 · ${visible.length} 条图条 · ${composition.included_pages.length} 类报告页`;
      onPages(composition.included_pages);
    });
    host.querySelectorAll('[name=rwRateMode]').forEach(el=>el.onchange=()=>onMode(el.value));
    host.querySelector('[data-paper-preview]').onclick=onPreview;
    // The conclusion editor is a live node: move, never recreate its unsaved text.
    const dock=document.querySelector('.report-conclusion-dock');if(dock){host.querySelector('#rwConclusionSlot').append(dock);dock.hidden=false;}
    visible.forEach(({s,i,e,status})=>{const node=host.querySelector(`[data-rw-wave="${i}"]`);if(status==='stale'){node.textContent=e?.category==='AF'&&e.rhythm_episode_id?'图条依据已失效。请保存草稿并复核片段，返回后核对并替换原图条；导联和图注保留。':'原事件已不存在或依据已失效。请重新筛选事件；移除前可保留人工图注。';return;}loadWave(e,s).then(entry=>{if(node.isConnected)node.innerHTML=waveContext(entry,renderWave(entry))}).catch(error=>{if(node.isConnected)node.textContent='读取失败：'+error.message})});
  }
  return {distributions,compose,withRateMode,printEligible,waveContext,stripReviewState,reviewQueue,reviewExplanation};
})();
