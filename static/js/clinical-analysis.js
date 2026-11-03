"use strict";
/* Deterministic complete-index counterpart of ecg_core/clinical_analysis.py. */
(() => {
  const quality=globalThis.ECGRRQuality||(typeof require==='function'?require('./rr-quality.js'):null);
  const categories=[['fastest','最快心率'],['slowest','最慢心率'],['S','房早事件'],['V','室早事件'],['pause','长 RR 候选'],['rr_candidate','自选 RR 候选'],['rate','心率异常'],['AF','房颤事件'],['ST','ST-T'],['other','其他事件']];
  const reportCategories=categories.flatMap(item=>item[0]==='pause'?[['rr_interval','RR 间期']]:item[0]==='rr_candidate'?[]:[item]);
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
  // Synchronous UTF-8 SHA-256 for stable record/group IDs, shared with the
  // Python ST record canonicalizer. This never substitutes for report signing.
  function sttCanonical(value){
    const compare=(a,b)=>{const left=Array.from(a,x=>x.codePointAt(0)),right=Array.from(b,x=>x.codePointAt(0));for(let i=0;i<Math.min(left.length,right.length);i++)if(left[i]!==right[i])return left[i]-right[i];return left.length-right.length;};
    function tree(v){
      if(Array.isArray(v))return ['array',v.map(tree)];
      if(v&&typeof v==='object')return ['object',Object.keys(v).sort(compare).map(key=>[key,tree(v[key])])];
      if(typeof v==='number'){
        if(!Number.isFinite(v))throw Error('ST-T依据含非有限数值');
        if(!Number.isSafeInteger(v)){const bytes=new DataView(new ArrayBuffer(8));bytes.setFloat64(0,v,false);return ['float64',Array.from(new Uint8Array(bytes.buffer),b=>b.toString(16).padStart(2,'0')).join('')];}
      }
      return v;
    }
    return JSON.stringify(tree(value));
  }
  function sttDigest(value){
    const bytes=new TextEncoder().encode(sttCanonical(value)),length=bytes.length,padded=(length+9+63)&~63,buffer=new Uint8Array(padded);buffer.set(bytes);buffer[length]=128;
    const data=new DataView(buffer.buffer);data.setUint32(padded-8,Math.floor(length/0x20000000));data.setUint32(padded-4,(length*8)>>>0);
    const constants=[0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2],hash=[0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19],words=new Uint32Array(64),rotr=(x,n)=>(x>>>n)|(x<<(32-n));
    for(let offset=0;offset<padded;offset+=64){for(let i=0;i<16;i++)words[i]=data.getUint32(offset+i*4);for(let i=16;i<64;i++){const a=words[i-15],b=words[i-2],s0=rotr(a,7)^rotr(a,18)^(a>>>3),s1=rotr(b,17)^rotr(b,19)^(b>>>10);words[i]=(words[i-16]+s0+words[i-7]+s1)>>>0;}
      let [a,b,c,d,e,f,g,h]=hash;for(let i=0;i<64;i++){const S1=rotr(e,6)^rotr(e,11)^rotr(e,25),ch=(e&f)^(~e&g),t1=(h+S1+ch+constants[i]+words[i])>>>0,S0=rotr(a,2)^rotr(a,13)^rotr(a,22),maj=(a&b)^(a&c)^(b&c),t2=(S0+maj)>>>0;h=g;g=f;f=e;e=(d+t1)>>>0;d=c;c=b;b=a;a=(t1+t2)>>>0;}[a,b,c,d,e,f,g,h].forEach((x,i)=>hash[i]=(hash[i]+x)>>>0);
    }
    return hash.map(x=>x.toString(16).padStart(8,'0')).join('');
  }
  const sttResults=['st_depression','st_elevation','t_change','nonspecific','no_change','artifact','indeterminate'],sttAbnormal=['st_depression','st_elevation','t_change','nonspecific'];
  function sttResult(d){if(sttResults.includes(d.result_code))return d.result_code;const text=String(d.finding||'');if(text.includes('未见'))return 'no_change';if(text.includes('伪差')||text.includes('体位'))return 'artifact';if(text.includes('无法'))return 'indeterminate';if(text.includes('压低'))return 'st_depression';if(text.includes('抬高'))return 'st_elevation';if(text.includes('T 波')||text.includes('T波')||d.stt_event_evidence?.kind==='t_wave_inversion')return 't_change';return d.status==='confirmed'?'nonspecific':'indeterminate';}
  function sttProtocol(raw={},extent='point'){
    if(!raw||typeof raw!=='object'||Array.isArray(raw))throw Error('ST-T测量协议须为对象');const ms=raw.measurement_ms??60,mode=raw.extent??extent,baseline=raw.baseline_method??'pre_qrs_stable';
    if(![0,60,80].includes(ms)||!['point','whole'].includes(mode)||!['pre_qrs_stable','manual_iso_point'].includes(baseline))throw Error('ST-T测量协议无效');
    return {method_version:'stt-hospital-review-v1',measurement_ms:ms,extent:mode,baseline_method:baseline,units:'source_device_units',calibration_verified:false};
  }
  function sttSavedProtocol(details,evidence){
    if(evidence.measurement_protocol&&typeof evidence.measurement_protocol==='object')return structuredClone(evidence.measurement_protocol);
    if(details.measurement_protocol&&typeof details.measurement_protocol==='object')return sttProtocol(details.measurement_protocol);
    const profile=details.range_statistics?.method_profile;if(!profile||!Number.isInteger(profile.measurement_ms)||![0,60,80].includes(profile.measurement_ms))return null;
    return {method_version:profile.id??null,measurement_ms:profile.measurement_ms,extent:'whole',baseline_method:profile.id==='raw-200hz-fixed16s-st-perbeat-mean-v1'?'pre_qrs_stable':null,units:profile.units??null,calibration_verified:profile.calibration_verified===true,range_profile:structuredClone(profile)};
  }
  function sttMetadata(a,basis=null){
    const d=a.details||{},code=sttResult(d),explicit=d.reviewed===true,bound=!!(d.review_scope||d.stt_event_evidence?.scope),reviewState=explicit||bound&&['confirmed','excluded'].includes(d.status)?'reviewed':'unreviewed',family=['st_depression','st_elevation'].includes(code)?'ST':code==='t_change'?'T':'NOTE',group=reviewState==='reviewed'&&sttAbnormal.includes(code)&&family!=='NOTE'?family:reviewState==='reviewed'?'ST_NOTE':'pending',first=a.sample_index,end=(d.end_sample??first)+1,evidence=d.stt_event_evidence||{},extent=d.review_extent??(Object.keys(evidence).length?'whole':'point'),eligible=reviewState==='reviewed',table=eligible&&['st_depression','st_elevation','t_change'].includes(code)&&extent==='whole'&&end-first>=12000&&!!Object.keys(evidence).length;
    return {schema_version:'stt-review-record-v1',record_id:'annotation:'+a.id,event_id:'annotation:'+a.id,annotation_id:a.id,record_version:d.record_version??1,review_state:reviewState,result_code:code,result_kind:family,report_group:group,status:d.status||'pending',review_extent:extent,range:{start_sample:first,end_sample:end,start_s:first/200,end_s:end/200,duration_s:(end-first)/200},basis_version:basis,measurement_protocol:sttSavedProtocol(d,evidence),point_measurement_protocol:d.measurement_protocol?sttProtocol(d.measurement_protocol):null,report_eligibility:{table,text:eligible,strip:eligible},report_use:{table:false,text:false,strip:false},source_scope:structuredClone(d.review_scope||evidence.scope||null),finding:d.finding??a.label??'',note:a.note||'',physician_note:d.physician_note??null,leads:structuredClone(d.review_leads||evidence.leads||(a.lead&&!['全部',''].includes(a.lead)?[a.lead]:[])),legacy:!explicit};
  }
  function sttDecorate(event,a,beatVersion){
    const d=a.details||{},scope=d.review_scope||d.stt_event_evidence?.scope||{},material=structuredClone([a.id,a.sample_index,d,a.lead||'',a.note||'',a.label||'']);
    for(const key of ['review_scope','stt_candidate_scope'])if(material[2][key]&&typeof material[2][key]==='object')delete material[2][key].analysis_revision;
    if(material[2].stt_event_evidence?.scope)delete material[2].stt_event_evidence.scope.analysis_revision;
    const basis=beatVersion+'-stt-record-v1-'+sttDigest(material).slice(0,24),receipt=sttMetadata(a,basis);
    if(Array.isArray(d.withdrawn_report_settings)&&d.withdrawn_report_settings.length)event.retained_settings=structuredClone(d.withdrawn_report_settings[0]);
    return Object.assign(event,{basis_version:basis,stt_review_state:receipt.review_state,stt_result_code:receipt.result_code,stt_result_kind:receipt.result_kind,stt_report_group:receipt.report_group,stt_record_version:receipt.record_version,stt_report_eligibility:receipt.report_eligibility,stt_review_receipt:receipt,stt_source_scope:scope,stt_continuous:receipt.report_eligibility.table,stt_physician_note:d.physician_note??a.note??'',diagnosis_status:receipt.review_state==='reviewed'&&sttAbnormal.includes(receipt.result_code)?'confirmed':'pending'});
  }
  function sttMarkStale(event){Object.assign(event,{diagnosis_status:'pending',stt_evidence_stale:true,stt_review_state:'stale',stt_report_group:'pending',stt_report_eligibility:{table:false,text:false,strip:false}});Object.assign(event.stt_review_receipt,{review_state:'stale',report_group:'pending',report_eligibility:event.stt_report_eligibility});return event;}
  function sttNormalizedUses(raw){if(!Array.isArray(raw)||raw.length>2000)throw Error('ST-T报告用途须为记录列表');const seen=new Set();return raw.map(row=>{if(!row||!['event_id','basis_version'].every(k=>typeof row[k]==='string'&&row[k])||['table','text','strip'].some(k=>k in row&&typeof row[k]!=='boolean')||seen.has(row.event_id))throw Error('ST-T报告用途字段无效或重复');seen.add(row.event_id);return {event_id:row.event_id,basis_version:row.basis_version,table:row.table??false,text:row.text??false,strip:row.strip??false};});}
  function sttUseFor(c,event){if('stt_report_use' in c)return sttNormalizedUses(c.stt_report_use).find(row=>row.event_id===event.event_id)||{event_id:event.event_id,basis_version:event.basis_version,table:false,text:false,strip:false};const pick=(c.selected_events||[]).find(s=>s.event_id===event.event_id),pages=c.included_pages||['summary','hourly','event_strips'];return {event_id:event.event_id,basis_version:pick?.basis_version||event.basis_version,table:!!pick&&pages.includes('st_events')&&!!event.stt_report_eligibility?.table,text:!!pick?.referenced_in_report,strip:!!pick&&pick.print_enabled!==false&&pages.includes('event_strips')};}
  function buildIndex(feed,templates=[],annotations=[],review={}){
    const rows=feed.beats,markers=feed.markers||[],opts=feed.document.settings;
    const bv=fingerprint(rows.concat(markers).map(r=>`${r.id}:${r.sample_index}:${r.class_code}`).join('|')+'|'+encode(Object.keys(opts).sort().map(k=>[k,opts[k]])));
    const findings=annotations.filter(a=>['ST','ST_REVIEW_NOTE','AT','VT','AF','AFL','STRIP'].includes(a.details?.kind));
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
        ranked.forEach((r,i)=>{make(key,name,`${name} ${Object.fromEntries(categories)[key]} ${Math.round(r.hr)} bpm`,[r]).candidate_rank=i+1;});
      }
    }
    pairs.forEach(([previous,r])=>{if(r.rr_ms>2500)Object.assign(make('pause','pause',`长 RR ${(r.rr_ms/1000).toFixed(3)} s`,[r]),{rr_start_sample:previous.sample_index,rr_end_sample:r.sample_index})});
    const definitions=[['rate','tachy','快心率',r=>rateRows.has(r)&&r.hr>=opts.tachy],['rate','brady','慢心率',r=>rateRows.has(r)&&r.hr<=opts.brady],['AF','AF','房颤',r=>['A','M'].includes(r.class_code)],['AF','AFL','房扑',r=>['C','H'].includes(r.class_code)]];
    for(const [cat,sub,label,predicate] of definitions){if(cat==='AF'&&annotations.some(a=>a.details?.rhythm_authoritative))continue;let i=0;while(i<rows.length){if(!predicate(rows[i])){i++;continue}let j=i+1;while(j<rows.length&&predicate(rows[j]))j++;const item=make(cat,sub,label,rows.slice(i,j));if(cat==='AF'){item.end_s=j<rows.length?rows[j].sample_index/200:feed.duration;item.rhythm_status='pending';item.diagnosis_status='pending';}i=j}}
    rows.concat(markers).forEach(r=>{if(!['N','S','V','A','M','C','H','X'].includes(r.class_code))make('other',r.class_code,r.name||r.class_code,[r])});
    findings.forEach(a=>{
      const d=a.details,rhythm=['AF','AFL'].includes(d.kind),stRecord=['ST','ST_REVIEW_NOTE'].includes(d.kind);if(!stRecord&&(d.status!=='confirmed'&&!rhythm||d.status==='excluded'))return;
      if(!annotations.some(x=>x.details?.rhythm_authoritative)&&rhythm&&d.status==='pending'&&findings.some(b=>b.details.kind===d.kind&&b.details.status==='confirmed'&&b.sample_index===a.sample_index&&b.details.end_sample===d.end_sample))return;
      const kind=d.kind,cat=rhythm?'AF':stRecord?'ST':kind==='AT'?'S':kind==='STRIP'?'other':'V',start=a.sample_index,end=d.end_sample??start,whole=stRecord||['AF','AFL','STRIP'].includes(kind),targets=rows.filter(r=>r.sample_index>=start&&r.sample_index<=end&&(whole||r.class_code===cat));
      const defaultLabel={ST:'ST 改变',ST_REVIEW_NOTE:'ST-T 复核记录',AF:'房颤',AFL:'房扑',AT:'房速',VT:'室速',STRIP:'人工图条'}[kind];
      const item=make(cat,stRecord?'ST':whole?kind:'tachycardia',d.finding||defaultLabel,targets,[{id:`a:${a.id}:start`,sample_index:start},{id:`a:${a.id}:end`,sample_index:end}],!whole,`annotation:${a.id}`);if(d.status!=='confirmed')item.diagnosis_status='pending';item.lead=a.lead||'全部';item.note=a.note||'';
      if(stRecord&&d.range_statistics&&typeof d.range_statistics==='object'&&!Array.isArray(d.range_statistics)){item.range_statistics=JSON.parse(JSON.stringify(d.range_statistics));item.end_s=(end+1)/200;}
      if(stRecord){item.end_s=(end+1)/200;item.diagnosis_status=d.status==='confirmed'?'confirmed':'pending';if(d.stt_event_evidence&&typeof d.stt_event_evidence==='object'&&!Array.isArray(d.stt_event_evidence))item.stt_event_evidence=JSON.parse(JSON.stringify(d.stt_event_evidence));sttDecorate(item,a,bv);}
      if(cat==='AF'){item.end_s=(end+1)/200;item.rhythm_status=d.status||'pending';} // Keep episode review separate from workflow approval.
    });
    events.filter(e=>e.category==='AF').forEach(e=>{const annotation=e.event_id.startsWith('annotation:')?e.event_id.slice(11):null;e.rhythm_episode_id=annotation===null?'beat-'+e.start_sample:annotation.startsWith('af:')?annotation.slice(3):'source-'+annotation;});
    // Selected rhythm strips depend on their own episode, not other AF/AFL edits.
    events.filter(e=>e.category==='AF').forEach(e=>{e.basis_version=bv+'-'+fingerprint(encode([e.event_id,e.start_sample,e.end_sample,e.end_s,e.subtype,e.rhythm_status,e.label,e.lead||'',e.note||'']))+'-episode-local-v1-episode-status-v2-inclusive-end-v1';});
    events.sort((a,b)=>a.start_sample-b.start_sample||(a.event_id<b.event_id?-1:1));
    return {quality_control:{artifact_count:rows.concat(markers).filter(r=>r.class_code==='X').length,artifact_samples:rows.concat(markers).filter(r=>r.class_code==='X').map(r=>r.sample_index),role:'quality_control_only'},events,rows:rows.concat(markers),templates,basis_versions:basis,data_version:bv+'-'+av+'-rr-quality-v3-'+periodicVersion+'-af-end-v1-status-v2-no-artifact-v1',beat_version:bv,duration_s:feed.duration};
  }
  function rrIntervalGroups(index){
    const rrEvents=index.events.filter(e=>['pause','rr_candidate'].includes(e.category));if(!rrEvents.length)return [];
    const report=globalThis.ECGReportEngine||(typeof require==='function'?require('./report-engine.js'):null),pairs=new Map(report.intervalPairs(index.rows,index.duration_s).map(pair=>[pair[1].sample_index,pair])),groups=new Map();
    for(const e of rrEvents){
      const pair=pairs.get(e.start_sample),p=e.candidate_context;
      if(!pair||e.rr_ms!==pair[1].rr_ms||e.category==='pause'&&pair[1].rr_ms<=2500||e.category==='rr_candidate'&&(pair[0].sample_index!==p?.rr_start_sample||pair[1].sample_index!==p?.rr_end_sample))continue;
      const key=`rr-pair-v1:${index.beat_version}:${pair[0].sample_index}:${pair[1].sample_index}`;
      if(!groups.has(key))groups.set(key,[]);groups.get(key).push(e);
    }
    return [...groups].map(([key,events])=>{
      events.sort((a,b)=>(a.category==='rr_candidate'?0:1)-(b.category==='rr_candidate'?0:1)||(a.event_id<b.event_id?-1:a.event_id>b.event_id?1:0));
      const aliases=events.map(e=>({event_id:e.event_id,basis_version:e.basis_version,category:e.category}));
      return {...events[0],rr_semantic_key:key,rr_alias_event_ids:aliases.map(a=>a.event_id),rr_aliases:aliases,rr_sources:['auto','manual'].filter(source=>events.some(e=>e.category===(source==='auto'?'pause':'rr_candidate')))};
    });
  }
  function normalizeRRSelections(index,entries){const lookup=new Map(index.events.map(e=>[e.event_id,e])),keys=new Map(rrIntervalGroups(index).flatMap(e=>e.rr_alias_event_ids.map(id=>[id,e.rr_semantic_key]))),seen=new Set();return entries.filter(entry=>{const event=lookup.get(entry.event_id),key=event?.basis_version===entry.basis_version?keys.get(entry.event_id):null;if(!key)return true;if(seen.has(key))return false;seen.add(key);return true;});}
  function queryIndex(index,params={},occurrences=false){
    if(params instanceof URLSearchParams)params=Object.fromEntries(params);
    const category=params.category||'all',mode=({'NPN':'nnp','NNP':'nnp','NPP':'npp','三联律(NPN)':'nnp','三联律(NNP)':'nnp','三联律(NPP)':'npp'}[params.mode]||params.mode||'all'),code=params.class_code||'S',templateId=String(params.template_id||'all'),offset=Math.max(0,Number(params.offset)||0),limit=Math.max(1,Math.min(200,Number(params.limit)||100));
    const template=index.templates.find(t=>String(t.id)===templateId);if(templateId!=='all'&&!template)throw Error('模板不存在，请刷新');const samples=template?new Set(template.sample_indices):null,fast=(params.fast_slow_mode||'rr').toUpperCase(),ids=params.ids?new Set(params.ids.split('|')):null;
    const rrGroups=rrIntervalGroups(index),rrSource=params.rr_source===undefined?'all':params.rr_source;if(!['all','auto','manual'].includes(rrSource))throw Error('无效的 RR 来源筛选');
    const rawOccurrences=occurrences&&mode==='all',timeOf=rawOccurrences?r=>r.sample_index/200:e=>e.time_s;
    let items;
    // Hold row references until pagination; do not construct 100k display cards.
    if(rawOccurrences)items=index.rows.filter(r=>(code==='all'||(code==='other'?!['N','S','V'].includes(r.class_code):r.class_code===code))&&(!samples||samples.has(r.sample_index)));
    else {items=index.events.filter(e=>ids?ids.has(e.event_id):(occurrences?e.category===(['A','M','C','H'].includes(code)?'AF':code):category==='all'||e.category===category)&&(mode!=='all'?e.subtype===mode:!e.pattern_only)&&(!['fastest','slowest'].includes(e.category)||fast==='BOTH'||e.subtype===fast));if(samples)items=items.filter(e=>e.target_samples.some(s=>samples.has(s)))}
    const rrAliasGroups=new Map(rrGroups.flatMap(e=>e.rr_alias_event_ids.map(id=>[id,e])));
    if(!occurrences&&!ids&&category==='rr_interval')items=rrGroups.filter(e=>rrSource==='all'||e.rr_sources.includes(rrSource));
    else if(!occurrences)items=items.map(e=>{const group=rrAliasGroups.get(e.event_id);return group?{...e,rr_semantic_key:group.rr_semantic_key,rr_alias_event_ids:group.rr_alias_event_ids,rr_aliases:group.rr_aliases,rr_sources:group.rr_sources}:e;});
    const stt_group=params.stt_group||'all';if(!['all','ST','T','ST_NOTE','pending'].includes(stt_group))throw Error('ST-T复核分组无效');const stt_counts=Object.fromEntries(['ST','T','ST_NOTE','pending'].map(key=>[key,index.events.filter(e=>e.category==='ST'&&e.stt_report_group===key).length]));if(category==='ST'&&!ids&&stt_group!=='all')items=items.filter(e=>e.stt_report_group===stt_group);
    const pause_band=params.pause_band||'all';
    if(!['all','over3','2.5to3','b0','b1','b2'].includes(pause_band))throw Error('无效的长 RR 筛选范围');
    const pauses=index.events.filter(e=>e.category==='pause'),pause_counts={all:pauses.length,over3:pauses.filter(e=>e.rr_ms>3000).length,'2.5to3':pauses.filter(e=>e.rr_ms<=3000).length};
    const pause_distribution=quality.rrDistribution(index.rows,index.duration_s,params.pause_edges_ms);
    if(!occurrences&&category==='pause'&&!ids&&pause_band!=='all'){
      if(pause_band.startsWith('b')){const bucket=pause_distribution.bins[Number(pause_band[1])];items=items.filter(e=>e.rr_ms>=bucket.lower_ms&&(bucket.upper_ms===null||e.rr_ms<bucket.upper_ms));}
      else items=items.filter(e=>pause_band==='over3'?e.rr_ms>3000:e.rr_ms<=3000);
    }
    const rateCandidates=!occurrences&&['fastest','slowest'].includes(category)&&!ids,sortOrder=['rr_candidate','rr_interval'].includes(category)?(params.sort||'hr_asc'):rateCandidates?(params.sort||'hr_desc'):'time';
    const rawSpacing=params.candidate_spacing_s===undefined?0:params.candidate_spacing_s;
    if(![0,7,30,60,'0','7','30','60'].includes(rawSpacing))throw Error('候选定位点间隔须为 0、7、30 或 60 秒');
    const candidate_spacing_s=rateCandidates?Number(rawSpacing):0;
    if(!['hr_desc','hr_asc','time'].includes(sortOrder))throw Error('无效的候选排序方式');
    if(rawOccurrences)items.sort((a,b)=>a.sample_index-b.sample_index||(a.id<b.id?-1:a.id>b.id?1:0));
    else items.sort((a,b)=>(sortOrder==='time'?0:(sortOrder==='hr_desc'?1:-1)*(a.rr_ms-b.rr_ms))||a.start_sample-b.start_sample||(a.event_id<b.event_id?-1:1));
    const counts=Object.fromEntries(categories.map(([key])=>[key,index.events.filter(e=>!e.pattern_only&&e.category===key&&(!['fastest','slowest'].includes(key)||fast==='BOTH'||e.subtype===fast)).length])),subtypes={},beats={};
    counts.rr_interval=rrGroups.length;const rr_source_counts={all:rrGroups.length,auto:rrGroups.filter(e=>e.rr_sources.includes('auto')).length,manual:rrGroups.filter(e=>e.rr_sources.includes('manual')).length};
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
    const confirmedIds=new Set(index.events.filter(e=>e.diagnosis_status==='confirmed').map(e=>e.event_id)),confirmedRR=rrGroups.filter(e=>e.rr_alias_event_ids.some(id=>confirmedIds.has(id)));confirmed_category_counts.rr_interval=confirmedRR.length;confirmed_beat_counts.rr_interval=new Set(confirmedRR.flatMap(e=>e.target_samples)).size;
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
      const target=items.findIndex(e=>e.event_id===params.locate_event||e.rr_alias_event_ids?.includes(params.locate_event));
      if(target<0)throw Error('目标事件已失效或不在当前筛选内，请重新选择；未跳转到其他事件');
      if(params.locate_basis!==(items[target].rr_aliases?.find(a=>a.event_id===params.locate_event)?.basis_version||items[target].basis_version))throw Error('目标事件依据已变化，请重新选择');
      pageOffset=Math.floor(target/limit)*limit;focus.focus_index=target;
    }
    let page=items.slice(pageOffset,pageOffset+limit);
    if(rawOccurrences)page=page.map(r=>({event_id:'beat:'+r.id,class_code:r.class_code,category:code,subtype:'beat',label:r.name||r.class_code,sample_index:r.sample_index,start_sample:r.sample_index,end_sample:r.sample_index,time_s:r.sample_index/200,end_s:r.sample_index/200,target_samples:[r.sample_index],beat_count:1,hr:r.hr??null,rr_ms:r.rr_ms??null,basis_version:index.beat_version,templates:template?[{id:String(template.id),name:template.name}]:[],diagnosis_status:r.source_sample!==r.sample_index||r.class_code!==({1:'N',2:'S',3:'V',34:'X'}[r.source_group]||'OTHER')?'edited':'pending'}));
    return {...focus,stt_group,stt_counts,rr_source:rrSource,rr_source_counts,candidate_spacing_s,candidate_unspaced_total,candidate_hidden_count,time_bins,time_filter,unfiltered_total,pause_counts,pause_distribution,pause_band,sort_order:sortOrder,candidate_limit:rateCandidates?200:null,confirmed_category_counts,confirmed_beat_counts,time_counts,items:page,total:items.length,offset:pageOffset,limit,category_counts:counts,subtype_counts:subtypes,beat_counts:beats,basis_versions:index.basis_versions,data_version:index.data_version};
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
  function evidenceSelection(s,e){const p=(globalThis.ECGReportEngine||(typeof require==='function'?require('./report-engine.js'):null)).settings(s);return {leads:p.leads,duration_s:p.duration_s,range_start_s:p.range_start_s??null,range_end_s:p.range_end_s??null,caption:s.caption||e.label||'',notes:s.notes||''};}
  function evidenceConfirmed(s,e){const own=evidenceSelection(s,e),review=e?.evidence_review;return review?.status==='confirmed'&&review.presentations.some(p=>Object.keys(own).every(k=>JSON.stringify(p.selection?.[k])===JSON.stringify(own[k])));}
  function reportUsed(c,s,e){const pages=c.page_selection_version===1?c.included_pages||[]:['summary','hourly','event_strips'];if(e?.category==='ST'){const use=sttUseFor(c,e);return use.strip&&pages.includes('event_strips')&&s.print_enabled!==false;}return s.referenced_in_report===true||pages.includes('event_strips')&&s.print_enabled!==false&&(!e||!['fastest','slowest'].includes(e.category)||c.fast_slow_mode==='both'||e.subtype===(c.fast_slow_mode||'rr').toUpperCase());}
  function normalizeReportSelections(index,entries){
    const engine=globalThis.ECGReportEngine||(typeof require==='function'?require('./report-engine.js'):null),lookup=new Map(index.events.map(e=>[e.event_id,e])),seen=new Set(),ids=new Map();
    const identified=entries.filter(s=>{engine.stripIdentity(s);const key=engine.stripKey(s);if(ids.has(key)){if(ids.get(key)!==s.event_id)throw Error('图条标识不能用于不同事件');return false;}ids.set(key,s.event_id);return true;});
    return normalizeRRSelections(index,identified).filter(s=>{const e=lookup.get(s.event_id);let key='event|'+s.event_id;if(e?.category==='AF'){if(e.basis_version!==s.basis_version)return true;let range;try{range=engine.resolve(index,e,s);}catch(_){return true;}key=['af',e.event_id,e.basis_version,Math.round(range.start_s*200),Math.round(range.end_s*200)].join('|');}if(seen.has(key))return false;seen.add(key);return true;});
  }
  function validateReport(index,composition,review,approving=false){
    if('include_hrv' in composition&&typeof composition.include_hrv!=='boolean')throw Error('HRV 入报选项须为布尔值');
    const retained=normalizeReportSelections(index,composition.selected_events||[]);
    for(const entry of retained){if('range_start_s' in entry||'range_end_s' in entry){const event=index.events.find(e=>e.event_id===entry.event_id);if(event&&event.basis_version===entry.basis_version&&reportUsed(composition,entry,event))ECGReportEngine.resolve(index,event,entry)}}
    const lookup=new Map(index.events.map(e=>[e.event_id,e])),selected=[],rrGroups=rrIntervalGroups(index),rrKeys=new Map(rrGroups.flatMap(e=>e.rr_alias_event_ids.map(id=>[id,e.rr_semantic_key]))),seenRR=new Set();
    for(const [number,entry] of retained.entries()){const e=lookup.get(entry.event_id),used=reportUsed(composition,entry,e);if(entry.event_id.startsWith('other:X:')||(e?.category==='other'&&e.subtype==='X')){if(approving&&used)throw Error('伪差仅用于质控，请移除历史伪差图条后再审核');continue}if(!e||e.basis_version!==entry.basis_version){if(approving&&used)throw Error(`第 ${number+1} 条图条依据已变化（失效），请重新核对或移出本次报告`);continue}const rrKey=rrKeys.get(e.event_id);if(rrKey&&seenRR.has(rrKey))continue;if(rrKey)seenRR.add(rrKey);if(approving&&used&&e.category==='AF'&&e.rhythm_status!=='confirmed')throw Error('所选房颤／房扑片段尚未确认；请在报告候选区确认本段，或从报告中移除该图条。');if(approving&&used){if(e.evidence_only){if(!evidenceConfirmed(entry,e))throw Error(`第 ${number+1} 条人工图条待核对，请在报告中“确认本条”或移出本次报告`);}else if(e.category==='ST'?e.stt_review_state!=='reviewed':e.diagnosis_status!=='confirmed')throw Error('请先完成本条复核');if(['pause','rr_candidate'].includes(e.category)&&(entry.caption||e.label).includes('最长')&&e.rr_ms!==ECGReportEngine.intervalPairs(index.rows,index.duration_s).reduce((m,[,b])=>Math.max(m,b.rr_ms),-Infinity))throw Error('本条不是当前可分析记录的最长 RR，请核对图注');}selected.push({...e,caption:entry.caption||e.label,...(globalThis.ECGReportEngine?{...ECGReportEngine.settings(entry),...ECGReportEngine.stripIdentity(entry)}:{}),print_enabled:entry.print_enabled!==false,referenced_in_report:entry.referenced_in_report===true,notes:entry.notes||''})}
    if(approving)for(const use of sttNormalizedUses(composition.stt_report_use||[])){const pages=composition.included_pages||['summary','hourly','event_strips'],actual=use.text||use.table&&pages.includes('st_events')||use.strip&&pages.includes('event_strips');if(!actual)continue;const e=lookup.get(use.event_id);if(!e||e.basis_version!==use.basis_version||e.category!=='ST'||e.stt_review_state!=='reviewed')throw Error('采用的ST-T复核依据已变化或尚未完成');if(['table','text','strip'].some(k=>use[k]&&!e.stt_report_eligibility?.[k]))throw Error('该ST-T复核不支持所选用途');if(use.strip&&pages.includes('event_strips')&&!retained.some(s=>s.event_id===use.event_id&&s.basis_version===use.basis_version&&s.print_enabled!==false))throw Error('ST-T代表图条尚未选择');}
    if(approving&&(composition.diagnosis_blocks||[]).some(b=>b.needs_review))throw Error('请核对保留的人工诊断文字');
    return selected;
  }
  const api={sttDigest,sttCanonical,sttResult,sttProtocol,sttSavedProtocol,sttMetadata,sttDecorate,sttMarkStale,sttNormalizedUses,sttUseFor,categories,reportCategories,rrIntervalGroups,normalizeRRSelections,normalizeReportSelections,patterns,buildIndex,queryIndex,hrvWindows,validateReport,fingerprint,evidenceSelection,evidenceConfirmed,reportUsed};globalThis.ECGClinicalAnalysis=api;if(typeof module!=='undefined')module.exports=api;
})();
