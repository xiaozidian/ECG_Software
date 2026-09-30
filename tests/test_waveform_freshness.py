"""Synthetic evidence/range race checks; no patient record is modified."""
import subprocess
import pytest
from test_analysis_provenance import synthetic_case, synthetic_app


@pytest.mark.parametrize('endpoint', ['waveform', 'event-waveform'])
@pytest.mark.parametrize('change', ['raw', 'edit'])
def test_continuous_wave_requires_current_basis(synthetic_app, synthetic_case, endpoint, change):
    client = synthetic_app.test_client()
    _, cid, paths = synthetic_case
    base = f'/api/cases/{cid}'
    index = client.get(base + '/report-events').json
    identity = {k: index[k] for k in ('analysis_basis', 'analysis_revision')}
    current = client.get(base + '/' + endpoint, query_string=identity)
    assert current.status_code == 200
    assert all(current.json.get(k) == v for k, v in identity.items())
    if change == 'raw':
        raw = paths['data'].read_bytes()
        paths['data'].write_bytes(b'\1' + raw[1:])
    else:
        synthetic_app.extensions['storage'].audit('test', 'beat_override.editor', cid)
    stale = client.get(base + '/' + endpoint, query_string=identity)
    assert stale.status_code == 409 and '依据已变化' in stale.json['error']


@pytest.mark.parametrize('endpoint,reader', [('waveform', 'read_waveform'), ('event-waveform', 'read_event_waveform')])
def test_wave_read_rejects_mid_read_change(synthetic_app, synthetic_case, monkeypatch, endpoint, reader):
    import app as server
    _, cid, _ = synthetic_case
    original = getattr(server, reader)
    def racing(*args, **kwargs):
        result = original(*args, **kwargs)
        synthetic_app.extensions['storage'].audit('test', 'beat_override.editor', cid)
        return result
    monkeypatch.setattr(server, reader, racing)
    response = synthetic_app.test_client().get(f'/api/cases/{cid}/{endpoint}?analysis=edited')
    assert response.status_code == 409 and '依据已变化' in response.json['error']


@pytest.mark.parametrize('scenario', ['range-order', 'range-apply', 'range-refresh', 'range-valid', 'detail-loading', 'wave-failure', 'wave-case', 'edit-failure', 'edit-case', 'stt-failure', 'stt-case', 'edit-load-failure', 'edit-load-case'])
def test_browser_waveform_and_range_navigation(scenario):
    subprocess.run(['node', 'tests/browser_waveform_freshness.cjs', scenario], check=True, timeout=15)


@pytest.mark.parametrize('params', [{'range_start_s':'bad','range_end_s':7}, {'range_start_s':0}, {'range_end_s':7}, {'range_start_s':-1,'range_end_s':7}, {'range_start_s':'NaN','range_end_s':7}, {'range_start_s':0,'range_end_s':'Infinity'}])
def test_manual_range_does_not_silently_substitute_invalid_input(synthetic_app, synthetic_case, params):
    client=synthetic_app.test_client();base=f'/api/cases/{synthetic_case[1]}'
    event=client.get(base+'/report-events').json['items'][0]
    response=client.get(base+'/report-strip',query_string=dict(event_id=event['event_id'],basis_version=event['basis_version'],**params))
    assert response.status_code==400,response.json
