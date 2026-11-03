'use strict';
// Real retained range editor and shipped CSS, mathematical samples only.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.ECG_PLAYWRIGHT_CORE||'playwright-core');
const root=path.resolve(__dirname,'..'),read=p=>fs.readFileSync(path.join(root,p),'utf8');
const scripts=['clinical-review-tools','occurrence-card','report-range-editor'].map(name=>`<script>${read('static/js/'+name+'.js')}</script>`).join('');
const html=`<!doctype html><meta charset="utf-8"><style>body{margin:0;font:13px system-ui}*{box-sizing:border-box}button,select{font:inherit}#reportV2Content{position:fixed;top:278px;bottom:8px;left:80px;right:12px}#reportV2Content>.v2-category-bar{flex:none}#reportV2Content .v2-event-layout{display:grid}#reportV2Content .v2-event-list{overflow:auto}${read('static/css/clinical-review-tools.css')}${read('static/css/report-workspace.css')}</style>
<main id="reportV2"><div id="reportV2Content" class="report-candidate-workspace"><div class="v2-category-bar">房颤事件 · 数学候选</div><div class="v2-event-layout"><aside class="v2-event-list">候选列表</aside><article class="v2-event-detail report-af-detail"><details class="v2-candidate-distributions"><summary>分布 / 筛选</summary><div class="rw-distributions"><section class="rw-distribution"><header>类型</header><div style="height:43px"></div></section><section class="rw-distribution"><header>时间</header><div style="height:43px"></div></section></div></details><div id="v2EventWave" class="report-af-browser"><section class="rw-af-candidate-browse"><div class="rw-af-whole"><strong>整段候选</strong><span>D1 00:02:00 — D1 00:08:00 · 360 秒</span><b>待确认</b></div><div class="rw-af-strip"><strong>本次图条</strong><span>D1 00:04:56.500 — D1 00:05:03.500 · 7 秒 · 8 搏</span><b>待应用</b></div><nav class="rw-af-browse-controls"><button>段首</button><button>段中</button><button>段末</button><button>回图条</button><button>前一屏</button><button>后一屏</button><input type="range"><select><option>7 秒</option></select><button>选作图条</button></nav><small>浏览窗口 D1 00:04:52.500 — D1 00:05:07.500</small></section><section id="editor"></section></div></article></div></div></main>${scripts}<script>
const names=['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6'],wave={start_s:292.5,duration_s:15,sample_rate_hz:200,stride:1,beats:[],leads:Object.fromEntries(names.map((n,j)=>[n,Array.from({length:3000},(_,i)=>50000+j*100+Math.sin(i*.07)*(j===11?4000:100+j*10))]))};
const editor=document.querySelector('#editor');ECGReportRange.mount(editor,{strip:{start_s:293,end_s:300,visible_beat_count:8,leads:['II','V1','V5']},inReport:false},wave,async()=>{},async()=>{},{context:'mathematical',basis:'basis',event:{event_id:'mathematical-AF'},displayProfile:ECGReviewTools.reportAmplitude(wave),fitToFrame:true});
editor.classList.add('rw-twelve-range');const toolbar=document.createElement('div');toolbar.className='rw-main-range-toolbar';toolbar.append(...['.report-display-controls','[data-range-apply]','[data-range-cancel]','[data-range-reset]','.range-precision'].map(s=>editor.querySelector(s)));editor.querySelector('header').replaceWith(toolbar);const note=document.createElement('small');note.className='rw-review-lead-note';note.textContent='显示 15 秒 · 200 Hz · 步进 1 · 入报 II / V1 / V5';toolbar.after(note);editor._rangeChooseRange({range_start_s:296.5,range_end_s:303.5});
window.mathSource=wave;
</script>`;
const frames=page=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
(async()=>{
 let browser;const errors=[];
 try{
  browser=await chromium.launch({executablePath:process.env.ECG_CHROME||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true,chromiumSandbox:true});
  const page=await browser.newPage();page.on('pageerror',e=>errors.push(e.message));await page.route('**/*',r=>r.abort());await page.setContent(html);
  const tallGains=new Map();
  for(const category of ['AF','V','rr_interval']){
   await page.locator('.v2-event-detail').evaluate((node,isAF)=>node.classList.toggle('report-af-detail',isAF),category==='AF');await page.locator('#v2EventWave').evaluate((node,isAF)=>{node.classList.toggle('report-af-browser',isAF);node.querySelector('.rw-af-candidate-browse').hidden=!isAF;},category==='AF');
  for(const [width,height]of [[1366,768],[1920,1080],[1500,1343],[1920,1440],[1920,1800]]){
   await page.setViewportSize({width,height});
   for(const open of [false,true]){
    await page.locator('.v2-candidate-distributions').evaluate((e,v)=>e.open=v,open);await frames(page);
    for(const leads of [3,12,3]){
     await page.locator('button[data-display-leads="'+leads+'"]').click();await frames(page);
     const result=await page.evaluate(()=>{
      const editor=document.querySelector('#editor'),stage=editor.querySelector('.report-range-stage'),svg=stage.querySelector('svg'),box=stage.getBoundingClientRect(),laneErrors=[];
      for(const lane of svg.querySelectorAll('[data-wave-lead]')){const p=lane.querySelector('polyline[data-lead]'),points=p.getAttribute('points').trim().split(' ').map(s=>s.split(',').map(Number));if(points.length!==mathSource.leads[p.dataset.lead].length)laneErrors.push('source point count');const lo=Number(lane.dataset.signalTop),hi=Number(lane.dataset.signalBottom);if(points.some(p=>p[1]<lo-.01||p[1]>hi+.01))laneErrors.push(p.dataset.lead+' exceeds lane');}
      return {count:svg.querySelectorAll('[data-wave-lead]').length,editorGain:Number(editor.dataset.displayGain),svgGain:Number(svg.dataset.displayGain),units:editor.querySelector('[data-display-units]').textContent,box:{y:box.y,height:box.height,bottom:box.bottom},svgHeight:svg.getBoundingClientRect().height,viewHeight:svg.viewBox.baseVal.height,laneErrors,pending:ECGReportRange.pending().map(d=>[d.a,d.b])};
     });
     assert.equal(result.count,leads);assert(result.box.height>=160,JSON.stringify({category,width,height,open,leads,...result}));assert(result.box.height<=420.1,JSON.stringify({category,width,height,open,leads,...result}));assert(result.box.bottom<=height+1,JSON.stringify({category,width,height,open,leads,...result}));assert(Math.abs(result.svgHeight-result.box.height)<1);assert(Math.abs(result.viewHeight-result.box.height)<1);assert.equal(result.editorGain,result.svgGain);assert(result.units.includes(String(Number(result.svgGain.toPrecision(4)))+' px/u'));assert.deepEqual(result.laneErrors,[]);assert.deepEqual(result.pending,[[296.5,303.5]]);
     if(width===1920&&height>=1080){const key=[category,open,leads].join('|');if(tallGains.has(key))assert.equal(result.svgGain,tallGains.get(key),'taller viewport increased the viewing gain');else tallGains.set(key,result.svgGain);}
    }
   }
  }
  }
  await page.locator('[data-display-factor="0.5"]').click();await frames(page);assert.match(await page.locator('[data-display-units]').textContent(),/显示 0.5×/);const manualGain=await page.locator('#editor').getAttribute('data-display-gain');await page.setViewportSize({width:1920,height:1080});await frames(page);assert.equal(await page.locator('#editor').getAttribute('data-display-gain'),manualGain,'viewport resize changed the manual viewing gain');assert.match(await page.locator('[data-display-units]').textContent(),/显示 0.5×/);assert.deepEqual(errors,[]);
  console.log('Candidate frame fit: AF/V/RR, 1366 through tall 1920, 3L/12L, bounded height, stable actual/manual gain, all source points and pending range passed');
 }finally{await browser?.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
