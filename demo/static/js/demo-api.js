"use strict";

/* Browser-only API for the single published ECG case. */
(() => {
  const RATE=200,COUNT=1,STORE_KEY="cardioinsight-pages-single-case-v1";
  const ASSET_BASE="static/demo-data/uploaded-sim-af-001";
  const sourceCase=window.__CARDIOINSIGHT_UPLOADED_CASE__;
  if(!sourceCase)throw new Error("病例数据资源未加载");

  const nativeFetch=window.fetch.bind(window),savedDefault={reports:{},annotations:{},patients:{},audit:[]};
  let saved={...savedDefault};
  try{saved={...savedDefault,...JSON.parse(localStorage.getItem(STORE_KEY)||"{}")} }catch(_){/* unavailable */}
  const persist=()=>{try{localStorage.setItem(STORE_KEY,JSON.stringify(saved))}catch(_){/* unavailable */}};
  const copy=value=>JSON.parse(JSON.stringify(value));
  const round=(value,digits=2)=>{if(!Number.isFinite(value))return null;const p=10**digits;return Math.round(value*p)/p};
  const response=(value,status=200)=>new Response(JSON.stringify(value),{status,headers:{"Content-Type":"application/json; charset=utf-8","Cache-Control":"no-store"}});
  const failure=(message,status=400)=>response({error:message},status);
  const requestBody=options=>{try{return options?.body?JSON.parse(options.body):{}}catch(_){return {}}};
  const now=()=>new Date().toISOString().replace("T"," ").slice(0,19);
  const caseId=sourceCase.case_id;
  const duration=Number(sourceCase.technical.duration_seconds_raw);
  const beats=copy(sourceCase.beats);
  const candidateWindow=sourceCase.simulation_profile.rhythm_candidate_windows_s[0];
  const audit=(action,detail="")=>{saved.audit.unshift({created_at:now(),actor:"pages-demo",case_id:caseId,action,detail});saved.audit=saved.audit.slice(0,300);persist()};

  function annotationList(){
    const initial=[{id:-1,sample_index:candidateWindow[0]*RATE,lead:"II",category:"rhythm",label:"房颤候选片段",note:"直接读取已上传的源 DATA 片段",created_by:"published-case",created_at:"2026-08-12 09:00:00"}];
    return initial.concat(saved.annotations[caseId]||[]);
  }
  const report=item=>copy(saved.reports[caseId]||{status:"draft",version:1,conclusion:item.conclusion,updated_at:""});
  function present(detailed=false){
    const item=copy(sourceCase);delete item.beats;
    if(saved.patients[caseId])Object.assign(item.metadata,saved.patients[caseId]);
    if(detailed){
      const valid=beats.filter(x=>x.group!==34),rr=valid.map(x=>x.rr_ms),groups={};
      beats.forEach(x=>groups[x.group]=(groups[x.group]||0)+1);
      const longest=valid.reduce((a,b)=>a.rr_ms>b.rr_ms?a:b);
      item.calculated={record_count:beats.length,valid_beats:valid.length,first_beat_time_s:valid[0]?.time_s||0,group_counts:Object.fromEntries(Object.entries(groups).map(([key,value])=>[String(key),value])),avg_hr_from_duration:round(valid.length*60/duration),avg_hr_from_rr:round(60000/(rr.reduce((a,b)=>a+b,0)/rr.length)),longest_rr_ms:longest.rr_ms,longest_rr_time_s:longest.time_s,min_rr_ms:Math.min(...rr),format_verified:true};
      item.report_workflow=report(item);item.annotations=annotationList();
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
    const calculated={nn_count:nn.length,mean_nn_ms:round(mean(nn)),sdnn_ms:round(sampleDeviation(nn)),sdann_ms:round(sampleDeviation(segmentMeans)),sdnn_index_ms:round(mean(segmentDeviations)),rmssd_ms:round(successiveDifferences.length?Math.sqrt(mean(successiveDifferences.map(value=>value**2))):null),pnn50_pct:round(successiveDifferences.length?successiveDifferences.filter(value=>Math.abs(value)>50).length*100/successiveDifferences.length:null),triangular_index:round(peak?nn.length/peak:null),method:"当前 10 分钟源 EBI 片段；5 分钟分段；三角指数箱宽 1/128 秒"};
    return {source,calculated,comparison:{source_label:"完整源报告",source_duration:sourceCase.metadata.source_record_duration_text,calculated_label:"当前公开片段重算",calculated_duration:sourceCase.metadata.duration_text,warning:"统计时长不同；10 分钟 SDANN、SDNN index 与三角指数仅作演示估计，不应解释为算法误差或临床结论。"}};
  }
  function rrVisuals(){
    const normal=beats.filter(x=>x.group===1&&x.rr_ms>=300&&x.rr_ms<=2000).map(x=>x.rr_ms),histogram=Array.from({length:35},(_,index)=>({start_ms:300+index*50,end_ms:350+index*50,count:0}));
    normal.forEach(value=>histogram[Math.min(34,Math.max(0,Math.floor((value-300)/50)))].count++);
    const step=Math.max(1,Math.floor(normal.length/900)),poincare=[];for(let index=step;index<normal.length;index+=step)poincare.push([normal[index-step],normal[index]]);
    return {histogram,poincare};
  }

  let waveformPromise=null;
  async function waveformBuffer(){
    if(!waveformPromise)waveformPromise=nativeFetch(`${ASSET_BASE}/waveform.bin`).then(result=>{if(!result.ok)throw new Error(`波形资源加载失败（${result.status}）`);return result.arrayBuffer()});
    return waveformPromise;
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
  async function waveform(params,forced={}){
    const buffer=await waveformBuffer(),view=new DataView(buffer),start=Math.max(0,Math.min(duration-1,Number(forced.start??params.get("start")??0))),windowSeconds=Math.max(.5,Math.min(120,duration-start,Number(forced.duration??params.get("duration")??10))),supported=["I","II","III","aVR","aVL","aVF","V1","V2","V3","V4","V5","V6"],leads=forced.leads||String(params.get("leads")||"II,V1,V5").split(",").filter(x=>supported.includes(x)),max=Math.max(200,Math.min(12000,Number(forced.maxPoints??params.get("max_points")??4000))),startSample=Math.floor(start*RATE),sampleCount=Math.min(Math.floor(windowSeconds*RATE),buffer.byteLength/16-startSample),stride=Math.max(1,Math.ceil(sampleCount/max)),applyFilter=(forced.filter||params.get("filter")||"display")!=="raw",data={};
    leads.forEach(lead=>{let values=Array.from({length:sampleCount},(_,offset)=>leadValue(view,startSample+offset,lead));if(applyFilter)values=displayFilter(values);data[lead]=values.filter((_,offset)=>offset%stride===0)});
    return {start_s:round(startSample/RATE,3),duration_s:round(sampleCount/RATE,3),sample_rate_hz:RATE,display_sample_rate_hz:RATE/stride,stride,units:"µV",filter:applyFilter?"0.5–40 Hz display filter":"raw",calibration_note:"已上传源 DATA 片段 · 未建立计量学溯源",leads:data,beats:beats.filter(x=>x.time_s>=start&&x.time_s<=start+windowSeconds),annotations:annotationList().filter(x=>x.sample_index/RATE>=start&&x.sample_index/RATE<=start+windowSeconds)};
  }
  function scatter(mode="rr",hour=0,max=12000){
    const points=[];
    for(let index=1;index<beats.length-1;index++){const previous=beats[index-1],current=beats[index],following=beats[index+1];if(mode==="n"&&current.group!==1||mode==="nn"&&!(previous.group===1&&current.group===1&&following.group===1)||mode==="s"&&current.group!==2||mode==="v"&&current.group!==3)continue;if(mode==="hour"&&(current.time_s<hour||current.time_s>=hour+3600))continue;points.push({sample_index:current.sample_index,time_s:current.time_s,x:current.rr_ms,y:following.rr_ms,rr_ms:current.rr_ms,next_rr_ms:following.rr_ms,previous_group:previous.group,group:current.group,next_group:following.group,label:current.label})}
    const stride=Math.max(1,Math.ceil(points.length/max)),shown=points.filter((_,index)=>index%stride===0).slice(0,max),upper=points.some(x=>x.x>2000||x.y>2000)?3000:2000;
    return {mode,definition:"源逐搏 RR 配对",candidate_count:points.length,returned_count:shown.length,sampled:shown.length<points.length,sampling:"deterministic-temporal",hour_start_s:mode==="hour"?hour:null,hour_end_s:mode==="hour"?hour+3600:null,axis:{x_label:"RR(i)",y_label:"RR(i+1)",x_unit:"ms",y_unit:"ms"},bounds:{x_min:0,x_max:upper,y_min:0,y_max:upper},points:shown,_all:points};
  }
  function inside(x,y,polygon){let hit=false,previous=polygon.length-1;for(let index=0;index<polygon.length;index++){const a=polygon[index],b=polygon[previous];if((a[1]>y)!==(b[1]>y)&&x<=(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0])hit=!hit;previous=index}return hit}
  function eventData(params){
    const type=params.get("type")||"all",brady=Number(params.get("brady")||50),tachy=Number(params.get("tachy")||120),pause=Number(params.get("pause")||2.5),limit=Number(params.get("limit")||500),summary={AF:0,V:0,S:0,pause:0,tachy:0,brady:0,noise:0},items=[];
    beats.forEach(beat=>{let kind,label,severity;if(beat.af_onset){kind="AF";label="房颤候选片段";severity="high"}else if(beat.group===2){kind="S";label="室上性候选心搏";severity="medium"}else if(beat.group===3){kind="V";label="室性候选心搏";severity="high"}else if(beat.group===34){kind="noise";label="噪声/待确认心搏";severity="low"}else if(beat.rr_ms>=pause*1000){kind="pause";label=`长 RR 间期 ${(beat.rr_ms/1000).toFixed(2)}s`;severity="high"}else if(beat.hr>=tachy){kind="tachy";label=`心动过速候选 ${Math.round(beat.hr)} bpm`;severity="medium"}else if(beat.hr<=brady){kind="brady";label=`心动过缓候选 ${Math.round(beat.hr)} bpm`;severity="medium"}else return;summary[kind]++;if(type==="all"||type===kind)items.push({...beat,type:kind,label,severity,review_status:"待复核"})});
    return {summary,total:items.length,offset:0,limit,items:items.slice(0,limit)};
  }

  async function route(url,options={}){
    const path=url.pathname,method=String(options.method||"GET").toUpperCase();
    if(path==="/api/health")return response({status:"ok",version:"0.13.0-single-case",case_count:COUNT,data_root_found:true,demo_readonly:true,allow_phi:false});
    if(path==="/api/dashboard"){const item=present();return response({totals:{cases:1,recording_hours:round(duration/3600,2),beats:item.summary.total_beats,pending_reports:report(item).status==="reviewed"?0:1},cases:[item],privacy:{phi_visible:true}})}
    if(path==="/api/cases")return response({items:[present()],total:1});
    if(path==="/api/settings")return response({app_name:"CardioInsight Holter 病例数据在线演示",version:"0.13.0-single-case",data_root:"徐有德 · 10 分钟源病例片段",case_count:1,integrity_manifest:{available:true,case_count:1,algorithm:"SHA-256"},platform:{name:"Web",release:"Cloudflare Pages / GitHub Pages",machine:"Browser",storage_root:"localStorage（仅演示修改）",config_path:"无本地配置"},clinical_use:false});
    if(path==="/api/audit")return response({items:saved.audit});
    if(path==="/api/privacy/view")return failure("在线演示不提供身份信息模式切换",403);
    let match=path.match(/^\/api\/annotations\/(\d+)$/);if(match&&method==="DELETE"){saved.annotations[caseId]=(saved.annotations[caseId]||[]).filter(x=>String(x.id)!==match[1]);persist();return response({ok:true})}
    match=path.match(/^\/api\/cases\/([^/]+)(?:\/(.*))?$/);if(!match)return failure("接口不存在",404);
    const requestedId=decodeURIComponent(match[1]),action=match[2]||"";if(requestedId!==caseId)return failure("病例不存在",404);
    if(!action&&method==="GET")return response(present(true));
    if(action==="open"&&method==="POST"){audit("case.open","打开病例");return response({ok:true})}
    if(action==="trend")return response(trend());if(action==="hrv")return response(hrv());if(action==="rr-visuals")return response(rrVisuals());if(action==="waveform")return response(await waveform(url.searchParams));
    if(action==="scatter"){const data=scatter(url.searchParams.get("mode")||"rr",Math.floor(Number(url.searchParams.get("hour_start_s")||0)/3600)*3600,Number(url.searchParams.get("max_points")||12000));delete data._all;return response(data)}
    if(action==="scatter-selection"&&method==="POST"){const payload=requestBody(options),data=scatter(payload.mode||"rr",Number(payload.hour_start_s)||0,1e9),chosen=data._all.filter(point=>inside(point.x,point.y,payload.polygon||[]));return response({mode:payload.mode,total:chosen.length,sample_indices:chosen.map(x=>x.sample_index),group_counts:chosen.reduce((result,x)=>(result[x.group]=(result[x.group]||0)+1,result),{}),exact:true,hour_start_s:payload.mode==="hour"?Number(payload.hour_start_s)||0:null,hour_end_s:payload.mode==="hour"?(Number(payload.hour_start_s)||0)+3600:null})}
    if(action==="waveform-strips"&&method==="POST"){const payload=requestBody(options),items=await Promise.all((payload.sample_indices||[]).map(async sample=>{const beat=beats.find(x=>x.sample_index===sample),pre=Number(payload.pre_s||1.5),post=Number(payload.post_s||2.5),wave=await waveform(new URLSearchParams(),{start:sample/RATE-pre,duration:pre+post,leads:payload.leads||["II","V1","V5"],maxPoints:payload.max_points||800,filter:payload.filter||"display"});return {sample_index:sample,time_s:sample/RATE,label:beat?.label||"N",group:beat?.group||1,rr_ms:beat?.rr_ms||0,hr:beat?.hr||null,start_s:wave.start_s,duration_s:wave.duration_s,anchor_offset_s:pre,display_sample_rate_hz:wave.display_sample_rate_hz,leads:wave.leads}}));return response({items})}
    if(action==="events")return response(eventData(url.searchParams));
    if(action==="annotations"&&method==="GET")return response({items:annotationList()});
    if(action==="annotations"&&method==="POST"){const item={...requestBody(options),id:Date.now(),created_by:"pages-demo",created_at:now()};(saved.annotations[caseId]||(saved.annotations[caseId]=[])).push(item);audit("annotation.create","仅保存于当前浏览器");return response(item,201)}
    if(action==="patient"&&method==="PATCH"){saved.patients[caseId]={...(saved.patients[caseId]||{}),...requestBody(options)};audit("patient.update","仅保存于当前浏览器");return response(saved.patients[caseId])}
    if(action==="report"&&method==="GET")return response(report(present()));
    if(action==="report"&&method==="PUT"){const payload=requestBody(options),old=report(present()),item={status:payload.status||"draft",version:old.version+1,conclusion:String(payload.conclusion||""),updated_at:now()};saved.reports[caseId]=item;audit(`report.${item.status}`,"仅保存于当前浏览器");return response(item)}
    return failure("接口不存在",404);
  }

  window.fetch=(input,options={})=>{const raw=typeof input==="string"?input:input?.url,url=new URL(raw,location.href);return url.pathname.startsWith("/api/")?Promise.resolve().then(()=>route(url,options)):nativeFetch(input,options)};
  document.addEventListener("DOMContentLoaded",()=>document.querySelector("#downloadReport")?.addEventListener("click",event=>{event.preventDefault();event.stopImmediatePropagation();const text=`CardioInsight Holter 病例数据在线演示\n${document.querySelector("#reportCaseLabel")?.textContent||"尚未选择病例"}\n\n仅用于研究与软件功能验证，不可用于临床用途。\n`,link=document.createElement("a");link.href=URL.createObjectURL(new Blob([text],{type:"text/plain;charset=utf-8"}));link.download="CardioInsight_病例演示说明.txt";link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000)},true));
})();
