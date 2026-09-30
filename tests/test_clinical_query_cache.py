"""Deterministic concurrency and revision safety, only disposable synthetic data."""
from concurrent.futures import Future, ThreadPoolExecutor
import threading

import pytest

from ecg_core.clinical_query_cache import ClinicalQueryCache, ClinicalQueryBusy
from ecg_core.review_workflow import ReportConflict
from test_analysis_provenance import synthetic_case, synthetic_app, replace_preserving_mtime


def value(n=2):
    return {'rows':[{'sample_index':i} for i in range(n)],
            'events':[{'target_samples':[0], 'label':'synthetic'}]}


def test_results_are_detached_and_oversize_entries_are_not_retained():
    cache = ClinicalQueryCache(max_units=5)
    calls = []
    def build():
        calls.append(1)
        return value()
    a = cache.project(('case','basis',0), build, lambda x:x)
    a['rows'].clear()
    a['events'][0]['target_samples'].append(999)
    b = cache.project(('case','basis',0), build, lambda x:x)
    assert b == value() and len(calls) == 1
    for _ in range(2):
        cache.project(('other','basis',0), lambda:value(100), lambda x:len(x['rows']))
    assert cache.retention()['entries'] == 1 and cache.retention()['units'] == 4


def test_lru_weight_and_revision_retention():
    cache = ClinicalQueryCache(max_entries=2, max_units=8)
    for key in [('a','basis',0),('b','basis',0),('a','basis',1),('c','basis',0)]:
        cache.project(key, value, lambda x:x['rows'])
    assert list(cache._entries) == [('a','basis',1),('c','basis',0)]
    assert cache.retention()['units'] == 8
    cache.project(('a','basis',1), value, lambda x:x['rows'])
    cache.project(('d','basis',0), value, lambda x:x['rows'])
    assert list(cache._entries) == [('a','basis',1),('d','basis',0)]


@pytest.mark.parametrize('failure',[False,True])
def test_simultaneous_readers_share_build_but_not_response(failure, monkeypatch):
    from ecg_core import clinical_query_cache
    cache = ClinicalQueryCache()
    entered, release, joined = threading.Event(), threading.Event(), threading.Event()
    join_lock = threading.Lock()
    waiters = []
    class ObservedFuture(Future):
        def result(self, timeout=None):
            with join_lock:
                waiters.append(1)
                if len(waiters) == 3:
                    joined.set()
            return super().result(timeout)
    monkeypatch.setattr(clinical_query_cache, 'Future', ObservedFuture)
    calls = []
    def build():
        calls.append(1)
        entered.set()
        assert release.wait(5)
        if failure:
            raise ReportConflict('synthetic source changed')
        return value()
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(cache.project,('c','b',0),build,lambda x:x) for _ in range(4)]
        assert entered.wait(5)
        # Ensure the other requests joined the same Future before releasing it.
        try:
            assert joined.wait(5)
        finally:
            release.set()
        if failure:
            for future in futures:
                with pytest.raises(ReportConflict):
                    future.result(timeout=5)
        else:
            outputs = [f.result(timeout=5) for f in futures]
            assert outputs == [value()]*4
            assert len({id(x) for x in outputs}) == 4
    assert len(calls) == 1
    if failure:
        assert cache.retention()['entries'] == 0
        assert cache.project(('c','b',0),value,lambda x:x) == value()
    assert cache.retention()['pending'] == 0


def test_wait_timeout_does_not_cancel_or_duplicate_original_build():
    cache = ClinicalQueryCache(wait_seconds=.01)
    entered, release = threading.Event(), threading.Event()
    def build():
        entered.set()
        assert release.wait(5)
        return value()
    with ThreadPoolExecutor(max_workers=1) as pool:
        owner = pool.submit(cache.project,('c','b',0),build,lambda x:x)
        assert entered.wait(5)
        try:
            with pytest.raises(ClinicalQueryBusy):
                cache.project(('c','b',0),lambda:pytest.fail('duplicate build'),lambda x:x)
            assert cache.retention()['pending'] == 1
        finally:
            release.set()
        assert owner.result(timeout=5) == value()
    assert cache.project(('c','b',0),lambda:pytest.fail('lost result'),lambda x:x) == value()


def test_different_keys_build_independently():
    cache = ClinicalQueryCache()
    barrier = threading.Barrier(2)
    def build():
        barrier.wait(timeout=5)
        return value()
    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks=[pool.submit(cache.project,(c,'basis',0),build,lambda x:x) for c in ('a','b')]
        assert [t.result(timeout=5) for t in tasks] == [value(),value()]


def test_builder_timeout_is_not_misreported_as_busy():
    cache = ClinicalQueryCache()
    failed = Future()
    failed.set_exception(TimeoutError('synthetic source timeout'))
    cache._pending[('c','b',0)] = failed
    with pytest.raises(TimeoutError, match='source timeout'):
        cache.project(('c','b',0), lambda:pytest.fail('duplicate build'), lambda x:x)


def test_busy_api_is_retryable_and_owner_result_remains_valid(synthetic_app, synthetic_case, monkeypatch):
    import app as server
    cache=synthetic_app.extensions['clinical_query_cache'];cache.wait_seconds=.01
    original=server.build_index;entered=threading.Event();release=threading.Event();calls=[]
    def blocked(*args,**kwargs):
        calls.append(1);entered.set()
        assert release.wait(5)
        return original(*args,**kwargs)
    monkeypatch.setattr(server,'build_index',blocked)
    url=f'/api/cases/{synthetic_case[1]}/template-occurrences?class_code=N'
    def get():
        with synthetic_app.test_client() as client:
            return client.get(url)
    with ThreadPoolExecutor(max_workers=1) as pool:
        owner=pool.submit(get)
        assert entered.wait(5)
        try:
            waiting=get()
            assert waiting.status_code==503 and waiting.json['code']=='clinical_query_busy'
            assert 'items' not in waiting.json
        finally:
            release.set()
        result=owner.result(timeout=5)
        assert result.status_code==200,result.json
    retry=get()
    assert retry.status_code==200 and retry.json==result.json
    assert len(calls)==1


@pytest.mark.parametrize('change',['missing-data','missing-ebi','missing-lps','data-empty','ebi-tail','lps-xml'])
def test_warm_cache_never_hides_source_failure(synthetic_app, synthetic_case, change):
    from test_source_integrity import corrupt
    _,cid,paths=synthetic_case;client=synthetic_app.test_client()
    url=f'/api/cases/{cid}/template-occurrences?class_code=N'
    before=client.get(url);assert before.status_code==200,before.json
    originals={k:p.read_bytes() for k,p in paths.items()}
    if change.startswith('missing-'):
        paths[change.split('-')[1]].unlink()
    else:
        corrupt(paths,change)
    response=client.get(url)
    assert response.status_code==(503 if change.startswith('missing-') else 422),response.json
    assert 'items' not in response.json
    for k,content in originals.items():paths[k].write_bytes(content)
    after=client.get(url)
    assert after.status_code==200 and after.json==before.json


def test_relabel_and_undo_change_cached_results(synthetic_app, synthetic_case):
    client=synthetic_app.test_client();base=f'/api/cases/{synthetic_case[1]}'
    query=base+'/template-occurrences?class_code=V'
    first=client.get(query);assert first.status_code==200 and first.json['total']==0
    relabel=client.put(base+'/beat-editor',json=dict(operation='relabel',revision=0,
        confirmed=True,selection={'samples':[6000]},class_code='V'))
    assert relabel.status_code==200,relabel.json
    edited=client.get(query)
    assert edited.status_code==200 and edited.json['total']==1
    assert edited.json['items'][0]['sample_index']==6000
    assert edited.json['items'][0]['diagnosis_status']=='edited'
    assert edited.json['data_version']!=first.json['data_version']
    undo=client.put(base+'/beat-editor',json=dict(operation='undo',revision=1,confirmed=True))
    assert undo.status_code==200,undo.json
    restored=client.get(query)
    assert restored.status_code==200 and restored.json['total']==0
    assert restored.json['data_version']==first.json['data_version']
    assert restored.json['analysis_revision']>edited.json['analysis_revision']


def test_query_pagination_and_category_changes_reuse_private_index(synthetic_app, synthetic_case, monkeypatch):
    import app as server
    original, calls = server.build_index, []
    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(server,'build_index',counted)
    client=synthetic_app.test_client();base=f'/api/cases/{synthetic_case[1]}'
    for suffix in ['/report-events?category=fastest','/report-events?category=slowest',
                   '/template-occurrences?class_code=N&limit=3&offset=0',
                   '/template-occurrences?class_code=N&limit=3&offset=3']:
        response=client.get(base+suffix)
        assert response.status_code == 200,response.json
    assert len(calls) == 1
    # Consumers elsewhere never receive the cache-owned object.
    assert client.get(base+'/report-statistics').status_code == 200
    assert len(calls) == 2
    assert client.get(base+'/report-events').status_code == 200 and len(calls) == 2


@pytest.mark.parametrize('change',['source-data','source-ebi','source-lps','beat','template','rhythm','annotation','patient','review'])
def test_every_clinical_identity_change_rebuilds(synthetic_app, synthetic_case, monkeypatch, change):
    import app as server
    original, calls = server.build_index, []
    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(server,'build_index',counted)
    _,cid,paths=synthetic_case;client=synthetic_app.test_client();url=f'/api/cases/{cid}/report-events'
    first=client.get(url)
    assert first.status_code == 200, first.json
    store=synthetic_app.extensions['storage']
    if change.startswith('source-'):
        kind=change.split('-')[1];path=paths[kind];content=path.read_bytes()
        if kind == 'data': content=b'\1'+content[1:]
        elif kind == 'ebi':content=b'\1'+content[1:] # Valid metadata-byte change, not a fake clinical beat.
        else:content=content.replace(b'08:00:00',b'08:01:00')
        replace_preserving_mtime(path,content)
    elif change == 'review':
        store.complete_review(cid,dict(step='edit',confirmed=True,revision=0),'synthetic')
    else:
        action={'beat':'beat_override.editor','template':'beat_template.update','rhythm':'annotation.rhythm',
                'annotation':'annotation.update','patient':'patient.update'}[change]
        store.audit('synthetic',action,cid)
    old={k:first.json[k] for k in ('analysis_basis','analysis_revision')}
    assert client.get(url,query_string=old).status_code == 409
    second=client.get(url)
    assert second.status_code == 200,second.json
    assert len(calls) == 2
    if change == 'review':
        assert second.json['items'][0]['diagnosis_status'] == 'confirmed'
    assert synthetic_app.extensions['clinical_query_cache'].retention()['entries'] == 1


@pytest.mark.parametrize('change',['during-build','during-hit'])
def test_revision_change_never_publishes_mixed_index(synthetic_app, synthetic_case, monkeypatch, change):
    import app as server
    cid=synthetic_case[1];client=synthetic_app.test_client();url=f'/api/cases/{cid}/report-events'
    name='build_index' if change=='during-build' else 'query_index'
    if change=='during-hit':assert client.get(url).status_code==200
    original=getattr(server,name)
    def racing(*args,**kwargs):
        result=original(*args,**kwargs)
        synthetic_app.extensions['storage'].audit('synthetic','beat_override.editor',cid)
        return result
    monkeypatch.setattr(server,name,racing)
    response=client.get(url)
    assert response.status_code==409,response.json
    if change=='during-build':
        assert synthetic_app.extensions['clinical_query_cache'].retention()['entries']==0
    monkeypatch.setattr(server,name,original)
    assert client.get(url).status_code==200


def test_case_and_application_caches_are_isolated(synthetic_case,tmp_path):
    from app import create_app
    apps=[create_app(data_root=synthetic_case[0],db_path=tmp_path/f'isolated-{n}.db',testing=True) for n in range(2)]
    assert apps[0].extensions['clinical_query_cache'] is not apps[1].extensions['clinical_query_cache']
    assert apps[0].test_client().get(f'/api/cases/{synthetic_case[1]}/report-events').status_code==200
    assert apps[1].extensions['clinical_query_cache'].retention()['entries']==0
