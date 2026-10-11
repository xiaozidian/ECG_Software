"use strict";
/* View-only, exact beat membership. Clinical checked targets remain independent. */
((root)=>{
  const ordered=values=>[...new Set(values)].sort((a,b)=>a-b);
  const bounded=rr=>Number.isFinite(rr)&&rr>=300&&rr<=2000;
  function nn(rows,samples){
    const positions=new Map(rows.map((r,i)=>[r.sample_index,i]));
    const bins=Array.from({length:34},(_,i)=>({start_ms:300+i*50,end_ms:350+i*50,count:0,samples:[]}));
    let nonNN=0,invalid=0,pairs=0;
    for(const sample of ordered(samples)){
      const i=positions.get(sample),r=rows[i],a=rows[i-1],b=rows[i+1];
      if(!r||!a||!bounded(r.rr_ms)||a.class_code==='X'||r.class_code==='X'){invalid++;continue;}
      if(a.class_code!=='N'||r.class_code!=='N'){nonNN++;continue;}
      const bin=bins[Math.min(33,Math.floor((r.rr_ms-300)/50))];bin.count++;bin.samples.push(sample);
      if(b?.class_code==='N'&&bounded(b.rr_ms))pairs++;
    }
    return {bins,nn:bins.reduce((n,b)=>n+b.count,0),nonNN,invalid,pairs,total:ordered(samples).length};
  }
  function intersect(samples,source,partition){
    const sourceSet=new Set(source),partSet=new Set(partition),exact=ordered(samples),inSource=exact.filter(s=>sourceSet.has(s));
    const matched=inSource.filter(s=>partSet.has(s));
    return {samples:matched,total:exact.length,sourceMatched:inSource.length,crossSource:exact.length-inSource.length,otherGroups:inSource.length-matched.length};
  }
  const pageOf=(samples,page,size=32)=>samples.slice(Math.max(0,page)*size,(Math.max(0,page)+1)*size);
  const math=Object.freeze({nn,intersect,pageOf,ordered});
  root.ECGTemplateLinkedMath=math;
  if(typeof module!=='undefined')module.exports=math;
  if(typeof document==='undefined')return;
  const q=s=>document.querySelector(s),escape=s=>escapeHtml(String(s)),C=()=>root.ECGLinkedSelection;
  let rows=[],rowsKey=null,rowsPending=null,rowsError=null,rowMap=new Map(),reference=null,frame=0,pageIndex=0,cohort=null,lastCohortKey=null,drag=null,cardKey=null,cardWaves=new Map();
  let subscribed=false;
  const keyScope=scope=>JSON.stringify(scope&&[scope.caseId,scope.caseToken,scope.analysis_basis,scope.analysis_revision,scope.beatRevision]);
  const active=()=>state.currentPage==='edit'&&!!C()?.snapshot().scope&&C().snapshot().scope.caseId===state.caseId&&C().snapshot().scope.caseToken===state.caseRequestId;
  const morph=()=>typeof morphologyWorkbench!=='undefined'?morphologyWorkbench.privateSnapshot():null;
  const viewKey=()=>{const m=morph();return JSON.stringify([state.currentPage,state.editMode,m?.sourceKey,m?.partitionGeneration,m?.viewedScope,m?.leads,state.editLead,C()?.snapshot().scope?.beatRevision]);};
  const sameRows=()=>rowsKey===keyScope(C()?.snapshot().scope);
  function message(text,error=false){const e=q('#templateLinkedStatus');if(e){e.textContent=text;e.dataset.error=String(error);}}
  function schedule(){if(!frame)frame=requestAnimationFrame(()=>{frame=0;refresh();});}
  function assertResponse(scope,data){ECGAnalysisConsistency.assertSame(scope,data);if(String(data.beat_revision??data.revision)!==String(scope.beatRevision))throw Error('心搏版本已变化，请重新读取后选择');}
  async function ensureRows(){
    if(!active())return;
    const scope=C().snapshot().scope,k=keyScope(scope);if(rowsKey===k||rowsError?.key===k)return;
    if(rowsPending?.key===k&&C().isCurrent(rowsPending.ticket,k))return;
    const ticket=C().beginLane('template.rows',k,{focusSensitive:false});rowsPending={key:k,ticket};rowsError=null;
    try{
      const data=await api(ECGAnalysisConsistency.url(scope.caseId,'overview',{},scope),{signal:ticket.signal,readLane:'template-linked-rows'});
      if(!C().isCurrent(ticket,keyScope(C().snapshot().scope))||!active())return;
      assertResponse(scope,data);
      rows=data.rows.map(([sample,rr,code])=>Object.freeze({sample_index:sample,time_s:sample/200,rr_ms:rr,class_code:code}));
      if(rows.some(r=>!Number.isSafeInteger(r.sample_index)||r.sample_index<0))throw Error('逐搏位置无效，请重新读取');
      rowMap=new Map(rows.map(r=>[r.sample_index,r]));reference=nn(rows,rows.map(r=>r.sample_index));rowsKey=k;schedule();
    }catch(error){if(error.name!=='AbortError'&&C().isCurrent(ticket,keyScope(C().snapshot().scope))){rowsError={key:k,message:error.message};render();}}
    finally{if(rowsPending?.ticket===ticket)rowsPending=null;}
  }
  function getCohort(){
    const snap=C().snapshot(),m=morph();
    if(!sameRows()||!m?.ready||m.caseId!==snap.scope?.caseId||m.caseToken!==snap.scope.caseToken||String(m.analysis_basis)!==String(snap.scope.analysis_basis)||String(m.analysis_revision)!==String(snap.scope.analysis_revision)||String(m.beatRevision)!==String(snap.scope.beatRevision))return null;
    const group=m.viewedScope.kind==='group',partition=group?m.groups[m.viewedScope.slot]:m.remainder;
    if(snap.kind==='none'&&!group){
      if(snap.focusSample==null)return {samples:[],total:0,sourceMatched:0,crossSource:0,otherGroups:0,active:false,focusOnly:false,m,snap};
      const sample=snap.focusSample,exists=rowMap.has(sample);
      return {samples:exists?[sample]:[],total:1,sourceMatched:m.sourcePopulation.includes(sample)?1:0,crossSource:m.sourcePopulation.includes(sample)?0:1,otherGroups:0,active:true,focusOnly:true,m,snap};
    }
    return {...intersect(snap.kind==='samples'?snap.samples:m.sourcePopulation,m.sourcePopulation,partition),active:true,focusOnly:false,m,snap};
  }
  function sourceLabel(c){return typeof editClassLabel==='function'?editClassLabel(c.m.source):c.m.source;}
  function describe(c){
    if(c.focusOnly)return '定位 '+c.samples.length+' 搏 · 未启用集合筛选；密度仍按原集合统计';
    const density=c.m.linked;
    return (c.snap.kind==='samples'?'精确选集 '+fmtNumber(c.total)+' 搏':'当前来源 '+fmtNumber(c.total)+' 搏')+' · '+sourceLabel(c)+' · '+(c.m.viewedScope.kind==='group'?c.m.viewedScope.slot+'组':'剩余集合')+'匹配 '+fmtNumber(c.samples.length)+' 搏 · 跨来源排除 '+fmtNumber(c.crossSource)+' · 其他组排除 '+fmtNumber(c.otherGroups)+(c.snap.timeBounds?' · 显式范围 ['+formatElapsedPrecise(c.snap.timeBounds.start_s)+', '+formatElapsedPrecise(c.snap.timeBounds.end_s)+')':'')+(density?.phase==='ready'?' · 密度参与 '+fmtNumber(density.top.included)+' 搏 / 边界不足 '+fmtNumber(density.top.skipped_edges)+' 搏':density?' · 密度'+(density.phase==='loading'?'读取中':'读取失败，原分组保留'):'');
  }
  function geometry(canvas){const rect=canvas.getBoundingClientRect(),library=canvas.id==='editLibraryScatterCanvas',m=library?{l:20,r:6,t:6,b:16}:{l:31,r:9,t:10,b:22};return {...m,rect,w:Math.max(1,rect.width-m.l-m.r),h:Math.max(1,rect.height-m.t-m.b)};}
  function coordinates(event,canvas){const g=geometry(canvas),b=state.editScatterData?.bounds||{x_min:0,x_max:2000,y_min:0,y_max:2000},x=Math.max(0,Math.min(1,(event.clientX-g.rect.left-g.l)/g.w)),y=Math.max(0,Math.min(1,(event.clientY-g.rect.top-g.t)/g.h));return [b.x_min+x*(b.x_max-b.x_min),b.y_max-y*(b.y_max-b.y_min)];}
  function scatterOverlay(canvas){
    if(!active()||!sameRows()||!canvas?.getClientRects().length)return;
    const snap=C().snapshot(),g=geometry(canvas),b=state.editScatterData?.bounds;if(!b)return;
    const ctx=canvas.getContext('2d'),dpr=canvas.width/g.rect.width;ctx.save();ctx.setTransform(dpr,0,0,canvas.height/g.rect.height,0,0);
    const selected=new Set(cohort?.active&&!cohort.focusOnly?cohort.samples:[]),x=p=>g.l+(p.x-b.x_min)/(b.x_max-b.x_min)*g.w,y=p=>g.t+g.h-(p.y-b.y_min)/(b.y_max-b.y_min)*g.h;
    ctx.beginPath();ctx.rect(g.l,g.t,g.w,g.h);ctx.clip();
    for(const point of state.editScatterData.points||[]){if(!selected.has(point.sample_index)&&point.sample_index!==snap.focusSample)continue;ctx.beginPath();ctx.arc(x(point),y(point),point.sample_index===snap.focusSample?5:3,0,Math.PI*2);ctx.strokeStyle=point.sample_index===snap.focusSample?'#d17b17':'#087f7a';ctx.lineWidth=1.8;ctx.stroke();}
    if(drag?.canvas===canvas){const a=drag.first,p=drag.last;ctx.strokeStyle='#087f7a';ctx.setLineDash([4,3]);ctx.lineWidth=1.5;ctx.strokeRect(x({x:a[0]}) ,y({y:a[1]}),x({x:p[0]})-x({x:a[0]}),y({y:p[1]})-y({y:a[1]}));}
    ctx.restore();
  }
  function histogram(canvas,stats){
    if(!canvas?.getClientRects().length||!reference)return;
    const library=canvas.id==='editLibraryHistogramCanvas',height=editCanvasHeight(canvas,library?92:90,library?54:48),{ctx,width}=canvasContext(canvas,height),m=library?{l:20,r:7,t:7,b:14}:{l:34,r:10,t:7,b:17},max=Math.max(1,...reference.bins.map(b=>b.count)),w=(width-m.l-m.r)/34,h=height-m.t-m.b;
    ctx.clearRect(0,0,width,height);ctx.fillStyle='#fff';ctx.fillRect(0,0,width,height);
    reference.bins.forEach((b,i)=>{ctx.fillStyle='#c7dddd';ctx.fillRect(m.l+i*w+1,height-m.b-b.count/max*h,Math.max(1,w-2),b.count/max*h);const selected=stats?.bins[i].count||0;if(selected){ctx.fillStyle='#d68b27';ctx.fillRect(m.l+i*w+1,height-m.b-selected/max*h,Math.max(1,w-2),selected/max*h);}});
    ctx.fillStyle='#536f7c';ctx.font='11px '+UI_FONT;ctx.fillText('300',m.l,height-3);ctx.textAlign='right';ctx.fillText('2000 ms',width-m.r,height-3);ctx.textAlign='left';
    canvas.setAttribute('aria-label','全记录相邻 N-N 参考，300至2000毫秒；橙色为所选 N-N 间期，按选中搏终点统计；点击柱筛选该区间');
  }
  function invalidateRowsPresentation(){
    rows=[];rowMap=new Map();reference=null;rowsError=null;rowsKey=null;cohort=null;lastCohortKey=null;cardKey=null;cardWaves.clear();
    for(const id of ['editHistogramCanvas','editLibraryHistogramCanvas']){const canvas=q('#'+id);if(canvas)canvas.getContext('2d').clearRect(0,0,canvas.width,canvas.height);}
    q('#templateLinkedCards')?.hidePopover?.();const grid=q('#templateLinkedCardGrid');if(grid)grid.replaceChildren();
  }
  function render(){
    const entry=q('#templateLinkedOpen'),tools=q('#occurrenceViewControls');if(entry&&tools&&entry.parentElement!==tools)tools.prepend(entry);
    if(!active())return;
    if(!sameRows()){
      cohort=null;const error=rowsError?.key===keyScope(C().snapshot().scope)?rowsError:null,button=q('#templateLinkedOpen');if(button){button.disabled=!error;button.textContent=error?'联动读取失败 · 重试':'联动依据读取中';button.title=error?'重新读取当前病例与版本的完整逐搏依据':'等待当前病例与版本的完整逐搏依据';}
      for(const id of ['templateNnScope','templateLibraryNnScope']){const n=q('#'+id);if(n)n.textContent='正在读取当前全记录 N-N 参考…';}
      message(error?'联动逐搏依据读取失败：'+error.message+'；请点“联动读取失败 · 重试”，原分组保留。':'正在读取当前病例与版本的完整逐搏依据；暂不显示旧选集。',!!error);return;
    }
    cohort=getCohort();
    const stats=cohort?.active?nn(rows,cohort.samples):null;
    for(const id of ['editHistogramCanvas','editLibraryHistogramCanvas'])histogram(q('#'+id),stats);
    for(const id of ['editScatterCanvas','editLibraryScatterCanvas'])scatterOverlay(q('#'+id));
    const button=q('#templateLinkedOpen');if(button){button.disabled=!cohort;button.textContent=cohort?.active?(cohort.focusOnly?'定位搏':'联动匹配')+' '+fmtNumber(cohort.samples.length)+' · 查看':'联动选集 · 尚未选择';button.title=cohort?.active?describe(cohort):'单击定位；框选筛选完整集合；联动选集不自动加入改型目标';button.setAttribute('aria-label',button.title+'；打开独立所选搏');}
    const clear=q('#templateLinkedClear');if(clear)clear.disabled=C().snapshot().kind==='none'&&C().snapshot().focusSample==null;
    for(const id of ['templateNnScope','templateLibraryNnScope']){const n=q('#'+id);if(n)n.textContent=stats?'所选 N-N '+stats.nn+' · 非 N-N '+stats.nonNN+' · 无效/超界 '+stats.invalid+' · N-N 散点 '+stats.pairs:'全记录 N-N '+fmtNumber(reference.nn)+(C().snapshot().kind==='samples'?' · 当前来源匹配未读取':' · 尚未启用筛选');}
    if(cohort){message(cohort.active?describe(cohort):'单击仅定位并高亮；框选按完整逐搏集合筛选。联动集合不自动加入改型勾选。');}
    const newKey=JSON.stringify([keyScope(C().snapshot().scope),C().snapshot().selectionGeneration,cohort?.focusOnly?C().snapshot().focusGeneration:null,viewKey()]);
    if(lastCohortKey!==newKey){pageIndex=0;lastCohortKey=newKey;cardKey=null;cardWaves.clear();}
    if(q('#templateLinkedCards')?.matches(':popover-open'))renderCards();
  }
  function refresh(){if(!active()){C()?.cancelPresentationLanes('template.');q('#templateLinkedCards')?.hidePopover?.();return;}ensureRows();render();}
  function focusSample(sample,expected=C()?.snapshot().scope){
    if(!active()||!sameRows()||!rowMap.has(sample))return false;
    const row=rowMap.get(sample);if(!C().focus(sample,{expectedScope:expected,origin:'template-point'})){message('该搏不在当前精确选集或依据已变化；请先清除筛选或重新读取再定位。',true);return false;}
    return clinicalUI.focusLinkedBeat(sample,row.time_s,expected);
  }
  function selectSamples(samples,origin='template-filter',expected=C()?.snapshot().scope){
    if(!active()||!sameRows())return false;
    const exact=ordered(samples);if(exact.some(s=>!rowMap.has(s)))throw Error('选集含已变化的心搏，请重新读取');
    return C().select({samples:exact,timeBounds:null,sourcePopulation:rows.length,origin},{expectedScope:expected});
  }
  async function selectPolygon(polygon,expected=C()?.snapshot().scope){
    if(!active()||!sameRows())return;
    const k=viewKey(),ticket=C().beginLane('template.scatter-selection',k,{focusSensitive:false});message('正在按完整相邻 RR 数据匹配框选…');
    try{
      const result=await api('/api/cases/'+encodeURIComponent(expected.caseId)+'/scatter-selection',{method:'POST',signal:ticket.signal,body:JSON.stringify({mode:'rr',polygon,analysis_basis:expected.analysis_basis,analysis_revision:expected.analysis_revision,beat_revision:expected.beatRevision})});
      if(!C().isCurrent(ticket,viewKey())||!active())return;assertResponse(expected,result);
      if(result.exact!==true||!Array.isArray(result.sample_indices)||result.total!==result.sample_indices.length)throw Error('框选未返回完整精确集合');
      selectSamples(result.sample_indices,'template-scatter-box',expected);
    }catch(error){if(error.name!=='AbortError'&&C().isCurrent(ticket,viewKey()))message('框选未应用：'+error.message,true);}
  }
  function clear(){if(active())C().clear({expectedScope:C().snapshot().scope,origin:'template-clear'});}
  async function renderCards(){
    const panel=q('#templateLinkedCards'),c=getCohort();if(!panel)return;
    if(!c){C().cancelLane('template.cards');cardKey=null;cardWaves.clear();q('#templateLinkedCardSummary').textContent='当前来源与分组匹配尚未读取；保留权威选集，暂不显示旧匹配卡。';q('#templateLinkedCardPage').textContent='匹配读取中';q('#templateLinkedPrev').disabled=q('#templateLinkedNext').disabled=true;q('#templateLinkedCardGrid').innerHTML='<p class="empty-state">正在读取当前来源与版本…</p>';return;}
    const pages=Math.max(1,Math.ceil(c.samples.length/32));pageIndex=Math.min(pageIndex,pages-1);const samples=pageOf(c.samples,pageIndex);
    const scope=C().snapshot().scope,k=JSON.stringify([keyScope(scope),C().snapshot().selectionGeneration,c.focusOnly?C().snapshot().focusGeneration:null,viewKey(),pageIndex,state.editLead]);
    q('#templateLinkedCardSummary').textContent=describe(c)+'；仅显式勾选才加入改型目标。';q('#templateLinkedCardPage').textContent=(pageIndex+1)+' / '+pages+' 页 · '+c.samples.length+' 搏 · 每页最多32';q('#templateLinkedPrev').disabled=pageIndex===0;q('#templateLinkedNext').disabled=pageIndex>=pages-1;
    const host=q('#templateLinkedCardGrid');
    if(cardKey===k){syncCards();return;}cardKey=k;
    host.innerHTML=samples.length?samples.map(sample=>{const r=rowMap.get(sample);return `<article class="template-linked-card" data-linked-sample="${sample}"><header><button type="button" data-linked-focus="${sample}">${escape(r?.class_code||'—')} · ${formatElapsedPrecise(sample/200)}</button><label><input type="checkbox" data-linked-check="${sample}" ${state.editSelectedSamples.has(sample)?'checked':''}>加入改型选择</label></header><div data-linked-wave="${sample}">读取实际双导联波形…</div><small>RR ${fmtNumber(r?.rr_ms)} ms · 设备单位 u，电压未校准</small></article>`}).join(''):'<p class="empty-state">当前匹配集合为0搏；未回退到原全量。</p>';
    if(!samples.length)return;
    const ticket=C().beginLane('template.cards',viewKey(),{focusSensitive:c.focusOnly}),leads=ECGOccurrenceCard.leads(state.editLead||'II',2);
    try{
      const result=await api('/api/cases/'+encodeURIComponent(scope.caseId)+'/waveform-strips',{method:'POST',signal:ticket.signal,body:JSON.stringify({sample_indices:samples,leads,pre_s:.6,post_s:1,max_points:800,analysis_basis:scope.analysis_basis,analysis_revision:scope.analysis_revision,beat_revision:scope.beatRevision})});
      if(!C().isCurrent(ticket,viewKey())||cardKey!==k||!active())return;assertResponse(scope,result);
      if(result.items.length!==samples.length||result.items.some(x=>!samples.includes(x.sample_index)))throw Error('波形返回集合不完整');
      for(const item of result.items){cardWaves.set(item.sample_index,item);const target=host.querySelector('[data-linked-wave="'+item.sample_index+'"]');if(target)target.innerHTML=ECGOccurrenceCard.svg(item,{sample_index:item.sample_index,target_samples:[item.sample_index],label:item.class_code||item.label||'心搏'}, {height:96});}
      syncCards();
    }catch(error){if(error.name!=='AbortError'&&C().isCurrent(ticket,viewKey())&&cardKey===k){host.querySelectorAll('[data-linked-wave]').forEach(x=>x.textContent='波形读取失败；请关闭再打开重试。');cardKey=null;message(error.message,true);}}
  }
  function syncCards(){for(const el of document.querySelectorAll('[data-linked-sample]')){const sample=Number(el.dataset.linkedSample);el.dataset.focused=String(C().snapshot().focusSample===sample);const check=el.querySelector('[data-linked-check]');if(check)check.checked=state.editSelectedSamples.has(sample);}}
  function bindScatter(canvas){
    if(!canvas)return;canvas.style.touchAction='none';canvas.setAttribute('aria-description','单击定位；拖动矩形按完整散点数据筛选，不自动勾选改型');
    canvas.addEventListener('click',event=>{event.preventDefault();event.stopImmediatePropagation();},true);
    canvas.addEventListener('pointerdown',event=>{if(event.button!==0||!active()||!sameRows())return;event.preventDefault();const p=coordinates(event,canvas);drag={canvas,first:p,last:p,client:[event.clientX,event.clientY],expected:C().snapshot().scope};canvas.setPointerCapture(event.pointerId);},true);
    canvas.addEventListener('pointermove',event=>{if(drag?.canvas!==canvas)return;drag.last=coordinates(event,canvas);state.editMode==='library'?renderEditLibraryAnalytics():renderEditScatter();},true);
    canvas.addEventListener('pointerup',event=>{
      if(drag?.canvas!==canvas)return;const job=drag;drag=null;if(canvas.hasPointerCapture(event.pointerId))canvas.releasePointerCapture(event.pointerId);const p=coordinates(event,canvas),moved=Math.hypot(event.clientX-job.client[0],event.clientY-job.client[1]);
      if(moved>=6){selectPolygon([job.first,[p[0],job.first[1]],p,[job.first[0],p[1]]],job.expected);return;}
      const g=geometry(canvas),b=state.editScatterData?.bounds;let nearest=null,distance=14;
      for(const point of state.editScatterData?.points||[]){const x=g.rect.left+g.l+(point.x-b.x_min)/(b.x_max-b.x_min)*g.w,y=g.rect.top+g.t+g.h-(point.y-b.y_min)/(b.y_max-b.y_min)*g.h,d=Math.hypot(x-event.clientX,y-event.clientY);if(d<=distance){distance=d;nearest=point;}}
      if(nearest)focusSample(nearest.sample_index,job.expected);schedule();
    },true);
    canvas.addEventListener('pointercancel',()=>{drag=null;schedule();});
  }
  function mount(){
    if(!C()||subscribed)return;subscribed=true;
    C().subscribe((snap,detail)=>{if(detail?.change==='scope')invalidateRowsPresentation();if(detail?.change==='focus'){cohort=getCohort();renderEditScatter();renderEditLibraryAnalytics();syncCards();if(snap.kind==='none')schedule();return;}pageIndex=0;schedule();});
    morphologyWorkbench.subscribeLinked(schedule);const methodSummary=q('.morph-method-details>summary');if(methodSummary)methodSummary.textContent='来源、联动统计与保存说明';
    const open=document.createElement('button');open.id='templateLinkedOpen';open.type='button';open.className='text-button';open.textContent='联动选集 · 尚未选择';open.setAttribute('aria-controls','templateLinkedCards');
    const heading=q('#editGalleryTitle')?.closest('.edit-panel-heading');if(heading)heading.append(open);
    const panel=document.createElement('section');panel.id='templateLinkedCards';panel.className='template-linked-selected';panel.setAttribute('popover','manual');panel.setAttribute('aria-label','独立联动选集，原事件列表不变');
    panel.innerHTML='<header><h2>独立所选搏</h2><button type="button" id="templateLinkedClose" class="button secondary">关闭</button></header><p id="templateLinkedCardSummary"></p><div class="template-linked-card-tools"><button type="button" id="templateLinkedPrev">上一页</button><output id="templateLinkedCardPage"></output><button type="button" id="templateLinkedNext">下一页</button><button type="button" id="templateLinkedClear">清除联动筛选</button></div><div id="templateLinkedCardGrid"></div>';
    q('#page-edit').append(panel);open.onclick=()=>{if(!sameRows()){rowsError=null;ensureRows();schedule();return;}panel.showPopover();renderCards();q('#templateLinkedClose').focus();};q('#templateLinkedClose').onclick=()=>{C().cancelLane('template.cards');cardKey=null;panel.hidePopover();open.focus();};
    q('#morphRetry')?.addEventListener('click',()=>{rowsError=null;schedule();});q('#templateLinkedPrev').onclick=()=>{pageIndex=Math.max(0,pageIndex-1);cardKey=null;renderCards();};q('#templateLinkedNext').onclick=()=>{pageIndex++;cardKey=null;renderCards();};q('#templateLinkedClear').onclick=clear;
    panel.addEventListener('click',event=>{const b=event.target.closest('[data-linked-focus]');if(b)focusSample(Number(b.dataset.linkedFocus));});
    panel.addEventListener('change',event=>{const e=event.target;if(e.hasAttribute('data-linked-check')){const sample=Number(e.dataset.linkedCheck);if(!sameRows()||!rowMap.has(sample)||!clinicalUI.setLinkedChecked(sample,e.checked,C().snapshot().scope)){e.checked=state.editSelectedSamples.has(sample);message('改型勾选未应用：当前依据已变化，请重新读取',true);}syncCards();}});
    panel.addEventListener('keydown',event=>{if(['n','s','v','x','p','o','backspace'].includes(event.key.toLowerCase())&&!event.target.closest('input,select,textarea'))event.stopPropagation();if(event.key==='Escape'){event.preventDefault();event.stopPropagation();q('#templateLinkedClose').click();}});
    const status=document.createElement('p');status.id='templateLinkedStatus';status.className='template-linked-status';status.setAttribute('role','status');q('.morph-method-details')?.append(status);
    for(const [id,noticeId] of [['editHistogramCanvas','templateNnScope'],['editLibraryHistogramCanvas','templateLibraryNnScope']]){
      const canvas=q('#'+id);if(!canvas)continue;const article=canvas.closest('article'),h=article.querySelector('h2'),p=article.querySelector('.edit-panel-heading p');if(h)h.textContent='N-N 参考与所选集';if(p)p.textContent='全记录相邻 N-N；按所选搏终点叠加，不计算新诊断';
      const notice=document.createElement('p');notice.id=noticeId;notice.className='template-linked-nn';canvas.after(notice);canvas.tabIndex=0;
      canvas.addEventListener('click',event=>{if(!active()||!sameRows()||!reference)return;const r=canvas.getBoundingClientRect(),library=id.includes('Library'),left=library?20:34,right=library?7:10,index=Math.floor((event.clientX-r.left-left)/(r.width-left-right)*34);if(index>=0&&index<34)selectSamples(reference.bins[index].samples,'template-nn-bin');});
      canvas.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();clear();}});
    }
    bindScatter(q('#editScatterCanvas'));bindScatter(q('#editLibraryScatterCanvas'));
    const oldScatter=renderEditScatter;renderEditScatter=()=>{oldScatter();scatterOverlay(q('#editScatterCanvas'));};
    const oldAnalytics=renderEditLibraryAnalytics;renderEditLibraryAnalytics=()=>{oldAnalytics();if(sameRows()){const c=getCohort();histogram(q('#editLibraryHistogramCanvas'),c?.active?nn(rows,c.samples):null);}scatterOverlay(q('#editLibraryScatterCanvas'));};
    const oldOverview=renderEditOverview;renderEditOverview=()=>{oldOverview();if(sameRows()){const c=getCohort();histogram(q('#editHistogramCanvas'),c?.active?nn(rows,c.samples):null);}};
    document.addEventListener('change',event=>{if(['editLeadSelect','editLibraryLeadSelect'].includes(event.target.id))schedule();});
    window.addEventListener('resize',schedule);schedule();
  }
  root.ECGTemplateLinkedView=Object.freeze({refresh,schedule,render,focusSample,selectPolygon,selectSamples,clear,stats:()=>cohort?.active?nn(rows,cohort.samples):null,context:()=>cohort?Object.freeze({...cohort,samples:Object.freeze([...cohort.samples])}):null,math});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount);else mount();
})(globalThis);
