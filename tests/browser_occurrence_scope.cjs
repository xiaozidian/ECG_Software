/* Synthetic UI regression: ordinary case/basis boundaries, no browser or service. */
'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.env.ECG_OCCURRENCE_SOURCE||'static/js/clinical-ui.js','utf8');
const render=source.slice(source.indexOf('  function renderOccurrences(){'),source.indexOf('  async function refreshReport('));
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function node(){
 const value={dataset:{},style:{setProperty(){}},children:[],isConnected:true,classList:{add(){}},textContent:'',setAttribute(){},removeAttribute(){},contains(){return false},querySelectorAll(){return this.children},querySelector(selector){return this.parts?.[selector]||null},insertBefore(child,anchor){const prior=this.children.indexOf(child);if(prior>=0)this.children.splice(prior,1);const at=this.children.indexOf(anchor);this.children.splice(at<0?this.children.length:at,0,child);child.parent=this;child.isConnected=true;},remove(){this.isConnected=false;if(this.parent)this.parent.children.splice(this.parent.children.indexOf(this),1)}};
 Object.defineProperty(value,'firstElementChild',{get(){return this.children[0]||null}});
 Object.defineProperty(value,'nextElementSibling',{get(){return this.parent?.children[this.parent.children.indexOf(this)+1]||null}});
 Object.defineProperty(value,'innerHTML',{get(){return this.html||''},set(html){this.html=html;if(html===''){this.children.forEach(child=>child.isConnected=false);this.children=[];}else if(html.includes('occurrence-open'))this.parts={button:node(),input:node(),'.occurrence-wave':node()};}});
 return value;
}
function fixture(){
 const lane=node(),host=node(),nodes=new Map(),reads=[];
 host.clientWidth=170;host.scrollTop=0;host.parts={'.occurrence-lane':lane};host.children=[lane];
 nodes.set('#editTemplateGallery',host);
 for(const id of ['#editGalleryTitle','#editGalleryDescription','#editGalleryCount'])nodes.set(id,node());
 nodes.get('#editGalleryCount').textContent='retained current count';
 const item={event_id:'synthetic-beat',sample_index:200,target_samples:[200],time_s:1,class_code:'N',label:'synthetic N',beat_count:1};
 const context={id:'synthetic-A',caseToken:1,evidenceScope:'basis-A'};
 const state={currentPage:'edit',caseId:'synthetic-A',caseRequestId:1,editLead:'II',editTemplates:[],editSelectedSamples:new Set(),caseData:{analysis_revision:0}};
 const ctx=vm.createContext({state,occurrenceContext:context,occurrence:{total:1,analysis_revision:0},occurrenceToken:1,occurrenceFocus:null,waveEvidenceScope:'basis-A',pageCache:new Map([[0,[item]]]),type:'N',template:'all',editMode:'all',occurrenceLeadCount:2,rhythmWrite:null,tileWidth:0,
  qs:selector=>nodes.get(selector)||null,document:{activeElement:{tagName:'BODY'},createElement:node},
  occurrenceGrid:()=>({first:0,last:1,visibleFirst:1,visibleLast:1,width:170,height:142,contentHeight:142,columns:1,row:142}),
  syncEditTimeSlider(){},syncOccurrenceJump(){},occurrenceViewControls(){},releaseOccurrenceWaves(){},modeLabel:()=> 'all',
  beatEditor:{renderOccurrenceToolbar(){},registerOccurrence(card,item,scope){card.editScope=scope;}},ECGOccurrenceCard:{geometry:{waveHeight:132},leads:()=>['II','V1'],syncSelection(){}},
  eventWaveKey:()=> 'synthetic-key',thumbnailCache:{retain(){}},esc:String,formatElapsed:String,svg:wave=>'<svg>'+wave.marker+'</svg>',
  eventWave:(event,id,leads)=>{let resolve;const promise=new Promise(done=>resolve=done);reads.push({event,id,leads,resolve});return promise;}});
 vm.runInContext(render,ctx);
 return {ctx,reads,host,lane,nodes,state,context};
}
function change(ctx,kind){if(kind==='different-case'){ctx.state.caseId='synthetic-B';ctx.state.caseRequestId=2;}else if(kind==='same-case-reopen')ctx.state.caseRequestId=2;else ctx.waveEvidenceScope='basis-B';}
(async()=>{
 for(const kind of ['different-case','same-case-reopen','changed-basis']){
  const f=fixture();change(f.ctx,kind);f.ctx.renderOccurrences();
  assert.equal(f.reads.length,0,kind+': stale records dispatched a thumbnail under the new context');
  assert.equal(f.nodes.get('#editGalleryCount').textContent,'retained current count',kind+': a rejected layout callback altered retained counts');
 }
 for(const kind of ['different-case','same-case-reopen','changed-basis']){
  const f=fixture();f.ctx.renderOccurrences();assert.equal(f.reads.length,1);
  const card=f.lane.children[0];change(f.ctx,kind);f.reads[0].resolve({marker:'old-wave',duration_s:1});await tick();
  assert.equal(card.occurrenceWave,undefined,kind+': a late thumbnail mounted under the new context');
  assert.doesNotMatch(card.querySelector('.occurrence-wave').innerHTML,/old-wave/);
  card.querySelector('button').onclick();assert.equal(f.state.editSelectedSamples.size,0,kind+': retained old card changed the new case selection');
  await assert.rejects(card.editScope.samples(true),/变化/,kind+': old card menu returned samples under the new context');
 }
 const valid=fixture();valid.ctx.renderOccurrences();assert.equal(valid.reads.length,1);
 const card=valid.lane.children[0],wave={marker:'current-wave',duration_s:1};valid.reads[0].resolve(wave);await tick();
 assert.strictEqual(card.occurrenceWave,wave);assert.match(card.querySelector('.occurrence-wave').innerHTML,/current-wave/);
 valid.ctx.renderOccurrences();assert.strictEqual(valid.lane.children[0],card,'valid same-case repaint detached current DOM');assert.equal(valid.reads.length,1,'valid same-case repaint reread its retained wave');
 console.log('PASS: new-case, same-case-reopen and changed-basis reads/callbacks are isolated; current same-case DOM and wave are retained.');
})().catch(error=>{console.error(error);process.exitCode=1;});
