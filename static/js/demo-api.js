"use strict";

/* Browser-only deterministic API. It never reads patient files or external data. */
(() => {
  const RATE=200,DURATION=1800,COUNT=10,STORE_KEY="cardioinsight-pages-demo-v1";
  const nativeFetch=window.fetch.bind(window),beatCache=new Map(),caseCache=new Map();
  const scales={I:.78,II:1,III:.66,aVR:-.82,aVL:.42,aVF:.86,V1:-.48,V2:-.18,V3:.25,V4:.72,V5:1.02,V6:.88};
  const labels={1:"N",2:"S",3:"V",34:"噪声"};
  const diagnoses=["窦性心律","偶发室性候选","偶发室上性候选","心率变异","低心率片段","高心率片段","长 RR 候选","基线漂移","多类事件","常规复核"];
  let saved={reports:{},annotations:{},patients:{},audit:[]};
  try{saved={...saved,...JSON.parse(localStorage.getItem(STORE_KEY)||"{}")}}catch(_){/* unavailable */}
  const persist=()=>{try{localStorage.setItem(STORE_KEY,JSON.stringify(saved))}catch(_){/* unavailable */}};
  const copy=value=>JSON.parse(JSON.stringify(value));
  const round=(value,digits=2)=>{const p=10**digits;return Math.round(value*p)/p};
  const response=(value,status=200)=>new Response(JSON.stringify(value),{status,headers:{"Content-Type":"application/json; charset=utf-8","Cache-Control":"no-store"}});
  const failure=(message,status=400)=>response({error:message},status);
  const requestBody=options=>{try{return options?.body?JSON.parse(options.body):{}}catch(_){return {}}};
  const now=()=>new Date().toISOString().replace("T"," ").slice(0,19);
  function audit(action,caseId="",detail=""){saved.audit.unshift({created_at:now(),actor:"pages-demo",case_id:caseId,action,detail});saved.audit=saved.audit.slice(0,300);persist()}
  function indexOf(caseId){const m=/^SYNTH-(\d{3})$/.exec(caseId||"");const i=m?Number(m[1])-1:-1;return i>=0&&i<COUNT?i:-1}

  function beats(index){
    if(beatCache.has(index))return beatCache.get(index);
    const list=[],base=54+index*4;let time=.62,n=0;
    while(time<DURATION){
      let rr=60000/base*(1+.055*Math.sin(n*.071+index)+.025*Math.sin(n*.019));
      if(n>0&&n%503===0)rr=2680+index*18;
      let group=1;if(n>0&&n%(101-index%3)===0)group=3;else if(n>0&&n%(73+index%4)===0)group=2;else if(n>0&&n%347===0)group=34;
      time+=rr/1000;if(time>=DURATION)break;
      list.push({sample_index:Math.round(time*RATE),time_s:round(time,3),group,label:labels[group],rr_ms:Math.round(rr),hr:round(60000/rr,1)});n++;
    }
    beatCache.set(index,list);return list;
  }
  function baseCase(index){
    if(caseCache.has(index))return caseCache.get(index);
    const all=beats(index),valid=all.filter(x=>x.group!==34),rr=valid.map(x=>x.rr_ms),counts={1:0,2:0,3:0,34:0};all.forEach(x=>counts[x.group]++);
    const avg=round(60000/(rr.reduce((a,b)=>a+b,0)/rr.length),1),num=String(index+1).padStart(2,"0");
    const item={case_id:`SYNTH-${String(index+1).padStart(3,"0")}`,metadata:{name:`合成${num}号`,patient_id:`DEMO-${String(index+1).padStart(4,"0")}`,sex:index%2?"女":"男",age:28+index*5,bed:"在线合成演示",clinical_diagnosis:`${diagnoses[index]}（纯合成）`,requesting_physician:"虚构演示",start_time:`2026-08-${num} 09:00`,start_iso:`2026-08-${num}T09:00:00`,duration_text:"30 分钟"},summary:{total_beats:valid.length,avg_hr:avg,min_hr:Math.round(Math.min(...rr.map(x=>60000/x))),max_hr:Math.round(Math.max(...rr.map(x=>60000/x))),ventricular_beats:counts[3],supraventricular_beats:counts[2],longest_rr_s:round(Math.max(...rr)/1000,3),sdnn_ms:62+index,sdann_ms:48+index,sdnn_index_ms:36+index,rmssd_ms:31+index*.8,pnn50_pct:8+index*.7,triangular_index:18+index*.5},conclusion:`第 ${index+1} 例纯合成浏览器演示。所有候选与统计仅展示交互，不代表真实患者或临床结论。`,technical:{sample_rate_hz:RATE,independent_channels:8,derived_leads:12,sample_format:"synthetic formula",units:"µV（合成演示，无计量含义）",duration_seconds_raw:DURATION,raw_size_bytes:0,report_pages:1},integrity:{manifest_available:true,algorithm:"DETERMINISTIC-SYNTHETIC",file_count:0,case_sha256:"",source_version_warning:false},active:true,phi_masked:true,report_image_urls:[],generated_report_url:"#synthetic-demo"};
    caseCache.set(index,item);return item;
  }
  function annotationList(caseId){const i=indexOf(caseId),initial=[{id:-(i+1),sample_index:(120+i*7)*RATE,lead:"II",category:"note",label:"合成演示标记",note:"由浏览器演示模拟器生成",created_by:"demo-generator",created_at:"2026-08-12 09:00:00"}];return initial.concat(saved.annotations[caseId]||[])}
  const report=item=>copy(saved.reports[item.case_id]||{status:"draft",version:1,conclusion:item.conclusion,updated_at:""});
  function present(index,detailed=false){
    const item=copy(baseCase(index));if(saved.patients[item.case_id])Object.assign(item.metadata,saved.patients[item.case_id]);
    if(detailed){const all=beats(index),valid=all.filter(x=>x.group!==34),rr=valid.map(x=>x.rr_ms),groups={};all.forEach(x=>groups[x.group]=(groups[x.group]||0)+1);const longest=valid.reduce((a,b)=>a.rr_ms>b.rr_ms?a:b);item.calculated={record_count:all.length,valid_beats:valid.length,first_beat_time_s:valid[0]?.time_s||0,group_counts:Object.fromEntries(Object.entries(groups).map(([k,v])=>[String(k),v])),avg_hr_from_duration:round(valid.length*60/DURATION),avg_hr_from_rr:round(60000/(rr.reduce((a,b)=>a+b,0)/rr.length)),longest_rr_ms:longest.rr_ms,longest_rr_time_s:longest.time_s,min_rr_ms:Math.min(...rr),format_verified:true};item.report_workflow=report(item);item.annotations=annotationList(item.case_id)}
    return item;
  }
  function trend(index){const base=baseCase(index).summary.avg_hr,points=[];for(let t=30;t<DURATION;t+=60)points.push({time_s:t,hr:round(base+9*Math.sin(t/247+index)+4*Math.sin(t/73),1)});const values=points.map(x=>x.hr);return {bin_seconds:60,points,min_hr:Math.min(...values),max_hr:Math.max(...values)}}
  function hrv(index){const source=baseCase(index).summary;return {source,calculated:{nn_count:beats(index).filter(x=>x.group===1).length,mean_nn_ms:round(60000/source.avg_hr),sdnn_ms:source.sdnn_ms+1.4,sdann_ms:source.sdann_ms+.8,sdnn_index_ms:source.sdnn_index_ms+1.1,rmssd_ms:source.rmssd_ms+.6,pnn50_pct:source.pnn50_pct+.3,triangular_index:source.triangular_index+.2,method:"纯合成 RR 序列"}}}
  function rrVisuals(index){const normal=beats(index).filter(x=>x.group===1&&x.rr_ms>=300&&x.rr_ms<=2000).map(x=>x.rr_ms),histogram=Array.from({length:35},(_,i)=>({start_ms:300+i*50,end_ms:350+i*50,count:0}));normal.forEach(x=>histogram[Math.min(34,Math.max(0,Math.floor((x-300)/50)))].count++);const step=Math.max(1,Math.floor(normal.length/900)),poincare=[];for(let i=step;i<normal.length;i+=step)poincare.push([normal[i-step],normal[i]]);return {histogram,poincare}}

  const gaussian=(x,c,w)=>Math.exp(-(((x-c)/w)**2));
  function signal(t,index,lead){const bpm=54+index*4+3*Math.sin(t/51+index),period=60/bpm,phase=((t+.07*index)%period)/period;const shape=110*gaussian(phase,.18,.035)-120*gaussian(phase,.36,.014)+1050*gaussian(phase,.39,.012)-230*gaussian(phase,.425,.018)+310*gaussian(phase,.68,.075);return Math.round((shape+45*Math.sin(2*Math.PI*t/8.3+index)+12*Math.sin(2*Math.PI*t*13.1+index*.3))*(scales[lead]??1))}
  function waveform(index,params,forced={}){
    const start=Math.max(0,Math.min(DURATION-1,Number(forced.start??params.get("start")??0))),duration=Math.max(.5,Math.min(120,DURATION-start,Number(forced.duration??params.get("duration")??10))),leads=forced.leads||String(params.get("leads")||"II,V1,V5").split(",").filter(x=>x in scales),max=Math.max(200,Math.min(5000,Number(forced.maxPoints??params.get("max_points")??4000))),count=Math.max(200,Math.min(max,Math.round(duration*RATE)+1)),data={};
    leads.forEach(lead=>{const values=[];for(let n=0;n<count;n++)values.push(signal(start+duration*n/(count-1),index,lead));data[lead]=values});
    return {start_s:round(start,3),duration_s:round(duration,3),sample_rate_hz:RATE,display_sample_rate_hz:round((count-1)/duration),filter:forced.filter||params.get("filter")||"display",calibration_note:"纯数学合成波形 · 无临床或计量学含义",leads:data,beats:beats(index).filter(x=>x.time_s>=start&&x.time_s<=start+duration),annotations:annotationList(baseCase(index).case_id).filter(x=>x.sample_index/RATE>=start&&x.sample_index/RATE<=start+duration)};
  }
  function scatter(index,mode="rr",hour=0,max=12000){const all=beats(index),points=[];for(let n=1;n<all.length-1;n++){const a=all[n-1],b=all[n],c=all[n+1];if(mode==="n"&&b.group!==1||mode==="nn"&&!(a.group===1&&b.group===1&&c.group===1)||mode==="s"&&b.group!==2||mode==="v"&&b.group!==3)continue;if(mode==="hour"&&(b.time_s<hour||b.time_s>=hour+3600))continue;points.push({sample_index:b.sample_index,time_s:b.time_s,x:b.rr_ms,y:c.rr_ms,rr_ms:b.rr_ms,next_rr_ms:c.rr_ms,previous_group:a.group,group:b.group,next_group:c.group,label:b.label})}const stride=Math.max(1,Math.ceil(points.length/max)),shown=points.filter((_,i)=>i%stride===0).slice(0,max),upper=points.some(x=>x.x>2000||x.y>2000)?3000:2000;return {mode,definition:"纯合成逐搏 RR 配对",candidate_count:points.length,returned_count:shown.length,sampled:shown.length<points.length,sampling:"deterministic-browser-demo",hour_start_s:mode==="hour"?hour:null,hour_end_s:mode==="hour"?hour+3600:null,axis:{x_label:"RR(i)",y_label:"RR(i+1)",x_unit:"ms",y_unit:"ms"},bounds:{x_min:0,x_max:upper,y_min:0,y_max:upper},points:shown,_all:points}}
  function inside(x,y,p){let hit=false,j=p.length-1;for(let i=0;i<p.length;i++){const a=p[i],b=p[j];if((a[1]>y)!==(b[1]>y)&&x<=(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0])hit=!hit;j=i}return hit}
  function eventData(index,params){const type=params.get("type")||"all",brady=Number(params.get("brady")||50),tachy=Number(params.get("tachy")||120),pause=Number(params.get("pause")||2.5),limit=Number(params.get("limit")||500),summary={V:0,S:0,pause:0,tachy:0,brady:0,noise:0},items=[];beats(index).forEach(b=>{let kind,label,severity;if(b.group===2){kind="S";label="室上性候选心搏";severity="medium"}else if(b.group===3){kind="V";label="室性候选心搏";severity="high"}else if(b.group===34){kind="noise";label="噪声/待确认心搏";severity="low"}else if(b.rr_ms>=pause*1000){kind="pause";label=`长 RR 间期 ${(b.rr_ms/1000).toFixed(2)}s`;severity="high"}else if(b.hr>=tachy){kind="tachy";label=`心动过速候选 ${Math.round(b.hr)} bpm`;severity="medium"}else if(b.hr<=brady){kind="brady";label=`心动过缓候选 ${Math.round(b.hr)} bpm`;severity="medium"}else return;summary[kind]++;if(type==="all"||type===kind)items.push({...b,type:kind,label,severity,review_status:"待复核"})});return {summary,total:items.length,offset:0,limit,items:items.slice(0,limit)}}

  async function route(url,options={}){
    const path=url.pathname,method=String(options.method||"GET").toUpperCase();
    if(path==="/api/health")return response({status:"ok",version:"0.12.0-static-demo",case_count:COUNT,data_root_found:true,demo_readonly:true,allow_phi:false,synthetic_only:true});
    if(path==="/api/dashboard"){const cases=Array.from({length:COUNT},(_,i)=>present(i));return response({totals:{cases:COUNT,recording_hours:COUNT*.5,beats:cases.reduce((n,x)=>n+x.summary.total_beats,0),pending_reports:cases.filter(x=>report(x).status!=="reviewed").length},cases,privacy:{phi_visible:false,synthetic_only:true}})}
    if(path==="/api/cases")return response({items:Array.from({length:COUNT},(_,i)=>present(i)),total:COUNT});
    if(path==="/api/settings")return response({app_name:"CardioInsight Holter 纯合成在线演示",version:"0.12.0-static-demo",data_root:"浏览器内固定公式（无病例文件）",case_count:COUNT,integrity_manifest:{available:true,case_count:COUNT,algorithm:"DETERMINISTIC-SYNTHETIC"},platform:{name:"Web",release:"GitHub Pages",machine:"Browser",storage_root:"localStorage（仅演示修改）",config_path:"无本地配置"},clinical_use:false});
    if(path==="/api/audit")return response({items:saved.audit});
    if(path==="/api/privacy/view")return failure("纯合成在线演示不提供身份信息模式",403);
    let match=path.match(/^\/api\/annotations\/(\d+)$/);if(match&&method==="DELETE"){Object.keys(saved.annotations).forEach(id=>saved.annotations[id]=(saved.annotations[id]||[]).filter(x=>String(x.id)!==match[1]));persist();return response({ok:true})}
    match=path.match(/^\/api\/cases\/([^/]+)(?:\/(.*))?$/);if(!match)return failure("演示接口不存在",404);
    const caseId=decodeURIComponent(match[1]),action=match[2]||"",index=indexOf(caseId);if(index<0)return failure("合成病例不存在",404);
    if(!action&&method==="GET")return response(present(index,true));
    if(action==="open"&&method==="POST"){audit("case.open",caseId,"打开纯合成病例");return response({ok:true})}
    if(action==="trend")return response(trend(index));if(action==="hrv")return response(hrv(index));if(action==="rr-visuals")return response(rrVisuals(index));if(action==="waveform")return response(waveform(index,url.searchParams));
    if(action==="scatter"){const data=scatter(index,url.searchParams.get("mode")||"rr",Math.floor(Number(url.searchParams.get("hour_start_s")||0)/3600)*3600,Number(url.searchParams.get("max_points")||12000));delete data._all;return response(data)}
    if(action==="scatter-selection"&&method==="POST"){const payload=requestBody(options),data=scatter(index,payload.mode||"rr",Number(payload.hour_start_s)||0,1e9),chosen=data._all.filter(p=>inside(p.x,p.y,payload.polygon||[]));return response({mode:payload.mode,total:chosen.length,sample_indices:chosen.map(x=>x.sample_index),group_counts:chosen.reduce((o,x)=>(o[x.group]=(o[x.group]||0)+1,o),{}),exact:true,hour_start_s:payload.mode==="hour"?Number(payload.hour_start_s)||0:null,hour_end_s:payload.mode==="hour"?(Number(payload.hour_start_s)||0)+3600:null})}
    if(action==="waveform-strips"&&method==="POST"){const payload=requestBody(options),items=(payload.sample_indices||[]).map(sample=>{const beat=beats(index).find(x=>x.sample_index===sample),pre=Number(payload.pre_s||1.5),post=Number(payload.post_s||2.5),wave=waveform(index,new URLSearchParams(),{start:sample/RATE-pre,duration:pre+post,leads:payload.leads||["II","V1","V5"],maxPoints:payload.max_points||800,filter:payload.filter||"display"});return {sample_index:sample,time_s:sample/RATE,label:beat?.label||"N",group:beat?.group||1,rr_ms:beat?.rr_ms||0,hr:beat?.hr||null,start_s:wave.start_s,duration_s:wave.duration_s,anchor_offset_s:pre,display_sample_rate_hz:wave.display_sample_rate_hz,leads:wave.leads}});return response({items})}
    if(action==="events")return response(eventData(index,url.searchParams));
    if(action==="annotations"&&method==="GET")return response({items:annotationList(caseId)});
    if(action==="annotations"&&method==="POST"){const item={...requestBody(options),id:Date.now(),created_by:"pages-demo",created_at:now()};(saved.annotations[caseId]||(saved.annotations[caseId]=[])).push(item);audit("annotation.create",caseId,"仅保存于当前浏览器");return response(item,201)}
    if(action==="patient"&&method==="PATCH"){saved.patients[caseId]={...(saved.patients[caseId]||{}),...requestBody(options)};audit("patient.update",caseId,"仅保存于当前浏览器");return response(saved.patients[caseId])}
    if(action==="report"&&method==="GET")return response(report(baseCase(index)));
    if(action==="report"&&method==="PUT"){const payload=requestBody(options),old=report(baseCase(index)),item={status:payload.status||"draft",version:old.version+1,conclusion:String(payload.conclusion||""),updated_at:now()};saved.reports[caseId]=item;audit(`report.${item.status}`,caseId,"仅保存于当前浏览器");return response(item)}
    return failure("演示接口不存在",404);
  }
  window.fetch=(input,options={})=>{const raw=typeof input==="string"?input:input?.url,url=new URL(raw,location.href);return url.pathname.startsWith("/api/")?Promise.resolve().then(()=>route(url,options)):nativeFetch(input,options)};
  document.addEventListener("DOMContentLoaded",()=>document.querySelector("#downloadReport")?.addEventListener("click",event=>{event.preventDefault();event.stopImmediatePropagation();const text=`CardioInsight Holter 纯合成数据在线演示\n${document.querySelector("#reportCaseLabel")?.textContent||"尚未选择病例"}\n\n不含真实病例，不可用于临床用途。\n`,link=document.createElement("a");link.href=URL.createObjectURL(new Blob([text],{type:"text/plain;charset=utf-8"}));link.download="CardioInsight_纯合成演示说明.txt";link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000)},true));
})();
