'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('static/js/morphology-workbench.js','utf8');
const code=source.slice(source.indexOf('  const densityBatches='),source.indexOf('  async function request('));
function setup(){
  const calls=[];let mode='ready';
  const api=async(url,opts)=>{
    const query=new URL(url,'http://synthetic.invalid').searchParams,body=JSON.parse(opts.body);calls.push({url,body,signal:opts.signal});
    if(opts.signal?.aborted)throw Object.assign(Error('cancelled'),{name:'AbortError'});
    if(mode==='error')throw Error('synthetic failure');
    const names=(query.get('leads')||query.get('lead')).split(','),common={population_samples:[200,400],source_total:2,revision:body.revision,case_id:url.split('/')[3],analysis_basis:body.analysis_basis,analysis_revision:body.analysis_revision,beat_revision:body.beat_revision};
    const items=names.map(lead=>({lead,bins:[1,2],sample_indices:[200,400]}));
    if(mode==='incomplete')items.pop();
    return names.length===1?{...items[0],...common}:{...common,items};
  };
  const scope=vm.createContext({api,URLSearchParams,structuredClone});
  vm.runInContext(code+'\nglobalThis.read=densityRead;',scope);
  const body={revision:2,beat_revision:2,analysis_basis:'math-basis',analysis_revision:4};
  const read=(lead,changes={})=>scope.read(changes.id||'math-A',new URLSearchParams({class_code:'N',lead,...changes.params}),{...body,...changes.body},{},changes.signal);
  return {calls,read,setMode:value=>mode=value};
}
async function run(){
  const h=setup(),signal=new AbortController().signal;
  const [a,b,c]=await Promise.all([h.read('II',{signal}),h.read('V1',{signal}),h.read('II',{signal})]);
  assert.equal(h.calls.length,1);assert.match(h.calls[0].url,/leads=II%2CV1/);
  assert.equal(a.lead,'II');assert.equal(b.lead,'V1');
  a.bins[0]=99;a.population_samples.push(999);a.sample_indices[0]=999;
  assert.equal(c.bins[0],1);assert.equal(c.sample_indices[0],200);assert.equal(c.population_samples.length,2);assert.equal(b.population_samples.length,2);
  const split=setup();await Promise.all(['II','V1','III'].map(l=>split.read(l)));
  assert.equal(split.calls.length,2);assert.match(split.calls[1].url,/lead=III/);
  for(const change of [{id:'math-B'},{body:{analysis_basis:'different'}},{body:{analysis_revision:5}},{body:{revision:3,beat_revision:3}},{body:{samples:[200]}},{body:{exclude_samples:[400]}},{body:{amplitude_limit:300}},{params:{gate:'1,2,3,4'}},{signal:new AbortController().signal}]){
    const isolated=setup();await Promise.all([isolated.read('II'),isolated.read('V1',change)]);assert.equal(isolated.calls.length,2,JSON.stringify(change));
  }
  for(const mode of ['incomplete','error']){
    const bad=setup();bad.setMode(mode);
    const values=await Promise.allSettled([bad.read('II'),bad.read('V1')]);
    assert.ok(values.every(v=>v.status==='rejected'),'partial batch was published');
    bad.setMode('ready');await Promise.all([bad.read('II'),bad.read('V1')]);assert.equal(bad.calls.length,2,'failed batch was cached');
  }
  const cancelled=setup(),controller=new AbortController();controller.abort();
  const values=await Promise.allSettled([cancelled.read('II',{signal:controller.signal}),cancelled.read('V1',{signal:controller.signal})]);
  assert.ok(values.every(v=>v.status==='rejected'&&v.reason.name==='AbortError'));
  console.log(JSON.stringify({passed:true,checks:16}));
}
run().catch(e=>{console.error(e);process.exitCode=1;});
