"use strict";
/* Selected original interval -> exact source ECG. No nearest-beat fallback. */
((root)=>{
  let owner=0,workbench=null,loadAbort=null,evidenceNode=null,lastEvidence=null,resizeObserver=null;
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function evidence(){
    if(!evidenceNode){evidenceNode=document.querySelector('#rrLocatedEvidence')||document.createElement('article');evidenceNode.id='rrLocatedEvidence';evidenceNode.className='rrv-waveform-evidence';evidenceNode.setAttribute('aria-live','polite');}
    evidenceNode.hidden=false;return evidenceNode;
  }
  function clear(message='选择间期查看原始波形'){
    lastEvidence=null;const node=evidence();node.removeAttribute('data-rr-target');node.setAttribute('aria-busy','false');
    node.innerHTML=`<div class="card-header"><h2>所选间期 · 原始连续波形</h2></div><p role="status">${esc(message)}</p>`;
  }
  function dispose(){owner++;loadAbort?.abort();loadAbort=null;lastEvidence=null;resizeObserver?.disconnect();resizeObserver=null;workbench?.dispose();workbench=null;if(evidenceNode)clear();}
  async function load(){
    const node=evidence();dispose();const ticket=owner,id=state.caseId,caseToken=state.caseRequestId,host=document.querySelector('#rrReviewWorkbench');
    if(!host||!id)return;
    const current=()=>ticket===owner&&state.caseId===id&&state.caseRequestId===caseToken&&state.currentPage==='rr'&&host.isConnected;
    host.innerHTML='<p role="status">读取当前 RR 复核依据…</p>';clear('读取当前筛选，随后显示第一个可精确定位间期的原始波形。');loadAbort=new AbortController();
    try{
      const basis=await api(`/api/cases/${encodeURIComponent(id)}/analysis-basis`,{signal:loadAbort.signal});
      const editor=await api(ECGAnalysisConsistency.url(id,'beat-editor',{},basis),{signal:loadAbort.signal});
      if(!current())return;
      const identity={...basis,beat_revision:editor.revision};
      const readSelection=async(target,guard)=>{
        if(target===null){if(current())clear(guard.reason==='cancel'?'波形读取已取消，可重新读取。':'选择当前条件的间期查看原始波形。');return false;}
        const stillCurrent=()=>current()&&guard.isCurrent();if(!stillCurrent())return false;
        clear('正在读取所选间期的精确原始三导联波形…');node.setAttribute('aria-busy','true');
        try{
          const result=await api(`/api/cases/${encodeURIComponent(id)}/rr-review/locate`,{method:'POST',body:JSON.stringify({target}),signal:guard.signal});
          if(!stillCurrent())return false;
          if(result.case_id!==id||['sample_index','beat_id','interval_id','interval_start_sample','interval_end_sample','index_key'].some(key=>result.target?.[key]!==target[key]))throw Error('精确定位结果不一致，未显示波形');
          ECGAnalysisConsistency.assertSame(identity,result);ECGAnalysisConsistency.assertSame(identity,result.waveform);
          const wave=result.waveform,fs=Number(wave?.sample_rate_hz);
          if(wave?.case_id!==id||!Number.isInteger(wave?.stride)||wave.stride<=0||!Number.isFinite(fs)||fs<=0||!Number.isFinite(wave?.start_s)||!Number.isFinite(wave?.duration_s)||wave.duration_s<=0||!wave.beats?.some(b=>b.sample_index===target.sample_index))throw Error('原始证据缺少目标心搏，未使用最近邻替代');
          if(!['II','V1','V5'].every(lead=>Array.isArray(wave.leads?.[lead])&&wave.leads[lead].length===wave.leads.II.length&&wave.leads[lead].length&&wave.leads[lead].every(Number.isFinite)))throw Error('原始三导联证据不完整，未显示');
          if(!['raw','raw overview'].includes(wave.filter))throw Error('返回的证据不是原始波形，未显示');
          lastEvidence={wave,target,guard:stillCurrent};renderEvidence();
          if(guard.reveal)node.scrollIntoView({block:'nearest'});
          return {located:true};
        }catch(error){
          if(!stillCurrent()||error.name==='AbortError')return false;
          clear(`所选波形读取失败：${error.message}`);node.querySelector('[role="status"]').setAttribute('role','alert');
          const button=document.createElement('button');button.type='button';button.className='button secondary';button.textContent='重读所选波形';button.onclick=()=>workbench?.retrySelection();node.appendChild(button);throw error;
        }finally{if(stillCurrent())node.setAttribute('aria-busy','false');}
      };
      workbench=ECGRRReview.mount({host,caseId:id,caseToken,basis:identity,api,isCurrent:current,filter:'raw',onSelection:readSelection,onLocate:readSelection});
      const slot=host.querySelector('[data-rr-role="evidence-slot"]');if(!slot)throw Error('RR 原始波形区域未挂载');slot.appendChild(node);
      if(typeof ResizeObserver!=='undefined'){resizeObserver=new ResizeObserver(()=>{if(lastEvidence?.guard())renderEvidence();});resizeObserver.observe(node);}
      await workbench.load();
    }catch(error){if(!current()||error.name==='AbortError')return;host.innerHTML=`<p role="alert">RR 读取失败：${esc(error.message)}</p><button class="button secondary" type="button" data-rr-load-retry>重试</button>`;host.querySelector('button').onclick=()=>load().catch(handleError);clear('当前筛选读取未完成，重试后再显示原始证据。');}
    finally{if(current())loadAbort=null;}
  }
  function renderEvidence(){
    const value=lastEvidence;if(!value||!value.guard()||!evidenceNode?.isConnected)return;
    const {wave,target}=value,fs=wave.sample_rate_hz,left=target.interval_start_sample/fs,ends=wave.start_s+wave.duration_s,offWindow=left<wave.start_s||left>=ends;
    const time=s=>typeof formatElapsedPrecise==='function'?formatElapsedPrecise(s):`${s.toFixed(3)} s`;
    const width=Math.max(1,evidenceNode.clientWidth-24);
    evidenceNode.setAttribute('data-rr-target',String(target.sample_index));evidenceNode.setAttribute('aria-busy','false');
    evidenceNode.innerHTML=`<div class="card-header"><h2>所选间期 · 原始连续波形</h2><button type="button" class="button secondary" data-rr-return>返回间期列表</button></div><div class="rrv-wave-stage">${waveSvg(wave,target,width)}</div><p class="rrv-wave-caption">${esc(time(wave.start_s))}–${esc(time(ends))} · II / V1 / V5 · 原始波形 · 设备单位 u，未校准${wave.stride>1?` · 显示步长 ${wave.stride} 样本`:''}${offWindow?' · 前搏在当前窗口外；本窗展示精确终搏，不覆盖完整间期':''}</p>`;
    evidenceNode.querySelector('[data-rr-return]').onclick=()=>{if(value.guard()){const row=document.querySelector('#rrReviewWorkbench tr[aria-selected="true"]');row?.scrollIntoView({block:'nearest'});row?.focus({preventScroll:true});}};
  }
  function waveSvg(wave,target,width){
    const fs=wave.sample_rate_hz,rowHeight=88,entries=['II','V1','V5'].map(lead=>[lead,wave.leads[lead]]),height=rowHeight*entries.length;
    const x=sample=>(sample/fs-wave.start_s)/wave.duration_s*width,left=x(target.interval_start_sample),right=x(target.sample_index);
    const marks=[[left,'前搏','#2678b9'],[right,'终搏','#bc6500']].filter(([at])=>at>=0&&at<width);
    return `<svg style="display:block;width:100%;height:${height}px" viewBox="0 0 ${width} ${height}" role="img" aria-label="所选原始 RR 间期的精确三导联波形"><rect width="100%" height="100%" fill="white"/><rect x="${Math.max(0,left)}" y="0" width="${Math.max(0,Math.min(width,right)-Math.max(0,left))}" height="${height}" fill="#e8f5f2"/>${entries.map(([lead,values],j)=>{const peak=Math.max(50,...values.map(Math.abs)),mid=j*rowHeight+rowHeight/2;return `<path d="M0 ${mid}H${width}" stroke="#e4ecef"/><text x="3" y="${j*rowHeight+17}" font-size="12" fill="#1c5961">${lead}</text><polyline fill="none" stroke="#244f59" stroke-width="1.1" points="${values.map((v,i)=>`${(i*(wave.stride||1)/fs/wave.duration_s*width).toFixed(3)},${(mid-v/peak*rowHeight*.36).toFixed(3)}`).join(' ')}"/>`}).join('')}${marks.map(([at,label,color])=>`<path d="M${at} 0V${height}" stroke="${color}" stroke-width="1.5"/><text x="${Math.max(4,Math.min(width-36,at+4))}" y="14" font-size="12" fill="${color}">${label}</text>`).join('')}</svg>`;
  }
  root.ecgRRBridge={load,dispose,snapshot:()=>workbench?.snapshot()??null};
})(globalThis);
