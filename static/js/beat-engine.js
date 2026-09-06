"use strict";
/* Portable, deterministic physician-edit engine. UI codes are NOT WFDB codes.
 * The Python implementation is ecg_core/beat_editor.py; parity tests cover both.
 * No automatic disease diagnosis; QRS proposals require physician confirmation. */
(() => {
  const rows=[
    ["N","正常",1,"beat"],["S","房性早搏",2,"beat"],["V","室性早搏",3,"beat"],
    ["J","交界性早搏",2,"beat"],["G","交界性逸搏",4,"beat"],
    ["P","起搏（未细分）",5,"beat"],["PA","心房起搏",5,"beat"],["PV","心室起搏",5,"beat"],["PD","双腔起搏",5,"beat"],["PF","起搏融合波",5,"beat"],
    ["B","束支传导阻滞（未细分）",6,"beat"],["BL","左束支传导阻滞",6,"beat"],["BR","右束支传导阻滞",6,"beat"],
    ["A","房颤",4,"rhythm"],["C","房扑",4,"rhythm"],["F","融合波",7,"beat"],["E","室性逸搏",7,"beat"],
    ["R","室内差异性传导",6,"beat"],["W","房性逸搏",4,"beat"],["O","房早未下传",0,"nonbeat"],
    ["Z","房早伴室内差异性传导",2,"beat"],["M","房颤伴室内差异性传导",4,"rhythm"],["H","房扑伴室内差异性传导",4,"rhythm"],
    ["Y","P波",0,"nonbeat"],["T","T波",0,"nonbeat"],["X","伪差",34,"artifact"],["OTHER","其他／未分类",8,"beat"]
  ];
  const types=Object.fromEntries(rows.map(([code,name,group,kind])=>[code,{code,name,group,kind}]));
  const defaults={lead:"II",refractory_ms:200,sensitivity:4,search_seconds:10,brady:50,tachy:120,pause:2.5,nn_min:300,nn_max:2000};
  const clone=x=>JSON.parse(JSON.stringify(x)),blank=()=>({changes:{},settings:{...defaults},longest_id:null});
  const integer=(v,label,low=0,high=200000000)=>{if(!Number.isInteger(v)||v<low||v>high)throw Error(label+"必须为范围内整数");return v};
  function settings(values){
    if(!values||typeof values!=="object"||Array.isArray(values)||Object.keys(values).some(k=>!(k in defaults)))throw Error("不支持的设置字段");
    const result={...defaults,...values};
    if(!["I","II","III","aVR","aVL","aVF","V1","V2","V3","V4","V5","V6"].includes(result.lead))throw Error("不支持的分析导联");
    [["refractory_ms",100,500],["sensitivity",1,12],["search_seconds",1,60],["brady",20,100],["tachy",80,250],["pause",1.5,10],["nn_min",250,1000],["nn_max",1000,5000]].forEach(([k,lo,hi])=>{if(!Number.isFinite(result[k])||result[k]<lo||result[k]>hi)throw Error(k+" 超出范围")});
    if(result.brady>=result.tachy||result.nn_min>=result.nn_max)throw Error("上下限顺序不正确");
    return result;
  }
  function materialize(source,doc,legacy=[]){
    const map=new Map(source.map(r=>["s:"+r.sample_index,{...r,id:"s:"+r.sample_index,source_sample:r.sample_index,source_group:r.group,class_code:({1:"N",2:"S",3:"V",34:"X"})[r.group]||"OTHER"}]));
    legacy.forEach(r=>{const value=map.get("s:"+r.sample_index);if(value)value.class_code=r.class_code==="O"?"OTHER":r.class_code});
    Object.entries(doc.changes).forEach(([id,r])=>map.set(id,{id,source_sample:null,source_group:null,...map.get(id),...r}));
    const beats=[],markers=[];
    for(const r of map.values()){
      if(r.deleted)continue;
      const row={...r,...types[r.class_code],label:r.class_code,time_s:r.sample_index/200,rr_ms:0,hr:null};delete row.code;
      (row.kind==="nonbeat"?markers:beats).push(row);
    }
    beats.sort((a,b)=>a.sample_index-b.sample_index);markers.sort((a,b)=>a.sample_index-b.sample_index);
    let previous=null;
    beats.forEach(row=>{row.rr_ms=previous&&row.group!==34?(row.sample_index-previous.sample_index)*5:0;row.hr=row.rr_ms?round(60000/row.rr_ms,1):null;previous=row.group!==34?row:null});
    return {beats,markers,document:doc};
  }
  function select(rows,payload){
    const choice=payload.selection||{},scope=choice.scope||"samples";
    if(scope==="all")return rows.slice();
    if(scope==="range"){const start=integer(choice.start,"起点"),end=integer(choice.end,"终点");if(start>end)throw Error("起点晚于终点");return rows.filter(r=>r.sample_index>=start&&r.sample_index<=end)}
    if(scope!=="samples")throw Error("不支持的选区");
    const samples=choice.samples||payload.sample_indices||[];
    if(!Array.isArray(samples)||samples.length>200000)throw Error("选区最多 200000 搏");
    const requested=new Set(samples.map(s=>integer(s,"采样点"))),result=rows.filter(r=>requested.has(r.sample_index));
    if(result.length!==requested.size)throw Error("选区含已删除或移动的心搏，请刷新");return result;
  }
  function apply(source,document,legacy,payload,duration){
    const doc=clone(document),feed=materialize(source,doc,legacy),op=payload.operation;
    const insertedIds=[];
    let chosen=["settings","insert"].includes(op)?[]:select(feed.beats.concat(feed.markers),payload);
    if(!["settings","insert"].includes(op)&&!chosen.length)throw Error("请先选择心搏");
    if(op==="settings"){doc.settings=settings(payload.settings||{});return {document:doc,affected:0}}
    if(op==="relabel"){
      if(!types[payload.class_code])throw Error("未知人工分类");
      chosen.forEach(r=>doc.changes[r.id]={...doc.changes[r.id],sample_index:r.sample_index,class_code:payload.class_code,deleted:false});
    }else if(op==="delete"){chosen.forEach(r=>doc.changes[r.id]={...r,deleted:true})}
    else if(op==="restore"){chosen.forEach(r=>doc.changes[r.id]=r.source_sample===null?{...r,deleted:true}:{sample_index:r.source_sample,class_code:({1:"N",2:"S",3:"V",34:"X"})[r.source_group]||"OTHER",deleted:false})}
    else if(op==="move"){if(chosen.length!==1)throw Error("每次只移动一个 QRS");doc.changes[chosen[0].id]={...chosen[0],sample_index:integer(payload.target_sample,"目标采样点",0,Math.floor(duration*200)-1)}}
    else if(op==="insert"){
      const positions=payload.positions,code=payload.class_code||"OTHER";
      if(!Array.isArray(positions)||!positions.length||positions.length>500)throw Error("每次添加 1–500 个位置");
      positions.forEach(s=>integer(s,"新增采样点",0,Math.floor(duration*200)-1));
      if(new Set(positions).size!==positions.length)throw Error("新增位置不能重复");
      if(types[code]?.kind!=="beat")throw Error("添加 QRS 必须选择心搏类型");
      const occupied=new Set(feed.beats.concat(feed.markers).map(r=>r.sample_index));
      positions.forEach(s=>{if(occupied.has(s))throw Error("目标位置已有标记");let id="i:"+s,suffix=1;while(Object.hasOwn(doc.changes,id))id="i:"+s+":"+suffix++;insertedIds.push(id);doc.changes[id]={id,sample_index:s,class_code:code,source_sample:null,source_group:null,deleted:false}});chosen=positions;
    }else if(op==="longest"){if(chosen.length!==1||!chosen[0].rr_ms)throw Error("请选择有前一心搏的 RR 终点");doc.longest_id=chosen[0].id}
    else throw Error("不支持的编辑命令");
    const final=materialize(source,doc,legacy).beats;
    if(["insert","move","restore"].includes(op)){
      const affected=new Set(op==="insert"?insertedIds:chosen.map(r=>r.id)),valid=final.filter(r=>r.group!==34);
      for(let i=1;i<valid.length;i++)if(valid[i].sample_index-valid[i-1].sample_index<20&&(affected.has(valid[i].id)||affected.has(valid[i-1].id)))throw Error("目标距另一 QRS 不足 100 ms");
    }
    if(doc.longest_id&&!final.some(r=>r.id===doc.longest_id))doc.longest_id=null;
    return {document:doc,affected:chosen.length};
  }
  const mean=a=>a.length?a.reduce((s,x)=>s+x,0)/a.length:null;
  const deviation=a=>a.length>1?Math.sqrt(a.reduce((s,x)=>s+(x-mean(a))**2,0)/(a.length-1)):null;
  const round=(v,d=2)=>v===null||!Number.isFinite(v)?null:Math.round((v+Number.EPSILON)*10**d)/10**d;
  const median=a=>{const s=a.slice().sort((a,b)=>a-b),i=Math.floor(s.length/2);return s.length%2?s[i]:(s[i-1]+s[i])/2};
  function hrv(feed,duration){
    const nn=[],opts=feed.document.settings;
    for(let i=1;i<feed.beats.length;i++){const a=feed.beats[i-1],b=feed.beats[i];if(a.class_code==="N"&&b.class_code==="N"&&b.rr_ms>=opts.nn_min&&b.rr_ms<=opts.nn_max)nn.push([i,b.sample_index,b.rr_ms])}
    if(nn.length<3)return {nn_count:nn.length,method:"修订版严格相邻 N-N；样本不足"};
    const values=nn.map(r=>r[2]),diffs=[],blocks={},hist={};
    for(let i=1;i<nn.length;i++)if(nn[i][0]===nn[i-1][0]+1)diffs.push(nn[i][2]-nn[i-1][2]);
    nn.forEach(([,sample,value])=>{const k=Math.floor(sample/60000);if((k+1)*300<=duration)(blocks[k]||(blocks[k]=[])).push(value);const bin=Math.floor(value/7.8125);hist[bin]=(hist[bin]||0)+1});
    const groups=Object.values(blocks).filter(x=>x.length>=30);
    return {nn_count:nn.length,successive_nn_pairs:diffs.length,mean_nn_ms:round(mean(values)),sdnn_ms:round(deviation(values)),sdann_ms:round(deviation(groups.map(mean))),sdnn_index_ms:round(mean(groups.map(deviation))),rmssd_ms:round(diffs.length?Math.sqrt(mean(diffs.map(x=>x*x))):null),pnn50_pct:round(diffs.length?100*diffs.filter(x=>Math.abs(x)>50).length/diffs.length:null),triangular_index:round(values.length/Math.max(...Object.values(hist))),completed_five_minute_blocks:groups.length,method:"修订版：连续 N-N，差分不跨异位/伪差；完整5分钟块且至少30个NN；7.8125ms箱宽。短记录仅供研究。"};
  }
  function metrics(feed,duration){
    const valid=feed.beats.filter(r=>r.group!==34),rr=valid.map(r=>r.rr_ms).filter(x=>x>=250&&x<=5000),longest=valid.reduce((a,b)=>!a||b.rr_ms>a.rr_ms?b:a,null),groups={};
    feed.beats.forEach(r=>groups[r.group]=(groups[r.group]||0)+1);
    return {record_count:feed.beats.length,valid_beats:valid.length,first_beat_time_s:valid[0]?.time_s??null,group_counts:groups,avg_hr_from_duration:round(valid.length*60/Math.max(1,duration)),avg_hr_from_rr:rr.length?round(60000/mean(rr)):null,longest_rr_ms:longest?.rr_ms??null,longest_rr_time_s:longest?.time_s??null,min_rr_ms:rr.length?rr.reduce((a,b)=>Math.min(a,b)):null,format_verified:true};
  }
  function detect(values,start,existing,options){
    const opts=settings(options),n=values.length;if(n<40||values.some(x=>!Number.isFinite(x)))return [];
    const energy=values.map((x,i)=>i?(x-values[i-1])**2:0),smoothed=[];let sum=0;
    energy.forEach((x,i)=>{sum+=x;if(i>=16)sum-=energy[i-16];smoothed.push(sum/Math.min(i+1,16))});
    const mid=median(smoothed),mad=median(smoothed.map(x=>Math.abs(x-mid))),threshold=mid+opts.sensitivity*Math.max(mad,mid*.15,1e-6),candidates=[];
    for(let i=20;i<n-20;i++)if(smoothed[i]>threshold&&smoothed[i]>=smoothed[i-1]&&smoothed[i]>smoothed[i+1]){
      const lo=Math.max(0,i-20),hi=Math.min(n,i+5),base=median(values.slice(lo,hi));let peak=lo;
      for(let j=lo+1;j<hi;j++)if(Math.abs(values[j]-base)>Math.abs(values[peak]-base))peak=j;
      candidates.push([smoothed[i],peak]);
    }
    const gap=Math.round(opts.refractory_ms/5),selected=[];
    candidates.sort((a,b)=>b[0]-a[0]||b[1]-a[1]).forEach(([strength,peak])=>{if(existing.every(x=>Math.abs(start+peak-x)>=gap)&&selected.every(x=>Math.abs(peak-x[1])>=gap))selected.push([strength,peak])});
    return selected.sort((a,b)=>a[1]-b[1]).slice(0,500).map(([strength,peak])=>({sample_index:start+peak,time_s:(start+peak)/200,score:round(strength/Math.max(threshold,1e-6)),label:"QRS候选，未分类"}));
  }
  function events(feed,type="all",offset=0,limit=200){
    const items=[],summary={},opts=feed.document.settings;
    feed.beats.forEach(r=>{
      const kinds=[];
      if(r.group===34)kinds.push(["noise","伪差 / 待确认","low"]);
      else if(r.kind==="rhythm")kinds.push([["A","M"].includes(r.class_code)?"AF":"AFL","人工逐搏节律："+r.name,"medium"]);
      else if([2,3].includes(r.group))kinds.push([r.group===2?"S":"V",r.name+"（待复核）","medium"]);
      else if(r.class_code!=="N")kinds.push(["manual","人工分类："+r.name,"low"]);
      if(r.group!==34&&r.rr_ms){
        if(r.rr_ms>=opts.pause*1000)kinds.push(["pause","长 RR "+(r.rr_ms/1000).toFixed(3)+" s","high"]);
        if(r.hr>=opts.tachy)kinds.push(["tachy","快心率候选 "+r.hr+" bpm","medium"]);
        else if(r.hr<=opts.brady)kinds.push(["brady","慢心率候选 "+r.hr+" bpm","medium"]);
      }
      kinds.forEach(([kind,label,severity])=>{summary[kind]=(summary[kind]||0)+1;if(type==="all"||type===kind)items.push({...r,type:kind,label,severity,review_status:"待复核"})});
    });
    return {summary,total:items.length,offset,limit,items:items.slice(offset,offset+limit),analysis:"edited",definition:"独立逐搏分类及 RR 阈值候选；不是发作次数或自动疾病诊断"};
  }
  const engine={types,defaults,blank,settings,materialize,select,apply,hrv,metrics,detect,events};
  globalThis.ECGBeatEngine=engine;
  if(typeof module!=="undefined")module.exports=engine;
})();
