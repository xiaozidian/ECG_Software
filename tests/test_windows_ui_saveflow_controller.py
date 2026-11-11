"""Disposable controller contracts only: these are not real patient/native tests."""
import copy
from pathlib import Path
import zipfile

import pytest

from scripts import prepare_windows19_baseline as baseline
from scripts.verify_windows_ui_saveflow_native import (
    APP, BASE_APP, BASE_CORE, BASE_PE_SHA, metadata_identity, compare_api, fingerprint,
)
from scripts.verify_windows_stt_independent_upgrade import invalidated_composition


ROOT = Path(__file__).resolve().parents[1]


def identity():
    release = dict(packaging_version='1.0.19', app_version=APP, software_version=APP,
                   source_id='P01', source_data_bundled=False)
    old = dict(packaging_version='1.0.18', app_version=BASE_APP,
               source_id='P01', source_data_bundled=False)
    shared = dict(core_version=BASE_CORE, ui_version='ui-current-mathematical')
    previous = dict(core_version=BASE_CORE, ui_version='ui-original18-mathematical')
    return release, old, shared, previous


def test_same_clinical_core_and_new_actual_program_is_the_UI_upgrade_contract():
    release, old, shared, previous = identity()
    proof = metadata_identity(release, shared, old_release=old, old_shared=previous,
                              new_PE_sha256='a' * 64, old_PE_sha256=BASE_PE_SHA)
    assert proof['same_clinical_core'] and proof['packaging_version'] == '1.0.19'


@pytest.mark.parametrize('fault', ['wrong-package', 'wrong-app', 'bundled-source', 'wrong-source',
                                  'reused-binary', 'repack-only', 'internal-fixture', 'changed-core',
                                  'old-version', 'same-UI', 'wrong-old-PE', 'same-PE'])
def test_new19_controller_rejects_false_identity(fault):
    release, old, shared, previous = identity()
    current_sha, prior_sha = 'a' * 64, BASE_PE_SHA
    if fault == 'wrong-package': release['packaging_version'] = '1.0.18'
    if fault == 'wrong-app': release['app_version'] = '0.12.31-obsolete'
    if fault == 'bundled-source': release['source_data_bundled'] = True
    if fault == 'wrong-source': release['source_id'] = 'M01'
    if fault == 'reused-binary': release['binary_reused_without_rebuild'] = True
    if fault == 'repack-only': release['ui_repack_only'] = True
    if fault == 'internal-fixture': release['verification_fixture_only'] = True
    if fault == 'changed-core': shared['core_version'] = 'different-core'
    if fault == 'old-version': old['packaging_version'] = '1.0.15'
    if fault == 'same-UI': shared['ui_version'] = previous['ui_version']
    if fault == 'wrong-old-PE': prior_sha = 'f' * 64
    if fault == 'same-PE': current_sha = prior_sha
    with pytest.raises(AssertionError):
        metadata_identity(release, shared, old_release=old, old_shared=previous,
                          new_PE_sha256=current_sha, old_PE_sha256=prior_sha)


def basis(app, exe):
    engine = dict(app_version=app, artifacts=dict(app=exe))
    value = dict(schema=1, engine=engine, engine_id=fingerprint(engine), inputs={'mathematical_source': 'c' * 64})
    value['digest'] = fingerprint({k: v for k, v in value.items() if k != 'engine'})
    return value


def upgrade():
    package = dict(base_exe_sha256=BASE_PE_SHA, new_exe_sha256='a' * 64)
    old_basis, new_basis = basis(BASE_APP, BASE_PE_SHA), basis(APP, package['new_exe_sha256'])
    composition = dict(selected_events=[dict(event_id='annotation:1', basis_version='old', caption='mathematical original')],
                       category_reviews={'ST': 'old'}, diagnosis_blocks=[dict(manual=True, needs_review=False,
                       acknowledged=True, text='mathematical saved physician text')])
    evidence = dict(kind='t_low_flat', start_s=100, end_s=200,
                    measurement_protocol={'method_version': 'stt-hospital-review-v3'})
    report = dict(status='reviewed', reviewed_by='mathematical-verifier', version=4, review_revision=2,
                  current_analysis_basis=old_basis, composition=composition,
                  analysis_provenance={'basis': old_basis, 'signature': 'retained'}, conclusion='retained mathematical prose')
    before = dict(report=report, beat_editor={'revision': 0}, annotations={'items': [dict(id=1, details=evidence)]},
                  events={'items': [dict(event_id='annotation:1', category='ST', stt_review_state='reviewed', stt_event_evidence=evidence)]},
                  stt={'analysis': {'algorithm_version': 'stt-screening-0.4.0-comprehensive-independent'}})
    after = copy.deepcopy(before)
    after['report'].update(status='draft', reviewed_by='', version=5, review_revision=3,
                           current_analysis_basis=new_basis, composition=invalidated_composition(composition))
    after['events']['items'][0]['stt_review_state'] = 'stale'
    return before, after, package


def test_same_core_upgrade_preserves_original_approval_without_resigning():
    before, after, package = upgrade()
    proof = compare_api(before, after, package)
    assert proof['historical_signature_preserved_not_resigned'] and proof['clinical_core_same']


@pytest.mark.parametrize('fault', ['source-changed', 'auto-approved', 'version-twice', 'review-revision',
                                  'conclusion-changed', 'selection-removed', 'signature-resigned',
                                  'annotation-rewritten', 'beats-edited', 'missing-record', 'promoted-record',
                                  'proof-relabelled', 'algorithm-changed'])
def test_upgrade_contract_rejects_history_or_approval_mutation(fault):
    before, after, package = upgrade()
    if fault == 'source-changed': after['report']['current_analysis_basis'] = basis(APP, 'b' * 64)
    if fault == 'auto-approved': after['report']['status'] = 'reviewed'
    if fault == 'version-twice': after['report']['version'] += 1
    if fault == 'review-revision': after['report']['review_revision'] += 1
    if fault == 'conclusion-changed': after['report']['conclusion'] = 'lost'
    if fault == 'selection-removed': after['report']['composition']['selected_events'] = []
    if fault == 'signature-resigned': after['report']['analysis_provenance']['signature'] = 'new signature'
    if fault == 'annotation-rewritten': after['annotations']['items'][0]['details']['kind'] = 'st_elevation'
    if fault == 'beats-edited': after['beat_editor']['revision'] = 1
    if fault == 'missing-record': after['events']['items'] = []
    if fault == 'promoted-record': after['events']['items'][0]['stt_review_state'] = 'reviewed'
    if fault == 'proof-relabelled': after['events']['items'][0]['stt_event_evidence']['kind'] = 'st_elevation'
    if fault == 'algorithm-changed': after['stt']['analysis']['algorithm_version'] = 'different'
    with pytest.raises(AssertionError):
        compare_api(before, after, package)


@pytest.mark.parametrize('unsafe', ['../escape', '/absolute', 'M01/../escape', 'M01/back\\slash', 'M01/C:drive'])
def test_baseline_math_archive_rejects_unsafe_paths(tmp_path, monkeypatch, unsafe):
    source = tmp_path / 'math.zip'
    with zipfile.ZipFile(source, 'w') as archive:
        for name in [unsafe, 'M01/a', 'M01/b', 'M01/c', 'M01/d']:
            # Preserve the actual invalid ZIP bytes on Windows too; ZipInfo's
            # constructor would otherwise normalize a backslash before writing.
            info = zipfile.ZipInfo('independent-fixture-placeholder')
            info.filename = info.orig_filename = name
            archive.writestr(info, b'independent mathematical path test')
    with zipfile.ZipFile(source) as archive:
        assert archive.infolist()[0].orig_filename == unsafe
    monkeypatch.setattr(baseline, 'validate_source', lambda _: None)
    with pytest.raises(AssertionError):
        baseline.extract_math(source, tmp_path / 'extract')
    assert not (tmp_path / 'escape').exists()


def test_baseline_math_archive_accepts_five_legal_members_and_validates_source(tmp_path, monkeypatch):
    source = tmp_path / 'legal-math.zip'
    names = ['M01/data/a', 'M01/DGS/b', 'M01/report_image/c', 'M01/note.txt', 'M01/source-manifest.json']
    payload = b'independent mathematical legal path test'
    with zipfile.ZipFile(source, 'w') as archive:
        for name in names:
            archive.writestr(name, payload)
    calls = []
    monkeypatch.setattr(baseline, 'validate_source', lambda root: calls.append(root))
    destination = tmp_path / 'legal-extract'
    actual = baseline.extract_math(source, destination)
    assert actual == destination / 'M01' and calls == [actual]
    assert sorted(p.relative_to(destination).as_posix() for p in destination.rglob('*') if p.is_file()) == sorted(names)
    assert all((destination / name).read_bytes() == payload for name in names)


def test_new_workflow_runs_scoped_guards_and_actual_fresh19_and_original18():
    workflow = (ROOT / '.github/workflows/windows-ui-saveflow.yml').read_text()
    for path in ('tests/test_review_write_local_sync.py', 'tests/test_af_review_write_refresh.py',
                 'tests/test_report_card_and_stt_controls.py', 'tests/test_windows_ui_saveflow_controller.py',
                 'tests/test_windows_ui_saveflow_interactions.py'):
        assert 'python -m pytest' in workflow and path in workflow
    assert 'DOCTOR_PACKAGING_VERSION: "1.0.19"' in workflow
    assert 'scripts/prepare_windows19_baseline.py' in workflow
    assert workflow.count('scripts/verify_windows_ui_saveflow_native.py') == 2
    assert '--base-software-archive' in workflow and 'upgrade18-to19-native.json' in workflow
    assert 'verification-upgrade-version "auto"' in workflow
    assert 'scripts/verify_windows_doctor_browser_ui19.py' in workflow and 'scripts/verify_windows_p01.py' in workflow
    assert 'run_windows_release_tests.py' not in workflow and 'run_windows_ui_tests.py' not in workflow
    assert '  push:' not in workflow and '  workflow_dispatch:' in workflow
    assert baseline.RUN == 42936491344 and baseline.HEAD == 'f559f7ee07ef79fb6f3e69f737618b41032e7f36'
    assert baseline.ARTIFACTS['p01']['inner_sha256'] == '74467c07be74df009664008870f104c26838ef29c86406826edf4bc7b109af60'
    assert APP == BASE_APP == '0.12.32-stt-report-buttons.20261110'
    source = (ROOT / 'scripts/verify_windows_ui_saveflow_native.py').read_text()
    assert 'from scripts.verify_ui_saveflow_ui import verify as saveflow' in source
    assert "result['UI_saveflow'] = await saveflow(page, doctor_source.CASE_ID" in source
    assert "result['legacy_UI'] = await verify_legacy(page, doctor_source.CASE_ID" in source


def test_native_wrapper_has_no_patient_or_PDF_scope_and_actual_runtime_guards():
    source = (ROOT / 'scripts/verify_windows_ui_saveflow_native.py').read_text()
    for text in ("os.name == 'nt'", "pe_is_x64(exe)", 'embedded_modules(exe, ROOT)',
                 "process_modules, state1['pid'], exe", "channel='msedge'", 'cleanup_owned(',
                 'pdf_operations=0', 'physical_hospital_Windows10_verified=False'):
        assert text in source
    assert 'load_old_oracles(' not in source and 'monkeypatch' not in source


def test_ui19_browser_driver_keeps_all_legacy_protections_and_selects_explicit_AF_adapter():
    old = (ROOT / 'scripts/verify_windows_doctor_browser.py').read_text()
    new = (ROOT / 'scripts/verify_windows_doctor_browser_ui19.py').read_text()
    original = 'from verify_windows_af_editor import verify_af_editor'
    adapted = 'from verify_windows_af_editor_ui19 import verify_af_editor'
    assert old.count(original) == new.count(adapted) == 1
    assert new.replace(adapted, original) == old
    workflow = (ROOT / '.github/workflows/windows-ui-saveflow.yml').read_text()
    assert 'tests/test_windows_af_editor_ui19.py' in workflow
    assert 'scripts/verify_windows_doctor_browser_ui19.py' in workflow
