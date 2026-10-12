"""Actual Flask integration using generated 90-second files and disposable DBs.

Never request conftest's patient-backed app/client/data_root fixtures.
"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from app import create_app
from ecg_core.workspace_backup import restore_backup
import app as server
from test_analysis_provenance import synthetic_case,synthetic_app,replace_preserving_mtime


def ok(response,status=200):
    assert response.status_code==status,response.get_json()
    return response.get_json()


def state(client,base):
    return ok(client.get(base+'/hrv-review'))


def preview(client,base,current,start=2000,end=2200,**extra):
    document=deepcopy(current['document'])
    document['exclusions']=[dict(id='api-synthetic-gap',start_sample=start,end_sample=end,reason='纯合成 API 验证')]
    payload=dict(scope=current['scope'],expected_hrv_revision=current['hrv_revision'],operation='replace',document=document,window=0,**extra)
    return ok(client.post(base+'/hrv-review/preview',json=payload))


def apply_payload(current,predicted):
    return dict(scope=current['scope'],expected_hrv_revision=current['hrv_revision'],confirmed=True,window=0,
                preview_token=predicted['preview_token'],preview_digest=predicted['preview_digest'])


def apply_hrv(client,base,start=2000,end=2200):
    current=state(client,base)
    predicted=preview(client,base,current,start,end)
    return ok(client.put(base+'/hrv-review',json=apply_payload(current,predicted)))


def confirm_hrv(client,base,current=None):
    current=current or state(client,base)
    payload=dict(scope=current['scope'],expected_hrv_revision=current['hrv_revision'],
                 expected_document_digest=current['digest'],window=0,confirmed=True,
                 nn_rhythm_artifact_reviewed=True,note='合成工作流确认，不是临床认证')
    return ok(client.post(base+'/hrv-review/confirm',json=payload))


def synthetic_catalog(client,version='api-v1'):
    listing=ok(client.get('/api/terminology/catalogs'))
    builtin=listing['items'][0]
    catalog=ok(client.get('/api/terminology/catalog',query_string={k:builtin[k] for k in ('namespace','version')}))
    catalog.pop('sha256')
    catalog.update(namespace='synthetic.api.original',version=version,title='纯合成 API 术语目录')
    return listing['catalog_revision'],catalog


def import_catalog(client,version='api-v1'):
    revision,catalog=synthetic_catalog(client,version)
    predicted=ok(client.post('/api/terminology/import',json=dict(catalog=catalog,expected_catalog_revision=revision)))
    return ok(client.post('/api/terminology/import',json=dict(catalog=catalog,expected_catalog_revision=revision,
                  confirm=True,preview_hash=predicted['preview_hash'])))['catalog']


def usage(catalog):
    term=next(n for n in catalog['nodes'] if n['kind']=='term')
    return dict(usage_id='api-usage-1',namespace=catalog['namespace'],version=catalog['version'],
        catalog_hash=catalog['sha256'],stable_id=term['stable_id'],label=term['label'],
        inserted_text='保留医生输入原文；此为合成说明。',approval=term['approval'],source=term['source'],
        license=term['license'],scope=term['scope'],review=term['review'],inserted_at='2026-10-12T08:00:00Z')


def save_report(client,base,*,catalog=None,include_hrv=False,composition=None):
    current=ok(client.get(base+'/report'))
    content=deepcopy(composition if composition is not None else current['composition'])
    if catalog is not None:content['terminology_usages']=[usage(catalog)]
    if include_hrv:
        content.update(include_hrv=True,included_pages=['summary','hrv_time'],active_page='summary',
                       hrv_review_reference=current['current_hrv_reference'])
    payload=dict(expected_version=current['version'],expected_review_revision=current['review_revision'],
                 status='draft',conclusion='纯合成病例：保留报告正文',composition=content)
    return ok(client.put(base+'/report',json=payload))


def test_rr_actual_route_counts_and_strict_identity(synthetic_app,synthetic_case):
    client=synthetic_app.test_client();_,cid,paths=synthetic_case;base=f'/api/cases/{cid}'
    hashes={k:sha256(p.read_bytes()).hexdigest() for k,p in paths.items()}
    rr=ok(client.get(base+'/rr-review',query_string={'limit':5}))
    assert rr['total']==88 and rr['histogram']['measurement_count']==88
    target=rr['items'][0]['target']
    located=ok(client.post(base+'/rr-review/locate',json={'target':target}))
    assert located['located'] and located['target']==target
    assert any(b['sample_index']==target['sample_index'] for b in located['waveform']['beats'])
    for change,status in [({'sample_index':True},400),({'sample_index':target['sample_index']+1},409),
                          ({'beat_id':'absent'},409),({'beat_revision':target['beat_revision']+1},409),({'case_id':'foreign'},409)]:
        bad={**target,**change}
        assert client.post(base+'/rr-review/locate',json={'target':bad}).status_code==status
    missing=deepcopy(target);missing.pop('analysis_basis')
    assert client.post(base+'/rr-review/locate',json={'target':missing}).status_code==400
    synthetic_app.extensions['storage'].audit('test','beat_override.editor',cid)
    assert client.post(base+'/rr-review/locate',json={'target':target}).status_code==409
    assert {k:sha256(p.read_bytes()).hexdigest() for k,p in paths.items()}==hashes


def test_default_rr_locate_uses_moved_edited_endpoint(synthetic_app,synthetic_case):
    client=synthetic_app.test_client();_,cid,_=synthetic_case;base=f'/api/cases/{cid}'
    ok(client.put(base+'/beat-editor',json=dict(operation='move',selection={'samples':[2000]},target_sample=2001,revision=0,confirmed=True)))
    rr=ok(client.get(base+'/rr-review',query_string={'limit':200}))
    target=next(x['target'] for x in rr['items'] if x['end_sample']==2001)
    located=ok(client.post(base+'/rr-review/locate',json={'target':target}))
    assert located['target']['sample_index']==2001
    assert any(b['sample_index']==2001 for b in located['waveform']['beats'])


def test_hrv_preview_cancel_replay_and_saved_revision(synthetic_app,synthetic_case):
    client=synthetic_app.test_client();_,cid,paths=synthetic_case;base=f'/api/cases/{cid}'
    hashes={k:sha256(p.read_bytes()).hexdigest() for k,p in paths.items()}
    current=state(client,base)
    assert current['hrv_revision']==0 and not current['document']['exclusions']
    assert current['evidence']['baseline']==current['evidence']['reviewed']
    predicted=preview(client,base,current)
    assert state(client,base)['hrv_revision']==0
    cancel=dict(scope=current['scope'],expected_hrv_revision=0,preview_token=predicted['preview_token'],window=0)
    cancelled=ok(client.post(base+'/hrv-review/cancel',json=cancel))
    assert cancelled['hrv_revision']==0 and not cancelled['document']['exclusions']
    assert client.put(base+'/hrv-review',json=apply_payload(current,predicted)).status_code==409
    predicted=preview(client,base,current)
    payload=apply_payload(current,predicted)
    saved=ok(client.put(base+'/hrv-review',json=payload))
    assert saved['hrv_revision']==1 and saved['document']['exclusions']==predicted['after']['exclusions']
    assert client.put(base+'/hrv-review',json=payload).status_code==409
    reopened=state(client,base)
    assert reopened['digest']==saved['digest']
    assert reopened['evidence']['coverage']['excluded_s']==1
    assert {k:sha256(p.read_bytes()).hexdigest() for k,p in paths.items()}==hashes


def test_hrv_confirmation_and_stale_scope_actual_routes(synthetic_app,synthetic_case):
    client=synthetic_app.test_client();_,cid,_=synthetic_case;base=f'/api/cases/{cid}'
    saved=apply_hrv(client,base)
    required=dict(scope=saved['scope'],expected_hrv_revision=saved['hrv_revision'],
                  expected_document_digest=saved['digest'],window=0,confirmed=True)
    assert client.post(base+'/hrv-review/confirm',json=required).status_code==400
    confirmed=confirm_hrv(client,base,saved)
    assert confirmed['confirmation']['valid'] and confirmed['confirmation']['clinical_validation'] is False
    stale={**required,'nn_rhythm_artifact_reviewed':True}
    assert client.post(base+'/hrv-review/confirm',json=stale).status_code==409
    synthetic_app.extensions['storage'].audit('test','beat_override.editor',cid)
    current=state(client,base)
    assert current['confirmation']['valid'] is False
    foreign={**current['scope'],'source_digest':'wrong-source'}
    assert client.post(base+'/hrv-review/preview',json=dict(scope=foreign,expected_hrv_revision=1,operation='reset',window=0)).status_code==409


def test_reviewed_hrv_report_requires_current_window_confirmation(synthetic_app,synthetic_case):
    client=synthetic_app.test_client();_,cid,_=synthetic_case;base=f'/api/cases/{cid}'
    ok(client.get(base+'/report'))  # Establish current source basis before confirmations.
    store=synthetic_app.extensions['storage']
    for step in ('edit','stt'):
        store.complete_review(cid,dict(step=step,confirmed=True,revision=store.get_review(cid)['revision']),'synthetic-doctor')
    composition=ok(client.get(base+'/report'))['composition']
    composition['category_reviews']=ok(client.get(base+'/report-events'))['basis_versions']
    draft=save_report(client,base,composition=composition,include_hrv=True)
    def finish(report):
        return client.put(base+'/report',json=dict(expected_version=report['version'],expected_review_revision=report['review_revision'],
                         status='reviewed',conclusion=report['conclusion'],composition=report['composition']))
    denied=finish(draft)
    assert denied.status_code==409 and 'HRV' in denied.json['error']
    confirmed=confirm_hrv(client,base)
    assert confirmed['confirmation']['valid'] and confirmed['confirmation']['window_index']==0
    fresh=save_report(client,base,include_hrv=True)
    approved=ok(finish(fresh))
    assert approved['status']=='reviewed'
    apply_hrv(client,base)
    current=ok(client.get(base+'/report'))
    assert current['status']=='draft' and not state(client,base)['confirmation'].get('valid')
    assert finish(approved).status_code==409


def test_hrv_report_reference_save_pdf_and_stale_ref_rejection(synthetic_app,synthetic_case):
    client=synthetic_app.test_client();_,cid,_=synthetic_case;base=f'/api/cases/{cid}'
    apply_hrv(client,base)
    saved=save_report(client,base,include_hrv=True)
    old_reference=deepcopy(saved['composition']['hrv_review_reference'])
    assert old_reference['hrv_revision']==1
    pdf=client.get(base+'/report.pdf')
    assert pdf.status_code==200,pdf.get_json()
    assert pdf.data.startswith(b'%PDF')
    assert pdf.headers['X-HRV-Revision']=='1'
    assert pdf.headers['X-HRV-Document-Digest']==old_reference['document_digest']
    assert pdf.headers['X-Report-SHA256']==sha256(pdf.data).hexdigest()
    assert client.get(base+'/hrv-report.pdf').status_code==409
    standalone=client.get(base+'/hrv-report.pdf',query_string=dict(expected_hrv_revision=1,expected_hrv_digest=old_reference['document_digest']))
    assert standalone.status_code==200,standalone.get_json()
    assert standalone.headers['X-HRV-Revision']=='1'
    assert standalone.headers['X-HRV-Document-Digest']==old_reference['document_digest']
    assert standalone.headers['X-HRV-Profile']==old_reference['profile']
    apply_hrv(client,base,2400,2600)
    fresh=ok(client.get(base+'/report'))
    assert fresh['current_hrv_reference']['hrv_revision']==2
    stale=deepcopy(fresh['composition']);stale['hrv_review_reference']=old_reference
    response=client.put(base+'/report',json=dict(expected_version=fresh['version'],expected_review_revision=fresh['review_revision'],
                    status='draft',conclusion=fresh['conclusion'],composition=stale))
    assert response.status_code==409 and 'HRV' in response.json['error']
    response=client.get(base+'/report.pdf')
    assert response.status_code==409 and 'HRV' in response.json['error']
    assert client.get(base+'/hrv-report.pdf',query_string=dict(expected_hrv_revision=1,expected_hrv_digest=old_reference['document_digest'])).status_code==409


@pytest.mark.parametrize('change',['beat','annotation'])
def test_scope_data_version_projection_matches_actual_clinical_events(synthetic_app,synthetic_case,change):
    client=synthetic_app.test_client();_,cid,_=synthetic_case;base=f'/api/cases/{cid}'
    before=state(client,base)['scope']
    assert before['data_version']==ok(client.get(base+'/report-events'))['data_version']
    if change=='beat':
        ok(client.put(base+'/beat-editor',json=dict(operation='relabel',selection={'samples':[2000]},class_code='V',revision=0,confirmed=True)))
    else:
        ok(client.post(base+'/annotations',json=dict(sample_index=2000,lead='II',label='纯合成 ST 注释',
                   details={'kind':'ST','status':'confirmed','end_sample':2100})),201)
    after=state(client,base)['scope']
    assert after['data_version']!=before['data_version']
    assert after['data_version']==ok(client.get(base+'/report-events'))['data_version']


def test_rr_api_cache_preserves_full_results_and_invalidates_scope(synthetic_app,synthetic_case,monkeypatch):
    client=synthetic_app.test_client();_,cid,_=synthetic_case;base=f'/api/cases/{cid}'
    original=server.build_rr_index
    builds=[]
    def counted(*args,**kwargs):
        builds.append(1)
        return original(*args,**kwargs)
    monkeypatch.setattr(server,'build_rr_index',counted)
    first=ok(client.get(base+'/rr-review',query_string={'limit':5}))
    cached=ok(client.get(base+'/rr-review',query_string={'limit':5}))
    other_page=ok(client.get(base+'/rr-review',query_string={'offset':85,'limit':5,'mode':'ratio'}))
    assert first==cached and len(builds)==1
    assert other_page['total']==88 and len(other_page['items'])==3
    assert other_page['summary']==first['summary']
    synthetic_app.extensions['storage'].audit('test','beat_override.editor',cid)
    fresh=ok(client.get(base+'/rr-review',query_string={'limit':5}))
    assert len(builds)==2 and fresh['analysis_revision']>first['analysis_revision']
    assert fresh['index_key']!=first['index_key'] and fresh['total']==88


def test_terminology_import_immutable_version_and_report_usage_snapshot(synthetic_app,synthetic_case):
    client=synthetic_app.test_client();_,cid,_=synthetic_case;base=f'/api/cases/{cid}'
    revision,catalog=synthetic_catalog(client)
    predicted=ok(client.post('/api/terminology/import',json=dict(catalog=catalog,expected_catalog_revision=revision)))
    assert predicted['preview_only'] and ok(client.get('/api/terminology/catalogs'))['catalog_revision']==0
    assert client.post('/api/terminology/import',json=dict(catalog=catalog,expected_catalog_revision=0,confirm=True,preview_hash='wrong')).status_code==400
    published=ok(client.post('/api/terminology/import',json=dict(catalog=catalog,expected_catalog_revision=0,
                      confirm=True,preview_hash=predicted['preview_hash'])))['catalog']
    assert published['approval']=='draft'
    saved=save_report(client,base,catalog=published)
    snapshot=deepcopy(saved['composition']['terminology_usages'])
    changed=deepcopy(catalog);changed['nodes'][-1]['text']='Changed synthetic text'
    assert client.post('/api/terminology/import',json=dict(catalog=changed,expected_catalog_revision=1)).status_code==409
    changed['version']='api-v2'
    new=ok(client.post('/api/terminology/import',json=dict(catalog=changed,expected_catalog_revision=1)))
    ok(client.post('/api/terminology/import',json=dict(catalog=changed,expected_catalog_revision=1,confirm=True,preview_hash=new['preview_hash'])))
    reopened=ok(client.get(base+'/report'))
    assert reopened['conclusion']==saved['conclusion']
    assert reopened['composition']['terminology_usages']==snapshot
    assert client.get('/api/terminology/catalog',query_string=dict(namespace=published['namespace'],version=published['version'],hash='0'*64)).status_code==404


def test_backup_restore_preserves_new_tables_and_expires_hrv_confirmation(synthetic_app,synthetic_case,tmp_path):
    client=synthetic_app.test_client();root,cid,_=synthetic_case;base=f'/api/cases/{cid}'
    catalog=import_catalog(client)
    apply_hrv(client,base)
    confirmed=confirm_hrv(client,base)
    saved=save_report(client,base,catalog=catalog,include_hrv=True)
    original_document=state(client,base)['document']
    created=ok(client.post('/api/workspace/backups',json={'saved_work_acknowledged':True}),201)
    assert created['verified'] and not created['raw_ecg_included']
    verified=ok(client.post('/api/workspace/backups/'+created['name']+'/verify',json={}))
    assert verified['verified']
    restored=restore_backup(created['path'],tmp_path/'recovered-three-feature')
    application=create_app(data_root=root,db_path=Path(restored['database']),testing=True)
    recovered=application.test_client()
    current=state(recovered,base)
    assert current['document']==original_document
    assert not current['confirmation'].get('valid')
    assert current['scope']!=confirmed['scope']
    assert ok(recovered.get('/api/terminology/catalog',query_string={k:catalog[k] for k in ('namespace','version')}))==catalog
    report=ok(recovered.get(base+'/report'))
    assert report['conclusion']==saved['conclusion']
    assert report['composition']['terminology_usages']==saved['composition']['terminology_usages']
    health=ok(recovered.get('/api/health'))
    stale=dict(scope=confirmed['scope'],expected_hrv_revision=confirmed['hrv_revision'],
        expected_document_digest=confirmed['digest'],window=0,confirmed=True,nn_rhythm_artifact_reviewed=True)
    assert recovered.post(base+'/hrv-review/confirm',json=stale,headers={'X-CardioInsight-Workspace':health['workspace_epoch']}).status_code==409


def test_hrv_measurement_cache_shares_panels_and_invalidates_every_identity(synthetic_app,synthetic_case,monkeypatch):
    client=synthetic_app.test_client();root,cid,paths=synthetic_case;base=f'/api/cases/{cid}'
    original=server.analyze_hrv_review;calls=[]
    def counted(*args,**kwargs):
        calls.append((args[2],deepcopy(args[3])))
        return original(*args,**kwargs)
    monkeypatch.setattr(server,'analyze_hrv_review',counted)
    main=ok(client.get(base+'/hrv-analysis'))
    review=state(client,base)
    assert len(calls)==1 and review['evidence']['reviewed']['periods']==main['periods']
    # Main-panel server enrichment must not enter the retained pure measurements.
    assert 'hrv_review' not in review['evidence']['reviewed']
    assert 'representatives' not in review['evidence']['reviewed']
    untouched=deepcopy(review['evidence'])
    main['periods']['full']['nn_count']=-999
    review['evidence']['reviewed']['periods']['full']['nn_count']=-777
    assert state(client,base)['evidence']==untouched and len(calls)==1
    # Document edits bind a distinct preview key; repeated same preview reuses it.
    predicted=preview(client,base,review)
    assert len(calls)==2 and predicted['evidence_preview']['coverage']['excluded_s']==1
    predicted=preview(client,base,review)  # New preview cancels the earlier token.
    assert len(calls)==2
    applied=ok(client.put(base+'/hrv-review',json=apply_payload(review,predicted)))
    current=state(client,base)
    assert len(calls)==3 and current['hrv_revision']==applied['hrv_revision']==1
    ok(client.get(base+'/hrv-analysis'))
    assert len(calls)==3
    old_scope=current['scope']
    synthetic_app.extensions['storage'].audit('synthetic','beat_override.editor',cid)
    revised=state(client,base)
    assert len(calls)==4 and revised['scope']['analysis_revision']!=old_scope['analysis_revision']
    assert not revised['document_stale'] and revised['evidence']['coverage']['excluded_s']==1
    assert client.get(base+'/hrv-review',query_string=old_scope).status_code==409
    ok(client.put(base+'/beat-editor',json=dict(operation='relabel',selection={'samples':[2000]},class_code='V',revision=0,confirmed=True)))
    changed_beat=state(client,base)
    assert len(calls)==5 and changed_beat['scope']['beat_revision']!=revised['scope']['beat_revision']
    assert changed_beat['document_stale'] and changed_beat['evidence']['reviewed'] is None
    # Only disposable synthetic files are changed; same-mtime content invalidates.
    content=paths['data'].read_bytes()
    replace_preserving_mtime(paths['data'],b'\1'+content[1:])
    source=state(client,base)
    assert len(calls)==6 and source['scope']['analysis_basis']!=changed_beat['scope']['analysis_basis']
    assert client.get(base+'/hrv-review',query_string=revised['scope']).status_code==409
    assert client.get(base+'/hrv-analysis',query_string=revised['scope']).status_code==409
    # A second tiny generated case has distinct identity even with identical bytes.
    other='8888888888888888'
    for path in paths.values():
        relative=path.relative_to(root/cid)
        destination=root/other/relative.parent/relative.name.replace(cid,other)
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes(path.read_bytes())
    other_base=f'/api/cases/{other}'
    other_review=state(client,other_base)
    assert len(calls)==7 and other_review['scope']['case_id']==other
    ok(client.get(other_base+'/hrv-analysis'))
    assert len(calls)==7
    retention=synthetic_app.extensions['hrv_measurement_cache'].retention()
    assert retention['max_entries']==4 and retention['max_units']==32*1024*1024
    assert retention['units']<=retention['max_units'] and retention['pending']==0


def test_hrv_measurement_cache_window_is_part_of_identity_without_large_waveform(synthetic_app,synthetic_case,monkeypatch):
    client=synthetic_app.test_client();_,cid,_=synthetic_case;base=f'/api/cases/{cid}'
    repository=synthetic_app.extensions['case_repository'];get_case=repository.get_case
    def extended_metadata(case_id):
        case=deepcopy(get_case(case_id))
        # Route/cache-only synthetic duration overlay; no 24h waveform is written.
        case['technical']['duration_seconds_raw']=86490
        return case
    monkeypatch.setattr(repository,'get_case',extended_metadata)
    original=server.analyze_hrv_review;windows=[]
    def counted(*args,**kwargs):
        windows.append(args[2]);return original(*args,**kwargs)
    monkeypatch.setattr(server,'analyze_hrv_review',counted)
    first=ok(client.get(base+'/hrv-review',query_string={'window':0}))
    second=ok(client.get(base+'/hrv-review',query_string={'window':1}))
    repeated=ok(client.get(base+'/hrv-review',query_string={'window':1}))
    assert windows==[0,1] and second==repeated
    assert first['window_index']==0 and second['window_index']==1
    assert second['evidence']['reviewed']['start_s']==86400
    assert second['evidence']['reviewed']['periods']['full']['nn_count']==0


@pytest.mark.parametrize('stage',['build','hit'])
def test_hrv_measurement_cache_checks_revision_after_build_and_hit(synthetic_app,synthetic_case,monkeypatch,stage):
    client=synthetic_app.test_client();_,cid,_=synthetic_case;base=f'/api/cases/{cid}'
    store=synthetic_app.extensions['storage']
    if stage=='build':
        original=server.analyze_hrv_review
        def racing(*args,**kwargs):
            value=original(*args,**kwargs)
            store.audit('synthetic','beat_override.editor',cid)
            return value
        monkeypatch.setattr(server,'analyze_hrv_review',racing)
    else:
        state(client,base)
        cache=synthetic_app.extensions['hrv_measurement_cache'];original=cache.read
        def racing(*args,**kwargs):
            value=original(*args,**kwargs)
            store.audit('synthetic','beat_override.editor',cid)
            return value
        monkeypatch.setattr(cache,'read',racing)
    assert client.get(base+'/hrv-review').status_code==409
    assert synthetic_app.extensions['hrv_measurement_cache'].retention()['pending']==0
