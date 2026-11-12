"""A performance upgrade may preserve equal evidence, never fabricate a review."""
import copy
import hashlib
from types import SimpleNamespace

import pytest

from ecg_core.clinical_analysis import beat_basis_version
from ecg_core.stt import ALGORITHM_VERSION
from ecg_core.stt_compatibility import evaluate_record, certificate_matches
from ecg_core.stt_range import analyze_stt_range
from ecg_core.stt_records import decorate_event, protocol, RHYTHM_POLICY
from test_stt_range import synthetic


@pytest.fixture
def evidence(tmp_path):
    raw, records = synthetic(seconds=80)
    path = tmp_path/'mathematical.DATA'
    path.write_bytes(raw.tobytes())
    feed = SimpleNamespace(beats=[dict(id='s:'+str(r['sample_index']),
                                      sample_index=r['sample_index'],class_code='N') for r in records],
                           markers=[],document={'settings':{'nn_min_ms':300,'nn_max_ms':2000}},
                           records=records,duration=80)
    engine=dict(sample_rate_hz=200,channels=8,input_format='little-endian int16')
    old=dict(schema=1,digest='old-program',engine=engine,
             inputs={'data':{'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()},
                     'ebi':{'bytes':1,'sha256':hashlib.sha256(b'qrs-source').hexdigest()},'lps':{'bytes':1,'sha256':hashlib.sha256(b'metadata-source').hexdigest()}})
    new={**copy.deepcopy(old),'digest':'new-program'}
    scope=dict(case_id='synthetic',analysis_basis=new['digest'],beat_revision=2,analysis_revision=9)
    old_scope={**scope,'analysis_basis':old['digest'],'analysis_revision':8}
    measured=analyze_stt_range(path,records,start_sample=0,end_sample=12000,leads=['II'],measurement_ms=60,
                              basis=scope,source_digest='synthetic-content')
    p=protocol(dict(extent='whole'));p['range_profile']=measured['method_profile']
    child=dict(kind='st_depression',result_code='st_depression',start_s=0,end_s=60,leads=['II'],
               measurement_protocol=p,rhythm_policy=RHYTHM_POLICY,metrics=measured['leads'],
               coverage=measured['coverage'],counts=measured['counts'])
    annotation=dict(id=7,case_id='synthetic',sample_index=0,lead='II',label='工程测量复核',
                    note='医生原文保持',created_at='2026-01-01T00:00:00',details=dict(
                    kind='ST',reviewed=True,status='confirmed',result_code='st_depression',
                    review_scope=old_scope,review_leads=['II'],review_extent='whole',
                    measurement_protocol=protocol(dict(extent='whole')),end_sample=11999,
                    record_version=4,stt_event_evidence={**child,'scope':old_scope,
                    'algorithm_version':ALGORITHM_VERSION}))
    def refs(a=None):
        return [decorate_event({'event_id':'annotation:7'},a or annotation,
                               beat_basis_version(feed))['basis_version']]
    def check(**kw):
        args=dict(annotation=annotation,previous_basis=old,current_basis=new,current_scope=scope,
                  current_feed=feed,waveform_path=path,persisted_basis_versions=refs())
        args.update(kw);return evaluate_record(**args)
    return SimpleNamespace(raw=raw,path=path,records=records,feed=feed,old=old,new=new,scope=scope,
                           annotation=annotation,check=check,refs=refs)


def test_equal_measurements_preserve_authored_content_and_basis(evidence):
    e=evidence; original=copy.deepcopy(e.annotation); result=e.check()
    assert result['compatible'] and result['reason']=='exact_record_evidence_equal'
    proof=result['proof']
    assert proof['retained_basis_version']==e.refs()[0]
    assert certificate_matches(proof,e.annotation,e.new,e.scope,e.feed)
    assert e.annotation==original
    assert e.annotation['details']['review_scope']['analysis_basis']=='old-program'
    assert e.annotation['details']['record_version']==4
    assert len(proof['measurements'])==1


@pytest.mark.parametrize('change',[
    'previous_scope','beat_revision','case','source','contract','epoch','method','algorithm',
    'annotation_case','not_st','source_unavailable','finding_bounds','missing_metrics','missing_old_beat_reference','old_beat_reference','old_settings'
])
def test_real_changes_or_insufficient_evidence_never_gain_eligibility(evidence,change):
    e=evidence;a=e.annotation;kw={}
    if change=='previous_scope':e.old['digest']='a-different-old-program'
    elif change=='beat_revision':e.scope['beat_revision']+=1
    elif change=='case':e.scope['case_id']='different-case'
    elif change=='source':e.new['inputs']['data']['sha256']='changed-raw-input'
    elif change=='contract':e.new['engine']['sample_rate_hz']=250
    elif change=='epoch':e.new['recovery_epoch']='different-restored-workspace'
    elif change=='method':
        a['details']['measurement_protocol']['method_version']='a-new-measurement-method'
        kw['persisted_basis_versions']=e.refs()
    elif change=='algorithm':
        a['details']['stt_event_evidence']['algorithm_version']='a-new-screening-method'
        kw['persisted_basis_versions']=e.refs()
    elif change=='annotation_case':e.annotation['case_id']='another-recording'
    elif change=='not_st':e.annotation['details']['kind']='AF'
    elif change=='source_unavailable':
        def missing(*args,**kwargs):raise OSError('unavailable synthetic file')
        kw['range_analyzer']=missing
    elif change=='finding_bounds':
        a['details']['stt_event_evidence']['end_s']=59
        kw['persisted_basis_versions']=e.refs()
    elif change=='missing_metrics':
        a['details']['stt_event_evidence'].pop('metrics')
        kw['persisted_basis_versions']=e.refs()
    elif change=='missing_old_beat_reference':kw['persisted_basis_versions']=[]
    elif change=='old_beat_reference':kw['persisted_basis_versions']=['old-beats-stt-record-v1-mismatch']
    elif change=='old_settings':
        old=e.refs();e.feed.document['settings']['nn_min_ms']=400;kw['persisted_basis_versions']=old
    before=copy.deepcopy(a);result=e.check(**kw)
    assert not result['compatible'] and result['proof'] is None
    assert a==before


def test_current_engine_remeasurement_must_equal_stored_numeric_evidence(evidence):
    e=evidence
    def changed(*args,**kwargs):
        r=analyze_stt_range(*args,**kwargs)
        r['leads'][0]['mean_units']+=1
        return r
    r=e.check(range_analyzer=changed)
    assert not r['compatible'] and r['reason']=='remeasured_statistics_changed'


@pytest.mark.parametrize('change',['text','new_basis','new_scope','beat','method','wrong_record'])
def test_compatibility_certificate_cannot_outlive_its_exact_record_and_inputs(evidence,change):
    e=evidence;r=e.check();assert r['compatible'];proof=r['proof']
    if change=='text':e.annotation['note']='new unreviewed prose'
    elif change=='new_basis':e.new['digest']='third-program'
    elif change=='new_scope':e.scope['beat_revision']+=1
    elif change=='beat':e.feed.beats[10]['class_code']='V'
    elif change=='method':e.annotation['details']['measurement_protocol']['rhythm_policy']='mask-AF'
    elif change=='wrong_record':proof['record_id']='annotation:99'
    assert not certificate_matches(proof,e.annotation,e.new,e.scope,e.feed)


def test_prior_unreviewed_and_stale_records_are_not_promoted(evidence):
    e=evidence
    for scope,reviewed in [('old-program',False),('older-program-before-old',True)]:
        e.annotation['details']['review_scope']['analysis_basis']=scope
        e.annotation['details']['reviewed']=reviewed
        result=e.check(persisted_basis_versions=e.refs())
        assert not result['compatible']


@pytest.mark.parametrize('adoption',['never_adopted','withdrawn'])
def test_unadopted_review_preserved_only_after_verified_implementation_policy(evidence,adoption):
    e=evidence;before=copy.deepcopy(e.annotation)
    denied=e.check(persisted_basis_versions=[])
    assert not denied['compatible']
    accepted=e.check(persisted_basis_versions=[],implementation_compatible=True)
    assert accepted['compatible']
    assert accepted['proof']['beat_identity_evidence']=='authoritative_revision_and_verified_implementation'
    assert e.annotation==before
    refs=e.refs()
    e.feed.beats[4]['class_code']='V'
    rejected=e.check(persisted_basis_versions=refs,implementation_compatible=True)
    assert not rejected['compatible']


def test_legacy_policy_does_not_override_real_measurement_difference(evidence):
    e=evidence
    def changed(*args,**kwargs):
        r=analyze_stt_range(*args,**kwargs);r['counts']['used_count']+=1;return r
    rejected=e.check(persisted_basis_versions=[],implementation_compatible=True,range_analyzer=changed)
    assert not rejected['compatible'] and rejected['reason']=='remeasured_statistics_changed'


def test_new_server_input_binding_preserves_unadopted_review_and_detects_same_revision_edit(evidence):
    from ecg_core.stt_compatibility import make_input_binding
    e=evidence
    old_scope=e.annotation['details']['review_scope']
    e.annotation['details']['stt_input_binding']=make_input_binding(e.feed,old_scope,e.old)
    before=copy.deepcopy(e.annotation)
    accepted=e.check(persisted_basis_versions=[])
    assert accepted['compatible']
    assert accepted['proof']['beat_identity_evidence']=='server_input_binding'
    assert e.annotation==before
    e.feed.beats[10]['class_code']='V'
    rejected=e.check(persisted_basis_versions=[],implementation_compatible=True)
    assert not rejected['compatible'] and rejected['reason']=='stored_input_binding_changed'


def test_implementation_policy_flag_is_explicit_boolean_and_not_a_client_truthy_value(evidence):
    e=evidence
    for value in (None,False,1,'true',{'approved':True}):
        rejected=e.check(persisted_basis_versions=[],implementation_compatible=value)
        assert not rejected['compatible']


def test_new_binding_requires_the_server_saving_scope(evidence):
    from ecg_core.stt_compatibility import make_input_binding
    e=evidence
    with pytest.raises(ValueError):
        make_input_binding(e.feed,e.scope,e.old)


def test_legacy_policy_requires_complete_original_content_hashes(evidence):
    e=evidence
    for damaged in ({}, {'data':{'bytes':1,'sha256':'missing-cryptographic-hash'}}):
        e.old['inputs']=copy.deepcopy(damaged);e.new['inputs']=copy.deepcopy(damaged)
        r=e.check(persisted_basis_versions=[],implementation_compatible=True)
        assert not r['compatible'] and r['reason']=='missing_source_content_evidence'


def test_point_review_does_not_need_report_adoption_under_verified_same_method(evidence):
    e=evidence
    d=e.annotation['details']
    e.annotation['sample_index']=200
    d.update(end_sample=200,review_extent='point',
             measurement_protocol=protocol(dict(extent='point',baseline_method='manual_iso_point')),
             point_measurement=dict(window_start_s=0,window_duration_s=5,
                                    iso_sample=100,j_sample=200,measurement_sample=212,
                                    measurement_ms=60,leads=['II']))
    d.pop('stt_event_evidence')
    r=e.check(persisted_basis_versions=[],implementation_compatible=True)
    assert r['compatible'] and r['proof']['point_digest'] and r['proof']['measurements']==[]
    assert certificate_matches(r['proof'],e.annotation,e.new,e.scope,e.feed)


def test_point_geometry_change_is_not_hidden_by_same_program_policy(evidence):
    e=evidence;d=e.annotation['details'];e.annotation['sample_index']=200
    d.update(end_sample=200,review_extent='point',
             measurement_protocol=protocol(dict(extent='point',baseline_method='manual_iso_point')),
             point_measurement=dict(window_start_s=0,window_duration_s=5,
                                    iso_sample=100,j_sample=200,measurement_sample=250,
                                    measurement_ms=60,leads=['II']))
    d.pop('stt_event_evidence')
    r=e.check(persisted_basis_versions=[],implementation_compatible=True)
    assert not r['compatible'] and r['reason']=='invalid_measurement_evidence'
