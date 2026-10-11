'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),crypto=require('node:crypto');
const root=path.resolve(__dirname,'..'),read=file=>fs.readFileSync(path.join(root,file),'utf8');
function reportApi(source=read('static/js/hrv-report.js')){
  const context=vm.createContext({});
  vm.runInContext(read('static/js/report-paper.js'),context);
  vm.runInContext(source,context);
  return context.ECGHrvReport;
}
const model={case:{case_id:'synthetic-hrv-continuous',metadata:{patient_id:'SYNTHETIC',name:'软件验证'}},report:{status:'draft'}};
function payload(hours=26,{clock=true,window=0}={}){
  const base={label:'全程（当前窗口）',mean_nn_ms:800,sdnn_ms:42,sdann_ms:30,sdnn_index_ms:21,rmssd_ms:22,pnn50_pct:8,triangular_index:12,nn_count:3600,valid_nn_s:2880,coverage_s:3600,five_minute_blocks:9,spectral_blocks:8,frequency:{total_ms2:200,vlf_ms2:50,lf_ms2:100,hf_ms2:50,lf_hf:2},histogram:[{rr_ms:780,count:2},{rr_ms:800,count:30},{rr_ms:820,count:2}],psd:[{hz:0,power:0},{hz:.1,power:100},{hz:.2,power:null},{hz:.3,power:25}]};
  const start=window*86400,hourly=Array.from({length:hours},(_,i)=>({...base,label:`验证小时 ${String(i+1).padStart(2,'0')}`,start_s:start+i*3600,end_s:start+(i+1)*3600,total_beats:3600+i,avg_hr:60+i,min_hr:45,max_hr:100,v_count:i,s_count:2*i,pause_count:0,pause_over3:0,sdnn_ms:i===0?0:i===1?null:42+i}));
  const event=(count)=>({single:count,couplet:0,run:0,bigeminy:0,trigeminy:0,total:count});
  return {start_s:start,end_s:start+hours*3600,actual_duration_s:hours*3600,clock_available:clock,window_count:2,window_index:window,method:'当前 NN · <统计口径> · 空缺不补齐',risk_note:'SDNN 统计参考，不单独给出风险或诊断。',periods:{full:base,day:{...base,label:'日间（钟点）'},night:{...base,label:'夜间（钟点）'}},hourly,trend:hourly.map((h,i)=>({time_s:h.start_s,hr:i===1?null:60+i,sdnn_ms:h.sdnn_ms})),rate_sdnn:[{hr_range:'50–79',minute_bins:hours,sdnn_ms:40},{hr_range:'≥170',minute_bins:0,sdnn_ms:null}],st_trends:{II:hourly.map((h,i)=>({time_s:h.start_s,deviation_units:i===1?null:(i%2?-1:1)*(i+1)}))},event_statistics:{hourly:hourly.map((h,i)=>({start_s:h.start_s,end_s:h.end_s,af:i%2,S:event(i+1),V:event(i)}))},representatives:['fastest','slowest','V','S','pause'].map((category,i)=>({category,label:`代表条 ${category} <候选>`,hr:50+i,waveform:{duration_s:3,leads:{II:[0,1,-1,.5,0]}}}))};
}
function continuous(html){return html.slice(html.indexOf('<div class="hrv-continuous">'),html.indexOf('<details class="hrv-paper-preview">'));}
function detailRows(html){const table=html.match(/<table class="hrvp-table hrvp-hourly hrvp-detail">([\s\S]*?)<\/table>/);assert(table,'continuous hourly statistics must exist');return [...table[1].matchAll(/<tbody>([\s\S]*?)<\/tbody>/g)][0][1].match(/<tr>/g)||[];}
const sha=text=>crypto.createHash('sha256').update(text).digest('hex');
// Locked against the pre-change A4 output for the deterministic 26-hour fixture.
const golden={pages:'e08d7b66c4d4a5ef36f91ace92beb520a5c773881748cc5dc2e1d9344cb989d0',overviewPages:'b24a1a90f8410ce72c930e01fa97ec66ef3779ae7e1b40cabfcf7ac05fa00188'};
function verify(){
  const api=reportApi(),data=payload(),before=JSON.stringify(data),html=api.ui(model,data,true),screen=continuous(html);
  assert.equal(detailRows(screen).length,26,'all 26 supplied hours must be rendered together');
  for(const row of data.hourly)assert.equal(screen.split(`>${row.label}<`).length-1,1,'every hour has exactly one screen statistics row');
  for(const category of ['fastest','slowest','V','S','pause'])assert(screen.includes(`代表条 ${category} &lt;候选&gt;`),'representative omitted: '+category);
  assert(screen.includes('ms²/Hz'));assert(screen.includes('总功率 ms²'));assert(screen.includes('设备单位'));assert(screen.includes('频域总功率'));assert(screen.includes('ST 相对基线变化'));assert(screen.includes('LF/HF'));assert(screen.includes('SDNN 与 NN 心率关系'));
  assert(!screen.includes('rp-sheet'));assert(!screen.includes('统计续页'));assert(!screen.includes('data-inspect-chart'),'screen copies must not acquire a selected-period chart identity');
  assert(html.indexOf('hrv-continuous')<html.indexOf('hrv-paper-preview'));
  assert.match(html,/<details class="hrv-paper-preview"><summary>A4 \/ PDF 预览/);assert(!html.includes('<details class="hrv-paper-preview" open'));
  assert(html.endsWith(api.pages(model,data)+'</div></details></div>'),'preview must contain the exact export pages');
  assert.equal((html.match(/class="v2-hrv-window"/g)||[]).length,1);assert.equal((html.match(/data-hrv-include/g)||[]).length,1);assert.equal((html.match(/data-hrv-export/g)||[]).length,1);
  assert.match(html,/data-hrv-include checked/);assert.match(screen,/&lt;统计口径&gt;/);assert.equal(JSON.stringify(data),before,'rendering must not mutate analysis data');
  assert.equal((api.pages(model,data).match(/rp-sheet rp-hrv/g)||[]).length,3,'A4 still paginates the 26 supplied rows');
  for(const key of ['pages','overviewPages'])assert.equal(sha(api[key](model,data)),golden[key],key+' must remain byte-identical to the frozen A4 output');
  for(const small of [payload(0),payload(2,{clock:false,window:1})]){
    const page=api.ui(model,small,false),web=continuous(page);
    assert.equal(detailRows(web).length,small.hourly.length);assert(!page.includes('data-hrv-include checked'));
    if(!small.clock_available)assert(page.includes('记录起始时钟不可用，日间/夜间不计算。'));
    assert(page.endsWith(api.pages(model,small)+'</div></details></div>'));
  }
  const baseline=process.env.HRV_CONTINUOUS_BASELINE;
  if(baseline){const old=reportApi(fs.readFileSync(baseline,'utf8'));for(const d of [data,payload(0),payload(2,{clock:false,window:1})])for(const key of ['pages','overviewPages'])assert.equal(api[key](model,d),old[key](model,d),'baseline byte comparison: '+key);}
  // Exercise the real demo analyzer over a 26-hour synthetic recording and both actual 24-hour windows.
  require('../static/js/report-engine.js');require('../static/js/clinical-analysis.js');require('../static/js/hrv-analysis.js');
  const duration=26*3600,beats=Array.from({length:duration},(_,i)=>({id:'s:'+i*200,sample_index:i*200,time_s:i,class_code:i%3599===3?'V':'N',rr_ms:i?1000:0,hr:i?60:null})),feed={beats,markers:[],duration,document:{settings:{nn_min:300,nn_max:2000,pause:2.5,tachy:120,brady:50}}};
  let coverage=0,rows=0;
  for(let window=0;window<2;window++){
    const d=ECGHrvAnalysis.analyze(feed,'2026-09-20 08:30:00',window),original=JSON.stringify(d),page=api.ui(model,d,false),web=continuous(page);
    assert.equal(d.window_count,2);assert.equal(d.window_index,window);assert.equal(detailRows(web).length,d.hourly.length);
    for(const row of d.hourly)assert(web.includes('>'+row.label+'<'));
    assert(page.includes(`<option value="${window}" selected>`));assert.equal(JSON.stringify(d),original);
    coverage+=d.actual_duration_s;rows+=d.hourly.length;
  }
  assert.equal(coverage,duration);assert.equal(rows,28,'clock-aligned partial hours in both windows are retained');
  console.log('HRV continuous: 26 supplied rows, real 26h/two-window coverage, periods, units, gaps, representatives, controls, escaping, immutability and byte-identical A4 output passed');
}
function fixture(){
  const scripts=['static/js/report-paper.js','static/js/hrv-report.js','static/js/hrv-review-evidence.js'].map(file=>`<script>${read(file)}</script>`).join('');
  const css=['static/css/report-paper.css','static/css/hrv-review-evidence.css'].map(read).join('\n');
  return `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>合成 HRV 连续布局验证</title><style>body{margin:0;padding:16px;box-sizing:border-box;font-family:system-ui,sans-serif;background:#edf2f3}main{max-width:1800px;min-width:0;margin:auto}.button{font:inherit;border:1px solid #b8ccd5;border-radius:5px;background:white;color:#164a54;padding:8px 12px}*{box-sizing:border-box}${css}</style><main id="fixture"></main>${scripts}<script>const fixtureData=${JSON.stringify(payload())};fixture.innerHTML=ECGHrvReport.ui(${JSON.stringify(model)},fixtureData,true);ECGReportPaper.number(fixture);const host=document.createElement('div');host.className='hrv-review-host';fixture.querySelector('.hrv-evidence-notice').after(host);ECGHrvReview.mount(host,fixtureData,{scope:'synthetic-continuous-layout'});</script></html>`;
}
module.exports={payload,model,fixture,reportApi,sha};
if(require.main===module){
  if(process.argv[2]==='--fixture'){fs.writeFileSync(process.argv[3],fixture());console.log(process.argv[3]);}
  else if(process.argv[2]==='--golden'){const api=reportApi(fs.readFileSync(process.argv[3],'utf8')),d=payload();console.log(JSON.stringify({pages:sha(api.pages(model,d)),overviewPages:sha(api.overviewPages(model,d))}));}
  else verify();
}
