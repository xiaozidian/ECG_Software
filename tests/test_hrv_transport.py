"""Lossless HRV wire representation; synthetic input and disposable workspace."""
import gzip
import json

import pytest

from test_analysis_provenance import synthetic_case, synthetic_app


@pytest.fixture
def transport_app(synthetic_case, tmp_path, monkeypatch):
    import app as server
    from scripts.serve_local_review import create_review_app
    monkeypatch.setenv('ECG_ALLOW_PHI', '0')
    original = server.analyze_hrv_review
    def measured(*args, **kwargs):
        result = original(*args, **kwargs)
        # An opaque large numeric extension proves compression preserves every
        # JSON field and element, including fields the UI does not inspect.
        result['reviewed']['transport_test_values'] = list(range(12000))
        return result
    monkeypatch.setattr(server, 'analyze_hrv_review', measured)
    return create_review_app(synthetic_case[0], tmp_path/'review',
                             purpose='isolated_verification', source_kind='mathematical_synthetic')


@pytest.mark.parametrize('route', ['hrv-analysis', 'hrv-review'])
@pytest.mark.parametrize('encoding,packed', [('gzip', True), ('br,gzip,deflate', True),
    ('*;q=0.5', True), ('gzip;q=0,*;q=1', False), ('identity', False), ('', False)])
def test_negotiated_wire_is_exact_and_no_store(transport_app, synthetic_case, route, encoding, packed):
    client=transport_app.test_client();url=f'/api/cases/{synthetic_case[1]}/{route}'
    plain=client.get(url, headers={'Accept-Encoding':'identity'})
    result=client.get(url, headers={'Accept-Encoding':encoding})
    assert plain.status_code==result.status_code==200
    assert ('gzip'==result.headers.get('Content-Encoding')) is packed
    decoded=gzip.decompress(result.data) if packed else result.data
    assert decoded==plain.data
    assert json.loads(decoded)==plain.json
    assert len(result.data)<len(plain.data) if packed else len(result.data)==len(plain.data)
    assert result.headers['Cache-Control']=='no-store'
    assert 'Accept-Encoding' in result.vary
    assert int(result.headers['Content-Length'])==len(result.data)
    # Aliasing occurred before compression; signed scopes/numbers stay intact.
    payload=json.loads(decoded)
    if route=='hrv-review':assert payload['scope']['display_case_id']=='C01'
    else:assert payload['hrv_review']['scope']['display_case_id']=='C01'


def test_transport_does_not_compress_errors_other_routes_or_small_bodies(synthetic_app, synthetic_case):
    client=synthetic_app.test_client();url=f'/api/cases/{synthetic_case[1]}'
    for suffix in ['/hrv', '/hrv-analysis?window=invalid', '/analysis-basis']:
        response=client.get(url+suffix,headers={'Accept-Encoding':'gzip'})
        assert 'Content-Encoding' not in response.headers
        assert response.headers['Cache-Control']=='no-store'


def test_hrv_enrichment_reuses_the_guarded_event_index(synthetic_app, synthetic_case, monkeypatch):
    import app as server
    calls=[];original=server.build_index
    def counted(*args, **kwargs):calls.append(1);return original(*args, **kwargs)
    monkeypatch.setattr(server,'build_index',counted)
    client=synthetic_app.test_client();url=f'/api/cases/{synthetic_case[1]}'
    assert client.get(url+'/template-occurrences?class_code=N').status_code==200
    assert len(calls)==1
    old=client.get(url+'/hrv-analysis').json
    assert 'representatives' in old and 'event_statistics' in old and len(calls)==1
    # An annotation invalidates both the HRV evidence and event projection.
    saved=client.post(url+'/annotations',json={'sample_index':200,'category':'note','label':'数学缓存标记'})
    assert saved.status_code==201
    fresh=client.get(url+'/hrv-analysis').json
    assert len(calls)==2 and fresh['analysis_revision']>old['analysis_revision']
    assert client.get(url+'/hrv-analysis').json==fresh and len(calls)==2
