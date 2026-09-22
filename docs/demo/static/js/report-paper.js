"use strict";
/* A4 evidence document. The editor controls deliberately stay outside the paper. */
(()=>{
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),value=x=>x==null?'—':String(x),num=x=>x==null?'—':String(Math.round(x*100)/100);
  function clock(meta,seconds=0){
    const raw=meta.start_iso||meta.start_time,parsed=Date.parse(String(raw).replace(' ','T').slice(0,19)+'Z');
    if(Number.isFinite(parsed))return new Date(parsed+seconds*1000).toISOString().slice(0,19).replace('T',' ');
    const s=Math.floor(seconds),d=Math.floor(s/86400)+1;return `D${d} ${[Math.floor(s%86400/3600),Math.floor(s%3600/60),s%60].map(x=>String(x).padStart(2,'0')).join(':')}`;
  }
  function wrapText(text,width=53){
    const lines=[];for(const source of String(text||'（未填写）').split('\n')){let line='',measure=0;for(const ch of source){const w=ch.charCodeAt(0)>255?1:.55;if(measure+w>width){lines.push(line);line='';measure=0;}line+=ch;measure+=w;}lines.push(line);}return lines;
  }
  function shell(model,body,kind){const meta=model.case.metadata||{};return `<section class="rp-sheet rp-${kind}" aria-label="A4 ${kind==='summary'?'报告首页':kind==='hourly'?'统计表格':'报告证据'}"><header class="rp-running"><span>患者 ID：${esc(meta.patient_id||model.case.case_id)}</span><span>姓名：${esc(meta.name||'—')}</span><span>${model.report.status==='reviewed'?'已审核':'未审核 · 草稿'}</span></header><div class="rp-body">${body}</div><footer class="rp-footer"><span>研究与软件验证输出 · 需医生复核，不用于临床决策</span><span data-rp-page></span></footer></section>`;}
  function kv(items){return items.map(([k,v])=>`<div><span>${esc(k)}：</span>${esc(value(v))}</div>`).join('');}
  function summary(model){
    const meta=model.case.metadata||{},s=model.statistics.summary||{},h=model.statistics.hrv||{},opts=model.statistics.settings||{},report=model.report;
    const titles=(report.composition?.diagnosis_blocks||[]).map(b=>b.text).filter(Boolean),text=[report.conclusion||'（未填写）',...titles.length?['图条说明（不替代诊断）：'+titles.join('；')]:[]].join('\n'),lines=wrapText(text),first=lines.splice(0,15);
    const hrPoint=r=>r?`${num(r.hr)} 次/分（${clock(meta,r.time_s).slice(5)}）`:'—';
    const rhythm=code=>{const x=s[code]||{};return `<section><h3>${code==='V'?'室性':'室上性'}心搏</h3>${kv([['总数',`${value(x.total)} 搏（${value(x.pct)}%）`],['单发',`${value(x.single)} 次`],['成对',`${value(x.couplet)} 对`],['短阵（≥3搏）',`${value(x.run)} 阵`],['二联律',`${value(x.bigeminy)} 阵`],['三联律',`${value(x.trigeminy)} 阵`]])}</section>`;};
    const body=`<div class="rp-title">${meta.hospital?`<h1>${esc(meta.hospital)}</h1>`:''}<h1>动态心电图检测报告</h1></div><h2>检查信息</h2><div class="rp-exam rp-box">${kv([['姓名',meta.name],['性别',meta.sex],['年龄',meta.age!=null?meta.age+' 岁':null],['起搏器',meta.pacemaker],['ID 号',meta.patient_id||model.case.case_id],['床位',meta.bed],['记录时间',meta.start_time],['记录时长',meta.duration_text],['申请医生',meta.requesting_doctor],['申请科室',meta.department],['临床诊断',meta.clinical_diagnosis]])}</div><h2>分析统计</h2><div class="rp-analysis rp-box"><div class="rp-two"><section><h3>概要</h3>${kv([['总心搏数',`${value(s.total)} 搏`],['伪差',`${value(s.noise)} 个`],['室性心搏',`${value(s.V?.total)} 搏`],['室上性心搏',`${value(s.S?.total)} 搏`],['最长 RR',s.longest?`${num(s.longest.rr_ms/1000)} 秒（${clock(meta,s.longest.time_s).slice(5)}）`:'—'],['长 RR 候选',`${value(s.pause)} 次 >2.5s；其中 ${value(s.pause_over3)} 次 >3s`]])}</section><section><h3>心率</h3>${kv([['最慢心率',hrPoint(s.slowest)],['平均心率',`${num(s.avg_hr)} 次/分`],['最快心率',hrPoint(s.fastest)],['快心率心搏',`${value(s.tachy_beats)} 搏（≥${value(opts.tachy)} bpm）`],['慢心率心搏',`${value(s.brady_beats)} 搏（≤${value(opts.brady)} bpm）`],['已确认房颤/房扑',`${value(s.af)} 段`]])}</section></div><div class="rp-two">${rhythm('V')}${rhythm('S')}</div><section class="rp-hrv"><h3>心率变异性 · 当前修订 N-N</h3><div>${[['SDNN',h.sdnn_ms,'ms'],['SDANN',h.sdann_ms,'ms'],['SDNN index',h.sdnn_index_ms,'ms'],['rMSSD',h.rmssd_ms,'ms'],['pNN50',h.pnn50_pct,'%'],['三角指数',h.triangular_index,'']].map(([k,v,u])=>`<span>${k}: ${num(v)} ${u}</span>`).join('')}</div><p>频域（源报告独立对照）：LF/HF ${num(model.case.summary?.lf_hf)} · LF ${num(model.case.summary?.lf)} · HF ${num(model.case.summary?.hf)}；— 表示未提供或样本不足。</p></section></div><p class="rp-method">${esc(model.statistics.method)} 所有自动结果仍须医生核对。</p><h2>报告结论</h2><div class="rp-conclusion rp-box"><p>${esc(first.join('\n'))}</p><div class="rp-signatures"><span>审核医生：${esc(report.reviewed_by||'未审核')}</span><span>报告状态：${report.status==='reviewed'?'已审核':'草稿'} v${report.version||1}</span><span>报告日期：${esc((report.updated_at||'未保存').slice(0,10))}</span></div></div>`;
    const pages=[shell(model,body,'summary')];while(lines.length)pages.push(shell(model,`<h2>报告结论（续）</h2><p class="rp-continuation">${esc(lines.splice(0,48).join('\n'))}</p>`,'continuation'));return pages.join('');
  }
  function hourly(model){
    const stats=model.statistics,rows=stats.hourly||[],pages=[];
    const row=r=>`<tr><td>${esc(r.label||'总计').replace(' ','<br>')}</td><td>${value(r.total)}</td>${['min_hr','avg_hr','max_hr'].map(k=>`<td>${num(r[k])}</td>`).join('')}${['V','S'].map(k=>['single','couplet','run','bigeminy','trigeminy','total','pct'].map(p=>`<td>${num(r[k]?.[p])}</td>`).join('')).join('')}<td>${value(r.af)}</td><td>${value(r.pause)} / ${value(r.pause_over3)}</td></tr>`;
    for(let i=0;i<Math.max(1,rows.length);i+=25){const part=rows.slice(i,i+25),last=i+25>=rows.length;pages.push(shell(model,`<h2>统计表格${i?'（续）':''}</h2><table class="rp-hourly-table"><thead><tr><th rowspan="2">时间</th><th rowspan="2">心搏数</th><th colspan="3">心率 bpm</th><th colspan="7">室性心搏</th><th colspan="7">室上性心搏</th><th rowspan="2">房颤<br>房扑</th><th rowspan="2">长RR<br>&gt;2.5 / &gt;3s</th></tr><tr><th>最慢</th><th>平均</th><th>最快</th>${[0,1].map(()=>['单发','成对','短阵','二联律','三联律','总计','%'].map(x=>`<th>${x}</th>`).join('')).join('')}</tr></thead><tbody>${part.map(row).join('')}</tbody>${last?`<tfoot>${row(stats.summary||{})}</tfoot>`:''}</table><p class="rp-method">${esc(stats.method)} 首尾不足一小时按实际覆盖统计；无可用数据以 — 显示。</p>`,'hourly'));}return pages.join('');
  }
  function stripSvg(entry,paper={},height=276){
    const wave=entry.waveform,spec=entry.strip||{},names=spec.leads||Object.keys(wave.leads),width=760,left=48,plotWidth=700,top=28,contextHeight=24,bottom=height-40,row=(bottom-top)/Math.max(1,names.length),gain=parseFloat(paper.gain)||10,scale=4*gain/1000;
    const n=x=>Number(x).toFixed(2),text=(x,y,t,size=9,anchor='start')=>`<text x="${n(x)}" y="${n(y)}" font-size="${size}" text-anchor="${anchor}" fill="#111">${esc(t)}</text>`,line=(x,y,x2,y2,color='#ccc',stroke=.35)=>`<path d="M${n(x)} ${n(y)}L${n(x2)} ${n(y2)}" stroke="${color}" stroke-width="${stroke}"/>`;
    let svg=`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(names.join('、'))}，${num(wave.duration_s)} 秒，${spec.visible_beat_count??wave.beats?.length??0} 个心搏"><rect width="760" height="${height}" fill="white"/>`;
    // One mm = four SVG units. The actual time scale is printed, never mislabeled 25 mm/s after extension.
    for(let x=left;x<=left+plotWidth;x+=4)svg+=line(x,top,x,bottom,(x-left)%20===0?'#b9b9b9':'#e4e4e4',(x-left)%20===0?.5:.25);
    for(let y=top;y<=bottom;y+=4)svg+=line(left,y,left+plotWidth,y,(y-top)%20===0?'#b9b9b9':'#e4e4e4',(y-top)%20===0?.5:.25);
    for(const r of wave.beats||[]){const x=left+(r.sample_index/200-wave.start_s)/wave.duration_s*plotWidth;if(x<left||x>left+plotWidth)continue;svg+=text(x,8,r.class_code||'',8,'middle')+text(x,17,Math.round(r.hr||0)||'—',7,'middle')+text(x,25,r.rr_ms||'—',7,'middle');}
    names.forEach((name,j)=>{
      const values=wave.leads[name]||[],sorted=values.slice().sort((a,b)=>a-b),median=sorted.length?sorted[Math.floor(sorted.length/2)]:0,base=top+(j+.65)*row,lower=row*.32,upper=row*.62;
      const calibrated=wave.calibration_verified===true,perUnit=calibrated?scale:Math.min(upper/Math.max(1,...values.map(v=>v-median)),lower/Math.max(1,...values.map(v=>median-v)))*.95,pulse=calibrated?1000*scale:Math.min(20,upper*.8);
      svg+=text(3,base+4,name,10);svg+=`<path d="M24 ${n(base)}h4v${n(-pulse)}h8v${n(pulse)}h5" stroke="#111" stroke-width=".65" fill="none"/>`;
      if(!calibrated)svg+=text(2,base+13,`${Math.round(pulse/perUnit)}u`,6);
      const points=values.map((v,i)=>`${n(left+i/(wave.display_sample_rate_hz||200)/wave.duration_s*plotWidth)},${n(base-Math.max(-lower,Math.min(upper,(v-median)*perUnit)))}`).join(' ');
      svg+=`<polyline points="${points}" stroke="#111" stroke-width=".7" fill="none"/>`;
      if(calibrated&&values.some(v=>(v-median)*scale>upper||(v-median)*scale < -lower))svg+=text(left+plotWidth-2,top+j*row+9,'幅度超框，请降低增益',8,'end');
    });
    svg+=text(left,bottom+11,`${num(plotWidth/4/wave.duration_s)} mm/s · ${wave.calibration_verified===true?gain+' mm/mV':'逐导联自适应幅度 · u = 设备单位，电压未校准'} · ${num(wave.duration_s)} s`,8);
    const c=entry.context;if(c){const vals=c.leads.II||[],sorted=vals.slice().sort((a,b)=>a-b),median=sorted[Math.floor(sorted.length/2)]||0,amp=Math.max(50,...vals.map(v=>Math.abs(v-median))),y=height-contextHeight,mid=y+contextHeight/2,x=left+(wave.start_s-c.start_s)/c.duration_s*plotWidth,w=wave.duration_s/c.duration_s*plotWidth;
      svg+=`<rect x="${n(x)}" y="${y}" width="${n(w)}" height="${contextHeight}" fill="#dedede"/>`+text(4,mid+3,'II',8);
      svg+=`<polyline points="${vals.map((v,i)=>`${n(left+i/Math.max(1,vals.length-1)*plotWidth)},${n(mid-(v-median)/amp*9)}`).join(' ')}" stroke="#111" stroke-width=".65" fill="none"/>`+line(left,y,left+plotWidth,y,'#444',.6);
    }
    return svg+'</svg>';
  }
  function stripPages(model,entries){
    const pages=[],notes=[];let batch=[],units=0;
    const flush=()=>{if(!batch.length)return;pages.push(shell(model,`<div class="rp-strips" style="--rp-slots:${units}">${batch.map(e=>{const leads=e.strip.leads.length,slots=leads<=3?1:leads<=6?2:3,height=slots*304-28;return `<article class="rp-strip" style="--rp-span:${slots}"><header><span>${esc(clock(model.case.metadata,e.waveform.start_s))}</span><strong>${esc(e.caption||e.label)}</strong><span>HR: ${num(e.hr)} bpm</span></header>${stripSvg(e,model.report.composition?.paper,height)}<p class="rp-strip-note">${esc(e.strip.warning||`${e.strip.visible_beat_count} 搏 · ${e.strip.leads.join(' / ')}`)}</p></article>`}).join('')}</div>`,'waveforms'));batch=[];units=0;};
    entries.forEach((entry,i)=>{const lines=wrapText(entry.caption||entry.label,46),e={...entry};if(lines.length>1){e.caption=`[图条 ${i+1}] ${lines[0]}…`;notes.push(...wrapText(`图条 ${i+1}：${entry.caption||entry.label}`,53),'');}const u=e.strip.leads.length<=3?1:e.strip.leads.length<=6?2:3;if(units+u>3)flush();batch.push(e);units+=u;if(units===3)flush();});flush();
    while(notes.length)pages.push(shell(model,`<h2>图条说明（完整图注）</h2><p class="rp-continuation">${esc(notes.splice(0,44).join('\n'))}</p>`,'captions'));
    return pages.join('');
  }
  function render(model,entries=[]){return summary(model)+hourly(model)+stripPages(model,entries)+(model.report.composition?.include_hrv&&model.hrv?ECGHrvReport.pages(model,model.hrv):'');}
  function number(host){const pages=[...host.querySelectorAll('.rp-sheet')];pages.forEach((p,i)=>{p.querySelector('[data-rp-page]').textContent=`第 ${i+1} / ${pages.length} 页`;});}
  globalThis.ECGReportPaper={render,summary,hourly,stripPages,stripSvg,number,clock,wrapText,shell};
})();
