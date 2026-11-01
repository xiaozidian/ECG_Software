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
 // A report save changes curation, not the source of a visible strip. Reads
 // begun both before and during autosave must survive its completion.
 const reportRequests=[],reportState={caseId:'C01',caseRequestId:1,currentPage:'report'};
 const reportContext=vm.createContext({state:reportState,ECGReadRequests:Reads.create(),fetch:(path,options)=>{const g=gate();reportRequests.push({path,options,...g});return g.promise}});vm.runInContext(adapter,reportContext);
 const response=value=>({ok:true,headers:{get:()=> 'application/json'},json:async()=>value});
 const strip=reportContext.api('/api/cases/C01/report-strip').catch(e=>({error:e.name}));await tick();
 const saving=reportContext.api('/api/cases/C01/report',{method:'PUT',body:'{}'});await tick();
 assert(!reportRequests[0].options.signal.aborted,'autosave cancelled an already-loading report strip');
 const wave=reportContext.api('/api/cases/C01/waveform').catch(e=>({error:e.name}));await tick();
 reportRequests[1].resolve(response({version:2}));await saving;
 assert(!reportRequests[0].options.signal.aborted&&!reportRequests[2].options.signal.aborted,'autosave completion cancelled visible waveform reads');
 reportRequests[0].resolve(response({strip:true}));reportRequests[2].resolve(response({wave:true}));
 assert.equal((await strip).strip,true);assert.equal((await wave).wave,true);
 // A failed save must not replace a waveform with an unrelated cancellation.
 const retryRead=reportContext.api('/api/cases/C01/report-strip').catch(e=>({error:e.name}));await tick();
 const failedSave=reportContext.api('/api/cases/C01/report',{method:'PUT',body:'{}'});const rejectedSave=assert.rejects(failedSave,/save conflict/);await tick();
 reportRequests[4].resolve({ok:false,headers:{get:()=> 'application/json'},json:async()=>({error:'save conflict'})});await rejectedSave;
 assert(!reportRequests[3].options.signal.aborted);reportRequests[3].resolve(response({strip:true}));assert.equal((await retryRead).strip,true);
 // Scope changes still cancel old reads, even after report-only writes.
 const oldPage=reportContext.api('/api/cases/C01/waveform').catch(e=>({error:e.name}));await tick();reportState.currentPage='review';
 const newPage=reportContext.api('/api/cases/C01/overview');await tick();assert.equal((await oldPage).error,'AbortError');
 reportRequests[6].resolve(response({current:true}));assert.equal((await newPage).current,true);
 // Candidate and report acknowledgements must preserve the live raw read while
 // a fresh report-metadata request must not join its pre-write predecessor.
 for(const [path,method] of [['evidence-candidates','POST'],['evidence-candidates','PATCH'],['report-evidence/confirm','POST']]){
  const requests=[],state={caseId:'C01',caseRequestId:1,currentPage:'report'};
  const ctx=vm.createContext({state,ECGReadRequests:Reads.create(),fetch:(path,options)=>{const g=gate();requests.push({path,options,...g});return g.promise}});vm.runInContext(adapter,ctx);
  const raw=ctx.api('/api/cases/C01/waveform').catch(e=>({error:e.name}));await tick();
  const oldMetadata=ctx.api('/api/cases/C01/report-events');await tick();
  const writing=ctx.api('/api/cases/C01/'+path,{method,body:'{}'});await tick();
  assert(!requests[0].options.signal.aborted&&!requests[1].options.signal.aborted,'report-only evidence write cancelled visible source reads');
  requests[2].resolve(response({saved:true}));await writing;
  const freshMetadata=ctx.api('/api/cases/C01/report-events');await tick();
  assert.equal(requests.length,4,'post-write report read joined an obsolete pending projection');
  assert(!requests[0].options.signal.aborted,'report-only evidence acknowledgement cancelled source waveform');
  requests[1].resolve(response({status:'pending'}));requests[3].resolve(response({status:'confirmed'}));requests[0].resolve(response({wave:true}));
  assert.equal((await oldMetadata).status,'pending');assert.equal((await freshMetadata).status,'confirmed');assert.equal((await raw).wave,true);
 }
 console.log('External signals, real api transport, report/evidence write overlap, metadata freshness and navigation cancellation passed');
})().catch(e=>{console.error(e);process.exitCode=1});
