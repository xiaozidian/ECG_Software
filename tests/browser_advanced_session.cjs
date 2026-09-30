const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const tick=()=>new Promise(r=>setImmediate(r));
const gate=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}};
function setup(){
  const listeners={};const ctx=vm.createContext({window:{addEventListener:(name,fn)=>listeners[name]=fn}});
  vm.runInContext(fs.readFileSync('static/js/advanced-analysis.js','utf8'),ctx);
  function host(){
    const nodes=new Map();
    const get=s=>{if(!nodes.has(s))nodes.set(s,{hidden:false,attrs:{},textContent:'',innerHTML:'',value:'',checked:false,
      setAttribute(k,v){this.attrs[k]=v},querySelector:get,querySelectorAll:()=>[],insertAdjacentHTML(){},reportValidity:()=>true});return nodes.get(s)};
    const form=get('form');form.elements={};
    for(const [key,value] of Object.entries({start_s:0,duration_s:300,sap_start_s:0,sap_end_s:'',use_estimate:'',standard_leads:'',uv_per_unit:'',calibration_note:''}))form.elements[key]={value,checked:false};
    const buttons=['qtd','vcg'].map(x=>({dataset:{amTab:x},setAttribute(){}}));
    return {isConnected:true,innerHTML:'',attrs:{},nodes,get,buttons,querySelector:get,
      querySelectorAll:s=>s==='[data-am-tab]'?buttons:[],setAttribute(k,v){this.attrs[k]=v},
      replaceWith(other){this.replacement=other;other.isConnected=true;this.isConnected=false}};
  }
  return {api:ctx.ECGAdvancedAnalysis,host,listeners};
}
async function scenario(mode){
  const {api,host,listeners}=setup();const h=host(),g=gate();let active=true,changed=0,options={},calls=0;
  const config={sessionKey:['case-A',1,'basis-A'],contextCurrent:()=>active,options,
    duration:90,compute:()=>{calls++;return g.promise},onChange:x=>{changed++;options=x},onPrint(){},onLocate(){}};
  api.mountRetained(h,config);const form=h.get('form');
  assert.equal(api.pending(),false);
  form.elements.start_s.value='12';form.elements.duration_s.value='45';form.oninput();
  assert.equal(api.pending(),true);assert.throws(()=>api.assertApplied(),/研究测量/);
  assert.match(h.get('.am-status').textContent,/尚未计算/);
  let prevented=0;listeners.beforeunload({preventDefault(){prevented++}});assert.equal(prevented,1);
  h.get('.am-panel').open=true;
  const replacement=host();api.mountRetained(replacement,{...config,options:{}});
  assert.equal(replacement.replacement,h);assert.equal(h.get('.am-panel').open,true);
  assert.equal(form.elements.start_s.value,'12');assert.equal(form.elements.duration_s.value,'45');
  if(mode==='discard'){
    h.get('[data-discard-settings]').onclick();assert.equal(api.pending(),false);
    assert.equal(form.elements.start_s.value,0);assert.equal(form.elements.duration_s.value,300);return;
  }
  form.onsubmit({preventDefault(){}});form.onsubmit({preventDefault(){}});assert.equal(calls,1);
  assert.equal(h.attrs['aria-busy'],'true');assert.throws(()=>api.assertApplied(),/正在计算/);
  form.oninput();assert.equal(h.attrs['aria-busy'],'true');
  if(mode==='detached')h.isConnected=false;
  if(mode==='basis')active=false;
  if(mode==='replaced')api.mountRetained(host(),{...config,sessionKey:['case-B',2,'basis-B']});
  if(mode==='clear')api.clear();
  if(mode==='failed')g.reject(Error('network-down'));
  else g.resolve({advanced:{basis:'basis-A',calibration:'device units',options:{start_s:12,duration_s:45},qtd:{leads:[]}},derivatives:{}});
  await tick();assert.equal(h.attrs['aria-busy'],'false');
  assert.equal(changed,mode==='success'?1:0);
  if(mode==='success'){
    assert.equal(api.pending(),false);assert.equal(h.get('.am-results').hidden,false);
    const next=host();api.mountRetained(next,{...config,options:{duration_s:45,start_s:12}});
    assert.equal(next.replacement,h); // Key order changes during a saved-report roundtrip are harmless.
    const other=host();api.mountRetained(other,{...config,options:{start_s:20,duration_s:45}});
    assert.equal(other.replacement,undefined); // An explicitly loaded different report is not overwritten.
  }else if(mode==='failed'){
    assert.equal(api.pending(),true);assert.match(h.get('.am-status').textContent,/network-down.*可重试/);
    h.get('[data-discard-settings]').onclick();assert.equal(api.pending(),false);
  }else if(mode==='detached'){
    assert.match(h.get('.am-status').textContent,/结果未应用/);
    const next=host();api.mountRetained(next,config);assert.equal(next.replacement,h);
    assert.equal(h.attrs['aria-busy'],'false');assert.equal(api.pending(),true);
  }else assert.equal(api.pending(),false);
}
async function gates(){
  const source=fs.readFileSync('static/js/clinical-ui.js','utf8');
  for(const name of ['save','previewPaper','print','downloadReport','reloadReport']){
    const start=source.indexOf('  async function '+name+'('),end=source.indexOf('\n  }',start)+4;
    assert(start>=0);const ctx=vm.createContext({ECGAdvancedAnalysis:{assertApplied(){throw Error('pending-advanced')}}});
    vm.runInContext(source.slice(start,end),ctx);await assert.rejects(ctx[name](),/pending-advanced/);
  }
}
async function endpoints(){
  const {api,host}=setup(),h=host();let changed=0,calculated;
  const options={start_s:12,duration_s:45};
  const row={lead:'II',points:[],valid:true,q_ms:-35,t_ms:340,automatic:{q_ms:-35,t_ms:340}};
  api.mountRetained(h,{sessionKey:['A'],contextCurrent:()=>true,duration:90,options,
    compute:async next=>({advanced:{options:next,basis:'a',qtd:{leads:[row]}},derivatives:{}}),
    onChange:x=>{changed++;calculated=x},onPrint(){},onLocate(){}});
  h.get('form').onsubmit({preventDefault(){}});await tick();assert.equal(changed,1);
  h.get('[data-t]').value='350';h.get('[data-t]').oninput();
  assert.equal(api.pending(),true);h.buttons[1].onclick();assert.match(h.get('.am-status').textContent,/先应用/);
  const select=h.get('[data-am-lead]');select.value='V1';select.onchange({target:select});assert.equal(select.value,'II');
  const next=host();api.mountRetained(next,{sessionKey:['A'],contextCurrent:()=>true,options:calculated});
  assert.equal(next.replacement,h);assert.equal(h.get('[data-t]').value,'350');
  h.get('[data-discard-settings]').onclick();assert.equal(h.get('[data-discard-settings]').hidden,true);assert.equal(api.pending(),false);
}
async function staleResult(){
  const {api,host}=setup(),h=host();let valid=true,calls=0;
  api.mountRetained(h,{sessionKey:['A'],contextCurrent:()=>true,isCurrent:()=>valid,options:{},duration:90,
    compute:async options=>{calls++;return {advanced:{options,basis:'a',qtd:{leads:[]}},derivatives:{}}},onChange(){},onPrint(){},onLocate(){}});
  const form=h.get('form');form.onsubmit({preventDefault(){}});await tick();assert.equal(h.get('.am-results').hidden,false);
  valid=false;form.oninput();assert.equal(api.pending(),true);
  h.get('[data-discard-settings]').onclick();assert.equal(api.pending(),false);
  assert.equal(h.get('.am-results').hidden,true);assert.match(h.get('.am-status').textContent,/旧结果保持隐藏/);
  form.onsubmit({preventDefault(){}});await tick();assert.equal(calls,1);assert.match(h.get('.am-status').textContent,/载入最新版本/);
}
(async()=>{for(const mode of ['discard','success','failed','detached','basis','replaced','clear'])await scenario(mode);await gates();await endpoints();await staleResult();console.log('advanced session: 7 lifecycle scenarios and 5 output-entry gates passed; endpoint switch and stale-result protection passed');})().catch(e=>{console.error(e);process.exit(1)});
