"""Trusted performance receipts preserve authored state, never authorize JSON."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from ecg_core.performance_compatibility import trusted_certificate_shape, AUDIT_ACTION
from ecg_core.review_workflow import ReportConflict
from test_performance_compatibility import continuity, evidence
from test_performance_continuity_transaction import prepare_known_parent, rows
from test_analysis_provenance import synthetic_app, synthetic_case
from test_screening_compatibility import source


@pytest.fixture
def proof(continuity):
    c=continuity;service=c.service();certificate=c.resolve(service)
    assert trusted_certificate_shape(certificate)
    def matches(value=None):
        return service._cached_performance_snapshot_matches(value or certificate,c.case,c.previous,
            c.current,c.e.feed,[c.e.annotation],c.report,c.e.scope['analysis_revision'],c.e.scope['beat_revision'])
    return SimpleNamespace(c=c,service=service,certificate=certificate,matches=matches)


def test_complete_performance_proof_matches_only_its_live_snapshot(proof):
    assert proof.matches()
    assert proof.certificate['retained_stt_records']==[7]
    assert proof.certificate['screening_algorithm_version']=='stt-screening-0.5.0-morphology-qualified'
    assert 'screening_transition' not in proof.certificate


@pytest.mark.parametrize('field',[
    'schema','cache_schema','continuity_kind','case_id','policy_digest','reference_basis',
    'execution_basis','execution_engine_id','source_inputs_digest','beat_revision','beat_basis_version',
    'edited_feed_digest','editor_document_digest','authored_annotations_digest','review_revision',
    'report_version','report_composition_digest','screening_algorithm_version','report_row_present',
])
def test_each_cache_identity_or_snapshot_difference_misses(proof,field):
    changed=deepcopy(proof.certificate);changed[field]='not-the-verified-value'
    assert not proof.matches(changed)


@pytest.mark.parametrize('field',[
    'cache_schema','continuity_kind','case_id','beat_basis_version','edited_feed_digest',
    'report_state_digest','report_row_present','screening_algorithm_version','stt_proofs',
])
def test_old_or_incomplete_certificate_is_never_trusted(proof,field):
    changed=deepcopy(proof.certificate);changed.pop(field)
    assert not trusted_certificate_shape(changed) and not proof.matches(changed)


@pytest.mark.parametrize('change',['beat','marker','records','settings','duration','annotation','review_revision'])
def test_changed_live_inputs_or_authored_state_miss(proof,change):
    c=proof.c
    if change=='beat':c.e.feed.beats[5]['class_code']='V'
    elif change=='marker':c.e.feed.markers.append(dict(id='marker:1',sample_index=205,class_code='X'))
    elif change=='records':c.e.feed.records[5]['rr_ms']=1001
    elif change=='settings':c.e.feed.document['settings']['nn_min_ms']+=1
    elif change=='duration':c.e.feed.duration+=1
    elif change=='annotation':c.e.annotation['note']='changed physician prose'
    else:c.e.scope['analysis_revision']+=1
    assert not proof.matches()


@pytest.mark.parametrize('field,value',[
    ('conclusion','same-version text'),('reviewed_by','different signer'),('status','draft'),
    ('composition',{'selected_events':[]}),('analysis_provenance',{}),('updated_at','different-time'),
])
def test_same_version_report_identity_change_is_409(proof,field,value):
    proof.c.report[field]=value
    with pytest.raises(ReportConflict,match='同一版本'):proof.matches()


def test_real_report_version_advance_forces_full_verification(proof):
    proof.c.report.update(version=10,status='draft')
    assert not proof.matches()


@pytest.mark.parametrize('change',['source','epoch','dependencies','source_contract','unknown_parent','newengine','basis'])
def test_build_source_epoch_or_engine_change_cannot_consult_cache(proof,change):
    c=proof.c;service=proof.service
    if change=='source':c.current['inputs']['data']['sha256']='0'*64
    elif change=='epoch':c.current['recovery_epoch']='restored-workspace'
    elif change=='dependencies':c.current['engine']['dependencies']['mathematical-runtime']='2'
    elif change=='source_contract':c.current['engine']['sample_rate_hz']=250
    elif change=='unknown_parent':service.policy['parent_engine_ids']=[]
    elif change=='newengine':service.runtime.engine_id='0'*64
    else:c.current['digest']='0'*64
    service.storage=SimpleNamespace(get_compatible_implementation=lambda *a:pytest.fail('must reject before cache'))
    assert c.resolve(service) is None


def test_policy_change_is_not_an_alias_for_previous_proof(proof,monkeypatch):
    c=proof.c;service=proof.service;service.policy_digest='0'*64
    service.storage=SimpleNamespace(get_compatible_implementation=lambda *a:proof.certificate)
    from ecg_core import stt_compatibility
    old=stt_compatibility.evaluate_record;calls=[]
    def spy(*a,**kw):calls.append(1);return old(*a,**kw)
    monkeypatch.setattr(stt_compatibility,'evaluate_record',spy)
    result=c.resolve(service)
    assert result and result['policy_digest']=='0'*64 and len(calls)==1
    assert service.diagnostics()['verified_certificate_reuses']==0


@pytest.fixture
def cached_app(synthetic_app,synthetic_case):
    app=synthetic_app;cid=synthetic_case[1];previous,old=prepare_known_parent(app,cid)
    client=app.test_client();response=client.get('/api/cases/'+cid+'/report')
    assert response.status_code==200,response.json
    store=app.extensions['storage'];runtime=app.extensions['analysis_runtime']
    case=app.extensions['case_repository'].get_case(cid);current=runtime.direct_basis(case)
    certificate=store.get_compatible_implementation(cid,runtime.engine_id,current['digest'])
    assert certificate and certificate['reference_basis']==previous
    return SimpleNamespace(app=app,cid=cid,client=client,store=store,runtime=runtime,case=case,
        current=current,previous=previous,old=old,certificate=certificate,
        base='/api/cases/'+cid,service=app.extensions['performance_compatibility'])


def test_restart_reuses_audited_proof_without_evaluating_records_or_running_analyzers(cached_app,monkeypatch):
    from ecg_core import stt,stt_screening_legacy,stt_compatibility
    e=cached_app;before=rows(e.store);audit=e.store.list_audit();e.runtime._basis_bindings.clear()
    for module,name in ((stt,'analyze_stt'),(stt_screening_legacy,'analyze_stt'),
                        (stt_compatibility,'analyze_stt_range'),(stt_compatibility,'evaluate_record')):
        monkeypatch.setattr(module,name,lambda *a,**kw:pytest.fail('cache must not recompute'))
    response=e.client.get(e.base+'/report')
    assert response.status_code==200,response.json
    assert response.json['status']=='reviewed' and response.json['current_analysis_basis']==e.previous
    assert rows(e.store)==before and e.store.list_audit()==audit
    assert e.service.diagnostics()['verified_certificate_reuses']==1
    assert e.service.diagnostics()['full_verification_attempts']==1
    assert e.runtime.compatibility_certificate(e.case)==e.certificate


@pytest.mark.parametrize('damage',['missing','wrong_hash','wrong_action','wrong_case','wrong_engine','invalid_json'])
def test_bad_independent_audit_forces_full_verification_then_repairs_and_reuses(cached_app,monkeypatch,damage):
    e=cached_app
    with e.store.connect() as db:
        if damage=='missing':db.execute('DELETE FROM audit_log WHERE case_id=? AND action=?',(e.cid,AUDIT_ACTION))
        elif damage=='wrong_action':db.execute('UPDATE audit_log SET action=? WHERE case_id=? AND action=?',('analysis.screening_refinement_verified',e.cid,AUDIT_ACTION))
        elif damage=='wrong_case':db.execute('UPDATE audit_log SET case_id=? WHERE case_id=? AND action=?',('another-synthetic-case',e.cid,AUDIT_ACTION))
        elif damage=='invalid_json':db.execute('UPDATE audit_log SET detail=? WHERE case_id=? AND action=?',('{broken',e.cid,AUDIT_ACTION))
        else:
            row=db.execute('SELECT id,detail FROM audit_log WHERE case_id=? AND action=?',(e.cid,AUDIT_ACTION)).fetchone()
            detail=json.loads(row['detail']);detail['proof_sha256' if damage=='wrong_hash' else 'execution_engine']='wrong-proof'
            db.execute('UPDATE audit_log SET detail=? WHERE id=?',(json.dumps(detail),row['id']))
    audit=e.store.list_audit()
    assert e.store.get_compatible_implementation(e.cid,e.runtime.engine_id,e.current['digest']) is None
    assert e.store.list_audit()==audit
    e.runtime._basis_bindings.clear();response=e.client.get(e.base+'/report')
    assert response.status_code==200,response.json
    assert e.service.diagnostics()['full_verification_attempts']==2
    assert e.store.get_compatible_implementation(e.cid,e.runtime.engine_id,e.current['digest'])==e.certificate
    assert len(e.store.list_audit())==len(audit)+1
    repaired=e.store.list_audit();e.runtime._basis_bindings.clear()
    assert e.client.get(e.base+'/report').status_code==200
    assert e.service.diagnostics()['full_verification_attempts']==2
    assert e.service.diagnostics()['verified_certificate_reuses']==1
    assert e.store.list_audit()==repaired


@pytest.mark.parametrize('damage',['schema','kind','cache_schema','field','proof'])
def test_getter_does_not_trust_modified_json_even_with_an_audit_for_original(cached_app,damage):
    e=cached_app;changed=deepcopy(e.certificate)
    if damage=='schema':changed['schema']='arbitrary-compatibility'
    elif damage=='kind':changed['continuity_kind']='arbitrary-upgrade'
    elif damage=='cache_schema':changed['cache_schema']='arbitrary-cache'
    elif damage=='field':changed.pop('report_state_digest')
    else:changed['stt_proofs']=[{'forged':'proof'}]
    with e.store.connect() as db:
        db.execute('UPDATE analysis_implementation_compatibility SET certificate=? WHERE case_id=?',
                   (json.dumps(changed),e.cid))
    assert e.store.get_compatible_implementation(e.cid,e.runtime.engine_id,e.current['digest']) is None


@pytest.mark.parametrize('damage',['legacy','schema','kind','cache_schema','missing_snapshot'])
def test_even_a_matching_audit_cannot_authorize_an_unrecognized_cache_format(cached_app,damage):
    from ecg_core.analysis_provenance import digest
    e=cached_app;changed=deepcopy(e.certificate)
    if damage=='legacy':
        for key in ('cache_schema','continuity_kind','case_id','edited_feed_digest','report_state_digest'):
            changed.pop(key)
    elif damage=='schema':changed['schema']='unrecognized-policy'
    elif damage=='kind':changed['continuity_kind']='unrecognized-kind'
    elif damage=='cache_schema':changed['cache_schema']='unrecognized-cache'
    else:changed.pop('report_row_present')
    with e.store.connect() as db:
        db.execute('UPDATE analysis_implementation_compatibility SET certificate=? WHERE case_id=?',
                   (json.dumps(changed),e.cid))
        row=db.execute('SELECT id,detail FROM audit_log WHERE case_id=? AND action=?',(e.cid,AUDIT_ACTION)).fetchone()
        detail=json.loads(row['detail']);detail['proof_sha256']=digest(changed)
        db.execute('UPDATE audit_log SET detail=? WHERE id=?',(json.dumps(detail),row['id']))
    audit=e.store.list_audit()
    assert e.store.get_compatible_implementation(e.cid,e.runtime.engine_id,e.current['digest']) is None
    assert e.store.list_audit()==audit


def test_lookup_is_exact_for_case_engine_and_basis(cached_app):
    e=cached_app
    assert e.store.get_compatible_implementation('other-case',e.runtime.engine_id,e.current['digest']) is None
    assert e.store.get_compatible_implementation(e.cid,'0'*64,e.current['digest']) is None
    assert e.store.get_compatible_implementation(e.cid,e.runtime.engine_id,'0'*64) is None


def test_report_created_after_absent_row_snapshot_cannot_commit_or_reuse_at_same_version(
        synthetic_app,synthetic_case):
    app=synthetic_app;cid=synthetic_case[1];prepare_known_parent(app,cid)
    store=app.extensions['storage'];runtime=app.extensions['analysis_runtime']
    with store.connect() as db:db.execute('DELETE FROM report_drafts WHERE case_id=?',(cid,))
    client=app.test_client();base='/api/cases/'+cid
    response=client.get(base+'/report');assert response.status_code==200,response.json
    case=app.extensions['case_repository'].get_case(cid);current=runtime.direct_basis(case)
    certificate=store.get_compatible_implementation(cid,runtime.engine_id,current['digest'])
    assert certificate['report_version']==1 and certificate['report_row_present'] is False
    original_composition=store.get_report(cid,'')['composition']
    created=store.save_report(cid,'New same-version row','draft','synthetic-doctor')
    assert created['version']==2  # Ordinary server saves correctly advance it.
    # Simulate an out-of-band same-version insert, not a legitimate new save.
    with store.connect() as db:
        db.execute('UPDATE report_drafts SET version=1,composition=? WHERE case_id=?',
                   (json.dumps(original_composition),cid))
    before=rows(store);audit=store.list_audit()
    with pytest.raises(ReportConflict):
        store.record_compatible_implementation(cid,certificate,'synthetic-verifier',lambda:None)
    runtime._basis_bindings.clear();reopened=client.get(base+'/report')
    assert reopened.status_code==409 and '同一版本' in reopened.json['error']
    assert rows(store)==before and store.list_audit()==audit


@pytest.mark.parametrize('field,value',[
    ('conclusion','same-version rewrite'),('reviewed_by','different signer'),('status','draft'),
    ('analysis_provenance','{"screening_algorithm_version":"forged"}'),('updated_at','different-time')])
def test_same_version_database_tamper_returns_409_without_recertifying(cached_app,field,value):
    e=cached_app
    with e.store.connect() as db:db.execute('UPDATE report_drafts SET '+field+'=? WHERE case_id=?',(value,e.cid))
    before=rows(e.store);audit=e.store.list_audit();e.runtime._basis_bindings.clear()
    response=e.client.get(e.base+'/report')
    assert response.status_code==409 and '同一版本' in response.json['error']
    assert rows(e.store)==before and e.store.list_audit()==audit


@pytest.mark.parametrize('change',['conclusion','signer','status','provenance','timestamp','delete'])
def test_atomic_commit_rejects_report_race_even_at_same_version(cached_app,change):
    e=cached_app
    with e.store.connect() as db:
        if change=='delete':db.execute('DELETE FROM report_drafts WHERE case_id=?',(e.cid,))
        else:
            field={'conclusion':'conclusion','signer':'reviewed_by','status':'status',
                   'provenance':'analysis_provenance','timestamp':'updated_at'}[change]
            value='{"screening_algorithm_version":"forged"}' if change=='provenance' else 'changed-value'
            db.execute('UPDATE report_drafts SET '+field+'=? WHERE case_id=?',(value,e.cid))
    before=rows(e.store);audit=e.store.list_audit()
    with pytest.raises(ReportConflict):
        e.store.record_compatible_implementation(e.cid,e.certificate,'synthetic-verifier',lambda:None)
    assert rows(e.store)==before and e.store.list_audit()==audit


def test_new_engine_adds_its_own_certificate_and_audit_without_overwriting_old(cached_app):
    e=cached_app;second=deepcopy(e.certificate)
    second['execution_engine_id']='1'*64;second['execution_basis']='2'*64
    before=rows(e.store);audit=e.store.list_audit()
    e.store.record_compatible_implementation(e.cid,second,'synthetic-verifier',lambda:None)
    assert rows(e.store)==before and len(e.store.list_audit())==len(audit)+1
    assert e.store.get_compatible_implementation(e.cid,e.runtime.engine_id,e.current['digest'])==e.certificate
    assert e.store.get_compatible_implementation(e.cid,'1'*64,'2'*64)==second


def test_actual_raw_source_change_still_invalidates_even_with_audited_cache(cached_app,synthetic_case):
    e=cached_app;path=synthetic_case[2]['data'];raw=path.read_bytes();path.write_bytes(b'\1'+raw[1:])
    e.runtime._basis_bindings.clear();response=e.client.get(e.base+'/report')
    assert response.status_code==200,response.json
    assert response.json['status']=='draft' and response.json['reviewed_by']==''
    assert response.json['current_analysis_basis']['digest']!=e.previous['digest']




def test_04_reference_with_new_05_authored_record_and_signature_stays_screening_chain(
        synthetic_app,synthetic_case,source):
    from ecg_core.stt import ALGORITHM_VERSION
    from test_screening_continuity_transaction import prepare_screening_upgrade
    from test_stt_hospital_records import payload
    from test_stt_range import synthetic
    app=synthetic_app;cid=synthetic_case[1]
    raw,_=synthetic(seconds=90);synthetic_case[2]['data'].write_bytes(raw.tobytes())
    previous,_=prepare_screening_upgrade(app,cid,source)
    client=app.test_client();base='/api/cases/'+cid
    assert client.get(base+'/report').status_code==200
    submitted=payload(client,base,'st_depression',review_extent='whole',end_sample=11999,
        measurement_protocol=dict(measurement_ms=60,extent='whole'))
    submitted['sample_index']=0
    saved=client.post(base+'/annotations',json=submitted)
    assert saved.status_code==201,saved.json
    assert saved.json['details']['stt_input_binding']['screening_method']==ALGORITHM_VERSION
    receipt=saved.json['stt_review_receipt'];store=app.extensions['storage']
    for step in ('edit','stt'):
        store.complete_review(cid,dict(step=step,confirmed=True,revision=store.get_review(cid)['revision']),'synthetic-doctor')
    report=client.get(base+'/report').json
    ref=dict(event_id=receipt['event_id'],basis_version=receipt['basis_version'])
    composition={**report['composition'],'page_selection_version':1,'included_pages':['summary','st_events'],
        'stt_report_use':[{**ref,'table':False,'text':True,'strip':False}]}
    draft=client.put(base+'/report',json=dict(expected_version=report['version'],status='draft',
        conclusion='Synthetic .5 work with retained .4 reference',composition=composition))
    assert draft.status_code==200,draft.json
    signed=client.put(base+'/report',json=dict(expected_version=draft.json['version'],status='reviewed',
        conclusion=draft.json['conclusion'],composition=draft.json['composition']))
    assert signed.status_code==200,signed.json
    assert signed.json['analysis_provenance']['screening_algorithm_version']==ALGORITHM_VERSION
    before=rows(store);runtime=app.extensions['analysis_runtime'];runtime._basis_bindings.clear()
    reopened=client.get(base+'/report')
    assert reopened.status_code==200,reopened.json
    assert reopened.json['status']=='reviewed' and reopened.json['current_analysis_basis']==previous
    assert rows(store)==before
    case=app.extensions['case_repository'].get_case(cid);certificate=runtime.compatibility_certificate(case)
    assert certificate['continuity_kind']=='stt_screening_refinement'
    assert certificate['signed_report_snapshot'] is None
    assert saved.json['id'] in certificate['retained_stt_records']
    assert app.extensions['performance_compatibility'].diagnostics()['full_verification_attempts']==0
