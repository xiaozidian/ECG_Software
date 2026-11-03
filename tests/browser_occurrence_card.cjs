"use strict";
const assert=require('node:assert/strict');
const card=require('../static/js/occurrence-card.js');
const scenario=process.argv[2];
if(scenario==='source-points'){
 const wave={sample_rate_hz:200,stride:1,start_s:1,duration_s:.025,leads:{II:[0,25,-50,100,-25],V1:[-25,50,0,-100,25]}};
 const original=JSON.stringify(wave),svg=card.svg(wave,{sample_index:202,label:'N'},{width:200,height:90});
 const rows=[...svg.matchAll(/data-lead="([^"]+)"[^>]+points="([^"]+)"/g)];
 assert.deepEqual(rows.map(r=>r[1]),['II','V1']);
 // Shared annotation space and the explicit plot inset are now part of the
 // renderer. Recover every original amplitude through its declared geometry.
 for(const row of rows){const group=svg.match(new RegExp('<g data-wave-lead="'+row[1]+'"[^>]*'))[0],scale=Number(group.match(/data-wave-scale="([^"]+)"/)[1]),baseline=Number(group.match(/data-wave-baseline="([^"]+)"/)[1]),points=row[2].split(' ').map(p=>p.split(',').map(Number));assert(scale>0);assert.equal(points.length,wave.leads[row[1]].length);points.forEach(([x,y],i)=>{assert(Math.abs(x-(24+i/200/.025*152))<.001);assert(Math.abs((baseline-y)/scale-wave.leads[row[1]][i])<.01);});}
 assert.equal(JSON.stringify(wave),original);assert.match(svg,/stroke-width="1.15" vector-effect="non-scaling-stroke"/);
}else if(scenario==='stride-and-anchor'){
 const wave={sample_rate_hz:200,stride:4,start_s:10,duration_s:.1,leads:{II:[0,100,0,-100,0]}};
 const svg=card.svg(wave,{sample_index:2010,label:'V'},{width:200});
 assert.deepEqual([...svg.matchAll(/points="([^"]+)"/g)][0][1].split(' ').map(p=>Number(p.split(',')[0])),[24,54.4,84.8,115.2,145.6]);
 const anchor=svg.match(/class="occurrence-anchor" x1="([^"]+)"/);assert(Math.abs(Number(anchor[1])-100)<1e-8);
 assert.match(svg,/步进 4 采样的概览，请回看完整波形/);assert.match(svg,/设备单位 u/);
}else if(scenario==='whole-group'){
 const item={sample_index:2000,start_sample:1900,end_sample:2600,target_samples:[1900,2000,2600]};
 const range=card.windowFor(item);assert.equal(range.start,6.2);assert.equal(range.end,13.8);
 for(const sample of item.target_samples)assert(range.start<=sample/200&&sample/200<=range.end);
 assert(Math.abs((10-range.start)/(range.end-range.start)-.5)<1e-12);
}else if(scenario==='record-boundary'){
 const item={sample_index:100,start_sample:100,end_sample:100,target_samples:[100]};
 assert.deepEqual(card.windowFor(item),{start:0,end:1.7});
 const svg=card.svg({sample_rate_hz:200,start_s:0,duration_s:1.7,stride:1,leads:{II:[0,1]}},item);
 assert(Math.abs(Number(svg.match(/class="occurrence-anchor" x1="([^"]+)"/)[1])-(24+.5/1.7*192))<1e-8);
 assert(!card.svg({sample_rate_hz:200,start_s:1,duration_s:1,stride:1,leads:{II:[0,1]}},item).includes('class="occurrence-anchor"'));
}else if(scenario==='lead-identity'){
 for(const primary of ['II','V1','V5'])for(const count of [2,3]){const result=card.leads(primary,count);assert.equal(result[0],primary);assert.equal(result.length,count);assert.equal(new Set(result).size,count);}
 const svg=card.svg({sample_rate_hz:200,start_s:0,duration_s:1,leads:{'II<':[0,1]}},{sample_index:100,label:'N<'});
 assert.match(svg,/data-lead="II&lt;"/);assert.match(svg,/aria-label="N&lt;/);
}else if(scenario==='mixed-selection'){
 const input={},attrs={},button={setAttribute(k,v){attrs[k]=v},removeAttribute(k){delete attrs[k]}};
 const node={dataset:{},querySelector(s){return s==='button'?button:input}},item={sample_index:100,target_samples:[100,200,300]};
 const state={editSelectedSamples:new Set([100]),editSelectedSample:200};
 card.syncSelection(node,item,state);assert.equal(node.dataset.selected,'mixed');assert.equal(node.dataset.current,'true');assert.equal(attrs['aria-pressed'],'mixed');assert.equal(input.indeterminate,true);assert.equal(input.checked,false);
 state.editSelectedSamples=new Set([100,200,300]);card.syncSelection(node,item,state);assert.equal(node.dataset.selected,'true');assert.equal(input.indeterminate,false);
 state.editSelectedSamples.clear();state.editSelectedSample=400;card.syncSelection(node,item,state);assert.equal(node.dataset.selected,'false');assert.equal(node.dataset.current,'false');assert.equal(attrs['aria-current'],undefined);
}else throw Error('unknown scenario '+scenario);
console.log(scenario+' passed');
