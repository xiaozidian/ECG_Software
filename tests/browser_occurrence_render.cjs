/* Exercise the actual renderer with a small DOM model; not a browser timing claim. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('static/js/clinical-ui.js','utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const gate=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}};
function fixture(){
  const metrics={cards:0,svg:0,reads:0},scopes=new WeakMap(),document={activeElement:null};
  class Element{
    constructor(tag='div'){this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.style={setProperty(){}};this.classList={add(){}};this.scrollTop=0;this.clientWidth=1020;this.attributes={};}
    set scrollTop(value){this._scrollTop=this.dataset.readState==='loading'?0:value}
    get scrollTop(){return this._scrollTop||0}
    get isConnected(){return this===host||Boolean(this.parentElement?.isConnected)}
    get firstElementChild(){return this.children[0]||null}
    get nextElementSibling(){const siblings=this.parentElement?.children||[];return siblings[siblings.indexOf(this)+1]||null}
    setAttribute(k,v){this.attributes[k]=v} removeAttribute(k){delete this.attributes[k]}
    setCustomValidity(value){this.validationMessage=value} reportValidity(){this.validityReported=true}
    contains(node){return this===node||this.children.some(x=>x.contains(node))}
    focus(){document.activeElement=this}
    closest(){return this.dataset.occIndex!==undefined?this:this.parentElement?.closest()}
    remove(){if(this.contains(document.activeElement))document.activeElement=null;const p=this.parentElement;if(p)p.children.splice(p.children.indexOf(this),1);this.parentElement=null;}
    insertBefore(child,before){if(child===before)return child;child.remove();child.parentElement=this;const i=this.children.indexOf(before);this.children.splice(i<0?this.children.length:i,0,child);return child}
    appendChild(child){return this.insertBefore(child,null)}
    replaceChildren(...children){this.innerHTML='';children.forEach(child=>this.appendChild(child))}
    after(child){this.parentElement?.insertBefore(child,this.nextElementSibling)}
    set innerHTML(value){for(const child of [...this.children])child.remove();this.html=value;
      if(value.includes('class="occurrence-lane"')){const n=new Element();n.className='occurrence-lane';this.appendChild(n)}
      if(value.includes('class="occurrence-open"')){metrics.cards++;const button=new Element('button'),wave=new Element('span'),input=new Element('input');wave.className='occurrence-wave';input.checked=value.includes("'checked'")||value.includes(' checked>');button.appendChild(wave);this.appendChild(button);this.appendChild(input)}
    }
    get innerHTML(){return this.html||''}
    querySelector(selector){
      const match=selector.match(/^\[data-occ-index="(\d+)"\](?: (button|input))?$/);
      if(match){const card=this.all().find(x=>String(x.dataset.occIndex)===match[1]);return (match[2]?card?.querySelector(match[2]):card)||null}
      return this.all().find(x=>selector.startsWith('.')?x.className===selector.slice(1):selector.startsWith('input')?x.tagName==='INPUT':x.tagName===selector.toUpperCase())||null;
    }
    all(){return this.children.flatMap(x=>[x,...x.all()])}
    querySelectorAll(){return this.all().filter(x=>x.dataset.occIndex!==undefined)}
  }
  const host=new Element(),nodes=new Map([['#editTemplateGallery',host]]);
  document.createElement=tag=>new Element(tag);
  const items=Array.from({length:240},(_,n)=>({event_id:'event-'+n,basis_version:'v1',sample_index:(n+1)*200,start_sample:(n+1)*200,end_sample:(n+1)*200,time_s:n+1,target_samples:[(n+1)*200],templates:[],beat_count:1,label:'正常',diagnosis_status:'source'}));
  const wave={leads:{II:Array.from({length:480},(_,i)=>Math.sin(i)*200),V1:Array(480).fill(2),V5:Array(480).fill(3)},duration_s:2.4,start_s:0,beats:[]};
  const retained=[];
  const context=vm.createContext({document,console,AbortController,state:{caseId:'A',caseRequestId:1,currentPage:'edit',editLead:'II',editSelectedSamples:new Set()},occurrenceContext:{id:'A',caseToken:1,evidenceScope:'A-r1'},occurrenceReadAbort:null,rhythmWrite:null,occurrenceToken:1,occurrence:{total:240},waveEvidenceScope:'A-r1',tileWidth:0,type:'N',editCase:'A',editMode:'all',template:'all',reportWaveCache:new Map(),pageCache:new Map(Array.from({length:5},(_,i)=>[i*48,items.slice(i*48,i*48+48)])),thumbnailCache:{retain:(owner,keys)=>retained.push({owner,keys}),clear(){}},
    qs:s=>{if(!nodes.has(s))nodes.set(s,new Element());return nodes.get(s)},ECGReviewTools:require('../static/js/clinical-review-tools.js'),ECGOccurrenceCard:require('../static/js/occurrence-card.js'),esc:String,formatElapsed:String,modeLabel:()=> '全部',syncEditTimeSlider(){},setEditStart(){},renderEditScatter(){},
    beatEditor:{registerOccurrence:(card,item,scope)=>scopes.set(card,{item,scope}),syncOccurrenceSelection(){}},
    eventWave:()=>{metrics.reads++;return Promise.resolve(wave)}});
  context.filters=()=>{};context.renderEditDensity=()=>{};context.syncWaveEvidence=()=>{};context.morphologyWorkbench={};context.loadMorphology=async()=>{};context.handleError=error=>{throw error};
  context.updateTemplates=()=>{};
  context.run=fn=>Promise.resolve().then(fn).catch(context.handleError);
  vm.runInContext(source.slice(source.indexOf('  function sameEvidence('),source.indexOf('  let reportCase=')),context);
  vm.runInContext(source.slice(source.indexOf('  function editParams('),source.indexOf('  async function loadMorphology(')),context);
  vm.runInContext(source.slice(source.indexOf('  function svg('),source.indexOf('  async function eventWave(')),context);
  const svg=context.svg;context.svg=(...args)=>{metrics.svg++;return svg(...args)};
  vm.runInContext(source.slice(source.indexOf('  function renderOccurrences('),source.indexOf('  async function refreshReport(')),context);
  context.bindOccurrenceJump();
  const render=()=>context.renderOccurrences(),card=n=>host.querySelector(`[data-occ-index="${n}"]`);
  return {context,host,document,metrics,scopes,items,render,card,wave,retained};
}
async function main(which){
  const f=fixture(),{context:c,host,metrics,render,card,document,scopes}=f;
  if(which==='viewport-rows'){
    c.innerWidth=1280;c.state.editMode='cluster';host.dataset.workspaceRows='1';render();await tick();
    assert.equal(c.qs('#editGalleryCount').textContent,'1–6 / 240');
    const samples=await scopes.get(card(0)).scope.samples(true);
    assert.deepEqual([...samples],[200,400,600,800,1000,1200]);
    assert(host.querySelector('.occurrence-lane').children.length>6,'test must include loaded off-screen rows');
    host.scrollTop=142;render();await tick();assert.equal(c.qs('#editGalleryCount').textContent,'7–12 / 240');
    assert.deepEqual([...(await scopes.get(card(6)).scope.samples(true))],[1400,1600,1800,2000,2200,2400]);return;
  }
  const input=c.qs('#occJump'),go=c.qs('#occGo'),response=(total=20)=>({total,items:f.items.slice(0,total)});
  if(which.startsWith('read-')){
    const pending=gate(),signals=[];c.endpoint=(_,params,id,options)=>{signals.push(options.signal);return pending.promise};
    const first=c.loadOccurrences(),cancel=host.children.find(x=>x.dataset.occurrenceRead==='cancel');assert(cancel);assert.equal(host.dataset.readState,'loading');assert.equal(signals[0].aborted,false);
    if(which==='read-retry'){
      pending.reject(Error('503'));await assert.rejects(first,/503/);assert.equal(host.dataset.readState,'error');const retry=host.children.find(x=>x.dataset.occurrenceRead==='retry');assert(retry);c.qs('#occSearch').value='保留输入';c.endpoint=async()=>response(5);retry.onclick();await tick();await tick();assert.equal(c.occurrence.total,5);assert.equal(c.qs('#occSearch').value,'保留输入');assert.equal(input.value,'1');assert.equal(input.disabled,false);return;
    }
    if(which==='read-superseded'){
      const next=gate();c.endpoint=(_,params,id,options)=>{signals.push(options.signal);return next.promise};const second=c.loadOccurrences();assert.equal(signals[0].aborted,true);cancel.onclick();assert.equal(signals[1].aborted,false,'obsolete cancel stopped the current request');next.resolve(response(5));await second;pending.resolve(response(200));await first;assert.equal(c.occurrence.total,5);assert.equal(host.dataset.readState,'ready');return;
    }
    if(which==='read-leave'){c.state.currentPage='report';c.releaseOccurrenceWaves();assert.equal(signals[0].aborted,true);pending.resolve(response());await first;assert.equal(c.occurrence,null);return;}
    cancel.onclick();assert.equal(signals[0].aborted,true);assert.equal(host.dataset.readState,'cancelled');pending.resolve(response());await first;assert.equal(c.occurrence,null);assert.equal(metrics.cards,0);assert(host.children.some(x=>x.dataset.occurrenceRead==='retry'));return;
  }
  if(which.startsWith('resume-')){
    render();await tick();input.value='100';go.onclick();await tick();
    c.qs('#occSearch').value='模板';const mark=c.occurrenceBookmark(20000);
    assert.equal(mark.sample,20000);
    if(['resume-filter','resume-case','resume-lifecycle','resume-token','resume-page'].includes(which)){
      if(which==='resume-filter')c.type='V';
      if(which==='resume-case')c.state.caseId='B';
      if(which==='resume-lifecycle')c.state.caseRequestId=2;
      if(which==='resume-token')c.occurrenceToken++;
      if(which==='resume-page')c.state.currentPage='report';
      c.endpoint=()=>{throw Error('stale bookmark must not fetch/reset')};
      const top=host.scrollTop;await c.loadOccurrences(mark);assert.equal(host.scrollTop,top);return;
    }
    if(which==='resume-scrolled'){host.scrollTop=0;render();await tick();}
    const pending=gate();let params;
    c.endpoint=async(_,p)=>{params=p;return pending.promise};const loading=c.loadOccurrences(mark);
    assert.equal(params.near_sample,which==='resume-scrolled'?200:20000);
    if(which==='resume-late-lifecycle')c.state.caseRequestId=2;
    if(which==='resume-no-focus')input.focus();
    const empty=which==='resume-empty',index=which==='resume-scrolled'?0:99,offset=Math.floor(index/48)*48;
    pending.resolve({total:empty?0:240,offset:empty?0:offset,items:empty?[]:f.items.slice(offset,offset+48),resume_index:empty?null:index,resume_exact:which==='resume-exact',resume_sample:empty?null:f.items[index].sample_index});
    await loading;
    if(which==='resume-late-lifecycle'){assert.equal(c.occurrence,null);return;}
    if(empty){assert.equal(input.disabled,true);assert.equal(c.qs('#occResume').hidden,true);return;}
    assert.equal(host.scrollTop>0,which!=='resume-scrolled');assert.ok(card(index));assert.equal(input.value,String(index+1));assert.equal(c.state.editSelectedSamples.size,0);
    const button=c.qs('#occResume');assert.equal(button.hidden,false);assert.match(button.textContent,which==='resume-exact'?/原时间位置/:/未自动勾选/);
    if(which==='resume-no-focus')assert.equal(document.activeElement,input);
    button.onclick();await tick();assert.equal(document.activeElement,card(index).querySelector('button'));assert.equal(c.state.editSelectedSamples.size,0);
    assert.equal(c.qs('#occSearch').value,'模板');return;
  }
  if(which.startsWith('jump-')){
    render();await tick();input.value='100';
    if(which==='jump-reset'){
      const request=gate();c.endpoint=()=>request.promise;const loading=c.loadOccurrences();
      assert.equal(input.value,'');assert.equal(input.disabled,true);assert.equal(go.disabled,true);assert.equal(c.qs('#editGalleryCount').textContent,'读取中…');
      request.resolve(response());await loading;assert.equal(input.value,'1');assert.equal(input.max,'20');assert.equal(go.disabled,false);assert.equal(host.scrollTop,0);
    }else if(which==='jump-draft'){
      for(const value of ['120','','1.5','999']){input.value=value;host.scrollTop=142;render();await tick();assert.equal(input.value,value)}
    }else if(which==='jump-validation'){
      const position=host.scrollTop;
      for(const value of ['',0,-1,1.5,241,'Infinity','NaN',1e30]){input.value=String(value);go.onclick();assert.match(input.validationMessage,/1–240/);assert.equal(input.validityReported,true);assert.equal(host.scrollTop,position);input.oninput();assert.equal(input.validationMessage,'')}
      input.value='240';go.onclick();await tick();assert.equal(input.value,'240');assert.equal(document.activeElement,card(239).querySelector('button'));assert.equal(c.state.editSelectedSamples.size,0);
    }else if(which==='jump-enter'){
      let stopped=0,prevented=0;input.onkeydown({key:'Enter',preventDefault(){prevented++},stopPropagation(){stopped++}});await tick();
      assert.equal(stopped,1);assert.equal(prevented,1);assert.equal(document.activeElement,card(99).querySelector('button'));assert.equal(c.state.editSelectedSamples.size,0);
    }else if(which==='jump-empty'){
      c.endpoint=async()=>response(0);await c.loadOccurrences();assert.equal(input.value,'');assert.equal(go.disabled,true);assert.equal(input.disabled,true);assert.match(host.innerHTML,/0 条匹配记录/);
      go.onclick();assert.equal(host.scrollTop,0);c.endpoint=async()=>response(1);await c.loadOccurrences();assert.equal(input.value,'1');assert.equal(input.max,'1');assert.equal(go.disabled,false);
    }else if(which==='jump-failure'){
      c.endpoint=async()=>{throw Error('offline')};await assert.rejects(c.loadOccurrences(),/offline/);assert.equal(go.disabled,true);assert.equal(input.value,'');assert.equal(c.qs('#editGalleryCount').textContent,'读取失败');
      c.endpoint=async()=>response(3);await c.loadOccurrences();assert.equal(input.value,'1');assert.equal(input.max,'3');assert.equal(go.disabled,false);
    }else if(which==='jump-filter-race'||which==='jump-case-race'){
      const old=gate();c.endpoint=()=>old.promise;const first=c.loadOccurrences();
      if(which==='jump-case-race')c.state.caseId='B';else c.type='V';
      c.endpoint=async()=>response(6);await c.loadOccurrences();input.value='4';old.resolve(response(200));await first;
      assert.equal(c.occurrence.total,6);assert.equal(input.max,'6');assert.equal(input.value,'4');assert.equal(go.disabled,false);
    }else if(which==='jump-late-error'){
      const old=gate();c.endpoint=()=>old.promise;const first=c.loadOccurrences();
      c.endpoint=async()=>response(5);await c.loadOccurrences();old.reject(Error('old failure'));await first;
      assert.equal(c.occurrence.total,5);assert.equal(input.max,'5');assert.equal(go.disabled,false);assert.doesNotMatch(host.innerHTML,/加载失败/);assert.notEqual(c.qs('#editGalleryCount').textContent,'读取失败');
    }else if(['jump-lazy-focus','jump-focus-abandoned','jump-focus-scrolled','jump-lazy-filter','jump-lazy-arrow'].includes(which)){
      const page=gate();c.pageCache.delete(96);c.endpoint=()=>page.promise;
      if(which==='jump-lazy-arrow'){
        host.scrollTop=2130;render();await tick();assert.ok(card(95));card(95).querySelector('button').focus();card(95).onkeydown({key:'ArrowRight',preventDefault(){},stopPropagation(){}});
      }else go.onclick();
      assert.equal(document.activeElement,host);
      if(which==='jump-focus-abandoned')input.focus();
      if(which==='jump-focus-scrolled'){host.scrollTop=0;render()}
      if(which==='jump-lazy-filter'){c.endpoint=async()=>response(7);await c.loadOccurrences();input.value='3'}
      page.resolve({total:240,items:f.items.slice(96,144)});await tick();await tick();
      if(which==='jump-focus-abandoned')assert.equal(document.activeElement,input);
      else if(which==='jump-focus-scrolled')assert.equal(document.activeElement,host);
      else if(which==='jump-lazy-filter'){assert.equal(c.occurrence.total,7);assert.equal(input.value,'3');assert.equal(card(99),null)}
      else assert.equal(document.activeElement,card(which==='jump-lazy-arrow'?96:99).querySelector('button'));
      assert.equal(c.state.editSelectedSamples.size,0);
    }else throw Error('Unknown jump test '+which);
    return;
  }
  if(which==='failure-retry'){
    c.eventWave=()=>Promise.reject(Error('offline'));render();await tick();assert.match(card(0).querySelector('.occurrence-wave').textContent,/点击重试/);
    c.eventWave=()=>Promise.resolve(f.wave);card(0).querySelector('button').onclick();await tick();assert.equal(metrics.svg,1);return;
  }
  if(which==='late-response'){
    const old=gate(),fresh=gate();c.eventWave=()=>old.promise;render();const prior=card(0);
    c.state.editLead='V5';c.eventWave=()=>fresh.promise;render();old.resolve(f.wave);await tick();
    assert.equal(metrics.svg,0);assert.equal(prior.isConnected,false);fresh.resolve(f.wave);await tick();assert.equal(metrics.svg,24);return;
  }
  render();await tick();const initial=card(6),base=metrics.svg;
  if(which==='inactive'){
    c.state.currentPage='report';host.scrollTop=568;render();await tick();assert.equal(metrics.svg,base);assert.equal(f.retained.at(-1).keys.length,0);return;
  }
  if(which==='navigation'){
    let blocked=true,releases=0;c.clinicalUI={releaseOccurrenceWaves:()=>releases++};c.goPage=name=>{if(!blocked)c.state.currentPage=name};
    vm.runInContext(source.slice(source.indexOf('const goPageLegacy='),source.indexOf('const setEditModeLegacy=')),c);
    c.goPage('report');assert.equal(releases,0);blocked=false;c.goPage('report');assert.equal(releases,1);return;
  }
  if(which==='demand'){
    assert.equal(f.retained.at(-1).owner,'occurrence');assert.equal(f.retained.at(-1).keys.length,24);
    host.scrollTop=568;render();await tick();assert.equal(f.retained.at(-1).keys.length,30);assert.ok(f.retained.at(-1).keys.every(key=>Number(key.split('|')[3].slice(6))>=18));
    c.occurrence.total=0;render();assert.equal(f.retained.at(-1).keys.length,0);return;
  }
  if(which==='benchmark'||which==='reuse'){
    const start=performance.now();for(let n=1;n<=120;n++){host.scrollTop=n;render();await tick()}
    const result={frames:120,initialCards:base,totalCards:metrics.cards,totalWaveSerializations:metrics.svg,totalWaveLookups:metrics.reads,elapsedMs:+(performance.now()-start).toFixed(3)};
    if(which==='benchmark'){console.log(JSON.stringify(result));return}
    assert.equal(metrics.svg,base);assert.equal(card(6),initial);
  }else if(which==='rows'){
    host.scrollTop=284;render();await tick();assert.equal(card(6),initial);assert.equal(card(0),null);assert.equal(metrics.svg,36);assert.equal(host.querySelector('.occurrence-lane').children.length,30);
    host.scrollTop=0;render();await tick();assert.equal(card(6),initial);assert.deepEqual(host.querySelector('.occurrence-lane').children.map(n=>Number(n.dataset.occIndex)),Array.from({length:24},(_,i)=>i));
  }else if(which==='scope'){
    const reads=metrics.reads;c.waveEvidenceScope='A-r2';render();await tick();assert.equal(card(6),initial);assert.equal(metrics.reads,reads,'unvalidated basis dispatched old records');
    c.occurrenceContext={id:'A',caseToken:1,evidenceScope:'A-r2'};render();await tick();assert.notEqual(card(6),initial);const revised=card(6);c.occurrenceToken++;render();await tick();assert.notEqual(card(6),revised);
    const filtered=card(6),beforeCaseReads=metrics.reads;c.state.caseId='B';c.state.caseRequestId=2;render();await tick();assert.equal(metrics.reads,beforeCaseReads,'old case records dispatched under the new case');
    c.waveEvidenceScope='B-r1';c.occurrenceContext={id:'B',caseToken:2,evidenceScope:'B-r1'};render();await tick();assert.notEqual(card(6),filtered);
  }else if(which==='selection'){
    c.state.editSelectedSamples.add(1400);render();assert.equal(card(6).querySelector('input').checked,true);
    host.scrollTop=142;render();await tick();const actual=await scopes.get(initial).scope.samples(true);assert.equal(actual[0],1400);assert.equal(actual.length,12);
  }else if(which==='focus'){
    initial.querySelector('input').focus();const focused=document.activeElement;host.scrollTop=40;render();await tick();assert.equal(document.activeElement,focused);assert.equal(focused.isConnected,true);
  }else if(which==='resize'){
    host.clientWidth=510;render();await tick();assert.equal(card(6),initial);const before=metrics.svg;
    initial.onkeydown({key:'ArrowDown',stopPropagation(){},preventDefault(){}});await tick();assert.equal(document.activeElement.closest().dataset.occIndex,9);assert.equal(host.scrollTop,426);assert.ok(metrics.svg>=before);
  }else if(which==='replaced-item'){
    c.pageCache.get(0)[6]={...f.items[6],label:'已修订',target_samples:[9999]};render();await tick();assert.notEqual(card(6),initial);assert.equal(scopes.get(card(6)).item.target_samples[0],9999);assert.equal(metrics.svg,base+1);
  }else throw Error('Unknown test '+which);
}
main(process.argv[2]||'reuse').catch(e=>{console.error(e);process.exitCode=1});
