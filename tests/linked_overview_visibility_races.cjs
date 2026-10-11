'use strict';
// Independent synthetic audit. No browser, server, patient data, or source writes.
const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs'),crypto=require('node:crypto');
const base=path.resolve(__dirname,'..');
const file=path.join(base,'static/js/overview-linked-view.js');
const loadedSha256=crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const L=require(file),E=require(path.join(base,'static/js/overview-engine.js'));
const C=require(path.join(base,'static/js/linked-selection.js'));
global.document={activeElement:null};global.innerHeight=800;global.innerWidth=1280;
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const rows=E.decode({duration_s:10,rows:[[0,0,'N'],[160,800,'N'],[360,1000,'S'],[500,700,'X'],[700,0,'N'],[880,900,'N'],[1060,900,'N']]});
const scope={caseId:'synthetic',caseToken:1,analysis_basis:'synthetic-basis',analysis_revision:7,beatRevision:3};
function setup(mini='absent'){
  const state={caseId:'synthetic',caseRequestId:1,currentPage:'review',filter:'raw'},jobs=[],nodes=new Map(),drawn=[];
  global.ECGLinkedSelection=C.create({getActiveCase:()=>({caseId:state.caseId,caseToken:state.caseRequestId}),onSubscriberError:error=>{throw error;}});
  if(mini!=='absent'){
    nodes.set('#scatterSelectionList',{scrollTop:0,clientHeight:mini==='hidden'?0:154,getClientRects:()=>mini==='hidden'?[]:[{}],getBoundingClientRect:()=>({top:mini==='offscreen'?1000:0,bottom:mini==='offscreen'?1154:154,left:0,right:300})});
    nodes.set('#scatterSelectionEmpty',{hidden:false,innerHTML:''});
    nodes.set('#scatterSelectionVirtual',{hidden:false,innerHTML:'',style:{},querySelectorAll(){return [...this.innerHTML.matchAll(/data-strip-canvas="(\d+)"/g)].map(m=>({dataset:{stripCanvas:m[1]}}));},querySelector:()=>null});
  }
  const qs=s=>{
    if(s.startsWith('#ovLinkedDensity')||s.startsWith('[data-ov-density-count'))return null;
    if(['#scatterSelectionList','#scatterSelectionEmpty','#scatterSelectionVirtual'].includes(s))return nodes.get(s)||null;
    if(!nodes.has(s))nodes.set(s,{textContent:'',dataset:{}});return nodes.get(s);
  };
  const controller=L.create({getState:()=>state,api:(url,options)=>new Promise((resolve,reject)=>jobs.push({url,body:JSON.parse(options.body),signal:options.signal,resolve,reject})),qs,esc:String,formatTime:String,formatNumber:String,drawChanged(){},drawStrip(canvas,item){drawn.push(item?.marker);}});
  controller.attach(scope,rows);
  return {state,jobs,nodes,drawn,controller,central:global.ECGLinkedSelection};
}
const strips=x=>x.jobs.filter(j=>j.url.includes('waveform-strips'));
function resolveDensity(job){
  const members=job.body.samples??rows.map(r=>r.sample_index);
  job.resolve({analysis_basis:job.body.analysis_basis,analysis_revision:job.body.analysis_revision,beat_revision:job.body.revision,population_samples:members,total:members.length,included:members.length,skipped_edges:0,lead:new URL(job.url,'http://synthetic.invalid').searchParams.get('lead'),bins:[members.length]});
}
function resolveStrip(job,marker){job.resolve({analysis_basis:job.body.analysis_basis,analysis_revision:job.body.analysis_revision,beat_revision:job.body.revision,items:job.body.sample_indices.map(sample_index=>({sample_index,marker}))});}
(async()=>{
  const observations=[],passed=[];
  let x=setup();
  const ii=x.jobs.find(j=>j.url.endsWith('lead=II')),v1=x.jobs.find(j=>j.url.endsWith('lead=V1'));
  ii.reject(Error('synthetic II failure'));await tick();
  resolveDensity(v1);await tick();
  const d=x.controller.inspect();
  observations.push({id:'density-sibling-after-failure',phase:d.phase,displayedLeads:Object.keys(d.density),issuePresent:d.phase==='error'&&Object.keys(d.density).length>0});
  x.controller.dispose();
  x=setup('visible');
  const oldStrip=strips(x)[0];
  const filterGeneration=x.controller.inspect().generation;
  x.state.filter='filtered';x.controller.renderMini();
  const beforeReject=strips(x).length;
  const newStrip=strips(x).find(j=>j.body.filter==='filtered');assert(newStrip,'filter change must start a new request');resolveStrip(newStrip,'filtered');await tick();
  oldStrip.reject(Error('synthetic late raw-filter failure'));await tick();x.controller.renderMini();
  assert.equal(x.controller.inspect().generation,filterGeneration);assert.equal(x.nodes.get('#scatterSelectionVirtual').innerHTML.includes('读取失败，点击重试'),false);assert(x.drawn.length&&x.drawn.every(m=>m==='filtered'));assert.equal(strips(x).filter(j=>j.body.filter==='filtered').length,1);
  passed.push('filter-late-rejection-cannot-poison-new-waveform-or-selection');
  observations.push({id:'old-filter-rejection-poisons-new-filter',rawRequestSamples:oldStrip.body.sample_indices,requestsBeforeReject:beforeReject,requestsAfterReject:strips(x).length,newFilterRequests:strips(x).filter(j=>j.body.filter==='filtered').length,failureVisible:x.nodes.get('#scatterSelectionVirtual').innerHTML.includes('读取失败，点击重试'),issuePresent:strips(x).filter(j=>j.body.filter==='filtered').length===0&&x.nodes.get('#scatterSelectionVirtual').innerHTML.includes('读取失败，点击重试')});
  x.controller.dispose();
  x=setup('visible');const staleRaw=strips(x)[0],successGeneration=x.controller.inspect().generation;
  x.state.filter='filtered';x.controller.renderMini();const currentFiltered=strips(x).find(j=>j.body.filter==='filtered');assert(currentFiltered);resolveStrip(currentFiltered,'filtered');await tick();resolveStrip(staleRaw,'stale-raw');await tick();x.controller.renderMini();
  assert.equal(x.controller.inspect().generation,successGeneration);assert(x.drawn.length&&x.drawn.every(m=>m==='filtered'));
  x.state.filter='raw';x.controller.renderMini();assert.equal(strips(x).filter(j=>j.body.filter==='raw').length,2,'stale raw success must not populate the old filter cache');
  passed.push('filter-late-success-cannot-draw-or-cache-old-waveform');x.controller.dispose();
  x=setup('visible');x.controller.select([160,880]);const leaving=strips(x).at(-1),beforeReturn=strips(x).length;
  x.state.currentPage='edit';x.central.cancelPresentationLanes('overview.');
  x.state.currentPage='review';x.controller.renderMini();x.controller.refresh();
  observations.push({id:'return-waits-for-cancelled-transport',cancelledSignal:leaving.signal.aborted,stripRequestsBefore:beforeReturn,stripRequestCount:strips(x).length,selectionKind:x.controller.inspect().kind,issuePresent:leaving.signal.aborted&&strips(x).length===beforeReturn});
  assert.deepEqual(x.controller.inspect().samples,[160,880]);assert.equal(x.controller.inspect().kind,'samples');assert.equal(strips(x).length,beforeReturn+1);x.controller.dispose();
  x=setup('hidden');
  observations.push({id:'zero-height-hidden-minis-still-fetch',viewportHeight:0,viewportRects:0,stripRequestCount:strips(x).length,fetchedSamples:strips(x)[0]?.body.sample_indices||[],issuePresent:strips(x).length>0});
  x.controller.dispose();
  x=setup('offscreen');
  const beforeVisible=strips(x).length;
  x.nodes.get('#scatterSelectionList').getBoundingClientRect=()=>({top:0,bottom:154,left:0,right:300});
  x.controller.renderMini();
  observations.push({id:'offscreen-minis-defer-until-visible',requestsOffscreen:beforeVisible,requestsOnScreen:strips(x).length,issuePresent:beforeVisible!==0||strips(x).length!==1});x.controller.dispose();
  x=setup('visible');x.controller.select([]);const emptyJobs=strips(x).length,emptyGeneration=x.controller.inspect().generation;
  assert.deepEqual(x.controller.inspect().samples,[]);assert.equal(x.nodes.get('#scatterSelectionVirtual').innerHTML,'');assert.equal(x.nodes.get('#scatterSelectionVirtual').hidden,true);
  x.controller.clear();assert.equal(x.controller.inspect().kind,'none');assert.deepEqual(x.controller.inspect().samples,rows.map(r=>r.sample_index));assert(x.controller.inspect().generation>emptyGeneration);assert.equal(strips(x).length,emptyJobs+1);
  passed.push('explicit-empty-card-list-and-clear-global-restart');x.controller.dispose();
  assert.equal(observations[0].phase,'error');assert.deepEqual(observations[0].displayedLeads,[]);
  for(const observation of observations)assert.equal(observation.issuePresent,false,observation.id);
  const endSha256=crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
  assert.equal(loadedSha256,endSha256,'source changed during synthetic verification');
  console.log(JSON.stringify({passed:true,total:passed.length+observations.length,tests:[...passed,...observations.map(o=>o.id)],kind:'independent-synthetic-audit',productionModule:'overview-linked-view.js',sourceSha256:loadedSha256,endSha256,sourceStable:loadedSha256===endSha256,transportIgnoresAbort:true,noNetwork:true,passedTests:passed,observations},null,2));
})().catch(error=>{console.error(error);process.exitCode=1;});
