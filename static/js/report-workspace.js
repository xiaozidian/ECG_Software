"use strict";
/* Web-only composition and linked distribution controls, separate from paper geometry. */
globalThis.ECGReportWorkspace=(()=>{
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let filter='all',reviewFilter='all',caseId=null;
  let view={expanded:new Set(),active:null,position:null,pageOpen:new Map(),waveHeights:new Map(),termState:{}},previewToken=0;
  const boundHosts=new WeakSet();
  const positionSelectors=['.v2-event-detail','.rw-selected-strips','.rw-strip-index nav','.rw-rail nav','.rw-page-options','.rw-wave-scroll','.v2-event-list'];
  let waveSvgId=0;
  function preciseTime(seconds){if(!Number.isFinite(seconds)||seconds<0)return '—';const ms=Math.round(seconds*1000),day=Math.floor(ms/86400000)+1,t=ms%86400000;return `D${day} ${[Math.floor(t/3600000),Math.floor(t%3600000/60000),Math.floor(t%60000/1000)].map(v=>String(v).padStart(2,'0')).join(':')}.${String(t%1000).padStart(3,'0')}`;}
  // Render only the channel arrays supplied by the source. No missing lead is synthesized here.
  function reviewWaveSvg(wave,event=null,options={}){
    const card=globalThis.ECGOccurrenceCard||(typeof require==='function'?require('./occurrence-card.js'):null);
    const count=Object.keys(wave.leads||{}).length,preview=typeof document!=='undefined'?document.querySelector('.rw-event-preview-dialog[open] [data-rw-preview-wave]'):null;
    const available=Number(options.height)||(preview?preview.clientHeight-38:count*70+48),height=Math.max(count*56+(count>6?24:0)+24,available);
    const recordStart=options.recordStart??(typeof state!=='undefined'?state.caseData?.metadata?.start_time:null);
    // One full-width clock for every lead. Short viewports scroll the rows;
    // they never halve the time axis or squeeze the channels to fit a page.
    return card.svg(wave,event||{}, {...options,width:options.width||preview?.clientWidth||1000,height,recordStart,inset:options.inset??24,timeAxis:true,columns:1}).replace('<svg ',`<svg class="rw-twelve-wave" style="height:${height}px" data-review-lead-count="${count}" `);
  }
  // Pointer enlargement belongs only to the visible SVG. Table inclusion stays immediate.
  function bindWavePreview(host,open,isCurrent=()=>true){
    host._rwWaveOpen=open;host._rwWaveCurrent=isCurrent;
    if(!host.hasAttribute('tabindex'))host.setAttribute('tabindex','0');
    host.setAttribute('aria-description','波形只读复核；双击具体波形或 Shift+Enter 查看本图条。左侧列表单击或勾选入报。');
    if(host._rwWaveBound)return;host._rwWaveBound=true;
    host.addEventListener('click',event=>{if(event.target.closest?.('svg')&&host.contains(event.target)){event.stopPropagation();if(host._rwWaveCurrent())host.focus({preventScroll:true});}},true);
    host.addEventListener('dblclick',event=>{if(event.button!==0||!event.target.closest?.('svg')||!host.contains(event.target)||!host._rwWaveCurrent())return;event.preventDefault();event.stopPropagation();host._rwWaveOpen?.();},true);
  }
  function bindTwelveWave(host,{wave,readWave,isCurrent=()=>true,recordStart=null,domain=null,event=null}){
    const open=mountEventPreview(host,{event,title:'12 导联 · 同一记录时间窗',isCurrent,
      loadWave:async()=>{const full=await readWave();if(!isCurrent())throw Error('病例或标注依据已变化，请重新打开波形');
        const names=Object.keys(full.leads||{});if(!['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6'].every(n=>names.includes(n)))throw Error('来源没有提供完整十二导联，未补绘');
        if(Math.abs(full.start_s-wave.start_s)>.005||Math.abs(full.duration_s-wave.duration_s)>.005||full.sample_rate_hz!==wave.sample_rate_hz)throw Error('十二导联时间窗或采样率与原图不一致，未显示');
        globalThis.ECGAnalysisConsistency?.assertSame(wave,full);return full;},
      renderWave:full=>reviewWaveSvg(full,event,{recordStart,domain})});
    if(typeof beatEditor!=='undefined')beatEditor.bindWaveSurface(host,{wave,isCurrent,onPreview:open,readOnly:typeof state!=='undefined'&&state.currentPage==='report'});
    return open;
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
  function mountEventPreview(host,{event,loadWave,renderWave,isCurrent=()=>true,title='12 导联事件复核',loadingLabel='正在读取 12 导联…'}){
    host.querySelector('[data-rw-event-preview]')?.remove();
    const open=()=>{
      if(!isCurrent()||!host.isConnected||document.querySelector('dialog[open]'))return;
      const root=host.closest('#reportV2Content')||host,position=capturePosition(root),token=++previewToken;
      position.focus=host;
      const dialog=document.createElement('dialog');dialog.className='rw-event-preview-dialog';dialog.dataset.reportFullscreen='true';dialog.setAttribute('aria-labelledby','rwEventPreviewTitle');
      dialog.innerHTML=`<header><div><h2 id="rwEventPreviewTitle">${esc(title)}</h2><p>${esc(event?.label||'连续波形')}${event?.time_s!==undefined?' · '+esc(formatElapsed(event.time_s)):''}</p></div><button type="button" data-rw-close>返回事件列表</button></header><p class="rw-hint">只读查看；返回后保留原筛选与位置。</p><div data-rw-preview-wave role="status">${esc(loadingLabel)}</div>`;
      document.body.append(dialog);dialog.querySelector('[data-rw-close]').onclick=()=>dialog.close();
      dialog.addEventListener('close',()=>{if(token===previewToken)previewToken++;dialog.remove();if(isCurrent())restorePosition(position);},{once:true});
      dialog.showModal();
      const target=dialog.querySelector('[data-rw-preview-wave]');
      function load(){
        target.textContent=loadingLabel;
        Promise.resolve().then(loadWave).then(wave=>{
          if(!dialog.open||token!==previewToken)return;
          if(!isCurrent()){target.textContent='当前病例或依据已变化，请关闭后重新选择事件。';return;}
          target.removeAttribute('role');target.innerHTML=waveContext({waveform:wave},renderWave(wave));
          if(typeof beatEditor!=='undefined')beatEditor.bindWaveSurface(target,{wave,isCurrent:()=>dialog.open&&token===previewToken&&isCurrent(),readOnly:true,previewLabel:'返回原波形',onPreview:()=>dialog.close()});
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
    bindWavePreview(host,open,isCurrent);
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
    const ticks=Array.from({length:8},(_,i)=>i*duration/7),recordStart=typeof state!=='undefined'?state.caseData?.metadata?.start_time:null,tools=globalThis.ECGReviewTools,domain=/data-amplitude-domain="([0-9.]+)"/.exec(waveSvg)?.[1];
    return `${reviewNote?`<p class="rw-wave-context" data-rhythm-review-note><strong>${esc(reviewNote)}</strong></p>`:''}<p class="rw-wave-context" data-wave-metadata>${esc(tools.waveMeta(wave,recordStart,domain))} · ${count} 搏${spec.warning?' · '+esc(spec.warning):''}</p><div class="rw-wave-scroll" tabindex="0" role="region" aria-label="单列连续波形；短窗口可上下滚动"><div class="rw-wave-canvas">${waveSvg}</div></div>`;
  }
  function bars(title,rows,selected,attribute){
    const max=Math.max(1,...rows.map(x=>x.count));
    return `<section class="rw-distribution"><header><strong>${title}</strong><span>次数 · 最大 ${max}</span></header><div class="rw-bars" style="--bar-count:${rows.length}">${rows.map((r,i)=>`<button type="button" ${attribute}="${esc(r.key??i)}" aria-pressed="${String(selected===String(r.key??i))}" aria-label="${esc(r.label)}：${r.count} 次，${r.count?'点击筛选':'没有候选'}" title="${esc(r.label)} · ${r.count} 次 · ${r.count?'仅筛选显示，不改变已选图条':'此分箱没有候选事件'}" ${r.count?'':'disabled'}><span class="rw-bar-count">${r.count}</span><i style="height:${r.count/max*64}px;--rw-bar-size:${r.count/max*64}px"></i><span class="rw-bar-label${attribute==='data-hour-bin'&&i%Math.max(1,Math.ceil(rows.length/7))!==0&&i!==rows.length-1?' rw-sparse-tick':''}">${attribute==='data-hour-bin'?r.label.split(' ').map(part=>`<span class="rw-clock-part">${esc(part)}</span>`).join(''):esc(r.label)}</span></button>`).join('')}</div></section>`;
  }
  function distributions(host,data,{mode,range,pauseBand,category,labels,change}){
    const rows=category==='pause'?data.pause_distribution.bins.map((b,i)=>({key:'b'+i,count:b.count,label:b.label})):Object.entries(data.subtype_counts).map(([key,count])=>({key,count,label:labels[key]||key}));
    const time=data.time_bins||[],active=time.findIndex(b=>range&&b.start_s===range[0]&&b.end_s===range[1]);
    host.innerHTML=bars('事件数量分布',rows,category==='pause'?pauseBand:mode,'data-pattern-bin')+bars('时间分布 · 按记录时钟逐小时',time,String(active),'data-hour-bin')+`<div class="rw-filter-status"><span role="status">${mode==='all'?'全部亚型':esc(labels[mode]||mode)} · ${active>=0?esc(time[active].label)+' 时段':'全部时间'} · ${data.total} 条${data.candidate_spacing_s?` · 定位点间隔 ≥${data.candidate_spacing_s} 秒`:''}</span><button type="button" data-clear-bins ${mode==='all'&&!range&&pauseBand==='all'&&!data.candidate_spacing_s?'disabled':''}>清除筛选</button></div><p class="rw-hint">点击柱形筛选左侧事件；亚型与小时可组合。柱图为实际日期和钟点；左表 D1 为记录起点后的时长。跨时段事件按起点归属；模式可能重叠，不相加。</p>`;
    host.onclick=e=>{const b=e.target.closest('button');if(!b||b.disabled)return;if(b.hasAttribute('data-clear-bins'))change({mode:'all',range:null,pauseBand:'all',spacing:0});if(b.dataset.patternBin!==undefined)change(category==='pause'?{pauseBand:b.dataset.patternBin}:{mode:b.dataset.patternBin});if(b.dataset.hourBin!==undefined){const bin=time[Number(b.dataset.hourBin)];change({range:[bin.start_s,bin.end_s]})}};
    if(category==='pause'){
      host.insertAdjacentHTML('beforeend',`<details class="rr-stat-config"><summary>配置互斥统计边界（不改检测阈值）</summary><div>${data.pause_distribution.edges_ms.map((v,i)=>`<label>边界 ${i+1}（秒）<input type="number" data-stat-edge="${i}" step="0.001" min="0.001" max="60" value="${v/1000}"></label>`).join('')}<button type="button" data-stat-apply>应用统计边界</button></div><p role="status" data-stat-status></p></details><p class="rw-hint">${esc(data.pause_distribution.method)} 恰好 2.5 秒可进入统计；原候选池仍严格 &gt;2.5 秒。柱图数量与检测候选数可能不同，临床定义待签核。</p>`);
      host.querySelector('[data-stat-apply]').onclick=()=>{try{const edges=ECGOverviewEngine.pauseEdges([...host.querySelectorAll('[data-stat-edge]')].map(x=>Math.round(Number(x.value)*1000)));change({pauseEdges:edges});}catch(error){host.querySelector('[data-stat-status]').textContent=error.message;}};
    }
    const clear=host.querySelector('[data-clear-bins]');if(clear)clear.title=clear.disabled?'当前没有亚型、时段或间隔筛选':'仅清除显示筛选，保留已选图条与诊断复核';
  }
  function releaseTerminology(host){
    host?._rwTerminologyController?.destroy();
    host?._rwTerminologyRestoreLayout?.();
    if(host){delete host._rwTerminologyController;delete host._rwTerminologyRestoreLayout;}
  }
  function getTerminologyUsages(host){return host?._rwTerminologyController?.getUsages()??(host?._rwTerminologyUsages?structuredClone(host._rwTerminologyUsages):null);}
  function sortSelections(selected,lookup,order){
    if(!['time','type'].includes(order))throw Error('无效的图条排序');
    const keys=['fastest','slowest','S','V','pause','rr_candidate','rate','AF','ST','other'],rank=e=>{const i=keys.indexOf(e.category);return i<0?keys.length:i;};
    return selected.map((s,i)=>({s,i,e:lookup.get(s.event_id)})).sort((a,b)=>{
      if(!a.e||!b.e)return Number(!a.e)-Number(!b.e)||a.i-b.i;
      const type=order==='type'?(rank(a.e)-rank(b.e)||String(a.e.subtype).localeCompare(String(b.e.subtype))):0;
      return type||a.e.time_s-b.e.time_s||a.i-b.i;
    }).map(r=>r.s);
  }
  function stripActions(i,status){
    const stale=status==='stale';
    return '<details class="rw-strip-tools" data-rw-tools="'+i+'"><summary>图条操作</summary><div class="rw-strip-options" aria-label="本条图条操作">'+
      [['three','3L · II / V1 / V5'],['all','12L'],['one','1L · II'],['preview','查看图条'],['edit','编辑图条'],['rename','重命名'],['print','取消 / 恢复打印'],['remove','删除图条（可撤销）']].map(([key,label])=>'<button type="button" data-rw-strip-action="'+key+'" data-rw-strip="'+i+'"'+(stale&&key!=='remove'?' disabled':'')+'>'+label+'</button>').join('')+'</div></details>';
  }
  function compose(host,{id,composition,selected,lookup,sections,onPages,onMode,onPreview,onStripLeads,onStripEdit,onStripPrint,onStripRemove,onSort,onTemplates,loadTrend,renderWave,loadWave,renderAdvanced,terms=[],overview=null,isCurrent=()=>true,termContext=null,onUsages=null,showTerminology=false,showAdvanced=false,recordStart=null}){
    releaseTerminology(host);
    // Hiding the assistant does not discard versioned text already saved in a report.
    host._rwTerminologyUsages=composition.terminology_usages??null;
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
    const queue=reviewQueue(selected,lookup,filter,reviewFilter),counts=queue.counts;
    const visible=queue.visible.filter(r=>!view.timeRange||r.e&&r.e.time_s>=view.timeRange[0]&&r.e.time_s<view.timeRange[1]);
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
        <header class="rw-heading"><div><h2>报告编排</h2><p><span data-rw-visible-count>${visible.length}</span> 条图条 · <span data-rw-page-count>${composition.included_pages.length}</span> 类报告页</p></div><div class="rw-sort-controls" aria-label="全部已选图条排序"><span>全部图条排序</span><button type="button" data-rw-sort="type">按类型</button><button type="button" data-rw-sort="time">按时间</button><button type="button" data-paper-preview>预览 A4</button></div></header>
        <div class="rw-columns">
          <section class="rw-evidence" aria-label="已入报证据"><header class="rw-evidence-heading"><h3>入报图条</h3><span>共 ${selected.length} 条</span></header>
            <div class="rw-selected-strips">${visible.map(({s,i,e,status})=>`<article class="rw-strip" data-rw-key="${esc(s.event_id)}"><header><strong>${i+1}. ${esc(s.caption||e?.label||'已失效图条')}</strong><span>${e?formatElapsed(e.time_s):'需重新选择'}</span>${stripActions(i,status)}</header><div class="rw-mini-wave" data-rw-mini="${i}" aria-label="图条 ${i+1} 的已选导联">${status==='stale'?'依据已失效，须重新核对':'可见时读取本条真实波形…'}</div><small class="rw-mini-range" data-rw-mini-range="${i}">本条显示与入报 ${esc((s.leads||composition.strip_defaults?.leads||['II','V1','V5']).join(' / '))}</small><div class="rw-strip-actions"><button type="button" data-rw-toggle="${i}" aria-expanded="${view.expanded.has(s.event_id)}" aria-controls="rwStripBody${i}">${view.expanded.has(s.event_id)?'折叠波形':'展开波形'}</button><button type="button" data-back-event="${i}">回看事件</button></div><div id="rwStripBody${i}" class="rw-strip-body" ${view.expanded.has(s.event_id)?'':'hidden'}><div data-rw-wave="${i}">${e?'读取波形…':'依据已变化，请移除后重新选择'}</div><label>图注<input data-caption="${i}" maxlength="500" value="${esc(s.caption)}"></label></div></article>`).join('')||'<div class="rw-empty"><strong>尚无入报图条</strong><p>在事件选图中核对波形，再加入报告草稿。</p><button type="button" data-category="fastest">前往事件选图</button></div>'}</div>
          </section>
          <section id="rwConclusionSlot" class="rw-conclusion-pane" aria-label="报告结论编辑"></section>
        </div>
      </div>
    </div>`;
    if(overview){const panel=document.createElement('aside');panel.className='rw-overview';panel.setAttribute('aria-label','全记录统计总览');panel.innerHTML=`<h3>全记录统计总览</h3><p>当前依据 r${esc(overview.revision??'—')} · 已确认结果</p><table><thead><tr><th>分类</th><th>次数</th><th>搏数</th></tr></thead><tbody>${overview.categories.map(row=>`<tr><th>${esc(row.label)}</th><td>${esc(row.events??'—')}</td><td>${esc(row.beats??'—')}</td></tr>`).join('')}</tbody></table><p>统计独立于选图。未确认候选不计作确诊。</p><section><h4>源报告独立对照</h4><dl><div><dt>有效心搏</dt><dd>${esc(overview.source.total_beats??'—')}</dd></div><div><dt>平均心率</dt><dd>${ECGReviewTools.bpm(overview.source.avg_hr)} bpm</dd></div><div><dt>SDNN</dt><dd>${esc(overview.source.sdnn_ms??'—')} ms</dd></div></dl><p>保留源报告摘要；不改写为当前修订统计或诊断。</p></section>`;host.querySelector('.rw-main').append(panel);}
    host.querySelector('.rw-rail fieldset').insertAdjacentHTML('beforeend','<p class="rw-hint">仅影响本次输出，保留所有选图、图注和区间。</p>');
    host.querySelector('.rw-evidence-heading').append(host.querySelector('.rw-sort-controls'));
    host.querySelector('.rw-evidence-heading').insertAdjacentHTML('afterend',`<section class="rw-review-queue" aria-label="入报图条复核状态"><nav aria-label="按复核状态筛选">${Object.entries(reviewLabels).map(([key,label])=>`<button type="button" data-review-filter="${key}" aria-pressed="${reviewFilter===key}">${label} <b>${counts[key]}</b></button>`).join('')}</nav><p role="status">${esc(filter==='all'?'全部类型':groups.get(filter).name)} · ${reviewLabels[reviewFilter]} · 显示 ${visible.length} / ${selected.length} 条</p>${filter!=='all'||reviewFilter!=='all'?'<button type="button" data-clear-strip-filters>显示全部已选图条</button>':''}</section>`);
    if(!visible.length&&selected.length)host.querySelector('.rw-selected-strips').innerHTML='<p class="empty-state">当前组合没有匹配图条；其他已选图条仍保留。可切换状态或显示全部已选图条。</p>';
    if(composition.paper?.voltage_estimate)host.querySelector('.rw-heading').insertAdjacentHTML('afterend',`<p class="rw-hint">导出图条使用独立保存的${esc(ECGVoltage.note(composition.paper.voltage_estimate))}网页预览仍为自适应幅度；请在“导联 / 区间”调整导出增益，并用 A4 预览核对。</p>`);
    visible.forEach(({i,e,status})=>{
      const node=host.querySelector(`[data-rw-wave="${i}"]`),included=printEligible(e,composition.fast_slow_mode),back=host.querySelector(`[data-back-event="${i}"]`);
      node.closest('.rw-strip').querySelector('header').insertAdjacentHTML('afterend',`<p class="rw-print-status" data-review-status="${status}" title="${esc(reviewExplanation(status,e))}">${reviewLabels[status]}${status==='stale'?' · 须重新核对，不能导出':''}${included?'':' · 本次不输出，选图仍保留'}</p>`);
      back.disabled=status==='stale';back.title=status==='stale'?'旧依据无法回看；有对应节律片段时请使用复核片段入口，否则重新筛选':'回看此图条对应的事件';
    });
    visible.forEach(({i,e})=>{if(e?.category==='AF'&&e.rhythm_episode_id)host.querySelector(`[data-back-event="${i}"]`).insertAdjacentHTML('afterend',`<button type="button" data-review-rhythm="${i}">保存草稿并复核片段</button>`);});
    if(showAdvanced&&renderAdvanced){const panel=document.createElement('div');panel.className='rw-research';host.querySelector('.rw-workspace').append(panel);renderAdvanced(panel);}
    function redraw(selector){
      compose(host,{id,composition,selected,lookup,sections,onPages,onMode,onPreview,onStripLeads,onStripEdit,onStripPrint,onStripRemove,onSort,onTemplates,loadTrend,renderWave,loadWave,renderAdvanced,terms,overview,isCurrent,termContext,onUsages,showTerminology,showAdvanced});
      host.querySelector(selector)?.focus({preventScroll:true});
    }
    host.querySelectorAll('[data-strip-filter]').forEach(b=>b.onclick=()=>{filter=b.dataset.stripFilter;redraw('[data-strip-filter][aria-pressed="true"]')});
    host.querySelectorAll('[data-review-filter]').forEach(b=>b.onclick=()=>{reviewFilter=b.dataset.reviewFilter;redraw('[data-review-filter][aria-pressed="true"]')});
    host.querySelector('[data-clear-strip-filters]')?.addEventListener('click',()=>{filter='all';reviewFilter='all';view.timeRange=null;redraw('[data-review-filter="all"]')});
    if(loadTrend){
      const timeline=document.createElement('details');timeline.className='rw-curation-timeline';timeline.open=Boolean(view.timelineOpen||view.timeRange);timeline.ontoggle=()=>{view.timelineOpen=timeline.open;};timeline.setAttribute('aria-label','已选图条时间分布与全程心率');timeline.innerHTML='<summary>已选图条时间分布 · 展开筛选</summary><p>正在读取全程时间轴…</p>';host.querySelector('.rw-selected-strips').before(timeline);
      Promise.resolve().then(loadTrend).then(data=>{
        if(!timeline.isConnected||!isCurrent())return;
        const total=data.duration_s;if(!Number.isFinite(total)||total<=0)throw Error('记录时长无效');
        const bins=Array.from({length:24},(_,i)=>({start:i*total/24,end:(i+1)*total/24,count:0}));
        selected.forEach(s=>{const e=lookup.get(s.event_id);if(e&&e.time_s>=0&&e.time_s<total)bins[Math.min(23,Math.floor(e.time_s/total*24))].count++;});const max=Math.max(1,...bins.map(b=>b.count));
        const rows=ECGOverviewEngine.decode(data),valid=rows.filter(ECGOverviewEngine.valid),maxHR=valid.reduce((m,r)=>Math.max(m,Math.ceil(r.hr/50)*50),100);
        const buckets=Array.from({length:800},()=>null);valid.forEach(r=>{if(r.time_s<0||r.time_s>=total)return;const i=Math.min(799,Math.floor(r.time_s/total*800)),b=buckets[i]||(buckets[i]={lo:r.hr,hi:r.hr});b.lo=Math.min(b.lo,r.hr);b.hi=Math.max(b.hi,r.hr);});
        const x=t=>44+t/total*940,y=hr=>68-hr/maxHR*56;
        timeline.innerHTML=`<header><strong>已选图条时间分布</strong><span>${view.timeRange?esc(formatElapsed(view.timeRange[0]))+'–'+esc(formatElapsed(view.timeRange[1])):'全记录'} · 仅筛选显示，保留所有入报选择</span><button type="button" data-curation-clear ${view.timeRange?'':'disabled'}>全程</button></header><div class="rw-curation-bins">${bins.map((b,i)=>`<button type="button" data-curation-timebin="${i}" aria-pressed="${view.timeRange?.[0]===b.start}" aria-label="${esc(formatElapsed(b.start))} 至 ${esc(formatElapsed(b.end))}，已选 ${b.count} 条" ${b.count?'':'disabled'}><span>${b.count||''}</span><i style="height:${Math.max(1,b.count/max*28)}px"></i></button>`).join('')}</div><svg viewBox="0 0 1000 90" role="img" aria-label="全记录有效 RR 导出的心率，纵轴 bpm；每列保留该时段最小最大值，空白表示无有效间期"><rect x="44" y="10" width="940" height="58" fill="#fff"/>${[0,maxHR/2,maxHR].map(hr=>`<path d="M44 ${y(hr)}H984" stroke="#d8e1e6"/><text x="39" y="${y(hr)+3}" text-anchor="end" font-size="10">${Math.round(hr)}</text>`).join('')}${buckets.map((b,i)=>b?`<path d="M${44+(i+.5)/800*940} ${y(b.lo)}V${y(b.hi)+.5}" stroke="#245f7d" stroke-width="1.1"/>`:'').join('')}${selected.map(s=>lookup.get(s.event_id)).filter(Boolean).map(e=>`<path d="M${x(e.time_s)} 8v5" stroke="#af5d17"/>`).join('')}${Array.from({length:5},(_,i)=>`<text x="${44+i*940/4}" y="84" font-size="10" text-anchor="${i===0?'start':i===4?'end':'middle'}">${esc(formatElapsed(total*i/4))}</text>`).join('')}<text x="5" y="9" font-size="9">bpm</text></svg>`;
        const summary=document.createElement('summary');summary.textContent='已选图条时间分布 · 展开筛选';timeline.prepend(summary);
        timeline.querySelector('[data-curation-clear]').onclick=()=>{view.timeRange=null;redraw('[data-review-filter="all"]');};timeline.querySelectorAll('[data-curation-timebin]').forEach(b=>b.onclick=()=>{const bin=bins[Number(b.dataset.curationTimebin)];view.timeRange=[bin.start,bin.end];redraw('[data-review-filter][aria-pressed="true"]');});
      }).catch(error=>{if(timeline.isConnected&&isCurrent()){
        const summary=document.createElement('summary');summary.textContent='时间轴读取失败 · 展开详情';
        const detail=document.createElement('p');detail.textContent=error.message;
        timeline.replaceChildren(summary,detail);
      }});
    }
    host.querySelectorAll('[data-report-page]').forEach(el=>el.onchange=()=>{
      composition.included_pages=[...host.querySelectorAll('[data-report-page]:checked')].map(x=>x.dataset.reportPage);
      host.querySelector('[data-rw-page-count]').textContent=composition.included_pages.length;host.querySelector('.rw-output-options summary span').textContent=composition.included_pages.length+' 类页';
      host.querySelectorAll('[data-rw-page-group]').forEach(group=>{group.querySelector('summary').textContent=`${group.dataset.rwPageGroup} · ${group.querySelectorAll('input:checked').length} / ${group.querySelectorAll('input').length}`;});
      onPages(composition.included_pages);
    });
    host.querySelectorAll('[name=rwRateMode]').forEach(el=>el.onchange=()=>onMode(el.value));
    host.querySelector('[data-paper-preview]').onclick=onPreview;
    const templateButton=document.createElement('button');templateButton.type='button';templateButton.textContent='综述模板';templateButton.onclick=()=>{if(isCurrent())onTemplates?.();};host.querySelector('.rw-sort-controls').append(templateButton);
    if(host._rwOutsideMenu)document.removeEventListener('pointerdown',host._rwOutsideMenu,true);
    host._rwOutsideMenu=e=>{if(host.isConnected&&!e.target.closest?.('.rw-strip-tools'))host.querySelectorAll('.rw-strip-tools[open]').forEach(n=>n.open=false);};document.addEventListener('pointerdown',host._rwOutsideMenu,true);
    // The conclusion editor is a live node: move, never recreate its unsaved text.
    const dock=document.querySelector('.report-conclusion-dock');if(dock){
      const disclosure=document.createElement('details');disclosure.className='rw-conclusion-disclosure';
      disclosure.open=view.conclusionOpen??!globalThis.matchMedia?.('(min-width:1100px) and (max-height:820px)').matches;
      disclosure.innerHTML='<summary>报告结论 · 展开编辑</summary>';
      disclosure.ontoggle=()=>{view.conclusionOpen=disclosure.open;disclosure.querySelector('summary').textContent=disclosure.open?'报告结论 · 收起编辑':'报告结论 · 展开编辑';};
      host.querySelector('#rwConclusionSlot').append(disclosure);disclosure.append(dock);dock.hidden=false;
    }
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
      node.dataset.loaded='loading';node.textContent='正在读取本条真实波形…';
      return readRow(row).then(entry=>{if(!node.isConnected||caseId!==id||!isCurrent())return;const projected=globalThis.ECGReportStripEditor.project(entry),domain=ECGReviewTools.waveDomain(entry.waveform,JSON.stringify([id,row.e.event_id,row.e.basis_version,'selected-strip'])),card=globalThis.ECGOccurrenceCard||(typeof require==='function'?require('./occurrence-card.js'):null),many=projected.strip.leads.length>6;node.closest('.rw-strip').classList.toggle('rw-many-leads',many);const height=Math.max(100,projected.strip.leads.length*(many?56:44)+24);node.style.height=height+'px';node.style.minHeight=height+'px';node.innerHTML=card.svg(projected.waveform,row.e,{width:Math.max(240,node.clientWidth||600),height,timeAxis:true,columns:1,recordStart,domain});node.dataset.loaded='ready';host.querySelector(`[data-rw-mini-range="${i}"]`).textContent=`${preciseTime(entry.waveform.start_s)} — ${preciseTime(entry.waveform.start_s+entry.waveform.duration_s)} · ${entry.strip.visible_beat_count} 搏 · 本条显示与入报 ${entry.strip.leads.join(' / ')} · 设备单位 u，未校准`;const open=mountEventPreview(node,{event:row.e,title:'12 导联 · 本条入报时间窗',loadingLabel:'正在读取十二导联…',loadWave:()=>Promise.resolve(entry.waveform),renderWave:wave=>reviewWaveSvg(wave,row.e,{recordStart,domain}),isCurrent:()=>node.isConnected&&caseId===id&&isCurrent()});bindWavePreview(node,open,()=>node.isConnected&&caseId===id&&isCurrent());if(typeof beatEditor!=='undefined')beatEditor.bindWaveSurface(node,{wave:projected.waveform,onPreview:open,readOnly:true,isCurrent:()=>node.isConnected&&caseId===id&&isCurrent()});}).catch(error=>{if(!node.isConnected||caseId!==id||!isCurrent())return;delete node.dataset.loaded;node.textContent='图条读取失败：'+error.message;const retry=document.createElement('button');retry.type='button';retry.textContent='重试本条波形';retry.onclick=()=>loadMini(row);node.append(retry);});
    }
    if(typeof IntersectionObserver!=='undefined'){view.miniObserver=new IntersectionObserver(entries=>entries.forEach(entry=>{if(entry.isIntersecting){const row=visible.find(r=>String(r.i)===entry.target.dataset.rwMini);if(row)loadMini(row);}}),{root:host.querySelector('.rw-selected-strips'),rootMargin:'0px'});host.querySelectorAll('[data-rw-mini]').forEach(node=>view.miniObserver.observe(node));}else visible.forEach(loadMini);
    function loadRow(row){
      const {s,i,e,status}=row,node=host.querySelector(`[data-rw-wave="${i}"]`);
      if(node.dataset.loaded)return;
      if(status==='stale'){node.dataset.loaded='stale';node.textContent=e?.category==='AF'&&e.rhythm_episode_id?'图条依据已失效。请保存草稿并复核片段，返回后核对并替换原图条；导联和图注保留。':'原事件已不存在或依据已失效。请重新筛选事件；移除前可保留人工图注。';return;}
      if(view.waveHeights.has(s.event_id))node.style.minHeight=view.waveHeights.get(s.event_id)+'px';
      node.dataset.loaded='loading';node.textContent='读取波形…';
      return readRow(row).then(entry=>{if(node.isConnected&&caseId===id&&isCurrent()){const projected=globalThis.ECGReportStripEditor.project(entry),domain=ECGReviewTools.waveDomain(entry.waveform,JSON.stringify([id,e.event_id,e.basis_version,'selected-strip']));node.innerHTML=waveContext(entry,reviewWaveSvg(projected.waveform,e,{recordStart,domain,width:node.clientWidth||1000}));bindTwelveWave(node,{wave:projected.waveform,readWave:()=>Promise.resolve(entry.waveform),recordStart,domain,isCurrent:()=>node.isConnected&&caseId===id&&isCurrent(),event:e});node.dataset.loaded='ready';node.style.minHeight='';}}).catch(error=>{
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
      host.querySelectorAll('[data-rw-sort]').forEach(button=>button.onclick=()=>{if(isCurrent())onSort?.(button.dataset.rwSort);});
    visible.forEach(row=>{
      const card=host.querySelector('[data-rw-key="'+CSS.escape(row.s.event_id)+'"]'),tools=card.querySelector('[data-rw-tools]');
      card.tabIndex=0;card.setAttribute('aria-description','右键或 Shift+F10 打开图条操作；也可使用图条操作按钮。');
      const open=event=>{globalThis.ECGReportStripEditor.menu({card,event,isCurrent,actions:[...tools.querySelectorAll('[data-rw-strip-action]')].map(b=>({label:b.textContent,disabled:b.disabled,run:()=>b.click()}))});};
      tools.querySelector('summary').onclick=event=>{event.preventDefault();open(event);};
      card.oncontextmenu=event=>{if(event.target.closest('input,textarea,select,[contenteditable]'))return;event.preventDefault();open(event);};
      card.onkeydown=event=>{if(event.key==='ContextMenu'||event.shiftKey&&event.key==='F10'){event.preventDefault();open();}if(event.key==='Escape'){tools.open=false;globalThis.ECGReportStripEditor.closeMenu();}};
      card.classList.toggle('rw-print-disabled',row.s.print_enabled===false);
      if(row.s.print_enabled===false)card.querySelector('.rw-print-status').append(' · 已取消打印（选图保留）');
      tools.querySelector('[data-rw-strip-action=print]').textContent=row.s.print_enabled===false?'恢复打印':'取消打印';
      tools.querySelectorAll('[data-rw-strip-action]').forEach(button=>button.onclick=async()=>{
        if(!isCurrent())return;const action=button.dataset.rwStripAction;tools.open=false;
        if(action==='edit'){onStripEdit?.(row.i);return;}
        if(action==='print'){onStripPrint?.(row.i,row.s.print_enabled===false);return;}
        if(action==='remove'){onStripRemove?.(row.i);return;}
        if(action==='rename'){expand(row,true);const input=card.querySelector('[data-caption]');input.focus();input.select();return;}
        if(action==='preview'){
          const mini=card.querySelector('[data-rw-mini]');
          try{if(!mini._rwOpenPreview)await loadMini(row);if(isCurrent())mini._rwOpenPreview?.();}catch(error){handleError(error);}return;
        }
        onStripLeads?.(row.i,action==='one'?['II']:action==='three'?['II','V1','V5']:[...ECGReportEngine.leads]);
      });
    });
    host.querySelectorAll('[data-rw-index]').forEach(b=>b.onclick=()=>focusStrip(visible.find(r=>r.i===Number(b.dataset.rwIndex))));
    host.querySelector('[data-rw-evidence]').onclick=()=>{const row=visible.find(r=>r.s.event_id===view.active)||visible[0];if(row)focusStrip(row);};
    host.querySelector('[data-rw-evidence]').disabled=!visible.length;
    const editor=dock?.querySelector('#conclusionEditor');
    host.querySelector('[data-rw-conclusion]').disabled=!editor;
    host.querySelector('[data-rw-conclusion]').onclick=()=>{const disclosure=editor?.closest('.rw-conclusion-disclosure');if(disclosure)disclosure.open=true;editor?.scrollIntoView({block:'center'});editor?.focus({preventScroll:true});};
    const save=document.querySelector('#reportSaveState');host.querySelector('[data-rw-save-state]').textContent=save?.textContent||'';
    if(save){view.saveObserver?.disconnect();view.saveObserver=new MutationObserver(()=>{const target=host.querySelector('[data-rw-save-state]');if(target)target.textContent=save.textContent;});view.saveObserver.observe(save,{childList:true,characterData:true,subtree:true});}
    if(editor){
      const oldTerms=dock.querySelector('[data-rw-terms]');if(oldTerms){if(oldTerms.dataset.rwCase===String(id)){view.termState.open=oldTerms.open;view.termState.choice=oldTerms.querySelector('[data-rw-term]')?.value;}oldTerms._rwTerminologyController?.destroy();oldTerms.remove();}
      if(showTerminology){
      const assistant=document.createElement('details');assistant.dataset.rwTerms='';assistant.dataset.rwCase=String(id);assistant.className='rw-terms';
      editor.after(assistant);assistant.open=!!view.termState.open;
      const termsCurrent=()=>assistant.isConnected&&caseId===id&&dock.querySelector('#conclusionEditor')===editor&&isCurrent();
      assistant.ontoggle=()=>{if(termsCurrent())view.termState.open=assistant.open;};
      if(termContext&&globalThis.ECGTerminologyTree?.mount){
        assistant.classList.add('rw-versioned-terms');
        const previousColumns=dock.style.getPropertyValue('grid-template-columns'),previousRows=dock.style.getPropertyValue('grid-template-rows');
        dock.style.gridTemplateColumns='minmax(0,1fr)';dock.style.gridTemplateRows='auto minmax(120px,1fr) auto auto';
        host._rwTerminologyRestoreLayout=()=>{if(previousColumns)dock.style.gridTemplateColumns=previousColumns;else dock.style.removeProperty('grid-template-columns');if(previousRows)dock.style.gridTemplateRows=previousRows;else dock.style.removeProperty('grid-template-rows');};
        assistant.style.gridColumn='1 / -1';assistant.style.gridRow='4';assistant.style.height='auto';assistant.style.maxHeight='40dvh';
        const summary=document.createElement('summary');summary.textContent='术语树 · 示例 / 待核准';
        const treeHost=document.createElement('div');treeHost.dataset.rwTermTree='';
        assistant.append(summary,treeHost);
        const controller=globalThis.ECGTerminologyTree.mount(treeHost,{
          editor,caseId:id,reportContext:termContext.reportContext??'draft',api:termContext.api,
          usages:composition.terminology_usages||[],isCurrent:termsCurrent,
          onUsageDirty:usages=>{if(!termsCurrent())return;composition.terminology_usages=usages;host._rwTerminologyUsages=usages;onUsages?.(usages);}
        });
        const columns=treeHost.querySelector('.tt-columns');if(columns&&treeHost.clientWidth>0&&treeHost.clientWidth<380)columns.style.gridTemplateColumns='minmax(0,1fr)';
        host._rwTerminologyController=controller;assistant._rwTerminologyController=controller;
      }else{
        const options=terms.length?terms:[...new Set([...groups].filter(([key])=>key!=='stale').map(([,g])=>g.name))];
        assistant.innerHTML=`<summary>术语助手 · 选择后插入</summary><p class="rw-hint">候选名称不等于诊断。只插入你选择的文字，插在光标或选区末尾，保留医生正文。</p><label>选择文字<select data-rw-term><option value="">请选择</option>${options.map(t=>`<option value="${esc(typeof t==='string'?t:t.text)}">${esc(typeof t==='string'?t:t.label)}</option>`).join('')}</select></label><div><button type="button" data-rw-insert disabled>插入所选文字</button><button type="button" data-rw-undo disabled>撤销本次插入</button></div><p role="status" data-rw-term-status></p>`;
        const picker=assistant.querySelector('[data-rw-term]'),insert=assistant.querySelector('[data-rw-insert]'),undo=assistant.querySelector('[data-rw-undo]'),status=assistant.querySelector('[data-rw-term-status]');let insertion=view.termState.insertion||null;picker.value=view.termState.choice||'';insert.disabled=!picker.value||editor.readOnly||editor.disabled;undo.disabled=!insertion;
        picker.onchange=()=>{if(!termsCurrent())return;view.termState.choice=picker.value;insert.disabled=!picker.value||editor.readOnly||editor.disabled;};
        insert.onclick=()=>{if(!termsCurrent())return;insertion=insertSelectedText(editor,picker.value);view.termState.insertion=insertion;undo.disabled=!insertion;status.textContent=insertion?'已插入所选文字，原正文保留；需保存草稿。':'无法插入：请检查编辑权限、选择文字及正文长度。';};
        undo.onclick=()=>{if(!termsCurrent())return;if(!undoInsertedText(editor,insertion)){status.textContent='正文已有后续修改，保留当前文字；可在正文中手动撤销。';undo.disabled=true;return;}insertion=null;view.termState.insertion=null;undo.disabled=true;status.textContent='已撤销本次插入，原正文恢复；需保存草稿。';};
      }
      }
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
  return {preciseTime,sortSelections,distributions,compose,withRateMode,printEligible,waveContext,stripReviewState,reviewQueue,reviewExplanation,mountEventPreview,capturePosition,restorePosition,pageGroups,insertSelectedText,undoInsertedText,reviewWaveSvg,bindWavePreview,bindTwelveWave,releaseTerminology,getTerminologyUsages};
})();
