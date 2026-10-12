const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const code=fs.readFileSync('static/js/app.js','utf8'),snippet=code.slice(code.indexOf('function editTwelveScope('),code.indexOf('async function openEditTwelveLead('))+code.slice(code.indexOf('async function loadEditWaveform('),code.indexOf('function setEditStart('));
const gate=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
async function run(changeCase){
 const pending=[],renders=[],nodes=new Map(),state={caseId:'synthetic-A',caseRequestId:1,currentPage:'edit',caseData:{technical:{duration_seconds_raw:1800}},editRequestId:0,editStart:0,editDuration:20,editLead:'II',editSelectedClass:'source-N',editTemplates:[]};
 const context=vm.createContext({state,URLSearchParams,DEFAULT_PREVIEW_LEADS:['II','V1','V5'],EDIT_SOURCE_CLASSES:[{key:'source-N'}],$:s=>{if(!nodes.has(s))nodes.set(s,{textContent:''});return nodes.get(s)},clearWaveformSurface:()=>state.editWaveform=null,api:(url)=>{const g=gate();pending.push({url,...g});return g.promise;},renderEditClasses(){},renderEditOverview(){},renderEditScatter(){},renderEditWaveform:()=>renders.push(state.editWaveform),renderEditLibrary(){},loadEditTemplateStrips:async()=>{}});
 vm.runInContext(snippet,context);
 const init=context.loadEdit();assert.equal(pending.length,5);
 if(changeCase){state.caseId='synthetic-B';state.caseRequestId++;}
 state.editStart=400;state.editLead='V5';const latest=context.loadEditWaveform(),wave={start_s:400,duration_s:20,leads:{V5:[4,5,6]}};
 pending[5].resolve(wave);await latest;
 const values=[{points:[1]},{histogram:[]},{start_s:0,leads:{II:[1,2,3]}},{items:[{id:7,name:'existing synthetic template',sample_indices:[200,400]}]},{items:[]}];
 pending.slice(0,5).forEach((g,i)=>g.resolve(values[i]));await init;
 assert.strictEqual(state.editWaveform,wave,'old initial wave replaced latest lead/time');assert.equal(state.editStart,400);assert.equal(state.editLead,'V5');
 if(changeCase){assert.equal(state.editTemplates.length,0,'old case templates crossed the case boundary');assert.equal(state.editScatterData,undefined);}else{assert.equal(state.editTemplates.length,1,'fast tab/lead read discarded existing templates');assert.equal(state.editTemplates[0].id,7);assert.deepEqual(state.editScatterData,{points:[1]});}
}
Promise.all([run(false),run(true)]).then(()=>console.log('Initial workspace keeps current-case templates while latest wave wins; old-case workspace results are discarded')).catch(e=>{console.error(e);process.exitCode=1});
