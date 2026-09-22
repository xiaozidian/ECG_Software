"use strict";
/* Deterministic complete-index counterpart of ecg_core/clinical_analysis.py. */
(() => {
  const categories=[['fastest','最快心率'],['slowest','最慢心率'],['S','房早事件'],['V','室早事件'],['pause','停搏事件'],['rate','心率异常'],['AF','房颤事件'],['ST','ST段事件'],['other','其他事件']];
  const patterns=[['all','全部'],['single','单发'],['couplet','成对'],['triplet','连续三发'],['run','连续多发'],['tachycardia','心动过速'],['bigeminy','二联律'],['nnp','三联律（NNP）'],['npp','三联律（NPP）'],['quadrigeminy','四联律']];
  const encode=value=>JSON.stringify(value).replace(/[\u007f-\uffff]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0'));
  function fingerprint(text){let n=2166136261;for(let i=0;i<text.length;i++)n=Math.imul(n^text.charCodeAt(i),16777619)>>>0;return n.toString(16).padStart(8,'0')}
  function buildIndex(feed,templates=[],annotations=[],review={}){
    const rows=feed.beats,markers=feed.markers||[],opts=feed.document.settings;
    const bv=fingerprint(rows.concat(markers).map(r=>`${r.id}:${r.sample_index}:${r.class_code}`).join('|')+'|'+encode(Object.keys(opts).sort().map(k=>[k,opts[k]])));
    const findings=annotations.filter(a=>['ST','AT','VT','AF','AFL','STRIP'].includes(a.details?.kind));
    const av=fingerprint(encode(findings.map(a=>[a.id,a.sample_index,a.details]))),basis=Object.fromEntries(categories.map(([key])=>[key,bv]));
    basis.pause=bv+'-rr-gt2500-v2';
    for(const [key,kind] of [['ST','ST'],['S','AT'],['V','VT'],['AF','AF'],['other','STRIP']])basis[key]=bv+'-'+fingerprint(encode(findings.filter(a=>a.details.kind===kind||(key==='AF'&&a.details.kind==='AFL')).map(a=>[a.id,a.sample_index,a.details])));
    const byTemplate=new Map();templates.forEach(t=>t.sample_indices.forEach(s=>{if(!byTemplate.has(s))byTemplate.set(s,[]);byTemplate.get(s).push({id:String(t.id),name:t.name})}));
    const events=[];
    function make(category,subtype,label,targets,segment=targets,pattern=false,identifier=null){
      if(!segment.length)return null;
      const first=segment[0],last=segment.at(-1),start=first.sample_index,end=last.sample_index,names=new Map();
      targets.forEach(r=>(byTemplate.get(r.sample_index)||[]).forEach(t=>names.set(t.id,t)));
      const item={event_id:identifier||`${category}:${subtype}:${first.id}:${last.id}`,category,subtype,label,sample_index:start,start_sample:start,end_sample:end,time_s:start/200,end_s:end/200,target_samples:targets.map(r=>r.sample_index),beat_count:targets.length,templates:[...names.values()],hr:first.hr??null,rr_ms:first.rr_ms??null,basis_version:basis[category]||bv,pattern_only:pattern,diagnosis_status:review.steps?.[category==='ST'?'stt':'edit']?.status==='done'?'confirmed':'pending'};events.push(item);return item;
    }
    for(const code of ['S','V']){
      const label=code==='S'?'房早':'室早';let i=0;
      while(i<rows.length){if(rows[i].class_code!==code){i++;continue}let j=i+1;while(j<rows.length&&rows[j].class_code===code)j++;const count=j-i,kind=count===1?'single':count===2?'couplet':count===3?'triplet':'run';make(code,kind,{single:'单发',couplet:'成对',triplet:'连续三发',run:'连续多发'}[kind]+label,rows.slice(i,j));i=j}
      for(const [kind,cycle] of [['bigeminy',['N',code]],['nnp',['N','N',code]],['npp',['N',code,code]],['quadrigeminy',['N','N','N',code]]]){
        const length=cycle.length;let i=0;
        while(i+2*length<=rows.length){let j=i;while(j+length<=rows.length&&cycle.every((c,k)=>rows[j+k].class_code===c))j+=length;if(j-i>=2*length){const segment=rows.slice(i,j);make(code,kind,label+Object.fromEntries(patterns)[kind],segment.filter(r=>r.class_code===code),segment,true);i=j}else i++}
      }
    }
    const valid=rows.filter(r=>r.class_code!=='X'&&r.rr_ms>0),nn=rows.filter((b,i)=>i&&rows[i-1].class_code==='N'&&b.class_code==='N'&&b.rr_ms>=opts.nn_min&&b.rr_ms<=opts.nn_max);
    // Stable IDs preserve previously selected extrema; adjacent real beats remain available.
    for(const [name,subset] of [['RR',valid],['NN',nn]]){
      const usable=subset.filter(r=>Number.isFinite(r.hr)&&r.hr>0&&Number.isFinite(r.rr_ms));
      for(const [key,direction] of [['fastest',1],['slowest',-1]]){
        const ranked=[...usable].sort((a,b)=>direction*(a.rr_ms-b.rr_ms)||a.sample_index-b.sample_index||(a.id<b.id?-1:a.id>b.id?1:0)).slice(0,200);
        ranked.forEach((r,i)=>{make(key,name,`${name} ${Object.fromEntries(categories)[key]} ${r.hr} bpm`,[r]).candidate_rank=i+1;});
      }
    }
    valid.forEach(r=>{if(Number.isFinite(r.rr_ms)&&r.rr_ms>2500)make('pause','pause',`长 RR ${(r.rr_ms/1000).toFixed(3)} s`,[r])});
    const definitions=[['rate','tachy','快心率',r=>r.class_code!=='X'&&(r.hr||0)>=opts.tachy],['rate','brady','慢心率',r=>r.class_code!=='X'&&(r.hr||0)>0&&r.hr<=opts.brady],['AF','AF','房颤',r=>['A','M'].includes(r.class_code)],['AF','AFL','房扑',r=>['C','H'].includes(r.class_code)]];
    for(const [cat,sub,label,predicate] of definitions){if(cat==='AF'&&annotations.some(a=>a.details?.rhythm_authoritative))continue;let i=0;while(i<rows.length){if(!predicate(rows[i])){i++;continue}let j=i+1;while(j<rows.length&&predicate(rows[j]))j++;make(cat,sub,label,rows.slice(i,j));i=j}}
    rows.concat(markers).forEach(r=>{if(!['N','S','V','A','M','C','H'].includes(r.class_code))make('other',r.class_code,r.name||r.class_code,[r])});
    findings.forEach(a=>{
      const d=a.details,rhythm=['AF','AFL'].includes(d.kind);if(d.status!=='confirmed'&&!rhythm||d.status==='excluded')return;
      if(rhythm&&d.status==='pending'&&findings.some(b=>b.details.kind===d.kind&&b.details.status==='confirmed'&&b.sample_index===a.sample_index&&b.details.end_sample===d.end_sample))return;
      const kind=d.kind,cat=rhythm?'AF':kind==='ST'?'ST':kind==='AT'?'S':kind==='STRIP'?'other':'V',start=a.sample_index,end=d.end_sample??start,whole=['ST','AF','AFL','STRIP'].includes(kind),targets=rows.filter(r=>r.sample_index>=start&&r.sample_index<=end&&(whole||r.class_code===cat));
      const item=make(cat,whole?kind:'tachycardia',d.finding||(kind==='AT'?'房速':'室速'),targets,[{id:`a:${a.id}:start`,sample_index:start},{id:`a:${a.id}:end`,sample_index:end}],!whole,`annotation:${a.id}`);if(d.status!=='confirmed')item.diagnosis_status='pending';item.lead=a.lead||'全部';item.note=a.note||'';
    });
    events.sort((a,b)=>a.start_sample-b.start_sample||(a.event_id<b.event_id?-1:1));
    return {events,rows:rows.concat(markers),templates,basis_versions:basis,data_version:bv+'-'+av,beat_version:bv,duration_s:feed.duration};
  }
  function queryIndex(index,params={},occurrences=false){
    if(params instanceof URLSearchParams)params=Object.fromEntries(params);
    const category=params.category||'all',mode=({'NPN':'nnp','NNP':'nnp','NPP':'npp','三联律(NPN)':'nnp','三联律(NNP)':'nnp','三联律(NPP)':'npp'}[params.mode]||params.mode||'all'),code=params.class_code||'S',templateId=String(params.template_id||'all'),offset=Math.max(0,Number(params.offset)||0),limit=Math.max(1,Math.min(200,Number(params.limit)||100));
    const template=index.templates.find(t=>String(t.id)===templateId);if(templateId!=='all'&&!template)throw Error('模板不存在，请刷新');const samples=template?new Set(template.sample_indices):null,fast=(params.fast_slow_mode||'rr').toUpperCase(),ids=params.ids?new Set(params.ids.split('|')):null;
    let items;
    if(occurrences&&mode==='all')items=index.rows.filter(r=>(code==='all'||r.class_code===code)&&(!samples||samples.has(r.sample_index))).map(r=>({event_id:'beat:'+r.id,category:code,subtype:'beat',label:r.name||r.class_code,sample_index:r.sample_index,start_sample:r.sample_index,end_sample:r.sample_index,time_s:r.sample_index/200,end_s:r.sample_index/200,target_samples:[r.sample_index],beat_count:1,hr:r.hr??null,rr_ms:r.rr_ms??null,basis_version:index.beat_version,templates:template?[{id:String(template.id),name:template.name}]:[],diagnosis_status:r.source_sample!==r.sample_index||r.class_code!==({1:'N',2:'S',3:'V',34:'X'}[r.source_group]||'OTHER')?'edited':'pending'}));
    else {items=index.events.filter(e=>ids?ids.has(e.event_id):(occurrences?e.category===(['A','M','C','H'].includes(code)?'AF':code):category==='all'||e.category===category)&&(mode!=='all'?e.subtype===mode:!e.pattern_only)&&(!['fastest','slowest'].includes(e.category)||fast==='BOTH'||e.subtype===fast));if(samples)items=items.filter(e=>e.target_samples.some(s=>samples.has(s)))}
    const pause_band=params.pause_band||'all';
    if(!['all','over3','2.5to3'].includes(pause_band))throw Error('无效的长 RR 筛选范围');
    const pauses=index.events.filter(e=>e.category==='pause'),pause_counts={all:pauses.length,over3:pauses.filter(e=>e.rr_ms>3000).length,'2.5to3':pauses.filter(e=>e.rr_ms<=3000).length};
    if(!occurrences&&category==='pause'&&!ids&&pause_band!=='all')items=items.filter(e=>pause_band==='over3'?e.rr_ms>3000:e.rr_ms<=3000);
    const rateCandidates=!occurrences&&['fastest','slowest'].includes(category)&&!ids,sortOrder=rateCandidates?(params.sort||'hr_desc'):'time';
    if(!['hr_desc','hr_asc','time'].includes(sortOrder))throw Error('无效的候选排序方式');
    items.sort((a,b)=>(sortOrder==='time'?0:(sortOrder==='hr_desc'?1:-1)*(a.rr_ms-b.rr_ms))||a.start_sample-b.start_sample||(a.event_id<b.event_id?-1:1));
    const counts=Object.fromEntries(categories.map(([key])=>[key,index.events.filter(e=>!e.pattern_only&&e.category===key&&(!['fastest','slowest'].includes(key)||fast==='BOTH'||e.subtype===fast)).length])),subtypes={},beats={};
    index.events.forEach(e=>{if(e.category===(occurrences?(['A','M','C','H'].includes(code)?'AF':code):category)&&(!samples||e.target_samples.some(s=>samples.has(s))))subtypes[e.subtype]=(subtypes[e.subtype]||0)+1});index.rows.forEach(r=>beats[r.class_code]=(beats[r.class_code]||0)+1);
    const time_counts={};items.forEach(e=>{const h=Math.floor(e.time_s/3600);time_counts[h]=(time_counts[h]||0)+1});
    const confirmed_category_counts={},confirmed_beat_counts={};for(const [key] of categories){const rows=index.events.filter(e=>e.category===key&&!e.pattern_only&&e.diagnosis_status==='confirmed'&&(!['fastest','slowest'].includes(key)||fast==='BOTH'||e.subtype===fast));confirmed_category_counts[key]=rows.length;confirmed_beat_counts[key]=new Set(rows.flatMap(e=>e.target_samples)).size}
    return {pause_counts,pause_band,sort_order:sortOrder,candidate_limit:rateCandidates?200:null,confirmed_category_counts,confirmed_beat_counts,time_counts,items:items.slice(offset,offset+limit),total:items.length,offset,limit,category_counts:counts,subtype_counts:subtypes,beat_counts:beats,basis_versions:index.basis_versions,data_version:index.data_version};
  }
  const mean=a=>a.length?a.reduce((a,b)=>a+b,0)/a.length:null,sd=a=>a.length>1?Math.sqrt(a.reduce((s,x)=>s+(x-mean(a))**2,0)/(a.length-1)):null,round=x=>x===null?null:Math.round((x+Number.EPSILON)*100)/100;
  function hrvWindows(feed,startTime,window=0){
    const opts=feed.document.settings,rows=feed.beats,duration=feed.duration,parsed=Date.parse(String(startTime).replace(' ','T').slice(0,19)+'Z'),clock=Number.isFinite(parsed)?parsed:null;
    window=Math.max(0,Math.min(Number(window)||0,Math.max(0,Math.ceil(duration/86400)-1)));const lo=window*86400,hi=Math.min(duration,lo+86400),nn=[];
    for(let i=0;i<rows.length-1;i++){const a=rows[i],b=rows[i+1];if(a.class_code==='N'&&b.class_code==='N'&&b.rr_ms>=opts.nn_min&&b.rr_ms<=opts.nn_max)nn.push([i,a.sample_index/200,b.sample_index/200,b.rr_ms])}
    function period(label,intervals){const merged=[];for(const [a,b] of intervals){if(merged.length&&Math.abs(merged.at(-1)[1]-a)<1e-6)merged.at(-1)[1]=b;else merged.push([a,b])}intervals=merged;const chosen=nn.filter(x=>intervals.some(([a,b])=>x[1]>=a&&x[2]<=b)),values=chosen.map(x=>x[3]),diffs=[];for(let i=1;i<chosen.length;i++){const a=chosen[i-1],b=chosen[i];if(b[0]===a[0]+1&&intervals.some(([s,e])=>a[1]>=s&&b[2]<=e))diffs.push(b[3]-a[3])}return {label,nn_count:values.length,coverage_s:Math.round(intervals.reduce((s,[a,b])=>s+b-a,0)*1000)/1000,valid_nn_s:Math.round(values.reduce((a,b)=>a+b,0))/1000,mean_nn_ms:round(mean(values)),sdnn_ms:values.length>=3?round(sd(values)):null,rmssd_ms:diffs.length?round(Math.sqrt(mean(diffs.map(x=>x*x)))):null,pnn50_pct:diffs.length?round(100*diffs.filter(x=>Math.abs(x)>50).length/diffs.length):null}}
    const day=[],night=[],hourly=[];let t=lo;
    while(t<hi){const dt=clock!==null?new Date(clock+t*1000):null,length=Math.min(hi-t,3600-(dt?dt.getUTCMinutes()*60+dt.getUTCSeconds()+dt.getUTCMilliseconds()/1000:t%3600)),end=t+length;if(dt)(dt.getUTCHours()>=6&&dt.getUTCHours()<22?day:night).push([t,end]);hourly.push({...period(dt?dt.toISOString().slice(5,16).replace('T',' '):`+${t/3600}h`,[[t,end]]),start_s:t,end_s:end,partial:length<3600});t=end}
    return {window_index:window,window_count:Math.max(1,Math.ceil(duration/86400)),start_s:lo,end_s:hi,actual_duration_s:hi-lo,clock_available:clock!==null,periods:{full:period(hi-lo===86400?'24小时窗口':'当前记录（不足24小时）',[[lo,hi]]),day:period('日间 06:00–22:00（清醒代理）',day),night:period('夜间 22:00–06:00',night)},hourly,method:'修订后连续 N-N；窗口内直接计算；缺失时段留空；日间是清醒时段代理'};
  }
  function validateReport(index,composition,review,approving=false){
    if('include_hrv' in composition&&typeof composition.include_hrv!=='boolean')throw Error('HRV 入报选项须为布尔值');
    for(const entry of composition.selected_events||[]){if('range_start_s' in entry||'range_end_s' in entry){const event=index.events.find(e=>e.event_id===entry.event_id);if(event&&event.basis_version===entry.basis_version)ECGReportEngine.resolve(index,event,entry)}}
    const lookup=new Map(index.events.map(e=>[e.event_id,e])),selected=[];
    for(const entry of composition.selected_events||[]){const e=lookup.get(entry.event_id);if(!e||e.basis_version!==entry.basis_version){if(approving)throw Error('已选图条因诊断修订失效，请重新筛选');continue}if(approving&&['fastest','slowest'].includes(e.category)&&!['BOTH',e.subtype].includes((composition.fast_slow_mode||'rr').toUpperCase()))throw Error('极值图条与 RR/NN 选择不一致');if(approving&&e.diagnosis_status!=='confirmed')throw Error('请先完成编辑／ST-T诊断确认');selected.push({...e,caption:entry.caption||e.label,...(globalThis.ECGReportEngine?ECGReportEngine.settings(entry):{})})}
    if(approving){const counts=queryIndex(index,{fast_slow_mode:composition.fast_slow_mode||'rr'}).category_counts,missing=categories.filter(([k])=>counts[k]&&composition.category_reviews?.[k]!==index.basis_versions[k]);if(missing.length)throw Error('请完成报告分类筛选：'+missing.map(x=>x[1]).join('、'));if((composition.diagnosis_blocks||[]).some(b=>b.needs_review))throw Error('请核对保留的人工诊断文字')}
    return selected;
  }
  const api={categories,patterns,buildIndex,queryIndex,hrvWindows,validateReport,fingerprint};globalThis.ECGClinicalAnalysis=api;if(typeof module!=='undefined')module.exports=api;
})();
