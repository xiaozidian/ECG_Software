"""Numerical reuse follows actual inputs, independent of workflow-only writes."""
import copy,json
from test_analysis_provenance import synthetic_case,synthetic_app

def measured(app,monkeypatch):
    import app as server
    calls=[];real=server.analyze_hrv_review
    def traced(*args,**kwargs):
        calls.append(1);return real(*args,**kwargs)
    monkeypatch.setattr(server,'analyze_hrv_review',traced)
    return calls

def get(client,url):
    r=client.get(url);assert r.status_code==200,r.json
    return r.json

def test_verified_preview_survives_own_save_and_returns_detached_values(synthetic_app,synthetic_case,monkeypatch):
    calls=measured(synthetic_app,monkeypatch);client=synthetic_app.test_client();cid=synthetic_case[1];url=f'/api/cases/{cid}/hrv-review'
    before=get(client,url);assert len(calls)==1
    doc=copy.deepcopy(before['document']);doc['exclusions'].append(dict(id='engineering',start_sample=2000,end_sample=4000,reason='mathematical'))
    payload=dict(scope=before['scope'],expected_hrv_revision=before['hrv_revision'],window=0)
    pre=client.post(url+'/preview',json={**payload,'operation':'replace','document':doc});assert pre.status_code==200,pre.json
    assert len(calls)==2
    saved=client.put(url,json={**payload,'preview_token':pre.json['preview_token'],'preview_digest':pre.json['preview_digest'],'confirmed':True});assert saved.status_code==200,saved.json
    assert saved.json['scope']['analysis_revision']>before['scope']['analysis_revision']
    again=get(client,url);assert again['evidence']==pre.json['evidence_preview'];assert len(calls)==2
    again['evidence']['reviewed']['periods']['full']['nn_count']=-1
    assert get(client,url)['evidence']==pre.json['evidence_preview'] and len(calls)==2

def test_imported_rhythm_details_invalidate_even_without_workflow_revision(synthetic_app,synthetic_case,monkeypatch):
    calls=measured(synthetic_app,monkeypatch);client=synthetic_app.test_client();cid=synthetic_case[1];url=f'/api/cases/{cid}/hrv-review';store=synthetic_app.extensions['storage']
    before=get(client,url)
    ann=store.create_annotation(cid,dict(sample_index=2000,lead='II',label='synthetic',details=dict(kind='AF',status='pending',end_sample=4000)),'engineering')
    first=get(client,url);rev=first['scope']['analysis_revision'];assert len(calls)==2
    with store.connect() as db:db.execute('update annotations set details=? where id=?',(json.dumps({**ann['details'],'end_sample':8000}),ann['id']))
    second=get(client,url)
    assert second['scope']['analysis_revision']==rev and len(calls)==3
    assert second['evidence']['baseline']['periods']['full']['nn_count']<first['evidence']['baseline']['periods']['full']['nn_count']<before['evidence']['baseline']['periods']['full']['nn_count']

def test_rhythm_input_race_on_numeric_cache_hit_is_rejected(synthetic_app,synthetic_case,monkeypatch):
    client=synthetic_app.test_client();cid=synthetic_case[1];url=f'/api/cases/{cid}/hrv-review';store=synthetic_app.extensions['storage']
    ann=store.create_annotation(cid,dict(sample_index=2000,lead='II',label='synthetic',details=dict(kind='AF',status='pending',end_sample=4000)),'engineering')
    get(client,url);cache=synthetic_app.extensions['hrv_measurement_cache'];original=cache.read
    def racing(*args,**kwargs):
        result=original(*args,**kwargs)
        with store.connect() as db:db.execute('update annotations set details=? where id=?',(json.dumps({**ann['details'],'end_sample':8000}),ann['id']))
        return result
    monkeypatch.setattr(cache,'read',racing)
    response=client.get(url);assert response.status_code==409

def test_event_projection_reuses_workflow_only_change_and_rebuilds_review_decision(synthetic_app,synthetic_case,monkeypatch):
    import app as server
    client=synthetic_app.test_client();cid=synthetic_case[1];url=f'/api/cases/{cid}/hrv-analysis';calls=[];original=server.report_statistics
    def traced(*args,**kwargs):
        calls.append(1);return original(*args,**kwargs)
    monkeypatch.setattr(server,'report_statistics',traced)
    first=get(client,url);assert len(calls)==1
    store=synthetic_app.extensions['storage']
    with store.connect() as db:store.invalidate_review(db,cid,'hrv_review.confirmed')
    second=get(client,url)
    assert second['analysis_revision']>first['analysis_revision'] and len(calls)==1
    assert second['event_statistics']==first['event_statistics']
    assert second['representatives']==first['representatives']
    review=store.get_review(cid)
    store.complete_review(cid,dict(step='edit',confirmed=True,revision=review['revision']),'engineering')
    third=get(client,url);assert len(calls)==2
    assert any(r['diagnosis_status']=='confirmed' for r in third['representatives'])

def test_scope_bearing_projection_falls_back_to_revision_cache(synthetic_app,synthetic_case,monkeypatch):
    import app as server
    client=synthetic_app.test_client();cid=synthetic_case[1];url=f'/api/cases/{cid}/hrv-analysis';store=synthetic_app.extensions['storage'];original=server.prepare_strip;calls=[]
    def scoped(*args,**kwargs):
        calls.append(1);return {**original(*args,**kwargs),'future_scope':{'analysis_revision':store.get_review(cid)['revision']}}
    monkeypatch.setattr(server,'prepare_strip',scoped)
    first=get(client,url);n=len(calls);assert n>0
    with store.connect() as db:store.invalidate_review(db,cid,'hrv_review.confirmed')
    second=get(client,url);assert len(calls)>n
    assert second['representatives'][0]['future_scope']['analysis_revision']==second['analysis_revision']
