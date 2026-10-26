"use strict";
/* One draft per strip. Closing never writes a selection or changes a heartbeat. */
globalThis.ECGReportStripEditor=(()=>{
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let menuOwner=null;
  function closeMenu(){if(!menuOwner)return;const {node,card}=menuOwner;menuOwner=null;try{node.hidePopover();}catch(_){}node.remove();if(card.isConnected)card.focus({preventScroll:true});}
  function menu({card,event,actions,isCurrent=()=>true}){
    closeMenu();if(!isCurrent())return;
    const node=document.createElement('div'),rect=card.getBoundingClientRect();node.className='rw-strip-contextmenu';node.setAttribute('popover','manual');node.setAttribute('role','menu');node.setAttribute('aria-label','本条报告图条操作');
    node.innerHTML='<header><strong>本条报告图条</strong><button type="button" data-context-close aria-label="关闭图条菜单">×</button></header>'+actions.map((a,i)=>`<button type="button" role="menuitem" data-context-action="${i}" ${a.disabled?'disabled':''}>${esc(a.label)}</button>`).join('');
    document.body.append(node);menuOwner={node,card};try{node.showPopover();}catch(_){}
    const bounds=node.getBoundingClientRect();node.style.left=Math.max(8,Math.min(innerWidth-bounds.width-8,event?.clientX??rect.left))+'px';node.style.top=Math.max(8,Math.min(innerHeight-bounds.height-8,event?.clientY??rect.top))+'px';
    node.querySelector('[data-context-close]').onclick=closeMenu;
    node.querySelectorAll('[data-context-action]').forEach(b=>b.onclick=()=>{const action=actions[Number(b.dataset.contextAction)];closeMenu();if(isCurrent())action.run();});
    node.onkeydown=e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();closeMenu();}else if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();const buttons=[...node.querySelectorAll('[role=menuitem]:not(:disabled)')],i=buttons.indexOf(document.activeElement);buttons[(i+(e.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length]?.focus();}};
    node.querySelector('[role=menuitem]:not(:disabled)')?.focus({preventScroll:true});
  }
  if(typeof document!=='undefined')document.addEventListener('pointerdown',e=>{if(menuOwner&&!menuOwner.node.contains(e.target))closeMenu();},true);
  function project(entry,names=entry.strip.leads){
    if(!names.length||names.some(n=>!Object.hasOwn(entry.waveform.leads,n)))throw Error('所选导联无源数据，不能补绘');
    return {...entry,waveform:{...entry.waveform,leads:Object.fromEntries(names.map(n=>[n,entry.waveform.leads[n]]))}};
  }
  function curation(raw){
    const result={print_enabled:raw.print_enabled!==false,notes:raw.notes??'',preview_lead:raw.preview_lead??'II'};
    if(typeof result.notes!=='string'||result.notes.length>2000||!ECGReportEngine.leads.includes(result.preview_lead))throw Error('图条注释或预览导联无效');
    if('print_enabled' in raw&&typeof raw.print_enabled!=='boolean')throw Error('打印状态无效');
    return result;
  }
  function clockBase(meta){const date=Date.parse(String(meta.start_iso||meta.start_time||'').replace(' ','T').slice(0,19)+'Z');return Number.isFinite(date)?date:null;}
  function clockAt(base,seconds){return base==null?'':new Date(base+seconds*1000).toISOString().slice(0,23);}
  function draft(selection,entry,raw,total){
    const caption=String(raw.caption??'');if(caption.length>500)throw Error('名称最多 500 字');
    const start=Math.round(Number(raw.start_s)*200)/200,duration=Math.round(Number(raw.duration_s)*200)/200;
    if(!Number.isFinite(start)||!Number.isFinite(duration)||start<0||duration<1||duration>120||start+duration>total+.001)throw Error('图条范围须位于本记录内，时长 1–120 秒');
    const spec=ECGReportEngine.settings({leads:raw.leads,duration_s:duration,range_start_s:start,range_end_s:Math.round((start+duration)*200)/200});
    return {...selection,...spec,...curation(raw),caption};
  }
  async function open({selection,event,loadWave,isCurrent=()=>true,onApply,metadata={},total}){
    if(document.querySelector('dialog[open]')||!isCurrent())return;
    const original=structuredClone(selection),dialog=document.createElement('dialog');dialog.className='rw-strip-editor-dialog';dialog.setAttribute('aria-labelledby','rwStripEditorTitle');
    dialog.innerHTML='<header><h2 id="rwStripEditorTitle">编辑图条</h2><button type="button" data-se-close>关闭</button></header><div data-se-body role="status">正在读取本条真实波形…</div>';
    document.body.append(dialog);dialog.querySelector('[data-se-close]').onclick=()=>dialog.close();let active=true;
    dialog.addEventListener('close',()=>{active=false;dialog.remove();},{once:true});dialog.showModal();
    const current=()=>active&&dialog.open&&isCurrent();
    try{
      const entry=await loadWave(event,original);if(!current())return;
      const wave=entry.waveform,base=clockBase(metadata),options=curation(original),body=dialog.querySelector('[data-se-body]');let previewSerial=0;
      body.removeAttribute('role');body.innerHTML=`<form><div class="se-fields"><label>图条起始时间（记录时钟）<input data-se-clock type="datetime-local" step="0.005" value="${clockAt(base,wave.start_s)}" ${base==null?'disabled':''}></label><label>记录起点后秒数<input data-se-start type="number" min="0" max="${total}" step="0.005" value="${wave.start_s}"></label><label>打印时长（秒）<input data-se-duration type="number" min="1" max="120" step="0.005" value="${wave.duration_s}"></label><label>图条名称<input data-se-caption maxlength="500" value="${esc(original.caption||event.label)}"></label><label>心率<input readonly value="${ECGReviewTools.bpm(event.hr)} bpm"></label><label>预览导联<select data-se-preview aria-label="预览导联">${ECGReportEngine.leads.map(n=>`<option ${options.preview_lead===n?'selected':''}>${n}</option>`).join('')}</select></label></div><fieldset><legend>本条展示与打印通道</legend><div class="se-leads">${ECGReportEngine.leads.map(n=>`<label><input type="checkbox" data-se-lead value="${n}" ${original.leads.includes(n)?'checked':''}>${n}</label>`).join('')}</div><div class="se-shortcuts"><button type="button" data-se-preset="three">3L · II / V1 / V5</button><button type="button" data-se-preset="all">全选 / 12L</button><button type="button" data-se-preset="clear">清空</button><button type="button" data-se-preset="original">恢复本条设置</button></div><label><input type="checkbox" data-se-default>将导联选择设为本报告后续选图默认</label><label><input type="checkbox" data-se-print ${options.print_enabled?'checked':''}>本次打印此图条</label></fieldset><p class="rw-hint">网格与 N/S/V 等标注保留。波形为逐导联自适应幅度，设备电压尚未校准；暂不提供假定的 mm/mV 增益。范围调整须覆盖事件及至少 5 个可用心搏；RR 候选还须包含原始两个计时点。</p><label class="se-notes">图条注释<textarea data-se-notes aria-label="图条注释" rows="3" maxlength="2000">${esc(options.notes)}</textarea></label><div class="se-shortcuts"><button type="button" data-se-preview-button>预览本条草稿</button><span>预览不写入报告；确定后仍需保存草稿。</span></div><div data-se-wave></div><p role="status" data-se-status></p><footer><button type="submit">确定</button><button type="button" data-se-cancel>取消</button></footer></form>`;
      const q=s=>body.querySelector(s),form=q('form'),status=q('[data-se-status]');
      const values=()=>({caption:q('[data-se-caption]').value,start_s:Number(q('[data-se-start]').value),duration_s:Number(q('[data-se-duration]').value),leads:[...body.querySelectorAll('[data-se-lead]:checked')].map(n=>n.value),notes:q('[data-se-notes]').value,preview_lead:q('[data-se-preview]').value,print_enabled:q('[data-se-print]').checked});
      q('[data-se-cancel]').onclick=()=>dialog.close();q('[data-se-start]').oninput=()=>{q('[data-se-clock]').value=clockAt(base,Number(q('[data-se-start]').value));};
      q('[data-se-clock]').oninput=()=>{const t=Date.parse(q('[data-se-clock]').value+'Z');if(base!=null&&Number.isFinite(t))q('[data-se-start]').value=String(Math.round((t-base)/5)/200);};
      body.querySelectorAll('[data-se-preset]').forEach(b=>b.onclick=()=>{const names=b.dataset.sePreset==='three'?['II','V1','V5']:b.dataset.sePreset==='all'?ECGReportEngine.leads:b.dataset.sePreset==='original'?original.leads:[];body.querySelectorAll('[data-se-lead]').forEach(n=>n.checked=names.includes(n.value));});
      function draw(result,name){const host=q('[data-se-wave]'),domain=ECGReviewTools.waveDomain(result.waveform,JSON.stringify([event.event_id,event.basis_version,'strip-editor']));let twelve=false;
        const paint=()=>{const wave=twelve?result.waveform:project(result,[name]).waveform;host.innerHTML=`<button type="button" data-se-twelve>${twelve?'返回单导联预览':'查看 12 导联'}</button><p data-wave-metadata>${esc(ECGReviewTools.waveMeta(wave,metadata.start_time,domain))}</p>`+ECGReportWorkspace.reviewWaveSvg(wave,event,{width:host.clientWidth||1000,recordStart:metadata.start_time,domain});host.querySelector('[data-se-twelve]').onclick=()=>{if(current()){twelve=!twelve;paint();}};};
        host.ondblclick=e=>{if(e.button===0&&current()&&e.target.closest('svg')){e.preventDefault();e.stopPropagation();twelve=!twelve;paint();}};paint();}
      draw(entry,options.preview_lead);
      async function checked(){if(!current())throw Error('病例或报告依据已变化，请关闭后重开');const next=draft(original,entry,values(),total),validated=await loadWave(event,next);if(!current())throw Error('病例或报告已变化，本次修改未应用');return {next,validated};}
      q('[data-se-preview-button]').onclick=async()=>{const token=++previewSerial;status.textContent='正在校验预览范围…';try{const {validated,next}=await checked();if(current()&&token===previewSerial){draw(validated,next.preview_lead);status.textContent='仅预览本条草稿；原图条尚未修改。';}}catch(error){if(current())status.textContent=error.message;}};
      form.onsubmit=async e=>{e.preventDefault();previewSerial++;const submit=form.querySelector('[type=submit]');submit.disabled=true;status.textContent='正在校验图条…';try{const {next}=await checked();await onApply(next,{setDefaults:q('[data-se-default]').checked});if(current())dialog.close();else if(dialog.open)dialog.close();}catch(error){if(current()){status.textContent=error.message;submit.disabled=false;}}};
    }catch(error){if(current())dialog.querySelector('[data-se-body]').textContent='读取失败：'+error.message;}
  }
  return {project,curation,draft,clockAt,clockBase,open,menu,closeMenu};
})();
