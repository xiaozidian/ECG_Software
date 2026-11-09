"""Fabricated controller contracts only: no GitHub, PE execution or native pass."""
import copy
from pathlib import Path
import shutil
import zipfile
import xml.etree.ElementTree as ET

import pytest

from scripts import prepare_windows17_native_continuation as continuation


def metadata():
    run = dict(id=continuation.PRODUCER, head_sha=continuation.SOURCE_COMPILE_COMMIT,
               path=continuation.WORKFLOW, status='completed', conclusion='failure', run_attempt=1,
               repository={'full_name': continuation.REPO}, head_repository={'full_name': continuation.REPO})
    steps = [dict(number=n, name=continuation.STEP_NAMES.get(n, 'fixture-step-' + str(n)), status='completed',
                  conclusion='failure' if n == 16 else 'skipped' if 17 <= n <= 20 else 'success') for n in range(1, 26)]
    jobs = dict(total_count=1, jobs=[dict(id=continuation.PRODUCER_JOB, run_id=continuation.PRODUCER,
                head_sha=continuation.SOURCE_COMPILE_COMMIT, run_attempt=1, status='completed', conclusion='failure', steps=steps)])
    rows = [dict(id=r['id'], name=r['name'], digest='sha256:' + r['sha256'], size_in_bytes=r['bytes'], expired=False,
                 workflow_run=dict(id=continuation.PRODUCER, head_sha=continuation.SOURCE_COMPILE_COMMIT))
            for r in continuation.ARTIFACTS.values()]
    return run, jobs, dict(total_count=len(rows), artifacts=rows)


def test_producer_failed16_is_preserved_and_scopes_are_reused_not_native_passes():
    proof = continuation.validate_producer_metadata(*metadata())
    assert proof['conclusion'] == 'failure'
    assert [s['number'] for s in proof['passed_steps10_to15']] == list(range(10, 16))
    assert proof['original_failed_step16']['conclusion'] == 'failure'
    assert all(s['conclusion'] == 'skipped' for s in proof['native_steps17_to20_originally_skipped'])


@pytest.mark.parametrize('fault', ['head', 'workflow', 'producer_success', 'job_id', 'step10_failed', 'step13_skipped',
                                  'second_failure', 'old_native_pass', 'expired', 'artifact_sha', 'artifact_size', 'artifact_head'])
def test_fixed_producer_and_actual_passed_step_contract_rejects_faults(fault):
    run, jobs, artifacts = metadata()
    steps = jobs['jobs'][0]['steps']
    row = artifacts['artifacts'][0]
    if fault == 'head': run['head_sha'] = '0' * 40
    elif fault == 'workflow': run['path'] = 'other.yml'
    elif fault == 'producer_success': run['conclusion'] = 'success'
    elif fault == 'job_id': jobs['jobs'][0]['id'] += 1
    elif fault == 'step10_failed': steps[9]['conclusion'] = 'failure'
    elif fault == 'step13_skipped': steps[12]['conclusion'] = 'skipped'
    elif fault == 'second_failure': steps[16]['conclusion'] = 'failure'
    elif fault == 'old_native_pass': steps[17]['conclusion'] = 'success'
    elif fault == 'expired': row['expired'] = True
    elif fault == 'artifact_sha': row['digest'] = 'sha256:' + '0' * 64
    elif fault == 'artifact_size': row['size_in_bytes'] += 1
    elif fault == 'artifact_head': row['workflow_run']['head_sha'] = '0' * 40
    with pytest.raises(ValueError): continuation.validate_producer_metadata(run, jobs, artifacts)


@pytest.mark.parametrize('fault', [None, 'same_run', 'same_commit', 'wrong_workflow', 'already_success', 'wrong_repository'])
def test_source_compile_and_acceptance_provenance_are_separate(fault):
    commit, run_id = 'a' * 40, 999
    run = dict(id=run_id, head_sha=commit, path=continuation.ACCEPTANCE_WORKFLOW, status='in_progress', conclusion=None,
               repository={'full_name': continuation.REPO}, head_repository={'full_name': continuation.REPO})
    if fault == 'same_run': run['id'] = run_id = continuation.PRODUCER
    elif fault == 'same_commit': run['head_sha'] = commit = continuation.SOURCE_COMPILE_COMMIT
    elif fault == 'wrong_workflow': run['path'] = continuation.WORKFLOW
    elif fault == 'already_success': run.update(status='completed', conclusion='success')
    elif fault == 'wrong_repository': run['repository']['full_name'] = 'fixture/other'
    if fault:
        with pytest.raises(ValueError): continuation.validate_acceptance(run, commit, run_id)
    else:
        proof = continuation.validate_acceptance(run, commit, run_id)
        assert proof['source_compile_commit'] == continuation.SOURCE_COMPILE_COMMIT != proof['commit']
        assert proof['native_gates_status'] == 'pending'


def test_invalid_provenance_and_existing_attempt_do_not_reach_network(tmp_path, monkeypatch):
    def forbidden(*args): raise AssertionError('No network allowed in this test')
    monkeypatch.setattr(continuation, '_api', forbidden)
    with pytest.raises(ValueError): continuation.prepare(tmp_path / 'new', continuation.SOURCE_COMPILE_COMMIT, 999)
    assert not (tmp_path / 'new').exists()
    with pytest.raises(ValueError): continuation.prepare(tmp_path, 'a' * 40, 999)


@pytest.mark.parametrize('names', [['../escape'], ['/absolute'], ['x\\y'], ['x:stream'], ['CON.txt'], ['A', 'a'], ['a', 'a/b']])
def test_original_zip_unsafe_paths_and_duplicates_fail(tmp_path, names):
    path = tmp_path / 'unsafe.zip'
    with zipfile.ZipFile(path, 'x') as archive:
        for name in names: archive.writestr(name, b'fabricated')
    with pytest.raises(ValueError): continuation.validate_zip(path)


def test_original_zip_crc_and_byte_identity_are_readonly(tmp_path):
    path = tmp_path / 'original.zip'
    with zipfile.ZipFile(path, 'x', zipfile.ZIP_STORED) as archive: archive.writestr('a/value', b'fixture-CRC')
    original = path.read_bytes()
    proof = continuation.validate_zip(path, continuation.digest(path), len(original))
    assert proof['crc_verified'] and path.read_bytes() == original
    with pytest.raises(ValueError): continuation.validate_zip(path, '0' * 64)
    with pytest.raises(ValueError): continuation.validate_zip(path, expected_bytes=1)
    path.write_bytes(original.replace(b'fixture-CRC', b'fixture-CRX', 1))
    with pytest.raises(zipfile.BadZipFile): continuation.validate_zip(path)


def _xml(path, cases):
    suite = ET.Element('testsuite')
    for attributes, tag, details in cases:
        case = ET.SubElement(suite, 'testcase', attributes)
        if tag:
            ET.SubElement(case, tag, details).text = 'FileNotFoundError: summary.json' if tag == 'failure' else ''
    ET.ElementTree(suite).write(path, encoding='utf-8')


@pytest.fixture
def qa(tmp_path):
    def simple(count): return [({'name': 'fabricated-' + str(n), 'classname': 'tests.fixture'}, None, {}) for n in range(count)]
    _xml(tmp_path / 'doctor17-new-tests.xml', simple(106))
    core = simple(868)
    for module, count in [('test_windows_source_identity', 6), ('test_windows_request_source_lease', 10)]:
        core += [({'name': 'os-fixture-' + str(n), 'classname': 'tests.' + module}, None, {}) for n in range(count)]
    core.append(({'name': 'test_native_xattr_does_not_interrupt_unchanged_build'}, 'skipped', {'message': 'Native macOS xattr reproduction'}))
    _xml(tmp_path / 'scoped-tests.xml', core)
    _xml(tmp_path / 'ui-regressions-tests.xml', simple(833))
    _xml(tmp_path / 'historical-af.xml', [({'name': n}, 'failure', {}) for n in sorted(continuation.HISTORICAL)])
    counts = dict(total=885, passed=884, failed=0, error=0, skipped=1)
    continuation.dump(tmp_path / 'test-summary.json', dict(status='passed', current=counts, full_suite_green=False,
        historical_af=[dict(name=n, status='missing_historical_material') for n in continuation.HISTORICAL], unexplained_af_failures=[]))
    continuation.dump(tmp_path / 'ui-test-summary.json', dict(status='passed', current=dict(total=833, passed=833, failed=0, error=0, skipped=0),
                                                             declared_test_functions=289, file_count=115))
    requests = [dict(phase='warmup' if n < 4 else 'measured', request_source_leases=n % 2 == 0, wall_seconds=.5,
                     all_diagnostic_fields_equal=True, raw_leads_equal_independent_samples=True, source_handles_released_after_teardown=True,
                     hash=dict(events=[dict(content_matches=True, bytes_read=276480000)], data_calls=1 if n % 2 == 0 else 2,
                               data_bytes_read=276480000 if n % 2 == 0 else 552960000), diagnostic_sha256='d' * 64, analysis_basis='b' * 64)
                for n in range(10)]
    continuation.dump(tmp_path / 'windows-request-source-perf.json', dict(status='passed', failures=[],
        environment=dict(system='Windows', python='3.12.10'), scope=dict(existing_patient_sources_read=False, diagnostic_algorithms_modified=False),
        temporary_source_and_workspace_removed=True, requests=requests, summary=dict(fallback=dict(requests=3), request_lease=dict(requests=3)),
        thresholds=dict(each_optimized_request_seconds_strictly_below=1.0, optimized_data_hash_calls=1, optimized_data_bytes_read=276480000, measured_requests_per_mode=3)))
    continuation.dump(tmp_path / 'browser-validation.json', dict(status='failed',
        checks=[dict(status='passed') for _ in range(3)] + [dict(status='failed', name='browser-verification-completion', evidence=dict(error='AssertionError: Native ST method profile changed'))],
        network=dict(page_errors=[], http_errors=[], resource_failures=[], external_requests=0)))
    return tmp_path


def test_original_scope_counts_and_failed16_are_not_native_acceptance(qa):
    proof = continuation.validate_qa(qa)
    assert proof['historical_af_counts']['failed'] == 2
    assert proof['historical_missing_material_in_new17_passes'] is False
    assert proof['original_failed_browser16']['status'] == 'failed'
    assert [r['counts']['total'] for r in proof['junit_scopes'].values()] == [106, 885, 833]
    assert all(r['rerun_in_continuation'] is False for r in proof['junit_scopes'].values())


@pytest.mark.parametrize('fault', ['historical_green', 'core_count', 'ui_skip', 'ui_selection', 'perf_failed',
                                  'perf_threshold', 'perf_hash_calls', 'perf_equivalence', 'perf_patient', 'wrong_browser_error', 'extra_page_error'])
def test_original_qa_rejects_weakened_or_relabelled_contracts(qa, fault):
    filename = 'test-summary.json' if fault in ('historical_green', 'core_count') else 'ui-test-summary.json' if fault in ('ui_skip', 'ui_selection') else 'browser-validation.json' if fault in ('wrong_browser_error', 'extra_page_error') else 'windows-request-source-perf.json'
    path = qa / filename
    row = continuation.read(path)
    if fault == 'historical_green': row['full_suite_green'] = True
    elif fault == 'core_count': row['current']['passed'] += 1
    elif fault == 'ui_skip': row['current']['skipped'] = 1
    elif fault == 'ui_selection': row['declared_test_functions'] -= 1
    elif fault == 'perf_failed': row['status'] = 'failed'
    elif fault == 'perf_threshold': row['requests'][0]['wall_seconds'] = 1.0
    elif fault == 'perf_hash_calls': row['requests'][0]['hash']['data_calls'] = 0
    elif fault == 'perf_equivalence': row['requests'][0]['all_diagnostic_fields_equal'] = False
    elif fault == 'perf_patient': row['scope']['existing_patient_sources_read'] = True
    elif fault == 'wrong_browser_error': row['checks'][-1]['evidence']['error'] = 'different failure'
    elif fault == 'extra_page_error': row['network']['page_errors'] = ['fixture error']
    path.unlink()
    continuation.dump(path, row)
    with pytest.raises(ValueError): continuation.validate_qa(qa)


def test_internal18_updater_fixture_keeps_original17_all_other_payload_bytes(tmp_path):
    from scripts.windows_doctor_build import ASSET_FILES, create_content_manifest
    original = tmp_path / 'fabricated-original17'
    original.mkdir()
    continuation.dump(original / 'RELEASE.json', dict(source_id='M01', packaging_version='1.0.17', release_version='1.0.17',
        app_version=continuation.APP, source_commit=continuation.SOURCE_COMPILE_COMMIT))
    (original / '版本说明.txt').write_text('fabricated original17', encoding='utf-8')
    (original / 'CardioInsightDoctorEval.exe').write_bytes(b'fabricated PE bytes; never executed')
    for name in ASSET_FILES:
        target = original / '_internal' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(continuation.ROOT / name, target)
    create_content_manifest(original, with_source=False)
    before = {p.relative_to(original).as_posix(): p.read_bytes() for p in original.rglob('*') if p.is_file()}
    archive, proof = continuation.make_wrapper_fixture(original, tmp_path)
    assert proof['user_deliverable'] is proof['application_release'] is False
    assert proof['all_other_payload_and_PE_identical'] is True
    assert before == {p.relative_to(original).as_posix(): p.read_bytes() for p in original.rglob('*') if p.is_file()}
    with zipfile.ZipFile(archive) as data:
        assert data.read(continuation.PACKAGE + '/CardioInsightDoctorEval.exe') == before['CardioInsightDoctorEval.exe']
        release = continuation.loads(data.read(continuation.PACKAGE + '/RELEASE.json'))
        assert release['packaging_version'] == '1.0.18' and release['verification_fixture_only'] is True
        assert release['source_commit'] == continuation.SOURCE_COMPILE_COMMIT
