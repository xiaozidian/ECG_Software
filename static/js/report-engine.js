"use strict";
/* Paper data contract, kept in parity with ecg_core/report_layout.py. */
(()=>{
  const leads=['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6'],defaults=['II','V1','V5'];
  const stripKey=selection=>selection?.strip_id||selection?.event_id;
  function stripIdentity(raw={}){const result={};if(raw.strip_id!==undefined){if(typeof raw.strip_id!=='string'||!raw.strip_id||raw.strip_id.length>100)throw Error('无效图条标识');result.strip_id=raw.strip_id;}if(raw.representative_role!==undefined){if(!['start','middle','end','custom'].includes(raw.representative_role))throw Error('无效代表图条位置');result.representative_role=raw.representative_role;}return result;}
  function settingsForEvent(event,raw={}){return settings({...raw,leads:raw.leads??(['fastest','slowest','pause','rr_candidate','rr_interval'].includes(event?.category)?defaults:leads)});}
  function reviewNote(entry){
    if(entry.category!=='AF')return '';
    const name=entry.subtype==='AFL'?'房扑':'房颤';
    if(entry.rhythm_status==='confirmed')return `${name}片段已确认 · 不代表报告已审核`;
    if(entry.rhythm_status==='excluded')return `${name}片段已排除 · 不应入报`;
    return `${name}片段待复核 · 非确诊`;
  }
  function intervalPairs(rows,duration){
    const quality=globalThis.ECGRRQuality||(typeof require==='function'?require('./rr-quality.js'):null);
    const qrs=quality.qrsRows(rows),valid=quality.intervalMask(qrs),pairs=[];
    qrs.forEach((r,i)=>{if(valid[i]&&r.sample_index/200<duration)pairs.push([qrs[i-1],r])});
    return pairs;
  }
  function settings(raw={}){
    const selected=raw.leads??defaults,seconds=raw.duration_s??7;
    if(!Array.isArray(selected)||!selected.length||selected.length>12||selected.some(x=>!leads.includes(x))||new Set(selected).size!==selected.length)throw Error('请选择 1–12 个不重复的有效导联');
    if(typeof seconds!=='number'||!Number.isFinite(seconds)||seconds<1||seconds>120)throw Error('入报时长须为 1–120 秒；不足 5 搏将自动延长');
    const spec={leads:leads.filter(x=>selected.includes(x)),duration_s:seconds};
    if('range_start_s' in raw||'range_end_s' in raw){const a=raw.range_start_s,b=raw.range_end_s;if([a,b].some(x=>typeof x!=='number'||!Number.isFinite(x))||a<0||b-a<1||b-a>120)throw Error('人工入报区间须为非负起点、1–120 秒，并同时提供起止时间');Object.assign(spec,{range_start_s:Math.round(a*200)/200,range_end_s:Math.round(b*200)/200})}return spec;
  }
  const beatRows=index=>index.rows.filter(r=>!['X','O','Y','T'].includes(r.class_code)&&r.sample_index>=0&&r.sample_index<index.duration_s*200).sort((a,b)=>a.sample_index-b.sample_index);
  function resolve(index,event,raw={}){
    const spec=settings(raw),total=Math.max(.005,index.duration_s),length=Math.min(total,spec.duration_s),rows=beatRows(index),times=rows.map(r=>r.sample_index/200);let anchor=Math.min(Math.max(0,event.start_sample/200),total);
    if(event.category==='ST'&&event.stt_event_evidence&&typeof event.stt_event_evidence==='object')anchor=Math.min(Math.max(0,event.stt_event_evidence.peak_time_s??anchor),total);
    let start=Math.max(0,Math.min(anchor-length/2,total-length)),end=start+length;
    let pauseStartSample=null;
    if(['pause','rr_candidate'].includes(event.category)){
      const pairs=intervalPairs(index.rows,index.duration_s).filter(([a,b])=>b.sample_index===event.start_sample&&(event.category==='pause'?b.rr_ms>2500:a.sample_index===event.candidate_context?.rr_start_sample));
      if(pairs.length!==1)throw Error('长 RR 的 R 峰依据已变化，请重新选择事件');
      pauseStartSample=pairs[0][0].sample_index;
      start=Math.max(0,Math.min(start,pauseStartSample/200-.2));end=Math.min(total,Math.max(end,anchor+.3));
    }
    const manual='range_start_s' in spec;
    if(manual){start=spec.range_start_s;end=spec.range_end_s;if(end>total)throw Error('人工区间须在记录范围内，并包含当前事件定位心搏');if(['AF','ST'].includes(event.category)){if(!(start<(event.end_s??(event.end_sample??event.start_sample)/200)&&end>event.start_sample/200))throw Error('代表图条须与当前房颤／房扑或 ST 事件片段相交');}else if(!(start<=anchor&&anchor<end))throw Error('人工区间须在记录范围内，并包含当前事件定位心搏');if(pauseStartSample!==null&&Math.round(start*200)>pauseStartSample)throw Error('RR 候选入图须包含完整间期的两个 R 峰（原始计时点）');if(times.filter(t=>t>=start&&t<end).length<Math.min(5,times.length))throw Error('人工入报区间至少包含 5 个可用心搏，请向外拖动橘色边界')}
    if(!manual&&times.filter(t=>t>=start&&t<end).length<5&&times.length){
      const n=Math.min(5,times.length),found=times.findIndex(t=>t>=anchor),pivot=found<0?times.length-1:found,candidates=[];
      for(let i=Math.max(0,pivot-n);i<Math.min(pivot+1,times.length-n+1);i++){
        const lo=Math.max(0,Math.min(start,times[i]-.2)),hi=Math.min(total,Math.max(end,times[i+n-1]+.3));candidates.push([hi-lo,Math.abs((hi+lo)/2-anchor),lo,hi]);
      }
      candidates.sort((a,b)=>a[0]-b[0]||a[1]-b[1]||a[2]-b[2]);if(candidates.length)[,,start,end]=candidates[0];
    }
    start=Math.floor(start*200+1e-7)/200;end=Math.min(total,Math.ceil(end*200-1e-7)/200);
    const visible=rows.filter(r=>r.sample_index/200>=start&&r.sample_index/200<end).map(r=>Object.fromEntries(['sample_index','class_code','hr','rr_ms'].map(k=>[k,r[k]??null]))),actual=Math.round((end-start)*1000)/1000;
    let warning=visible.length<5?`记录可用心搏不足 5 个，当前仅 ${visible.length} 搏`:'';
    if(!manual&&actual>spec.duration_s+.01)warning=`为${event.category==='pause'?'覆盖完整 RR 间期并包含至少 5 搏':'包含至少 5 搏'}，已由 ${spec.duration_s} 秒延长至 ${actual} 秒`+(warning?`；${warning}`:'');
    return {...spec,start_s:start,end_s:end,actual_duration_s:actual,visible_beats:visible,visible_beat_count:visible.length,warning,
      context_start_s:Math.max(0,Math.min((manual&&['AF','ST'].includes(event.category)?(start+end)/2:anchor)-Math.max(30,actual*3)/2,total-Math.min(total,Math.max(30,actual*3)))),context_duration_s:Math.min(total,Math.max(30,actual*3))};
  }
  function afRepresentatives(index,event,raw={}){
    if(event?.category!=='AF'||!Number.isFinite(event.end_s)||event.end_s<=event.start_sample/200)throw Error('找不到有效房颤／房扑片段');
    const spec=settingsForEvent(event,raw),a=event.start_sample/200,b=event.end_s,L=spec.duration_s,positions={},roles=['start','middle','end'];delete spec.range_start_s;delete spec.range_end_s;
    const anchors=b-a<=L?{start:(a+b)/2,middle:(a+b)/2,end:(a+b)/2}:{start:a+L/2,middle:(a+b)/2,end:b-L/2};
    for(const role of roles){const resolved=resolve(index,{...event,start_sample:Math.floor(anchors[role]*200+.5)},spec),selectable=resolved.visible_beat_count>=5&&resolved.actual_duration_s<=120;positions[role]={representative_role:role,start_s:resolved.start_s,end_s:resolved.end_s,duration_s:resolved.actual_duration_s,visible_beat_count:resolved.visible_beat_count,warning:resolved.actual_duration_s>120?'包含 5 搏所需范围超过 120 秒，请人工回看后选择可用图条':resolved.warning,selectable};}
    const equal=(x,y)=>Math.round(x.start_s*200)===Math.round(y.start_s*200)&&Math.round(x.end_s*200)===Math.round(y.end_s*200),covers=(x,lo,hi)=>x.start_s<=lo+1e-8&&x.end_s>=hi-1e-8;
    const whole=['middle','start','end'].map(role=>positions[role]).find(p=>p.selectable&&covers(p,a,b));let items;
    if(whole)items=[whole];else{items=['start','end'].map(role=>positions[role]).filter(p=>p.selectable).filter((p,i,list)=>!list.slice(0,i).some(q=>equal(p,q)));const middle=positions.middle;let covered=middle.start_s;for(const p of [...items].sort((x,y)=>x.start_s-y.start_s)){if(p.start_s>covered+1e-8)break;covered=Math.max(covered,p.end_s);}if(middle.selectable&&covered<middle.end_s-1e-8&&!items.some(p=>equal(p,middle)))items.push(middle);items.sort((x,y)=>roles.indexOf(x.representative_role)-roles.indexOf(y.representative_role));}
    return {items,positions,requested_duration_s:L,episode_start_s:a,episode_end_s:b,units:'seconds',minimum_visible_beats:5};
  }
  function sttRepresentatives(index,event,raw={}){
    if(event?.category!=='ST')throw Error('仅 ST-T 复核记录支持此代表图条推荐');
    const spec=settings(raw);delete spec.range_start_s;delete spec.range_end_s;
    const a=event.start_sample/200,b=event.end_s??(event.end_sample??event.start_sample)/200;if(!(b>a))throw Error('ST-T 复核范围无效');
    const proof=event.stt_event_evidence||{};let extreme=proof.peak_time_s;
    if(!Number.isFinite(extreme)||!(a<=extreme&&extreme<b))extreme=(proof.findings||[]).find(c=>Number.isFinite(c.peak_time_s)&&a<=c.peak_time_s&&c.peak_time_s<b)?.peak_time_s??null;
    const anchorKind=extreme===null?'middle':'extreme',length=spec.duration_s,anchors={start:a+Math.min(length,b-a)/2,middle:extreme??(a+b)/2,end:b-Math.min(length,b-a)/2},positions={};
    for(const [role,anchor] of Object.entries(anchors)){
      const view={...event,start_sample:Math.floor(anchor*200+.5)};delete view.stt_event_evidence;
      const value=resolve(index,view,spec),selectable=value.visible_beat_count>=5&&value.actual_duration_s<=120;
      positions[role]={representative_role:role,anchor_kind:role==='middle'?anchorKind:role,label:role==='middle'?(anchorKind==='extreme'?'极值':'段中'):role==='start'?'起始':'末尾',start_s:value.start_s,end_s:value.end_s,duration_s:value.actual_duration_s,visible_beat_count:value.visible_beat_count,selectable,warning:value.actual_duration_s<=120?value.warning:'包含 5 搏所需范围超过 120 秒，请人工选择图条'};
    }
    const available=Object.fromEntries(Object.entries(positions).filter(([,p])=>p.selectable)),covering=['middle','start','end'].map(role=>available[role]).find(p=>p&&p.start_s<=a&&p.end_s>=b);let items=covering?[covering]:[];
    if(!covering){for(const role of ['start','end','middle']){const p=available[role];if(!p)continue;let cursor=p.start_s;for(const previous of [...items].sort((x,y)=>x.start_s-y.start_s))if(previous.start_s<=cursor)cursor=Math.max(cursor,previous.end_s);if(cursor<p.end_s)items.push(p);}items.sort((x,y)=>['start','middle','end'].indexOf(x.representative_role)-['start','middle','end'].indexOf(y.representative_role));}
    return {items,positions,episode_start_s:a,episode_end_s:b,units:'seconds',minimum_visible_beats:5,requested_duration_s:length};
  }
  function statistics(index,startTime,opts,pauseEdges=null){
    const rows=beatRows(index),parsed=Date.parse(String(startTime).replace(' ','T').slice(0,19)+'Z'),clock=Number.isFinite(parsed)?parsed:null,round=x=>Math.round(x*100)/100;
    const quality=globalThis.ECGRRQuality||(typeof require==='function'?require('./rr-quality.js'):null);
    const rrRows=quality.validRRRows(index.rows,index.duration_s),rateRows=rrRows.filter(quality.consistentRate),episodes=quality.rhythmEpisodes(index.events);
    function aggregate(lo,hi){
      const beats=rows.filter(r=>r.sample_index/200>=lo&&r.sample_index/200<hi),rates=rateRows.filter(r=>r.sample_index/200>=lo&&r.sample_index/200<hi),events=index.events.filter(e=>e.time_s>=lo&&e.time_s<hi);
      const intervals=rrRows.filter(r=>r.sample_index/200>=lo&&r.sample_index/200<hi);
      const slow=rates.reduce((a,b)=>!a||b.hr<a.hr?b:a,null),fast=rates.reduce((a,b)=>!a||b.hr>a.hr?b:a,null),longest=intervals.reduce((a,b)=>!a||b.rr_ms>a.rr_ms?b:a,null),point=r=>r?{hr:quality.consistentRate(r)?r.hr:null,time_s:r.sample_index/200,rr_ms:r.rr_ms}:null;
      const result={total:beats.length,noise:index.rows.filter(r=>r.sample_index/200>=lo&&r.sample_index/200<hi&&r.class_code==='X').length,min_hr:slow?.hr??null,max_hr:fast?.hr??null,avg_hr:rates.length?round(60000/(rates.reduce((s,r)=>s+r.rr_ms,0)/rates.length)):null,fastest:point(fast),slowest:point(slow),longest:point(longest),tachy_beats:rates.filter(r=>r.hr>=opts.tachy).length,brady_beats:rates.filter(r=>r.hr<=opts.brady).length,pause:events.filter(e=>e.category==='pause').length};
      for(const code of ['V','S']){const total=beats.filter(r=>r.class_code===code).length;result[code]={total,pct:beats.length?round(total/beats.length*100):null};for(const [kind,subtypes] of Object.entries({single:['single'],couplet:['couplet'],run:['triplet','run'],bigeminy:['bigeminy'],trigeminy:['nnp','npp']}))result[code][kind]=events.filter(e=>e.category===code&&subtypes.includes(e.subtype)).length;}
      result.pause_over3=events.filter(e=>e.category==='pause'&&e.rr_ms>3000).length;
      result.rr_interval_count=intervals.length;result.rate_interval_count=rates.length;
      result.rhythm=quality.rhythmSummary(episodes,index.duration_s,lo,hi);result.af=result.rhythm.confirmed_any.count;
      return result;
    }
    const hourly=[];let t=0;
    while(t<index.duration_s){const dt=clock!==null?new Date(clock+t*1000):null,length=Math.min(index.duration_s-t,3600-(dt?dt.getUTCMinutes()*60+dt.getUTCSeconds()+dt.getUTCMilliseconds()/1000:t%3600)),end=t+length;hourly.push({label:dt?dt.toISOString().slice(5,16).replace('T',' '):`+${t/3600}h`,start_s:t,end_s:end,...aggregate(t,end)});t=end;}
    const pause_distribution=quality.rrDistribution(index.rows,index.duration_s,pauseEdges);pause_distribution.bins.forEach(b=>delete b.samples);
    return {pause_distribution,summary:aggregate(0,index.duration_s),hourly,settings:opts,method:'当前修订逐搏统计；心率由有效 RR 计算。成对、短阵和联律按起点计次，模式可重叠，不与总心搏相加；长 RR 为阈值候选，房颤/房扑仅计医生已确认片段。'};
  }
  const api={leads,defaults,stripKey,stripIdentity,settingsForEvent,reviewNote,intervalPairs,settings,resolve,afRepresentatives,sttRepresentatives,statistics};globalThis.ECGReportEngine=api;if(typeof module!=='undefined')module.exports=api;
})();
