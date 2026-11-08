"use strict";
/* Full raw min/max envelope + exact local selection. Never a diagnosis editor. */
const ECGFullRecordRetain=(()=>{
  const esc=x=>escapeHtml(String(x??''));
  const requestedLeads=['II','V1','V5'];
  const reportLeads=['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6'];
  let active=null;
  function windowAt(center,total,length=30){
    if(!Number.isFinite(center)||!Number.isFinite(total)||total<0||!Number.isFinite(length)||length<=0)throw Error('全记录时间范围无效');
    const n=Math.min(length,total),a=Math.min(total-n,Math.round(Math.max(0,Math.min(total-n,center-n/2))*200)/200);return [a,Math.min(total,a+n)];
  }
  // Canvas drawing and picking both use the content box, excluding CSS borders/padding.
  function envelopeGeometry(canvas){
    const box=canvas.getBoundingClientRect(),style=getComputedStyle(canvas),px=name=>parseFloat(style[name])||0;
    const left=box.left+px('borderLeftWidth')+px('paddingLeft');
    const width=Math.max(1,box.width-px('borderLeftWidth')-px('borderRightWidth')-px('paddingLeft')-px('paddingRight'));
    const height=Math.max(1,box.height-px('borderTopWidth')-px('borderBottomWidth')-px('paddingTop')-px('paddingBottom'));
    return {left,width,height,plotLeft:35,plotWidth:Math.max(1,width-40)};
  }
  function envelopeSurface(canvas,dpr=globalThis.devicePixelRatio||1){
    dpr=Number.isFinite(dpr)&&dpr>0?Math.min(dpr,2):1;
    const geometry=envelopeGeometry(canvas),w=geometry.width,h=geometry.height,ctx=canvas.getContext('2d');
    canvas.width=Math.max(1,Math.round(w*dpr));canvas.height=Math.max(1,Math.round(h*dpr));
    ctx.setTransform(canvas.width/w,0,0,canvas.height/h,0,0);
    return {ctx,width:w,height:h,plotLeft:geometry.plotLeft,plotWidth:geometry.plotWidth};
  }
  function envelopeTime(clientX,geometry,total){return Math.max(0,Math.min(total,Math.round(Math.max(0,Math.min(total,(clientX-geometry.left-geometry.plotLeft)/geometry.plotWidth*total))*200)/200));}
  // Cache source extrema once. Pointer moves and resize never rescan/flatten a long envelope.
  function envelopeModel(overview){
    const total=overview?.total_duration_s,edges=overview?.bin_edges_s;
    if(!Number.isFinite(total)||total<=0||!Array.isArray(edges)||edges.length<2||edges[0]!==0||Math.abs(edges.at(-1)-total)>1e-7||edges.some((x,i)=>!Number.isFinite(x)||(i&&x<=edges[i-1])))throw Error('全记录幅度包络时间范围无效');
    const entries=requestedLeads.map(lead=>{
      const bins=overview.leads?.[lead];
      if(!Array.isArray(bins)||bins.length!==edges.length-1)throw Error(`全记录缺少 ${lead} 幅度包络`);
      let peak=0;
      for(const pair of bins){if(!Array.isArray(pair)||pair.length!==2||!pair.every(Number.isFinite)||pair[0]>pair[1])throw Error(`${lead} 全记录幅度包络不完整`);peak=Math.max(peak,Math.abs(pair[0]),Math.abs(pair[1]));}
      return {lead,bins,peak,amplitude:Math.max(50,peak)};
    });
    return {total,edges,entries};
  }
  function drawEnvelope(canvas,model,center){
    const {ctx,width:w,height:h,plotLeft,plotWidth}=envelopeSurface(canvas),total=model.total;
    ctx.fillStyle='#fffaf8';ctx.fillRect(0,0,w,h);
    for(const [j,{lead,bins,amplitude}]of model.entries.entries()){
      const mid=j*40+24,scale=16/amplitude;ctx.strokeStyle='#29434c';ctx.lineWidth=1;ctx.beginPath();
      bins.forEach(([lo,hi],i)=>{const x=plotLeft+model.edges[i]/total*plotWidth;ctx.moveTo(x,mid-hi*scale);ctx.lineTo(x,mid-lo*scale);});
      ctx.stroke();ctx.fillStyle='#0a736f';ctx.font='11px sans-serif';ctx.fillText(lead,3,mid);
    }
    const [a,b]=windowAt(center,total);ctx.fillStyle='#0c928628';ctx.strokeStyle='#087e78';ctx.fillRect(plotLeft+a/total*plotWidth,0,Math.max(2,(b-a)/total*plotWidth),125);ctx.strokeRect(plotLeft+a/total*plotWidth,0,Math.max(2,(b-a)/total*plotWidth),125);ctx.fillStyle='#3c5b64';ctx.fillText(formatElapsed(0),plotLeft,141);ctx.textAlign='right';ctx.fillText(formatElapsed(total),w-5,141);ctx.textAlign='left';
    if(canvas.dataset)Object.assign(canvas.dataset,{sourceDuration:String(total),renderWidth:String(w),renderHeight:String(h)});
    return [a,b];
  }
  function observeEnvelope(canvas,draw,current){
    let frame=0,closed=false;
    const schedule=()=>{if(closed||frame)return;frame=requestAnimationFrame(()=>{frame=0;if(!closed&&current())draw();});};
    const observer=typeof ResizeObserver==='undefined'?null:new ResizeObserver(schedule);
    observer?.observe(canvas);window.addEventListener('resize',schedule);
    return ()=>{closed=true;observer?.disconnect();window.removeEventListener('resize',schedule);if(frame)cancelAnimationFrame(frame);frame=0;};
  }
  async function open(){
    if(active?.node.isConnected)return;
    ECGReportRange.assertApplied();const id=state.caseId,token=state.caseRequestId;if(!id)return;
    let invalidated=false;
    const ownPage=state.currentPage,current=()=>!invalidated&&id===state.caseId&&token===state.caseRequestId&&ownPage===state.currentPage;
    const node=document.createElement('dialog');node.className='review-candidate-dialog full-record-retain';node.setAttribute('aria-label','全记录留图');
    node.innerHTML='<header><h2>全记录留图</h2><button type="button" data-full-close>关闭</button></header><p>全览保留每箱原始幅度极值。点击或拖动定位框查看局部；在下方网格波形拖动橘色边界，保留候选后再到报告勾选。</p><canvas data-full-envelope height="145" tabindex="0" aria-label="全记录三导联幅度包络，点击或左右键移动局部窗口"></canvas><output data-full-time></output><div class="full-record-position"><label>定位中心（记录起点后秒数）<input type="number" min="0" step="0.005" data-full-center></label><button type="button" data-full-locate>载入此时段</button></div><details class="full-record-method"><summary>全览方法与校准状态</summary><p data-full-method></p></details><div data-full-detail>正在读取全记录幅度包络…</div><p role="status" data-full-status></p>';
    document.body.append(node);node.showModal();const key='full-record-retain:'+id+':'+token;
    let overview=null,model=null,domain=null,identity=null,center=Math.min((state.start||0)+3.5,Number(state.caseData.technical.duration_seconds_raw)),range=null,detailToken=0,busy=false,drag=null,saved=false,inputDirty=false,detailAbort=null;
    const overviewAbort=typeof AbortController==='undefined'?null:new AbortController();
    const status=node.querySelector('[data-full-status]'),canvas=node.querySelector('canvas'),input=node.querySelector('[data-full-center]');
    const locate=node.querySelector('[data-full-locate]');
    function syncControls(){input.disabled=busy;locate.disabled=busy||!model;canvas.setAttribute('aria-disabled',String(busy||!model));}
    function closeIfStale(){if(current()&&node.isConnected)return false;if(node.isConnected&&!busy)node.close();return true;}
    const owner={node,invalidate(){invalidated=true;if(!busy&&node.isConnected)node.close();}};active=owner;
    const stopObserving=observeEnvelope(canvas,()=>draw(false),()=>!closeIfStale()&&node.open);
    input.oninput=()=>{inputDirty=true;};syncControls();
    node.querySelector('[data-full-close]').onclick=()=>{if(!busy)node.close();};node.oncancel=e=>{if(busy)e.preventDefault();};node.onclose=()=>{stopObserving();overviewAbort?.abort();detailAbort?.abort();detailToken++;drag=null;ECGReportRange.forget(key);node.remove();if(active===owner)active=null;if(saved&&id===state.caseId&&token===state.caseRequestId)document.dispatchEvent(new CustomEvent('ecg-evidence-candidates-changed',{detail:{case_id:id}}));};
    function draw(syncInput=true){if(!model||closeIfStale())return;const total=model.total,[a,b]=drawEnvelope(canvas,model,center);
      node.querySelector('[data-full-time]').textContent=`全记录 ${formatElapsed(0)} — ${formatElapsed(total)} · 局部 ${formatElapsed(a)} — ${formatElapsed(b)}`;if(syncInput&&!inputDirty)input.value=center.toFixed(3);
    }
    async function detail(){if(!model||closeIfStale())return;detailAbort?.abort();detailAbort=typeof AbortController==='undefined'?null:new AbortController();const run=++detailToken,host=node.querySelector('[data-full-detail]'),total=model.total,[lo,hi]=windowAt(center,total);ECGReportRange.forget(key);host.textContent='正在读取该时段的原始三导联与全部标注…';status.textContent='尚未保留新候选；切换定位会重置未保留选段。';
      try{const params=new URLSearchParams({start:lo,duration:hi-lo,leads:'II,V1,V5',filter:'raw',max_points:12000,analysis_basis:identity.analysis_basis,analysis_revision:identity.analysis_revision});const wave=await api(`/api/cases/${id}/waveform?${params}`,detailAbort?{signal:detailAbort.signal}:{});if(run!==detailToken||closeIfStale())return;ECGAnalysisConsistency.assertSame(identity,wave);const a=Math.max(lo,Math.min(hi-7,center-3.5)),b=Math.min(hi,a+7),entry={event_id:key,sample_index:Math.min(Math.max(0,Math.ceil(total*200)-1),Math.round(center*200)),label:'全记录人工选段',inReport:false,strip:{start_s:a,end_s:b}};range=[a,b];
        ECGReportRange.mount(host,entry,wave,async chosen=>{if(closeIfStale())throw Error('病例或页面已变化，未保存');busy=true;syncControls();node.querySelector('[data-full-close]').disabled=true;try{const result=await api(`/api/cases/${id}/evidence-candidates`,{method:'POST',body:JSON.stringify({...identity,kind:'strip',caption:'全记录人工留图',settings:{duration_s:chosen.range_end_s-chosen.range_start_s,...chosen,leads:[...reportLeads]}})});saved=true;if(!current()||!node.isConnected)return;entry.strip.start_s=chosen.range_start_s;entry.strip.end_s=chosen.range_end_s;range=[chosen.range_start_s,chosen.range_end_s];const reportKnown=state.report?.case_id===id&&Array.isArray(state.report?.composition?.selected_events),included=reportKnown&&state.report.composition.selected_events.some(p=>p.event_id===`local-pick:${result.item.id}`);status.textContent=`留图候选 #${result.item.id} 已保留${!reportKnown?'，是否入报请到报告编排核对':included?'，报告草稿已选中此候选':'，尚未入报'}。到报告“其他事件”核对选择；重复保留同一区间会去重，已有图条设置保留。`;}finally{busy=false;if(node.isConnected){node.querySelector('[data-full-close]').disabled=false;syncControls();closeIfStale();}}},async()=>{await detail();},{context:JSON.stringify([id,token]),basis:JSON.stringify(identity),event:{event_id:key},candidateOnly:true,domain,recordStart:state.caseData?.metadata?.start_time});
        host.querySelector('header strong').textContent='人工留图选段';const time=document.createElement('p');time.className='full-record-detail-clock';time.textContent=`${ECGReviewTools.recordClock(state.caseData?.metadata?.start_time,lo)||ECGReviewTools.elapsed(lo)} — ${ECGReviewTools.recordClock(state.caseData?.metadata?.start_time,hi)||ECGReviewTools.elapsed(hi)} · 锁定全记录幅度`;host.querySelector('header').after(time);host.querySelector('header span').textContent='拖动波形或橘色边界；保留后进入候选池，报告另行勾选';host.querySelector('[data-range-apply]').textContent='保留选段候选';host.querySelector('[data-range-reset]').textContent='重置本窗口选段';
      }catch(error){if(run===detailToken&&!closeIfStale()){host.textContent='局部波形未取得，未保留图条。';status.textContent=error.message;}}
    }
    function position(e){center=envelopeTime(e.clientX,envelopeGeometry(canvas),model.total);inputDirty=false;draw();}
    canvas.onpointerdown=e=>{if(!model||busy||drag||e.button!==0||e.isPrimary===false||closeIfStale())return;e.preventDefault();drag={id:e.pointerId,center,input:input.value,inputDirty};canvas.setPointerCapture(e.pointerId);position(e);};canvas.onpointermove=e=>{if(drag?.id===e.pointerId&&!busy&&!closeIfStale())position(e);};canvas.onpointerup=e=>{if(drag?.id!==e.pointerId)return;drag=null;if(!closeIfStale())detail();};
    function cancelDrag(e){if(!drag||drag.id!==e.pointerId)return;const prior=drag;center=prior.center;drag=null;inputDirty=prior.inputDirty;draw(false);input.value=prior.input;}
    canvas.onpointercancel=cancelDrag;canvas.onlostpointercapture=cancelDrag;
    canvas.onkeydown=e=>{if(!model||busy||!['ArrowLeft','ArrowRight'].includes(e.key)||closeIfStale())return;e.preventDefault();e.stopPropagation();center=Math.max(0,Math.min(model.total,center+(e.key==='ArrowLeft'?-1:1)*(e.shiftKey?3600:30)));inputDirty=false;draw();detail();};
    locate.onclick=()=>{if(!model||busy||closeIfStale())return;const n=input.value.trim()===''?NaN:Number(input.value);if(!Number.isFinite(n)||n<0||n>model.total){status.textContent='定位中心超出全记录范围。';return;}center=n;inputDirty=false;draw();detail();};
    try{overview=await api(`/api/cases/${id}/waveform-overview?bins=1000`,overviewAbort?{signal:overviewAbort.signal}:{});if(closeIfStale())return;const nextModel=envelopeModel(overview),nextIdentity=ECGReviewCandidates.scope(overview);ECGAnalysisConsistency.identity(nextIdentity);if(nextIdentity.case_id!==id||!Number.isInteger(nextIdentity.beat_revision))throw Error('全记录病例依据缺失，请重新载入');const nextDomain=ECGReviewTools.waveDomain({leads:Object.fromEntries(nextModel.entries.map(({lead,peak})=>[lead,[-peak,peak]]))},key);model=nextModel;identity=nextIdentity;domain=nextDomain;node.querySelector('[data-full-method]').textContent=overview.method+' 全览按导联适应幅度；局部使用共同全记录幅度范围，设备电压未校准。';input.max=model.total;syncControls();draw();await detail();}catch(error){if(!closeIfStale())status.textContent=error.message;}
  }
  const result={open,invalidate:()=>active?.invalidate(),windowAt,envelopeGeometry,envelopeSurface,envelopeTime,envelopeModel,drawEnvelope,observeEnvelope};if(typeof module!=='undefined')module.exports=result;return result;
})();
