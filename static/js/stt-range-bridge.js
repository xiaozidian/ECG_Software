"use strict";
/* Range evidence is independent of the ten-second manual waveform window. */
globalThis.ECGSTTRangeBridge = (() => {
  const copy = value => JSON.parse(JSON.stringify(value));
  const keys = ['case_id','analysis_basis','analysis_revision','beat_revision'];
  const MACHINE_PREFIX='范围 ST 均值（机器逐搏统计、16秒块 J）：';
  function ordered(value) {
    if (Array.isArray(value)) return value.map(ordered);
    if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(k => [k,ordered(value[k])]));
    return value;
  }
  const equal = (a,b) => JSON.stringify(ordered(a)) === JSON.stringify(ordered(b));
  const integer = value => Number.isSafeInteger(value) && value >= 0;
  const number = value => value === null ? '—' : Number.isFinite(value) ? String(Number(value.toFixed(3))) : '—';
  function time(sample) {
    const ms = sample % 200*5, seconds = Math.floor(sample/200);
    return `${Math.floor(seconds/3600)}:${String(Math.floor(seconds%3600/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}${ms?'.'+String(ms).padStart(3,'0'):''}`;
  }
  function identity(value, id) {
    if (!value || value.case_id!==id || typeof value.analysis_basis!=='string' || !value.analysis_basis.trim()
        || !integer(value.analysis_revision) || !integer(value.beat_revision)) return null;
    const result = Object.fromEntries(keys.map(k => [k,value[k]]));
    for (const k of ['source_digest','data_version']) if (typeof value[k]==='string' && value[k]) result[k]=value[k];
    return result;
  }
  function mount(options = {}) {
    const {state,api,onLocate,toast=()=>{}} = options;
    const host = typeof options.host==='string' ? document.querySelector(options.host) : options.host || document.querySelector('#sttRangeReview');
    if (!state || typeof state!=='object' || typeof api!=='function' || !host) throw Error('缺少范围统计接入上下文。');
    if (!globalThis.ECGSTTRangeReview?.mount) throw Error('范围统计组件尚未加载。');
    host._sttRangeBridge?.destroy();
    const note = host.ownerDocument.querySelector('#sttReviewNote');
    const point = host.ownerDocument.querySelector('#sttMeasurementPoint');
    if (!note) throw Error('缺少 ST-T 复核备注表单。');
    const owner = {}, tokenOf = options.getCaseToken || (()=>state.caseRequestId);
    const epochOf = options.getWorkspaceEpoch || (()=>state.workspaceEpoch);
    let disposed=false, component=null, mountedId=null, activeScope=null, sourceEnd=null, externalMethod=null;
    let pagePaused=false, pausedRequest=false;
    let accepted=null, generation=0, saveCandidate=null, ownFragment='', staleFragments=new Set();
    const issuedSnapshots=new WeakMap();
    host._sttRangeBridgeOwner=owner;
    function owned() {return !disposed && host._sttRangeBridgeOwner===owner && host.isConnected;}
    function live() {
      const id=state.caseId, data=state.caseData;
      if (!owned() || typeof id!=='string' || !id || !data || data.case_id!==id || state.caseLoading) throw Error('请先读取当前病例的 ST-T 依据。');
      const value=identity(state.sttReview?.server_identity || state.sttReview,id) || identity(state.sttRangeBasis,id);
      if (!value) throw Error('逐搏计算依据尚未就绪，请重新读取 ST-T。');
      // Never fill a missing beat revision with zero or confuse the edited
      // case-detail analysis_revision with the global clinical revision.
      const clinical=data.clinical_identity || (typeof data.analysis_basis==='string'?data:null);
      if (clinical && ['analysis_basis','analysis_revision'].some(k=>clinical[k]!==undefined && clinical[k]!==value[k])) throw Error('ST-T 计算依据已变化，请重新读取。');
      if (integer(data.review_workflow?.revision) && data.review_workflow.revision!==value.analysis_revision) throw Error('复核版本已变化，请重新读取 ST-T。');
      if (integer(data.beat_revision) && data.beat_revision!==value.beat_revision) throw Error('逐搏版本已变化，请重新读取 ST-T。');
      const token=tokenOf(), epoch=epochOf();
      if (!(integer(token) || typeof token==='string' && token) || typeof epoch!=='string') throw Error('病例或工作区上下文缺失，请重新读取。');
      const duration=Number(data.technical?.duration_seconds_raw), end=Math.round(duration*200);
      if (!Number.isFinite(duration) || duration<=0 || !integer(end) || Math.abs(duration*200-end)>1e-5) throw Error('记录时长尚未就绪。');
      return {id,scope:{...value,client_case_token:token,workspace_epoch:epoch},end};
    }
    function current(scope=activeScope) {
      try {return !!scope && equal(live().scope,scope);} catch (_) {return false;}
    }
    function inSTT() {return state.currentPage===undefined || state.currentPage==='stt';}
    function notify(message,type='error') {try {toast(message,type);} catch (_) {}}
    function clearAccepted(reason) {
      if (accepted && ownFragment && note.value.includes(ownFragment)) staleFragments.add(ownFragment);
      accepted=null; state.sttRangeReviewed=null;
      if (reason) host.dataset.sttRangeSnapshotState='stale';
    }
    function formSelection() {
      if (!component) return null;
      const start=host.querySelector('[data-sttr-start]')?.value, end=host.querySelector('[data-sttr-end]')?.value;
      const range=globalThis.ECGSTTRangeReview.validateSeconds(start,end,sourceEnd);
      return {...range,measurement_ms:Number(host.querySelector('[data-sttr-measurement]')?.value),
        leads:[...host.querySelectorAll('[data-sttr-lead]:checked')].map(x=>x.value)};
    }
    function defaultRange(end) {
      const desired=Math.round(Math.max(0,Number(state.sttStart)||0)*200);
      const start=Math.max(0,Math.min(desired,Math.max(0,end-12000)));
      return {start_sample:start,end_sample:Math.min(end,start+12000)};
    }
    function method() {
      const value=Number(point?.value ?? state.sttMeasurementMs ?? 60);
      return [0,60,80].includes(value) ? value : 60;
    }
    function compact(result) {const value=copy(result);delete value.blocks;return value;}
    function fragment(result) {
      const m=result.method_profile.measurement_ms, pointLabel=m===0?'J 点':`J+${m} ms`;
      const means=result.leads.map(row=>`${row.lead} ${number(row.mean_units)} u（n=${row.used_count}）`).join('；');
      return `${MACHINE_PREFIX}记录后 ${time(result.range.start_sample)}–${time(result.range.end_sample)}，${pointLabel}；${means}；有效 ${result.counts.used_count} / 剔除 ${result.counts.excluded_count} / 缺失 ${result.counts.missing_count} 搏。J 与基线替代待核对，u 未标定；均值不单独证明持续下移。`;
    }
    function assertResultCurrent(result, context) {
      if (!owned() || !inSTT() || !current() || context?.isCurrent?.()!==true || !equal(result?.scope,activeScope)) throw Error('当前范围统计已失效，请重新计算。');
      const liveResult=component.state();
      if (!liveResult.result || !equal(liveResult.result,result) || !equal(liveResult.request,context.request)) throw Error('所选范围或统计方法已变化，请重新计算。');
      const mathematicalContext=state.demoReadonly===true && globalThis.__CARDIOINSIGHT_MATHEMATICAL_CASE__?.integrity?.mathematical_fixture===true;
      const native=result.binding?.status==='caller_source_and_basis_bound' && !mathematicalContext
        && result.binding?.source_kind!=='pure_mathematical' && result.simulation?.browser_computed!==true;
      const math=mathematicalContext
        && result.binding?.status==='mathematical_raw_source_and_basis_bound' && result.binding?.source_kind==='pure_mathematical'
        && result.simulation?.browser_computed===true && result.simulation?.real_patient_inputs_read===false && result.simulation?.clinical_validation===false;
      const receiptKind=native?'native-stt-range-hmac-v1':math?'browser-math-content-digest-v1':null;
      if (!/^[a-f0-9]{64}$/.test(result.result_digest||'') || !receiptKind
          || typeof result.binding.source_digest!=='string' || !result.binding.source_digest
          || result.save_receipt?.kind!==receiptKind || !/^[a-f0-9]{64}$/.test(result.save_receipt?.digest||'')) throw Error('统计来源绑定或保存凭据缺失，请重新计算。');
    }
    function reviewed(result,context) {
      assertResultCurrent(result,context);
      const line=fragment(result), old=note.value;
      const next=ownFragment && old.includes(ownFragment) ? old.replace(ownFragment,line) : old+(old && !old.endsWith('\n')?'\n':'')+line;
      const maximum=Math.min(1200,note.maxLength>=0?note.maxLength:1200);
      if (next.length>maximum) {
        const error=Error(`复核备注最多 ${maximum} 字；请先精简原文字，再填入范围统计。`);
        notify(error.message);throw error;
      }
      // No finding, quality checkbox, ISO/J cursor, doctor confirmation or
      // storage operation is performed here.
      const value=compact(result);
      accepted={value,generation:++generation,fragment:line};
      state.sttRangeReviewed=copy(value);ownFragment=line;
      staleFragments.clear();host.dataset.sttRangeSnapshotState='current';
      note.value=next;
      note.dispatchEvent(new Event('input',{bubbles:true}));
      return copy(value);
    }
    async function locate(range,context) {
      assertResultCurrent(context.result,context);
      if (typeof onLocate!=='function') return;
      return onLocate(copy(range),{...context,isCurrent:()=>owned()&&current(context.request.scope)&&context.isCurrent()});
    }
    function create(context,selection=null) {
      component?.destroy();
      activeScope=copy(context.scope);mountedId=context.id;sourceEnd=context.end;externalMethod=method();
      const preferred=Array.isArray(state.sttLeads)?state.sttLeads:state.leads;
      const leads=Array.isArray(preferred)?preferred.filter(x=>globalThis.ECGSTTRangeReview.LEADS.includes(x)):[];
      component=globalThis.ECGSTTRangeReview.mount(host,{id:context.id,basis:activeScope,api,
        recordEndSample:sourceEnd,initialRange:selection||defaultRange(sourceEnd),
        initialLeads:selection?.leads?.length?selection.leads:leads.length?[...new Set(leads)]:['II','V1','V5'],
        measurementMs:selection?.measurement_ms ?? externalMethod,
        isCurrent:()=>inSTT()&&owned()&&current(),onReviewed:reviewed,...(typeof onLocate==='function'?{onLocate:locate}:{})});
      // Use the component's exact decimal/sample validator and Chinese error
      // state instead of stopping submit at a browser-specific step popup.
      const form=host.querySelector('[data-sttr-form]');if(form)form.noValidate=true;
      pagePaused=!inSTT();pausedRequest=pagePaused;
      host.dataset.sttRangeSnapshotState='empty';
    }
    function sync() {
      if (!owned()) return null;
      let context;
      try {context=live();}
      catch(error) {
        clearAccepted(error.message);
        component?.invalidate(error.message);
        if (!component) host.textContent=error.message;
        return null;
      }
      if (!component || mountedId!==context.id) {
        clearAccepted('病例已变化');saveCandidate=null;
        create(context);return component;
      }
      if (sourceEnd!==context.end) {
        let selected;
        try {selected=formSelection();globalThis.ECGSTTRangeReview.validateRange(selected.start_sample,selected.end_sample,context.end);}
        catch (_) {selected=null;}
        clearAccepted('记录长度已变化');create(context,selected);return component;
      }
      if (!equal(activeScope,context.scope)) {
        clearAccepted('统计依据已变化');activeScope=copy(context.scope);component.setBasis(activeScope);
        pausedRequest=!inSTT();
      }
      if (!inSTT()) {
        // state() checks the component's page guard and would erase a ready
        // result.  Read the pending flag without invoking that guard instead.
        pagePaused=true;
        if (host.getAttribute('aria-busy')==='true') {
          component.invalidate('已离开 ST-T，范围计算已取消；返回后可重试。');pausedRequest=true;
        }
        return component;
      }
      if (pagePaused) {
        if (pausedRequest) component.setBasis(activeScope);
        pagePaused=false;pausedRequest=false;
      }
      if (component.state().stale) {
        clearAccepted('统计依据已变化');component.setBasis(activeScope);
      }
      const nextMethod=method();
      if (nextMethod!==externalMethod) {
        clearAccepted('测量点已变化');externalMethod=nextMethod;
        try {const selected=formSelection();component.setRange({...selected,measurement_ms:nextMethod});}
        catch (_) {
          // Preserve an unfinished/off-grid time draft when the existing
          // measurement selector changes; validation belongs to Calculate.
          component.setBasis(activeScope);
          const selector=host.querySelector('[data-sttr-measurement]');if(selector)selector.value=String(nextMethod);
        }
      }
      return component;
    }
    function snapshotForSave() {
      sync();
      const staleText=[...staleFragments].some(value=>note.value.includes(value));
      if (staleText) throw Error('备注中的范围统计已失效；请重新计算填入，或删除该统计文字后保存。');
      if (!accepted || !state.sttRangeReviewed) {
        if (note.value.includes(MACHINE_PREFIX)) throw Error('备注中的机器范围统计缺少当前来源绑定，请重新计算填入或删除该统计文字。');
        return null;
      }
      if (!current(accepted.value.scope) || !equal(state.sttRangeReviewed,accepted.value)) {
        clearAccepted('统计快照已变化');throw Error('范围统计快照已失效，请重新计算后保存。');
      }
      let selected;
      try {selected=formSelection();} catch (_) {clearAccepted('范围无效');throw Error('范围已变化，请重新计算后保存。');}
      const value=accepted.value;
      if (selected.start_sample!==value.range.start_sample || selected.end_sample!==value.range.end_sample
          || selected.measurement_ms!==value.method_profile.measurement_ms || !equal(selected.leads,value.leads.map(x=>x.lead))) {
        clearAccepted('范围或导联已变化');throw Error('范围或统计方法已变化，请重新计算后保存。');
      }
      if (!note.value.includes(accepted.fragment)) {
        accepted=null;state.sttRangeReviewed=null;
        if (note.value.includes(MACHINE_PREFIX)) throw Error('机器统计文字已被修改，请重新计算填入，或移除机器统计文字后保存医生备注。');
        return null;
      }
      if (note.value.replace(accepted.fragment,'').includes(MACHINE_PREFIX)) throw Error('备注仍含另一份未绑定机器统计，请核对并移除后保存。');
      saveCandidate={generation:accepted.generation,digest:value.result_digest};
      const snapshot=copy(value);issuedSnapshots.set(snapshot,accepted.generation);return snapshot;
    }
    function clearAfterSave(expectedSnapshot=null) {
      if (!owned() || !accepted || !saveCandidate || saveCandidate.generation!==accepted.generation
          || saveCandidate.digest!==accepted.value.result_digest || expectedSnapshot &&
          (expectedSnapshot.result_digest!==accepted.value.result_digest || issuedSnapshots.get(expectedSnapshot)!==accepted.generation)) return false;
      accepted=null;state.sttRangeReviewed=null;saveCandidate=null;ownFragment='';staleFragments.clear();
      host.dataset.sttRangeSnapshotState='saved';return true;
    }
    const edited = event => {
      if (owned() && event.target?.matches?.('[data-sttr-start],[data-sttr-end],[data-sttr-lead],[data-sttr-measurement]')) clearAccepted('统计参数已变化');
    };
    const externalChange = () => {if (owned()) sync();};
    host.addEventListener('input',edited);host.addEventListener('change',edited);
    point?.addEventListener('change',externalChange);
    const controller={sync,snapshotForSave,clearAfterSave,
      destroy() {
        if (disposed) return;
        if (host._sttRangeBridgeOwner===owner) {clearAccepted('组件已关闭');component?.destroy();delete host._sttRangeBridgeOwner;delete host._sttRangeBridge;}
        disposed=true;host.removeEventListener('input',edited);host.removeEventListener('change',edited);point?.removeEventListener('change',externalChange);
      }};
    host._sttRangeBridge=controller;sync();return controller;
  }
  return {mount};
})();
if (typeof module!=='undefined' && module.exports) module.exports=globalThis.ECGSTTRangeBridge;
