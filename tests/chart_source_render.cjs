'use strict';
// Pure Node regression: no browser automation or patient-data writes.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const app=fs.readFileSync('static/js/app.js','utf8'),overview=fs.readFileSync('static/js/overview-workbench.js','utf8');
const inspection=fs.readFileSync('static/js/chart-inspection.js','utf8');
assert(!inspection.includes('.drawImage('),'Inspector must never enlarge a bitmap snapshot');
assert(inspection.includes('isCanvas && !renderers.has(node)'),'Unsupported canvases must not advertise data redraw');
const registered=new Map(),layouts=new Map(),log=[];
const ctx=new Proxy({createLinearGradient:()=>({addColorStop(){}})}, {get:(o,k)=>k in o?o[k]:(...args)=>log.push([k,...args]),set:(o,k,v)=>(o[k]=v,true)});
const canvas=(logicalHeight=200,cssWidth=500)=>({style:{},dataset:{},width:0,height:logicalHeight||0,clientWidth:cssWidth,id:'',getAttribute(name){return name==='height'&&this.height?String(this.height):null;},getBoundingClientRect:()=>({width:cssWidth,height:200}),getClientRects:()=>[{}],getContext:()=>ctx});
function extract(source,name){
 const from=source.indexOf('function '+name+'(');assert(from>=0,name);const start=source.indexOf('{',from);let depth=0,quote=null,line=false,block=false;
 for(let i=start;i<source.length;i++){const c=source[i],n=source[i+1];if(line){if(c==='\n')line=false;continue;}if(block){if(c==='*'&&n==='/'){block=false;i++;}continue;}if(quote){if(c==='\\'){i++;continue;}if(c===quote)quote=null;continue;}if(c==='/'&&n==='/'){line=true;i++;continue;}if(c==='/'&&n==='*'){block=true;i++;continue;}if(['"',"'",'`'].includes(c)){quote=c;continue;}if(c==='{')depth++;if(c==='}'&&!--depth)return source.slice(from,i+1);}
 throw Error('No complete function '+name);
}
const state={caseData:{technical:{duration_seconds_raw:3600}},trend:{points:[{time_s:0,hr:60},{time_s:1800,hr:120},{time_s:3600,hr:80}]},rr:{histogram:[{count:1},{count:4}],poincare:[[800,900],[900,1000]]},start:60,scatterSelectedSet:new Set([10,55]),scatterSelectedSamples:[10,55]};
const rows=Array.from({length:200},(_,i)=>({time_s:100+i/200,hr:60+i%3,rr_ms:1000,sample_index:i,class_code:'N'}));
const ui={rows,maxHR:200,maxRR:2000,hist:{bins:[{count:1,samples:[1],start:0,end:500},{count:4,samples:[2,3,4,5],start:500,end:1000}],max:1000},ratio:false,log:false,bin:null,mode:'rr',hour:0,bound:null,size:1.4,guides:true,polygon:[],af:false};
const sandbox={window:{devicePixelRatio:2},innerWidth:1400,UI_FONT:'sans-serif',state,ui,linked:null,geometries:new WeakMap(),formatElapsed:String,fmtNumber:String,duration:()=>3600,linkedTimeSpan:()=>null,span:()=>[60,70],E:{valid:()=>true,pairs:()=>[{x:800,y:900,time_s:65,sample_index:1,class_code:'N'}]},ECGReviewTools:{scatterBound:()=>2000},colors:{N:'#000'},qs:()=>{throw Error('Inspector must not access editing UI');},ECGChartInspection:{registerRenderer:(node,fn,layout)=>{registered.set(node,fn);layouts.set(node,layout);},unregisterRenderer:node=>{registered.delete(node);layouts.delete(node);}},syncHistogramReview:()=>{throw Error('Inspector must not sync editing UI');},histogramNonempty:()=>[0,1]};
const context=vm.createContext(sandbox);
for(const name of ['canvasContext','drawAxes','renderTrendChart','renderHistogram','renderPoincare','drawReportSeries'])vm.runInContext(extract(app,name),context);
for(const name of ['prepare','axis','shade','drawTime','drawHistogram','drawScatter'])vm.runInContext(extract(overview,name),context);
const stateSnapshot=()=>JSON.stringify({state,ui},(_key,value)=>value instanceof Set?[...value]:value),before=stateSnapshot();
for(const dpr of [1,2])for(const factor of [1,1.5,2,3]){
 const target={width:Math.round(800*factor),height:Math.round(300*factor),dpr,readOnly:true};
 for(const name of ['renderTrendChart','renderHistogram','renderPoincare','drawHistogram','drawScatter']){
  const c=canvas();context[name](c,target,false);assert.equal(c.width,target.width*dpr,name);assert.equal(c.height,target.height*dpr,name);assert.equal(c.style.width,target.width+'px');
 }
 for(const kind of ['hr','rr']){const c=canvas();log.length=0;context.drawTime(c,90,110,kind,target);const g=sandbox.geometries.get(c);assert.equal(g.start,90);assert.equal(g.end,110);assert.equal(g.w,target.width-54);assert.equal(c.width,target.width*dpr);if(kind==='rr')assert.equal(log.filter(x=>x[0]==='fillRect'&&x[3]===1.2).length,rows.length,'Every RR is redrawn from source');}
}
assert.equal(stateSnapshot(),before,'Read-only redraw may not change clinical or selection state');
assert.equal(registered.size,0,'Read-only redraw must not replace source registrations');
const source=canvas();context.renderTrendChart(source);assert.equal(typeof registered.get(source),'function');const copy=canvas();registered.get(source)(copy,{width:1600,height:400,dpr:2});assert.equal(copy.width,3200);
const poincare=canvas();context.renderPoincare(poincare);assert(layouts.get(poincare),'HRV source renderer is missing equal-unit layout metadata');assert.deepEqual(JSON.parse(JSON.stringify(layouts.get(poincare))),{plotAspectRatio:1,margins:{l:44,r:16,t:15,b:27}},'Actual HRV source renderer must declare its equal-unit square axes');
const lorenz=canvas();lorenz.id='ovAFLorenz';context.drawScatter(lorenz);assert(layouts.get(lorenz),'Overview source renderer is missing equal-unit layout metadata');assert.deepEqual(JSON.parse(JSON.stringify(layouts.get(lorenz))),{plotAspectRatio:1,margins:{l:42,r:12,t:6,b:18}},'Actual overview/Lorenz source renderer must declare its equal-unit square axes');
for(const logical of [83,null]){
 const c=canvas(logical,500.5),expected=logical||200;
 for(const dpr of [1,2,1.25,1.5,2]){
  sandbox.window.devicePixelRatio=dpr;log.length=0;const g=context.canvasContext(c);assert.equal(g.width,500.5,'A fractional CSS slot must keep its complete source time axis');assert.equal(g.height,expected);assert.equal(c.style.height,expected+'px');assert.equal(c.height,Math.round(expected*dpr));assert.deepEqual(log.find(row=>row[0]==='setTransform').slice(1),[c.width/g.width,0,0,c.height/g.height,0,0],'Fractional DPR must map through actual rounded backing dimensions');
 }
 const report=canvas(logical,500.5),reportHeight=logical||80;
 for(const dpr of [1,2,1.25,2]){sandbox.window.devicePixelRatio=dpr;context.drawReportSeries(report,[{x:0,y:40},{x:10,y:80}],p=>p.x,p=>p.y);assert.equal(report.style.height,reportHeight+'px','Repeated report preview repaint cannot feed backing height into CSS');assert.equal(report.height,Math.round(reportHeight*dpr));}
}
const originalTrend=state.trend;state.trend=null;context.renderTrendChart(source);assert(!registered.has(source),'Missing trend data revokes the old source renderer');state.trend=originalTrend;
const api=require('../static/js/chart-inspection.js');let changed=null;global.ecgChartInspection={sourceChanged:n=>changed=n};api.registerRenderer(source,()=>{});assert.equal(changed,source,'Source redraw invalidates existing inspection');
console.log('Source data redraw, 100–300% geometry, DPR 1/2, preserved time range, every RR, read-only state and renderer invalidation passed.');
