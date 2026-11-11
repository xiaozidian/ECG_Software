"""New19 AF cleanup receipt/readiness contracts; original18 helper stays intact."""
import ast
import asyncio
import copy
import inspect
import json
from pathlib import Path
import subprocess

import pytest
from scripts.verify_windows_af_editor_ui19 import verify_undo_receipt, wait_current_af_review

ROOT=Path(__file__).resolve().parents[1]


def values():
    before=dict(case_id='math',revision=3,analysis_revision=8,analysis_basis='math-source',beat_revision=2)
    submitted={**before,'operation':'undo','request_id':'one'}
    returned={**before,'revision':4,'analysis_revision':9,
              'last_operation':{'request_id':'one','operation':'undo','revision':4}}
    return before,submitted,returned


def test_actual_outbound_revision_and_one_persisted_undo_are_accepted():
    verify_undo_receipt(*values())


@pytest.mark.parametrize('fault',['request-case','reply-case','request-revision','request-global','request-source','request-beat','request-op',
                                  'reply-revision','reply-global','reply-source','reply-beat','reply-id','reply-op','reply-last-revision'])
def test_bad_or_duplicate_undo_acknowledgements_are_rejected(fault):
    before,submitted,returned=values()
    if fault=='request-case':submitted['case_id']='other'
    if fault=='reply-case':returned['case_id']='other'
    if fault=='request-revision':submitted['revision']=2
    if fault=='request-global':submitted['analysis_revision']=7
    if fault=='request-source':submitted['analysis_basis']='other'
    if fault=='request-beat':submitted['beat_revision']=3
    if fault=='request-op':submitted['operation']='save'
    if fault=='reply-revision':returned['revision']=5
    if fault=='reply-global':returned['analysis_revision']=10
    if fault=='reply-source':returned['analysis_basis']='other'
    if fault=='reply-beat':returned['beat_revision']=3
    if fault=='reply-id':returned['last_operation']['request_id']='other'
    if fault=='reply-op':returned['last_operation']['operation']='redo'
    if fault=='reply-last-revision':returned['last_operation']['revision']=3
    with pytest.raises(AssertionError):verify_undo_receipt(before,submitted,returned)


@pytest.mark.parametrize('fault',['valid','wrong-case','wrong-token','wrong-workspace','wrong-case-header','busy','old-UI','old-case','old-wave','wrong-beat',
                                  'coverage-disabled','form-stale','form-disabled','modal-open','no-wave'])
def test_retained_surface_is_not_enough_to_advance_to_next_undo(fault):
    class Page:
        async def wait_for_function(self,js,*,arg):self.js,self.arg=js,arg
    page=Page();asyncio.run(wait_current_af_review(page,dict(case_id='math',analysis_basis='math-source',analysis_revision=9,beat_revision=2),dict(caseId='math',caseToken=1,workspaceEpoch='math-workspace')))
    driver=r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const {js,expected,fault}=JSON.parse(fs.readFileSync(0,'utf8'));
const C=require('./static/js/analysis-consistency.js'),identity={analysis_basis:'math-source',analysis_revision:9};
const state={caseId:'math',caseRequestId:1,workspaceEpoch:'math-workspace',caseData:{case_id:'math',clinical_identity:{...identity},beat_editor_history:{revision:2}},waveform:{...identity,leads:{II:[0,1]}}};
let current={...identity},busy=false,coverage={disabled:false},dialog={open:false},form={dataset:{stale:'false'},querySelectorAll:()=>[{hidden:false,disabled:false}]};
if(fault==='wrong-case')state.caseId='other';
if(fault==='wrong-token')state.caseRequestId=2;
if(fault==='wrong-workspace')state.workspaceEpoch='other';
if(fault==='wrong-case-header')state.caseData.case_id='other';
if(fault==='busy')busy=true;
if(fault==='old-UI')current.analysis_revision--;
if(fault==='old-case')state.caseData.clinical_identity.analysis_revision--;
if(fault==='old-wave')state.waveform.analysis_revision--;
if(fault==='wrong-beat')state.caseData.beat_editor_history.revision++;
if(fault==='coverage-disabled')coverage.disabled=true;
if(fault==='form-stale')form.dataset.stale='true';
if(fault==='form-disabled')form.querySelectorAll=()=>[{hidden:false,disabled:true}];
if(fault==='modal-open')dialog.open=true;
if(fault==='no-wave')state.waveform=null;
const context={state,ECGAnalysisConsistency:C,overviewWorkbench:{isSaving:()=>busy,waveformBasis:()=>current},document:{querySelector:selector=>selector==='#ovDialog'?dialog:selector==='#ovEpisodeForm'?form:coverage}};
const result=vm.runInNewContext('('+js+')',context)(expected);assert.equal(result,fault==='valid');
"""
    subprocess.run(['node','-e',driver],input=json.dumps(dict(js=page.js,expected=page.arg,fault=fault)),
                   cwd=ROOT,text=True,check=True,timeout=15)


def test_original_clinical_viewports_guards_and_three_undo_logic_are_preserved():
    old=ast.parse((ROOT/'scripts/verify_windows_af_editor.py').read_text())
    new=ast.parse((ROOT/'scripts/verify_windows_af_editor_ui19.py').read_text())
    old_fn=next(n for n in old.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='verify_af_editor')
    new_fn=copy.deepcopy(next(n for n in new.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='verify_af_editor'))
    old_cleanup=next(n for n in old_fn.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='cleanup')
    new_fn.body=[copy.deepcopy(old_cleanup) if isinstance(n,ast.AsyncFunctionDef) and n.name=='cleanup' else n
                 for n in new_fn.body if not (isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in ('cleanup_receipts','cleanup_owner') for t in n.targets))]
    returned=new_fn.body[-1].value
    kept=[(k,v) for k,v in zip(returned.keys,returned.values) if not (isinstance(k,ast.Constant) and k.value=='cleanup_receipts')]
    returned.keys,returned.values=map(list,zip(*kept))
    assert ast.dump(new_fn,include_attributes=False)==ast.dump(old_fn,include_attributes=False)
    text=(ROOT/'scripts/verify_windows_af_editor_ui19.py').read_text()
    assert 'for _ in range(successful_commits):' in text
    assert "assert restored == base['document']" in text
    assert "submitted = response.request.post_data_json" in text
    assert 'verify_undo_receipt(before_undo, submitted, returned)' in text
    assert 'await wait_current_af_review(page, returned, cleanup_owner)' in text
    assert 'timeout=' not in inspect.getsource(wait_current_af_review)
