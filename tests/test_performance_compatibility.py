"""Upgrade policy and real ST evidence must both permit evidence continuity."""
import copy
import json
from types import SimpleNamespace

import pytest

from ecg_core.performance_compatibility import (
    POLICY_NAME, POLICY_SCHEMA, PerformanceCompatibility, code_fingerprints, digest,
    code_value,
)
from ecg_core.stt_compatibility import certificate_matches, make_input_binding
from test_stt_compatibility import evidence


@pytest.fixture
def continuity(evidence, tmp_path):
    e = evidence
    root = tmp_path / 'installed-build'
    root.mkdir()
    (root / 'app.py').write_text('RELEASE = "approved-performance-build"\n')
    old_engine = {**e.old['engine'], 'dependencies': {'mathematical-runtime': '1'},
                  'artifacts': {'app': 'published-parent-code'}}
    current_engine = {**copy.deepcopy(old_engine),
                      'artifacts': {'app': 'approved-performance-code'}}

    def basis(engine):
        body = dict(schema=1, engine_id=digest(engine), inputs=copy.deepcopy(e.old['inputs']))
        return {**body, 'digest': digest(body), 'engine': engine}

    previous, current = basis(old_engine), basis(current_engine)
    e.annotation['details']['review_scope']['analysis_basis'] = previous['digest']
    e.annotation['details']['stt_event_evidence']['scope']['analysis_basis'] = previous['digest']
    policy = dict(schema=POLICY_SCHEMA, parent_engine_ids=[previous['engine_id']],
                  parent_engines=[old_engine], current_code=code_fingerprints(root, ('app',)))
    runtime = SimpleNamespace(engine_id=current['engine_id'], module_names=(),
                              assert_current=lambda: None)
    report = dict(version=9, composition=dict(selected_events=[
        dict(event_id='annotation:7', basis_version=e.refs()[0])], stt_report_use=[
        dict(event_id='annotation:7', basis_version=e.refs()[0], table=True, text=True)]))
    case = dict(case_id='synthetic', paths={'data': str(e.path)})

    def service(write_policy=True):
        if write_policy:
            (root / POLICY_NAME).write_text(json.dumps(policy))
        return PerformanceCompatibility(root, runtime, None, None)

    def resolve(instance=None, annotations=None):
        return (instance or service()).resolve(
            case, previous, current, e.feed,
            [e.annotation] if annotations is None else annotations, report,
            review_revision=e.scope['analysis_revision'], beat_revision=e.scope['beat_revision'])

    return SimpleNamespace(e=e, root=root, policy=policy, runtime=runtime, previous=previous,
                           current=current, report=report, case=case,
                           service=service, resolve=resolve)


def test_complete_policy_and_remeasurement_keep_original_evidence_basis(continuity):
    c = continuity
    annotations_before = copy.deepcopy(c.e.annotation)
    report_before = copy.deepcopy(c.report)
    instance = c.service()
    assert instance.diagnostics()['code_matched']
    certificate = c.resolve(instance)
    assert certificate['reference_basis'] == c.previous
    assert certificate['execution_basis'] == c.current['digest']
    assert certificate['execution_basis'] != certificate['reference_basis']['digest']
    assert certificate['retained_stt_records'] == [7]
    assert certificate['stt_proofs'][0]['retained_basis_version'] == c.e.refs()[0]
    direct_scope = {**c.e.scope, 'analysis_basis': c.current['digest']}
    assert certificate_matches(certificate['stt_proofs'][0], c.e.annotation,
                               c.current, direct_scope, c.e.feed)
    assert c.e.annotation == annotations_before
    assert c.report == report_before
    certificate['reference_basis']['engine']['artifacts']['app'] = 'local-test-change'
    assert c.previous['engine']['artifacts']['app'] == 'published-parent-code'


@pytest.mark.parametrize('adoption', ['never_adopted', 'withdrawn'])
def test_policy_preserves_valid_review_without_report_adoption(continuity, adoption):
    c = continuity
    c.report['composition'] = dict(selected_events=[], stt_report_use=[])
    certificate = c.resolve()
    assert certificate['retained_stt_records'] == [7], adoption
    assert certificate['stt_proofs'][0]['beat_identity_evidence'] == (
        'authoritative_revision_and_verified_implementation')
    assert c.report['composition'] == dict(selected_events=[], stt_report_use=[])


def test_valid_unadopted_record_uses_server_beat_binding_when_available(continuity):
    c = continuity
    c.report['composition'] = dict(selected_events=[], stt_report_use=[])
    c.e.annotation['details']['stt_input_binding'] = make_input_binding(
        c.e.feed, c.e.annotation['details']['review_scope'], c.previous)
    certificate = c.resolve()
    assert certificate['stt_proofs'][0]['beat_identity_evidence'] == 'server_input_binding'


def test_preexisting_stale_and_unreviewed_records_never_become_reviewed(continuity):
    c = continuity
    stale = copy.deepcopy(c.e.annotation)
    stale['id'] = 8
    stale['details']['review_scope']['analysis_basis'] = 'already-stale-before-upgrade'
    unreviewed = copy.deepcopy(c.e.annotation)
    unreviewed['id'] = 9
    unreviewed['details']['reviewed'] = False
    unreviewed['details']['status'] = 'pending'
    af = dict(id=10, case_id='synthetic', sample_index=0, details=dict(kind='AF'))
    annotations = [stale, unreviewed, af, c.e.annotation]
    before = copy.deepcopy(annotations)
    certificate = c.resolve(annotations=annotations)
    assert certificate['retained_stt_records'] == [7]
    assert [p['record_id'] for p in certificate['stt_proofs']] == ['annotation:7']
    assert annotations == before


@pytest.mark.parametrize('change', [
    'missing_policy', 'unknown_schema', 'changed_current_code', 'unknown_parent_id',
    'changed_parent_manifest', 'corrupt_parent_engine_id', 'corrupt_parent_basis',
    'raw_input_contents', 'recovery_epoch', 'dependencies', 'source_contract',
])
def test_policy_source_and_build_differences_refuse_continuity(continuity, change):
    c = continuity
    if change == 'unknown_schema':
        c.policy['schema'] = 'a-different-policy'
    elif change == 'changed_current_code':
        (c.root / 'app.py').write_text('RELEASE = "different-code"\n')
    elif change == 'unknown_parent_id':
        c.policy['parent_engine_ids'] = ['unknown-release']
    elif change == 'changed_parent_manifest':
        c.policy['parent_engines'] = [{**c.previous['engine'], 'extra': 'unpublished'}]
    elif change == 'corrupt_parent_engine_id':
        c.previous['engine_id'] = 'forged-parent-engine'
    elif change == 'corrupt_parent_basis':
        c.previous['digest'] = 'forged-parent-basis'
    elif change == 'raw_input_contents':
        c.current['inputs']['data']['sha256'] = '0' * 64
    elif change == 'recovery_epoch':
        c.current['recovery_epoch'] = 'workspace-restored'
    elif change == 'dependencies':
        c.current['engine']['dependencies']['mathematical-runtime'] = '2'
    elif change == 'source_contract':
        c.current['engine']['sample_rate_hz'] = 250
    instance = c.service(write_policy=change != 'missing_policy')
    assert not instance.build_allowed(c.previous, c.current), change
    assert c.resolve(instance) is None


def test_real_stored_numeric_difference_refuses_whole_case_continuity(continuity):
    c = continuity
    metrics = c.e.annotation['details']['stt_event_evidence']['metrics']
    metrics[0]['mean_units'] += 1
    # A new receipt alone cannot make incorrect saved measurements compatible.
    for row in (c.report['composition']['selected_events'] +
                c.report['composition']['stt_report_use']):
        row['basis_version'] = c.e.refs()[0]
    instance = c.service()
    assert instance.build_allowed(c.previous, c.current)
    assert c.resolve(instance) is None


def test_actual_waveform_remeasurement_difference_refuses_continuity(continuity):
    c = continuity
    (c.e.raw * 2).astype(c.e.raw.dtype).tofile(c.e.path)
    instance = c.service()
    # Runtime supplies source hashes; the numerical comparison is a second guard.
    assert instance.build_allowed(c.previous, c.current)
    assert c.resolve(instance) is None


def test_same_revision_changed_beats_cannot_override_persisted_report_identity(continuity):
    c = continuity
    c.e.feed.beats[10]['class_code'] = 'V'
    instance = c.service()
    assert instance.build_allowed(c.previous, c.current)
    assert c.resolve(instance) is None


def test_same_revision_changed_beats_refused_for_unadopted_server_binding(continuity):
    c = continuity
    c.report['composition'] = dict(selected_events=[], stt_report_use=[])
    c.e.annotation['details']['stt_input_binding'] = make_input_binding(
        c.e.feed, c.e.annotation['details']['review_scope'], c.previous)
    c.e.feed.beats[10]['sample_index'] += 1
    assert c.resolve() is None


def test_beat_revision_change_does_not_revive_previously_stale_review(continuity):
    c = continuity
    c.e.scope['beat_revision'] += 1
    certificate = c.resolve()
    assert certificate['retained_stt_records'] == []
    assert certificate['stt_proofs'] == []
    assert c.e.annotation['details']['review_scope']['beat_revision'] == 2


def test_code_identity_ignores_only_installation_path_and_debug_line_positions():
    code = 'def calculation(value):\n    return value + 1\n'
    original = compile(code, '/old/install/app.py', 'exec')
    moved = compile('\n\n# debug-line-only change\n' + code, '/new/install/app.py', 'exec')
    assert code_value(original) == code_value(moved)


def test_code_identity_refuses_actual_instructions_or_constants_changes():
    original = compile('def calculation(value):\n    return value + 1\n', 'app', 'exec')
    changed_constant = compile('def calculation(value):\n    return value + 2\n', 'app', 'exec')
    changed_operation = compile('def calculation(value):\n    return value - 1\n', 'app', 'exec')
    assert code_value(original) != code_value(changed_constant)
    assert code_value(original) != code_value(changed_operation)


@pytest.mark.parametrize('policy_name', [POLICY_NAME, 'performance-parent-engines.json'])
def test_policy_hot_change_remains_blocked_by_executing_runtime(tmp_path, monkeypatch, policy_name):
    from ecg_core import analysis_provenance as provenance
    from ecg_core.review_workflow import ReportConflict

    module = tmp_path / 'ecg_core' / 'analysis_provenance.py'
    module.parent.mkdir()
    module.write_text('# mathematical installation path only\n')
    (tmp_path / 'app.py').write_text('RELEASE = "fixed-code"\n')
    policy = tmp_path / policy_name
    policy.write_text('{"fixed": true}\n')
    monkeypatch.setattr(provenance, '__file__', str(module))
    monkeypatch.setattr(provenance, 'MODULES', ())
    runtime = provenance.AnalysisRuntime()
    runtime.assert_current()
    original_engine = runtime.engine_id
    policy.write_text('{"fixed": false}\n')
    with pytest.raises(ReportConflict):
        runtime.assert_current()
    assert runtime.engine_id == original_engine

