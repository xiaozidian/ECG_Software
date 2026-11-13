"""Only independently audited, exact-snapshot migration proofs survive restart."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from ecg_core.analysis_provenance import digest
from ecg_core.review_workflow import ReportConflict
from test_screening_compatibility import continuity, evidence, source
from test_analysis_provenance import synthetic_app, synthetic_case
from test_screening_continuity_transaction import prepare_screening_upgrade
from test_performance_continuity_transaction import rows


@pytest.fixture
def proof(continuity):
    c=continuity;service=c.service();certificate=c.resolve(service)
    assert certificate
    def matches(value=None):
        return service._cached_snapshot_matches(value or certificate,c.case,c.previous,c.current,c.e.feed,
            [c.e.annotation],c.report,c.e.scope['analysis_revision'],c.e.scope['beat_revision'])
    return SimpleNamespace(c=c,service=service,certificate=certificate,matches=matches)


def test_full_proof_matches_only_its_exact_live_snapshot(proof):
    assert proof.matches()
    assert len(proof.certificate['edited_feed_digest'])==64


@pytest.mark.parametrize('field',[
    'schema','continuity_kind','case_id','policy_digest','screening_transition','reference_basis',
    'execution_basis','execution_engine_id','source_inputs_digest','beat_revision','beat_basis_version',
    'edited_feed_digest','editor_document_digest','authored_annotations_digest','review_revision',
    'report_version','report_composition_digest','measurement_projection_digest','signed_report_snapshot',
])
def test_each_certificate_identity_or_proof_difference_is_a_cache_miss(proof,field):
    changed=deepcopy(proof.certificate);changed[field]='not-the-verified-value'
    assert not proof.matches(changed)


@pytest.mark.parametrize('change',['beat','marker','records','settings','duration','annotation','review_revision'])
def test_live_edited_inputs_or_authored_snapshot_change_cannot_reuse(proof,change):
    c=proof.c
    if change=='beat':c.e.feed.beats[5]['class_code']='V'
    elif change=='marker':c.e.feed.markers.append(dict(id='marker:1',sample_index=205,class_code='X'))
    elif change=='records':c.e.feed.records[5]['rr_ms']=1001
    elif change=='settings':c.e.feed.document['settings']['nn_min_ms']+=1
    elif change=='duration':c.e.feed.duration+=1
    elif change=='annotation':c.e.annotation['note']='same-revision changed physician prose'
    else:c.e.scope['analysis_revision']+=1
    assert not proof.matches()


@pytest.mark.parametrize('field,value',[
    ('conclusion','same-version unreviewed text'),('reviewed_by','different signer'),('status','draft'),
    ('composition',{'selected_events':[]}),('analysis_provenance',{}),('updated_at','different-time'),
])
def test_same_version_report_tampering_is_a_conflict_not_a_new_measurement_authorization(proof,field,value):
    proof.c.report[field]=value
    with pytest.raises(ReportConflict,match='同一版本'):
        proof.matches()


def test_real_new_report_version_is_a_cache_miss_for_full_verification(proof):
    proof.c.report.update(version=10,status='draft')
    assert not proof.matches()


@pytest.mark.parametrize('change',['source','epoch','dependencies','source_contract','unknown_parent','policy'])
def test_input_build_and_policy_guards_run_before_cache_or_analyzers(proof,monkeypatch,change):
    from ecg_core import stt,stt_screening_legacy
    c=proof.c;service=proof.service
    if change=='source':c.current['inputs']['data']['sha256']='0'*64
    elif change=='epoch':c.current['recovery_epoch']='a-restored-workspace'
    elif change=='dependencies':c.current['engine']['dependencies']['synthetic-runtime']='2'
    elif change=='source_contract':c.current['engine']['sample_rate_hz']=250
    elif change=='unknown_parent':service.policy['parent_engine_ids']=[]
    else:service._measurement_ok=False
    service.storage=SimpleNamespace(get_compatible_implementation=lambda *args:pytest.fail('must not consult cache'))
    monkeypatch.setattr(stt,'analyze_stt',lambda *args,**kwargs:pytest.fail('must not analyze changed build/source'))
    monkeypatch.setattr(stt_screening_legacy,'analyze_stt',lambda *args,**kwargs:pytest.fail('must not analyze changed build/source'))
    assert service.resolve(c.case,c.previous,c.current,c.e.feed,[c.e.annotation],c.report,
        c.e.scope['analysis_revision'],c.e.scope['beat_revision']) is None


@pytest.fixture
def cached_app(synthetic_app,synthetic_case,source):
    app=synthetic_app;cid=synthetic_case[1]
    previous,old=prepare_screening_upgrade(app,cid,source)
    client=app.test_client();response=client.get('/api/cases/'+cid+'/report')
    assert response.status_code==200,response.json
    store=app.extensions['storage'];runtime=app.extensions['analysis_runtime']
    case=app.extensions['case_repository'].get_case(cid);current=runtime.direct_basis(case)
    certificate=store.get_compatible_implementation(cid,runtime.engine_id,current['digest'])
    assert certificate and certificate['reference_basis']==previous
    return SimpleNamespace(app=app,cid=cid,client=client,store=store,runtime=runtime,
        case=case,current=current,previous=previous,old=old,certificate=certificate,
        base='/api/cases/'+cid,service=app.extensions['screening_compatibility'])


def test_restart_reuses_exact_audited_proof_without_either_analyzer_or_duplicate_audit(cached_app,monkeypatch):
    from ecg_core import stt,stt_screening_legacy
    e=cached_app;before=rows(e.store);audit=e.store.list_audit()
    e.runtime._basis_bindings.clear()
    monkeypatch.setattr(stt,'analyze_stt',lambda *args,**kwargs:pytest.fail('current analyzer must not run'))
    monkeypatch.setattr(stt_screening_legacy,'analyze_stt',lambda *args,**kwargs:pytest.fail('legacy analyzer must not run'))
    response=e.client.get(e.base+'/report')
    assert response.status_code==200,response.json
    assert response.json['status']=='reviewed' and response.json['current_analysis_basis']==e.previous
    assert rows(e.store)==before and e.store.list_audit()==audit
    assert e.service.diagnostics()['verified_certificate_reuses']==1
    assert e.service.diagnostics()['full_verification_attempts']==1
    assert e.runtime.compatibility_certificate(e.case)==e.certificate


@pytest.mark.parametrize('damage',['missing','wrong_hash','wrong_action','wrong_case','wrong_engine','invalid_json'])
def test_missing_or_mismatched_independent_audit_forces_full_verification_repairs_audit_then_reuses(cached_app,monkeypatch,damage):
    from ecg_core import stt,stt_screening_legacy
    e=cached_app;action='analysis.screening_refinement_verified'
    with e.store.connect() as db:
        if damage=='missing':db.execute('DELETE FROM audit_log WHERE case_id=? AND action=?',(e.cid,action))
        elif damage=='wrong_action':db.execute('UPDATE audit_log SET action=? WHERE case_id=? AND action=?',('analysis.performance_upgrade_verified',e.cid,action))
        elif damage=='wrong_case':db.execute('UPDATE audit_log SET case_id=? WHERE case_id=? AND action=?',('another-synthetic-case',e.cid,action))
        elif damage=='invalid_json':db.execute('UPDATE audit_log SET detail=? WHERE case_id=? AND action=?',('{broken',e.cid,action))
        else:
            row=db.execute('SELECT id,detail FROM audit_log WHERE case_id=? AND action=?',(e.cid,action)).fetchone()
            detail=json.loads(row['detail']);detail['proof_sha256' if damage=='wrong_hash' else 'execution_engine']='wrong-proof'
            db.execute('UPDATE audit_log SET detail=? WHERE id=?',(json.dumps(detail),row['id']))
    audit=e.store.list_audit()
    assert e.store.get_compatible_implementation(e.cid,e.runtime.engine_id,e.current['digest']) is None
    assert e.store.list_audit()==audit  # The reader cannot manufacture an audit.
    calls={'old':0,'new':0};old=stt_screening_legacy.analyze_stt;new=stt.analyze_stt
    def old_spy(*args,**kwargs):calls['old']+=1;return old(*args,**kwargs)
    def new_spy(*args,**kwargs):calls['new']+=1;return new(*args,**kwargs)
    monkeypatch.setattr(stt_screening_legacy,'analyze_stt',old_spy);monkeypatch.setattr(stt,'analyze_stt',new_spy)
    e.runtime._basis_bindings.clear();response=e.client.get(e.base+'/report')
    assert response.status_code==200,response.json
    assert calls=={'old':1,'new':1}
    assert e.store.get_compatible_implementation(e.cid,e.runtime.engine_id,e.current['digest'])==e.certificate
    assert len(e.store.list_audit())==len(audit)+1
    repaired=e.store.list_audit();e.runtime._basis_bindings.clear()
    response=e.client.get(e.base+'/report')
    assert response.status_code==200,response.json
    assert calls=={'old':1,'new':1} and e.store.list_audit()==repaired


def test_modified_certificate_json_does_not_self_authorize(cached_app):
    e=cached_app;changed=deepcopy(e.certificate);changed['measurement_projection_digest']='0'*64
    with e.store.connect() as db:
        db.execute('UPDATE analysis_implementation_compatibility SET certificate=? '
                   'WHERE case_id=? AND execution_engine_id=? AND execution_basis=?',
                   (json.dumps(changed),e.cid,e.runtime.engine_id,e.current['digest']))
    assert e.store.get_compatible_implementation(e.cid,e.runtime.engine_id,e.current['digest']) is None


def test_lookup_does_not_generalize_an_engine_basis_or_case(cached_app):
    e=cached_app
    assert e.store.get_compatible_implementation(e.cid,'new-execution-engine',e.current['digest']) is None
    assert e.store.get_compatible_implementation(e.cid,e.runtime.engine_id,'different-input-basis') is None
    assert e.store.get_compatible_implementation('different-case',e.runtime.engine_id,e.current['digest']) is None


def test_same_version_report_database_tamper_after_restart_returns_409_without_recertifying(cached_app,monkeypatch):
    from ecg_core import stt,stt_screening_legacy
    e=cached_app
    with e.store.connect() as db:db.execute('UPDATE report_drafts SET conclusion=? WHERE case_id=?',('same-version unreviewed rewrite',e.cid))
    before=rows(e.store);audit=e.store.list_audit();e.runtime._basis_bindings.clear()
    monkeypatch.setattr(stt,'analyze_stt',lambda *args,**kwargs:pytest.fail('must not recertify tampered report'))
    monkeypatch.setattr(stt_screening_legacy,'analyze_stt',lambda *args,**kwargs:pytest.fail('must not recertify tampered report'))
    response=e.client.get(e.base+'/report')
    assert response.status_code==409 and '同一版本' in response.json['error']
    assert rows(e.store)==before and e.store.list_audit()==audit


def test_real_source_change_after_audited_cache_still_invalidates(cached_app,synthetic_case,monkeypatch):
    from ecg_core import stt,stt_screening_legacy
    e=cached_app;path=synthetic_case[2]['data'];raw=path.read_bytes();path.write_bytes(b'\1'+raw[1:])
    e.runtime._basis_bindings.clear()
    monkeypatch.setattr(stt,'analyze_stt',lambda *args,**kwargs:pytest.fail('changed source cannot reuse migration'))
    monkeypatch.setattr(stt_screening_legacy,'analyze_stt',lambda *args,**kwargs:pytest.fail('changed source cannot reuse migration'))
    response=e.client.get(e.base+'/report')
    assert response.status_code==200,response.json
    assert response.json['status']=='draft' and response.json['reviewed_by']==''
    assert response.json['current_analysis_basis']['digest']!=e.previous['digest']
