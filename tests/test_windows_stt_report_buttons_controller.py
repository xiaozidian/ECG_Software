"""Disposable controller contracts only: these are not real patient/native tests."""
import copy
from pathlib import Path
import zipfile

import pytest

from scripts import prepare_windows18_baseline as baseline
from scripts.verify_windows_stt_report_buttons_native import (
    APP, BASE_APP, BASE_CORE, BASE_PE_SHA, metadata_identity, compare_api, fingerprint,
)
from scripts.verify_windows_stt_independent_upgrade import invalidated_composition


ROOT = Path(__file__).resolve().parents[1]


def identity():
    release = dict(packaging_version='1.0.18', app_version=APP, software_version=APP,
                   source_id='P01', source_data_bundled=False)
    old = dict(packaging_version='1.0.17', app_version=BASE_APP,
               source_id='P01', source_data_bundled=False)
    shared = dict(core_version=BASE_CORE, ui_version='ui-current-mathematical')
    previous = dict(core_version=BASE_CORE, ui_version='ui-original17-mathematical')
    return release, old, shared, previous


def test_same_clinical_core_and_new_actual_program_is_the_UI_upgrade_contract():
    release, old, shared, previous = identity()
    proof = metadata_identity(release, shared, old_release=old, old_shared=previous,
                              new_PE_sha256='a' * 64, old_PE_sha256=BASE_PE_SHA)
    assert proof['same_clinical_core'] and proof['packaging_version'] == '1.0.18'


@pytest.mark.parametrize('fault', ['wrong-package', 'wrong-app', 'bundled-source', 'wrong-source',
                                  'reused-binary', 'repack-only', 'internal-fixture', 'changed-core',
                                  'old-version', 'same-UI', 'wrong-old-PE', 'same-PE'])
def test_new18_controller_rejects_false_identity(fault):
    release, old, shared, previous = identity()
    current_sha, prior_sha = 'a' * 64, BASE_PE_SHA
    if fault == 'wrong-package': release['packaging_version'] = '1.0.17'
    if fault == 'wrong-app': release['app_version'] = BASE_APP
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
            archive.writestr(name, b'independent mathematical path test')
    monkeypatch.setattr(baseline, 'validate_source', lambda _: None)
    with pytest.raises(AssertionError):
        baseline.extract_math(source, tmp_path / 'extract')
    assert not (tmp_path / 'escape').exists()


def test_new_workflow_executes_current_wrappers_and_real18_controllers():
    workflow = (ROOT / '.github/workflows/windows-stt-report-buttons.yml').read_text()
    for path in ('tests/test_report_preview_interactions.py', 'tests/test_stt_use_save_wait.py',
                 'tests/test_stt_membership_remount.py',
                 'tests/test_windows_stt_report_buttons_controller.py'):
        assert 'python -m pytest' in workflow and path in workflow
    assert 'DOCTOR_PACKAGING_VERSION: "1.0.18"' in workflow
    assert 'scripts/prepare_windows18_baseline.py' in workflow
    assert workflow.count('scripts/verify_windows_stt_report_buttons_native.py') == 2
    assert '--base-software-archive' in workflow
    assert 'upgrade17-to18-native.json' in workflow
    assert 'verification-upgrade-version "auto"' in workflow
    assert '*upgrade-fixture*' not in workflow
    assert baseline.ARTIFACTS['p01']['inner_sha256'] == '789833bb742b1d50341aedb2e5a122007918272d2e41164321e4a66a4d49b31a'


def test_native_wrapper_has_no_patient_or_PDF_scope_and_actual_runtime_guards():
    source = (ROOT / 'scripts/verify_windows_stt_report_buttons_native.py').read_text()
    for text in ("os.name == 'nt'", "pe_is_x64(exe)", 'embedded_modules(exe, ROOT)',
                 "process_modules, state1['pid'], exe", "channel='msedge'", 'cleanup_owned(',
                 'pdf_operations=0', 'physical_hospital_Windows10_verified=False'):
        assert text in source
    assert 'load_old_oracles(' not in source and 'monkeypatch' not in source


def test_native_buttons_cover_cancel_then_immediate_readopt_without_navigation():
    source = (ROOT / 'scripts/verify_stt_report_buttons_ui.py').read_text()
    assert "re.escape(case_id) + r'/report(?:\\?.*)?$'" in source
    reopen = source[source.index('saved_middle = next'):source.index('selected_view = await page.evaluate')]
    assert "p.get('representative_role') == 'middle'" in reopen
    assert "await category('strips')" in reopen and '[data-back-event=' in reopen
    assert 'host._afCurrentStrip?.().replaceKey===key' in reopen
    assert 'data-display-leads="12"' in reopen and 'data-display-factor="2"' in reopen
    start = source.index('selected_view = await page.evaluate')
    end = source.index("checks.append('withdraw-then-directly-readopt-same-live-graph", start)
    actual = source[start:end]
    assert "await toggle('strip', False)" in actual
    assert "selected_view['replaceKey'] == saved_middle['strip_id'] and selected_view['replaceKey']" in actual
    assert "selected_view['button'] == '保存本图' and '已入报' in selected_view['summary']" in actual
    assert "selected_view['display'] == {'mode': 12, 'gain': 2}" in actual
    assert "current_view['replaceKey'] is None" in actual
    assert "'已选 0 图' in current_view['whole']" in actual
    assert "readopted[0]['representative_role'] == selected_view['role'] == 'middle'" in actual
    assert 'async with page.expect_response' in actual and 'direct_response.status == 200' in actual
    assert 'state.reportComposition.selected_events.some(p=>p.event_id===id)' in actual
    assert actual.count("await page.locator('[data-af-include-current]').click()") == 2
    assert 'await browse(' not in actual and 'await category(' not in actual
    assert 'await picks()' in actual and "current_view['display'] == selected_view['display']" in actual
