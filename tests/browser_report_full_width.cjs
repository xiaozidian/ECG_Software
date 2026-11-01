'use strict';
// The visible waveform width, not only its surrounding card, is the contract.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.ECG_PLAYWRIGHT_CORE||'playwright-core');
const out=process.env.ECG_FULL_WIDTH_EVIDENCE,baseline=process.argv.includes('--baseline');
const result={baseline,scope:'same mathematical report strip at 1/3/12 leads',measurements:[],errors:[],forbidden:[]};
(async()=>{let browser,context;try{
 browser=await chromium.launch({headless:true,chromiumSandbox:true,executablePath:process.env.ECG_CHROME});
 context=await browser.newContext({viewport:{width:1920,height:1080},acceptDownloads:false});
 await context.route('**/*',r=>{const u=new URL(r.request().url());if(u.origin!=='http://127.0.0.1:8895'||/\.pdf|exports|source-report|report-images/.test(u.pathname)){result.forbidden.push(u.pathname);return r.abort()}return r.continue()});
 const page=await context.newPage();page.setDefaultTimeout(15000);page.on('pageerror',e=>result.errors.push(e.message));
 const proof=await(await page.request.get('http://127.0.0.1:8895/api/local-review-context')).json();assert.equal(proof.source_kind,'mathematical_synthetic');
 await page.goto('http://127.0.0.1:8895/');await page.locator('#worklistBody tr').first().getByRole('button').first().click();await page.locator('.sidebar [data-page="report"]').click();await page.locator('#reportV2Nav [data-category="fastest"]').click();await page.locator('.v2-event-list [data-include]').first().check();await page.locator('#reportV2Nav [data-category="final"]').click();await page.locator('[data-rw-mini="0"] svg').waitFor();
 for(const [action,count] of [['one',1],['three',3],['all',12]]){
  await page.locator('[data-rw-strip-action="'+action+'"][data-rw-strip="0"]').evaluate(b=>b.click());await page.waitForFunction(n=>document.querySelector('[data-rw-mini="0"] svg')?.querySelectorAll('[data-wave-lead]').length===n,count);
  const measurement=await page.locator('[data-rw-mini="0"]').evaluate(node=>{const svg=node.querySelector('svg'),m=svg.getScreenCTM(),g=svg.querySelector('[data-wave-lead="II"]'),p=g.querySelector('polyline'),card=node.closest('.rw-strip').getBoundingClientRect();return {count:svg.querySelectorAll('[data-wave-lead]').length,frameWidth:node.clientWidth,frameHeight:node.clientHeight,cardWidth:card.width,cardHeight:card.height,contentWidth:svg.viewBox.baseVal.width*m.a,plotWidth:Number(svg.dataset.plotWidth)*m.a,gain:Number(g.dataset.waveScale)*m.d,domain:Number(svg.dataset.amplitudeDomain),sourceStart:svg.dataset.sourceStart,sourceDuration:svg.dataset.sourceDuration,rate:svg.dataset.sampleRate,stride:svg.dataset.stride,timeTicks:svg.querySelectorAll('[data-wave-time]').length,overflow:svg.querySelectorAll('[data-wave-overflow="true"]').length,points:Array.from(p.points,v=>[v.x*m.a,v.y]),preview:svg.dataset.reportPreview||''};});
  result.measurements.push(measurement);
 }
 const [one,three,twelve]=result.measurements;
 if(!baseline){for(const m of result.measurements){assert(Math.abs(m.contentWidth-m.frameWidth)<1,'waveform must fill its entire frame at '+m.count+' leads');assert(Math.abs(m.plotWidth-one.plotWidth)<1,'same event must use the same visible time-axis width');assert(Math.abs(m.gain-one.gain)<1e-8,'lead count must not change the shared thumbnail gain');assert.equal(m.preview,'full-width');assert.equal(m.overflow,0);assert(m.timeTicks>=2);assert(Math.abs(m.cardHeight-one.cardHeight)<1);assert.equal(m.points.length,one.points.length);assert(m.points.every((p,i)=>Math.abs(p[0]-one.points[i][0])<.01),'source samples must keep the same screen time coordinate');for(const key of ['sourceStart','sourceDuration','rate','stride'])assert.equal(m[key],one[key]);}}
 await page.waitForFunction(()=>!state.reportDirty&&!state.reportSaving);await page.screenshot({path:path.join(out,'same-strip-12-leads.png')});
 result.sameCardFullWidth=!baseline;result.passed=true;assert.deepEqual(result.errors,[]);assert.deepEqual(result.forbidden,[]);
}catch(e){result.passed=false;result.error=String(e.stack||e);throw e;}finally{await context?.close();await browser?.close();fs.mkdirSync(out,{recursive:true});for(const m of result.measurements)delete m.points;fs.writeFileSync(path.join(out,'browser-results.json'),JSON.stringify(result,null,2)+'\n');}})().catch(e=>{console.error(e);process.exitCode=1});
