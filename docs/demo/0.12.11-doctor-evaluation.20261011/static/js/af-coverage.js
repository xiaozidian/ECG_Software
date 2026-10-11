"use strict";
// Presentation of the production screen's abstentions; no new classifier.
const ECGAFCoverage=(()=>{
  const reasons={incomplete_window:'不足完整 30 秒',insufficient_intervals:'有效 N-N 间期少于 20 个',low_quality:'有效 N-N 占比不足 90%',insufficient_coverage:'有效间期覆盖不足 25 秒'};
  function summarize(result,start,end){
    if(!Number.isFinite(start)||!Number.isFinite(end)||start<0||end<=start||!Array.isArray(result?.windows)||!result.windows.length)throw Error('筛查覆盖数据不完整，请重新检查');
    let cursor=start,assessed=0,skipped=0,candidate=0,evaluated=0;
    const gaps=[];
    for(const w of result.windows){
      const seconds=w.end_s-w.start_s;
      if(!Number.isFinite(w.start_s)||!Number.isFinite(w.end_s)||Math.abs(w.start_s-cursor)>1e-6||seconds<=0||seconds>30||w.end_s>end+1e-6||typeof w.evaluated!=='boolean'||typeof w.candidate!=='boolean'||(w.evaluated?(w.reason!==null||seconds!==30):(!Object.hasOwn(reasons,w.reason)||w.candidate)))throw Error('筛查覆盖窗口不连续或状态无效，请重新检查');
      cursor=w.end_s;
      if(w.evaluated){assessed+=seconds;evaluated++;if(w.candidate)candidate+=seconds;continue;}
      skipped+=seconds;
      const last=gaps.at(-1);
      if(last&&last.end_s===w.start_s&&last.reason===w.reason){last.end_s=w.end_s;last.windows++;}
      else gaps.push({start_s:w.start_s,end_s:w.end_s,reason:w.reason,windows:1});
    }
    if(Math.abs(cursor-end)>1e-6||evaluated!==result.evaluated_windows||result.windows.length-evaluated!==result.skipped_windows)throw Error('筛查覆盖范围或计数不一致，请重新检查');
    return {start_s:start,end_s:end,total_s:end-start,assessed_s:assessed,skipped_s:skipped,candidate_s:candidate,coverage_pct:assessed/(end-start)*100,evaluated_windows:evaluated,skipped_windows:result.skipped_windows,gaps};
  }
  function page(summary,index=0,size=20){
    if(!Number.isInteger(index)||index<0||!Number.isInteger(size)||size<1||size>100)throw Error('未评估时段页码无效');
    const pages=Math.max(1,Math.ceil(summary.gaps.length/size)),current=Math.min(index,pages-1),offset=current*size;
    return {index:current,pages,offset,items:summary.gaps.slice(offset,offset+size)};
  }
  const states={all:'全部窗口',candidate:'不规则候选',negative:'已评估未提示',unassessed:'未评估'};
  const stateOf=w=>!w.evaluated?'unassessed':w.candidate?'candidate':'negative';
  function windowSnapshot(result){
    // Preserve the screen's actual measurements, including unavailable values.
    // Never recompute a classification from rounded display numbers.
    return result.windows.map((w,index)=>{
      for(const key of ['total_intervals','valid_intervals','pair_count','triple_count'])if(!Number.isInteger(w[key])||w[key]<0)throw Error('筛查窗口计数无效，请重新检查');
      if(w.valid_intervals>w.total_intervals||!Number.isFinite(w.coverage_s)||w.coverage_s<0)throw Error('筛查窗口质量数据无效，请重新检查');
      for(const key of ['cv','normalized_rmssd','turning_ratio'])if(w[key]!==null&&(!Number.isFinite(w[key])||w[key]<0))throw Error('筛查窗口特征无效，请重新检查');
      if(w.turning_ratio>1)throw Error('筛查窗口转折率无效，请重新检查');
      return Object.freeze({...w,index,state:stateOf(w)});
    });
  }
  function windowPage(windows,filter='all',index=0){
    if(!Object.hasOwn(states,filter)||!Number.isInteger(index)||index<0)throw Error('筛查窗口筛选或页码无效');
    const matching=windows.filter(w=>filter==='all'||w.state===filter),pages=Math.max(1,Math.ceil(matching.length/20)),current=Math.min(index,pages-1),offset=current*20;
    return {matching,total:matching.length,index:current,pages,offset,items:matching.slice(offset,offset+20)};
  }
  return {reasons,summarize,page,states,windowSnapshot,windowPage};
})();
if(typeof module!=='undefined')module.exports=ECGAFCoverage;
