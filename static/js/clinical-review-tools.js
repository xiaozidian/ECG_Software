"use strict";
/* Geometry shared by virtual review cards and interactive R-peak locators. */
(()=>{
  function virtualGrid(total,width,scrollTop=0,design={}){
    const columns=Math.max(1,Math.min(design.columns||6,Math.floor(width/(design.minWidth||170)))),row=design.row||126,visibleRows=design.visibleRows||3,rows=Math.ceil(total/columns),height=Math.min(visibleRows,rows)*row||48;
    const top=Math.min(Math.max(0,scrollTop),Math.max(0,rows*row-height)),firstRow=Math.floor(top/row);
    return {columns,row,height,top,width:width/columns,contentHeight:rows*row,first:Math.max(0,(firstRow-1)*columns),last:Math.min(total,(firstRow+visibleRows+2)*columns),visibleFirst:total?firstRow*columns+1:0,visibleLast:Math.min(total,Math.ceil((top+height)/row)*columns)};
  }
  function markCanvas(ctx,x,top,bottom,code,options={}){
    ctx.save();ctx.globalAlpha=1;ctx.font='bold 11px sans-serif';
    const label=String(code||'?'),w=Math.max(18,ctx.measureText(label).width+8),labelY=Math.max(0,top-20),bandTop=Math.max(top,labelY+20);
    // Multiply leaves dark ECG traces dark; no opaque line crosses the R peak.
    ctx.globalCompositeOperation='multiply';ctx.fillStyle='rgba(217,75,136,.14)';ctx.fillRect(x-12,bandTop,24,Math.max(0,bottom-bandTop));
    ctx.globalCompositeOperation='source-over';ctx.fillStyle='#c92a2b';
    ctx.fillRect(x-3,bandTop,6,2);ctx.fillRect(x-3,bottom-2,6,2);
    if(options.showLabel===false){ctx.restore();return;}
    ctx.fillStyle='#fff';ctx.fillRect(x-w/2,labelY,w,18);ctx.strokeStyle='#1760c2';ctx.lineWidth=1.5;ctx.strokeRect(x-w/2,labelY,w,18);
    ctx.fillStyle='#164d9a';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(label,x,labelY+9);ctx.restore();
  }
  function markSvg(x,height,code){
    const label=String(code||'?').replace(/[^A-Za-z?]/g,'');
    return `<g class="selected-r-peak" pointer-events="none"><rect class="selected-r-band" x="${x-12}" y="20" width="24" height="${Math.max(0,height-20)}" fill="#d94b88" fill-opacity=".14" style="mix-blend-mode:multiply"/><path d="M${x-3} 21h6M${x-3} ${height-1}h6" stroke="#c92a2b" stroke-width="2"/><rect x="${x-10}" y="0" width="20" height="18" fill="white" stroke="#1760c2" stroke-width="1.5"/><text x="${x}" y="13" fill="#164d9a" text-anchor="middle" font-size="13" font-weight="bold">${label}</text></g>`;
  }
  // The report workspace is the save destination for HRV inclusion drafts.
  const shouldConfirmNavigation=(current,next,dirty)=>Boolean(dirty&&current!==next&&next!=='report');
  // Display geometry only. Never search a positive peak or mutate reviewed sample indices.
  function waveRow(values,{top=0,bottom,floor=50,preferredScale=Infinity,annotated=true,domain=null,sharedLabelY=null}={}){
    // A separate annotation lane stays above every displayed sample, including
    // negative/QS and biphasic QRS. Fit all samples, never a percentile or clamp.
    const shared=Number.isFinite(sharedLabelY),labelY=shared?sharedLabelY:top+3,signalTop=top+(shared?6:annotated?24:6),signalBottom=Math.max(signalTop+1,bottom-6);
    let positive=floor,negative=floor;
    for(const item of values||[]){const value=Number(item);if(Number.isFinite(value)){positive=Math.max(positive,value);negative=Math.max(negative,-value);}}
    if(Number.isFinite(domain)&&domain>0){const scale=(bottom-top-(shared?12:30))/(2*domain),baseline=top+(bottom-top+(shared?0:18))/2;return {top,bottom,labelY,signalTop:shared?signalTop:top+24,signalBottom:bottom-6,baseline,scale,overflow:positive>domain||negative>domain};}
    const scale=Math.min((signalBottom-signalTop)/(positive+negative),preferredScale);
    const baseline=(signalTop+signalBottom+(positive-negative)*scale)/2;
    return {top,bottom,labelY,signalTop,signalBottom,baseline,scale};
  }
  // Explicitly scoped display lock. Panning never learns a new gain or baseline.
  const amplitudeLocks=new Map();
  function waveDomain(wave,key,reset=false){
    if(reset)amplitudeLocks.delete(key);
    if(!amplitudeLocks.has(key)){let max=1000;for(const values of Object.values(wave.leads||{}))for(const value of values)if(Number.isFinite(Number(value)))max=Math.max(max,Math.abs(Number(value)));amplitudeLocks.set(key,Math.ceil(max*1.25/100)*100);}
    return amplitudeLocks.get(key);
  }
  // Preserve pixels per source unit when a later window exceeds the initial
  // display lock. Add vertical space instead of hiding a lead or changing gain.
  function lockedWaveRows(values,{top=0,rowHeight=64,domain,scale=null,labelY=4}={}){
    if(!Number.isFinite(domain)||domain<=0)throw Error('显示幅度依据无效');
    const fixedScale=Number.isFinite(scale)&&scale>0?scale:Math.max(1,rowHeight-12)/(2*domain);
    const peaks=values.map(items=>{let peak=0;for(const item of items||[]){const value=Number(item);if(Number.isFinite(value))peak=Math.max(peak,Math.abs(value));}return peak;});
    const peak=Math.max(0,...peaks),height=Math.max(rowHeight,12+2*peak*fixedScale);
    return {scale:fixedScale,rowHeight:height,expanded:peak>domain,displayDomain:(height-12)/(2*fixedScale),
      layouts:peaks.map((value,index)=>{const start=top+index*height,bottom=start+height;return {top:start,bottom,labelY,signalTop:start+6,signalBottom:bottom-6,baseline:start+height/2,scale:fixedScale,overflow:value>domain};})};
  }
  function elapsed(seconds){if(!Number.isFinite(seconds))return '—';const n=Math.round(Math.max(0,seconds)*1000),sec=Math.floor(n/1000);return `D${Math.floor(sec/86400)+1} ${[Math.floor(sec%86400/3600),Math.floor(sec%3600/60),sec%60].map(x=>String(x).padStart(2,'0')).join(':')}.${String(n%1000).padStart(3,'0')}`;}
  function recordClock(start,seconds){
    // Metadata is a recorder wall clock, not the browser's timezone. No guessed epoch.
    const m=String(start||'').match(/^(\d{4})[-/](\d{2})[-/](\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?$/);
    if(!m||!Number.isFinite(seconds))return null;
    const base=Date.UTC(+m[1],+m[2]-1,+m[3],+m[4],+m[5],+m[6],Number(('0.'+(m[7]||'0')))*1000),d=new Date(base+Math.round(seconds*1000));
    const original=new Date(base);if(original.getUTCFullYear()!==+m[1]||original.getUTCMonth()!==+m[2]-1||original.getUTCDate()!==+m[3]||original.getUTCHours()!==+m[4]||original.getUTCMinutes()!==+m[5]||original.getUTCSeconds()!==+m[6])return null;
    return d.toISOString().replace('T',' ').replace('Z','');
  }
  function windowAt(start,duration,total){const length=Math.min(Math.max(0,duration),Math.max(0,total));return {start:Math.max(0,Math.min(Number(start)||0,Math.max(0,total-length))),duration:length};}
  const sampleStride=wave=>wave.stride||((wave.sample_rate_hz||200)/(wave.display_sample_rate_hz||wave.sample_rate_hz||200));
  function fiducialPosition(beat,wave,values,{left=0,width,baseline,scale,top,bottom,labelY=top+3}){
    const fs=wave.sample_rate_hz||200,time=Number.isFinite(beat.sample_index)?beat.sample_index/fs:beat.time_s;
    const fraction=(time-wave.start_s)/wave.duration_s;
    if(!Number.isFinite(fraction)||fraction<0||fraction>1||!values?.length)return null;
    const offset=Math.max(0,Math.min(values.length-1,(time-wave.start_s)*fs/sampleStride(wave))),a=Math.floor(offset),b=Math.min(values.length-1,a+1);
    const value=Number(values[a])+(Number(values[b])-Number(values[a]))*(offset-a),signalY=baseline-value*scale;
    if(!Number.isFinite(signalY))return null;
    const x=left+fraction*width;
    return {x,labelX:Math.max(left+9,Math.min(left+width-9,x)),signalY,y:labelY,time};
  }
  function labelCanvas(ctx,position,code,color,selected=false){
    if(!position)return;ctx.save();ctx.font='bold 10px sans-serif';ctx.textAlign='center';ctx.textBaseline='middle';
    const label=String(code||'?'),w=Math.max(15,ctx.measureText(label).width+6),x=position.labelX??position.x,y=position.y;
    ctx.fillStyle='#fff';ctx.fillRect(x-w/2,y,w,14);ctx.strokeStyle=selected?'#1760c2':color;ctx.lineWidth=selected?1.4:.7;ctx.strokeRect(x-w/2,y,w,14);
    ctx.fillStyle=selected?'#164d9a':color;ctx.fillText(label,x,y+7);ctx.restore();
  }
  const bpm=value=>value==null||value===''||typeof value==='boolean'||!Number.isFinite(Number(value))?'—':String(Math.round(Number(value)));
  function scatterBound(points,requested=null){
    if(Number.isFinite(requested)&&requested>0)return requested;
    let max=0;for(const p of points)for(const v of [p.x,p.y])if(Number.isFinite(v))max=Math.max(max,v);
    return Math.max(2000,Math.ceil(max*1.02/500)*500);
  }
  function clockLabel(recordStart,seconds){return recordClock(recordStart,seconds)?.slice(11,23)||elapsed(seconds);}
  function waveMeta(wave,recordStart=null,domain=null){
    const start=recordClock(recordStart,wave.start_s),end=recordClock(recordStart,wave.start_s+wave.duration_s);
    return `${start||elapsed(wave.start_s)} — ${end||elapsed(wave.start_s+wave.duration_s)} · ${Number(wave.duration_s).toFixed(3)} 秒 · ${wave.sample_rate_hz||200} Hz · 步进 ${sampleStride(wave)} · ${wave.filter==='raw'?'原始波形':wave.filter==='display'?'0.5–40 Hz 显示滤波':wave.filter||'来源滤波未提供'} · ${domain?'锁定幅度 ±'+domain+' u':'自适应设备幅度'} · 电压未校准；屏幕时间轴，纸速未标定${start?'':' · 记录时钟未提供'}`;
  }
  function canvasTimeAxis(ctx,wave,{left=0,width=ctx.canvas.clientWidth,y,recordStart=null}={}){
    const count=Math.max(1,Math.min(5,Math.floor(width/150))),ticks=[];ctx.save();ctx.font='12px sans-serif';ctx.fillStyle='#405563';
    for(let i=0;i<=count;i++){const time=wave.start_s+wave.duration_s*i/count,x=left+width*i/count,label=clockLabel(recordStart,time);ctx.textAlign=i===0?'left':i===count?'right':'center';ctx.fillText(label,x,y);ticks.push({time,label});}ctx.restore();
    if(ctx.canvas.dataset)ctx.canvas.dataset.waveTimeTicks=JSON.stringify(ticks);return ticks;
  }
  const api={clockLabel,waveMeta,canvasTimeAxis,waveDomain,lockedWaveRows,elapsed,recordClock,windowAt,waveRow,sampleStride,scatterBound,bpm,fiducialPosition,labelCanvas,virtualGrid,markCanvas,markSvg,shouldConfirmNavigation};globalThis.ECGReviewTools=api;if(typeof module!=='undefined')module.exports=api;
})();
