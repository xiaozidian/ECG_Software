"""Reject misleading compatibility verdicts; actual Windows acceptance runs separately."""
import copy
from pathlib import Path
import pytest
from scripts.verify_windows_performance_preserve import (
    APP, BASE_APP, BASE_PE_SHA, metadata_identity, compare_api, fingerprint,
)


def baseline():
    engine = dict(app_version=BASE_APP, artifacts=dict(app=BASE_PE_SHA))
    basis = dict(schema=1, engine=engine, engine_id=fingerprint(engine), inputs={'math': 'c'*64})
    basis['digest'] = fingerprint({k:v for k,v in basis.items() if k!='engine'})
    evidence = {'kind':'t_inversion', 'start_s':60, 'end_s':180, 'measurements':[1,2,3]}
    eligibility = dict(table=True, text=True, strip=True)
    report = dict(status='reviewed', reviewed_by='mathematical-physician', version=5, review_revision=2,
                  current_analysis_basis=basis, current_hrv_reference={'revision':0,'scope':{'analysis_basis':basis['digest']}},
                  conclusion='original authored conclusion', analysis_provenance={'basis':basis,'signature':'original signature'},
                  composition={'selected_events':[{'event_id':'annotation:1','leads':['I','II']}],
                               'stt_report_use':[{'event_id':'annotation:1',**eligibility}]})
    before = dict(report=report, beat_editor={'revision':0}, annotations={'items':[{'id':1,'details':evidence}]},
                  workflow={'steps':{'stt':{'status':'done','actor':'mathematical-physician'}}},
                  events={'items':[{'event_id':'annotation:1','category':'ST','stt_review_state':'reviewed',
                                    'stt_report_eligibility':eligibility,'stt_event_evidence':evidence}]},
                  stt={'analysis':{'algorithm_version':'stt-screening-0.4.0-comprehensive-independent'}})
    return before, copy.deepcopy(before), dict(base_exe_sha256=BASE_PE_SHA,new_exe_sha256='a'*64)


def test_performance_upgrade_preserves_qualified_review_and_original_signature():
    before,after,package=baseline()
    proof=compare_api(before,after,package)
    assert proof['original_signature_retained_not_resigned']
    assert proof['retained_qualified_STT']==['annotation:1']
    assert proof['original_status']==proof['upgraded_status']=='reviewed'


@pytest.mark.parametrize('fault', ['basis-replaced','draft','reviewer-lost','version-changed','revision-changed',
                                  'conclusion-lost','signature-resigned','selection-lost','HRV-reset','workflow-reset',
                                  'record-stale','table-ineligible','text-ineligible','strip-ineligible',
                                  'annotation-rewritten','proof-relabelled','record-lost','beats-edited','algorithm-changed'])
def test_preservation_verdict_rejects_partial_or_false_upgrade(fault):
    before,after,package=baseline(); report=after['report']; event=after['events']['items'][0]
    if fault=='basis-replaced': report['current_analysis_basis']['engine_id']='new-engine'
    if fault=='draft': report['status']='draft'
    if fault=='reviewer-lost': report['reviewed_by']=''
    if fault=='version-changed': report['version']+=1
    if fault=='revision-changed': report['review_revision']+=1
    if fault=='conclusion-lost': report['conclusion']=''
    if fault=='signature-resigned': report['analysis_provenance']['signature']='new'
    if fault=='selection-lost': report['composition']['selected_events']=[]
    if fault=='HRV-reset': report['current_hrv_reference']['revision']=1
    if fault=='workflow-reset': after['workflow']['steps']['stt']['status']='stale'
    if fault=='record-stale': event['stt_review_state']='stale'
    if fault.endswith('-ineligible'): event['stt_report_eligibility'][fault.split('-')[0]]=False
    if fault=='annotation-rewritten': after['annotations']['items'][0]['details']['start_s']=61
    if fault=='proof-relabelled': event['stt_event_evidence']['end_s']=181
    if fault=='record-lost': after['events']['items']=[]
    if fault=='beats-edited': after['beat_editor']['revision']=1
    if fault=='algorithm-changed': after['stt']['analysis']['algorithm_version']='changed'
    with pytest.raises(AssertionError): compare_api(before,after,package)


def test_package_identity_requires_distinct_real_delivered_executables():
    release=dict(packaging_version='1.0.21',app_version=APP,software_version=APP,source_id='P01',source_data_bundled=False)
    previous=dict(packaging_version='1.0.20',app_version=BASE_APP,source_id='P01',source_data_bundled=False)
    shared=dict(core_version='performance-source',ui_version='new-ui')
    old=dict(core_version='old-source',ui_version='old-ui')
    proof=metadata_identity(release,shared,old_release=previous,old_shared=old,new_PE_sha256='a'*64,old_PE_sha256=BASE_PE_SHA)
    assert proof['packaging_version']=='1.0.21'
    with pytest.raises(AssertionError):
        metadata_identity(release,shared,old_release=previous,old_shared=old,new_PE_sha256=BASE_PE_SHA,old_PE_sha256=BASE_PE_SHA)


def test_current_package_requires_policy_and_original20_content_can_be_verified(tmp_path):
    import json, shutil
    from tests.test_windows_doctor_build import minimal_package
    from scripts.windows_doctor_build import package_inventory, PackageError
    root=minimal_package(tmp_path)
    policy=root/'_internal/performance-compatibility.json'
    (root/'RELEASE.json').write_text(json.dumps({'packaging_version':'1.0.21'}))
    package_inventory(root)
    policy.unlink()
    with pytest.raises(PackageError,match='software allowlist'):
        package_inventory(root)
    (root/'RELEASE.json').write_text(json.dumps({'packaging_version':'1.0.20'}))
    package_inventory(root)
