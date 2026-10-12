"""Report-strip cache semantics through actual Flask routes and generated inputs.

Only imported synthetic fixtures are used; conftest's patient-backed client is
never requested. Reference results build a fresh uncached legacy index and read
all generated waveform values through the original prepare_strip interface.
"""
from array import array
from copy import deepcopy
from hashlib import sha256
import json
import sys

import pytest
import app as server
from ecg_core.beat_editor import BeatEditorStore, EditedRecords
from ecg_core.clinical_analysis import build_index as fresh_build_index
from ecg_core.ebi import load_records
from ecg_core.report_layout import prepare_strip as fresh_prepare_strip
from ecg_core.rr_quality import annotation_exclusions
from ecg_core.waveform import read_event_waveform as fresh_reader
from test_analysis_provenance import synthetic_case, synthetic_app, replace_preserving_mtime

IDENTITY=('case_id','analysis_basis','analysis_revision','beat_revision')


def ok(response,status=200):
    assert response.status_code==status,response.get_json()
    return response.get_json()


def spy_builds(monkeypatch):
    original=server.build_index;calls=[]
    def counted(*args,**kwargs):
        calls.append(1)
        return original(*args,**kwargs)
    monkeypatch.setattr(server,'build_index',counted)
    return calls


def candidates(client,base,**extra):
    return ok(client.get(base+'/report-events',query_string={'category':'fastest','limit':5,**extra}))


def strip_params(listing,event=None,**extra):
    event=event or listing['items'][0]
    return {**{k:listing[k] for k in IDENTITY},'event_id':event['event_id'],
            'basis_version':event['basis_version'],**extra}


def fresh_index(application,cid):
    case=application.extensions['case_repository'].get_case(cid)
    store=application.extensions['storage']
    document=BeatEditorStore(store).snapshot(cid)['document']
    feed=EditedRecords(load_records(case['paths']['ebi']),document,
                       store.list_beat_overrides(cid),case['technical']['duration_seconds_raw'])
    annotations=store.list_annotations(cid)
    feed.excluded_rhythm_intervals=annotation_exclusions(annotations)
    templates=store.list_beat_templates(cid);by_id={r['id']:r for r in feed.beats}
    with store.connect() as db:
        refs={r['template_id']:json.loads(r['beat_ids']) for r in db.execute(
            'SELECT * FROM beat_edit_template_refs WHERE case_id=?',(cid,))}
    for template in templates:
        template['sample_indices']=[by_id[k]['sample_index'] for k in refs.get(
            template['id'],[f's:{s}' for s in template['sample_indices']]) if k in by_id]
    index=fresh_build_index(feed,templates,annotations,store.get_review(cid))
    index['start_time']=case['metadata'].get('start_iso') or case['metadata'].get('start_time')
    return case,index


def cold_identity_and_event(application,client,base,cid):
    identity=ok(client.get(base+'/analysis-basis'))
    identity.update(case_id=cid,beat_revision=BeatEditorStore(application.extensions['storage']).snapshot(cid)['revision'])
    _,index=fresh_index(application,cid)
    event=next(e for e in index['events'] if e['category']=='fastest' and e['subtype']=='RR')
    return {**identity,'items':[event]},event


def reference_strip(application,cid,event,settings=None):
    case,index=fresh_index(application,cid)
    exact=next(e for e in index['events'] if e['event_id']==event['event_id'])
    assert exact['basis_version']==event['basis_version']
    value=fresh_prepare_strip(index,exact,settings or {},
        lambda start,end,leads,points:fresh_reader(case['paths']['data'],start,end,leads,points))
    return json.loads(json.dumps(value,allow_nan=False))


def assert_full_legacy_result(response,reference,listing):
    assert {key:response[key] for key in reference}==reference
    assert response['analysis_basis']==listing['analysis_basis']
    assert response['analysis_revision']==listing['analysis_revision']
    assert set(response)==set(reference)|{'analysis_basis','analysis_revision'}


def test_candidates_then_details_reuse_one_build(synthetic_app,synthetic_case,monkeypatch):
    calls=spy_builds(monkeypatch);client=synthetic_app.test_client();_,cid,_=synthetic_case;base=f'/api/cases/{cid}'
    listing=candidates(client,base)
    first=ok(client.get(base+'/report-strip',query_string=strip_params(listing)))
    second=ok(client.get(base+'/report-strip',query_string=strip_params(listing)))
    assert first==second and len(calls)==1
    assert_full_legacy_result(first,reference_strip(synthetic_app,cid,listing['items'][0]),listing)


def test_cold_detail_then_candidates_share_one_build(synthetic_app,synthetic_case,monkeypatch):
    calls=spy_builds(monkeypatch);client=synthetic_app.test_client();_,cid,_=synthetic_case;base=f'/api/cases/{cid}'
    identity,event=cold_identity_and_event(synthetic_app,client,base,cid)
    detail=ok(client.get(base+'/report-strip',query_string=strip_params(identity,event)))
    listing=candidates(client,base)
    assert len(calls)==1 and any(e['event_id']==event['event_id'] for e in listing['items'])
    assert_full_legacy_result(detail,reference_strip(synthetic_app,cid,event),listing)


@pytest.mark.parametrize('settings',[{}, {'leads':['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6'],'duration_s':1},
                                    {'leads':['II','V5'],'duration_s':10,'range_start_s':0,'range_end_s':8.005}])
def test_all_legacy_clinical_and_wave_values_match_varying_generated_signal(synthetic_app,synthetic_case,monkeypatch,settings):
    _,cid,paths=synthetic_case
    signal=array('h',((sample*11+channel*29)%2001-1000 for sample in range(18000) for channel in range(8)))
    if sys.byteorder!='little':signal.byteswap()
    paths['data'].write_bytes(signal.tobytes())
    hashes={key:sha256(path.read_bytes()).hexdigest() for key,path in paths.items()}
    calls=spy_builds(monkeypatch);client=synthetic_app.test_client();base=f'/api/cases/{cid}'
    listing=candidates(client,base);event=listing['items'][0]
    query={'leads':','.join(settings.get('leads',['II','V1','V5'])),'duration':settings.get('duration_s',7)}
    query.update({k:settings[k] for k in ('range_start_s','range_end_s') if k in settings})
    detail=ok(client.get(base+'/report-strip',query_string=strip_params(listing,event,**query)))
    assert_full_legacy_result(detail,reference_strip(synthetic_app,cid,event,settings),listing)
    assert any(value!=0 for values in detail['waveform']['leads'].values() for value in values)
    assert len(calls)==1 and {key:sha256(path.read_bytes()).hexdigest() for key,path in paths.items()}==hashes


def test_server_payload_mutation_does_not_poison_cached_index(synthetic_app,synthetic_case,monkeypatch):
    calls=spy_builds(monkeypatch);client=synthetic_app.test_client();_,cid,_=synthetic_case;base=f'/api/cases/{cid}'
    listing=candidates(client,base);params=strip_params(listing);original=server.jsonify;payloads=[]
    def capture(*args,**kwargs):
        response=original(*args,**kwargs)
        for value in args:
            if isinstance(value,dict) and {'event_id','strip','waveform'}<=set(value):payloads.append(value)
        return response
    monkeypatch.setattr(server,'jsonify',capture)
    first=ok(client.get(base+'/report-strip',query_string=params))
    assert len(payloads)==1
    # This is the actual server-side payload after cache projection, not the
    # inherently detached client.json copy or the trusted internal projector.
    payloads[0]['target_samples'].append(-123)
    payloads[0]['templates'].append({'id':'poison','name':'changed synthetic template'})
    payloads[0]['strip']['visible_beats'][0]['sample_index']=-456
    payloads[0]['waveform']['leads']['II'][0]=999999
    second=ok(client.get(base+'/report-strip',query_string=params))
    assert second==first and len(calls)==1
    assert candidates(client,base)==listing
    assert_full_legacy_result(second,reference_strip(synthetic_app,cid,listing['items'][0]),listing)


@pytest.mark.parametrize('change',['source-data','source-ebi','source-lps','beat','annotation','global-review'])
def test_changed_source_or_review_rejects_old_scope_and_rebuilds(synthetic_app,synthetic_case,monkeypatch,change):
    calls=spy_builds(monkeypatch);client=synthetic_app.test_client();_,cid,paths=synthetic_case;base=f'/api/cases/{cid}'
    listing=candidates(client,base);old=strip_params(listing)
    ok(client.get(base+'/report-strip',query_string=old));assert len(calls)==1
    if change.startswith('source-'):
        path=paths[change.split('-')[1]];content=path.read_bytes()
        content=content.replace(b'08:00:00',b'08:01:00') if change=='source-lps' else b'\1'+content[1:]
        replace_preserving_mtime(path,content)
    elif change=='beat':
        ok(client.put(base+'/beat-editor',json=dict(operation='move',selection={'samples':[2000]},target_sample=2001,revision=0,confirmed=True)))
    elif change=='annotation':
        ok(client.post(base+'/annotations',json=dict(sample_index=2000,lead='II',label='Synthetic ST annotation',
                    details={'kind':'ST','status':'confirmed','end_sample':2400})),201)
    else:synthetic_app.extensions['storage'].audit('synthetic','beat_override.editor',cid)
    assert client.get(base+'/report-strip',query_string=old).status_code==409
    assert len(calls)==1
    current=candidates(client,base)
    assert len(calls)==2
    fresh=ok(client.get(base+'/report-strip',query_string=strip_params(current)))
    assert len(calls)==2
    assert_full_legacy_result(fresh,reference_strip(synthetic_app,cid,current['items'][0]),current)
    assert any(current[k]!=listing[k] for k in ('analysis_basis','analysis_revision'))


def test_identical_case_bytes_do_not_share_cache_or_accept_foreign_scope(synthetic_app,synthetic_case,monkeypatch):
    calls=spy_builds(monkeypatch);client=synthetic_app.test_client();root,cid,paths=synthetic_case;base=f'/api/cases/{cid}'
    first=candidates(client,base);other='8888888888888888'
    for path in paths.values():
        relative=path.relative_to(root/cid);target=root/other/relative.parent/relative.name.replace(cid,other)
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(path.read_bytes())
    other_base=f'/api/cases/{other}'
    assert client.get(other_base+'/report-strip',query_string=strip_params(first)).status_code==409
    assert len(calls)==1
    second=candidates(client,other_base)
    assert second['analysis_basis']==first['analysis_basis'] and second['case_id']!=first['case_id']
    ok(client.get(other_base+'/report-strip',query_string=strip_params(second)))
    ok(client.get(base+'/report-strip',query_string=strip_params(first)))
    assert len(calls)==2


def test_fake_targets_and_invalid_linked_scope_never_resolve_nearest_event(synthetic_app,synthetic_case,monkeypatch):
    calls=spy_builds(monkeypatch);client=synthetic_app.test_client();_,cid,_=synthetic_case;base=f'/api/cases/{cid}'
    listing=candidates(client,base);params=strip_params(listing)
    bad=[{'event_id':'absent-event'}, {'basis_version':'old-event-basis'}, {'case_id':'different-synthetic-case'},
         {'analysis_basis':'f'*64}, {'analysis_revision':listing['analysis_revision']+1},
         {'beat_revision':listing['beat_revision']+1}, {'revision':listing['beat_revision']+1}]
    for change in bad:assert client.get(base+'/report-strip',query_string={**params,**change}).status_code==409
    for value in ('true','-1','1.0','１'):
        assert client.get(base+'/report-strip',query_string={**params,'beat_revision':value}).status_code==400
    assert len(calls)==1
    ok(client.get(base+'/report-strip',query_string=params));assert len(calls)==1


@pytest.mark.parametrize('stage',['build','cached-projection','wave-source'])
def test_guard_rechecks_after_build_projection_and_wave_read(synthetic_app,synthetic_case,monkeypatch,stage):
    calls=spy_builds(monkeypatch);client=synthetic_app.test_client();_,cid,paths=synthetic_case;base=f'/api/cases/{cid}'
    identity,event=cold_identity_and_event(synthetic_app,client,base,cid)
    store=synthetic_app.extensions['storage']
    if stage=='build':
        original=server.build_index
        def racing(*args,**kwargs):
            result=original(*args,**kwargs);store.audit('synthetic','beat_override.editor',cid);return result
        monkeypatch.setattr(server,'build_index',racing)
    elif stage=='cached-projection':
        identity=candidates(client,base);cache=synthetic_app.extensions['clinical_query_cache'];original=cache.project
        def racing(*args,**kwargs):
            result=original(*args,**kwargs);store.audit('synthetic','beat_override.editor',cid);return result
        monkeypatch.setattr(cache,'project',racing)
    else:
        identity=candidates(client,base);original=server.read_event_waveform;changed=[]
        def racing(*args,**kwargs):
            result=original(*args,**kwargs)
            if not changed:
                changed.append(1);content=paths['data'].read_bytes();replace_preserving_mtime(paths['data'],b'\1'+content[1:])
            return result
        monkeypatch.setattr(server,'read_event_waveform',racing)
    response=client.get(base+'/report-strip',query_string=strip_params(identity,event))
    assert response.status_code==409 and 'waveform' not in response.json
    assert len(calls)==1 and synthetic_app.extensions['clinical_query_cache'].retention()['pending']==0
    if stage=='build':assert synthetic_app.extensions['clinical_query_cache'].retention()['entries']==0


@pytest.mark.parametrize('operation',['save','pdf'])
def test_warm_read_cache_never_bypasses_fresh_save_or_export_guard(synthetic_app,synthetic_case,monkeypatch,operation):
    calls=spy_builds(monkeypatch);client=synthetic_app.test_client();_,cid,_=synthetic_case;base=f'/api/cases/{cid}'
    listing=candidates(client,base);ok(client.get(base+'/report-strip',query_string=strip_params(listing)))
    report=ok(client.get(base+'/report'));composition=deepcopy(report['composition'])
    composition.update(included_pages=['summary','event_strips'],active_page='summary',
                       selected_events=[{'event_id':listing['items'][0]['event_id'],'basis_version':listing['items'][0]['basis_version']}],
                       hrv_review_reference=report['current_hrv_reference'])
    saved=ok(client.put(base+'/report',json=dict(expected_version=report['version'],
             expected_review_revision=report['review_revision'],status='draft',conclusion='Synthetic preserved draft',composition=composition)))
    assert len(calls)>=2
    count_before=len(calls);store=synthetic_app.extensions['storage'];original=server.build_index;entered=[]
    with store.connect() as db:
        audits_before=db.execute("SELECT COUNT(*) FROM audit_log WHERE action IN ('report.draft','report.export_pdf')").fetchone()[0]
    def racing(*args,**kwargs):
        result=original(*args,**kwargs)
        if not entered:entered.append(1);store.audit('synthetic','beat_override.editor',cid)
        return result
    monkeypatch.setattr(server,'build_index',racing)
    if operation=='save':
        response=client.put(base+'/report',json=dict(expected_version=saved['version'],expected_review_revision=saved['review_revision'],
                     status='draft',conclusion='This attempted new text must not commit',composition=saved['composition']))
    else:response=client.get(base+'/report.pdf',query_string={'expected_version':saved['version'],'expected_review_revision':saved['review_revision']})
    assert response.status_code==409 and entered and len(calls)>count_before
    assert not response.data.startswith(b'%PDF')
    with store.connect() as db:
        row=db.execute('SELECT conclusion FROM report_drafts WHERE case_id=?',(cid,)).fetchone()
        audits_after=db.execute("SELECT COUNT(*) FROM audit_log WHERE action IN ('report.draft','report.export_pdf')").fetchone()[0]
    assert row[0]=='Synthetic preserved draft' and audits_after==audits_before


def test_nonempty_stable_template_refs_and_legacy_memberships_match_fresh_strip(synthetic_app,synthetic_case,monkeypatch):
    client=synthetic_app.test_client();_,cid,paths=synthetic_case;base=f'/api/cases/{cid}'
    hashes={key:sha256(path.read_bytes()).hexdigest() for key,path in paths.items()}
    ok(client.put(base+'/beat-editor',json=dict(operation='relabel',selection={'samples':[6000]},class_code='V',revision=0,confirmed=True)))
    bound=ok(client.post(base+'/beat-templates?analysis=edited',json=dict(name='Synthetic stable template',rhythm_family='自定义',lead='II',sample_indices=[6000])),201)
    ok(client.put(base+'/beat-editor',json=dict(operation='move',selection={'samples':[6000]},target_sample=6001,revision=1,confirmed=True)))
    legacy=synthetic_app.extensions['storage'].create_beat_template(cid,
        dict(name='Synthetic legacy template',rhythm_family='自定义',lead='II',sample_indices=[6200]),'synthetic')
    calls=spy_builds(monkeypatch)
    ventricular=candidates(client,base,category='V');event=ventricular['items'][0]
    assert event['sample_index']==6001 and event['templates']==[{'id':str(bound['id']),'name':bound['name']}]
    first=ok(client.get(base+'/report-strip',query_string=strip_params(ventricular,event)))
    assert_full_legacy_result(first,reference_strip(synthetic_app,cid,event),ventricular)
    fastest=candidates(client,base);event=next(e for e in fastest['items'] if e['sample_index']==6200)
    assert event['templates']==[{'id':str(legacy['id']),'name':legacy['name']}]
    second=ok(client.get(base+'/report-strip',query_string=strip_params(fastest,event)))
    assert_full_legacy_result(second,reference_strip(synthetic_app,cid,event),fastest)
    assert len(calls)==1 and {key:sha256(path.read_bytes()).hexdigest() for key,path in paths.items()}==hashes


def test_cached_event_index_does_not_cache_main_or_context_waveforms(synthetic_app,synthetic_case,monkeypatch):
    builds=spy_builds(monkeypatch);client=synthetic_app.test_client();_,cid,_=synthetic_case;base=f'/api/cases/{cid}'
    listing=candidates(client,base);original=server.read_event_waveform;reads=[]
    def counted(*args,**kwargs):
        reads.append((args[1],args[2],tuple(args[3]),args[4]))
        return original(*args,**kwargs)
    monkeypatch.setattr(server,'read_event_waveform',counted)
    for duration in (7,9):
        response=ok(client.get(base+'/report-strip',query_string=strip_params(listing,duration=duration)))
        assert_full_legacy_result(response,reference_strip(synthetic_app,cid,listing['items'][0],{'duration_s':duration}),listing)
    assert len(builds)==1 and len(reads)==4
    assert [row[2] for row in reads]==[('II','V1','V5'),('II',),('II','V1','V5'),('II',)]
    assert reads[0][1]-reads[0][0]==7 and reads[2][1]-reads[2][0]==9
