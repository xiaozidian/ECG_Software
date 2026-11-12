"""A failed producer may lend exact binaries, never a fabricated native verdict."""
import copy
import xml.etree.ElementTree as ET

import pytest

from scripts import prepare_windows21_continuation as c


@pytest.fixture
def metadata():
    run = dict(id=c.PRODUCER, head_sha=c.COMPILE_COMMIT, path=c.WORKFLOW,
               status='completed', conclusion='failure', run_attempt=1,
               repository={'full_name': c.REPO}, head_repository={'full_name': c.REPO})
    steps = [dict(number=n, name=c.STEP_NAMES.get(n, 'setup-or-upload-'+str(n)), status='completed',
                  conclusion='success' if n < 15 or n >= 20 else 'failure' if n == 15 else 'skipped')
             for n in range(1, 25)]
    jobs = dict(total_count=1, jobs=[dict(id=c.JOB, run_id=c.PRODUCER, head_sha=c.COMPILE_COMMIT,
        run_attempt=1, name=c.JOB_NAME, status='completed', conclusion='failure', steps=steps)])
    artifacts = dict(total_count=5, artifacts=[dict(id=w['id'], name=w['name'], size_in_bytes=w['bytes'],
        digest='sha256:'+w['sha256'], expired=False,
        workflow_run={'id': c.PRODUCER, 'head_sha': c.COMPILE_COMMIT}) for w in c.ARTIFACTS.values()])
    return run, jobs, artifacts


def test_exact_producer_retains_failure_and_skipped_native_scope(metadata):
    proof = c.validate_producer(*metadata)
    assert proof['conclusion'] == 'failure'
    assert len(proof['passed_steps1_to14']) == 14
    assert proof['failed_step15']['conclusion'] == 'failure'
    assert len(proof['skipped_native_steps16_to19']) == 4


@pytest.mark.parametrize('change', ['producer_head', 'producer_success', 'producer_attempt', 'different_repo',
    'job_head', 'missing_source_gate', 'different_gate_name', 'second_failure', 'native_was_not_skipped',
    'artifact_digest', 'artifact_size', 'artifact_expired', 'artifact_head', 'extra_artifact'])
def test_producer_or_artifact_differences_never_reuse_prerequisites(metadata, change):
    run, jobs, artifacts = copy.deepcopy(metadata)
    job = jobs['jobs'][0]
    if change == 'producer_head': run['head_sha'] = 'f'*40
    elif change == 'producer_success': run['conclusion'] = 'success'
    elif change == 'producer_attempt': run['run_attempt'] = 2
    elif change == 'different_repo': run['head_repository']['full_name'] = 'another/repo'
    elif change == 'job_head': job['head_sha'] = 'a'*40
    elif change == 'missing_source_gate': job['steps'][9]['conclusion'] = 'skipped'
    elif change == 'different_gate_name': job['steps'][11]['name'] = 'a smaller scope'
    elif change == 'second_failure': job['steps'][12]['conclusion'] = 'failure'
    elif change == 'native_was_not_skipped': job['steps'][15]['conclusion'] = 'success'
    elif change == 'artifact_digest': artifacts['artifacts'][0]['digest'] = 'sha256:'+'0'*64
    elif change == 'artifact_size': artifacts['artifacts'][0]['size_in_bytes'] -= 1
    elif change == 'artifact_expired': artifacts['artifacts'][0]['expired'] = True
    elif change == 'artifact_head': artifacts['artifacts'][0]['workflow_run']['head_sha'] = 'd'*40
    elif change == 'extra_artifact': artifacts['artifacts'].append(copy.deepcopy(artifacts['artifacts'][0]))
    with pytest.raises(ValueError): c.validate_producer(run, jobs, artifacts)


def acceptance():
    return dict(id=999, head_sha='b'*40, path=c.CONTINUATION, status='in_progress', conclusion=None,
                repository={'full_name': c.REPO}, head_repository={'full_name': c.REPO})


def test_validator_is_distinct_and_bound_to_actual_continuation_workflow():
    assert c.validate_acceptance(acceptance(), 'b'*40, 999)['native_gates'] == 'pending'


@pytest.mark.parametrize('field,value', [('id', c.PRODUCER), ('head_sha', c.COMPILE_COMMIT),
    ('path', c.WORKFLOW), ('status', 'completed'), ('conclusion', 'success')])
def test_validator_may_not_masquerade_as_producer_or_completed_acceptance(field, value):
    run = acceptance();run[field] = value
    with pytest.raises(ValueError): c.validate_acceptance(run, 'b'*40, 999)


@pytest.mark.parametrize('defect', ['failure', 'error', 'skipped', 'missing_case', 'wrong_summary'])
def test_junit_must_cover_every_original_case_without_failure_or_skip(tmp_path, defect):
    root = ET.Element('testsuites')
    suite = ET.SubElement(root, 'testsuite', tests='2', failures='0', errors='0', skipped='0')
    first = ET.SubElement(suite, 'testcase', name='one')
    if defect != 'missing_case': ET.SubElement(suite, 'testcase', name='two')
    if defect in ('failure', 'error', 'skipped'): ET.SubElement(first, defect)
    if defect == 'wrong_summary': suite.set('tests', '1')
    path = tmp_path/'original.xml';ET.ElementTree(root).write(path)
    with pytest.raises(ValueError): c.junit(path, 2)


def test_complete_junit_can_be_reused_only_as_original_precondition(tmp_path):
    suite = ET.Element('testsuite', tests='1', failures='0', errors='0', skipped='0')
    ET.SubElement(suite, 'testcase', name='actual_earlier_precondition')
    path = tmp_path/'original.xml';ET.ElementTree(suite).write(path)
    proof = c.junit(path, 1)
    assert proof['passed'] == 1 and proof['rerun'] is False


def test_pipeline_retains_every_native_gate_and_delivers_original_archives_only():
    text = (c.ROOT/'.github/workflows/windows-performance-continuation.yml').read_text()
    for name in ['verify_windows_doctor_browser_ui21.py', 'verify_windows_p01.py',
                 'verify_windows_performance_preserve.py', '--base-software-archive',
                 'prepare_windows21_baseline.py', '--finalize-evidence', '--repeats 3']:
        assert name in text
    assert text.count('if: success()') == 4
    assert 'ECG_EXPECTED_WINDOWS_BUILD_COMMIT=$($proof.source_compile_commit)' in text
    assert 'browser-screenshots/*.json' in text or 'doctor-native/evidence/**/*' in text
    assert 'windows_doctor_build.py `' not in text
