'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
require('../static/js/report-evidence-ui.js');
global.ECGReportSections={selectedPages:c=>c.included_pages||[]};
const source=fs.readFileSync('static/js/clinical-ui.js','utf8');
let entries=[],c={included_pages:['event_strips']};
const lookup=new Map([
 ['pending',{event_id:'pending',category:'AF',rhythm_status:'pending'}],
 ['confirmed',{event_id:'confirmed',category:'AF',rhythm_status:'confirmed'}],
 ['flutter',{event_id:'flutter',category:'AF',subtype:'AFL',rhythm_status:'pending'}],
 ['ventricular',{event_id:'ventricular',category:'V',diagnosis_status:'pending'}]
]);
const context=vm.createContext({selected:()=>entries,selectedLookup:lookup,composition:()=>c,ECGReportEvidenceUI:global.ECGReportEvidenceUI});
vm.runInContext(source.slice(source.indexOf('  function pendingRhythmPicks('),source.indexOf('  function renderReportShell(')),context);
const pending=()=>JSON.parse(vm.runInContext('JSON.stringify(pendingRhythmPicks())',context));
assert.deepEqual(pending(),[],'unselected pending rhythm never blocks report approval');
entries=[{event_id:'pending'}];assert.deepEqual(pending(),[0]);
entries=[{event_id:'confirmed'}];assert.deepEqual(pending(),[]);
entries=[{event_id:'flutter'}];assert.deepEqual(pending(),[0]);
entries=[{event_id:'ventricular'}];assert.deepEqual(pending(),[],'other workflow retains its own guards');
entries=[{event_id:'pending',print_enabled:false}];assert.deepEqual(pending(),[]);
c={included_pages:['summary']};entries=[{event_id:'pending'}];assert.deepEqual(pending(),[],'retained nonprinting pick is not an output gate');
entries=[{event_id:'pending',referenced_in_report:true}];assert.deepEqual(pending(),[0]);
entries=[{event_id:'pending',referenced_in_report:true,print_enabled:false}];assert.deepEqual(pending(),[0]);
require('../static/js/report-consistency.js');
const workflow=fs.readFileSync('static/js/clinical-workflow.js','utf8'),approve={disabled:false,title:''};
const state={report:{version:1},reportComposition:c,reportRhythmPending:pending(),reportEvidencePending:[]};
const preflight=vm.createContext({state,ECGReportConsistency:global.ECGReportConsistency,$:key=>key==='#approveReport'?approve:key==='#conclusionEditor'?{value:'Doctor conclusion'}:null,pending:()=>[],writable:()=>true});
vm.runInContext(workflow.slice(workflow.indexOf('  function renderPreflight('),workflow.indexOf('  function decision(')),preflight);
vm.runInContext('renderPreflight()',preflight);assert.equal(approve.disabled,true);assert.match(approve.title,/房颤/);
state.reportRhythmPending=[];vm.runInContext('renderPreflight()',preflight);assert.equal(approve.disabled,false);
console.log('AF output-only approval preflight: 12 checks passed');
