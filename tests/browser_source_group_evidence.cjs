'use strict';
const assert=require('node:assert/strict');
require('../static/js/occurrence-card.js');
const api=require('../static/js/source-group-evidence.js');
const tick=()=>new Promise(r=>setImmediate(r));
const gate=()=>{let resolve;return {promise:new Promise(r=>resolve=r),resolve:v=>resolve(v)}};
function fixture(loadWave){
 const nodes=new Map(),q=s=>{if(!nodes.has(s))nodes.set(s,{hidden:false,disabled:false,value:'',innerHTML:'',textContent:'',setAttribute(k,v){this[k]=v},replaceChildren(){this.innerHTML=''},setCustomValidity(v){this.error=v},reportValidity(){return !this.error}});return nodes.get(s)};
 const host={isConnected:true,hidden:true,innerHTML:'',querySelector:q,setAttribute(k,v){this[k]=v}};
 const item={sample_index:2000,target_samples:[2000,7000,18000],beat_count:3};let valid=true;
 api.mount(host,{item,loadWave,onLocate:t=>host.located=t,isCurrent:()=>valid});
 return {host,q,item,invalidate:()=>valid=false};
}
const wave=(value=1,stride=1)=>({start_s:7,duration_s:6,sample_rate_hz:200,stride,filter:'raw',leads:{II:[value,30,2],V1:[2,3,4],V5:[3,4,5]}});
(async()=>{
 let reads=[];let f=fixture(async(p,s)=>{reads.push({p,s});return wave()});await tick();
 assert.equal(reads[0].p.start,7);assert.equal(reads[0].p.duration,6);assert.equal(reads[0].p.filter,'raw');assert.match(f.q('[data-sg-status]').textContent,/第 1 \/ 3 源搏/);
 const unchanged=JSON.stringify(f.item);f.q('[data-sg-index]').value='3';f.q('[data-sg-go]').onclick();await tick();assert.equal(reads.at(-1).p.start,87);
 f.q('[data-sg-twelve]').onclick();await tick();assert.equal(reads.at(-1).p.leads.split(',').length,12);assert.equal(reads.at(-1).p.start,87);
 f.q('[data-sg-twelve]').onclick();await tick();assert.equal(reads.at(-1).p.leads.split(',').length,3);assert.equal(f.q('[data-sg-index]').value,'3');f.q('[data-sg-locate]').onclick();assert.equal(f.host.located,90);assert.equal(JSON.stringify(f.item),unchanged);
 f.q('[data-sg-index]').value='4';f.q('[data-sg-go]').onclick();assert.match(f.q('[data-sg-index]').error,/1–3/);assert.equal(reads.length,4);
 const old=gate(),newest=gate();let n=0;f=fixture(()=>++n===1?old.promise:newest.promise);f.q('[data-sg-next]').onclick();newest.resolve(wave(22));await tick();const html=f.q('[data-sg-wave]').innerHTML;old.resolve(wave(99));await tick();assert.equal(f.q('[data-sg-wave]').innerHTML,html);assert.match(f.q('[data-sg-status]').textContent,/第 2 \/ 3/);
 const late=gate();f=fixture(()=>late.promise);f.invalidate();late.resolve(wave());await tick();assert.equal(f.q('[data-sg-wave]').innerHTML,'');
 f=fixture(async()=>wave(1,4));await tick();assert.equal(f.q('[data-sg-wave]').innerHTML,'');assert.equal(f.q('[data-sg-retry]').hidden,false);assert.match(f.q('[data-sg-status]').textContent,/不能作为本区证据/);
 api.clear();assert.equal(f.host.hidden,true);console.log('source excerpts: every target reachable, unchanged group, raw stride guard, twelve-return, stale and cancelled reads passed');
})().catch(e=>{console.error(e);process.exitCode=1});
