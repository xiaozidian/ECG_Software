"use strict";
/* Read-only RR review. Every result and location is pinned to one exact beat revision. */
((root)=>{
  const MODES={rr:{label:'RR 间期',unit:'ms',metric:'rr_ms'},ratio:{label:'R/R 比值',unit:'%',metric:'ratio_pct'},hr:{label:'瞬时心率',unit:'bpm',metric:'hr_bpm'}};
  const DEFAULT_QUERY={mode:'rr',pair_type:'all',population:'all',quality:'all',start_s:null,end_s:null,range_min:null,range_max:null,offset:0,limit:50};
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const finite=value=>typeof value==='number'&&Number.isFinite(value);
  const metric=(value,digits=1)=>finite(value)?value.toLocaleString('zh-CN',{maximumFractionDigits:digits}):'—';
  const count=value=>Number.isSafeInteger(value)&&value>=0?value.toLocaleString('zh-CN'):'未知';
  const time=value=>finite(value)?`${Math.floor(value/3600).toString().padStart(2,'0')}:${Math.floor(value%3600/60).toString().padStart(2,'0')}:${(value%60).toFixed(2).padStart(5,'0')}`:'—';
  const optionalNumber=value=>value===null||value===undefined||value===''?null:Number(value);
  const REASONS=Object.freeze({
    artifact_boundary:'伪差边界',flutter_no_ordinary_rr:'室扑/室颤波形标记，无法解释普通 RR',
    unknown_type:'类型未知',outside_current_nn_bounds:'当前 NN 范围外',
    excluded_rhythm_interval:'完整间期与排除节律重叠',missing_stored_rr:'输入间期缺失',
    stored_sample_mismatch:'输入间期与采样间距不一致',outside_recording:'录制范围外',
    invalid_sample:'样本位置无效',non_increasing_samples:'样本位置未递增',duplicate_sample:'样本位置重复',
    invalid_stored_rr:'输入间期无效',invalid_interval:'间期无效',non_normal_label:'两端并非均为 N 标签',
    nn_settings_unknown:'当前 NN 范围未设置',nn_recording_scope_unknown_or_outside:'记录范围未知或超出记录范围',
    sinus_and_quality_not_verified:'窦性与质量未核实',no_confirmed_verification_evidence:'缺少已确认的核实证据',
    verification_scope_mismatch:'核实证据与当前病例或修订不一致',verification_method_mismatch:'核实方法与当前方法不一致',
    interval_outside_verified_scope:'完整间期超出核实范围',
    preceding_original_interval_unavailable:'前一原始间期不可用',no_preceding_original_interval:'没有前一原始间期'
  });
  const reasonLabel=code=>typeof code==='string'&&Object.hasOwn(REASONS,code)?REASONS[code]:'原因未说明';
  const SOURCES=Object.freeze({source_label:'原始标签',physician_edit:'人工改型',physician_insert:'人工补搏',provided_annotation:'既有注释',physician_override:'人工覆盖',physician_position_edit:'位置修订'});
  const sourceLabel=code=>typeof code==='string'&&Object.hasOwn(SOURCES,code)?SOURCES[code]:'未知来源';
  function methodValue(name,value){
    if(typeof value==='boolean')return value?'是':'否';
    if(name==='references'){
      if(!Array.isArray(value))return '资料未提供';
      return value.map(url=>{
        if(typeof url!=='string'||!/^https:\/\/(?:www\.)?physionet\.org(?:\/|$)/.test(url))return `<span title="${esc(url)}">资料链接未确认</span>`;
        const label=url.includes('ann2rr')?'PhysioNet · RR 间期定义':url.includes('ecgmap.h')?'PhysioNet · 注释类型映射':'PhysioNet 官方资料';
        return `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>`;
      }).join('；')||'资料未提供';
    }
    return esc(value===null||value===undefined?'未知':typeof value==='string'?value:JSON.stringify(value));
  }
  const key=query=>JSON.stringify(Object.entries(query).filter(([name])=>name!=='offset'&&name!=='limit'&&name!=='range_min'&&name!=='range_max'));
  function normalizeQuery(input){
    const q={...DEFAULT_QUERY,...input};
    if(!MODES[q.mode])throw Error('请选择 RR、R/R 或心率');
    if(!['all','normal_pair','nn_eligible','nn_verified','unknown'].includes(q.population))throw Error('间期总体无效');
    if(!['all','valid','invalid'].includes(q.quality))throw Error('质量筛选无效');
    if(q.pair_type!=='all'){
      let pair;try{pair=JSON.parse(q.pair_type);}catch(_){throw Error('请选择完整的有序间期类型');}
      if(!Array.isArray(pair)||pair.length!==2||pair.some(v=>typeof v!=='string'))throw Error('有序间期类型无效');
      q.pair_type=JSON.stringify(pair);
    }
    for(const name of ['start_s','end_s','range_min','range_max']){
      q[name]=optionalNumber(q[name]);if(q[name]!==null&&(!Number.isFinite(q[name])||q[name]<0))throw Error('范围必须是非负有限数值');
    }
    if(q.start_s!==null&&q.end_s!==null&&q.end_s<=q.start_s)throw Error('结束时间必须晚于开始时间');
    if(q.range_min!==null&&q.range_max!==null&&q.range_max<=q.range_min)throw Error('数值上限必须大于下限');
    if(!Number.isSafeInteger(Number(q.offset))||Number(q.offset)<0)throw Error('结果起始序号无效');
    if(!Number.isSafeInteger(Number(q.limit))||Number(q.limit)<1||Number(q.limit)>200)throw Error('每页应为 1–200 条');
    q.offset=Number(q.offset);q.limit=Number(q.limit);
    return Object.fromEntries(Object.keys(DEFAULT_QUERY).map(name=>[name,q[name]]));
  }
  function normalizeBasis(basis={}){
    const result={analysis_basis:basis.analysis_basis,analysis_revision:basis.analysis_revision,beat_revision:basis.beat_revision??basis.beatRevision};
    if(typeof result.analysis_basis!=='string'||!result.analysis_basis||!Number.isSafeInteger(result.analysis_revision)||!Number.isSafeInteger(result.beat_revision))throw Error('RR 复核需要明确的分析依据及逐搏修订');
    return Object.freeze(result);
  }
  function assertIdentity(response,context){
    for(const field of ['analysis_basis','analysis_revision','beat_revision'])if(response?.[field]!==context[field])throw Error('RR 返回的分析依据或逐搏修订已变化，请重新载入');
  }
  function validateResponse(response,context,query){
    assertIdentity(response,context);
    if(typeof context.caseId!=='string'||!context.caseId||response.case_id!==context.caseId)throw Error('RR 返回的病例身份不一致，未显示');
    if(!Number.isSafeInteger(response.total)||response.total<0||response.offset!==query.offset||response.limit!==query.limit||!Array.isArray(response.items))throw Error('RR 分页结果不完整，未显示');
    if(response.items.length!==Math.min(query.limit,Math.max(0,response.total-query.offset)))throw Error('RR 匹配结果缺失，未显示不完整页面');
    if(response.query){
      // The server expands blank time fields to the full recording [0, duration).
      const returned=normalizeQuery({...response.query,start_s:null,end_s:null});
      for(const name of Object.keys(query))if(name!=='start_s'&&name!=='end_s'&&returned[name]!==query[name])throw Error('RR 返回的筛选范围不一致，未显示');
      const expectedStart=query.start_s??0,expectedEnd=query.end_s??response.duration_s??null;
      if(response.query.start_s!==expectedStart||response.query.end_s!==expectedEnd)throw Error('RR 返回的时间范围不一致，未显示');
    }
    const ids=new Set();
    for(const item of response.items){
      const target=item?.target;
      if(!item.id||ids.has(item.id)||item.right?.sample_index!==item.end_sample||item.left?.sample_index!==item.start_sample)throw Error('RR 结果缺少准确的心搏身份，未显示');
      ids.add(item.id);
      // Invalid intervals remain reviewable even when no exact terminal target exists.
      if(target===null){if(item.quality?.valid!==false)throw Error('有效 RR 缺少准确定位目标，未显示');continue;}
      assertIdentity(target,context);
      if(target.case_id!==context.caseId||target.caseId!==context.caseId)throw Error('RR 定位目标来自其他病例或缺少病例身份，未显示');
      if(!Number.isSafeInteger(item.end_sample)||item.end_sample<0||target.sample_index!==item.end_sample||target.interval_start_sample!==item.start_sample||target.interval_end_sample!==item.end_sample||!target.beat_id||target.beat_id!==item.right?.id)throw Error('RR 结果缺少准确的心搏身份，未显示');
    }
    for(const histogram of [response.histogram,response.selected_histogram].filter(Boolean)){
      if(histogram.mode!==query.mode||!Array.isArray(histogram.bins)||histogram.bins.some(bin=>!finite(bin.start)||bin.start<0||!(bin.end===null||finite(bin.end)&&bin.end>bin.start)||!Number.isSafeInteger(bin.count)||bin.count<0))throw Error('RR 柱图统计无效，未显示');
    }
    return response;
  }
  function mount(options){
    const host=options.host;
    if(!host||typeof options.api!=='function')throw Error('RR 复核需要容器和 API');
    if(typeof options.caseId!=='string'||!options.caseId)throw Error('RR 复核需要明确的病例身份');
    for(const name of ['case_id','caseId'])if(options.basis?.[name]!==undefined&&options.basis[name]!==options.caseId)throw Error('RR 挂载依据与当前病例不一致');
    const identity=normalizeBasis(options.basis),context=Object.freeze({caseId:options.caseId,caseToken:options.caseToken,...identity});
    let query={...DEFAULT_QUERY},response=null,histogram=null,histogramKey='',phase='idle',error='',generation=0,controller=null,stripController=null,locateController=null,disposed=false;
    let logScale=false,showStrips=false,stripsPhase='idle',stripError='',stripItems=new Map(),brush=null,keyboardBin=0,locateGeneration=0,locatedIndex=null,locationMessage='';
    let selectedIndex=null,selectionPhase='idle',hasLoaded=false;
    const listeners=[];
    const current=()=>!disposed&&(typeof options.isCurrent!=='function'||options.isCurrent(context)!==false);
    const qs=name=>host.querySelector('[data-rr-role="'+name+'"]');
    const field=name=>host.querySelector('[data-rr-field="'+name+'"]');
    const on=(type,handler)=>{host.addEventListener(type,handler);listeners.push([type,handler]);};
    const setText=(name,text)=>{const el=qs(name);if(el)el.textContent=text;};
    host.classList?.add('rr-review-workbench');
    host.innerHTML=`<section class="rrv-workspace" aria-label="RR 间期复核"><header class="rrv-heading"><div><h2>RR 间期复核</h2><p>按原始相邻心搏核对 · 精确定位终搏</p></div><div class="rrv-heading-actions"><button type="button" data-rr-action="cancel">取消读取</button><button type="button" data-rr-action="retry">重新读取</button></div></header><div class="rrv-summary" data-rr-role="summary"></div><div class="rrv-grid"><aside class="rrv-filter"><h3>间期条件</h3><label>显示指标<select data-rr-field="mode"><option value="rr">RR 间期 · ms</option><option value="ratio">R/R 比值 · %</option><option value="hr">瞬时心率 · bpm</option></select></label><label>有序类型 · 前搏 → 终搏<select data-rr-field="pair_type"><option value="all">全部有序类型</option></select></label><label>统计总体<select data-rr-field="population"><option value="all">全部间期</option><option value="normal_pair">N → N 类型间期</option><option value="nn_eligible">既有 NN 筛选候选（窦性未核实）</option><option value="nn_verified">已核实窦性与质量的 NN</option><option value="unknown">类型未知</option></select></label><label>RR 可计算性<select data-rr-field="quality"><option value="all">全部质量</option><option value="valid">可计算普通 RR</option><option value="invalid">不可计算普通 RR</option></select></label><form data-rr-form="range"><fieldset><legend>时间范围 · 秒</legend><div class="rrv-field-pair"><label>开始<input data-rr-field="start_s" type="number" min="0" step="any" placeholder="全程"></label><label>结束<input data-rr-field="end_s" type="number" min="0" step="any" placeholder="全程"></label></div></fieldset><fieldset><legend data-rr-role="range-label">RR 范围 · ms</legend><div class="rrv-field-pair"><label>下限 · 含<input data-rr-field="range_min" type="number" min="0" step="any" placeholder="不限"></label><label>上限 · 不含<input data-rr-field="range_max" type="number" min="0" step="any" placeholder="不限"></label></div></fieldset><div class="rrv-filter-actions"><button type="submit" data-rr-action="apply">应用范围</button><button type="button" data-rr-action="clear-range">清除数值范围</button></div></form><p class="rrv-rule">原始邻居保持不变。筛选不会拼接新的 RR。类型未知与未通过 NN 候选规则的间期分别保留。</p></aside><div class="rrv-main"><section class="rrv-chart-card"><header><div><h3 data-rr-role="chart-title">RR 分布</h3><output data-rr-role="chart-count">尚未读取</output></div><label class="rrv-check"><input type="checkbox" data-rr-field="log">计数对数显示</label></header><canvas data-rr-role="histogram" tabindex="0" role="img" aria-label="间期柱图。拖动选择数值范围；方向键移动，Shift 加方向键扩大范围，Enter 应用，Escape 清除。"></canvas><div class="rrv-chart-foot"><span data-rr-role="selection">拖动柱图或输入范围；下限包含，上限不包含</span><span>方向键移动 · Shift 扩展 · Enter 应用</span></div></section><section class="rrv-results"><div class="rrv-selected" data-rr-role="selected" aria-live="polite"></div><div data-rr-role="evidence-slot"></div><header><div><h3>匹配间期</h3><output data-rr-role="count">尚未读取</output></div><label class="rrv-check"><input type="checkbox" data-rr-field="strips">当前页三导联片段</label></header><div class="rrv-status" data-rr-role="status" role="status" aria-live="polite"></div><div data-rr-role="results"></div><footer class="rrv-pagination"><button type="button" data-rr-action="previous">上一页</button><output data-rr-role="page">—</output><button type="button" data-rr-action="next">下一页</button><label>每页<select data-rr-field="limit"><option value="25">25</option><option value="50" selected>50</option><option value="100">100</option><option value="200">200</option></select></label><form data-rr-form="page"><label>转到序号<input data-rr-field="ordinal" type="number" min="1" step="1" inputmode="numeric"></label><button type="submit">前往</button></form></footer></section></div></div><details class="rrv-method"><summary>依据、来源与计算口径</summary><div data-rr-role="provenance"></div></details></section>`;
    function syncFields(){
      for(const name of Object.keys(DEFAULT_QUERY)){const node=field(name);if(node)node.value=query[name]??'';}
      if(field('log'))field('log').checked=logScale;
      if(field('strips'))field('strips').checked=showStrips;
      setText('range-label',`${MODES[query.mode].label}范围 · ${MODES[query.mode].unit}`);
      setText('chart-title',`${MODES[query.mode].label}分布`);
    }
    function renderSummary(){
      const summary=response?.summary;
      const entries=[['当前 QRS','qrs_count'],['原邻间期','interval_count'],['可计算 RR','valid_rr_count'],['不可计算 RR','invalid_count'],['类型未知','unknown_type_count'],['N → N','normal_pair_count'],['NN 候选（未核实）','nn_eligible_count']];
      const node=qs('summary');if(node)node.innerHTML=entries.map(([label,name])=>`<div><span>${label}</span><strong>${count(summary?.[name])}</strong></div>`).join('');
    }
    function renderPairs(){
      const node=field('pair_type');if(!node)return;
      const pairs=response?.pair_types||[];
      node.innerHTML='<option value="all">全部有序类型</option>'+pairs.map(pair=>`<option value="${esc(pair.code)}">${esc(pair.left_type)} → ${esc(pair.right_type)} · ${count(pair.total)}</option>`).join('');
      if(query.pair_type!=='all'&&!pairs.some(pair=>pair.code===query.pair_type))node.innerHTML+=`<option value="${esc(query.pair_type)}">${esc(JSON.parse(query.pair_type).join(' → '))} · 当前条件 0</option>`;
      node.value=query.pair_type;
    }
    function renderMethod(){
      const method=response?.method||{};
      const descriptions=Object.entries(method).map(([name,value])=>`<li><strong>${esc(({rr:'RR',ratio:'R/R',hr:'心率',normal_pair:'N → N',nn:'NN 候选规则',classification:'类型来源',manual_review:'人工复核',unknown:'未知类型',verified_nn:'已核实 NN',population:'时间归属',nn_min_ms:'NN 候选下限 · ms',nn_max_ms:'NN 候选上限 · ms',nn_settings_known:'NN 候选范围已知',duration_known:'记录时长已知',hospital_mapping_verified:'医院映射已核实',references:'资料'})[name]||name)}</strong> ${methodValue(name,value)}</li>`).join('');
      const node=qs('provenance');if(node)node.innerHTML=`<p>依据：<strong>${esc(identity.analysis_basis)}</strong> · 分析修订 ${identity.analysis_revision} · 逐搏修订 ${identity.beat_revision}${response?` · 方法 ${esc(response.method_version||'未知')} · 采样率 ${metric(response.sample_rate_hz)} Hz`:''}</p>${descriptions?`<ul>${descriptions}</ul>`:'<p>读取后显示当前计算口径与注释来源。</p>'}<p>NN 筛选候选不代表已核实 NN。已核实 NN 需要窦性、质量与范围证据；缺少证据时保留未核实状态。</p><p>对数显示采用 log₁₀(计数 + 1)，每柱真实计数与筛选总体保持一致。</p>`;
    }
    function renderRows(){
      const node=qs('results');if(!node)return;
      if(phase!=='ready'||!response){node.innerHTML=`<div class="rrv-empty">${esc(phase==='loading'?'正在读取当前条件的完整结果…':phase==='error'?'读取未完成，请重新读取。':phase==='cancelled'?'读取已取消，可重新读取当前条件。':phase==='inactive'?'当前病例或依据已变化，请重新打开 RR 复核。':'选择条件后读取 RR 间期。')}</div>`;return;}
      if(!response.total){node.innerHTML='<div class="rrv-empty"><strong>匹配 0 个间期</strong><span>当前条件没有匹配结果；类型未知和不可计算间期可分别筛选查看。</span></div>';return;}
      node.innerHTML=`<div class="rrv-table-scroll"><table><thead><tr><th>序号 / 时间</th><th>前搏 → 终搏</th><th>RR · ms</th><th>R/R · %</th><th>心率 · bpm</th><th>计算 / NN</th><th>定位</th></tr></thead><tbody>${response.items.map((item,index)=>{
        const valid=item.quality?.valid,known=item.type_known;
        const provenance=`${sourceLabel(item.left?.classification_source)} → ${sourceLabel(item.right?.classification_source)}`;
        const provenanceKeys=`${item.left?.classification_source||'unknown'} → ${item.right?.classification_source||'unknown'}`;
        const qualityCode=item.quality?.reason||'',nnCode=item.nn_reason||'';
        const nnText=item.nn_eligible_verified===true?'已核实 NN':item.nn_eligible_current_rules===true?'NN 候选 · 窦性未核实':`NN 候选未通过：${reasonLabel(nnCode)}`;
        const selected=typeof options.onSelection==='function'?selectedIndex===index:locatedIndex===index;
        return `<tr data-rr-row-index="${index}" tabindex="${selected?'0':'-1'}" aria-selected="${selected?'true':'false'}" class="${selected?'rrv-selected-row':''}"><td><strong>${count(response.offset+index+1)}</strong><small>${time(item.time_s)}</small></td><td><span class="rrv-pair${known===false?' rrv-unknown':''}">${esc(item.left_type)} → ${esc(item.right_type)}</span><small title="${esc(provenanceKeys)}">${esc(provenance)}</small><small>样本 ${esc(item.start_sample??'未知')} → ${esc(item.end_sample??'未知')}</small></td><td>${metric(item.rr_ms)}${item.rr_ms===null&&finite(item.computed_rr_ms)?`<small>采样间距 ${metric(item.computed_rr_ms)} ms</small>`:''}${finite(item.stored_rr_ms)&&item.stored_rr_ms!==item.rr_ms?`<small>输入间期 ${metric(item.stored_rr_ms)}</small>`:''}</td><td>${metric(item.ratio_pct,2)}</td><td>${metric(item.hr_bpm,2)}</td><td><span class="rrv-quality ${valid===true?'rrv-valid':'rrv-invalid'}">${valid===true?'可计算 RR':valid===false?'不可计算 RR':'计算未知'}</span>${valid===false?`<small title="${esc(qualityCode)}">${esc(reasonLabel(qualityCode))}</small>`:''}<small title="${esc(nnCode)}">${esc(nnText)}</small></td><td>${item.target===null?`<button type="button" disabled>目标不可用</button><small title="${esc(qualityCode)}">${esc(reasonLabel(qualityCode))}</small>`:`<button type="button" data-rr-action="locate" data-rr-index="${index}" aria-label="精确定位第 ${response.offset+index+1} 个间期终搏，样本 ${item.end_sample}">定位终搏</button>`}</td></tr>${showStrips&&item.target!==null?`<tr class="rrv-strip-row"><td colspan="7"><div class="rrv-strip-label">II / V1 / V5 · 终搏 R 对齐 · 设备单位未校准</div>${stripItems.has(item.end_sample)?`<canvas data-rr-strip="${item.end_sample}" aria-label="间期终搏样本 ${item.end_sample} 的三导联波形"></canvas>`:`<div class="rrv-strip-placeholder">${esc(stripsPhase==='error'?stripError||'片段读取失败':stripsPhase==='ready'?'片段缺失':'正在读取当前页真实片段…')}</div>`}</td></tr>`:''}`;
      }).join('')}</tbody></table></div>`;
      if(showStrips)for(const canvas of node.querySelectorAll('canvas[data-rr-strip]')){
        const sample=Number(canvas.dataset.rrStrip),strip=stripItems.get(sample),item=response.items.find(r=>r.end_sample===sample);drawStrip(canvas,strip);
        if(strip&&item&&options.bindStrip){
          const run=generation,scopeCurrent=()=>current()&&run===generation&&showStrips&&canvas.isConnected;
          options.bindStrip(canvas,strip,item,scopeCurrent,async visible=>{
            if(!scopeCurrent())throw Error('间期筛选已变化，请重新右击');
            if(visible)return response.items.filter(r=>r.target!==null).map(r=>r.end_sample);
            const own={...query},indexKey=response.index_key,total=response.total,samples=[];
            for(let offset=0;offset<total;offset+=200){
              if(!scopeCurrent())throw Error('间期筛选已变化，已停止全选');
              const page={...own,offset,limit:200},params=new URLSearchParams({...identity,case_id:context.caseId});
              for(const [k,v]of Object.entries(page))if(v!==null)params.set(k,String(v));
              const result=await options.api('/api/cases/'+encodeURIComponent(context.caseId)+'/rr-review?'+params);
              validateResponse(result,context,page);if(!scopeCurrent()||result.index_key!==indexKey||result.total!==total)throw Error('间期依据已变化，未应用全选');
              samples.push(...result.items.filter(r=>r.target!==null).map(r=>r.end_sample));
            }
            return [...new Set(samples)];
          });
        }
      }
    }
    function renderSelection(){
      const node=qs('selected');if(!node)return;
      const item=selectedIndex===null?null:response?.items?.[selectedIndex];
      if(typeof options.onSelection!=='function'){node.hidden=true;return;}
      node.hidden=false;
      const quality=item?.quality?.valid===true?'可计算普通 RR':item?.quality?.valid===false?'不可计算普通 RR：'+reasonLabel(item.quality.reason):'RR 可计算性未知';
      const nn=item?.nn_eligible_verified===true?'已核实 NN（仅当前修订和核实范围）':item?.nn_eligible_current_rules===true?'既有 NN 筛选候选（窦性未核实）':'未纳入既有 NN 候选：'+reasonLabel(item?.nn_reason);
      const sources=item?sourceLabel(item.left?.classification_source)+' → '+sourceLabel(item.right?.classification_source):'';
      const status=selectionPhase==='loading'?'正在读取精确原始波形…':selectionPhase==='ready'?'已显示所选原始波形':selectionPhase==='error'?locationMessage||'波形读取未完成':selectionPhase==='pending'?'等待波形核对':phase==='loading'?'正在读取当前筛选…':'选择间期查看原始波形';
      node.innerHTML=item?`<div><strong>当前第 ${count(response.offset+selectedIndex+1)} 个间期 · ${esc(item.left_type)} → ${esc(item.right_type)}</strong><span>RR ${metric(item.rr_ms)} ms · R/R ${metric(item.ratio_pct,2)} % · ${time(item.time_s)}</span></div><div><span role="status">${esc(status)}</span>${selectionPhase==='error'?'<button type="button" data-rr-action="retry-selection">重读所选波形</button>':''}</div><p class="rrv-selection-boundary"><strong>${esc(quality)}</strong> · ${esc(nn)}<span>类型来源：${esc(sources)}</span></p><small>可计算 RR 不代表临床质量合格；源 N 标签不等于医生已核实窦性，节律、信号质量与核实范围仍需复核。↑ / ↓ 切换当前页间期。</small>`:`<strong>${esc(status)}</strong><small>原始波形按当前病例与修订精确读取；没有合法目标时不使用最近邻替代。</small>`;
    }
    function render(){
      if(!current()&&phase!=='inactive'){abort('inactive');phase='inactive';response=null;histogram=null;}
      syncFields();renderSummary();renderMethod();renderRows();renderSelection();
      const busy=phase==='loading';
      setText('status',phase==='error'?error:phase==='loading'?'正在读取当前条件…':phase==='cancelled'?'已取消读取':phase==='inactive'?'病例或依据已变化，结果已失效':'尚未读取');
      if(phase==='ready')setText('status',locationMessage||`当前条件完整匹配 ${count(response.total)} 个间期`);
      const status=qs('status');if(status)status.dataset.state=phase;
      qs('results')?.setAttribute('aria-busy',String(busy));
      setText('count',phase==='ready'?`完整匹配 ${count(response.total)} 个 · 当前页 ${count(response.items.length)} 个`:busy?'正在核对完整匹配数量…':'—');
      setText('page',phase==='ready'?response.total?`${count(response.offset+1)}–${count(response.offset+response.items.length)} / ${count(response.total)}`:'0 / 0':'—');
      for(const action of ['previous','next']){const button=host.querySelector('[data-rr-action="'+action+'"]');if(button)button.disabled=phase!=='ready'||(action==='previous'?response.offset<=0:response.offset+response.items.length>=response.total);}
      const cancelButton=host.querySelector('[data-rr-action="cancel"]');if(cancelButton)cancelButton.disabled=!busy&&stripsPhase!=='loading'&&selectionPhase!=='loading';
      drawHistogram();
    }
    function drawHistogram(){
      const canvas=qs('histogram');if(!canvas)return;
      const bins=histogram?.bins||[],ctx=canvas.getContext?.('2d');
      const selectedCount=response?.selected_histogram?.bins?.reduce((n,b)=>n+b.count,0);
      const total=bins.reduce((n,b)=>n+b.count,0);
      setText('chart-count',histogram?`可绘制 ${count(total)} 个${selectedCount!==undefined?` · 当前数值范围 ${count(selectedCount)} 个`:''}`:phase==='loading'?'正在读取柱图…':'尚未读取');
      const left=query.range_min,right=query.range_max;
      const previewBins=brush&&bins.length?bins.slice(Math.min(brush.anchor,brush.end),Math.max(brush.anchor,brush.end)+1):null;
      setText('selection',previewBins?.length?`预选 [${metric(previewBins[0].start,3)}, ${previewBins[previewBins.length-1].end===null?'∞':metric(previewBins[previewBins.length-1].end,3)}) ${MODES[query.mode].unit} · ${count(previewBins.reduce((n,b)=>n+b.count,0))} 个；Enter 应用`:left===null&&right===null?'拖动柱图或输入范围；下限包含，上限不包含':`当前范围 [${left===null?'0':metric(left,3)}, ${right===null?'∞':metric(right,3)}) ${MODES[query.mode].unit}`);
      canvas.setAttribute('aria-description',histogram?`${MODES[query.mode].label}，${count(total)} 个可绘制间期，${logScale?'对数计数显示':'线性计数显示'}。${qs('selection')?.textContent||''}`:'柱图尚未读取');
      if(!ctx)return;
      const rect=canvas.getBoundingClientRect?.()||{width:640,height:230};
      const width=Math.max(260,rect.width||640),height=Math.max(180,rect.height||230),dpr=Math.min(root.devicePixelRatio||1,2);
      canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,width,height);
      const g={left:46,top:20,width:width-60,height:height-55};canvas._rrGeometry=g;
      ctx.fillStyle='#fbfdfd';ctx.fillRect(0,0,width,height);ctx.font='11px sans-serif';ctx.fillStyle='#526773';
      if(!bins.length){ctx.fillText(phase==='loading'?'正在读取分布…':'暂无分布',g.left,height/2);return;}
      const max=Math.max(1,...bins.map(b=>logScale?Math.log10(b.count+1):b.count));
      const preview=brush?[Math.min(brush.anchor,brush.end),Math.max(brush.anchor,brush.end)]:null;
      bins.forEach((bin,index)=>{
        const value=logScale?Math.log10(bin.count+1):bin.count,x=g.left+index*g.width/bins.length,w=Math.max(1,g.width/bins.length-.5),h=value/max*g.height;
        const selected=preview?index>=preview[0]&&index<=preview[1]:(left!==null||right!==null)&&(left===null||bin.start>=left)&&(right===null||bin.end!==null&&bin.end<=right);
        if(selected){ctx.fillStyle='#e3f3f1';ctx.fillRect(x,g.top,w,g.height);}
        ctx.fillStyle=selected?'#0c6e6c':'#4ba39e';ctx.fillRect(x,g.top+g.height-h,w,h);
        if(index===keyboardBin&&canvas===root.document?.activeElement){ctx.strokeStyle='#173c49';ctx.strokeRect(x,g.top,w,g.height);}
      });
      ctx.strokeStyle='#b7ced4';ctx.beginPath();ctx.moveTo(g.left,g.top);ctx.lineTo(g.left,g.top+g.height);ctx.lineTo(g.left+g.width,g.top+g.height);ctx.stroke();
      ctx.fillStyle='#526773';ctx.fillText(logScale?metric(max,2):count(max),2,g.top+4);ctx.fillText('0',25,g.top+g.height+4);
      [0,Math.floor(bins.length/2),bins.length-1].forEach(index=>{const bin=bins[index];ctx.textAlign=index===0?'left':index===bins.length-1?'right':'center';ctx.fillText(bin.end===null?`≥${metric(bin.start)}`:metric(bin.start),g.left+index*g.width/bins.length,g.top+g.height+19);});ctx.textAlign='left';
      ctx.fillText(MODES[query.mode].unit,g.left+g.width-35,height-3);
      if(total===0)ctx.fillText('可绘制间期为 0；缺少指标的间期仍保留在结果中',g.left+8,g.top+g.height/2);
    }
    function drawStrip(canvas,strip){
      if(!strip)return;
      const ctx=canvas.getContext?.('2d');if(!ctx)return;
      const rect=canvas.getBoundingClientRect?.()||{width:600,height:108},width=Math.max(260,rect.width||600),height=108,dpr=Math.min(root.devicePixelRatio||1,2);
      canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);ctx.fillStyle='#071b22';ctx.fillRect(0,0,width,height);
      const leads=['II','V1','V5'],x0=34,w=width-42;
      canvas._ecgWaveGeometry={l:x0,w};
      const amplitudes=leads.flatMap(lead=>(strip.leads?.[lead]||[]).filter(finite));const limit=Math.max(1,...amplitudes.map(Math.abs));
      ctx.strokeStyle='#26434b';ctx.lineWidth=.5;for(let x=x0;x<width;x+=w/20){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,height);ctx.stroke();}
      leads.forEach((lead,index)=>{const values=strip.leads?.[lead]||[],y=index*36+18;ctx.fillStyle='#b9d6d7';ctx.font='10px sans-serif';ctx.fillText(lead,7,y+3);ctx.strokeStyle='#72d6c3';ctx.lineWidth=1;ctx.beginPath();values.forEach((value,i)=>{if(!finite(value))return;const x=x0+(i*(strip.stride||1)/strip.sample_rate_hz)/strip.duration_s*w,py=y-value/limit*14;if(i===0)ctx.moveTo(x,py);else ctx.lineTo(x,py);});ctx.stroke();});
      const marker=x0+strip.anchor_offset_s/strip.duration_s*w;ctx.strokeStyle='#ffc978';ctx.setLineDash([3,3]);ctx.beginPath();ctx.moveTo(marker,0);ctx.lineTo(marker,height);ctx.stroke();ctx.setLineDash([]);
    }
    function abort(reason='query'){
      generation++;controller?.abort();stripController?.abort();locateController?.abort();controller=null;stripController=null;locateController=null;locateGeneration++;brush=null;stripItems.clear();stripsPhase='idle';stripError='';locatedIndex=null;selectedIndex=null;selectionPhase='idle';locationMessage='';
      if(typeof options.onSelection==='function'){
        const run=generation,focusRun=locateGeneration;
        const guard=Object.freeze({signal:new AbortController().signal,isCurrent:()=>run===generation&&focusRun===locateGeneration&&current(),reason,rowIndex:null});
        try{Promise.resolve(options.onSelection(null,guard)).catch(()=>{});}catch(_){/* Clearing old evidence must not prevent cancellation. */}
      }
    }
    async function load(patch={}){
      if(!current()){abort();phase='inactive';response=null;histogram=null;render();return null;}
      let next;
      try{
        const merged={...query,...patch};
        if(patch.mode&&patch.mode!==query.mode&&!Object.hasOwn(patch,'range_min')&&!Object.hasOwn(patch,'range_max')){merged.range_min=null;merged.range_max=null;}
        if(!Object.hasOwn(patch,'offset')&&Object.entries(patch).some(([name,value])=>name!=='limit'&&name!=='offset'&&value!==query[name]))merged.offset=0;
        if(Object.hasOwn(patch,'limit')&&!Object.hasOwn(patch,'offset'))merged.offset=0;
        next=normalizeQuery(merged);
      }catch(problem){abort();phase='error';error=problem.message;response=null;render();return null;}
      const selectionReason=!hasLoaded?'initial':next.offset!==query.offset?'page':'query';
      abort(selectionReason);query=next;const run=generation,requestController=new AbortController();controller=requestController;
      response=null;phase='loading';error='';
      if(histogramKey!==key(query)){histogram=null;histogramKey=key(query);}
      render();
      const params=new URLSearchParams({...identity,case_id:context.caseId});
      for(const [name,value] of Object.entries(query))if(value!==null)params.set(name,String(value));
      try{
        const result=await options.api('/api/cases/'+encodeURIComponent(context.caseId)+'/rr-review?'+params,{method:'GET',signal:requestController.signal});
        if(run!==generation||requestController.signal.aborted||!current())return null;
        validateResponse(result,context,query);response=result;histogram=result.histogram||null;phase='ready';controller=null;keyboardBin=Math.min(keyboardBin,Math.max(0,(histogram?.bins.length||1)-1));renderPairs();render();
        hasLoaded=true;
        if(typeof options.onSelection==='function'){const first=response.items.findIndex(item=>item.target!==null);if(first>=0)void select(first,selectionReason);}
        if(showStrips)void loadStrips(run);
        return result;
      }catch(problem){
        if(run!==generation||requestController.signal.aborted||!current())return null;
        response=null;histogram=null;phase='error';error=problem.message||'RR 读取失败';controller=null;render();return null;
      }
    }
    async function loadStrips(run=generation){
      if(!showStrips||phase!=='ready'||!response||!current())return;
      stripController?.abort();stripController=new AbortController();const ticket=stripController,items=response.items,samples=[...new Set(items.filter(item=>item.target!==null).map(item=>item.end_sample))];
      stripItems.clear();stripError='';stripsPhase=samples.length?'loading':'ready';render();
      try{
        // Sixteen exact excerpts per request; page size does not truncate result membership.
        for(let start=0;start<samples.length;start+=16){
          if(ticket.signal.aborted||run!==generation||!current()||!showStrips)return;
          const batch=samples.slice(start,start+16);
          const result=await options.api('/api/cases/'+encodeURIComponent(context.caseId)+'/waveform-strips',{method:'POST',signal:ticket.signal,body:JSON.stringify({...identity,case_id:context.caseId,revision:identity.beat_revision,sample_indices:batch,pre_s:1.5,post_s:2.5,leads:['II','V1','V5'],max_points:800,filter:options.filter||'display'})});
          if(ticket.signal.aborted||run!==generation||!current()||!showStrips)return;
          assertIdentity(result,context);
          if(result.case_id!==context.caseId)throw Error('三导联片段返回的病例身份不一致');
          if(!Array.isArray(result.items)||result.items.length!==batch.length||result.items.some((item,index)=>item.case_id!==context.caseId||item.sample_index!==batch[index]))throw Error('三导联片段的精确心搏集合不一致');
          for(const item of result.items)stripItems.set(item.sample_index,item);
          renderRows();
        }
        stripsPhase='ready';stripController=null;render();
      }catch(problem){
        if(ticket.signal.aborted||run!==generation||!current()||!showStrips)return;
        stripItems.clear();stripsPhase='error';stripError=problem.message||'片段读取失败';stripController=null;render();setText('status','当前页小波形读取失败，可重新读取。完整结果仍可精确定位。');
      }
    }
    async function select(index,reason='pointer',{force=false,focus=false}={}){
      if(phase!=='ready'||!response||!current()||typeof options.onSelection!=='function')return false;
      const item=response.items[index];if(!item||item.target===null)return false;
      if(!force&&selectedIndex===index&&['loading','ready','pending'].includes(selectionPhase))return false;
      locateController?.abort();const ticket=new AbortController();locateController=ticket;
      const run=generation,focusRun=++locateGeneration;
      const guard=Object.freeze({signal:ticket.signal,isCurrent:()=>run===generation&&focusRun===locateGeneration&&selectedIndex===index&&current()&&!ticket.signal.aborted,reason,rowIndex:index,reveal:reason==='pointer'||reason==='keyboard'});
      const target=Object.freeze({...item.target,case_token:context.caseToken});
      selectedIndex=index;locatedIndex=null;selectionPhase='loading';locationMessage='正在读取所选间期的精确原始波形…';render();
      if(focus){const row=host.querySelector('[data-rr-row-index="'+index+'"]');row?.focus({preventScroll:true});row?.scrollIntoView?.({block:'nearest'});}
      try{
        assertIdentity(target,context);if(target.case_id!==context.caseId||target.caseId!==context.caseId)throw Error('RR 目标病例身份已变化，未读取');
        const result=await options.onSelection(target,guard);if(!guard.isCurrent())return false;
        if(result===false||result?.located===false)throw Error(result?.reason||'所选精确目标已失效，未显示波形');
        if(result===true||result?.located===true){locatedIndex=index;selectionPhase='ready';locationMessage=`已精确定位终搏样本 ${target.sample_index}`;}
        else{selectionPhase='pending';locationMessage='已请求所选原始波形，等待波形核对';}
        if(locateController===ticket)locateController=null;render();if(focus)host.querySelector('[data-rr-row-index="'+index+'"]')?.focus({preventScroll:true});return true;
      }catch(problem){if(guard.isCurrent()){if(locateController===ticket)locateController=null;selectionPhase='error';locationMessage=problem.message||'原始波形读取未完成，可重试';render();if(focus)host.querySelector('[data-rr-row-index="'+index+'"]')?.focus({preventScroll:true});}return false;}
    }
    async function locate(index){
      if(typeof options.onSelection==='function')return select(index,'pointer',{force:selectionPhase!=='loading',focus:true});
      if(phase!=='ready'||!response||!current())return;
      const item=response.items[index];if(!item||item.target===null)return;
      locateController?.abort();const ticket=new AbortController();locateController=ticket;
      const run=generation,focusRun=++locateGeneration;
      const guard=Object.freeze({signal:ticket.signal,isCurrent:()=>run===generation&&focusRun===locateGeneration&&current()&&!ticket.signal.aborted});
      const target=Object.freeze({...item.target,case_token:context.caseToken});
      try{
        assertIdentity(target,context);
        if(target.case_id!==context.caseId||target.caseId!==context.caseId)throw Error('RR 目标病例身份已变化，未定位');
        if(typeof options.onLocate!=='function')throw Error('尚未连接精确波形定位');
        const result=await options.onLocate(target,guard);
        if(run!==generation||focusRun!==locateGeneration||!current())return;
        if(result===false||result?.located===false)throw Error(result?.reason||'目标已失效，未定位');
        if(result===true||result?.located===true){locatedIndex=index;locationMessage=`已精确定位终搏样本 ${target.sample_index}`;}
        else{locatedIndex=null;locationMessage='已请求定位，等待波形核对';}
        if(locateController===ticket)locateController=null;render();
      }catch(problem){if(run===generation&&focusRun===locateGeneration&&current()&&!ticket.signal.aborted){if(locateController===ticket)locateController=null;locatedIndex=null;locationMessage=problem.message||'目标已失效，未定位';render();}}
    }
    function rangeFields(){return Object.fromEntries(['start_s','end_s','range_min','range_max'].map(name=>[name,field(name)?.value??query[name]]));}
    function commitBrush(){
      const bins=histogram?.bins;if(!bins?.length||!brush||phase!=='ready')return;
      const first=bins[Math.min(brush.anchor,brush.end)],last=bins[Math.max(brush.anchor,brush.end)];
      void load({range_min:first.start,range_max:last.end,offset:0});
    }
    function pointerBin(event){const canvas=qs('histogram'),g=canvas?._rrGeometry,bins=histogram?.bins;if(!g||!bins?.length)return null;const rect=canvas.getBoundingClientRect();return Math.max(0,Math.min(bins.length-1,Math.floor((event.clientX-rect.left-g.left)/g.width*bins.length)));}
    on('click',event=>{
      const button=event.target.closest?.('[data-rr-action]');
      if(!button){const row=event.target.closest?.('[data-rr-row-index]');if(row&&host.contains(row)&&typeof options.onSelection==='function')void select(Number(row.dataset.rrRowIndex),'pointer',{focus:true});return;}
      if(!host.contains(button))return;
      const action=button.dataset.rrAction;
      if(action==='apply'){event.preventDefault();void load(rangeFields());}
      else if(action==='cancel'){cancel();}
      else if(action==='retry'){void retry();}
      else if(action==='retry-selection'&&selectedIndex!==null){void select(selectedIndex,'pointer',{force:true,focus:true});}
      else if(action==='clear-range'){void load({range_min:null,range_max:null,offset:0});}
      else if(action==='previous'&&phase==='ready'){void load({offset:Math.max(0,query.offset-query.limit)});}
      else if(action==='next'&&phase==='ready'&&query.offset+response.items.length<response.total){void load({offset:query.offset+query.limit});}
      else if(action==='locate'){void locate(Number(button.dataset.rrIndex));}
    });
    on('change',event=>{
      const name=event.target.dataset?.rrField;if(!name)return;
      if(name==='log'){logScale=event.target.checked;drawHistogram();}
      else if(name==='strips'){showStrips=event.target.checked;if(showStrips)void loadStrips();else{stripController?.abort();stripController=null;stripItems.clear();stripsPhase='idle';render();}}
      else if(['mode','pair_type','population','quality','limit'].includes(name))void load({[name]:name==='limit'?Number(event.target.value):event.target.value});
    });
    on('submit',event=>{
      const form=event.target.closest?.('[data-rr-form]');if(!form)return;event.preventDefault();
      if(form.dataset.rrForm==='range')void load(rangeFields());
      else if(form.dataset.rrForm==='page'&&phase==='ready'){const ordinal=Number(field('ordinal')?.value);if(Number.isSafeInteger(ordinal)&&ordinal>=1&&ordinal<=response.total)void load({offset:Math.floor((ordinal-1)/query.limit)*query.limit});else{locationMessage=`请输入 1–${count(response.total)} 的结果序号`;render();}}
    });
    on('pointerdown',event=>{if(event.target!==qs('histogram')||phase!=='ready')return;const index=pointerBin(event);if(index===null)return;brush={anchor:index,end:index,pointerId:event.pointerId};keyboardBin=index;event.target.setPointerCapture?.(event.pointerId);event.preventDefault();drawHistogram();});
    on('pointermove',event=>{if(!brush||event.target!==qs('histogram')||event.pointerId!==brush.pointerId)return;const index=pointerBin(event);if(index!==null){brush.end=index;keyboardBin=index;drawHistogram();}});
    on('pointerup',event=>{if(!brush||event.target!==qs('histogram')||event.pointerId!==brush.pointerId)return;const index=pointerBin(event);if(index!==null)brush.end=index;event.target.releasePointerCapture?.(event.pointerId);commitBrush();});
    on('pointercancel',()=>{brush=null;drawHistogram();});
    on('keydown',event=>{
      const row=event.target.closest?.('[data-rr-row-index]');
      if(row&&host.contains(row)&&typeof options.onSelection==='function'&&phase==='ready'&&['ArrowUp','ArrowDown','Home','End'].includes(event.key)){
        event.preventDefault();const indexes=response.items.map((item,index)=>item.target!==null?index:null).filter(index=>index!==null);
        if(!indexes.length)return;const before=selectedIndex??Number(row.dataset.rrRowIndex),position=Math.max(0,indexes.indexOf(before));
        const next=event.key==='Home'?indexes[0]:event.key==='End'?indexes.at(-1):indexes[Math.max(0,Math.min(indexes.length-1,position+(event.key==='ArrowUp'?-1:1)))];
        void select(next,'keyboard',{focus:true});return;
      }
      if(event.target!==qs('histogram')||phase!=='ready'||!histogram?.bins.length)return;
      if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){
        event.preventDefault();const before=keyboardBin;keyboardBin=event.key==='Home'?0:event.key==='End'?histogram.bins.length-1:Math.max(0,Math.min(histogram.bins.length-1,keyboardBin+(event.key==='ArrowLeft'?-1:1)));
        if(event.shiftKey){if(!brush)brush={anchor:before,end:keyboardBin};else brush.end=keyboardBin;}else brush={anchor:keyboardBin,end:keyboardBin};
        drawHistogram();
      }else if(event.key==='Enter'||event.key===' '){event.preventDefault();if(!brush)brush={anchor:keyboardBin,end:keyboardBin};commitBrush();}
      else if(event.key==='Escape'){event.preventDefault();brush=null;void load({range_min:null,range_max:null,offset:0});}
    });
    function cancel(){abort('cancel');response=null;phase=current()?'cancelled':'inactive';render();}
    function retry(){return load();}
    function snapshot(){
      if(!current()){abort();phase='inactive';response=null;histogram=null;render();}
      return {context:{...context},phase,query:{...query},total:response?.total??null,matched_count:response?.total??null,offset:query.offset,limit:query.limit,items:response?.items?response.items.map(item=>({...item})):[],rows:response?.items?response.items.map(item=>({...item})):[],summary:response?.summary?{...response.summary}:null,error,generation,stripsPhase,locationMessage,selectedIndex,selectedTarget:selectedIndex===null?null:response?.items?.[selectedIndex]?.target??null,selectionPhase};
    }
    function dispose(){abort('dispose');disposed=true;for(const [type,handler]of listeners)host.removeEventListener(type,handler);resizeObserver?.disconnect();host.innerHTML='';host.classList?.remove('rr-review-workbench');}
    const resizeObserver=typeof root.ResizeObserver==='function'?new root.ResizeObserver(()=>{drawHistogram();if(showStrips)renderRows();}):null;resizeObserver?.observe(host);
    render();
    return {load,cancel,retry,dispose,snapshot,select,retrySelection:()=>selectedIndex===null?Promise.resolve(false):select(selectedIndex,'pointer',{force:true,focus:true})};
  }
  const api={mount,normalizeQuery,normalizeBasis,assertIdentity,validateResponse,metric};root.ECGRRReview=api;if(typeof module!=='undefined')module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
