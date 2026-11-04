"use strict";
(root=>{
  const titles={cover:'封面',summary:'首页报告',hourly:'小时统计表格',scatter:'散点图',st_trend:'ST 分析',t_trend:'T 波趋势图',event_strips:'事件图条',st_events:'ST-T 事件与复核',pacing:'起搏报告',af:'房颤 / 房扑',hrv_time:'HRV 时域报告',hrv_frequency:'HRV 频域报告',hrv_overview:'HRV 概述',hrt:'心率震荡 (HRT)',qtd:'QT 离散度 (QTd)',vcg:'心电向量 (VCG)',dc:'心率减速力 (DC)',twa:'T 波电交替 (TWA)',vlp:'心室晚电位 (VLP)',sap:'睡眠窒息 (SAP)'};
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
  function sttStatus(automatic={}){
    const q=automatic.quality||{},coverage=typeof q.coverage_pct==='number'&&Number.isFinite(q.coverage_pct)?q.coverage_pct:null;
    let code,label,note;
    if(!automatic.enabled){code='not_evaluated';label='未评估';note='筛查尚未运行或缺少输入；不能解释为未检出或正常。';}
    else if(!q.eligible_blocks||coverage===null||coverage<=0){code='not_evaluable';label='不可评估';note='没有通过质量门槛的可评估数据；零候选不能解释为正常。';}
    else if(automatic.items?.length){code='pending_review';label='事件待复核';note='研究筛查候选须回看原始波形；不生成自动诊断。';}
    else{code='no_findings';label='已评估范围未检出';note='在通过质量门槛的范围内未检出持续性候选；不代表确认正常。';}
    if(coverage!==null&&coverage<100&&automatic.enabled)note+=' 未覆盖或被排除的区间仍需独立评估。';
    return {code,label,coverage_pct:coverage,note,can_assert_normal:false};
  }
  const stLeads=['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6'];
  function stReportEvents(index,family='ST'){
    const result=[];
    for(const e of index.events){
      if(e.category!=='ST'||(e.stt_review_state??(e.diagnosis_status==='confirmed'?'reviewed':'unreviewed'))!=='reviewed'||e.stt_evidence_stale)continue;
      const p=e.stt_event_evidence||{},start=e.time_s,end=e.end_s??start;
      if(!(family==='T'?['t_wave_inversion']:['st_depression','st_elevation']).includes(p.kind)||end-start<60-1e-9||['no_change','artifact','indeterminate','nonspecific'].includes(e.stt_result_code))continue;
      const leads=e.stt_review_receipt?.leads?.length?e.stt_review_receipt.leads:p.leads?.length?p.leads:stLeads.includes(e.lead)?[e.lead]:[];
      for(const lead of leads){
        const m=(p.metrics||[]).find(r=>r.lead===lead)||{},depressed=p.kind==='st_depression',anchor=m[depressed?'minimum_st_sample':'maximum_st_sample']??null;
        result.push({event_id:e.event_id,record_id:e.event_id,row_id:e.event_id+':'+lead,basis_version:e.basis_version,label:e.label||'',lead,kind:p.kind,result_code:e.stt_result_code??null,review_state:'reviewed',start_s:start,end_s:end,duration_s:Math.round((end-start)*1000)/1000,leads:[lead],peak_deviation_units:p.peak_deviation_units??null,peak_time_s:p.peak_time_s??null,source:p.source||'physician_selected_range',review_status:'confirmed',continuous_target_s:p.continuous_target_s??null,measurement_protocol:p.measurement_protocol??null,units:'source_device_units',slope:null,calibrated_mm:null,mean_st_level_units:m.mean_st_level_units??null,extreme_st_level_units:m[depressed?'minimum_st_level_units':'maximum_st_level_units']??null,extreme_st_time_s:anchor===null?null:anchor/200,extreme_st_sample:anchor,minimum_st_sample:m.minimum_st_sample??null,maximum_st_sample:m.maximum_st_sample??null,minimum_st_level_units:m.minimum_st_level_units??null,maximum_st_level_units:m.maximum_st_level_units??null,reference_sample:m.reference_sample??null,reference_st_level_units:m.reference_st_level_units??null,mean_t_amplitude_units:m.mean_t_amplitude_units??null,extreme_t_amplitude_units:m.extreme_t_amplitude_units??null,extreme_t_time_s:m.extreme_t_sample==null?null:m.extreme_t_sample/200,t_reference_units:p.t_reference_units??null,used_beat_count:m[family==='T'?'t_used_count':'used_count']??null,coverage:p.coverage??null,boundary_resolution_s:p.boundary_resolution_s??16});
      }
    }
    return result;
  }
  function stReviewNotes(index){return index.events.filter(e=>e.category==='ST'&&!e.stt_report_eligibility?.table).map(e=>({event_id:e.event_id,basis_version:e.basis_version,label:e.label??'ST-T 复核',start_s:e.time_s,end_s:e.end_s??e.time_s,review_kind:e.stt_review_receipt?.review_extent==='whole'?'whole_review':e.range_statistics?'range_mean':'point_or_legacy_range',review_status:e.stt_review_state??e.diagnosis_status??'pending',review_state:e.stt_review_state??null,result_code:e.stt_result_code??null,report_group:e.stt_report_group??null,note:e.note??'',physician_note:e.stt_physician_note??e.note??'',measurement_protocol:e.stt_review_receipt?.measurement_protocol??null}));}
  function stIntervalUnion(intervals){const merged=[];for(const [a,b] of [...intervals].sort((a,b)=>a[0]-b[0]||a[1]-b[1])){if(b<=a)continue;if(merged.length&&a<=merged.at(-1)[1])merged.at(-1)[1]=Math.max(b,merged.at(-1)[1]);else merged.push([a,b]);}return merged;}
  function stSummary(rows){
    const clinical=root.ECGClinicalAnalysis||(typeof require==='function'?require('./clinical-analysis.js'):null),groups=[];
    for(const e of [...rows].sort((a,b)=>a.start_s-b.start_s||a.end_s-b.end_s||(String(a.lead||'')<String(b.lead||'')?-1:String(a.lead||'')>String(b.lead||'')?1:0))){
      let g=[...groups].reverse().find(g=>e.start_s<g.end_s&&clinical.sttCanonical(e.measurement_protocol)===clinical.sttCanonical(g.measurement_protocol));
      if(!g){g={start_s:e.start_s,end_s:e.end_s,events:[],measurement_protocol:e.measurement_protocol??null};groups.push(g);}g.events.push(e);g.end_s=Math.max(g.end_s,e.end_s);
    }
    const unique=values=>[...new Set(values)].sort(),result=groups.map(g=>{const {events,...base}=g,intervals=stIntervalUnion(events.map(e=>[e.start_s,e.end_s])),ids=unique(events.map(e=>e.row_id??e.event_id));return {...base,group_id:'stt-time-group:'+clinical.sttDigest([ids,g.measurement_protocol]).slice(0,24),child_event_ids:ids,record_event_ids:unique(events.map(e=>e.event_id)),leads:unique(events.filter(e=>e.lead).map(e=>e.lead)),directions:unique(events.map(e=>e.kind??null)),span_s:g.end_s-g.start_s,union_duration_s:intervals.reduce((s,[a,b])=>s+b-a,0),support_intervals:intervals};});
    return {confirmed_lead_event_count:rows.length,confirmed_record_count:new Set(rows.map(e=>e.event_id)).size,confirmed_time_group_count:result.length,confirmed_union_duration_s:stIntervalUnion(rows.map(r=>[r.start_s,r.end_s])).reduce((s,[a,b])=>s+b-a,0),groups:result,denominator:'full_record_confirmed_events_not_report_selection',clinical_episode_count:null};
  }
  function reportHeartRate(rows,duration){const total=Math.max(0,Number(duration)||0),counts=Array(Math.ceil(total/60)).fill(0);for(const row of rows){if(row.class_code==='X')continue;const time=row.sample_index/200;if(time>=0&&time<total)counts[Math.floor(time/60)]++;}return counts.map((n,i)=>{const start=i*60,end=Math.min(total,(i+1)*60);return {start_s:start,end_s:end,time_s:(start+end)/2,detected_beat_count:n,hr:n?Math.round(n*60/(end-start)*100)/100:null};});}
  function evidence(index,st={}){
    const rows=quality.qrsRows(index.rows).map(r=>({...r,time_s:r.sample_index/200})).sort((a,b)=>a.sample_index-b.sample_index),af=index.events.filter(e=>e.category==='AF'),points=[],counts={},valid=quality.intervalMask(rows);
    rows.forEach((r,i)=>{if(['P','PA','PV','PD','PF'].includes(r.class_code))counts[r.class_code]=(counts[r.class_code]||0)+1;if(i&&valid[i-1]&&valid[i])points.push({x:rows[i-1].rr_ms,y:r.rr_ms})});
    const af_summary=index.duration_s>0?quality.rhythmSummary(quality.rhythmEpisodes(af),index.duration_s):null;
    const stEvents=stReportEvents(index),tEvents=stReportEvents(index,'T'),stride=Math.max(1,Math.ceil(points.length/8000));return {st_evaluation:sttStatus(st.automatic_candidates),sections:catalog(),scatter:{points:points.filter((_,i)=>i%stride===0),total:points.length,stride},pacing:{counts,total:Object.values(counts).reduce((a,b)=>a+b,0),method:'仅统计当前起搏类型标记；不检测夺获失败、感知异常或器械故障。'},af_summary,af:af.map(e=>({time_s:e.time_s,end_s:e.end_s,label:e.label,status:e.rhythm_status||e.diagnosis_status})),st_trends:Object.fromEntries(stLeads.map(lead=>[lead,(st.analysis?.trends?.leads?.[lead]||[]).map(p=>({...p,...(p.eligible===false||p.axis_shift_suspected?{st_level_units:null,reference_units:null,deviation_units:null,t_amplitude_units:null,t_reference_units:null}:{})}))])),st_events:stEvents,t_events:tEvents,st_summary:stSummary(stEvents),t_summary:stSummary(tEvents),st_representatives:[],st_review_notes:stReviewNotes(index),st_measurement_protocol:(root.ECGClinicalAnalysis||(typeof require==='function'?require('./clinical-analysis.js'):null)).sttProtocol({measurement_ms:60,extent:'whole'}),units:'source_device_units',st_trend_resolution_s:60,heart_rate_trend:reportHeartRate(rows,index.duration_s),heart_rate_method:'current_detected_nonartifact_beats_per_actual_60s_bin_support',...derivatives(rows,af.map(e=>[e.time_s,e.end_s]))};
  }
  function rhythmParagraphs(s){
    if(!s||!(s.denominator_s>0))return ['记录时长未提供，无法计算房颤 / 房扑负荷；不以 0 代替缺失数据。'];
    return ['confirmed_af','confirmed_afl'].map((key,i)=>{const r=s[key];return `已确认${i?'房扑':'房颤'}：${r.count} 段，${r.seconds.toFixed(3)} 秒；占记录时长 ${r.pct.toFixed(2)}%。`;}).concat(
      `分母：完整记录 ${s.denominator_s.toFixed(3)} 秒；确认房颤 / 房扑合并去重 ${s.confirmed_any.seconds.toFixed(3)} 秒（${s.confirmed_any.pct.toFixed(2)}%）。`,
      `待复核 ${s.pending_any.count} 段，不计入确认负荷。同类及合并统计分别按时间并集去重，房颤与房扑时长不能直接相加。`);
  }
  const finite=x=>typeof x==='number'&&Number.isFinite(x);
  function sttNumber(x,digits=2){if(!finite(x))return '—';const scale=10**digits,v=Math.round(x*scale)/scale;return v===0?'0':String(v);}
  function sttDuration(x){return finite(x)?`${sttNumber(x/60)} 分（${sttNumber(x,3)} 秒）`:'—';}
  function sttClock(meta,x){const text=ECGReportPaper.clock(meta,finite(x)?x:0);return /^\d{4}-\d{2}-\d{2} /.test(text)?text.slice(5):text;}
  function sttUnit(e){return ['mV','µV','μV'].includes(e.st_units)&&e.st_calibration_verified===true?e.st_units:'u';}
  function sttUse(composition,row,purpose){
    const id=row.selection_event_id||row.event_id;
    if(Object.hasOwn(composition,'stt_report_use'))return (composition.stt_report_use||[]).some(p=>p.event_id===id&&p.basis_version===row.basis_version&&p[purpose]===true);
    return (composition.selected_events||[]).some(p=>p.event_id===id&&p.basis_version===row.basis_version&&(purpose!=='text'||p.referenced_in_report===true));
  }
  function sttKind(r,family){return ({st_depression:'ST压低',st_elevation:'ST抬高',t_wave_inversion:'T改变',t_change:'T改变'})[r.kind||r.result_kind]||(family==='T'?'T改变':'ST改变');}
  function sttProtocol(e){const p=e.st_measurement_protocol||{},ms=p.measurement_ms??p.st_measurement_ms;return [finite(ms)?(ms===0?'STJ':`ST${ms}`):'测量点见复核记录','逐分钟完整证据；缺失处断线'].join(' · ');}
  function sttSummaryLines(e,composition,family='ST'){
    const all=family==='T'?(e.t_events||[]):(e.st_events||[]),s=family==='T'?(e.t_summary||{}):(e.st_summary||{});
    return [`${family}全记录已确认：导联事件 ${sttNumber(s.confirmed_lead_event_count??all.length,0)}，去重时段 ${sttNumber(s.confirmed_time_group_count,0)}，累计 ${sttDuration(s.confirmed_union_duration_s)}`,
      `本次选用明细 ${all.filter(r=>sttUse(composition,r,'table')).length} / ${all.length} 行；统计独立于图条选择。`];
  }
  function sttTrendDocument(model,key){
    const e=model.evidence||{},composition=model.report?.composition||{},meta=model.case.metadata||{},family=key==='t_trend'?'T':'ST',unit=sttUnit(e);
    const metric=family==='T'?'t_amplitude_units':composition.stt_trend_metric==='delta'?'deviation_units':'st_level_units';
    const metricLabel=family==='T'?'T幅度':metric==='deviation_units'?'ΔST（相对参考）':'ST电平（相对ISO）';
    const trendRows=stLeads.map(lead=>{const input=e.st_trends?.[lead]||[],points=input.map(p=>({x:finite(p.time_s)?p.time_s/3600:null,y:p.eligible===false||p.axis_shift_suspected||!finite(p[metric])?null:p[metric]}));return {lead,points,valid_minutes:points.filter(p=>finite(p.y)).length,total_minutes:input.length};});
    const heart=(e.heart_rate_trend||[]).map(p=>({x:finite(p.time_s)?p.time_s/3600:null,y:p.eligible===false||!finite(p.hr??p.bpm)||(p.hr??p.bpm)<=0?null:(p.hr??p.bpm)}));
    const extent=Math.max(0,...stLeads.flatMap(lead=>(e.st_trends?.[lead]||[]).map(p=>finite(p.end_s)?p.end_s:finite(p.time_s)?p.time_s:0)),...heart.filter(p=>finite(p.x)).map(p=>p.x*3600));
    const duration=model.case.technical?.duration_seconds_raw??e.st_duration_s??extent,xmax=finite(duration)&&duration>0?duration/3600:1;
    const roles=family==='T'?[]:metric==='deviation_units'?['reference','delta_peak']:['reference','st_min','st_max'],labels={reference:metric==='deviation_units'?'ΔST参考搏':'实际参考搏',st_min:'最深ST电平',st_max:'最高ST电平',delta_peak:'最大ΔST'};
    const reps=e.st_representatives||[];
    return {key,title:family==='T'?'十二导联 T 波幅度趋势':'十二导联 ST 分析',paragraphs:[`${metricLabel} · ${unit}${unit==='u'?'（电压未标定）':''}`,sttProtocol(e)],charts:[],rows:[],layout:'stt_trend',metric,metric_label:metricLabel,unit,x_max:xmax,
      time_ticks:Array.from({length:7},(_,i)=>({x:xmax*i/6,label:sttClock(meta,xmax*i/6*3600).replace(/:\d{2}$/,'')})),trend_rows:trendRows,heart_rate:heart,
      summary_lines:sttSummaryLines(e,composition,family),representatives:roles.map(role=>{const rep=reps.find(r=>r.role===role&&(metric!=='deviation_units'||r.metric==='deviation_units'));return rep?{...rep,role,label:rep.label||labels[role],clock:finite(rep.time_s)?sttClock(meta,rep.time_s):'—'}:{role,label:labels[role],lead:null,time_s:null,clock:'—',waveform:null};})};
  }
  function sttEventDocuments(model){
    const e=model.evidence||{},composition=model.report?.composition||{},meta=model.case.metadata||{},unit=sttUnit(e),docs=[];
    for(const family of ['ST','T']){
      const all=family==='ST'?(e.st_events||[]):(e.t_events||[]),chosen=all.filter(r=>sttUse(composition,r,'table'));
      if(family==='T'&&!chosen.length)continue;
      const columns=['导联','类型','起止时间','持续时间',`平均${family} (${unit})`,`极值${family} (${unit})`,family==='ST'?`最大ΔST (${unit})`:`最大ΔT (${unit})`,...(family==='ST'?['斜率']:[])];
      const rows=chosen.map(r=>({event_id:r.event_id,basis_version:r.basis_version,row_id:r.row_id||r.event_id,cells:[r.lead||(r.leads||[]).join('/')||'—',sttKind(r,family),`${sttClock(meta,r.start_s)}\n${sttClock(meta,r.end_s)}`,sttDuration(r.duration_s),sttNumber(family==='ST'?r.mean_st_level_units:r.mean_t_amplitude_units),sttNumber(family==='ST'?r.extreme_st_level_units:r.extreme_t_amplitude_units),sttNumber(r.peak_deviation_units),...(family==='ST'?[finite(r.slope)&&r.slope_unit?sttNumber(r.slope)+' '+r.slope_unit:'—']:[])]}));
      for(let i=0;i<Math.max(1,rows.length);i+=24){const part=rows.slice(i,i+24);docs.push({key:'st_events',title:`${family}事件明细${i?'（续）':''}`,paragraphs:[...sttSummaryLines(e,composition,family),`完整事件起止独立于代表图条；幅度 ${unit}${unit==='u'?'，非mV':''}；— 表示未提供可靠测量。`],charts:[],rows:part.length?part.map(r=>r.cells.join(' · ')):[`当前没有选用的已确认${family}事件；不表示正常或已排除。`],layout:'stt_table',columns,table_rows:part});}
    }
    const textRecords=new Map();for(const r of [...(e.st_review_notes||[]),...(e.st_events||[]),...(e.t_events||[])]){const k=r.event_id+'|'+r.basis_version;if(!textRecords.has(k))textRecords.set(k,r);}
    const notes=[...textRecords.values()].filter(r=>sttUse(composition,r,'text'));
    if(notes.length){
      const lines=notes.flatMap(r=>ECGReportPaper.wrapText(`${sttClock(meta,r.start_s)} — ${sttClock(meta,r.end_s)} · ${r.label||'ST-T复核'}${(r.physician_note??r.note)?' · '+(r.physician_note??r.note):''}${r.range_statistics||r.review_kind==='range_mean'?' · 范围均值；此范围不证明连续ST事件。':!r.stt_event_evidence&&r.review_kind==='point_or_legacy_range'?' · 点复核／旧范围；此范围不证明连续ST事件。':''}`,70));
      for(let i=0;i<lines.length;i+=28)docs.push({key:'st_events',title:'ST-T复核说明'+(i?'（续）':''),paragraphs:i?[]:['本次采用的复核意见；未见改变、伪差及无法判读不计入已确认异常事件。'],charts:[],rows:lines.slice(i,i+28)});
    }
    return docs;
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
      if(key==='st_trend'||key==='t_trend')pages.push(sttTrendDocument(model,key));
      if(key==='st_events')pages.push(...sttEventDocuments(model));
      if(['hrv_time','hrv_frequency'].includes(key)){if(!d)throw Error('HRV 数据尚未加载');const periods=['full','day','night'].map(k=>d.periods[k]);add(key,[d.method,...(d.hrv_review?[`fixed-300s-fft-compat-v1 · HRV r${d.hrv_review.hrv_revision} / ${d.hrv_review.digest.slice(0,12)} · ${d.hrv_review.confirmation?.valid?'医生已声明核实本窗口节律与伪差':'本窗口窦性与信号质量尚未核实'}`]:[]),'日间 / 夜间按记录钟点分段，不代表实际清醒 / 睡眠；— 表示数据不足。'],periods.map(p=>({title:p.label+(key==='hrv_time'?' · RR ms / 频数':' · Hz / ms²/Hz'),bars:key==='hrv_time',points:(key==='hrv_time'?p.histogram:p.psd).map(q=>({x:key==='hrv_time'?q.rr_ms:q.hz,y:key==='hrv_time'?q.count:q.power}))})),periods.flatMap(p=>[p.label,key==='hrv_time'?`NN ${p.nn_count}；SDNN ${val(p.sdnn_ms)} ms；SDANN ${val(p.sdann_ms)} ms；rMSSD ${val(p.rmssd_ms)} ms；pNN50 ${val(p.pnn50_pct)} %`:`总功率 ${val(p.frequency.total_ms2)}；VLF ${val(p.frequency.vlf_ms2)}；LF ${val(p.frequency.lf_ms2)}；HF ${val(p.frequency.hf_ms2)} ms²；LF/HF ${val(p.frequency.lf_hf)}`]));}
    }return pages;
  }
  const sttEscape=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function sttPath(points,x,y){let pen=false,path='';for(const p of points){if(!finite(p.x)||!finite(p.y)){pen=false;continue;}path+=(pen?'L':'M')+x(p.x).toFixed(3)+' '+y(p.y).toFixed(3)+' ';pen=true;}return path.trim();}
  function sttTrendSvg(doc){
    const width=760,left=58,right=12,top=8,hrHeight=50,rowHeight=42,axisHeight=28,height=top+hrHeight+doc.trend_rows.length*rowHeight+axisHeight,plot=width-left-right,x=v=>left+v/doc.x_max*plot;
    const bound=Math.max(1,...doc.trend_rows.flatMap(r=>r.points.filter(p=>finite(p.y)).map(p=>Math.abs(p.y)))),hrBound=Math.max(200,...doc.heart_rate.filter(p=>finite(p.y)).map(p=>p.y));
    const row=(label,points,y0,h,lo,hi)=>{
      const y=v=>y0+h-4-(v-lo)/(hi-lo)*(h-8),valid=points.filter(p=>finite(p.x)&&finite(p.y)),path=sttPath(points,x,y),zero=lo<=0&&hi>=0?`<line x1="${left}" x2="${width-right}" y1="${y(0)}" y2="${y(0)}" stroke="#aaa" stroke-width=".5" stroke-dasharray="2 3"/>`:'';
      return `<g data-stt-trend-lead="${sttEscape(label)}"><rect x="${left}" y="${y0}" width="${plot}" height="${h}" fill="none" stroke="#444" stroke-width=".55"/><text x="2" y="${y0+h/2+4}" font-size="13">${sttEscape(label)}</text><text x="${left-5}" y="${y0+10}" text-anchor="end" font-size="8.5">${sttNumber(hi)}</text><text x="${left-5}" y="${y0+h-2}" text-anchor="end" font-size="8.5">${sttNumber(lo)}</text>${zero}${doc.time_ticks.map(t=>`<line x1="${x(t.x)}" x2="${x(t.x)}" y1="${y0}" y2="${y0+h}" stroke="#ccc" stroke-width=".4"/>`).join('')}${path?`<path d="${path}" fill="none" stroke="#111" stroke-width=".8"/>`:''}${valid.length===1?`<circle cx="${x(valid[0].x)}" cy="${y(valid[0].y)}" r="1.25" fill="#111"/>`:''}${!valid.length?`<text x="${left+8}" y="${y0+h/2+3}" font-size="10">无有效测量</text>`:''}</g>`;
    };
    const content=row('心率',doc.heart_rate,top,hrHeight,0,hrBound)+doc.trend_rows.map((r,i)=>row(r.lead,r.points,top+hrHeight+i*rowHeight,rowHeight,-bound,bound)).join('');
    return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="十二导联${sttEscape(doc.metric_label)}及同轴心率趋势" data-stt-metric="${doc.metric}" data-stt-lead-count="${doc.trend_rows.length}" xmlns="http://www.w3.org/2000/svg">${content}${doc.time_ticks.map((t,i)=>`<text x="${x(t.x)}" y="${height-7}" text-anchor="${i===0?'start':i===doc.time_ticks.length-1?'end':'middle'}" font-size="10">${sttEscape(t.label)}</text>`).join('')}</svg>`;
  }
  function sttRepresentativeHtml(rep,unit){
    const wave=rep.waveform,lead=rep.lead||Object.keys(wave?.leads||{})[0],values=wave?.leads?.[lead],valid=Array.isArray(values)?values.filter(finite):[];
    let graph='<p class="rp-stt-representative-empty">暂无真实代表搏</p>';
    if(valid.length>1&&finite(wave.start_s)&&finite(wave.duration_s)&&wave.duration_s>0){
      const lo=Math.min(...valid),hi=Math.max(...valid),span=Math.max(1,hi-lo),points=values.map((v,i)=>({x:i/Math.max(1,values.length-1),y:finite(v)?v:null})),x=v=>8+v*224,y=v=>76-(v-lo)/span*62,path=sttPath(points,x,y);
      const anchor=finite(rep.time_s)?(rep.time_s-wave.start_s)/wave.duration_s:null;
      graph=`<svg viewBox="0 0 240 90" role="img" aria-label="真实${sttEscape(rep.label)}" data-source-start="${wave.start_s}" data-source-duration="${wave.duration_s}" data-source-r-sample="${rep.sample_index??''}" xmlns="http://www.w3.org/2000/svg"><rect x="1" y="1" width="238" height="88" fill="none" stroke="#999" stroke-width=".6"/><path d="${path}" fill="none" stroke="#111" stroke-width="1"/>${anchor!==null&&anchor>=0&&anchor<=1?`<line x1="${x(anchor)}" x2="${x(anchor)}" y1="4" y2="84" stroke="#666" stroke-width=".6" stroke-dasharray="2 2"/>`:''}</svg>`;
    }
    return `<section class="rp-stt-representative" data-stt-representative="${sttEscape(rep.role)}"><h3>${sttEscape(rep.label)}</h3><p>${sttEscape(lead||'—')} · ${sttEscape(rep.clock)} · ${sttEscape(unit)}</p>${graph}</section>`;
  }
  function sttHospitalHtml(doc){
    const header=`<h2>${sttEscape(doc.title)}</h2><div class="rp-stt-method">${doc.paragraphs.map(p=>`<p>${sttEscape(p)}</p>`).join('')}</div>`;
    if(doc.layout==='stt_trend')return header+`<figure class="rp-stt-trend-figure">${sttTrendSvg(doc)}</figure><div class="rp-stt-summary">${doc.summary_lines.map(s=>`<p>${sttEscape(s)}</p>`).join('')}</div>${doc.representatives.length?`<div class="rp-stt-representatives" style="--stt-representative-count:${doc.representatives.length}">${doc.representatives.map(r=>sttRepresentativeHtml(r,doc.unit)).join('')}</div>`:''}`;
    return header+`<table class="rp-stt-event-table"><thead><tr>${doc.columns.map(c=>`<th>${sttEscape(c)}</th>`).join('')}</tr></thead><tbody>${doc.table_rows.length?doc.table_rows.map(r=>`<tr data-stt-event-id="${sttEscape(r.event_id)}" data-stt-row-id="${sttEscape(r.row_id)}">${r.cells.map(c=>`<td>${sttEscape(c).replace(/\n/g,'<br>')}</td>`).join('')}</tr>`).join(''):`<tr><td colspan="${doc.columns.length}">${sttEscape(doc.rows[0])}</td></tr>`}</tbody></table>`;
  }
  function pages(model,keys){const esc=sttEscape;return documents(model,keys).map(doc=>doc.layout?ECGReportPaper.shell(model,sttHospitalHtml(doc),'stt'):ECGReportPaper.shell(model,`<h2>${esc(doc.title)}</h2>${doc.paragraphs.map(p=>`<p class="rp-method">${esc(p)}</p>`).join('')}${doc.charts.map(c=>`<section class="rp-supplement-chart ${c.xy?'rp-vector-chart':''}"><h3>${esc(c.title)}</h3>${c.xy||c.markers?ECGAdvancedAnalysis.plot(c.points,c):c.scatter?scatterSvg(c.points):ECGHrvReport.plot(c.points,'x','y',{xmin:Math.min(0,...c.points.map(p=>p.x)),xmax:c.title.includes('Hz /')?.5:c.title.includes('RR ms / 频数')?2000:null,bars:c.bars,height:135,unit:c.title})}</section>`).join('')}<div class="rp-supplement-rows">${doc.rows.map(r=>`<p>${esc(r)}</p>`).join('')||(!doc.charts.length?'<p>本页未列出的项目不代表正常或已排除。</p>':'')}</div>`,'supplement')).join('')}
  function scatterSvg(points){const max=Math.max(2000,...points.flatMap(p=>[p.x,p.y]));return `<svg viewBox="0 0 560 530" role="img" aria-label="相邻 RR 散点，毫秒"><path d="M50 20V480H510M50 480L510 20" fill="none" stroke="#999"/><text x="10" y="15">RR(i+1) · ${max} ms</text><text x="360" y="515">RR(i) · ${max} ms</text><text x="30" y="495">0</text>${points.map(p=>`<circle cx="${50+p.x/max*460}" cy="${480-p.y/max*460}" r=".65" fill="#222"/>`).join('')}</svg>`}
  const api={sttStatus,catalog,selectedPages,validate,derivatives,evidence,stReportEvents,stReviewNotes,stSummary,rhythmParagraphs,documents,pages,sttUse,sttTrendDocument,sttEventDocuments};root.ECGReportSections=api;if(typeof module!=='undefined')module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
