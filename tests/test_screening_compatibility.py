"""A real screening change retains only exactly proved authored evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from ecg_core.analysis_provenance import MODULES
from ecg_core.performance_compatibility import code_fingerprints, digest, PerformanceCompatibility
from ecg_core.screening_compatibility import (
    POLICY_NAME, POLICY_SCHEMA, CONTINUITY_KIND, LEGACY_SOURCE_SHA256,
    LEGACY_SCREENING_VERSION, REFINED_SCREENING_VERSION, ScreeningCompatibility,
    measurement_contract, measurement_projection,
)
from ecg_core.report_sections import screening_presentation
from ecg_core.review_workflow import ReportConflict
from ecg_core.stt_compatibility import evaluate_record, certificate_matches, make_input_binding
from test_stt_compatibility import evidence

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('screening_policy_builder', ROOT/'scripts/build_screening_policy.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


@pytest.fixture
def source(tmp_path):
    root = tmp_path/'screening-build'
    shutil.copytree(ROOT/'ecg_core', root/'ecg_core', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(ROOT/'app.py', root/'app.py')
    return root


@pytest.fixture
def continuity(evidence, source):
    e = evidence
    engine = {**e.old['engine'], 'dependencies': {'synthetic-runtime': '1'},
              'artifacts': {'app': 'synthetic-published-parent', 'ecg_core.stt': LEGACY_SOURCE_SHA256}}
    current_engine = {**copy.deepcopy(engine), 'artifacts': {'app': 'synthetic-screening-refinement'}}
    def basis(value):
        body = dict(schema=1, engine_id=digest(value), inputs=copy.deepcopy(e.old['inputs']))
        return {**body, 'digest': digest(body), 'engine': value}
    previous, current = basis(engine), basis(current_engine)
    e.annotation['details']['review_scope']['analysis_basis'] = previous['digest']
    e.annotation['details']['stt_event_evidence']['scope']['analysis_basis'] = previous['digest']
    e.annotation['details']['stt_event_evidence']['algorithm_version'] = LEGACY_SCREENING_VERSION
    policy = builder.build(source, [engine])
    report = dict(version=9, status='reviewed', reviewed_by='synthetic-doctor', updated_at='synthetic-time',
                  conclusion='Synthetic unchanged authored report', analysis_provenance={'basis': previous},
                  composition=dict(selected_events=[dict(event_id='annotation:7', basis_version=e.refs()[0])],
                                   stt_report_use=[dict(event_id='annotation:7', basis_version=e.refs()[0], table=True)]))
    runtime = SimpleNamespace(engine_id=current['engine_id'], module_names=MODULES, assert_current=lambda:None)
    case = dict(case_id='synthetic', paths={'data': str(e.path)})
    def service(write=True):
        if write:
            (source/POLICY_NAME).write_text(json.dumps(policy))
        return ScreeningCompatibility(source, runtime, None, None)
    def resolve(instance=None, annotations=None):
        return (instance or service()).resolve(case, previous, current, e.feed,
            [e.annotation] if annotations is None else annotations, report,
            e.scope['analysis_revision'], e.scope['beat_revision'])
    return SimpleNamespace(e=e, root=source, policy=policy, runtime=runtime, previous=previous,
                           current=current, report=report, case=case, service=service, resolve=resolve)


def test_policy_is_explicit_and_measurement_identity_is_unchanged(continuity):
    c = continuity
    assert c.policy['schema'] == POLICY_SCHEMA
    assert c.policy['continuity_kind'] == CONTINUITY_KIND
    assert c.policy['screening_from'] == LEGACY_SCREENING_VERSION
    assert c.policy['screening_to'] == REFINED_SCREENING_VERSION
    assert c.policy['measurement_contract'] == measurement_contract(c.root)
    assert c.service().diagnostics()['measurement_matched']
    assert not PerformanceCompatibility(c.root, c.runtime, None, None).build_allowed(c.previous, c.current)


def test_actual_old_and_new_measurements_equal_and_authored_record_is_untouched(continuity):
    c = continuity
    annotation, report = copy.deepcopy(c.e.annotation), copy.deepcopy(c.report)
    certificate = c.resolve()
    assert certificate is not None
    assert certificate['reference_basis'] == c.previous
    assert certificate['execution_basis'] == c.current['digest']
    assert certificate['retained_stt_records'] == [7]
    assert certificate['stt_proofs'][0]['algorithm_version'] == LEGACY_SCREENING_VERSION
    transition = certificate['screening_transition']
    scope = {**c.e.scope, 'analysis_basis':c.current['digest']}
    assert certificate_matches(certificate['stt_proofs'][0], c.e.annotation,
                               c.current, scope, c.e.feed, screening_transition=transition)
    assert not certificate_matches(certificate['stt_proofs'][0], c.e.annotation,
                                   c.current, scope, c.e.feed)
    assert c.e.annotation == annotation and c.report == report
    assert certificate['signed_report_snapshot']['before_digest'] == certificate['signed_report_snapshot']['after_digest']


def test_default_record_comparison_does_not_accept_old_screening_version(continuity):
    c = continuity
    scope = {**c.e.scope, 'analysis_basis':c.current['digest']}
    checked = evaluate_record(c.e.annotation, c.previous, c.current, scope, c.e.feed, c.e.path,
                               persisted_basis_versions=c.e.refs(), implementation_compatible=True)
    assert not checked['compatible'] and checked['reason'] == 'screening_algorithm_changed'


@pytest.mark.parametrize('adoption', ['selected', 'unselected', 'withdrawn'])
def test_old_server_binding_and_report_adoption_are_preserved(continuity, adoption):
    c = continuity
    d = c.e.annotation['details']
    d['stt_input_binding'] = make_input_binding(c.e.feed, d['review_scope'], c.previous)
    d['stt_input_binding']['screening_method'] = LEGACY_SCREENING_VERSION
    if adoption != 'selected':
        c.report['composition'] = dict(selected_events=[], stt_report_use=[])
    else:
        for row in c.report['composition']['selected_events']+c.report['composition']['stt_report_use']:
            row['basis_version'] = c.e.refs()[0]
    before = copy.deepcopy(c.e.annotation), copy.deepcopy(c.report)
    certificate = c.resolve()
    assert certificate and certificate['retained_stt_records'] == [7]
    assert (c.e.annotation, c.report) == before
    if adoption != 'selected':
        assert certificate['stt_proofs'][0]['beat_identity_evidence'] == 'server_input_binding'
    c.e.feed.document['settings']['nn_min_ms'] += 1
    assert c.resolve() is None


@pytest.mark.parametrize('change', ['legacy_code','measurement_function','configuration','measurement_module','method'])
def test_builder_refuses_changed_measurement_or_frozen_baseline(source, change):
    if change == 'legacy_code':
        path = source/'ecg_core/stt_screening_legacy.py'
        path.write_bytes(path.read_bytes()+b'\n')
    elif change == 'measurement_function':
        path = source/'ecg_core/stt.py'
        text = path.read_text().replace('st_slope=(st_80-st_j)/.08', 'st_slope=(st_80-st_j)/.09')
        path.write_text(text)
    elif change == 'configuration':
        path = source/'ecg_core/stt.py'
        path.write_text(path.read_text().replace('"t_noise_multiplier": 3.0', '"t_noise_multiplier": 4.0'))
    elif change == 'measurement_module':
        path = source/'ecg_core/stt_range.py'
        path.write_bytes(path.read_bytes()+b'\n')
    else:
        path = source/'ecg_core/stt_records.py'
        path.write_text(path.read_text().replace("METHOD = 'stt-hospital-review-v3'", "METHOD = 'a-different-method'"))
    with pytest.raises(ValueError):
        measurement_contract(source, require_source=True)


@pytest.mark.parametrize('change', ['missing_policy','wrong_schema','wrong_from','wrong_to','wrong_contract',
                                  'current_code','unknown_parent','source','epoch','dependency','source_contract'])
def test_unverified_policy_or_real_input_change_refuses_continuity(continuity, change):
    c = continuity
    if change == 'wrong_schema': c.policy['schema']='performance-evidence-continuity-v1'
    elif change == 'wrong_from': c.policy['screening_from']='unknown-old-screening'
    elif change == 'wrong_to': c.policy['screening_to']='unknown-new-screening'
    elif change == 'wrong_contract': c.policy['measurement_contract']['method']='different-method'
    elif change == 'current_code': (c.root/'app.py').write_text('CHANGED_EXECUTING_CODE = True\n')
    elif change == 'unknown_parent': c.policy['parent_engine_ids']=['unknown-parent']
    elif change == 'source': c.current['inputs']['data']['sha256']='0'*64
    elif change == 'epoch': c.current['recovery_epoch']='restored-workspace'
    elif change == 'dependency': c.current['engine']['dependencies']['synthetic-runtime']='2'
    elif change == 'source_contract': c.current['engine']['sample_rate_hz']=250
    instance = c.service(write=change!='missing_policy')
    assert not instance.build_allowed(c.previous, c.current)
    assert c.resolve(instance) is None


def test_numerical_difference_refuses_whole_case_continuity(continuity, monkeypatch):
    from ecg_core import stt
    c = continuity
    original = stt.analyze_stt
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        result['quality']['coverage_pct'] += 1
        return result
    monkeypatch.setattr(stt, 'analyze_stt', changed)
    assert c.resolve() is None


def test_previously_stale_or_unreviewed_record_is_not_revived(continuity):
    c = continuity
    stale = copy.deepcopy(c.e.annotation)
    stale['id']=8
    stale['details']['review_scope']['analysis_basis']='already-stale'
    pending = copy.deepcopy(c.e.annotation)
    pending['id']=9
    pending['details']['reviewed']=False
    pending['details']['status']='pending'
    before = copy.deepcopy([stale, pending, c.e.annotation])
    checked = c.resolve(annotations=[stale, pending, c.e.annotation])
    assert checked and checked['retained_stt_records']==[7]
    assert [stale, pending, c.e.annotation] == before


def test_signed_report_freezes_candidate_dependent_label_and_new_draft_uses_current(continuity, monkeypatch):
    from ecg_core import stt, stt_screening_legacy
    c = continuity
    original = stt_screening_legacy.analyze_stt(c.e.path, c.e.feed.records, c.e.feed.duration)
    old = copy.deepcopy(original);new = copy.deepcopy(original)
    old['candidates']=[dict(id='synthetic-old-candidate')]
    new['candidates']=[]
    old['quality'].update(eligible_blocks=1, coverage_pct=100)
    new['quality']=copy.deepcopy(old['quality'])
    monkeypatch.setattr(stt_screening_legacy, 'analyze_stt', lambda *args,**kwargs:copy.deepcopy(old))
    monkeypatch.setattr(stt, 'analyze_stt', lambda *args,**kwargs:copy.deepcopy(new))
    instance = c.service();certificate=c.resolve(instance)
    assert certificate
    c.runtime.compatibility_certificate=lambda case:copy.deepcopy(certificate)
    presentation=screening_presentation(dict(analysis=new,automatic_candidates=dict(enabled=True,items=[],quality=new['quality'])))
    assert presentation['st_evaluation']['code']=='no_findings'
    frozen=instance.apply_report_presentation(c.case,c.report,presentation,c.e.feed)
    assert frozen['st_evaluation']['code']=='pending_review'
    assert frozen['st_trends']==presentation['st_trends']
    draft={**c.report,'status':'draft','version':10}
    assert instance.apply_report_presentation(c.case,draft,presentation,c.e.feed)==presentation
    newly_signed={**c.report,'version':11,'analysis_provenance':{
        **c.report['analysis_provenance'],'screening_algorithm_version':REFINED_SCREENING_VERSION}}
    assert instance.apply_report_presentation(c.case,newly_signed,presentation,c.e.feed)==presentation
    same_version_changed={**c.report,'conclusion':'unreviewed same-version edit'}
    with pytest.raises(ReportConflict):
        instance.apply_report_presentation(c.case,same_version_changed,presentation,c.e.feed)
    presentation['st_trends']['II'][0]['st_level_units']=12345
    with pytest.raises(ReportConflict):
        instance.apply_report_presentation(c.case,c.report,presentation,c.e.feed)


def test_report_freeze_refuses_same_revision_edited_beat_identity(continuity):
    c = continuity;instance=c.service();certificate=c.resolve(instance)
    assert certificate
    c.runtime.compatibility_certificate=lambda case:certificate
    c.e.feed.beats[4]['class_code']='V'
    with pytest.raises(ReportConflict):
        instance.apply_report_presentation(c.case,c.report,{},c.e.feed)


def test_report_newly_signed_under_refinement_is_not_relabelled_as_old_after_restart(continuity):
    c=continuity
    c.report['analysis_provenance'].update(screening_algorithm_version=REFINED_SCREENING_VERSION,
                                         execution_engine_id=c.current['engine_id'])
    before=copy.deepcopy(c.report)
    certificate=c.resolve()
    assert certificate and certificate['signed_report_snapshot'] is None
    assert c.report==before


def test_policy_hot_change_is_tracked_by_runtime(tmp_path, monkeypatch):
    from ecg_core import analysis_provenance as provenance
    module=tmp_path/'ecg_core/analysis_provenance.py';module.parent.mkdir()
    module.write_text('# synthetic runtime\n');(tmp_path/'app.py').write_text('# synthetic entry\n')
    policy=tmp_path/POLICY_NAME;policy.write_text('{"fixed": true}\n')
    monkeypatch.setattr(provenance,'__file__',str(module));monkeypatch.setattr(provenance,'MODULES',())
    runtime=provenance.AnalysisRuntime()
    policy.write_text('{"fixed": false}\n')
    with pytest.raises(ReportConflict):runtime.assert_current()
