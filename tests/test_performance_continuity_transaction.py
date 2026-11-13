"""A verified performance release must preserve authored work atomically."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import json

import pytest

from ecg_core.analysis_provenance import digest
from ecg_core.beat_editor import BeatEditorStore
from ecg_core.overview import RhythmReviewStore
from ecg_core.repository import CaseRepository
from ecg_core.review_workflow import ReportConflict
from ecg_core.storage import Storage
from test_analysis_provenance import approve, make_basis, synthetic_app, synthetic_case


def rows(store):
    with store.connect() as db:
        return {name:list(map(tuple,db.execute('SELECT * FROM '+name))) for name in
                ('case_analysis_basis','report_drafts','case_review','annotations','beat_edit_documents','rhythm_reviews')}


def certificate(store,cid='case'):
    report=store.get_report(cid,'')
    return dict(reference_basis=store.get_analysis_basis(cid),execution_basis='new-execution',
                execution_engine_id='verified-performance-build',review_revision=store.get_review(cid)['revision'],
                report_version=report['version'],report_composition_digest=digest(report['composition']),
                authored_annotations_digest=digest(store.list_annotations(cid)),
                beat_revision=0,editor_document_digest=digest({}),retained_stt_records=[])


@pytest.fixture
def approved_store(tmp_path):
    store=Storage(tmp_path/'doctor.db')
    BeatEditorStore(store);RhythmReviewStore(store)
    store.sync_analysis_basis('case',make_basis(1),'tester')
    approve(store,'case',{'selected_events':[{'event_id':'synthetic','basis_version':'v1'}]})
    return store


def test_continuity_preserves_all_authored_rows_and_adds_separate_idempotent_audit(approved_store):
    store=approved_store;before=rows(store);proof=certificate(store)
    old_audit=store.list_audit()
    store.record_compatible_implementation('case',proof,'upgrade-checker',lambda:None)
    assert rows(store)==before
    assert store.get_report('case','')['status']=='reviewed'
    assert len(store.list_audit())==len(old_audit)+1
    assert store.list_audit()[0]['action']=='analysis.performance_upgrade_verified'
    store.record_compatible_implementation('case',proof,'upgrade-checker',lambda:None)
    assert rows(store)==before and len(store.list_audit())==len(old_audit)+1
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM analysis_implementation_compatibility').fetchone()[0]==1


@pytest.mark.parametrize('change',['basis','review_revision','report_version','composition','annotations','missing_beats','source_race'])
def test_races_and_mismatched_snapshots_commit_no_partial_continuity(approved_store,change):
    store=approved_store;proof=certificate(store);before=rows(store);old_audit=store.list_audit()
    if change=='basis':proof['reference_basis']=make_basis(9)
    if change=='review_revision':proof['review_revision']+=1
    if change=='report_version':proof['report_version']+=1
    if change=='composition':proof['report_composition_digest']='different-adoption'
    if change=='annotations':proof['authored_annotations_digest']='different-annotation'
    if change=='missing_beats':proof['beat_revision']=1
    def check():
        if change=='source_race':raise ReportConflict('source changed while verifying')
    with pytest.raises(ReportConflict):store.record_compatible_implementation('case',proof,'checker',check)
    assert rows(store)==before and store.list_audit()==old_audit
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM analysis_implementation_compatibility').fetchone()[0]==0


def prepare_known_parent(app,cid):
    # Explicit test-only published parent: real current manifest with a different
    # archived application identity. Real releases ship exact parent manifests.
    runtime=app.extensions['analysis_runtime'];store=app.extensions['storage']
    case=app.extensions['case_repository'].get_case(cid)
    execution=runtime.direct_basis(case)
    parent=deepcopy(execution['engine']);parent['artifacts']['app']='synthetic-published-parent'
    body=dict(schema=execution['schema'],engine_id=digest(parent),inputs=execution['inputs'])
    prior={**body,'digest':digest(body),'engine':parent}
    store.sync_analysis_basis(cid,prior,'synthetic-upgrade-setup')
    old=approve(store,cid)
    policy=app.extensions['performance_compatibility']
    # A changed source checkout must not regenerate the shipped performance
    # policy. This fixture explicitly constructs its synthetic performance-only
    # parent/current pair instead of authorizing the real screening change.
    from ecg_core.performance_compatibility import code_fingerprints, POLICY_SCHEMA
    policy.policy={'schema':POLICY_SCHEMA,'current_code':code_fingerprints(policy.root,
        ('app',)+tuple('ecg_core.'+n for n in runtime.module_names))}
    policy._code_ok=True
    policy.policy['parent_engines']=[parent];policy.policy['parent_engine_ids']=[digest(parent)]
    policy.policy_digest=digest(policy.policy)
    return prior,old


def test_known_performance_upgrade_keeps_approval_and_formal_export(synthetic_app,synthetic_case,monkeypatch):
    app=synthetic_app;cid=synthetic_case[1];prior,old=prepare_known_parent(app,cid)
    store=app.extensions['storage'];before=rows(store);client=app.test_client();base='/api/cases/'+cid
    current=client.get(base+'/report')
    assert current.status_code==200,current.json
    assert current.json['status']=='reviewed' and current.json['reviewed_by']==old['reviewed_by']
    assert current.json['version']==old['version']
    assert current.json['current_analysis_basis']==prior
    assert rows(store)==before
    monkeypatch.setattr('app.build_report_pdf',lambda *a,**k:BytesIO(b'%PDF-verified-formal-test'))
    pdf=client.get(base+'/report.pdf',query_string={'expected_version':old['version']})
    assert pdf.status_code==200,pdf.json
    assert pdf.headers['X-Analysis-Basis']==prior['digest']
    assert pdf.headers['X-Execution-Engine']==app.extensions['analysis_runtime'].engine_id
    assert rows(store)==before


def test_real_source_change_after_compatible_upgrade_still_invalidates(synthetic_app,synthetic_case):
    app=synthetic_app;cid=synthetic_case[1];prior,old=prepare_known_parent(app,cid)
    client=app.test_client();base='/api/cases/'+cid
    assert client.get(base+'/report').json['status']=='reviewed'
    path=synthetic_case[2]['data'];data=path.read_bytes();path.write_bytes(b'\1'+data[1:])
    changed=client.get(base+'/report')
    assert changed.status_code==200,changed.json
    assert changed.json['status']=='draft' and changed.json['reviewed_by']==''
    assert changed.json['current_analysis_basis']['digest']!=prior['digest']
    assert client.get(base+'/report.pdf',query_string={'expected_version':old['version']}).status_code==409


def test_upgraded_workspace_can_be_backed_up_with_continuity_receipt(approved_store,tmp_path):
    from ecg_core.workspace_backup import create_backup,verify_backup
    store=approved_store
    store.record_compatible_implementation('case',certificate(store),'upgrade-checker',lambda:None)
    before=rows(store)
    result=create_backup(store.path,tmp_path/'saved-work')
    archive=Path(result['path'])
    checked=verify_backup(archive)
    assert checked['tables']['analysis_implementation_compatibility']==1
    assert rows(store)==before
