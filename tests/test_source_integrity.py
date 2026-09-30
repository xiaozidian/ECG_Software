"""Failure injection only in synthetic temporary input files, never patient data."""
import io
import json
import subprocess
from pathlib import Path

import pytest

from test_analysis_provenance import synthetic_case, synthetic_app, approve
from ecg_core.ebi import HEADER_SIZE, RECORD, load_records
from ecg_core.lps_parser import parse_lps
from ecg_core.repository import CaseRepository
from ecg_core.source_identity import SourceInvalid, SourceReadError
from ecg_core.waveform import read_waveform, read_waveform_strips, read_event_waveform
from ecg_core.overview import density
from ecg_core.stt import analyze_stt
from ecg_core.advanced_analysis import analyze


def corrupt(paths, kind):
    if kind == 'data-empty': paths['data'].write_bytes(b'')
    elif kind == 'data-tail': paths['data'].write_bytes(bytes(3200) + b'\0')
    elif kind == 'data-truncated': paths['data'].write_bytes(bytes(3200))
    elif kind == 'ebi-header': paths['ebi'].write_bytes(bytes(8))
    elif kind == 'ebi-empty': paths['ebi'].write_bytes(bytes(HEADER_SIZE))
    elif kind == 'ebi-tail': paths['ebi'].write_bytes(bytes(HEADER_SIZE + 1))
    elif kind in ('ebi-duplicate', 'ebi-unsorted', 'ebi-outside'):
        samples = {'ebi-duplicate': [200, 200], 'ebi-unsorted': [400, 200],
                   'ebi-outside': [200, 90 * 200]}[kind]
        paths['ebi'].write_bytes(bytes(HEADER_SIZE) + b''.join(
            RECORD.pack(s, 1, 1, 0, 0, 0, 1000) for s in samples))
    elif kind == 'lps-xml': paths['lps'].write_text('<root><PShape>')
    elif kind == 'lps-empty': paths['lps'].write_text('<root/>')
    elif kind == 'lps-time': paths['lps'].write_text('<root><PShape>记录时间:未知</PShape></root>')


@pytest.mark.parametrize('kind', ['data-empty', 'data-tail', 'data-truncated',
    'ebi-header', 'ebi-empty', 'ebi-tail', 'ebi-duplicate', 'ebi-unsorted', 'ebi-outside',
    'lps-xml', 'lps-empty', 'lps-time'])
def test_damaged_input_blocks_all_report_paths_without_mutation(synthetic_app, synthetic_case, kind):
    _, cid, paths = synthetic_case
    client = synthetic_app.test_client()
    base = f'/api/cases/{cid}'
    assert client.get(base + '/report').status_code == 200
    store = synthetic_app.extensions['storage']
    saved = approve(store, cid)
    audit_before = store.list_audit()
    originals = {key: path.read_bytes() for key, path in paths.items()}
    corrupt(paths, kind)
    for endpoint in ('', '/waveform', '/report', '/report.pdf', '/hrv-report.pdf', '/hrv', '/stt-review'):
        result = client.get(base + endpoint)
        assert result.status_code == 422, (kind, endpoint, result.json)
        assert result.json['code'] == 'source_invalid'
        assert str(paths['data'].parent.parent) not in json.dumps(result.json)
        assert not result.data.startswith(b'%PDF')
    assert client.post(base + '/advanced-analysis', json={}).status_code == 422
    assert client.put(base + '/report', json={'conclusion': 'must not save'}).status_code == 422
    assert store.get_report(cid, '') == saved
    assert store.list_audit() == audit_before
    # Recovery is explicit and non-destructive; restoring identical bytes keeps evidence valid.
    for key, content in originals.items(): paths[key].write_bytes(content)
    recovered = client.get(base + '/report')
    assert recovered.status_code == 200
    assert recovered.json['status'] == saved['status']
    assert recovered.json['version'] == saved['version']


@pytest.mark.parametrize('source', ['data', 'ebi', 'lps'])
def test_missing_file_has_actionable_error_and_scan_issue(synthetic_app, synthetic_case, source):
    _, cid, paths = synthetic_case
    paths[source].unlink()
    client = synthetic_app.test_client()
    result = client.get(f'/api/cases/{cid}/report.pdf')
    assert result.status_code == 503 and result.json['code'] == 'source_unreadable'
    assert str(paths[source]) not in result.json['error']
    cases = client.get('/api/cases').json
    assert cases['items'] == [] and cases['source_issues'][0]['case_id'] == cid
    health = client.get('/api/health').json
    assert health['status'] == 'data_issues' and health['unavailable_case_count'] == 1
    assert client.get('/api/dashboard').json['source_issues'] == cases['source_issues']


@pytest.mark.parametrize('reader', ['waveform', 'strips', 'event', 'density', 'stt', 'advanced'])
@pytest.mark.parametrize('content', [b'', bytes(3201)])
def test_every_raw_reader_rejects_partial_frames(tmp_path, reader, content):
    path = tmp_path / 'broken.DATA'
    path.write_bytes(content)
    readers = {
        'waveform': lambda: read_waveform(path, 0, 1),
        'strips': lambda: read_waveform_strips(path, []),
        'event': lambda: read_event_waveform(path, 0, 1),
        'density': lambda: density(path, []),
        'stt': lambda: analyze_stt(path, []),
        'advanced': lambda: analyze(path, {'rows': [], 'events': []}),
    }
    with pytest.raises(SourceInvalid, match='完整'):
        readers[reader]()


def test_missing_source_metrics_are_not_zero(synthetic_case):
    result = parse_lps(synthetic_case[2]['lps'])
    assert result['summary']['total_beats'] == 89
    for key in ('ventricular_beats', 'supraventricular_beats', 'tachy_beats', 'brady_beats'):
        assert result['summary'][key] is None


def test_short_read_never_labels_truncated_signal_with_requested_duration(synthetic_case, monkeypatch):
    path = synthetic_case[2]['data']
    original = Path.open
    def partial(self, *args, **kwargs):
        return io.BytesIO(bytes(16)) if self == path else original(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', partial)
    with pytest.raises(SourceInvalid, match='读取不完整'):
        read_waveform(path=path, start_s=0, duration_s=7)


@pytest.mark.parametrize('source', ['data', 'ebi', 'lps'])
def test_permission_failure_is_sanitized(synthetic_case, monkeypatch, source):
    path = synthetic_case[2][source]
    original = Path.open
    def denied(self, *args, **kwargs):
        if self == path:
            raise PermissionError('sensitive path: ' + str(path))
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', denied)
    readers = {'data': lambda: read_waveform(path, 0, 7),
               'ebi': lambda: load_records(path_text=str(path)), 'lps': lambda: parse_lps(path)}
    with pytest.raises(SourceReadError, match='权限') as caught:
        readers[source]()
    assert str(path) not in str(caught.value)


def test_one_broken_case_does_not_hide_healthy_cases(synthetic_case):
    root, cid, _ = synthetic_case
    (root / '8888888888888888').mkdir()
    good, issues = CaseRepository(root).scan_cases()
    assert [case['case_id'] for case in good] == [cid]
    assert len(issues) == 1 and issues[0]['case_id'] == '8888888888888888'


def test_dashboard_displays_failure_and_recovery_without_false_zero():
    subprocess.run(['node', 'tests/browser_source_integrity.cjs'], check=True, timeout=15)
