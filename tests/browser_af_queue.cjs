'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('static/js/overview-workbench.js','utf8'),scenario=process.argv[2];
const helpers=source.slice(source.indexOf('  // The queue is read-only:'),source.indexOf('  function afMode('));
const action=source.slice(source.indexOf('  async function action('),source.indexOf('  function bind('));
const basisCode=source.slice(source.indexOf('  const rhythmBasis='),source.indexOf('  function confirmRhythm('));
const boundaryCode=source.slice(source.indexOf('  const afClock='),source.indexOf('  // The queue is read-only:'));
const savingCode=source.slice(source.indexOf('  function syncAFSaveState('),source.indexOf('  const rhythmBasis='));
const esc=x=>String(x).replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;').replaceAll('>','&gt;');
const unesc=x=>x.replaceAll('&quot;','"').replaceAll('&lt;','<').replaceAll('&gt;','>').replaceAll('&amp;','&');
let focuses=0,scrolls=0,seeks=[],requests=0,accept=null,confirmation=null,currentForm=null,resolveSeek=null;
const nodes=new Map(),node=()=>({innerHTML:'',textContent:'',value:'',hidden:false,disabled:false,dataset:{},focus(){focuses++;},scrollIntoView(){scrolls++;},setAttribute(){}});
function qs(key){
  if(key==='#ovEpisodeForm')return currentForm;
  if(key.startsWith('#ovEpisodeForm '))return currentForm?.querySelector(key.slice('#ovEpisodeForm '.length));
  if(key==='#ovEpisodeEditor details')return null;
  if(!nodes.has(key))nodes.set(key,node());return nodes.get(key);
}
// A small form DOM adapter for the shipped flat editor. Its controls, disabled
// states and input events are real fixture state, not string-presence stubs.
function formNode(html){
  const controls=[],buttons=new Map(),elements={};
  for(const match of html.matchAll(/<input\b([^>]*)>/g)){
    const attrs=match[1],name=attrs.match(/\bname="([^"]+)"/)?.[1];
    if(name){const item={...node(),name,value:unesc(attrs.match(/\bvalue="([^"]*)"/)?.[1]||'')};elements[name]=item;controls.push(item);}
  }
  for(const match of html.matchAll(/<select\b([^>]*)>([\s\S]*?)<\/select>/g)){
    const name=match[1].match(/\bname="([^"]+)"/)[1],value=match[2].match(/value="([^"]*)"\s+selected/)?.[1]||match[2].match(/value="([^"]*)"/)?.[1]||'';
    const item={...node(),name,value:unesc(value)};elements[name]=item;controls.push(item);
  }
  for(const match of html.matchAll(/<button\b([^>]*)>([\s\S]*?)<\/button>/g)){
    const attrs=match[1],action=attrs.match(/data-ov="([^"]*)"/)?.[1];
    const item={...node(),textContent:unesc(match[2]),hidden:/\bhidden\b/.test(attrs),disabled:/\bdisabled\b/.test(attrs),dataset:{ov:action}};
    if(action)buttons.set(action,item);controls.push(item);
  }
  const duration=node(),error=node();error.hidden=true;
  const form={elements,dataset:{stale:html.match(/data-stale="([^"]+)"/)[1]},
    querySelector(selector){
      if(selector==='[data-af-duration]')return duration;
      if(selector==='[role="alert"]')return error;
      if(selector==='#ovEpisodeDraftHint')return qs(selector);
      const name=selector.match(/^\[name="([^"]+)"\]$/)?.[1];if(name)return elements[name]||null;
      const action=selector.match(/^\[data-ov="([^"]+)"\]$/)?.[1];if(action)return buttons.get(action)||null;
      return null;
    },querySelectorAll(){return controls;}};
  return form;
}
Object.defineProperty(qs('#ovEpisodeEditor'),'innerHTML',{get(){return this.html||'';},set(html){
  this.html=html;
  if(!html.includes('id="ovEpisodeForm"')){currentForm=null;return;}
  currentForm=formNode(html);
}});
const episodes=Array.from({length:1200},(_,i)=>({id:'e:'+String(i).padStart(4,'0'),start_s:i*2,end_s:i*2+1,kind:i%5?'AF':'AFL',status:['pending','confirmed','excluded'][i%3],note:'note',source:'manual'}));
const c={ui:{id:'case',episode:null,af:true,revision:2,rhythm:{revision:3,document:{episodes},can_undo:true,can_redo:false}},state:{caseId:'case',caseData:{},duration:10},
  qs,esc,copy:x=>JSON.parse(JSON.stringify(x)),duration:()=>86400,formatElapsedPrecise:String,formatElapsed:String,
  name:x=>x==='AF'?'房颤':'房扑',statusName:x=>({pending:'待复核',confirmed:'医生确认',excluded:'已排除'})[x],
  button:(label,action,attrs='')=>`<button data-ov="${action}" ${attrs}>${label}</button>`,
  innerWidth:1366,overviewReady:true,coverageFocus:0,renderGapNavigation:()=>{},
  coverageBasis:()=>({id:c.state.caseId,revision:c.ui.revision,data:c.state.caseData}),
  sameCoverageBasis:b=>b.id===c.state.caseId&&b.revision===c.ui.revision&&b.data===c.state.caseData,
  seek:async(...args)=>{seeks.push(args);if(scenario.startsWith('race-'))await new Promise(r=>resolveSeek=r);},
  run:fn=>Promise.resolve().then(fn),closeMenu:()=>{},
  ECGRhythmRangeEditor:require('../static/js/rhythm-range-editor.js'),draw(){},renderWaveform(){},
  dialog:(title,body,fn)=>{accept=fn;},E:require('../static/js/overview-engine.js'),
  confirmRhythm:(title,doc)=>{confirmation=doc;},
  saveRhythm:async doc=>{requests++;confirmation=doc;},
  FormData:class{constructor(form){this.form=form;}get(k){return this.form.elements[k].value;}},
};
vm.createContext(c);vm.runInContext('let episodeFilter="all",episodePage=0,episodeNavigation=0,episodeEditor=null;const episodeDrafts=new Map();'+basisCode+boundaryCode+savingCode+helpers+action,c);
const call=s=>vm.runInContext(s,c);
const result=s=>JSON.parse(JSON.stringify(call(s)));
const select=async(id='e:0003')=>{await call(`locateEpisode(${JSON.stringify(id)})`);};
const edit=value=>{currentForm.elements.note.value=value;currentForm.oninput({target:currentForm.elements.note});};
const input=(name,value)=>{currentForm.elements[name].value=value;currentForm.oninput({target:currentForm.elements[name]});};
(async()=>{
  if(scenario==='summary-saved-only'){
    await select('e:0001');
    const before=qs('#ovAFSummary').innerHTML;
    currentForm.elements.status.value='pending';currentForm.oninput({target:currentForm.elements.status});call('renderEpisodes()');
    assert.equal(qs('#ovAFSummary').innerHTML,before);
    assert.match(before,/已确认房颤 320 段/);assert.match(before,/320\.000 秒/);assert.match(before,/已确认房扑 80 段/);assert.match(before,/80\.000 秒/);
    c.ui.rhythm.document.episodes[1]={...episodes[1],status:'pending'};c.ui.rhythm.revision++;call('renderEpisodes()');
    assert.notEqual(qs('#ovAFSummary').innerHTML,before);return;
  }
  if(scenario==='bounded'){
    const before=JSON.stringify(episodes);call('renderEpisodes()');
    assert.equal((qs('#ovEpisodeRows').innerHTML.match(/<tr/g)||[]).length,20);
    assert.deepEqual(result('episodeQueue().counts'),{all:1200,pending:400,confirmed:400,excluded:400,drafts:0});
    assert.match(qs('#ovEpisodePages').innerHTML,/1 \/ 60/);
    await call('action("episode-page:59")');assert.match(qs('#ovEpisodeRows').innerHTML,/e%3A1199/);
    await assert.rejects(call('action("episode-page:60")'),/页码/);
    assert.equal(JSON.stringify(episodes),before);assert.equal(confirmation,null);return;
  }
  if(scenario==='filter'){
    for(const status of ['pending','confirmed','excluded']){await call(`action("episode-filter:${status}")`);assert.equal(result('episodeQueue().items').length,400);assert(result('episodeQueue().visible').every(x=>x.status===status));}
    await assert.rejects(call('action("episode-filter:unknown")'),/筛选/);return;
  }
  if(scenario==='sort'){
    c.ui.rhythm.document.episodes=[...episodes].reverse();const before=JSON.stringify(c.ui.rhythm.document.episodes);
    assert.equal(result('episodeQueue().items')[0].id,'e:0000');assert.equal(JSON.stringify(c.ui.rhythm.document.episodes),before);return;
  }
  if(scenario==='empty'){
    c.ui.rhythm.document.episodes=[];call('renderEpisodes()');assert.match(qs('#ovEpisodeRows').innerHTML,/暂无片段/);assert.equal(result('episodeQueue().pages'),1);assert.equal(result('episodeQueue().items').length,0);assert.equal(currentForm,null);assert.equal(confirmation,null);return;
  }
  if(scenario==='empty-filter'){
    c.ui.rhythm.document.episodes=[episodes[0]];await call('action("episode-filter:confirmed")');assert.match(qs('#ovEpisodeRows').innerHTML,/此筛选下无片段/);assert.equal(call('episodeQueue().after'),undefined);assert.equal(result('episodeQueue().items').length,0);assert.equal(confirmation,null);return;
  }
  if(scenario.startsWith('race-')){
    const p=call('locateEpisode("e:0003")'),first=resolveSeek;
    if(scenario==='race-case')c.state.caseId='other';
    if(scenario==='race-beats')c.ui.revision++;
    if(scenario==='race-rhythm')c.ui.rhythm.revision++;
    if(scenario==='race-source')c.state.caseData={};
    if(scenario==='race-close')c.ui.af=false;
    if(scenario==='race-navigation'){
      const second=call('locateEpisode("e:0006")');first();await p;assert.equal(focuses,0);resolveSeek();await second;assert.equal(focuses,1);return;
    }
    first();await p;assert.equal(focuses,0);assert.equal(confirmation,null);return;
  }
  await select();
  if(scenario==='boundary-sync'){
    input('startClock','+6.500');input('endClock','+7.500');
    assert.equal(currentForm.elements.start.value,'6.5');assert.equal(currentForm.elements.end.value,'7.5');
    assert.deepEqual(Array.from(c.ui.range),[6.5,7.5]);assert.equal(currentForm.querySelector('[data-af-duration]').textContent,'1.000 s');
    await call('action("episode-start")');assert.deepEqual(seeks.at(-1),[4.5,true,6.5]);
    await call('action("episode-end")');assert.deepEqual(seeks.at(-1),[6.5,true,7.495]);
    assert.equal(requests,0);assert.equal(episodes[3].start_s,6);assert.equal(episodes[3].end_s,7);return;
  }
  if(scenario==='confirmed-edit-pending'){
    await select('e:0004');assert.equal(currentForm.elements.status.value,'confirmed');
    const summary=qs('#ovAFSummary').innerHTML;input('startClock','+8.005');
    assert.equal(currentForm.elements.start.value,'8.005');assert.equal(currentForm.elements.status.value,'pending');
    assert.deepEqual(Array.from(c.ui.range),[8.005,9]);assert.equal(qs('#ovAFSummary').innerHTML,summary);
    assert.equal(episodes[4].status,'confirmed');assert.equal(requests,0);return;
  }
  if(scenario==='explicit-save-kind'){
    input('kind','AFL');edit('new AFL note');await call('action("af-save:pending")');
    assert.equal(requests,1);const saved=confirmation.episodes.find(x=>x.id==='e:0003');
    assert.deepEqual(JSON.parse(JSON.stringify(saved)),{id:'e:0003',start_s:6,end_s:7,kind:'AFL',status:'pending',source:'manual',note:'new AFL note'});
    assert.equal(episodes[3].kind,'AF');assert.equal(episodes[3].note,'note');return;
  }
  if(scenario==='navigation'){
    assert.deepEqual(seeks[0],[4,true,6]);assert.equal(c.ui.range.join(','),'6,7');
    await call('action("episode-end")');assert.deepEqual(seeks[1],[6,true,6.995]);
    await call('action("episode:e%3A0060")');assert.equal(c.ui.episode,'e:0060');assert.equal(call('episodePage'),3);
    assert.equal(confirmation,null);return;
  }
  if(scenario==='after-confirm'){
    await call('action("episode-filter:pending")');c.ui.rhythm.document.episodes[3]={...episodes[3],status:'confirmed'};c.ui.rhythm.revision++;
    call('renderEpisodes()');assert.equal(result('episodeQueue().after').id,'e:0006');assert.equal(result('episodeQueue().before').id,'e:0000');
    assert.match(qs('#ovEpisodeNavigation').innerHTML,/当前片段不在此筛选内/);return;
  }
  edit('draft <script> & 中文');
  if(scenario==='removed-draft'){
    c.ui.rhythm.document.episodes=episodes.filter(x=>x.id!=='e:0003');c.ui.rhythm.revision++;
    await select('e:0006');await call('action("episode-filter:drafts")');assert.match(qs('#ovEpisodeRows').innerHTML,/片段已移除/);
    await select();assert.equal(currentForm.elements.note.value,'draft <script> & 中文');assert.equal(currentForm.dataset.stale,'true');assert(currentForm.querySelector('[data-ov="af-save:pending"]').disabled);await assert.rejects(call('action("af-save:pending")'),/修订已变化/);assert.equal(requests,0);return;
  }
  if(scenario==='retain-form'){
    const original=currentForm;await call('action("episode-filter:pending")');await call('action("episode-page:1")');assert.equal(currentForm,original);assert.equal(currentForm.elements.note.value,'draft <script> & 中文');return;
  }
  if(scenario==='retain-navigation'){
    await select('e:0006');assert.equal(currentForm.elements.note.value,'note');await select();assert.equal(currentForm.elements.note.value,'draft <script> & 中文');assert(!qs('#ovEpisodeEditor').innerHTML.includes('<script>'));return;
  }
  if(scenario==='case-isolation'){
    c.ui.id=c.state.caseId='other';await select();assert.equal(currentForm.elements.note.value,'note');c.ui.id=c.state.caseId='case';await select();assert.equal(currentForm.elements.note.value,'draft <script> & 中文');return;
  }
  if(scenario==='stale-draft'){
    c.ui.rhythm={...c.ui.rhythm,revision:4};call('renderEpisodes()');assert.equal(currentForm.elements.note.value,'draft <script> & 中文');assert.equal(currentForm.dataset.stale,'true');
    assert(currentForm.querySelector('[data-ov="af-save:pending"]').disabled);
    // The actual explicit-save action must enforce the captured revision too.
    await assert.rejects(call('action("af-save:pending")'),/修订已变化/);assert.equal(confirmation,null);assert.equal(requests,0);return;
  }
  if(scenario==='save-clears-draft'){
    c.ui.rhythm.document.episodes[3]={...episodes[3],note:'draft <script> & 中文'};c.ui.rhythm.revision++;call('renderEpisodes()');assert.equal(call('episodeDrafts.size'),0);assert.equal(currentForm.elements.status.value,'pending');assert.equal(qs('#ovEpisodeDraftHint').textContent,'待复核');
    assert.match(qs('#ovEpisodeFilter').innerHTML,/本地未保存（0）/);assert(!qs('#ovEpisodeRows').innerHTML.includes(' · 未保存'));return;
  }
  if(scenario==='discard'){
    await call('action("episode-discard")');assert.equal(call('episodeDrafts.size'),0);assert.equal(currentForm.elements.note.value,'note');assert.equal(requests,0);assert.equal(accept,null);return;
  }
  if(scenario==='discard-stale'){
    c.ui.revision++;call('renderEpisodes()');assert.equal(currentForm.dataset.stale,'true');const before=JSON.stringify(c.ui.rhythm.document);await call('action("episode-discard")');assert.equal(call('episodeDrafts.size'),0);assert.equal(currentForm.elements.note.value,'note');assert.equal(JSON.stringify(c.ui.rhythm.document),before);assert.equal(requests,0);return;
  }
  throw Error('unknown '+scenario);
})().catch(e=>{console.error(e);process.exitCode=1;});
