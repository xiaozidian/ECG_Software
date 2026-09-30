const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
async function main(scenario){
  if(scenario==='headers'){
    const source=fs.readFileSync('static/js/app.js','utf8');let options;
    const context=vm.createContext({state:{workspaceEpoch:'recovered',caseId:null},fetch:async(_,o)=>{
      options=o;return {ok:true,headers:{get:()=> 'application/json'},json:async()=>({})};}});
    vm.runInContext(source.slice(source.indexOf('async function api('),source.indexOf('\nfunction toast(')),context);
    await context.api('/api/workspace/backups',{method:'POST',headers:{'X-Test':'one'}});
    assert.equal(options.headers['X-CardioInsight-Workspace'],'recovered');
    assert.equal(options.headers['X-CardioInsight-Request'],'1');assert.equal(options.headers['X-Test'],'one');return;
  }
  class Element{
    constructor(){this.children=[];this.checked=false;this.textContent='';this.attributes={};this.classList={toggle:()=>{}};}
    append(...items){this.children.push(...items);}
    replaceChildren(){this.children=[];}
    setAttribute(k,v){this.attributes[k]=v;}
    querySelectorAll(){return this.children.flatMap(row=>row.children.filter(el=>el.type==='button'));}
  }
  const ids=['createWorkspaceBackup','backupAcknowledged','backupStatus','backupList','refreshWorkspaceBackups','backupLocation','restoredWorkspaceNotice'];
  const elements=Object.fromEntries(ids.map(key=>[key,new Element()]));
  const panel=new Element();panel.querySelector=id=>elements[id.slice(1)];
  let calls=[],holdResolve,hold=false,failing=false,refreshFail=false;
  const state={reportDirty:false};
  const context=vm.createContext({state,document:{querySelector:()=>panel,createElement:()=>new Element()},
    loadSettings:async()=>{},api:async(path,options)=>{
      calls.push([path,options]);
      if(!options){if(refreshFail)throw Error('列表失败');return {enabled:scenario!=='disabled',reason:'仅本机',directory:'/synthetic',items:[{name:'a.ecgbackup',bytes:1024}]};}
      if(hold)await new Promise(resolve=>{holdResolve=resolve;});
      if(failing)throw Error('空间不足，请重试');
      return {path:'/synthetic/a.ecgbackup',created_at:'2026-01-01T00:00:00Z',verified:true};
    }});
  vm.runInContext(fs.readFileSync('static/js/workspace-backup.js','utf8'),context);
  await context.loadSettings();
  const button=elements.createWorkspaceBackup,ack=elements.backupAcknowledged,status=elements.backupStatus;
  assert.equal(button.disabled,true);ack.checked=true;ack.onchange();
  if(scenario==='disabled'){assert.equal(button.disabled,true);await button.onclick();assert.equal(calls.length,1);return;}
  assert.equal(button.disabled,false);
  if(scenario==='dirty')state.reportDirty=true;
  if(scenario==='failure')failing=true;
  if(scenario==='refresh-failure')refreshFail=true;
  if(scenario==='verify'){
    await elements.backupList.children[0].children[1].onclick();
    assert.match(calls[1][0],/\/verify$/);assert.match(status.textContent,/校验通过/);return;
  }
  if(scenario==='busy'){
    hold=true;const task=button.onclick();assert.equal(button.disabled,true);
    assert.equal(panel.attributes['aria-busy'],'true');await button.onclick();
    assert.equal(calls.length,2);holdResolve();await task;assert.equal(panel.attributes['aria-busy'],'false');return;
  }
  await button.onclick();
  if(scenario==='dirty'){assert.equal(calls.length,1);assert.match(status.textContent,/未保存/);assert.equal(button.disabled,false);}
  else if(scenario==='failure'){
    assert.match(status.textContent,/空间不足/);assert.equal(button.disabled,false);assert.equal(ack.checked,true);
    failing=false;await button.onclick();assert.match(status.textContent,/已创建并校验/);
  }else{
    assert.match(status.textContent,/已创建并校验/);assert.equal(ack.checked,false);assert.equal(button.disabled,true);
    if(scenario==='refresh-failure')assert.match(status.textContent,/列表刷新失败/);
    assert.deepEqual(JSON.parse(calls[1][1].body),{saved_work_acknowledged:true});
  }
}
main(process.argv[2]).catch(error=>{console.error(error);process.exitCode=1;});
