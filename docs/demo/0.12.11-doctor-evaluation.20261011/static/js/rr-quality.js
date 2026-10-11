"use strict";
/* Interval contract mirrored by ecg_core/rr_quality.py. No disease inference. */
(root=>{
  const nonbeats=new Set(['O','Y','T']);
  const rhythmEpisodes=events=>events.filter(e=>e.category==='AF'&&e.end_s>e.time_s).map(e=>({start_s:e.time_s,end_s:e.end_s,kind:e.subtype||'AF',status:e.rhythm_status||e.diagnosis_status||'pending'}));
  function rhythmSummary(episodes,duration,start=0,end=duration){
    if(![duration,start,end].every(Number.isFinite)||!(0<=start&&start<=end&&end<=duration))throw Error('节律统计范围无效');
    const groups={confirmed_af:[],confirmed_afl:[],confirmed_any:[],pending_any:[]},counts=Object.fromEntries(Object.keys(groups).map(k=>[k,0]));
    for(const e of episodes){
      const {start_s:a,end_s:b,kind,status}=e;
      if(![a,b].every(Number.isFinite)||b<=a||!['AF','AFL'].includes(kind)||!['pending','confirmed','excluded'].includes(status))throw Error('节律片段格式无效');
      const keys=status==='confirmed'?['confirmed_any',kind==='AF'?'confirmed_af':'confirmed_afl']:status==='pending'?['pending_any']:[];
      for(const key of keys){counts[key]+=Number(start<=a&&a<end);const lo=Math.max(start,a),hi=Math.min(end,b);if(hi>lo)groups[key].push([lo,hi]);}
    }
    const result={start_s:start,end_s:end,denominator_s:end-start},round=v=>Math.round(v*1e6)/1e6;
    for(const [key,spans] of Object.entries(groups)){
      const merged=[];for(const [a,b] of spans.sort((a,b)=>a[0]-b[0]||a[1]-b[1])){if(merged.length&&a<=merged.at(-1)[1])merged.at(-1)[1]=Math.max(b,merged.at(-1)[1]);else merged.push([a,b]);}
      const seconds=round(merged.reduce((s,[a,b])=>s+b-a,0));result[key]={count:counts[key],intersecting_count:spans.length,seconds,pct:end>start?round(seconds/(end-start)*100):null};
    }return result;
  }
  const qrsRows=rows=>rows.filter(r=>!nonbeats.has(r.class_code));
  // Stored end_sample is inclusive; a single sample is a 5 ms exclusion.
  const annotationExclusions=annotations=>annotations.filter(a=>['AF','AFL'].includes(a.details?.kind)&&a.details.status!=='excluded'&&Number.isFinite(a.sample_index)&&Number.isFinite(a.details.end_sample)).map(a=>[a.sample_index/200,(a.details.end_sample+1)/200]);
  function intervalMask(rows,excluded=[]){
    const spans=excluded.filter(([a,b])=>Number.isFinite(a)&&Number.isFinite(b)&&b>a).sort((a,b)=>a[0]-b[0]||a[1]-b[1]),merged=[];
    for(const [a,b] of spans){if(merged.length&&a<=merged.at(-1)[1])merged.at(-1)[1]=Math.max(b,merged.at(-1)[1]);else merged.push([a,b])}
    return rows.map((b,i)=>{
      if(!i)return false;
      const a=rows[i-1],s=a.sample_index,t=b.sample_index,rr=b.rr_ms;
      if([a,b].some(r=>r.class_code==='X'||nonbeats.has(r.class_code))||![s,t,rr].every(Number.isFinite)||s<0||t<=s||rr<=0||Math.abs((t-s)*5-rr)>10)return false;
      let lo=0,hi=merged.length;
      while(lo<hi){const mid=(lo+hi)>>>1;if(merged[mid][0]<t/200)lo=mid+1;else hi=mid}
      return !lo||merged[lo-1][1]<=s/200;
    });
  }
  function nnIntervals(feed){
    const rows=qrsRows(feed.beats),valid=intervalMask(rows,feed.excluded_rhythm_intervals),opts=feed.document.settings,result=[];
    rows.forEach((r,i)=>{if(valid[i]&&rows[i-1].class_code==='N'&&r.class_code==='N'&&r.rr_ms>=opts.nn_min&&r.rr_ms<=opts.nn_max&&r.sample_index/200<=feed.duration)result.push([i-1,rows[i-1].sample_index/200,r.sample_index/200,r.rr_ms])});
    return result;
  }
  function fiveMinuteBlocks(nn,end,start=0){
    const buckets=new Map();
    for(const r of nn){const k=Math.floor((r[1]-start)/300);if(k>=0&&r[2]<=Math.min(end,start+(k+1)*300)){if(!buckets.has(k))buckets.set(k,[]);buckets.get(k).push(r)}}
    return [...buckets].sort((a,b)=>a[0]-b[0]).filter(([k,r])=>start+(k+1)*300<=end&&r.length>=30&&r.reduce((s,x)=>s+x[3],0)>=240000).map(([k,r])=>[start+k*300,start+(k+1)*300,r]);
  }
  function validRRRows(rows,duration){
    const qrs=qrsRows(rows),valid=intervalMask(qrs);
    return qrs.filter((r,i)=>valid[i]&&r.sample_index/200<duration);
  }
  function consistentRate(row){
    return Number.isFinite(row.hr)&&row.hr>0&&Number.isFinite(row.rr_ms)&&row.rr_ms>0&&Math.abs(row.hr-60000/row.rr_ms)<=.051;
  }
  const api={rhythmEpisodes,rhythmSummary,qrsRows,annotationExclusions,intervalMask,nnIntervals,validRRRows,consistentRate,fiveMinuteBlocks};root.ECGRRQuality=api;if(typeof module!=='undefined')module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
