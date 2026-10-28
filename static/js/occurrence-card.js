"use strict";
/* Screen thumbnails retain source samples and use CSS-pixel geometry. */
(()=>{
  const geometry={columns:6,minWidth:240,row:182,waveHeight:132,visibleRows:2};
  const tools=globalThis.ECGReviewTools||(typeof require==='function'?require('./clinical-review-tools.js'):null);
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function leads(primary='II',count=3){return [primary,...['II','V1','V5'].filter(name=>name!==primary)].slice(0,count===1?1:count===2?2:3);}
  function windowFor(item){
    const anchor=item.sample_index/200,targets=[item.start_sample,item.end_sample,...(item.target_samples||[])].filter(Number.isFinite).map(s=>s/200);
    const half=Math.max(1.2,...targets.map(t=>Math.abs(t-anchor)+.8));
    // RR only widens the viewport. Source waveform labels keep their original samples.
    const rrStart=Number.isFinite(item.rr_ms)&&item.rr_ms>1500?anchor-item.rr_ms/1000-.5:anchor-half;
    const centeredHalf=Math.max(half,anchor-rrStart);
    // Do not widen a request past the existing waveform endpoint's 120s bound.
    return centeredHalf*2<=120?{start:Math.max(0,anchor-centeredHalf),end:anchor+centeredHalf}:{start:Math.max(0,Math.min(anchor-half,rrStart)),end:anchor+half};
  }
  function syncSelection(card,item,state){
    const samples=item.target_samples||[item.sample_index],count=samples.filter(s=>state.editSelectedSamples.has(s)).length;
    const all=count===samples.length,partial=count>0&&!all,input=card.querySelector('input[type=checkbox]'),button=card.querySelector('button');
    if(input){input.checked=all;input.indeterminate=partial;}
    card.dataset.selected=partial?'mixed':String(all);
    card.dataset.current=String(samples.includes(state.editSelectedSample));
    if(button){button.setAttribute('aria-pressed',partial?'mixed':String(all));if(samples.includes(state.editSelectedSample))button.setAttribute('aria-current','true');else button.removeAttribute('aria-current');}
  }
  function svg(wave,item={}, {width=240,height=geometry.waveHeight,inset=24,timeAxis=false,annotations='shared',centerSample=null,columns=1,domain=null,recordStart=null,rowHeight=null}={}){
    width=Math.max(1,Number(width)||240);height=Math.max(1,Number(height)||geometry.waveHeight);
    const order=['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6'];
    const names=[...order.filter(name=>Object.hasOwn(wave.leads||{},name)),...Object.keys(wave.leads||{}).filter(name=>!order.includes(name))];
    // Twelve leads always share one full-width time axis, including legacy callers.
    const fixedRows=Number.isFinite(rowHeight)&&rowHeight>=32;
    const entries=names.map(name=>[name,wave.leads[name]]),sharedTwelve=names.length>6,sharedLane=fixedRows||sharedTwelve,annotationHeight=sharedLane&&annotations!=='none'?24:0;
    if(fixedRows)height=annotationHeight+entries.length*rowHeight+(timeAxis?24:0);
    const plotHeight=height-(timeAxis?24:0),row=(plotHeight-annotationHeight)/Math.max(1,entries.length),fs=wave.sample_rate_hz||200,stride=tools.sampleStride(wave),sourceDuration=wave.duration_s;
    // Display-only centered viewport. Keep every source sample and original timing.
    const center=Number.isFinite(centerSample)?centerSample/fs:null;
    const half=center===null?null:Math.max(center-wave.start_s,wave.start_s+sourceDuration-center,1/fs);
    const displayStart=center===null?wave.start_s:center-half,duration=center===null?sourceDuration:2*half;
    const displayWave={...wave,start_s:displayStart,duration_s:duration};
    const left=Math.min(inset,width/4),plotWidth=width-2*left,anchor=left+(item.sample_index/fs-displayStart)/duration*plotWidth;
    const label=`${item.label||'心搏'}，${duration}秒，设备单位 u，${domain?'锁定幅度 ±'+domain+' u':'各导联自适应幅度'}${stride>1?'，步进 '+stride+' 采样的概览，请回看完整波形':''}`;
    let output=`<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" ${fixedRows?`data-fixed-row-height="${rowHeight}" height="${height}"`:''} data-columns="1" data-sample-rate="${fs}" data-stride="${stride}" data-amplitude-domain="${domain||'adaptive'}" data-record-start="${escape(recordStart||'')}" data-annotations="${annotations==='none'?'none':'shared'}" data-display-start="${displayStart}" data-display-duration="${duration}" data-source-start="${wave.start_s}" data-source-duration="${sourceDuration}" data-plot-left="${left}" data-plot-width="${plotWidth}" aria-label="${escape(label)}"><rect width="100%" height="100%" fill="#fff"/>`;
    const sourceLeft=left+(wave.start_s-displayStart)/duration*plotWidth,sourceRight=left+(wave.start_s+sourceDuration-displayStart)/duration*plotWidth;
    for(const [x,w] of [[left,sourceLeft-left],[sourceRight,left+plotWidth-sourceRight]])if(w>.01)output+=`<g class="occurrence-unavailable"><rect x="${x}" y="0" width="${w}" height="${plotHeight}" fill="#f2f4f5"/><title>此显示范围没有载入波形；未补零或推断心搏</title></g>`;
    const step=plotWidth/duration*.2;
    for(let x=left;x<=left+plotWidth;x+=step)output+=`<path d="M${x.toFixed(3)} 0V${plotHeight}" stroke="#f0d8d5" stroke-width=".5" vector-effect="non-scaling-stroke"/>`;
    for(let y=0;y<=plotHeight;y+=10)output+=`<path d="M${left} ${y}H${left+plotWidth}" stroke="#f0d8d5" stroke-width=".5" vector-effect="non-scaling-stroke"/>`;
    if(anchor>=left&&anchor<=left+plotWidth)output+=`<line class="occurrence-anchor" x1="${anchor}" x2="${anchor}" y1="0" y2="${plotHeight}" stroke="#d18427" stroke-width="1" vector-effect="non-scaling-stroke"/>`;
    entries.forEach(([name,values],j)=>{
      const shape=tools.waveRow(values,{top:annotationHeight+j*row,bottom:annotationHeight+(j+1)*row,annotated:annotations!=='none'&&j===0,sharedLabelY:sharedLane?3:null,domain}),{baseline,scale}=shape;
      const points=values.map((value,i)=>`${(left+(wave.start_s-displayStart+i*stride/fs)/duration*plotWidth).toFixed(3)},${(baseline-value*scale).toFixed(3)}`).join(' ');
      output+=`<g data-wave-lead="${escape(name)}" data-wave-scale="${scale}" data-wave-baseline="${baseline}" data-wave-overflow="${Boolean(shape.overflow)}" data-signal-top="${shape.signalTop}" data-signal-bottom="${shape.signalBottom}"><polyline opacity="${shape.overflow?0:1}" data-lead="${escape(name)}" fill="none" stroke="#172126" stroke-width="1.15" vector-effect="non-scaling-stroke" points="${points}"/><text class="ecg-lead-name" x="2" y="${annotationHeight+j*row+13}" font-size="11" fill="#36454d">${escape(name)}</text>`;
      if(shape.overflow)output+=`<text x="${left+24}" y="${baseline}" font-size="12" fill="#a52727">幅度超范围，请适应当前幅度后复核</text>`;
      for(const beat of (annotations!=='none'&&j===0?wave.beats||[item]:[])){
        const p=tools.fiducialPosition(beat,displayWave,values,{left,width:plotWidth,...shape});if(!p)continue;
        output+=`<g data-fiducial-sample="${beat.sample_index}" data-fiducial-x="${p.x}"><rect x="${p.labelX-7}" y="${p.y}" width="14" height="14" fill="#fff" stroke="${beat.class_code==='V'?'#b13e36':beat.class_code==='S'?'#147955':'#607c87'}" stroke-width=".6"/><text x="${p.labelX}" y="${p.y+10}" text-anchor="middle" font-size="11" fill="${beat.class_code==='V'?'#b13e36':beat.class_code==='S'?'#147955':'#25434e'}">${escape(beat.class_code||'?')}</text></g>`;
      }
      output+='</g>';
    });
    const tickCount=Math.max(1,Math.min(5,Math.floor(plotWidth/150)));
    if(timeAxis)for(let i=0;i<=tickCount;i++)output+=`<text data-wave-time="${displayStart+i*duration/tickCount}" x="${left+i*plotWidth/tickCount}" y="${height-6}" font-size="12" text-anchor="${i===0?'start':i===tickCount?'end':'middle'}" fill="#536b75">${escape(tools.clockLabel(recordStart,displayStart+i*duration/tickCount))}</text>`;
    return output+'</svg>';
  }
  let menuOwner=null;
  function rrCandidateAvailable(item){return Number.isFinite(item.rr_ms)&&item.rr_ms>0&&Number.isInteger(item.sample_index)&&item.sample_index>0&&!['X','O','Y','T'].includes(item.class_code);}
  function closeMenu(){if(!menuOwner)return;const {node,card}=menuOwner;menuOwner=null;try{node.hidePopover()}catch(_){}node.remove();if(card?.isConnected)card.focus({preventScroll:true});}
  function menu({card,event,item,isCurrent,onPreview,onLeads,onCandidate,onEdit,onPool}){
    closeMenu();if(!isCurrent())return;event?.preventDefault();event?.stopPropagation();
    const node=document.createElement('div'),rect=card.getBoundingClientRect();node.className='ecg-mini-menu';node.setAttribute('role','menu');node.setAttribute('aria-label','三导联小图操作');node.setAttribute('popover','manual');
    const rr=Number.isFinite(item.rr_ms)&&item.rr_ms>0?escape(item.rr_ms)+' ms':'未提供',eligible=rrCandidateAvailable(item);
    node.innerHTML=`<header><strong>小图 · RR ${rr}</strong><button type="button" data-mini="close" aria-label="关闭小图菜单">×</button></header><button type="button" role="menuitem" data-mini="preview">预览 12 导联</button><button type="button" role="menuitem" data-mini="three">3 导联 · II / V1 / V5</button><button type="button" role="menuitem" data-mini="one">1 导联 · II</button><button type="button" role="menuitem" data-mini="candidate" ${eligible?'':'disabled title="未提供有效前 RR，或为质控心搏；不能建立 RR 候选"'}>加入最长 RR 间期候选…</button><button type="button" role="menuitem" data-mini="pool">查看 / 撤销 RR 候选</button>${onEdit?'<button type="button" role="menuitem" data-mini="edit">心搏修订…</button>':''}<p>仅选候选，不自动入报。计时采用原心搏位置；相邻 RR 的质量仍须服务器核验。</p>`;
    document.body.append(node);menuOwner={node,card};node.style.left=Math.max(8,Math.min(innerWidth-290,event?.clientX??rect.left))+'px';node.style.top=Math.max(8,Math.min(innerHeight-330,event?.clientY??rect.top))+'px';try{node.showPopover()}catch(_){}
    node.onclick=e=>{const b=e.target.closest('[data-mini]');if(!b||b.disabled)return;const action=b.dataset.mini;closeMenu();if(action==='close'||!isCurrent())return;Promise.resolve().then(()=>action==='preview'?onPreview():action==='three'?onLeads(['II','V1','V5']):action==='one'?onLeads(['II']):action==='candidate'?onCandidate():action==='pool'?onPool():onEdit?.()).catch(globalThis.handleError||console.error);};
    node.onkeydown=e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();closeMenu();}else if(['ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();const all=[...node.querySelectorAll('[role=menuitem]:not(:disabled)')],i=all.indexOf(document.activeElement);all[(i+(e.key==='ArrowUp'?-1:1)+all.length)%all.length]?.focus();}};
    node.querySelector('[role=menuitem]').focus({preventScroll:true});
  }
  if(typeof document!=='undefined')document.addEventListener('pointerdown',e=>{if(menuOwner&&!menuOwner.node.contains(e.target))closeMenu();},true);
  const api={geometry,leads,windowFor,syncSelection,svg,menu,closeMenu,rrCandidateAvailable};globalThis.ECGOccurrenceCard=api;if(typeof module!=='undefined')module.exports=api;
})();
