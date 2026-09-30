const assert=require('node:assert/strict');
const {create}=require('../static/js/waveform-loader.js');
const tick=()=>new Promise(r=>setTimeout(r,0));
const gate=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}};
const caught=promise=>promise.then(value=>({value}),error=>({error:error.message}));
async function backlog(prune){
  const batches=[],waiting=[];
  const loader=create((group,inputs)=>{const g=gate();batches.push(inputs);waiting.push({g,inputs});return g.promise});
  const jobs=[];
  for(let i=0;i<48;i++)jobs.push(caught(loader.get('active-'+i,'A',i,{owner:'occurrence'})));
  await tick();await tick();assert.equal(batches.length,2);
  for(let view=0;view<20;view++)for(let i=0;i<24;i++)jobs.push(caught(loader.get('old-'+view+'-'+i,'A',100+view*24+i,{owner:'occurrence'})));
  for(let i=0;i<24;i++)jobs.push(caught(loader.get('new-'+i,'A',1000+i,{owner:'occurrence'})));
  if(prune)loader.retain('occurrence',Array.from({length:24},(_,i)=>'new-'+i));
  let resolved=0;
  while(resolved<waiting.length){const entry=waiting[resolved++];entry.g.resolve(entry.inputs);await tick();await tick();}
  const results=await Promise.all(jobs);
  return {requests:batches.length,currentViewportBatch:batches.findIndex(batch=>batch.includes(1000))+1,cancelledBeforeRequest:results.filter(x=>x.error).length,completed:results.filter(x=>'value'in x).length};
}
async function main(which){
  if(which==='benchmark'){console.log(JSON.stringify({scope:'deterministic scheduler simulation; no browser or network timing',fifo:await backlog(false),currentViewport:await backlog(true)}));return}
  if(which==='backlog'){
    const result=await backlog(true);assert.deepEqual(result,{requests:3,currentViewportBatch:3,cancelledBeforeRequest:480,completed:72});return;
  }
  const calls=[],waiters=[];
  const loader=create((group,inputs)=>{calls.push([group,inputs]);const g=gate();waiters.push(g);return g.promise},{batchSize:1,concurrency:1});
  const occupied=caught(loader.get('running','A',0,{owner:'occurrence'}));await tick();await tick();
  const old=caught(loader.get('old','A',1,{owner:'occurrence'}));
  if(which==='shared-report'){
    const report=loader.get('old','A',1);loader.retain('occurrence',[]);
    waiters[0].resolve([0]);await tick();await tick();assert.deepEqual(calls[1],['A',[1]]);waiters[1].resolve([1]);assert.equal(await report,1);assert.equal((await old).value,1);
  }else if(which==='multiple-owners'){
    const second=loader.get('old','A',1,{owner:'second'});loader.retain('occurrence',[]);
    waiters[0].resolve([0]);await tick();await tick();waiters[1].resolve([1]);assert.equal(await second,1);assert.equal((await old).value,1);
  }else if(which==='reenter'){
    loader.retain('occurrence',[]);const fresh=caught(loader.get('old','A',2,{owner:'occurrence'}));
    assert.match((await old).error,/视野/);waiters[0].resolve([0]);await tick();await tick();assert.deepEqual(calls[1],['A',[2]]);waiters[1].resolve([2]);assert.equal((await fresh).value,2);
  }else if(which==='inflight'){
    loader.retain('occurrence',['running']);assert.equal(calls.length,1);assert.match((await old).error,/视野/);
    const shared=loader.get('running','A',0,{owner:'occurrence'});waiters[0].resolve([0]);assert.equal(await shared,0);assert.equal((await occupied).value,0);assert.equal(calls.length,1);
  }else if(which==='priority'){
    const report=caught(loader.get('report','report',3));const latest=caught(loader.get('new','A',2,{owner:'occurrence'}));loader.retain('occurrence',['new']);
    waiters[0].resolve([0]);await tick();await tick();assert.deepEqual(calls[1],['A',[2]]);waiters[1].resolve([2]);await tick();await tick();assert.deepEqual(calls[2],['report',[3]]);waiters[2].resolve([3]);assert.equal((await latest).value,2);assert.equal((await report).value,3);await old;
  }else if(which==='clear'){
    loader.clear();loader.retain('occurrence',[]);const fresh=caught(loader.get('running','A',7,{owner:'occurrence'}));waiters[0].resolve([0]);await tick();await tick();waiters[1].resolve([7]);assert.equal((await fresh).value,7);assert.match((await occupied).error,/依据/);await old;
  }else throw Error('Unknown test '+which);
}
main(process.argv[2]||'backlog').catch(error=>{console.error(error);process.exitCode=1});
