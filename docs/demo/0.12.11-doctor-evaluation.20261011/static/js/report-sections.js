"use strict";
(root=>{
  const titles={cover:'封面',summary:'首页报告',hourly:'小时统计表格',scatter:'散点图',st_trend:'ST 趋势图',t_trend:'T 波趋势图',event_strips:'事件图条',st_events:'ST 事件',pacing:'起搏报告',af:'房颤 / 房扑',hrv_time:'HRV 时域报告',hrv_frequency:'HRV 频域报告',hrv_overview:'HRV 概述',hrt:'心率震荡 (HRT)',qtd:'QT 离散度 (QTd)',vcg:'心电向量 (VCG)',dc:'心率减速力 (DC)',twa:'T 波电交替 (TWA)',vlp:'心室晚电位 (VLP)',sap:'睡眠窒息 (SAP)'};
  Object.assign(titles,{qtd:'QT 离散度（研究测量）',vcg:'推导心电向量（研究）',twa:'T 波电交替（研究测量）',sap:'睡眠呼吸暂停相关 ECG 筛查（非诊断）'});
  const blocked={vlp:'200 Hz 输入不能覆盖晚电位高频带宽；插值无法补足采集信息'};
  const reason=key=>blocked[key]||(root.__CARDIOINSIGHT_UPLOADED_CASE__&&['qtd','vcg','twa','sap'].includes(key)?'需本地原始采样计算；纯静态演示不运行此算法':'');
  const catalog=()=>Object.entries(titles).map(([key,title])=>({key,title,available:!reason(key),reason:reason(key)}));
  const selectedPages=c=>c.page_selection_version===1?[...(c.included_pages||[])]:['summary','hourly','event_strips',...(c.include_hrv?['hrv_time','hrv_overview']:[])];
  function validate(c){const pages=selectedPages(c);if(!pages.length)throw Error('请至少选择一类报告页');for(const k of pages)if(!titles[k]||reason(k))throw Error(`${titles[k]||k}：${reason(k)||'不支持的报告页'}`);return pages;}
  const quality=root.ECGRRQuality||(typeof require==='function'?require('./rr-quality.js'):null);
  function derivatives(input,excluded=[]){
    const rows=quality.qrsRows(input),valid=quality.intervalMask(rows,excluded);
    const normal=i=>valid[i]&&rows[i-1].class_code==='N'&&rows[i].class_code==='N'&&rows[i].rr_ms>=300&&rows[i].rr_ms<=2000,bad=[0],jumps=[0];
    rows.forEach((r,i)=>{const prev=rows[i-1]?.rr_ms;bad.push(bad.at(-1)+Number(!normal(i)));jumps.push(jumps.at(-1)+Number(Number.isFinite(prev)&&prev>0&&Number.isFinite(r.rr_ms)&&Math.abs(r.rr_ms/prev-1)>.2+1e-12))});
    const segment=(a,b)=>bad[b]===bad[a]&&jumps[b]===jumps[a+1],onsets=[],tach=[],sourceEvents=[];
    for(let i=5;i<rows.length-21;i++){
      if(rows[i].class_code!=='V'||!segment(i-5,i)||!segment(i+2,i+22)||rows[i+1].class_code!=='N'||!valid[i]||!valid[i+1])continue;
      const beforeRows=rows.slice(i-5,i),base=beforeRows.reduce((s,r)=>s+r.rr_ms,0)/5,c=rows[i].rr_ms,p=rows[i+1].rr_ms;
      if(!(300<=c&&c<base*.8&&base*1.2<p&&p<=3000))continue;
      const sinus=beforeRows.concat(rows.slice(i+2,i+22)).map(r=>r.rr_ms);
      if(sinus.some((v,j)=>j&&Math.abs(v-sinus[j-1])>200))continue;
      if(sinus.some((v,j)=>j>=5&&Math.abs(v/(sinus.slice(j-5,j).reduce((s,x)=>s+x,0)/5)-1)>.2+1e-12))continue;
      const before=rows[i-2].rr_ms+rows[i-1].rr_ms;
      onsets.push(100*(rows[i+2].rr_ms+rows[i+3].rr_ms-before)/before);tach.push(rows.slice(i+2,i+17).map(r=>r.rr_ms));
      sourceEvents.push({sample_index:rows[i].sample_index,time_s:rows[i].sample_index/200,start_sample:rows[i-5].sample_index,end_sample:rows[i+21].sample_index,to_pct:Math.round(onsets.at(-1)*1e4)/1e4,rr_ms:[...tach.at(-1)]});
    }
    const average=tach.length?Array.from({length:15},(_,i)=>tach.reduce((s,r)=>s+r[i],0)/tach.length):[],slopes=average.length?Array.from({length:11},(_,i)=>average.slice(i,i+5).reduce((s,v,j)=>s+(j-2)*v,0)/10):[];
    const sums=Array(60).fill(0);let anchors=0;
    for(let i=30;i<rows.length-29;i++){if(!segment(i-30,i+30))continue;const d=rows[i].rr_ms/rows[i-1].rr_ms-1;if(!(0<d&&d<=.05+1e-12))continue;anchors++;for(let j=0;j<60;j++)sums[j]+=rows[i+j-30].rr_ms;}
    const prsa=anchors?sums.map(v=>v/anchors):[],round=x=>Math.round(x*1e4)/1e4;
    return {hrt:{source_events:sourceEvents,eligible_pvc:onsets.length,to_pct:onsets.length>=5?round(onsets.reduce((a,b)=>a+b,0)/onsets.length):null,ts_ms_per_rr:onsets.length>=5?round(Math.max(...slopes)):null,tachogram:average.map((y,i)=>({x:i+1,y:round(y)})),method:'HRT 研究性计算：孤立 V，前 5 / 后 20 个正常间期；排除完整间期与房颤/房扑区间的交集、伪差及不连续数据；正常间期相邻差≤200 ms，恢复间期相对前5个正常间期均值偏差≤20%。TO 为逐事件均值，TS 为平均恢复序列前 15 间期内 5 点最大回归斜率。少于 5 个合格事件不报 TO/TS；不输出风险等级。'},dc:{anchor_count:anchors,dc_ms:anchors>=20?round((prsa[30]+prsa[31]-prsa[29]-prsa[28])/4):null,prsa:prsa.map((y,i)=>({x:i-30,y:round(y)})),method:'DC 研究性 PRSA：T=1，L=30；减速锚点增幅 0–5%，只用连续正常 N-N、排除异常节律区段。DC=(X0+X1-X-1-X-2)/4；少于 20 个锚点不报告值。阈值为软件质量控制，不是诊断标准。'}};
  }
  function evidence(index,st={}){
    const rows=quality.qrsRows(index.rows).map(r=>({...r,time_s:r.sample_index/200})).sort((a,b)=>a.sample_index-b.sample_index),af=index.events.filter(e=>e.category==='AF'),points=[],counts={},valid=quality.intervalMask(rows);
    rows.forEach((r,i)=>{if(['P','PA','PV','PD','PF'].includes(r.class_code))counts[r.class_code]=(counts[r.class_code]||0)+1;if(i&&valid[i-1]&&valid[i])points.push({x:rows[i-1].rr_ms,y:r.rr_ms})});
    const af_summary=index.duration_s>0?quality.rhythmSummary(quality.rhythmEpisodes(af),index.duration_s):null;
    const stride=Math.max(1,Math.ceil(points.length/8000));return {sections:catalog(),scatter:{points:points.filter((_,i)=>i%stride===0),total:points.length,stride},pacing:{counts,total:Object.values(counts).reduce((a,b)=>a+b,0),method:'仅统计当前起搏类型标记；不检测夺获失败、感知异常或器械故障。'},af_summary,af:af.map(e=>({time_s:e.time_s,end_s:e.end_s,label:e.label,status:e.rhythm_status||e.diagnosis_status})),st_trends:st.analysis?.trends?.leads||{},st_events:st.automatic_candidates?.items||[],...derivatives(rows,af.map(e=>[e.time_s,e.end_s]))};
  }
  function rhythmParagraphs(s){
    if(!s||!(s.denominator_s>0))return ['记录时长未提供，无法计算房颤 / 房扑负荷；不以 0 代替缺失数据。'];
    return ['confirmed_af','confirmed_afl'].map((key,i)=>{const r=s[key];return `已确认${i?'房扑':'房颤'}：${r.count} 段，${r.seconds.toFixed(3)} 秒；占记录时长 ${r.pct.toFixed(2)}%。`;}).concat(
      `分母：完整记录 ${s.denominator_s.toFixed(3)} 秒；确认房颤 / 房扑合并去重 ${s.confirmed_any.seconds.toFixed(3)} 秒（${s.confirmed_any.pct.toFixed(2)}%）。`,
      `待复核 ${s.pending_any.count} 段，不计入确认负荷。同类及合并统计分别按时间并集去重，房颤与房扑时长不能直接相加。`);
  }
  function documents(model,keys){
    const e=model.evidence||{},d=model.hrv,pages=[],val=x=>x==null?'—':String(x),meta=model.case.metadata||{},clock=t=>ECGReportPaper.clock(meta,t),add=(key,paragraphs=[],charts=[],rows=[])=>{const wrapped=rows.flatMap(row=>ECGReportPaper.wrapText(row,70));for(let i=0;i<Math.max(1,wrapped.length);i+=28)pages.push({key,title:titles[key]+(i?'（续）':''),paragraphs:i?[]:paragraphs,charts:i?[]:charts,rows:wrapped.slice(i,i+28)})};
    for(const key of keys){
      if(['qtd','vcg','twa','sap'].includes(key)){if(!e.advanced?.documents?.[key])throw Error('研究测量尚未计算，请先在本地工作台计算');pages.push(...e.advanced.documents[key]);continue;}
      if(key==='cover')add(key,['动态心电图检测报告',`检查记录：${(model.case.display_case_id||model.case.case_id)}`,`记录时间：${clock(0)}`,`记录时长：${meta.duration_text||'—'}`,'研究与软件验证输出。请由医生核对分析统计、原始波形与诊断结论。']);
      if(key==='scatter')add(key,[`相邻 RR 配对 ${val(e.scatter?.total)} 个；图中等间隔抽取 1/${val(e.scatter?.stride)} 显示，统计保留全量。`],[{title:'Lorenz RR(i) / RR(i+1) · ms',points:e.scatter?.points||[],scatter:true}]);
      if(key==='pacing')add(key,[e.pacing?.method||'无可用数据'],[],Object.entries(e.pacing?.counts||{}).map(([k,n])=>`${k} 起搏标记：${n} 搏`).concat(`起搏类型总标记数：${val(e.pacing?.total)} 搏；— 表示未提供，0 不等同排除起搏器。`));
      if(key==='af')add(key,[...rhythmParagraphs(e.af_summary),'片段确认与报告整体审核是独立状态；自动 RR 不规则筛查不等同房颤诊断。','本页仅汇总已保存片段，不证明全程已评估；无片段或未提示不能排除房颤，未评估时段须回看原始波形。'],[],(e.af||[]).map(r=>`${clock(r.time_s)} · ${((r.end_s-r.time_s)/60).toFixed(2)} 分钟 · ${r.label} · ${r.status==='confirmed'?'医生确认':'待复核'}`));
      if(key==='hrt'||key==='dc'){const r=e[key]||{};add(key,[r.method||'无可用数据',key==='hrt'?`合格室早 ${val(r.eligible_pvc)}；TO ${val(r.to_pct)} %；TS ${val(r.ts_ms_per_rr)} ms/RR`:`减速锚点 ${val(r.anchor_count)}；DC ${val(r.dc_ms)} ms`,'— 表示样本不足或无可用结果，不代表正常。'],[{title:key==='hrt'?'平均恢复 RR · ms / 序号':'PRSA · RR ms / 相对锚点',points:(key==='hrt'?r.tachogram:r.prsa)||[]}]);}
      if(key==='st_trend'||key==='t_trend'){const leads=Object.entries(e.st_trends||{});if(!leads.length)add(key,['当前没有可用的 ST-T 研究性测量数据；不能解释为正常。']);for(let i=0;i<leads.length;i+=3)add(key,['设备单位，非 mV；未校准的研究性趋势，空缺不补线，不生成缺血或复极诊断。'],leads.slice(i,i+3).map(([lead,points])=>({title:lead+' · '+titles[key]+' / 相对小时',points:points.map(p=>({x:p.time_s/3600,y:key==='st_trend'?p.deviation_units:p.t_amplitude_units}))})));}
      if(key==='st_events')add(key,['ST-T 研究性候选清单，未确认诊断；幅度单位为设备单位，非 mV。'],[],(e.st_events||[]).map(r=>`${clock(r.start_s||0)} · ${r.type||r.label||'ST-T 候选'} · ${(r.leads||[]).join('/')} · ${val(r.duration_s)} 秒 · 偏移 ${val(r.peak_deviation_units)}`));
      if(['hrv_time','hrv_frequency'].includes(key)){if(!d)throw Error('HRV 数据尚未加载');const periods=['full','day','night'].map(k=>d.periods[k]);add(key,[d.method,'日间 / 夜间按记录钟点分段，不代表实际清醒 / 睡眠；— 表示数据不足。'],periods.map(p=>({title:p.label+(key==='hrv_time'?' · RR ms / 频数':' · Hz / ms²/Hz'),bars:key==='hrv_time',points:(key==='hrv_time'?p.histogram:p.psd).map(q=>({x:key==='hrv_time'?q.rr_ms:q.hz,y:key==='hrv_time'?q.count:q.power}))})),periods.flatMap(p=>[p.label,key==='hrv_time'?`NN ${p.nn_count}；SDNN ${val(p.sdnn_ms)} ms；SDANN ${val(p.sdann_ms)} ms；rMSSD ${val(p.rmssd_ms)} ms；pNN50 ${val(p.pnn50_pct)} %`:`总功率 ${val(p.frequency.total_ms2)}；VLF ${val(p.frequency.vlf_ms2)}；LF ${val(p.frequency.lf_ms2)}；HF ${val(p.frequency.hf_ms2)} ms²；LF/HF ${val(p.frequency.lf_hf)}`]));}
    }return pages;
  }
  function pages(model,keys){const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));return documents(model,keys).map(doc=>ECGReportPaper.shell(model,`<h2>${esc(doc.title)}</h2>${doc.paragraphs.map(p=>`<p class="rp-method">${esc(p)}</p>`).join('')}${doc.charts.map(c=>`<section class="rp-supplement-chart ${c.xy?'rp-vector-chart':''}"><h3>${esc(c.title)}</h3>${c.xy||c.markers?ECGAdvancedAnalysis.plot(c.points,c):c.scatter?scatterSvg(c.points):ECGHrvReport.plot(c.points,'x','y',{xmin:Math.min(0,...c.points.map(p=>p.x)),xmax:c.title.includes('Hz /')?.5:c.title.includes('RR ms / 频数')?2000:null,bars:c.bars,height:135,unit:c.title})}</section>`).join('')}<div class="rp-supplement-rows">${doc.rows.map(r=>`<p>${esc(r)}</p>`).join('')||(!doc.charts.length?'<p>本页未列出的项目不代表正常或已排除。</p>':'')}</div>`,'supplement')).join('')}
  function scatterSvg(points){const max=Math.max(2000,...points.flatMap(p=>[p.x,p.y]));return `<svg viewBox="0 0 560 530" role="img" aria-label="相邻 RR 散点，毫秒"><path d="M50 20V480H510M50 480L510 20" fill="none" stroke="#999"/><text x="10" y="15">RR(i+1) · ${max} ms</text><text x="360" y="515">RR(i) · ${max} ms</text><text x="30" y="495">0</text>${points.map(p=>`<circle cx="${50+p.x/max*460}" cy="${480-p.y/max*460}" r=".65" fill="#222"/>`).join('')}</svg>`}
  const api={catalog,selectedPages,validate,derivatives,evidence,rhythmParagraphs,documents,pages};root.ECGReportSections=api;if(typeof module!=='undefined')module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
