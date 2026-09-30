"""Protect physician drafts and exports against concurrent case/report changes."""
from io import BytesIO
import json
import subprocess

import pytest

from ecg_core.review_workflow import ReportConflict
from ecg_core.storage import Storage


def test_first_save_advances_version_and_rejects_second_window(tmp_path):
    store=Storage(tmp_path/'consistency.db')
    original=store.get_report('test','source')
    first=store.save_report('test','first window','draft','tester',expected_version=original['version'])
    assert first['version']==original['version']+1
    with pytest.raises(ReportConflict):
        store.save_report('test','second window','draft','tester',expected_version=original['version'])
    assert store.get_report('test','')['conclusion']=='first window'
    assert len([x for x in store.list_audit() if x['action']=='report.draft'])==1


@pytest.mark.parametrize('status',['draft','returned'])
def test_case_edit_advances_all_report_states(tmp_path,status):
    store=Storage(tmp_path/'consistency.db')
    first=store.save_report('test','unchanged text',status,'tester',{'category_reviews':{'V':'old'}})
    store.set_beat_overrides('test',[dict(sample_index=200,group=1)],'V','tester')
    latest=store.get_report('test','')
    assert latest['version']==first['version']+1
    assert latest['review_revision']==first['review_revision']+1
    assert latest['status']=='draft' and latest['composition']['category_reviews']=={}
    assert latest['conclusion']=='unchanged text'
    with pytest.raises(ReportConflict):
        store.save_report('test','stale','draft','tester',expected_version=first['version'])


@pytest.mark.parametrize('action',['annotation','override','patient','report'])
def test_mutation_and_invalidation_rollback_together(tmp_path,monkeypatch,action):
    store=Storage(tmp_path/'consistency.db')
    old=store.save_report('test','before','draft','tester')
    def fail(*args):raise RuntimeError('simulated audit failure')
    monkeypatch.setattr(store,'_audit',fail)
    with pytest.raises(RuntimeError):
        if action=='annotation':store.create_annotation('test',dict(sample_index=200,label='test'),'tester')
        if action=='override':store.set_beat_overrides('test',[dict(sample_index=200,group=1)],'V','tester')
        if action=='patient':store.save_patient_override('test',{'age':42},'tester')
        if action=='report':store.save_report('test','after','draft','tester')
    assert store.list_annotations('test')==[]
    assert store.list_beat_overrides('test')==[]
    assert store.get_patient_override('test')=={}
    assert store.get_report('test','')==old


def test_api_requires_version_and_blocks_stale_revision(client):
    case=client.get('/api/cases').json['items'][0]['case_id'];base=f'/api/cases/{case}'
    for version in [None,True,0,'1',1.5]:
        assert client.put(base+'/report',json={'expected_version':version,'conclusion':'test'}).status_code==400
    before=client.get(base+'/report').json
    client.patch(base+'/patient',json={'age':42})
    response=client.put(base+'/report',json={'expected_version':before['version'],
        'expected_review_revision':before['review_revision'],'conclusion':'stale'})
    assert response.status_code==409 and response.json['code']=='report_conflict'
    assert client.get(base+'/report').json['conclusion']==before['conclusion']


def test_case_change_during_report_validation_is_rejected(client,monkeypatch):
    import app as server
    case=client.get('/api/cases').json['items'][0]['case_id'];base=f'/api/cases/{case}'
    store=client.application.extensions['storage'];original=server.validate_report
    def racing(*args,**kwargs):
        result=original(*args,**kwargs)
        store.save_patient_override(case,{'age':43},'other-window')
        return result
    monkeypatch.setattr(server,'validate_report',racing)
    response=client.put(base+'/report',json={'expected_version':1,'conclusion':'race'})
    assert response.status_code==409
    assert not store.get_report(case,'')['updated_at']


def test_export_discards_mixed_revision_and_no_success_audit(client,monkeypatch):
    case=client.get('/api/cases').json['items'][0]['case_id'];base=f'/api/cases/{case}'
    store=client.application.extensions['storage']
    def racing_pdf(*args):
        store.save_patient_override(case,{'age':44},'other-window')
        return BytesIO(b'%PDF-stale')
    monkeypatch.setattr('app.build_report_pdf',racing_pdf)
    response=client.get(base+'/report.pdf')
    assert response.status_code==409 and not response.data.startswith(b'%PDF')
    assert not any(x['action']=='report.export_pdf' for x in store.list_audit())
    assert client.get(base+'/report.pdf?expected_version=999').status_code==409
    assert client.get(base+'/report.pdf?expected_review_revision=999').status_code==409


def test_export_success_exposes_provenance(client,monkeypatch):
    case=client.get('/api/cases').json['items'][0]['case_id'];base=f'/api/cases/{case}'
    monkeypatch.setattr('app.build_report_pdf',lambda *args:BytesIO(b'%PDF-stable'))
    report=client.get(base+'/report').json
    response=client.get(base+'/report.pdf')
    assert response.status_code==200
    assert response.headers['X-Report-Version']==str(report['version'])
    assert response.headers['X-Review-Revision']==str(report['review_revision'])


def test_browser_keeps_unsaved_content_and_original_base():
    script="""
require('./static/js/report-consistency.js');const a=ECGReportConsistency;
const state={report:{version:2,review_revision:4,conclusion:'original'},reportDirty:true};
const remote={version:3,review_revision:5,conclusion:'other window'};
if(a.receive(state,remote)!==false||!state.reportStale||state.report.version!==2)throw Error('overwritten dirty base');
state.reportDirty=false;if(!a.receive(state,remote)||state.reportStale)throw Error('reload failed');
state.reportSaving=true;if(a.receive(state,{...remote,version:4})||state.report.version!==3)throw Error('in-flight overwrite');
const before=a.content('submitted',{pages:['summary']});
if(before===a.content('typed during save',{pages:['summary']}))throw Error('lost late typing');
if(a.sameBase({version:3,review_revision:5},{version:3,review_revision:6}))throw Error('ignored changed case');
console.log(JSON.stringify(state));
"""
    result=json.loads(subprocess.check_output(['node','-e',script],text=True))
    assert result['report']['conclusion']=='other window'


def test_browser_approval_uses_one_gate_for_all_renderers():
    script="""
const assert=require('node:assert/strict');require('./static/js/report-consistency.js');
const {canApprove}=ECGReportConsistency, state={report:{version:1}};
assert.equal(canApprove(state,'doctor conclusion',true,true),true);
for(const key of ['reportDirty','reportStale','reportSaving','reportEvidenceLoading','reportEvidenceError'])
  assert.equal(canApprove({...state,[key]:true},'conclusion',true,true),false);
assert.equal(canApprove({...state,reportComposition:{diagnosis_blocks:[{needs_review:true}]}},'conclusion',true,true),false);
for(const text of ['', '  \\n ', null, undefined])
  assert.equal(canApprove(state,text,true,true),false);
assert.equal(canApprove(state,'conclusion',false,true),false);
assert.equal(canApprove(state,'conclusion',true,false),false);
assert.equal(canApprove({},'conclusion',true,true),false);
const fs=require('node:fs');
for(const path of ['static/js/clinical-ui.js','static/js/clinical-workflow.js'])
  assert.match(fs.readFileSync(path,'utf8'),/ECGReportConsistency.canApprove/);
"""
    subprocess.run(['node','-e',script],check=True,timeout=15)
