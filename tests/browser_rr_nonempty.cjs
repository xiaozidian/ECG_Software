'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.ECG_PLAYWRIGHT_CORE||'playwright-core');
const out=process.env.ECG_RR_EVIDENCE,result={scope:'mathematical overview RR nonempty selection and tail discovery',checks:[],errors:[],forbidden:[]};
(async()=>{let browser,context;try{
 browser=await chromium.launch({headless:true,chromiumSandbox:true,executablePath:process.env.ECG_CHROME});context=await browser.newContext({viewport:{width:1920,height:1080},acceptDownloads:false});
 await context.route('**/*',route=>{const u=new URL(route.request().url());if(u.origin!=='http://127.0.0.1:8895'||/\.pdf|exports|source-report/.test(u.pathname)){result.forbidden.push(u.pathname);return route.abort();}return route.continue();});
 const page=await context.newPage();page.setDefaultTimeout(15000);page.on('pageerror',e=>result.errors.push(e.message));page.on('download',()=>result.forbidden.push('download'));
 await page.goto('http://127.0.0.1:8895/');await page.locator('#worklistBody tr').first().getByRole('button').first().click();await page.locator('.sidebar [data-page="review"]').click();
 await page.waitForFunction(()=>document.querySelector('#ovHistogram')?.dataset.nonemptyBins&&ecgOverviewLinked?.active());
 async function verify(ratio){
  const expected=await page.evaluate(async ratio=>{const data=await api('/api/cases/'+state.caseId+'/overview'),hist=ECGOverviewEngine.histogram(ECGOverviewEngine.decode(data),ratio);return {hist:hist.bins.map((b,i)=>({index:i,start:b.start,end:b.end,count:b.count,samples:b.samples})),n:hist.bins.length};},ratio);
  const nonempty=expected.hist.filter(b=>b.count&&b.samples.length),last=nonempty.at(-1);assert(last);
  const options=await page.locator('#ovHistBins option:not([disabled])').evaluateAll(nodes=>nodes.map(n=>Number(n.value)));assert.deepEqual(options,nonempty.map(b=>b.index).reverse());
  await page.locator('[data-ov="hist-longest"]').click();
  await page.waitForFunction(index=>Number(document.querySelector('#ovHistBins').value)===index,last.index);
  const selected=await page.evaluate(()=>ECGLinkedSelection.snapshot());assert.deepEqual(selected.samples,[...last.samples].sort((a,b)=>a-b));assert.equal(selected.sourcePopulation.start,last.start);assert.equal(selected.sourcePopulation.end,last.index===expected.n-1?null:last.end);
  const empty=expected.hist.find(b=>!b.count);assert(empty);
  const canvas=page.locator('#ovHistogram'),size=await canvas.boundingBox();
  await canvas.click({position:{x:42+(empty.index+.5)/expected.n*(size.width-54),y:12}});
  assert.deepEqual(await page.evaluate(()=>ECGLinkedSelection.snapshot()),selected);
  const steps=[];for(let i=nonempty.length-2;i>=Math.max(0,nonempty.length-5);i--){await page.locator('[data-ov="hist-shorter"]').click();const value=Number(await page.locator('#ovHistBins').inputValue());assert.equal(value,nonempty[i].index);assert((await page.evaluate(()=>ECGLinkedSelection.snapshot().samples.length))>0);steps.push(value);}
  await canvas.focus();await page.keyboard.press('End');assert.equal(Number(await page.locator('#ovHistBins').inputValue()),last.index);
  await page.keyboard.press('ArrowLeft');assert.equal(Number(await page.locator('#ovHistBins').inputValue()),nonempty.at(-2).index);
  await page.keyboard.press('Home');assert.equal(Number(await page.locator('#ovHistBins').inputValue()),nonempty[0].index);
  result.checks.push({ratio,maximumNonemptyBin:last.index,count:last.count,emptyClickPreservedSelection:true,descendingSteps:steps,rareMarkers:JSON.parse(await canvas.getAttribute('data-rare-bins')||'[]').length});
 }
 await verify(false);await page.locator('[data-ov="hist-ratio"]').click();await verify(true);
 const retained=await page.evaluate(()=>({samples:ECGLinkedSelection.snapshot().samples,sourcePopulation:ECGLinkedSelection.snapshot().sourcePopulation}));
 await page.locator('.sidebar [data-page="report"]').click();await page.waitForFunction(()=>!state.reportEvidenceLoading&&!state.reportViewLoading);await page.locator('#reportV2Nav [data-category="final"]').click();await page.locator('#conclusionEditor').fill('数学：仅保存报告不能清空RR复核选区');await page.waitForFunction(()=>!state.reportDirty&&!state.reportSaving&&state.report.conclusion==='数学：仅保存报告不能清空RR复核选区');
 assert.deepEqual(await page.evaluate(()=>({samples:ECGLinkedSelection.snapshot().samples,sourcePopulation:ECGLinkedSelection.snapshot().sourcePopulation})),retained);result.checks.push('report-autosave-retains-RR-cohort-and-provenance');
 assert.deepEqual(result.errors,[]);assert.deepEqual(result.forbidden,[]);result.passed=true;
}catch(e){result.passed=false;result.error=String(e.stack||e);throw e;}finally{await context?.close();await browser?.close();fs.mkdirSync(out,{recursive:true});fs.writeFileSync(path.join(out,'browser-results.json'),JSON.stringify(result,null,2)+'\n');}})().catch(e=>{console.error(e);process.exitCode=1;});
