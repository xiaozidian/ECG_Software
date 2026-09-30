'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('static/js/overview-workbench.js','utf8'),scenario=process.argv[2];
const helpers=source.slice(source.indexOf('  // The queue is read-only:'),source.indexOf('  function afMode('));
const action=source.slice(source.indexOf('  async function action('),source.indexOf('  function bind('));
const basisCode=source.slice(source.indexOf('  const rhythmBasis='),source.indexOf('  function confirmRhythm('));
const fields=['start','end','kind','status','note'];
const esc=x=>String(x).replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;').replaceAll('>','&gt;');
const unesc=x=>x.replaceAll('&quot;','"').replaceAll('&lt;','<').replaceAll('&gt;','>').replaceAll('&amp;','&');
let focuses=0,scrolls=0,seeks=[],requests=0,accept=null,confirmation=null,currentForm=null,resolveSeek=null;
const nodes=new Map(),node=()=>({innerHTML:'',textContent:'',hidden:false,disabled:false,focus(){focuses++;},scrollIntoView(){scrolls++;},setAttribute(){}});
function qs(key){if(key==='#ovEpisodeForm')return currentForm;if(!nodes.has(key))nodes.set(key,node());return nodes.get(key);}
Object.defineProperty(qs('#ovEpisodeEditor'),'innerHTML',{get(){return this.html||'';},set(html){
  this.html=html;
  if(!html.includes('id="ovEpisodeForm"')){currentForm=null;return;}
  currentForm={elements:{}};
  for(const k of fields){let value;
    if(k==='note')value=html.match(/<textarea[^>]*>([\s\S]*?)<\/textarea>/)[1];
    else if(k==='start'||k==='end')value=html.match(new RegExp('name="'+k+'"[^>]*value="([^"]*)"'))[1];
    else value=html.match(new RegExp('<select name="'+k+'">([\\s\\S]*?)<\\/select>'))[1].match(/value="([^"]*)" selected/)[1];
    currentForm.elements[k]={value:unesc(value)};
  }
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
  dialog:(title,body,fn)=>{accept=fn;},E:require('../static/js/overview-engine.js'),
  confirmRhythm:(title,doc)=>{confirmation=doc;},
  FormData:class{constructor(form){this.form=form;}get(k){return this.form.elements[k].value;}},
};
vm.createContext(c);vm.runInContext('let episodeFilter="all",episodePage=0,episodeNavigation=0,episodeEditor=null;const episodeDrafts=new Map();'+basisCode+helpers+action,c);
const call=s=>vm.runInContext(s,c);
const result=s=>JSON.parse(JSON.stringify(call(s)));
const select=async(id='e:0003')=>{await call(`locateEpisode(${JSON.stringify(id)})`);};
const edit=value=>{currentForm.elements.note.value=value;currentForm.oninput();};
(async()=>{
  if(scenario==='summary-saved-only'){
    await select('e:0001');
    const before=qs('#ovAFSummary').innerHTML;
    currentForm.elements.status.value='pending';currentForm.oninput();call('renderEpisodes()');
    assert.equal(qs('#ovAFSummary').innerHTML,before);
    assert.match(before,/已确认房颤/);assert.match(before,/已确认房扑/);assert.match(before,/分母：完整记录/);
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
    c.ui.rhythm.document.episodes=[];call('renderEpisodes()');assert.match(qs('#ovEpisodeRows').innerHTML,/不代表排除房颤/);assert.equal(result('episodeQueue().pages'),1);return;
  }
  if(scenario==='empty-filter'){
    c.ui.rhythm.document.episodes=[episodes[0]];await call('action("episode-filter:confirmed")');assert.match(qs('#ovEpisodeRows').innerHTML,/此筛选下没有片段/);assert.equal(call('episodeQueue().after'),undefined);return;
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
    await select();assert.equal(currentForm.elements.note.value,'draft <script> & 中文');assert.match(qs('#ovEpisodeDraftHint').textContent,/不能直接覆盖/);return;
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
    c.ui.rhythm={...c.ui.rhythm,revision:4};call('renderEpisodes()');assert.equal(currentForm.elements.note.value,'draft <script> & 中文');assert.match(qs('#ovEpisodeDraftHint').textContent,/不能直接覆盖/);
    assert.match(qs('#ovEpisodeEditor').innerHTML,/type="submit"[^>]* disabled/);
    // Even programmatic submission cannot bypass the captured revision guard.
    let caught;c.run=fn=>{try{fn();}catch(e){caught=e;}};currentForm.onsubmit({preventDefault(){},target:currentForm});assert.match(caught.message,/修订已变化/);assert.equal(confirmation,null);return;
  }
  if(scenario==='save-clears-draft'){
    c.ui.rhythm.document.episodes[3]={...episodes[3],note:'draft <script> & 中文'};c.ui.rhythm.revision++;call('renderEpisodes()');assert.equal(call('episodeDrafts.size'),0);assert.match(qs('#ovEpisodeDraftHint').textContent,/浏览不会确认/);
    assert.match(qs('#ovEpisodeFilter').innerHTML,/本地未保存（0）/);assert(!qs('#ovEpisodeRows').innerHTML.includes(' · 未保存'));return;
  }
  if(scenario==='discard'){
    await call('action("episode-discard")');assert.equal(call('episodeDrafts.size'),1);qs('#ovDialog').close=()=>{};await accept();assert.equal(call('episodeDrafts.size'),0);assert.equal(currentForm.elements.note.value,'note');return;
  }
  if(scenario==='discard-stale'){
    await call('action("episode-discard")');c.ui.revision++;assert.throws(()=>accept(),/修订已变化/);assert.equal(call('episodeDrafts.size'),1);return;
  }
  throw Error('unknown '+scenario);
})().catch(e=>{console.error(e);process.exitCode=1;});
