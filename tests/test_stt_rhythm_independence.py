"""AF/AFL diagnoses must not alter ST/T source measurements or saved decisions."""
import copy
import json
from pathlib import Path
from uuid import uuid4

import pytest

from ecg_core.stt_records import METHOD, RHYTHM_POLICY, RANGE_PROFILE, review_metadata
from test_analysis_provenance import synthetic_case
from test_stt_continuous import st_app
from test_stt_hospital_records import api_case, payload

IDENTITY=('case_id','analysis_basis','analysis_revision','beat_revision')


def ok(response):
    assert response.status_code in (200,201),response.json
    return response.json


def numeric_range(client,base):
    measured=ok(client.get(base+'/stt-review'))
    value=ok(client.post(base+'/stt-range',json=dict(scope={k:measured[k] for k in IDENTITY},
        start_sample=120*200,end_sample=200*200,leads=['II','V5'],measurement_ms=80)))
    # A request still carries the real global concurrency revision. Its
    # numerical inputs and outputs must be independent of AF/AFL decisions.
    binding={k:v for k,v in value['binding'].items() if k!='scope_digest'}
    identity={k:v for k,v in value['server_identity'].items() if k!='analysis_revision'}
    return ({k:v for k,v in value.items() if k not in ('scope','server_identity','save_receipt','binding','result_digest')},binding,identity)


def adopt(client,base,receipt):
    report=ok(client.get(base+'/report'));eid=receipt['event_id'];basis=receipt['basis_version']
    pick=dict(event_id=eid,basis_version=basis,leads=['II'],duration_s=7,caption='医生原图注',notes='保留附注')
    blocks=[dict(key='ST:review:'+eid,text='医生独立ST判断',manual=True,needs_review=False,acknowledged=True),
            dict(key='ST:ST',text='保留ST自动文字',manual=False,needs_review=False,acknowledged=False)]
    composition={**report['composition'],'included_pages':['st_events','event_strips'],'selected_events':[pick],
        'stt_report_use':[dict(event_id=eid,basis_version=basis,table=True,text=True,strip=True)],
        'category_reviews':{'ST':basis},'diagnosis_blocks':blocks}
    saved=ok(client.put(base+'/report',json=dict(expected_version=report['version'],status='draft',
        conclusion='医生原结论',composition=composition)))
    return saved['composition']


@pytest.mark.parametrize('kind',['AF','AFL'])
def test_AF_AFL_lifecycle_keeps_ST_T_candidates_means_and_adopted_record_exact(st_app,kind):
    app,cid=st_app;client=app.test_client();base='/api/cases/'+cid
    measured=ok(client.get(base+'/stt-review'))
    candidate=next(c for c in measured['automatic_candidates']['items'] if c['kind']=='st_elevation' and c['leads']==['II'])
    p=payload(client,base,'st_elevation',review_extent='whole',end_sample=round(candidate['end_s']*200)-1,
        stt_candidate_id=candidate['id'],stt_candidate_scope={k:measured[k] for k in IDENTITY})
    p['sample_index']=round(candidate['start_s']*200)
    saved=ok(client.post(base+'/annotations',json=p));receipt=saved['stt_review_receipt'];eid=receipt['event_id']
    composition=adopt(client,base,receipt)
    before=ok(client.get(base+'/stt-review'))['analysis'];before_range=numeric_range(client,base)
    before_sections=ok(client.get(base+'/report-sections'))
    background=dict(id=str(uuid4()),start_s=2,end_s=10,kind=kind,status='pending',source='manual',note='保留原节律候选')
    selected=dict(id=str(uuid4()),start_s=20,end_s=240,kind=kind,status='pending',source='manual',note='独立节律判断')
    operations=[selected,{**selected,'start_s':40,'end_s':260},
        {**selected,'start_s':40,'end_s':260,'status':'confirmed'},
        {**selected,'status':'excluded'},{**selected,'status':'pending'},None]
    for episode in operations:
        current=ok(client.get(base+'/rhythm-review'))
        document=dict(episodes=[background]+([episode] if episode else []),bookmarks={})
        changed=ok(client.put(base+'/rhythm-review',json={**{k:current[k] for k in IDENTITY},
            'revision':current['revision'],'confirmed':True,'document':document}))
        assert changed['document']['episodes'][0]==background
        assert ok(client.get(base+'/stt-review'))['analysis']==before
        assert numeric_range(client,base)==before_range
        event=next(e for e in ok(client.get(base+'/report-events?category=ST'))['items'] if e['event_id']==eid)
        assert event['stt_review_state']=='reviewed' and event['basis_version']==receipt['basis_version']
        assert event['stt_report_eligibility']==dict(table=True,text=True,strip=True)
        current_report=ok(client.get(base+'/report'))
        assert current_report['composition']==composition and current_report['conclusion']=='医生原结论'
        sections=ok(client.get(base+'/report-sections'))
        for key in ('st_trends','st_events','t_events','st_summary','t_summary'):
            if key in before_sections:assert sections[key]==before_sections[key]
    stored=next(a for a in ok(client.get(base+'/annotations'))['items'] if a['id']==saved['id'])
    assert stored['details']==saved['details'] and stored['note']==saved['note']
    assert stored['details']['stt_event_evidence']['rhythm_policy']==RHYTHM_POLICY
    assert 'rhythm_exclusions_digest' not in stored['details']['stt_event_evidence']


@pytest.mark.parametrize('kind',['AF','AFL'])
@pytest.mark.parametrize('status',['pending','confirmed','excluded'])
def test_legacy_AF_annotation_create_delete_preserves_ST_text_and_review_state(api_case,kind,status):
    client,base=api_case
    saved=ok(client.post(base+'/annotations',json=payload(client,base,'indeterminate')))
    receipt=saved['stt_review_receipt'];eid=receipt['event_id'];report=ok(client.get(base+'/report'))
    blocks=[dict(key='ST:review:'+eid,text='医生原ST意见',manual=True,needs_review=False,acknowledged=True)]
    composition={**report['composition'],'diagnosis_blocks':blocks,'category_reviews':{'ST':receipt['basis_version']},
        'stt_report_use':[dict(event_id=eid,basis_version=receipt['basis_version'],table=False,text=True,strip=False)]}
    composition=ok(client.put(base+'/report',json=dict(expected_version=report['version'],status='draft',
        conclusion='保留原结论',composition=composition)))['composition']
    a=ok(client.post(base+'/annotations',json=dict(sample_index=1800,lead='全部',label='独立节律',note='保留AF原文',
        details=dict(kind=kind,status=status,end_sample=6000))))
    for deleting in (False,True):
        if deleting:assert client.delete('/api/annotations/'+str(a['id'])).status_code==200
        report=ok(client.get(base+'/report'));assert report['composition']==composition
        event=next(e for e in ok(client.get(base+'/report-events?category=ST'))['items'] if e['event_id']==eid)
        assert event['stt_review_state']=='reviewed' and event['basis_version']==receipt['basis_version']


def test_historical_protocol_is_never_relabelled_and_old_mask_method_requires_recheck():
    old=dict(method_version='stt-hospital-review-v1',measurement_ms=80,extent='point',baseline_method='manual_iso_point',
        units='source_device_units',calibration_verified=False)
    row=dict(id=1,sample_index=1000,lead='II',note='历史医生意见',details=dict(kind='ST',reviewed=True,
        result_code='st_depression',status='confirmed',end_sample=15000,measurement_protocol=old))
    receipt=review_metadata(row)
    assert receipt['measurement_protocol']==old and receipt['point_measurement_protocol']==old
    assert receipt['review_state']=='stale' and not any(receipt['report_eligibility'].values())
    assert row['details']['measurement_protocol']['method_version']=='stt-hospital-review-v1'
    row['details']['measurement_protocol']={**old,'method_version':METHOD,'rhythm_policy':RHYTHM_POLICY}
    assert review_metadata(row)['review_state']=='reviewed'
    row['details']['stt_event_evidence']=dict(rhythm_exclusions_digest='old-mask',measurement_protocol=copy.deepcopy(old))
    assert review_metadata(row)['review_state']=='stale'
    row['details']['measurement_protocol']['measurement_ms']=42
    assert review_metadata(row)['point_measurement_protocol'] is None


def test_saved_ST_true_beat_and_method_changes_still_expire_current_use(st_app):
    app,cid=st_app;client=app.test_client();base='/api/cases/'+cid
    p=payload(client,base,'st_elevation',review_extent='whole',end_sample=39999);p['sample_index']=24000
    saved=ok(client.post(base+'/annotations',json=p));eid=saved['stt_review_receipt']['event_id'];adopt(client,base,saved['stt_review_receipt'])
    current=ok(client.get(base+'/beat-editor'))
    ok(client.put(base+'/beat-editor',json=dict(operation='move',selection={'samples':[26000]},
        target_sample=26001,revision=current['revision'],confirmed=True)))
    event=next(e for e in ok(client.get(base+'/report-events?category=ST'))['items'] if e['event_id']==eid)
    assert event['stt_review_state']=='stale' and not any(event['stt_report_eligibility'].values())
    block=ok(client.get(base+'/report'))['composition']['diagnosis_blocks'][0]
    assert block['needs_review'] is True and block['acknowledged'] is False
    # A source-independent doctor record does not let an unknown method become current.
    store=app.extensions['storage']
    with store.connect() as db:
        details=copy.deepcopy(saved['details']);details['measurement_protocol']['method_version']='unknown-future-method'
        db.execute('UPDATE annotations SET details=? WHERE id=?',(json.dumps(details),saved['id']))
    changed=ok(client.get(base+'/annotations'))['items'][0]['stt_review_receipt']
    assert changed['point_measurement_protocol']['method_version']=='unknown-future-method'
    assert changed['review_state']=='stale'


def test_actual_source_change_invalidates_saved_ST_without_rewriting_original_record(st_app):
    app,cid=st_app;client=app.test_client();base='/api/cases/'+cid
    p=payload(client,base,'st_elevation',review_extent='whole',end_sample=39999);p['sample_index']=24000
    saved=ok(client.post(base+'/annotations',json=p));adopt(client,base,saved['stt_review_receipt'])
    original=copy.deepcopy(saved['details']);basis=saved['stt_review_receipt']['basis_version']
    path=Path(app.extensions['case_repository'].get_case(cid)['paths']['data'])
    with path.open('r+b') as stream:
        stream.seek(10*200*16);value=stream.read(1);stream.seek(-1,1);stream.write(bytes([value[0]^1]))
    row=next(a for a in ok(client.get(base+'/annotations'))['items'] if a['id']==saved['id'])
    assert row['details']==original and row['stt_review_receipt']['basis_version']==basis
    assert row['stt_review_receipt']['review_state']=='stale'
    assert not any(row['stt_review_receipt']['report_eligibility'].values())
    block=ok(client.get(base+'/report'))['composition']['diagnosis_blocks'][0]
    assert block['needs_review'] is True and block['acknowledged'] is False


def test_actual_flatline_remains_a_gap_even_when_AF_is_independent(st_app):
    app,cid=st_app;client=app.test_client();base='/api/cases/'+cid
    path=Path(app.extensions['case_repository'].get_case(cid)['paths']['data'])
    with path.open('r+b') as stream:
        stream.seek(128*200*16);stream.write(bytes(48*200*16))
    ok(client.post(base+'/annotations',json=dict(sample_index=20*200,lead='全部',label='独立AF候选',
        details=dict(kind='AF',status='pending',end_sample=260*200-1))))
    analysis=ok(client.get(base+'/stt-review'))['analysis']
    minute=next(p for p in analysis['trends']['leads']['II'] if p['start_s']==120)
    assert not minute['eligible'] and minute['t_amplitude_units'] is None
    assert 'flatline' in minute['quality_reasons'] and 'rhythm_exclusion' not in minute['quality_reasons']
    assert analysis['exclusions']['intervals']==[]
    assert not any(c['start_s']<144 and c['end_s']>160 for c in analysis['candidates'])


def test_actual_record_method_change_alone_is_stale_and_old_method_save_is_rejected(api_case):
    client,base=api_case;saved=ok(client.post(base+'/annotations',json=payload(client,base,'indeterminate')))
    cid=base.rsplit('/',1)[-1];store=client.application.extensions['storage']
    d=copy.deepcopy(saved['details']);d['measurement_protocol']['method_version']='unknown-future-method'
    with store.connect() as db:
        db.execute('UPDATE annotations SET details=? WHERE case_id=? AND id=?',(json.dumps(d),cid,saved['id']))
    receipt=next(a for a in ok(client.get(base+'/annotations'))['items'] if a['id']==saved['id'])['stt_review_receipt']
    assert receipt['review_state']=='stale' and receipt['measurement_protocol']['method_version']=='unknown-future-method'
    p=payload(client,base);p['details']['measurement_protocol']['method_version']='stt-hospital-review-v1'
    assert client.post(base+'/annotations',json=p).status_code==400
    assert len(store.list_annotations(cid))==1 and store.list_annotations(cid)[0]['details']==d


def test_RR_and_HRV_still_exclude_pending_and_confirmed_AF_AFL():
    from ecg_core.rr_quality import annotation_exclusions,nn_intervals
    from test_rr_quality import recording
    feed=recording([1000]*10);all_nn=nn_intervals(feed)
    for kind in ('AF','AFL'):
        for status in ('pending','confirmed','excluded'):
            annotations=[dict(sample_index=400,details=dict(kind=kind,status=status,end_sample=799))]
            feed.excluded_rhythm_intervals=annotation_exclusions(annotations)
            selected=nn_intervals(feed)
            assert (len(selected)==len(all_nn)) is (status=='excluded')
