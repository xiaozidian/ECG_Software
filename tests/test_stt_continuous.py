"""Continuous duration is separate from minute evidence and short report strips."""
import copy
import json
from pathlib import Path
import subprocess
import numpy as np
import pytest
from app import create_app
from ecg_core.stt import DEFAULT_CONFIG, _lead_episodes, _merge_episodes, minute_trends
from ecg_core.ebi import HEADER_SIZE, RECORD
from ecg_core.report_sections import evidence, st_report_events
from ecg_core.report_sections_pdf import documents
from ecg_core.report_layout import resolve_strip
from test_report_layout import index_for
from test_analysis_provenance import synthetic_case


def point(start,end,value=130,**extra):
    return dict(start_s=start,end_s=end,time_s=(start+end)/2,deviation_units=value,
        t_amplitude_units=100,eligible=True,quality_score=.9,axis_shift_suspected=False,**extra)


@pytest.mark.parametrize('seconds,found',[(59,False),(60,True),(61,True)])
def test_target_minimum_is_continuous_time_not_point_count(seconds,found):
    rows=[point(0,seconds)]
    result=_lead_episodes(rows,'II',DEFAULT_CONFIG)
    assert bool(result)==found
    if found:assert result[0]['duration_s']==seconds and result[0]['continuous_target_s']==seconds


def test_weak_values_cannot_sum_short_target_runs_to_sixty_seconds():
    rows=[point(0,32),point(32,48,70),point(48,80)]
    assert _lead_episodes(rows,'II',DEFAULT_CONFIG)==[]
    # A true continuous target run survives short normal hysteresis, but its
    # peak target support is not increased by the normal interval.
    rows=[point(0,64),point(64,80,0),point(80,96,70),point(96,128,0)]
    result=_lead_episodes(rows,'II',DEFAULT_CONFIG)
    assert len(result)==1 and result[0]['end_s']==96 and result[0]['continuous_target_s']==64


@pytest.mark.parametrize('fault',[{'eligible':False},{'axis_shift_suspected':True},{'deviation_units':None}])
def test_quality_or_missing_cuts_and_never_remerges(fault):
    bad=point(64,80);bad.update(fault)
    result=_lead_episodes([point(0,64),bad,point(80,144)],'II',DEFAULT_CONFIG)
    merged=_merge_episodes(result)
    assert [(r['start_s'],r['end_s']) for r in merged]==[(0,64),(80,144)]
    other=_lead_episodes([point(48,112)],'V5',DEFAULT_CONFIG)
    assert len(_merge_episodes(result+other))==3


def test_hour_boundaries_do_not_split_and_source_tail_uses_actual_support():
    result=_lead_episodes([point(3584,3600),point(3600,3616),point(3616,3632),point(3632,3650)],'II',DEFAULT_CONFIG)
    assert [(r['start_s'],r['end_s'],r['duration_s']) for r in result]==[(3584,3650,66)]


def test_minute_evidence_weights_real_overlap_keeps_zero_and_missing_distinct():
    rows=[point(0,16,0),point(16,32,100),point(32,48,100),point(48,64,100),point(64,80,0)]
    result=minute_trends(rows,80,DEFAULT_CONFIG)
    assert len(result)==2 and result[0]['deviation_units']==73.33 and result[1]['deviation_units']==20
    bad=copy.deepcopy(rows);bad[1]['eligible']=False
    missing=minute_trends(bad,80,DEFAULT_CONFIG)
    assert missing[0]['deviation_units'] is None and missing[0]['coverage_pct']==73.33
    assert missing[0]['partial_deviation_units'] is not None
    whole_day=[point(start,min(start+16,86400),0) for start in range(0,86400,16)]
    minutes=minute_trends(whole_day,86400,DEFAULT_CONFIG)
    assert len(minutes)==1440 and all(p['deviation_units']==0 for p in minutes)


@pytest.fixture
def st_app(synthetic_case,tmp_path):
    root,cid,paths=synthetic_case;duration=320
    samples=np.arange(duration*200);phase=samples%200;second=samples//200
    values=np.where(phase==0,900,np.where(phase==1,600,np.where(phase==2,250,np.where(phase==3,80,0))))
    values=values+np.where((phase>=55)&(phase<=62),180,0)
    values=values+np.where((second>=120)&(second<205)&(phase>=18)&(phase<=44),130,0)
    paths['data'].write_bytes(np.repeat(values[:,None],8,axis=1).astype('<i2').tobytes())
    paths['ebi'].write_bytes(bytes(HEADER_SIZE)+b''.join(RECORD.pack(i*200,1,1,0,0,0,1000) for i in range(1,duration)))
    return create_app(data_root=root,db_path=tmp_path/'st-case.db',testing=True),cid


def test_candidate_full_range_save_report_event_table_and_short_peak_strip(st_app):
    app,cid=st_app;client=app.test_client();base=f'/api/cases/{cid}'
    measured=client.get(base+'/stt-review').json
    candidate=next(c for c in measured['automatic_candidates']['items'] if c['kind']=='st_elevation' and c['leads']==['II'])
    scope={k:measured[k] for k in ('case_id','analysis_basis','analysis_revision','beat_revision')}
    payload=dict(sample_index=round(candidate['start_s']*200),lead='II',category='note',label='ST 整段复核',note='数学验证',
        details=dict(kind='ST',status='confirmed',finding='ST 段抬高候选',end_sample=round(candidate['end_s']*200)-1,
            stt_candidate_id=candidate['id'],stt_candidate_scope=scope))
    bad=copy.deepcopy(payload);bad['details']['end_sample']-=200
    assert client.post(base+'/annotations',json=bad).status_code==400
    forged=copy.deepcopy(payload);forged['details']['stt_event_evidence']={}
    assert client.post(base+'/annotations',json=forged).status_code==400
    saved=client.post(base+'/annotations',json=payload)
    assert saved.status_code==201,saved.json
    proof=saved.json['details']['stt_event_evidence']
    assert proof['duration_s']==candidate['duration_s'] and proof['duration_s']>60
    event=client.get(base+'/report-events?category=ST').json['items'][0]
    assert event['end_s']-event['time_s']==candidate['duration_s'] and event['diagnosis_status']=='confirmed'
    wave=client.get(base+'/report-strip',query_string={'event_id':event['event_id'],'basis_version':event['basis_version'],'duration':7}).json
    assert wave['strip']['actual_duration_s']==7
    assert wave['strip']['start_s']<=candidate['peak_time_s']<wave['strip']['end_s']
    assert event['end_s']-event['time_s']>wave['strip']['actual_duration_s']
    sections=client.get(base+'/report-sections').json
    assert any(r['event_id']==event['event_id'] for r in sections['st_events'])
    pick={'event_id':event['event_id'],'basis_version':event['basis_version']}
    docs=documents({'metadata':{}},{'section_evidence':sections,'composition':{'selected_events':[pick]}},['st_events'])
    assert any(f"{candidate['duration_s']:g}" in row for doc in docs for row in doc['rows'])
    assert not any('自动筛查候选清单' in text for doc in docs for text in doc['paragraphs'])
    # Global final-review gate still exists after the individual event review.
    report=client.get(base+'/report').json
    response=client.put(base+'/report',json={'expected_version':report['version'],'status':'reviewed','conclusion':'数学验证',
        'composition':{'page_selection_version':1,'included_pages':['st_events'],'selected_events':[pick]}})
    assert response.status_code in (400,409) and '报告审核前请确认' in response.json['error']


def test_legacy_point_and_range_means_remain_notes_not_continuous_events():
    index=index_for(list(range(100)),duration=100)
    index['events']+=[dict(event_id='legacy-point',basis_version='old',category='ST',diagnosis_status='confirmed',
        time_s=10,end_s=20,label='旧ST点复核'),dict(event_id='legacy-mean',basis_version='old',category='ST',
        diagnosis_status='confirmed',time_s=0,end_s=80,label='范围均值',range_statistics={'range':{}})]
    result=evidence(index)
    assert result['st_events']==[] and len(result['st_review_notes'])==2
    assert [p['review_kind'] for p in result['st_review_notes']]==['point_or_legacy_range','range_mean']
    report={'composition':{'selected_events':[{'event_id':'legacy-point','basis_version':'old'},{'event_id':'legacy-mean','basis_version':'old'}]},'section_evidence':result}
    docs=documents({'metadata':{}},report,['st_events'])
    assert any('不证明连续' in row for doc in docs for row in doc['rows'])
