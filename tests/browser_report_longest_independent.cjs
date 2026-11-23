'use strict';

const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

// Run the actual controller entry point. A numeric longest-RR review must not
// inherit the first printed strip merely because Number(null) is zero.
const source=fs.readFileSync('static/js/clinical-ui.js','utf8');
const start=source.indexOf('  async function reviewReportEvidence(');
assert(start>=0);
const end=source.indexOf('\n  }',start)+4;
const event={event_id:'local-pick:mathematical',basis_version:'synthetic-basis',
  category:'rr_candidate',label:'RR 1.000 s'};
const selection={...event,leads:['II'],duration_s:7,range_start_s:7,
  range_end_s:14,caption:'人工选择的短 RR',notes:'保留原注释'};
const original=JSON.stringify(selection);
const opened=[];
const context=vm.createContext({
  A:{categories:[]},reportEvidenceOpening:false,reportData:{analysis_revision:2},active:event,
  state:{caseId:'synthetic',caseRequestId:3,currentPage:'report',
    report:{version:4},reportStale:false,reportEvidenceLoading:false,
    caseData:{clinical_identity:{analysis_revision:2}}},
  clinicalWorkflow:{writable:()=>true},
  ECGReportRange:{assertApplied(){}},
  selected:()=>[selection],selectedLookup:new Map([[event.event_id,event]]),
  composition:()=>({selected_events:[selection]}),
  copy:x=>JSON.parse(JSON.stringify(x)),
  flushReportAutosave:async()=>{},
  ECGReportConsistency:{content:()=>original},qs:()=>({value:'合成验收结论'}),
  ECGReportEvidenceUI:{eligible:()=>true,open:async options=>{
    assert(options.isCurrent());opened.push(options);
  }},api:()=>{throw Error('The component must delegate its read to the evidence dialog');}
});
vm.runInContext(source.slice(source.indexOf('  const reportCategories='),source.indexOf('  const tabs=')),context);
vm.runInContext(source.slice(start,end),context);

(async()=>{
  await context.reviewReportEvidence(null,'longest');
  assert.equal(opened[0].target,'longest');
  assert.equal(opened[0].event,null);
  assert.deepEqual(JSON.parse(JSON.stringify(opened[0].entry)),{});
  assert.equal(opened[0].include,false);
  assert.equal(JSON.stringify(selection),original);
  await context.reviewReportEvidence(0);
  assert.equal(opened[1].event,event);
  assert.deepEqual(JSON.parse(JSON.stringify(opened[1].entry)),selection);
  assert.equal(opened[1].include,false);
  await context.reviewReportEvidence('active');
  assert.deepEqual(JSON.parse(JSON.stringify(opened[2].entry)),selection);
  assert.equal(context.reportEvidenceOpening,false);
  console.log('Numeric longest RR uses its own range; printed and active entries retain theirs.');
})().catch(error=>{console.error(error);process.exitCode=1;});
