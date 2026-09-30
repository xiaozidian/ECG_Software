"""Cross-panel read identity: all inputs are disposable synthetic records."""
import pytest
import subprocess
from test_analysis_provenance import synthetic_case, synthetic_app

READS = ['', 'trend', 'rr-visuals', 'scatter', 'hrv', 'hrv-windows',
         'hrv-analysis', 'stt-review', 'report-statistics', 'report-sections']


@pytest.mark.parametrize('kind', READS)
@pytest.mark.parametrize('change', ['edit', 'source'])
def test_read_endpoints_bind_source_and_review(synthetic_app, synthetic_case, kind, change):
    client = synthetic_app.test_client()
    _, cid, paths = synthetic_case
    base = f'/api/cases/{cid}'
    seed = client.get(base + '/report-events').json
    identity = {k: seed[k] for k in ('analysis_basis', 'analysis_revision')}
    url = base + ('/' + kind if kind else '')
    response = client.get(url, query_string=dict(analysis='edited', **identity))
    assert response.status_code == 200, response.json
    observed = response.json.get('clinical_identity', response.json)
    assert all(observed.get(k) == v for k, v in identity.items())
    if change == 'edit':
        synthetic_app.extensions['storage'].audit('synthetic', 'beat_override.editor', cid)
    else:
        content = paths['data'].read_bytes()
        paths['data'].write_bytes(b'\1' + content[1:])
    response = client.get(url, query_string=dict(analysis='edited', **identity))
    assert response.status_code == 409, response.json


@pytest.mark.parametrize('kind,reader', [('hrv', 'hrv'), ('hrv-analysis', 'analyze_hrv'),
    ('hrv-windows', 'hrv_windows'), ('stt-review', 'build_stt_review'),
    ('report-statistics', 'report_statistics'), ('report-sections', 'build_stt_review'),
    ('trend', 'heart_rate_trend'), ('rr-visuals', 'rr_visuals'), ('scatter', 'scatter_points'),
    ('', 'ebi_metrics')])
def test_mid_read_revision_is_rejected(synthetic_app, synthetic_case, monkeypatch, kind, reader):
    import app as server
    cid = synthetic_case[1]
    original = getattr(server, reader)
    def racing(*args, **kwargs):
        result = original(*args, **kwargs)
        synthetic_app.extensions['storage'].audit('synthetic', 'beat_override.editor', cid)
        return result
    monkeypatch.setattr(server, reader, racing)
    url = f'/api/cases/{cid}' + ('/' + kind if kind else '')
    response = synthetic_app.test_client().get(url, query_string={'analysis': 'edited'})
    assert response.status_code == 409, response.json


def test_hrv_download_rejects_displayed_old_basis(synthetic_app, synthetic_case):
    client = synthetic_app.test_client();cid = synthetic_case[1]
    seed = client.get(f'/api/cases/{cid}/report-events').json
    identity = {k: seed[k] for k in ('analysis_basis', 'analysis_revision')}
    synthetic_app.extensions['storage'].audit('synthetic', 'beat_override.editor', cid)
    result = client.get(f'/api/cases/{cid}/hrv-report.pdf', query_string=identity)
    assert result.status_code == 409, result.json


@pytest.mark.parametrize('mid_read', [False, True])
def test_advanced_measurements_bind_analysis_basis(synthetic_app, synthetic_case, monkeypatch, mid_read):
    from ecg_core import advanced_analysis
    client=synthetic_app.test_client();cid=synthetic_case[1]
    basis=client.get(f'/api/cases/{cid}/analysis-basis').json
    if mid_read:
        original=advanced_analysis.analyze
        def racing(*args, **kwargs):
            result=original(*args, **kwargs)
            synthetic_app.extensions['storage'].audit('synthetic','beat_override.editor',cid)
            return result
        monkeypatch.setattr(advanced_analysis,'analyze',racing)
    else:
        synthetic_app.extensions['storage'].audit('synthetic','beat_override.editor',cid)
    result=client.post(f'/api/cases/{cid}/advanced-analysis',json={**basis,'options':{}})
    assert result.status_code==409,result.json


@pytest.mark.parametrize('scenario', ['missing','nested','final','mixed','absent','success','missing-metrics',
    'trends-success','trends-mixed','trends-failure','trends-case',
    'stt-success','stt-cache','stt-mixed','stt-failure','stt-case',
    'hrv-late-error','hrv-old-controls','hrv-export',
    'demo-root','demo-batch','demo-race','demo-stale','demo-overview','demo-rhythm'])
def test_browser_analysis_batch_lifecycle(scenario):
    subprocess.run(['node','tests/browser_analysis_consistency.cjs',scenario],check=True,timeout=20)
