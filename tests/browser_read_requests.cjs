'use strict';
const assert=require('node:assert/strict');
const Reads=require('../static/js/read-requests.js');
const gate=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  const reads=Reads.create(),g=gate();let requests=0;
  const build=async()=>{requests++;return g.promise};
  const first=reads.read('caseA:r1:review','waveform',build,'wave');
  const second=reads.read('caseA:r1:review','waveform',build,'wave');
  await tick();assert.equal(requests,1);g.resolve({leads:{II:[1,2]}});
  const [a,b]=await Promise.all([first,second]);a.leads.II[0]=99;assert.equal(b.leads.II[0],1);
  assert.equal(reads.pendingCount(),0);
  await reads.read('caseA:r1:review','waveform',async()=>{requests++;return {fresh:true}},'wave');
  assert.equal(requests,2,'completed clinical results must not be cached');

  // An uncooperative transport (including the static demo) cannot return a
  // cancelled result even if it ignores AbortSignal and eventually succeeds.
  const old=gate();let signal;
  const stale=reads.read('caseA:r1:review','start=0',s=>{signal=s;return old.promise},'wave');
  const rejected=assert.rejects(stale,{name:'AbortError'});
  await tick();const latest=reads.read('caseA:r1:review','start=10',async()=>({start:10}),'wave');
  assert.equal(signal.aborted,true);old.resolve({start:0});await rejected;
  assert.deepEqual(await latest,{start:10});

  for(const scope of ['caseB:r1:review','caseB:r2:review','caseB:r2:stt']){
    const pending=gate();let owned;
    const previous=reads.read('caseA:r1:review','result',s=>{owned=s;return pending.promise});
    const cancelled=assert.rejects(previous,{name:'AbortError'});await tick();
    assert.deepEqual(await reads.read(scope,'result',async()=>({scope})),{scope});
    assert.equal(owned.aborted,true);pending.resolve({old:true});await cancelled;
  }
  await assert.rejects(reads.read('caseA:r1:review','offline',async()=>{throw Error('offline')}),/offline/);
  assert.equal(reads.pendingCount(),0);
  assert.deepEqual(await reads.read('caseA:r1:review','offline',async()=>({retry:true})),{retry:true});
  const pending=gate();const cancelled=reads.read('caseA:r1:review','result',()=>pending.promise);
  const rejection=assert.rejects(cancelled,{name:'AbortError'});await tick();reads.clear();pending.resolve({old:true});await rejection;
  assert.equal(reads.pendingCount(),0);
})().catch(error=>{console.error(error);process.exitCode=1});
