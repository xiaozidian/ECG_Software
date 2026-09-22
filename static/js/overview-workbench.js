"use strict";
/* Hospital overview: a single time cursor, full-cohort plots and reversible review. */
const overviewWorkbench=(()=>{
  const E=ECGOverviewEngine,qs=s=>document.querySelector(s),esc=escapeHtml;
  const ui={id:null,revision:null,rows:[],rhythm:null,range:null,hour:0,af:false,episode:null,ratio:false,log:false,hist:null,bin:null,mode:'rr',bound:2000,size:1.4,guides:true,selectionMode:'box',scatter:[],polygon:[],contextTime:0,ruler:null,rulerPoints:[],showEvents:true,loadToken:0,densityToken:0,densityKey:null,density:null};
  const geometries=new WeakMap(),run=fn=>Promise.resolve().then(fn).catch(handleError),copy=x=>JSON.parse(JSON.stringify(x));
  const request=(path,options)=>api(`/api/cases/${state.caseId}/${path}`,options);
  const button=(label,action,attrs='')=>`<button type="button" data-ov="${action}" ${attrs}>${label}</button>`;
  const duration=()=>state.caseData?.technical.duration_seconds_raw||1;
  const span=()=>ui.range||[state.start,Math.min(duration(),state.start+state.duration)];
  const hour=()=>Math.min(Math.floor(state.start/3600)*3600,Math.max(0,duration()-Math.min(3600,duration())));
  const name=x=>x==='AF'?'房颤':'房扑';
  const statusName=x=>({pending:'待复核',confirmed:'医生确认',excluded:'已排除'})[x]||x;
  function lane(id,label,kind,minutes=false){return `<section class="ov-lane"><header><h2>${label}</h2><output data-coordinate="${id}"></output>${button('操作','menu-'+kind,`aria-label="${label}操作" data-canvas="${id}"`)}</header><canvas id="${id}" height="76" tabindex="0" data-ov-plot="${kind}" ${minutes?'data-hour="1"':''} aria-label="${label}；点击定位，拖动选区，右键或 Shift+F10 打开操作"></canvas></section>`}
  function mount(){
    const page=qs('#page-review'),grid=page.querySelector('.analysis-grid');if(!grid)return;
    page.classList.add('overview-workbench');
    const tools=document.createElement('div');tools.className='ov-commandbar';tools.innerHTML=`<div><strong>全程总览</strong><output id="ovStatus" aria-live="polite">正在读取逐搏数据</output></div><div>${button('房颤 / 房扑分析','af-open','class="button secondary"')}${button('跳转时间','jump')}${button('清除选区','clear-range')}<output id="ovRange"></output></div>`;grid.before(tools);
    const settings=document.createElement('details');settings.className='ov-settings';settings.innerHTML='<summary>病例信息 / 波形设置</summary><div></div>';settings.lastElementChild.append(qs('#caseHero'),page.querySelector('.review-toolbar'));tools.firstElementChild.append(settings);
    const histogram=document.createElement('section');histogram.className='ov-histogram';histogram.innerHTML=`<header><div role="group" aria-label="直方图类型">${button('全程 RR 直方图','hist-rr','aria-pressed="true"')}${button('全程 R/R 直方图','hist-ratio','aria-pressed="false"')}</div><label><input id="ovLog" type="checkbox">优化显示（对数）模式</label><output id="ovHistInfo">横轴 RR（ms）· 纵轴心搏数</output></header><canvas id="ovHistogram" height="104" tabindex="0" aria-label="全程 RR 直方图，点击柱形筛选心搏；左右键切换柱形"></canvas>`;grid.before(histogram);
    const trends=document.createElement('div');trends.className='ov-trends';trends.innerHTML=lane('ovFullHR','全程心率趋势图','hr')+lane('ovHourHR','小时心率趋势图','hr',true)+lane('ovFullRR','全程 RR 散点图','rr')+lane('ovHourRR','小时 RR 散点图','rr',true);
    const main=grid.querySelector('.analysis-main');main.prepend(trends);main.querySelector('.trend-strip-card').classList.add('ov-legacy-trend');
    const stats=document.createElement('section');stats.className='ov-statistics';stats.innerHTML='<h2>结论统计</h2><dl id="ovStatistics"></dl><p>估算项保留源报告；其余按当前修订重算。长 RR 为阈值候选，不等同确诊停搏。</p>';grid.querySelector('.scatter-review-card').after(stats);
    const scatterHead=document.createElement('div');scatterHead.className='ov-scatter-options';scatterHead.innerHTML=`<label>范围<select id="ovScatterRange"><option value="2000">0–2000 ms</option><option value="3000">0–3000 ms</option><option value="5000">0–5000 ms</option></select></label>${button('散点操作','menu-scatter','data-canvas="scatterCanvas" aria-label="Lorenz 散点图操作"')}<output id="ovScatterCount"></output>`;qs('.scatter-plot-pane').prepend(scatterHead);
    qs('#scatterCanvas').dataset.ovPlot='scatter';qs('#scatterCanvas').setAttribute('aria-label','Lorenz 相邻 RR 散点图；拖动框选，右键或 Shift+F10 编辑选中心搏');
    const navigator=document.createElement('section');navigator.className='ov-navigator';navigator.innerHTML='<header><strong>连续波形导航 · II</strong><output id="ovNavigatorTime"></output></header><canvas id="ovNavigator" height="60" tabindex="0" aria-label="当前窗口前后连续波形导航；点击定位，左右键移动"></canvas>';qs('#waveformCard').after(navigator);
    const af=document.createElement('section');af.id='ovAF';af.hidden=true;af.innerHTML=`<header class="ov-af-heading"><div><h2>房颤 / 房扑编辑与分析</h2><p>RR 散点定位 → 原始波形核对 → 医生确认片段</p></div><div>${button('返回总览','af-close')}${button('重分析 RR 候选','af-screen')}${button('撤销','af-undo')}${button('重做','af-redo')}</div></header>${lane('ovAFFull','全程 RR 散点图','rr')}<div class="ov-af-grid"><aside><section class="ov-af-lorenz"><h3>相邻 RR 散点 · 选中时段</h3><canvas id="ovAFLorenz" height="230" tabindex="0" data-ov-plot="scatter" aria-label="房颤时段 Lorenz 散点图"></canvas></section><section class="ov-episodes"><header><h3>房颤 / 房扑片段</h3>${button('添加片段','af-add')}</header><output id="ovAFSummary"></output><div class="ov-episode-table"><table><thead><tr><th>开始 / 持续</th><th>类型</th><th>状态</th></tr></thead><tbody id="ovEpisodeRows"></tbody></table></div></section></aside><div><div class="ov-af-hour">${button('前一小时','af-prev')}<output id="ovAFHour"></output>${button('后一小时','af-next')}</div>${[0,1,2,3].map(i=>lane('ovQuarter'+i,'15 分钟 RR · '+(i+1),'rr')).join('')}<div id="ovEpisodeEditor"></div></div></div><div id="ovAFWaveHost"></div><p class="ov-method">RR 自动筛查只提示不规则候选，未识别 P 波，不能区分所有早搏、伪差或房扑；确认后才计入医生确认负荷。原始 DATA / EBI 保持只读。</p>`;grid.after(af);
    const menu=document.createElement('div');menu.id='ovMenu';menu.className='ov-menu';menu.hidden=true;menu.setAttribute('popover','manual');menu.setAttribute('role','menu');document.body.append(menu);
    const dialog=document.createElement('dialog');dialog.id='ovDialog';dialog.className='ov-dialog';document.body.append(dialog);
    bind();
  }
  async function load(force=false){
    if(!state.caseId)return;const id=state.caseId;
    if(!force&&ui.id===id&&ui.rows.length){draw();return}
    const token=++ui.loadToken;qs('#ovStatus').textContent='正在读取完整逐搏索引…';
    try{const [data,rhythm]=await Promise.all([request('overview'),request('rhythm-review')]);if(token!==ui.loadToken||id!==state.caseId)return;
      if(ui.id!==id){ui.range=null;ui.episode=null;ui.bin=null;ui.densityKey=null;ui.rulerPoints=[];ui.mode=state.scatterMode;ui.rangeBounds=null}
      ui.id=id;ui.revision=data.revision;ui.rows=E.decode(data);ui.rhythm=rhythm;ui.estimated=data.estimated_beats;ui.settings=data.settings;ui.hist=E.histogram(ui.rows,ui.ratio);ui.hour=hour();
      ui.maxHR=200;ui.maxRR=2000;for(const r of ui.rows){if(E.valid(r)){ui.maxHR=Math.max(ui.maxHR,Math.ceil(r.hr/50)*50);ui.maxRR=Math.max(ui.maxRR,Math.ceil(r.rr_ms/500)*500)}}
      qs('#ovStatus').textContent=`${fmtNumber(ui.rows.length)} 条逐搏记录 · 修订 r${data.revision}`;draw();renderEpisodes();
    }catch(error){if(token===ui.loadToken)qs('#ovStatus').innerHTML=`读取失败 · ${button('重试','reload')}`;throw error}
  }
  function prepare(canvas,height){
    const box=canvasContext(canvas,height),{ctx,width}=box;ctx.clearRect(0,0,width,height);ctx.fillStyle='#fbfdfd';ctx.fillRect(0,0,width,height);ctx.font=`10px ${UI_FONT}`;
    return {...box,l:42,r:12,t:6,b:18,w:Math.max(1,width-54),h:Math.max(1,height-24)};
  }
  function axis(g,maxY,start,end,units=''){const {ctx,l,w,h,t,height}=g;ctx.strokeStyle='#e2eaed';ctx.fillStyle='#526773';ctx.textAlign='right';for(const f of [0,.5,1]){const y=t+h*(1-f);ctx.beginPath();ctx.moveTo(l,y);ctx.lineTo(l+w,y);ctx.stroke();ctx.fillText(Math.round(maxY*f)+units,l-5,y+3)}ctx.textAlign='left';ctx.fillText(formatElapsed(start),l,height-3);ctx.textAlign='right';ctx.fillText(formatElapsed(end),l+w,height-3);ctx.textAlign='left'}
  function shade(g,start,end){
    const {ctx,l,w,h,t}=g,range=span(),map=v=>l+(v-start)/(end-start)*w;
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
    ctx.restore();
  }
  function drawHistogram(){
    const canvas=qs('#ovHistogram');if(!canvas.getClientRects().length||!ui.hist)return;const g=prepare(canvas,76),{ctx,l,w,h,t,height}=g,bins=ui.hist.bins,max=Math.max(1,...bins.map(x=>x.count)),scale=v=>ui.log?Math.log10(v+1)/Math.log10(max+1):v/max;
    ctx.fillStyle='#526773';ctx.textAlign='right';for(const f of [0,.5,1]){const value=ui.log?Math.round((max+1)**f-1):Math.round(max*f),y=t+h*(1-f);ctx.fillText(fmtNumber(value),l-5,y+3);ctx.strokeStyle='#e2eaed';ctx.beginPath();ctx.moveTo(l,y);ctx.lineTo(l+w,y);ctx.stroke()}ctx.textAlign='left';
    const bar=w/bins.length;bins.forEach((b,i)=>{ctx.fillStyle=ui.bin===i?'#d39235':'#4ba6ad';ctx.fillRect(l+i*bar,t+h-h*scale(b.count),Math.max(.8,bar-1),h*scale(b.count))});
    const ticks=w<420?2:6;for(let i=0;i<=ticks;i++){ctx.textAlign=i===ticks?'right':i===0?'left':'center';ctx.fillStyle='#526773';ctx.fillText((i===ticks?bins.at(-1).start+'+':Math.round(ui.hist.max*i/ticks))+(ui.ratio?'%':' ms'),l+w*i/ticks,height-3)}ctx.textAlign='left';
    geometries.set(canvas,{...g,kind:'hist'});qs('#ovHistInfo').textContent=ui.bin===null?`横轴 ${ui.ratio?'相邻 RR 比值（%）':'RR（ms）'} · 纵轴心搏数${ui.log?'，log10(n+1)':''}`:`${ui.bin===bins.length-1?'≥'+bins[ui.bin].start:bins[ui.bin].start+'–'+bins[ui.bin].end}${ui.ratio?'%':' ms'} · ${fmtNumber(bins[ui.bin].count)} 搏`;
  }
  const colors={N:'#263c46',S:'#269766',V:'#d04a45',X:'#a5b0b7',A:'#854a9b',C:'#aa6b28'};
  function drawScatter(canvas=qs('#scatterCanvas')){
    if(!canvas?.getClientRects().length||!ui.rows.length)return;
    const af=canvas.id==='ovAFLorenz';
    // The overview owns a flex-sized plot slot. Measure it, not the old square
    // canvas height, so resizing/disclosing controls cannot leave blank space.
    const height=af?Math.max(110,canvas.clientWidth-30):Math.max(1,canvas.parentElement.clientHeight);
    const points=E.pairs(ui.rows,af?'rr':ui.mode,ui.hour).filter(r=>!af||(r.time_s>=span()[0]&&r.time_s<=span()[1])),g=prepare(canvas,height),{ctx,l,w,h,t}=g,bound=ui.bound;
    if(!af){ui.scatter=points;state.scatterData={mode:ui.mode,points,bounds:{x_min:0,x_max:bound,y_min:0,y_max:bound},hour_start_s:ui.hour};qs('#scatterLoading').hidden=true;if(ui.rangeBounds!==bound){ui.rangeBounds=bound;initializeScatterRangeInputs(state.scatterData.bounds)}}geometries.set(canvas,{...g,kind:'scatter',points,bound});
    ctx.strokeStyle='#d1dde2';ctx.strokeRect(l,t,w,h);ctx.fillStyle='#526773';ctx.fillText('RR(i+1) · ms',l+4,t+10);ctx.fillText('0',l-12,t+h+12);ctx.textAlign='right';ctx.fillText(bound+' ms · RR(i)',l+w,t+h+14);ctx.textAlign='left';ctx.fillText(String(bound),1,t+8);
    ctx.save();ctx.beginPath();ctx.rect(l,t,w,h);ctx.clip();
    if(ui.guides){ctx.setLineDash([4,4]);ctx.strokeStyle='#9fb0b8';for(const slope of [.5,1,2]){ctx.beginPath();ctx.moveTo(l,t+h);ctx.lineTo(l+w,t+h-h*slope);ctx.stroke()}ctx.setLineDash([])}
    for(const r of points){if(r.x>bound||r.y>bound)continue;ctx.fillStyle=state.scatterSelectedSet.has(r.sample_index)?'#d08a2e':colors[r.class_code]||'#854a9b';ctx.fillRect(l+r.x/bound*w,t+h-r.y/bound*h,ui.size,ui.size)}
    if(ui.polygon.length){ctx.strokeStyle='#078986';ctx.fillStyle='rgba(11,146,144,.12)';ctx.beginPath();ui.polygon.forEach(([x,y],i)=>i?ctx.lineTo(l+x/bound*w,t+h-y/bound*h):ctx.moveTo(l+x/bound*w,t+h-y/bound*h));ctx.closePath();ctx.fill();ctx.stroke()}ctx.restore();
    if(!af)qs('#ovScatterCount').textContent=`${fmtNumber(points.length)} 个相邻 RR 配对 · 已选 ${fmtNumber(state.scatterSelectedSamples.length)} 搏`;
  }
  function selectSamples(samples){
    clearScatterSelection();state.scatterSelectedSamples=[...new Set(samples)].sort((a,b)=>a-b);state.scatterSelectedSet=new Set(state.scatterSelectedSamples);
    qs('#scatterSelectionCount').textContent=fmtNumber(samples.length)+' 搏';qs('#clearScatterSelection').disabled=!samples.length;qs('#scatterSelectionList').scrollTop=0;renderScatterSelectionList();drawScatter();
  }
  function drawStats(){const s=E.stats(ui.rows,ui.settings?.pause||2.5),pct=n=>`${fmtNumber(n)} (${(n/Math.max(1,s.total)*100).toFixed(2)}%)`;
    qs('#ovStatistics').innerHTML=[['总心搏（源报告估算）',ui.estimated==null?'—':fmtNumber(ui.estimated)],['总心搏（当前有效）',fmtNumber(s.valid)],['伪差',pct(s.counts.X||0)],['室早',pct(s.counts.V||0)],['房早',pct(s.counts.S||0)],['停搏 / 长 RR 候选',`${s.pauses} 次（≥${ui.settings?.pause||2.5} s）`]].map(([k,v])=>`<div><dt>${k}</dt><dd>${v}</dd></div>`).join('')+Object.entries(ui.rhythm?.document.bookmarks||{}).map(([key,time])=>`<div><dt>${({fastest:'最快心率',slowest:'最慢心率',fastest_nn:'最快窦性',slowest_nn:'最慢窦性'})[key]}书签</dt><dd>${button(formatElapsed(time),'bookmark-jump:'+time)}</dd></div>`).join('');
  }
  function draw(){
    if(!ui.rows.length)return;ui.hour=hour();const end=Math.min(duration(),ui.hour+3600);qs('#ovRange').textContent=`选区 ${formatElapsed(span()[0])}–${formatElapsed(span()[1])}`;
    if(ui.af){drawTime(qs('#ovAFFull'),0,duration(),'rr');drawScatter(qs('#ovAFLorenz'));qs('#ovAFHour').textContent=`${formatElapsed(ui.hour)}–${formatElapsed(end)}`;for(let i=0;i<4;i++){const c=qs('#ovQuarter'+i),start=ui.hour+i*900;c.closest('.ov-lane').hidden=start>=duration();if(start<duration())drawTime(c,start,start+900,'rr')}}
    else{drawHistogram();drawTime(qs('#ovFullHR'),0,duration(),'hr');drawTime(qs('#ovHourHR'),ui.hour,end,'hr');drawTime(qs('#ovFullRR'),0,duration(),'rr');drawTime(qs('#ovHourRR'),ui.hour,end,'rr');drawScatter();drawStats()}
  }
  function seek(time,keepRange=false){
    if(!keepRange)ui.range=null;
    state.locatedTime={caseId:state.caseId,time:Number(time)||0};
    state.start=E.clamp(Number(time)||0,0,Math.max(0,duration()-state.duration));state.editStart=state.start;ui.hour=hour();draw();return run(()=>loadWaveform());
  }
  function timeAt(event,canvas){const g=geometries.get(canvas),r=canvas.getBoundingClientRect();return g?E.clamp(g.start+(event.clientX-r.left-g.l)/g.w*(g.end-g.start),g.start,g.end):state.start}
  function scatterAt(event,canvas){const g=geometries.get(canvas),r=canvas.getBoundingClientRect();return [E.clamp((event.clientX-r.left-g.l)/g.w,0,1)*g.bound,E.clamp(1-(event.clientY-r.top-g.t)/g.h,0,1)*g.bound]}
  function inside(x,y,poly){let hit=false;for(let i=0,j=poly.length-1;i<poly.length;j=i++){const a=poly[i],b=poly[j];if((a[1]>y)!==(b[1]>y)&&x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0])hit=!hit}return hit}
  function closeMenu(){const menu=qs('#ovMenu');try{menu.hidePopover()}catch(_){}menu.hidden=true}
  function group(title,items){return `<details><summary>${title}</summary>${items}</details>`}
  function showMenu(kind,event,canvasId){
    if(!ui.rows.length)return;event?.preventDefault?.();const canvas=qs('#'+(canvasId||'ovFullRR')),rect=canvas.getBoundingClientRect(),x=event?.clientX??rect.left+50,y=event?.clientY??rect.top+20;
    if(kind!=='scatter'&&event?.clientX!==undefined){ui.contextTime=timeAt(event,canvas);const [a,b]=span();if(ui.contextTime<a||ui.contextTime>b){ui.range=[ui.contextTime,Math.min(duration(),ui.contextTime+state.duration)];draw()}}else ui.contextTime=state.start;
    const codes=['N','S','V','X','A','C','P','O','OTHER'],types=action=>codes.map(c=>button(`${c} · ${ECGBeatEngine.types[c].name}`,action+':'+c)).join('');let html='';
    if(kind==='rr')html=button('添加房颤段','af-add:AF')+button('添加房扑段','af-add:AFL')+button('删除当前房颤 / 房扑','af-delete-current')+button('移除选区内的房颤 / 房扑','af-cut')+button('移除所有房颤 / 房扑段','af-clear')+button('标记为全程房颤','af-all:AF')+button('标记为全程房扑','af-all:AFL')+button('重分析房颤','af-screen')+button('进入房颤编辑与分析','af-open');
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
    const value=await request('rhythm-review',{method:'PUT',body:JSON.stringify({document,operation,revision:base.revision,beat_revision:ui.revision,confirmed:true})});
    if(id!==state.caseId)return;ui.rhythm=value;qs('#ovDialog').close();state.reportComposer=null;await clinicalWorkflow.refresh(id);renderEpisodes();draw();toast('片段复核已保存 · 可撤销','success');
  }
  function confirmRhythm(title,document,detail){
    const count=document.episodes.filter(x=>x.status!=='excluded').length;
    dialog(title,`<p>${esc(detail)}</p><p>保存后保留 ${count} 段。片段边界和复核状态会同步到报告事件；源波形不变，可撤销。</p>`,()=>saveRhythm(document));
  }
  function episodeForm(kind='AF',whole=false){
    const bounds=whole?[0,duration()]:span();dialog(whole?'标记全程'+name(kind):'添加'+name(kind)+'片段',`<p>${whole?'将替换现有片段，原记录保留在撤销历史。':'输入记录起点后的秒数；核对波形后再确认诊断。'}</p><div class="ov-fields"><label>开始（秒）<input name="start" type="number" step=".005" min="0" max="${duration()}" value="${bounds[0].toFixed(3)}" required></label><label>结束（秒）<input name="end" type="number" step=".005" min="0" max="${duration()}" value="${bounds[1].toFixed(3)}" required></label><label>类型<select name="kind"><option value="AF" ${kind==='AF'?'selected':''}>房颤</option><option value="AFL" ${kind==='AFL'?'selected':''}>房扑</option></select></label><label>复核状态<select name="status"><option value="pending">待复核</option><option value="confirmed">医生确认</option></select></label><label class="ov-wide">备注<textarea name="note" maxlength="1000" rows="2"></textarea></label></div>`,data=>{
      const start=Number(data.get('start')),end=Number(data.get('end')),doc=copy(ui.rhythm.document);if(whole)doc.episodes=[];
      doc.episodes.push({id:crypto.randomUUID(),start_s:start,end_s:end,kind:data.get('kind'),status:data.get('status'),source:'manual',note:data.get('note')});E.validateDocument(doc,duration());return saveRhythm(doc);
    });
  }
  function renderEpisodes(){
    if(!ui.rhythm)return;const episodes=ui.rhythm.document.episodes,confirmed=episodes.filter(x=>x.status==='confirmed'),pending=episodes.filter(x=>x.status==='pending'),seconds=confirmed.reduce((n,x)=>n+x.end_s-x.start_s,0);
    qs('#ovAFSummary').textContent=`确认 ${confirmed.length} 段 · 待复核 ${pending.length} 段 · 确认负荷 ${(seconds/duration()*100).toFixed(2)}%`;
    qs('#ovEpisodeRows').innerHTML=episodes.length?episodes.map(x=>`<tr ${ui.episode===x.id?'aria-selected="true"':''}><td>${button(formatElapsed(x.start_s),'episode:'+x.id)}<small>${((x.end_s-x.start_s)/60).toFixed(2)} 分钟</small></td><td>${name(x.kind)}</td><td>${statusName(x.status)}</td></tr>`).join(''):'<tr><td colspan="3">暂无片段。可框选 RR 时段添加，或重分析 RR 候选。</td></tr>';
    qs('[data-ov="af-undo"]').disabled=!ui.rhythm.can_undo;qs('[data-ov="af-redo"]').disabled=!ui.rhythm.can_redo;
    const x=episodes.find(x=>x.id===ui.episode),editor=qs('#ovEpisodeEditor');if(!x){editor.innerHTML='<p>选择左侧片段可调整起止、类型和复核状态。</p>';return}
    editor.innerHTML=`<details class="ov-episode-details" ${innerWidth>1500?'open':''}><summary>编辑选中片段 · ${formatElapsed(x.start_s)} · ${statusName(x.status)}</summary><form id="ovEpisodeForm"><h3>编辑选中片段</h3><div class="ov-fields"><label>开始（秒）<input name="start" type="number" step=".005" value="${x.start_s}" required></label><label>结束（秒）<input name="end" type="number" step=".005" value="${x.end_s}" required></label><label>类型<select name="kind"><option value="AF" ${x.kind==='AF'?'selected':''}>房颤</option><option value="AFL" ${x.kind==='AFL'?'selected':''}>房扑</option></select></label><label>复核状态<select name="status">${['pending','confirmed','excluded'].map(s=>`<option value="${s}" ${s===x.status?'selected':''}>${statusName(s)}</option>`).join('')}</select></label><label class="ov-wide">备注<textarea name="note" rows="2" maxlength="1000">${esc(x.note||'')}</textarea></label></div><footer><span>${esc(x.source)}</span>${button('删除片段','af-delete-current')}<button type="submit" class="button primary">核对并保存片段</button></footer></form></details>`;
    qs('#ovEpisodeForm').onsubmit=event=>{event.preventDefault();const data=new FormData(event.target),doc=copy(ui.rhythm.document),item=doc.episodes.find(e=>e.id===x.id);Object.assign(item,{start_s:Number(data.get('start')),end_s:Number(data.get('end')),kind:data.get('kind'),status:data.get('status'),note:data.get('note')});run(()=>{E.validateDocument(doc,duration());confirmRhythm('确认片段修订',doc,`${name(item.kind)} · ${formatElapsed(item.start_s)}–${formatElapsed(item.end_s)} · ${statusName(item.status)}`)})};
  }
  function afMode(enabled){
    ui.af=enabled;const page=qs('#page-review'),wave=qs('#waveformCard');page.classList.toggle('ov-af-mode',enabled);qs('#ovAF').hidden=!enabled;
    if(enabled&&!ui.range)ui.range=[hour(),Math.min(duration(),hour()+3600)];
    if(enabled)qs('#ovAFWaveHost').append(wave);else page.querySelector('.analysis-main').insertBefore(wave,qs('.ov-navigator'));
    draw();renderEpisodes();renderWaveform();
  }
  function screenAF(){
    const candidates=E.screenAF(ui.rows,duration()),preserved=ui.rhythm.document.episodes.filter(x=>x.source!=='rr-irregularity-v1');
    const fresh=candidates.flatMap(x=>{let pieces=[x];for(const y of preserved)pieces=E.cut(pieces,y.start_s,y.end_s);return pieces});
    confirmRhythm('RR 不规则候选重分析',{...ui.rhythm.document,episodes:preserved.concat(fresh)},`检出 ${fresh.length} 段 RR 不规则候选，全部为待复核；未进行 P 波识别，不自动识别房扑。保留人工与既有源片段，替换此前本算法的候选。`);
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
    const [start,end]=span(),wave=await request('waveform?'+new URLSearchParams({start,duration:Math.max(1,Math.min(12,end-start)),leads:leads===12?ALL_LEADS.join(','):'II,V1,V5',filter:state.filter,max_points:2400}));
    const entries=Object.entries(wave.leads),row=leads===12?95:180,width=1000,height=entries.length*row;
    const paths=entries.map(([lead,values],i)=>{const scale=row*.35/Math.max(100,...values.map(Math.abs)),base=row*(i+.5);return `<text x="0" y="${row*i+15}">${lead}</text><path d="${values.map((v,j)=>`${j?'L':'M'}${(35+j/(values.length-1)*950).toFixed(1)},${(base-v*scale).toFixed(1)}`).join(' ')}" fill="none" stroke="#223f4b" stroke-width="1"/>`}).join('');
    dialog('图条打印预览',`<div id="ovPrintSheet"><h2>心电图条 · ${esc(state.caseData.metadata.name)}</h2><p>${formatElapsed(wave.start_s)}–${formatElapsed(wave.start_s+wave.duration_s)} · 自适应幅度，非标准走纸比例</p><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="待打印心电图条">${paths}</svg></div>`,()=>{document.body.classList.add('ov-print-strip');window.print();},'打印 A4 图条');
  }
  async function navigatorWave(){
    if(!state.caseId||ui.af||state.currentPage!=='review')return;const seconds=Math.min(120,Math.max(30,state.duration*3)),start=E.clamp(state.start-seconds/3,0,Math.max(0,duration()-seconds)),key=[state.caseId,start,seconds,state.filter].join(':');
    if(ui.navKey!==key){ui.navKey=key;const result=await request('waveform?'+new URLSearchParams({start,duration:seconds,leads:'II',filter:state.filter,max_points:2400}));if(ui.navKey!==key)return;ui.nav=result}
    const wave=ui.nav,canvas=qs('#ovNavigator');if(!wave||!canvas.getClientRects().length)return;const g=prepare(canvas,60),{ctx,l,w,h,t}=g,values=wave.leads.II||[],limit=Math.max(100,...values.map(Math.abs));geometries.set(canvas,{...g,start:wave.start_s,end:wave.start_s+wave.duration_s,kind:'navigator'});
    shade(g,wave.start_s,wave.start_s+wave.duration_s);ctx.strokeStyle='#334f5b';ctx.beginPath();values.forEach((v,i)=>{const x=l+i/(values.length-1)*w,y=t+h/2-v/limit*h*.45;i?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.stroke();qs('#ovNavigatorTime').textContent=formatElapsed(wave.start_s)+'–'+formatElapsed(wave.start_s+wave.duration_s);
  }
  function waveformOverlay(){
    const canvas=qs('#waveformCanvas'),wave=state.waveform;if(!wave||!canvas?.getClientRects().length)return;const ctx=canvas.getContext('2d'),rect=canvas.getBoundingClientRect(),width=rect.width,height=rect.height;
    const beats=wave.beats||[],minimum=width/Math.max(1,beats.length);ctx.fillStyle='#35616a';ctx.font=`9px ${UI_FONT}`;
    if(minimum>32)beats.forEach(r=>{const x=(r.time_s-wave.start_s)/wave.duration_s*width;if(x>=0&&x<width-20){ctx.fillText(r.hr?Math.round(r.hr)+' bpm':'—',x+3,23);ctx.fillText(r.rr_ms?r.rr_ms+' ms':'—',x+3,34)}});
    if(!ui.ruler||!ui.rulerPoints.length)return;const points=ui.rulerPoints,xAt=t=>(t-wave.start_s)/wave.duration_s*width;
    ctx.save();ctx.strokeStyle='#b9671d';ctx.fillStyle='#965119';ctx.lineWidth=1;
    if(ui.ruler==='parallel'){points.forEach(p=>{const y=p.y*height;ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(width,y);ctx.stroke()})}
    else {const delta=points.length===2?Math.abs(points[1].time-points[0].time):0,positions=ui.ruler==='divider'&&delta>.02?Array.from({length:Math.min(120,Math.ceil(wave.duration_s/delta)+3)},(_,i)=>points[0].time+(i-Math.ceil((points[0].time-wave.start_s)/delta))*delta):points.map(p=>p.time);positions.forEach(t=>{const x=xAt(t);ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,height);ctx.stroke()})}
    if(points.length===2){const delta=Math.abs(points[1].time-points[0].time),leadCount=Object.keys(wave.leads).length,sameLead=Math.floor(points[0].y*leadCount)===Math.floor(points[1].y*leadCount),amplitude=Math.abs(points[1].y-points[0].y)*leadCount*1000/.31/(state.gain/10),text=ui.ruler==='parallel'?(sameLead?`Δ幅度 ${amplitude.toFixed(1)} 设备标度（未溯源）`:'请在同一导联内放置两条平行线'):`Δt ${(delta*1000).toFixed(0)} ms${delta>0?' · '+(60/delta).toFixed(1)+' bpm':''}`;ctx.fillStyle='#fff8ed';ctx.fillRect(40,height-28,Math.min(330,width-40),24);ctx.fillStyle='#965119';ctx.fillText(text,48,height-12)}ctx.restore();
  }
  async function action(value,element){
    const [key,...tail]=value.split(':'),arg=tail.join(':');if(key.startsWith('menu-')&&key!=='menu-close')return showMenu(key.slice(5),null,element?.dataset.canvas);
    closeMenu();
    if(key==='menu-close')return;
    if(key==='dialog-close'){qs('#ovDialog').close();return}
    if(key==='reload')return load(true);
    if(key==='clear-range'){ui.range=null;ui.rangeAnchor=null;draw();return}
    if(key==='hist-rr'||key==='hist-ratio'){ui.ratio=key==='hist-ratio';ui.bin=null;ui.hist=E.histogram(ui.rows,ui.ratio);qs('[data-ov="hist-rr"]').setAttribute('aria-pressed',String(!ui.ratio));qs('[data-ov="hist-ratio"]').setAttribute('aria-pressed',String(ui.ratio));drawHistogram();return}
    if(key==='af-open'||key==='af-close'){afMode(key==='af-open');return}
    if(key==='af-prev'||key==='af-next'){seek(ui.hour+(key==='af-next'?3600:-3600));return}
    if(key==='af-add'||key==='af-all')return episodeForm(arg||'AF',key==='af-all');
    if(key==='af-screen')return screenAF();
    if(key==='af-undo'||key==='af-redo')return saveRhythm(null,key==='af-undo'?'undo':'redo');
    if(key==='episode'){ui.episode=arg;const x=ui.rhythm.document.episodes.find(x=>x.id===arg);if(x){ui.range=[x.start_s,x.end_s];seek(x.start_s,true);renderEpisodes()}return}
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
    if(key==='mode'){ui.mode=arg;state.scatterMode=arg;ui.polygon=[];clearScatterSelection();document.querySelectorAll('[data-scatter-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.scatterMode===arg)));drawScatter();return}
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
    const ruler=document.createElement('div');ruler.id='ovRulerStatus';ruler.className='ov-ruler-status';ruler.hidden=true;qs('#waveformCard').prepend(ruler);
    document.addEventListener('click',event=>{const button=event.target.closest('[data-ov]');if(button){event.preventDefault();run(()=>action(button.dataset.ov,button))}},true);
    qs('#ovLog').onchange=event=>{ui.log=event.target.checked;drawHistogram()};qs('#ovScatterRange').onchange=event=>run(()=>action('bound:'+event.target.value));
    let drag=null;
    const own=target=>target.closest?.('[data-ov-plot],#ovHistogram,#ovNavigator');
    document.addEventListener('pointerdown',event=>{
      if(!qs('#ovMenu').hidden&&!event.target.closest('#ovMenu'))closeMenu();
      const canvas=own(event.target);if(!canvas||event.button!==0||!ui.rows.length)return;const g=geometries.get(canvas);if(!g)return;event.preventDefault();event.stopImmediatePropagation();canvas.focus({preventScroll:true});canvas.setPointerCapture(event.pointerId);
      const rect=canvas.getBoundingClientRect(),point={x:event.clientX-rect.left,y:event.clientY-rect.top};drag={canvas,g,point,last:point,time:g.kind==='scatter'||g.kind==='density'||g.kind==='hist'?null:timeAt(event,canvas),points:g.kind==='scatter'?[scatterAt(event,canvas)]:[]};
    },true);
    document.addEventListener('pointermove',event=>{
      const canvas=own(event.target);if(!canvas)return;const g=geometries.get(canvas);if(!g)return;const rect=canvas.getBoundingClientRect(),point={x:event.clientX-rect.left,y:event.clientY-rect.top};
      if(g.kind==='hr'||g.kind==='rr'){const time=timeAt(event,canvas),value=E.clamp(1-(point.y-g.t)/g.h,0,1)*g.maxY,output=qs(`[data-coordinate="${canvas.id}"]`);if(output)output.textContent=`${formatElapsedPrecise(time)} · ${value.toFixed(0)} ${g.kind==='hr'?'bpm':'ms'}`}
      if(!drag||drag.canvas!==canvas)return;event.preventDefault();event.stopImmediatePropagation();drag.last=point;
      if(g.kind==='scatter'){
        const current=scatterAt(event,canvas),first=drag.points[0];if(ui.selectionMode==='lasso')drag.points.push(current);ui.polygon=ui.selectionMode==='lasso'?drag.points:[first,[current[0],first[1]],current,[first[0],current[1]]];drawScatter(canvas);return;
      }
      if(g.kind!=='hist'){const time=timeAt(event,canvas);ui.range=[Math.min(drag.time,time),Math.max(drag.time,time)];draw()}
    },true);
    document.addEventListener('pointerup',event=>{
      if(!drag)return;const job=drag;drag=null;event.preventDefault();event.stopImmediatePropagation();const {canvas,g,point,last}=job,dist=Math.hypot(last.x-point.x,last.y-point.y);
      if(g.kind==='hist'){ui.bin=E.clamp(Math.floor((point.x-g.l)/g.w*ui.hist.bins.length),0,ui.hist.bins.length-1);selectSamples(ui.hist.bins[ui.bin].samples);drawHistogram();return}
      if(g.kind==='scatter'){
        if(dist<4||ui.selectionMode==='point'){const [x,y]=scatterAt(event,canvas),nearest=g.points.reduce((a,b)=>!a||Math.hypot(b.x-x,b.y-y)<Math.hypot(a.x-x,a.y-y)?b:a,null);ui.polygon=[];if(nearest){selectSamples([nearest.sample_index]);seek(nearest.time_s)}}
        else selectSamples(g.points.filter(r=>inside(r.x,r.y,ui.polygon)).map(r=>r.sample_index));return;
      }
      const time=timeAt(event,canvas);if(ui.rangeAnchor!==undefined&&ui.rangeAnchor!==null){ui.range=[Math.min(ui.rangeAnchor,time),Math.max(ui.rangeAnchor,time)];ui.rangeAnchor=null;seek(ui.range[0],true)}else if(dist<4)seek(time);else{if(span()[1]-span()[0]<.005)ui.range=null;seek(span()[0],true)}
    },true);
    document.addEventListener('click',event=>{if(own(event.target)){event.preventDefault();event.stopImmediatePropagation()}
      const mode=event.target.closest('[data-scatter-mode]');if(mode){event.preventDefault();event.stopImmediatePropagation();run(()=>action('mode:'+mode.dataset.scatterMode))}
      if(event.target.id==='waveformCanvas'&&ui.ruler){event.preventDefault();event.stopImmediatePropagation();const r=event.target.getBoundingClientRect();if(ui.rulerPoints.length===2)ui.rulerPoints=[];ui.rulerPoints.push({time:state.waveform.start_s+(event.clientX-r.left)/r.width*state.waveform.duration_s,y:(event.clientY-r.top)/r.height});renderWaveform()}
    },true);
    document.addEventListener('contextmenu',event=>{const canvas=own(event.target);if(!canvas)return;event.preventDefault();event.stopImmediatePropagation();const kind=geometries.get(canvas)?.kind;if(['hr','rr','scatter'].includes(kind))showMenu(kind,event,canvas.id)},true);
    document.addEventListener('keydown',event=>{
      if(qs('#ovDialog').open){event.stopImmediatePropagation();return}
      const menu=qs('#ovMenu');if(!menu.hidden){if(event.key==='Escape'){closeMenu();event.preventDefault();event.stopImmediatePropagation();return}if(['ArrowDown','ArrowUp'].includes(event.key)){const items=[...menu.querySelectorAll('button,summary')].filter(x=>x.getClientRects().length),index=items.indexOf(document.activeElement);items[(index+(event.key==='ArrowDown'?1:-1)+items.length)%items.length]?.focus();event.preventDefault();event.stopImmediatePropagation()}return}
      const canvas=own(event.target);if(!canvas)return;
      if(event.shiftKey&&event.key==='F10'){const g=geometries.get(canvas);if(['rr','hr','scatter'].includes(g?.kind)){showMenu(g.kind,null,canvas.id);event.preventDefault();event.stopImmediatePropagation()}return}
      if(event.key==='Escape'){ui.range=null;ui.polygon=[];ui.densityBox=null;draw();return}
      if(['ArrowLeft','ArrowRight'].includes(event.key)){event.preventDefault();event.stopImmediatePropagation();const direction=event.key==='ArrowLeft'?-1:1;if(canvas.id==='ovHistogram'){ui.bin=E.clamp((ui.bin??0)+direction,0,ui.hist.bins.length-1);selectSamples(ui.hist.bins[ui.bin].samples);drawHistogram()}else seek(state.start+direction*(event.shiftKey?60:state.duration))}
    },true);
    window.addEventListener('afterprint',()=>document.body.classList.remove('ov-print-strip'));
    new ResizeObserver(()=>requestAnimationFrame(()=>{draw();run(navigatorWave)})).observe(qs('#page-review'));
    new ResizeObserver(()=>requestAnimationFrame(()=>drawScatter())).observe(qs('.scatter-canvas-wrap'));
  }
  const previousCase=loadCase,previousWave=renderWaveform,previousAnnotations=renderAnnotations;
  loadCase=async(...args)=>{const result=await previousCase(...args);if(result)await load(true);return result};
  renderOverview=()=>{draw();run(navigatorWave)};
  renderScatter=()=>drawScatter();
  loadScatter=async()=>{await load();ui.mode=state.scatterMode;drawScatter()};
  applyScatterSelectionPolygon=async polygon=>{ui.polygon=polygon;selectSamples(E.pairs(ui.rows,ui.mode,ui.hour).filter(r=>inside(r.x,r.y,polygon)).map(r=>r.sample_index))};
  renderWaveform=()=>{previousWave();waveformOverlay()};
  renderAnnotations=items=>{previousAnnotations(items.filter(x=>!x.internal).map(x=>String(x.id).startsWith('af:')?{...x,note:(x.note||'')+'（在房颤分析页编辑）'}:x));qs('#annotationList').querySelectorAll('[data-delete-annotation]').forEach(b=>{if(b.dataset.deleteAnnotation.startsWith('af:'))b.remove()})};
  document.addEventListener('DOMContentLoaded',mount);
  return {load,draw};
})();
