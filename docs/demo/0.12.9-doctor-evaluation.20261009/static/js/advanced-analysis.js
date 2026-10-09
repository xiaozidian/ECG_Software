"use strict";
globalThis.ECGAdvancedAnalysis=(()=>{
  // Retain one live panel, never patient data for an unbounded set of cases.
  let retained=null;
  const signature=x=>JSON.stringify(x,(_,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.keys(v).sort().map(k=>[k,v[k]])):v);
  function mountRetained(host,{sessionKey,contextCurrent,...config}){
    const key=signature(sessionKey),optionsKey=signature(config.options||{});
    if(retained?.key===key&&retained.optionsKey===optionsKey){host.replaceWith(retained.host);return retained.controller;}
    const session={key,optionsKey,host,contextCurrent};retained=session;
    session.controller=mount(host,{...config,
      isCurrent:()=>retained===session&&contextCurrent()&&host.isConnected&&(!config.isCurrent||config.isCurrent()),
      onChange:options=>{session.optionsKey=signature(options);config.onChange(options);}
    });
    return session.controller;
  }
  const pending=()=>Boolean(retained?.contextCurrent()&&retained.controller?.pending());
  function assertApplied(){
    if(!pending())return;
    const panel=retained.host.querySelector('.am-panel');if(panel)panel.open=true;
    throw Error('研究测量有未应用修改或正在计算。请回到“报告 → 报告”的研究测量区，计算并复核，或明确放弃修改后再保存、预览或导出。');
  }
  function clear(){retained=null;}
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const titles={qtd:'QT 离散度',vcg:'推导 VCG',twa:'T 波电交替',sap:'ECG 呼吸暂停筛查',hrt:'HRT / DC'};
  const value=x=>x==null?'—':String(x);
  const seconds=s=>Number(s).toFixed(1)+' s';
  function plot(points,{title='',markers=[],xy=false,other=null}={}){
    const valid=points.filter(p=>Number.isFinite(p.x)&&Number.isFinite(p.y));
    if(!valid.length)return '<p>无可绘制数据</p>';
    const all=other?valid.concat(other):valid;
    let xmin=Math.min(0,...all.map(p=>p.x)),xmax=Math.max(1,...all.map(p=>p.x)),ymin=Math.min(0,...all.map(p=>p.y)),ymax=Math.max(1,...all.map(p=>p.y));
    if(xy){const bound=Math.max(Math.abs(xmin),Math.abs(xmax),Math.abs(ymin),Math.abs(ymax));xmin=ymin=-bound;xmax=ymax=bound;}
    const w=xy?260:650,h=xy?260:180,px=x=>45+(x-xmin)/(xmax-xmin)*(w-60),py=y=>h-30-(y-ymin)/(ymax-ymin)*(h-50);
    const path=pts=>{let pen=false;return pts.map(p=>{if(!Number.isFinite(p.y)){pen=false;return '';}const cmd=pen?'L':'M';pen=true;return cmd+px(p.x).toFixed(2)+' '+py(p.y).toFixed(2)}).join(' ')};
    const svg=`<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(title)}"><title>${esc(title)}</title><path d="M45 20V${h-30}H${w-15}" stroke="#647882" fill="none"/><path d="M45 ${py(0)}H${w-15}" stroke="#d8e2e7"/><path d="${path(points)}" fill="none" stroke="#173b4f" stroke-width="1.4"/>${other?`<path d="${path(other)}" fill="none" stroke="#0a7676" stroke-width="1.4" stroke-dasharray="5 3"/>`:''}${markers.filter(Number.isFinite).map((m,i)=>`<path d="M${px(m)} 20V${h-30}" stroke="#a45c0a" stroke-dasharray="3 3"/><text x="${px(m)+3}" y="15" font-size="11">${i?'T终点':'Q起点'}</text>`).join('')}<g fill="#3c525f" font-size="11"><text x="43" y="${h-10}">${xmin.toFixed(0)}</text><text x="${w-15}" y="${h-10}" text-anchor="end">${xmax.toFixed(0)}</text><text x="40" y="25" text-anchor="end">${ymax.toPrecision(3)}</text><text x="40" y="${h-32}" text-anchor="end">${ymin.toPrecision(3)}</text></g></svg>`;
    return xy?svg:`<div class="am-plot-scroll" tabindex="0" role="region" aria-label="${esc(title)}，可横向滚动">${svg}</div>`;
  }
  function mount(host,{options={},duration,compute,onChange,onPrint,onLocate,isCurrent=()=>host.isConnected}){
    if(globalThis.__CARDIOINSIGHT_UPLOADED_CASE__){host.innerHTML='<p class="am-boundary">QTd / VCG / TWA / ECG 呼吸筛查需本地工作台的原始采样计算。此纯静态演示未提供计算服务，不以预设数值替代。</p>';return;}
    let result=null,derivatives=null,tab='qtd',lead='II',busy=false,requestId=0,edited=false,hrtPage=0,hrtEvent=null;
    let current=JSON.parse(JSON.stringify(options));
    host.innerHTML=`<details class="am-panel"><summary>研究指标测量与复核 · QTd / VCG / TWA / ECG 筛查 / HRT / DC</summary><div class="am-body"><p class="am-boundary">研究与软件验证用途。自动结果未经临床验证，不生成确诊、风险等级或 AHI。VLP 所需高频信息不在当前 200 Hz 采集中。</p><form class="am-form"><fieldset><legend>QT / VCG / TWA 原始信号片段</legend><label>起点（记录后秒数）<input name="start_s" type="number" min="0" max="${Math.max(0,duration-1)}" step="1" value="${esc(current.start_s||0)}" required></label><label>分析时长（秒）<input name="duration_s" type="number" min="30" max="600" step="1" value="${esc(current.duration_s||300)}" required></label><p>自动 QT 使用片段内最多 64 个完整正常搏；TWA 使用连续 128 搏窗口。短记录按实际范围分析。</p></fieldset><fieldset><legend>ECG 周期性 RR 变化筛查</legend><label>起点（记录后秒数）<input name="sap_start_s" type="number" min="0" max="${Math.max(0,duration-1)}" value="${esc(current.sap_start_s||0)}" required></label><label>终点（留空＝记录末尾）<input name="sap_end_s" type="number" min="1" max="${duration}" value="${esc(current.sap_end_s??'')}"></label><p>5 分钟窗；范围需由医生确认，软件不推断睡眠。HRT / DC 使用全程有效正常间期。</p></fieldset><fieldset class="am-calibration"><legend>导联与幅度依据（可选）</legend><label class="am-check"><input name="use_estimate" type="checkbox" ${current.voltage_estimate?'checked':''}>使用顶部当前估算系数（非设备校准）</label><p data-am-estimate>选择后点击计算，复制当时的系数；顶部切换不改写已有结果。</p><label class="am-check"><input name="standard_leads" type="checkbox" ${current.standard_leads?'checked':''}>已核实通道为标准 I、II、V1–V6 电极位置与相同增益（仅用于启用推导 VCG）</label><label>统一系数（µV / 设备单位；留空＝未校准）<input name="uv_per_unit" type="number" min="0.000001" max="10000" step="any" value="${esc(current.voltage_estimate?'':(current.uv_per_unit??''))}"></label><label>设备校准依据<input name="calibration_note" maxlength="300" value="${esc(current.voltage_estimate?'':(current.calibration_note||''))}" placeholder="设备规格或校准记录，不是显示增益"></label></fieldset><div class="am-actions"><button type="submit">计算并复核</button><button type="button" data-reset-markers>清除人工端点并重算</button></div></form><p class="am-status" role="status" aria-live="polite">按需计算；不会修改原始 ECG 或心搏诊断。设置随报告草稿保存。</p><div class="am-results" hidden><nav aria-label="研究测量类型">${Object.entries(titles).map(([k,t])=>`<button type="button" data-am-tab="${k}" aria-pressed="${k===tab}">${t}</button>`).join('')}</nav><div class="am-content"></div></div></div></details>`;
    const form=host.querySelector('form'),status=host.querySelector('.am-status'),content=host.querySelector('.am-content');
    form.querySelector('.am-actions').insertAdjacentHTML('beforeend','<button type="button" data-discard-settings hidden>放弃未计算修改</button>');
    const discard=host.querySelector('[data-discard-settings]');
    status.textContent='按需计算；计算成功的设置才随报告草稿保存。未计算输入仅暂存在本窗口，不修改原始 ECG 或心搏诊断。';
    function restore(){
      for(const [name,fallback] of [['start_s',0],['duration_s',300],['sap_start_s',0],['sap_end_s','']])form.elements[name].value=current[name]??fallback;
      form.elements.use_estimate.checked=Boolean(current.voltage_estimate);form.elements.standard_leads.checked=Boolean(current.standard_leads);
      form.elements.uv_per_unit.value=current.voltage_estimate?'':(current.uv_per_unit??'');form.elements.calibration_note.value=current.voltage_estimate?'':(current.calibration_note||'');
      edited=false;discard.hidden=true;lock(false);host.querySelector('.am-results').hidden=!result||!isCurrent();
      if(result&&isCurrent())render();
      status.textContent=isCurrent()?'已放弃未应用修改，恢复上次已计算设置；未进行过计算时恢复初始设置。':'已放弃未应用修改；当前依据已失效，旧结果保持隐藏。请载入最新版本后重新核对并计算。';
    }
    discard.onclick=()=>{if(!busy)restore();};
    function read(){const estimate=form.elements.use_estimate.checked?globalThis.ECGVoltage?.snapshot():null;if(form.elements.use_estimate.checked&&!estimate)throw Error('请先在顶部开启估算电压，或取消使用估算系数');return {...current,voltage_estimate:estimate,start_s:Number(form.elements.start_s.value),duration_s:Number(form.elements.duration_s.value),sap_start_s:Number(form.elements.sap_start_s.value),sap_end_s:form.elements.sap_end_s.value===''?null:Number(form.elements.sap_end_s.value),standard_leads:form.elements.standard_leads.checked,uv_per_unit:estimate?estimate.uv_per_unit:(form.elements.uv_per_unit.value===''?null:Number(form.elements.uv_per_unit.value)),calibration_note:estimate?ECGVoltage.note(estimate):form.elements.calibration_note.value};}
    function lock(on){busy=on;host.querySelectorAll('button,input,select').forEach(el=>el.disabled=on);if(!on){form.elements.uv_per_unit.disabled=form.elements.calibration_note.disabled=form.elements.use_estimate.checked;}host.setAttribute('aria-busy',String(on));}
    async function calculate(next){
      if(busy)return;
      if(!isCurrent()){host.querySelector('.am-results').hidden=true;status.textContent='当前页面或分析依据已变化，请先处理未应用修改，并载入最新版本后重新计算。';return;}
      const id=++requestId;lock(true);host.querySelector('.am-results').hidden=true;status.textContent='正在读取原始样本并计算；请稍候…';
      try{
        const payload=await compute(next);if(id!==requestId)return;
        if(!isCurrent()){status.textContent='页面或分析依据已变化，本次结果未应用。输入仍在本窗口暂存，返回后请重新计算。';return;}
        result=payload.advanced;derivatives=payload.derivatives;current=result.options;
        edited=false;discard.hidden=true;
        onChange(current);host.querySelector('.am-results').hidden=false;
        status.textContent=`计算完成 · 依据 ${result.basis} · ${result.calibration} · 当前报告使用此组参数；是否已保存以报告保存状态为准。`;
        render();
      }catch(error){if(id===requestId)status.textContent='未完成：'+error.message+'；输入已保留，可重试。';}
      finally{if(id===requestId)lock(false);}
    }
    form.onsubmit=e=>{e.preventDefault();if(busy||!form.reportValidity())return;let next;try{next=read();}catch(error){status.textContent=error.message;return;}if(next.start_s!==(current.start_s||0)||next.duration_s!==(current.duration_s||300)){next.markers={};next.marker_basis='';}calculate(next);};
    host.querySelector('[data-reset-markers]').onclick=()=>{if(form.reportValidity()){try{calculate({...read(),markers:{},marker_basis:''});}catch(error){status.textContent=error.message;}}};
    host.querySelectorAll('[data-am-tab]').forEach(button=>button.onclick=()=>{if(edited){status.textContent='请先应用本导联端点或放弃修改，再切换测量类型。';return;}tab=button.dataset.amTab;render();});
    // Unsaved settings must not leave an old result looking current or printable.
    lock(false);form.oninput=()=>{if(busy)return;edited=true;discard.hidden=false;lock(false);host.querySelector('.am-results').hidden=true;status.textContent='参数尚未计算，仅在本窗口暂存。筛选和子页往返会保留输入；请计算并复核，或放弃修改后再保存、预览或导出。';};
    function render(){
      if(!isCurrent()){host.querySelector('.am-results').hidden=true;status.textContent='分析依据已变化，请载入最新版本后重新计算。';return;}
      host.querySelectorAll('[data-am-tab]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.amTab===tab)));
      const r=result[tab];
      if(tab==='hrt'){
        content.innerHTML=['hrt','dc'].map(k=>{const d=derivatives?.[k]||{},points=d.tachogram||d.prsa||[],ready=points.some(p=>Number.isFinite(p.x)&&Number.isFinite(p.y));return `<section><h3>${k.toUpperCase()} · ${ready?'全程平均曲线':'数据条件不足'}</h3><p>${k==='hrt'?`合格室早 ${esc(value(d.eligible_pvc))} · TO ${esc(value(d.to_pct))} % · TS ${esc(value(d.ts_ms_per_rr))} ms/RR`:`锚点 ${esc(value(d.anchor_count))} · DC ${esc(value(d.dc_ms))} ms`}</p><p class="am-aggregate-note">${k==='hrt'?'合格室早的平均 RR 响应；横轴为室早后 RR 序号，纵轴 ms。'+(Array.isArray(d.source_events)?'逐事件源位置可在下表回看，不改变平均指标。':'当前未提供逐事件曲线或原始时间定位。'):'锚点对齐的平均 RR 曲线；横轴为相对锚点 RR 序号，纵轴 ms。'}</p>${ready?plot(points,{title:k.toUpperCase()+' 平均 RR 曲线 · RR 序号 / ms'}):'<p class="am-empty-evidence">没有可用平均曲线。指标空缺不解释为零或阴性。</p>'}<details class="am-method"><summary>算法与质控口径</summary><p>${esc(d.method||'当前服务未提供方法说明。')}</p></details><button type="button" data-am-print="${k}">单独打印 / 保存 PDF</button></section>`}).join('');
        const events=derivatives?.hrt?.source_events;
        if(Array.isArray(events)&&events.length){
          hrtPage=Math.min(hrtPage,Math.ceil(events.length/20)-1);
          const first=hrtPage*20,chosen=events[hrtEvent];
          content.insertAdjacentHTML('beforeend',`<section class="am-hrt-source"><h3>合格室早源证据 · ${events.length} 个事件</h3><p>位置来自 EBI 源采样索引，时间按当前 200 Hz 输入契约换算（设备采样率仍待核验）；逐事件 TO 为计算证据，不解释为风险等级。</p>${chosen?`<p>源采样 ${chosen.sample_index} · 记录后 ${seconds(chosen.time_s)} · 逐事件 TO ${value(chosen.to_pct)} %</p>${plot(chosen.rr_ms.map((y,i)=>({x:i+1,y})),{title:'逐事件恢复 RR · RR 序号 / ms'})}<button type="button" data-am-locate="${chosen.time_s}" data-am-raw>回看该室早连续波形</button>`:''}<div class="am-table-scroll"><table><thead><tr><th>源采样 / 记录后秒</th><th>逐事件 TO %</th><th>证据</th></tr></thead><tbody>${events.slice(first,first+20).map((e,i)=>`<tr><td>${e.sample_index} / ${seconds(e.time_s)}</td><td>${value(e.to_pct)}</td><td><button type="button" data-am-hrt-event="${first+i}" aria-pressed="${hrtEvent===first+i}">恢复曲线</button> <button type="button" data-am-locate="${e.time_s}" data-am-raw>连续波形</button></td></tr>`).join('')}</tbody></table></div><div class="am-actions"><button type="button" data-am-hrt-page="-1" ${hrtPage===0?'disabled':''}>上一页源事件</button><span>${first+1}–${Math.min(first+20,events.length)} / ${events.length}</span><button type="button" data-am-hrt-page="1" ${first+20>=events.length?'disabled':''}>下一页源事件</button></div></section>`);
          content.querySelectorAll('[data-am-hrt-event]').forEach(b=>b.onclick=()=>{if(!isCurrent())return;hrtEvent=Number(b.dataset.amHrtEvent);render();});
          content.querySelectorAll('[data-am-hrt-page]').forEach(b=>b.onclick=()=>{if(!isCurrent())return;hrtPage+=Number(b.dataset.amHrtPage);render();});
        }else if(Array.isArray(events))content.insertAdjacentHTML('beforeend','<p class="am-empty-evidence">无合格源室早事件，未提供源位置跳转；不补造时间。</p>');
      }else{
        content.innerHTML=`<header><h3>${titles[tab]} · ${r.status==='research'?'研究测量':'数据条件不足'}</h3><button type="button" data-am-print="${tab}">单独打印 / 保存 PDF</button></header><p>${esc(r.reason)}</p><details class="am-method"><summary>算法、质控与解释边界</summary><p>${esc(r.method)}</p></details>`;
        if(tab==='qtd'){
          content.insertAdjacentHTML('beforeend',`<p>合格心搏 ${r.beat_count} · 有效导联 ${r.valid_leads||0} · QTd ${value(r.qtd_ms)} ms · QTcB 离散度 ${value(r.qtc_bazett_dispersion_ms)} ms · QTcF 离散度 ${value(r.qtc_fridericia_dispersion_ms)} ms</p>`);
          if(r.leads.length){
            const row=r.leads.find(x=>x.lead===lead)||r.leads[0];lead=row.lead;
            content.insertAdjacentHTML('beforeend',`<label>复核导联<select data-am-lead>${r.leads.map(l=>`<option ${l.lead===lead?'selected':''}>${l.lead}</option>`).join('')}</select></label><div class="am-qt-wave">${plot(row.points,{title:lead+' 中位心搏，横轴相对 R ms，纵轴设备单位',markers:row.valid?[row.q_ms,row.t_ms]:[]})}</div><p>${esc(lead+' · '+row.reason)} · 横轴相对 R 峰 ms；纵轴设备单位。</p><div class="am-endpoints"><label>QRS 起点（ms）<input data-q type="number" min="-180" max="-5" step="5" value="${row.q_ms??row.automatic.q_ms??-50}"></label><label>T 波终点（ms）<input data-t type="number" min="100" max="600" step="5" value="${row.t_ms??row.automatic.t_ms??400}"></label><button type="button" data-apply-qt>应用本导联端点</button><button type="button" data-exclude-qt>排除本导联</button><button type="button" data-auto-qt>恢复本导联自动端点</button></div><div class="am-table-scroll" tabindex="0" role="region" aria-label="逐导联 QT 测量"><table><thead><tr><th>导联</th><th>QT ms</th><th>QTcB ms</th><th>QTcF ms</th><th>端点状态</th></tr></thead><tbody>${r.leads.map(l=>`<tr class="${l.lead===lead?'am-current-lead':''}"><td><button type="button" data-am-row-lead="${esc(l.lead)}" aria-pressed="${l.lead===lead}">${esc(l.lead)}</button></td><td>${value(l.qt_ms)}</td><td>${value(l.qtc_bazett_ms)}</td><td>${value(l.qtc_fridericia_ms)}</td><td>${esc(l.reason)}</td></tr>`).join('')}</tbody></table></div>`);
            function selectLead(next){if(!isCurrent()){host.querySelector('.am-results').hidden=true;status.textContent='分析依据已变化，请载入最新版本后重新计算。';return false;}if(edited||busy){status.textContent='请先应用本导联端点或放弃修改，再切换导联。';return false;}lead=next;render();return true;}
            content.querySelector('[data-am-lead]').onchange=e=>{if(!selectLead(e.target.value))e.target.value=lead;};
            content.querySelectorAll('[data-am-row-lead]').forEach(b=>b.onclick=()=>{if(selectLead(b.dataset.amRowLead))content.querySelector('[data-am-lead]').focus();});
            for(const selector of ['[data-q]','[data-t]'])content.querySelector(selector).oninput=()=>{edited=true;discard.hidden=false;status.textContent='人工端点尚未应用。请应用本导联端点或放弃修改，再保存或导出。';};
            const apply=m=>calculate({...current,marker_basis:result.basis,markers:{...current.markers,[lead]:m}});
            content.querySelector('[data-apply-qt]').onclick=()=>{const q=content.querySelector('[data-q]'),t=content.querySelector('[data-t]');if(q.reportValidity()&&t.reportValidity())apply({q_ms:Number(q.value),t_ms:Number(t.value)});};
            content.querySelector('[data-exclude-qt]').onclick=()=>apply({exclude:true});
            content.querySelector('[data-auto-qt]').onclick=()=>{const markers={...current.markers};delete markers[lead];calculate({...current,markers});};
          }
        }
        if(tab==='vcg')content.insertAdjacentHTML('beforeend',`<p>峰值模长 ${value(r.peak_magnitude)} ${esc(r.unit||'')} · 未采集高频信息不会通过变换恢复。</p><div class="am-vcg">${r.loops.map(p=>`<figure><figcaption>${esc(p.title)} · ${esc(r.unit)}</figcaption>${plot(p.points,{title:p.title,xy:true})}</figure>`).join('')}</div>`);
        if(tab==='twa'){
          const best=r.windows[0];
          content.insertAdjacentHTML('beforeend',`<p>检测窗口 ${r.tested_windows} · 合格窗口/导联 ${r.windows.length} · 幅度 ${esc(r.unit)}。K 为频谱比值；— 表示噪声方差不足，不代表阴性。</p>${best?`<p>最大幅度组合 ${best.lead} · 记录后 ${seconds(best.start_s)}–${seconds(best.end_s)}</p>${plot(best.even,{title:'偶数（实线）/ 奇数（虚线）ST-T 均值；横轴 ms',other:best.odd})}<p>实线：偶数搏；虚线：奇数搏；横轴相对 R（ms），纵轴 ${esc(r.unit)}。</p><div class="am-table-scroll" tabindex="0"><table><thead><tr><th>导联 / 起点</th><th>交替幅度</th><th>噪声</th><th>K</th><th>复核</th></tr></thead><tbody>${r.windows.map(w=>`<tr><td>${w.lead} / ${seconds(w.start_s)}</td><td>${w.amplitude}</td><td>${w.noise}</td><td>${value(w.k_score)}</td><td><button data-am-locate="${w.start_s}">回看</button></td></tr>`).join('')}</tbody></table></div>`:''}`);
        }
        if(tab==='sap')content.insertAdjacentHTML('beforeend',`<p>可分析 ${r.valid_minutes} 分钟 · 周期性变化候选 ${r.candidate_windows} 个 5 分钟窗（不是呼吸暂停次数）</p><div class="am-table-scroll" tabindex="0"><table><thead><tr><th>范围（记录后秒）</th><th>结果</th><th>周期 s / 自相关</th><th>复核</th></tr></thead><tbody>${r.windows.map(w=>`<tr><td>${seconds(w.start_s)}–${seconds(w.end_s)}</td><td>${w.valid?(w.candidate?'周期性变化候选':'未达工程阈值'):esc(w.reason)}</td><td>${value(w.period_s)} / ${value(w.autocorrelation)}</td><td><button data-am-locate="${w.start_s}">回看</button></td></tr>`).join('')||'<tr><td colspan="4">不足一个完整 5 分钟窗</td></tr>'}</tbody></table></div>`);
      }
      content.querySelectorAll('[data-am-print]').forEach(b=>b.onclick=()=>{if(!isCurrent()){host.querySelector('.am-results').hidden=true;status.textContent='分析依据已变化，请载入最新版本后重新计算。';return;}if(edited||busy){status.textContent='请先应用修改或放弃修改，再打印研究测量。';return;}onPrint(b.dataset.amPrint,{advanced:result,...derivatives});});
      content.querySelectorAll('[data-am-locate]').forEach(b=>b.onclick=()=>{if(isCurrent())onLocate(Number(b.dataset.amLocate),{raw:b.hasAttribute?.('data-am-raw')||false});else{host.querySelector('.am-results').hidden=true;status.textContent='分析依据已变化，请载入最新版本后重新计算。';}});
    }
    return {pending:()=>edited||busy};
  }
  return {mount,mountRetained,plot,pending,assertApplied,clear};
})();
if(typeof window!=='undefined')window.addEventListener('beforeunload',event=>{if(ECGAdvancedAnalysis.pending()){event.preventDefault();event.returnValue='';}});
