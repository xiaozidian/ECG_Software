// Run the shipped export path against controlled network completion and cancellation.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('static/js/clinical-ui.js','utf8');
const elements=new Map(['#downloadReport','#cancelReportExport'].map(key=>[key,{setAttribute(name,value){this[name]=value;}}]));
const state={caseId:'math-A',caseRequestId:1,report:{version:4,review_revision:2}};
const gate=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return{promise,resolve,reject};};
let reads=[],pdfs=[],downloads=0,notices=[],readyLink=null,revoked=[];
elements.get('#downloadReport').after=link=>{readyLink=link;link.isConnected=true;};
const ctx=vm.createContext({state,AbortController,URLSearchParams,resolveWorkstationLeave:async()=>true,qs:key=>elements.get(key),
  ECGReportRange:{assertApplied(){}},ECGReportConsistency:{sameBase:(a,b)=>a.version===b.version&&a.review_revision===b.review_revision},
  api:(url,options)=>{const g=gate();reads.push({...g,url,options});return g.promise;},
  fetch:(url,options)=>{const g=gate();pdfs.push({...g,url,options});return g.promise;},
  document:{createElement:()=>({events:{},addEventListener(name,fn){this.events[name]=fn;},click(){let prevented=false;this.events.click?.({preventDefault(){prevented=true;}});if(!prevented)downloads++;},remove(){this.isConnected=false;}})},URL:{createObjectURL:()=> 'blob:math',revokeObjectURL(url){revoked.push(url);}},
  setTimeout(){},clearTimeout(){},handleError:error=>notices.push(error.message),toast:text=>notices.push(text)});
vm.runInContext(source.slice(source.indexOf('  async function downloadReport('),source.indexOf('  async function printHtml(')),ctx);
const tick=()=>new Promise(r=>setImmediate(r));
const meta=()=>({...state.report});
const good=()=>({ok:true,blob:async()=>({math:true})});
(async()=>{
  const first=ctx.downloadReport();await tick();assert.equal(elements.get('#downloadReport').disabled,true);assert.equal(elements.get('#cancelReportExport').hidden,false);
  await ctx.downloadReport();assert.equal(reads.length,1,'duplicate click started metadata');
  reads[0].resolve(meta());await tick();assert.equal(pdfs.length,1);
  await ctx.downloadReport();assert.equal(pdfs.length,1,'duplicate click started PDF');
  pdfs[0].resolve(good());await first;assert.equal(downloads,1);assert(readyLink.isConnected,'ready PDF must be attached for WebKit');assert.equal(readyLink.textContent,'保存已生成 PDF');assert.equal(elements.get('#downloadReport').disabled,false);

  const cancelled=ctx.downloadReport();await tick();ctx.cancelReportExport(true);assert(reads[1].options.signal.aborted);assert.equal(notices.length,1);
  const replacement=ctx.downloadReport();await tick();reads[1].resolve(meta());await cancelled;
  assert.equal(elements.get('#downloadReport').disabled,true,'old completion cleared new job');assert.equal(pdfs.length,1,'cancelled metadata started PDF');
  reads[2].resolve(meta());await tick();ctx.cancelReportExport();assert(pdfs[1].options.signal.aborted);
  pdfs[1].resolve(good());await replacement;assert.equal(downloads,1,'cancelled PDF downloaded');

  const failure=ctx.downloadReport();await tick();reads[3].resolve(meta());await tick();pdfs[2].resolve({ok:false,status:503,json:async()=>({error:'math retry'})});
  await assert.rejects(failure,/math retry/);assert.equal(elements.get('#downloadReport').disabled,false);assert.equal(state.report.version,4);
  const retry=ctx.downloadReport();await tick();reads[4].resolve(meta());await tick();pdfs[3].resolve(good());await retry;assert.equal(downloads,2);

  const completedLink=readyLink;state.reportDirty=true;completedLink.click();assert.equal(downloads,2,'changed report saved an obsolete blob');assert.equal(completedLink.isConnected,false);assert(revoked.length>0);state.reportDirty=false;
  const obsolete=ctx.downloadReport();await tick();reads[5].resolve(meta());await tick();state.caseId='math-B';state.caseRequestId++;state.report=null;
  ctx.cancelReportExport();pdfs[4].resolve(good());await obsolete;assert.equal(downloads,2,'prior case downloaded');
  state.report={version:1,review_revision:1};
  const revised=ctx.downloadReport();await tick();reads[6].resolve(meta());await tick();state.report.version++;
  pdfs[5].resolve(good());await assert.rejects(revised,/导出期间报告已变化/);assert.equal(downloads,2);
  assert.equal(elements.get('#cancelReportExport').hidden,true);assert.equal(elements.get('#downloadReport')['aria-busy'],'false');
  const app=fs.readFileSync('static/js/app.js','utf8');assert.match(app,/if\(typeof clinicalUI!=='undefined'\)clinicalUI\.cancelReportExport\(\)/);
  assert.match(source,/if\(leavingReport&&state.currentPage!=='report'\)clinicalUI\.cancelReportExport\(\)/);
  console.log('export duplicate, cancellation, retry, stale completion and case isolation passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
