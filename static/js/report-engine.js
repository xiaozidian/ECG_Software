"use strict";
/* Paper data contract, kept in parity with ecg_core/report_layout.py. */
(()=>{
  const leads=['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6'],defaults=['II','V1','V5'];
  function settings(raw={}){
    const selected=raw.leads??defaults,seconds=raw.duration_s??7;
    if(!Array.isArray(selected)||!selected.length||selected.length>12||selected.some(x=>!leads.includes(x))||new Set(selected).size!==selected.length)throw Error('请选择 1–12 个不重复的有效导联');
    if(typeof seconds!=='number'||!Number.isFinite(seconds)||seconds<1||seconds>120)throw Error('入报时长须为 1–120 秒；不足 5 搏将自动延长');
    return {leads:leads.filter(x=>selected.includes(x)),duration_s:seconds};
  }
  const beatRows=index=>index.rows.filter(r=>!['X','O','Y','T'].includes(r.class_code)&&r.sample_index>=0&&r.sample_index<index.duration_s*200).sort((a,b)=>a.sample_index-b.sample_index);
  function resolve(index,event,raw={}){
    const spec=settings(raw),total=Math.max(.005,index.duration_s),anchor=Math.min(Math.max(0,event.start_sample/200),total),length=Math.min(total,spec.duration_s),rows=beatRows(index),times=rows.map(r=>r.sample_index/200);
    let start=Math.max(0,Math.min(anchor-length/2,total-length)),end=start+length;
    if(times.filter(t=>t>=start&&t<end).length<5&&times.length){
      const n=Math.min(5,times.length),found=times.findIndex(t=>t>=anchor),pivot=found<0?times.length-1:found,candidates=[];
      for(let i=Math.max(0,pivot-n);i<Math.min(pivot+1,times.length-n+1);i++){
        const lo=Math.max(0,Math.min(start,times[i]-.2)),hi=Math.min(total,Math.max(end,times[i+n-1]+.3));candidates.push([hi-lo,Math.abs((hi+lo)/2-anchor),lo,hi]);
      }
      candidates.sort((a,b)=>a[0]-b[0]||a[1]-b[1]||a[2]-b[2]);if(candidates.length)[,,start,end]=candidates[0];
    }
    start=Math.floor(start*200+1e-7)/200;end=Math.min(total,Math.ceil(end*200-1e-7)/200);
    const visible=rows.filter(r=>r.sample_index/200>=start&&r.sample_index/200<end).map(r=>Object.fromEntries(['sample_index','class_code','hr','rr_ms'].map(k=>[k,r[k]??null]))),actual=Math.round((end-start)*1000)/1000;
    let warning=visible.length<5?`记录可用心搏不足 5 个，当前仅 ${visible.length} 搏`:'';
    if(actual>spec.duration_s+.01)warning=`为包含至少 5 搏，已由 ${spec.duration_s} 秒延长至 ${actual} 秒`+(warning?`；${warning}`:'');
    return {...spec,start_s:start,end_s:end,actual_duration_s:actual,visible_beats:visible,visible_beat_count:visible.length,warning,
      context_start_s:Math.max(0,Math.min(anchor-Math.max(30,actual*3)/2,total-Math.min(total,Math.max(30,actual*3)))),context_duration_s:Math.min(total,Math.max(30,actual*3))};
  }
  function statistics(index,startTime,opts){
    const rows=beatRows(index),parsed=Date.parse(String(startTime).replace(' ','T').slice(0,19)+'Z'),clock=Number.isFinite(parsed)?parsed:null,round=x=>Math.round(x*100)/100;
    function aggregate(lo,hi){
      const beats=rows.filter(r=>r.sample_index/200>=lo&&r.sample_index/200<hi),rates=beats.filter(r=>r.rr_ms>0&&r.hr>0),events=index.events.filter(e=>e.time_s>=lo&&e.time_s<hi);
      const slow=rates.reduce((a,b)=>!a||b.hr<a.hr?b:a,null),fast=rates.reduce((a,b)=>!a||b.hr>a.hr?b:a,null),longest=rates.reduce((a,b)=>!a||b.rr_ms>a.rr_ms?b:a,null),point=r=>r?{hr:r.hr,time_s:r.sample_index/200,rr_ms:r.rr_ms}:null;
      const result={total:beats.length,noise:index.rows.filter(r=>r.sample_index/200>=lo&&r.sample_index/200<hi&&r.class_code==='X').length,min_hr:slow?.hr??null,max_hr:fast?.hr??null,avg_hr:rates.length?round(60000/(rates.reduce((s,r)=>s+r.rr_ms,0)/rates.length)):null,fastest:point(fast),slowest:point(slow),longest:point(longest),tachy_beats:rates.filter(r=>r.hr>=opts.tachy).length,brady_beats:rates.filter(r=>r.hr<=opts.brady).length,pause:events.filter(e=>e.category==='pause').length,af:events.filter(e=>e.category==='AF'&&e.diagnosis_status==='confirmed').length};
      for(const code of ['V','S']){const total=beats.filter(r=>r.class_code===code).length;result[code]={total,pct:beats.length?round(total/beats.length*100):0};for(const [kind,subtypes] of Object.entries({single:['single'],couplet:['couplet'],run:['triplet','run'],bigeminy:['bigeminy'],trigeminy:['nnp','npp']}))result[code][kind]=events.filter(e=>e.category===code&&subtypes.includes(e.subtype)).length;}
      return result;
    }
    const hourly=[];let t=0;
    while(t<index.duration_s){const dt=clock!==null?new Date(clock+t*1000):null,length=Math.min(index.duration_s-t,3600-(dt?dt.getUTCMinutes()*60+dt.getUTCSeconds()+dt.getUTCMilliseconds()/1000:t%3600)),end=t+length;hourly.push({label:dt?dt.toISOString().slice(5,16).replace('T',' '):`+${t/3600}h`,start_s:t,end_s:end,...aggregate(t,end)});t=end;}
    return {summary:aggregate(0,index.duration_s),hourly,settings:opts,method:'当前修订逐搏统计；心率由有效 RR 计算。成对、短阵和联律按起点计次，模式可重叠，不与总心搏相加；长 RR 为阈值候选，房颤/房扑仅计医生已确认片段。'};
  }
  const api={leads,defaults,settings,resolve,statistics};globalThis.ECGReportEngine=api;if(typeof module!=='undefined')module.exports=api;
})();
