"""Shared UI selection keeps exact RR-bin provenance; mathematical data only."""
import subprocess


def test_histogram_keyboard_selection_keeps_bounds_and_tail_without_retiming():
    script = r"""
const fs=require('fs'), vm=require('vm'), assert=require('node:assert/strict');
const source=fs.readFileSync('static/js/overview-workbench.js','utf8');
const bins=[{start:0,end:25,count:0,samples:[]},{start:25,end:50,count:2,samples:[100,200]},{start:50,end:75,count:1,samples:[300]}];
const before=JSON.stringify(bins), calls=[];
const context={ui:{bin:null,ratio:false,hist:{bins}},E:{clamp:(n,a,b)=>Math.max(a,Math.min(b,n))},selectSamples:(samples,details)=>calls.push({samples,details}),drawHistogram(){}};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('  function selectHistogramBin('),source.indexOf('  function drawHistogram(')),context);
context.selectHistogramBin(1);
assert.deepEqual(calls[0].samples,[100,200]);
assert.equal(calls[0].details.origin,'overview-histogram');
assert.equal(calls[0].details.sourcePopulation.start,25);
assert.equal(calls[0].details.sourcePopulation.end,50);
assert.equal(calls[0].details.sourcePopulation.fullCount,2);
context.selectHistogramBin(99);assert.equal(calls[1].details.sourcePopulation.end,null);
context.ui.ratio=true;context.selectHistogramBin(1);assert.equal(calls[2].details.sourcePopulation.kind,'rr-ratio-bin');
const selected=context.ui.bin,n=calls.length;
assert.equal(context.selectHistogramBin(0),false);assert.equal(context.ui.bin,selected);assert.equal(calls.length,n);
assert.equal(context.selectHistogramBin(NaN),false);assert.equal(calls.length,n);
context.ui.bin=null;context.navigateHistogram(-1);assert.equal(context.ui.bin,2);
context.navigateHistogram(-1);assert.equal(context.ui.bin,1);
assert.equal(context.navigateHistogram(-1),false);assert.equal(context.ui.bin,1);
context.navigateHistogram(1);assert.equal(context.ui.bin,2);
assert.equal(JSON.stringify(bins),before);
"""
    subprocess.run(['node', '-e', script], check=True, timeout=10)


def test_save_in_progress_disables_export_and_restores_actions():
    script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('static/js/clinical-ui.js','utf8');
const node=()=>({disabled:false,textContent:'',attrs:{},setAttribute(k,v){this.attrs[k]=v;}});
const nodes={'#saveReport':node(),'#downloadReport':node(),'#cancelReportExport':node()},state={reportSaving:true};
let writable=true;
const ctx={state,qs:s=>nodes[s],clinicalWorkflow:{writable:()=>writable}};vm.createContext(ctx);
vm.runInContext(source.slice(source.indexOf('  function renderExportState(){'),source.indexOf('  function cancelReportExport(')),ctx);
ctx.renderExportState();assert(nodes['#saveReport'].disabled);assert(nodes['#downloadReport'].disabled);assert.equal(nodes['#saveReport'].attrs['aria-busy'],'true');
state.reportSaving=false;ctx.renderExportState();assert.equal(nodes['#saveReport'].disabled,false);assert.equal(nodes['#downloadReport'].disabled,false);
state.reportExportJob={};ctx.renderExportState();assert(nodes['#downloadReport'].disabled);assert.equal(nodes['#cancelReportExport'].hidden,false);
state.reportExportJob=null;state.privacySaving=true;ctx.renderExportState();assert(nodes['#downloadReport'].disabled);
writable=false;ctx.renderExportState();assert(nodes['#saveReport'].disabled);
writable=true;state.reportStale=true;ctx.renderExportState();assert(nodes['#saveReport'].disabled);
assert(source.slice(source.indexOf('  function renderReportShell(){'),source.indexOf('  async function reloadReport(')).includes('renderExportState();'));
"""
    subprocess.run(['node','-e',script],check=True,timeout=10)
