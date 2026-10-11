"""Density views reject stale disposable input, preserving numerical output."""
import pytest
from test_analysis_provenance import synthetic_case, synthetic_app


def test_density_basis_is_numerically_identical(synthetic_app, synthetic_case):
    client = synthetic_app.test_client()
    cid = synthetic_case[1]
    basis = client.get(f'/api/cases/{cid}/report-events').json
    url = f'/api/cases/{cid}/waveform-density?class_code=N&lead=II'
    original = client.post(url, json={'revision': 0})
    guarded = client.post(url, json={'revision': 0, 'analysis_basis': basis['analysis_basis']})
    assert original.status_code == guarded.status_code == 200
    assert original.json == guarded.json


@pytest.mark.parametrize('mid_read', [False, True])
def test_density_rejects_changed_synthetic_signal(synthetic_app, synthetic_case, monkeypatch, mid_read):
    import app as server
    client = synthetic_app.test_client()
    _, cid, files = synthetic_case
    basis = client.get(f'/api/cases/{cid}/report-events').json['analysis_basis']
    def change():
        source = files['data'].read_bytes()
        files['data'].write_bytes(b'\1' + source[1:])
    if mid_read:
        original = server.density
        def racing(*args, **kwargs):
            result = original(*args, **kwargs)
            change()
            return result
        monkeypatch.setattr(server, 'density', racing)
    else:
        change()
    result = client.post(f'/api/cases/{cid}/waveform-density?class_code=N&lead=II',
                         json={'revision': 0, 'analysis_basis': basis})
    assert result.status_code == 409
    assert 'bins' not in result.json
