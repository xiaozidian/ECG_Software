"""Construction reuse is read-only, revision-bound and detached from write paths."""
from copy import deepcopy

from ecg_core.beat_editor import EditedRecords, blank
from test_analysis_provenance import synthetic_case, synthetic_app


def test_nested_extension_rows_and_document_are_deeply_detached():
    doc = blank()
    feed = EditedRecords(((200,0,1,0,0,0,1000), (400,0,1,0,0,0,1000)), doc, [], 90)
    feed.beats[0]['extension'] = {'values': [1,2]}
    feed.prepare_read_snapshot()
    assert feed._scalar_read_rows is False
    a, b = feed.clone_for_read(), feed.clone_for_read()
    a.beats[0]['extension']['values'].append(99)
    a.document['changes']['synthetic'] = {'sample_index': 300}
    assert b.beats[0]['extension'] == feed.beats[0]['extension'] == {'values':[1,2]}
    assert not b.document['changes'] and not feed.document['changes']


def test_write_builds_fresh_and_navigation_never_advances_review(synthetic_app, synthetic_case, monkeypatch):
    import app as server
    calls=[];original=server.EditedRecords
    def counted(*a,**kw):
        calls.append(1)
        return original(*a,**kw)
    monkeypatch.setattr(server,'EditedRecords',counted)
    cid=synthetic_case[1];client=synthetic_app.test_client();base=f'/api/cases/{cid}'
    assert client.get(base+'?analysis=edited').status_code==200
    store=synthetic_app.extensions['storage']
    review=store.get_review(cid)['revision'];version=store.get_report(cid,'')['version']
    for endpoint in ['/overview','/trend','/waveform','/rr-visuals','/waveform-density']:
        for _ in range(2):assert client.get(base+endpoint+'?analysis=edited').status_code==200
    assert len(calls)==1
    assert store.get_review(cid)['revision']==review
    assert store.get_report(cid,'')['version']==version
    changed=client.put(base+'/beat-editor',json={'operation':'relabel','revision':0,'confirmed':True,
        'selection':{'samples':[6000]},'class_code':'V'})
    assert changed.status_code==200,changed.json
    assert len(calls)>1
    fresh=client.get(base+'/overview?analysis=edited').json
    assert next(row for row in fresh['rows'] if row[0]==6000)[2]=='V'
    assert store.get_review(cid)['revision']>review


def test_post_density_and_get_overview_share_one_construction(synthetic_app,synthetic_case,monkeypatch):
    import app as server
    calls=[];original=server.EditedRecords
    def counted(*a,**kw):calls.append(1);return original(*a,**kw)
    monkeypatch.setattr(server,'EditedRecords',counted)
    base=f'/api/cases/{synthetic_case[1]}'
    client=synthetic_app.test_client()
    assert client.get(base+'/overview?analysis=edited').status_code==200
    assert client.post(base+'/waveform-density?leads=II,V1&analysis=edited',json={}).status_code==200
    assert len(calls)==1


def test_annotation_change_refreshes_cached_exclusions(synthetic_app,synthetic_case):
    client=synthetic_app.test_client();cid=synthetic_case[1];base=f'/api/cases/{cid}'
    first=client.get(base+'/overview?analysis=edited').json
    hrv_before=client.get(base+'/hrv?analysis=edited').json
    store=synthetic_app.extensions['storage']
    created=client.post(base+'/annotations',json={'sample_index':4000,'label':'数学夹具节律排除',
        'category':'note','details':{'kind':'AF','status':'pending','end_sample':8000}})
    assert created.status_code==201,created.json
    second=client.get(base+'/overview?analysis=edited').json
    assert second['analysis_revision']>first['analysis_revision']
    assert second['rows']==first['rows']
    cache=synthetic_app.extensions['waveform_beat_cache']
    assert len(cache._entries)==1
    assert next(iter(cache._entries))[2]==second['analysis_revision']
    snapshot=next(iter(cache._entries.values()))[0]
    # NN excludes the complete inclusive saved span, while the source rows stay intact.
    assert snapshot.excluded_rhythm_intervals==[(20.0,40.005)]
    hrv_after=client.get(base+'/hrv?analysis=edited').json
    assert hrv_after['calculated']['nn_count']<hrv_before['calculated']['nn_count']
    assert client.get(base+'/overview?analysis=edited').json==second
