"use strict";
/* Full-source mathematical raw ST statistics. No patient source or clinical validation. */
globalThis.ECGSTTRangeMath = (() => {
  const RATE=200, BLOCK=3200, MINIMUM=12000;
  const LEADS=['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6'];
  const BASELINE=[-40,-36,-32,-28,-24], ST=[-2,-1,0,1,2];
  const BASE_PROFILE={"id":"raw-200hz-fixed16s-st-perbeat-mean-v1","sample_rate_hz":200,"sample_rate_device_verified":false,"block_seconds":16,"minimum_range_samples":12000,"measurement_ms":60,"baseline_offsets_samples":[-40,-36,-32,-28,-24],"baseline":"five-point pre-QRS median (-200,-180,-160,-140,-120 ms); PR surrogate, physician verification required","st_window_offsets_samples":[-2,-1,0,1,2],"st_measurement":"five-point median centred on machine J plus selected offset","aggregate":"arithmetic_mean_of_used_per_beat_st_minus_baseline","j_basis":"fixed_16s_machine_estimate_after_explicit_masks","j_representative_limit":7,"minimum_j_representatives":3,"representative_exclusion_halo_samples":[-40,47],"mean_beat_limit":null,"candidate_rules":"legacy group=1; same fixed-block neighbours not group 3/34; integer RR 350..2000 ms inclusive; source edge guard","source_edge_guard":"R >=50 and R+120 < source sample count; unavailable guard is counted as missing, never clamped","mask_rule":"R anchor or baseline span [R-40,R-23) or ST span [R+J+offset-2,R+J+offset+3) intersects explicit half-open mask","neighbours_rebuilt_after_masks":false,"quality_gate":{"minimum_normal_ratio":0.35,"minimum_score":0.42,"population":"original block non-artifact anchors outside explicit masks; candidate density after exact support masks","landmark_confidence_is_gate":false},"quality_note":"existing engineering block gate; labels, machine landmarks and signal quality are not physician verified","unit_label":"u","units":"device_unit","calibration_verified":false,"lead_mapping_verified":false,"filter":"raw source; no display high-pass","diagnosis_generated":false,"mean_proves_sustained_depression":false};
  const copy=value=>JSON.parse(JSON.stringify(value));
  function fail(message){throw new Error(message);}
  function integer(value,label){if(!Number.isSafeInteger(value))fail(label+' must be an integer sample');return value;}
  function finiteJSON(value){
    if(value===null||typeof value==='string'||typeof value==='boolean')return;
    if(typeof value==='number'&&Number.isFinite(value))return;
    if(Array.isArray(value)){value.forEach(finiteJSON);return;}
    if(value&&typeof value==='object'&&Object.getPrototypeOf(value)!==null){Object.values(value).forEach(finiteJSON);return;}
    fail('basis and method inputs must contain finite JSON values');
  }
  function canonical(value){
    finiteJSON(value);
    const ordered=v=>Array.isArray(v)?v.map(ordered):v&&typeof v==='object'?Object.fromEntries(Object.keys(v).sort().map(k=>[k,ordered(v[k])])):v;
    return JSON.stringify(ordered(value));
  }
  async function digest(value){return shaBytes(new TextEncoder().encode(canonical(value)));}
  async function shaBytes(bytes){
    if(!globalThis.crypto?.subtle)fail('Mathematical source binding requires SHA-256 support');
    const bytesHash=new Uint8Array(await crypto.subtle.digest('SHA-256',bytes));
    return Array.from(bytesHash,b=>b.toString(16).padStart(2,'0')).join('');
  }
  function median(values){const a=values.filter(Number.isFinite).slice().sort((x,y)=>x-y);if(!a.length)return 0;const k=Math.floor(a.length/2);return a.length%2?a[k]:(a[k-1]+a[k])/2;}
  function mad(values){const center=median(values);return median(values.map(v=>Math.abs(v-center)));}
  function roundEven(value){const lo=Math.floor(value),fraction=value-lo;return fraction<.5?lo:fraction>.5?lo+1:lo%2===0?lo:lo+1;}
  // Python decimal round uses the exact binary float, not a rounded x*10**digits.
  function roundDecimal(value,digits){
    if(!Number.isFinite(value))fail('Nonfinite arithmetic result');
    const bits=new DataView(new ArrayBuffer(8));bits.setFloat64(0,Math.abs(value),false);
    const hi=bits.getUint32(0,false),low=bits.getUint32(4,false),exp=(hi>>>20)&2047;
    let n=(BigInt(hi&1048575)<<32n)|BigInt(low),power;
    if(exp===0)power=-1074;else{n|=1n<<52n;power=exp-1023-52;}
    let d=1n;if(power>=0)n<<=BigInt(power);else d<<=BigInt(-power);
    const factor=10n**BigInt(digits);n*=factor;
    let q=n/d;const remainder=n%d;
    if(remainder*2n>d||(remainder*2n===d&&q%2n!==0n))q++;
    const out=Number(q)/Number(factor);return value<0||Object.is(value,-0)?-out:out;
  }
  function evenly(values,limit){if(values.length<=limit)return values.slice();return Array.from({length:limit},(_,i)=>values[roundEven(i*(values.length-1)/(limit-1))]);}
  function profile(ms=60){if(!Number.isInteger(ms)||![0,60,80].includes(ms))fail('measurement_ms must be 0, 60 or 80');return {...copy(BASE_PROFILE),measurement_ms:ms};}
  function strictRecords(records){
    if(!Array.isArray(records))fail('invalid beat record');
    const normalized=records.map(row=>{
      let sample,group,rr;
      if(Array.isArray(row)){if(row.length<7)fail('invalid beat record');[sample,group,rr]=[row[0],row[2],row[6]];}
      else if(row&&typeof row==='object'){sample=row.sample_index;group=Object.hasOwn(row,'group')?row.group:row.source_group;rr=row.rr_ms;}
      else fail('invalid beat record');
      if(!Number.isSafeInteger(sample)||!Number.isSafeInteger(group))fail('beat sample and group must be integer values');
      if(!rr)rr=0;
      if(typeof rr==='string'){if(!/^[+-]?[0-9]+(?:_[0-9]+)*$/.test(rr.trim()))fail('invalid beat record');rr=Number(rr.replaceAll('_',''));}
      if(typeof rr==='boolean')rr=Number(rr);
      if(typeof rr!=='number'||!Number.isFinite(rr))fail('invalid beat record');
      return [sample,group,Math.trunc(rr)];
    }).sort((a,b)=>a[0]-b[0]||a[1]-b[1]||a[2]-b[2]);
    if(normalized.some((r,i)=>i&&r[0]===normalized[i-1][0]))fail('duplicate beat sample anchors are ambiguous');
    return normalized;
  }
  function rawSnapshot(raw){
    let bytes;
    if(Object.prototype.toString.call(raw)==='[object ArrayBuffer]')bytes=new Uint8Array(raw);
    else if(ArrayBuffer.isView(raw))bytes=new Uint8Array(raw.buffer,raw.byteOffset,raw.byteLength);
    else fail('raw_samples must be complete source-format bytes');
    if(!bytes.byteLength||bytes.byteLength%16)fail('source must contain complete nonempty eight-channel frames');
    return new Uint8Array(bytes);
  }
  function readLeads(view,sample,total){
    const at=Math.max(0,Math.min(total-1,sample))*16;
    const raw=Array.from({length:8},(_,i)=>view.getInt16(at+i*2,true)),a=raw[0],b=raw[1];
    return [a,b,b-a,-(a+b)/2,a-b/2,b-a/2,...raw.slice(2)];
  }
  function frameValues(view,beat,offsets,total){return offsets.map(offset=>readLeads(view,beat[0]+offset,total));}
  function spanOffsets(start,end,step=1){const rows=[];for(let i=start;i<=end;i+=step)rows.push(i);return rows;}
  function estimateJ(view,beats,total){
    const energies=Array.from({length:33},(_,i)=>median(beats.flatMap(row=>{
      const a=readLeads(view,row[0]+i-1,total),b=readLeads(view,row[0]+i,total);
      return [1,6,10].map(k=>Math.abs(b[k]-a[k])); // Stored II/V1/V5; derived columns 1/6/10.
    })));
    let peakIndex=0;for(let i=1;i<21;i++)if(energies[i]>energies[peakIndex])peakIndex=i;
    const peak=energies[peakIndex],noise=median(energies.slice(-8)),threshold=Math.max(2,noise*2.5,peak*.12);
    let j=18;for(let i=Math.max(8,peakIndex+2);i<29;i++)if(energies.slice(i,i+4).every(v=>v<=threshold)){j=i;break;}
    return [j,Math.max(0,Math.min(1,(peak-noise)/Math.max(peak,1)))];
  }
  function blockMeasurement(view,beats,population,total,ms,normalCount){
    const [j,confidence]=estimateJ(view,beats,total),stOffset=j+roundEven(ms*RATE/1000);
    const columns=LEADS.map(()=>({baseline:[],st:[],t:[],qrs:[],span:[]}));
    for(const row of beats){
      const base=frameValues(view,row,BASELINE,total),st=frameValues(view,row,spanOffsets(stOffset-2,stOffset+2),total);
      const qrs=frameValues(view,row,spanOffsets(-8,j,2),total);
      const rrSamples=Math.max(roundEven(row[2]*RATE/1000),roundEven(.45*RATE));
      const last=Math.min(j+72,Math.max(j+30,roundEven(rrSamples*.62)));
      const t=frameValues(view,row,spanOffsets(j+24,last,2),total);
      for(let k=0;k<LEADS.length;k++){
        const baseline=median(base.map(r=>r[k])),q=qrs.map(r=>r[k]),tv=t.map(r=>r[k]-baseline);
        let tValue=tv[0];for(const v of tv)if(Math.abs(v)>Math.abs(tValue))tValue=v;
        columns[k].baseline.push(baseline);columns[k].st.push(median(st.map(r=>r[k]))-baseline);
        columns[k].t.push(tValue);columns[k].qrs.push(Math.max(...q)-Math.min(...q));
        columns[k].span.push(Math.max(...base.map(r=>r[k]))-Math.min(...base.map(r=>r[k])));
      }
    }
    const scores=[],leadValues={};
    LEADS.forEach((lead,k)=>{
      const col=columns[k],qrs=median(col.qrs),baseVariation=mad(col.baseline)+median(col.span);
      const qrsVariation=mad(col.qrs)/Math.max(qrs,1),noiseRatio=baseVariation/Math.max(qrs,40);
      const score=Math.max(0,Math.min(1,1-Math.min(.65,noiseRatio)-Math.min(.35,qrsVariation)));
      scores.push(score);leadValues[lead]={st_level_units:roundDecimal(median(col.st),2),t_amplitude_units:roundDecimal(median(col.t),2),qrs_amplitude_units:roundDecimal(qrs,2),quality_score:roundDecimal(score,3)};
    });
    const ratio=normalCount/Math.max(population,1),overall=Math.max(0,Math.min(1,median(scores)*Math.min(1,ratio/.6)));
    return {j_offset_ms:j*5,landmark_confidence:roundDecimal(confidence,3),normal_beat_count:normalCount,measurement_beat_count:beats.length,normal_beat_ratio:roundDecimal(ratio,3),quality_score:roundDecimal(overall,3),eligible:ratio>=.35&&overall>=.42,leads:leadValues};
  }
  function pyStrip(value){return value.replace(/^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/g,'');}
  async function normalizeMasks(items,total){
    if(items===null||items===undefined)items=[];if(!Array.isArray(items))fail('each mask must be a dictionary with integer sample boundaries');
    const masks=await Promise.all(items.map(async item=>{
      if(!item||typeof item!=='object'||Array.isArray(item))fail('each mask must be a dictionary with integer sample boundaries');
      const start=integer(item.start_sample,'mask start_sample'),end=integer(item.end_sample,'mask end_sample');
      if(!(0<=start&&start<end&&end<=total))fail('mask must be a nonempty half-open interval within the source');
      if(typeof item.reason!=='string'||!pyStrip(item.reason)||Array.from(item.reason).length>200)fail('each mask requires a nonempty reason of at most 200 characters');
      const kind=Object.hasOwn(item,'kind')?item.kind:'exclusion';if(!['exclusion','missing'].includes(kind))fail('mask kind must be exclusion or explicitly known missing');
      const row={start_sample:start,end_sample:end,reason:pyStrip(item.reason),kind};
      for(const key of ['origin','review_status'])if(Object.hasOwn(item,key)){
        if(typeof item[key]!=='string'||Array.from(item[key]).length>200)fail('mask '+key+' must be a string');row[key]=item[key];
      }
      const flag=Object.fromEntries(['kind','reason','origin','review_status'].filter(k=>Object.hasOwn(row,k)).map(k=>[k,row[k]]));
      return {row,key:await digest(row),flag,flagKey:await digest(flag)};
    }));
    return [...new Map(masks.map(mask=>[mask.key,mask])).values()].sort((a,b)=>a.row.start_sample-b.row.start_sample||a.row.end_sample-b.row.end_sample||a.key.localeCompare(b.key));
  }
  function hits(masks,start,end){return masks.filter(m=>m.row.start_sample<end&&m.row.end_sample>start);}
  function maskStatus(rows){return rows.some(m=>m.row.kind==='missing')?'missing':'excluded';}
  function unionSize(rows){let total=0,previous=null;for(const [start,end] of rows.filter(r=>r[1]>r[0]).sort((a,b)=>a[0]-b[0]||a[1]-b[1])){
    if(previous===null||start>previous[1]){if(previous)total+=previous[1]-previous[0];previous=[start,end];}else previous[1]=Math.max(previous[1],end);
  }return total+(previous?previous[1]-previous[0]:0);}
  function intersect(masks,start,end,kind=null){return unionSize(masks.filter(m=>kind===null||m.row.kind===kind).map(m=>[Math.max(start,m.row.start_sample),Math.min(end,m.row.end_sample)]));}
  function bump(counts,key){counts[key]=(counts[key]||0)+1;}
  function sortedCounts(counts){return Object.fromEntries(Object.keys(counts).sort().map(k=>[k,counts[k]]));}
  function countsOf(status,reasons){return {detected_count:Object.values(status).reduce((a,b)=>a+b,0),used_count:status.used||0,excluded_count:status.excluded||0,missing_count:status.missing||0,reason_counts:sortedCounts(reasons)};}
  function mean(values){return values.length?values.reduce((sum,value)=>sum+value,0)/values.length:null;}
  async function calculate(raw,records,options={}){
    const bytes=rawSnapshot(raw),view=new DataView(bytes.buffer),total=bytes.byteLength/16;
    const start=integer(options.start_sample,'start_sample'),end=integer(options.end_sample,'end_sample');
    if(!(0<=start&&start<end&&end<=total))fail('range must lie within the source; boundaries are not silently clipped');
    if(end-start<MINIMUM)fail('selected range must contain at least 60 seconds (12000 samples)');
    const method=profile(options.measurement_ms===undefined?60:options.measurement_ms);
    const chosen=options.leads===undefined||options.leads===null?LEADS.slice():Array.isArray(options.leads)?options.leads.slice():options.leads;
    if(!Array.isArray(chosen)||!chosen.length||chosen.some(x=>!LEADS.includes(x))||new Set(chosen).size!==chosen.length)fail('select unique supported leads');
    const suppliedScope=options.basis===undefined||options.basis===null?{}:options.basis;
    if(!suppliedScope||typeof suppliedScope!=='object'||Array.isArray(suppliedScope))fail('basis must be a dictionary');
    canonical(suppliedScope);const scope=copy(suppliedScope),normalized=strictRecords(records);
    const masks=await normalizeMasks(options.exclusions,total),publicMasks=masks.map(m=>m.row);
    const byBlock=new Map();for(const row of normalized)if(0<=row[0]&&row[0]<total){const id=Math.floor(row[0]/BLOCK);if(!byBlock.has(id))byBlock.set(id,[]);byBlock.get(id).push(row);}
    const values=Object.fromEntries(chosen.map(l=>[l,[]])),statuses={},reasons={},maskFlags={},flagDefinitions={};
    const blocks=[],usedAnchors=[];let eligibleSamples=0;
    for(let grid=Math.floor(start/BLOCK);grid<=Math.floor((end-1)/BLOCK);grid++){
      const rows=byBlock.get(grid)||[],classifications=new Map(),observations=new Map(),candidates=[];
      rows.forEach((row,i)=>{
        const [r,group,rr]=row,previous=rows[i-1]?.[1],following=rows[i+1]?.[1];
        const anchor=hits(masks,r,r+1),baseline=hits(masks,r-40,r-23);observations.set(r,anchor.concat(baseline));
        if(group!==1)classifications.set(r,['excluded','non_n_candidate']);
        else if([3,34].includes(previous)||[3,34].includes(following))classifications.set(r,['excluded','adjacent_v_or_artifact']);
        else if(!(350<=rr&&rr<=2000))classifications.set(r,['excluded','rr_outside_legacy_bounds']);
        else if(anchor.length){const status=maskStatus(anchor);classifications.set(r,[status,status==='missing'?'explicit_missing_interval':'explicit_anchor_exclusion']);}
        else if(baseline.length){const status=maskStatus(baseline);classifications.set(r,[status,status==='missing'?'explicit_missing_support':'measurement_support_exclusion']);}
        else if(r<50||r+120>=total)classifications.set(r,['missing','source_edge_guard_unavailable']);
        else candidates.push(row);
      });
      const representatives=evenly(candidates.filter(r=>!hits(masks,r[0]-40,r[0]+47).length),7);
      const blockStart=grid*BLOCK,blockEnd=Math.min(total,(grid+1)*BLOCK),selected=rows.filter(r=>start<=r[0]&&r[0]<end);
      const block={block_index:grid,start_sample:blockStart,end_sample:blockEnd,range_start_sample:Math.max(start,blockStart),range_end_sample:Math.min(end,blockEnd),j_representative_samples:representatives.map(r=>r[0]),candidate_count:candidates.length,j_offset_samples:null,landmark_confidence:null,quality_score:null,eligible:false};
      const actual=[];let stOffset=null;
      if(representatives.length<3){block.reason='insufficient_uncontaminated_j_representatives';for(const row of candidates)classifications.set(row[0],['missing','j_unavailable']);}
      else{
        const [j]=estimateJ(view,representatives,total);stOffset=j+Math.trunc(method.measurement_ms*RATE/1000);
        for(const row of candidates){const r=row[0],support=hits(masks,r-40,r-23).concat(hits(masks,r+stOffset-2,r+stOffset+3));observations.get(r).push(...support);
          if(support.length){const status=maskStatus(support);classifications.set(r,[status,status==='missing'?'explicit_missing_support':'measurement_support_exclusion']);}else actual.push(row);
        }
        const population=rows.filter(r=>r[1]!==34&&!hits(masks,r[0],r[0]+1).length).length;
        const measurement=blockMeasurement(view,representatives,population,total,method.measurement_ms,actual.length);
        Object.assign(block,{j_offset_samples:j,j_offset_ms:j*5,landmark_confidence:measurement.landmark_confidence,quality_score:measurement.quality_score,normal_beat_ratio:measurement.normal_beat_ratio,eligible:measurement.eligible});
        block.reason=measurement.eligible?null:'engineering_quality_gate';
        for(const row of actual)classifications.set(row[0],measurement.eligible?['used','used']:['excluded','engineering_quality_gate']);
        if(measurement.eligible){const lo=Math.max(start,blockStart),hi=Math.min(end,blockEnd);eligibleSamples+=hi-lo-intersect(masks,lo,hi);}
      }
      const used=actual.filter(r=>start<=r[0]&&r[0]<end&&classifications.get(r[0])[0]==='used');
      const blockValues=Object.fromEntries(chosen.map(l=>[l,[]]));
      for(const row of used){const base=frameValues(view,row,BASELINE,total),st=frameValues(view,row,ST.map(x=>x+stOffset),total);
        for(const lead of chosen){const k=LEADS.indexOf(lead),difference=median(st.map(r=>r[k]))-median(base.map(r=>r[k]));blockValues[lead].push(difference);values[lead].push(difference);}
        usedAnchors.push(row[0]);
      }
      const blockStatus={},blockReasons={},blockFlags={};
      for(const row of selected){const [status,reason]=classifications.get(row[0]);bump(statuses,status);bump(blockStatus,status);
        if(status!=='used'){bump(reasons,reason);bump(blockReasons,reason);}
        const flags=new Map(observations.get(row[0]).map(m=>[m.flagKey,m.flag]));
        for(const [key,flag] of flags){flagDefinitions[key]=flag;bump(maskFlags,key);bump(blockFlags,key);}
      }
      block.counts=countsOf(blockStatus,blockReasons);
      block.mask_reason_counts=Object.keys(blockFlags).sort().map(k=>({...flagDefinitions[k],beat_count:blockFlags[k]}));
      block.leads=chosen.map(lead=>({lead,mean_units:mean(blockValues[lead]),used_count:blockValues[lead].length}));blocks.push(block);
    }
    const counts=countsOf(statuses,reasons),duration=(end-start)/RATE,allMask=intersect(masks,start,end),missing=intersect(masks,start,end,'missing');
    const result={schema_version:'stt-range-mean-v1',scope,method_profile:method,range:{start_sample:start,end_sample:end,start_s:start/RATE,end_s:end/RATE,duration_s:duration,half_open:true},exclusions:{intervals:publicMasks,digest:await digest(publicMasks)},counts,
      coverage:{requested_duration_s:duration,source_coverage_s:duration-missing/RATE,explicit_excluded_s:(allMask-missing)/RATE,explicit_missing_s:missing/RATE,engineering_eligible_block_coverage_s:eligibleSamples/RATE,engineering_eligible_block_coverage_pct:eligibleSamples*100/(end-start),used_anchor_span_s:usedAnchors.length?(usedAnchors.at(-1)-usedAnchors[0])/RATE:null,max_used_anchor_gap_s:usedAnchors.length>1?Math.max(...usedAnchors.slice(1).map((x,i)=>(x-usedAnchors[i])/RATE)):null,coverage_is_signal_quality:false,definition:'intersection of eligible fixed 16s blocks with selected range, less union of explicit masks; does not certify each second or infer undetected beats'},
      mask_reason_counts:Object.keys(maskFlags).sort().map(k=>({...flagDefinitions[k],beat_count:maskFlags[k]})),count_definition:'used/excluded/missing and primary reason counts are mutually exclusive per detected R; mask reason flags may overlap and never invent undetected beats',
      leads:chosen.map(lead=>({lead,mean_units:mean(values[lead]),used_count:values[lead].length,excluded_count:counts.excluded_count,missing_count:counts.missing_count,reason_counts:{...counts.reason_counts}})),blocks,
      binding:{source_digest:await shaBytes(bytes),source_sample_count:total,beats_digest:await digest(normalized),scope_digest:await digest(scope),method_digest:await digest(method),exclusions_digest:await digest(publicMasks),range_digest:await digest([start,end,chosen]),status:'mathematical_raw_source_and_basis_bound',source_kind:'pure_mathematical',runtime_canonicalization:'sorted-js-json-v1',implementation_digest:await digest(implementationSources())},
      review_status:'statistics_pending_physician_review',interpretation:{diagnosis_generated:false,sustained_depression_inferred:false,signal_quality_verified:false,sinus_origin_verified:false},
      simulation:{browser_computed:true,real_patient_inputs_read:false,clinical_validation:false,full_source_sample_zero_is_caller_contract:true}};
    if(options.source_digest!==undefined&&options.source_digest!==null&&options.source_digest!==result.binding.source_digest)fail('source_digest does not match actual full mathematical raw bytes');
    result.result_digest=await digest(result);return result;
  }
  function implementationSources(){return {schema:'actual-function-sources-and-constants-v1',constants:{RATE,BLOCK,MINIMUM,LEADS,BASELINE,ST,BASE_PROFILE},functions:[copy,fail,integer,finiteJSON,canonical,digest,shaBytes,median,mad,roundEven,roundDecimal,evenly,profile,strictRecords,rawSnapshot,readLeads,frameValues,spanOffsets,estimateJ,blockMeasurement,pyStrip,normalizeMasks,hits,maskStatus,unionSize,intersect,bump,sortedCounts,countsOf,mean,calculate,implementationSources].map(fn=>fn.toString())};}
  return Object.freeze({calculate,methodProfile:profile,schema_version:'stt-range-mean-v1',source_kind:'pure_mathematical'});
})();
