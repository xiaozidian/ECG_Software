"use strict";
/* Exclusion-only editor. HRV values come from the server; ECG/NN labels and
   thresholds are never written by this component. */
globalThis.ECGHRVEditor=(()=>{
  const SCOPE=['case_id','source_digest','data_version','analysis_basis','beat_revision','analysis_revision'];
  const SOURCE=SCOPE.filter(k=>k!=='analysis_revision'), bookmarks=new Map(),editors=new Set();
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const copy=v=>JSON.parse(JSON.stringify(v)), n=v=>Number.isFinite(v)?String(Math.round(v*100)/100):'—';
  const time=v=>{if(!Number.isFinite(v))return '—';const ticks=Math.round(v*200),h=Math.floor(ticks/720000),m=Math.floor(ticks%720000/12000),s=Math.floor(ticks%12000/200),ms=(ticks%200)*5;return `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}${ms?'.'+String(ms).padStart(3,'0'):''}`;};
  const metrics=[['nn_count','NN 候选数',''],['mean_nn_ms','平均 NN','ms'],['sdnn_ms','SDNN','ms'],['rmssd_ms','rMSSD','ms'],['pnn50_pct','pNN50','%'],['sdann_ms','SDANN','ms'],['sdnn_index_ms','SDNN index','ms'],['triangular_index','三角指数','']];
  const frequency=[['total_ms2','总功率','ms²'],['vlf_ms2','VLF','ms²'],['lf_ms2','LF','ms²'],['hf_ms2','HF','ms²'],['lf_hf','LF/HF','']];
  const reasons={incomplete_300s_block:'不足完整 300 秒',nn_count_below_30:'NN 候选不足 30 个',nn_coverage_below_240s:'有效 NN 累计不足 240 秒',block_not_qualified:'未达到既有短段计算门槛',too_few_nn_observations:'NN 观测不足',invalid_nn_time_order:'NN 时间顺序无效',insufficient_spectral_observation_span:'频谱观测跨度不足',spectral_gap_over_5s:'频谱区间存在超过 5 秒的缺口',spectral_interpolation_crosses_exclusion:'频谱插值将跨越排除区间',spectrum_unavailable:'频谱不可用'};
  function validateScope(scope,id){if(!scope||typeof scope!=='object'||scope.case_id!==id)throw Error('HRV 病例依据不一致，请重新读取');for(const k of SCOPE){const v=scope[k];if(['beat_revision','analysis_revision'].includes(k)?!Number.isSafeInteger(v)||v<0:typeof v!=='string'||!v.trim())throw Error('HRV 计算依据不完整，请重新读取');}return scope;}
  const sameScope=(a,b)=>!!a&&!!b&&SCOPE.every(k=>a[k]===b[k]);
  const sameSource=(a,b)=>!!a&&!!b&&SOURCE.every(k=>a[k]===b[k]);
  function givenScope(scope,basis){return SCOPE.every(k=>basis?.[k]===undefined||scope[k]===basis[k]);}
  function rangeInput(start,end,reason,limit){
    if(String(start??'').trim()===''||String(end??'').trim()==='')throw Error('请填写记录后的排除起止秒数');
    const a=Number(start),b=Number(end),sa=a*200,sb=b*200;
    if(!Number.isFinite(a)||!Number.isFinite(b)||Math.abs(sa-Math.round(sa))>1e-7||Math.abs(sb-Math.round(sb))>1e-7)throw Error('起止时间必须落在 5 ms 采样边界');
    if(!Number.isSafeInteger(Math.round(sa))||!Number.isSafeInteger(Math.round(sb))||sa<0||sb>limit||sa>=sb)throw Error('排除区间必须位于记录内，且起点早于终点');
    if(typeof reason!=='string'||!reason.trim()||reason.length>500)throw Error('请填写 1–500 字的排除原因');
    return {start_sample:Math.round(sa),end_sample:Math.round(sb),reason:reason.trim()};
  }
  function compare(left,right,columns=metrics){return `<table class="hrv-edit-comparison"><thead><tr><th scope="col">指标</th><th scope="col">原值</th><th scope="col">复核值</th></tr></thead><tbody>${columns.map(([k,label,u])=>`<tr><th scope="row">${esc(label)}${u?' '+esc(u):''}</th><td data-hrv-edit-value="original-${k}">${n(left?.[k])}</td><td data-hrv-edit-value="reviewed-${k}">${n(right?.[k])}</td></tr>`).join('')}</tbody></table>`;}
  function availability(row){if(!row)return '未应用历史排除区间';if(!row.qualified)return (row.qualification_reasons||[]).map(r=>reasons[r]||r).join('；')||'短段不可估计';return row.spectral_qualified?'有可计算短段频谱':reasons[row.spectral_reason]||row.spectral_reason||'频谱不可用';}
  function evidenceOf(value,preview=false){return value?.[preview?'evidence_preview':'evidence']||((value?.baseline&&value?.blocks)?value:null);}
  function blockTable(evidence,{pending=false,stale=false}={}){return (evidence?.blocks||[]).map((b,i)=>{const r=stale?null:b.reviewed;return `<tr data-hrv-edit-row="${esc(b.id)}"><th scope="row"><button type="button" data-hrv-edit-block="${esc(b.id)}" aria-pressed="false">${i+1}</button></th><td>记录后 ${time(b.start_s)}–${time(b.end_s)}${b.complete?'':' · 不完整'}</td><td>${n(b.baseline?.nn_count)} / ${n(r?.nn_count)}</td><td>${n(b.baseline?.sdnn_ms)} / ${n(r?.sdnn_ms)}</td><td>${esc(availability(r))}</td><td>${n(stale?null:b.excluded_s)} 秒${pending?' · 预览':''}</td></tr>`;}).join('')||'<tr><td colspan="6">当前窗口没有可列出的时间段；缺失不显示为零。</td></tr>';}
  function mount(host,{id,basis={},api,isCurrent=()=>host.isConnected,onSaved=()=>{},onLocate=null,onPendingChange=()=>{},writable=true,windowIndex=0,cancelPreview=true}={}){
    if(typeof id!=='string'||!id||typeof api!=='function')throw Error('HRV 编辑器缺少病例或接口');
    let model=null,preview=null,busy=false,failed=false,disposed=false,epoch=0,selected=null,domain='time',error='',waveEpoch=0,rangeDirty=false;
    const base='/api/cases/'+encodeURIComponent(id)+'/hrv-review',mountOwner={};host._hrvEditorOwner=mountOwner;
    host.classList.add('hrv-edit');host.setAttribute('aria-label','固定五分钟 HRV 区间复核');
    host.innerHTML=`<header class="hrv-edit-heading"><div><h2>五分钟 HRV 复核</h2><p data-hrv-edit-heading>读取当前窗口…</p></div><div class="hrv-edit-actions"><button type="button" class="button secondary" data-hrv-edit-action="reload">重新读取</button><button type="button" class="button secondary" data-hrv-edit-action="undo">撤销区间修订</button><button type="button" class="button secondary" data-hrv-edit-action="redo">重做</button><button type="button" class="button secondary" data-hrv-edit-action="reset">重置排除区间</button></div></header><p class="hrv-edit-boundary">NN 为既有 N 标签、纳入范围和节律排除规则筛选的候选；窦性来源与信号质量尚未自动验证。固定 300 秒、至少 30 NN 和累计 240 秒是当前工程兼容协议。此页只编辑 HRV 排除区间，保留原始波形、心搏标记和 NN 阈值。</p><p class="hrv-edit-status" data-hrv-edit-status role="status" aria-live="polite"></p><section class="hrv-edit-preview" data-hrv-edit-preview hidden><h3>重算预览 · 尚未保存</h3><p>核对当前窗口与所选短段的原值、复核值及排除范围后确认保存；取消保留已保存文档。</p><button type="button" class="button primary" data-hrv-edit-action="apply">确认保存区间修订</button><button type="button" class="button secondary" data-hrv-edit-action="cancel">取消预览</button></section><div class="hrv-edit-window-summary" data-hrv-edit-summary></div><div class="hrv-edit-layout"><div><div class="hrv-edit-table-scroll" tabindex="0" role="region" aria-label="五分钟固定分段表，可横向和纵向滚动"><table><thead><tr><th scope="col">段</th><th scope="col">实际范围</th><th scope="col">NN 原 / 复核</th><th scope="col">SDNN ms 原 / 复核</th><th scope="col">计算可用性</th><th scope="col">排除覆盖</th></tr></thead><tbody data-hrv-edit-blocks></tbody></table></div><form class="hrv-edit-range" data-hrv-edit-range><h3>排除区间</h3><p>记录后的半开区间 [起点, 终点)；重叠范围按并集剔除。恢复一条记录后，其他重叠排除仍保留。</p><div class="hrv-edit-range-fields"><label>起点（秒）<input data-hrv-edit-start type="number" step="0.005" required></label><label>终点（秒）<input data-hrv-edit-end type="number" step="0.005" required></label></div><label>原因<input data-hrv-edit-reason maxlength="500" required placeholder="说明此区间为何不纳入 HRV"></label><button type="submit" class="button secondary" data-hrv-edit-action="exclude">预览剔除此区间</button></form><div class="hrv-edit-exclusions" data-hrv-edit-exclusions></div></div><section class="hrv-edit-detail"><nav class="hrv-edit-domain" aria-label="五分钟时域或频域"><button type="button" class="button secondary" data-hrv-edit-action="time" aria-pressed="true">时域</button><button type="button" class="button secondary" data-hrv-edit-action="frequency" aria-pressed="false">频域</button></nav><div data-hrv-edit-detail></div><button type="button" class="button secondary" data-hrv-edit-action="locate">查看所选段原始波形</button><div class="hrv-edit-wave" data-hrv-edit-wave></div></section></div><section class="hrv-edit-confirmation"><h3>医生复核声明</h3><p data-hrv-edit-confirmation>当前窗口待复核。</p><label><input type="checkbox" data-hrv-edit-ack>我已核对当前窗口的 NN 候选、节律及伪差；此确认是当前窗口的复核声明，不是临床认证或输入节律金标准。</label><label>当前窗口备注<textarea data-hrv-edit-note maxlength="1200" rows="2"></textarea></label><button type="button" class="button primary" data-hrv-edit-action="confirm">确认当前窗口复核</button></section><details class="hrv-edit-method"><summary>计算口径与范围</summary><p>原值为当前保存心搏及 NN 依据下、未做 HRV 区间排除的严格计算值；不使用源报告或 raw HRV 作为编辑前值。时域总体保留全部符合既有规则的 NN，不仅限于合格短段。排除后保留原邻接关系，差分及谱不跨剔除缺口。单短段的 SDANN 不可估计，显示 —。</p><p>当前模式为固定五分钟网格，未实现医院每小时代表段选择。FFT 使用 4 Hz 线性插值、1024 点对称 Hann 窗；VLF 仅探索性估计。pNN50 使用严格大于 50 ms、有效连续差分数作分母，单位为百分比；LF/HF 沿用频带值先四位小数量化再相除。— 表示不可用；0 是实际统计零值。</p></details>`;
    const q=s=>host.querySelector(s), els={heading:q('[data-hrv-edit-heading]'),status:q('[data-hrv-edit-status]'),preview:q('[data-hrv-edit-preview]'),summary:q('[data-hrv-edit-summary]'),blocks:q('[data-hrv-edit-blocks]'),detail:q('[data-hrv-edit-detail]'),exclusions:q('[data-hrv-edit-exclusions]'),wave:q('[data-hrv-edit-wave]'),confirmation:q('[data-hrv-edit-confirmation]'),start:q('[data-hrv-edit-start]'),end:q('[data-hrv-edit-end]'),reason:q('[data-hrv-edit-reason]'),ack:q('[data-hrv-edit-ack]'),note:q('[data-hrv-edit-note]')};
    function active(){return !disposed&&host._hrvEditorOwner===mountOwner&&host.isConnected&&isCurrent();}
    function invalidate(){if(disposed||host._hrvEditorOwner!==mountOwner)return;error='当前病例或计算依据已变化，请重新读取 HRV。';els.status.textContent=error;els.summary.innerHTML='';els.blocks.innerHTML='<tr><td colspan="6">旧分段统计已停止显示。</td></tr>';els.detail.innerHTML='';els.wave.textContent='旧波形定位已停止。';host.querySelectorAll('button,input,textarea').forEach(el=>el.disabled=true);}
    function requireActive(){if(!active()){invalidate();throw Error('HRV 病例或计算依据已变化');}}
    function owner(){return {epoch,scope:model?copy(model.scope):null,revision:model?.hrv_revision};}
    function owned(o){return active()&&o.epoch===epoch&&(!o.scope||sameScope(o.scope,model?.scope))&&o.revision===model?.hrv_revision;}
    const shown=()=>evidenceOf(preview,true)||evidenceOf(model);
    const stale=()=>!!model?.document_stale&&!preview;
    function bookmarkKey(){return model?JSON.stringify([...SOURCE.map(k=>model.scope[k]),windowIndex]):null;}
    function remember(){const key=bookmarkKey();if(!key||!active())return;bookmarks.delete(key);bookmarks.set(key,{selected,domain,scrollTop:q('.hrv-edit-table-scroll')?.scrollTop||0});while(bookmarks.size>16)bookmarks.delete(bookmarks.keys().next().value);}
    function pending(){return busy||!!preview||rangeDirty||!!els.ack.checked||!!els.note.value.trim();}
    function controls(){
      if(host._hrvEditorOwner!==mountOwner)return;
      host.setAttribute('aria-busy',String(busy));
      host.querySelectorAll('[data-hrv-edit-action]').forEach(b=>{const action=b.dataset.hrvEditAction;let disabled=busy||!active();if(!['reload','time','frequency','locate'].includes(action))disabled ||= !writable||!model||failed;if(['undo','redo','reset','exclude','confirm'].includes(action))disabled ||= !!preview;if(action==='undo')disabled ||= !model?.can_undo;if(action==='redo')disabled ||= !model?.can_redo;if(action==='apply'||action==='cancel')disabled ||= !preview;if(action==='confirm')disabled ||= model?.document_stale||!els.ack.checked||!shown()?.reviewed;if(action==='locate')disabled ||= !selected||typeof onLocate!=='function';b.disabled=disabled;if(action==='time'||action==='frequency')b.setAttribute('aria-pressed',String(action===domain));});
      host.querySelectorAll('[data-hrv-edit-restore]').forEach(b=>b.disabled=busy||!!preview||!writable||failed||!active());
      for(const el of [els.start,els.end,els.reason,els.ack,els.note])el.disabled=busy||!writable||!!preview||!model||failed||!active();
      els.preview.hidden=!preview;try{onPendingChange(pending()||failed);}catch{}
      els.status.textContent=error||(busy?'正在读取或核对当前依据…':preview?'正在显示未保存的重算预览。':model?.document_stale?'来源或心搏依据已变化；历史排除区间未应用，请核对后重新预览保存或重置。':model?`已保存 HRV 区间修订 r${model.hrv_revision} · ${writable?'可复核编辑':'当前只读'}`:'等待当前 HRV 依据。');
    }
    function renderDetail(){
      const block=shown()?.blocks?.find(b=>b.id===selected),right=stale()?null:block?.reviewed;
      if(!block){els.detail.innerHTML='<p>选择一个实际短段查看证据。</p>';return;}
      const columns=domain==='frequency'?frequency:metrics;
      const left=domain==='frequency'?block.baseline?.frequency:block.baseline,r=domain==='frequency'?right?.frequency:right;
      let plots='';
      if(domain==='frequency'&&globalThis.ECGHrvReview?.plot){plots=`<div class="hrv-edit-plots">${[['原值',block.baseline],['复核值',right]].map(([label,row])=>`<figure><figcaption>${label} · 同一短段功率谱</figcaption>${ECGHrvReview.plot(row?.psd||[],'hz','power',{width:300,title:label+'短段功率谱，Hz / ms²/Hz',empty:availability(row)})}</figure>`).join('')}</div>`;}
      els.detail.innerHTML=`<h3>所选段 · 记录后 ${time(block.start_s)}–${time(block.end_s)}</h3><p>实际 ${n(block.duration_s)} 秒${block.complete?'':'，不足五分钟'} · ${esc(availability(right))} · 信号质量未知</p>${compare(left,r,columns)}${plots}<p>单段原 NN ${n(block.baseline?.nn_count)} / 复核 NN ${n(right?.nn_count)}；未自动证实窦性来源。</p>`;
    }
    function select(idValue,{fill=true,locate=false}={}){
      requireActive();const block=shown()?.blocks?.find(b=>b.id===idValue);if(!block)return false;if(fill&&rangeDirty&&!preview&&selected!==idValue){if(typeof globalThis.confirm!=='function'||!globalThis.confirm('有尚未预览的自定义排除范围。取消此范围并查看另一段？'))return false;els.reason.value='';}selected=idValue;
      els.blocks.querySelectorAll('[data-hrv-edit-block]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.hrvEditBlock===selected)));
      if(fill&&!preview){els.start.value=String(block.start_sample/200);els.end.value=String(block.end_sample/200);rangeDirty=false;}
      renderDetail();controls();remember();if(locate)return locateSelected();return true;
    }
    function render(){
      const evidence=shown(),coverage=evidence?.coverage||{},original=evidence?.baseline?.periods?.full,reviewed=stale()?null:evidence?.reviewed?.periods?.full;
      els.heading.textContent=`第 ${windowIndex+1} 个 24 小时窗口 · 记录后 ${time(coverage.window_start_s)}–${time(coverage.window_end_s)} · 全记录至 ${time(coverage.record_end_s)}`;
      els.summary.innerHTML=`<h3>当前窗口对照${preview?' · 重算预览':''}</h3><p>原值与复核值使用同一当前心搏/NN 依据；排除覆盖 ${n(stale()?null:coverage.excluded_s)} 秒，保留范围 ${n(stale()?null:coverage.retained_s)} 秒。范围覆盖不表示信号质量已合格。</p>${compare(original,reviewed,[metrics[0],metrics[1],metrics[2],metrics[3],metrics[4]])}`;
      const scroll=q('.hrv-edit-table-scroll'),oldScroll=scroll?.scrollTop||0;
      els.blocks.innerHTML=blockTable(evidence,{pending:!!preview,stale:stale()});if(scroll)scroll.scrollTop=oldScroll;
      const document=preview?.after||model?.document,entries=document?.exclusions||[];
      els.exclusions.innerHTML=`<h3>${preview?'预览':'已保存'}排除记录 · ${entries.length}</h3>${entries.length?'<ul>'+entries.map(e=>`<li><span>记录后 ${time(e.start_sample/200)}–${time(e.end_sample/200)} · ${esc(e.reason)}</span><button type="button" class="button secondary" data-hrv-edit-restore="${esc(e.id)}" ${preview||busy||!writable?'disabled':''}>预览恢复</button></li>`).join('')+'</ul>':'<p>没有 HRV 区间排除。</p>'}`;
      const c=model?.confirmation;els.confirmation.textContent=preview?'预览尚未保存，当前预览没有医生确认。':c?.valid?`当前窗口复核声明已保存${c.updated_at?' · '+c.updated_at:''}；不覆盖其他窗口。`:'当前窗口待复核；浏览和重算成功不会自动确认。';
      if(!evidence?.blocks?.some(b=>b.id===selected))selected=evidence?.blocks?.[0]?.id||null;
      if(selected)select(selected,{fill:!preview});else renderDetail();controls();
    }
    function wireDoc(){return copy(model.document);}
    async function reload(){
      requireActive();if(busy)return;if(preview||rangeDirty||els.ack.checked||els.note.value.trim()){if(typeof globalThis.confirm!=='function'||!globalThis.confirm('HRV 有尚未保存的区间修改。取消这些修改并重新读取？'))return;await discard();}const requestEpoch=++epoch;busy=true;error='';controls();
      try{const params=new URLSearchParams({window:String(windowIndex)});for(const k of SCOPE)if(basis[k]!==undefined&&k!=='case_id')params.set(k,String(basis[k]));const result=await api(base+'?'+params.toString());if(!active()||requestEpoch!==epoch)return;validateScope(result.scope,id);if(!Number.isSafeInteger(result.hrv_revision)||result.hrv_revision<0||typeof result.digest!=='string'||!result.document)throw Error('HRV 文档与版本信息不完整');if(!givenScope(result.scope,basis))throw Error('HRV 读取结果与当前页面依据不一致，请重新载入页面');if(result.window_index!==windowIndex)throw Error('HRV 窗口已变化，请重新读取');model=copy(result);preview=null;failed=false;els.ack.checked=false;els.note.value='';const mark=bookmarks.get(bookmarkKey());selected=mark?.selected||selected;domain=mark?.domain||domain;render();if(mark&&q('.hrv-edit-table-scroll'))q('.hrv-edit-table-scroll').scrollTop=mark.scrollTop;
      }catch(e){if(active()&&requestEpoch===epoch){failed=true;error='HRV 读取失败：'+e.message;}}
      finally{if(active()&&requestEpoch===epoch){busy=false;controls();}}
    }
    async function makePreview(operation,document=null){
      requireActive();if(busy||preview||!model||!writable||failed)return;const o=owner();busy=true;error='';controls();
      try{const payload={scope:o.scope,expected_hrv_revision:o.revision,operation,window:windowIndex};if(document)payload.document=document;const result=await api(base+'/preview',{method:'POST',body:JSON.stringify(payload)});if(!owned(o))return;validateScope(result.scope,id);if(!sameScope(result.scope,o.scope)||result.expected_hrv_revision!==o.revision||result.window_index!==windowIndex)throw Error('HRV 预览依据不一致，请重新读取');if(!result.preview_token||!result.preview_digest||!result.after)throw Error('HRV 预览凭证不完整');preview=copy(result);els.ack.checked=false;render();
      }catch(e){if(owned(o))error='HRV 重算预览失败：'+e.message;}
      finally{if(owned(o)){busy=false;controls();}}
    }
    async function addExclusion(start=els.start.value,end=els.end.value,reason=els.reason.value){
      requireActive();if(!model||busy||preview||!writable||failed)return;try{const limit=Math.round((evidenceOf(model)?.coverage?.record_end_s??0)*200),entry=rangeInput(start,end,reason,limit),document=wireDoc();entry.id='x-'+entry.start_sample+'-'+entry.end_sample+'-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,7);document.exclusions.push(entry);return await makePreview('replace',document);}catch(e){error=e.message;controls();}
    }
    async function restore(idValue){requireActive();if(busy||preview||!model||!writable||failed)return;const document=wireDoc(),old=document.exclusions.length;document.exclusions=document.exclusions.filter(e=>e.id!==idValue);if(old===document.exclusions.length)return;return makePreview('replace',document);}
    async function cancel(){
      requireActive();if(busy||!preview)return;const old=preview,o=owner();preview=null;rangeDirty=false;els.reason.value='';error='';render();
      if(!cancelPreview)return;busy=true;controls();try{await api(base+'/cancel',{method:'POST',body:JSON.stringify({scope:o.scope,expected_hrv_revision:o.revision,preview_token:old.preview_token,window:windowIndex})});if(!owned(o))return;error='预览已取消，已保存区间和确认状态保持原样。';}catch(e){if(owned(o))error='本地预览已取消、文档未更改；服务器凭证取消未完成：'+e.message;}finally{if(owned(o)){busy=false;controls();}}
    }
    async function discard(){requireActive();if(busy)throw Error('HRV 正在读取或保存，请等待完成');if(preview)await cancel();rangeDirty=false;els.reason.value='';els.ack.checked=false;els.note.value='';if(active()&&selected)select(selected);controls();}
    async function saveResult(result,o,evidence){
      if(!owned(o))return;validateScope(result.scope,id);if(!Number.isSafeInteger(result.hrv_revision)||result.hrv_revision<o.revision||typeof result.digest!=='string'||!result.document)throw Error('HRV 保存返回的版本信息不完整');if(!sameSource(result.scope,o.scope)||result.scope.analysis_revision<o.scope.analysis_revision)throw Error('HRV 保存返回的来源依据不一致，请重新读取');model=copy({...result,evidence:result.evidence||evidence});basis=copy(result.scope);preview=null;failed=false;els.ack.checked=false;els.note.value='';busy=false;render();remember();
      try{await onSaved(result,{windowIndex,selectedBlockId:selected,domain});}catch(e){if(active()){failed=true;error='HRV 修订已保存，页面更新尚未完成，请重新读取：'+e.message;controls();}}
    }
    async function apply(){
      requireActive();if(busy||!preview||!model||!writable)return;const o=owner(),draft=preview;busy=true;error='';controls();
      try{const result=await api(base,{method:'PUT',body:JSON.stringify({scope:o.scope,expected_hrv_revision:o.revision,preview_token:draft.preview_token,preview_digest:draft.preview_digest,confirmed:true,window:windowIndex})});if(!owned(o))return;await saveResult(result,o,evidenceOf(draft,true));}
      catch(e){if(owned(o))error='HRV 区间修订未确认保存：'+e.message;}
      finally{if(active()){busy=false;controls();}}
    }
    async function confirm(){
      requireActive();if(busy||preview||!model||!writable||failed||model.document_stale||!els.ack.checked||!shown()?.reviewed)return;const o=owner();busy=true;error='';controls();
      try{const result=await api(base+'/confirm',{method:'POST',body:JSON.stringify({scope:o.scope,expected_hrv_revision:o.revision,expected_document_digest:model.digest,confirmed:true,nn_rhythm_artifact_reviewed:true,note:els.note.value,window:windowIndex})});if(!owned(o))return;await saveResult(result,o,evidenceOf(model));}
      catch(e){if(owned(o))error='当前窗口复核声明未保存：'+e.message;}
      finally{if(active()){busy=false;controls();}}
    }
    async function locateSelected(){
      requireActive();const block=shown()?.blocks?.find(b=>b.id===selected);if(!block||typeof onLocate!=='function')return;const o=owner(),token=++waveEpoch;els.wave.textContent='正在定位所选实际区间的原始波形…';const current=()=>owned(o)&&token===waveEpoch&&selected===block.id;
      try{await onLocate(copy(block),{scope:copy(o.scope),windowIndex,host:els.wave,isCurrent:current});if(!current())return;if(els.wave.textContent==='正在定位所选实际区间的原始波形…')els.wave.textContent='已定位原始波形；返回后保留当前短段。';}catch(e){if(current())els.wave.textContent='原始波形定位失败，请重试：'+e.message;}
    }
    host.addEventListener('click',event=>{const block=event.target.closest?.('[data-hrv-edit-block]'),restoreButton=event.target.closest?.('[data-hrv-edit-restore]'),button=event.target.closest?.('[data-hrv-edit-action]');if(block){event.preventDefault();try{select(block.dataset.hrvEditBlock,{locate:true});}catch{}return;}if(restoreButton){event.preventDefault();if(!restoreButton.disabled)restore(restoreButton.dataset.hrvEditRestore).catch(e=>{if(active()){error=e.message;controls();}});return;}if(!button||button.disabled)return;const action=button.dataset.hrvEditAction;if(action==='exclude')return;event.preventDefault();if(action==='time'||action==='frequency'){try{requireActive();domain=action;renderDetail();controls();remember();}catch{}return;}const task=action==='reload'?reload:action==='apply'?apply:action==='cancel'?cancel:action==='confirm'?confirm:action==='locate'?locateSelected:()=>makePreview(action);Promise.resolve().then(task).catch(e=>{if(active()){error=e.message;controls();}});});
    q('[data-hrv-edit-range]').addEventListener('input',()=>{if(active()&&!busy&&!preview){rangeDirty=true;controls();}});
    q('[data-hrv-edit-range]').addEventListener('submit',event=>{event.preventDefault();addExclusion().catch(e=>{if(active()){error=e.message;controls();}});});els.ack.addEventListener('change',controls);els.note.addEventListener('input',controls);
    els.blocks.addEventListener('keydown',event=>{const block=event.target.closest?.('[data-hrv-edit-block]');if(!block||!['ArrowUp','ArrowDown'].includes(event.key))return;event.preventDefault();const blocks=shown()?.blocks||[],i=blocks.findIndex(b=>b.id===block.dataset.hrvEditBlock),next=blocks[Math.max(0,Math.min(blocks.length-1,i+(event.key==='ArrowDown'?1:-1)))];if(next){try{select(next.id);els.blocks.querySelector(`[data-hrv-edit-block="${next.id}"]`)?.focus();}catch{}}});
    q('.hrv-edit-table-scroll')?.addEventListener('scroll',remember,{passive:true});controls();const ready=reload();
    const controller={ready,reload,select,preview:makePreview,addExclusion,restore,apply,cancel,confirm,locate:locateSelected,setDomain(value){if(!['time','frequency'].includes(value))return;requireActive();domain=value;renderDetail();controls();remember();},current:()=>selected,domain:()=>domain,state:()=>copy({model,preview,busy,failed,error,rangeDirty}),active,pending,pendingDetails:()=>({busy,preview:!!preview,rangeDirty,statementDirty:!!els.ack.checked||!!els.note.value.trim()}),discard,destroy(){disposed=true;++epoch;++waveEpoch;editors.delete(controller);}};editors.add(controller);return controller;
  }
  function allowLeave(){const pending=[...editors].filter(c=>c.active()&&c.pending());if(!pending.length)return true;if(pending.some(c=>c.pendingDetails().busy)){if(typeof globalThis.toast==='function')globalThis.toast('HRV 正在读取或保存，请等待完成后再离开。','error');return false;}if(typeof globalThis.confirm!=='function'||!globalThis.confirm('HRV 有尚未保存的区间修改。取消这些修改并离开？'))return false;pending.forEach(c=>c.discard().catch(()=>{}));return true;}
  globalThis.addEventListener?.('beforeunload',event=>{if([...editors].some(c=>c.active()&&c.pending())){event.preventDefault();event.returnValue='';}});
  const pending=()=>[...editors].some(c=>c.active()&&c.pending());
  function assertApplied(){if(pending())throw Error('HRV 有未保存范围、预览或复核声明，请先保存或取消后继续报告操作');}
  return {mount,allowLeave,pending,assertApplied,validateScope,sameScope,sameSource,rangeInput,compare,blockTable,availability,format:n};
})();
if(typeof module!=='undefined'&&module.exports)module.exports=globalThis.ECGHRVEditor;
