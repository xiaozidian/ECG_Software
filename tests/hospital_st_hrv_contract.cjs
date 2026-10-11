'use strict';
// Synthetic requests and production renderers only. No case or workspace writes.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const prefix=fs.readFileSync('tests/browser_advanced_session.cjs','utf8').split('async function scenario(')[0];
const ctx={require};vm.runInNewContext(prefix+'\nglobalThis.fixture=setup;',ctx);
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject};};
const response=start=>({advanced:{basis:'synthetic',calibration:'device units',options:{start_s:start,duration_s:45},qtd:{leads:[]}},derivatives:{}});
async function cancellation(){
 const {api,host}=ctx.fixture(),h=host(),requests=[],applied=[];
 api.mountRetained(h,{sessionKey:['synthetic-cancel'],contextCurrent:()=>true,duration:900,options:{},compute:options=>{const gate=deferred();requests.push({options,gate});return gate.promise;},onChange:options=>applied.push(options),onPrint(){},onLocate(){}});
 const form=h.get('form');form.elements.start_s.value='12';form.elements.duration_s.value='45';form.oninput();form.onsubmit({preventDefault(){}});
 assert.equal(requests.length,1);assert.equal(h.attrs['aria-busy'],'true');assert.equal(h.get('[data-cancel-analysis]').disabled,false);
 h.get('[data-cancel-analysis]').onclick();assert.equal(h.attrs['aria-busy'],'false');assert.equal(form.elements.start_s.value,'12');assert(api.pending());assert.throws(()=>api.assertApplied(),/未应用/);
 form.elements.start_s.value='24';form.oninput();form.onsubmit({preventDefault(){}});assert.equal(requests.length,2);
 requests[1].gate.resolve(response(24));await tick();assert.equal(applied.length,1);assert.equal(applied[0].start_s,24);assert.equal(h.get('.am-settings').open,false);assert.equal(api.pending(),false);
 const status=h.get('.am-status').textContent;requests[0].gate.resolve(response(12));await tick();assert.equal(applied.length,1);assert.equal(h.get('.am-status').textContent,status);
 form.elements.start_s.value='30';form.oninput();form.onsubmit({preventDefault(){}});h.get('[data-cancel-analysis]').onclick();const cancelled=h.get('.am-status').textContent;
 requests[2].gate.reject(Error('late-cancelled-network-error'));await tick();assert.equal(h.get('.am-status').textContent,cancelled);assert.equal(applied.length,1);
 h.get('[data-discard-settings]').onclick();assert.equal(api.pending(),false);assert.equal(form.elements.start_s.value,24);
 form.onsubmit({preventDefault(){}});api.clear();assert.equal(h.attrs['aria-busy'],'false');requests[3].gate.resolve(response(24));await tick();assert.equal(applied.length,1);assert.equal(api.pending(),false);
}
function sharedPlane(){
 const {payload,model,reportApi}=require('./browser_hrv_continuous.cjs'),api=reportApi(),data=payload(26),before=JSON.stringify(data),html=api.ui(model,data,true);
 const screen=html.slice(html.indexOf('<div class="hrv-continuous">'),html.indexOf('<details class="hrv-paper-preview">'));
 const paper=api.pages(model,data),series=markup=>markup.match(/<(?:path|rect|circle)\b[^>]*(?:stroke="#222"|fill="#222")[^>]*>/g)||[];
 assert(series(screen).length>20);assert.deepEqual(series(screen),series(paper),'screen and paper must retain every measured plotting coordinate and missing-data gap');
 const order=['心率变异性分析报告','全程（当前窗口）','日间（钟点）','夜间（钟点）','SDNN 与 NN 心率关系','记录趋势报告','ST 相对基线变化','频域总功率（ms²）'];
 for(const markup of [screen,paper]){let previous=-1;for(const label of order){const at=markup.indexOf(label);assert(at>previous,'same evidence order: '+label);previous=at;}}
 for(const unit of ['ms²/Hz','RR ms','pNN50','LF/HF','设备单位'])assert(screen.includes(unit)&&paper.includes(unit));
 assert(html.indexOf('data-hrv-export')>html.indexOf('hrv-paper-preview'),'independent export belongs to the final A4 entry');assert.equal((html.match(/data-hrv-export/g)||[]).length,1);
 assert.equal(JSON.stringify(data),before);
 const {api:advanced}=ctx.fixture();assert(!/NaN|Infinity/.test(advanced.plot([{x:0,y:800},{x:null,y:820},{x:2,y:830}],{title:'synthetic missing coordinate'})));
}
function periodDomains(){
 const api=require('../static/js/hrv-review-evidence.js'),{payload}=require('./browser_hrv_continuous.cjs'),data=payload(3);data.hourly[2].frequency={...data.hourly[2].frequency,lf_ms2:0,hf_ms2:null};const original=JSON.stringify(data);
 function host(){const rows=api.rows(data).map((_,i)=>({dataset:{hrvrRow:String(i)},setAttribute(k,v){this[k]=v;},focus(){}})),domains=['time','frequency'].map(domain=>({dataset:{hrvrDomain:domain},setAttribute(k,v){this[k]=v;}})),body={innerHTML:''},status={textContent:''},scroll={scrollTop:0,addEventListener(){}},tbody={innerHTML:''};return {isConnected:true,innerHTML:'',classList:{add(){}},setAttribute(){},querySelector:s=>({'.hrvr-detail':body,'.hrvr-status':status,'.hrvr-table-scroll':scroll,tbody}[s]),querySelectorAll:s=>s==='[data-hrvr-row]'?rows:s==='[data-hrvr-domain]'?domains:[],body,rows,domains};}
 let current=true;const h=host(),scope='synthetic-domain-revision-1',controller=api.mount(h,data,{scope,isCurrent:()=>current});controller.select(5);controller.setDomain('frequency');assert.equal(controller.current(),'hour-2');assert.equal(controller.domain(),'frequency');assert.equal((h.body.innerHTML.match(/<figure>/g)||[]).length,1);assert.match(h.body.innerHTML,/功率谱/);assert.match(h.body.innerHTML,/0 <small>ms²/);assert.match(h.body.innerHTML,/— <small>ms²/);
 const returned=api.mount(host(),data,{scope});assert.equal(returned.current(),'hour-2');assert.equal(returned.domain(),'frequency');current=false;assert.equal(controller.setDomain('time'),false);assert(!h.body.innerHTML.includes('<svg'));assert(h.rows.concat(h.domains).every(b=>b.disabled));assert.equal(api.mount(host(),data,{scope}).domain(),'frequency');
 const fresh=host(),other=api.mount(fresh,data,{scope:'synthetic-domain-revision-2'});assert.equal(other.domain(),'time');assert.equal(other.current(),'full');other.setDomain('frequency');assert.equal(other.current(),'full');assert.equal(JSON.stringify(data),original);
 const unavailable=host(),empty=api.mount(unavailable,{...data,clock_available:false},{scope:'synthetic-domain-no-clock'});empty.select(1);empty.setDomain('frequency');assert(!unavailable.body.innerHTML.includes('<svg'));assert.match(unavailable.body.innerHTML,/起始时钟不可用/);
}
(async()=>{await cancellation();sharedPlane();periodDomains();console.log('Hospital ST/HRV: cancellation, retry, late success/error, clear, pending output gates, scoped period-domain retention and identical screen/paper plotting coordinates passed');})().catch(error=>{console.error(error);process.exitCode=1});
