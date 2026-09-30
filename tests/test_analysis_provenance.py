"""Synthetic-only mutation tests: never replace or edit patient source files."""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import create_app
from ecg_core.analysis_provenance import AnalysisRuntime, digest
from ecg_core.ebi import HEADER_SIZE, RECORD, load_records, _record_sample_indexes
from ecg_core.repository import CaseRepository
from ecg_core.review_workflow import ReportConflict
from ecg_core.source_identity import file_evidence, file_signature, SourceUnavailable
from ecg_core.storage import Storage


@pytest.fixture
def synthetic_case(tmp_path):
    root = tmp_path / 'synthetic'
    case_id = '9999999999999999'
    folder = root / case_id
    paths = {'data': folder / 'data' / f'{case_id}.DATA',
             'ebi': folder / 'DGS' / f'{case_id}.EBI',
             'lps': folder / 'report_image' / f'{case_id}_1.LPS'}
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    paths['data'].write_bytes(bytes(90 * 200 * 8 * 2))
    paths['ebi'].write_bytes(bytes(HEADER_SIZE) + b''.join(
        RECORD.pack(i * 200, 1, 1, 0, 0, 0, 1000) for i in range(1, 90)))
    paths['lps'].write_text('<root><PShape>记录时间:2026-01-01 08:00:00</PShape>'
                            '<PShape>总心搏数:89</PShape></root>', encoding='utf-8')
    return root, case_id, paths


@pytest.fixture
def synthetic_app(synthetic_case, tmp_path):
    return create_app(data_root=synthetic_case[0], db_path=tmp_path / 'case.db', testing=True)


def replace_preserving_mtime(path, data):
    before = path.stat()
    path.write_bytes(data)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))


def make_basis(revision):
    body = {'schema': 1, 'engine_id': str(revision), 'inputs': {'data': {'sha256': 'synthetic'}}}
    return {**body, 'digest': digest(body)}


def approve(store, case_id, composition=None):
    for step in ('edit', 'stt'):
        store.complete_review(case_id, {'step': step, 'confirmed': True,
            'revision': store.get_review(case_id)['revision']}, 'test-doctor')
    saved = store.save_report(case_id, '合成病例复核结论', 'draft', 'test-doctor', composition)
    return store.save_report(case_id, saved['conclusion'], 'reviewed', 'test-doctor',
                             saved['composition'], expected_version=saved['version'])


def test_hash_uses_content_not_size_mtime_or_path(tmp_path):
    a = tmp_path / 'source'
    a.write_bytes(b'aaaa')
    before = file_evidence(a)
    signature = file_signature(a)
    replace_preserving_mtime(a, b'bbbb')
    assert file_signature(a)[2:4] == signature[2:4]
    assert file_evidence(a) != before
    b = tmp_path / 'other-name'
    b.write_bytes(b'bbbb')
    assert file_evidence(a) == file_evidence(b)
    assert set(before) == {'sha256', 'bytes'}


def test_unchanged_contents_do_not_invalidate_basis(synthetic_case):
    root, case_id, paths = synthetic_case
    runtime = AnalysisRuntime()
    repository = CaseRepository(root)
    before = runtime.basis(repository.get_case(case_id))
    replace_preserving_mtime(paths['data'], paths['data'].read_bytes())
    assert runtime.basis(repository.get_case(case_id)) == before


def test_hash_checks_replacement_during_cached_read(tmp_path, monkeypatch):
    from ecg_core import source_identity
    path = tmp_path / 'source'
    path.write_bytes(b'aaaa')
    file_evidence(path)  # Prime the hash cache.
    original = source_identity._digest
    def racing_digest(*args):
        result = original(*args)
        replace_preserving_mtime(path, b'bbbb')
        return result
    monkeypatch.setattr(source_identity, '_digest', racing_digest)
    with pytest.raises(ReportConflict, match='校验期间'):
        file_evidence(path)


def test_file_set_change_during_hashing_is_rejected(synthetic_case, monkeypatch):
    from ecg_core import analysis_provenance
    root, case_id, paths = synthetic_case
    runtime = AnalysisRuntime()
    case = CaseRepository(root).get_case(case_id)
    original = analysis_provenance.file_evidence
    def racing_evidence(path):
        result = original(path)
        if str(path) == str(paths['ebi']):
            content = paths['data'].read_bytes()
            replace_preserving_mtime(paths['data'], b'\1' + content[1:])
        return result
    monkeypatch.setattr(analysis_provenance, 'file_evidence', racing_evidence)
    with pytest.raises(ReportConflict, match='文件集'):
        runtime.basis(case)


def test_missing_input_does_not_disclose_path(synthetic_case):
    root, case_id, paths = synthetic_case
    case = CaseRepository(root).get_case(case_id)
    runtime = AnalysisRuntime()
    paths['data'].unlink()
    with pytest.raises(ReportConflict, match='缺失') as caught:
        runtime.basis(case)
    assert str(paths['data']) not in str(caught.value)


def test_frozen_entrypoint_uses_executable_archive(tmp_path, monkeypatch):
    from ecg_core import analysis_provenance
    archive = tmp_path / 'synthetic-executable'
    archive.write_bytes(b'synthetic frozen archive, not a real executable')
    monkeypatch.setattr(analysis_provenance, '__file__', str(tmp_path / 'ecg_core' / 'analysis_provenance.py'))
    monkeypatch.setattr(analysis_provenance.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(analysis_provenance.sys, 'executable', str(archive))
    runtime = AnalysisRuntime()
    assert runtime.manifest['artifacts']['app'] == sha256(archive.read_bytes()).hexdigest()
    assert len(runtime.manifest['artifacts']) == len(analysis_provenance.MODULES) + 1
    archive.write_bytes(b'a different build')
    with pytest.raises(ReportConflict, match='重启'):
        runtime.assert_current()


def test_ebi_records_and_sample_index_caches_refresh(synthetic_case):
    path = synthetic_case[2]['ebi']
    original = load_records(str(path))
    assert _record_sample_indexes(str(path))[0] == 200
    changed = bytearray(path.read_bytes())
    changed[HEADER_SIZE:HEADER_SIZE + RECORD.size] = RECORD.pack(220, 1, 3, 0, 0, 0, 1100)
    replace_preserving_mtime(path, changed)
    assert load_records(str(path))[0][0:3] == (220, 1, 3)
    assert _record_sample_indexes(str(path))[0] == 220
    assert original[0][0:3] == (200, 1, 1)


def test_repository_refreshes_metadata_and_duration(synthetic_case):
    root, case_id, paths = synthetic_case
    repository = CaseRepository(root)
    original = repository.get_case(case_id)
    replace_preserving_mtime(paths['lps'], paths['lps'].read_bytes().replace(b':89', b':88'))
    assert repository.get_case(case_id)['summary']['total_beats'] == 88
    paths['data'].write_bytes(bytes(60 * 200 * 8 * 2))
    # Duration can change only as a consistent input set; out-of-range EBI is rejected.
    paths['ebi'].write_bytes(bytes(HEADER_SIZE) + b''.join(
        RECORD.pack(i * 200, 1, 1, 0, 0, 0, 1000) for i in range(1, 60)))
    assert repository.get_case(case_id)['technical']['duration_seconds_raw'] == 60
    assert original['technical']['duration_seconds_raw'] == 90


def test_runtime_rejects_hot_source_changes_without_editing_app(tmp_path):
    source = tmp_path / 'synthetic-module.py'
    source.write_text('value = 1')
    runtime = AnalysisRuntime()
    runtime.files = {source: file_signature(source)}
    runtime.assert_current()
    replace_preserving_mtime(source, b'value = 2')
    with pytest.raises(ReportConflict, match='重启'):
        runtime.assert_current()


def test_basis_change_is_atomic_idempotent_and_preserves_doctor_work(tmp_path):
    store = Storage(tmp_path / 'basis.db')
    assert not store.sync_analysis_basis('case', make_basis(1), 'tester')
    composition = {'selected_events': [{'event_id': 'synthetic-event', 'basis_version': 'v1'}],
                   'category_reviews': {'V': 'old-review'}}
    old = approve(store, 'case', composition)
    assert old['status'] == 'reviewed'
    assert store.sync_analysis_basis('case', make_basis(2), 'tester')
    current = store.get_report('case', '')
    assert current['status'] == 'draft' and current['reviewed_by'] == ''
    assert current['conclusion'] == old['conclusion']
    assert current['composition']['selected_events'] == old['composition']['selected_events']
    assert current['composition']['category_reviews'] == {}
    assert current['version'] == old['version'] + 1
    assert current['review_revision'] == old['review_revision'] + 1
    assert store.get_review('case')['pending_steps'] == ['edit', 'stt']
    assert not store.sync_analysis_basis('case', make_basis(2), 'tester')
    assert store.get_report('case', '') == current
    assert len([x for x in store.list_audit() if x['action'] == 'analysis.basis_changed']) == 1
    # Invalidation retains the former approval basis for audit, not as current approval.
    assert current['analysis_provenance'] == old['analysis_provenance']


def test_legacy_review_is_not_grandfathered_without_evidence(tmp_path):
    store = Storage(tmp_path / 'legacy.db')
    old = approve(store, 'legacy')
    assert old['status'] == 'reviewed' and old['analysis_provenance'] == {}
    assert store.sync_analysis_basis('legacy', make_basis(1), 'tester')
    assert store.get_report('legacy', '')['status'] == 'draft'


def test_basis_invalidation_rolls_back_on_audit_failure(tmp_path, monkeypatch):
    store = Storage(tmp_path / 'rollback.db')
    store.sync_analysis_basis('case', make_basis(1), 'tester')
    old = approve(store, 'case')
    original = store._audit
    def fail_after_invalidation(*args):
        original(*args)
        raise RuntimeError('synthetic failure after invalidation')
    monkeypatch.setattr(store, '_audit', fail_after_invalidation)
    with pytest.raises(RuntimeError):
        store.sync_analysis_basis('case', make_basis(2), 'tester')
    assert store.get_report('case', '') == old
    assert store.get_analysis_basis('case') == make_basis(1)
    assert not any(x['action'] == 'analysis.basis_changed' for x in store.list_audit())


def test_readonly_neither_mutates_nor_reuses_unknown_approval(tmp_path):
    store = Storage(tmp_path / 'readonly.db')
    assert not store.sync_analysis_basis('fresh', make_basis(1), 'tester', readonly=True)
    assert store.get_analysis_basis('fresh') is None and not store.list_audit()
    old = approve(store, 'legacy')
    with pytest.raises(ReportConflict, match='只读'):
        store.sync_analysis_basis('legacy', make_basis(1), 'tester', readonly=True)
    assert store.get_report('legacy', '') == old
    store.sync_analysis_basis('case', make_basis(1), 'tester')
    with pytest.raises(ReportConflict, match='只读'):
        store.sync_analysis_basis('case', make_basis(2), 'tester', readonly=True)
    assert store.get_analysis_basis('case') == make_basis(1)


def test_save_binds_normalized_options_and_rejects_stale_or_changed_source(tmp_path):
    store = Storage(tmp_path / 'save.db')
    basis = make_basis(1)
    store.sync_analysis_basis('case', basis, 'tester')
    old = store.save_report('case', 'draft', 'draft', 'tester', expected_analysis_basis=basis['digest'])
    assert old['analysis_provenance']['composition_sha256'] == digest(store.get_report('case', '')['composition'])
    with pytest.raises(ReportConflict, match='计算依据'):
        store.save_report('case', 'stale', 'draft', 'tester', expected_analysis_basis='stale')
    def changed_source():
        raise ReportConflict('source changed during validation')
    with pytest.raises(ReportConflict):
        store.save_report('case', 'changed', 'draft', 'tester', check_source=changed_source)
    assert store.get_report('case', '') == old


@pytest.mark.parametrize('source', ['engine', 'data', 'ebi', 'lps'])
def test_case_access_invalidates_previous_approval(synthetic_app, synthetic_case, source):
    _, case_id, paths = synthetic_case
    client = synthetic_app.test_client()
    base = '/api/cases/' + case_id
    assert client.get(base + '/report').status_code == 200
    store = synthetic_app.extensions['storage']
    old = approve(store, case_id)
    if source == 'engine':
        synthetic_app.extensions['analysis_runtime'].engine_id = 'synthetic-new-build'
    else:
        content = paths[source].read_bytes()
        if source == 'lps':
            content = content.replace(b':89', b':88')
        elif source == 'ebi':
            content = b'x' + content[1:]  # Header change; no malformed signal data.
        else:
            content = b'\1' + content[1:]
        replace_preserving_mtime(paths[source], content)
    current = client.get(base + '/report').json
    assert current['status'] == 'draft' and current['version'] == old['version'] + 1
    assert current['conclusion'] == old['conclusion']
    assert current['current_analysis_basis']['digest'] != old['analysis_provenance']['basis']['digest']
    assert client.get(base + '/report.pdf', query_string={'expected_version': old['version']}).status_code == 409


@pytest.mark.parametrize('endpoint,action', [('report.pdf', 'report.export_pdf'), ('hrv-report.pdf', 'hrv.export_pdf')])
def test_exports_bind_exact_bytes_and_basis(synthetic_app, synthetic_case, monkeypatch, endpoint, action):
    case_id = synthetic_case[1]
    client = synthetic_app.test_client()
    base = '/api/cases/' + case_id
    monkeypatch.setattr('app.build_report_pdf', lambda *args: BytesIO(b'%PDF-synthetic-exact-bytes'))
    report = client.get(base + '/report').json
    manifest = report['current_analysis_basis']
    assert set(manifest['inputs']) == {'data', 'ebi', 'lps'}
    assert not any(str(path) in json.dumps(manifest) for path in synthetic_case[2].values())
    response = client.get(base + '/' + endpoint)
    assert response.status_code == 200, response.json
    assert response.headers['X-Report-SHA256'] == sha256(response.data).hexdigest()
    assert response.headers['X-Analysis-Basis'] == manifest['digest']
    audit = next(x for x in synthetic_app.extensions['storage'].list_audit() if x['action'] == action)
    assert response.headers['X-Report-SHA256'] in audit['detail']


@pytest.mark.parametrize('endpoint,action', [('report.pdf', 'report.export_pdf'), ('hrv-report.pdf', 'hrv.export_pdf')])
def test_source_change_during_export_never_returns_mixed_pdf(synthetic_app, synthetic_case, monkeypatch, endpoint, action):
    path = synthetic_case[2]['data']
    def racing_pdf(*args):
        content = path.read_bytes()
        replace_preserving_mtime(path, b'\1' + content[1:])
        return BytesIO(b'%PDF-mixed-source')
    monkeypatch.setattr('app.build_report_pdf', racing_pdf)
    response = synthetic_app.test_client().get('/api/cases/' + synthetic_case[1] + '/' + endpoint)
    assert response.status_code == 409 and not response.data.startswith(b'%PDF')
    assert not any(x['action'] == action for x in synthetic_app.extensions['storage'].list_audit())


def test_hrv_render_failure_does_not_log_success(synthetic_app, synthetic_case, monkeypatch):
    def failed_pdf(*args):
        raise ValueError('synthetic render failure')
    monkeypatch.setattr('app.build_report_pdf', failed_pdf)
    response = synthetic_app.test_client().get('/api/cases/' + synthetic_case[1] + '/hrv-report.pdf')
    assert response.status_code == 400
    assert not any(x['action'] == 'hrv.export_pdf' for x in synthetic_app.extensions['storage'].list_audit())


def test_manual_parameters_in_provenance_and_stale_approval_blocked(synthetic_app, synthetic_case, monkeypatch):
    client = synthetic_app.test_client()
    base = '/api/cases/' + synthetic_case[1]
    old = client.get(base + '/report').json
    composition = deepcopy(old['composition'])
    composition['advanced_options'] = {'standard_leads': True, 'uv_per_unit': 2, 'calibration_note': 'synthetic calibration'}
    response = client.put(base + '/report', json={'expected_version': old['version'],
        'conclusion': 'synthetic draft', 'composition': composition})
    assert response.status_code == 200, response.json
    saved = response.json
    assert saved['analysis_provenance']['composition_sha256'] == digest(saved['composition'])
    store = synthetic_app.extensions['storage']
    approve(store, synthetic_case[1], saved['composition'])
    # Simulated legacy/corrupt provenance: do not silently export as approved.
    with store.connect() as db:
        db.execute("UPDATE report_drafts SET analysis_provenance='{}' WHERE case_id=?", (synthetic_case[1],))
    monkeypatch.setattr('app.build_report_pdf', lambda *args: pytest.fail('must not render unbound approval'))
    result = client.get(base + '/report.pdf')
    assert result.status_code == 409 and '审核依据' in result.json['error']


def simulate_nonresident(monkeypatch, path):
    from ecg_core import source_identity
    original = Path.stat
    def flagged(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        if str(self) != str(path):
            return result
        attrs = {k: getattr(result, k) for k in dir(result) if k.startswith('st_')}
        attrs['st_flags'] = attrs.get('st_flags', 0) | 0x40000000
        return SimpleNamespace(**attrs)
    monkeypatch.setattr(source_identity.sys, 'platform', 'darwin')
    monkeypatch.setattr(Path, 'stat', flagged)


@pytest.mark.parametrize('reader', ['hash', 'waveform', 'strips', 'event', 'density', 'stt', 'advanced', 'ebi'])
def test_cloud_placeholder_is_rejected_before_signal_read(synthetic_case, monkeypatch, reader):
    from ecg_core.waveform import read_waveform, read_waveform_strips, read_event_waveform
    from ecg_core.overview import density
    from ecg_core.stt import analyze_stt
    from ecg_core.advanced_analysis import analyze
    path = synthetic_case[2]['ebi' if reader == 'ebi' else 'data']
    simulate_nonresident(monkeypatch, path)
    actions = {
        'hash': lambda: file_evidence(path),
        'waveform': lambda: read_waveform(path, 0, 5),
        'strips': lambda: read_waveform_strips(path, [400]),
        'event': lambda: read_event_waveform(path, 0, 5),
        'density': lambda: density(path, [400]),
        'stt': lambda: analyze_stt(path, []),
        'advanced': lambda: analyze(path, {'rows': [], 'events': []}),
        'ebi': lambda: load_records(str(path)),
    }
    with pytest.raises(SourceUnavailable, match='下载到本地'):
        actions[reader]()


def test_unavailable_input_blocks_export_without_erasing_approval(synthetic_app, synthetic_case, monkeypatch):
    client = synthetic_app.test_client()
    base = '/api/cases/' + synthetic_case[1]
    assert client.get(base + '/report').status_code == 200
    store = synthetic_app.extensions['storage']
    old = approve(store, synthetic_case[1])
    audit_before = store.list_audit()
    simulate_nonresident(monkeypatch, synthetic_case[2]['data'])
    for endpoint in ('report', 'waveform', 'report.pdf', 'hrv-report.pdf'):
        response = client.get(base + '/' + endpoint)
        assert response.status_code == 503 and response.json['code'] == 'source_not_local'
        assert str(synthetic_case[2]['data']) not in response.json['error']
    assert store.get_report(synthetic_case[1], '') == old
    assert store.list_audit() == audit_before
