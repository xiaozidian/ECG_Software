"""End-to-end report approval with synthetic signals and scoped physician evidence."""
from copy import deepcopy
from hashlib import sha256
import subprocess

import pytest

from ecg_core.ebi import HEADER_SIZE, RECORD
from ecg_core.workspace_backup import _check_database
from test_analysis_provenance import synthetic_case, synthetic_app


def ok(response):
    assert response.status_code in (200, 201), response.get_json()
    return response.get_json()


def scope(client, base):
    current=ok(client.get(base+'/evidence-candidates'))
    return {k:current[k] for k in ('case_id','analysis_basis','analysis_revision','beat_revision')}


def finish_existing_steps(app, cid):
    store=app.extensions['storage']
    for step in ('edit','stt'):
        store.complete_review(cid, {'step':step,'confirmed':True,'revision':store.get_review(cid)['revision']},'synthetic-doctor')


def pick(client, base, kind='rr'):
    request={**scope(client,base),'kind':kind,'caption':'合成 RR 证据',
             'sample_index':2000,'rr_ms':1000,'settings':{'leads':['II','V1','V5'],'duration_s':7}}
    if kind=='strip':request['settings'].update(range_start_s=7,range_end_s=14)
    candidate=ok(client.post(base+'/evidence-candidates',json=request))['item']
    event=ok(client.get(base+'/report-events',query_string={'ids':f"local-pick:{candidate['id']}"}))['items'][0]
    entry=dict(event_id=event['event_id'],basis_version=event['basis_version'],caption=request['caption'],**event['retained_settings'])
    return event,entry


def save(client,base,entries,status='draft'):
    report=ok(client.get(base+'/report'))
    return client.put(base+'/report',json={'expected_version':report['version'],
        'expected_review_revision':report['review_revision'],'conclusion':'合成数据验收，无临床诊断含义',
        'status':status,'composition':{'included_pages':['summary','event_strips'],
            'page_selection_version':1,'selected_events':entries}})


def preview(client,base,event=None,entry=None,target=None):
    body={**scope(client,base),'entry':entry or {}}
    if target:body['target']=target
    else:body.update(event_id=event['event_id'],basis_version=event['basis_version'])
    data=ok(client.post(base+'/report-evidence/preview',json=body))
    return data,{**body,'confirmed':True,'evidence_key':data['evidence_key'],
        'presentation_key':data['presentation_key'],'report_version':data['report_version']}


@pytest.mark.parametrize('kind',['rr','strip'])
def test_confirmed_manual_evidence_can_be_approved_and_exported(synthetic_app,synthetic_case,kind):
    _,cid,paths=synthetic_case;client=synthetic_app.test_client();base=f'/api/cases/{cid}'
    hashes={k:sha256(p.read_bytes()).hexdigest() for k,p in paths.items()}
    ok(client.get(base+'/report'))
    finish_existing_steps(synthetic_app,cid)
    event,entry=pick(client,base,kind)
    draft=ok(save(client,base,[entry]))
    response=save(client,base,[entry],'reviewed')
    assert response.status_code==400 and '第 1 条人工图条待核对' in response.json['error']
    before=scope(client,base)
    value,body=preview(client,base,event,entry)
    assert value['strip']['leads']==['II','V1','V5']
    confirmation=ok(client.post(base+'/report-evidence/confirm',json=body))
    assert confirmation['beat_revision']==before['beat_revision']
    assert all(confirmation['review']['steps'][k]['status']=='done' for k in ('edit','stt'))
    assert confirmation['report']['conclusion']==draft['conclusion']
    assert confirmation['report']['composition']==draft['composition']
    fresh=ok(client.get(base+'/report-events',query_string={'ids':event['event_id']}))['items'][0]
    assert fresh['evidence_review']['status']=='confirmed'
    assert fresh['diagnosis_status']=='pending' and fresh['evidence_only'] is True
    approved=ok(save(client,base,[entry],'reviewed'));assert approved['status']=='reviewed'
    response=client.get(base+'/report.pdf');assert response.status_code==200,response.get_json()
    assert b'%PDF' in response.data[:8]
    text=subprocess.check_output(['pdftotext','-','-'],input=response.data).decode()
    assert '合成 RR 证据' in text
    assert {k:sha256(p.read_bytes()).hexdigest() for k,p in paths.items()}==hashes
    assert _check_database(synthetic_app.extensions['storage'].path)['tables']['report_evidence_reviews']==1


def test_unused_candidate_and_nonprinting_pick_do_not_block_but_explicit_reference_does(synthetic_app,synthetic_case):
    _,cid,_=synthetic_case;client=synthetic_app.test_client();base=f'/api/cases/{cid}'
    ok(client.get(base+'/report'));finish_existing_steps(synthetic_app,cid)
    _,entry=pick(client,base)
    ok(save(client,base,[]));assert ok(save(client,base,[],'reviewed'))['status']=='reviewed'
    hidden={**entry,'print_enabled':False}
    ok(save(client,base,[hidden]));assert ok(save(client,base,[hidden],'reviewed'))['status']=='reviewed'
    response=client.get(base+'/report.pdf');assert response.status_code==200
    text=subprocess.check_output(['pdftotext','-','-'],input=response.data).decode()
    assert '合成 RR 证据' not in text
    referenced={**hidden,'referenced_in_report':True}
    ok(save(client,base,[referenced]));assert save(client,base,[referenced],'reviewed').status_code==400
    assert len(ok(client.get(base+'/evidence-candidates'))['items'])==1


@pytest.mark.parametrize('change',[{'leads':['II']},{'caption':'修改后的客观测量图注'},{'notes':'新增图条注释'},{'range_start_s':7,'range_end_s':14}])
def test_changed_printed_content_requires_review_and_can_then_be_confirmed(synthetic_app,synthetic_case,change):
    _,cid,_=synthetic_case;client=synthetic_app.test_client();base=f'/api/cases/{cid}'
    ok(client.get(base+'/report'));finish_existing_steps(synthetic_app,cid)
    event,entry=pick(client,base);ok(save(client,base,[entry]));_,body=preview(client,base,event,entry)
    ok(client.post(base+'/report-evidence/confirm',json=body))
    changed={**entry,**change};ok(save(client,base,[changed]))
    assert save(client,base,[changed],'reviewed').status_code==400
    _,body=preview(client,base,event,changed);ok(client.post(base+'/report-evidence/confirm',json=body))
    assert ok(save(client,base,[changed],'reviewed'))['status']=='reviewed'


def test_integral_json_numbers_reuse_the_same_confirmed_evidence(synthetic_app,synthetic_case):
    _,cid,_=synthetic_case;client=synthetic_app.test_client();base=f'/api/cases/{cid}'
    ok(client.get(base+'/report'));finish_existing_steps(synthetic_app,cid)
    event,entry=pick(client,base);entry['duration_s']=7.0
    ok(save(client,base,[entry]));_,body=preview(client,base,event,entry)
    body['entry']['duration_s']=7
    ok(client.post(base+'/report-evidence/confirm',json=body))
    assert ok(save(client,base,[{**entry,'duration_s':7}],'reviewed'))['status']=='reviewed'


def test_preview_and_confirmation_reject_mixed_versions_and_unreadable_wave(synthetic_app,synthetic_case,monkeypatch):
    _,cid,_=synthetic_case;client=synthetic_app.test_client();base=f'/api/cases/{cid}'
    event,entry=pick(client,base);ok(save(client,base,[entry]));_,body=preview(client,base,event,entry)
    for bad in ({'beat_revision':999},{'evidence_key':'forged'},{'presentation_key':'forged'},{'report_version':999}):
        assert client.post(base+'/report-evidence/confirm',json={**body,**bad}).status_code==409
    monkeypatch.setattr('app.read_event_waveform',lambda *args,**kwargs:dict(start_s=0,duration_s=7,leads={}))
    assert client.post(base+'/report-evidence/confirm',json=body).status_code==409
    assert synthetic_app.extensions['storage'].list_report_evidence(cid)==[]


def test_correction_invalidates_old_pick_and_confirmation_without_following_neighbor(synthetic_app,synthetic_case):
    _,cid,_=synthetic_case;client=synthetic_app.test_client();base=f'/api/cases/{cid}'
    ok(client.get(base+'/report'));finish_existing_steps(synthetic_app,cid)
    event,entry=pick(client,base);ok(save(client,base,[entry]));_,body=preview(client,base,event,entry)
    ok(client.post(base+'/report-evidence/confirm',json=body))
    editor=ok(client.get(base+'/beat-editor'))
    response=client.put(base+'/beat-editor',json={'revision':editor['revision'],'operation':'relabel',
        'selection':{'samples':[2000]},'class_code':'V','confirmed':True})
    assert response.status_code==200,response.get_json()
    assert ok(client.get(base+'/report-events',query_string={'ids':event['event_id']}))['items']==[]
    assert client.post(base+'/report-evidence/confirm',json=body).status_code==409
    finish_existing_steps(synthetic_app,cid)
    blocked=save(client,base,[entry],'reviewed');assert blocked.status_code==400 and '失效' in blocked.json['error']
    assert ok(client.get(base+'/report'))['composition']['selected_events'][0]['event_id']==entry['event_id']


def test_longest_can_be_reviewed_without_creating_candidate_or_printing(synthetic_app,synthetic_case):
    _,cid,_=synthetic_case;client=synthetic_app.test_client();base=f'/api/cases/{cid}'
    initial=ok(client.get(base+'/report'));finish_existing_steps(synthetic_app,cid)
    value,body=preview(client,base,target='longest')
    assert value['event']['rr_ms']==1000
    result=ok(client.post(base+'/report-evidence/confirm',json=body))
    assert result['report']['composition']==initial['composition']
    assert ok(client.get(base+'/evidence-candidates'))['items']==[]
    current=ok(client.get(base+'/report-rr-evidence'))['event']
    assert current['evidence_review']['status']=='confirmed'


def test_shorter_pick_cannot_be_confirmed_or_approved_as_longest(synthetic_app,synthetic_case):
    _,cid,paths=synthetic_case
    paths['ebi'].write_bytes(bytes(HEADER_SIZE)+b''.join(RECORD.pack(i*200+(200 if i>=40 else 0),1,1,0,0,0,2000 if i==40 else 1000) for i in range(1,89)))
    client=synthetic_app.test_client();base=f'/api/cases/{cid}'
    event,entry=pick(client,base);entry['caption']='全程最长 RR 1.000 s'
    ok(save(client,base,[entry]));_,body=preview(client,base,event,entry)
    response=client.post(base+'/report-evidence/confirm',json=body)
    assert response.status_code==400 and '不是当前可分析记录的最长' in response.json['error']
    assert ok(client.get(base+'/report-rr-evidence'))['event']['rr_ms']==2000


def test_candidate_save_uses_adjacency_without_building_report_index(synthetic_app,synthetic_case,monkeypatch):
    _,cid,_=synthetic_case;client=synthetic_app.test_client();base=f'/api/cases/{cid}'
    own=scope(client,base);before=ok(client.get(base+'/report'))
    def forbidden(*args,**kwargs):raise AssertionError('Candidate-only save must not rebuild the full report index')
    monkeypatch.setattr('app.build_index',forbidden)
    item=ok(client.post(base+'/evidence-candidates',json={**own,'kind':'rr','sample_index':2000,'rr_ms':1000}))['item']
    assert item['payload']['rr_end_sample']==2000
    assert ok(client.get(base+'/report'))==before


def test_withdrawal_removes_report_pick_atomically_and_restore_stays_unselected(synthetic_app,synthetic_case):
    _,cid,_=synthetic_case;client=synthetic_app.test_client();base=f'/api/cases/{cid}'
    event,entry=pick(client,base);saved=ok(save(client,base,[entry]))
    own=scope(client,base);candidate=ok(client.get(base+'/evidence-candidates'))['items'][0]
    bad=client.patch(base+'/evidence-candidates',json={**own,'id':candidate['id'],'status':'withdrawn','expected_report_version':saved['version']-1})
    assert bad.status_code==409
    assert ok(client.get(base+'/evidence-candidates'))['items'][0]['status']=='active'
    assert ok(client.get(base+'/report'))['composition']['selected_events']==saved['composition']['selected_events']
    result=ok(client.patch(base+'/evidence-candidates',json={**own,'id':candidate['id'],'status':'withdrawn','expected_report_version':saved['version']}))
    assert result['report']['composition']['selected_events']==[]
    assert result['report']['conclusion']==saved['conclusion'] and result['report']['status']=='draft'
    assert result['report']['version']==saved['version']+1
    assert ok(client.get(base+'/report-events',query_string={'ids':event['event_id']}))['items']==[]
    restored=ok(client.patch(base+'/evidence-candidates',json={**own,'id':candidate['id'],'status':'active','expected_report_version':result['report']['version']}))
    assert restored['report']['composition']['selected_events']==[]
    assert ok(client.get(base+'/report-events',query_string={'ids':event['event_id']}))['items']


def test_legacy_withdrawn_selection_is_repaired_without_deleting_other_stale_evidence(synthetic_app,synthetic_case):
    from ecg_core.storage import Storage
    _,cid,_=synthetic_case;client=synthetic_app.test_client();base=f'/api/cases/{cid}'
    event,entry=pick(client,base);other={**entry,'event_id':'unrelated-old-evidence','caption':'保留其他待核对图条'}
    report=ok(save(client,base,[entry,other]));store=synthetic_app.extensions['storage']
    with store.connect() as db:db.execute("UPDATE evidence_candidates SET status='withdrawn' WHERE case_id=?",(cid,))
    repaired=Storage(store.path).get_report(cid,'')
    assert repaired['composition']['selected_events']==[report['composition']['selected_events'][1]]
    assert repaired['conclusion']==report['conclusion']
    assert repaired['version']==report['version']+1
    assert Storage(store.path).get_report(cid,'')['version']==repaired['version']
