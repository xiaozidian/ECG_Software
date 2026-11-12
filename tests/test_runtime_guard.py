"""Runtime-change diagnostics: synthetic artifacts only; guards remain strict."""
from concurrent.futures import ThreadPoolExecutor
import json
import logging
import os

import pytest

from ecg_core import analysis_provenance as provenance
from ecg_core.review_workflow import ReportConflict
from ecg_core.source_identity import file_signature
from test_analysis_provenance import synthetic_app, synthetic_case


def diagnostic_rows(caplog):
    return [json.loads(r.message.split(' ', 1)[1]) for r in caplog.records
            if r.name == provenance.__name__ and r.message.startswith('analysis_runtime_changed ')]


def artifact_runtime(tmp_path):
    source = tmp_path / 'private-installation-name.py'
    source.write_text('value = 1')
    runtime = provenance.AnalysisRuntime()
    runtime.files = {source: file_signature(source)}
    runtime.file_names = {source: 'ecg_core.config'}
    return runtime, source


def test_unchanged_runtime_is_quiet_and_does_not_rehash(tmp_path, monkeypatch, caplog):
    runtime, _ = artifact_runtime(tmp_path)
    monkeypatch.setattr(provenance, 'file_evidence', lambda p: pytest.fail('unchanged path must not be rehashed'))
    caplog.set_level(logging.WARNING)
    for _ in range(20):
        runtime.assert_current()
    assert diagnostic_rows(caplog) == []


@pytest.mark.parametrize('field', range(5))
def test_changed_attribute_is_identified_without_exposing_paths(tmp_path, monkeypatch, caplog, field):
    runtime, source = artifact_runtime(tmp_path)
    expected = runtime.files[source]
    actual = list(expected)
    actual[field] += 1
    monkeypatch.setattr(provenance, 'file_signature', lambda p: tuple(actual))
    with pytest.raises(ReportConflict, match='重启') as caught:
        runtime.assert_current()
    rows = diagnostic_rows(caplog)
    assert rows == [{'engine_id': runtime.engine_id, 'changes': [{
        'module': 'ecg_core.config', 'reason': 'metadata_changed',
        'fields': {provenance.SIGNATURE_FIELDS[field]: {'expected': expected[field], 'actual': actual[field]}}}]}]
    assert source.name not in caplog.text and str(source.parent) not in caplog.text
    assert runtime.engine_id not in str(caught.value)
    assert runtime.files[source] == expected  # Logging never adopts a new build.


@pytest.mark.parametrize('errno', [2, 13, 5])
def test_stat_failure_is_sanitized_and_still_rejected(tmp_path, monkeypatch, caplog, errno):
    runtime, source = artifact_runtime(tmp_path)
    def failed(path):
        raise OSError(errno, 'private diagnosis or filename must not be logged', str(source))
    monkeypatch.setattr(provenance, 'file_signature', failed)
    with pytest.raises(ReportConflict):
        runtime.assert_current()
    assert diagnostic_rows(caplog)[0]['changes'] == [
        {'module': 'ecg_core.config', 'reason': 'stat_failed', 'errno': errno}]
    assert 'private' not in caplog.text and str(source) not in caplog.text


@pytest.mark.parametrize('same_content', [True, False])
def test_real_rewrite_remains_rejected_without_rebasing(tmp_path, caplog, same_content):
    runtime, source = artifact_runtime(tmp_path)
    old = source.stat()
    source.write_text('value = 1' if same_content else 'value = 2')
    os.utime(source, ns=(old.st_atime_ns, old.st_mtime_ns + 1_000_000_000))
    with pytest.raises(ReportConflict):
        runtime.assert_current()
    assert diagnostic_rows(caplog)[0]['changes'][0]['module'] == 'ecg_core.config'
    assert 'mtime_ns' in diagnostic_rows(caplog)[0]['changes'][0]['fields']
    assert 'value' not in caplog.text


def test_concurrent_rejections_log_same_change_once_and_new_change_again(tmp_path, caplog):
    runtime, source = artifact_runtime(tmp_path)
    source.write_text('changed build, not executable')
    def reject(_):
        with pytest.raises(ReportConflict):
            runtime.assert_current()
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(reject, range(80)))
    assert len(diagnostic_rows(caplog)) == 1
    source.write_text('a different changed build, not executable')
    reject(0)
    assert len(diagnostic_rows(caplog)) == 2


def test_unknown_artifact_has_fixed_name_not_private_basename(tmp_path, caplog):
    runtime, source = artifact_runtime(tmp_path)
    runtime.file_names.clear()
    source.unlink()
    with pytest.raises(ReportConflict):
        runtime.assert_current()
    assert diagnostic_rows(caplog)[0]['changes'][0]['module'] == 'untracked-artifact'
    assert 'private' not in caplog.text


def test_logging_failure_does_not_bypass_guard_and_can_retry(tmp_path, monkeypatch, caplog):
    runtime, source = artifact_runtime(tmp_path)
    source.write_text('changed source')
    original = provenance.LOGGER.warning
    def failed(*args, **kwargs):
        raise OSError('synthetic logging destination failure')
    monkeypatch.setattr(provenance.LOGGER, 'warning', failed)
    with pytest.raises(ReportConflict, match='重启'):
        runtime.assert_current()
    assert runtime._last_change_diagnostic is None
    monkeypatch.setattr(provenance.LOGGER, 'warning', original)
    with pytest.raises(ReportConflict, match='重启'):
        runtime.assert_current()
    assert len(diagnostic_rows(caplog)) == 1


def test_api_rejections_do_not_publish_diagnostics_or_change_saved_work(
        synthetic_app, synthetic_case, tmp_path, caplog):
    app = synthetic_app
    client = app.test_client()
    case_id = synthetic_case[1]
    base = '/api/cases/' + case_id
    original = client.get(base + '/report')
    assert original.status_code == 200
    store = app.extensions['storage']
    saved = store.get_report(case_id, '')
    audit = store.list_audit()
    runtime = app.extensions['analysis_runtime']
    source = tmp_path / 'private-module.py'
    source.write_text('old build')
    runtime.files[source] = file_signature(source)
    runtime.file_names[source] = 'ecg_core.config'
    source.write_text('new build')
    for method, endpoint, payload in [
            ('get', '/report', None), ('get', '/report.pdf', None),
            ('post', '/advanced-analysis', {'options': {'duration_s': 60}}),
            ('put', '/report', {'conclusion': 'must not save', 'expected_version': saved['version']})]:
        response = getattr(client, method)(base + endpoint, json=payload)
        assert response.status_code == 409, response.json
        assert response.json['code'] == 'report_conflict'
        assert set(response.json) == {'error', 'code'}
        assert '软件文件已更新' in response.json['error']
        assert 'ecg_core' not in response.json['error']
    assert store.get_report(case_id, '') == saved
    assert store.list_audit() == audit
    assert len(diagnostic_rows(caplog)) == 1
    assert case_id not in caplog.text


def test_diagnostic_probe_keeps_sources_and_omits_patient_content(synthetic_app, synthetic_case):
    from hashlib import sha256
    from scripts.diagnose_runtime_guard import probe
    paths = synthetic_case[2]
    before = {key: sha256(path.read_bytes()).hexdigest() for key, path in paths.items()}
    handlers = list(provenance.LOGGER.handlers)
    result = probe(synthetic_app, rounds=2)
    assert result['case_count'] == 1 and result['request_count'] == 4
    assert result['status_counts'] == {'200': 2, '400': 2}
    assert result['unexpected_count'] == 0 and result['runtime_changes'] == []
    encoded = json.dumps(result)
    assert synthetic_case[1] not in encoded
    assert not any(str(p) in encoded or value in encoded for p, value in zip(paths.values(), before.values()))
    assert before == {key: sha256(path.read_bytes()).hexdigest() for key, path in paths.items()}
    assert provenance.LOGGER.handlers == handlers


def test_probe_captures_guard_failure_without_calling_it_success(synthetic_app, tmp_path):
    from scripts.diagnose_runtime_guard import probe
    runtime = synthetic_app.extensions['analysis_runtime']
    source = tmp_path / 'private-module.py'
    source.write_text('before')
    runtime.files[source] = file_signature(source)
    runtime.file_names[source] = 'ecg_core.config'
    source.write_text('after')
    result = probe(synthetic_app, rounds=2)
    assert result['status_counts'] == {'409': 4}
    assert result['unexpected_count'] == 4
    assert len(result['runtime_changes']) == 1
    assert result['runtime_changes'][0]['changes'][0]['module'] == 'ecg_core.config'


def test_failed_probe_removes_its_handler(synthetic_app, monkeypatch):
    from types import SimpleNamespace
    from scripts.diagnose_runtime_guard import probe
    handlers = list(provenance.LOGGER.handlers)
    monkeypatch.setattr(synthetic_app, 'test_client', lambda: SimpleNamespace(
        get=lambda url: SimpleNamespace(status_code=503)))
    with pytest.raises(RuntimeError, match='未执行'):
        probe(synthetic_app)
    assert provenance.LOGGER.handlers == handlers


@pytest.mark.parametrize('rounds', [0, 11, True, 1.5])
def test_probe_requires_bounded_integer_rounds(rounds):
    from scripts.diagnose_runtime_guard import probe
    with pytest.raises(ValueError, match='rounds'):
        probe(None, rounds=rounds)
