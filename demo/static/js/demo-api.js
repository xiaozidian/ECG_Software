"use strict";

/* Browser-only mathematical API. No uploaded or patient dataset is consumed. */
(() => {
  const STT_RHYTHM_POLICY='independent_of_AF_AFL_reviews',STT_ALGORITHM='stt-screening-0.3.2-independent-rhythm',STT_RANGE_PROFILE='raw-200hz-fixed16s-st-perbeat-mean-v2',STT_METHOD='stt-hospital-review-v2';
  const RATE=200,COUNT=1,STORE_KEY=window.__CARDIOINSIGHT_SOURCE_VERSION__?.source_fingerprint?"cardioinsight.math."+window.__CARDIOINSIGHT_SOURCE_VERSION__.source_fingerprint:"cardioinsight-public-math-4314-v2";
  const rawSignalMetadata=()=>({units:'device_unit',unit_label:'设备单位',calibration_verified:false,calibration_note:'u = 设备单位，电压未校准；显示放大不等于 mm/mV 标定。',signal_profile:{id:'data-int16le-8ch-200hz-v1',sample_rate_hz:RATE,channel_count:8,sample_format:'little-endian int16',stored_leads:['I','II','V1','V2','V3','V4','V5','V6'],derived_leads:{III:'II-I',aVR:'-(I+II)/2',aVL:'I-II/2',aVF:'II-I/2'},basis:'当前支持的 DATA 导入格式；采样率与通道映射尚未经设备资料核验',device_verified:false}});
  const TEMPLATE_FAMILIES=new Set(["全部","单发","成对","房速","二联律","三联律(NPN)","三联律(NNP)","连续三发","连续多发","室速","三联律(NPP)","四联律","自定义"]),TEMPLATE_LEADS=new Set(["I","II","III","aVR","aVL","aVF","V1","V2","V3","V4","V5","V6"]);
  const ASSET_BASE="static/demo-data/mathematical-4314";
  const sourceCase=window.__CARDIOINSIGHT_MATHEMATICAL_CASE__;
  if(!sourceCase?.integrity?.mathematical_fixture||sourceCase.simulation_profile?.real_patient_inputs_read!==false)throw new Error("纯数学输入未加载或来源不符合公开演示契约");

  const nativeFetch=window.fetch.bind(window),savedDefault={reports:{},annotations:{},patients:{},templates:{},beatOverrides:{},reviews:{},audit:[]};
  const defaultComposition={schema_version:3,selected_events:[],category_reviews:{},diagnosis_blocks:[],strip_defaults:{leads:["II","V1","V5"],duration_s:7},template:"comprehensive",included_pages:["cover","summary","hourly","event_strips","hrv_time","hrv_overview"],active_page:"summary",preview_mode:"compose",fast_slow_mode:"rr",paper:{size:"A4",orientation:"portrait",show_grid:true,show_labels:true,speed:"25 mm/s",gain:"10 mm/mV"}};
  let saved={...savedDefault};
  try{saved={...savedDefault,...JSON.parse(localStorage.getItem(STORE_KEY)||"{}")} }catch(_){/* unavailable */}
  saved.beatOverrides=saved.beatOverrides||{};
  const persist=()=>{try{localStorage.setItem(STORE_KEY,JSON.stringify(saved))}catch(_){throw new Error("浏览器存储失败，请检查空间/隐私设置；修改未能持久保存");}};
  const copy=value=>JSON.parse(JSON.stringify(value));
  const round=(value,digits=2)=>{if(!Number.isFinite(value))return null;const p=10**digits;return Math.round(value*p)/p};
  const response=(value,status=200)=>new Response(JSON.stringify(value),{status,headers:{"Content-Type":"application/json; charset=utf-8","Cache-Control":"no-store"}});
  const failure=(message,status=400)=>response({error:message},status);
  const requestBody=options=>{const value=options?.body?JSON.parse(options.body):{};if(!value||Array.isArray(value)||typeof value!=="object")throw Error("请求正文必须为 JSON 对象");return value;};
  const number=(value,label,min,max,integer=false)=>{if(typeof value!=="number"||!Number.isFinite(value)||value<min||value>max||integer&&!Number.isInteger(value))throw Error(label+" 超出支持范围");return value;};
  const now=()=>new Date().toISOString().replace("T"," ").slice(0,19);
  const caseId=sourceCase.case_id;
  const duration=Number(sourceCase.technical.duration_seconds_raw);
  let beats=copy(sourceCase.beats),activeEdited=false;
  const engine=globalThis.ECGBeatEngine;
  const editorValue=()=>copy(saved.beatEditor?.[caseId]||{revision:0,document:engine.blank(),undo:[],redo:[]});
  const editedFeed=doc=>({...engine.materialize(sourceCase.beats,doc||editorValue().document,overrideList()),duration,excluded_rhythm_intervals:ECGRRQuality.annotationExclusions(annotationList())});
  function editorSummary(value){
    const feed=editedFeed(value.document),counts={};
    feed.beats.forEach(r=>counts[r.class_code]=(counts[r.class_code]||0)+1);
    return {revision:value.revision,settings:value.document.settings,can_undo:!!value.undo.length,can_redo:!!value.redo.length,types:engine.types,metrics:engine.metrics(feed,duration),hrv:engine.hrv(feed,duration),type_counts:counts,markers:feed.markers,manual_longest:feed.beats.find(r=>r.id===value.document.longest_id)||null,note:"修订位置重算 RR；不生成自动疾病诊断，数学生成心搏 保留不变"};
  }
  async function editorRoute(action,method,payload){
    if(!engine)throw Error("编辑计算模块未加载，请刷新");
    const stored=JSON.parse(localStorage.getItem(STORE_KEY)||"{}");
    saved={...savedDefault,...stored};
    const current=editorValue();
    if(method==="GET")return action.endsWith("/beats")?{items:editedFeed().beats,markers:editedFeed().markers}:editorSummary(current);
    if(!Number.isInteger(payload.revision)||payload.revision!==current.revision)throw Error("编辑版本已变化，请刷新预览");
    const op=payload.operation;
    if(action.endsWith("/preview")){
      if(op==="detect"){
        const start=Number(payload.start_s),seconds=Number(payload.duration_s);
        if(!Number.isFinite(start)||start<0||start>=duration||!Number.isFinite(seconds)||seconds<1||seconds>60)throw Error("搜索范围必须为记录内的 1–60 秒");
        const feed=editedFeed(),buffer=await waveformBuffer(),view=new DataView(buffer),first=Math.round(start*RATE),count=Math.min(Math.round(seconds*RATE),buffer.byteLength/16-first),values=Array.from({length:count},(_,i)=>leadValue(view,first+i,current.document.settings.lead));
        return {revision:current.revision,requires_confirmation:true,candidates:engine.detect(values,first,feed.beats.filter(r=>r.group!==34).map(r=>r.sample_index),current.document.settings),method:"导数平方能量 / MAD 阈值 / 局部峰定位 / 不应期排重；研究候选，须逐一确认"};
      }
      const result=engine.apply(sourceCase.beats,current.document,overrideList(),payload,duration);
      return {affected:result.affected,before:editorSummary(current),after:editorSummary({...current,document:result.document}),requires_confirmation:true};
    }
    if(method!=="PUT"||payload.confirmed!==true)throw Error("请确认预览后再提交");
    const previous=copy(saved);
    try{
      if(["undo","redo"].includes(op)){if(!current[op].length)throw Error("没有可撤销／重做的操作");current[op==="undo"?"redo":"undo"].push(current.document);current.document=current[op].pop()}
      else{const result=engine.apply(sourceCase.beats,current.document,overrideList(),payload,duration);current.undo=current.undo.concat([current.document]).slice(-20);current.redo=[];current.document=result.document}
      current.revision++;(saved.beatEditor||(saved.beatEditor={}))[caseId]=current;
      invalidateWorkflow("beat_override.editor");
      saved.audit.unshift({created_at:now(),actor:"pages-demo",case_id:caseId,action:"beat_editor."+op,detail:"revision="+current.revision});saved.audit=saved.audit.slice(0,300);persist();
      return editorSummary(current);
    }catch(error){saved=previous;throw error}
  }
  // Mathematical waveforms have no pre-seeded clinical diagnoses.
  const audit=(action,detail="",rhythmOnly=false)=>{invalidateWorkflow(action,rhythmOnly);saved.audit.unshift({created_at:now(),actor:"pages-demo",case_id:caseId,action,detail});saved.audit=saved.audit.slice(0,300);persist()};

  const reviewSteps=["edit","stt"];
  function workflow(){
    const value=saved.reviews[caseId]||(saved.reviews[caseId]={case_id:caseId,revision:0,steps:{},events:{}});
    const pending=reviewSteps.filter(step=>step==="edit"&&value.steps[step]?.status!=="done");
    return {...copy(value),pending_steps:pending,next_step:pending[0]||"report",report_status:saved.reports[caseId]?.status||"draft",report_version:saved.reports[caseId]?.version||1};
  }
  function invalidateWorkflow(action,rhythmOnly=action.startsWith('annotation.rhythm')){
    let affected;
    if(action.startsWith("beat_override.")||action==="patient.update"||action==="analysis.basis_changed")affected=reviewSteps;
    else if(action.startsWith("beat_template."))affected=reviewSteps;
    else if(rhythmOnly)affected=[];
    else if(action.startsWith("annotation."))affected=["stt","events"];
    else if(action==="event.review")affected=["events"];
    else return;
    workflow();const value=saved.reviews[caseId];value.revision++;
    affected.forEach(step=>{if(value.steps[step])Object.assign(value.steps[step],{status:"stale",reason:action})});
    if(action.startsWith("beat_override.")||action==="analysis.basis_changed")Object.values(value.events).forEach(item=>item.status="pending");
    const report=saved.reports[caseId];if(report?.composition){
      if(rhythmOnly){const st=report.composition.category_reviews?.ST;report.composition.category_reviews=st?{ST:st}:{};}
      else if(action.startsWith("annotation."))delete report.composition.category_reviews?.ST;else if(action!=="event.review")report.composition.category_reviews={};
      (report.composition.diagnosis_blocks||[]).forEach(block=>{if(block.manual&&!(rhythmOnly&&String(block.key||'').startsWith('ST:')))Object.assign(block,{needs_review:true,acknowledged:false})});
    }
    if(report){report.status="draft";report.reviewed_by="";report.version++;report.updated_at=now();}
  }
  function removeRetiredRhythmPicks(before,after,aliases){
    const current=new Map(after.episodes.map(x=>[x.id,x])),retired=new Set(before.episodes.filter(x=>!current.has(x.id)).map(x=>x.id));
    current.forEach(x=>{if(x.status==='excluded')retired.add(x.id)});
    const withdrawn=new Set();retired.forEach(id=>{withdrawn.add('annotation:af:'+id);if(id.startsWith('source-'))withdrawn.add('annotation:'+id.slice(7));(aliases[id]||[]).forEach(key=>withdrawn.add(key));});
    const report=saved.reports[caseId],composition=report?.composition;if(!composition)return [];
    const selected=composition.selected_events||[],removed=selected.filter(x=>withdrawn.has(x.event_id)).map(x=>x.event_id);if(!removed.length)return [];
    composition.selected_events=selected.filter(x=>!withdrawn.has(x.event_id));delete composition.category_reviews?.AF;
    composition.diagnosis_blocks=(composition.diagnosis_blocks||[]).filter(x=>!String(x.key||'').startsWith('AF:')||x.manual);
    return removed;
  }
  function confirmWorkflow(payload){
    const current=workflow();
    if(!reviewSteps.includes(payload.step)||payload.confirmed!==true)throw new Error("请选择复核环节并明确确认");
    if(!Number.isInteger(payload.revision)||payload.revision!==current.revision)throw new Error("病例已发生修改，请重新核对当前环节");
    if(typeof (payload.note??"")!=="string"||String(payload.note||"").length>1200)throw new Error("复核备注必须是 1200 字以内的文本");
    const value=saved.reviews[caseId];value.revision++;value.steps[payload.step]={status:"done",note:String(payload.note||"").trim(),actor:"pages-demo",updated_at:now()};
    audit("workflow.complete",payload.step);return workflow();
  }
  function reviewEvents(payload){
    workflow();const types=new Set(["V","S","pause","tachy","brady","noise","AF","AFL","manual"]),valid=new Set(beats.map(x=>x.sample_index)),items=payload.items;
    if(!["retained","excluded","pending"].includes(payload.status)||!Array.isArray(items)||!items.length||items.length>500)throw new Error("无效的事件处理请求");
    if(items.some(x=>!x||!Number.isInteger(x.sample_index)||!valid.has(x.sample_index)||!types.has(x.type)))throw new Error("事件心搏或候选类型不存在");
    items.forEach(x=>saved.reviews[caseId].events[`${x.type}:${x.sample_index}`]={sample_index:x.sample_index,type:x.type,status:payload.status,actor:"pages-demo",updated_at:now()});
    audit("event.review",`${payload.status}: ${items.length}`);return workflow();
  }

  const reportIdentity=()=>({case_id:caseId,analysis_basis:'public-math-4314-v2:'+caseId,analysis_revision:workflow().revision,beat_revision:editorValue().revision});
  const reportHash=value=>'math-evidence-v1:'+ECGClinicalAnalysis.fingerprint(JSON.stringify(value));
  function reportScope(expected,complete=false){const actual=reportIdentity();if(complete&&Object.keys(actual).some(k=>!Object.hasOwn(expected,k))||Object.keys(actual).some(k=>expected[k]!==undefined&&String(expected[k])!==String(actual[k]))){const e=Error('报告证据依据已变化，请重新读取');e.status=409;throw e;}return actual;}
  function reportDescriptor(index,event){
    const own=reportIdentity(),scope={case_id:caseId,analysis_basis:own.analysis_basis,beat_revision:own.beat_revision};
    if(['pause','rr_candidate'].includes(event.category)){const pair=ECGReportEngine.intervalPairs(index.rows,index.duration_s).find(([a,b])=>b.sample_index===event.start_sample);if(!pair||pair[1].rr_ms!==event.rr_ms||event.candidate_context&&event.candidate_context.rr_start_sample!==pair[0].sample_index)throw Error('RR 原始两搏或测量已变化');const row=r=>({id:r.id,sample_index:r.sample_index,class_code:r.class_code});return {schema:1,scope,kind:'rr',previous:row(pair[0]),terminal:row(pair[1]),rr_ms:pair[1].rr_ms,endpoint_delta_ms:(pair[1].sample_index-pair[0].sample_index)*5};}
    const p=event.candidate_context;if(event.evidence_only&&event.subtype==='manual_strip')return {schema:1,scope,kind:'strip',start_sample:p.start_sample,end_sample:p.end_sample};throw Error('此事件沿用原有诊断确认流程');
  }
  function attachReportEvidence(index,event){const descriptor=reportDescriptor(index,event),key=reportHash(descriptor),r=saved.evidenceReviews?.[caseId]?.[key];event.evidence_ref={key,...descriptor};event.evidence_review={status:r?'confirmed':'pending',presentations:r?.presentations||[],actor:r?.actor||'',confirmed_at:r?.updated_at||''};return event;}
  function longestReportEvent(index){
    const pair=ECGReportEngine.intervalPairs(index.rows,index.duration_s).reduce((best,p)=>!best||p[1].rr_ms>best[1].rr_ms?p:best,null);if(!pair)return null;
    const [a,b]=pair,event={event_id:'report-longest-rr',category:'rr_candidate',subtype:'rr_measurement',label:`最长 RR ${(b.rr_ms/1000).toFixed(3)} s（当前可分析记录）`,sample_index:b.sample_index,start_sample:b.sample_index,end_sample:b.sample_index,time_s:b.sample_index/200,end_s:b.sample_index/200,rr_ms:b.rr_ms,hr:b.hr,target_samples:[b.sample_index],beat_count:1,templates:[],evidence_only:true,diagnosis_status:'pending',candidate_scope:reportIdentity(),candidate_context:{rr_start_sample:a.sample_index,rr_end_sample:b.sample_index,rr_start_id:a.id,rr_end_id:b.id,rr_ms:b.rr_ms,start_s:a.sample_index/200,end_s:b.sample_index/200}};
    event.basis_version='report-rr-v1:'+reportHash(reportDescriptor(index,event));return attachReportEvidence(index,event);
  }
  const currentSttProtocol=p=>p?.rhythm_policy===STT_RHYTHM_POLICY&&[STT_METHOD,STT_RANGE_PROFILE].includes(p.method_version??p.id);
  function clinicalBaseIndex(){
    const index={...ECGClinicalAnalysis.buildIndex({...editedFeed(),duration},templateList(),annotationList(),workflow()),start_time:sourceCase.metadata.start_iso||sourceCase.metadata.start_time},identity=reportIdentity();
    for(const event of index.events){if(event.category!=='ST')continue;const scope=event.stt_source_scope||{},binding=saved.sttRecordBindings?.[caseId]?.[event.event_id],proof=event.stt_event_evidence;
      const stale=Object.keys(scope).length>0&&['case_id','analysis_basis','beat_revision'].some(k=>scope[k]!==identity[k])||binding&&(binding.beat_version!==index.beat_version||binding.source_digest&&binding.source_digest!==sttRawDigest)||event.stt_review_state==='reviewed'&&!sttRawDigest||proof?.source==='reviewed_automatic_candidate'&&sourceCase.stt_review&&(editorValue().revision!==sourceCase.stt_review_binding?.beat_revision||overrideList().length||sttRawDigest!==sourceCase.stt_review_binding.raw_waveform_sha256);
      const statistics=event.range_statistics,methodStale=event.stt_review_state==='reviewed'&&(!currentSttProtocol(event.stt_review_receipt?.measurement_protocol)||statistics&&(!currentSttProtocol(statistics.method_profile)||statistics.binding?.source_digest!==sttRawDigest)||proof&&proof.rhythm_policy!==STT_RHYTHM_POLICY);
      if(stale||methodStale)ECGClinicalAnalysis.sttMarkStale(event);
    }
    return index;
  }
  function clinicalIndex(){
    const index=clinicalBaseIndex(),own=reportIdentity(),active=[];
    for(const c of saved.evidenceCandidates?.[caseId]||[]){if(c.status!=='active'||['case_id','analysis_basis','beat_revision'].some(k=>c.scope[k]!==own[k]))continue;const p=c.payload,row=index.rows.find(r=>r.sample_index===p.anchor_sample&&!['X','O','Y','T'].includes(r.class_code));if(!row)continue;
      const event={event_id:'local-pick:'+c.id,category:c.kind==='rr'?'rr_candidate':'other',subtype:c.kind==='rr'?'manual_rr':'manual_strip',label:p.caption,sample_index:p.anchor_sample,start_sample:p.anchor_sample,end_sample:p.anchor_sample,time_s:p.anchor_sample/200,end_s:p.anchor_sample/200,target_samples:[p.anchor_sample],beat_count:1,templates:[],hr:row.hr,rr_ms:p.rr_ms??row.rr_ms,basis_version:'local-pick-v1:'+reportHash([c.scope,p]),pattern_only:false,diagnosis_status:'pending',local_candidate_id:c.id,retained_settings:p.settings,candidate_context:p,candidate_scope:c.scope,evidence_only:true};
      try{attachReportEvidence(index,event);}catch{continue;}index.events.push(event);active.push([event.event_id,event.basis_version]);
    }
    for(const e of index.events)if(e.category==='pause')attachReportEvidence(index,e);
    if(active.length){index.basis_versions.rr_candidate=index.beat_version+'-'+reportHash(active);index.data_version+='-picks-'+reportHash(active);}return index;
  }
  function reportCandidateRoute(method,p){
    const own=reportScope(p,method!=='GET'),list=(saved.evidenceCandidates||={})[caseId]||=[];
    if(method==='GET')return {items:copy(list),report_version:report(present()).version,...own};
    if(method==='PATCH'){
      const c=list.find(c=>c.id===p.id);if(!c||!['active','withdrawn'].includes(p.status))throw Error('候选操作无效');
      const current=report(present()),eventId='local-pick:'+c.id,selected=current.composition.selected_events||[],included=selected.some(e=>e.event_id===eventId);
      if(p.status==='withdrawn'&&included){if(p.expected_report_version!==current.version){const e=Error('报告已变化，候选未撤销，请刷新后重试');e.status=409;throw e;}
        const next={...current,composition:{...current.composition,selected_events:selected.filter(e=>e.event_id!==eventId)},version:current.version+1,status:'draft',reviewed_by:'',updated_at:now()};
        next.composition.diagnosis_blocks=(next.composition.diagnosis_blocks||[]).filter(b=>b.manual||!['rr_candidate:manual_rr','other:manual_strip'].includes(b.key)||next.composition.selected_events.some(e=>e.event_id.startsWith('local-pick:'))).map(b=>b.manual&&['rr_candidate:manual_rr','other:manual_strip'].includes(b.key)?{...b,needs_review:true,acknowledged:false}:b);saved.reports[caseId]=next;
      }
      c.status=p.status;audit('evidence_candidate.'+p.status,'数学候选');return {item:copy(c),report:report(present()),review:workflow(),...own};
    }
    if(method!=='POST'||!['rr','strip'].includes(p.kind))throw Error('候选操作无效');
    if(typeof(p.caption??'')!=='string'||(p.caption||'').length>120)throw Error('候选图注须为不超过120字的文本');
    const index=clinicalIndex(),settings=ECGReportEngine.settingsForEvent({category:p.kind==='rr'?'rr_candidate':'other'},p.settings||{}),context={};if(p.kind==='rr')settings.leads=['II','V1','V5'];let anchor;
    if(p.kind==='rr'){
      const pair=ECGReportEngine.intervalPairs(index.rows,index.duration_s).find(([a,b])=>b.sample_index===p.sample_index);if(!pair||p.rr_ms!==undefined&&p.rr_ms!==pair[1].rr_ms)throw Error('此位置没有匹配的有效相邻 RR');const [a,b]=pair;anchor=b;
      Object.assign(context,{rr_start_sample:a.sample_index,rr_end_sample:b.sample_index,rr_start_id:a.id,rr_end_id:b.id,rr_ms:b.rr_ms,endpoint_delta_ms:(b.sample_index-a.sample_index)*5,start_s:a.sample_index/200,end_s:b.sample_index/200});
      const bounds=p.population?.rr_bounds_ms;if(bounds&&(!Array.isArray(bounds)||bounds.length!==2||b.rr_ms<bounds[0]||bounds[1]!==null&&b.rr_ms>=bounds[1]))throw Error('RR 不在所选柱状区间');
      context.population={origin:p.population?.origin||'manual-card',claim:'用户选取的 RR 候选；不声明全记录最长',...(bounds?{rr_bounds_ms:bounds}:{})};settings.duration_s=Math.min(120,Math.max(settings.duration_s,b.rr_ms/1000+2));
    }else{if(!('range_start_s' in settings)){number(p.time_s,'留图定位时间',0,duration-.005);const strip=ECGReportEngine.resolve(index,{start_sample:Math.floor(p.time_s*200+.5),category:'other'},settings);if(strip.actual_duration_s>120)throw Error('至少 5 搏所需留图范围超过 120 秒，请选择更合适的位置');Object.assign(settings,{range_start_s:strip.start_s,range_end_s:strip.end_s});}anchor=index.rows.find(r=>r.sample_index/200>=settings.range_start_s&&r.sample_index/200<settings.range_end_s&&!['X','O','Y','T'].includes(r.class_code));if(!anchor)throw Error('区间没有可用心搏');Object.assign(context,{start_s:settings.range_start_s,end_s:settings.range_end_s,start_sample:Math.round(settings.range_start_s*200),end_sample:Math.round(settings.range_end_s*200),population:{origin:'full-record-retain',claim:'人工选段；不构成诊断'}});}
    const event={start_sample:anchor.sample_index,category:p.kind==='rr'?'rr_candidate':'other',candidate_context:context},spec=ECGReportEngine.resolve(index,event,settings),caption=(p.caption||'').trim()||(p.kind==='rr'?`自选 RR 候选 ${(anchor.rr_ms/1000).toFixed(3)} s`:'全记录人工留图');
    Object.assign(context,{caption,settings:{...settings},anchor_sample:anchor.sample_index,context_start_s:spec.context_start_s,context_duration_s:spec.context_duration_s});
    const key=reportHash([p.kind,{case_id:caseId,analysis_basis:own.analysis_basis,beat_revision:own.beat_revision},p.kind==='rr'?[context.rr_start_sample,context.rr_end_sample]:[context.start_sample,context.end_sample]]);let item=list.find(c=>c.candidate_key===key);
    if(item)item.status='active';else{item={id:Math.max(0,...list.map(c=>c.id))+1,case_id:caseId,kind:p.kind,candidate_key:key,scope:copy(own),payload:context,status:'active'};list.push(item);}audit('evidence_candidate.create','数学候选');return {item:copy(item),report:report(present()),review:workflow(),...own};
  }
  async function reportEvidenceRoute(action,method,p){
    const own=reportScope(p,action!=='report-rr-evidence'),index=clinicalIndex();
    if(action==='report-rr-evidence'&&method==='GET')return {event:longestReportEvent(index),...own};
    const event=p.target==='longest'?longestReportEvent(index):index.events.find(e=>e.event_id===p.event_id);if(!event||p.basis_version&&p.basis_version!==event.basis_version)throw Error('图条依据已变化，请重新核对');
    const descriptor=reportDescriptor(index,event),entry={...(Object.keys(p.entry||{}).length?p.entry:event.retained_settings||{}),caption:p.entry?.caption||event.label,notes:p.entry?.notes||''},spec=ECGReportEngine.resolve(index,event,entry);
    const selection={...ECGReportEngine.settings(entry),range_start_s:entry.range_start_s??null,range_end_s:entry.range_end_s??null,caption:entry.caption,notes:entry.notes},proof={selection,start_s:spec.start_s,end_s:spec.end_s},key=reportHash(descriptor),proofKey=reportHash(proof),params=new URLSearchParams({whole:'1',filter:'raw'});
    const wave=await waveform(params,{start:spec.start_s,duration:spec.actual_duration_s,leads:spec.leads,maxPoints:12000,filter:'raw'});wave.beats=spec.visible_beats;
    if(spec.leads.some(l=>!wave.leads[l]?.length))throw Error('导联未完整读取');reportScope(own,true);
    if(action==='report-evidence/preview'&&method==='POST')return {...event,event,entry,strip:spec,waveform:wave,context:await waveform(params,{start:spec.context_start_s,duration:spec.context_duration_s,leads:['II'],maxPoints:1600,filter:'raw'}),evidence_key:key,presentation_key:proofKey,report_version:report(present()).version,...own};
    if(action!=='report-evidence/confirm'||method!=='POST'||p.confirmed!==true)throw Error('请明确确认本条证据');
    if(p.evidence_key!==key||p.presentation_key!==proofKey||p.report_version!==report(present()).version){const e=Error('报告或刚才读取的波形已变化，请重新核对');e.status=409;throw e;}
    if(descriptor.kind==='rr'&&entry.caption.includes('最长')&&event.rr_ms!==longestReportEvent(index)?.rr_ms)throw Error('本条不是当前可分析记录的最长 RR，请使用客观 RR 图注');
    const reviews=(saved.evidenceReviews||={})[caseId]||={},record=reviews[key]||{evidence_key:key,descriptor,presentations:[],actor:'browser-demo-user',updated_at:now(),status:'confirmed'};
    if(!record.presentations.some(x=>x.presentation_key===proofKey)){record.presentations.push({...proof,presentation_key:proofKey});record.updated_at=now();reviews[key]=record;demoReviewChanged('report_evidence.confirmed');persist();}
    return {item:record,report:report(present()),review:workflow(),...reportIdentity()};
  }
  const nextAnnotationId=()=>Math.max(Date.now(),1+Math.max(0,...(saved.annotations[caseId]||[]).map(a=>Number(a.id)||0)));
  function annotationItems(){
    const items=copy(annotationList());if(!items.some(a=>['ST','ST_REVIEW_NOTE'].includes(a.details?.kind)))return items;
    const index=clinicalBaseIndex(),events=new Map(index.events.filter(e=>e.category==='ST').map(e=>[e.event_id,e])),composition=report(present()).composition;
    for(const item of items){const event=events.get('annotation:'+item.id);if(event)item.stt_review_receipt={...copy(event.stt_review_receipt),report_use:ECGClinicalAnalysis.sttUseFor(composition,event)};}
    return items;
  }
  function annotationList(){
    const initial=[];
    const items=initial.concat(saved.annotations[caseId]||[]),rhythm=saved.rhythms?.[caseId];
    return rhythm?items.filter(x=>!['AF','AFL'].includes(x.details?.kind)).concat(ECGOverviewEngine.annotations(rhythm.document,rhythm.updated_at)):items;
  }
  function templateList(){const list=copy(saved.templates?.[caseId]||[]);if(activeEdited){const map=new Map(editedFeed().beats.map(r=>[r.id,r]));list.forEach(item=>{item.sample_indices=(item.beat_ids||item.sample_indices.map(s=>"s:"+s)).filter(id=>map.has(id)).map(id=>map.get(id).sample_index).sort((a,b)=>a-b);item.beat_count=item.sample_indices.length})}return list}
  function overrideList(){return copy(Object.values(saved.beatOverrides?.[caseId]||{}).sort((a,b)=>a.sample_index-b.sample_index))}
  function validateOverrideSamples(payload){const samples=Array.isArray(payload.sample_indices)?payload.sample_indices:[],valid=new Map(beats.map(beat=>[beat.sample_index,beat]));if(!samples.length||samples.length>500||samples.some(sample=>!Number.isInteger(sample))||new Set(samples).size!==samples.length)throw new Error("sample_indices 必须包含 1–500 个不重复心搏");if(samples.some(sample=>!valid.has(sample)))throw new Error("sample_indices 必须对应数学生成心搏 中的心搏");return samples.map(sample=>valid.get(sample))}
  function saveOverrides(payload){const type=String(payload.class_code||"").toUpperCase();if(!new Set(["N","S","V","X","P","O"]).has(type))throw new Error("人工心搏类型必须是 N、S、V、X、P 或 O");const selected=validateOverrideSamples(payload),bucket=saved.beatOverrides[caseId]||(saved.beatOverrides[caseId]={}),stamp=now();const items=selected.map(beat=>bucket[beat.sample_index]={case_id:caseId,sample_index:beat.sample_index,source_group:beat.group,class_code:type,created_by:"pages-demo",created_at:bucket[beat.sample_index]?.created_at||stamp,updated_at:stamp});audit("beat_override.reclassify",`class=${type} beats=${items.length}`);persist();return copy(items)}
  function restoreOverrides(payload){const selected=validateOverrideSamples(payload),bucket=saved.beatOverrides[caseId]||(saved.beatOverrides[caseId]={});let changed=0;selected.forEach(beat=>{if(bucket[beat.sample_index]){delete bucket[beat.sample_index];changed++}});audit("beat_override.restore",`beats=${changed}`);persist();return changed}
  function saveTemplate(payload){
    if(Object.hasOwn(payload,"revision")&&payload.revision!==editorValue().revision)throw Error("编辑版本已变化，请重新加载密度图");
    if(!Array.isArray(payload.sample_indices)||payload.sample_indices.some(s=>!Number.isInteger(s)||s<0)||new Set(payload.sample_indices).size!==payload.sample_indices.length)throw Error("sample_indices 必须是不重复的非负整数数组");
    const name=String(payload.name||"").trim(),family=String(payload.rhythm_family||"自定义"),lead=String(payload.lead||"II"),sourceClass=String(payload.source_class||""),samples=[...new Set((Array.isArray(payload.sample_indices)?payload.sample_indices:[]).filter(value=>Number.isInteger(value)&&value>=0))].sort((a,b)=>a-b),validSamples=new Set(editedFeed().beats.map(beat=>beat.sample_index));if(!name)throw new Error("模板类别名称不能为空");if(!TEMPLATE_FAMILIES.has(family))throw new Error("不支持的节律家族");if(!TEMPLATE_LEADS.has(lead))throw new Error("不支持的参考导联");if(sourceClass&&!(sourceClass.startsWith("source-")&&engine.types[sourceClass.slice(7)]||/^custom-\d+$/.test(sourceClass)))throw new Error("父类别不存在");if(!samples.length)throw new Error("请先圈选心搏");if(samples.length>250000)throw new Error("单个模板类别最多包含 250000 个心搏");if(samples.some(sample=>!validSamples.has(sample)))throw new Error("模板类别只能包含数学生成心搏 中的心搏");const beatBySample=new Map(editedFeed().beats.map(beat=>[beat.sample_index,beat]));if(sourceClass.startsWith("source-")&&samples.some(sample=>beatBySample.get(sample)?.class_code!==sourceClass.slice(7)))throw new Error("选中心搏不属于指定的源类别");if(sourceClass.startsWith("custom-")){const parent=templateList().find(item=>`custom-${item.id}`===sourceClass);if(!parent)throw new Error("父类别不存在");const parentSamples=new Set(parent.sample_indices);if(samples.some(sample=>!parentSamples.has(sample)))throw new Error("选中心搏不属于指定的父模板");}
    const item={beat_ids:samples.map(s=>activeEdited?beatBySample.get(s)?.id:"s:"+s),id:Math.max(Date.now(),1+Math.max(0,...templateList().map(t=>t.id))),case_id:caseId,name:name.slice(0,80),rhythm_family:family,lead,source_class:sourceClass,sample_indices:samples,start_sample:samples[0],end_sample:samples[samples.length-1],beat_count:samples.length,note:String(payload.note||"").slice(0,1200),created_by:"pages-demo",created_at:now(),updated_at:now()};
    (saved.templates[caseId]||(saved.templates[caseId]=[])).unshift(item);audit("beat_template.create",`#${item.id} ${item.name} beats=${item.beat_count}`);persist();return copy(item);
  }
  const report=item=>{const value=copy(saved.reports[caseId]||{status:"draft",version:1,conclusion:item.conclusion,updated_at:""});value.composition={...copy(defaultComposition),...(value.composition||{}),paper:{...defaultComposition.paper,...(value.composition?.paper||{})}};value.review_revision=workflow().revision;value.current_analysis_basis={digest:'public-math-4314-v2:'+caseId,source:'browser-local-revision',verified:false};return value};
  function present(detailed=false){
    const item=copy(sourceCase);delete item.beats;Object.assign(item.technical,rawSignalMetadata());
    item.review_workflow=workflow();item.analysis_revision=editorValue().revision;
    if(saved.patients[caseId])Object.assign(item.metadata,saved.patients[caseId]);
    if(detailed){
      const valid=beats.filter(x=>x.group!==34),rr=valid.map(x=>x.rr_ms),groups={};
      beats.forEach(x=>groups[x.group]=(groups[x.group]||0)+1);
      const longest=valid.reduce((a,b)=>!a||b.rr_ms>a.rr_ms?b:a,null);
      item.calculated={record_count:beats.length,valid_beats:valid.length,first_beat_time_s:valid[0]?.time_s??null,group_counts:Object.fromEntries(Object.entries(groups).map(([key,value])=>[String(key),value])),avg_hr_from_duration:round(valid.length*60/duration),avg_hr_from_rr:rr.length?round(60000/(rr.reduce((a,b)=>a+b,0)/rr.length)):null,longest_rr_ms:longest?.rr_ms??null,longest_rr_time_s:longest?.time_s??null,min_rr_ms:rr.length?Math.min(...rr):null,format_verified:true};
      item.report_workflow=report(item);item.annotations=annotationItems();if(activeEdited){item.calculated=engine.metrics(editedFeed(),duration);item.analysis_revision=editorValue().revision;item.beat_editor_settings=editorValue().document.settings;item.manual_longest=editorSummary(editorValue()).manual_longest}
    }
    return item;
  }
  function trend(){
    const points=[];
    for(let time=30;time<duration;time+=60){const count=beats.filter(x=>x.group!==34&&x.time_s>=time-30&&x.time_s<time+30).length;points.push({time_s:time,hr:count})}
    const values=points.map(x=>x.hr);return {bin_seconds:60,points,min_hr:Math.min(...values),max_hr:Math.max(...values)};
  }
  const mean=values=>values.length?values.reduce((sum,value)=>sum+value,0)/values.length:null;
  const sampleDeviation=values=>values.length>1?Math.sqrt(values.reduce((sum,value)=>sum+(value-mean(values))**2,0)/(values.length-1)):null;
  function hrv(){
    const isNormal=beat=>beat.group===1&&beat.rr_ms>=300&&beat.rr_ms<=2000;
    const normalBeats=beats.filter(isNormal),nn=normalBeats.map(beat=>beat.rr_ms),successiveDifferences=[];
    for(let index=1;index<beats.length;index++)if(isNormal(beats[index-1])&&isNormal(beats[index]))successiveDifferences.push(beats[index].rr_ms-beats[index-1].rr_ms);
    const segmentMeans=[],segmentDeviations=[];
    for(let start=0;start+300<=duration;start+=300){const values=normalBeats.filter(beat=>beat.time_s>=start&&beat.time_s<start+300).map(beat=>beat.rr_ms);if(values.length>1){segmentMeans.push(mean(values));segmentDeviations.push(sampleDeviation(values))}}
    const binWidth=1000/128,histogram=new Map();nn.forEach(value=>{const bin=Math.floor(value/binWidth);histogram.set(bin,(histogram.get(bin)||0)+1)});const peak=Math.max(0,...histogram.values());
    const source=copy(sourceCase.source_report_summary||{});source.mean_nn_ms=Number.isFinite(source.avg_hr)?round(60000/source.avg_hr):null;source.mean_nn_derived=Number.isFinite(source.avg_hr);
    const calculated={nn_count:nn.length,mean_nn_ms:round(mean(nn)),sdnn_ms:round(sampleDeviation(nn)),sdann_ms:round(sampleDeviation(segmentMeans)),sdnn_index_ms:round(mean(segmentDeviations)),rmssd_ms:round(successiveDifferences.length?Math.sqrt(mean(successiveDifferences.map(value=>value**2))):null),pnn50_pct:round(successiveDifferences.length?successiveDifferences.filter(value=>Math.abs(value)>50).length*100/successiveDifferences.length:null),triangular_index:round(peak?nn.length/peak:null),method:"当前 10 分钟数学生成心搏 片段；5 分钟分段；三角指数箱宽 1/128 秒"};
    return {source,calculated:activeEdited?engine.hrv(editedFeed(),duration):calculated,comparison:{source_label:"生成器参考摘要",source_duration:sourceCase.metadata.source_record_duration_text,calculated_label:"当前数学波形重算",calculated_duration:sourceCase.metadata.duration_text,warning:"统计时长不同；10 分钟 SDANN、SDNN index 与三角指数仅作演示估计，不应解释为算法误差或临床结论。"}};
  }
  function sttReview(){
    if(sourceCase.stt_review){
      const binding=sourceCase.stt_review_binding||{},value=copy(sourceCase.stt_review),identity=reportIdentity(),policyCurrent=binding.rhythm_policy===STT_RHYTHM_POLICY&&binding.algorithm_version===STT_ALGORITHM&&value.analysis?.algorithm_version===STT_ALGORITHM&&value.analysis?.rhythm_policy===STT_RHYTHM_POLICY,valid=binding.case_id===caseId&&binding.analysis_basis===identity.analysis_basis&&binding.beat_revision===editorValue().revision&&!overrideList().length&&policyCurrent&&!!sttRawDigest&&sttRawDigest===binding.raw_waveform_sha256&&binding.beat_version===clinicalBaseIndex().beat_version&&binding.data_version===binding.beat_version+'-stt-independent-v2';
      value.simulation={python_precomputed:true,browser_recomputed:false,patient_inputs_read:false,precomputed_binding:copy(binding)};
      if(valid)return {...value,...identity,review_records:annotationItems().filter(a=>['ST','ST_REVIEW_NOTE'].includes(a.details?.kind))};
      return {...value,case_id:binding.case_id,analysis_basis:binding.analysis_basis,beat_revision:binding.beat_revision,analysis_revision:0,current_scope:identity,review_records:annotationItems().filter(a=>['ST','ST_REVIEW_NOTE'].includes(a.details?.kind)),stale:true,analysis:null,
        automatic_candidates:{...value.automatic_candidates,enabled:false,items:[],summary:{candidate_count:0,st_depression_count:0,st_elevation_count:0,t_wave_count:0},reason_code:!policyCurrent?'method_changed_precomputed_evidence':!sttRawDigest||sttRawDigest!==binding.raw_waveform_sha256?'source_changed_precomputed_evidence':'beat_edits_invalidated_precomputed_evidence',reasons:[policyCurrent?'心搏或来源已修订；此数学 Demo 的预计算 ST/T 证据已失效，未伪装为重新分析。':'此预计算采用旧测量方法或节律策略，须用当前方法重新计算；未改签旧值。']}};
    }
    const fragments=String(sourceCase.conclusion||"").split(/(?<=[。！？；!?;])\s*|\n+/).map(value=>value.trim()).filter(value=>/(?:ST段|ST[-‑–— ]?T|T波|T倒置|T低平)/i.test(value)).map(value=>value.replace(/(?:[+\-−＋－]?\s*\d+(?:\.\d+)?)\s*(?:mV|µV|μV)/gi,"【病例幅度已隐藏】"));
    return {...reportIdentity(),review_records:annotationItems().filter(a=>['ST','ST_REVIEW_NOTE'].includes(a.details?.kind)),schema_version:"manual-stt-review-v1",review_mode:"manual_review_only",manual_review_only:true,calibration_unverified:true,measurement_protocol:{default_measurement:"J+60 ms",default_landmark:"ST60",baseline:{preferred:"PR_segment",fallback:"individual_stable_baseline",label:"PR 段/个体稳定基线",requires_manual_confirmation:true},landmarks:[{code:"J",offset_from_j_ms:0,label:"J 点"},{code:"ST60",offset_from_j_ms:60,label:"J+60 ms"},{code:"ST80",offset_from_j_ms:80,label:"J+80 ms"}],case_amplitude_output:{enabled:false,reason:"原始电压标定和分析链未独立验证，不输出病例 ST 幅度。"}},lead_system:{status:"unknown",mapping_verified:false,electrode_placement_verified:false,message:"导联体系及采集通道到标准导联的映射未经独立核验。"},calibration:{status:"unverified",voltage_gain_verified:false,filter_response_verified_for_st:false,message:"在增益、零线稳定性及 ST 分析滤波响应核验前，仅允许人工定性复核。"},automatic_candidates:{enabled:false,reason_code:"measurement_chain_not_validated",reasons:["电压增益与零线标定未独立验证","J 点、基线和 ST 复核点尚无经验证的自动定位算法","动态心电的体位变化、基线漂移与伪差需要人工排除"]},reference_thresholds:{enabled:false,reference_only:true,applied_to_case:false,title:"动态心电常用研究筛查参考（未启用）",st_depression_example:{magnitude_mV:.10,measurement_landmarks:["ST60","ST80"],minimum_duration_s:60},warning:"该参考不是病例判定规则，不得用于自动生成诊断。"},source_report:{origin:"source_report_conclusion",available:Boolean(fragments.length),fragments,is_source_excerpt:true,software_interpretation_added:false},clinical_safety:{diagnosis_generated:false,requires_physician_review:true,statement:"本界面仅用于医师人工复核，不生成缺血诊断或替代临床判断。"}};
  }
  function rrVisuals(){
    const normal=beats.filter((x,i)=>x.group===1&&x.rr_ms>=300&&x.rr_ms<=2000&&(!activeEdited||(i>0&&beats[i-1].class_code==="N"))).map(x=>x.rr_ms),histogram=Array.from({length:35},(_,index)=>({start_ms:300+index*50,end_ms:350+index*50,count:0}));
    normal.forEach(value=>histogram[Math.min(34,Math.max(0,Math.floor((value-300)/50)))].count++);
    const step=Math.max(1,Math.floor(normal.length/900)),poincare=[];for(let index=step;index<normal.length;index+=step)poincare.push([normal[index-step],normal[index]]);
    if(activeEdited){const pairs=[];for(let i=1;i<beats.length-1;i++){const a=beats[i-1],b=beats[i],c=beats[i+1];if([a,b,c].every(r=>r.class_code==="N")&&[b.rr_ms,c.rr_ms].every(x=>x>=300&&x<=2000))pairs.push([b.rr_ms,c.rr_ms])}return {histogram,poincare:pairs.filter((_,i)=>i%Math.max(1,Math.ceil(pairs.length/900))===0)}}return {histogram,poincare};
  }

  let waveformPromise=null,sttSourcePromise=null,sttRawDigest=null;
  async function waveformBuffer(){
    if(!waveformPromise){
      const pending=nativeFetch(`${ASSET_BASE}/waveform.bin`).then(result=>{if(!result.ok)throw new Error(`波形资源加载失败（${result.status}）`);return result.arrayBuffer()});
      waveformPromise=pending;
      pending.catch(()=>{if(waveformPromise===pending)waveformPromise=null;});
    }
    return waveformPromise;
  }
  async function prepareDemoSttSource(){
    if(!sttSourcePromise)sttSourcePromise=(async()=>{const raw=await waveformBuffer();if(raw.byteLength!==Math.round(duration*RATE)*16)sttFailure('ST数学原始波形长度与来源范围不一致',409);const digest=await crypto.subtle.digest('SHA-256',raw);sttRawDigest=Array.from(new Uint8Array(digest),v=>v.toString(16).padStart(2,'0')).join('');return sttRawDigest;})();
    return sttSourcePromise;
  }
  function displayFilter(values){
    if(!values.length)return values;
    const highpass=Math.exp(-2*Math.PI*.5/RATE),lowpass=1-Math.exp(-2*Math.PI*40/RATE);let baseline=values[0],low=0;
    return values.map(value=>{baseline=highpass*baseline+(1-highpass)*value;const high=value-baseline;low+=lowpass*(high-low);return round(low,2)});
  }
  function leadValue(view,sample,lead){
    const offset=sample*16,read=channel=>view.getInt16(offset+channel*2,true),leadI=read(0),leadII=read(1);
    if(lead==="I")return leadI;if(lead==="II")return leadII;if(lead==="III")return leadII-leadI;if(lead==="aVR")return-(leadI+leadII)/2;if(lead==="aVL")return leadI-leadII/2;if(lead==="aVF")return leadII-leadI/2;
    return read({V1:2,V2:3,V3:4,V4:5,V5:6,V6:7}[lead]??1);
  }
  async function waveformOverview(params){
    const rawBins=params.get('bins')??'1000',bins=Number(rawBins);
    if(!/^[+-]?\d+$/.test(rawBins.trim())||!Number.isSafeInteger(bins)||bins<50||bins>1600)throw Error('全览分箱须为50–1600');
    const buffer=await waveformBuffer(),total=buffer.byteLength/16;
    if(!Number.isSafeInteger(total)||total<1||total!==Math.round(duration*RATE)){
      const error=new Error('数学原始波形长度与来源范围不一致');error.status=409;throw error;
    }
    const count=Math.min(total,bins),boundaries=Array.from({length:count+1},(_,index)=>Math.floor(index*total/count)),view=new DataView(buffer),leads={II:[],V1:[],V5:[]};
    // Visit every real sample: point decimation would lose narrow negative QS or R peaks.
    for(let index=0;index<count;index++){
      let minII=Infinity,maxII=-Infinity,minV1=Infinity,maxV1=-Infinity,minV5=Infinity,maxV5=-Infinity;
      for(let sample=boundaries[index];sample<boundaries[index+1];sample++){
        const offset=sample*16,ii=view.getInt16(offset+2,true),v1=view.getInt16(offset+4,true),v5=view.getInt16(offset+12,true);
        minII=Math.min(minII,ii);maxII=Math.max(maxII,ii);minV1=Math.min(minV1,v1);maxV1=Math.max(maxV1,v1);minV5=Math.min(minV5,v5);maxV5=Math.max(maxV5,v5);
      }
      leads.II.push([minII,maxII]);leads.V1.push([minV1,maxV1]);leads.V5.push([minV5,maxV5]);
    }
    return {start_s:0,total_duration_s:total/RATE,total_samples:total,sample_rate_hz:RATE,bin_edges_s:boundaries.map(sample=>sample/RATE),leads,...rawSignalMetadata(),method:'全记录原始采样逐箱最小/最大包络；仅用于时间导航，请在局部原始波形复核；不改变采样、增益、R点或RR。'};
  }
  async function waveform(params,forced={}){
    const waveBeats=beats.slice(),waveMarkers=activeEdited?editedFeed().markers:[];
    const buffer=await waveformBuffer(),view=new DataView(buffer),start=Math.max(0,Math.min(duration-1,Number(forced.start??params.get("start")??0))),windowSeconds=Math.max(.5,Math.min(params.get("whole")==="1"?duration:120,duration-start,Number(forced.duration??params.get("duration")??10))),supported=["I","II","III","aVR","aVL","aVF","V1","V2","V3","V4","V5","V6"],leads=forced.leads||String(params.get("leads")||"II,V1,V5").split(",").filter(x=>supported.includes(x)),max=Math.max(200,Math.min(12000,Number(forced.maxPoints??params.get("max_points")??4000))),startSample=Math.floor(start*RATE+1e-7),sampleCount=Math.min(Math.floor(windowSeconds*RATE+1e-7),buffer.byteLength/16-startSample),stride=Math.max(1,Math.ceil(sampleCount/max)),applyFilter=(forced.filter||params.get("filter")||"display")!=="raw",data={};
    leads.forEach(lead=>{let values=Array.from({length:sampleCount},(_,offset)=>leadValue(view,startSample+offset,lead));if(applyFilter)values=displayFilter(values);data[lead]=values.filter((_,offset)=>offset%stride===0)});
    return {start_s:round(startSample/RATE,3),duration_s:round(sampleCount/RATE,3),sample_rate_hz:RATE,display_sample_rate_hz:RATE/stride,stride,...rawSignalMetadata(),filter:applyFilter?"0.5–40 Hz display filter":"raw",calibration_note:"纯数学合成波形 · "+rawSignalMetadata().calibration_note,leads:data,beats:waveBeats.concat(waveMarkers).filter(x=>x.time_s>=start&&x.time_s<=start+windowSeconds),annotations:annotationList().filter(x=>x.sample_index/RATE>=start&&x.sample_index/RATE<=start+windowSeconds)};
  }
  function scatter(mode="rr",hour=0,max=12000){
    const points=[];
    for(let index=1;index<beats.length-1;index++){const previous=beats[index-1],current=beats[index],following=beats[index+1];if(activeEdited&&([previous,current,following].some(r=>r.group===34)||current.rr_ms<=0||following.rr_ms<=0))continue;if(mode==="n"&&current.group!==1||mode==="nn"&&!(previous.group===1&&current.group===1&&following.group===1)||mode==="s"&&current.group!==2||mode==="v"&&current.group!==3)continue;if(mode==="hour"&&(current.time_s<hour||current.time_s>=hour+3600))continue;points.push({sample_index:current.sample_index,time_s:current.time_s,x:current.rr_ms,y:following.rr_ms,rr_ms:current.rr_ms,next_rr_ms:following.rr_ms,previous_group:previous.group,group:current.group,next_group:following.group,label:current.label})}
    const stride=Math.max(1,Math.ceil(points.length/max)),shown=points.filter((_,index)=>index%stride===0).slice(0,max),upper=points.some(x=>x.x>2000||x.y>2000)?3000:2000;
    return {mode,definition:"源逐搏 RR 配对",candidate_count:points.length,returned_count:shown.length,sampled:shown.length<points.length,sampling:"deterministic-temporal",hour_start_s:mode==="hour"?hour:null,hour_end_s:mode==="hour"?hour+3600:null,axis:{x_label:"RR(i)",y_label:"RR(i+1)",x_unit:"ms",y_unit:"ms"},bounds:{x_min:0,x_max:upper,y_min:0,y_max:upper},points:shown,_all:points};
  }
  function inside(x,y,polygon){let hit=false,previous=polygon.length-1;for(let index=0;index<polygon.length;index++){const a=polygon[index],b=polygon[previous];if((a[1]>y)!==(b[1]>y)&&x<=(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0])hit=!hit;previous=index}return hit}
  function eventData(params){
    if(activeEdited){const feed=editedFeed();for(const key of ["brady","tachy","pause"])if(params.has(key))feed.document.settings[key]=Number(params.get(key));engine.settings(feed.document.settings);return engine.events(feed,params.get("type")||"all",Math.max(0,Number(params.get("offset"))||0),Math.max(1,Math.min(1000,Number(params.get("limit"))||200)))}
    const type=params.get("type")||"all",brady=Number(params.get("brady")||50),tachy=Number(params.get("tachy")||120),pause=Number(params.get("pause")||2.5),limit=Number(params.get("limit")||500),summary={AF:0,V:0,S:0,pause:0,tachy:0,brady:0,noise:0},items=[];
    beats.forEach(beat=>{let kind,label,severity;if(activeEdited&&["A","M","C","H"].includes(beat.class_code)){kind=["A","M"].includes(beat.class_code)?"AF":"AFL";label="人工标记："+beat.name;severity="medium"}else if(beat.af_onset&&!activeEdited){kind="AF";label="房颤候选片段";severity="high"}else if(beat.group===2){kind="S";label="室上性候选心搏";severity="medium"}else if(beat.group===3){kind="V";label="室性候选心搏";severity="high"}else if(beat.group===34){kind="noise";label="噪声/待确认心搏";severity="low"}else if(beat.rr_ms>=pause*1000){kind="pause";label=`长 RR 间期 ${(beat.rr_ms/1000).toFixed(2)}s`;severity="high"}else if(beat.hr>=tachy){kind="tachy";label=`心动过速候选 ${Math.round(beat.hr)} bpm`;severity="medium"}else if(beat.hr>0&&beat.hr<=brady){kind="brady";label=`心动过缓候选 ${Math.round(beat.hr)} bpm`;severity="medium"}else if(activeEdited&&[4,5,6,7,8].includes(beat.group)){kind="manual";label="人工分类："+beat.name;severity="low"}else return;summary[kind]=(summary[kind]||0)+1;if(type==="all"||type===kind)items.push({...beat,type:kind,label,severity,review_status:"待复核"})});
    const offset=Math.max(0,Number(params.get("offset"))||0);return {summary,total:items.length,offset,limit,items:items.slice(offset,offset+limit)};
  }

  // New review endpoints use the same browser state and saved beat feed.
  // This identity is deliberately not represented as verified patient/raw data.
  let reviewAdapter=null;
  function demoReviewScope(){
    const previous=activeEdited;activeEdited=true;
    try{return {case_id:caseId,source_digest:'unverified-browser-math-labels:'+ECGClinicalAnalysis.fingerprint(JSON.stringify(sourceCase.beats)),data_version:clinicalBaseIndex().data_version,analysis_basis:'public-math-4314-v2:'+caseId,beat_revision:editorValue().revision,analysis_revision:workflow().revision};}
    finally{activeEdited=previous;}
  }
  function demoSttScope(){return {...demoReviewScope(),source_digest:'raw-sha256:'+sttRawDigest,data_version:clinicalBaseIndex().beat_version+'-stt-independent-v2'};}
  function demoReviewChanged(action){
    workflow();if(action!=='report_evidence.confirmed')saved.reviews[caseId].revision++;
    const value=saved.reports[caseId];if(value){value.status='draft';value.reviewed_by='';value.version++;value.updated_at=now();}
    saved.audit.unshift({created_at:now(),actor:'browser-demo-user',case_id:caseId,action,detail:'纯数学浏览器复核声明；无患者或临床金标准'});saved.audit=saved.audit.slice(0,300);
  }
  function demoReview(){
    if(!globalThis.ECGDemoReviewAPI)throw Error('数学Demo复核模块未加载，请刷新');
    return reviewAdapter||(reviewAdapter=ECGDemoReviewAPI.create({saved:()=>saved,persist,scope:demoReviewScope,sttScope:demoSttScope,prepareSttSource:prepareDemoSttSource,feed:editedFeed,annotations:annotationList,rawWaveform:waveformBuffer,startTime:sourceCase.metadata.start_iso||sourceCase.metadata.start_time,duration,caseId,sourceCase,nativeFetch,waveform,changed:demoReviewChanged}));
  }
  function sttFailure(message,status=400){const error=Error(message);error.status=status;throw error;}
  function withdrawSttGeneratedText(composition,eventId){
    const key='ST:review:'+eventId,removed=[],kept=[];
    for(const block of composition.diagnosis_blocks||[]){
      if(block.key!==key)kept.push(block);
      else if(block.manual===false)removed.push(block);
      else kept.push({...block,needs_review:true,acknowledged:false});
    }
    if('diagnosis_blocks'in composition)composition.diagnosis_blocks=kept;
    return removed;
  }
  function sttBeatVersion(){return clinicalBaseIndex().beat_version;}
  function sttReplay(payload,annotationId,requestHash){
    const previous=saved.sttReviewSubmissions?.[caseId]?.[payload.details.submission_id];if(!previous)return null;
    if(previous.request_sha256!==requestHash||previous.operation!==(annotationId===null?'create':'update')||annotationId!==null&&previous.annotation_id!==annotationId)sttFailure('此提交编号已用于另一份ST-T内容，未覆盖或重复保存',409);
    reportScope(Object.fromEntries(['case_id','analysis_basis','beat_revision'].map(k=>[k,payload.details.review_scope?.[k]])));
    if(previous.beat_version!==sttBeatVersion()||previous.source_digest&&previous.source_digest!==sttRawDigest)sttFailure('此提交的原始来源或心搏已变化，未套用旧复核',409);
    const row=annotationItems().find(a=>a.id===previous.annotation_id);if(!row)sttFailure('该ST-T提交曾已保存但记录已删除，未自动重建',409);return row;
  }
  async function saveSttRecord(raw,annotationId=null){
    const sourceStorageBefore=localStorage.getItem(STORE_KEY);
    await prepareDemoSttSource();
    if(sourceStorageBefore!==localStorage.getItem(STORE_KEY))sttFailure('核对原始波形期间病例已变化，未保存；请重新读取后核对',409);
    const A=ECGClinicalAnalysis,payload=copy(raw),d=payload.details,results=['st_depression','st_elevation','t_change','nonspecific','no_change','artifact','indeterminate'];
    if(!d||d.kind!=='ST'||d.reviewed!==true||!results.includes(d.result_code))sttFailure('请选择并保存本条医生复核结果');
    if(typeof d.submission_id!=='string'||!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(d.submission_id))sttFailure('ST-T提交编号须为规范UUID');
    if(!d.review_scope||['case_id','analysis_basis','analysis_revision','beat_revision'].some(k=>!Object.hasOwn(d.review_scope,k)))sttFailure('ST-T保存缺少当前完整依据');
    const requestHash=A.sttDigest(payload),replayed=sttReplay(payload,annotationId,requestHash);if(replayed)return replayed;
    const identity=reportScope(d.review_scope,true),storageBefore=localStorage.getItem(STORE_KEY),beatVersion=sttBeatVersion(),first=payload.sample_index,end=d.end_sample,total=Math.round(duration*RATE);
    if(!Number.isSafeInteger(first)||!Number.isSafeInteger(end)||first<0||first>end||end>=total)sttFailure('ST-T复核完整范围超出记录');
    if(!Array.isArray(d.review_leads)||!d.review_leads.length||new Set(d.review_leads).size!==d.review_leads.length||d.review_leads.some(l=>!TEMPLATE_LEADS.has(l)))sttFailure('请选择实际复核导联，查看导联不代表异常导联');
    for(const [key,max]of [['label',120],['note',2000],['lead',16],['category',32]])if(typeof (payload[key]??'')!=='string'||Array.from(payload[key]??'').length>max)sttFailure('ST-T复核文字无效或过长');
    if(!['','全部',...TEMPLATE_LEADS].includes(payload.lead??''))sttFailure('ST-T导联无效');
    if(Object.hasOwn(d,'stt_event_evidence'))sttFailure('ST-T事件证据须由服务器核验');
    const before=annotationId===null?null:(saved.annotations[caseId]||[]).find(a=>a.id===annotationId);
    if(annotationId!==null&&(!before||!['ST','ST_REVIEW_NOTE'].includes(before.details?.kind)))sttFailure('原ST-T复核记录不存在，未创建另一条',409);
    if(before&&(!Number.isSafeInteger(payload.expected_record_version)||payload.expected_record_version!==(before.details.record_version||1)))sttFailure('ST-T记录版本已变化，请载入本条后重新核对',409);
    if(d.measurement_protocol?.method_version&&d.measurement_protocol.method_version!==STT_METHOD)sttFailure('旧ST-T测量方法须重新核对，未改签旧记录');
    d.measurement_protocol=A.sttProtocol(d.measurement_protocol);if(!currentSttProtocol(d.measurement_protocol))sttFailure('当前ST-T测量协议未加载，请刷新后复核');if(d.measurement_protocol.extent==='whole'&&d.measurement_protocol.baseline_method==='manual_iso_point')sttFailure('整段统计不能把单搏手工ISO应用到全部心搏');d.status=['st_depression','st_elevation','t_change','nonspecific'].includes(d.result_code)?'confirmed':['no_change','artifact'].includes(d.result_code)?'excluded':'pending';
    const point=d.point_measurement;if(point){if(typeof point!=='object'||['iso_sample','j_sample','measurement_sample'].some(k=>!Number.isSafeInteger(point[k])||point[k]<0||point[k]>=total)||!(point.iso_sample<point.j_sample&&point.j_sample<=point.measurement_sample)||point.measurement_ms!==d.measurement_protocol.measurement_ms||Math.abs(point.measurement_sample-point.j_sample-d.measurement_protocol.measurement_ms/5)>1)sttFailure('ST-T手工点测量位置或协议无效');}
    const extent=d.review_extent??'point';if(!['point','whole'].includes(extent))sttFailure('ST-T复核作用范围无效');d.review_extent=extent;
    let chosen=null,measured=null;
    if(d.stt_candidate_id){reportScope(d.stt_candidate_scope||{},true);measured=sttReview();if(measured.stale)sttFailure('心搏、来源或测量方法已变化，数学Demo预计算ST-T候选已失效',409);chosen=measured.automatic_candidates?.items?.find(c=>c.id===d.stt_candidate_id);if(!chosen)sttFailure('原ST-T候选已变化，请重选后核对',409);}
    if(d.range_statistics)await demoReview().validateSttRangeSave(payload);
    if(extent==='whole'){
      const exact=chosen&&first===Math.round(chosen.start_s*RATE)&&end+1===Math.round(chosen.end_s*RATE)&&d.review_leads.every(l=>chosen.leads.includes(l)),machineProtocol=A.sttProtocol({measurement_ms:d.measurement_protocol.extent==='whole'?d.measurement_protocol.measurement_ms:60,extent:'whole'}),kind=({st_depression:'st_depression',st_elevation:'st_elevation',t_change:'t_wave_inversion'}[d.result_code])||chosen?.kind||'stt_review';
      const proof={...(exact?Object.fromEntries(['continuous_target_s','peak_time_s','peak_deviation_units','quality_score'].filter(k=>Object.hasOwn(chosen,k)).map(k=>[k,chosen[k]])):{}),kind,start_s:first/RATE,end_s:(end+1)/RATE,duration_s:(end+1-first)/RATE,leads:d.review_leads.slice(),measurement_protocol:machineProtocol,scope:identity,units:'source_device_units',source:exact?'reviewed_automatic_candidate':'physician_selected_range',original_machine_range:chosen?{start_s:chosen.start_s,end_s:chosen.end_s}:null,boundary_resolution_s:exact?16:.005,continuous_target_s:exact?chosen.continuous_target_s??null:null};
      if(chosen)proof.candidate_id=chosen.id;
      if(end+1-first>=12000){
        const cached=chosen?.whole_statistics,useCached=exact&&cached&&machineProtocol.measurement_ms===60&&currentSttProtocol(cached.method_profile)&&!cached.exclusions?.intervals?.length;
        const statistics=useCached?cached:await demoReview().route(new URL(`/api/cases/${caseId}/stt-range`,location.href),'POST',{scope:demoSttScope(),start_sample:first,end_sample:end+1,leads:d.review_leads,measurement_ms:machineProtocol.measurement_ms});
        proof.metrics=copy(statistics.leads.filter(r=>d.review_leads.includes(r.lead)));proof.coverage=copy(statistics.coverage);proof.counts=copy(statistics.counts);proof.measurement_protocol.range_profile=copy(statistics.method_profile);
      }
      proof.rhythm_policy=STT_RHYTHM_POLICY;d.stt_event_evidence=proof;
    }
    if(storageBefore!==localStorage.getItem(STORE_KEY)){
      saved={...copy(savedDefault),...JSON.parse(localStorage.getItem(STORE_KEY)||'{}')};const concurrent=sttReplay(raw,annotationId,requestHash);if(concurrent)return concurrent;sttFailure('验证期间病例已变化，未保存；请重新读取后核对',409);
    }
    reportScope(identity,true);if(sttBeatVersion()!==beatVersion)sttFailure('保存期间心搏依据已变化，未保存',409);
    const previous=copy(saved),reconciliation={removed_selections:[],removed_uses:[],removed_diagnosis_blocks:[],reason:'ST-T记录修订后重新选择本次采用用途'},stamp=now();
    try{
      const list=(saved.annotations[caseId]||=[]),id=annotationId??Math.max(Date.now(),1+Math.max(0,...list.map(a=>Number(a.id)||0)));
      d.record_version=before?(before.details.record_version||1)+1:1;
      if(before){const report=saved.reports[caseId];if(report?.composition){const c=report.composition,eventId='annotation:'+id;reconciliation.removed_selections=(c.selected_events||[]).filter(s=>s.event_id===eventId);reconciliation.removed_uses=(c.stt_report_use||[]).filter(s=>s.event_id===eventId);c.selected_events=(c.selected_events||[]).filter(s=>s.event_id!==eventId);if('stt_report_use'in c)c.stt_report_use=c.stt_report_use.filter(s=>s.event_id!==eventId);reconciliation.removed_diagnosis_blocks=withdrawSttGeneratedText(c,eventId);if(reconciliation.removed_selections.length)d.withdrawn_report_settings=copy(reconciliation.removed_selections);}if(!reconciliation.removed_selections.length&&before.details.withdrawn_report_settings)d.withdrawn_report_settings=copy(before.details.withdrawn_report_settings);d.last_report_reconciliation=copy(reconciliation);}
      const item={...payload,case_id:caseId,id,created_by:before?.created_by||'pages-demo',created_at:before?.created_at||stamp,updated_at:stamp};delete item.expected_record_version;
      if(before)list.splice(list.indexOf(before),1,item);else list.push(item);
      ((saved.sttReviewSubmissions||={})[caseId]||={})[d.submission_id]={request_sha256:requestHash,operation:annotationId===null?'create':'update',annotation_id:id,beat_version:beatVersion,source_digest:sttRawDigest};
      ((saved.sttRecordBindings||={})[caseId]||={})['annotation:'+id]={beat_version:beatVersion,source_digest:sttRawDigest};
      audit('annotation.stt.'+(before?'update':'create'),'仅数学浏览器保存一条医生复核；不生成全程阴性诊断');
      const result=annotationItems().find(a=>a.id===id);result.stt_review_receipt.report_reconciliation=copy(reconciliation);return result;
    }catch(error){saved=previous;throw error;}
  }
  function meanAnnotationPayload(value){
    const details=value.details,allowed=['kind','status','end_sample','finding','range_statistics','submission_id','point_measurement_sample_index'];
    if(!details||typeof details!=='object'||Array.isArray(details)||Object.keys(details).some(key=>!allowed.includes(key)))throw Error('范围统计标注包含未支持的字段');
    const lead=value.lead??'',category=value.category??'note',label=value.label??'人工标注',note=value.note??'';
    if(typeof lead!=='string'||!(lead===''||lead==='全部'||TEMPLATE_LEADS.has(lead))||!['note','N','S','V','noise'].includes(category))throw Error('标注导联或类别无效');
    if(typeof label!=='string'||!label.trim()||typeof note!=='string'||details.finding!==undefined&&typeof details.finding!=='string')throw Error('标注标题、备注与发现须为文本');
    if(Object.hasOwn(details,'submission_id')&&(typeof details.submission_id!=='string'||!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(details.submission_id)))throw Error('区间统计提交编号须为规范 UUID');
    const slice=(text,count)=>Array.from(text).slice(0,count).join(''),trim=text=>text.replace(/^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/g,'');
    const normalized={kind:details.kind,status:details.status,end_sample:details.end_sample,finding:slice(details.finding===undefined?label:details.finding,120),range_statistics:copy(details.range_statistics)};
    for(const key of ['submission_id','point_measurement_sample_index'])if(Object.hasOwn(details,key))normalized[key]=details[key];
    const title=trim(label);if(!title)throw Error('标注标题须为非空文本');
    return {sample_index:value.sample_index,lead:slice(lead,16),category:slice(category,32),label:slice(title,120),note:slice(note,2000),details:normalized};
  }
  function meanSubmission(payload){
    const identifier=payload.details.submission_id;if(identifier===undefined)return null;
    const matches=(saved.annotations[caseId]||[]).filter(row=>row.details?.submission_id===identifier&&row.details?.range_statistics);
    if(matches.length>1){const error=Error('区间统计提交记录重复，请保留工作并核对');error.status=409;throw error;}
    if(!matches.length)return null;
    const existing=matches[0],intent=Object.fromEntries(['sample_index','lead','category','label','note','details'].map(key=>[key,existing[key]]));
    if(JSON.stringify(intent)!==JSON.stringify(payload)){
      // Statistics and details are objects; key order is not a save intent.
      const order=value=>Array.isArray(value)?value.map(order):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(key=>[key,order(value[key])])):value;
      if(JSON.stringify(order(intent))!==JSON.stringify(order(payload))){const error=Error('此提交编号已保存另一份内容；未重复保存或覆盖，请核对已保存标注');error.status=409;throw error;}
    }
    demoReview().assertSttRangeSavedSource(existing.details.range_statistics);return copy(existing);
  }
  function reconcileMeanSubmission(payload){
    if(payload.details.submission_id===undefined)return null;
    saved={...copy(savedDefault),...JSON.parse(localStorage.getItem(STORE_KEY)||'{}')};
    return meanSubmission(payload);
  }

  async function route(url,options={}){
    const path=url.pathname,method=String(options.method||"GET").toUpperCase();
    activeEdited=!!engine&&url.searchParams.get("analysis")==="edited";beats=activeEdited?editedFeed().beats:copy(sourceCase.beats);
    if(path.startsWith('/api/terminology/')||/^\/api\/cases\/[^/]+\/(rr-review(?:\/locate)?|hrv-review(?:\/(preview|confirm|cancel))?|stt-range)$/.test(path)){try{return response(await demoReview().route(url,method,requestBody(options)))}catch(error){return failure(error.message,error.status||400)}}
    if(path==="/api/health")return response({status:"ok",version:sourceCase.software_release_id,case_count:COUNT,data_root_found:true,demo_readonly:true,allow_phi:false});
    if(path==="/api/dashboard"){const item=present();return response({totals:{cases:1,recording_hours:round(duration/3600,2),beats:item.summary.total_beats,pending_reports:report(item).status==="reviewed"?0:1},cases:[item],privacy:{phi_visible:false}})}
    if(path==="/api/cases")return response({items:[present()],total:1});
    if(path==="/api/settings")return response({app_name:"CardioInsight 纯数学交互演示",version:sourceCase.software_release_id,data_root:"全新公式生成的10分钟数学输入；无患者资料",case_count:1,integrity_manifest:{available:true,case_count:1,algorithm:"SHA-256"},platform:{name:"Web",release:"Cloudflare Pages / GitHub Pages",machine:"Browser",storage_root:"localStorage（仅演示修改）",config_path:"无本地配置"},clinical_use:false});
    if(path==="/api/audit")return response({items:saved.audit});
    if(path==="/api/privacy/view")return failure("在线演示不提供身份信息模式切换",403);
    let match=path.match(/^\/api\/annotations\/(\d+)$/);if(match&&method==="DELETE"){const list=saved.annotations[caseId]||[],row=list.find(x=>String(x.id)===match[1]);if(row&&['ST','ST_REVIEW_NOTE'].includes(row.details?.kind)){const c=saved.reports[caseId]?.composition,id='annotation:'+row.id;if(c){c.selected_events=(c.selected_events||[]).filter(s=>s.event_id!==id);if('stt_report_use'in c)c.stt_report_use=c.stt_report_use.filter(s=>s.event_id!==id);withdrawSttGeneratedText(c,id);}}saved.annotations[caseId]=list.filter(x=>String(x.id)!==match[1]);audit("annotation.delete","移除本地标注",!!row&&["AF","AFL"].includes(row.details?.kind));return response({ok:true})}
    match=path.match(/^\/api\/beat-templates\/(\d+)$/);if(match){const templates=saved.templates[caseId]||[],index=templates.findIndex(item=>String(item.id)===match[1]);if(index<0)return failure("模板类别不存在",404);if(method==="PATCH"){const payload=requestBody(options);if(Object.keys(payload).some(k=>!["name","rhythm_family","note"].includes(k)))return failure("只能修改模板名称、家族和备注");const item=templates[index],name=payload.name===undefined?item.name:String(payload.name||"").trim(),family=payload.rhythm_family===undefined?item.rhythm_family:String(payload.rhythm_family);if(!name)return failure("模板类别名称不能为空");if(!TEMPLATE_FAMILIES.has(family))return failure("不支持的节律家族");item.name=name.slice(0,80);item.rhythm_family=family;if(payload.note!==undefined)item.note=String(payload.note||"").slice(0,1200);item.updated_at=now();audit("beat_template.update",`#${item.id} ${item.name}`);persist();return response(copy(item))}if(method==="DELETE"){templates.splice(index,1);audit("beat_template.delete",`#${match[1]}`);persist();return response({ok:true})}}
    match=path.match(/^\/api\/cases\/([^/]+)(?:\/(.*))?$/);if(!match)return failure("接口不存在",404);
    const requestedId=decodeURIComponent(match[1]),action=match[2]||"";if(requestedId!==caseId)return failure("病例不存在",404);
    if(action==='evidence-candidates'){try{return response(reportCandidateRoute(method,method==='GET'?Object.fromEntries(url.searchParams):requestBody(options)))}catch(error){return failure(error.message,error.status||400)}}
    if(['report-rr-evidence','report-evidence/preview','report-evidence/confirm'].includes(action)){try{return response(await reportEvidenceRoute(action,method,method==='GET'?Object.fromEntries(url.searchParams):requestBody(options)))}catch(error){return failure(error.message,error.status||400)}}
    if(action.startsWith("beat-editor")){try{return response(await editorRoute(action,method,requestBody(options)))}catch(error){return failure(error.message)}}
    if(action==="overview")return response({revision:editorValue().revision,duration_s:duration,columns:['sample_index','rr_ms','class_code'],rows:editedFeed().beats.map(r=>[r.sample_index,r.rr_ms,r.class_code]),estimated_beats:sourceCase.summary.total_beats,settings:editorValue().document.settings});
    if(action==="rhythm-review"){
      const previous=copy(saved);
      let removed=[];
      try{
        saved={...savedDefault,...JSON.parse(localStorage.getItem(STORE_KEY)||"{}")};
        const initial=ECGOverviewEngine.initialEpisodes(editedFeed().beats,annotationList(),duration);
        saved.rhythms ||= {};let value=copy(saved.rhythms[caseId]||{revision:0,document:initial,undo:[],redo:[],updated_at:''});
        if(method==='PUT'){
          const p=requestBody(options),basis=demoReviewScope();
          if(p.confirmed!==true)throw Error('请核对修改并明确确认保存');
          if(p.request_id!==undefined&&p.request_id!==null&&(typeof p.request_id!=='string'||!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(p.request_id)))throw Error('保存请求编号无效');
          if(!Number.isSafeInteger(p.revision)||p.revision<0||!Number.isSafeInteger(p.beat_revision)||p.beat_revision<0)throw Error('缺少有效的复核或心搏版本');
          for(const key of ['analysis_revision','beat_revision'])if(p[key]!==undefined&&(!Number.isSafeInteger(p[key])||p[key]<0))throw Error('病例版本必须为非负整数');
          if(Object.keys(basis).some(key=>p[key]!==undefined&&p[key]!==basis[key])||p.revision!==value.revision||p.beat_revision!==editorValue().revision)return failure('病例依据已变化，未保存片段；请重新载入后核对',409);
          const before=copy(value.document),aliases={};clinicalBaseIndex().events.filter(e=>e.category==='AF').forEach(e=>{(aliases[e.rhythm_episode_id]||=[]).push(e.event_id)});
          if(['undo','redo'].includes(p.operation)){if(!value[p.operation].length)throw Error('没有可撤销/重做的操作');value[p.operation==='undo'?'redo':'undo'].push(value.document);value.document=value[p.operation].pop()}
          else if(!p.operation||p.operation==='save'){const document=ECGOverviewEngine.validateDocument(p.document,duration);value.undo=(value.undo.concat([value.document])).slice(-20);value.redo=[];value.document=document}else throw Error('不支持的复核操作');
          value.revision++;value.updated_at=now();saved.rhythms[caseId]=value;
          value.last_operation=p.request_id?{request_id:p.request_id,operation:p.operation||'save',revision:value.revision}:{};
          invalidateWorkflow('annotation.rhythm_review');
          removed=removeRetiredRhythmPicks(before,value.document,aliases);
          saved.audit.unshift({created_at:now(),actor:'pages-demo',case_id:caseId,action:'annotation.rhythm_review',detail:'r'+value.revision});saved.audit=saved.audit.slice(0,300);
          persist();
        }
        else if(method!=='GET')return failure('节律复核接口方法不受支持',405);
        return response({revision:value.revision,document:value.document,can_undo:!!value.undo.length,can_redo:!!value.redo.length,updated_at:value.updated_at,last_operation:value.last_operation||{},removed_report_events:removed,...demoReviewScope()});
      }catch(error){saved=previous;return failure(error.message)}
    }
    if(action==='waveform-density'){
      try{const params=url.searchParams,feed=editedFeed(),template=params.get('template_id'),item=template?templateList().find(t=>String(t.id)===template):null,type=params.get('class_code')||'N',payload=method==='POST'?requestBody(options):{},revision=editorValue().revision;
        if(template&&!item)throw Error('模板不存在');
        if(!template&&type!=='all'&&!engine.types[type])throw Error('不支持的心搏类型');
        if(Object.hasOwn(payload,'revision')&&payload.revision!==revision)throw Error('编辑版本已变化，请重新加载密度图');
        const allowed=item?new Set(item.sample_indices):null,source=feed.beats.filter(r=>allowed?allowed.has(r.sample_index):type==='all'||r.class_code===type).map(r=>r.sample_index),samples=ECGOverviewEngine.densitySamples(source,payload),buffer=await waveformBuffer(),view=new DataView(buffer),lead=params.get('lead')||'II',gate=params.has('gate')?params.get('gate').split(',').map(Number):null;
        if(gate&&(gate.length!==4||gate.some(x=>!Number.isFinite(x))||gate[0]>gate[1]||gate[2]>gate[3]))throw Error('形态框选范围错误');
        const result=await ECGOverviewEngine.density(samples,buffer.byteLength/16,(s,l)=>leadValue(view,s,l),lead,gate,payload.amplitude_limit??null);
        if(revision!==editorValue().revision)throw Error('编辑版本已变化，请重新加载密度图');
        return response({...result,source_total:source.length,revision});
      }catch(error){return failure(error.message)}
    }
    if(!action&&method==="GET")return response(present(true));
    if(action==="open"&&method==="POST"){audit("case.open","打开病例");return response({ok:true})}
    if(action==="template-occurrences"||action==="report-events"){try{return response(ECGClinicalAnalysis.queryIndex(clinicalIndex(),url.searchParams,action==="template-occurrences"))}catch(error){return failure(error.message)}}
    if(action==="event-waveform"){url.searchParams.set("whole","1");url.searchParams.set("duration",Math.max(1,Number(url.searchParams.get("end"))-Number(url.searchParams.get("start"))));url.searchParams.set("filter","raw");return response(await waveform(url.searchParams))}
    if(action==='event-waveforms'&&method==='POST'){
      try{const p=requestBody(options);
        if(!Array.isArray(p.ranges)||!p.ranges.length||p.ranges.length>32)throw Error('每批需包含 1–32 个波形区间');
        const leads=p.leads||['II','V1','V5'],maxPoints=p.max_points??1200;
        if(!Array.isArray(leads)||!leads.length||leads.length>12||leads.some(l=>!TEMPLATE_LEADS.has(l))||new Set(leads).size!==leads.length)throw Error('导联包含不支持或重复的值');
        if(!Number.isInteger(maxPoints)||maxPoints<200||maxPoints>1200)throw Error('波形采样点数错误');
        if(p.ranges.some(r=>!r||![r.start,r.end].every(x=>typeof x==='number'&&Number.isFinite(x))||r.start<0||r.end<r.start+1||r.end>2678400))throw Error('波形区间格式错误');
        const items=[];for(const r of p.ranges)items.push(await waveform(new URLSearchParams({whole:'1',filter:'raw'}),{start:r.start,duration:r.end-r.start,leads,maxPoints,filter:'raw'}));
        return response({items});
      }catch(error){return failure(error.message)}
    }
    if(action==="report-statistics"){const feed={...editedFeed(),duration},result=ECGReportEngine.statistics(clinicalIndex(),sourceCase.metadata.start_iso||sourceCase.metadata.start_time,feed.document.settings);result.hrv=engine.hrv(feed,duration);return response(result)}
    if(action==="report-sections")return response(ECGReportSections.evidence(clinicalIndex(),sttReview()));
    if(['report-af-representatives','report-strip-preview'].includes(action)){
      if(method!=='GET')return failure('此图条接口仅支持只读GET',405);
      try{
        const own=reportScope(Object.fromEntries(url.searchParams)),index=clinicalIndex(),raw={duration_s:Number(url.searchParams.get('duration')||7)},leadArg=url.searchParams.get('leads');if(leadArg)raw.leads=leadArg.split(',');
        if(action==='report-af-representatives'){
          const event=index.events.find(e=>e.event_id===url.searchParams.get('event_id'));
          if(!event||event.category!=='AF'||url.searchParams.has('basis_version')&&url.searchParams.get('basis_version')!==event.basis_version)return failure('房颤／房扑片段依据已变化，请重新选择',409);
          return response({...ECGReportEngine.afRepresentatives(index,event,raw),event_id:event.event_id,basis_version:event.basis_version,...own});
        }
        const time=Number(url.searchParams.get('time_s')??url.searchParams.get('time')??0);number(time,'留图定位时间',0,Math.max(0,duration-.005));
        if(url.searchParams.has('range_start_s')||url.searchParams.has('range_end_s'))for(const key of ['range_start_s','range_end_s']){if(!url.searchParams.has(key))throw Error('人工区间须同时提供起止时间');raw[key]=Number(url.searchParams.get(key));}
        const event={event_id:'preview-only',category:'other',subtype:'manual_strip',label:'人工波形图条',start_sample:Math.floor(time*200+.5),time_s:time},spec=ECGReportEngine.resolve(index,event,ECGReportEngine.settingsForEvent(event,raw)),params=new URLSearchParams({whole:'1',filter:'raw'});
        const wave=await waveform(params,{start:spec.start_s,duration:spec.actual_duration_s,leads:spec.leads,maxPoints:12000,filter:'raw'});wave.beats=spec.visible_beats;
        const context=await waveform(params,{start:spec.context_start_s,duration:spec.context_duration_s,leads:['II'],maxPoints:1600,filter:'raw'});reportScope(own,true);
        return response({event,strip:spec,waveform:wave,context,preview_only:true,...own});
      }catch(error){return failure(error.message,error.status||400)}
    }
    if(action==="report-strip"){
      const index=clinicalIndex(),event=index.events.find(e=>e.event_id===url.searchParams.get('event_id'));
      if(!event||event.basis_version!==url.searchParams.get('basis_version'))return failure('图条依据已变化，请重新选择事件',409);
      try{const manual=url.searchParams.has('range_start_s')||url.searchParams.has('range_end_s')?{range_start_s:Number(url.searchParams.get('range_start_s')),range_end_s:Number(url.searchParams.get('range_end_s'))}:{};const spec=ECGReportEngine.resolve(index,event,{leads:String(url.searchParams.get('leads')||'II,V1,V5').split(','),duration_s:Number(url.searchParams.get('duration')||7),...manual}),params=new URLSearchParams({whole:'1',filter:'raw'});
        const wave=await waveform(params,{start:spec.start_s,duration:spec.actual_duration_s,leads:spec.leads,maxPoints:12000,filter:'raw'});wave.beats=spec.visible_beats;
        const context=await waveform(params,{start:spec.context_start_s,duration:spec.context_duration_s,leads:['II'],maxPoints:1600,filter:'raw'});
        return response({...event,strip:spec,waveform:wave,context});
      }catch(error){return failure(error.message)}
    }
    if(action==="hrv-windows")return response(ECGClinicalAnalysis.hrvWindows({...editedFeed(),duration},sourceCase.metadata.start_iso||sourceCase.metadata.start_time,Number(url.searchParams.get("window")||0)));
    if(action==='hrv-analysis'){
      let data;try{data=await demoReview().analysis(Number(url.searchParams.get('window')||0),Object.fromEntries(url.searchParams));}catch(error){return failure(error.message,error.status||400)}
      data.representatives=[];const index=clinicalIndex();data.event_statistics=ECGReportEngine.statistics(index,sourceCase.metadata.start_iso||sourceCase.metadata.start_time,editedFeed().document.settings);
      for(const category of ['fastest','slowest','V','S','pause']){const candidates=index.events.filter(e=>e.category===category&&e.time_s>=data.start_s&&e.time_s<data.end_s&&(!['fastest','slowest'].includes(category)||e.subtype==='RR'));if(['fastest','slowest'].includes(category))candidates.sort((a,b)=>(category==='fastest'?-1:1)*(a.hr-b.hr)||a.time_s-b.time_s);const event=candidates[0];if(!event)continue;const spec=ECGReportEngine.resolve(index,event,{leads:['II']});const wave=await waveform(new URLSearchParams({whole:'1',filter:'raw'}),{start:spec.start_s,duration:spec.actual_duration_s,leads:['II'],maxPoints:1000,filter:'raw'});data.representatives.push({...event,strip:spec,waveform:wave})}
      return response(data);
    }
    if(action==="review-workflow"&&method==="GET")return response(workflow());
    if(action==="review-workflow"&&method==="PUT"){try{return response(confirmWorkflow(requestBody(options)))}catch(error){return failure(error.message)}}
    if(action==="event-reviews"&&method==="PUT"){try{return response(reviewEvents(requestBody(options)))}catch(error){return failure(error.message)}}
    if(action==='waveform-overview'&&method==='GET')return response(await waveformOverview(url.searchParams));
    if(action==="trend")return response(trend());if(action==="hrv")return response(hrv());if(action==="stt-review")return response(sttReview());if(action==="rr-visuals")return response(rrVisuals());if(action==="waveform")return response(await waveform(url.searchParams));if(action==="beat-templates"&&method==="GET")return response({items:templateList()});if(action==="beat-templates"&&method==="POST"){try{return response(saveTemplate(requestBody(options)),201)}catch(error){return failure(error.message)}}if(action==="beat-overrides"&&method==="GET")return response({items:overrideList()});if(action==="beat-overrides"&&method==="PUT"){try{const items=saveOverrides(requestBody(options));return response({items,changed:items.length})}catch(error){return failure(error.message)}}if(action==="beat-overrides"&&method==="DELETE"){try{return response({ok:true,changed:restoreOverrides(requestBody(options))})}catch(error){return failure(error.message)}}
    if(action==="scatter"){const data=scatter(url.searchParams.get("mode")||"rr",Math.floor(Number(url.searchParams.get("hour_start_s")||0)/3600)*3600,Number(url.searchParams.get("max_points")||12000));delete data._all;return response(data)}
    if(action==="scatter-selection"&&method==="POST"){
      const payload=requestBody(options),mode=payload.mode||"rr",polygon=payload.polygon,hour=number(payload.hour_start_s??0,"小时起点",0,2678400);
      if(!["rr","n","nn","s","v","hour"].includes(mode))throw Error("不支持的散点模式");
      if(!Array.isArray(polygon)||polygon.length<3||polygon.length>128||polygon.some(p=>!Array.isArray(p)||p.length!==2||p.some(v=>typeof v!=="number"||!Number.isFinite(v)||Math.abs(v)>1e9)))throw Error("圈选边界必须包含 3–128 个有限坐标点");
      const data=scatter(mode,hour,1e9),chosen=data._all.filter(point=>inside(point.x,point.y,polygon));return response({mode,total:chosen.length,sample_indices:chosen.map(x=>x.sample_index),group_counts:chosen.reduce((result,x)=>(result[x.group]=(result[x.group]||0)+1,result),{}),exact:true,hour_start_s:mode==="hour"?hour:null,hour_end_s:mode==="hour"?hour+3600:null});
    }
    if(action==="waveform-strips"&&method==="POST"){
      const payload=requestBody(options),samples=payload.sample_indices,leads=payload.leads||["II","V1","V5"],pre=number(payload.pre_s??1.5,"片段前时长",.2,3),post=number(payload.post_s??2.5,"片段后时长",.4,5),maxPoints=number(payload.max_points??800,"采样点数",200,1200,true),filter=payload.filter||"display",bySample=new Map(beats.map(b=>[b.sample_index,b]));
      if(!Array.isArray(samples)||!samples.length||samples.length>32||samples.some(s=>!Number.isInteger(s)||!bySample.has(s))||new Set(samples).size!==samples.length)throw Error("每批须为 1–32 个不重复的现有心搏位置");
      if(!Array.isArray(leads)||!leads.length||leads.length>6||leads.some(l=>!TEMPLATE_LEADS.has(l))||new Set(leads).size!==leads.length)throw Error("导联包含不支持或重复的值");
      if(pre+post>6||!["display","raw"].includes(filter))throw Error("片段时长或滤波参数错误");
      const items=await Promise.all(samples.map(async sample=>{const beat=bySample.get(sample),wave=await waveform(new URLSearchParams(),{start:sample/RATE-pre,duration:pre+post,leads,maxPoints,filter});return {...wave,...beat,sample_index:sample,time_s:sample/RATE,start_s:wave.start_s,duration_s:wave.duration_s,anchor_offset_s:sample/RATE-wave.start_s,display_sample_rate_hz:wave.display_sample_rate_hz,leads:wave.leads};}));return response({sample_rate_hz:RATE,...rawSignalMetadata(),items});
    }
    if(action==="events")return response(eventData(url.searchParams));
    if(action==="annotations"&&method==="GET")return response({items:annotationItems()});
    if((action==='annotations'&&method==='POST'&&requestBody(options).details?.reviewed===true)||(/^annotations\/\d+$/.test(action)&&method==='PUT')){try{return response(await saveSttRecord(requestBody(options),action==='annotations'?null:Number(action.split('/')[1])),method==='POST'?201:200)}catch(error){return failure(error.message,error.status||400)}}
    if(action==="annotations"&&method==="POST"){
      let payload=requestBody(options);
      if(payload.details&&Object.hasOwn(payload.details,'stt_event_evidence'))return failure('ST-T 机器事件证据不能由客户端自行填入');
      if(payload.details&&Object.hasOwn(payload.details,'stt_candidate_id')){
        const d=payload.details;if(d.kind!=='ST'||Object.hasOwn(d,'range_statistics'))return failure('自动 ST-T 整段复核与范围均值分别保存');
        const identity=reportScope(d.stt_candidate_scope||{},true),measured=sttReview();
        if(measured.stale)return failure('心搏、来源或测量方法已变化，数学 Demo 预计算 ST-T 候选已失效',409);
        const candidate=measured.automatic_candidates?.items?.find(c=>c.id===d.stt_candidate_id);
        if(!candidate)return failure('ST-T 连续事件依据已变化，请重新读取候选',409);
        if(payload.sample_index!==Math.round(candidate.start_s*200)||d.end_sample!==Math.round(candidate.end_s*200)-1)return failure('整段 ST-T 复核范围须与所选候选完整起止一致');
        d.stt_event_evidence={...Object.fromEntries(['kind','start_s','end_s','duration_s','continuous_target_s','peak_time_s','peak_deviation_units','leads','quality_score'].map(k=>[k,candidate[k]])),candidate_id:candidate.id,algorithm_version:measured.analysis.algorithm_version,scope:identity,source:'reviewed_automatic_candidate',units:'source_device_units',rhythm_policy:STT_RHYTHM_POLICY,measurement_protocol:ECGClinicalAnalysis.sttProtocol({extent:'whole'})};
      }
      if(payload.details&&Object.hasOwn(payload.details,'range_statistics')){
        payload=meanAnnotationPayload(payload);
        const existing=meanSubmission(payload);if(existing)return response(existing,201);
        const storedBefore=localStorage.getItem(STORE_KEY);let checked;
        try{checked=await demoReview().validateSttRangeSave(payload)}
        catch(error){if(error.status===409){const concurrent=reconcileMeanSubmission(payload);if(concurrent)return response(concurrent,201)}throw error}
        if(storedBefore!==localStorage.getItem(STORE_KEY)){
          const concurrent=reconcileMeanSubmission(payload);if(concurrent)return response(concurrent,201);
          return failure('验证期间病例已变化，未保存；请重新计算后核对',409);
        }
        // No asynchronous work occurs between this final identity guard and
        // the single localStorage commit of annotation, audit and revisions.
        demoReview().assertSttRangeSaveCurrent(checked);
        const previous=copy(saved),item={...payload,case_id:caseId,id:nextAnnotationId(),created_by:"pages-demo",created_at:now()};
        try{(saved.annotations[caseId]||(saved.annotations[caseId]=[])).push(item);audit("annotation.create","仅保存于当前浏览器；纯数学范围统计摘要");return response(item,201)}
        catch(error){saved=previous;throw error}
      }
      const item={...payload,id:nextAnnotationId(),created_by:"pages-demo",created_at:now()};(saved.annotations[caseId]||(saved.annotations[caseId]=[])).push(item);audit("annotation.create","仅保存于当前浏览器",["AF","AFL"].includes(item.details?.kind));return response(item,201);
    }
    if(action==="patient"&&method==="PATCH"){saved.patients[caseId]={...(saved.patients[caseId]||{}),...requestBody(options)};audit("patient.update","仅保存于当前浏览器");return response(saved.patients[caseId])}
    if(action==="report"&&method==="GET"){const value=report(present());return response({...value,current_hrv_reference:await demoReview().reference(value.composition.hrv_window||0)});}
    if(action==="report"&&method==="PUT"){
      const payload=requestBody(options);
      if(!["draft","reviewed","returned"].includes(payload.status||"draft"))return failure("invalid report status");
      if(payload.status==="reviewed"&&(workflow().pending_steps.length||!String(payload.conclusion||"").trim()))return failure("请先确认全部复核环节并填写结论");
      const old=report(present());
      if(!Number.isInteger(payload.expected_version)||payload.expected_version!==old.version)return failure("报告版本已变更，请重新载入",409);
      if(!Number.isInteger(payload.expected_review_revision)||payload.expected_review_revision!==workflow().revision)return failure("报告复核依据已变更，请重新载入",409);
      const composition=copy(payload.composition||old.composition);let mergedRR=[];
      try{
        if(Object.hasOwn(composition,'stt_trend_metric')&&!['st_level','delta'].includes(composition.stt_trend_metric))throw Error('ST趋势指标须为ST电平或ΔST');
        if(Object.hasOwn(composition,'stt_report_use'))composition.stt_report_use=ECGClinicalAnalysis.sttNormalizedUses(composition.stt_report_use);
        composition.strip_defaults=ECGReportEngine.settings(composition.strip_defaults);
        const entries=(composition.selected_events||[]).map(s=>({...s,...ECGReportEngine.settings(s)})),index=clinicalIndex();
        composition.selected_events=ECGClinicalAnalysis.normalizeReportSelections(index,entries);
        if(composition.selected_events.some(s=>s.strip_id!==undefined||s.representative_role!==undefined))composition.schema_version=3;
        const retained=new Set(composition.selected_events);mergedRR=entries.filter(s=>!retained.has(s)).map(s=>s.event_id);
        ECGClinicalAnalysis.validateReport(index,composition,workflow(),payload.status==="reviewed");
        await demoReview().validateReport(composition,payload.status==="reviewed");
      }catch(error){return failure(error.message,error.status||400)}
      const item={status:payload.status||"draft",version:old.version+1,conclusion:String(payload.conclusion||""),composition,updated_at:now()};
      saved.reports[caseId]=item;audit(`report.${item.status}`,"仅保存于当前浏览器");persist();return response({...report(present()),rr_merged_event_ids:mergedRR});
    }
    return failure("接口不存在",404);
  }

  // Browser demo identity is a local revision, not a verified raw-file fingerprint.
  const clinicalReads=new Set(['','analysis-basis','report','overview','rhythm-review','trend','rr-visuals','scatter','hrv','hrv-windows','hrv-analysis','stt-review','report-statistics','report-sections','template-occurrences','report-events','waveform','waveform-overview','event-waveform','event-waveforms','report-strip','report-af-representatives','report-strip-preview','evidence-candidates','report-rr-evidence','report-evidence/preview','waveform-density','scatter-selection','waveform-strips','rr-review','rr-review/locate','hrv-review','stt-range']);
  async function clinicalRoute(url,options){
    const match=url.pathname.match(/^\/api\/cases\/([^/]+)(?:\/(.*))?$/),action=match?.[2]||'',method=String(options.method||'GET').toUpperCase();
    if(!match||decodeURIComponent(match[1])!==caseId||!clinicalReads.has(action)||(method!=='GET'&&!(['event-waveforms','waveform-density','scatter-selection','waveform-strips','rr-review/locate','stt-range','report-evidence/preview'].includes(action)&&method==='POST')))return route(url,options);
    const stored=localStorage.getItem(STORE_KEY);
    saved={...copy(savedDefault),...JSON.parse(stored||'{}')};
    const basis={case_id:caseId,analysis_basis:'public-math-4314-v2:'+caseId,analysis_revision:workflow().revision,beat_revision:editorValue().revision};
    const expected=action==='stt-range'?{}:method==='POST'?requestBody(options):Object.fromEntries(url.searchParams);
    if(Object.keys(basis).some(key=>expected[key]!==undefined&&String(expected[key])!==String(basis[key])))return failure('分析依据已变化，请重新读取后复核',409);
    const result=action==='analysis-basis'?response(basis):await route(url,options);
    if(!result.ok)return result;
    if(stored!==localStorage.getItem(STORE_KEY)||basis.analysis_revision!==workflow().revision)return failure('分析期间病例已变化，请重新读取后复核',409);
    const payload=await result.json();
    if(action==='stt-review'&&payload.stale)return response(payload,result.status);
    if(['event-waveforms','waveform-strips'].includes(action))payload.items=payload.items.map(item=>({...item,...basis}));
    return response({...payload,...(action?basis:{clinical_identity:basis})},result.status);
  }
  window.fetch=(input,options={})=>{
    const raw=typeof input==="string"?input:input?.url,url=new URL(raw,location.href),signal=options.signal||input?.signal;
    if(!url.pathname.startsWith("/api/"))return nativeFetch(input,options);
    const abort=()=>{if(signal?.aborted)throw new DOMException('读取已取消','AbortError');};
    const method=String(options.method||'GET').toUpperCase(),readPost=/\/(event-waveforms|waveform-density|scatter-selection|waveform-strips|preview|locate|stt-range)$/.test(url.pathname),reviewPreview=/\/hrv-review\/preview$/.test(url.pathname),mutation=method!=='GET'&&(!readPost||reviewPreview);
    const run=async()=>{
      abort();saved={...copy(savedDefault),...JSON.parse(localStorage.getItem(STORE_KEY)||'{}')};const previous=copy(saved);
      try{if(/\/(?:stt-review|report|report-events|report-sections|report-strip|annotations)(?:\/\d+)?$/.test(url.pathname)&&(sourceCase.stt_review||(saved.annotations[caseId]||[]).some(a=>['ST','ST_REVIEW_NOTE'].includes(a.details?.kind))))await prepareDemoSttSource().catch(()=>null);const result=await clinicalRoute(url,options);if(!mutation)abort();if(!result.ok&&mutation)saved=previous;return result;}
      catch(error){if(mutation)saved=previous;if(error.name==='AbortError')throw error;return failure(error.message,error.status||400);}
    };
    return mutation&&globalThis.navigator?.locks?navigator.locks.request(STORE_KEY,{signal},run):Promise.resolve().then(run);
  };
})();
