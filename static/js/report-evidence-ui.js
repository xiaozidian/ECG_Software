"use strict";
/* The report owns evidence review; view-only lead changes never alter print settings. */
globalThis.ECGReportEvidenceUI=(()=>{
  const fields=['case_id','analysis_basis','analysis_revision','beat_revision'];
  const scope=value=>Object.fromEntries(fields.map(k=>[k,value[k]]));
  const eligible=e=>!!e&&(e.evidence_only||e.category==='pause');
  const used=(c,s,e)=>{const pages=ECGReportSections.selectedPages(c);if(e?.category==='ST'&&Array.isArray(c.stt_report_use)){const use=c.stt_report_use.find(row=>row.event_id===s.event_id);return !!use&&use.strip&&pages.includes('event_strips')&&s.print_enabled!==false;}return s.referenced_in_report===true||pages.includes('event_strips')&&s.print_enabled!==false&&(!e||!['fastest','slowest'].includes(e.category)||c.fast_slow_mode==='both'||e.subtype===(c.fast_slow_mode||'rr').toUpperCase());};
  const selection=(s,e)=>{const p=ECGReportEngine.settings(s);return {leads:p.leads,duration_s:p.duration_s,range_start_s:p.range_start_s??null,range_end_s:p.range_end_s??null,caption:s.caption||e.label||'',notes:s.notes||''};};
  function confirmed(s,e){
    const own=selection(s,e),review=e?.evidence_review;
    return review?.status==='confirmed'&&review.presentations.some(p=>Object.keys(own).every(k=>JSON.stringify(p.selection?.[k])===JSON.stringify(own[k])));
  }
  function paint(host,wave,event){
    const height=Math.max(180,Math.min(490,innerHeight-310)),width=Math.max(280,host.clientWidth||900);
    host.innerHTML=ECGReportWorkspace.reviewWaveSvg(wave,event,{width,fitHeight:height,recordStart:state.caseData?.metadata?.start_time});
    const svg=host.querySelector('svg'),ref=event.evidence_ref;
    if(ref?.kind!=='rr')return;
    const x=sample=>Number(svg.dataset.plotLeft)+(sample/wave.sample_rate_hz-wave.start_s)/wave.duration_s*Number(svg.dataset.plotWidth);
    const a=x(ref.previous.sample_index),b=x(ref.terminal.sample_index),h=Number(svg.viewBox.baseVal.height)-24;
    svg.insertAdjacentHTML('beforeend',`<g data-report-rr-interval><rect x="${a}" y="36" width="${b-a}" height="${Math.max(0,h-36)}" fill="#087e7e" fill-opacity=".06"/><path d="M${a} 36V${h}" stroke="#2678b9"/><path d="M${b} 36V${h}" stroke="#bc6500"/></g>`);
  }
  let generation=0;
  async function open({api,id,identity,event=null,entry={},target=null,isCurrent=()=>true,onSaved,onCorrect,include=false}){
    document.querySelector('#reportEvidenceDialog')?.close();
    const token=++generation,dialog=document.createElement('dialog');dialog.id='reportEvidenceDialog';dialog.className='modal rw-rr-review-dialog';dialog.setAttribute('aria-labelledby','reportEvidenceTitle');
    dialog.innerHTML='<header class="modal-header"><h2 id="reportEvidenceTitle">核对入报证据</h2><button type="button" data-evidence-close aria-label="关闭核对窗口">×</button></header><p data-evidence-description></p><div class="rw-rr-view-leads" aria-label="当前查看导联"><span>查看导联</span><button type="button" data-evidence-leads="1">1L</button><button type="button" data-evidence-leads="3">3L</button><button type="button" data-evidence-leads="12">12L</button></div><div data-evidence-wave aria-live="polite">正在读取本条原始波形…</div><p data-evidence-metadata></p><p class="rw-hint">核对原始波形、两端心搏、测量和图注。确认记录用于本条证据，疾病诊断由医生另行判断。</p><p role="status" data-evidence-status></p><footer class="modal-actions"><button type="button" data-evidence-retry hidden>重试读取</button><button type="button" data-evidence-correct disabled>修正识别</button><button type="button" data-evidence-close>稍后核对</button><button type="button" class="button primary" data-evidence-confirm disabled></button></footer>';
    const button=dialog.querySelector('[data-evidence-confirm]');button.textContent=include?'确认并入报':'确认本条';
    document.body.append(dialog);dialog.showModal();
    let preview=null,viewWave=null,busy=false,reading=0;
    const current=()=>token===generation&&dialog.open&&dialog.isConnected&&isCurrent();
    const status=dialog.querySelector('[data-evidence-status]'),host=dialog.querySelector('[data-evidence-wave]');
    const body={...scope(identity),...(target?{target}:{event_id:event.event_id,basis_version:event.basis_version}),entry};
    const disable=()=>{dialog.querySelectorAll('button').forEach(b=>{b.disabled=busy;});button.disabled=busy||!preview||!viewWave;dialog.querySelector('[data-evidence-correct]').disabled=busy||!preview||!viewWave;};
    const fail=error=>{if(!current())return;viewWave=null;status.textContent='读取未完成：'+error.message;host.textContent='本条波形未就绪，请重试后核对。';dialog.querySelector('[data-evidence-retry]').hidden=false;disable();};
    function render(){if(!current()||!viewWave)return;paint(host,viewWave,preview.event);host.dataset.ready='true';host.dataset.leadCount=String(Object.keys(viewWave.leads).length);dialog.querySelectorAll('[data-evidence-leads]').forEach(b=>b.setAttribute('aria-pressed',String(Number(b.dataset.evidenceLeads)===Object.keys(viewWave.leads).length)));}
    async function load(){
      const read=++reading;preview=null;viewWave=null;disable();host.textContent='正在读取本条原始波形…';
      try{const value=await api(`/api/cases/${id}/report-evidence/preview`,{method:'POST',body:JSON.stringify(body)});if(!current()||read!==reading)return;
        ECGAnalysisConsistency.assertSame(identity,value);preview=value;viewWave=value.waveform;
        const ref=value.event.evidence_ref;dialog.querySelector('#reportEvidenceTitle').textContent=target==='longest'?'核对最长 RR 数值':'核对入报证据';
        dialog.querySelector('[data-evidence-description]').textContent=(value.entry.caption||value.event.label)+(ref?.kind==='rr'?` · RR ${ref.rr_ms} ms · 两端 R 峰相隔 ${ref.endpoint_delta_ms} ms`:'');
        dialog.querySelector('[data-evidence-metadata]').textContent=`${ECGReviewTools.clockLabel(state.caseData?.metadata?.start_time,value.waveform.start_s)} — ${ECGReviewTools.clockLabel(state.caseData?.metadata?.start_time,value.waveform.start_s+value.waveform.duration_s)} · 本条${target?'核对':'入报'}导联 ${value.strip.leads.join(' / ')} · 查看切换不改入报设置`;
        status.textContent=target==='longest'?'核对当前可分析记录中的最大 RR；确认数值不增加打印图条。':'已读取当前图条；查看后确认，或修正心搏识别。';
        dialog.querySelector('[data-evidence-retry]').hidden=true;render();disable();
      }catch(error){if(read===reading)fail(error);}
    }
    dialog.querySelectorAll('[data-evidence-close]').forEach(b=>b.onclick=()=>{if(!busy)dialog.close();});
    dialog.addEventListener('cancel',e=>{if(busy)e.preventDefault();});
    const observer=typeof ResizeObserver==='undefined'?null:new ResizeObserver(()=>render());observer?.observe(host);
    dialog.addEventListener('close',()=>{observer?.disconnect();dialog.remove();});
    dialog.querySelector('[data-evidence-retry]').onclick=load;
    dialog.querySelectorAll('[data-evidence-leads]').forEach(b=>b.onclick=async()=>{
      if(!current()||!preview||busy)return;const read=++reading,n=Number(b.dataset.evidenceLeads),names=n===1?['II']:n===3?['II','V1','V5']:ECGReportEngine.leads;
      viewWave=null;disable();host.textContent='正在读取同一时间窗的所选导联…';
      try{const q=new URLSearchParams({...scope(preview),start:preview.waveform.start_s,end:preview.waveform.start_s+preview.waveform.duration_s,leads:names.join(','),max_points:12000,analysis:'edited'});
        const wave=await api(`/api/cases/${id}/event-waveform?${q}`);if(!current()||read!==reading)return;ECGAnalysisConsistency.assertSame(preview,wave);
        if(Math.abs(wave.start_s-preview.waveform.start_s)>.005||Math.abs(wave.duration_s-preview.waveform.duration_s)>.005||!names.every(name=>wave.leads[name]?.length))throw Error('导联或时间窗不一致');
        viewWave=wave;status.textContent='已显示同一时间窗；原入报导联设置保留。';render();disable();
      }catch(error){if(read===reading)fail(error);}
    });
    dialog.querySelector('[data-evidence-correct]').onclick=()=>{if(!current()||!preview||!viewWave||busy)return;const value=preview;dialog.close();onCorrect?.(value);};
    button.onclick=async()=>{
      if(!current()||!preview||!viewWave||busy)return;busy=true;disable();status.textContent='正在保存本条核对…';
      try{const value=await api(`/api/cases/${id}/report-evidence/confirm`,{method:'POST',body:JSON.stringify({...body,...scope(preview),entry:preview.entry,confirmed:true,evidence_key:preview.evidence_key,presentation_key:preview.presentation_key,report_version:preview.report_version})});
        if(!current())return;dialog.close();await onSaved?.(value);
      }catch(error){if(current())status.textContent='核对未保存：'+error.message;else globalThis.handleError?.(error);}
      finally{busy=false;if(current())disable();}
    };
    await load();return dialog;
  }
  function correction({host,preview,isCurrent=()=>true}){
    document.querySelector('#reportEvidenceCorrection')?.remove();
    const panel=document.createElement('section');panel.id='reportEvidenceCorrection';panel.className='rw-rr-correction';panel.innerHTML='<header><strong>修正本条识别</strong><button type="button" data-correction-close>结束修正</button></header><p>右击需要修订的 N / V 等心搏，或右击波形位置补入、移动、删除 QRS。保存后将重算 RR 并返回报告；原选图保留，依据变化时需要重新选择。</p><div data-correction-wave></div>';
    host.prepend(panel);const wave={...preview.waveform,...scope(preview),beats:preview.waveform.beats.map(b=>({...b,time_s:b.sample_index/200}))},stage=panel.querySelector('[data-correction-wave]');
    paint(stage,wave,preview.event);beatEditor.bindWaveSurface(stage,{wave,readOnly:false,isCurrent:()=>panel.isConnected&&isCurrent()});
    panel.querySelector('[data-correction-close]').onclick=()=>panel.remove();panel.scrollIntoView({block:'start'});stage.focus({preventScroll:true});return panel;
  }
  return {eligible,confirmed,selection,used,open,correction};
})();
