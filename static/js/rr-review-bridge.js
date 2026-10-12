"use strict";
/* Full app adapter. Reads exact source samples; no nearest-beat substitution. */
((root)=>{
  let owner=0,workbench=null,loadAbort=null;
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function dispose(){owner++;loadAbort?.abort();loadAbort=null;workbench?.dispose();workbench=null;}
  async function load(){
    dispose();const ticket=owner,id=state.caseId,caseToken=state.caseRequestId,host=document.querySelector('#rrReviewWorkbench'),waveHost=document.querySelector('#rrLocatedEvidence');
    if(!host||!id)return;const current=()=>ticket===owner&&state.caseId===id&&state.caseRequestId===caseToken&&state.currentPage==='rr'&&host.isConnected;
    host.innerHTML='<p role="status">读取当前 RR 复核依据…</p>';waveHost.hidden=true;
    loadAbort=new AbortController();
    try{
      const basis=await api(`/api/cases/${encodeURIComponent(id)}/analysis-basis`,{signal:loadAbort.signal});
      const editor=await api(ECGAnalysisConsistency.url(id,'beat-editor',{},basis),{signal:loadAbort.signal});
      if(!current())return;
      const identity={...basis,beat_revision:editor.revision};
      workbench=ECGRRReview.mount({host,caseId:id,caseToken,basis:identity,api,isCurrent:current,filter:'raw',onLocate:async(target,guard)=>{
        const stillCurrent=()=>current()&&guard.isCurrent();
        const result=await api(`/api/cases/${encodeURIComponent(id)}/rr-review/locate`,{method:'POST',body:JSON.stringify({target}),signal:guard.signal});
        if(!stillCurrent())return false;
        if(result.case_id!==id||result.target.sample_index!==target.sample_index||result.target.beat_id!==target.beat_id||result.target.interval_id!==target.interval_id)throw Error('精确定位结果不一致，未显示波形');
        ECGAnalysisConsistency.assertSame(identity,result);
        const wave=result.waveform;
        if(!wave?.beats?.some(b=>b.sample_index===target.sample_index))throw Error('原始证据中缺少目标心搏，未使用最近邻替代');
        waveHost.hidden=false;
        waveHost.innerHTML=`<div class="card-header"><h2>RR 原始波形证据</h2><button type="button" class="button secondary" data-rr-return>返回分类列表</button></div><p>采样 ${target.interval_start_sample} → ${target.interval_end_sample} · 逐搏修订 ${identity.beat_revision} · 设备单位 u，未校准</p>${waveSvg(wave,target)}<p>原始采样，无额外显示滤波；竖线指向所选终搏。</p>`;
        waveHost.querySelector('[data-rr-return]').onclick=()=>{if(stillCurrent()){host.querySelector('[data-rr-role="results"]')?.scrollIntoView({block:'center'});host.querySelector('[data-rr-action="locate"]')?.focus({preventScroll:true});}};
        waveHost.scrollIntoView({block:'start'});return {located:true};
      }});
      await workbench.load();
    }catch(error){if(!current()||error.name==='AbortError')return;host.innerHTML=`<p role="alert">RR 读取失败：${esc(error.message)}</p><button class="button secondary" type="button" data-rr-load-retry>重试</button>`;host.querySelector('button').onclick=()=>load().catch(handleError);}
    finally{if(current())loadAbort=null;}
  }
  function waveSvg(wave,target){
    const width=1200,rowHeight=125,entries=Object.entries(wave.leads||{}),height=rowHeight*entries.length,x=(target.sample_index/200-wave.start_s)/wave.duration_s*width;
    return `<svg style="display:block;width:100%;max-height:430px" viewBox="0 0 ${width} ${height}" role="img" aria-label="精确 RR 原始三导联波形"><rect width="100%" height="100%" fill="white"/>${entries.map(([lead,values],j)=>{const peak=Math.max(50,...values.map(v=>Math.abs(v))),mid=j*rowHeight+rowHeight/2;return `<text x="2" y="${j*rowHeight+16}" font-size="14">${esc(lead)}</text><polyline fill="none" stroke="#244f59" stroke-width="1.1" points="${values.map((v,i)=>`${(i*(wave.stride||1)/(wave.sample_rate_hz||200)/wave.duration_s*width).toFixed(3)},${(mid-v/peak*rowHeight*.4).toFixed(3)}`).join(' ')}"/>`}).join('')}<path d="M${x} 0V${height}" stroke="#cc7200" stroke-width="1.5"/><text x="${Math.max(4,Math.min(width-90,x+5))}" y="14" fill="#9c5300">目标终搏</text></svg>`;
  }
  root.ecgRRBridge={load,dispose,snapshot:()=>workbench?.snapshot()??null};
})(globalThis);
