'use strict';
// Real menu and SVG geometry; outbound report writes/printing are mathematical stubs.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.ECG_PLAYWRIGHT_CORE||'playwright-core');
const root=path.resolve(__dirname,'..'),read=p=>fs.readFileSync(path.join(root,p),'utf8');
const scripts=['clinical-review-tools','occurrence-card','analysis-consistency','report-workspace','report-wave-menu'].map(n=>`<script>${read('static/js/'+n+'.js')}</script>`).join('');
const html=`<!doctype html><meta charset="utf-8"><style>body{margin:0;background:#edf3f4;font:13px system-ui}#host{position:relative;left:90px;top:170px;width:calc(100vw - 180px);height:400px;background:white}#host>svg:first-child{width:100%;height:100%}${read('static/css/clinical-ui.css')}${read('static/css/report-wave-menu.css')}</style><section id="preview" class="v2-event-detail"><div id="host" tabindex="0"></div></section><script>
const state={caseId:'math-one',caseRequestId:1,currentPage:'report',caseData:{technical:{duration_seconds_raw:600},clinical_identity:{analysis_basis:'math-basis',analysis_revision:1}}};window.mathState=state;
window.sent=[];window.handled=[];function handleError(e){handled.push(e.message)}function toast(){}
const clinicalUI={insertWaveStrip:async x=>sent.push({action:'insert',...x,wave:undefined}),printWaveStrip:async x=>sent.push({action:'print',...x,wave:undefined})};const beatEditor={openSettings:()=>sent.push({action:'settings'})};const overviewWorkbench={waveAction:async(...x)=>sent.push({action:'overview',args:x})};async function goPage(p){state.currentPage=p}function jumpTo(t){sent.push({action:'jump',time:t})}window.print=()=>{throw Error('Native printing excluded')};
</script>${scripts}<script>
const wave={case_id:'math-one',analysis_basis:'math-basis',analysis_revision:1,start_s:10,duration_s:15,sample_rate_hz:200,stride:1,units:'device_unit',beats:[],leads:Object.fromEntries(['II','V1','V5'].map((n,j)=>[n,Array.from({length:3000},(_,i)=>50000+Math.sin(i*.07)*(100+j*20))]))};window.mathWave=wave;const host=document.querySelector('#host');ECGReportWorkspace.bindWavePreview(document.querySelector('#preview'),()=>sent.push({action:'unexpected-preview'}));host.innerHTML=ECGOccurrenceCard.svg(wave,{}, {width:1000,height:400,timeAxis:true,inset:24,displayProfile:ECGReviewTools.reportAmplitude(wave),fitHeight:true});host.addEventListener('contextmenu',e=>{e.preventDefault();ECGReportWaveMenu.open({event:e,host,wave,isCurrent:()=>true})});
</script>`;
const frames=p=>p.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
(async()=>{
 let browser;
 try{
  browser=await chromium.launch({executablePath:process.env.ECG_CHROME||process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true,chromiumSandbox:true});
  const page=await browser.newPage({viewport:{width:1366,height:768}}),errors=[],blocked=[];page.on('pageerror',e=>errors.push(e.message));await page.route('**/*',r=>{blocked.push({method:r.request().method(),url:r.request().url()});return r.abort();});await page.setContent(html);await frames(page);
  async function point(fraction,lead=0,y=.5){return page.locator('#host>svg:first-child').evaluate((svg,{fraction,lead,y})=>{const r=svg.getBoundingClientRect(),v=svg.viewBox.baseVal,g=svg.querySelectorAll('[data-wave-lead]')[lead],top=Number(g.dataset.signalTop),bottom=Number(g.dataset.signalBottom);return {x:r.left+(Number(svg.dataset.plotLeft)+Number(svg.dataset.plotWidth)*fraction)/v.width*r.width,y:r.top+(top+(bottom-top)*y)/v.height*r.height};},{fraction,lead,y});}
  async function open(fraction=.4,lead=0){const p=await point(fraction,lead);await page.mouse.click(p.x,p.y,{button:'right'});await page.locator('#reportWaveMenu').waitFor({state:'visible'});return p;}
  async function action(name){await page.locator('[data-report-wave-action="'+name+'"]').click();await frames(page);}
  await open();const labels=await page.locator('#reportWaveMenu>button,#reportWaveMenu>details>summary').allTextContents();
  assert.equal(labels.length,16);assert.match(labels[0],/插入图条/);assert.match(labels[1],/插入缩略图条/);assert.match(labels[2],/即时打印图条/);assert.match(labels[14],/重分析房早/);assert.match(labels[15],/检查选项/);
  await action('insert');let sent=await page.evaluate(()=>sent);assert.equal(sent.length,1);assert.equal(sent[0].action,'insert');assert.equal(sent[0].case_id,'math-one');assert.equal(sent[0].case_token,1);assert.equal(sent[0].time,16);assert.equal(await page.evaluate(()=>state.currentPage),'report');
  await open(.3);await action('short');sent=await page.evaluate(()=>sent);assert.equal(sent.at(-1).short,true);assert.equal(sent.at(-1).time,14.5);
  const tolerance=await page.locator('#host>svg:first-child').evaluate(svg=>Number(svg.dataset.displayDuration)/(Number(svg.dataset.plotWidth)*svg.getBoundingClientRect().width/svg.viewBox.baseVal.width)+.005);
  await open(.2);await action('anchor');let end=await point(.8);await page.mouse.click(end.x,end.y);const seconds=Number((await page.locator('.report-wave-tool-status output').innerText()).match(/([\d.]+) 秒$/)[1]);assert(Math.abs(seconds-9)<=tolerance*2);await open(.6);await action('insert');sent=await page.evaluate(()=>sent);assert(Math.abs(sent.at(-1).start_s-13)<=tolerance);assert(Math.abs(sent.at(-1).end_s-22)<=tolerance);for(const name of ['start_s','end_s'])assert(Math.abs(sent.at(-1)[name]*200-Math.round(sent.at(-1)[name]*200))<1e-6);
  await open(.1);await action('measure');assert.equal(await page.locator('.report-wave-ruler-layer').evaluate(n=>getComputedStyle(n).backgroundColor),'rgba(0, 0, 0, 0)');let a=await point(.2,0,.3),b=await point(.4,0,.7);await page.mouse.click(a.x,a.y);await page.mouse.click(b.x,b.y);assert(Math.abs(Number((await page.locator('.report-wave-tool-status output').innerText()).match(/Δt (\d+) ms/)[1])-3000)<=tolerance*2000);assert.match(await page.locator('.report-wave-tool-status output').innerText(),/Δ幅度/);assert.equal(await page.evaluate(()=>state.currentPage),'report');
  await open(.1);await action('parallel');a=await point(.2,0,.3);b=await point(.4,1,.7);await page.mouse.click(a.x,a.y);await page.mouse.click(b.x,b.y);assert.match(await page.locator('.report-wave-tool-status output').innerText(),/点击第二个位置/);b=await point(.4,0,.7);await page.mouse.click(b.x,b.y);assert.match(await page.locator('.report-wave-tool-status output').innerText(),/II · Δ幅度/);
  await page.keyboard.press('Escape');assert.equal(await page.locator('.report-wave-tool-status').count(),0);
  for(const [width,height]of [[1366,768],[1920,1080]]){
   await page.setViewportSize({width,height});await frames(page);await open(.99,2);let r=await page.locator('#reportWaveMenu').boundingBox();assert(r.x>=0&&r.y>=0&&r.x+r.width<=width&&r.y+r.height<=height);
   await page.locator('#reportWaveMenu summary').hover();await page.locator('[data-report-wave-action="print:12"]').waitFor({state:'visible'});await frames(page);r=await page.locator('#reportWaveMenu details>div').boundingBox();assert(r.x>=0&&r.y>=0&&r.x+r.width<=width&&r.y+r.height<=height);
   await action('print:12');sent=await page.evaluate(()=>sent);assert.equal(sent.at(-1).action,'print');assert.equal(sent.at(-1).leads.length,12);
  }
  // Report-only annotations advance this projection while the case header still describes r1.
  await page.evaluate(()=>{state.report={case_id:'math-one',review_revision:2};wave.analysis_revision=2;});
  await open();await action('short');assert.equal((await page.evaluate(()=>sent)).at(-1).action,'insert');
  await open();await page.evaluate(()=>state.report.review_revision=3);await action('insert');
  assert.match((await page.evaluate(()=>handled)).pop(),/依据已变化/);
  await page.evaluate(()=>{state.report.review_revision=2;handled.length=0;});
  await open();await page.evaluate(()=>state.caseId='math-two');await action('insert');assert.match((await page.evaluate(()=>handled)).at(-1),/病例或波形已变化/);assert(await page.locator('#reportWaveMenu').isHidden());assert.equal((await page.evaluate(()=>handled)).length,1);assert.deepEqual(blocked,[]);assert.deepEqual(errors,[]);
  console.log('Report hospital menu: action order, scoped insertion, short and selected range, inline rulers, same-lead amplitude, print submenu, viewport fit and stale owner rejection passed');
 }finally{await browser?.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
