"use strict";
/* Deterministic complete-index counterpart of ecg_core/clinical_analysis.py. */
(() => {
  const quality=globalThis.ECGRRQuality||(typeof require==='function'?require('./rr-quality.js'):null);
  const categories=[['fastest','最快心率'],['slowest','最慢心率'],['S','房早事件'],['V','室早事件'],['pause','停搏事件'],['rate','心率异常'],['AF','房颤事件'],['ST','ST段事件'],['other','其他事件']];
  const patterns=[['all','全部'],['single','单发'],['couplet','成对'],['triplet','连续三发'],['run','连续多发'],['tachycardia','心动过速'],['bigeminy','二联律'],['nnp','三联律（NNP）'],['npp','三联律（NPP）'],['quadrigeminy','四联律']];
  const periodicVersion='periodic-v2';
  // Two complete cycles in any phase, then the matching tail. Never bridge
  // another beat type or emit overlapping spans within the same pattern.
  function* repeatingSpans(codes,cycle){
    const length=cycle.length,rotations=new Set(cycle.map((_,k)=>cycle.slice(k).concat(cycle.slice(0,k)).join('|')));
    if(!length)throw new Error('A repeating cycle must not be empty');
    let i=0;
    while(i+2*length<=codes.length){
      const unit=codes.slice(i,i+length);
      if(rotations.has(unit.join('|'))&&unit.every((c,k)=>codes[i+length+k]===c)){
        let end=i+2*length;
        while(end<codes.length&&codes[end]===codes[end-length])end++;
        yield [i,end];i=end;
      }else i++;
    }
  }
  const encode=value=>JSON.stringify(value).replace(/[\u007f-\uffff]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0'));
  function fingerprint(text){let n=2166136261;for(let i=0;i<text.length;i++)n=Math.imul(n^text.charCodeAt(i),16777619)>>>0;return n.toString(16).padStart(8,'0')}
  function buildIndex(feed,templates=[],annotations=[],review={}){
    const rows=feed.beats,markers=feed.markers||[],opts=feed.document.settings;
    const bv=fingerprint(rows.concat(markers).map(r=>`${r.id}:${r.sample_index}:${r.class_code}`).join('|')+'|'+encode(Object.keys(opts).sort().map(k=>[k,opts[k]])));
    const findings=annotations.filter(a=>['ST','AT','VT','AF','AFL','STRIP'].includes(a.details?.kind));
    const av=fingerprint(encode(findings.map(a=>[a.id,a.sample_index,a.details]))),basis=Object.fromEntries(categories.map(([key])=>[key,bv]));
    const excluded=[...(feed.excluded_rhythm_intervals||[]),...quality.annotationExclusions(annotations)];
    for(const key of ['fastest','slowest'])basis[key]=bv+'-rr-quality-v3-nn-'+fingerprint(encode(excluded));
    basis.pause=bv+'-rr-gt2500-v4-r-peaks';basis.rate=bv+'-rr-quality-v3';
    for(const [key,kind] of [['ST','ST'],['S','AT'],['V','VT'],['AF','AF'],['other','STRIP']])basis[key]=bv+'-'+fingerprint(encode(findings.filter(a=>a.details.kind===kind||(key==='AF'&&a.details.kind==='AFL')).map(a=>[a.id,a.sample_index,a.details])));
    basis.AF+='-episode-status-v2-inclusive-end-v1';
    for(const key of ['S','V'])basis[key]+='-'+periodicVersion;
    const byTemplate=new Map();templates.forEach(t=>t.sample_indices.forEach(s=>{if(!byTemplate.has(s))byTemplate.set(s,[]);byTemplate.get(s).push({id:String(t.id),name:t.name})}));
    const events=[];
    function make(category,subtype,label,targets,segment=targets,pattern=false,identifier=null){
      if(!segment.length)return null;
      const first=segment[0],last=segment.at(-1),start=first.sample_index,end=last.sample_index,names=new Map();
      targets.forEach(r=>(byTemplate.get(r.sample_index)||[]).forEach(t=>names.set(t.id,t)));
      const item={event_id:identifier||`${category}:${subtype}:${first.id}:${last.id}`,category,subtype,label,sample_index:start,start_sample:start,end_sample:end,time_s:start/200,end_s:end/200,target_samples:targets.map(r=>r.sample_index),beat_count:targets.length,templates:[...names.values()],hr:first.hr??null,rr_ms:first.rr_ms??null,basis_version:basis[category]||bv,pattern_only:pattern,diagnosis_status:review.steps?.[category==='ST'?'stt':'edit']?.status==='done'?'confirmed':'pending'};events.push(item);return item;
    }
    const codes=rows.map(r=>r.class_code);
    for(const code of ['S','V']){
      const label=code==='S'?'房早':'室早';let i=0;
      while(i<rows.length){if(rows[i].class_code!==code){i++;continue}let j=i+1;while(j<rows.length&&rows[j].class_code===code)j++;const count=j-i,kind=count===1?'single':count===2?'couplet':count===3?'triplet':'run';make(code,kind,{single:'单发',couplet:'成对',triplet:'连续三发',run:'连续多发'}[kind]+label,rows.slice(i,j));i=j}
      for(const [kind,cycle] of [['bigeminy',['N',code]],['nnp',['N','N',code]],['npp',['N',code,code]],['quadrigeminy',['N','N','N',code]]]){
        for(const [i,j] of repeatingSpans(codes,cycle)){
          const segment=rows.slice(i,j);
          make(code,kind,label+Object.fromEntries(patterns)[kind],segment.filter(r=>r.class_code===code),segment,true);
        }
      }
    }
    const report=globalThis.ECGReportEngine||(typeof require==='function'?require('./report-engine.js'):null);
    const nnValid=quality.intervalMask(rows,excluded),pairs=report.intervalPairs(rows,feed.duration),valid=pairs.map(([,r])=>r),rateRows=new Set(valid.filter(quality.consistentRate)),nn=rows.filter((b,i)=>nnValid[i]&&rows[i-1].class_code==='N'&&b.class_code==='N'&&b.rr_ms>=opts.nn_min&&b.rr_ms<=opts.nn_max);
    // Stable IDs preserve previously selected extrema; adjacent real beats remain available.
    for(const [name,subset] of [['RR',valid],['NN',nn]]){
      const usable=subset.filter(r=>rateRows.has(r));
      for(const [key,direction] of [['fastest',1],['slowest',-1]]){
        const ranked=[...usable].sort((a,b)=>direction*(a.rr_ms-b.rr_ms)||a.sample_index-b.sample_index||(a.id<b.id?-1:a.id>b.id?1:0)).slice(0,200);
        ranked.forEach((r,i)=>{make(key,name,`${name} ${Object.fromEntries(categories)[key]} ${r.hr} bpm`,[r]).candidate_rank=i+1;});
      }
    }
    pairs.forEach(([previous,r])=>{if(r.rr_ms>2500)Object.assign(make('pause','pause',`长 RR ${(r.rr_ms/1000).toFixed(3)} s`,[r]),{rr_start_sample:previous.sample_index,rr_end_sample:r.sample_index})});
    const definitions=[['rate','tachy','快心率',r=>rateRows.has(r)&&r.hr>=opts.tachy],['rate','brady','慢心率',r=>rateRows.has(r)&&r.hr<=opts.brady],['AF','AF','房颤',r=>['A','M'].includes(r.class_code)],['AF','AFL','房扑',r=>['C','H'].includes(r.class_code)]];
    for(const [cat,sub,label,predicate] of definitions){if(cat==='AF'&&annotations.some(a=>a.details?.rhythm_authoritative))continue;let i=0;while(i<rows.length){if(!predicate(rows[i])){i++;continue}let j=i+1;while(j<rows.length&&predicate(rows[j]))j++;const item=make(cat,sub,label,rows.slice(i,j));if(cat==='AF'){item.end_s=j<rows.length?rows[j].sample_index/200:feed.duration;item.rhythm_status='pending';item.diagnosis_status='pending';}i=j}}
    rows.concat(markers).forEach(r=>{if(!['N','S','V','A','M','C','H'].includes(r.class_code))make('other',r.class_code,r.name||r.class_code,[r])});
    findings.forEach(a=>{
      const d=a.details,rhythm=['AF','AFL'].includes(d.kind);if(d.status!=='confirmed'&&!rhythm||d.status==='excluded')return;
      if(!annotations.some(x=>x.details?.rhythm_authoritative)&&rhythm&&d.status==='pending'&&findings.some(b=>b.details.kind===d.kind&&b.details.status==='confirmed'&&b.sample_index===a.sample_index&&b.details.end_sample===d.end_sample))return;
      const kind=d.kind,cat=rhythm?'AF':kind==='ST'?'ST':kind==='AT'?'S':kind==='STRIP'?'other':'V',start=a.sample_index,end=d.end_sample??start,whole=['ST','AF','AFL','STRIP'].includes(kind),targets=rows.filter(r=>r.sample_index>=start&&r.sample_index<=end&&(whole||r.class_code===cat));
      const defaultLabel={ST:'ST 改变',AF:'房颤',AFL:'房扑',AT:'房速',VT:'室速',STRIP:'人工图条'}[kind];
      const item=make(cat,whole?kind:'tachycardia',d.finding||defaultLabel,targets,[{id:`a:${a.id}:start`,sample_index:start},{id:`a:${a.id}:end`,sample_index:end}],!whole,`annotation:${a.id}`);if(d.status!=='confirmed')item.diagnosis_status='pending';item.lead=a.lead||'全部';item.note=a.note||'';
      if(cat==='AF'){item.end_s=(end+1)/200;item.rhythm_status=d.status||'pending';} // Keep episode review separate from workflow approval.
    });
    events.filter(e=>e.category==='AF').forEach(e=>{const annotation=e.event_id.startsWith('annotation:')?e.event_id.slice(11):null;e.rhythm_episode_id=annotation===null?'beat-'+e.start_sample:annotation.startsWith('af:')?annotation.slice(3):'source-'+annotation;});
    events.sort((a,b)=>a.start_sample-b.start_sample||(a.event_id<b.event_id?-1:1));
    return {events,rows:rows.concat(markers),templates,basis_versions:basis,data_version:bv+'-'+av+'-rr-quality-v3-'+periodicVersion+'-af-end-v1-status-v2',beat_version:bv,duration_s:feed.duration};
  }
  function queryIndex(index,params={},occurrences=false){
    if(params instanceof URLSearchParams)params=Object.fromEntries(params);
    const category=params.category||'all',mode=({'NPN':'nnp','NNP':'nnp','NPP':'npp','三联律(NPN)':'nnp','三联律(NNP)':'nnp','三联律(NPP)':'npp'}[params.mode]||params.mode||'all'),code=params.class_code||'S',templateId=String(params.template_id||'all'),offset=Math.max(0,Number(params.offset)||0),limit=Math.max(1,Math.min(200,Number(params.limit)||100));
    const template=index.templates.find(t=>String(t.id)===templateId);if(templateId!=='all'&&!template)throw Error('模板不存在，请刷新');const samples=template?new Set(template.sample_indices):null,fast=(params.fast_slow_mode||'rr').toUpperCase(),ids=params.ids?new Set(params.ids.split('|')):null;
    const rawOccurrences=occurrences&&mode==='all',timeOf=rawOccurrences?r=>r.sample_index/200:e=>e.time_s;
    let items;
    // Hold row references until pagination; do not construct 100k display cards.
    if(rawOccurrences)items=index.rows.filter(r=>(code==='all'||r.class_code===code)&&(!samples||samples.has(r.sample_index)));
    else {items=index.events.filter(e=>ids?ids.has(e.event_id):(occurrences?e.category===(['A','M','C','H'].includes(code)?'AF':code):category==='all'||e.category===category)&&(mode!=='all'?e.subtype===mode:!e.pattern_only)&&(!['fastest','slowest'].includes(e.category)||fast==='BOTH'||e.subtype===fast));if(samples)items=items.filter(e=>e.target_samples.some(s=>samples.has(s)))}
    const pause_band=params.pause_band||'all';
    if(!['all','over3','2.5to3'].includes(pause_band))throw Error('无效的长 RR 筛选范围');
    const pauses=index.events.filter(e=>e.category==='pause'),pause_counts={all:pauses.length,over3:pauses.filter(e=>e.rr_ms>3000).length,'2.5to3':pauses.filter(e=>e.rr_ms<=3000).length};
    if(!occurrences&&category==='pause'&&!ids&&pause_band!=='all')items=items.filter(e=>pause_band==='over3'?e.rr_ms>3000:e.rr_ms<=3000);
    const rateCandidates=!occurrences&&['fastest','slowest'].includes(category)&&!ids,sortOrder=rateCandidates?(params.sort||'hr_desc'):'time';
    const rawSpacing=params.candidate_spacing_s===undefined?0:params.candidate_spacing_s;
    if(![0,7,30,60,'0','7','30','60'].includes(rawSpacing))throw Error('候选定位点间隔须为 0、7、30 或 60 秒');
    const candidate_spacing_s=rateCandidates?Number(rawSpacing):0;
    if(!['hr_desc','hr_asc','time'].includes(sortOrder))throw Error('无效的候选排序方式');
    if(rawOccurrences)items.sort((a,b)=>a.sample_index-b.sample_index||(a.id<b.id?-1:a.id>b.id?1:0));
    else items.sort((a,b)=>(sortOrder==='time'?0:(sortOrder==='hr_desc'?1:-1)*(a.rr_ms-b.rr_ms))||a.start_sample-b.start_sample||(a.event_id<b.event_id?-1:1));
    const counts=Object.fromEntries(categories.map(([key])=>[key,index.events.filter(e=>!e.pattern_only&&e.category===key&&(!['fastest','slowest'].includes(key)||fast==='BOTH'||e.subtype===fast)).length])),subtypes={},beats={};
    index.events.forEach(e=>{if(e.category===(occurrences?(['A','M','C','H'].includes(code)?'AF':code):category)&&(!samples||e.target_samples.some(s=>samples.has(s))))subtypes[e.subtype]=(subtypes[e.subtype]||0)+1});index.rows.forEach(r=>beats[r.class_code]=(beats[r.class_code]||0)+1);
    const time_counts={};items.forEach(e=>{const h=Math.floor(timeOf(e)/3600);time_counts[h]=(time_counts[h]||0)+1});
    const clock=Date.parse(String(index.start_time).replace(' ','T').slice(0,19)+'Z'),time_bins=[];
    for(let start=0;start<index.duration_s;){const dt=Number.isFinite(clock)?new Date(clock+start*1000):null,seconds=dt?dt.getUTCMinutes()*60+dt.getUTCSeconds()+dt.getUTCMilliseconds()/1000:start%3600,end=Math.min(index.duration_s,start+3600-seconds);time_bins.push({start_s:start,end_s:end,label:dt?dt.toISOString().slice(5,16).replace('T',' '):`+${Math.floor(start/3600)}h`,count:0});start=end;}
    const dt=Number.isFinite(clock)?new Date(clock):null,origin=dt?dt.getUTCMinutes()*60+dt.getUTCSeconds()+dt.getUTCMilliseconds()/1000:0;
    items.forEach(e=>{const bin=time_bins[Math.floor((origin+timeOf(e))/3600)];if(bin)bin.count++});
    let time_filter=null;const unfiltered_total=items.length;
    if('time_start' in params||'time_end' in params){const a=Number(params.time_start),b=Number(params.time_end);if(!Number.isFinite(a)||!Number.isFinite(b)||params.time_start===''||params.time_end===''||!(0<=a&&a<b&&b<=index.duration_s))throw Error('时间筛选超出记录范围');time_filter=[a,b];items=items.filter(e=>a<=timeOf(e)&&timeOf(e)<b);}
    const candidate_unspaced_total=items.length;
    if(candidate_spacing_s){
      const kept=[];
      for(const e of [...items].sort((a,b)=>a.candidate_rank-b.candidate_rank||a.start_sample-b.start_sample||(a.event_id<b.event_id?-1:1))){
        if(kept.every(other=>e.subtype!==other.subtype||Math.abs(e.start_sample-other.start_sample)>=candidate_spacing_s*200))kept.push(e);
      }
      const ids=new Set(kept.map(e=>e.event_id));items=items.filter(e=>ids.has(e.event_id));
    }
    const candidate_hidden_count=candidate_unspaced_total-items.length;
    const confirmed_category_counts={},confirmed_beat_counts={};for(const [key] of categories){const rows=index.events.filter(e=>e.category===key&&!e.pattern_only&&e.diagnosis_status==='confirmed'&&(!['fastest','slowest'].includes(key)||fast==='BOTH'||e.subtype===fast));confirmed_category_counts[key]=rows.length;confirmed_beat_counts[key]=new Set(rows.flatMap(e=>e.target_samples)).size}
    let pageOffset=offset;const focus={};
    if(Object.prototype.hasOwnProperty.call(params,'near_sample')){
      const raw=params.near_sample,sample=Number(raw);
      if(!occurrences||!['number','string'].includes(typeof raw)||!/^\d+$/.test(String(raw))||!Number.isSafeInteger(sample)||sample<0)throw Error('附近定位仅支持心搏记录的非负整数采样位置');
      const position=e=>rawOccurrences?e.sample_index:e.start_sample;
      let lo=0,hi=items.length;
      while(lo<hi){const mid=Math.floor((lo+hi)/2);if(position(items[mid])<sample)lo=mid+1;else hi=mid;}
      const target=items.length?Math.min(lo,items.length-1):null;
      pageOffset=target===null?0:Math.floor(target/limit)*limit;
      Object.assign(focus,{resume_index:target,resume_sample:target===null?null:position(items[target]),resume_exact:target!==null&&position(items[target])===sample});
    }
    if(params.locate_event){
      if(occurrences||ids)throw Error('精确定位仅支持报告候选列表');
      const target=items.findIndex(e=>e.event_id===params.locate_event);
      if(target<0)throw Error('目标事件已失效或不在当前筛选内，请重新选择；未跳转到其他事件');
      if(params.locate_basis!==items[target].basis_version)throw Error('目标事件依据已变化，请重新选择');
      pageOffset=Math.floor(target/limit)*limit;focus.focus_index=target;
    }
    let page=items.slice(pageOffset,pageOffset+limit);
    if(rawOccurrences)page=page.map(r=>({event_id:'beat:'+r.id,category:code,subtype:'beat',label:r.name||r.class_code,sample_index:r.sample_index,start_sample:r.sample_index,end_sample:r.sample_index,time_s:r.sample_index/200,end_s:r.sample_index/200,target_samples:[r.sample_index],beat_count:1,hr:r.hr??null,rr_ms:r.rr_ms??null,basis_version:index.beat_version,templates:template?[{id:String(template.id),name:template.name}]:[],diagnosis_status:r.source_sample!==r.sample_index||r.class_code!==({1:'N',2:'S',3:'V',34:'X'}[r.source_group]||'OTHER')?'edited':'pending'}));
    return {...focus,candidate_spacing_s,candidate_unspaced_total,candidate_hidden_count,time_bins,time_filter,unfiltered_total,pause_counts,pause_band,sort_order:sortOrder,candidate_limit:rateCandidates?200:null,confirmed_category_counts,confirmed_beat_counts,time_counts,items:page,total:items.length,offset:pageOffset,limit,category_counts:counts,subtype_counts:subtypes,beat_counts:beats,basis_versions:index.basis_versions,data_version:index.data_version};
  }
  const mean=a=>a.length?a.reduce((a,b)=>a+b,0)/a.length:null,sd=a=>{if(a.length<2)return null;const m=mean(a);return Math.sqrt(a.reduce((s,x)=>s+(x-m)**2,0)/(a.length-1))},round=x=>x===null?null:Math.round((x+Number.EPSILON)*100)/100;
  function hrvWindows(feed,startTime,window=0){
    const opts=feed.document.settings,rows=feed.beats,duration=feed.duration,parsed=Date.parse(String(startTime).replace(' ','T').slice(0,19)+'Z'),clock=Number.isFinite(parsed)?parsed:null;
    window=Math.max(0,Math.min(Math.trunc(Number(window)||0),Math.max(0,Math.ceil(duration/86400)-1)));const lo=window*86400,hi=Math.min(duration,lo+86400),nn=quality.nnIntervals(feed);
    function period(label,intervals){const merged=[];for(const [a,b] of intervals){if(merged.length&&Math.abs(merged.at(-1)[1]-a)<1e-6)merged.at(-1)[1]=b;else merged.push([a,b])}intervals=merged;const chosen=nn.filter(x=>intervals.some(([a,b])=>x[1]>=a&&x[2]<=b)),values=chosen.map(x=>x[3]),diffs=[];for(let i=1;i<chosen.length;i++){const a=chosen[i-1],b=chosen[i];if(b[0]===a[0]+1&&intervals.some(([s,e])=>a[1]>=s&&b[2]<=e))diffs.push(b[3]-a[3])}return {label,nn_count:values.length,coverage_s:Math.round(intervals.reduce((s,[a,b])=>s+b-a,0)*1000)/1000,valid_nn_s:Math.round(values.reduce((a,b)=>a+b,0))/1000,mean_nn_ms:round(mean(values)),sdnn_ms:values.length>=3?round(sd(values)):null,rmssd_ms:diffs.length?round(Math.sqrt(mean(diffs.map(x=>x*x)))):null,pnn50_pct:diffs.length?round(100*diffs.filter(x=>Math.abs(x)>50).length/diffs.length):null}}
    const day=[],night=[],hourly=[];let t=lo;
    while(t<hi){const dt=clock!==null?new Date(clock+t*1000):null,length=Math.min(hi-t,3600-(dt?dt.getUTCMinutes()*60+dt.getUTCSeconds()+dt.getUTCMilliseconds()/1000:t%3600)),end=t+length;if(dt)(dt.getUTCHours()>=6&&dt.getUTCHours()<22?day:night).push([t,end]);hourly.push({...period(dt?dt.toISOString().slice(5,16).replace('T',' '):`+${t/3600}h`,[[t,end]]),start_s:t,end_s:end,partial:length<3600});t=end}
    return {window_index:window,window_count:Math.max(1,Math.ceil(duration/86400)),start_s:lo,end_s:hi,actual_duration_s:hi-lo,clock_available:clock!==null,periods:{full:period(hi-lo===86400?'24小时窗口':'当前记录（不足24小时）',[[lo,hi]]),day:period('日间 06:00–22:00（清醒代理）',day),night:period('夜间 22:00–06:00',night)},hourly,method:'修订后连续 N-N；窗口内直接计算；缺失时段留空；日间是清醒时段代理'};
  }
  function validateReport(index,composition,review,approving=false){
    if('include_hrv' in composition&&typeof composition.include_hrv!=='boolean')throw Error('HRV 入报选项须为布尔值');
    for(const entry of composition.selected_events||[]){if('range_start_s' in entry||'range_end_s' in entry){const event=index.events.find(e=>e.event_id===entry.event_id);if(event&&event.basis_version===entry.basis_version)ECGReportEngine.resolve(index,event,entry)}}
    const lookup=new Map(index.events.map(e=>[e.event_id,e])),selected=[];
    for(const entry of composition.selected_events||[]){const e=lookup.get(entry.event_id);if(!e||e.basis_version!==entry.basis_version){if(approving)throw Error('已选图条因诊断修订失效，请重新筛选');continue}if(approving&&e.category==='AF'&&e.rhythm_status!=='confirmed')throw Error('所选房颤／房扑片段尚未确认；请在房颤／房扑页完成片段诊断确认，或从报告中移除该图条。');if(approving&&e.diagnosis_status!=='confirmed')throw Error('请先完成编辑／ST-T诊断确认');selected.push({...e,caption:entry.caption||e.label,...(globalThis.ECGReportEngine?ECGReportEngine.settings(entry):{})})}
    if(approving){const counts=queryIndex(index,{fast_slow_mode:composition.fast_slow_mode||'rr'}).category_counts,missing=categories.filter(([k])=>counts[k]&&composition.category_reviews?.[k]!==index.basis_versions[k]);if(missing.length)throw Error('请完成报告分类筛选：'+missing.map(x=>x[1]).join('、'));if((composition.diagnosis_blocks||[]).some(b=>b.needs_review))throw Error('请核对保留的人工诊断文字')}
    return selected;
  }
  const api={categories,patterns,buildIndex,queryIndex,hrvWindows,validateReport,fingerprint};globalThis.ECGClinicalAnalysis=api;if(typeof module!=='undefined')module.exports=api;
})();
