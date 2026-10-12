"use strict";
/* Read-only range statistics. The calculator owns measurement and quality rules. */
globalThis.ECGSTTRangeReview = (() => {
  const LEADS = Object.freeze(['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6']);
  const PROFILE_ID = 'raw-200hz-fixed16s-st-perbeat-mean-v1';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const copy = value => JSON.parse(JSON.stringify(value));
  function number(value) {
    if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
    const rounded = Math.round(value * 1000) / 1000;
    return rounded === 0 && value !== 0 ? value.toPrecision(3) : String(rounded);
  }
  function ordered(value) {
    if (Array.isArray(value)) return value.map(ordered);
    if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(key => [key, ordered(value[key])]));
    return value;
  }
  function scopeMatches(left, right) {
    return !!left && !!right && typeof left === 'object' && typeof right === 'object'
      && !Array.isArray(left) && !Array.isArray(right)
      && JSON.stringify(ordered(left)) === JSON.stringify(ordered(right));
  }
  function validateBasis(value, id) {
    if (!value || typeof value !== 'object' || Array.isArray(value)
      || typeof value.analysis_basis !== 'string' || !value.analysis_basis.trim()
      || !Number.isSafeInteger(value.analysis_revision) || value.analysis_revision < 0
      || !Number.isSafeInteger(value.beat_revision) || value.beat_revision < 0
      || value.case_id !== id) throw Error('病例计算依据不完整，请重新读取。');
    const result = copy(value);
    if (!scopeMatches(value, result)) throw Error('病例计算依据包含不支持的值。');
    return result;
  }
  function validateRange(start, end, recordEndSample = Number.MAX_SAFE_INTEGER) {
    if (String(start ?? '').trim() === '' || String(end ?? '').trim() === '') throw Error('请填写范围起止时间。');
    const startSample = Number(start), endSample = Number(end);
    if (!Number.isSafeInteger(startSample) || !Number.isSafeInteger(endSample)) throw Error('起止样本必须为整数；每个样本为 5 ms。');
    if (startSample < 0 || endSample <= startSample || endSample > recordEndSample) throw Error('范围必须位于记录内，且起点早于终点。');
    if (endSample - startSample < 12000) throw Error('范围至少需要 60 秒。');
    return {start_sample: startSample, end_sample: endSample};
  }
  function sampleFromSeconds(value) {
    const text = String(value ?? '').trim();
    if (!text) throw Error('请填写范围起止时间。');
    const decimal = text.startsWith('.') ? '0'+text : text;
    const match = decimal.match(/^(\d+)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/);
    const seconds = Number(text);
    if (!match || !Number.isFinite(seconds) || !Number.isSafeInteger(Math.round(seconds*200))) throw Error('起止时间必须落在 5 ms 网格，不能自动取整。');
    // Decimal input is exact. A floating-point tolerance would silently snap
    // a pasted off-grid value such as 10.004999999999 to sample 2001.
    const fraction = (match[2] || '').replace(/0+$/, '');
    const coefficient = BigInt(match[1]+fraction);
    if (!coefficient) return 0;
    const power = Number(match[3] || 0)-fraction.length;
    if (!Number.isSafeInteger(power) || Math.abs(power)>64) throw Error('起止时间必须落在 5 ms 网格，不能自动取整。');
    const denominator = power<0 ? 10n**BigInt(-power) : 1n;
    const numerator = coefficient*200n*(power>0 ? 10n**BigInt(power) : 1n);
    if (numerator%denominator!==0n || numerator/denominator>BigInt(Number.MAX_SAFE_INTEGER)) throw Error('起止时间必须落在 5 ms 网格，不能自动取整。');
    return Number(numerator/denominator);
  }
  function validateSeconds(start, end, recordEndSample = Number.MAX_SAFE_INTEGER) {
    return validateRange(sampleFromSeconds(start),sampleFromSeconds(end),recordEndSample);
  }
  function elapsed(sample) {
    if (!Number.isSafeInteger(sample) || sample < 0) return '—';
    const seconds = Math.floor(sample / 200), ms = sample % 200 * 5;
    return `${Math.floor(seconds / 3600)}:${String(Math.floor(seconds % 3600 / 60)).padStart(2,'0')}:${String(seconds % 60).padStart(2,'0')}.${String(ms).padStart(3,'0')}`;
  }
  const count = value => Number.isSafeInteger(value) && value >= 0;
  function validateResult(result, request) {
    if (!result || result.schema_version !== 'stt-range-mean-v1' || !scopeMatches(request.scope, result.scope)) throw Error('返回的病例或计算依据不一致，已丢弃结果，请重新读取。');
    const range = result.range, method = result.method_profile;
    if (result.server_identity && !['case_id','analysis_basis','analysis_revision','beat_revision'].every(key => result.server_identity[key]===request.scope[key])) throw Error('返回的服务器计算依据不一致，已丢弃结果。');
    if (!range || range.start_sample !== request.start_sample || range.end_sample !== request.end_sample || range.half_open !== true
      || ![range.start_s,range.end_s,range.duration_s].every(Number.isFinite)
      || Math.abs(range.start_s-request.start_sample/200)>1e-7 || Math.abs(range.end_s-request.end_sample/200)>1e-7
      || Math.abs(range.duration_s-(request.end_sample-request.start_sample)/200)>1e-7) throw Error('返回的统计范围不一致，已丢弃结果。');
    if (!method || method.id !== PROFILE_ID || method.sample_rate_hz !== 200
      || method.measurement_ms !== request.measurement_ms || method.aggregate !== 'arithmetic_mean_of_used_per_beat_st_minus_baseline'
      || method.unit_label !== 'u' || method.calibration_verified !== false
      || JSON.stringify(method.baseline_offsets_samples)!=='[-40,-36,-32,-28,-24]'
      || JSON.stringify(method.st_window_offsets_samples)!=='[-2,-1,0,1,2]'
      || method.j_basis!=='fixed_16s_machine_estimate_after_explicit_masks') throw Error('返回的统计方法或单位不完整，已丢弃结果。');
    if (!result.counts || !['detected_count','used_count','excluded_count','missing_count'].every(key => count(result.counts[key]))
      || !result.coverage || result.coverage.coverage_is_signal_quality !== false) throw Error('返回的计数或覆盖信息不完整，已丢弃结果。');
    if (result.counts.detected_count !== result.counts.used_count+result.counts.excluded_count+result.counts.missing_count) throw Error('返回的有效、剔除与缺失计数不一致，已丢弃结果。');
    if (!Array.isArray(result.leads) || result.leads.length !== request.leads.length) throw Error('返回的导联不完整，已丢弃结果。');
    const names = result.leads.map(row => row?.lead);
    if (new Set(names).size !== names.length || request.leads.some(lead => !names.includes(lead))) throw Error('返回的导联不一致，已丢弃结果。');
    for (const row of result.leads) {
      if (!['used_count','excluded_count','missing_count'].every(key => count(row[key]))
        || !['used_count','excluded_count','missing_count'].every(key => row[key]===result.counts[key])
        || !(row.mean_units === null || typeof row.mean_units === 'number' && Number.isFinite(row.mean_units))
        || (row.used_count === 0) !== (row.mean_units === null)) throw Error('返回的导联均值或有效搏数无效，已丢弃结果。');
    }
    return copy(result);
  }
  const reasons = {
    non_n_candidate:'非 N 候选标签', adjacent_v_or_artifact:'相邻室性或伪差标签',
    rr_outside_legacy_bounds:'RR 超出现有范围', explicit_missing_interval:'已知缺失区间',
    explicit_anchor_exclusion:'已标记排除区间', source_edge_guard_unavailable:'原始边缘上下文不足',
    j_unavailable:'J 定位代表搏不足', explicit_missing_support:'测量窗口已知缺失',
    measurement_support_exclusion:'测量窗口与排除区间相交', engineering_quality_gate:'工程质量块未通过',
    non_normal_beat:'非正常搏标签', adjacent_ectopic:'相邻异位搏', adjacent_artifact:'相邻伪差',
    explicit_exclusion:'显式排除区间', excluded_rhythm:'排除节律区间', rhythm_exclusion:'排除节律区间',
    invalid_rr:'RR 不符合规则', invalid_boundary:'记录边界不足', insufficient_context:'测量上下文不足',
    insufficient_normal_beats:'正常搏不足', block_quality:'块质量未通过', low_quality:'质量未通过',
    non_finite_measurement:'测量缺失或非有限值', missing_samples:'原始采样缺失', low_j_confidence:'J 点置信度不足'
  };
  function reasonList(value) {
    const entries = value && typeof value === 'object' ? Object.entries(value).filter(([,n]) => count(n) && n > 0) : [];
    return entries.length ? entries.map(([key,n]) => `${esc(reasons[key] || key)}：${n}`).join('；') : '无已返回的原因计数';
  }
  function resultHTML(result) {
    const range = result.range;
    return `<p class="sttr-result-range">记录后 ${elapsed(range.start_sample)}–${elapsed(range.end_sample)} · ${number((range.end_sample-range.start_sample)/200)} 秒</p><div class="sttr-table-scroll"><table><thead><tr><th scope="col">导联</th><th scope="col">均值（u）</th><th scope="col">有效搏数</th></tr></thead><tbody>${result.leads.map(row => `<tr><th scope="row">${esc(row.lead)}</th><td data-sttr-mean="${esc(row.lead)}">${number(row.mean_units)}</td><td data-sttr-used="${esc(row.lead)}">${row.used_count}</td></tr>`).join('')}</tbody></table></div><p class="sttr-interpretation">均值不单独证明持续下移。— 表示没有可用均值；0 表示有效测量的零值。</p>`;
  }
  function detailsHTML(result) {
    const c = result.counts, coverage = result.coverage, m = result.method_profile;
    const fields = [['requested_duration_s','请求范围'],['source_coverage_s','实际记录覆盖'],['explicit_excluded_s','显式排除覆盖'],['explicit_missing_s','已知原始缺失'],['engineering_eligible_block_coverage_s','工程合格块覆盖'],['used_anchor_span_s','已用搏起止跨度'],['max_used_anchor_gap_s','已用搏最大间隔']];
    const flags = Array.isArray(result.mask_reason_counts) ? result.mask_reason_counts.filter(row => row && count(row.beat_count)) : [];
    const statuses = {pending:'待复核',confirmed:'已确认',excluded:'已排除'};
    const origins = {annotation:'医生标记',rhythm_annotation:'节律标记',rr_review:'RR 复核标记',hrv_review:'HRV 复核标记'};
    const flagHTML = flags.length ? `<div class="sttr-mask-reasons"><h4>具体标记理由</h4><ul>${flags.map(row => `<li>${row.kind==='missing'?'已知缺失':'排除标记'}：${esc(row.reason || '未提供理由')} · 涉及 ${row.beat_count} 搏${row.origin?' · '+esc(origins[row.origin] || row.origin):''}${row.review_status?' · 标记状态 '+esc(statuses[row.review_status] || row.review_status):''}</li>`).join('')}</ul><p>具体标记可能重叠，不能直接相加；有效、剔除、缺失及主原因按每个检测搏互斥计数。</p></div>` : '';
    const qualityNote = m.quality_note === 'existing engineering block gate; labels, machine landmarks and signal quality are not physician verified'
      ? '沿用工程块质量门槛；搏标签、机器定位和信号质量尚未获医生核对。' : m.quality_note || '';
    return `<summary>方法、剔除、缺失与覆盖</summary><div class="sttr-detail-content"><p>检测 ${c.detected_count} 搏 · 有效 ${c.used_count} 搏 · 剔除 ${c.excluded_count} 搏 · 缺失 ${c.missing_count} 搏</p><p>${reasonList(c.reason_counts)}</p>${flagHTML}<dl class="sttr-coverage">${fields.map(([key,label]) => `<div><dt>${label}</dt><dd>${number(coverage[key])} 秒</dd></div>`).join('')}<div><dt>工程合格块占比</dt><dd>${number(coverage.engineering_eligible_block_coverage_pct)} %</dd></div></dl><p>记录覆盖、合格块覆盖及搏起止跨度均不代表信号质量已获医生确认；搏起止跨度不表示全程连续可用。</p><dl class="sttr-method"><div><dt>统计</dt><dd>全部已用搏的 ST 相对每搏基线值之算术均值</dd></div><div><dt>测量点</dt><dd>${m.measurement_ms === 0 ? 'J 点' : 'J+'+m.measurement_ms+' ms'}</dd></div><div><dt>基线窗口</dt><dd>${esc((m.baseline_offsets_samples || []).map(v => Number.isFinite(v) ? v*5 : '—').join(' / '))} ms，相对 R 峰；窗口中位数作为稳定基线替代，须人工核对。</dd></div><div><dt>ST 窗口</dt><dd>${esc((m.st_window_offsets_samples || []).map(v => Number.isFinite(v) ? v*5 : '—').join(' / '))} ms，相对所选测量点；窗口中位数。</dd></div><div><dt>J 点依据</dt><dd>固定 16 秒块的机器估计；未表示医生已核对。${m.quality_gate?.landmark_confidence_is_gate===false?'J 点置信度不作为计算门槛。':''}</dd></div><div><dt>单位</dt><dd>u，设备原始单位，电压未校准，不能直接解释为临床 mV。</dd></div></dl><p>${esc(qualityNote)}</p><div class="sttr-lead-reasons">${result.leads.map(row => `<p><strong>${esc(row.lead)}</strong>：剔除 ${row.excluded_count} / 缺失 ${row.missing_count}；${reasonList(row.reason_counts)}</p>`).join('')}</div></div>`;
  }
  function mount(host, options = {}) {
    if (!host || typeof host.querySelector !== 'function') throw Error('缺少 ST 范围统计容器。');
    host._sttRangeController?.destroy();
    const {id, api, calculate: calculator, isCurrent = () => host.isConnected, onReviewed, onLocate} = options;
    if (typeof id !== 'string' || !id.trim()) throw Error('缺少当前病例标识。');
    if (typeof calculator !== 'function' && typeof api !== 'function') throw Error('缺少范围统计计算器。');
    let basis = validateBasis(options.basis, id);
    const recordEndSample = options.recordEndSample ?? Number.MAX_SAFE_INTEGER;
    if (!Number.isSafeInteger(recordEndSample) || recordEndSample < 0) throw Error('记录结束样本无效。');
    const initial = options.initialRange || {start_sample:0,end_sample:Math.min(recordEndSample,12000)};
    const selected = options.initialLeads || ['II','V1','V5'];
    if (!Array.isArray(selected) || !selected.length || new Set(selected).size !== selected.length || selected.some(lead => !LEADS.includes(lead))) throw Error('初始导联无效。');
    const measurementMs = options.measurementMs ?? 60;
    if (![0,60,80].includes(measurementMs)) throw Error('测量点仅支持 J、J+60 或 J+80 ms。');
    const mountOwner = {}, base = `/api/cases/${encodeURIComponent(id)}/stt-range`;
    let epoch = 0, disposed = false, stale = false, busy = false, callbackBusy = false, abort = null, result = null, resultRequest = null, handedOff = false, message = '选择范围后计算。';
    host._sttRangeOwner = mountOwner;
    host.classList.add('sttr-review');
    host.innerHTML = `<header class="sttr-heading"><h3>范围 ST 均值</h3><p>至少 60 秒；全部有效搏相对基线的 ST 算术均值。</p></header><form data-sttr-form><div class="sttr-range-controls"><label>起点（记录后秒）<input data-sttr-start type="number" min="0" step="0.005" inputmode="decimal" value="${esc(Number.isSafeInteger(initial.start_sample)?initial.start_sample/200:'')}"></label><label>终点（记录后秒，不含）<input data-sttr-end type="number" min="60" step="0.005" inputmode="decimal" value="${esc(Number.isSafeInteger(initial.end_sample)?initial.end_sample/200:'')}"></label><label>测量点<select data-sttr-measurement>${[0,60,80].map(ms => `<option value="${ms}"${measurementMs===ms?' selected':''}>${ms===0?'J 点':'J+'+ms+' ms'}</option>`).join('')}</select></label><div class="sttr-calculation-actions"><button type="submit" data-sttr-action="calculate">计算均值</button><button type="button" data-sttr-action="cancel" hidden>取消</button><button type="button" data-sttr-action="retry" hidden>重试</button></div></div><p class="sttr-range-time" data-sttr-range-time></p><fieldset class="sttr-leads"><legend>导联</legend>${LEADS.map(lead => `<label><input type="checkbox" data-sttr-lead value="${lead}"${selected.includes(lead)?' checked':''}>${lead}</label>`).join('')}</fieldset></form><p class="sttr-status" data-sttr-status role="status" aria-live="polite"></p><div data-sttr-results></div><details data-sttr-details hidden></details><div class="sttr-result-actions"><button type="button" data-sttr-action="locate"${typeof onLocate==='function'?'':' hidden'}>定位所选范围</button><button type="button" data-sttr-action="review"${typeof onReviewed==='function'?'':' hidden'}>填入复核备注</button></div>`;
    const q = selector => host.querySelector(selector);
    const els = {start:q('[data-sttr-start]'),end:q('[data-sttr-end]'),measurement:q('[data-sttr-measurement]'),status:q('[data-sttr-status]'),results:q('[data-sttr-results]'),details:q('[data-sttr-details]'),time:q('[data-sttr-range-time]')};
    function active() {
      if (disposed || stale || host._sttRangeOwner !== mountOwner || !host.isConnected) return false;
      try { return isCurrent() === true; } catch (_) { return false; }
    }
    function clearResult() { result = null; resultRequest = null; handedOff = false; els.results.innerHTML = ''; els.details.innerHTML = ''; els.details.hidden = true; }
    function controls() {
      if (disposed || host._sttRangeOwner !== mountOwner) return;
      const current = active(); host.setAttribute('aria-busy', String(busy)); els.status.textContent = message;
      q('[data-sttr-action="calculate"]').disabled = !current || busy;
      q('[data-sttr-action="cancel"]').hidden = !busy;
      q('[data-sttr-action="cancel"]').disabled = !current;
      q('[data-sttr-action="retry"]').disabled = !current || busy;
      q('[data-sttr-action="locate"]').disabled = !current || busy || callbackBusy || !result;
      q('[data-sttr-action="review"]').disabled = !current || busy || callbackBusy || !result || handedOff;
      host.querySelectorAll('input,select').forEach(el => el.disabled = !current);
      let a=null,b=null;
      try {a=sampleFromSeconds(els.start.value);b=sampleFromSeconds(els.end.value);} catch (_) {}
      els.time.textContent = `${elapsed(a)}–${elapsed(b)} · ${Number.isSafeInteger(a)&&Number.isSafeInteger(b)&&b>a?number((b-a)/200):'—'} 秒`;
    }
    function stopRequest() { ++epoch; abort?.abort(); abort = null; busy = false; callbackBusy = false; }
    function invalidate(reason = '当前病例或计算依据已变化，请重新读取。') {
      if (disposed || host._sttRangeOwner !== mountOwner) return;
      stopRequest(); stale = true; clearResult(); message = reason; controls();
    }
    function requireCurrent() { if (!active()) { invalidate(); return false; } return true; }
    function requestOfForm() {
      const range = validateSeconds(els.start.value, els.end.value, recordEndSample);
      const leads = [...host.querySelectorAll('input[data-sttr-lead]:checked')].map(el => el.value);
      if (!leads.length || new Set(leads).size !== leads.length || leads.some(lead => !LEADS.includes(lead))) throw Error('请选择至少一个有效导联。');
      const measurement = Number(els.measurement.value);
      if (![0,60,80].includes(measurement)) throw Error('测量点仅支持 J、J+60 或 J+80 ms。');
      return {scope:copy(basis),...range,leads,measurement_ms:measurement};
    }
    function edited() {
      if (!requireCurrent()) return;
      stopRequest(); clearResult(); message = '参数已变化，请重新计算。'; q('[data-sttr-action="retry"]').hidden = true; controls();
    }
    async function calculate() {
      if (!requireCurrent()) return null;
      let request;
      try { request = requestOfForm(); } catch (error) { stopRequest(); clearResult(); message = error.message; controls(); return null; }
      stopRequest(); clearResult(); const token = epoch, requestKey = JSON.stringify(ordered(request));
      const controller = new AbortController(); abort = controller; busy = true; message = '正在计算当前范围的均值…'; q('[data-sttr-action="retry"]').hidden = true; controls();
      try {
        const value = typeof calculator === 'function'
          ? await calculator(copy(request), {signal:controller.signal})
          : await api(base, {method:'POST',body:JSON.stringify(request),signal:controller.signal});
        if (disposed || host._sttRangeOwner !== mountOwner || token !== epoch) return null;
        if (!requireCurrent()) return null;
        if (requestKey !== JSON.stringify(ordered(requestOfForm()))) { edited(); return null; }
        result = validateResult(value, request); resultRequest = copy(request);
        els.results.innerHTML = resultHTML(result); els.details.innerHTML = detailsHTML(result); els.details.hidden = false;
        message = '范围均值已计算。'; return copy(result);
      } catch (error) {
        if (!disposed && host._sttRangeOwner === mountOwner && token === epoch) {
          if (!requireCurrent()) return null;
          clearResult(); message = '未取得当前范围结果：' + (error?.message || String(error)); q('[data-sttr-action="retry"]').hidden = false;
        }
        return null;
      } finally {
        if (!disposed && host._sttRangeOwner === mountOwner && token === epoch) { abort = null; busy = false; controls(); }
      }
    }
    function cancel() { if (!requireCurrent()) return; stopRequest(); clearResult(); message = '计算已取消，可重试当前参数。'; q('[data-sttr-action="retry"]').hidden = false; controls(); }
    async function callback(action) {
      if (!requireCurrent() || busy || callbackBusy || !result || action==='review'&&handedOff) return;
      const fn = action==='review'?onReviewed:onLocate;
      if (typeof fn !== 'function') return;
      const token = epoch, snapshot = copy(result), request = copy(resultRequest);
      const current = () => active() && token===epoch && resultRequest && scopeMatches(resultRequest,request);
      callbackBusy=true; message=action==='review'?'正在填入复核备注…':'正在定位所选范围…'; controls();
      try {
        if (action==='review') await fn(snapshot,{request,isCurrent:current});
        else await fn(copy(snapshot.range),{request,result:snapshot,isCurrent:current});
        if (!current()) return;
        if (action==='review') handedOff = true;
        message = action==='review'?'统计已填入复核备注，待医生核对保存。':'已定位所选范围。'; controls();
      } catch (error) { if (current()) { message = (action==='review'?'复核备注填写':'范围定位')+'未完成：'+(error?.message || String(error)); controls(); } }
      finally { if (current()) {callbackBusy=false; controls();} }
    }
    const input = event => { if (event.target.matches('input,select')) edited(); };
    const submit = event => { event.preventDefault(); calculate(); };
    const click = event => {
      const button = event.target.closest?.('[data-sttr-action]');
      if (!button || !host.contains(button) || button.disabled) return;
      const action = button.dataset.sttrAction;
      if (action==='calculate') return;
      event.preventDefault();
      if (action==='cancel') cancel(); else if (action==='retry') calculate(); else callback(action);
    };
    host.addEventListener('input',input); host.addEventListener('change',input); q('[data-sttr-form]').addEventListener('submit',submit); host.addEventListener('click',click);
    const controller = {
      calculate,cancel,retry:calculate,invalidate,
      setRange(range) { if (!requireCurrent()) return; els.start.value=Number.isSafeInteger(range.start_sample)?String(range.start_sample/200):''; els.end.value=Number.isSafeInteger(range.end_sample)?String(range.end_sample/200):''; if (range.measurement_ms!==undefined) els.measurement.value=String(range.measurement_ms); if (range.leads) host.querySelectorAll('[data-sttr-lead]').forEach(el=>el.checked=range.leads.includes(el.value)); edited(); },
      setBasis(next) { if (disposed || host._sttRangeOwner!==mountOwner) return; const updated=validateBasis(next,id); stopRequest(); basis=updated; stale=false; clearResult(); message='计算依据已更新，请重新计算。'; controls(); },
      state() { if (!disposed && host._sttRangeOwner===mountOwner && !active()) invalidate(); return copy({id,basis,busy,stale,result,request:resultRequest,handedOff,message,disposed}); },
      destroy() { if (disposed) return; stopRequest(); disposed=true; host.removeEventListener('input',input); host.removeEventListener('change',input); host.removeEventListener('click',click); q('[data-sttr-form]')?.removeEventListener('submit',submit); if (host._sttRangeOwner===mountOwner) {clearResult(); host.querySelectorAll('button,input,select').forEach(el=>el.disabled=true); host.removeAttribute('aria-busy'); delete host._sttRangeOwner; delete host._sttRangeController;} }
    };
    host._sttRangeController=controller; controls(); return controller;
  }
  return {mount,validateRange,validateSeconds,scopeMatches,LEADS};
})();
if (typeof module!=='undefined' && module.exports) module.exports=globalThis.ECGSTTRangeReview;
