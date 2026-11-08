'use strict';
// Source-owner contracts; pure Node VM, no browser or clinical-data writes.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const linked=fs.readFileSync('static/js/template-linked-view.js','utf8'),morph=fs.readFileSync('static/js/morphology-workbench.js','utf8'),app=fs.readFileSync('static/js/app.js','utf8');
function extract(source,name){
 const from=source.indexOf('function '+name+'(');assert(from>=0,name);const start=source.indexOf('{',from);let depth=0,quote=null,line=false,block=false;
 for(let i=start;i<source.length;i++){const c=source[i],n=source[i+1];if(line){if(c==='\n')line=false;continue;}if(block){if(c==='*'&&n==='/'){block=false;i++;}continue;}if(quote){if(c==='\\'){i++;continue;}if(c===quote)quote=null;continue;}if(c==='/'&&n==='/'){line=true;i++;continue;}if(c==='/'&&n==='*'){block=true;i++;continue;}if(['"',"'",'`'].includes(c)){quote=c;continue;}if(c==='{')depth++;if(c==='}'&&!--depth)return source.slice(from,i+1);}
 throw Error('Incomplete '+name);
}
function canvas(id='',dataset={}){
 const operations=[],attrs={},c={id,dataset:{...dataset},attrs,style:{},width:300,height:100,getBoundingClientRect:()=>({width:500.5,height:100.5}),getClientRects:()=>[{}],setAttribute:(k,v)=>attrs[k]=v,getAttribute:k=>attrs[k]};
 const ctx=new Proxy({drawImage(){throw Error('Inspection must redraw density bins, never copy raster');}}, {get:(o,k)=>k in o?o[k]:(...args)=>operations.push({name:k,args,fill:o.fillStyle,stroke:o.strokeStyle}),set:(o,k,v)=>(o[k]=v,true)});c.getContext=()=>ctx;c.operations=operations;return c;
}
const registry=new Map(),layouts=new Map(),api={registerRenderer:(node,fn,layout)=>{registry.set(node,fn);layouts.set(node,layout);},unregisterRenderer:node=>{registry.delete(node);layouts.delete(node);}};
const bins=Array.from({length:34},(_,i)=>({count:i===3?100:0,samples:[]})),stats={bins:bins.map((b,i)=>({count:i===3?25:0}))};
const selection={slot:'top',points:[{x:.2,y:.3},{x:.6,y:.8}]},focus={focusSample:7,selectionGeneration:4,scope:{caseId:'A'}},points=[{sample_index:7,x:800,y:900},{sample_index:8,x:1000,y:1200}];
const sandbox={window:{devicePixelRatio:2},devicePixelRatio:2,UI_FONT:'sans-serif',reference:{bins},root:{ECGChartInspection:api},ECGChartInspection:api,plots:new Map(),current:{groups:{source:[1,2]}},box:selection,active:()=>true,sameRows:()=>true,C:()=>({snapshot:()=>focus}),keyScope:scope=>JSON.stringify(scope),state:{editScatterData:{bounds:{x_min:0,x_max:2000,y_min:0,y_max:2000},points}},editScatterPointVisible:()=>true,drag:null,outline:{generation:4,scope:JSON.stringify(focus.scope),polygon:[[500,600],[1000,600],[1000,1000],[500,600]]},editCanvasHeight:(_canvas,height)=>height};
vm.createContext(sandbox);vm.runInContext(extract(app,'canvasContext'),sandbox);for(const name of ['geometry','scatterOverlay','histogram'])vm.runInContext(extract(linked,name),sandbox);vm.runInContext(extract(morph,'draw'),sandbox);
const before=JSON.stringify({selection,focus,points});
for(const id of ['editHistogramCanvas','editLibraryHistogramCanvas']){
 const source=canvas(id);sandbox.histogram(source,stats);assert(registry.has(source),'Actual selected NN painter must own inspector callback');const aria=source.attrs['aria-label'],sourceWidth=source.width;
 for(const factor of [1,1.5,2,3])for(const dpr of [1,2]){
  const target=canvas(),g={width:800*factor,height:300*factor,dpr,readOnly:true},size=registry.size;registry.get(source)(target,g);
  assert.equal(target.width,Math.round(g.width*dpr));assert.equal(target.height,Math.round(g.height*dpr));assert.deepEqual(target.attrs,{},'Read-only copy does not advertise original histogram filtering');assert.equal(registry.size,size);
  const bars=target.operations.filter(o=>o.name==='fillRect'&&['#c7dddd','#d68b27'].includes(o.fill));assert.equal(bars.length,35);const orange=bars.find(o=>o.fill==='#d68b27'),referenceBar=bars.filter(o=>o.fill==='#c7dddd')[3];assert.equal(orange.args[3],referenceBar.args[3]/4,'Selected NN count must keep 25/100 reference height at every zoom');assert.equal(target.operations.filter(o=>o.name==='fillText').at(-1).args[0],'2000 ms');
 }
 assert.equal(source.width,sourceWidth);assert.equal(source.attrs['aria-label'],aria);
 sandbox.reference=null;sandbox.histogram(source,stats);assert(!registry.has(source),'Absent actual NN data revokes renderer');sandbox.reference={bins};
}
const density={width:3,height:2,bins:[0,1,4,2,0,8],lead:'II',amplitude_limit:1300,included:15,total:17,skipped_edges:2};
for(const dataset of [{morphSource:'top'},{morphGroupPlot:'6'},{}]){
 const source=canvas('density',dataset);sandbox.draw(source,density);const fn=registry.get(source);assert.equal(typeof fn,'function');const size=registry.size,plotSize=sandbox.plots.size,description=source.attrs['aria-description'];assert.equal(source.dataset.inspectNote,'只读密度统计；'+description);
 for(const factor of [1,1.5,2,3])for(const dpr of [1,2,1.25]){
  const copy=canvas(),g={width:800*factor,height:300*factor,dpr,readOnly:true};fn(copy,g);assert.equal(copy.width,Math.round(g.width*dpr));assert.equal(copy.height,Math.round(g.height*dpr));assert.equal(copy.dataset.morphSource,dataset.morphSource);assert.equal(copy.dataset.morphGroupPlot,dataset.morphGroupPlot);assert.equal(registry.size,size);assert.equal(sandbox.plots.size,plotSize);assert(!sandbox.plots.has(copy),'Read-only density may not become an editing selection surface');assert.deepEqual(copy.attrs,{});
  const cells=copy.operations.filter(o=>o.name==='fillRect'&&o.fill.startsWith('rgb('));assert.equal(cells.length,4,'All four occupied source bins must survive every redraw');const pad=dataset.morphGroupPlot?2:dataset.morphSource?8:3,foot=dataset.morphGroupPlot?12:dataset.morphSource?24:20,cellW=(g.width-pad*2)/3,cellH=(g.height-pad-foot)/2;
  assert.deepEqual(cells.at(-1).args,[pad+2*cellW,pad+cellH,cellW,cellH]);assert.equal(cells.at(-1).fill,'rgb(255,0,0)','Maximum bin keeps original density colour scale');assert(copy.operations.some(o=>o.name==='fillText'&&o.args[0]==='+1s'));
  const boxes=copy.operations.filter(o=>o.name==='strokeRect');assert.equal(boxes.length,dataset.morphSource==='top'?1:0,'Source density gate must also be visible in inspection');
 }
 assert.equal(source.attrs['aria-description'],description);sandbox.draw(source,null);assert(!registry.has(source));assert(!sandbox.plots.has(source));assert.equal(source.dataset.inspectNote,undefined,'Missing data must not retain old density count note');
}
for(const library of [false,true]){
 const copy=canvas(),g={width:800,height:400,dpr:2,readOnly:true};copy.width=1600;copy.height=800;sandbox.scatterOverlay(copy,g,library);const arcs=copy.operations.filter(o=>o.name==='arc');assert.equal(arcs.length,1,'Focused scatter point must be retained');const m=library?{l:20,r:6,t:6,b:16}:{l:31,r:9,t:10,b:22};assert.deepEqual(arcs[0].args,[m.l+.4*(800-m.l-m.r),m.t+.55*(400-m.t-m.b),5,0,Math.PI*2]);assert(copy.operations.some(o=>o.name==='fill'&&o.args[0]==='evenodd'),'Exact selection outline is redrawn in target RR coordinates');assert.deepEqual(copy.attrs,{});
}
assert.equal(JSON.stringify({selection,focus,points}),before,'Read-only NN/density/overlay cannot change clinical selection/focus state');
// Exercise the actual mount wrappers: target arguments must reach the base painter,
// and its late-bound registered callback must paint the overlay on the new canvas.
const calls=[],wrapped={q:()=>null,renderEditScatter:(c,g)=>calls.push(['base',c,g]),renderEditLibraryScatter:(c,g)=>calls.push(['library',c,g]),scatterOverlay:(c,g,library)=>calls.push(['overlay',c,g,library])};vm.createContext(wrapped);
for(const name of ['oldScatter','oldLibraryScatter']){const line=linked.split('\n').find(line=>line.trim().startsWith('const '+name+'='));assert(line);vm.runInContext(line,wrapped);}
const copy=canvas(),geometry={width:800,height:400,dpr:2,readOnly:true};wrapped.renderEditScatter(copy,geometry);wrapped.renderEditLibraryScatter(copy,geometry);assert.equal(calls.length,4);assert.equal(calls[0][1],copy);assert.equal(calls[0][2],geometry);assert.equal(calls[1][3],false);assert.equal(calls[2][1],copy);assert.equal(calls[2][2],geometry);assert.equal(calls[3][3],true);
console.log('Actual source-owner contracts passed: selected NN bins, all density bins/gates, scatter focus/outline, read-only callbacks, geometry/DPR and invalidation.');
