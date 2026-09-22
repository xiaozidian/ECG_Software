"use strict";
/* Pure measurement/review functions shared by the workstation and static Demo. */
((root)=>{
  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
  const code=r=>r.class_code||({1:'N',2:'S',3:'V',34:'X'})[r.group]||'OTHER';
  const decode=data=>data.rows.map(([sample,rr,type])=>({sample_index:sample,time_s:sample/200,rr_ms:rr,class_code:type,hr:rr>0?60000/rr:null}));
  const valid=r=>code(r)!=='X'&&r.rr_ms>0;
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
  function stats(rows,pause=2.5){
    const counts={N:0,S:0,V:0,X:0},beats=rows.filter(r=>code(r)!=='X');
    rows.forEach(r=>counts[code(r)]=(counts[code(r)]||0)+1);
    return {total:rows.length,valid:beats.length,counts,pauses:beats.filter(r=>r.rr_ms>=pause*1000).length};
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
    return document.episodes.map(x=>({id:'af:'+x.id,sample_index:Math.round(x.start_s*200),lead:'全部',category:'note',label:(x.kind==='AF'?'房颤':'房扑')+' · '+({confirmed:'医生确认',excluded:'已排除',pending:'待复核'})[x.status],note:x.note||'',created_by:'房颤复核',created_at:stamp,details:{kind:x.kind,status:x.status,end_sample:Math.max(Math.round(x.start_s*200),Math.ceil(x.end_s*200)-1),finding:'房颤/房扑片段复核'}})).concat({id:'rhythm-control',sample_index:0,label:'',internal:true,details:{rhythm_authoritative:true}});
  }
  function initialEpisodes(rows,items,duration){
    const episodes=items.filter(x=>['AF','AFL'].includes(x.details?.kind)).map(x=>({id:'source-'+x.id,start_s:x.sample_index/200,end_s:Math.min(duration,((x.details.end_sample??x.sample_index)+1)/200),kind:x.details.kind,status:x.details.status||'pending',source:'source-annotation',note:x.note||''}));
    let run=null;for(const r of rows.concat({class_code:'',time_s:duration})){
      const kind=['A','M'].includes(code(r))?'AF':['C','H'].includes(code(r))?'AFL':null;
      if(run&&kind!==run.kind){run.end_s=r.time_s;if(run.end_s>run.start_s)episodes.push(run);run=null}
      if(kind&&!run)run={id:'beat-'+r.sample_index,start_s:r.time_s,end_s:r.time_s,kind,status:'pending',source:'beat-rhythm',note:'逐搏节律标记，须核对片段边界'};
    }return {episodes,bookmarks:{}};
  }
  function screenAF(rows,duration){
    // Transparent RR-only research screen. NO P-wave analysis and NO AFL detector.
    // Non-overlapping 30 s windows, only when timing coverage and quality suffice.
    const bins=Array.from({length:Math.ceil(duration/30)},()=>[]);
    rows.forEach(r=>{const i=Math.floor(r.time_s/30);if(bins[i])bins[i].push(r)});
    const episodes=[];let run=null;
    bins.forEach((all,i)=>{
      const good=all.filter(r=>code(r)==='N'&&r.rr_ms>=300&&r.rr_ms<=2000);
      let eligible=all.length>=20&&good.length/all.length>=.9&&all.at(-1).time_s-all[0].time_s>=25,cv=0,rmssd=0,turns=0;
      if(eligible){const values=good.map(r=>r.rr_ms),mean=values.reduce((a,b)=>a+b,0)/values.length;cv=Math.sqrt(values.reduce((s,x)=>s+(x-mean)**2,0)/values.length)/mean;
        let n=0;for(let k=1;k<all.length;k++)if(good.includes(all[k-1])&&good.includes(all[k])){rmssd+=(all[k].rr_ms-all[k-1].rr_ms)**2;n++}rmssd=n?Math.sqrt(rmssd/n)/mean:0;
        for(let k=1;k<values.length-1;k++)if((values[k]-values[k-1])*(values[k+1]-values[k])<0)turns++;turns/=Math.max(1,values.length-2);
      }
      const candidate=eligible&&cv>=.12&&rmssd>=.14&&turns>=.45&&turns<=.85;
      if(candidate){if(!run){run={id:'rr-'+i*30,start_s:i*30,end_s:Math.min(duration,(i+1)*30),kind:'AF',status:'pending',source:'rr-irregularity-v1',note:'30 秒 RR 筛查：CV≥0.12、归一化 RMSSD≥0.14、转折率 0.45–0.85；未分析 P 波，须排除伪差/早搏'};episodes.push(run)}else run.end_s=Math.min(duration,(i+1)*30)}else run=null;
    });return episodes;
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
    return {width,height,bins:Array.from(bins),total:samples.length,included:positions.length,skipped_edges:samples.length-positions.length,clipped_points:clipped,lead,x_min_s:-1,x_max_s:1,amplitude_limit:limit,units:'设备原始标度 µV（未溯源）',sample_indices:selected,population_samples:[...samples],method:'R 对齐 · 全集合计数 · 10 ms 栅格 · 去固定基线 · 无逐搏增益归一化'};
  }
  const api={clamp,code,valid,decode,pairs,histogram,stats,cut,validateDocument,annotations,initialEpisodes,screenAF,density,densitySamples};
  root.ECGOverviewEngine=api;if(typeof module!=='undefined')module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
