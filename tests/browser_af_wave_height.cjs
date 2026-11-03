'use strict';
// Shipped AF layout and canvas renderer, detached mathematical waveform only.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.ECG_PLAYWRIGHT_CORE||'playwright-core');
const root=path.resolve(__dirname,'..'),read=p=>fs.readFileSync(path.join(root,p),'utf8'),app=read('static/js/app.js');
const functions=app.slice(app.indexOf('function canvasContext('),app.indexOf('function renderOverview()'));
assert(functions.includes('function renderWaveform()'));
const lane='<section class="ov-lane"><header>数学 RR</header><canvas></canvas></section>';
const html=`<!doctype html><meta charset="utf-8"><style>*{box-sizing:border-box}body{margin:0;font:12px system-ui}button{font:inherit}#page-review{position:fixed;top:100px;bottom:8px;left:80px;right:12px}#waveformCard{width:100%}${read('static/css/overview-workbench.css')}</style>
<main id="page-review" class="active overview-workbench ov-af-mode"><section id="ovAF"><header class="ov-af-heading"><h2>房颤 / 房扑编辑与分析</h2></header>${lane}<div class="ov-af-grid"><aside>数学候选列表</aside><div><div class="ov-af-hour">小时范围</div>${lane.repeat(4)}<div id="ovEpisodeEditor">起点 / 终点</div></div></div><nav id="ovEpisodeNavigation">片段定位</nav><div id="ovAFWaveHost"><section id="waveformCard"><header class="waveform-title"><div><strong>连续波形</strong><small id="waveMeta"></small></div></header><div id="waveformScroller"><canvas id="waveformCanvas"></canvas></div><input id="timeSlider" type="range"><footer class="waveform-foot"><span id="calibrationNote">设备单位 u，电压未校准</span></footer></section></div></section></main>
<script>${read('static/js/clinical-review-tools.js')}</script><script>
const $=s=>document.querySelector(s),UI_FONT='system-ui',ECGVoltage={snapshot:()=>null};
const source=Object.fromEntries(['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6'].map((name,j)=>[name,Array.from({length:2000},(_,i)=>Math.sin(i*.03+j)*800)]));
const state={caseId:'mathematical',caseRequestId:1,currentPage:'review',caseData:{metadata:{start_time:'2026-01-01 00:00:00'}},gain:10,scatterFocusedSample:null,waveform:{start_s:0,duration_s:10,sample_rate_hz:200,display_sample_rate_hz:200,stride:1,beats:[],annotations:[],leads:{II:source.II,V1:source.V1,V5:source.V5}}};
${functions}
window.renderMath=(count=3)=>{state.waveform.leads=Object.fromEntries((count===12?Object.keys(source):count===1?['II']:['II','V1','V5']).map(name=>[name,source[name]]));renderWaveform();};
window.mathState=state;
</script>`;
const frames=page=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
const fitted=page=>page.waitForFunction(()=>{const canvas=document.querySelector('#waveformCanvas'),slot=document.querySelector('#waveformScroller'),height=canvas.getBoundingClientRect().height,dpr=Math.min(devicePixelRatio||1,2);return Math.abs(height-slot.clientHeight)<1&&Math.abs(canvas.height-height*dpr)<=1;},null,{timeout:3000});
(async()=>{let browser;const errors=[];try{
 browser=await chromium.launch({executablePath:process.env.ECG_CHROME||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true,chromiumSandbox:true});const page=await browser.newPage();page.on('pageerror',e=>errors.push(e.message));await page.route('**/*',r=>r.abort());await page.setContent(html);
 const tallScales=new Map();await page.evaluate(()=>renderMath(3));await fitted(page);
 for(const [width,height]of [[1366,768],[1920,1080],[1500,1343],[1920,1440],[1920,1800]]){
  // Resize must repaint through the shipped slot observer. Do not manually
  // invoke the renderer before checking the CSS, backing store and source.
  await page.setViewportSize({width,height});await fitted(page);await frames(page);
  for(const count of [1,3,12,3]){
   await page.evaluate(count=>renderMath(count),count);await frames(page);
   const result=await page.evaluate(()=>{const canvas=$('#waveformCanvas'),box=canvas.getBoundingClientRect(),scroller=$('#waveformScroller').getBoundingClientRect();return {box:{width:box.width,height:box.height,bottom:box.bottom},scroller:{height:scroller.height,bottom:scroller.bottom},scale:JSON.parse(canvas.dataset.waveScales),baselines:JSON.parse(canvas.dataset.waveBaselines),leads:JSON.parse(canvas.dataset.waveLeads),gain:mathState.gain,start:canvas.dataset.waveStart,duration:canvas.dataset.waveDuration,sourceLength:Object.values(mathState.waveform.leads).map(v=>v.length)};});
   assert.equal(result.leads.length,count);assert(result.box.height>=160&&result.box.height<=420.01,JSON.stringify({width,height,count,...result}));assert(result.box.bottom<=height+1,JSON.stringify({width,height,count,...result}));assert(Math.abs(result.box.height-result.scroller.height)<1,JSON.stringify({width,height,count,...result}));assert(result.scale.every(s=>s===result.scale[0]));assert.equal(result.gain,10);assert.equal(result.start,'0');assert.equal(result.duration,'10');assert(result.sourceLength.every(n=>n===2000));
   if(width===1920&&height>=1080){if(tallScales.has(count))assert.deepEqual(result.scale,tallScales.get(count),'taller AF editor changed viewing amplitude');else tallScales.set(count,result.scale);}
  }
 }
 await page.evaluate(()=>{mathState.gain=5;renderMath(3);});await frames(page);const before=await page.locator('#waveformCanvas').getAttribute('data-wave-scales');await page.setViewportSize({width:1920,height:1080});await fitted(page);await frames(page);assert.equal(await page.locator('#waveformCanvas').getAttribute('data-wave-scales'),before);assert.equal(await page.evaluate(()=>mathState.gain),5);
 const beforeLocal=await page.locator('#waveformCanvas').evaluate(node=>node.getBoundingClientRect().height);await page.evaluate(()=>document.querySelector('#ovAF').style.maxHeight='728px');await fitted(page);assert(await page.locator('#waveformCanvas').evaluate(node=>node.getBoundingClientRect().height)<beforeLocal,'local slot resize did not repaint the actual canvas');await page.evaluate(()=>document.querySelector('#ovAF').style.removeProperty('max-height'));await fitted(page);assert.equal(await page.locator('#waveformCanvas').getAttribute('data-wave-scales'),before);assert.equal(await page.evaluate(()=>mathState.gain),5);assert.match(await page.locator('#calibrationNote').textContent(),/u/);assert.deepEqual(errors,[]);
 console.log('AF canvas height: actual window/local slot resize repaints backing store; 1/3/12 leads fit one bounded frame and retain gain, source clock and sample arrays');
}finally{await browser?.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
