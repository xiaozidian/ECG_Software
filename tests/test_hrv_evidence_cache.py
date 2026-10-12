"""Read evidence isolation and invalidation; disposable mathematical records."""
from concurrent.futures import Future, ThreadPoolExecutor
import threading

import pytest

from ecg_core.clinical_query_cache import ClinicalEvidenceCache
from test_analysis_provenance import synthetic_case, synthetic_app, replace_preserving_mtime


def test_encoded_bound_detached_results_window_lru_and_new_revision():
    cache = ClinicalEvidenceCache(max_entries=3, max_units=200)
    calls = []
    def build():
        calls.append(1)
        return {'points': [1, 2], 'eligible': True}
    key = ('a', 'source', 1, '0')
    first = cache.read(key, build)
    first['points'].append(999)
    assert cache.read(key, build) == {'points': [1, 2], 'eligible': True}
    assert len(calls) == 1
    for k in [('a','source',1,'1'), ('b','source',1,'0'), ('a','source',1,'0'), ('c','source',1,'0')]:
        cache.read(k, build)
    assert ('a','source',1,'1') not in cache._entries
    cache.read(('a','source',2,'0'), build)
    assert not any(k[0]=='a' and k[2]==1 for k in cache._entries)
    cache.read(('a','new-source',2,'0'), build)
    assert not any(k[0]=='a' and k[1]=='source' for k in cache._entries)
    for _ in range(2):
        cache.read(('huge','source',1,'0'), lambda:{'points': 'x'*1000})
    assert not any(k[0]=='huge' for k in cache._entries)
    assert cache.retention()['units'] <= 200


@pytest.mark.parametrize('failure', [False, True])
def test_identical_readers_share_computation_and_failed_build_can_retry(failure, monkeypatch):
    from ecg_core import clinical_query_cache
    entered, joined, release = threading.Event(), threading.Event(), threading.Event()
    class ObservedFuture(Future):
        def result(self, timeout=None):
            joined.set()
            return super().result(timeout)
    monkeypatch.setattr(clinical_query_cache, 'Future', ObservedFuture)
    cache = ClinicalEvidenceCache()
    calls = []
    def build():
        calls.append(1)
        entered.set()
        assert release.wait(5)
        if failure:
            raise ValueError('source changed')
        return {'points': [1, 2]}
    with ThreadPoolExecutor(max_workers=2) as pool:
        owner = pool.submit(cache.read, ('a','source',1,'0'), build)
        assert entered.wait(5)
        waiter = pool.submit(cache.read, ('a','source',1,'0'), build)
        try:
            assert joined.wait(5)
        finally:
            release.set()
        if failure:
            for result in (owner, waiter):
                with pytest.raises(ValueError, match='source changed'):
                    result.result(timeout=5)
        else:
            a, b = owner.result(timeout=5), waiter.result(timeout=5)
            a['points'].append(999)
            assert b == {'points': [1, 2]}
    assert len(calls) == 1 and cache.retention()['pending'] == 0
    if failure:
        assert cache.retention()['entries'] == 0
        assert cache.read(('a','source',1,'0'), lambda:{'retry': True}) == {'retry': True}


def test_hrv_hit_then_revision_and_same_mtime_source_change_recompute(synthetic_app, synthetic_case, monkeypatch):
    import app as server
    client = synthetic_app.test_client()
    cid, paths = synthetic_case[1:]
    base = f'/api/cases/{cid}'
    original, calls = server.analyze_hrv_review, []
    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(server, 'analyze_hrv_review', counted)
    seed = client.get(base+'/hrv-analysis').json
    again = client.get(base+'/hrv-analysis')
    assert again.status_code == 200 and again.json == seed and len(calls) == 1
    identity = {k:seed[k] for k in ('analysis_basis','analysis_revision')}
    synthetic_app.extensions['storage'].audit('synthetic','beat_override.editor',cid)
    assert client.get(base+'/hrv-analysis',query_string=identity).status_code == 409
    current = client.get(base+'/hrv-analysis').json
    assert current['analysis_revision'] != seed['analysis_revision'] and len(calls) == 2
    content = paths['data'].read_bytes()
    replace_preserving_mtime(paths['data'], b'\1'+content[1:])
    source = client.get(base+'/hrv-analysis')
    assert source.status_code == 200 and source.json['analysis_basis'] != current['analysis_basis'] and len(calls) == 3
    assert synthetic_app.extensions['hrv_evidence_cache'].retention()['entries'] == 1


def test_revision_change_after_cache_hit_is_rejected(synthetic_app, synthetic_case, monkeypatch):
    cid = synthetic_case[1]
    client = synthetic_app.test_client()
    url = f'/api/cases/{cid}/hrv-analysis'
    assert client.get(url).status_code == 200
    cache = synthetic_app.extensions['hrv_evidence_cache']
    original = cache.read
    def racing(*args, **kwargs):
        result = original(*args, **kwargs)
        synthetic_app.extensions['storage'].audit('synthetic','beat_override.editor',cid)
        return result
    monkeypatch.setattr(cache, 'read', racing)
    assert client.get(url).status_code == 409
