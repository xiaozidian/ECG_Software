'use strict';
// Actual report DOM and shipped save/A4/export functions with isolated mathematical
// inputs. All network is blocked; this does not exercise clinical or server PDFs.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {chromium}=require(process.env.ECG_PLAYWRIGHT_CORE || process.env.PLAYWRIGHT_CORE || 'playwright-core');
const root=path.resolve(__dirname,'..'),read=p=>fs.readFileSync(path.join(root,p),'utf8');
const ui=read('static/js/clinical-ui.js'),workflow=read('static/js/clinical-workflow.js');
function region(source,a,b){const i=source.indexOf(a),j=source.indexOf(b,i);assert(i>=0&&j>i,`Shipped source region missing: ${a}`);return source.slice(i,j);}
const shipped=[
  region(ui,'  function composition(){','  function svg(wave,'),
  region(ui,'  function renderReportShell(){','  async function reloadReport('),
  region(ui,"  async function save(status='draft')",'  function gainHtml('),
  region(ui,'  async function selectedReportWaves(id){','  async function reportReviewWave('),
  region(ui,'  async function readPaperEvidence(id){','  async function printHtml('),
].join('\n');
const preflight=region(workflow,'  function renderPreflight()','  function decision(');
const assets=['static/js/report-workspace.js','static/css/report-workspace.css','static/css/clinical-review-tools.css','static/js/clinical-ui.js','static/js/clinical-workflow.js','static/js/report-range-editor.js','static/js/analysis-consistency.js','static/js/report-consistency.js','static/js/report-sections.js','static/js/report-engine.js'];
const out=path.resolve(process.env.ECG_REPORT_SIMPLIFIED_EVIDENCE||'/tmp/ecg-report-simplified-'+new Date().toISOString().replace(/[:.]/g,'-'));
const result={scope:'mathematical DOM fixture; actual shipped report functions; no services or clinical source data',checks:[],page_errors:[],network:[],assets:assets.map(p=>({path:p,sha256:crypto.createHash('sha256').update(read(p)).digest('hex')})),browser_closed:false};
const save=()=>fs.writeFileSync(path.join(out,'results.json'),JSON.stringify(result,null,2)+'\n');
function record(name){result.checks.push(name);save();console.log('PASS '+name);}
const scripts=['static/js/report-engine.js','static/js/report-sections.js','static/js/report-consistency.js','static/js/analysis-consistency.js','static/js/report-range-editor.js','static/js/report-workspace.js'].map(p=>`<script>${read(p)}</script>`).join('');
function fixture(){return `<!doctype html><meta charset="utf-8"><title>Mathematical report simplification</title><style>body{margin:0;font:14px system-ui}*{box-sizing:border-box}button,input{font:inherit}#page-report{padding:12px}#reportV2Content{height:640px}.report-conclusion-dock{background:white}#conclusionEditor{width:100%}#fixtureRange{position:fixed;bottom:0;right:0;width:380px;max-height:240px;overflow:auto;background:white;z-index:100}#fixtureRange:empty{display:none}${read('static/css/clinical-review-tools.css')}${read('static/css/report-workspace.css')}</style>
<main id="mainContent"><section id="page-report" class="active"><header><button id="saveReport">保存</button><button id="approveReport">审核</button><button id="returnReport">返回</button><button id="downloadReport">导出 PDF</button><button id="cancelReportExport" hidden>取消导出</button><span id="reportStatus"></span><span id="reportVersion"></span></header><div id="reportV2"><div id="reportV2Nav"></div><p id="reportV2Notice"></p><details id="reportPreflightDisclosure" open><summary>审核前检查</summary><article id="reportPreflight" tabindex="-1"></article></details><div id="reportV2Content"></div></div><article class="report-conclusion-dock"><header class="report-panel-heading"><strong>报告结论</strong><span id="reportSaveState"></span></header><textarea id="conclusionEditor" maxlength="12000"></textarea><footer>数学夹具</footer></article><span id="reportProvenance"></span><div id="fixtureRange"></div></section></main>${scripts}<script>
const clone=x=>structuredClone(x),qs=s=>document.querySelector(s),$=qs,esc=x=>String(x??''),escapeHtml=esc,formatElapsed=n=>'D1 '+Number(n).toFixed(3);
const originalText='保留的手写数学结论。人工复核示例。',originalUsage={namespace:'synthetic.original',catalog_version:'v1',catalog_hash:'a'.repeat(64),stable_id:'original.review',inserted_text:'人工复核示例。',approval:'draft',inserted_at:'2026-01-01T00:00:00Z',source:{title:'Original synthetic fixture'},license:{name:'MIT'},review:{status:'draft'}};
const picks=[{event_id:'math-first',basis_version:'current',caption:'原数学图注',leads:['II','V1','V5'],manual_start_s:1,manual_end_s:8},{event_id:'math-old',basis_version:'old',caption:'旧依据图注仍保留',leads:['II']}];
const initialComposition={schema_version:2,page_selection_version:1,included_pages:['summary','event_strips','hrv_time','st_events'],include_hrv:true,fast_slow_mode:'both',selected_events:clone(picks),terminology_usages:[clone(originalUsage)],category_reviews:{},diagnosis_blocks:[{key:'manual',manual:true,text:originalText}],strip_defaults:{leads:['II','V1','V5'],duration_s:7},paper:{size:'A4',orientation:'portrait'}};
const basis={analysis_basis:'synthetic-source-v1',analysis_revision:4},fullScope={case_id:'fixture',source_digest:'mathematical-only',data_version:'math-v1',beat_revision:4,...basis};
const state={caseId:'fixture',caseRequestId:7,currentPage:'report',privacyRequestId:0,reportDirty:false,reportStale:false,reportSaving:false,reportCategoryPending:[],report:{version:3,review_revision:4,status:'draft',conclusion:originalText,composition:clone(initialComposition),updated_at:'synthetic saved time'},reportComposition:clone(initialComposition),caseData:{case_id:'fixture',clinical_identity:clone(basis),metadata:{name:'数学夹具'}},editBeatOverrides:new Map()};
const A={categories:[]},tabs=[],STATUS_TEXT={draft:'草稿'},CASE_WORKFLOW_STEPS=[];let reportCase='fixture',reportVersion=3,category='final',reportData=null,reportToken=0,waveToken=0,reportRenderToken=0;
const data={steps:{},events:{}},pending=()=>[],writable=()=>true,copy=clone;
const selected=()=>state.reportComposition.selected_events,selectedLookup=new Map([['math-first',{event_id:'math-first',basis_version:'current',category:'V',subtype:'single',diagnosis_status:'confirmed',label:'数学图条',time_s:2}],['math-old',{event_id:'math-old',basis_version:'changed',category:'S',subtype:'single',diagnosis_status:'confirmed',label:'旧数学图条',time_s:12}]]);
const wave={start_s:1,duration_s:7,sample_rate_hz:200,stride:10,beats:[],leads:Object.fromEntries(['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6'].map((n,j)=>[n,Array.from({length:140},(_,i)=>30*Math.sin(i*.1+j))]))};
const entry={...basis,event_id:'math-first',caption:'原数学图注',waveform:wave,strip:{start_s:1,end_s:8,duration_s:7,visible_beat_count:7,leads:['II','V1','V5']}};
window.calls=[];window.downloads=[];window.renders=[];window.prints=[];window.termMounts=0;window.termApiCalls=0;window.advancedMounts=0;window.usagesDirty=0;window.heldReads=[];window.heldWaves=[];window.heldReports=[];window.heldBlobs=[];window.holdEvidence=false;window.holdWave=false;window.holdReport=false;window.holdBlob=false;window.changeFinalBasis=false;let basisReads=0;
const ECGReportPaper={render(model,entries){renders.push({model:clone(model),entries:clone(entries)});return '<article class="rp-page">数学 A4 输出</article>';},number(){}};
const run=fn=>Promise.resolve().then(fn),toast=()=>{},updateConclusionCount=()=>{},renderRhythmReturn=()=>{},renderRangeDraftNotice=()=>{},refreshReport=async()=>{};
${preflight}
const clinicalWorkflow={writable,readiness:()=>true,renderPreflight,refresh:async()=>{}};
const withPhi=x=>x;
async function api(url,options={}){const u=new URL(url,'https://mathematical.invalid'),body=options.body?JSON.parse(options.body):null;calls.push({path:u.pathname,method:options.method||'GET',query:Object.fromEntries(u.searchParams),body});if(!u.pathname.startsWith('/api/cases/fixture'))throw Error('Fixture identity scope changed');
 if(u.pathname.endsWith('/analysis-basis')){basisReads++;return {...basis,...(changeFinalBasis&&basisReads>1?{analysis_revision:5}:{})};}
 if(u.pathname==='/api/cases/fixture')return clone(state.caseData);
 if(u.pathname.endsWith('/report-statistics')){const value={...basis,mathematical:true};if(holdEvidence){holdEvidence=false;return new Promise(resolve=>heldReads.push(()=>resolve(value)));}return value;}
 if(u.pathname.endsWith('/report')&&options.method==='PUT')return {...body,version:state.report.version+1,review_revision:4,updated_at:'synthetic saved time'};
 if(u.pathname.endsWith('/report')){const value=clone(state.report);if(holdReport){holdReport=false;return new Promise(resolve=>heldReports.push(()=>resolve(value)));}return value;}
 if(u.pathname.endsWith('/hrv-review'))return {scope:clone(fullScope),document_stale:false,hrv_revision:2,digest:'saved-math-hrv',window_index:0,profile:'fixed-300s-fft-compat-v1'};
 throw Error('Unexpected synthetic endpoint '+u.pathname);}
const endpoint=(kind,params={},id=state.caseId)=>api('/api/cases/'+id+'/'+kind+'?'+new URLSearchParams(params));
const reportStrip=async(e,s,id)=>{if(id!=='fixture')throw Error('Wrong synthetic case');return clone(entry);};
const hrvForReport=async()=>({...basis,mathematical:true}),sectionsForReport=async()=>({...basis,mathematical:true});
async function printHtml(html,title,guard){guard();prints.push({html,title});}
window.fetch=async(url)=>{calls.push({path:String(url),method:'FETCH'});return {ok:true,blob:async()=>{const value=new Blob(['%PDF-1.4 synthetic-only'],{type:'application/pdf'});if(holdBlob){holdBlob=false;return new Promise(resolve=>heldBlobs.push(()=>resolve(value)));}return value;}};};HTMLAnchorElement.prototype.click=function(){downloads.push({url:this.href,name:this.download});};
${shipped}
qs('#conclusionEditor').value=originalText;qs('#conclusionEditor').addEventListener('input',dirty);
function mount(){ECGReportWorkspace.compose(qs('#reportV2Content'),{id:state.caseId,composition:state.reportComposition,selected:selected(),lookup:selectedLookup,sections:ECGReportSections.catalog(),isCurrent:()=>state.caseId==='fixture',termContext:{api:async()=>{termApiCalls++;throw Error('Hidden assistant must not load catalog');}},terms:['隐藏的旧助手'],onUsages:()=>usagesDirty++,loadWave:()=>holdWave?new Promise(resolve=>heldWaves.push(()=>resolve(clone(entry)))):Promise.resolve(clone(entry)),renderWave:value=>ECGReportWorkspace.reviewWaveSvg(value.waveform),onPages:pages=>{state.reportComposition.included_pages=pages;dirty();},onMode:mode=>{state.reportComposition.fast_slow_mode=mode;dirty();},onPreview:()=>run(previewPaper),renderAdvanced:()=>advancedMounts++});}
window.ECGTerminologyTree={mount(){termMounts++;throw Error('Hidden tree must not mount');}};
window.fixture={state,originalText,originalUsage,picks,wave,entry,mount,dirty,save,previewPaper,print,downloadReport,renderReportShell,selectedLookup,async attempt(name){try{await this[name]();return null;}catch(e){return e.message;}},resetRead(){basisReads=0;changeFinalBasis=false;},restore(){state.reportDirty=false;state.reportStale=false;state.reportSaving=false;state.caseId='fixture';state.caseRequestId=7;state.reportExportJob=null;changeFinalBasis=false;basisReads=0;ECGReportRange.clear();qs('#rwPaperPreview')?.close();}};
renderReportShell();mount();
</script>`;}

(async()=>{
 let browser,context;
 fs.mkdirSync(out,{recursive:true});
 try{
  browser=await chromium.launch({executablePath:process.env.ECG_CHROME||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true,chromiumSandbox:true});result.browser=await browser.version();
  context=await browser.newContext({viewport:{width:1600,height:1000}});await context.route('**/*',r=>{result.network.push(r.request().url());return r.abort();});
  const page=await context.newPage();page.setDefaultTimeout(10000);page.on('pageerror',e=>result.page_errors.push(e.message));await page.setContent(fixture());
  assert.equal(await page.locator('[data-rw-terms],[data-rw-term],.rw-research,.rw-review-help').count(),0);
  assert.equal(await page.locator('#reportPreflightDisclosure').isVisible(),false);assert.equal(await page.locator('#reportPreflight').isVisible(),false);
  assert.deepEqual(await page.evaluate(()=>[termMounts,termApiCalls,advancedMounts,usagesDirty]),[0,0,0,0]);
  for(const width of [900,1600,2048]){await page.setViewportSize({width,height:1000});assert(await page.evaluate(()=>{const pane=document.querySelector('.report-conclusion-dock'),editor=document.querySelector('#conclusionEditor');return editor.getBoundingClientRect().width>=pane.getBoundingClientRect().width-3;}));}
  record('default-report-has-no-terms-precheck-or-redundant-research-entry-and-editor-reclaims-width');

  const before=await page.evaluate(()=>({text:document.querySelector('#conclusionEditor').value,composition:structuredClone(fixture.state.reportComposition)}));
  assert.equal(await page.locator('[data-review-status="stale"]').count(),1);assert.match(await page.locator('[data-review-status="stale"]').textContent(),/不能导出/);assert(await page.locator('[data-back-event="1"]').isDisabled());
  await page.evaluate(()=>{window.retainedEditor=document.querySelector('#conclusionEditor');retainedEditor.focus();retainedEditor.setSelectionRange(3,9,'backward');});
  await page.locator('[data-review-filter="confirmed"]').click();
  assert.equal(await page.evaluate(()=>document.querySelector('#conclusionEditor')===retainedEditor),true);assert.equal(await page.locator('#conclusionEditor').inputValue(),before.text);
  await page.locator('[data-clear-strip-filters]').click();
  await page.evaluate(()=>{retainedEditor.focus();retainedEditor.setSelectionRange(3,9,'backward');fixture.mount();});
  assert.deepEqual(await page.evaluate(()=>[document.querySelector('#conclusionEditor')===retainedEditor,retainedEditor.selectionStart,retainedEditor.selectionEnd,retainedEditor.selectionDirection]),[true,3,9,'backward']);
  assert.deepEqual(await page.evaluate(()=>fixture.state.reportComposition),before.composition);
  record('filter-redraw-keeps-live-editor-caret-old-text-usages-picks-and-stale-evidence-warning');

  await page.locator('#conclusionEditor').fill(before.text+'手写数学后缀。');assert(await page.locator('#approveReport').isDisabled());
  assert.match(await page.evaluate(()=>fixture.attempt('print')),/先保存草稿/);assert.match(await page.evaluate(()=>fixture.attempt('downloadReport')),/先保存草稿/);
  // Draft A4 preview remains allowed; it is explicitly marked as unsaved/draft.
  await page.evaluate(()=>{fixture.state.reportComposition.selected_events=fixture.state.reportComposition.selected_events.slice(0,1);fixture.resetRead();});
  await page.evaluate(()=>fixture.previewPaper());assert.equal(await page.evaluate(()=>renders.at(-1).model.report.preview_unsaved),true);assert.equal(await page.evaluate(()=>renders.at(-1).model.report.status),'draft');
  await page.evaluate(()=>{document.querySelector('#rwPaperPreview').close();fixture.state.reportComposition.selected_events=structuredClone(fixture.picks);});
  record('typing-immediately-disables-approval-dirty-export-refuses-and-A4-preview-stays-marked-draft');

  await page.evaluate(()=>fixture.save());
  const saved=await page.evaluate(()=>({payload:calls.findLast(c=>c.method==='PUT').body,usages:ECGReportWorkspace.getTerminologyUsages(document.querySelector('#reportV2Content')),report:structuredClone(fixture.state.report)}));
  assert.equal(saved.payload.conclusion,before.text+'手写数学后缀。');assert.deepEqual(saved.payload.composition.terminology_usages,before.composition.terminology_usages);assert.deepEqual(saved.payload.composition.selected_events,before.composition.selected_events);assert.deepEqual(saved.payload.composition.included_pages,before.composition.included_pages);
  assert.deepEqual(saved.usages,before.composition.terminology_usages);assert.equal(saved.payload.composition.hrv_review_reference.document_digest,'saved-math-hrv');
  await page.evaluate(()=>{fixture.state.reportComposition=structuredClone(fixture.state.report.composition);fixture.renderReportShell();fixture.mount();const snapshot=ECGReportWorkspace.getTerminologyUsages(document.querySelector('#reportV2Content'));snapshot[0].inserted_text='Must not mutate saved usage';});
  assert.equal(await page.locator('#conclusionEditor').inputValue(),saved.payload.conclusion);assert.deepEqual(await page.evaluate(()=>fixture.state.reportComposition.terminology_usages),before.composition.terminology_usages);
  record('actual-save-and-reopen-preserve-original-term-snapshot-text-picks-HRV-reference-and-selected-report-pages');

  await page.evaluate(()=>{ECGReportRange.mount(document.querySelector('#fixtureRange'),{...structuredClone(fixture.entry),inReport:true},fixture.wave,()=>{},()=>{},{context:JSON.stringify(['fixture',7]),basis:'current',event:{event_id:'math-first'}});});
  await page.locator('#fixtureRange .range-precision summary').click();
  await page.locator('#fixtureRange [data-bound="start"]').fill('2');await page.locator('#fixtureRange [data-bound="start"]').dispatchEvent('change');
  assert.equal(await page.evaluate(()=>ECGReportRange.pending().length),1);
  for(const op of ['save','previewPaper','print','downloadReport'])assert.match(await page.evaluate(op=>fixture.attempt(op),op),/尚未应用/);
  await page.locator('#fixtureRange [data-range-cancel]').click();assert.equal(await page.evaluate(()=>ECGReportRange.pending().length),0);
  await page.evaluate(()=>{fixture.state.reportStale=true;fixture.renderReportShell();});assert(await page.locator('#approveReport').isDisabled());
  for(const op of ['save','previewPaper','print','downloadReport'])assert.match(await page.evaluate(op=>fixture.attempt(op),op),/最新|新版本/);
  assert.equal(await page.evaluate(()=>downloads.length+prints.length),0);
  record('actual-unapplied-range-and-stale-report-guards-still-block-save-A4-print-and-PDF');

  await page.evaluate(()=>fixture.restore());assert.match(await page.evaluate(()=>fixture.attempt('print')),/失效图条/);
  await page.evaluate(()=>{fixture.state.reportComposition.selected_events=fixture.state.reportComposition.selected_events.slice(0,1);fixture.resetRead();changeFinalBasis=true;});
  assert.match(await page.evaluate(()=>fixture.attempt('previewPaper')),/依据已变化/);assert.match(await page.locator('#rwPaperPreview .rp-pages').textContent(),/依据已变化/);
  await page.evaluate(()=>{document.querySelector('#rwPaperPreview').close();fixture.resetRead();changeFinalBasis=true;});assert.match(await page.evaluate(()=>fixture.attempt('print')),/依据已变化/);
  assert.equal(await page.evaluate(()=>downloads.length+prints.length),0);
  record('actual-full-evidence-read-refuses-stale-picks-and-mixed-source-basis-before-render-or-print');

  await page.evaluate(()=>{fixture.restore();holdEvidence=true;window.inflightPreview=fixture.attempt('previewPaper');});await page.waitForFunction(()=>heldReads.length===1);
  // The preview is modal. Trigger an external draft update through the real
  // textarea/input handler rather than pretending the background is editable.
  const renderCount=await page.evaluate(()=>renders.length);await page.evaluate(()=>{const editor=document.querySelector('#conclusionEditor');editor.value+='预览期间文稿更新';editor.dispatchEvent(new Event('input',{bubbles:true}));heldReads.shift()();});assert.match(await page.evaluate(()=>inflightPreview),/编排已修改/);assert.equal(await page.evaluate(()=>renders.length),renderCount);
  await page.evaluate(()=>{document.querySelector('#rwPaperPreview').close();fixture.restore();holdEvidence=true;window.inflightPreview=fixture.attempt('previewPaper');});await page.waitForFunction(()=>heldReads.length===1);await page.evaluate(()=>{fixture.state.caseId='other-mathematical-case';fixture.state.caseRequestId++;heldReads.shift()();});await page.evaluate(()=>inflightPreview);assert.equal(await page.evaluate(()=>renders.length),renderCount);
  await page.evaluate(()=>{fixture.restore();holdEvidence=true;window.inflightPrint=fixture.attempt('print');});await page.waitForFunction(()=>heldReads.length===1);await page.evaluate(()=>{fixture.state.report.version++;heldReads.shift()();});assert.match(await page.evaluate(()=>inflightPrint),/报告已变化/);assert.equal(await page.evaluate(()=>prints.length),0);
  record('late-A4-read-cannot-paint-new-text-or-case-and-version-change-blocks-inflight-print');

  await page.evaluate(()=>{fixture.restore();holdReport=true;window.inflightPDF=fixture.attempt('downloadReport');});await page.waitForFunction(()=>heldReports.length===1);await page.evaluate(()=>{fixture.state.report.version++;heldReports.shift()();});assert.match(await page.evaluate(()=>inflightPDF),/报告已变化/);assert.equal(await page.evaluate(()=>downloads.length),0);assert.equal(await page.evaluate(()=>fixture.state.reportExportJob),null);
  await page.evaluate(()=>{fixture.restore();holdBlob=true;window.inflightPDF=fixture.attempt('downloadReport');});await page.waitForFunction(()=>heldBlobs.length===1);await page.evaluate(()=>{fixture.state.privacyRequestId++;heldBlobs.shift()();});assert.match(await page.evaluate(()=>inflightPDF),/身份显示状态已变化/);assert.equal(await page.evaluate(()=>downloads.length),0);
  record('inflight-PDF-rechecks-report-version-and-privacy-after-remote-read-and-body-transfer');

  await page.evaluate(()=>{fixture.restore();document.querySelector('#conclusionEditor').value=fixture.state.report.conclusion;fixture.state.reportComposition.selected_events=fixture.state.reportComposition.selected_events.slice(0,1);fixture.dirty();});await page.evaluate(()=>fixture.save());await page.evaluate(()=>{fixture.resetRead();return fixture.print();});await page.evaluate(()=>fixture.downloadReport());
  assert.equal(await page.evaluate(()=>prints.length),1);assert.equal(await page.evaluate(()=>downloads.length),1);assert.equal(await page.evaluate(()=>fixture.state.reportExportJob),null);
  const pdfCall=await page.evaluate(()=>calls.findLast(c=>c.method==='FETCH'));assert.match(pdfCall.path,/expected_version=/);assert.match(pdfCall.path,/expected_review_revision=4/);
  assert.deepEqual(await page.evaluate(()=>fixture.state.report.composition.terminology_usages),before.composition.terminology_usages);
  record('valid-saved-report-still-prints-and-downloads-with-exact-version-and-retained-original-usages');

  await page.evaluate(()=>{fixture.restore();window.holdWave=true;fixture.mount();});await page.waitForFunction(()=>heldWaves.length>=1);await page.evaluate(()=>{fixture.state.caseId='other-mathematical-case';fixture.mount();heldWaves.splice(0).forEach(resolve=>resolve());});await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  assert.equal(await page.locator('.rw-mini-wave svg').count(),0);assert.deepEqual(await page.evaluate(()=>[termMounts,termApiCalls,advancedMounts,usagesDirty]),[0,0,0,0]);
  assert.equal(result.page_errors.length,0);assert.equal(result.network.length,0);
  record('old-wave-response-does-not-repaint-changed-report-context-and-no-hidden-assistant-network');
  result.passed=true;
 }catch(error){result.passed=false;result.error=String(error.stack||error);throw error;}
 finally{await context?.close();await browser?.close();result.browser_closed=true;save();console.log('Evidence: '+out);}
})().catch(error=>{console.error(error);process.exitCode=1});
