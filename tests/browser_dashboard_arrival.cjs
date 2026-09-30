// Actual shipped entry/render functions with deterministic network completion order.
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync('static/js/app.js', 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
function gate() { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return {promise, resolve, reject}; }
const caseRow = (id = 'A', extra = {}) => ({case_id:id, active:true, metadata:{name:'合成病例',patient_id:id}, summary:{avg_hr:70}, technical:{}, ...extra});
const payload = (rows = [caseRow()], issues = []) => ({cases:rows, source_issues:issues, totals:{cases:rows.length,recording_hours:1,beats:89,pending_reports:rows.length}});
function harness() {
  const elements = new Map(), requests = [], errors = [], opened = [], timers = new Map(); let timerId = 0;
  const $ = key => { if (!elements.has(key)) elements.set(key, {value:'',textContent:'',innerHTML:'',hidden:true,disabled:false,attrs:{},
    setAttribute(k,v){this.attrs[k]=v;},focus(){ctx.focus=key;},classList:{add(){}}}); return elements.get(key); };
  $('#worklistFilter').value = 'all';
  const state = {search:'',cases:[],dashboard:null,dashboardStatus:'loading',dashboardRequestId:0,dashboardError:'',workspaceReady:false,workspaceEpoch:'',includePhi:false,allowPhi:true};
  const noop = () => {};
  const ctx = vm.createContext({state,$,AbortController,navigator:{platform:''},
    setTimeout(fn,ms){const id=++timerId;timers.set(id,{fn,ms});return id;},clearTimeout:id=>timers.delete(id),
    handleError:e=>errors.push(e),selectCase:async(id,destination)=>{opened.push({id,destination});state.caseLoading={};},
    sourceHint:String,applyPlatformIdentity:noop,bindEvents:noop,updateWaveformModeUI:noop,setLeadPickerSelection:noop,
    setSttLeadPickerSelection:noop,setEditMode:noop,renderCaseWorkflow:noop,updateZoomControls:noop,loadSettings:async()=>{},
    api:(url,options={})=>{const r={url,...gate(),signal:options.signal};requests.push(r);return r.promise;}});
  vm.runInContext(source.slice(source.indexOf('function escapeHtml('), source.indexOf('async function api(')),ctx);
  vm.runInContext(source.slice(source.indexOf('function fmtNumber('), source.indexOf('function formatElapsed(')),ctx);
  vm.runInContext(source.slice(source.indexOf('function withPhi('), source.indexOf('function loadCaseWorkflow(')),ctx);
  vm.runInContext(source.slice(source.indexOf('async function init()'), source.indexOf('document.addEventListener("DOMContentLoaded",init)')),ctx);
  async function ready(rows=[caseRow()],issues=[]) {
    const pending=ctx.loadDashboard();
    if (!state.workspaceReady) { requests.at(-1).resolve({workspace_epoch:'first',data_root_found:true});await tick(); }
    requests.at(-1).resolve(payload(rows,issues));await pending;
  }
  return {ctx,state,$,requests,errors,opened,timers,ready};
}
async function run(which) {
  const h=harness(),{ctx,state,$,requests,opened,errors,timers}=h;
  if(which==='bootstrap') {
    const html=fs.readFileSync('templates/index.html','utf8');
    assert.match(html,/<button[^>]*id="openFirstCase"[^>]*disabled/);
    const pending=ctx.loadDashboard();assert.equal(requests[0].url,'/api/health');
    assert.equal($('#openFirstCase').disabled,true);assert.equal($('#worklistBody').attrs['aria-busy'],'true');
    assert.match($('#worklistBody').innerHTML,/正在读取/);assert.equal($('#metricCases').textContent,'—');
    await ctx.openWorklistCase('A');assert.equal(opened.length,0);
    requests[0].resolve({workspace_epoch:'first',data_root_found:true});await tick();
    assert.equal(state.workspaceEpoch,'first');assert.equal($('#openFirstCase').disabled,true);
    requests[1].resolve(payload());await pending;
    assert.equal($('#openFirstCase').disabled,false);assert.equal($('#worklistBody').attrs['aria-busy'],'false');
    assert.equal(timers.size,0);
  } else if(which==='health-retry') {
    const failed=ctx.loadDashboard();requests[0].reject(Error('服务暂不可用'));await assert.rejects(failed,/服务/);
    assert.equal(state.workspaceReady,false);assert.equal($('#dashboardLoadError').hidden,false);
    assert.equal($('#retryDashboard').disabled,false);assert.equal($('#patientCount').textContent,'—');
    const retry=ctx.retryDashboard();assert.equal(requests[1].url,'/api/health');
    requests[1].resolve({workspace_epoch:'restored',data_root_found:true});await tick();requests[2].resolve(payload());await retry;
    assert.equal(state.workspaceEpoch,'restored');assert.equal(ctx.focus,'#caseIndexStatus');assert.equal($('#dashboardLoadError').hidden,true);
  } else if(which==='scan-retry-epoch') {
    await h.ready();const failed=ctx.loadDashboard();requests.at(-1).reject(Error('index unavailable'));await assert.rejects(failed);
    assert.equal(state.cases.length,0);assert.doesNotMatch($('#worklistBody').innerHTML,/data-open-case/);
    assert.equal($('#qualityPercent').textContent,'—');assert.equal($('#patientCount').textContent,'—');
    await h.ready();assert.equal(requests.filter(r=>r.url==='/api/health').length,1);
    assert.equal(state.workspaceEpoch,'first');assert.equal($('#openFirstCase').disabled,false);
  } else if(which==='empty-filter'||which==='filtered-open'||which==='filter-during-load') {
    if(which==='filter-during-load') state.workspaceReady=true;
    const pending=which==='filter-during-load'?ctx.loadDashboard():null;
    state.search='B';$('#globalSearch').value='B';
    const rows=[caseRow('A'),caseRow('B',{summary:{avg_hr:52},review_workflow:{next_step:'report'}})];
    if(pending){ctx.renderWorklist();assert.equal($('#openFirstCase').disabled,true);requests.at(-1).resolve(payload(rows));await pending;}
    else await h.ready(rows);
    assert.match($('#worklistStatus').textContent,/1 \/ 2/);await ctx.openWorklistCase('A');assert.equal(opened.length,0);
    if(which==='empty-filter') {
      state.search='not-a-case';ctx.renderWorklist();assert.equal($('#openFirstCase').disabled,true);
      assert.equal($('#resetWorklistFilters').hidden,false);ctx.resetWorklistFilters();
      assert.equal($('#globalSearch').value,'');assert.equal($('#worklistFilter').value,'all');
      assert.equal($('#openFirstCase').disabled,false);assert.equal(ctx.focus,'#worklistStatus');
    } else {await ctx.openWorklistCase('B');assert.deepEqual(opened,[{id:'B',destination:'report'}]);}
  } else if(which==='clinical-filters') {
    await h.ready([caseRow('A'),caseRow('B',{summary:{avg_hr:52,ventricular_beats:2}}),caseRow('C',{summary:{avg_hr:null}})]);
    $('#worklistFilter').value='abnormal';ctx.renderWorklist();assert.match($('#worklistStatus').textContent,/1 \/ 3/);
    $('#worklistFilter').value='brady';ctx.renderWorklist();assert.equal(ctx.filteredCases().length,1);assert.equal(ctx.filteredCases()[0].case_id,'B');
    ctx.resetWorklistFilters();assert.equal(ctx.filteredCases().length,3);
  } else if(which==='empty-index') {
    await h.ready([]);assert.equal($('#openFirstCase').disabled,true);assert.match($('#worklistStatus').textContent,/数据源/);
    assert.equal($('#metricCases').textContent,'0');assert.equal($('#qualityPercent').textContent,'—');
  } else if(which==='missing-root') {
    const pending=ctx.loadDashboard();requests[0].resolve({data_root_found:false});await tick();requests[1].resolve(payload([]));await pending;
    assert.equal($('#dataSetupPanel').hidden,false);assert.equal($('#openFirstCase').disabled,true);
  } else if(which==='late-health') {
    const first=ctx.loadDashboard(),second=ctx.loadDashboard();assert.equal(requests[0].signal.aborted,true);
    requests[1].resolve({workspace_epoch:'new',data_root_found:true});await tick();requests[2].resolve(payload([caseRow('B')]));await second;
    requests[0].resolve({workspace_epoch:'old',data_root_found:false});assert.equal(await first,false);
    assert.equal(requests.length,3);assert.equal(state.workspaceEpoch,'new');assert.equal(state.cases[0].case_id,'B');
  } else if(which==='late-success'||which==='late-error') {
    state.workspaceReady=true;state.includePhi=true;const first=ctx.loadDashboard();
    state.includePhi=false;const second=ctx.loadDashboard();assert.match(requests[0].url,/include_phi=1/);assert.match(requests[1].url,/include_phi=0/);
    requests[1].resolve(payload([caseRow('B')]));await second;
    if(which==='late-success')requests[0].resolve(payload([caseRow('sensitive-old')]));else requests[0].reject(Error('obsolete error'));
    assert.equal(await first,false);assert.equal(state.cases[0].case_id,'B');assert.equal($('#dashboardLoadError').hidden,true);
    assert.doesNotMatch($('#worklistBody').innerHTML,/sensitive-old/);assert.equal(timers.size,0);
  } else if(which==='timeout') {
    const pending=ctx.loadDashboard();[...timers.values()].find(t=>t.ms===60000).fn();
    assert.equal(requests[0].signal.aborted,true);requests[0].reject(Error('abort'));await assert.rejects(pending);
    assert.match($('#dashboardLoadErrorText').textContent,/超时/);assert.equal($('#retryDashboard').disabled,false);assert.equal(timers.size,0);
  } else if(which==='invalid-response') {
    state.workspaceReady=true;const pending=ctx.loadDashboard();requests[0].resolve(null);await assert.rejects(pending,/响应不完整/);
    assert.equal(state.dashboardStatus,'error');assert.equal($('#openFirstCase').disabled,true);
  } else if(which==='settings-failure'||which==='settings-slow') {
    const settings=gate();ctx.loadSettings=()=>settings.promise;const pending=ctx.init();
    assert.equal($('#loading').attrs['aria-hidden'],'true');
    if(which==='settings-failure')settings.reject(Error('settings unavailable'));
    requests[0].resolve({data_root_found:true});await tick();requests[1].resolve(payload());await pending;
    assert.equal($('#openFirstCase').disabled,false);assert.equal(state.dashboardStatus,'ready');assert.equal(errors.length,which==='settings-failure'?1:0);
    settings.resolve();
  } else if(which==='duplicate-open') {
    await h.ready();await ctx.openWorklistCase('A');await ctx.openWorklistCase('A');assert.equal(opened.length,1);
  } else if(which==='failure-no-focus'||which==='network-copy') {
    const pending=ctx.retryDashboard();requests[0].reject(Error(which==='network-copy'?'Failed to fetch':'failed'));await pending;
    assert.equal(ctx.focus,undefined);assert.equal(errors.length,1);assert.equal($('#dashboardLoadError').hidden,false);
    if(which==='network-copy'){assert.match($('#dashboardLoadErrorText').textContent,/无法连接本地服务/);assert.match(errors[0].message,/无法连接本地服务/);}
  } else throw Error('Unknown test: '+which);
}
module.exports={harness,caseRow,payload};
if(require.main===module)run(process.argv[2]).catch(error=>{console.error(error);process.exitCode=1;});
