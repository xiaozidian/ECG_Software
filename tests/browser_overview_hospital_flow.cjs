'use strict';
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('static/js/overview-workbench.js','utf8');
const E=require(process.cwd()+'/static/js/overview-engine.js'),C=require(process.cwd()+'/static/js/analysis-consistency.js');
const chunk=(start,end)=>{const a=source.indexOf(start),b=source.indexOf(end,a+start.length);assert(a>=0&&b>a,`missing source ${start}`);return source.slice(a,b);};
const node=()=>({textContent:'',innerHTML:'',hidden:false,dataset:{},attrs:{},setAttribute(k,v){this.attrs[k]=v;},prepend(){},closest(){return null;}});
function gestures(){
  const handlers={},nodes=new Map(),buttons=['point','box','lasso'].map(mode=>Object.assign(node(),{dataset:{ov:'selection:'+mode}}));
  const pointerCapture=new Set(),rect={left:0,top:0,width:500,height:250};
  const canvas=Object.assign(node(),{id:'scatterCanvas',getBoundingClientRect:()=>rect,focus(){},setPointerCapture:p=>pointerCapture.add(p),hasPointerCapture:p=>pointerCapture.has(p),releasePointerCapture:p=>pointerCapture.delete(p),closest:s=>s.includes('[data-ov-plot]')?canvas:null});
  for(const key of ['#ovEpisodeFilter','#waveformCard','#ovGestureStatus','.ov-scatter-tools [data-ov="cancel-gesture"]','#ovScatterRange'])nodes.set(key,node());
  nodes.set('#ovDialog',{open:false});nodes.set('#ovMenu',{hidden:true});
  const state={caseId:'synthetic',caseRequestId:1,currentPage:'review',scatterSelectedSamples:[200],scatterSelectedSet:new Set([200]),duration:10,start:0};
  const ui={rows:[{}],loadToken:1,mode:'rr',bound:2000,selectionMode:'box',ratio:false,range:[10,20],polygon:[[20,30],[40,50],[60,70]],af:false};
  const geometry={kind:'scatter',width:500,height:250,l:42,t:6,w:446,h:226,bound:2000,points:[{sample_index:1000,x:800,y:800,time_s:5,class_code:'VP'},{sample_index:1200,x:1000,y:1000,time_s:6,class_code:'AP'},{sample_index:1600,x:1700,y:1700,time_s:8,class_code:'fP'}]};
  const geometries=new WeakMap([[canvas,geometry]]),calls={clear:0,select:0,draw:0,seek:0};
  const ctx={state,ui,E,geometries,qs:s=>nodes.get(s)||node(),cancelGesture:()=>false,linked:{snapshot:()=>({selectionGeneration:1}),active:()=>true,clearGatePreview(){},clear(){calls.clear++;}},draw:()=>calls.draw++,drawScatter:()=>calls.draw++,closeMenu(){},seek:()=>calls.seek++,selectSamples:s=>{calls.select++;state.scatterSelectedSamples=s;},run:fn=>fn(),innerWidth:1400,innerHeight:900,document:{createElement:node,querySelectorAll:()=>buttons,addEventListener:(type,fn)=>(handlers[type]??=[]).push(fn)},window:{addEventListener(){}},ResizeObserver:class{observe(){}},requestAnimationFrame(){},formatElapsed:String};
  vm.createContext(ctx);vm.runInContext(chunk('  function syncScatterTools(', '  function drawScatter(')+chunk('  function timeAt(', '  function closeMenu(')+chunk('  async function action(', '  function bind(')+chunk('  function bind(', '  const previousCase='),ctx);ctx.bind();
  const fire=(type,extra={})=>{const event={target:canvas,clientX:140,clientY:210,pointerId:7,button:0,preventDefault(){},stopImmediatePropagation(){},...extra};for(const fn of handlers[type]||[])fn(event);};
  return {ctx,ui,state,calls,nodes,buttons,pointerCapture,fire};
}
function gestureContracts(){
  let h=gestures(),originalPolygon=JSON.stringify(h.ui.polygon);h.fire('pointerdown');h.fire('pointermove',{clientX:350,clientY:50});assert.notEqual(JSON.stringify(h.ui.polygon),originalPolygon);assert.equal(h.nodes.get('.ov-scatter-tools [data-ov="cancel-gesture"]').disabled,false);h.fire('keydown',{key:'Escape'});assert.equal(JSON.stringify(h.ui.polygon),originalPolygon);assert.deepEqual(Array.from(h.ui.range),[10,20]);assert.deepEqual(h.state.scatterSelectedSamples,[200]);assert.equal(h.calls.clear,0);assert.equal(h.pointerCapture.size,0);h.fire('pointerup');assert.equal(h.calls.select,0);
  h=gestures();h.fire('pointerdown');h.fire('pointercancel',{pointerId:8});h.fire('pointerup',{pointerId:8});h.fire('pointermove',{pointerId:8,clientX:480,clientY:1});h.fire('pointermove',{clientX:350,clientY:50});h.fire('pointerup',{clientX:350,clientY:50});assert.deepEqual(Array.from(h.state.scatterSelectedSamples),[1000,1200]);assert.equal(h.calls.select,1);assert.equal(h.pointerCapture.size,0);
  h=gestures();h.fire('pointerdown');h.fire('pointermove',{clientX:350,clientY:50});h.ctx.cancelGesture();assert.deepEqual(h.state.scatterSelectedSamples,[200]);assert.equal(h.calls.clear,0);assert.equal(h.pointerCapture.size,0);
  h=gestures();h.fire('pointerdown');h.state.caseRequestId=2;h.ui.range=[99,100];h.state.scatterSelectedSamples=[777];h.fire('pointermove',{clientX:350,clientY:50});h.fire('pointerup');assert.deepEqual(h.ui.range,[99,100]);assert.deepEqual(h.state.scatterSelectedSamples,[777]);assert.equal(h.calls.select,0);assert.equal(h.pointerCapture.size,0);
  h=gestures();h.fire('pointerdown');h.state.currentPage='report';h.fire('pointerup',{clientX:350,clientY:50});assert.equal(h.calls.select,0);
  return h;
}
function navigator(){
  const basis={analysis_basis:'synthetic',analysis_revision:1},requests=[],out=node(),canvas={width:500,height:60,getContext:()=>({clearRect(){}}),getClientRects:()=>[{}]},geometries=new WeakMap();
  const painter={beginPath(){},lineTo(){},moveTo(){},stroke(){}};
  const state={caseId:'synthetic',caseRequestId:1,currentPage:'review',start:30,duration:10,filter:'raw'},ui={af:false,identity:basis};
  const ctx={state,ui,E,ECGAnalysisConsistency:C,overviewReady:true,waveformBasis:()=>ui.identity,qs:s=>s==='.ov-navigator'?{open:true}:s==='#ovNavigator'?canvas:out,request:path=>new Promise((resolve,reject)=>requests.push({path,resolve,reject})),duration:()=>600,button:(label,action)=>`<button data-ov="${action}">${label}</button>`,URLSearchParams,geometries,prepare:()=>({ctx:painter,l:42,w:446,h:36,t:6}),shade(){},formatElapsed:String};
  vm.createContext(ctx);vm.runInContext(chunk('  async function navigatorWave(', '  function waveformOverlay('),ctx);
  const wave=(start,identity=basis)=>({...identity,start_s:start,duration_s:30,leads:{II:[0,1,0]}});
  return {ctx,state,ui,requests,out,canvas,geometries,wave};
}
function beatMeasurementContracts(){
  const basis={analysis_basis:'synthetic',analysis_revision:1},list={style:{},innerHTML:''},host={dataset:{},scrollLeft:0,querySelector:()=>list,setAttribute(){}};
  const ui={},ctx={ui,qs:()=>host,waveformBasis:()=>basis,ECGAnalysisConsistency:C,esc:String,formatElapsed:String,formatElapsedPrecise:String,editEffectiveCode:r=>r.class_code};
  vm.createContext(ctx);vm.runInContext(chunk('  function drawBeatMetrics(', '  function waveformOverlay('),ctx);
  const wave={...basis,start_s:0,duration_s:10,beats:[{time_s:1,hr:80,rr_ms:750,class_code:'AP'},{time_s:1.1,hr:100,rr_ms:600,class_code:'VP'},{time_s:5,hr:0,rr_ms:0,class_code:'fP'}]};
  ctx.drawBeatMetrics(wave,200);assert.equal(host.dataset.metricCount,'3');assert.equal((list.innerHTML.match(/role="listitem"/g)||[]).length,3);assert.match(list.innerHTML,/80 bpm/);assert.match(list.innerHTML,/750 ms/);assert.match(list.innerHTML,/AP/);assert.match(list.innerHTML,/VP/);assert.match(list.innerHTML,/fP/);assert.match(list.innerHTML,/— bpm/);assert.match(list.innerHTML,/— ms/);assert(parseFloat(list.style.width)>200,'dense intervals keep every label in a scrollable band');
  ctx.drawBeatMetrics({...wave,analysis_revision:2},200);assert.equal(list.innerHTML,'');assert.equal(host.dataset.metricCount,'0','stale evidence removes measurement labels');
}
function initialMeasurementHarness(){
  const basis={analysis_basis:'synthetic',analysis_revision:1},list={style:{},innerHTML:''},host={dataset:{},scrollLeft:0,querySelector:()=>list,setAttribute(){}},status=node();
  const wave={...basis,start_s:0,duration_s:10,beats:[{sample_index:200,time_s:1,hr:80,rr_ms:750,class_code:'AP'},{sample_index:220,time_s:1.1,hr:100,rr_ms:600,class_code:'VP'},{sample_index:1000,time_s:5,hr:null,rr_ms:null,class_code:'fP'}]};
  const data={...basis,revision:1,duration_s:10,rows:[[200,750,'AP'],[220,600,'VP'],[1000,null,'fP']],settings:{pause:2.5}},rhythm={...basis,beat_revision:1,document:{episodes:[],bookmarks:{}}};
  const state={caseId:'synthetic',caseRequestId:1,currentPage:'review',scatterMode:'rr',waveform:wave},ui={loadToken:0,id:null,rows:[],ratio:false},calls={render:0,fetch:0};
  const ctx={state,ui,E,ECGAnalysisConsistency:{...C,read:async()=>[data,rhythm]},overviewReady:false,episodeFilter:'all',episodePage:0,episodeEditor:null,episodeNavigation:0,geometries:new WeakMap(),api(){},qs:s=>s==='#ovBeatMetrics'?host:s==='#ovBeatMetrics .ov-beat-metrics-list'?list:s==='#ovStatus'?status:null,document:{querySelectorAll:()=>[]},rememberEpisodeForm(){},hour:()=>0,duration:()=>10,renderCoverage(){},resetCoverage(){},draw(){},renderEpisodes(){},fmtNumber:String,esc:String,formatElapsed:String,formatElapsedPrecise:String,editEffectiveCode:r=>r.class_code,button:()=>''};
  ctx.renderWaveform=()=>{calls.render++;ctx.drawBeatMetrics(state.waveform,200);};ctx.loadWaveform=async()=>{calls.fetch++;state.waveform=wave;ctx.renderWaveform();};
  vm.createContext(ctx);vm.runInContext(chunk('  async function load(', '  function waveformFailed(')+chunk('  function drawBeatMetrics(', '  function waveformOverlay('),ctx);
  ctx.drawBeatMetrics(wave,200);assert.equal(list.innerHTML,'','an early waveform cannot show unconfirmed measurement evidence');
  return {ctx,state,ui,calls,host,list,data,rhythm};
}
async function initialMeasurementContracts(){
  let h=initialMeasurementHarness();await h.ctx.load();assert.equal(h.calls.fetch,0,'same-basis cached waveform needs no extra request');assert.equal(h.calls.render,1,'first confirmed overview load repaints its cached waveform');assert.equal(h.host.dataset.metricCount,'3');assert.match(h.list.innerHTML,/80 bpm/);assert.match(h.list.innerHTML,/750 ms/);assert.match(h.list.innerHTML,/— bpm/);assert.match(h.list.innerHTML,/— ms/);assert.match(h.list.innerHTML,/fP/);
  h=initialMeasurementHarness();let resolve;h.ctx.ECGAnalysisConsistency.read=()=>new Promise(r=>{resolve=r;});const old=h.ctx.load();h.state.caseRequestId=2;resolve([h.data,h.rhythm]);await old;assert.equal(h.calls.render,0,'late case request cannot repaint the old measurement band');assert.equal(h.list.innerHTML,'');
}
async function navigationContracts(){
  let h=navigator();const a=h.ctx.navigatorWave();await h.ctx.navigatorWave();assert.equal(h.requests.length,1,'same pending window is deduplicated');h.state.start=60;const b=h.ctx.navigatorWave();h.state.start=30;const latestA=h.ctx.navigatorWave();assert.equal(h.requests.length,3);h.requests[0].resolve(h.wave(999));await a;assert.equal(h.ui.nav,null,'first A cannot overwrite latest A');h.requests[2].resolve(h.wave(20));await latestA;h.requests[1].resolve(h.wave(50));await b;assert.equal(h.ui.nav.start_s,20);assert.equal(h.out.textContent,'20–50');
  h=navigator();const failed=h.ctx.navigatorWave();h.requests[0].reject(Error('synthetic transport failure'));await failed;assert.equal(h.ui.navKey,null);assert.match(h.out.innerHTML,/20–50.*navigator-retry/);const retry=h.ctx.navigatorWave();assert.equal(h.requests.length,2);h.requests[1].resolve(h.wave(20));await retry;assert.equal(h.ui.nav.start_s,20);
  h=navigator();const oldFilter=h.ctx.navigatorWave();h.state.filter='changed';h.requests[0].resolve(h.wave(20));await oldFilter;assert.equal(h.ui.nav,null,'changed filter cannot accept delayed result');const newFilter=h.ctx.navigatorWave();assert.match(h.requests[1].path,/filter=changed/);h.requests[1].resolve(h.wave(20));await newFilter;assert.equal(h.ui.nav.start_s,20);
  h=navigator();const oldCase=h.ctx.navigatorWave();h.state.caseRequestId=2;h.requests[0].resolve(h.wave(20));await oldCase;assert.equal(h.ui.nav,null,'same case id with new request scope rejects old result');
  h=navigator();const wrongRevision=h.ctx.navigatorWave();h.requests[0].resolve(h.wave(20,{analysis_basis:'synthetic',analysis_revision:2}));await wrongRevision;assert.equal(h.ui.nav,null);assert.match(h.out.innerHTML,/navigator-retry/);
}
(async()=>{gestureContracts();beatMeasurementContracts();const h=gestures();h.fire('pointerdown');h.fire('pointermove',{clientX:350,clientY:50});await h.ctx.action('selection:lasso');assert.equal(h.ui.selectionMode,'lasso');assert.deepEqual(h.state.scatterSelectedSamples,[200]);assert.equal(h.calls.clear,0);assert.equal(h.buttons[2].attrs['aria-pressed'],'true');h.fire('pointerup');assert.equal(h.calls.select,0);await initialMeasurementContracts();await navigationContracts();console.log('hospital overview: gesture cancellation, exact paced sample cohorts, scope changes, pending deduplication, A/B/A navigation, failure retry, filter/revision guards and first-load/all-beat HR/RR measurement labels passed');})().catch(error=>{console.error(error);process.exitCode=1;});
