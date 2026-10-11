'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),Reads=require('../static/js/read-requests.js');
const gate=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}};
const tick=()=>new Promise(r=>setImmediate(r));
(async()=>{
 const reads=Reads.create();let calls=0;const early=new AbortController();early.abort();
 await assert.rejects(reads.read('A','same',()=>{calls++;return {}},'',early.signal),{name:'AbortError'});assert.equal(calls,0);assert.equal(reads.pendingCount(),0);
 const shared=gate(),a=new AbortController(),b=new AbortController();let transport;
 const first=reads.read('A','same',s=>{calls++;transport=s;return shared.promise},'',a.signal),firstRejected=assert.rejects(first,{name:'AbortError'});
 const second=reads.read('A','same',()=>{throw Error('must deduplicate')},'',b.signal);await tick();a.abort();await firstRejected;assert(!transport.aborted);shared.resolve({values:[7]});assert.deepEqual(await second,{values:[7]});assert.equal(reads.pendingCount(),0);
 // No AbortSignal support in a transport still cannot deliver its late result.
 const old=gate(),ca=new AbortController(),cb=new AbortController();let oldTransport;
 const one=reads.read('A','retry',s=>{oldTransport=s;return old.promise},'',ca.signal),two=reads.read('A','retry',()=>old.promise,'',cb.signal);
 const oneRejected=assert.rejects(one,{name:'AbortError'}),twoRejected=assert.rejects(two,{name:'AbortError'});await tick();ca.abort();cb.abort();await Promise.all([oneRejected,twoRejected]);assert(oldTransport.aborted);assert.equal(reads.pendingCount(),0);
 const newer=gate(),retry=reads.read('A','retry',()=>newer.promise);await tick();old.resolve({old:true});await tick();assert.equal(reads.pendingCount(),1,'late cleanup removed new same-key transport');newer.resolve({new:true});assert.deepEqual(await retry,{new:true});assert.equal(reads.pendingCount(),0);
 // Completion/cancellation race: completed consumers stay detached, cancelled consumers reject.
 const racing=gate(),signal=new AbortController();const race=reads.read('A','race',()=>racing.promise,'',signal.signal),raceRejected=assert.rejects(race,{name:'AbortError'});await tick();racing.resolve({stale:true});signal.abort();await raceRejected;await tick();assert.equal(reads.pendingCount(),0);
 const completedSignal=new AbortController(),completed=await reads.read('A','complete',async()=>({ok:true}),'',completedSignal.signal);completedSignal.abort();assert.deepEqual(completed,{ok:true});assert.equal(reads.pendingCount(),0);
 // Run the real api() adapter, rather than a test stub which merely respects signal.
 const source=fs.readFileSync('static/js/app.js','utf8'),adapter=source.slice(source.indexOf('async function api('),source.indexOf('\nfunction toast('));
 const requests=[],state={caseId:null,caseRequestId:0,currentPage:'dashboard',workspaceEpoch:'test'};
 const context=vm.createContext({state,ECGReadRequests:Reads.create(),fetch:(path,options)=>{const g=gate();requests.push({path,options,...g});return g.promise}});vm.runInContext(adapter,context);
 const external=new AbortController(),request=context.api('/api/health',{signal:external.signal}),reject=assert.rejects(request,{name:'AbortError'});await tick();external.abort();await reject;assert(requests[0].options.signal.aborted);
 const live=context.api('/api/health');await tick();requests[0].resolve({ok:true,headers:{get:()=> 'application/json'},json:async()=>({old:true})});await tick();assert.equal(context.ECGReadRequests.pendingCount(),1);requests[1].resolve({ok:true,headers:{get:()=> 'application/json'},json:async()=>({fresh:true})});assert.equal((await live).fresh,true);
 const readC=new AbortController(),writeC=new AbortController();const read=context.api('/api/health',{signal:readC.signal}),readRejected=assert.rejects(read,{name:'AbortError'});await tick();const write=context.api('/api/test-write',{method:'POST',signal:writeC.signal,body:'{}'});await tick();await readRejected;assert.strictEqual(requests[3].options.signal,writeC.signal);assert(!writeC.signal.aborted,'read cancellation aborted write');requests[3].resolve({ok:true,headers:{get:()=> 'application/json'},json:async()=>({saved:true})});assert.equal((await write).saved,true);
 console.log('External signals: pre-abort, separate subscribers, shared survival, all-cancel/retry, late same-key cleanup, completion race, real api transport and write independence passed');
})().catch(e=>{console.error(e);process.exitCode=1});
