"""Screening continuity adds a separate receipt without editing authored rows."""
from copy import deepcopy
from io import BytesIO
import json

import pytest

from ecg_core.analysis_provenance import digest
from ecg_core.review_workflow import ReportConflict
from ecg_core.screening_compatibility import (ScreeningCompatibility, POLICY_NAME, POLICY_SCHEMA,
    CONTINUITY_KIND, LEGACY_SOURCE_SHA256, LEGACY_SCREENING_VERSION, REFINED_SCREENING_VERSION, report_identity)
from test_analysis_provenance import approve, synthetic_app, synthetic_case
from test_performance_continuity_transaction import approved_store, rows, certificate
from test_screening_compatibility import source, builder
from test_stt_compatibility import evidence


def screening_certificate(store):
    proof=certificate(store)
    report=store.get_report('case','')
    proof.update(schema=POLICY_SCHEMA,continuity_kind=CONTINUITY_KIND,
                 report_state_digest=report_identity(report),signed_report_snapshot=None)
    return proof


def test_screening_receipt_retains_rows_signature_picks_and_old_source_scope(approved_store):
    store=approved_store;before=rows(store);proof=screening_certificate(store)
    store.record_compatible_implementation('case',proof,'screening-verifier',lambda:None)
    assert rows(store)==before
    assert store.get_report('case','')['status']=='reviewed'
    assert store.list_audit()[0]['action']=='analysis.screening_refinement_verified'
    audit=store.list_audit()
    store.record_compatible_implementation('case',proof,'screening-verifier',lambda:None)
    assert rows(store)==before and store.list_audit()==audit


@pytest.mark.parametrize('field,value',[('status','draft'),('reviewed_by','a-different-signer'),
                                       ('conclusion','same-version changed text'),('analysis_provenance','{}')])
def test_same_version_changed_report_state_refuses_signature_continuity(approved_store,field,value):
    store=approved_store;proof=screening_certificate(store)
    with store.connect() as db:
        db.execute('UPDATE report_drafts SET '+field+'=? WHERE case_id=?',(value,'case'))
    before=rows(store);audit=store.list_audit()
    with pytest.raises(ReportConflict):
        store.record_compatible_implementation('case',proof,'screening-verifier',lambda:None)
    assert rows(store)==before and store.list_audit()==audit
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM analysis_implementation_compatibility').fetchone()[0]==0


def prepare_screening_upgrade(app,cid,source,configure=None):
    runtime=app.extensions['analysis_runtime'];store=app.extensions['storage']
    case=app.extensions['case_repository'].get_case(cid)
    execution=runtime.direct_basis(case)
    parent=deepcopy(execution['engine']);parent['artifacts']['app']='synthetic-published-04-parent'
    parent['artifacts']['ecg_core.stt']=LEGACY_SOURCE_SHA256
    body=dict(schema=execution['schema'],engine_id=digest(parent),inputs=execution['inputs'])
    previous={**body,'digest':digest(body),'engine':parent}
    store.sync_analysis_basis(cid,previous,'synthetic-screening-upgrade-setup')
    composition=configure(store,cid,previous,case) if configure else None
    old=approve(store,cid,composition)
    (source/POLICY_NAME).write_text(json.dumps(builder.build(source,[parent])))
    app.extensions['screening_compatibility']=ScreeningCompatibility(source,runtime,store,None)
    assert app.extensions['screening_compatibility'].diagnostics()['code_matched']
    return previous,old


def test_saved_legacy_review_pick_and_uses_survive_and_old_candidate_submission_is_rejected(
        synthetic_app,synthetic_case,source,evidence,monkeypatch):
    from uuid import uuid4
    from ecg_core.beat_editor import BeatEditorStore, EditedRecords
    from ecg_core.ebi import load_records
    from ecg_core.stt_compatibility import make_input_binding
    from ecg_core.stt_records import decorate_event
    from ecg_core.stt_range import analyze_stt_range
    from ecg_core.clinical_analysis import beat_basis_version
    from ecg_core import stt, stt_screening_legacy
    from test_stt_range import synthetic
    app=synthetic_app;cid=synthetic_case[1]
    raw,_=synthetic(seconds=90);synthetic_case[2]['data'].write_bytes(raw.tobytes())
    event=dict(kind='st_depression',leads=['II'],start_s=0,end_s=60)
    old_id=stt_screening_legacy._merge_episodes([event])[0]['id']
    assert old_id!=stt._merge_episodes([event])[0]['id']
    def configure(store,cid,previous,case):
        editor=BeatEditorStore(store);snapshot=editor.snapshot(cid)
        feed=EditedRecords(load_records(case['paths']['ebi']),snapshot['document'],[],90)
        scope=dict(case_id=cid,analysis_basis=previous['digest'],
                   analysis_revision=store.get_review(cid)['revision'],beat_revision=snapshot['revision'])
        details=deepcopy(evidence.annotation['details'])
        details.update(review_scope=scope,submission_id=str(uuid4()))
        details['stt_event_evidence'].update(scope=scope,algorithm_version=LEGACY_SCREENING_VERSION,
            candidate_id=old_id,source='reviewed_automatic_candidate')
        measured=analyze_stt_range(case['paths']['data'],feed.records,start_sample=0,end_sample=12000,
                                   leads=['II'],measurement_ms=60,basis=scope,
                                   source_digest=digest(previous['inputs']))
        details['stt_event_evidence'].update(metrics=measured['leads'],coverage=measured['coverage'],
                                             counts=measured['counts'])
        details['stt_event_evidence']['measurement_protocol']['range_profile']=measured['method_profile']
        details['stt_input_binding']=make_input_binding(feed,scope,previous)
        details['stt_input_binding']['screening_method']=LEGACY_SCREENING_VERSION
        payload=dict(sample_index=0,lead='II',label='Synthetic physician conclusion',
                     note='Retained physician prose',details=details)
        item=store.save_stt_record(cid,payload,'synthetic-doctor',guard=lambda db:None,
             replay_guard=lambda db:None,request_sha256=digest(payload))
        decorated=decorate_event({'event_id':'annotation:'+str(item['id'])},item,beat_basis_version(feed))
        composition=store.get_report(cid,'')['composition']
        selection=dict(event_id=decorated['event_id'],basis_version=decorated['basis_version'],
                       leads=['II'],duration_s=10,caption='Retained caption',notes='Retained strip notes',
                       print_enabled=True,referenced_in_report=True)
        composition.update(page_selection_version=1,included_pages=['summary','event_strips','st_events'],
            selected_events=[selection],stt_report_use=[dict(event_id=decorated['event_id'],
                basis_version=decorated['basis_version'],table=True,text=True,strip=True)])
        return composition
    previous,old=prepare_screening_upgrade(app,cid,source,configure)
    store=app.extensions['storage'];before=rows(store);client=app.test_client();base='/api/cases/'+cid
    review=client.get(base+'/stt-review')
    assert review.status_code==200,review.json
    assert review.json['analysis']['algorithm_version']==REFINED_SCREENING_VERSION
    receipt=review.json['review_records'][0]['stt_review_receipt']
    assert receipt['review_state']=='reviewed' and receipt['report_use']['table']
    assert receipt['report_use']['text'] and receipt['report_use']['strip']
    assert receipt['basis_version']==old['composition']['selected_events'][0]['basis_version']
    monkeypatch.setattr('app.build_report_pdf',lambda *args,**kwargs:BytesIO(b'%PDF-preserved-legacy-record'))
    exported=client.get(base+'/report.pdf',query_string={'expected_version':old['version']})
    assert exported.status_code==200,exported.json
    assert rows(store)==before
    scope={key:review.json[key] for key in ('case_id','analysis_basis','analysis_revision','beat_revision')}
    payload=dict(sample_index=0,lead='II',label='Stale candidate attempt',details=dict(kind='ST',
        reviewed=True,result_code='st_depression',review_extent='whole',review_leads=['II'],
        end_sample=11999,submission_id=str(uuid4()),review_scope=scope,
        stt_candidate_scope=scope,stt_candidate_id=old_id))
    rejected=client.post(base+'/annotations',json=payload)
    assert rejected.status_code==409,rejected.json
    assert rows(store)==before


def test_real_app_screening_upgrade_retains_reviewed_export_and_adds_truthful_audit(synthetic_app,synthetic_case,source,monkeypatch):
    app=synthetic_app;cid=synthetic_case[1]
    previous,old=prepare_screening_upgrade(app,cid,source)
    store=app.extensions['storage'];before=rows(store);client=app.test_client();base='/api/cases/'+cid
    response=client.get(base+'/report')
    assert response.status_code==200,response.json
    assert response.json['current_analysis_basis']==previous
    assert response.json['status']=='reviewed' and response.json['reviewed_by']==old['reviewed_by']
    assert response.json['version']==old['version']
    assert rows(store)==before
    assert store.list_audit()[0]['action']=='analysis.screening_refinement_verified'
    monkeypatch.setattr('app.build_report_pdf',lambda *args,**kwargs:BytesIO(b'%PDF-screening-verified-synthetic'))
    pdf=client.get(base+'/report.pdf',query_string={'expected_version':old['version']})
    assert pdf.status_code==200,pdf.json
    assert pdf.headers['X-Analysis-Basis']==previous['digest']
    assert pdf.headers['X-Execution-Engine']==app.extensions['analysis_runtime'].engine_id
    assert rows(store)==before


def test_true_source_change_after_screening_continuity_still_invalidates(synthetic_app,synthetic_case,source):
    app=synthetic_app;cid=synthetic_case[1]
    previous,old=prepare_screening_upgrade(app,cid,source)
    client=app.test_client();base='/api/cases/'+cid
    assert client.get(base+'/report').json['status']=='reviewed'
    path=synthetic_case[2]['data'];raw=path.read_bytes();path.write_bytes(b'\1'+raw[1:])
    changed=client.get(base+'/report')
    assert changed.status_code==200,changed.json
    assert changed.json['status']=='draft' and changed.json['reviewed_by']==''
    assert changed.json['current_analysis_basis']['digest']!=previous['digest']
    assert client.get(base+'/report.pdf',query_string={'expected_version':old['version']}).status_code==409


def test_new_report_save_records_actual_screening_and_restart_does_not_freeze_old_label(synthetic_app,synthetic_case,source):
    app=synthetic_app;cid=synthetic_case[1]
    previous,old=prepare_screening_upgrade(app,cid,source)
    client=app.test_client();base='/api/cases/'+cid
    retained=client.get(base+'/report').json
    composition={**retained['composition'],'include_hrv':False,
                 'page_selection_version':1,'included_pages':['summary']}
    draft=client.put(base+'/report',json=dict(expected_version=retained['version'],status='draft',
        conclusion=retained['conclusion'],composition=composition))
    assert draft.status_code==200,draft.json
    assert draft.json['analysis_provenance']['screening_algorithm_version']==REFINED_SCREENING_VERSION
    assert draft.json['analysis_provenance']['execution_engine_id']==app.extensions['analysis_runtime'].engine_id
    signed=client.put(base+'/report',json=dict(expected_version=draft.json['version'],status='reviewed',
        conclusion=draft.json['conclusion'],composition=draft.json['composition']))
    assert signed.status_code==200,signed.json
    assert signed.json['status']=='reviewed'
    runtime=app.extensions['analysis_runtime']
    runtime._basis_bindings.clear()  # A fresh process has no in-memory reference bindings.
    after=client.get(base+'/report')
    assert after.status_code==200,after.json
    assert after.json['status']=='reviewed' and after.json['version']==signed.json['version']
    case=app.extensions['case_repository'].get_case(cid)
    assert runtime.compatibility_certificate(case)['signed_report_snapshot'] is None
