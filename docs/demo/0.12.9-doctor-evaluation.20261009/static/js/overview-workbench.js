"use strict";
/* Hospital overview: a single time cursor, full-cohort plots and reversible review. */
const overviewWorkbench=(()=>{
  const E=ECGOverviewEngine,qs=s=>document.querySelector(s),esc=escapeHtml;
  const ui={id:null,revision:null,rows:[],rhythm:null,range:null,hour:0,af:false,episode:null,ratio:false,log:false,hist:null,bin:null,mode:'rr',bound:2000,size:1.4,guides:true,selectionMode:'box',scatter:[],polygon:[],contextTime:0,ruler:null,rulerPoints:[],showEvents:true,loadToken:0,densityToken:0,densityKey:null,density:null};
  const geometries=new WeakMap(),run=fn=>Promise.resolve().then(fn).catch(handleError),copy=x=>JSON.parse(JSON.stringify(x));
  let coverage=null,coveragePage=0,coverageBusy=false,coverageMessage='',coverageRun=0,coverageFocus=-1,overviewReady=false;
  let episodeFilter='all',episodePage=0,episodeNavigation=0,episodeEditor=null;
  let linked=null;
  const episodeDrafts=new Map();
  const request=(path,options)=>api(`/api/cases/${state.caseId}/${path}`,options);
  const button=(label,action,attrs='')=>`<button type="button" data-ov="${action}" ${attrs}>${label}</button>`;
  const duration=()=>state.caseData?.technical.duration_seconds_raw||1;
  const span=()=>ui.range||[state.start,Math.min(duration(),state.start+state.duration)];
  const linkedTimeSpan=()=>linked?.active()&&linked.snapshot().timeBounds?[linked.snapshot().timeBounds.start_s,linked.snapshot().timeBounds.end_s]:null;
  const hour=()=>Math.min(Math.floor(state.start/3600)*3600,Math.max(0,duration()-Math.min(3600,duration())));
  const name=x=>x==='AF'?'房颤':'房扑';
  const statusName=x=>({pending:'待复核',confirmed:'医生确认',excluded:'已排除'})[x]||x;
  function lane(id,label,kind,minutes=false){return `<section class="ov-lane"><header><h2>${label}</h2><output data-coordinate="${id}"></output>${button('操作','menu-'+kind,`aria-label="${label}操作" data-canvas="${id}"`)}</header><canvas id="${id}" height="76" tabindex="0" data-ov-plot="${kind}" ${minutes?'data-hour="1"':''} aria-label="${label}；点击定位，拖动选区，右键或 Shift+F10 打开操作"></canvas></section>`}
  function drawOverviewMini(canvas,strip){
    if(innerWidth<1100)return renderStripCanvas(canvas,strip);
    const dpr=Math.min(devicePixelRatio||1,2),width=Math.max(120,Math.floor(canvas.getBoundingClientRect().width)),height=84,gutter=22;
    canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);const ctx=canvas.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);ctx.fillStyle='#fff';ctx.fillRect(0,0,width,height);
    const entries=globalThis.ECGChartInspection?.entries(strip.leads||{})||Object.entries(strip.leads||{}),rowHeight=height/Math.max(entries.length,1),plotWidth=width-gutter,duration=Math.max(strip.duration_s,.001),anchor=gutter+strip.anchor_offset_s/duration*plotWidth;
    ctx.strokeStyle='rgba(228,141,127,.17)';ctx.lineWidth=1;for(let x=gutter;x<width;x+=plotWidth/20){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,height);ctx.stroke();}
    ECGReviewTools.markCanvas(ctx,anchor,0,height,editEffectiveCode(strip));
    entries.forEach(([lead,values],j)=>{const baseline=rowHeight*(j+.55),scale=rowHeight*.27/1000;ctx.strokeStyle='#1f2c32';ctx.lineWidth=.85;ctx.beginPath();values.forEach((value,i)=>{const x=gutter+i/Math.max(values.length-1,1)*plotWidth,y=baseline-Number(value)*scale;i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();ctx.fillStyle='#f4faf9';ctx.fillRect(0,j*rowHeight,gutter,rowHeight);ctx.fillStyle='#087777';ctx.font=`700 9px ${UI_FONT}`;ctx.fillText(lead,3,j*rowHeight+11);if(j<entries.length-1){ctx.strokeStyle='#e5ebed';ctx.beginPath();ctx.moveTo(0,(j+1)*rowHeight);ctx.lineTo(width,(j+1)*rowHeight);ctx.stroke();}});
  }
  function mount(){
    const page=qs('#page-review'),grid=page.querySelector('.analysis-grid');if(!grid)return;
    page.classList.add('overview-workbench');
    const tools=document.createElement('div');tools.className='ov-commandbar';tools.innerHTML=`<div><strong>全程总览</strong><output id="ovStatus" aria-live="polite">正在读取逐搏数据</output></div><div>${button('房颤 / 房扑分析','af-open','class="button secondary"')}${button('跳转时间','jump')}${button('清除选区','clear-range')}<output id="ovRange"></output></div>`;grid.before(tools);
    const settings=document.createElement('details');settings.className='ov-settings';settings.innerHTML='<summary>病例信息 / 波形设置</summary><div></div>';settings.lastElementChild.append(qs('#caseHero'),page.querySelector('.review-toolbar'));tools.firstElementChild.append(settings);
    const histogram=document.createElement('section');histogram.className='ov-histogram';histogram.innerHTML=`<header><div role="group" aria-label="直方图类型">${button('全程 RR 直方图','hist-rr','aria-pressed="true"')}${button('全程 R/R 直方图','hist-ratio','aria-pressed="false"')}</div><label><input id="ovLog" type="checkbox">优化显示（对数）模式</label><output id="ovHistInfo">横轴 RR（ms）· 纵轴心搏数</output></header><canvas id="ovHistogram" height="104" tabindex="0" aria-label="全程 RR 直方图，点击柱形筛选心搏；左右键切换柱形"></canvas>`;grid.before(histogram);
    const trends=document.createElement('div');trends.className='ov-trends';trends.innerHTML=lane('ovFullHR','全程心率趋势图','hr')+lane('ovHourHR','小时心率趋势图','hr',true)+lane('ovFullRR','全程 RR 散点图','rr')+lane('ovHourRR','小时 RR 散点图','rr',true);
    const main=grid.querySelector('.analysis-main');main.prepend(trends);main.querySelector('.trend-strip-card').classList.add('ov-legacy-trend');
    const stats=document.createElement('section');stats.className='ov-statistics';stats.innerHTML='<h2>结论统计 · 全程参考</h2><dl id="ovStatistics"></dl><details><summary>查看统计口径与限制</summary><p>全程诊断统计保留原口径，不随浏览选集改变。源报告单独保留；当前统计与报告按同一修订重算。长 RR 为候选，不等同确诊停搏。</p><p id="ovStatisticsMethod"></p></details>';grid.querySelector('.scatter-review-card').after(stats);
    const scatterHead=document.createElement('div');scatterHead.className='ov-scatter-options';scatterHead.innerHTML=`<label>范围<select id="ovScatterRange"><option value="2000">0–2000 ms</option><option value="3000">0–3000 ms</option><option value="5000">0–5000 ms</option></select></label>${button('散点操作','menu-scatter','data-canvas="scatterCanvas" aria-label="Lorenz 散点图操作"')}<output id="ovScatterCount"></output>`;qs('.scatter-plot-pane').prepend(scatterHead);
    const modePicker=document.createElement('label');modePicker.className='ov-scatter-mode-picker';modePicker.innerHTML=`类型<select id="ovScatterMode" aria-label="散点图类型">${[...qs('.scatter-mode-grid').querySelectorAll('[data-scatter-mode]')].map(b=>`<option value="${esc(b.dataset.scatterMode)}">${esc(b.textContent)}</option>`).join('')}</select>`;qs('.scatter-mode-grid').before(modePicker);modePicker.querySelector('select').onchange=e=>{const b=[...qs('.scatter-mode-grid').querySelectorAll('[data-scatter-mode]')].find(b=>b.dataset.scatterMode===e.target.value);if(b)b.click();};
    qs('#scatterCanvas').dataset.ovPlot='scatter';qs('#scatterCanvas').setAttribute('aria-label','Lorenz 相邻 RR 散点图；拖动框选，右键或 Shift+F10 编辑选中心搏');
    const navigator=document.createElement('details');navigator.className='ov-navigator';navigator.open=innerWidth<=1000||innerHeight>780;navigator.innerHTML='<summary><strong>连续波形导航 · II</strong><output id="ovNavigatorTime"></output></summary><canvas id="ovNavigator" height="60" tabindex="0" aria-label="当前窗口前后连续波形导航；点击定位，左右键移动"></canvas>';navigator.addEventListener('toggle',()=>{if(navigator.open)run(navigatorWave)});qs('#waveformCard').after(navigator);
    const af=document.createElement('section');af.id='ovAF';af.hidden=true;af.innerHTML=`<header class="ov-af-heading"><div><h2>房颤 / 房扑编辑与分析</h2><p>RR 散点定位 → 原始波形核对 → 医生确认片段</p></div><div>${button('返回总览','af-close')}${button('重分析 RR 候选','af-screen')}${button('撤销','af-undo')}${button('重做','af-redo')}</div></header>${lane('ovAFFull','全程 RR 散点图','rr')}<div class="ov-af-grid"><aside><section class="ov-af-lorenz"><h3>相邻 RR 散点 · 选中时段</h3><canvas id="ovAFLorenz" height="230" tabindex="0" data-ov-plot="scatter" aria-label="房颤时段 Lorenz 散点图"></canvas></section><section class="ov-episodes"><header><h3>房颤 / 房扑片段</h3>${button('添加片段','af-add')}</header><output id="ovAFSummary"></output><div class="ov-episode-table"><table><thead><tr><th>开始 / 持续</th><th>类型</th><th>状态</th></tr></thead><tbody id="ovEpisodeRows"></tbody></table></div></section></aside><div><div class="ov-af-hour">${button('前一小时','af-prev')}<output id="ovAFHour"></output>${button('后一小时','af-next')}</div>${[0,1,2,3].map(i=>lane('ovQuarter'+i,'15 分钟 RR · '+(i+1),'rr')).join('')}<div id="ovEpisodeEditor"></div></div></div><div id="ovAFWaveHost"></div><p class="ov-method">RR 自动筛查只提示不规则候选，未识别 P 波，不能区分所有早搏、伪差或房扑；确认后才计入医生确认负荷。原始 DATA / EBI 保持只读。</p>`;grid.after(af);
    const menu=document.createElement('div');menu.id='ovMenu';menu.className='ov-menu';menu.hidden=true;menu.setAttribute('popover','manual');menu.setAttribute('role','menu');document.body.append(menu);
    const dialog=document.createElement('dialog');dialog.id='ovDialog';dialog.className='ov-dialog';document.body.append(dialog);
    const coverageHost=document.createElement('section');coverageHost.id='ovAFCoverage';coverageHost.className='ov-af-coverage';coverageHost.setAttribute('aria-label','RR 筛查覆盖检查');af.firstElementChild.after(coverageHost);
    const gapNav=document.createElement('nav');gapNav.id='ovAFGapNavigation';gapNav.className='ov-af-gap-nav';gapNav.hidden=true;gapNav.setAttribute('aria-label','未评估时段导航');qs('#ovAFWaveHost').before(gapNav);
    const evidence=document.createElement('section');evidence.id='ovAFWindowEvidence';evidence.className='ov-af-window-evidence';evidence.hidden=true;evidence.tabIndex=-1;evidence.setAttribute('aria-label','当前筛查窗口依据');qs('#ovAFWaveHost').before(evidence);
    const queueControls=document.createElement('div');queueControls.className='ov-episode-controls';queueControls.innerHTML='<label for="ovEpisodeFilter">复核队列</label><select id="ovEpisodeFilter"></select>';
    qs('.ov-episode-table').before(queueControls);
    const pages=document.createElement('nav');pages.id='ovEpisodePages';pages.className='ov-episode-pages';pages.setAttribute('aria-label','房颤片段列表分页');qs('.ov-episode-table').after(pages);
    const episodeNav=document.createElement('nav');episodeNav.id='ovEpisodeNavigation';episodeNav.className='ov-episode-navigation';episodeNav.tabIndex=-1;episodeNav.setAttribute('aria-label','房颤片段连续复核');qs('#ovAFWaveHost').before(episodeNav);
    const reportBack=document.createElement('button');reportBack.type='button';reportBack.id='ovReturnReport';reportBack.hidden=true;reportBack.textContent='返回入报图条';reportBack.onclick=()=>{rememberEpisodeForm();run(()=>clinicalUI.returnFromRhythm());};qs('.ov-af-heading>div:last-child').prepend(reportBack);
    const context=document.createElement('output');context.id='ovFocusContext';context.className='ov-focus-context';context.setAttribute('aria-label','当前复核对象');qs('.scatter-card-header').after(context);
    const density=document.createElement('details');density.id='ovLinkedDensity';density.className='ov-linked-density';density.setAttribute('aria-label','同一心搏集合的双导联密度');
    density.innerHTML=`<summary><strong>联动形态密度 · II / V1</strong><span id="ovLinkedStatus" role="status" aria-live="polite">正在读取完整心搏集合</span></summary><header>${button('重新读取','linked-reload')}<span>展开密度图可拖动框选形态集合</span></header><div class="ov-linked-density-plots">${['II','V1'].map(lead=>`<figure><figcaption><strong>${lead}</strong><output data-ov-density-count="${lead}"></output></figcaption><canvas id="ovLinkedDensity${lead}" data-ov-density="${lead}" tabindex="0" aria-label="${lead} 真实心搏密度，拖动框选形态集合"></canvas></figure>`).join('')}</div><p>与分布、高亮、小波形共用精确心搏集合。R 对齐 ±1 s；去固定基线，不逐搏归一化；幅度为未校准设备单位。</p>`;
    main.querySelector('.ov-trends').after(density);
    density.addEventListener('toggle',()=>requestAnimationFrame(()=>{linked?.draw();draw();}));
    if(globalThis.ECGOverviewLinkedView&&globalThis.ECGLinkedSelection){
      linked=globalThis.ECGOverviewLinkedView.create({getState:()=>state,api,qs,esc,formatTime:formatElapsed,formatNumber:fmtNumber,getMode:()=>ui.mode,drawChanged:()=>draw(),drawStrip:drawOverviewMini,getMiniHeight:()=>innerWidth>=1100?112:154,invalidateLegacy:invalidateScatterStripLoads,onSnapshot:(snapshot,event)=>{if(event.change!=='focus'){ui.range=snapshot.origin==='overview-time-range'&&snapshot.timeBounds?[snapshot.timeBounds.start_s,snapshot.timeBounds.end_s]:null;if(snapshot.origin!=='overview-histogram')ui.bin=null;if(!String(snapshot.origin||'').startsWith('overview-'))ui.polygon=[];}}});
      globalThis.ecgOverviewLinked=linked;
      renderScatterSelectionList=()=>linked.renderMini();
      new IntersectionObserver(entries=>{if(entries.some(entry=>entry.isIntersecting))linked.renderMini();}).observe(qs('#scatterSelectionList'));
    }
    // The desktop shell mounts its evidence tabs in the same DOMContentLoaded
    // turn. Keep their real nodes and handlers, then place them beside the plot.
    requestAnimationFrame(()=>{
      const plot=qs('#page-review .scatter-plot-pane'),wrap=qs('#page-review .scatter-canvas-wrap');
      if(!plot||!wrap)return;
      const controls=qs('#page-review .workspace-scatter-controls');if(controls)wrap.after(controls);
      const foot=qs('#page-review .scatter-plot-foot');if(foot)plot.append(foot);
      plot.append(stats);
      const evidenceTabs=qs('#page-review .workspace-evidence-tabs');
      if(evidenceTabs){const disclosure=document.createElement('details');disclosure.className='ov-window-evidence';disclosure.innerHTML='<summary>当前窗口 / 人工标注</summary>';disclosure.append(evidenceTabs);plot.append(disclosure);}
      page.classList.add('ov-hospital-columns');draw();linked?.renderMini();
    });
    renderCoverage();bind();
  }
  async function openReportEpisode(episodeId,basis,id,caseToken){
    const current=()=>state.caseId===id&&state.caseRequestId===caseToken&&state.currentPage==='review';
    if(!current())return;
    qs('#ovReturnReport').hidden=false;afMode(true);
    await load(true);
    if(!current())return;
    if(!overviewReady)throw Error('片段尚未成功载入，请重试');
    ECGAnalysisConsistency.assertSame(basis,ui.identity);
    const matches=ui.rhythm.document.episodes.filter(x=>x.id===episodeId);
    if(matches.length!==1)throw Error('未找到原房颤／房扑片段，请返回报告重新核对；未跳到其他片段');
    episodeFilter='all';episodePage=0;
    await locateEpisode(episodeId);
    if(!current()||ui.episode!==episodeId)return;
    const details=qs('#ovEpisodeEditor details');if(details)details.open=true;
  }
  async function load(force=false){
    if(!state.caseId)return;const id=state.caseId;
    if(qs('#ovReturnReport'))qs('#ovReturnReport').hidden=!clinicalUI.hasRhythmReturn();
    if(!force&&overviewReady&&ui.id===id&&ui.rows.length){draw();return}
    const token=++ui.loadToken,caseToken=state.caseRequestId;
    invalidateEvidence('正在读取逐搏数据；旧覆盖结果已清除。');qs('#ovStatus').textContent='正在核对逐搏、片段与波形依据…';
    try{const [data,rhythm]=await ECGAnalysisConsistency.read(api,id,['overview','rhythm-review'].map(kind=>basis=>api(ECGAnalysisConsistency.url(id,kind,{},basis))));if(token!==ui.loadToken||id!==state.caseId||caseToken!==state.caseRequestId)return;
      if(data.revision!==rhythm.beat_revision)throw Error('逐搏与节律版本不一致，请重新载入后复核');
      if(ui.id!==id){rememberEpisodeForm();episodeFilter='all';episodePage=0;episodeEditor=null;ui.range=null;ui.episode=null;ui.bin=null;ui.densityKey=null;ui.rulerPoints=[];ui.mode=state.scatterMode;ui.rangeBounds=null}
      ui.id=id;ui.caseToken=caseToken;ui.identity=ECGAnalysisConsistency.identity(data);ui.revision=data.revision;ui.rows=E.decode(data);ui.rhythm=rhythm;ui.estimated=data.estimated_beats;ui.settings=data.settings;ui.hist=E.histogram(ui.rows,ui.ratio);ui.hour=hour();
      ui.statistics=E.stats(ui.rows,ui.settings?.pause||2.5,data.duration_s);
      ui.maxHR=200;ui.maxRR=2000;for(const r of ui.rows){if(E.valid(r)){ui.maxHR=Math.max(ui.maxHR,Math.ceil(r.hr/50)*50);ui.maxRR=Math.max(ui.maxRR,Math.ceil(r.rr_ms/500)*500)}}
      overviewReady=true;
      let waveCurrent=false;try{ECGAnalysisConsistency.assertSame(ui.identity,state.waveform);waveCurrent=true;}catch(_){}
      if(!waveCurrent)await loadWaveform();
      if(token!==ui.loadToken||id!==state.caseId||caseToken!==state.caseRequestId)return;
      ECGAnalysisConsistency.assertSame(ui.identity,state.waveform);
      globalThis.ecgOverviewLinked?.attach({caseId:id,caseToken,...ui.identity,beatRevision:ui.revision},ui.rows);
      coverageMessage='尚未检查覆盖；没有已保存片段不代表没有房颤。';renderCoverage();
      qs('#ovStatus').textContent=`${fmtNumber(ui.rows.length)} 条逐搏记录 · 修订 r${data.revision}`;draw();renderEpisodes();
    }catch(error){if(token===ui.loadToken&&id===state.caseId&&caseToken===state.caseRequestId){invalidateEvidence('未取得一致的病例依据，请重试载入。');qs('#ovStatus').innerHTML=`${esc(error.message)} · ${button('重试载入','reload')}`;}throw error}
  }
  function invalidateEvidence(message){
    globalThis.ecgOverviewLinked?.invalidate(message);
    globalThis.ecgChartInspection?.invalidate();
    rememberEpisodeForm();episodeEditor=null;overviewReady=false;ui.identity=null;ui.rows=[];ui.hist=null;ui.statistics=null;ui.rhythm=null;episodeNavigation++;
    for(const selector of ['#ovEpisodeRows','#ovAFSummary','#ovEpisodeNavigation','#ovEpisodeEditor','#ovEpisodePages','#ovStatistics','#ovStatisticsMethod']){const host=qs(selector);if(host)host.innerHTML='';}
    document.querySelectorAll('#page-review canvas[data-ov-plot],#ovHistogram,#scatterCanvas').forEach(canvas=>{geometries.delete(canvas);canvas.getContext('2d').clearRect(0,0,canvas.width,canvas.height);});
    const focus=qs('#ovFocusContext');if(focus)focus.textContent='当前波形依据尚未核对';
    resetCoverage(message);
  }
  function waveformBasis(){return overviewReady&&ui.id===state.caseId&&ui.caseToken===state.caseRequestId?ui.identity:null;}
  function waveformFailed(basis){
    if(basis&&ui.identity===basis){invalidateEvidence('波形依据读取失败或已变化，请重新载入后复核。');qs('#ovStatus').innerHTML=`波形与总览尚未重新核对 · ${button('重试载入','reload')}`;}
  }
  function prepare(canvas,height){
    if(innerWidth>=1100&&!ui.af&&['ovHistogram','ovFullHR','ovHourHR','ovFullRR','ovHourRR'].includes(canvas.id)){canvas.style.height='';height=Math.max(canvas.id==='ovHistogram'?58:46,canvas.getBoundingClientRect().height||height);}
    const box=canvasContext(canvas,height),ctx=box.ctx,width=canvas.getBoundingClientRect().width||box.width;
    // Fractional grid widths must keep painted coordinates and pointer
    // coordinates identical, including closely spaced / coincident RR points.
    ctx.setTransform(canvas.width/width,0,0,canvas.height/height,0,0);
    ctx.clearRect(0,0,width,height);ctx.fillStyle='#fbfdfd';ctx.fillRect(0,0,width,height);ctx.font=`12px ${UI_FONT}`;
    return {...box,width,l:42,r:12,t:6,b:18,w:Math.max(1,width-54),h:Math.max(1,height-24)};
  }
  function axis(g,maxY,start,end,units=''){const {ctx,l,w,h,t,height}=g;ctx.strokeStyle='#e2eaed';ctx.fillStyle='#526773';ctx.textAlign='right';for(const f of [0,.5,1]){const y=t+h*(1-f);ctx.beginPath();ctx.moveTo(l,y);ctx.lineTo(l+w,y);ctx.stroke();ctx.fillText(Math.round(maxY*f)+units,l-5,y+3)}ctx.textAlign='left';ctx.fillText(formatElapsed(start),l,height-3);ctx.textAlign='right';ctx.fillText(formatElapsed(end),l+w,height-3);ctx.textAlign='left'}
  function shade(g,start,end){
    const {ctx,l,w,h,t}=g,range=linkedTimeSpan()||span(),map=v=>l+(v-start)/(end-start)*w;
    ctx.save();ctx.beginPath();ctx.rect(l,t,w,h);ctx.clip();
    if(ui.showEvents)for(const episode of ui.rhythm?.document.episodes||[]){if(episode.status==='excluded'||episode.end_s<start||episode.start_s>end)continue;ctx.fillStyle=episode.status==='confirmed'?'rgba(134,72,149,.15)':'rgba(198,146,47,.12)';ctx.fillRect(map(episode.start_s),t,Math.max(1,map(episode.end_s)-map(episode.start_s)),h)}
    ctx.fillStyle='rgba(11,146,144,.13)';ctx.strokeStyle='#0b9290';const x1=map(range[0]),width=Math.max(2,map(range[1])-x1);ctx.fillRect(x1,t,width,h);ctx.strokeRect(x1,t,width,h);
    ctx.strokeStyle='#c26b20';ctx.beginPath();ctx.moveTo(map(state.start),t);ctx.lineTo(map(state.start),t+h);ctx.stroke();ctx.restore();
  }
  function drawTime(canvas,start,end,kind){
    if(!canvas||!canvas.getClientRects().length)return;end=Math.max(start+.005,Math.min(duration(),end));const g=prepare(canvas,58),{ctx,l,w,h,t}=g,maxY=kind==='hr'?ui.maxHR:ui.maxRR;
    geometries.set(canvas,{...g,start,end,maxY,kind});axis(g,maxY,start,end);shade(g,start,end);
    ctx.save();ctx.beginPath();ctx.rect(l,t,w,h);ctx.clip();ctx.fillStyle=kind==='hr'?'#207cba':'#52a72c';
    // Every RR contributes. At whole-record scale HR uses pixel min/max envelopes,
    // preserving short excursions instead of joining minute-average endpoints.
    const pixels=kind==='hr'?new Map():null;
    for(const r of ui.rows){if(r.time_s<start||r.time_s>end||!E.valid(r))continue;const value=kind==='hr'?r.hr:r.rr_ms,x=l+(r.time_s-start)/(end-start)*w,y=t+h-value/maxY*h;
      if(pixels){const k=Math.floor(x),old=pixels.get(k);pixels.set(k,old?[Math.min(old[0],y),Math.max(old[1],y)]:[y,y])}else ctx.fillRect(x,y,1.2,1.2);
    }
    if(pixels){ctx.strokeStyle='#207cba';ctx.lineWidth=1;let previous=null;ctx.beginPath();for(const [x,[low,high]] of pixels){ctx.moveTo(x,low);ctx.lineTo(x,Math.max(low+.7,high));if(previous){ctx.moveTo(previous[0],previous[1]);ctx.lineTo(x,(low+high)/2)}previous=[x,(low+high)/2]}ctx.stroke()}
    if(linked?.active()&&linked.snapshot().kind==='samples'){
      const selected=linked.currentSet();ctx.fillStyle='#d08a2e';
      for(const r of ui.rows){if(!selected.has(r.sample_index)||r.time_s<start||r.time_s>=end||!E.valid(r))continue;const value=kind==='hr'?r.hr:r.rr_ms,x=l+(r.time_s-start)/(end-start)*w,y=t+h-value/maxY*h;ctx.fillRect(x-1.5,y-1.5,3,3);}
      canvas.dataset.linkedCount=String(ui.rows.filter(r=>selected.has(r.sample_index)&&r.time_s>=start&&r.time_s<end&&E.valid(r)).length);
    }else canvas.dataset.linkedCount='0';
    const focused=linked?.active()?linked.snapshot().focusSample:null;
    if(focused!==null&&focused!==undefined&&focused/200>=start&&focused/200<end){const x=l+(focused/200-start)/(end-start)*w;ctx.strokeStyle='#a86920';ctx.lineWidth=1.5;ctx.beginPath();ctx.moveTo(x,t);ctx.lineTo(x,t+h);ctx.stroke();}
    ctx.restore();
  }
  function drawHistogram(){
    const canvas=qs('#ovHistogram');if(!canvas.getClientRects().length||!ui.hist)return;const g=prepare(canvas,76),{ctx,l,w,h,t,height}=g,bins=ui.hist.bins,max=Math.max(1,...bins.map(x=>x.count)),scale=v=>ui.log?Math.log10(v+1)/Math.log10(max+1):v/max;
    ctx.fillStyle='#526773';ctx.textAlign='right';for(const f of [0,.5,1]){const value=ui.log?Math.round((max+1)**f-1):Math.round(max*f),y=t+h*(1-f);ctx.fillText(fmtNumber(value),l-5,y+3);ctx.strokeStyle='#e2eaed';ctx.beginPath();ctx.moveTo(l,y);ctx.lineTo(l+w,y);ctx.stroke()}ctx.textAlign='left';
    const selected=linked?.active()&&linked.snapshot().kind==='samples'?linked.index().selectedHistogram(linked.snapshot(),ui.ratio):null;
    const bar=w/bins.length;bins.forEach((b,i)=>{ctx.fillStyle=selected?'#b8d8db':ui.bin===i?'#d39235':'#4ba6ad';ctx.fillRect(l+i*bar,t+h-h*scale(b.count),Math.max(.8,bar-1),h*scale(b.count));if(selected){ctx.fillStyle='#d08a2e';ctx.fillRect(l+i*bar,t+h-h*scale(selected.bins[i].count),Math.max(.8,bar-1),h*scale(selected.bins[i].count));}});
    const ticks=w<420?2:6;for(let i=0;i<=ticks;i++){ctx.textAlign=i===ticks?'right':i===0?'left':'center';ctx.fillStyle='#526773';ctx.fillText((i===ticks?bins.at(-1).start+'+':Math.round(ui.hist.max*i/ticks))+(ui.ratio?'%':' ms'),l+w*i/ticks,height-3)}ctx.textAlign='left';
    geometries.set(canvas,{...g,kind:'hist'});qs('#ovHistInfo').textContent=(ui.bin===null?`横轴 ${ui.ratio?'相邻 RR 比值（%）':'RR（ms）'} · 纵轴心搏数${ui.log?'，log10(n+1)':''}`:`${ui.bin===bins.length-1?'≥'+bins[ui.bin].start:bins[ui.bin].start+'–'+bins[ui.bin].end}${ui.ratio?'%':' ms'} · ${fmtNumber(bins[ui.bin].count)} 搏`)+(selected?` · 橙色：已选有效 ${fmtNumber(selected.bins.reduce((n,b)=>n+b.count,0))} 搏`:'');
    canvas.dataset.linkedCount=String(selected?selected.bins.reduce((n,b)=>n+b.count,0):0);
  }
  const colors={N:'#263c46',S:'#269766',V:'#d04a45',X:'#a5b0b7',A:'#854a9b',C:'#aa6b28'};
  function drawScatter(canvas=qs('#scatterCanvas')){
    if(!canvas?.getClientRects().length||!ui.rows.length)return;
    const af=canvas.id==='ovAFLorenz';if(!af&&qs('#ovScatterMode'))qs('#ovScatterMode').value=ui.mode;
    // The overview owns a flex-sized plot slot. Measure it, not the old square
    // canvas height, so resizing/disclosing controls cannot leave blank space.
    const height=af?Math.max(110,canvas.clientWidth-30):Math.max(1,canvas.getBoundingClientRect().height);
    const points=E.pairs(ui.rows,af?'rr':ui.mode,ui.hour).filter(r=>!af||(r.time_s>=span()[0]&&r.time_s<=span()[1])),g=prepare(canvas,height),{ctx,l,w,h,t}=g,bound=ui.bound;
    if(!af){ui.scatter=points;state.scatterData={mode:ui.mode,points,bounds:{x_min:0,x_max:bound,y_min:0,y_max:bound},hour_start_s:ui.hour};qs('#scatterLoading').hidden=true;if(ui.rangeBounds!==bound){ui.rangeBounds=bound;initializeScatterRangeInputs(state.scatterData.bounds)}}geometries.set(canvas,{...g,kind:'scatter',points,bound});
    ctx.strokeStyle='#d1dde2';ctx.strokeRect(l,t,w,h);ctx.fillStyle='#526773';ctx.fillText('RR(i+1) · ms',l+4,t+10);ctx.fillText('0',l-12,t+h+12);ctx.textAlign='right';ctx.fillText(bound+' ms · RR(i)',l+w,t+h+14);ctx.textAlign='left';ctx.fillText(String(bound),1,t+8);
    ctx.save();ctx.beginPath();ctx.rect(l,t,w,h);ctx.clip();
    if(ui.guides){ctx.setLineDash([4,4]);ctx.strokeStyle='#9fb0b8';for(const slope of [.5,1,2]){ctx.beginPath();ctx.moveTo(l,t+h);ctx.lineTo(l+w,t+h-h*slope);ctx.stroke()}ctx.setLineDash([])}
    for(const r of points){if(r.x>bound||r.y>bound)continue;ctx.fillStyle=state.scatterSelectedSet.has(r.sample_index)?'#d08a2e':colors[r.class_code]||'#854a9b';ctx.fillRect(l+r.x/bound*w,t+h-r.y/bound*h,ui.size,ui.size)}
    const focused=points.find(r=>r.sample_index===state.scatterFocusedSample);if(focused&&focused.x<=bound&&focused.y<=bound){ctx.strokeStyle='#0c6464';ctx.lineWidth=1.5;ctx.beginPath();ctx.arc(l+focused.x/bound*w,t+h-focused.y/bound*h,4,0,Math.PI*2);ctx.stroke();}
    if(ui.polygon.length){ctx.strokeStyle='#078986';ctx.fillStyle='rgba(11,146,144,.12)';ctx.beginPath();ui.polygon.forEach(([x,y],i)=>i?ctx.lineTo(l+x/bound*w,t+h-y/bound*h):ctx.moveTo(l+x/bound*w,t+h-y/bound*h));ctx.closePath();ctx.fill();ctx.stroke()}ctx.restore();
    if(!af)qs('#ovScatterCount').textContent=`${fmtNumber(points.length)} 个相邻 RR 配对 · 已选 ${fmtNumber(state.scatterSelectedSamples.length)} 搏`;
  }
  function selectSamples(samples,details={}){
    if(linked?.active()){linked.select(samples,details);return;}
    clearScatterSelection();state.scatterSelectedSamples=[...new Set(samples)].sort((a,b)=>a-b);state.scatterSelectedSet=new Set(state.scatterSelectedSamples);
    qs('#scatterSelectionCount').textContent=fmtNumber(samples.length)+' 搏';qs('#clearScatterSelection').disabled=!samples.length;qs('#scatterSelectionList').scrollTop=0;renderScatterSelectionList();drawScatter();drawContext();
  }
  function drawContext(){
    const target=qs('#ovFocusContext');if(!target)return;
    const wave=state.waveform,basis=waveformBasis();
    if(!overviewReady||!wave||!basis){target.textContent='当前波形依据尚未核对';return}
    try{ECGAnalysisConsistency.assertSame(basis,wave)}catch(_){target.textContent='当前波形依据尚未核对';return}
    const anchor=state.scatterFocusedSample,beat=(wave.beats||[]).find(b=>Number(b.sample_index)===Number(anchor)&&anchor!==null),count=state.scatterSelectedSamples.length,code=beat?editEffectiveCode(beat):'';
    target.textContent=`波形 ${formatElapsed(wave.start_s)}–${formatElapsed(wave.start_s+wave.duration_s)} · ${(globalThis.ECGChartInspection?.names(wave.leads||{})||Object.keys(wave.leads||{})).join(' / ')}${code?' · '+code:''} · 已选 ${fmtNumber(count)} 搏`;
  }
  function drawStats(){const s=ui.statistics||E.stats(ui.rows,ui.settings?.pause||2.5,duration()),pct=(n,denominator)=>`${fmtNumber(n)} (${(n/Math.max(1,denominator)*100).toFixed(2)}%)`;
    qs('#ovStatistics').innerHTML=[['总心搏（源报告估算）',ui.estimated==null?'—':fmtNumber(ui.estimated)],['总心搏（当前有效）',fmtNumber(s.valid)],['伪差',pct(s.counts.X||0,s.total)],['室早',pct(s.counts.V||0,s.valid)],['房早',pct(s.counts.S||0,s.valid)],['长 RR >2.5 s',`${s.pauses} 次（其中 >3 s：${s.pause_over3} 次）`]].map(([k,v])=>`<div><dt>${k}</dt><dd>${v}</dd></div>`).join('')+Object.entries(ui.rhythm?.document.bookmarks||{}).map(([key,time])=>`<div><dt>${({fastest:'最快心率',slowest:'最慢心率',fastest_nn:'最快窦性',slowest_nn:'最慢窦性'})[key]}书签</dt><dd>${button(formatElapsed(time),'bookmark-jump:'+time)}</dd></div>`).join('');
    qs('#ovStatisticsMethod').textContent=`当前 ${fmtNumber(s.total)} 条 QRS／伪差标记，排除伪差后 ${fmtNumber(s.valid)} 搏；有效 RR ${fmtNumber(s.rr_interval_count)} 个。室早／房早占有效心搏，伪差占全部标记。平均心率使用有效 RR，HRV 另用连续正常 N-N，数量可能不同。编辑提醒按 ≥${ui.settings?.pause||2.5} s 共 ${s.alert_pauses} 次；报告固定统计 >2.5 s，其中 >3 s 是子集。`;
  }
  function draw(){
    drawContext();if(!ui.rows.length)return;ui.hour=hour();const end=Math.min(duration(),ui.hour+3600),selection=linked?.active()?linked.snapshot():null,windowLabel=`${formatElapsed(state.start)}–${formatElapsed(Math.min(duration(),state.start+state.duration))}`;
    qs('#ovRange').textContent=selection?.timeBounds?`已选时段 ${formatElapsed(selection.timeBounds.start_s)}–${formatElapsed(selection.timeBounds.end_s)}`:selection?.kind==='samples'?`已选 ${fmtNumber(linked.cohort().length)} 搏 · 当前波形窗口 ${windowLabel}`:`当前波形窗口 ${windowLabel}`;
    if(ui.af){drawTime(qs('#ovAFFull'),0,duration(),'rr');drawScatter(qs('#ovAFLorenz'));qs('#ovAFHour').textContent=`${formatElapsed(ui.hour)}–${formatElapsed(end)}`;for(let i=0;i<4;i++){const c=qs('#ovQuarter'+i),start=ui.hour+i*900;c.closest('.ov-lane').hidden=start>=duration();if(start<duration())drawTime(c,start,start+900,'rr')}}
    else{drawHistogram();drawTime(qs('#ovFullHR'),0,duration(),'hr');drawTime(qs('#ovHourHR'),ui.hour,end,'hr');drawTime(qs('#ovFullRR'),0,duration(),'rr');drawTime(qs('#ovHourRR'),ui.hour,end,'rr');drawScatter();drawStats()}
  }
  function seek(time,keepRange=false,locatedTime=time,preserveWindow=false){
    if(coverage&&!preserveWindow){coverage.focus=-1;coverage.navigation++;renderWindowEvidence();}
    if(!keepRange)ui.range=null;
    state.locatedTime={caseId:state.caseId,time:Number(locatedTime)||0};
    state.start=E.clamp(Number(time)||0,0,Math.max(0,duration()-state.duration));state.editStart=state.start;ui.hour=hour();draw();return run(()=>loadWaveform());
  }
  function timeAt(event,canvas){const g=geometries.get(canvas),r=canvas.getBoundingClientRect();return g?E.clamp(g.start+(event.clientX-r.left-g.l)/g.w*(g.end-g.start),g.start,g.end):state.start}
  function scatterAt(event,canvas){const g=geometries.get(canvas),r=canvas.getBoundingClientRect();return [E.clamp((event.clientX-r.left-g.l)/g.w,0,1)*g.bound,E.clamp(1-(event.clientY-r.top-g.t)/g.h,0,1)*g.bound]}
  function inside(x,y,poly){let hit=false;for(let i=0,j=poly.length-1;i<poly.length;j=i++){const a=poly[i],b=poly[j];if((a[1]>y)!==(b[1]>y)&&x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0])hit=!hit}return hit}
  function closeMenu(){const menu=qs('#ovMenu');try{menu.hidePopover()}catch(_){}menu.hidden=true}
  function group(title,items){return `<details><summary>${title}</summary>${items}</details>`}
  function showMenu(kind,event,canvasId){
    if(!ui.rows.length)return;event?.preventDefault?.();const canvas=qs('#'+(canvasId||'ovFullRR')),rect=canvas.getBoundingClientRect(),x=event?.clientX??rect.left+50,y=event?.clientY??rect.top+20;
    if(kind!=='scatter'&&event?.clientX!==undefined){ui.contextTime=timeAt(event,canvas);if(!ui.range){ui.range=[ui.contextTime,Math.min(duration(),ui.contextTime+state.duration)];draw()}}else ui.contextTime=span()[0];
    if(kind==='rr')ui.episode=ui.rhythm?.document.episodes.find(x=>x.start_s<=ui.contextTime&&x.end_s>ui.contextTime)?.id||null;
    const codes=['N','S','V','X','A','C','P','O','OTHER'],types=action=>codes.map(c=>button(`${c} · ${ECGBeatEngine.types[c].name}`,action+':'+c)).join('');let html='';
    if(kind==='rr')html=button('添加房颤段','af-add:AF')+button('添加房扑段','af-add:AFL')+button('删除当前房颤 / 房扑','af-delete-current',ui.episode?'':'disabled')+button('移除选区内的房颤 / 房扑','af-cut')+button('移除所有房颤 / 房扑段','af-clear')+button('标记为全程房颤','af-all:AF')+button('标记为全程房扑','af-all:AFL')+button('重分析房颤（全程 RR 候选）','af-screen')+button('重分析选择区段房颤','af-screen-range')+button('设置选项 / 筛查方法','af-settings')+button('进入房颤编辑与分析','af-open');
    if(kind==='scatter')html=group('修改心拍',types('beat'))+button('排除房颤 / 房扑','af-exclude-scatter')+button('手动批量添加 QRS 波','edit:insert')+button('自动向前插入候选','edit:detect-before')+button('自动向后插入候选','edit:detect-after')+group('修改前一心搏',types('previous'))+group('修改后一心搏',types('next'))+group('散点图类型',[['n','N 散点'],['s','S 散点'],['v','V 散点'],['hour','小时散点'],['nn','N–N 散点'],['rr','R–R 散点']].map(([k,v])=>button(v,'mode:'+k)).join(''))+group('框选模式',button('矩形框选','selection:box')+button('自由圈选','selection:lasso')+button('单点定位','selection:point'))+group('显示范围',[2000,3000,5000].map(n=>button('0–'+n+' ms','bound:'+n)).join(''))+group('散点大小',[1,1.4,2.4,3.4].map(n=>button(n+' px','size:'+n)).join(''))+button((ui.guides?'隐藏':'显示')+'辅助线','guides');
    if(kind==='hr')html=button('插入图条','strip')+button('插入缩略图条','strip-short')+group('即时打印图条',button('三导联图条','print:3')+button('十二导联图条','print:12'))+button('插入心搏','edit:insert')+button('选择起始位置','range-anchor')+button('删除前面区段的标记','delete-before')+button('删除后面区段的标记','delete-after')+button('测量尺','ruler:measure')+button('分规尺','ruler:divider')+button('平行尺','ruler:parallel')+button('跳转到时间','jump')+button('转到诊断图','diagnostic')+button('转到全览图','af-close')+button((ui.showEvents?'隐藏':'显示')+'患者事件','events')+button('设为最快心率图条','bookmark:fastest')+button('设为最慢心率图条','bookmark:slowest')+button('设为最快窦性心率图条','bookmark:fastest_nn')+button('设为最慢窦性心率图条','bookmark:slowest_nn')+button('重分析房早','pac-screen')+button('设置选项','edit:settings');
    const menu=qs('#ovMenu');menu.innerHTML=`<header><strong>${kind==='rr'?'房颤 / 房扑':kind==='hr'?'心率与图条':'Lorenz 散点操作'}</strong>${button('关闭','menu-close','aria-label="关闭菜单"')}</header><p>${formatElapsed(span()[0])}–${formatElapsed(span()[1])}${kind==='scatter'?' · 已选 '+state.scatterSelectedSamples.length+' 搏':''}</p><div class="ov-menu-body">${html}</div>`;
    menu.hidden=false;try{menu.showPopover()}catch(_){}menu.style.left=Math.max(8,Math.min(x,innerWidth-menu.offsetWidth-12))+'px';menu.style.top=Math.max(8,Math.min(y,innerHeight-menu.offsetHeight-12))+'px';menu.querySelector('button')?.focus({preventScroll:true});
  }
  function dialog(title,body,accept,label='确认保存'){
    closeMenu();const el=qs('#ovDialog');el.innerHTML=`<form><header><h2>${esc(title)}</h2>${button('关闭','dialog-close','aria-label="关闭对话框"')}</header><div class="ov-dialog-body">${body}</div><p class="ov-error" role="alert"></p><footer>${button('取消','dialog-close')}<button type="submit" class="button primary">${label}</button></footer></form>`;
    el.querySelector('form').onsubmit=async event=>{event.preventDefault();const b=el.querySelector('[type=submit]');b.disabled=true;try{await accept(new FormData(event.target));}catch(error){el.querySelector('.ov-error').textContent=error.message}finally{b.disabled=false}};
    if(!el.open)el.showModal();
  }
  async function saveRhythm(document,operation='save'){
    const id=state.caseId,base=ui.rhythm;if(!base)throw Error('请等待复核数据载入');if(!clinicalWorkflow.writable())throw Error('当前服务只读');
    if(!overviewReady||ui.id!==id||!ui.identity)throw Error('病例依据尚未核对，请重试载入后保存');
    const value=await request('rhythm-review',{method:'PUT',body:JSON.stringify({...ui.identity,document,operation,revision:base.revision,beat_revision:ui.revision,confirmed:true})});
    if(id!==state.caseId||ui.rhythm!==base)return;ui.rhythm=value;qs('#ovDialog').close();state.reportComposer=null;
    await clinicalWorkflow.refresh(id).catch(()=>toast('片段已保存，报告复核状态读取失败，请重新核对报告。','error',6000));
    if(id!==state.caseId||ui.rhythm!==value)return;
    try{await load(true);}catch(error){toast('片段已保存，但新依据读取失败；请重试载入，不要重复保存。','error',6000);return;}
    toast('片段复核已保存 · 可撤销','success');
  }
  const rhythmBasis=()=>({caseId:state.caseId,rhythm:ui.rhythm?.revision,beats:ui.revision,identity:JSON.stringify(ui.identity||null)});
  function requireRhythmBasis(basis){
    if(state.caseId!==basis.caseId||ui.rhythm?.revision!==basis.rhythm||ui.revision!==basis.beats||JSON.stringify(ui.identity||null)!==basis.identity)throw Error('编辑或确认期间病例或修订已变化，未保存旧内容；请重新选择片段，核对后操作。');
  }
  function confirmRhythm(title,document,detail){
    const count=document.episodes.length,excluded=document.episodes.filter(x=>x.status==='excluded').length;
    const basis=rhythmBasis();
    dialog(title,`<p>${esc(detail)}</p><p>保存后保留 ${count} 条片段记录（含 ${excluded} 条已排除记录）。片段边界和复核状态会同步到报告事件；源波形不变，可撤销。</p>`,()=>{
      requireRhythmBasis(basis);
      return saveRhythm(document);
    });
  }
  function episodeForm(kind='AF',whole=false){
    const basis=rhythmBasis();
    const bounds=whole?[0,duration()]:span();dialog(whole?'标记全程'+name(kind):'添加'+name(kind)+'片段',`<p>${whole?'将替换现有片段，原记录保留在撤销历史。':'输入记录起点后的秒数；核对波形后再确认诊断。'}</p><div class="ov-fields"><label>开始（秒）<input name="start" type="number" step=".005" min="0" max="${duration()}" value="${bounds[0].toFixed(3)}" required></label><label>结束（秒）<input name="end" type="number" step=".005" min="0" max="${duration()}" value="${bounds[1].toFixed(3)}" required></label><label>类型<select name="kind"><option value="AF" ${kind==='AF'?'selected':''}>房颤</option><option value="AFL" ${kind==='AFL'?'selected':''}>房扑</option></select></label><label>复核状态<select name="status"><option value="pending">待复核</option><option value="confirmed">医生确认</option></select></label><label class="ov-wide">备注<textarea name="note" maxlength="1000" rows="2"></textarea></label></div>`,data=>{
      requireRhythmBasis(basis);
      const start=Number(data.get('start')),end=Number(data.get('end')),doc=copy(ui.rhythm.document);if(whole)doc.episodes=[];
      doc.episodes.push({id:crypto.randomUUID(),start_s:start,end_s:end,kind:data.get('kind'),status:data.get('status'),source:'manual',note:data.get('note')});E.validateDocument(doc,duration());return saveRhythm(doc);
    });
  }
  // The queue is read-only: navigating or filtering never confirms an episode.
  const episodeOrder=(a,b)=>a.start_s-b.start_s||a.end_s-b.end_s||a.id.localeCompare(b.id);
  const episodeKey=id=>JSON.stringify([state.caseId,id]);
  const episodeFilterName=s=>s==='all'?'全部片段':s==='drafts'?'本地未保存':statusName(s);
  const episodeFields=x=>({start:String(x.start_s),end:String(x.end_s),kind:x.kind,status:x.status,note:x.note||''});
  const sameEpisodeFields=(a,b)=>['start','end','kind','status','note'].every(k=>a[k]===b[k]||(['start','end'].includes(k)&&a[k]!==''&&b[k]!==''&&Number(a[k])===Number(b[k])));
  function episodeQueue(){
    const all=[...(ui.rhythm?.document.episodes||[])].sort(episodeOrder),counts={all:all.length,pending:0,confirmed:0,excluded:0};
    all.forEach(x=>counts[x.status]++);
    const drafts=[...episodeDrafts.values()].filter(d=>d.basis.caseId===state.caseId).map(d=>all.find(x=>x.id===d.original.id)||{...d.original,removed:true}).sort(episodeOrder);
    counts.drafts=drafts.length;
    const items=episodeFilter==='drafts'?drafts:all.filter(x=>episodeFilter==='all'||x.status===episodeFilter),current=all.find(x=>x.id===ui.episode),index=items.findIndex(x=>x.id===ui.episode);
    const before=current?items.filter(x=>episodeOrder(x,current)<0).at(-1):null,after=current?items.find(x=>episodeOrder(x,current)>0):items[0];
    const pages=Math.max(1,Math.ceil(items.length/20));episodePage=Math.min(Math.max(0,episodePage),pages-1);
    return {all,counts,items,current,index,before,after,pages,visible:items.slice(episodePage*20,episodePage*20+20)};
  }
  function rememberEpisodeForm(){
    if(!episodeEditor)return;
    const {form,key,basis,original}=episodeEditor,values={};
    for(const k of ['start','end','kind','status','note'])values[k]=form.elements[k].value;
    if(sameEpisodeFields(values,episodeFields(original)))episodeDrafts.delete(key);
    else episodeDrafts.set(key,{basis,original,values});
  }
  function episodeDraftHint(){
    const hint=qs('#ovEpisodeDraftHint');if(!hint||!episodeEditor)return;
    const draft=episodeDrafts.get(episodeEditor.key),stale=draft&&(draft.basis.rhythm!==ui.rhythm?.revision||draft.basis.beats!==ui.revision||draft.basis.identity!==rhythmBasis().identity||!ui.rhythm.document.episodes.some(x=>x.id===draft.original.id));
    hint.textContent=stale?'记录修订已变化。旧输入已保留供核对，不能直接覆盖；请放弃本地修改并重新编辑。':draft?'本片段有未保存修改；切换片段会暂存，刷新或关闭网页会丢失。':'浏览不会确认诊断；保存需再次核对。';
  }
  function renderEpisodeNavigation(q=episodeQueue()){
    const nav=qs('#ovEpisodeNavigation');if(!nav)return;
    const x=q.current,label=episodeFilterName(episodeFilter),link=(text,item)=>button(text,'episode:'+(item?encodeURIComponent(item.id):''),item?'':'disabled');
    nav.innerHTML=`<div><strong>${x?`选中片段：${name(x.kind)} · ${statusName(x.status)} · ${formatElapsedPrecise(x.start_s)}–${formatElapsedPrecise(x.end_s)}`:'选择片段开始逐段复核'}</strong><span>${esc(label)} ${q.index>=0?`${q.index+1} / ${q.items.length}`:`${q.items.length} 段${x?' · 当前片段不在此筛选内':''}`} · 按开始时间排序</span></div><div>${link('上一段',q.before)}${link(x?'下一段':'开始复核',q.after)}${button('回看起点','episode-start',x?'':'disabled')}${button('回看末尾','episode-end',x?'':'disabled')}${button('编辑片段','episode-edit',x?'':'disabled')}${button('返回列表','episode-list')}</div>`;
  }
  async function locateEpisode(id,edge='start'){
    if(!overviewReady||ui.id!==state.caseId)throw Error('请等待当前病例片段载入。');
    const q=episodeQueue(),x=q.all.find(x=>x.id===id);
    if(!x){if(episodeDrafts.has(episodeKey(id))){ui.episode=id;renderEpisodes();qs('#ovEpisodeEditor').scrollIntoView({block:'center'});return;}throw Error('片段已变化，请重新选择。');}
    const basis=coverageBasis(),rhythm=ui.rhythm.revision,token=++episodeNavigation;
    ui.episode=id;ui.range=[x.start_s,x.end_s];const index=q.items.findIndex(e=>e.id===id);if(index>=0)episodePage=Math.floor(index/20);
    coverageFocus=-1;renderGapNavigation();renderEpisodes();
    // Show context before the boundary; do not turn an exclusive end into an event sample.
    const at=edge==='end'?Math.max(x.start_s,x.end_s-state.duration/2):Math.max(0,x.start_s-Math.min(2,state.duration/4));
    await seek(at,true,edge==='end'?Math.max(x.start_s,x.end_s-.005):x.start_s);
    if(token!==episodeNavigation||!ui.af||!sameCoverageBasis(basis)||rhythm!==ui.rhythm.revision||ui.episode!==id)return;
    const nav=qs('#ovEpisodeNavigation');nav.scrollIntoView({block:'start'});nav.focus({preventScroll:true});
  }
  function renderEpisodes(){
    if(!ui.rhythm)return;rememberEpisodeForm();
    // Reconcile acknowledged input before computing the queue and its draft count.
    const saved=new Map(ui.rhythm.document.episodes.map(x=>[x.id,x]));
    for(const [key,draft] of episodeDrafts){
      const x=saved.get(draft.original.id);
      if(draft.basis.caseId===state.caseId&&x&&sameEpisodeFields(draft.values,episodeFields(x)))episodeDrafts.delete(key);
    }
    const q=episodeQueue(),episodes=q.all,summary=E.rhythmSummary(ui.rhythm.document.episodes,duration());
    qs('#ovAFSummary').innerHTML=['confirmed_af','confirmed_afl'].map((key,i)=>{const r=summary[key];return `<span><strong>已确认${i?'房扑':'房颤'} ${r.count} 段</strong><span>${r.seconds.toFixed(3)} 秒 · 负荷 ${r.pct==null?'—':r.pct.toFixed(2)+'%'}</span></span>`}).join('')+`<span>待复核 ${summary.pending_any.count} 段 · 不计入确认负荷</span><small>分母：完整记录 ${summary.denominator_s.toFixed(3)} 秒；重叠时段只计一次。仅统计已保存片段，0 不代表排除。</small>`;
    const select=qs('#ovEpisodeFilter');select.innerHTML=['all','pending','confirmed','excluded','drafts'].map(s=>`<option value="${s}" ${s===episodeFilter?'selected':''}>${episodeFilterName(s)}（${q.counts[s]}）</option>`).join('');
    qs('#ovEpisodeRows').innerHTML=q.visible.length?q.visible.map(x=>`<tr ${ui.episode===x.id?'aria-selected="true"':''}><td>${button(formatElapsedPrecise(x.start_s),'episode:'+encodeURIComponent(x.id),ui.episode===x.id?'aria-current="true"':'')}<small>${(x.end_s-x.start_s).toFixed(3)} 秒${episodeDrafts.has(episodeKey(x.id))?' · 未保存':''}</small></td><td>${name(x.kind)}</td><td>${x.removed?'片段已移除':statusName(x.status)}</td></tr>`).join(''):`<tr><td colspan="3">${episodes.length?'此筛选下没有片段，可切换查看全部。':'暂无已保存片段；请检查覆盖并回看原始波形。'} 不代表排除房颤。</td></tr>`;
    qs('#ovEpisodePages').innerHTML=`${button('上页','episode-page:'+(episodePage-1),episodePage?'':'disabled')}<output aria-live="polite">${episodePage+1} / ${q.pages} 页 · ${q.items.length} 段</output>${button('下页','episode-page:'+(episodePage+1),episodePage<q.pages-1?'':'disabled')}`;
    qs('[data-ov="af-undo"]').disabled=!ui.rhythm.can_undo;qs('[data-ov="af-redo"]').disabled=!ui.rhythm.can_redo;renderEpisodeNavigation(q);
    const key=episodeKey(ui.episode),editor=qs('#ovEpisodeEditor');let draft=episodeDrafts.get(key),x=q.current;
    if(!x&&!draft){episodeEditor=null;editor.innerHTML='<p>选择片段可调整起止、类型和复核状态。</p>';return;}
    const version=JSON.stringify(rhythmBasis());
    if(episodeEditor?.key===key&&episodeEditor.version===version){episodeDraftHint();return;}
    const missing=!x;x=x||draft.original;const fields=draft?.values||episodeFields(x),basis=draft?.basis||rhythmBasis(),stale=missing||basis.rhythm!==ui.rhythm.revision||basis.beats!==ui.revision||basis.identity!==rhythmBasis().identity;
    editor.innerHTML=`<details class="ov-episode-details" ${innerWidth>1500||stale?'open':''}><summary>编辑选中片段 · ${formatElapsedPrecise(x.start_s)} · ${missing?'已移除':statusName(x.status)}</summary><form id="ovEpisodeForm"><h3>编辑选中片段</h3><p id="ovEpisodeDraftHint" role="status"></p><div class="ov-fields"><label>开始（秒）<input name="start" type="number" step=".005" min="0" max="${duration()}" value="${esc(fields.start)}" required></label><label>结束（秒）<input name="end" type="number" step=".005" min="0" max="${duration()}" value="${esc(fields.end)}" required></label><label>类型<select name="kind">${['AF','AFL'].map(k=>`<option value="${k}" ${fields.kind===k?'selected':''}>${name(k)}</option>`).join('')}</select></label><label>复核状态<select name="status">${['pending','confirmed','excluded'].map(s=>`<option value="${s}" ${s===fields.status?'selected':''}>${statusName(s)}</option>`).join('')}</select></label><label class="ov-wide">备注<textarea name="note" rows="2" maxlength="1000">${esc(fields.note)}</textarea></label></div><footer><span>${esc(x.source)}</span>${button('放弃本地修改','episode-discard')}${button('删除片段','af-delete-current',missing?'disabled':'')}<button type="submit" class="button primary" ${stale?'disabled':''}>核对并保存片段</button></footer></form></details>`;
    const form=qs('#ovEpisodeForm');episodeEditor={key,version,form,basis,original:draft?.original||copy(x)};episodeDraftHint();
    form.oninput=form.onchange=()=>{rememberEpisodeForm();episodeDraftHint();};
    form.onsubmit=event=>{event.preventDefault();run(()=>{
      requireRhythmBasis(basis);rememberEpisodeForm();
      const data=new FormData(event.target),doc=copy(ui.rhythm.document),item=doc.episodes.find(e=>e.id===x.id);
      if(!item)throw Error('该片段已不在当前记录中，请重新选择后编辑。');
      Object.assign(item,{start_s:Number(data.get('start')),end_s:Number(data.get('end')),kind:data.get('kind'),status:data.get('status'),note:data.get('note'),source:'manual'});
      E.validateDocument(doc,duration());
      confirmRhythm('确认片段修订',doc,`${name(item.kind)} · ${formatElapsedPrecise(item.start_s)}–${formatElapsedPrecise(item.end_s)} · ${statusName(item.status)}。保存后作为人工片段保留，自动重分析不会替换；复核状态以此处选择为准。`);
    })};
  }
  function afMode(enabled){
    ui.af=enabled;const page=qs('#page-review'),wave=qs('#waveformCard');page.classList.toggle('ov-af-mode',enabled);qs('#ovAF').hidden=!enabled;
    if(enabled&&!ui.range)ui.range=[hour(),Math.min(duration(),hour()+3600)];
    if(enabled)qs('#ovAFWaveHost').append(wave);else page.querySelector('.analysis-main').insertBefore(wave,qs('.ov-navigator'));
    renderCoverage();draw();renderEpisodes();renderWaveform();
  }
  function coverageBasis(){
    if(!overviewReady||ui.id!==state.caseId||!ui.rhythm)throw Error('请等待当前病例逐搏数据载入，或重试读取；未进行筛查。');
    return {caseId:state.caseId,revision:ui.revision,rows:ui.rows,token:ui.loadToken,caseData:state.caseData};
  }
  function sameCoverageBasis(basis){
    return overviewReady&&basis.caseId===state.caseId&&ui.id===state.caseId&&basis.revision===ui.revision&&basis.rows===ui.rows&&basis.token===ui.loadToken&&basis.caseData===state.caseData;
  }
  function resetCoverage(message){coverageRun++;coverage=null;coveragePage=0;coverageFocus=-1;coverageBusy=false;coverageMessage=message;renderCoverage();}
  function publishCoverage(result,start,end,basis){
    if(!sameCoverageBasis(basis))return false;
    coverage={basis,summary:ECGAFCoverage.summarize(result,start,end),windows:ECGAFCoverage.windowSnapshot(result),filter:'all',page:0,focus:-1,navigation:0};coveragePage=0;coverageFocus=-1;coverageBusy=false;coverageMessage='';renderCoverage();return true;
  }
  function renderGapNavigation(){
    const host=qs('#ovAFGapNavigation');if(!host)return;
    const gap=coverage&&sameCoverageBasis(coverage.basis)&&coverage.summary.gaps[coverageFocus];
    host.hidden=!ui.af||!gap;if(host.hidden){host.innerHTML='';return;}
    host.innerHTML=`<span>未评估 ${coverageFocus+1} / ${coverage.summary.gaps.length} · ${esc(formatElapsed(gap.start_s))}–${esc(formatElapsed(gap.end_s))} · ${esc(ECGAFCoverage.reasons[gap.reason])}</span><div>${button('上一未评估时段','af-gap:'+(coverageFocus-1),coverageFocus===0?'disabled':'')}${button('下一未评估时段','af-gap:'+(coverageFocus+1),coverageFocus+1===coverage.summary.gaps.length?'disabled':'')}${button('返回覆盖列表','af-coverage-list')}</div>`;
  }
  function renderCoverage(){
    const host=qs('#ovAFCoverage');if(!host)return;
    if(coverage&&!sameCoverageBasis(coverage.basis)){coverage=null;coverageMessage='病例或逐搏依据已变化，请重新检查覆盖。';}
    renderGapNavigation();renderWindowEvidence();
    const disabled=!overviewReady||ui.id!==state.caseId||coverageBusy;
    const tools=`<div class="ov-coverage-actions">${button('检查全程覆盖','af-coverage',disabled?'disabled':'')}${button('检查选区覆盖','af-coverage-range',disabled?'disabled':'')}${!overviewReady?button('重试载入','reload'):''}</div>`;
    const note='<p class="ov-coverage-note">只读检查，不保存诊断片段。覆盖率不是正常率；未评估不代表正常，已评估未提示也不能排除房颤。此结果仅对应本次范围及逐搏修订，不作为已保存报告的覆盖证明。</p>';
    if(!coverage){host.innerHTML=`<header><strong>RR 筛查覆盖</strong>${tools}</header><p role="status">${esc(coverageBusy?'正在检查 RR 窗口…':coverageMessage||'尚未检查覆盖。')}</p>${note}`;return;}
    const s=coverage.summary,p=ECGAFCoverage.page(s,coveragePage),seconds=n=>`${Number(n.toFixed(3))} 秒`,detailsOpen=host.querySelector('details')?.open||false,windowsOpen=host.querySelector('#ovAFWindows')?.open||false;
    coveragePage=p.index;
    host.innerHTML=`<header><strong>RR 筛查覆盖 · ${s.start_s===0&&s.end_s===duration()?'全程':'选区'}</strong>${tools}</header><p role="status">${esc(formatElapsed(s.start_s))}–${esc(formatElapsed(s.end_s))} · 逐搏修订 r${esc(coverage.basis.revision)} · 已评估 ${seconds(s.assessed_s)} / ${seconds(s.total_s)}（${s.coverage_pct.toFixed(1)}%） · 未评估 ${seconds(s.skipped_s)}</p>${note}<details ${detailsOpen?'open':''}><summary>未评估时段：${s.gaps.length} 段 / ${s.skipped_windows} 个窗口${s.gaps.length?' · 展开定位波形':''}</summary>${s.gaps.length?`<ol start="${p.offset+1}">${p.items.map((g,i)=>`<li><span>${esc(formatElapsed(g.start_s))}–${esc(formatElapsed(g.end_s))}<small>${esc(ECGAFCoverage.reasons[g.reason])} · ${seconds(g.end_s-g.start_s)} · ${g.windows} 窗</small></span>${button('回看波形','af-gap:'+(p.offset+i),`aria-label="回看 ${esc(formatElapsed(g.start_s))} 起的未评估时段"`)}</li>`).join('')}</ol><footer>${button('上一页','af-gap-page:'+(p.index-1),p.index===0?'disabled':'')}<span>第 ${p.index+1} / ${p.pages} 页</span>${button('下一页','af-gap-page:'+(p.index+1),p.index+1===p.pages?'disabled':'')}</footer>`:'<p>本次范围没有因质量或时长被跳过的窗口；这不表示心律正常。</p>'}</details>`;
    host.insertAdjacentHTML('beforeend',windowList(windowsOpen));
  }
  function windowList(open=false){
    const c=coverage,p=ECGAFCoverage.windowPage(c.windows,c.filter,c.page);c.page=p.index;
    return `<details id="ovAFWindows" ${open?'open':''}><summary>逐窗提示依据 · ${c.windows.length} 个窗口</summary><div class="ov-window-filters" role="group" aria-label="筛查窗口状态">${Object.entries(ECGAFCoverage.states).map(([key,label])=>button(label,'af-window-filter:'+key,`aria-pressed="${c.filter===key}"`)).join('')}</div><p>固定 30 秒窗口，尾窗可能不足 30 秒。候选不是确诊；未提示不代表正常。明细不改变已保存片段。</p>${p.total?`<ol start="${p.offset+1}">${p.items.map(w=>`<li ${c.focus===w.index?'aria-current="true"':''}><span>${esc(formatElapsed(w.start_s))}–${esc(formatElapsed(w.end_s))}<small>${esc(ECGAFCoverage.states[w.state])}${w.reason?' · '+esc(ECGAFCoverage.reasons[w.reason]):''}</small></span>${button('查看依据与波形','af-window:'+w.index,`aria-label="查看 ${esc(formatElapsed(w.start_s))} 起的窗口依据与波形"`)}</li>`).join('')}</ol>`:'<p role="status">本次检查没有此类窗口；可选择其他状态查看。</p>'}<footer>${button('上一页','af-window-page:'+(p.index-1),p.index===0?'disabled':'')}<output tabindex="-1">${p.total} 个 · 第 ${p.index+1} / ${p.pages} 页</output>${button('下一页','af-window-page:'+(p.index+1),p.index+1===p.pages?'disabled':'')}</footer></details>`;
  }
  function renderWindowEvidence(){
    const host=qs('#ovAFWindowEvidence');if(!host)return;
    const c=coverage,w=c&&sameCoverageBasis(c.basis)&&c.windows[c.focus];
    host.hidden=!ui.af||!w;if(host.hidden){host.innerHTML='';return;}
    const p=ECGAFCoverage.windowPage(c.windows,c.filter),position=p.matching.findIndex(x=>x.index===w.index),metric=v=>v===null?'未计算':Number(v.toFixed(4)),ratio=w.total_intervals?`${(w.valid_intervals/w.total_intervals*100).toFixed(1)}%`:'无分母';
    host.innerHTML=`<header><strong>${esc(ECGAFCoverage.states[w.state])} · ${esc(formatElapsed(w.start_s))}–${esc(formatElapsed(w.end_s))}</strong><div>${button('上一窗口','af-window:'+(p.matching[position-1]?.index??-1),position<=0?'disabled':'')}${button('下一窗口','af-window:'+(p.matching[position+1]?.index??-1),position<0||position+1>=p.total?'disabled':'')}${button('返回窗口列表','af-window-list')}</div></header><p>逐搏修订 r${esc(c.basis.revision)} · ${w.evaluated?'达到本筛查器的评估条件，不表示波形质量已全面合格。':'未评估原因：'+esc(ECGAFCoverage.reasons[w.reason])+'。'} 范围采用左闭右开；请核对整个窗口，不只核对当前可见数秒。</p><dl><div><dt>有效 N-N / 窗口 QRS 条目</dt><dd>${w.valid_intervals} / ${w.total_intervals}（${ratio}）</dd></div><div><dt>有效间期覆盖</dt><dd>${Number(w.coverage_s.toFixed(3))} 秒</dd></div><div><dt>连续间期对 / 三元组</dt><dd>${w.evaluated?w.pair_count+' / '+w.triple_count:'未计算'}</dd></div><div><dt>CV（规则 ≥0.12）</dt><dd>${metric(w.cv)}</dd></div><div><dt>归一化 RMSSD（规则 ≥0.14）</dt><dd>${metric(w.normalized_rmssd)}</dd></div><div><dt>转折率（规则 0.45–0.85）</dt><dd>${metric(w.turning_ratio)}</dd></div></dl><p>以上为固定工程筛查规则，不是诊断标准。N-N 依赖当前逐搏类型与间期校验；未分析 P 波，不能排除早搏、伪差或判定房扑。时间沿用当前导入采样率；显示值经舍入，状态来自未舍入的筛查结果。</p>`;
  }
  function requireWindowCoverage(){
    if(!coverage||!sameCoverageBasis(coverage.basis)){resetCoverage('依据已变化，请重新检查覆盖后查看窗口。');throw Error('筛查窗口已失效，请重新检查覆盖。');}
    return coverage;
  }
  async function locateCoverageWindow(index){
    const c=requireWindowCoverage();
    if(!Number.isInteger(index)||!ECGAFCoverage.windowPage(c.windows,c.filter).matching.some(w=>w.index===index))throw Error('筛查窗口不在当前列表中');
    const w=c.windows[index],token=++c.navigation;c.focus=index;coverageFocus=-1;ui.range=[w.start_s,w.end_s];renderGapNavigation();renderWindowEvidence();
    await seek(w.start_s,true,w.start_s,true);
    if(c!==coverage||!sameCoverageBasis(c.basis)||token!==c.navigation||!ui.af)return;
    const host=qs('#ovAFWindowEvidence');host.scrollIntoView({block:'start'});host.focus({preventScroll:true});
  }
  function windowListAction(key,arg){
    const c=requireWindowCoverage();
    if(key==='af-window-filter'){
      ECGAFCoverage.windowPage(c.windows,arg);c.filter=arg;c.page=0;c.focus=-1;c.navigation++;
    }else if(key==='af-window-page'){
      const page=Number(arg),p=ECGAFCoverage.windowPage(c.windows,c.filter,page);if(p.index!==page)throw Error('页码无效');c.page=page;
    }else{
      const p=ECGAFCoverage.windowPage(c.windows,c.filter),index=p.matching.findIndex(w=>w.index===c.focus);c.page=Math.max(0,Math.floor(index/20));
    }
    renderCoverage();const host=qs('#ovAFWindows');host.open=true;
    if(key==='af-window-list')host.scrollIntoView({block:'start'});
    const focus=key==='af-window-filter'?host.querySelector('[aria-pressed="true"]'):host.querySelector('output');focus?.focus({preventScroll:true});
  }
  async function checkCoverage(selectedRange=false){
    if(coverageBusy)return;
    const basis=coverageBasis(),[start,end]=selectedRange?span():[0,duration()],recordDuration=duration(),token=++coverageRun;
    coverageBusy=true;coverage=null;renderCoverage();
    // Allow the busy state to paint before traversing the full beat index.
    await new Promise(resolve=>setTimeout(resolve,0));
    if(token!==coverageRun)return;
    if(!sameCoverageBasis(basis)){resetCoverage('病例或逐搏依据已变化，请重新载入后检查。');return;}
    try{publishCoverage(E.screenAFResult(basis.rows,recordDuration,start,end),start,end,basis);}
    catch(error){if(token===coverageRun&&sameCoverageBasis(basis)){coverageBusy=false;coverageMessage=error.message;renderCoverage();throw error;}}
  }
  async function locateCoverageGap(index){
    if(!coverage||!sameCoverageBasis(coverage.basis)){resetCoverage('依据已变化，请重新检查覆盖后定位。');throw Error('未评估时段已失效，请重新检查覆盖。');}
    if(!Number.isInteger(index)||index<0||index>=coverage.summary.gaps.length)throw Error('未评估时段序号无效');
    const c=coverage,basis=c.basis,gap=c.summary.gaps[index],token=++c.navigation;c.focus=-1;coverageFocus=index;ui.range=[gap.start_s,gap.end_s];renderGapNavigation();renderWindowEvidence();
    await seek(gap.start_s,true,gap.start_s,true);
    if(c!==coverage||token!==c.navigation||!sameCoverageBasis(basis)||!ui.af)return;
    qs('#ovAFGapNavigation').scrollIntoView({block:'start'});qs('#waveformCanvas').focus({preventScroll:true});
  }
  function screenAF(selectedRange=false){
    const basis=coverageBasis();
    const [start,end]=selectedRange?span():[0,duration()];
    if(end-start<30)throw Error('RR 筛查至少需要 30 秒，请扩大框选区间');
    const result=E.planAFRescreen(ui.rows,duration(),ui.rhythm.document,start,end);
    coverageRun++;coverageBusy=false;
    publishCoverage(result,start,end,basis);
    if(!result.evaluated_windows)throw Error('没有可评估的完整 30 秒窗口：有效间期或覆盖不足。已有片段未改变；请回看原始波形、修正伪差或扩大选区。未评估不代表正常。');
    confirmRhythm('RR 不规则候选重分析',result.document,`${formatElapsed(start)}–${formatElapsed(end)}：评估 ${result.evaluated_windows} 个完整 30 秒窗口，${result.skipped_windows} 个窗口因时长或质量不足未评估；拟写入 ${result.candidates.length} 段待复核 RR 不规则候选。未检出不等于排除房颤；未分析 P 波，不自动识别房扑。只替换可评估窗口内的算法待复核片段；保留医生已确认／已排除、人工、源片段及未评估区域。`);
  }
  function screenPAC(){
    const candidates=[];for(let i=6;i<ui.rows.length-1;i++){const r=ui.rows[i],prev=ui.rows.slice(i-5,i),next=ui.rows[i+1];if(r.class_code!=='N'||!prev.every(x=>x.class_code==='N'&&x.rr_ms>0)||next.class_code!=='N')continue;const sorted=prev.map(x=>x.rr_ms).sort((a,b)=>a-b),median=sorted[2];if((sorted[4]-sorted[0])/median<.2&&r.rr_ms<median*.75&&r.rr_ms>=300&&next.rr_ms<median*1.5)candidates.push(r)}
    dialog('房早候选重分析 · RR 筛查',`<p>发现 ${candidates.length} 个提前心搏候选。尚未验证 P 波和 QRS 形态，不能仅凭 RR 判断房早；选择后仍需预览改型。这里显示前 100 个，默认不选。</p><div class="ov-candidates">${candidates.slice(0,100).map(r=>`<label><input type="checkbox" name="samples" value="${r.sample_index}">${formatElapsed(r.time_s)} · RR ${r.rr_ms} ms ${button('回看','preview-beat:'+r.time_s)}</label>`).join('')||'<p>未发现满足该规则的候选。</p>'}</div>`,async data=>{const samples=data.getAll('samples').map(Number);if(!samples.length)throw Error('请先回看波形并选择候选');qs('#ovDialog').close();await beatEditor.invoke('relabel',{samples,code:'S'})},'预览改为房早');
  }
  async function insertStrip(short=false,caption='人工图条',bounds=span()){
    const [start,selectedEnd]=bounds,end=short?Math.min(duration(),start+3):Math.min(duration(),selectedEnd,start+120),id=state.caseId;
    const item=await request('annotations',{method:'POST',body:JSON.stringify({sample_index:Math.floor(start*200),category:'note',lead:'全部',label:caption,note:'从总览选区插入；等待报告复核',details:{kind:'STRIP',status:'confirmed',end_sample:Math.min(Math.ceil(end*200)-1,Math.floor(duration()*200)-1),finding:caption}})});
    const events=await request('report-events?'+new URLSearchParams({ids:'annotation:'+item.id,limit:1}));if(id!==state.caseId)return;if(!events.items.length)throw Error('图条已保存，但报告索引尚未更新，请重试');
    if(ui.af)afMode(false);goPage('report');if(state.currentPage!=='report')return;await clinicalUI.refreshReport();clinicalUI.addStrip(events.items[0]);toast('已加入报告图条草稿；请核对并保存','success');
  }
  async function printStrip(leads){
    if(state.privacySaving||state.privacyIdentityPending){toast('身份显示正在更新，请稍后重新打开图条打印', 'error');return;}
    const caseId=state.caseId,caseToken=state.caseRequestId,privacyRequestId=state.privacyRequestId;
    const current=()=>caseId===state.caseId&&caseToken===state.caseRequestId&&privacyRequestId===state.privacyRequestId&&!state.privacySaving&&!state.privacyIdentityPending;
    const [start,end]=span(),wave=await request('waveform?'+new URLSearchParams({start,duration:Math.max(1,Math.min(12,end-start)),leads:leads===12?ALL_LEADS.join(','):'II,V1,V5',filter:state.filter,max_points:2400}));
    if(!current())return;
    const entries=(globalThis.ECGChartInspection?.entries(wave.leads)||Object.entries(wave.leads)),row=leads===12?95:180,width=1000,height=entries.length*row;
    const paths=entries.map(([lead,values],i)=>{const scale=row*.35/Math.max(100,...values.map(Math.abs)),base=row*(i+.5);return `<text x="0" y="${row*i+15}">${lead}</text><path d="${values.map((v,j)=>`${j?'L':'M'}${(35+j/(values.length-1)*950).toFixed(1)},${(base-v*scale).toFixed(1)}`).join(' ')}" fill="none" stroke="#223f4b" stroke-width="1"/>`}).join('');
    dialog('图条打印预览',`<div id="ovPrintSheet"><h2>心电图条 · ${esc(state.caseData.metadata.name)}</h2><p>${formatElapsed(wave.start_s)}–${formatElapsed(wave.start_s+wave.duration_s)} · 自适应幅度，非标准走纸比例</p><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="待打印心电图条">${paths}</svg></div>`,()=>{if(!current()){toast('身份或病例已切换，请重新打开图条打印', 'error');return;}document.body.classList.add('ov-print-strip');window.print();},'打印 A4 图条');
  }
  async function navigatorWave(){
    if(!state.caseId||ui.af||state.currentPage!=='review'||!qs('.ov-navigator')?.open)return;const seconds=Math.min(120,Math.max(30,state.duration*3)),start=E.clamp(state.start-seconds/3,0,Math.max(0,duration()-seconds)),key=[state.caseId,start,seconds,state.filter].join(':');
    if(ui.navKey!==key){ui.navKey=key;const result=await request('waveform?'+new URLSearchParams({start,duration:seconds,leads:'II',filter:state.filter,max_points:2400}));if(ui.navKey!==key)return;ui.nav=result}
    const wave=ui.nav,canvas=qs('#ovNavigator');if(!wave||!canvas.getClientRects().length)return;const g=prepare(canvas,60),{ctx,l,w,h,t}=g,values=wave.leads.II||[],limit=Math.max(100,...values.map(Math.abs));geometries.set(canvas,{...g,start:wave.start_s,end:wave.start_s+wave.duration_s,kind:'navigator'});
    shade(g,wave.start_s,wave.start_s+wave.duration_s);ctx.strokeStyle='#334f5b';ctx.beginPath();values.forEach((v,i)=>{const x=l+i/(values.length-1)*w,y=t+h/2-v/limit*h*.45;i?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.stroke();qs('#ovNavigatorTime').textContent=formatElapsed(wave.start_s)+'–'+formatElapsed(wave.start_s+wave.duration_s);
  }
  function waveformOverlay(){
    const canvas=qs('#waveformCanvas'),wave=state.waveform;if(!wave||!canvas?.getClientRects().length)return;const ctx=canvas.getContext('2d'),rect=canvas.getBoundingClientRect(),width=rect.width,height=rect.height;
    const beats=wave.beats||[],minimum=width/Math.max(1,beats.length);ctx.fillStyle='#35616a';ctx.font=`9px ${UI_FONT}`;
    if(minimum>32)beats.forEach(r=>{const x=(r.time_s-wave.start_s)/wave.duration_s*width;if(x>=0&&x<width-20){ctx.fillText(r.hr?Math.round(r.hr)+' bpm':'—',x+3,23);ctx.fillText(r.rr_ms?r.rr_ms+' ms':'—',x+3,34)}});
    if(linked?.active()){
      let same=false;try{ECGAnalysisConsistency.assertSame(ui.identity,wave);same=true;}catch(_){}
      if(same){const members=linked.snapshot().kind==='samples'?linked.currentSet():null,focus=linked.snapshot().focusSample;ctx.save();ctx.fillStyle='rgba(208,138,46,.12)';ctx.strokeStyle='#a86920';for(const r of beats){const x=(r.sample_index/200-wave.start_s)/wave.duration_s*width;if(x<0||x>=width)continue;if(members?.has(r.sample_index))ctx.fillRect(x-2,0,4,height);if(r.sample_index===focus){ctx.lineWidth=1.5;ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,height);ctx.stroke();}}ctx.restore();}
    }
    if(!ui.ruler||!ui.rulerPoints.length)return;const points=ui.rulerPoints,xAt=t=>(t-wave.start_s)/wave.duration_s*width;
    ctx.save();ctx.strokeStyle='#b9671d';ctx.fillStyle='#965119';ctx.lineWidth=1;
    if(ui.ruler==='parallel'){points.forEach(p=>{const y=p.y*height;ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(width,y);ctx.stroke()})}
    else {const delta=points.length===2?Math.abs(points[1].time-points[0].time):0,positions=ui.ruler==='divider'&&delta>.02?Array.from({length:Math.min(120,Math.ceil(wave.duration_s/delta)+3)},(_,i)=>points[0].time+(i-Math.ceil((points[0].time-wave.start_s)/delta))*delta):points.map(p=>p.time);positions.forEach(t=>{const x=xAt(t);ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,height);ctx.stroke()})}
    if(points.length===2){const delta=Math.abs(points[1].time-points[0].time),leadCount=(globalThis.ECGChartInspection?.names(wave.leads)||Object.keys(wave.leads)).length,sameLead=Math.floor(points[0].y*leadCount)===Math.floor(points[1].y*leadCount),amplitude=Math.abs(points[1].y-points[0].y)*leadCount*1000/.31/(state.gain/10),text=ui.ruler==='parallel'?(sameLead?`Δ幅度 ${amplitude.toFixed(1)} 设备标度（未溯源）`:'请在同一导联内放置两条平行线'):`Δt ${(delta*1000).toFixed(0)} ms${delta>0?' · '+(60/delta).toFixed(1)+' bpm':''}`;ctx.fillStyle='#fff8ed';ctx.fillRect(40,height-28,Math.min(330,width-40),24);ctx.fillStyle='#965119';ctx.fillText(text,48,height-12)}ctx.restore();
  }
  async function action(value,element){
    const [key,...tail]=value.split(':'),arg=tail.join(':');if(key.startsWith('menu-')&&key!=='menu-close')return showMenu(key.slice(5),null,element?.dataset.canvas);
    closeMenu();
    if(key==='menu-close')return;
    if(key==='dialog-close'){qs('#ovDialog').close();return}
    if(key==='reload')return load(true);
    if(key==='clear-range'){ui.range=null;ui.rangeAnchor=null;ui.bin=null;ui.polygon=[];linked?.clear();draw();return}
    if(key==='linked-reload'){await linked?.refresh(true);return;}
    if(key==='hist-rr'||key==='hist-ratio'){ui.ratio=key==='hist-ratio';ui.bin=null;ui.hist=E.histogram(ui.rows,ui.ratio);qs('[data-ov="hist-rr"]').setAttribute('aria-pressed',String(!ui.ratio));qs('[data-ov="hist-ratio"]').setAttribute('aria-pressed',String(ui.ratio));drawHistogram();return}
    if(key==='af-open'||key==='af-close'){afMode(key==='af-open');return}
    if(key==='af-prev'||key==='af-next'){seek(ui.hour+(key==='af-next'?3600:-3600));return}
    if(key==='af-add'||key==='af-all')return episodeForm(arg||'AF',key==='af-all');
    if(key==='af-screen')return screenAF();
    if(key==='af-screen-range')return screenAF(true);
    if(key==='af-coverage'||key==='af-coverage-range')return checkCoverage(key==='af-coverage-range');
    if(key==='af-gap')return locateCoverageGap(Number(arg));
    if(key==='af-window')return locateCoverageWindow(Number(arg));
    if(['af-window-filter','af-window-page','af-window-list'].includes(key))return windowListAction(key,arg);
    if(key==='af-coverage-list'){coveragePage=Math.max(0,Math.floor(coverageFocus/20));renderCoverage();const host=qs('#ovAFCoverage'),details=host.querySelector('details');if(details)details.open=true;host.scrollIntoView({block:'start'});host.querySelector('summary')?.focus({preventScroll:true});return;}
    if(key==='af-gap-page'){const page=Number(arg);if(!Number.isInteger(page)||page<0)throw Error('页码无效');coveragePage=page;renderCoverage();qs('#ovAFCoverage summary')?.focus();return;}
    if(key==='af-settings')return dialog('房颤筛查方法与设置','<p>当前算法：30 秒固定窗口的 RR 不规则研究性筛查。至少 20 搏、正常类型占比 ≥90%、时间覆盖 ≥25 秒；CV≥0.12、归一化 RMSSD≥0.14、转折率 0.45–0.85。阈值固定，不是诊断标准。</p><p>右键拖动或左键拖动 RR 图可选择时段；右键点击保留已选范围。人工房颤/房扑片段不会被自动重分析覆盖。通用心搏、NN 和长 RR 设置可在下方打开。</p>',()=>{qs('#ovDialog').close();return beatEditor.invoke('settings',{time:ui.contextTime})},'打开通用分析设置');
    if(key==='af-undo'||key==='af-redo')return saveRhythm(null,key==='af-undo'?'undo':'redo');
    if(key==='episode')return locateEpisode(decodeURIComponent(arg));
    if(key==='episode-start'||key==='episode-end')return locateEpisode(ui.episode,key==='episode-end'?'end':'start');
    if(key==='episode-filter'){
      if(!['all','pending','confirmed','excluded','drafts'].includes(arg))throw Error('片段筛选无效');
      episodeFilter=arg;episodePage=0;renderEpisodes();return;
    }
    if(key==='episode-page'){
      const page=Number(arg),q=episodeQueue();if(!Number.isInteger(page)||page<0||page>=q.pages)throw Error('片段页码无效');
      episodePage=page;renderEpisodes();qs('.ov-episode-table').scrollTop=0;qs('#ovEpisodePages output').setAttribute('tabindex','-1');qs('#ovEpisodePages output').focus({preventScroll:true});return;
    }
    if(key==='episode-list'){
      const q=episodeQueue();if(q.index>=0)episodePage=Math.floor(q.index/20);renderEpisodes();
      const target=qs('#ovEpisodeRows [aria-current="true"]')||qs('#ovEpisodeFilter');target.scrollIntoView({block:'center'});target.focus({preventScroll:true});return;
    }
    if(key==='episode-edit'){
      renderEpisodes();const details=qs('#ovEpisodeEditor details');if(details)details.open=true;
      qs('#ovEpisodeEditor').scrollIntoView({block:'center'});qs('#ovEpisodeForm [name="status"]')?.focus({preventScroll:true});return;
    }
    if(key==='episode-discard'){
      const key=episodeKey(ui.episode),basis=rhythmBasis();
      return dialog('放弃本地修改','<p>仅清除本片段尚未保存的表单输入，重新显示已保存版本；不会删除已保存片段。</p>',()=>{requireRhythmBasis(basis);episodeDrafts.delete(key);episodeEditor=null;qs('#ovDialog').close();renderEpisodes();},'放弃并重新读取');
    }
    if(['af-delete-current','af-cut','af-clear','af-exclude-scatter'].includes(key)){
      const doc=copy(ui.rhythm.document);let detail='';
      if(key==='af-delete-current'){const x=ui.af&&ui.episode?doc.episodes.find(x=>x.id===ui.episode):doc.episodes.find(x=>x.start_s<=ui.contextTime&&x.end_s>ui.contextTime);if(!x)throw Error('当前位置没有房颤/房扑段，请先选择片段');doc.episodes=doc.episodes.filter(y=>y.id!==x.id);detail='删除选中片段；保留可撤销历史。'}
      else if(key==='af-cut'){doc.episodes=E.cut(doc.episodes,...span());detail='仅移除与当前选区重叠的部分；跨越边界的片段会切分保留。'}
      else if(key==='af-clear'){doc.episodes=[];detail='移除当前病例全部房颤/房扑片段（包含候选和确认段），可撤销。'}
      else {if(!state.scatterSelectedSamples.length)throw Error('请先在散点图框选心搏');const set=new Set(state.scatterSelectedSamples),selected=ui.rows.filter(r=>set.has(r.sample_index));for(const x of selected)doc.episodes=E.cut(doc.episodes,Math.max(0,x.time_s-x.rr_ms/1000),Math.min(duration(),x.time_s+.005));detail=`从片段中排除 ${selected.length} 个选中 RR 间期，不把离散点之间的时间一并删除。`}
      return confirmRhythm('确认房颤 / 房扑片段修改',doc,detail);
    }
    if(['beat','previous','next'].includes(key)){if(!state.scatterSelectedSamples.length)throw Error('请先在散点图框选心搏');return beatEditor.invoke(key==='beat'?'relabel':key,{code:arg,samples:state.scatterSelectedSamples,time:ui.contextTime})}
    if(key==='edit')return beatEditor.invoke(arg,{time:ui.contextTime,samples:state.scatterSelectedSamples});
    if(key==='mode'){ui.mode=arg;state.scatterMode=arg;ui.polygon=[];ui.bin=null;if(linked?.active())linked.clear('overview-mode-change');else clearScatterSelection();document.querySelectorAll('[data-scatter-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.scatterMode===arg)));draw();return}
    if(key==='selection'){ui.selectionMode=arg;ui.polygon=[];drawScatter();return}
    if(key==='bound'){ui.bound=Number(arg);qs('#ovScatterRange').value=arg;drawScatter();if(ui.af)drawScatter(qs('#ovAFLorenz'));return}
    if(key==='size'){ui.size=Number(arg);drawScatter();return}
    if(key==='guides'){ui.guides=!ui.guides;drawScatter();return}
    if(key==='jump')return dialog('跳转到记录时间',`<label>记录开始后的秒数<input name="time" type="number" step=".005" min="0" max="${duration()}" value="${state.start.toFixed(3)}" required></label><p>例如 3600 表示 D1 01:00:00。最大 ${duration().toFixed(3)} 秒。</p>`,data=>{seek(Number(data.get('time')));qs('#ovDialog').close()},'定位');
    if(key==='range-anchor'){ui.rangeAnchor=ui.contextTime;ui.range=[ui.contextTime,Math.min(duration(),ui.contextTime+.005)];draw();toast('起点已选；在任一心率 / RR 图点击终点');return}
    if(key==='delete-before'||key==='delete-after'){const samples=ui.rows.filter(r=>key==='delete-before'?r.time_s<span()[0]:r.time_s>=span()[1]).map(r=>r.sample_index);if(!samples.length)throw Error('该方向没有心搏标记');return beatEditor.invoke('delete',{samples,time:ui.contextTime})}
    if(key==='ruler'){await seek(ui.contextTime,true);ui.ruler=arg;ui.rulerPoints=[];renderWaveform();qs('#ovRulerStatus').hidden=false;qs('#ovRulerStatus').innerHTML=`${({measure:'测量尺',divider:'分规尺',parallel:'平行尺'})[arg]}：在连续波形点击两个位置。${button('关闭测量','ruler-close')}`;qs('#waveformCard').scrollIntoView({block:'center'});return}
    if(key==='ruler-close'){ui.ruler=null;ui.rulerPoints=[];qs('#ovRulerStatus').hidden=true;renderWaveform();return}
    if(key==='diagnostic'){await seek(ui.contextTime,true);qs('#waveformCard').scrollIntoView({block:'center'});qs('#waveformCanvas').focus({preventScroll:true});return}
    if(key==='events'){ui.showEvents=!ui.showEvents;qs('#annotationList').closest('article').hidden=!ui.showEvents;draw();return}
    if(key==='pac-screen')return screenPAC();
    if(key==='preview-beat'){seek(Number(arg));qs('#ovDialog').style.maxHeight='42vh';qs('#waveformCard').scrollIntoView({block:'end'});return}
    if(key==='strip'||key==='strip-short')return insertStrip(key==='strip-short');
    if(key==='print')return printStrip(Number(arg));
    if(key==='bookmark'){
      const row=ui.rows.reduce((a,b)=>!a||Math.abs(b.time_s-ui.contextTime)<Math.abs(a.time_s-ui.contextTime)?b:a,null),index=ui.rows.indexOf(row);if(!row||!E.valid(row))throw Error('当前位置没有有效 RR');
      if(arg.endsWith('_nn')&&(row.class_code!=='N'||ui.rows[index-1]?.class_code!=='N'))throw Error('此处不是连续正常心搏 NN 间期');
      const doc=copy(ui.rhythm.document),label='医生指定'+({fastest:'最快心率',slowest:'最慢心率',fastest_nn:'最快窦性心率',slowest_nn:'最慢窦性心率'})[arg];doc.bookmarks[arg]=row.time_s;
      return dialog('指定心率报告图条',`<p>${label}：${formatElapsed(row.time_s)} · ${row.hr.toFixed(1)} bpm。</p><p>保存定位书签，并创建该时刻前后 10 秒的报告图条加入草稿。不修改全记录数学极值；报告仍需核对和保存。</p>`,async()=>{await saveRhythm(doc);await insertStrip(false,label,[Math.max(0,row.time_s-3),Math.min(duration(),row.time_s+7)])});
    }
    if(key==='bookmark-jump'){seek(Number(arg));return}
  }
  function bind(){
    qs('#ovEpisodeFilter').onchange=event=>run(()=>action('episode-filter:'+event.target.value));
    window.addEventListener('beforeunload',event=>{rememberEpisodeForm();if(episodeDrafts.size){event.preventDefault();event.returnValue='';}});
    const ruler=document.createElement('div');ruler.id='ovRulerStatus';ruler.className='ov-ruler-status';ruler.hidden=true;qs('#waveformCard').prepend(ruler);
    document.addEventListener('click',event=>{const button=event.target.closest('[data-ov]');if(button){event.preventDefault();run(()=>action(button.dataset.ov,button))}},true);
    qs('#ovLog').onchange=event=>{ui.log=event.target.checked;drawHistogram()};qs('#ovScatterRange').onchange=event=>run(()=>action('bound:'+event.target.value));
    let drag=null;
    const dragCurrent=job=>job.caseId===state.caseId&&job.caseToken===state.caseRequestId&&job.loadToken===ui.loadToken&&job.selectionGeneration===(linked?.snapshot()?.selectionGeneration??null);
    const own=target=>target.closest?.('[data-ov-plot],#ovHistogram,#ovNavigator,[data-ov-density]');
    document.addEventListener('pointerdown',event=>{
      if(!qs('#ovMenu').hidden&&!event.target.closest('#ovMenu'))closeMenu();
      const canvas=own(event.target);if(!canvas||!ui.rows.length)return;
      // A resize can arrive before the queued repaint. Hit testing must use
      // the current CSS slot, otherwise an immediate click selects another beat.
      if(canvas.dataset.ovDensity)linked?.draw();
      let g=geometries.get(canvas);const slot=canvas.getBoundingClientRect();
      if(g&&(Math.abs(g.width-slot.width)>1||Math.abs(g.height-slot.height)>1)){draw();g=geometries.get(canvas);}
      const densityPoint=canvas.dataset.ovDensity?linked?.gatePoint(event,canvas):null;if(densityPoint)g={kind:'density'};
      if(!g||event.button!==0&&!(event.button===2&&g.kind==='rr'))return;event.preventDefault();event.stopImmediatePropagation();canvas.focus({preventScroll:true});canvas.setPointerCapture(event.pointerId);
      const rect=canvas.getBoundingClientRect(),point={x:event.clientX-rect.left,y:event.clientY-rect.top};drag={canvas,g,caseId:state.caseId,caseToken:state.caseRequestId,loadToken:ui.loadToken,selectionGeneration:linked?.snapshot()?.selectionGeneration??null,button:event.button,pointerId:event.pointerId,point,last:point,previousRange:ui.range?[...ui.range]:null,previousPolygon:ui.polygon.map(p=>[...p]),densityPoint,time:g.kind==='scatter'||g.kind==='density'||g.kind==='hist'?null:timeAt(event,canvas),points:g.kind==='scatter'?[scatterAt(event,canvas)]:[]};
    },true);
    document.addEventListener('pointermove',event=>{
      const canvas=own(event.target);if(!canvas)return;const g=canvas.dataset.ovDensity?{kind:'density'}:geometries.get(canvas);if(!g)return;const rect=canvas.getBoundingClientRect(),point={x:event.clientX-rect.left,y:event.clientY-rect.top};
      if(g.kind==='hr'||g.kind==='rr'){const time=timeAt(event,canvas),value=E.clamp(1-(point.y-g.t)/g.h,0,1)*g.maxY,output=qs(`[data-coordinate="${canvas.id}"]`);if(output)output.textContent=`${formatElapsedPrecise(time)} · ${value.toFixed(0)} ${g.kind==='hr'?'bpm':'ms'}`}
      if(!drag||drag.canvas!==canvas)return;if(!dragCurrent(drag)){drag=null;return;}event.preventDefault();event.stopImmediatePropagation();drag.last=point;
      if(drag.button===2&&Math.hypot(point.x-drag.point.x,point.y-drag.point.y)<4)return;
      if(g.kind==='density'){const current=linked?.gatePoint(event,canvas);if(current)linked.previewGate(canvas,drag.densityPoint,current);return;}
      if(g.kind==='scatter'){
        const current=scatterAt(event,canvas),first=drag.points[0];if(ui.selectionMode==='lasso')drag.points.push(current);ui.polygon=ui.selectionMode==='lasso'?drag.points:[first,[current[0],first[1]],current,[first[0],current[1]]];drawScatter(canvas);return;
      }
      if(g.kind!=='hist'){const time=timeAt(event,canvas);ui.range=[Math.min(drag.time,time),Math.max(drag.time,time)];draw()}
    },true);
    document.addEventListener('pointerup',event=>{
      if(!drag)return;const job=drag;drag=null;event.preventDefault();event.stopImmediatePropagation();const {canvas,g,point,last}=job,dist=Math.hypot(last.x-point.x,last.y-point.y);
      if(canvas.hasPointerCapture(job.pointerId))canvas.releasePointerCapture(job.pointerId);
      if(!dragCurrent(job))return;
      if(g.kind==='density'){const current=linked?.gatePoint(event,canvas);if(dist>=4&&current)run(()=>linked.gate(canvas,job.densityPoint,current));return;}
      if(job.button===2){if(dist>=4){linked?.timeInterval(...span());seek(span()[0],true);}showMenu('rr',event,canvas.id);return;}
      if(g.kind==='hist'){ui.bin=E.clamp(Math.floor((point.x-g.l)/g.w*ui.hist.bins.length),0,ui.hist.bins.length-1);selectSamples(ui.hist.bins[ui.bin].samples,{origin:'overview-histogram',sourcePopulation:{view:'overview',kind:ui.ratio?'rr-ratio-bin':'rr-bin',bin:ui.bin,start:ui.hist.bins[ui.bin].start,end:ui.hist.bins[ui.bin].end,fullCount:ui.hist.bins[ui.bin].count}});drawHistogram();return}
      if(g.kind==='scatter'){
        if(dist<4||ui.selectionMode==='point'){const [x,y]=scatterAt(event,canvas),distance=r=>Math.hypot((r.x-x)/g.bound*g.w,(r.y-y)/g.bound*g.h),nearest=g.points.filter(r=>r.x<=g.bound&&r.y<=g.bound).reduce((a,b)=>!a||distance(b)<distance(a)?b:a,null);ui.polygon=[];if(nearest&&distance(nearest)<=14){selectSamples([nearest.sample_index],{origin:'overview-point',focusSample:nearest.sample_index});seek(nearest.time_s)}}
        else selectSamples(g.points.filter(r=>inside(r.x,r.y,ui.polygon)).map(r=>r.sample_index),{origin:'overview-box'});return;
      }
      const time=timeAt(event,canvas);if(ui.rangeAnchor!==undefined&&ui.rangeAnchor!==null){ui.range=[Math.min(ui.rangeAnchor,time),Math.max(ui.rangeAnchor,time)];ui.rangeAnchor=null;linked?.timeInterval(...ui.range);seek(ui.range[0],true)}else if(dist<4){if(['hr','rr'].includes(g.kind)&&linked?.active()){const row=ui.rows.filter(r=>r.time_s>=g.start&&r.time_s<g.end&&E.valid(r)).reduce((a,b)=>!a||Math.abs(b.time_s-time)<Math.abs(a.time_s-time)?b:a,null);if(row){selectSamples([row.sample_index],{origin:'overview-time-point',focusSample:row.sample_index});seek(row.time_s);}}else seek(time);}else{if(span()[1]-span()[0]<.005)ui.range=null;else linked?.timeInterval(...span());seek(span()[0],true)}
    },true);
    document.addEventListener('pointercancel',()=>{if(drag){const job=drag;drag=null;if(!dragCurrent(job))return;ui.range=job.previousRange;ui.polygon=job.previousPolygon;linked?.clearGatePreview();draw();}},true);
    document.addEventListener('click',event=>{if(own(event.target)){event.preventDefault();event.stopImmediatePropagation()}
      if(event.target.id==='clearScatterSelection'&&linked?.active()){event.preventDefault();event.stopImmediatePropagation();ui.bin=null;ui.polygon=[];linked.clear();return;}
      const strip=event.target.closest('[data-scatter-sample]');if(strip&&linked?.active()&&state.currentPage==='review'){event.preventDefault();event.stopImmediatePropagation();const sample=Number(strip.dataset.scatterSample);linked.retryMini(sample);linked.focus(sample);focusScatterWaveform(sample/200,sample);return;}
      const mode=event.target.closest('[data-scatter-mode]');if(mode){event.preventDefault();event.stopImmediatePropagation();run(()=>action('mode:'+mode.dataset.scatterMode))}
      if(event.target.id==='waveformCanvas'&&ui.ruler){event.preventDefault();event.stopImmediatePropagation();const r=event.target.getBoundingClientRect();if(ui.rulerPoints.length===2)ui.rulerPoints=[];ui.rulerPoints.push({time:state.waveform.start_s+(event.clientX-r.left)/r.width*state.waveform.duration_s,y:(event.clientY-r.top)/r.height});renderWaveform()}
    },true);
    document.addEventListener('contextmenu',event=>{const canvas=own(event.target);if(!canvas)return;event.preventDefault();event.stopImmediatePropagation();const kind=geometries.get(canvas)?.kind;if(['hr','rr','scatter'].includes(kind))showMenu(kind,event,canvas.id)},true);
    document.addEventListener('keydown',event=>{
      if(qs('#ovDialog').open){event.stopImmediatePropagation();return}
      const menu=qs('#ovMenu');if(!menu.hidden){if(event.key==='Escape'){closeMenu();event.preventDefault();event.stopImmediatePropagation();return}if(['ArrowDown','ArrowUp'].includes(event.key)){const items=[...menu.querySelectorAll('button,summary')].filter(x=>x.getClientRects().length),index=items.indexOf(document.activeElement);items[(index+(event.key==='ArrowDown'?1:-1)+items.length)%items.length]?.focus();event.preventDefault();event.stopImmediatePropagation()}return}
      const canvas=own(event.target);if(!canvas)return;
      if(event.shiftKey&&event.key==='F10'){const g=geometries.get(canvas);if(['rr','hr','scatter'].includes(g?.kind)){showMenu(g.kind,null,canvas.id);event.preventDefault();event.stopImmediatePropagation()}return}
      if(event.key==='Escape'){drag=null;ui.range=null;ui.polygon=[];ui.densityBox=null;ui.bin=null;linked?.clear('overview-escape');draw();event.preventDefault();event.stopImmediatePropagation();return}
      if(['ArrowLeft','ArrowRight'].includes(event.key)){event.preventDefault();event.stopImmediatePropagation();const direction=event.key==='ArrowLeft'?-1:1;if(canvas.id==='ovHistogram'){ui.bin=E.clamp((ui.bin??0)+direction,0,ui.hist.bins.length-1);selectSamples(ui.hist.bins[ui.bin].samples,{origin:'overview-histogram'});drawHistogram()}else seek(state.start+direction*(event.shiftKey?60:state.duration))}
    },true);
    window.addEventListener('afterprint',()=>document.body.classList.remove('ov-print-strip'));
    new ResizeObserver(()=>requestAnimationFrame(()=>{draw();linked?.draw();linked?.refresh();linked?.renderMini();run(navigatorWave)})).observe(qs('#page-review'));
    new ResizeObserver(()=>requestAnimationFrame(()=>{drawScatter();renderScatterSelectionList()})).observe(qs('.scatter-canvas-wrap'));
  }
  const previousCase=loadCase,previousWave=renderWaveform,previousAnnotations=renderAnnotations;
  loadCase=async(...args)=>{
    const result=await previousCase(...args);
    if(result){
      // The template workspace needs its own evidence, not an eager all-day
      // overview and a second waveform. Rebuild review evidence when opened.
      const destination=state.caseLoading?.destination||state.currentPage;
      if(destination==='review')await load(true);
      else invalidateEvidence('进入心律与波形页后读取当前病例依据。');
    }
    return result;
  };
  renderOverview=()=>{draw();linked?.draw();linked?.refresh();linked?.renderMini();run(navigatorWave)};
  renderScatter=()=>drawScatter();
  loadScatter=async()=>{await load();ui.mode=state.scatterMode;drawScatter()};
  applyScatterSelectionPolygon=async polygon=>{ui.polygon=polygon;selectSamples(E.pairs(ui.rows,ui.mode,ui.hour).filter(r=>inside(r.x,r.y,polygon)).map(r=>r.sample_index))};
  renderWaveform=()=>{previousWave();waveformOverlay();drawContext()};
  renderAnnotations=items=>{previousAnnotations(items.filter(x=>!x.internal).map(x=>String(x.id).startsWith('af:')?{...x,note:(x.note||'')+'（在房颤分析页编辑）'}:x));qs('#annotationList').querySelectorAll('[data-delete-annotation]').forEach(b=>{if(b.dataset.deleteAnnotation.startsWith('af:'))b.remove()})};
  document.addEventListener('DOMContentLoaded',mount);
  return {load,draw,waveformBasis,waveformFailed,openReportEpisode};
})();
