'use strict';
// Source-painter contract only: no browser driving, clinical writes or real data.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('static/js/app.js','utf8');
function extract(name){const start=source.indexOf('function '+name+'(');assert(start>=0,name);const end=source.indexOf('\n}',start);assert(end>start,name+' terminator');return source.slice(start,end+2);}
const renderers=new Map(),layouts=new Map(),nodes=new Map();let readingCopy=false,domAccesses=0,sliderSyncs=0;
function canvas(id='copy'){
  const log=[],ctx=new Proxy({}, {get:(object,key)=>key in object?object[key]:(...args)=>log.push([key,...args]),set:(object,key,value)=>(object[key]=value,true)});
  return {id,log,style:{},dataset:{},width:0,height:0,parentElement:{clientWidth:500},getAttribute:()=>null,getBoundingClientRect:()=>({width:500,height:200}),getContext:()=>ctx};
}
for(const id of ['editTrendCanvas','editHistogramCanvas','editScatterCanvas','editLibraryHistogramCanvas','editLibraryTrendCanvas','editLibraryScatterCanvas'])nodes.set('#'+id,canvas(id));
nodes.set('#editWindowLabel',{textContent:''});nodes.set('#editHistogramRange',{textContent:''});
const strips=[{sample_index:10,leads:{II:[0,100,-50,0]}},{sample_index:20,leads:{II:[0,80,-40,0]}}];
const points=[{time_s:0,hr:60},{time_s:1800,hr:120},{time_s:3600,hr:80}];
const scatter={bounds:{x_min:100,x_max:2100,y_min:100,y_max:1100},points:[{x:100,y:100,sample_index:10,class_code:'N'},{x:1100,y:600,sample_index:20,class_code:'V'},{x:2100,y:1100,sample_index:30,class_code:'N'}]};
const state={caseId:'synthetic-contract',caseRequestId:2,caseData:{technical:{duration_seconds_raw:3600}},trend:{points},editRr:{histogram:[{count:1},{count:4},{count:2}]},editStart:600,editDuration:10,editScatterData:scatter,editScatterFilterActive:false,editLead:'II',editSelection:{source:'morphology',samples:[20],x1:.2,x2:.4,y1:.3,y2:.8},editMorphDraft:null,editMorphTraceGeometry:[],editSelectedSamples:new Set([20])};
const sandbox={window:{devicePixelRatio:2},UI_FONT:'sans-serif',state,formatElapsed:String,
  $:selector=>{assert(!readingCopy,'A readonly copy must not read or update the editing DOM');domAccesses++;return nodes.get(selector);},
  syncEditTimeSlider:()=>{assert(!readingCopy);sliderSyncs++;},editCanvasHeight:(_canvas,fallback)=>fallback,
  editDescriptor:()=>({type:'custom',sample_indices:[10,20],color:'#1a8a70'}),editBeatType:()=>({color:'#555'}),editSourceCode:()=> 'N',editSourceMatches:()=>true,
  ECGLinkedSelection:{snapshot:()=>({scope:{caseId:state.caseId,caseToken:state.caseRequestId},kind:'samples',samples:[20],selectionGeneration:1})},
  ECGReviewTools:{waveRow:(values,{top,bottom})=>({scale:(bottom-top)/(Math.max(1,...values.map(Math.abs))*2),baseline:(top+bottom)/2})},
  ECGChartInspection:{registerRenderer:(node,fn,layout)=>{assert(!readingCopy,'A readonly copy must not replace source registrations');renderers.set(node,fn);layouts.set(node,layout);},unregisterRenderer:node=>{assert(!readingCopy);renderers.delete(node);layouts.delete(node);}}
};
const context=vm.createContext(sandbox);
for(const name of ['canvasContext','paintEditOverviewTrend','paintEditOverviewHistogram','renderEditOverview','drawTemplateScatterPoints','renderEditScatter','drawEditDensityCanvas','paintEditLibraryHistogram','paintEditLibraryTrend','renderEditLibraryScatter','renderEditLibraryAnalytics'])vm.runInContext(extract(name),context);
context.renderEditOverview();context.renderEditScatter();context.renderEditLibraryAnalytics();
const density=canvas('density');context.drawEditDensityCanvas(density,strips,'#79e18b',true);
assert.equal(renderers.size,7,'All seven populated template analytics surfaces need source renderers');
for(const [selector,margins] of [['#editScatterCanvas',{l:31,r:9,t:10,b:22}],['#editLibraryScatterCanvas',{l:20,r:6,t:6,b:16}]])assert.deepEqual(JSON.parse(JSON.stringify(layouts.get(nodes.get(selector)))),{plotAspectRatio:2,margins},'Scatter layout must retain actual x/y unit ranges');
const serialize=()=>JSON.stringify(state,(_key,value)=>value instanceof Set?[...value]:value),before=serialize(),geometry=state.editMorphTraceGeometry,domBefore=domAccesses,syncBefore=sliderSyncs;
readingCopy=true;
for(const dpr of [1,2])for(const factor of [1,1.5,2,3])for(const [original,render] of renderers){
  const copy=canvas(),target={width:Math.round(800*factor),height:Math.round(300*factor),dpr,readOnly:true};render(copy,target);
  assert.equal(copy.width,target.width*dpr,original.id+' backing width');assert.equal(copy.height,target.height*dpr,original.id+' backing height');assert.equal(copy.style.width,target.width+'px');assert.equal(copy.style.height,target.height+'px');
  if(original.id.includes('Scatter')){
    const m=layouts.get(original).margins,arcs=copy.log.filter(op=>op[0]==='arc');assert.equal(arcs.length,scatter.points.length,'Every source point is reprojected');
    assert.deepEqual(arcs.map(op=>op.slice(1,3)),[[m.l,target.height-m.b],[m.l+(target.width-m.l-m.r)/2,m.t+(target.height-m.t-m.b)/2],[target.width-m.r,m.t]],'Scatter points use requested axes, never source pixels');
  }
  if(original===density){assert(copy.log.some(op=>op[0]==='lineTo'&&op[1]===target.width-8),'Density traces must cover the new source-coordinate width');assert.equal(state.editMorphTraceGeometry,geometry,'Copy must not replace original hit-test geometry');}
  if(original.id==='editTrendCanvas'){const highlight=copy.log.find(op=>op[0]==='fillRect'&&op[2]===7&&op[4]===target.height-24);assert(highlight,'Source time selection highlight must be preserved');assert.equal(highlight[1],38+600/3600*(target.width-50));}
}
// Even an empty copy must not clear the original hit-test geometry or registrations.
context.drawEditDensityCanvas(canvas(),[],'#79e18b',true,{width:800,height:300,dpr:1,readOnly:true});
readingCopy=false;
assert.equal(serialize(),before,'Inspection redraw may not change clinical, editing or selection state');assert.equal(state.editMorphTraceGeometry,geometry);assert.equal(domAccesses,domBefore);assert.equal(sliderSyncs,syncBefore);assert.equal(renderers.size,7);
state.trend={points:[]};state.editRr={histogram:[]};state.editScatterData={...scatter,points:[]};context.renderEditOverview();context.renderEditScatter();context.renderEditLibraryAnalytics();context.drawEditDensityCanvas(density,[{leads:{II:[]}}],'#79e18b',true);
assert.equal(renderers.size,0,'No-data paths must remove stale inspection renderers');assert.equal(state.editMorphTraceGeometry.length,0,'Only original empty density clears hit testing');
state.editScatterData={...scatter,bounds:{...scatter.bounds,x_max:scatter.bounds.x_min}};context.renderEditScatter();context.renderEditLibraryScatter();assert.equal(renderers.size,0,'Degenerate axes must not advertise an equal-unit renderer');
console.log('Template source redraw passed: 7 surfaces, 100–300%, DPR 1/2, exact scatter coordinates/layout, preserved selection and hit-testing, readonly DOM, empty/invalid unregister.');
