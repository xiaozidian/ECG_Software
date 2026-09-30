"""Report evidence must follow doctor edits, not stale browser/server caches."""
import subprocess
from hashlib import sha256
from copy import deepcopy
import pytest
from ecg_core.storage import Storage
from test_analysis_provenance import synthetic_case, synthetic_app


@pytest.mark.parametrize('scenario', ['removed', 'mixed', 'mixed_source', 'mixed_revision', 'failure', 'loader', 'strip_cache','remove'])
def test_browser_discards_stale_evidence_but_keeps_curation(scenario):
    subprocess.run(['node', 'tests/browser_report_freshness.cjs', scenario], check=True, timeout=15)


@pytest.mark.parametrize('action', ['beat_override.editor', 'annotation.rhythm_review', 'analysis.basis_changed', 'patient.update'])
def test_manual_diagnostic_acknowledgement_expires_after_basis_change(tmp_path, action):
    store=Storage(tmp_path/'ack.db')
    composition={'diagnosis_blocks':[{'key':'V:single','text':'医生手写结论','manual':True,'needs_review':False,'acknowledged':True}]}
    store.save_report('synthetic','保留正文','draft','tester',composition)
    store.audit('tester',action,'synthetic')
    saved=store.get_report('synthetic','')
    block=saved['composition']['diagnosis_blocks'][0]
    assert saved['conclusion']=='保留正文' and block['text']=='医生手写结论'
    assert block['needs_review'] is True and block['acknowledged'] is False


def test_report_event_queries_expose_source_identity(synthetic_app, synthetic_case):
    client=synthetic_app.test_client();_,cid,paths=synthetic_case;base=f'/api/cases/{cid}'
    before=client.get(base+'/report-events').json
    assert before.get('analysis_basis')==client.get(base+'/report').json['current_analysis_basis']['digest']
    data=paths['data'].read_bytes();paths['data'].write_bytes(b'\1'+data[1:])
    after=client.get(base+'/report-events').json
    assert after['data_version']==before['data_version'] # Same beats, different raw waveform.
    assert after['analysis_basis']!=before['analysis_basis']
    assert client.get(base+'/template-occurrences').json['analysis_basis']==after['analysis_basis']


@pytest.mark.parametrize('change', ['raw', 'edit'])
def test_waveforms_reject_obsolete_index_identity(synthetic_app, synthetic_case, change):
    client=synthetic_app.test_client();_,cid,paths=synthetic_case;base=f'/api/cases/{cid}'
    index=client.get(base+'/report-events').json
    event=index['items'][0]
    identity={k:index[k] for k in ('analysis_basis','analysis_revision')}
    batch=dict(ranges=[dict(start=0,end=7)],**identity)
    params=dict(event_id=event['event_id'],basis_version=event['basis_version'],**identity)
    assert client.post(base+'/event-waveforms',json=batch).status_code==200
    assert client.get(base+'/report-strip',query_string=params).status_code==200
    if change=='raw':
        raw=paths['data'].read_bytes();paths['data'].write_bytes(b'\1'+raw[1:])
    else:
        synthetic_app.extensions['storage'].audit('tester','beat_override.editor',cid)
    for response in [client.post(base+'/event-waveforms',json=batch),client.get(base+'/report-strip',query_string=params)]:
        assert response.status_code==409 and '依据已变化' in response.json['error']
    current=client.get(base+'/report-events').json
    batch.update({k:current[k] for k in identity})
    assert client.post(base+'/event-waveforms',json=batch).status_code==200


@pytest.mark.parametrize('endpoint', ['report-events','template-occurrences','report-strip','event-waveforms'])
def test_read_rejects_change_while_building_evidence(synthetic_app, synthetic_case, monkeypatch, endpoint):
    import app as server
    client=synthetic_app.test_client();_,cid,_=synthetic_case;base=f'/api/cases/{cid}'
    index=client.get(base+'/report-events').json;event=index['items'][0]
    name='query_index' if endpoint in ('report-events','template-occurrences') else 'read_event_waveform'
    original=getattr(server,name)
    def racing(*args,**kwargs):
        result=original(*args,**kwargs)
        synthetic_app.extensions['storage'].audit('tester','beat_override.editor',cid)
        return result
    monkeypatch.setattr(server,name,racing)
    if endpoint=='event-waveforms':response=client.post(base+'/'+endpoint,json={'ranges':[dict(start=0,end=7)]})
    else:response=client.get(base+'/'+endpoint,query_string=dict(event_id=event['event_id'],basis_version=event['basis_version']))
    assert response.status_code==409 and '依据已变化' in response.json['error']


def test_doctor_edit_invalidates_selected_report_undo_does_not_reapprove(synthetic_app, synthetic_case):
    client=synthetic_app.test_client();_,cid,paths=synthetic_case;base=f'/api/cases/{cid}'
    store=synthetic_app.extensions['storage'];original={k:sha256(v.read_bytes()).hexdigest() for k,v in paths.items()}
    def edit(operation,revision,**extra):
        response=client.put(base+'/beat-editor',json=dict(operation=operation,revision=revision,confirmed=True,**extra))
        assert response.status_code==200,response.json
        return response.json
    def ready():
        for step in ('edit','stt'):
            store.complete_review(cid,dict(step=step,confirmed=True,revision=store.get_review(cid)['revision']),'test-doctor')
    def save(report,status):
        return client.put(base+'/report',json=dict(status=status,expected_version=report['version'],expected_review_revision=report['review_revision'],conclusion=report['conclusion'],composition=report['composition']))
    edit('relabel',0,selection={'samples':[6000]},class_code='V');ready()
    events=client.get(base+'/report-events?category=V').json;event=events['items'][0]
    report=client.get(base+'/report').json
    report['conclusion']='合成病例：手工复核正文，不是患者诊断'
    report['composition'].update(selected_events=[dict(event_id=event['event_id'],basis_version=event['basis_version'],caption='合成室早')],category_reviews=events['basis_versions'],diagnosis_blocks=[dict(key='V:single',text='合成人工说明',manual=True,acknowledged=True,needs_review=False)])
    response=save(report,'draft');assert response.status_code==200,response.json
    response=save(response.json,'reviewed');assert response.status_code==200,response.json
    approved=response.json
    assert client.get(base+'/report-statistics').json['summary']['V']['total']==1
    edit('relabel',1,selection={'samples':[6000]},class_code='N')
    assert client.get(base+'/report-statistics').json['summary']['V']['total']==0
    assert client.get(base+'/report-events?category=V').json['total']==0
    invalid=client.get(base+'/report').json
    assert invalid['status']=='draft' and invalid['conclusion']==approved['conclusion']
    assert invalid['composition']['selected_events']==approved['composition']['selected_events']
    assert invalid['composition']['diagnosis_blocks'][0]['needs_review'] is True
    assert save(approved,'reviewed').status_code==409
    assert client.get(base+'/report.pdf',query_string={'expected_version':approved['version']}).status_code==409
    ready();invalid=client.get(base+'/report').json
    assert save(invalid,'reviewed').status_code==400 # Removed pick must be replaced.
    assert client.get(base+'/report.pdf').status_code in (400,409) # No stale strip even in draft.
    edit('undo',2)
    assert client.get(base+'/report-statistics').json['summary']['V']['total']==1
    restored=client.get(base+'/report').json
    assert restored['status']=='draft' and restored['composition']['diagnosis_blocks'][0]['needs_review']
    ready();restored=client.get(base+'/report').json
    restored['composition']['category_reviews']=client.get(base+'/report-events').json['basis_versions']
    draft=save(restored,'draft');assert draft.status_code==200,draft.json
    denied=save(draft.json,'reviewed');assert denied.status_code==400 and '人工诊断文字' in denied.json['error']
    reconciled=deepcopy(draft.json);reconciled['composition']['diagnosis_blocks'][0].update(needs_review=False,acknowledged=True)
    saved=save(reconciled,'draft');assert saved.status_code==200,saved.json
    assert save(saved.json,'reviewed').status_code==200
    assert {k:sha256(v.read_bytes()).hexdigest() for k,v in paths.items()}==original


def test_demo_invalidation_preserves_but_unconfirms_manual_text():
    script=r"""
const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('demo/static/js/demo-api.js','utf8');
const block={text:'doctor text',manual:true,needs_review:false,acknowledged:true};
const saved={reports:{A:{status:'reviewed',version:2,composition:{diagnosis_blocks:[block],category_reviews:{V:'old'}}}},reviews:{A:{revision:1,steps:{edit:{status:'done'},stt:{status:'done'}},events:{}}}};
vm.runInNewContext(source.slice(source.indexOf('  function invalidateWorkflow('),source.indexOf('  function confirmWorkflow('))+`invalidateWorkflow('beat_override.editor')`,{saved,caseId:'A',reviewSteps:['edit','stt'],workflow(){},now:()=>''});
assert.equal(block.text,'doctor text');assert.equal(block.needs_review,true);assert.equal(block.acknowledged,false);
assert.equal(saved.reports.A.status,'draft');assert.equal(saved.reviews.A.steps.edit.status,'stale');
"""
    subprocess.run(['node','-e',script],check=True,timeout=15)
