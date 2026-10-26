"use strict";
/* Explicit local picks, separate from editing beats and selecting report output. */
const ECGReviewCandidates=globalThis.ECGReviewCandidates=(()=>{
  const esc=x=>escapeHtml(String(x??''));
  const scope=c=>({case_id:c.case_id||c.caseId,analysis_basis:c.analysis_basis,analysis_revision:c.analysis_revision,beat_revision:c.beat_revision??c.beatRevision});
  function modal(title,body){const node=document.createElement('dialog');node.className='review-candidate-dialog';node.innerHTML=`<header><h2>${esc(title)}</h2><button type="button" data-candidate-close>关闭</button></header>${body}<p role="status" data-candidate-status></p>`;document.body.append(node);node.querySelector('[data-candidate-close]').onclick=()=>node.close();node.onclose=()=>node.remove();node.showModal();return node;}
  async function preview({identity,item,isCurrent=()=>true}){
    if(!isCurrent())return;const own=scope(identity),id=state.caseId,token=state.caseRequestId;
    const node=modal('小图 · 12 导联预览','<div data-candidate-wave>正在读取原始波形…</div><p>同一原心搏计时点；设备单位未校准。关闭不会保存或改型。</p>');
    try{const params=new URLSearchParams({start:Math.max(0,item.sample_index/200-Math.max(3,(item.rr_ms||0)/1000+.5)),duration:Math.min(120,Math.max(7,(item.rr_ms||0)/1000+4)),leads:'I,II,III,aVR,aVL,aVF,V1,V2,V3,V4,V5,V6',max_points:12000,filter:'raw',analysis_basis:own.analysis_basis,analysis_revision:own.analysis_revision});
      const wave=await api(`/api/cases/${id}/waveform?${params}`);
      if(!node.isConnected)return;if(id!==state.caseId||token!==state.caseRequestId||!isCurrent())throw Error('病例或小图集合已变化，请关闭后重开');
      node.querySelector('[data-candidate-wave]').innerHTML=ECGReportWorkspace.reviewWaveSvg(wave,{label:'原心搏三导联小图的12导联复核'});
    }catch(error){if(node.isConnected)node.querySelector('[data-candidate-status]').textContent=error.message;}
  }
  async function choose({identity,item,population={},isCurrent=()=>true}){
    if(!isCurrent())throw Error('小图集合已变化，请重新右击');
    if(!ECGOccurrenceCard.rrCandidateAvailable(item))throw Error('此心搏未提供有效前 RR，或为质控标记；不能建立 RR 候选。');
    const own=scope(identity),token=state.caseRequestId;
    const current=()=>isCurrent()&&state.caseId===own.case_id&&state.caseRequestId===token;
    const node=modal('加入最长 RR 间期候选',`<p>当前心搏 ${esc(formatElapsedPrecise(item.sample_index/200))} · RR ${esc(item.rr_ms)} ms。保存原相邻心搏、记录依据及 II / V1 / V5 上下文；此选取不声明全记录最长。</p><label>候选图注<input aria-label="候选图注" maxlength="120" value="自选 RR 候选 ${(Number(item.rr_ms)/1000).toFixed(3)} s"></label><div class="range-actions"><button type="button" data-candidate-save>保存候选</button><button type="button" data-candidate-cancel>取消</button></div><p>保存候选后，须在报告“最长 RR 间期候选”中另行勾选入报。</p>`);
    node.querySelector('[data-candidate-cancel]').onclick=()=>node.close();let busy=false;node.addEventListener('cancel',e=>{if(busy)e.preventDefault();});
    node.querySelector('[data-candidate-save]').onclick=async()=>{
      if(busy)return;const status=node.querySelector('[data-candidate-status]');if(!current()){status.textContent='病例或所选 RR 区间已变化，未保存；请关闭后重新选择。';return;}
      busy=true;node.querySelectorAll('button,input').forEach(x=>x.disabled=true);
      try{const result=await api(`/api/cases/${own.case_id}/evidence-candidates`,{method:'POST',body:JSON.stringify({...own,kind:'rr',sample_index:item.sample_index,rr_ms:item.rr_ms,population,caption:node.querySelector('input').value,settings:{leads:['II','V1','V5'],duration_s:7}})});
        if(node.isConnected){const reportKnown=state.report?.case_id===own.case_id&&Array.isArray(state.report?.composition?.selected_events),included=current()&&reportKnown&&state.report.composition.selected_events.some(p=>p.event_id===`local-pick:${result.item.id}`);status.textContent=`候选 #${result.item.id} 已保存；${!current()?'当前病例或选区已变化，请返回原选区核对':!reportKnown?'是否入报请到报告编排核对':included?'报告草稿已选中此候选':'尚未入报'}。已存图注：${result.item.payload.caption}。重复保存复用该候选，已有报告图注和设置保留。`;document.dispatchEvent(new CustomEvent('ecg-evidence-candidates-changed',{detail:{case_id:own.case_id}}));node.querySelector('[data-candidate-save]').hidden=true;node.querySelector('[data-candidate-cancel]').textContent='完成';}
      }catch(error){if(node.isConnected)status.textContent=error.message+'；没有自动重试。';}
      finally{busy=false;if(node.isConnected)node.querySelectorAll('button,input').forEach(x=>x.disabled=false);}
    };
  }
  async function pool(identity=null){
    const id=state.caseId,token=state.caseRequestId;
    const result=await api(`/api/cases/${id}/evidence-candidates`);if(id!==state.caseId||token!==state.caseRequestId)return;
    const own=scope(result),current=()=>id===state.caseId&&token===state.caseRequestId;
    const node=modal('最长 RR 间期候选',`<p>按 RR 从长到短。此处管理候选；入报请到报告页单独勾选。撤销保留审计记录。</p><div data-candidate-list></div>`);
    let items=result.items.filter(x=>x.kind==='rr'),busy=false;
    const render=()=>{node.querySelector('[data-candidate-list]').innerHTML=items.sort((a,b)=>b.payload.rr_ms-a.payload.rr_ms||a.payload.rr_end_sample-b.payload.rr_end_sample).map(c=>{const p=c.payload,valid=c.scope.analysis_basis===own.analysis_basis&&c.scope.beat_revision===own.beat_revision;return `<article><strong>${esc(p.caption)}</strong><p>${esc(formatElapsedPrecise(p.start_s))} → ${esc(formatElapsedPrecise(p.end_s))} · ${esc(p.rr_ms)} ms · II / V1 / V5 · ${c.status==='withdrawn'?'已撤销':valid?'来源当前':'来源已变化，不能入报'}</p><button type="button" data-candidate-id="${c.id}" ${!valid?'disabled':''}>${c.status==='withdrawn'?'恢复候选':'撤销候选'}</button></article>`;}).join('')||'<p>尚无 RR 候选。</p>';};render();
    node.querySelector('[data-candidate-list]').onclick=async e=>{const b=e.target.closest('[data-candidate-id]');if(!b||busy||!current())return;const item=items.find(x=>x.id===Number(b.dataset.candidateId));if(!item)return;busy=true;b.disabled=true;try{const r=await api(`/api/cases/${id}/evidence-candidates`,{method:'PATCH',body:JSON.stringify({...own,id:item.id,status:item.status==='active'?'withdrawn':'active'})});if(current()&&node.isConnected){items=items.map(x=>x.id===item.id?r.item:x);render();document.dispatchEvent(new CustomEvent('ecg-evidence-candidates-changed',{detail:{case_id:id}}));node.querySelector('[data-candidate-status]').textContent=r.item.status==='withdrawn'?'候选已撤销；已选报告图条会要求重新核对。':'候选已恢复；本次未更改报告入报选择，请核对原有图条。';}}catch(error){if(node.isConnected)node.querySelector('[data-candidate-status]').textContent=error.message;}finally{busy=false;if(b.isConnected)b.disabled=false;}};
  }
  return {choose,pool,scope,preview};
})();
