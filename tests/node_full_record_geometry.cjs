"use strict";
const assert=require('node:assert/strict');
const {envelopeGeometry,envelopeSurface,envelopeTime,observeEnvelope}=require('../static/js/full-record-retain.js');
let box={left:20,width:1002,height:147},transform;
global.getComputedStyle=()=>({borderLeftWidth:'1px',borderRightWidth:'1px',borderTopWidth:'1px',borderBottomWidth:'1px',paddingLeft:'0px',paddingRight:'0px',paddingTop:'0px',paddingBottom:'0px'});
const canvas={getBoundingClientRect:()=>box,getContext:()=>({setTransform:(...a)=>transform=a})};
for(const dpr of [1,2])for(const width of [1000,600,601.25]){
  box.width=width+2;const surface=envelopeSurface(canvas,dpr),g=envelopeGeometry(canvas);
  assert.equal(surface.width,width);assert.equal(g.left,21);assert.equal(surface.height,145);
  assert.equal(canvas.width,Math.round(width*dpr));assert.equal(canvas.height,145*dpr);
  assert.equal(transform[0],canvas.width/width);assert.equal(transform[3],dpr);
  for(const f of [0,.25,.5,.75,1])assert.equal(envelopeTime(g.left+g.plotLeft+g.plotWidth*f,g,86400),86400*f);
  assert.equal(envelopeTime(-999,g,86400),0);assert.equal(envelopeTime(99999,g,86400),86400);
}
// Padding, as well as borders, must be excluded from the drawable viewport.
global.getComputedStyle=()=>({borderLeftWidth:'2px',borderRightWidth:'3px',borderTopWidth:'1px',borderBottomWidth:'1px',paddingLeft:'4px',paddingRight:'5px',paddingTop:'2px',paddingBottom:'3px'});
box={left:10,width:1014,height:152};assert.deepEqual(envelopeGeometry(canvas),{left:16,width:1000,height:145,plotLeft:35,plotWidth:960});
let callback,observed,disconnected=0,drawn=0,current=true,next=1,frames=new Map(),listeners=new Map();
global.ResizeObserver=class{constructor(fn){callback=fn;}observe(target){observed=target;}disconnect(){disconnected++;}};
global.window={addEventListener:(name,fn)=>listeners.set(name,fn),removeEventListener:(name,fn)=>{assert.equal(listeners.get(name),fn);listeners.delete(name);}};
global.requestAnimationFrame=fn=>{const id=next++;frames.set(id,fn);return id;};global.cancelAnimationFrame=id=>frames.delete(id);
const flush=()=>{const pending=[...frames.values()];frames.clear();pending.forEach(fn=>fn());};
const stop=observeEnvelope(canvas,()=>{drawn++;envelopeSurface(canvas,2);},()=>current);
assert.equal(observed,canvas);callback();callback();assert.equal(frames.size,1);flush();assert.equal(drawn,1);
box.width=614;callback();flush();assert.equal(canvas.width,1200);assert.equal(drawn,2); // Container-only resize, no window event.
listeners.get('resize')();flush();assert.equal(drawn,3);
current=false;callback();flush();assert.equal(drawn,3);current=true;
callback();const late=[...frames.values()][0];stop();assert.equal(disconnected,1);assert.equal(frames.size,0);assert.equal(listeners.size,0);late();callback();assert.equal(frames.size,0);assert.equal(drawn,3);
console.log('Full-record geometry: border/padding, DPR 1/2, fractional sizes, time mapping, container/window resize, stale scope and close cleanup passed.');

// Exercise actual source rendering and the dialog lifecycle with deterministic
// DOM doubles. This is a Node contract test, not evidence of browser clicking.
const full=require('../static/js/full-record-retain.js');
global.ECGReviewTools=require('../static/js/clinical-review-tools.js');
global.ECGAnalysisConsistency=require('../static/js/analysis-consistency.js');
global.formatElapsed=String;global.devicePixelRatio=2;
for(const total of [.003,.005,4.5,30,600])for(const center of [-100,0,total/2,total,total+100]){
 const [a,b]=full.windowAt(center,total);assert(a>=0&&b<=total&&b>=a);assert(b-a<=30+1e-8);
}
assert.throws(()=>full.windowAt(0,-1));assert.throws(()=>full.windowAt(NaN,600));
assert.equal(full.envelopeTime(999,{left:0,plotLeft:0,plotWidth:10},.003),.003,'Rounding cannot leave a short source domain');
const ov=()=>({case_id:'C01',analysis_basis:'source',analysis_revision:2,beat_revision:0,total_duration_s:600,bin_edges_s:[0,200,400,600],method:'raw min/max',leads:{V5:[[-80,50],[-900,500],[-50,50]],II:[[-20,30],[-5000,4000],[-40,20]],V1:[[-70,90],[-60,20],[-30,10]]}});
const frozen=ov(),frozenText=JSON.stringify(frozen);for(const bins of Object.values(frozen.leads)){bins.forEach(Object.freeze);Object.freeze(bins);}Object.freeze(frozen.leads);Object.freeze(frozen.bin_edges_s);Object.freeze(frozen);
const model=full.envelopeModel(frozen);assert.deepEqual(model.entries.map(x=>x.lead),['II','V1','V5']);assert.equal(model.entries[0].peak,5000);assert.equal(JSON.stringify(frozen),frozenText);
for(const bad of [()=>({...ov(),leads:{II:ov().leads.II,V1:ov().leads.V1}}),()=>({...ov(),bin_edges_s:[0,400,200,600]}),()=>({...ov(),total_duration_s:601}),()=>({...ov(),leads:{...ov().leads,V5:[[-80,50],[NaN,1],[0,0]]}})])assert.throws(()=>full.envelopeModel(bad()));
// More bins than a spread call can safely accept: no flatten/spread argument
// limit and no silent loss of the last extremum.
const many=100000,huge={total_duration_s:many/200,bin_edges_s:Array.from({length:many+1},(_,i)=>i/200),leads:Object.fromEntries(['II','V1','V5'].map(lead=>[lead,Array.from({length:many},(_,i)=>i===many-1?[-32768,32767]:[-10,20])]))};
const longModel=full.envelopeModel(huge);assert(longModel.entries.every(x=>x.peak===32768));
let painted=0;const paintContext={setTransform(){},fillRect(){},strokeRect(){},beginPath(){},moveTo(){painted++;},lineTo(){},stroke(){},fillText(){}};
global.getComputedStyle=()=>({borderLeftWidth:'1px',borderRightWidth:'1px',borderTopWidth:'1px',borderBottomWidth:'1px',paddingLeft:'0px',paddingRight:'0px',paddingTop:'0px',paddingBottom:'0px'});
const bigCanvas={dataset:{},getBoundingClientRect:()=>({left:0,width:1002,height:147}),getContext:()=>paintContext};full.drawEnvelope(bigCanvas,longModel,250);assert.equal(painted,many*3);assert.equal(bigCanvas.width,2000);assert.equal(bigCanvas.height,290);
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
const tick=()=>new Promise(r=>setImmediate(r));
let caseToken=20;
function environment({overview=ov(),overviewWait=null,postWait=null}={}){
 const calls=[],mounts=[],events=[],attrs={};let rect={left:20,width:1002,height:147};
 const basic=()=>({textContent:'',value:'',disabled:false,setAttribute(){},after(){}});
 const view={...basic(),dataset:{},getBoundingClientRect:()=>rect,getContext:()=>paintContext,setPointerCapture(){},releasePointerCapture(){},hasPointerCapture:()=>true};
 const host={...basic(),querySelector:selector=>{if(!host[selector])host[selector]=basic();return host[selector];}};
 const fields={'canvas':view,'[data-full-status]':basic(),'[data-full-center]':basic(),'[data-full-locate]':basic(),'[data-full-close]':basic(),'[data-full-time]':basic(),'[data-full-method]':basic(),'[data-full-detail]':host};
 const node={isConnected:false,open:false,querySelector:s=>fields[s],setAttribute:(k,v)=>attrs[k]=v,showModal(){this.open=true;},close(){if(!this.open)return;this.open=false;this.onclose?.();},remove(){this.isConnected=false;}};
 global.document={createElement:name=>name==='dialog'?node:basic(),body:{append:n=>n.isConnected=true},dispatchEvent:e=>events.push(e)};
 global.CustomEvent=class{constructor(type,init){this.type=type;this.detail=init.detail;}};
 global.state={caseId:'C01',caseRequestId:++caseToken,currentPage:'review',start:0,caseData:{technical:{duration_seconds_raw:600},metadata:{start_time:'2025-01-01 00:00:00'}},report:null};
 global.ECGReviewCandidates={scope:v=>Object.fromEntries(['case_id','analysis_basis','analysis_revision','beat_revision'].map(k=>[k,v[k]]))};
 global.ECGReportRange={assertApplied(){},forget(){},mount:(host,entry,wave,apply,reset,options)=>mounts.push({entry,wave,apply,reset,options})};
 global.api=async(path,options={})=>{
  calls.push({path,options});
  if(path.includes('/waveform-overview?'))return overviewWait?overviewWait.promise:overview;
  if(path.includes('/waveform?')){const q=new URL('http://localhost'+path).searchParams;return {...overview,start_s:Number(q.get('start')),duration_s:Number(q.get('duration')),leads:{II:[1,2],V1:[3,4],V5:[5,6]},beats:[]};}
  assert(path.endsWith('/evidence-candidates'));assert.equal(options.method,'POST');return postWait?postWait.promise:{item:{id:52}};
 };
 return {node,fields,view,calls,mounts,events,resize(width){rect={...rect,width:width+2};callback();flush();},point(f,id=1){const g=full.envelopeGeometry(view);return {pointerId:id,button:0,clientX:g.left+g.plotLeft+f*g.plotWidth,preventDefault(){},stopPropagation(){}};}};
}
(async()=>{
 const wait=deferred(),env=environment({overviewWait:wait});const opening=full.open();assert.equal(env.fields['[data-full-locate]'].disabled,true);
 env.fields['[data-full-center]'].value='123.456';env.fields['[data-full-center]'].oninput();wait.resolve(ov());await opening;
 assert.equal(env.fields['[data-full-center]'].value,'123.456','Initial source arrival must retain an unsubmitted location');
 assert.equal(env.calls.length,2);assert.equal(env.mounts.length,1);const firstDomain=env.mounts[0].options.domain;assert.equal(firstDomain,6300);
 env.view.onpointerdown(env.point(.5));env.view.onpointercancel(env.point(.5));assert.equal(env.fields['[data-full-center]'].value,'123.456','A cancelled drag restores an unsubmitted numeric draft');assert.equal(env.calls.length,2);
 env.resize(600.25);assert.equal(env.calls.length,2,'Resize cannot re-fetch overview or local data');assert.equal(env.fields['[data-full-center]'].value,'123.456');assert.equal(env.view.width,1201);
 env.fields['[data-full-center]'].value='';env.fields['[data-full-locate]'].onclick();await tick();assert.equal(env.calls.length,2,'An empty position is not zero');
 env.fields['[data-full-center]'].value='100';env.fields['[data-full-locate]'].onclick();await tick();const oldText=env.fields['[data-full-time]'].textContent;const readCount=env.calls.length;
 env.view.onpointerdown(env.point(.5));assert.equal(env.fields['[data-full-center]'].value,'300.000');env.view.onpointercancel(env.point(.5));await tick();assert.equal(env.fields['[data-full-time]'].textContent,oldText);assert.equal(env.fields['[data-full-center]'].value,'100.000');assert.equal(env.calls.length,readCount,'Cancelled preview keeps its original detail');
 env.view.onpointerdown(env.point(.75));env.view.onpointercancel(env.point(.75,2));assert.equal(env.fields['[data-full-center]'].value,'450.000');env.view.onlostpointercapture(env.point(.75));assert.equal(env.fields['[data-full-center]'].value,'100.000');
 env.fields['[data-full-center]'].value='600';env.fields['[data-full-locate]'].onclick();await tick();assert.equal(env.mounts.at(-1).entry.sample_index,119999,'End boundary anchor must stay inside source samples');assert.equal(env.mounts.at(-1).wave.start_s,570);assert.equal(env.mounts.at(-1).options.domain,firstDomain);
 assert(env.calls.every(c=>!c.options.method),'All navigation remains read-only');full.invalidate();assert.equal(env.node.open,false);assert.equal(listeners.size,0);assert.equal(frames.size,0);
 // Stale source during a read closes without mounting or saving the old case.
 const late=deferred(),stale=environment({overviewWait:late});const staleOpen=full.open();full.invalidate();late.resolve(ov());await staleOpen;assert.equal(stale.node.isConnected,false);assert.equal(stale.mounts.length,0);assert.equal(stale.calls.length,1);
 // Missing lead is explicit and leaves the editor unavailable.
 const bad=ov();delete bad.leads.V5;const missing=environment({overview:bad});await full.open();assert.match(missing.fields['[data-full-status]'].textContent,/V5/);assert.equal(missing.mounts.length,0);assert.equal(missing.fields['[data-full-locate]'].disabled,true);full.invalidate();
 // The three-lead navigation preview is independent of a new Other-event
 // candidate's twelve-lead report default, even if the range editor returns 3L.
 const defaults=environment();await full.open();
 const chosen=Object.freeze({range_start_s:1,range_end_s:8,duration_s:7,leads:Object.freeze(['II','V1','V5'])});
 await defaults.mounts[0].apply(chosen);
 const retained=defaults.calls.filter(c=>c.options.method==='POST');assert.equal(retained.length,1);
 const payload=JSON.parse(retained[0].options.body);
 assert.equal(retained[0].path,'/api/cases/C01/evidence-candidates');assert.equal(payload.kind,'strip');assert.equal(payload.caption,'全记录人工留图');
 assert.deepEqual(payload.settings,{range_start_s:1,range_end_s:8,duration_s:7,leads:['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6']});
 assert.deepEqual(chosen.leads,['II','V1','V5'],'A new report default cannot mutate the editor preview settings');
 assert(defaults.calls.filter(c=>c.path.includes('/waveform?')).every(c=>new URL('http://localhost'+c.path).searchParams.get('leads')==='II,V1,V5'),'Navigation remains a three-lead read');
 assert.equal(state.report,null,'Retaining a candidate cannot directly select it in a report');assert.equal(defaults.mounts[0].options.candidateOnly,true);full.invalidate();
 // A source change must not abort or repeat an already-issued candidate write.
 const post=deferred(),saving=environment({postWait:post});await full.open();const save=saving.mounts[0].apply({range_start_s:0,range_end_s:7});assert.equal(saving.fields['[data-full-close]'].disabled,true);assert.equal(saving.fields['[data-full-locate]'].disabled,true);state.caseId='C02';full.invalidate();assert.equal(saving.node.open,true);post.resolve({item:{id:52}});await save;assert.equal(saving.node.isConnected,false);assert.equal(saving.calls.filter(c=>c.options.method==='POST').length,1);assert.equal(saving.events.length,0,'Old-case acknowledgement cannot refresh a different patient');
 console.log('Full-record lifecycle: source redraw/extrema, long envelopes, short/tail domains, retained input, drag cancellation, missing lead, stale read, and single acknowledged candidate write passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
