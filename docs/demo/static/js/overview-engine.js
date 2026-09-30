"use strict";
/* Pure measurement/review functions shared by the workstation and static Demo. */
((root)=>{
  const quality=root.ECGRRQuality||(typeof require==='function'?require('./rr-quality.js'):null);
  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
  const code=r=>r.class_code||({1:'N',2:'S',3:'V',34:'X'})[r.group]||'OTHER';
  const decode=data=>{
    const rows=data.rows.map(([sample,rr,type])=>({sample_index:sample,time_s:sample/200,rr_ms:rr,class_code:type,hr:Number.isFinite(rr)&&rr>0?60000/rr:null}));
    const measured=new Set(quality.validRRRows(rows,data.duration_s??Infinity));
    return rows.map(r=>({...r,rr_valid:measured.has(r)}));
  };
  const valid=r=>r.rr_valid!==false&&!['X','O','Y','T'].includes(code(r))&&Number.isFinite(r.rr_ms)&&r.rr_ms>0;
  function pairs(rows,mode='rr',start=0){
    const out=[];
    for(let i=1;i<rows.length-1;i++){
      const a=rows[i-1],b=rows[i],c=rows[i+1];
      if(!valid(b)||!valid(c)||code(a)==='X')continue;
      if(mode==='n'&&code(b)!=='N'||mode==='s'&&code(b)!=='S'||mode==='v'&&code(b)!=='V'||mode==='nn'&&![a,b,c].every(x=>code(x)==='N')||mode==='hour'&&(b.time_s<start||b.time_s>=start+3600))continue;
      out.push({...b,x:b.rr_ms,y:c.rr_ms});
    }return out;
  }
  function histogram(rows,ratio=false){
    const step=ratio?2.5:25,max=ratio?300:2600,bins=Array.from({length:Math.round(max/step)+1},(_,i)=>({start:i*step,end:(i+1)*step,count:0,samples:[]}));
    for(let i=1;i<rows.length;i++){
      const r=rows[i],previous=rows[i-1];if(!valid(r)||ratio&&!valid(previous))continue;
      const value=ratio?r.rr_ms/previous.rr_ms*100:r.rr_ms,index=clamp(Math.floor(value/step),0,bins.length-1);
      bins[index].count++;bins[index].samples.push(r.sample_index);
    }return {bins,step,max: max+step,ratio};
  }
  function stats(rows,pause=2.5,duration=Infinity){
    const inRecord=rows.filter(r=>Number.isFinite(r.sample_index)&&r.sample_index>=0&&r.sample_index/200<duration&&!['O','Y','T'].includes(code(r)));
    const counts={N:0,S:0,V:0,X:0},beats=inRecord.filter(r=>code(r)!=='X'),rr=quality.validRRRows(rows,duration);
    inRecord.forEach(r=>counts[code(r)]=(counts[code(r)]||0)+1);
    return {total:inRecord.length,valid:beats.length,counts,rr_interval_count:rr.length,pauses:rr.filter(r=>r.rr_ms>2500).length,pause_over3:rr.filter(r=>r.rr_ms>3000).length,alert_pauses:rr.filter(r=>r.rr_ms>=pause*1000).length};
  }
  function cut(episodes,start,end){
    return episodes.flatMap(x=>{
      if(x.end_s<=start||x.start_s>=end)return [{...x}];
      // Fresh bounded IDs survive repeated cuts of disjoint scatter selections.
      const out=[];if(x.start_s<start)out.push({...x,id:crypto.randomUUID(),end_s:start});if(x.end_s>end)out.push({...x,id:crypto.randomUUID(),start_s:end});return out;
    });
  }
  function validateDocument(value,duration){
    if(!value||!Array.isArray(value.episodes)||value.episodes.length>5000)throw Error('房颤片段格式错误');
    const seen=new Set();
    const episodes=value.episodes.map(x=>{
      if(!x||typeof x.id!=='string'||!x.id.length||x.id.length>100||seen.has(x.id))throw Error('片段标识必须唯一');seen.add(x.id);
      if(![x.start_s,x.end_s].every(n=>typeof n==='number'&&Number.isFinite(n))||x.start_s<0||x.start_s>=x.end_s||x.end_s>duration)throw Error('片段边界超出记录范围');
      if(!['AF','AFL'].includes(x.kind)||!['pending','confirmed','excluded'].includes(x.status))throw Error('片段类型或复核状态错误');
      return {...x,source:String(x.source||'manual').slice(0,80),note:String(x.note||'').slice(0,1000)};
    }).sort((a,b)=>a.start_s-b.start_s||a.end_s-b.end_s);
    const confirmed=episodes.filter(x=>x.status==='confirmed');for(let i=1;i<confirmed.length;i++)if(confirmed[i].start_s<confirmed[i-1].end_s)throw Error('已确认片段不能重叠，请先调整边界');
    const bookmarks={...value.bookmarks};for(const [key,time] of Object.entries(bookmarks))if(!['fastest','slowest','fastest_nn','slowest_nn'].includes(key)||typeof time!=='number'||!Number.isFinite(time)||time<0||time>=duration)throw Error('心率书签无效');
    return {episodes,bookmarks};
  }
  function annotations(document,stamp=''){
    // Validated times are milliseconds; avoid ceil() on an inexact sample product.
    return document.episodes.map(x=>({id:'af:'+x.id,sample_index:Math.round(x.start_s*200),lead:'全部',category:'note',label:(x.kind==='AF'?'房颤':'房扑')+' · '+({confirmed:'医生确认',excluded:'已排除',pending:'待复核'})[x.status],note:x.note||'',created_by:'房颤复核',created_at:stamp,details:{kind:x.kind,status:x.status,end_sample:Math.max(Math.round(x.start_s*200),Math.ceil(Math.round(x.end_s*1000)/5)-1),finding:'房颤/房扑片段复核'}})).concat({id:'rhythm-control',sample_index:0,label:'',internal:true,details:{rhythm_authoritative:true}});
  }
  function initialEpisodes(rows,items,duration){
    const episodes=items.filter(x=>['AF','AFL'].includes(x.details?.kind)).map(x=>({id:'source-'+x.id,start_s:x.sample_index/200,end_s:Math.min(duration,((x.details.end_sample??x.sample_index)+1)/200),kind:x.details.kind,status:x.details.status||'pending',source:'source-annotation',note:x.note||''}));
    let run=null;for(const r of rows.concat({class_code:'',time_s:duration})){
      const kind=['A','M'].includes(code(r))?'AF':['C','H'].includes(code(r))?'AFL':null;
      if(run&&kind!==run.kind){run.end_s=r.time_s;if(run.end_s>run.start_s)episodes.push(run);run=null}
      if(kind&&!run)run={id:'beat-'+r.sample_index,start_s:r.time_s,end_s:r.time_s,kind,status:'pending',source:'beat-rhythm',note:'逐搏节律标记，须核对片段边界'};
    }return {episodes,bookmarks:{}};
  }
  function screenAFResult(rows,duration,start=0,end=duration){
    // RR-only engineering screen, not a P-wave or AFL detector. The canonical
    // clock is the original sample index; display-relative time_s is not input.
    if(![duration,start,end].every(Number.isFinite)||duration<=0||start<0||end<=start||end>duration)throw Error('RR 筛查时间范围无效');
    const qrs=quality.qrsRows(rows),mask=quality.intervalMask(qrs);
    const windows=Array.from({length:Math.ceil((end-start)/30)},(_,i)=>({start_s:start+i*30,end_s:Math.min(end,start+(i+1)*30),rows:[]}));
    qrs.forEach((r,index)=>{const time=r.sample_index/200;if(!Number.isFinite(time)||time<start||time>=end)return;
      windows[Math.floor((time-start)/30)].rows.push({r,index});});
    const episodes=[];let run=null;
    for(const window of windows){
      const all=window.rows,good=all.filter(({r,index})=>mask[index]&&r.rr_valid!==false&&code(r)==='N'&&code(qrs[index-1])==='N'&&r.rr_ms>=300&&r.rr_ms<=2000&&qrs[index-1].sample_index/200>=window.start_s);
      const coverage=good.reduce((sum,{r})=>sum+r.rr_ms/1000,0);
      const reason=window.end_s-window.start_s<30?'incomplete_window':good.length<20?'insufficient_intervals':good.length/Math.max(1,all.length)<.9?'low_quality':coverage<25?'insufficient_coverage':null;
      let cv=null,rmssd=null,turns=null,pairs=0,triples=0;
      if(!reason){const mean=good.reduce((sum,{r})=>sum+r.rr_ms,0)/good.length;
        cv=Math.sqrt(good.reduce((sum,{r})=>sum+(r.rr_ms-mean)**2,0)/good.length)/mean;
        let squared=0,turnCount=0;
        for(let i=1;i<good.length;i++){
          const a=good[i-1],b=good[i];if(b.index!==a.index+1)continue;
          squared+=(b.r.rr_ms-a.r.rr_ms)**2;pairs++;
          if(i>=2&&a.index===good[i-2].index+1){triples++;if((a.r.rr_ms-good[i-2].r.rr_ms)*(b.r.rr_ms-a.r.rr_ms)<0)turnCount++;}
        }
        rmssd=pairs?Math.sqrt(squared/pairs)/mean:null;turns=triples?turnCount/triples:null;
      }
      const candidate=!reason&&cv>=.12&&rmssd!==null&&rmssd>=.14&&turns!==null&&turns>=.45&&turns<=.85;
      delete window.rows;Object.assign(window,{total_intervals:all.length,valid_intervals:good.length,coverage_s:coverage,reason,evaluated:!reason,cv,normalized_rmssd:rmssd,turning_ratio:turns,pair_count:pairs,triple_count:triples,candidate});
      if(candidate){if(!run){run={id:'rr-'+window.start_s,start_s:window.start_s,end_s:window.end_s,kind:'AF',status:'pending',source:'rr-irregularity-v2',note:'30 秒 RR 工程筛查：校验采样间距与连续有效 N-N；CV≥0.12、归一化 RMSSD≥0.14、连续转折率 0.45–0.85；未分析 P 波，须排除伪差/早搏'};episodes.push(run)}else run.end_s=window.end_s;}else run=null;
    }
    return {episodes,windows,evaluated_windows:windows.filter(w=>w.evaluated).length,skipped_windows:windows.filter(w=>!w.evaluated).length};
  }
  const screenAF=(rows,duration)=>screenAFResult(rows,duration).episodes;
  function planAFRescreen(rows,duration,document,start=0,end=duration){
    const result=screenAFResult(rows,duration,start,end),assessed=[];
    // Collapse adjacent evaluated windows before cutting long saved episodes.
    for(const w of result.windows){if(!w.evaluated)continue;if(assessed.length&&assessed.at(-1).end_s===w.start_s)assessed.at(-1).end_s=w.end_s;else assessed.push({start_s:w.start_s,end_s:w.end_s});}
    // Reanalysis cannot reverse a doctor's confirmed/excluded decision, nor
    // erase evidence in windows this run could not assess. Only pending output
    // of the explicitly known algorithm versions is replaceable.
    const preserved=document.episodes.flatMap(x=>{
      if(x.status!=='pending'||!['rr-irregularity-v1','rr-irregularity-v2'].includes(x.source))return [{...x}];
      let parts=[{...x}];for(const w of assessed)parts=cut(parts,w.start_s,w.end_s);return parts;
    });
    const candidates=result.episodes.flatMap(x=>{let parts=[{...x,id:crypto.randomUUID()}];for(const y of preserved)parts=cut(parts,y.start_s,y.end_s);return parts;});
    return {...result,candidates,document:{...document,episodes:preserved.concat(candidates)}};
  }
  function densitySamples(source,payload={}){
    const allowed=new Set(source),checked=name=>{const values=Object.hasOwn(payload,name)?payload[name]:[];
      if(!Array.isArray(values)||values.length>250000||values.some(s=>!Number.isInteger(s)||!allowed.has(s)))throw Error('密度图分组包含无效或已变化的心搏，请重新加载');
      if(new Set(values).size!==values.length)throw Error('密度图分组心搏不能重复');return new Set(values)};
    const included=Object.hasOwn(payload,'samples')?checked('samples'):allowed,excluded=checked('exclude_samples');
    return source.filter(s=>included.has(s)&&!excluded.has(s));
  }
  async function density(samples,count,read,lead,gate,amplitudeLimit=null){
    if(!['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6'].includes(lead))throw Error('不支持的密度图导联');
    if(amplitudeLimit!==null&&(!Number.isFinite(amplitudeLimit)||amplitudeLimit<1||amplitudeLimit>1e7))throw Error('密度图幅度范围错误');
    const positions=samples.filter(s=>s>=200&&s<count-200),width=200,height=128,bins=new Uint32Array(width*height),magnitudes=[];
    const baseline=s=>{let v=0;for(let i=-40;i< -20;i+=2)v+=read(s+i,lead);return v/10};
    const stride=Math.max(1,Math.ceil(positions.length/1000));for(let i=0;i<positions.length;i+=stride){const s=positions[i],zero=baseline(s);for(let o=-200;o<200;o+=8)magnitudes.push(Math.abs(read(s+o,lead)-zero))}
    magnitudes.sort((a,b)=>a-b);const limit=Math.round((amplitudeLimit??Math.max(100,magnitudes.length?magnitudes[Math.min(magnitudes.length-1,Math.floor(magnitudes.length*.995))]*1.15:100))*1000)/1000;let clipped=0;const selected=[];
    for(let i=0;i<positions.length;i++){
      const s=positions[i],zero=baseline(s);let matched=false;
      for(let x=0;x<200;x++){const offset=x*2-200,amp=read(s+offset,lead)-zero,y=Math.floor((limit-amp)/(2*limit)*height);if(y<0||y>=height){clipped++;continue}bins[y*width+x]++;if(gate&&offset/200>=gate[0]&&offset/200<=gate[1]&&amp>=gate[2]&&amp<=gate[3])matched=true}
      if(matched)selected.push(s);if(i%2000===1999)await new Promise(resolve=>setTimeout(resolve,0));
    }
    return {width,height,bins:Array.from(bins),total:samples.length,included:positions.length,skipped_edges:samples.length-positions.length,clipped_points:clipped,lead,x_min_s:-1,x_max_s:1,amplitude_limit:limit,units:'device_unit',unit_label:'设备单位',calibration_verified:false,sample_indices:selected,population_samples:[...samples],method:'R 对齐 · 全集合计数 · 10 ms 栅格 · 去固定基线 · 无逐搏增益归一化'};
  }
  const api={rhythmSummary:quality.rhythmSummary,clamp,code,valid,decode,pairs,histogram,stats,cut,validateDocument,annotations,initialEpisodes,screenAF,screenAFResult,planAFRescreen,density,densitySamples};
  root.ECGOverviewEngine=api;if(typeof module!=='undefined')module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
