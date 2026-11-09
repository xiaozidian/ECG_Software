"""Pure three-role migration preparation contracts; never native execution."""
import base64
import copy
import json
from pathlib import Path
import zipfile

import pytest

from scripts import prepare_windows17_migration_continuation as migration


def metadata():
    n = migration.native
    run = dict(id=migration.CURRENT_RUN, head_sha=migration.CURRENT_HEAD, path=n.ACCEPTANCE_WORKFLOW,
               status='completed', conclusion='failure', run_attempt=1, repository={'full_name': n.REPO}, head_repository={'full_name': n.REPO})
    steps = [dict(number=i, name=migration.STEPS.get(i, 'fixture-step-' + str(i)), status='completed',
                  conclusion='failure' if i == 15 else 'skipped' if i >= 16 else 'success',
                  started_at='2026-11-09T18:00:00Z', completed_at='2026-11-09T18:00:02Z') for i in range(1, 21)]
    jobs = dict(total_count=1, jobs=[dict(id=migration.CURRENT_JOB, run_id=migration.CURRENT_RUN, head_sha=migration.CURRENT_HEAD,
                run_attempt=1, name=n.PRODUCER_JOB_NAME, status='completed', conclusion='failure', steps=steps)])
    a = migration.QA_ARTIFACT
    artifact = dict(id=a['id'], name=a['name'], digest='sha256:' + a['sha256'], size_in_bytes=a['bytes'], expired=False,
                    workflow_run=dict(id=migration.CURRENT_RUN, head_sha=migration.CURRENT_HEAD))
    return run, jobs, dict(total_count=1, artifacts=[artifact])


def test_three_roles_preserve_actual_prior_passes_and_overall_failure():
    proof = migration.validate_metadata(*metadata())
    assert proof['overall_conclusion'] == 'failure'
    assert [s['number'] for s in proof['actual_passed_steps12_to14']] == [12, 13, 14]
    assert proof['original_failed_step15']['conclusion'] == 'failure'
    assert proof['original_M01_parity_step16']['conclusion'] == 'skipped'


@pytest.mark.parametrize('fault', ['head', 'workflow', 'overall_success', 'unfinished', 'job_id', 'step12_failed', 'step14_skipped',
                                  'second_failure', 'old_parity_promoted', 'artifact_sha', 'artifact_size', 'artifact_expired'])
def test_current_native_provenance_and_actual_step_conclusions_are_strict(fault):
    run, jobs, artifacts = metadata()
    if fault == 'head': run['head_sha'] = '0' * 40
    elif fault == 'workflow': run['path'] = migration.WORKFLOW
    elif fault == 'overall_success': run['conclusion'] = 'success'
    elif fault == 'unfinished': run['status'] = 'in_progress'
    elif fault == 'job_id': jobs['jobs'][0]['id'] += 1
    elif fault == 'step12_failed': jobs['jobs'][0]['steps'][11]['conclusion'] = 'failure'
    elif fault == 'step14_skipped': jobs['jobs'][0]['steps'][13]['conclusion'] = 'skipped'
    elif fault == 'second_failure': jobs['jobs'][0]['steps'][15]['conclusion'] = 'failure'
    elif fault == 'old_parity_promoted': jobs['jobs'][0]['steps'][15]['conclusion'] = 'success'
    elif fault == 'artifact_sha': artifacts['artifacts'][0]['digest'] = 'sha256:' + '0' * 64
    elif fault == 'artifact_size': artifacts['artifacts'][0]['size_in_bytes'] += 1
    elif fault == 'artifact_expired': artifacts['artifacts'][0]['expired'] = True
    with pytest.raises(ValueError): migration.validate_metadata(run, jobs, artifacts)


def test_migration_workflow_requires_explicit_allowlist_opt_in():
    n = migration.native
    row = dict(id=999, head_sha='a' * 40, path=migration.WORKFLOW, status='in_progress', conclusion=None,
               repository={'full_name': n.REPO}, head_repository={'full_name': n.REPO})
    with pytest.raises(ValueError): n.validate_acceptance(row, 'a' * 40, 999)
    assert n.validate_acceptance(row, 'a' * 40, 999, migration.WORKFLOW)['workflow'] == migration.WORKFLOW
    with pytest.raises(ValueError): n.validate_acceptance(row, 'a' * 40, 999, 'unregistered-workflow.yml')


@pytest.fixture
def qa(tmp_path, monkeypatch):
    n = migration.native
    base = dict(patient_inputs_read=False, clinical_validation=False, pdf_operations=0,
        package_identity=dict(source_commit=n.SOURCE_COMPILE_COMMIT, new_exe_sha256=n.ORIGINAL_EXE_SHA, packaging_version=n.VERSION,
            application_version=n.APP, production_source_identity=dict(source_sha256=n.PRODUCTION_SHA), shared_source_fingerprint=n.COMMON_SHA,
            packaged_UI_files=81), acceptance_provenance=dict(source_compile_commit=n.SOURCE_COMPILE_COMMIT, producer_run_id=n.PRODUCER,
            controller_commit=migration.CURRENT_HEAD, acceptance_run_id=migration.CURRENT_RUN,
            original_PE_recompiled=False, original_delivery_ZIPs_repacked=False),
        new_archive_sha256=n.ORIGINAL_INNERS['p01']['sha256'], embedded_new_runtime=dict(runtime_python_files_verified=40,
            runtime_python_sha256=migration.runtime_hashes(), includes_new_ST_record_module=True))
    fresh = copy.deepcopy(base)
    fresh.update(status='passed', mode='actual-fresh17-comprehensive-STT-and-AF-multistrip-doctor-flow', checks=['fixture-' + str(i) for i in range(22)],
        primary_checks=22, ui=dict(status='passed', primary_checks=10), af_multistrip_ui=dict(status='passed', primary_checks=10),
        native_frozen_runtime=True, source_hashes_unchanged=True, bundled_python_proved=True, page_errors=[], blocked_requests=[], cleanup_errors=[])
    failed = copy.deepcopy(base)
    failed.update(status='failed', mode='actual15-to17-upgrade', checks=[], error=migration.ERROR)
    failed['package_identity']['base_exe_sha256'] = n.OLD_EXE_SHA
    browser = dict(status='passed', checks=[dict(status='passed') for _ in range(41)], platform=dict(system='Windows'),
        scope=dict(native_frozen_runtime=True, mathematical_source_only=True, clinical_validation=False),
        runtime=dict(frozen_executable=True, pe_machine='AMD64', process_images_match_frozen_exe=True),
        browser=dict(installed_system_browser=True), performance=dict(repeats=3, rounds=[{}, {}, {}]),
        network=dict(page_errors=[], http_errors=[], resource_failures=[], external_requests=0))
    p01 = dict(status='passed', checks=[dict(status='passed') for _ in range(8)], patient_inputs_read=False,
               clinical_validation=False, pdf_operations=0, kind='mathematical_deidentified_fixture')
    rows = dict(zip(['browser-validation.json', 'p01-native.json', 'comprehensive-native.json', 'upgrade15-to17-native.json'],
                    [browser, p01, fresh, failed]))
    for name, value in rows.items(): n.dump(tmp_path / name, value)
    monkeypatch.setattr(migration, 'RECEIPT_SHA', {name: n.digest(tmp_path / name) for name in rows})
    return tmp_path


def test_pinned_prior_receipts_keep_the_failed_oldloader_separate(qa):
    proof = migration.validate_receipts(qa)
    assert proof['actual_passed'] == dict(full_software=41, P01=8, fresh_STT_AF=22)
    assert proof['original_failed15']['status'] == 'failed' and proof['original_failed15']['error'] == migration.ERROR
    assert proof['migration_native_pending'] and proof['original_failure_not_promoted']


@pytest.mark.parametrize('fault', ['bytes', 'browser_failed', 'P01_check_failed', 'fresh_failed', 'wrong_compile', 'wrong_PE',
                                  'wrong_controller', 'runtime39', 'wrong_P01_ZIP', 'new_failure_promoted', 'wrong_old_error', 'old_process_started'])
def test_prior_native_receipt_semantics_and_raw_hashes_cannot_be_weakened(qa, fault):
    name = 'browser-validation.json' if fault == 'browser_failed' else 'p01-native.json' if fault == 'P01_check_failed' else 'upgrade15-to17-native.json' if fault in ('new_failure_promoted', 'wrong_old_error', 'old_process_started') else 'comprehensive-native.json'
    path = qa / name
    row = migration.read(path)
    if fault == 'bytes': path.write_bytes(path.read_bytes() + b' ')
    else:
        if fault in ('browser_failed', 'fresh_failed'): row['status'] = 'failed'
        elif fault == 'P01_check_failed': row['checks'][0]['status'] = 'failed'
        elif fault == 'wrong_compile': row['package_identity']['source_commit'] = migration.CURRENT_HEAD
        elif fault == 'wrong_PE': row['package_identity']['new_exe_sha256'] = '0' * 64
        elif fault == 'wrong_controller': row['acceptance_provenance']['controller_commit'] = '0' * 40
        elif fault == 'runtime39': row['embedded_new_runtime']['runtime_python_files_verified'] = 39
        elif fault == 'wrong_P01_ZIP': row['new_archive_sha256'] = '0' * 64
        elif fault == 'new_failure_promoted': row['status'] = 'passed'
        elif fault == 'wrong_old_error': row['error'] = 'different failure'
        elif fault == 'old_process_started': row['actual_processes'] = [dict(phase='old15', pid=1)]
        path.unlink(); migration.dump(path, row); migration.RECEIPT_SHA[name] = migration.digest(path)
    with pytest.raises(ValueError): migration.validate_receipts(qa)


def make_logs(qa, tmp_path, fault=None):
    _, jobs, _ = metadata()
    path = tmp_path / 'current-native-logs.zip'
    with zipfile.ZipFile(path, 'x') as archive:
        for number, (filename, marker, script) in migration.RECEIPTS.items():
            stamp = b'2026-11-09T18:00:00.5000000Z '
            name = migration.native.PRODUCER_JOB_NAME + '/' + str(number) + '_' + migration.STEPS[number] + '.txt'
            raw = stamp + b'python scripts/' + script + (b' --base-software-archive fixture15' if number == 15 else b'') + b'\n'
            raw += stamp + marker + json.dumps(migration.read(qa / filename)).encode() + b'\n'
            if number == 15: raw += stamp + migration.ERROR.encode() + b'\n' + stamp + b'##[error]Process completed with exit code 1.\n'
            if fault == 'missing15' and number == 15: continue
            if fault == 'wrong_member' and number == 15: name = 'wrong/' + name
            if fault == 'wrong_command' and number == 14: raw = raw.replace(script, b'wrong_controller.py')
            if fault == 'outside_time' and number == 15: raw = raw.replace(b'18:00:00.5000000Z', b'18:00:03.5000000Z')
            if fault == 'JSON_mismatch' and number == 15: raw = raw.replace(migration.ERROR.encode(), b'different old failure')
            archive.writestr(name, raw)
            if fault == 'multiple15' and number == 15: archive.writestr('duplicate/' + name, raw)
        if fault == 'traversal': archive.writestr('../escape', b'fixture')
    return path, jobs


def test_original_native_logs_bind_all_three_passes_and_original_failure(qa, tmp_path):
    path, jobs = make_logs(qa, tmp_path)
    proof = migration.validate_run_logs(path, jobs, qa)
    assert [proof['step_members'][str(n)]['conclusion'] for n in [12, 13, 14, 15]] == ['success'] * 3 + ['failure']
    assert all(p['original_QA_JSON_equal'] for p in proof['step_members'].values())


@pytest.mark.parametrize('fault', ['missing15', 'wrong_member', 'wrong_command', 'outside_time', 'JSON_mismatch', 'multiple15', 'traversal'])
def test_original_current_native_logs_cannot_be_substituted_or_lost(qa, tmp_path, fault):
    path, jobs = make_logs(qa, tmp_path, fault)
    with pytest.raises(ValueError): migration.validate_run_logs(path, jobs, qa)


@pytest.mark.parametrize('fault', [None, 'missing_group', 'multiple_groups'])
def test_combined_only_log_representation_keeps_the_same_strict_step_binding(qa, tmp_path, fault):
    direct, jobs = make_logs(qa, tmp_path)
    combined = b''
    with zipfile.ZipFile(direct) as source:
        for number, (_, _, script) in migration.RECEIPTS.items():
            second = (number - 12) * 10
            step = jobs['jobs'][0]['steps'][number - 1]
            step.update(started_at=f'2026-11-09T18:00:{second:02d}Z', completed_at=f'2026-11-09T18:00:{second+2:02d}Z')
            stamp = f'2026-11-09T18:00:{second:02d}.5000000Z '.encode()
            name = migration.native.PRODUCER_JOB_NAME + '/' + str(number) + '_' + migration.STEPS[number] + '.txt'
            raw = source.read(name).replace(b'2026-11-09T18:00:00.5000000Z ', stamp)
            group = stamp + b'##[group]Run python scripts/' + script + b'\n'
            if fault == 'missing_group' and number == 15: group = group.replace(b'##[group]Run ', b'group missing ')
            if fault == 'multiple_groups' and number == 15: group += group
            combined += group + raw
    path = tmp_path / 'combined-only.zip'
    with zipfile.ZipFile(path, 'x') as archive:
        archive.writestr('0_' + migration.native.PRODUCER_JOB_NAME + '.txt', combined)
        archive.writestr(migration.native.PRODUCER_JOB_NAME + '/system.txt', b'fixture-system')
    if fault:
        with pytest.raises(ValueError): migration.validate_run_logs(path, jobs, qa)
    else:
        proof = migration.validate_run_logs(path, jobs, qa)
        assert all(r['source_format'] == 'exact_original_combined_member_byte_slice' for r in proof['step_members'].values())
        assert proof['step_members']['15']['conclusion'] == 'failure'


def code_fixture(tmp_path):
    scripts = tmp_path / 'scripts'; scripts.mkdir()
    before = b'def load_old_oracles():\n    return 1\n\ndef run():\n    return 2\n'
    index = []
    for name, raw in [('verify_windows_af_multistrip_native.py', before), *[(f'locked_{i}.py', b'pass\n') for i in range(49)]]:
        (scripts / name).write_bytes(raw)
        index.append(dict(name=name, type='file', sha=migration.git_blob(raw)))
    source = dict(path='scripts/verify_windows_af_multistrip_native.py', encoding='base64', content=base64.b64encode(before).decode(), sha=migration.git_blob(before))
    return index, source


def test_only_the_old15_loader_AST_can_change_and_other_native_dependencies_stay_exact(tmp_path):
    index, source = code_fixture(tmp_path)
    path = tmp_path / 'scripts/verify_windows_af_multistrip_native.py'
    path.write_bytes(path.read_bytes().replace(b'return 1', b'return 10'))
    proof = migration.validate_code_lock(index, source, tmp_path)
    assert proof['all_other_native_controller_AST_identical'] and proof['only_allowed_changed_function'] == 'load_old_oracles'
    assert len(proof['locked_script_git_blobs']) == 49


@pytest.mark.parametrize('fault', ['new_run_logic', 'module_import', 'dependency', 'wrong_original_blob'])
def test_current_native_code_lock_rejects_nonloader_changes(tmp_path, fault):
    index, source = code_fixture(tmp_path)
    path = tmp_path / 'scripts/verify_windows_af_multistrip_native.py'
    if fault == 'new_run_logic': path.write_bytes(path.read_bytes().replace(b'return 2', b'return 20'))
    elif fault == 'module_import': path.write_bytes(b'import current_code_substitute\n' + path.read_bytes())
    elif fault == 'dependency': (tmp_path / 'scripts/locked_0.py').write_bytes(b'changed\n')
    elif fault == 'wrong_original_blob': source['sha'] = '0' * 40
    with pytest.raises(ValueError): migration.validate_code_lock(index, source, tmp_path)
