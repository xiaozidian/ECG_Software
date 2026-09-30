"""Metadata-only changes may continue only with stable startup-identical bytes."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from hashlib import sha256
import json
import logging
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ecg_core import analysis_provenance as provenance
from ecg_core.review_workflow import ReportConflict
from ecg_core.source_identity import file_signature, SourceUnavailable
from test_analysis_provenance import synthetic_app, synthetic_case, approve


def register(runtime, source, name='ecg_core.config'):
    runtime.files[source] = file_signature(source)
    runtime.file_names[source] = name
    runtime.file_hashes[source] = sha256(source.read_bytes()).hexdigest()


def known_runtime(tmp_path):
    source = tmp_path / 'private-synthetic-source.py'
    source.write_text('value = 1\n')
    runtime = provenance.AnalysisRuntime()
    runtime.files = {}
    runtime.file_names = {}
    runtime.file_hashes = {}
    register(runtime, source)
    return runtime, source


def metadata_change(source):
    before = file_signature(source)
    source.chmod(source.stat().st_mode ^ 0o100)  # Temporary synthetic file only.
    actual = file_signature(source)
    assert before[:4] == actual[:4] and before[4] != actual[4]
    return actual


def test_metadata_only_is_verified_once_not_a_new_build(tmp_path, monkeypatch, caplog):
    runtime, source = known_runtime(tmp_path)
    original = runtime.files[source]
    identity = deepcopy(runtime.manifest), runtime.engine_id
    observed = metadata_change(source)
    evidence = provenance.file_evidence
    calls = []
    def tracked(path):
        calls.append(path)
        return evidence(path)
    monkeypatch.setattr(provenance, 'file_evidence', tracked)
    caplog.set_level(logging.INFO, logger=provenance.__name__)
    for _ in range(20):
        runtime.assert_current()
    assert calls == [source]
    assert runtime.files[source] == observed != original
    assert (runtime.manifest, runtime.engine_id) == identity
    assert 'analysis_runtime_changed ' not in caplog.text
    assert caplog.text.count('analysis_runtime_metadata_verified ') == 1
    assert str(source) not in caplog.text and source.name not in caplog.text
    metadata_change(source)
    runtime.assert_current()
    assert calls == [source, source]


@pytest.mark.skipif(sys.platform != 'darwin', reason='Native macOS xattr reproduction')
def test_native_xattr_does_not_interrupt_unchanged_build(tmp_path):
    runtime, source = known_runtime(tmp_path)
    before = runtime.files[source]
    subprocess.run(['/usr/bin/xattr', '-w', 'com.cardioinsight.runtime-probe',
                    'synthetic', str(source)], check=True)
    assert file_signature(source)[:4] == before[:4]
    assert file_signature(source)[4] != before[4]
    runtime.assert_current()
    assert runtime.files[source] == file_signature(source)


def test_concurrent_checks_share_one_verification(tmp_path, monkeypatch):
    runtime, source = known_runtime(tmp_path)
    metadata_change(source)
    evidence = provenance.file_evidence
    calls = []
    def tracked(path):
        calls.append(path)
        return evidence(path)
    monkeypatch.setattr(provenance, 'file_evidence', tracked)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: runtime.assert_current(), range(80)))
    assert calls == [source]


def test_real_change_with_restored_mtime_is_rejected_even_after_reversion(tmp_path):
    runtime, source = known_runtime(tmp_path)
    baseline = runtime.files[source]
    source.write_text('value = 2\n')
    os.utime(source, ns=(source.stat().st_atime_ns, baseline[3]))
    assert file_signature(source)[:4] == baseline[:4]
    with pytest.raises(ReportConflict, match='重启'):
        runtime.assert_current()
    assert runtime.files[source] == baseline
    source.write_text('value = 1\n')
    os.utime(source, ns=(source.stat().st_atime_ns, baseline[3]))
    with pytest.raises(ReportConflict, match='重启'):
        runtime.assert_current()
    assert runtime.files[source] == baseline


@pytest.mark.parametrize('mutation', ['mtime', 'replace', 'delete', 'size', 'unknown'])
def test_other_changes_stay_strict(tmp_path, monkeypatch, mutation):
    runtime, source = known_runtime(tmp_path)
    baseline = runtime.files[source]
    if mutation == 'mtime':
        os.utime(source, ns=(source.stat().st_atime_ns, baseline[3] + 1000000000))
    elif mutation == 'replace':
        replacement = tmp_path / 'replacement.py'
        replacement.write_bytes(source.read_bytes())
        os.utime(replacement, ns=(source.stat().st_atime_ns, baseline[3]))
        replacement.replace(source)
    elif mutation == 'delete':
        source.unlink()
    elif mutation == 'size':
        source.write_text('value = 1000\n')
    else:
        runtime.file_hashes.clear()
        metadata_change(source)
    monkeypatch.setattr(provenance, 'file_evidence', lambda _: pytest.fail('not eligible for ctime recovery'))
    with pytest.raises(ReportConflict):
        runtime.assert_current()
    assert runtime.files[source] == baseline


@pytest.mark.parametrize('fault', ['different', 'permission', 'placeholder', 'during_hash', 'after_hash'])
def test_unverified_or_racing_bytes_never_adopt_metadata(tmp_path, monkeypatch, caplog, fault):
    runtime, source = known_runtime(tmp_path)
    baseline = runtime.files[source]
    metadata_change(source)
    evidence = provenance.file_evidence
    def failed(path):
        if fault == 'permission':
            raise OSError(13, 'private filename must not be logged')
        if fault == 'placeholder':
            raise SourceUnavailable('private cloud filename')
        if fault == 'during_hash':
            raise ReportConflict('private racing filename')
        result = evidence(path)
        if fault == 'different':
            result['sha256'] = 'not-the-startup-build'
        elif fault == 'after_hash':
            metadata_change(source)
        return result
    monkeypatch.setattr(provenance, 'file_evidence', failed)
    with pytest.raises(ReportConflict, match='重启'):
        runtime.assert_current()
    assert runtime.files[source] == baseline
    assert 'private' not in caplog.text and source.name not in caplog.text


def test_one_changed_module_prevents_partial_rebase(tmp_path):
    runtime, source = known_runtime(tmp_path)
    other = tmp_path / 'second.py'
    other.write_text('b = 1')
    register(runtime, other, 'ecg_core.waveform')
    original = dict(runtime.files)
    metadata_change(source)
    other.write_text('b = 2')
    with pytest.raises(ReportConflict):
        runtime.assert_current()
    assert runtime.files == original


def test_verified_log_failure_does_not_change_content_decision(tmp_path, monkeypatch):
    runtime, source = known_runtime(tmp_path)
    observed = metadata_change(source)
    def failed(*args, **kwargs):
        raise OSError('logging unavailable')
    monkeypatch.setattr(provenance.LOGGER, 'info', failed)
    runtime.assert_current()
    assert runtime.files[source] == observed


def test_changed_build_remains_rejected_when_all_metadata_is_restored(tmp_path, monkeypatch):
    runtime, source = known_runtime(tmp_path)
    baseline = runtime.files[source]
    source.write_text('changed build')
    with pytest.raises(ReportConflict):
        runtime.assert_current()
    monkeypatch.setattr(provenance, 'file_signature', lambda _: baseline)
    with pytest.raises(ReportConflict):
        runtime.assert_current()


def test_changed_contents_are_hashed_once_and_rejection_log_is_deduplicated(tmp_path, monkeypatch, caplog):
    runtime, source = known_runtime(tmp_path)
    source.write_text('value = 2\n')
    os.utime(source, ns=(source.stat().st_atime_ns, runtime.files[source][3]))
    evidence = provenance.file_evidence
    calls = []
    def tracked(path):
        calls.append(path)
        return evidence(path)
    monkeypatch.setattr(provenance, 'file_evidence', tracked)
    def reject(_):
        with pytest.raises(ReportConflict):
            runtime.assert_current()
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(reject, range(80)))
    assert calls == [source]
    assert caplog.text.count('analysis_runtime_changed ') == 1


def test_second_module_verification_cannot_hide_first_module_race(tmp_path, monkeypatch):
    runtime, source = known_runtime(tmp_path)
    other = tmp_path / 'second.py'
    other.write_text('b = 1')
    register(runtime, other, 'ecg_core.waveform')
    baseline = dict(runtime.files)
    metadata_change(source)
    metadata_change(other)
    evidence = provenance.file_evidence
    def racing(path):
        result = evidence(path)
        if path == other:
            metadata_change(source)
        return result
    monkeypatch.setattr(provenance, 'file_evidence', racing)
    with pytest.raises(ReportConflict):
        runtime.assert_current()
    assert runtime.files == baseline


def test_benign_metadata_keeps_report_approval_and_api_outputs(synthetic_app, synthetic_case, tmp_path):
    client = synthetic_app.test_client()
    cid = synthetic_case[1]
    base = '/api/cases/' + cid
    assert client.get(base + '/report').status_code == 200
    store = synthetic_app.extensions['storage']
    saved = approve(store, cid)
    source = tmp_path / 'synthetic-module.py'
    source.write_text('value = 1')
    runtime = synthetic_app.extensions['analysis_runtime']
    register(runtime, source)
    endpoints = ['/report', '/waveform?start=1&duration=7&analysis=edited', '/beat-editor', '/report-events']
    before = [client.get(base + endpoint) for endpoint in endpoints]
    assert all(r.status_code == 200 for r in before), [(r.status_code, r.json) for r in before]
    audit = store.list_audit()
    metadata_change(source)
    after = [client.get(base + endpoint) for endpoint in endpoints]
    assert [r.status_code for r in after] == [200] * len(endpoints)
    assert [r.json for r in before] == [r.json for r in after]
    assert store.get_report(cid, '') == saved
    assert store.list_audit() == audit


def test_changed_content_blocks_report_save_and_export_after_benign_change(synthetic_app, synthetic_case, tmp_path):
    client = synthetic_app.test_client()
    cid = synthetic_case[1]
    base = '/api/cases/' + cid
    assert client.get(base + '/report').status_code == 200
    store = synthetic_app.extensions['storage']
    saved = approve(store, cid)
    runtime = synthetic_app.extensions['analysis_runtime']
    source = tmp_path / 'synthetic-module.py'
    source.write_text('value = 1')
    register(runtime, source)
    metadata_change(source)
    assert client.get(base + '/report').status_code == 200
    observed = runtime.files[source]
    source.write_text('value = 2')
    os.utime(source, ns=(source.stat().st_atime_ns, observed[3]))
    audit = store.list_audit()
    for method, route, payload in [('get', '/report.pdf', None), ('put', '/report',
            {'conclusion': 'must not save', 'expected_version': saved['version']})]:
        response = getattr(client, method)(base + route, json=payload)
        assert response.status_code == 409, response.json
        assert set(response.json) == {'code', 'error'}
        assert source.name not in json.dumps(response.json)
    assert store.get_report(cid, '') == saved
    assert store.list_audit() == audit
