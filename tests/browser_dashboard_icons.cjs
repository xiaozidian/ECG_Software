'use strict';
// Real rendered home template and ordered CSS; no application/API execution.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {chromium}=require(process.env.ECG_PLAYWRIGHT_CORE||process.env.PLAYWRIGHT_CORE||'playwright-core');
assert(process.argv[2],'Pass the rendered mathematical home HTML');
const html=fs.readFileSync(process.argv[2],'utf8'),root=path.resolve(__dirname,'..');
const app=fs.readFileSync(path.join(root,'static/js/app.js'),'utf8'),initStart=app.indexOf('async function init() {');
assert(initStart>=0,'Actual app initialization boundary must exist');
const loadingPattern=/  \$\("#loading"\)\.classList\.add\("hidden"\);\n  \$\("#loading"\)\.setAttribute\("aria-hidden", "true"\);/g;
const loadingMatches=[...app.matchAll(loadingPattern)];
assert.equal(loadingMatches.length,1,'Use the unique shipped loading-cover release statements');
assert(loadingMatches[0].index>initStart,'Loading release belongs to actual app init');
const loadingRelease=loadingMatches[0][0];
const macChrome='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const executablePath=process.env.ECG_CHROME||(fs.existsSync(macChrome)?macChrome:chromium.executablePath());
const out=path.resolve(process.env.ECG_DASHBOARD_ICON_EVIDENCE||'/tmp/ecg-dashboard-icons-'+new Date().toISOString().replace(/[:.]/g,'-'));
const result={scope:'real home template and CSS, actual init loading-cover release, authored display values, geometry and native Tab focus only; no popup selection-value, application transport or clinical validation claim',checks:[],fixture_prerequisites:[],geometry:[],focus:[],page_errors:[],network:[],browser_closed:false,assets:['templates/index.html','static/css/dashboard-icons.css','static/js/app.js'].map(p=>({path:p,sha256:crypto.createHash('sha256').update(fs.readFileSync(path.join(root,p))).digest('hex')}))};
const save=()=>fs.writeFileSync(path.join(out,'results.json'),JSON.stringify(result,null,2)+'\n');
const near=(a,b,message)=>assert(Math.abs(a-b)<.75,message);
const inside=(inner,outer,message)=>assert(inner.left>=outer.left-.75&&inner.right<=outer.right+.75&&inner.top>=outer.top-.75&&inner.bottom<=outer.bottom+.75,message);
async function measure(page){return page.evaluate(()=>{
 const box=n=>{const r=n.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height,cx:r.x+r.width/2,cy:r.y+r.height/2};};
 const cards=[...document.querySelectorAll('#page-dashboard .dashboard-metrics>.metric-card')].map(card=>{
  const icon=card.querySelector('.metric-icon'),svg=icon.querySelector('svg'),copy=card.querySelector('.metric-copy'),value=copy.querySelector('strong');
  return {card:box(card),icon:box(icon),svg:box(svg),copy:box(copy),value:box(value),label:copy.querySelector('span').textContent,iconDisplay:getComputedStyle(icon).display,svgStroke:getComputedStyle(svg).stroke,iconText:icon.textContent.trim(),valueClipped:value.scrollWidth>value.clientWidth+1};
 });
 const card=document.querySelector('#page-dashboard .dashboard-structure-card'),ring=card.querySelector('.quality-ring'),inner=ring.firstElementChild,strong=inner.querySelector('strong'),label=inner.querySelector('span');
 const sideStyle=getComputedStyle(card.parentElement);
 return {cards,ring:box(ring),inner:box(inner),percent:box(strong),structureLabel:box(label),structureCard:box(card),ringText:strong.textContent,sideColumns:sideStyle.gridTemplateColumns,sideDisplay:sideStyle.display,sideDirection:sideStyle.flexDirection,sideCards:[...card.parentElement.children].map(box),scope:card.querySelector('.card-header p').textContent};
});}
async function settle(page){await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));}
async function checkFocus(page,viewport){
 const expected=await page.evaluate(()=>{
  const nodes=[...document.querySelectorAll('a[href],button,input,select,textarea,summary,[tabindex]')].filter(n=>{const style=getComputedStyle(n);return n.tabIndex>=0&&!n.matches(':disabled')&&!n.closest('[inert]')&&n.getClientRects().length&&style.display!=='none'&&style.visibility!=='hidden';});
  nodes.sort((a,b)=>{const ai=a.tabIndex>0?a.tabIndex:Infinity,bi=b.tabIndex>0?b.tabIndex:Infinity;return ai-bi;});
  globalThis.homeFocusNodes=nodes;
  return nodes.map(n=>n.id||n.tagName.toLowerCase()+':'+(n.getAttribute('data-go')||n.getAttribute('aria-label')||n.textContent.trim().slice(0,24)));
 });
 assert(expected.length>=8,'Use the actual visible home/header/navigation controls');
 assert(expected.includes('worklistFilter'),'Existing native filter remains a keyboard stop');
 await page.evaluate(()=>homeFocusNodes[0].focus());
 const inspect=()=>page.evaluate(()=>({index:homeFocusNodes.indexOf(document.activeElement),decorative:Boolean(document.activeElement?.closest('#page-dashboard .metric-icon'))}));
 assert.equal((await inspect()).index,0);
 const forward=[],backward=[];
 for(let index=1;index<expected.length;index++){await page.keyboard.press('Tab');const actual=await inspect();assert.equal(actual.index,index,'Tab follows source-rendered visible-control order: '+expected[index]);assert.equal(actual.decorative,false,'Metric decorations add no Tab stop');forward.push(expected[actual.index]);}
 for(let index=expected.length-2;index>=0;index--){await page.keyboard.press('Shift+Tab');const actual=await inspect();assert.equal(actual.index,index,'Shift+Tab reverses source-rendered visible-control order: '+expected[index]);assert.equal(actual.decorative,false,'Metric decorations add no reverse Tab stop');backward.push(expected[actual.index]);}
 result.focus.push({viewport,expected,forward,backward});
}
(async()=>{let browser;fs.mkdirSync(out,{recursive:true});try{
 browser=await chromium.launch({executablePath,headless:true,chromiumSandbox:true});result.browser=await browser.version();
 for(const viewport of [{width:375,height:812,dpr:1},{width:900,height:900,dpr:1},{width:1100,height:850,dpr:1},{width:1600,height:1000,dpr:1},{width:2048,height:1152,dpr:2}]){
  const context=await browser.newContext({viewport:{width:viewport.width,height:viewport.height},deviceScaleFactor:viewport.dpr});try{
   const page=await context.newPage();page.on('pageerror',e=>result.page_errors.push(e.message));await page.route('**/*',r=>{result.network.push(r.request().url());return r.abort();});await page.setContent(html);await settle(page);
   const initial=await page.locator('#worklistFilter').evaluate(node=>{const r=node.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return {cover:hit?.closest('#loading')?.id||null,inert:Boolean(node.closest('[inert]')),modalCount:document.querySelectorAll('dialog:modal').length};});
   assert.equal(initial.cover,'loading','Stripped app scripts leave the actual startup cover in this fixture');assert.equal(initial.inert,false);assert.equal(initial.modalCount,0);
   // Complete only the actual init visibility step. This fixture runs no app
   // transport and makes no claim about real dashboard loading or readiness.
   await page.evaluate(source=>{const $=selector=>document.querySelector(selector);eval(source);},loadingRelease);await settle(page);
   const ready=await page.locator('#worklistFilter').evaluate(node=>{const r=node.getBoundingClientRect();return {hitIsSelect:document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===node,coverPointerEvents:getComputedStyle(document.querySelector('#loading')).pointerEvents};});
   assert.equal(ready.hitIsSelect,true,'Completed source visibility step permits a normal select pointer');assert.equal(ready.coverPointerEvents,'none');result.fixture_prerequisites.push({viewport,initial,ready});
   assert.equal(await page.locator('style[data-source="static/css/dashboard-icons.css"]').count(),1);
   assert.equal(await page.locator('style[data-source]').last().getAttribute('data-source'),'static/css/dashboard-icons.css','Home styles follow all workspace overrides');
   assert.equal(await page.locator('#page-dashboard .metric-icon svg').count(),4);
   assert.deepEqual(await page.locator('#page-dashboard .metric-copy>strong').evaluateAll(nodes=>nodes.map(n=>n.id)),['metricCases','metricHours','metricBeats','metricPending']);
   assert.equal(await page.locator('#page-dashboard .metric-icon').evaluateAll(nodes=>nodes.every(n=>n.getAttribute('aria-hidden')==='true'&&n.querySelector('svg').getAttribute('focusable')==='false'&&n.querySelector('svg').getAttribute('aria-hidden')==='true'&&!n.hasAttribute('tabindex'))),true);
   await page.evaluate(()=>{for(const [id,text] of Object.entries({metricCases:'2',metricHours:'48',metricBeats:'9,999,999',metricPending:'2',qualityStatus:'2 / 2 可读'}))document.getElementById(id).textContent=text;});await settle(page);
   for(const percent of ['—','0%','9%','100%']){
    await page.locator('#qualityPercent').evaluate((node,text)=>node.textContent=text,percent);await settle(page);const measured=await measure(page);result.geometry.push({viewport,percent,...measured});
    assert.deepEqual(measured.cards.map(c=>c.label),['病例总数','记录总时长','有效心搏','待复核报告']);
    for(const card of measured.cards){assert.equal(card.iconDisplay,'grid');assert.equal(card.iconText,'');assert.notEqual(card.svgStroke,'none');near(card.icon.width,card.icon.height,'Icon frame is square');near(card.svg.cx,card.icon.cx,'SVG horizontally centered');near(card.svg.cy,card.icon.cy,'SVG vertically centered');inside(card.icon,card.card,'Icon remains inside metric');inside(card.copy,card.card,'Metric text keeps its own space');assert.equal(card.valueClipped,false,'Full mathematical count is visible');}
    near(measured.ring.width,measured.ring.height,'Structural ring must be circular');near(measured.inner.width,measured.inner.height,'Inner ring must be circular');inside(measured.ring,measured.structureCard,'Ring stays inside its structure card');inside(measured.percent,measured.inner,'Percent fits inside ring');inside(measured.structureLabel,measured.inner,'Structural-readability label fits inside ring');assert(measured.percent.bottom<=measured.structureLabel.top,'Percent and label do not overlap');assert.equal(measured.scope,'不代表信号质量或临床有效性');
    if(viewport.width>=1001){
     if(measured.sideDisplay==='grid')assert.equal(measured.sideColumns.split(' ').length,1,'Narrow desktop grid sidebar remains a single column');
     else {assert.equal(measured.sideDisplay,'flex');assert.equal(measured.sideDirection,'column','Wide desktop retains its original single-column flex sidebar');}
     assert.equal(measured.sideCards.length,2);near(measured.sideCards[0].left,measured.sideCards[1].left,'Sidebar cards share one column left edge');near(measured.sideCards[0].right,measured.sideCards[1].right,'Sidebar cards share one column right edge');assert(measured.sideCards[0].bottom<=measured.sideCards[1].top,'Sidebar cards remain vertically separate');
    }
   }
   // Scope is the changed decorative icons and the page focus order. Native
   // popup value changes are a separate driver-capability probe, not layout.
   await page.locator('#worklistFilter').focus();assert.equal(await page.evaluate(()=>document.activeElement.id),'worklistFilter');await checkFocus(page,viewport);
   const name='home-icons-and-ring-'+viewport.width+'-DPR'+viewport.dpr;result.checks.push(name);console.log('PASS '+name);save();
  }finally{await context.close();}
 }
 assert.equal(result.page_errors.length,0);assert.equal(result.network.length,0);result.passed=true;
}catch(error){result.passed=false;result.error=String(error.stack||error);throw error;}finally{await browser?.close();result.browser_closed=true;save();console.log('Evidence: '+out);}})().catch(error=>{console.error(error);process.exitCode=1});
