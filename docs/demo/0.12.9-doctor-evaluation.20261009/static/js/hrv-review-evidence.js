"use strict";
/* Read-only view of the server's existing HRV payload; no calculation or report mutation. */
globalThis.ECGHrvReview=(()=>{
  const bookmarks=new Map();
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const finite=Number.isFinite,n=x=>finite(x)?String(Math.round(x*100)/100):'—';
  const time=s=>finite(s)?`${Math.floor(s/3600)}:${String(Math.floor(s%3600/60)).padStart(2,'0')}:${String(Math.floor(s%60)).padStart(2,'0')}`:'—';
  const metrics=[['mean_nn_ms','平均 NN','ms'],['sdnn_ms','SDNN','ms'],['sdann_ms','SDANN','ms'],['sdnn_index_ms','SDNN index','ms'],['rmssd_ms','rMSSD','ms'],['pnn50_pct','pNN50','%'],['triangular_index','三角指数','']];
  const frequencies=[['total_ms2','总功率','ms²'],['vlf_ms2','VLF','ms²'],['lf_ms2','LF','ms²'],['hf_ms2','HF','ms²'],['lf_hf','LF/HF','']];
  function rows(data){
    return [...['full','day','night'].filter(k=>data.periods?.[k]).map(k=>({key:k,kind:k,row:data.periods[k]})),...(data.hourly||[]).map((row,i)=>({key:'hour-'+i,kind:'hour',row}))];
  }
  function label(entry){return entry.row.label||({full:'全程',day:'日间',night:'夜间'})[entry.kind]||'逐小时';}
  function range(data,entry){
    if(entry.kind==='day'||entry.kind==='night')return data.clock_available?'窗口内钟点分段（不代表实际睡眠）':'记录起始时钟不可用，未计算';
    const r=entry.kind==='hour'?entry.row:data;
    return `记录后 ${time(r.start_s)}–${time(r.end_s)}${entry.row.partial?' · 首尾非完整小时':''}`;
  }
  function plot(points,xkey,ykey,{bars=false,title,empty,width=450}){
    points=Array.isArray(points)?points:[];
    const valid=points.filter(p=>p&&finite(p[xkey])&&finite(p[ykey]));
    if(!valid.length)return `<p class="hrvr-empty">${esc(empty)}</p>`;
    const w=Math.max(200,Math.round(width)),h=210,l=72,r=20,t=28,b=35,xmin=0,xmax=Math.max(bars?1:.5,...valid.map(p=>p[xkey])),ymax=Math.max(1,...valid.map(p=>p[ykey]));
    const x=v=>l+(v-xmin)/(xmax-xmin)*(w-l-r),y=v=>h-b-v/ymax*(h-t-b);
    let shape='';
    if(bars){const width=Math.max(.8,Math.min(12,(w-l-r)/valid.length*.75));shape=valid.map(p=>`<rect x="${(x(p[xkey])-width/2).toFixed(2)}" y="${y(p[ykey]).toFixed(2)}" width="${width}" height="${Math.max(.5,y(0)-y(p[ykey])).toFixed(2)}"/>`).join('');}
    else{let path='',pen=false;for(const p of points){if(!p||!finite(p[xkey])||!finite(p[ykey])){pen=false;continue;}path+=`${pen?'L':'M'}${x(p[xkey]).toFixed(2)} ${y(p[ykey]).toFixed(2)} `;pen=true;}shape=`<path d="${path}" fill="none" stroke="currentColor" stroke-width="1.7"/>`;shape+=points.filter((p,i)=>p&&finite(p[xkey])&&finite(p[ykey])&&(!points[i-1]||!finite(points[i-1][ykey]))&&(!points[i+1]||!finite(points[i+1][ykey]))).map(p=>`<circle cx="${x(p[xkey])}" cy="${y(p[ykey])}" r="2"/>`).join('');}
    return `<svg viewBox="0 0 ${w} ${h}" role="img" data-inspect-chart data-inspect-title="${esc(title)}" aria-label="${esc(title)}"><title>${esc(title)}</title><g class="hrvr-axes"><path d="M${l} ${t}V${h-b}H${w-r}" fill="none" stroke="currentColor"/><text x="${l-7}" y="${t+4}" text-anchor="end">${n(ymax)}</text><text x="${l-7}" y="${h-b}" text-anchor="end">0</text><text x="${l}" y="${h-9}">0</text><text x="${w-r}" y="${h-9}" text-anchor="end">${n(xmax)} ${bars?'ms':'Hz'}</text><text x="${l}" y="16">${bars?'NN 间期数':'ms²/Hz'}</text></g><g class="hrvr-series">${shape}</g></svg>`;
  }
  function detail(data,entry,width=450){
    if(!entry)return '<p class="hrvr-empty">暂无可复核 HRV 时段。</p>';
    const row=entry.row,noClock=['day','night'].includes(entry.kind)&&!data.clock_available;
    const cell=([k,title,unit],source=row)=>`<div><dt>${esc(title)}</dt><dd>${noClock?'—':n(source?.[k])}${unit?' <small>'+unit+'</small>':''}</dd></div>`;
    return `<header><h3>${esc(label(entry))}</h3><p>${esc(range(data,entry))}</p></header><dl class="hrvr-metrics">${metrics.map(m=>cell(m)).join('')}</dl><p class="hrvr-coverage">${noClock?'该钟点分段不可用。':`${n(row.nn_count)} NN · 有效 NN ${n(finite(row.valid_nn_s)?row.valid_nn_s/3600:null)} / 覆盖 ${n(finite(row.coverage_s)?row.coverage_s/3600:null)} h · 合格 5 分钟段 ${n(row.five_minute_blocks)} · 频谱段 ${n(row.spectral_blocks)}`}</p><div class="hrvr-plots"><figure><figcaption>NN 间期直方图 · ${esc(label(entry))}</figcaption>${plot(noClock?[]:row.histogram,'rr_ms','count',{width,bars:true,title:'NN 间期直方图，横轴 RR ms，纵轴间期数',empty:noClock?'起始时钟不可用，未计算。':'本时段无可用 NN 间期；缺失不显示为零。'})}</figure><figure><figcaption>功率谱 · ${esc(label(entry))}</figcaption>${plot(noClock?[]:row.psd,'hz','power',{width,title:'功率谱，横轴 Hz，纵轴 ms²/Hz',empty:noClock?'起始时钟不可用，未计算。':row.spectral_reason||'本时段无可用频谱。'})}</figure></div><dl class="hrvr-frequency">${frequencies.map(m=>cell(m,row.frequency)).join('')}</dl>`;
  }
  function mount(host,data,{isCurrent=()=>host.isConnected,scope=null}={}){
    host._hrvResizeObserver?.disconnect();
    const entries=rows(data),bookmark=scope?bookmarks.get(scope):null;let selected=Math.max(0,entries.findIndex(e=>e.key===bookmark?.key)),plotWidth=450;
    host.classList.add('hrvr-review');host.setAttribute('aria-label','HRV 时段证据复核');
    host.innerHTML=`<header class="hrvr-heading"><h2>时段复核</h2><p>选一行查看同一时段的指标与图形；不改变报告窗口。</p></header><div class="hrvr-layout"><div class="hrvr-table-scroll" tabindex="0" role="region" aria-label="HRV 时段列表，可滚动"><table><thead><tr><th scope="col">时段 / 记录后范围</th><th scope="col">NN 数</th><th scope="col">SDNN ms</th></tr></thead><tbody>${entries.map((e,i)=>`<tr><th scope="row"><button type="button" data-hrvr-row="${i}" aria-pressed="${i===selected}">${esc(label(e))}<small>${esc(range(data,e))}</small></button></th><td>${['day','night'].includes(e.kind)&&!data.clock_available?'—':n(e.row.nn_count)}</td><td>${['day','night'].includes(e.kind)&&!data.clock_available?'—':n(e.row.sdnn_ms)}</td></tr>`).join('')||'<tr><td colspan="3">暂无可用时段</td></tr>'}</tbody></table></div><section class="hrvr-detail" aria-label="所选时段指标与图形"></section></div><p class="hrvr-status" role="status" aria-live="polite"></p><details class="hrvr-method"><summary>统计口径与分段说明</summary><p>${esc(data.method||'使用当前服务返回的 NN 与频谱统计。')} — 表示数据不足，0 表示已有统计的零值；未对缺失区间补值。日夜为钟点分段，不推断睡眠。</p></details>`;
    const buttons=Array.from(host.querySelectorAll('[data-hrvr-row]')),body=host.querySelector('.hrvr-detail'),status=host.querySelector('.hrvr-status');
    const scroll=host.querySelector('.hrvr-table-scroll');
    function remember(){if(!scope||!isCurrent()||!host.isConnected)return;bookmarks.delete(scope);bookmarks.set(scope,{key:entries[selected]?.key,scrollTop:scroll?.scrollTop||0});while(bookmarks.size>12)bookmarks.delete(bookmarks.keys().next().value);}
    function select(index){
      if(!isCurrent()||!host.isConnected){body.innerHTML='<p class="hrvr-empty">当前病例或分析依据已变化，请重新载入 HRV。</p>';status.textContent='旧时段证据已停止显示。';host.querySelector('tbody').innerHTML='<tr><td colspan="3">旧时段统计已停止显示，请重新载入。</td></tr>';buttons.forEach(b=>{b.disabled=true;b.setAttribute('aria-pressed','false');});return false;}
      if(!Number.isInteger(index)||index<0||index>=entries.length){body.innerHTML=detail(data,null);return false;}
      selected=index;body.innerHTML=detail(data,entries[selected],plotWidth);buttons.forEach((b,i)=>b.setAttribute('aria-pressed',String(i===selected)));status.textContent=`当前复核：${label(entries[selected])} · ${range(data,entries[selected])}`;remember();return true;
    }
    buttons.forEach((b,i)=>{b.onclick=()=>select(i);b.onkeydown=event=>{const step=event.key==='ArrowDown'?1:event.key==='ArrowUp'?-1:0;if(!step)return;event.preventDefault();const next=Math.max(0,Math.min(entries.length-1,i+step));if(select(next))buttons[next].focus();};});
    function fit(){
      if(!host.isConnected){host._hrvResizeObserver?.disconnect();return;}
      if(!isCurrent()){select(selected);return;}
      const svg=body.querySelector?.('svg'),width=svg?.getBoundingClientRect().width;
      if(width>=200&&Math.abs(width-plotWidth)>1){plotWidth=width;select(selected);}
    }
    select(selected);if(scroll&&bookmark){scroll.scrollTop=bookmark.scrollTop;remember();}scroll?.addEventListener?.('scroll',remember,{passive:true});fit();
    if(typeof ResizeObserver!=='undefined'){host._hrvResizeObserver=new ResizeObserver(fit);host._hrvResizeObserver.observe(body);}
    return {select,current:()=>entries[selected]?.key};
  }
  return {mount,rows,detail,plot};
})();
if(typeof module!=='undefined'&&module.exports)module.exports=globalThis.ECGHrvReview;
