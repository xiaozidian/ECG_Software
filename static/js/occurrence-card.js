"use strict";
/* Screen thumbnails retain source samples and use CSS-pixel geometry. */
(()=>{
  const geometry={columns:6,minWidth:240,row:182,waveHeight:132,visibleRows:2};
  const tools=globalThis.ECGReviewTools||(typeof require==='function'?require('./clinical-review-tools.js'):null);
  let gridId=0;
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
  function svg(wave,item={}, {width=240,height=geometry.waveHeight,inset=24,timeAxis=false,annotations='shared',centerSample=null,columns=1,domain=null,recordStart=null,rowHeight=null,pixelGain=null,reportPreview=false,displayProfile=null,fitHeight=false}={}){
    width=Math.max(1,Number(width)||240);height=Math.max(1,Number(height)||geometry.waveHeight);
    const order=['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6'];
    const names=[...order.filter(name=>Object.hasOwn(wave.leads||{},name)),...Object.keys(wave.leads||{}).filter(name=>!order.includes(name))];
    // Twelve leads always share one full-width time axis, including legacy callers.
    const fitted=!!displayProfile&&(reportPreview||fitHeight);
    let signalPadding=6;
    if(displayProfile){
      domain=displayProfile.domain;
      const availableRow=(height-(annotations==='none'?0:36)-(timeAxis?24:0))/Math.max(1,names.length);
      const base=fitted?Math.max(32,availableRow):Number.isFinite(rowHeight)?rowHeight:Math.max(32,availableRow);
      const fit=tools.reportWaveGeometry(wave,displayProfile,base,pixelGain);
      rowHeight=fit.rowHeight;pixelGain=fit.pixelGain;
      if(fitted){
        // Fit every lead in the same frame, preserving one gain and every source point.
        signalPadding=Math.min(6,availableRow*.1);
        pixelGain*=Math.min(1,(availableRow-2*signalPadding)/(fit.rowHeight-12));
      }
    }
    const fixedRows=!fitted&&Number.isFinite(rowHeight)&&rowHeight>=32;
    const entries=names.map(name=>[name,wave.leads[name]]),sharedTwelve=names.length>6,sharedLane=fitted||fixedRows||sharedTwelve||reportPreview,annotationHeight=sharedLane&&annotations!=='none'?(displayProfile?36:24):0;
    if(fixedRows)height=annotationHeight+entries.length*rowHeight+(timeAxis?24:0);
    const plotHeight=height-(timeAxis?24:0),row=(plotHeight-annotationHeight)/Math.max(1,entries.length),fs=wave.sample_rate_hz||200,stride=tools.sampleStride(wave),sourceDuration=wave.duration_s;
    // Display-only centered viewport. Keep every source sample and original timing.
    const center=Number.isFinite(centerSample)?centerSample/fs:null;
    const half=center===null?null:Math.max(center-wave.start_s,wave.start_s+sourceDuration-center,1/fs);
    const displayStart=center===null?wave.start_s:center-half,duration=center===null?sourceDuration:2*half;
    const displayWave={...wave,start_s:displayStart,duration_s:duration};
    const left=Math.min(inset,width/4),plotWidth=width-2*left,anchor=left+(item.sample_index/fs-displayStart)/duration*plotWidth;
    const label=`${item.label||'心搏'}，${duration}秒，设备单位 u，${displayProfile?'本窗共同增益，基线居中，电压未校准':domain?'锁定幅度 ±'+domain+' u':'各导联自适应幅度'}${stride>1?'，步进 '+stride+' 采样的概览，请回看完整波形':''}`;
    let output=`<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" ${fixedRows?`data-fixed-row-height="${rowHeight}" height="${height}"`:''} ${displayProfile?`data-report-display="hospital" data-display-gain="${pixelGain}"`:''} ${reportPreview?'data-report-preview="full-width"':''} data-columns="1" data-sample-rate="${fs}" data-stride="${stride}" data-amplitude-domain="${domain||'adaptive'}" data-record-start="${escape(recordStart||'')}" data-annotations="${annotations==='none'?'none':'shared'}" data-display-start="${displayStart}" data-display-duration="${duration}" data-source-start="${wave.start_s}" data-source-duration="${sourceDuration}" data-plot-left="${left}" data-plot-width="${plotWidth}" aria-label="${escape(label+(reportPreview?'，缩略预览，请展开复核':''))}"><rect width="100%" height="100%" fill="${displayProfile?'#fffdf5':'#fff'}"/>`;
    const sourceLeft=left+(wave.start_s-displayStart)/duration*plotWidth,sourceRight=left+(wave.start_s+sourceDuration-displayStart)/duration*plotWidth;
    for(const [x,w] of [[left,sourceLeft-left],[sourceRight,left+plotWidth-sourceRight]])if(w>.01)output+=`<g class="occurrence-unavailable"><rect x="${x}" y="0" width="${w}" height="${plotHeight}" fill="#f2f4f5"/><title>此显示范围没有载入波形；未补零或推断心搏</title></g>`;
    const step=plotWidth/duration*.2;
    if(displayProfile){const id='reportPaper'+(++gridId);output+=`<defs><pattern id="${id}" width="${step}" height="20" patternUnits="userSpaceOnUse"><path d="${Array.from({length:4},(_,i)=>`M${step*(i+1)/5} 0V20M0 ${(i+1)*4}H${step}`).join('')}" stroke="#f4d6ad" stroke-width=".45"/><path d="M${step} 0H0V20" fill="none" stroke="#e9a256" stroke-width=".65"/></pattern></defs><rect x="${left}" y="${annotationHeight}" width="${plotWidth}" height="${plotHeight-annotationHeight}" fill="url(#${id})"/>`;
      if(!reportPreview&&anchor>=left&&anchor<=left+plotWidth)output+=`<rect x="${anchor-10}" y="${annotationHeight}" width="20" height="${plotHeight-annotationHeight}" fill="#ed5486" fill-opacity=".14" style="mix-blend-mode:multiply"/>`;
    }else{
      for(let x=left;x<=left+plotWidth;x+=step)output+=`<path d="M${x.toFixed(3)} 0V${plotHeight}" stroke="#f0d8d5" stroke-width=".5" vector-effect="non-scaling-stroke"/>`;
      for(let y=0;y<=plotHeight;y+=10)output+=`<path d="M${left} ${y}H${left+plotWidth}" stroke="#f0d8d5" stroke-width=".5" vector-effect="non-scaling-stroke"/>`;
    }
    if(anchor>=left&&anchor<=left+plotWidth)output+=`<line class="occurrence-anchor" x1="${anchor}" x2="${anchor}" y1="0" y2="${plotHeight}" stroke="#d18427" stroke-width="1" vector-effect="non-scaling-stroke"/>`;
    entries.forEach(([name,values],j)=>{
      const shape=tools.waveRow(values,{top:annotationHeight+j*row,bottom:annotationHeight+(j+1)*row,annotated:annotations!=='none'&&j===0,sharedLabelY:sharedLane?3:null,domain});
      if(reportPreview){shape.baseline=annotationHeight+(j+.5)*row;shape.signalTop=annotationHeight+j*row+2;shape.signalBottom=annotationHeight+(j+1)*row-2;shape.labelY=3;}
      if(Number.isFinite(pixelGain)&&pixelGain>0){shape.scale=pixelGain;shape.overflow=values.some(value=>{const y=shape.baseline-Number(value)*pixelGain;return y<shape.signalTop-1e-6||y>shape.signalBottom+1e-6;});}
      if(displayProfile){shape.baseline=annotationHeight+(j+.5)*row+(displayProfile.offsets[name]||0)*pixelGain;shape.signalTop=annotationHeight+j*row+signalPadding;shape.signalBottom=annotationHeight+(j+1)*row-signalPadding;shape.scale=pixelGain;shape.labelY=3;shape.overflow=false;}
      const {baseline,scale}=shape,labelFont=reportPreview?Math.min(9,row*.8):displayProfile?Math.min(11,row*.8):11;
      const points=values.map((value,i)=>`${(left+(wave.start_s-displayStart+i*stride/fs)/duration*plotWidth).toFixed(3)},${(baseline-value*scale).toFixed(3)}`).join(' ');
      output+=`<g data-wave-lead="${escape(name)}" data-wave-offset="${displayProfile?.offsets[name]||0}" data-wave-scale="${scale}" data-wave-baseline="${baseline}" data-wave-overflow="${Boolean(shape.overflow)}" data-signal-top="${shape.signalTop}" data-signal-bottom="${shape.signalBottom}"><polyline opacity="${shape.overflow?0:1}" data-lead="${escape(name)}" fill="none" stroke="#172126" stroke-width="1.15" vector-effect="non-scaling-stroke" points="${points}"/><text class="ecg-lead-name" x="2" y="${displayProfile?annotationHeight+(j+.5)*row+labelFont/3:reportPreview?shape.baseline+labelFont/3:annotationHeight+j*row+13}" font-size="${labelFont}" fill="#36454d">${escape(name)}</text>`;
      if(displayProfile&&!reportPreview){const rulerHeight=Math.min(20,row*.35),unitBase=10**Math.floor(Math.log10(rulerHeight/scale)),units=[1,2,5].map(v=>v*unitBase).filter(v=>v*scale<=rulerHeight).at(-1)||unitBase,rulerY=annotationHeight+(j+.5)*row;output+=`<path data-ruler-units="${units}" d="M12 ${rulerY}h4v${-units*scale}h5v${units*scale}h4" fill="none" stroke="#304fc4" stroke-width=".8"/>${row>=40?`<text x="4" y="${rulerY+14}" font-size="8" fill="#36454d">${Number(units.toPrecision(3))} u</text>`:''}`;}
      if(displayProfile&&!reportPreview)for(const beat of wave.beats||[]){if(!['S','V'].includes(beat.class_code))continue;const at=(beat.sample_index/fs-wave.start_s)*fs/stride,a=Math.max(0,Math.floor(at-.2*fs/stride)),b=Math.min(values.length,Math.ceil(at+.32*fs/stride));if(b<=a)continue;const colored=values.slice(a,b).map((value,k)=>`${(left+(wave.start_s-displayStart+(a+k)*stride/fs)/duration*plotWidth).toFixed(3)},${(baseline-value*scale).toFixed(3)}`).join(' ');output+=`<polyline data-class-sample="${beat.sample_index}" data-class-code="${beat.class_code}" points="${colored}" fill="none" stroke="${beat.class_code==='S'?'#269437':'#d63232'}" stroke-width="1.15" vector-effect="non-scaling-stroke"/>`;}
      if(shape.overflow)output+=`<text x="${left+24}" y="${baseline}" font-size="12" fill="#a52727">幅度超范围，请适应当前幅度后复核</text>`;
      for(const beat of (annotations!=='none'&&j===0?wave.beats||[item]:[])){
        const p=tools.fiducialPosition(beat,displayWave,values,{left,width:plotWidth,...shape});if(!p)continue;
        output+=`<g data-fiducial-sample="${beat.sample_index}" data-fiducial-x="${p.x}"><rect x="${p.labelX-7}" y="${p.y}" width="14" height="14" fill="#fff" stroke="${beat.class_code==='V'?'#b13e36':beat.class_code==='S'?'#147955':'#607c87'}" stroke-width=".6"/><text x="${p.labelX}" y="${p.y+10}" text-anchor="middle" font-size="11" fill="${beat.class_code==='V'?'#b13e36':beat.class_code==='S'?'#147955':'#25434e'}">${escape(beat.class_code||'?')}</text></g>`;
      }
      output+='</g>';
    });
    if(displayProfile&&!reportPreview&&annotations!=='none')for(const beat of wave.beats||[]){const end=Number.isFinite(beat.sample_index)?beat.sample_index/fs:beat.time_s,rr=beat.rr_ms,start=end-rr/1000;if(!Number.isFinite(rr)||rr<=0||start<displayStart-1e-8||end>displayStart+duration+1e-8)continue;const x=left+((start+end)/2-displayStart)/duration*plotWidth;output+=`<g data-interval-start="${start}" data-interval-end="${end}" data-interval-sample="${beat.sample_index}"><text x="${x}" y="11" text-anchor="middle" font-size="8" fill="#162b34">${tools.bpm(beat.hr)}</text><text x="${x}" y="23" text-anchor="middle" font-size="8" fill="#162b34">${rr}</text></g>`;}
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
    node.innerHTML=`<header><strong>小图 · RR ${rr}</strong><button type="button" data-mini="close" aria-label="关闭小图菜单">×</button></header><button type="button" role="menuitem" data-mini="preview">预览 12 导联</button><button type="button" role="menuitem" data-mini="three">3 导联 · II / V1 / V5</button><button type="button" role="menuitem" data-mini="one">1 导联 · II</button><button type="button" role="menuitem" data-mini="candidate" ${eligible?'':'disabled title="未提供有效前 RR，或为质控心搏；不能建立 RR 候选"'}>加入最长 RR 间期候选…</button><button type="button" role="menuitem" data-mini="pool">查看 / 撤销 RR 候选</button>${onEdit?'<button type="button" role="menuitem" data-mini="edit">心搏修订…</button>':''}<p>保存后仅加入候选；勾选入报后才进入报告。计时采用原心搏位置；相邻 RR 的质量仍须服务器核验。</p>`;
    document.body.append(node);menuOwner={node,card};node.style.left=Math.max(8,Math.min(innerWidth-290,event?.clientX??rect.left))+'px';node.style.top=Math.max(8,Math.min(innerHeight-330,event?.clientY??rect.top))+'px';try{node.showPopover()}catch(_){}
    node.onclick=e=>{const b=e.target.closest('[data-mini]');if(!b||b.disabled)return;const action=b.dataset.mini;closeMenu();if(action==='close'||!isCurrent())return;Promise.resolve().then(()=>action==='preview'?onPreview():action==='three'?onLeads(['II','V1','V5']):action==='one'?onLeads(['II']):action==='candidate'?onCandidate():action==='pool'?onPool():onEdit?.()).catch(globalThis.handleError||console.error);};
    node.onkeydown=e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();closeMenu();}else if(['ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();const all=[...node.querySelectorAll('[role=menuitem]:not(:disabled)')],i=all.indexOf(document.activeElement);all[(i+(e.key==='ArrowUp'?-1:1)+all.length)%all.length]?.focus();}};
    node.querySelector('[role=menuitem]').focus({preventScroll:true});
  }
  if(typeof document!=='undefined')document.addEventListener('pointerdown',e=>{if(menuOwner&&!menuOwner.node.contains(e.target))closeMenu();},true);
  const api={geometry,leads,windowFor,syncSelection,svg,menu,closeMenu,rrCandidateAvailable};globalThis.ECGOccurrenceCard=api;if(typeof module!=='undefined')module.exports=api;
})();
