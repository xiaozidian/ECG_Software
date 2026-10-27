'use strict';
// Real Chromium pointer/hit tests with the shipped stylesheet order and actual
// locate/range/saved-note functions. Mathematical transport only; main-page
// native/Demo acceptance is separate and must use the rebuilt served assets.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),crypto=require('node:crypto');
const {chromium}=require(process.env.ECG_PLAYWRIGHT_CORE||process.env.PLAYWRIGHT_CORE||'playwright-core');
const root=path.resolve(__dirname,'..'),read=p=>fs.readFileSync(path.join(root,p),'utf8');
const fixtureSource=read('tests/browser_report_st_note.cjs');
const boundary='\n(async()=>{\n let browser,context;fs.mkdirSync(out,{recursive:true});';
assert.equal(fixtureSource.split(boundary).length,2,'Public mathematical fixture boundary changed');
const sandbox={require,process,__dirname,Buffer};
vm.runInNewContext(fixtureSource.slice(0,fixtureSource.indexOf(boundary))+'\nglobalThis.mathematicalHtml=html;',sandbox);
const template=read('templates/index.html');
const styles=[...template.matchAll(/filename='(css\/[^']+)'/g)].map(match=>match[1]);
assert(styles.indexOf('css/report-workspace.css')>=0&&styles.indexOf('css/clinical-review-tools.css')>styles.indexOf('css/report-workspace.css'));
const css=styles.map(p=>read('static/'+p)).join('\n');
const shell=`<main class="main-shell" id="mainContent"><div class="safety-banner">纯数学软件布局验证</div><section id="page-report" class="page active report-candidate-page"><header class="report-page-heading"><div><h1>数学报告</h1><p id="reportCaseLabel">MATHEMATICAL</p></div><div class="report-actions"><button id="approveReport">审核</button></div></header><article id="reportV2"><nav id="reportV2Nav"><div class="v2-compose-tabs"><button>报告编排</button></div><div class="v2-candidate-tabs"><button>ST 段事件</button></div></nav><p id="reportV2Notice">数学选图；保存时备注。</p><div id="reportV2Content" class="report-candidate-workspace"><div class="v2-category-bar"><strong>ST 段事件 · 2 条</strong></div><div class="v2-event-layout"><div class="v2-event-list"><table><thead><tr><th>入报</th><th>时间</th><th>数学类型</th></tr></thead><tbody><tr><td><input type="checkbox"></td><td>10 秒</td><td>数学标签</td></tr></tbody></table></div><div class="v2-event-detail"><details class="v2-candidate-distributions" open><summary>分布 / 筛选</summary><div class="rw-distributions"><section class="rw-distribution"><header>数学分布</header><div class="rw-bars" style="--bar-count:2"><button><span>1</span><i style="--rw-bar-size:64px"></i><span>ST</span></button><button><span>1</span><i style="--rw-bar-size:64px"></i><span>ST</span></button></div></section></div></details><div id="v2EventNavigation"></div><div id="v2EventWave"></div><input id="v2Time" type="range" min="0" max="90" step="0.1"><small id="v2WaveLabel"></small></div></div></div></article><article class="report-conclusion-dock" hidden><textarea id="conclusionEditor" maxlength="12000"></textarea><span id="reportSaveState"></span></article><span id="reportProvenance"></span><div id="selectedA"></div><div id="selectedB"></div></section></main>`;
const html=sandbox.mathematicalHtml.replace(/<style>[\s\S]*?<\/style>/,`<style>${css}</style>`).replace(/<main>[\s\S]*?<\/main>/,shell);
const oldOverflow='.report-candidate-workspace #v2EventWave:has(> [data-report-saved-st-note]){overflow:visible!important;overscroll-behavior:auto!important}';
const out=path.resolve(process.env.ECG_REPORT_ST_NOTE_LAYOUT_EVIDENCE||'/tmp/ecg-report-st-note-layout-'+new Date().toISOString().replace(/[:.]/g,'-'));
const result={scope:'actual stylesheet/source-function pointer fixture; isolated mathematical transport; no clinical services',checks:[],geometry:[],page_errors:[],network:[],screenshots:[],browser_closed:false,assets:['static/css/report-workspace.css','static/js/clinical-ui.js','tests/browser_report_st_note.cjs','templates/index.html'].map(p=>({path:p,sha256:crypto.createHash('sha256').update(read(p)).digest('hex')}))};
const save=()=>fs.writeFileSync(path.join(out,'results.json'),JSON.stringify(result,null,2)+'\n');const record=name=>{result.checks.push(name);save();console.log('PASS '+name);};
const box=n=>{const r=n.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,top:r.top,bottom:r.bottom,client:n.clientHeight,scroll:n.scrollHeight,scrollTop:n.scrollTop,overflow:getComputedStyle(n).overflowY};};
async function geometry(page){return page.evaluate(()=>{const rectangle=n=>{const r=n.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,top:r.top,bottom:r.bottom,client:n.clientHeight,scroll:n.scrollHeight,scrollTop:n.scrollTop,overflow:getComputedStyle(n).overflowY};},host=document.querySelector('#v2EventWave'),summary=host.querySelector('[data-report-saved-st-note]>summary'),slider=document.querySelector('#v2Time'),stage=host.querySelector('.report-range-stage'),sr=summary.getBoundingClientRect(),hit=document.elementFromPoint(sr.x+sr.width/2,sr.y+sr.height/2);return {host:rectangle(host),summary:rectangle(summary),slider:rectangle(slider),stage:rectangle(stage),summaryHit:hit===summary,hitId:hit?.id||'',lead_count:stage.querySelectorAll('polyline').length};});}
async function hitOwn(page,selector){return page.locator(selector).evaluate(node=>{const r=node.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return hit===node||node.contains(hit);});}
async function settle(page){await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));}
(async()=>{let browser;fs.mkdirSync(out,{recursive:true});try{
 browser=await chromium.launch({executablePath:process.env.ECG_CHROME||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true,chromiumSandbox:true});result.browser=await browser.version();
 for(const viewport of [{width:900,height:900,dpr:1},{width:1600,height:1000,dpr:1},{width:2048,height:1152,dpr:2}]){
  const context=await browser.newContext({viewport:{width:viewport.width,height:viewport.height},deviceScaleFactor:viewport.dpr});try{
   const page=await context.newPage();page.setDefaultTimeout(10000);page.on('pageerror',e=>result.page_errors.push(e.message));await page.route('**/*',r=>{result.network.push(r.request().url());return r.abort();});await page.setContent(html);await page.evaluate(()=>initial);await settle(page);
   const metadata=await page.evaluate(()=>fixture.metadata()),baseline=await geometry(page);assert.equal(baseline.lead_count,12);
   if(viewport.width>=1100){
    // Current single-column geometry is verified by normal pointer access below.
    await page.locator('#v2EventWave').hover();await page.mouse.wheel(0,450);await settle(page);assert((await geometry(page)).host.scrollTop>0,'Natural wheel must reveal real saved-note scrolling');
   }
   const summary=page.locator('#v2EventWave [data-report-saved-st-note]>summary');await summary.scrollIntoViewIfNeeded();assert(await hitOwn(page,'#v2EventWave [data-report-saved-st-note]>summary'));await summary.click();assert.equal(await page.locator('#v2EventWave [data-report-saved-st-note]').evaluate(n=>n.open),true);
   const table=page.locator('#v2EventWave [data-report-saved-st-note] table');await table.scrollIntoViewIfNeeded();assert(await table.isVisible());assert.equal(await table.locator('tbody tr').count(),2);
   const append='#v2EventWave [data-report-append-st-note]';await page.locator(append).scrollIntoViewIfNeeded();assert(await hitOwn(page,append));const original=await page.locator('#conclusionEditor').inputValue();await page.locator(append).click();assert.equal(await page.locator('#conclusionEditor').inputValue(),original+'\n'+await page.evaluate(()=>fixture.eventA.note));assert.deepEqual(await page.evaluate(()=>fixture.metadata()),metadata);
   const opened=await geometry(page);assert.equal(opened.lead_count,12);assert(Math.abs(opened.stage.height-baseline.stage.height)<1,'Opening saved notes must retain the large 12-lead stage height');assert(opened.stage.height>=420,'Twelve leads retain the source large-height presentation');
   await summary.scrollIntoViewIfNeeded();await summary.click();assert.equal(await page.locator('#v2EventWave [data-report-saved-st-note]').evaluate(n=>n.open),false);
   // The normal mouse can still reach the separate slider after note scrolling.
   await page.locator('#v2Time').scrollIntoViewIfNeeded();assert(await hitOwn(page,'#v2Time'));await page.locator('#v2Time').click();
   result.geometry.push({viewport,phase:'fixed-open-note-source-stage-preserved',...opened});record('normal-pointer-summary-table-append-and-independent-slider-'+viewport.width+'-DPR'+viewport.dpr);
   // Removing the note exits the narrow selector; every prior waveform style
   // is then identical to a page with the CSS fix absent.
   await page.evaluate(()=>document.querySelector('#v2EventWave [data-report-saved-st-note]').remove());await settle(page);const unnoted=await page.locator('#v2EventWave').evaluate(n=>({height:n.getBoundingClientRect().height,overflow:getComputedStyle(n).overflowY,stage:n.querySelector('.report-range-stage').getBoundingClientRect().height}));const override=await page.addStyleTag({content:oldOverflow});await settle(page);const unnotedOld=await page.locator('#v2EventWave').evaluate(n=>({height:n.getBoundingClientRect().height,overflow:getComputedStyle(n).overflowY,stage:n.querySelector('.report-range-stage').getBoundingClientRect().height}));assert.deepEqual(unnoted,unnotedOld);await override.evaluate(n=>n.remove());
   const imagePath=path.join(out,'saved-note-pointer-'+viewport.width+'-DPR'+viewport.dpr+'.png');await page.screenshot({path:imagePath});result.screenshots.push({path:imagePath,sha256:crypto.createHash('sha256').update(fs.readFileSync(imagePath)).digest('hex')});
  }finally{await context.close();}
 }
 assert.equal(result.page_errors.length,0);assert.equal(result.network.length,0);record('no-note-layout-is-identical-and-no-network-or-browser-errors');result.passed=true;
}catch(error){result.passed=false;result.error=String(error.stack||error);throw error;}finally{await browser?.close();result.browser_closed=true;save();console.log('Evidence: '+out);}})().catch(error=>{console.error(error);process.exitCode=1});
