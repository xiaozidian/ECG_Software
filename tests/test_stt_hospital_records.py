"""Hospital ST/T review: independent mathematical records, no real cases/PDF."""
import copy
from uuid import uuid4
import pytest
from app import create_app
from ecg_core.stt_records import RESULTS,time_groups,use_for
from ecg_core.clinical_analysis import build_index,query_index,validate_report
from ecg_core.report_sections import evidence,st_summary
from ecg_core.stt import minute_trends,DEFAULT_CONFIG,_lead_episodes
from test_analysis_provenance import synthetic_case
from test_stt_continuous import st_app
from test_report_layout import index_for


@pytest.fixture
def api_case(synthetic_case,tmp_path):
    root,cid,_=synthetic_case
    return create_app(data_root=root,db_path=tmp_path/'stt-records.sqlite3',testing=True).test_client(),'/api/cases/'+cid


def payload(client,base,code='no_change',**changes):
    scope=client.get(base+'/stt-review').json
    d=dict(kind='ST',reviewed=True,result_code=code,finding=code,submission_id=str(uuid4()),
           end_sample=3999,review_scope={k:scope[k] for k in ('case_id','analysis_basis','analysis_revision','beat_revision')},
           review_leads=['II'],review_extent='point',measurement_protocol=dict(measurement_ms=60,extent='point'),physician_note='数学医生备注')
    d.update(changes)
    return dict(sample_index=2000,lead='II',category='note',label='数学ST-T复核',note='数学测量及备注',details=d)


@pytest.mark.parametrize('code',RESULTS)
def test_every_saved_decision_is_visible_and_completed_indeterminate_is_not_unreviewed(api_case,code):
    client,base=api_case;p=payload(client,base,code)
    r=client.post(base+'/annotations',json=p);assert r.status_code==201,r.json
    receipt=r.json['stt_review_receipt'];assert receipt['review_state']=='reviewed' and receipt['result_code']==code
    assert receipt['report_eligibility']==dict(table=False,text=True,strip=True)
    rows=client.get(base+'/report-events?category=ST&stt_group=all').json['items'];assert len(rows)==1
    assert rows[0]['event_id']==receipt['event_id'] and rows[0]['stt_review_state']=='reviewed'
    history=client.get(base+'/stt-review').json['review_records'];assert history[0]['stt_review_receipt']['basis_version']==receipt['basis_version']
    sections=client.get(base+'/report-sections').json
    assert sections['st_summary']['confirmed_lead_event_count']==0 and sections['t_summary']['confirmed_lead_event_count']==0


def test_UUID_replay_unrelated_record_keeps_basis_and_source_scope_is_still_required(api_case):
    client,base=api_case;p=payload(client,base)
    first=client.post(base+'/annotations',json=p);assert first.status_code==201
    repeated=client.post(base+'/annotations',json=p);assert repeated.status_code==201 and repeated.json['id']==first.json['id']
    assert len(client.get(base+'/annotations').json['items'])==1
    other=client.post(base+'/annotations',json=payload(client,base,'indeterminate'));assert other.status_code==201
    original=next(e for e in client.get(base+'/report-events?category=ST').json['items'] if e['event_id']==first.json['stt_review_receipt']['event_id'])
    assert original['basis_version']==first.json['stt_review_receipt']['basis_version']
    changed=copy.deepcopy(p);changed['note']='同UUID不同内容'
    assert client.post(base+'/annotations',json=changed).status_code==409
    wrong=payload(client,base);wrong['details']['review_scope']['analysis_basis']='wrong'
    assert client.post(base+'/annotations',json=wrong).status_code==409


def test_update_withdraws_only_own_uses_retains_curation_and_replay_never_recreates(api_case):
    client,base=api_case;p=payload(client,base);first=client.post(base+'/annotations',json=p).json;receipt=first['stt_review_receipt']
    draft=client.get(base+'/report').json
    pick=dict(event_id=receipt['event_id'],basis_version=receipt['basis_version'],caption='保留医生图注',notes='保留附注',leads=['II'],duration_s=7,print_enabled=False)
    use=dict(event_id=receipt['event_id'],basis_version=receipt['basis_version'],table=False,text=True,strip=False)
    save=client.put(base+'/report',json=dict(expected_version=draft['version'],status='draft',conclusion='数学结论',composition={**draft['composition'],'selected_events':[pick],'stt_report_use':[use]}));assert save.status_code==200,save.json
    edit=payload(client,base,'indeterminate',end_sample=4199);edit['sample_index']=2200;edit['expected_record_version']=1
    bad=copy.deepcopy(edit);bad['expected_record_version']=99
    assert client.put(base+'/annotations/'+str(first['id']),json=bad).status_code==409
    updated=client.put(base+'/annotations/'+str(first['id']),json=edit);assert updated.status_code==200,updated.json
    r=updated.json['stt_review_receipt'];assert r['record_version']==2 and r['range']['start_sample']==2200
    assert r['report_reconciliation']['removed_selections'][0]['caption']=='保留医生图注'
    assert client.get(base+'/report').json['composition']['selected_events']==[]
    assert client.get(base+'/report').json['composition']['stt_report_use']==[]
    again=client.put(base+'/annotations/'+str(first['id']),json=edit);assert again.status_code==200 and again.json['stt_review_receipt']['record_version']==2
    late=client.post(base+'/annotations',json=p);assert late.status_code==201 and late.json['id']==first['id']
    assert len(client.get(base+'/annotations').json['items'])==1


def test_legacy_excluded_pending_are_visible_not_promoted():
    index=index_for(list(range(100)),duration=100)
    # Build the real index from its row representation.
    from types import SimpleNamespace
    feed=SimpleNamespace(beats=index['rows'],markers=[],duration=100,document={'settings':dict(nn_min=300,nn_max=2000,pause=2.5,tachy=120,brady=50)})
    annotations=[dict(id=i,sample_index=1000,lead='II',details=dict(kind='ST',status=status,finding='未见明确动态ST-T改变' if status=='excluded' else '无法判读',end_sample=3000)) for i,status in enumerate(('excluded','pending'),1)]
    current=build_index(feed,annotations=annotations);rows=query_index(current,{'category':'ST'})['items'];assert len(rows)==2
    assert all(e['stt_review_state']=='unreviewed' and e['diagnosis_status']=='pending' for e in rows)
    assert st_summary([])['confirmed_time_group_count']==0


def test_minute_level_delta_T_and_gaps_are_independent():
    rows=[dict(start_s=a,end_s=b,time_s=(a+b)/2,eligible=True,quality_score=.9,axis_shift_suspected=False,
        st_level_units=20,reference_units=100,deviation_units=-80,t_amplitude_units=-50,t_reference_units=70) for a,b in [(0,16),(16,32),(32,48),(48,60)]]
    minute=minute_trends(rows,60,DEFAULT_CONFIG)[0]
    assert (minute['st_level_units'],minute['reference_units'],minute['deviation_units'],minute['t_amplitude_units'])==(20,100,-80,-50)
    rows[1]['eligible']=False
    bad=minute_trends(rows,60,DEFAULT_CONFIG)[0]
    assert all(bad[k] is None for k in ('st_level_units','reference_units','deviation_units','t_amplitude_units'))
    assert bad['partial_st_level_units']==20 and bad['lead_availability']=='unavailable'


def test_three_lead_rows_one_time_group_union_not_sum_and_touching_is_not_overlap():
    rows=[dict(event_id='one',row_id='one:'+lead,lead=lead,start_s=a,end_s=b,kind='st_depression',measurement_protocol={'measurement_ms':60}) for lead,a,b in [('II',0,180),('III',60,240),('aVF',100,200)]]
    s=st_summary(rows);assert s['confirmed_lead_event_count']==3 and s['confirmed_time_group_count']==1
    assert s['confirmed_union_duration_s']==240 and len(s['groups'][0]['child_event_ids'])==3
    rows.append(dict(rows[0],event_id='two',row_id='two:II',start_s=240,end_s=300))
    assert len(time_groups(rows))==2


def test_indeterminate_completed_may_be_used_but_unreviewed_and_stale_are_rejected(api_case):
    client,base=api_case;r=client.post(base+'/annotations',json=payload(client,base,'indeterminate')).json['stt_review_receipt']
    event=client.get(base+'/report-events?category=ST').json['items'][0]
    index={'events':[event],'rows':[],'duration_s':90}
    comp={'stt_report_use':[dict(event_id=r['event_id'],basis_version=r['basis_version'],table=False,text=True,strip=False)]}
    assert validate_report(index,comp,{},True)==[]
    event['stt_review_state']='stale'
    with pytest.raises(ValueError,match='复核|失效'):validate_report(index,comp,{},True)


def test_whole_machine_protocol_and_attached_mean_dont_replace_event_range(st_app):
    app,cid=st_app;client=app.test_client();base='/api/cases/'+cid
    measured=client.get(base+'/stt-review').json
    candidate=next(c for c in measured['automatic_candidates']['items'] if c['kind']=='st_elevation' and c['leads']==['II'])
    p=payload(client,base,'st_elevation',review_extent='whole',measurement_protocol=dict(measurement_ms=80,extent='point'),
        stt_candidate_id=candidate['id'],stt_candidate_scope={k:measured[k] for k in ('case_id','analysis_basis','analysis_revision','beat_revision')},end_sample=round(candidate['end_s']*200)-1)
    p['sample_index']=round(candidate['start_s']*200)
    attached=client.post(base+'/stt-range',json=dict(scope=p['details']['review_scope'],start_sample=p['sample_index']+200,end_sample=p['details']['end_sample']-200,leads=['II'],measurement_ms=80))
    assert attached.status_code==200,attached.json
    p['details']['range_statistics']=attached.json
    r=client.post(base+'/annotations',json=p);assert r.status_code==201,r.json
    receipt=r.json['stt_review_receipt'];assert receipt['measurement_protocol']['measurement_ms']==60 and receipt['point_measurement_protocol']['measurement_ms']==80
    assert receipt['range']['duration_s']==candidate['duration_s'] and receipt['report_eligibility']['table']
    response=client.get(base+'/report-sections');assert response.status_code==200,response.json
    sections=response.json;assert len(sections['st_events'])==1
    row=sections['st_events'][0];assert row['mean_st_level_units'] is not None and row['used_beat_count']>7
    # The raw plateau is130u at ST80 versus0u at J, over80ms.
    assert row['slope']==pytest.approx(130/.08) and row['slope_unit']=='u/s'
    assert row['calibrated_mm'] is None
    assert sections['st_summary']['confirmed_lead_event_count']==1
    assert r.json['details']['range_statistics']['range']['start_sample']!=r.json['sample_index']
    assert r.json['details']['range_statistics']['method_profile']['measurement_ms']==80
    assert sections['heart_rate_trend'] and sections['st_representatives']
    assert all(x['waveform']['sample_rate_hz']==200 and x['waveform']['leads'].get('II') for x in sections['st_representatives'])


def test_active_uses_only_gate_actual_enabled_pages_and_print_enabled_strips(api_case):
    client,base=api_case;receipt=client.post(base+'/annotations',json=payload(client,base,'indeterminate')).json['stt_review_receipt']
    event=client.get(base+'/report-events?category=ST').json['items'][0]
    index={'events':[event],'rows':[],'duration_s':90}
    use=dict(event_id=receipt['event_id'],basis_version='stale',table=True,text=False,strip=False)
    comp=dict(page_selection_version=1,included_pages=['st_trend'],stt_report_use=[use])
    assert validate_report(index,comp,{},True)==[]
    comp['included_pages']=['st_events']
    with pytest.raises(ValueError,match='依据'):validate_report(index,comp,{},True)
    use.update(table=False,strip=True,basis_version=receipt['basis_version']);comp['included_pages']=['event_strips']
    with pytest.raises(ValueError,match='不存在'):validate_report(index,comp,{},True)
    comp['selected_events']=[dict(event_id=event['event_id'],basis_version='stale',print_enabled=False)]
    assert validate_report(index,comp,{},True)==[]
    use.update(strip=False,text=True)
    assert validate_report(index,comp,{},True)==[]
    event['stt_review_state']='unreviewed'
    with pytest.raises(ValueError,match='复核'):validate_report(index,comp,{},True)


def test_relevant_and_unrelated_rhythm_decisions_do_not_invalidate_ST_statistics(st_app):
    app,cid=st_app;client=app.test_client();base='/api/cases/'+cid
    p=payload(client,base,'st_elevation',review_extent='whole',end_sample=39999);p['sample_index']=24000
    first=client.post(base+'/annotations',json=p);assert first.status_code==201,first.json
    eid=first.json['stt_review_receipt']['event_id'];basis=first.json['stt_review_receipt']['basis_version']
    def event():return next(e for e in client.get(base+'/report-events?category=ST').json['items'] if e['event_id']==eid)
    unrelated=dict(sample_index=50000,lead='全部',category='note',label='数学房颤',note='',details=dict(kind='AF',status='pending',end_sample=52000))
    assert client.post(base+'/annotations',json=unrelated).status_code==201
    assert event()['stt_review_state']=='reviewed' and event()['basis_version']==basis
    relevant=copy.deepcopy(unrelated);relevant['sample_index']=28000;relevant['details']['end_sample']=30000
    assert client.post(base+'/annotations',json=relevant).status_code==201
    assert event()['stt_review_state']=='reviewed' and event()['stt_report_eligibility']['table']
    assert event()['basis_version']==basis


def test_update_retains_previous_settings_for_reselection_and_deleted_UUID_does_not_recreate(api_case):
    client,base=api_case;first_payload=payload(client,base);first=client.post(base+'/annotations',json=first_payload).json;r=first['stt_review_receipt']
    draft=client.get(base+'/report').json
    pick=dict(event_id=r['event_id'],basis_version=r['basis_version'],caption='图注',notes='医生备注',leads=['II'],duration_s=7)
    assert client.put(base+'/report',json=dict(expected_version=draft['version'],status='draft',conclusion='数学结论',composition={**draft['composition'],'selected_events':[pick]})).status_code==200
    edit=payload(client,base,'indeterminate');edit['expected_record_version']=1
    saved=client.put(base+'/annotations/'+str(first['id']),json=edit);assert saved.status_code==200,saved.json
    events=client.get(base+'/report-events?category=ST').json['items'];assert events[0]['retained_settings']['caption']=='图注'
    assert client.delete('/api/annotations/'+str(first['id'])).status_code==200
    assert client.post(base+'/annotations',json=first_payload).status_code==409
    assert client.get(base+'/report-events?category=ST').json['items']==[]


def test_new_digest_uses_exact_float_bits_without_changing_equivalent_safe_numbers():
    from ecg_core.stt_records import digest
    assert digest({'医生':'备注','x':[20.,-0.,1e-7,1.234e22,True,None]})==digest({'x':[20,0,.0000001,1.234e22,True,None],'医生':'备注'})
    assert digest(1e-7)!=digest(1.0000000000000001e-7)
    assert digest(True)!=digest(1)
    assert digest(['float64','3e7ad7f29abcaf48'])!=digest(1e-7)
    with pytest.raises(ValueError):digest(float('nan'))


def test_review_workflow_requires_edit_but_never_all_ST_candidates(tmp_path):
    from ecg_core.storage import Storage
    storage=Storage(tmp_path/'review.db')
    with storage.connect() as db:
        storage._write_review(db,dict(case_id='math',revision=1,steps=dict(edit=dict(status='done'),stt=dict(status='pending')),events={}))
        storage.assert_report_ready(db,'math','医生数学复核结论')
        with pytest.raises(ValueError,match='结论'):storage.assert_report_ready(db,'math','')
        storage._write_review(db,dict(case_id='math',revision=2,steps=dict(edit=dict(status='stale'),stt=dict(status='done')),events={}))
        with pytest.raises(ValueError,match='编辑'):storage.assert_report_ready(db,'math','医生数学复核结论')


def test_whole_metrics_match_independent_per_beat_extrema_and_flat_source_lead_is_unavailable():
    import statistics
    from test_stt_range import synthetic,derived
    from ecg_core.stt_range import calculate_stt_range
    raw,records=synthetic(delta=lambda s:97 if s==11 else -13)
    raw[:,2]=0  # Stored V1 is absent; a derived limb zero remains a real projection.
    result=calculate_stt_range(raw,records,start_sample=0,end_sample=12000,leads=['II','V1','III'])
    row=result['leads'][0];anchors=[r['sample_index'] for r in records if r['sample_index']<12000]
    values=[]
    for anchor in anchors:
        baseline=statistics.median(derived(raw[anchor+offset],'II') for offset in (-40,-36,-32,-28,-24))
        values.append(statistics.median(derived(raw[anchor+20+offset],'II') for offset in (-2,-1,0,1,2))-baseline)
    assert row['minimum_st_level_units']==min(values) and row['maximum_st_level_units']==max(values)
    assert row['minimum_st_sample']==anchors[values.index(min(values))] and row['maximum_st_sample']==anchors[values.index(max(values))]
    assert row['reference_sample'] in anchors
    assert result['leads'][1]['used_count']==0 and result['leads'][1]['mean_units'] is None
    assert result['leads'][2]['used_count']==len(anchors) and result['leads'][2]['mean_units']==0


def test_T_is_separate_from_ST_and_protocols_never_merge_time_groups():
    from ecg_core.report_sections import st_report_events
    idx=index_for(list(range(180)),duration=180)
    t=dict(event_id='T',basis_version='T1',category='ST',time_s=10,end_s=130,label='医生T改变',stt_review_state='reviewed',
        stt_result_code='t_change',stt_report_eligibility=dict(table=True),stt_review_receipt={'leads':['V5']},
        stt_event_evidence=dict(kind='t_wave_inversion',leads=['V5'],measurement_protocol={'measurement_ms':60},metrics=[dict(lead='V5',mean_t_amplitude_units=-50,extreme_t_amplitude_units=-90,extreme_t_sample=20000,t_used_count=110)]))
    idx['events'].append(t)
    assert st_report_events(idx)==[]
    rows=st_report_events(idx,'T');assert len(rows)==1 and rows[0]['mean_t_amplitude_units']==-50
    assert rows[0]['extreme_t_amplitude_units']==-90 and rows[0]['extreme_t_time_s']==100 and rows[0]['used_beat_count']==110
    other={**rows[0],'event_id':'other','row_id':'other:V5','measurement_protocol':{'measurement_ms':80}}
    summary=st_summary(rows+[other]);assert summary['confirmed_time_group_count']==2 and summary['confirmed_union_duration_s']==120
    t['stt_result_code']='no_change'
    assert st_report_events(idx,'T')==[]


def test_real_source_change_preserves_record_but_requires_recheck(api_case,synthetic_case):
    client,base=api_case;row=client.post(base+'/annotations',json=payload(client,base)).json
    path=synthetic_case[2]['data'];data=bytearray(path.read_bytes());data[0:2]=bytes((1,0));path.write_bytes(data)
    current=client.get(base+'/report-events?category=ST').json['items'][0]
    assert current['event_id']==row['stt_review_receipt']['event_id'] and current['stt_review_state']=='stale'
    assert not any(current['stt_report_eligibility'].values())


def test_report_heart_rate_uses_current_anchors_actual_tail_and_missing_breaks():
    from ecg_core.report_sections import report_heart_rate
    rows=[dict(sample_index=t*200,class_code='N') for t in [1,2,3,121,122]]+[dict(sample_index=123*200,class_code='X')]
    points=report_heart_rate(rows,130)
    assert [p['hr'] for p in points]==[3,None,12] and points[-1]['detected_beat_count']==2
    assert points[-1]['start_s']==120 and points[-1]['end_s']==130 and points[-1]['time_s']==125


def test_UUID_ledger_is_supported_by_saved_work_backup_but_malformed_receipts_are_rejected(api_case):
    from ecg_core.workspace_backup import _check_database,BackupError
    client,base=api_case;assert client.post(base+'/annotations',json=payload(client,base)).status_code==201
    store=client.application.extensions['storage']
    assert _check_database(store.path)['tables']['stt_review_submissions']==1
    with store.connect() as db:db.execute("UPDATE stt_review_submissions SET request_sha256='not-a-sha256'")
    with pytest.raises(BackupError,match='ST-T'): _check_database(store.path)


@pytest.mark.parametrize('measurement_ms',[0,60,80])
def test_legacy_range_receipt_keeps_real_declared_protocol_without_inventing_point_or_review(measurement_ms):
    from ecg_core.stt_records import review_metadata
    from ecg_core.stt_range import method_profile
    profile=method_profile(measurement_ms)
    row=dict(id=1,sample_index=0,lead='II',note='旧均值',details=dict(kind='ST',status='confirmed',end_sample=15999,range_statistics=dict(method_profile=profile)))
    receipt=review_metadata(row)
    assert receipt['review_state']=='unreviewed' and not any(receipt['report_eligibility'].values())
    assert receipt['point_measurement_protocol'] is None
    assert receipt['measurement_protocol']==dict(method_version=profile['id'],measurement_ms=measurement_ms,extent='whole',
        baseline_method='pre_qrs_stable',units=profile['units'],calibration_verified=False,range_profile=profile)
    assert row['details']['range_statistics']['method_profile']==profile


def test_receipt_protocol_precedence_and_unknown_history_are_explicit():
    from ecg_core.stt_records import review_metadata,protocol
    row=dict(id=1,sample_index=0,lead='II',details=dict(kind='ST',status='pending',end_sample=1000))
    unknown=review_metadata(row)
    assert unknown['measurement_protocol'] is None and unknown['point_measurement_protocol'] is None
    row['details']['measurement_protocol']=dict(measurement_ms=80,extent='point',baseline_method='manual_iso_point')
    point=review_metadata(row);assert point['measurement_protocol']==row['details']['measurement_protocol']
    explicit=dict(measurement_ms=0,extent='whole',method_version='retained-original-method')
    row['details']['stt_event_evidence']={'measurement_protocol':explicit}
    whole=review_metadata(row)
    assert whole['measurement_protocol']==explicit and whole['point_measurement_protocol']==point['measurement_protocol']
    assert whole['review_state']=='unreviewed' and not any(whole['report_eligibility'].values())


def test_saved_pending_AF_preserves_machine_trends_and_continuity_without_changing_N_beats(st_app):
    app,cid=st_app;client=app.test_client();base='/api/cases/'+cid
    before=client.get(base+'/stt-review').json
    old=next(c for c in before['automatic_candidates']['items'] if c['kind']=='st_elevation' and c['leads']==['II'])
    # The same source and N beats keep the same ST/T evidence, even when an
    # overlapping AF diagnosis is pending. RR/HRV keep their own exclusion rule.
    mask=dict(sample_index=150*200,lead='全部',category='note',label='数学AF排除',note='',details=dict(kind='AF',status='pending',end_sample=151*200-1))
    saved=client.post(base+'/annotations',json=mask);assert saved.status_code==201,saved.json
    after=client.get(base+'/stt-review').json
    assert after['beat_revision']==before['beat_revision']
    assert after['analysis']['exclusions']['intervals']==[]
    assert after['analysis']==before['analysis']
    assert old in after['automatic_candidates']['items']
    assert client.delete('/api/annotations/'+str(saved.json['id'])).status_code==200
    restored=client.get(base+'/stt-review').json
    assert restored['analysis']==before['analysis']


def test_ST_review_note_global_identity_does_not_redefine_independent_range_identity(api_case):
    import json
    client,base=api_case;store=client.application.extensions['storage'];cid=base.rsplit('/',1)[-1]
    old=client.get(base+'/report-events?category=ST').json['data_version']
    annotation=store.create_annotation(cid,dict(sample_index=2000,lead='II',label='历史ST-T说明',details=dict(kind='ST',status='pending',end_sample=4000)),'math')
    with store.connect() as db:
        d=annotation['details'];d['kind']='ST_REVIEW_NOTE'
        db.execute('UPDATE annotations SET details=? WHERE id=?',(json.dumps(d),annotation['id']))
    event_reply=client.get(base+'/report-events?category=ST').json
    assert event_reply['data_version']!=old
    assert event_reply['items'][0]['stt_review_state']=='unreviewed'
    scope=client.get(base+'/hrv-review').json['scope']
    assert scope['data_version']==event_reply['data_version']
    response=client.post(base+'/stt-range',json=dict(scope={k:scope[k] for k in ('case_id','analysis_basis','analysis_revision','beat_revision','data_version')},start_sample=0,end_sample=12000,leads=['II'],measurement_ms=60))
    assert response.status_code==409  # A global HRV identity cannot impersonate the ST-only method identity.
    independent={k:scope[k] for k in ('case_id','analysis_basis','analysis_revision','beat_revision')}
    response=client.post(base+'/stt-range',json=dict(scope=independent,start_sample=0,end_sample=12000,leads=['II'],measurement_ms=60))
    assert response.status_code==200,response.json
    assert response.json['server_identity']['data_version'].endswith('-stt-independent-v2')
    assert response.json['server_identity']['data_version']!=event_reply['data_version']


def saved_normal_text_report(client,base):
    target=client.post(base+'/annotations',json=payload(client,base,'no_change')).json
    other=client.post(base+'/annotations',json=payload(client,base,'indeterminate')).json
    a,b=target['stt_review_receipt'],other['stt_review_receipt']
    def pick(receipt,caption):return dict(event_id=receipt['event_id'],basis_version=receipt['basis_version'],caption=caption,notes='保留附注',leads=['II'],duration_s=7,print_enabled=False)
    def use(receipt):return dict(event_id=receipt['event_id'],basis_version=receipt['basis_version'],table=False,text=True,strip=False)
    blocks=[dict(key='ST:review:'+a['event_id'],text='本段未见明确改变（自动生成）',manual=False,needs_review=False,acknowledged=False),
        dict(key='ST:review:'+a['event_id'],text='医生手写本条意见，必须保留',manual=True,needs_review=False,acknowledged=True),
        dict(key='ST:review:'+b['event_id'],text='另一记录自动文字，必须保留',manual=False,needs_review=False,acknowledged=False),
        dict(key='V:single',text='其他类别手写原文，必须保留',manual=True,needs_review=False,acknowledged=True)]
    report=client.get(base+'/report').json
    response=client.put(base+'/report',json=dict(expected_version=report['version'],status='draft',conclusion='医生原结论不得重写',
        composition={**report['composition'],'selected_events':[pick(a,'本条图注'),pick(b,'其他图注')],
            'stt_report_use':[use(a),use(b)],'diagnosis_blocks':blocks}))
    assert response.status_code==200,response.json
    return target,other,response.json


@pytest.mark.parametrize('operation',['update','delete'])
def test_same_ST_record_reconciliation_retracts_only_its_generated_text_atomically(api_case,operation):
    client,base=api_case;target,other,before=saved_normal_text_report(client,base)
    event_id=target['stt_review_receipt']['event_id'];other_id=other['stt_review_receipt']['event_id'];key='ST:review:'+event_id
    if operation=='update':
        edit=payload(client,base,'st_depression');edit['expected_record_version']=1
        response=client.put(base+'/annotations/'+str(target['id']),json=edit)
        assert response.status_code==200,response.json
        assert response.json['stt_review_receipt']['result_code']=='st_depression'
        assert response.json['stt_review_receipt']['report_reconciliation']['removed_diagnosis_blocks']==[before['composition']['diagnosis_blocks'][0]]
    else:
        response=client.delete('/api/annotations/'+str(target['id']))
        assert response.status_code==200,response.json
    after=client.get(base+'/report').json;c=after['composition']
    assert not any(b['key']==key and b['manual'] is False for b in c['diagnosis_blocks'])
    manual=next(b for b in c['diagnosis_blocks'] if b['key']==key)
    assert manual=={**before['composition']['diagnosis_blocks'][1],'needs_review':True,'acknowledged':False}
    assert next(b for b in c['diagnosis_blocks'] if b['key']=='ST:review:'+other_id)==before['composition']['diagnosis_blocks'][2]
    # The pre-existing whole-case handwritten-prose guard remains conservative:
    # unrelated words/curation stay exact, while acknowledgement is withdrawn.
    assert next(b for b in c['diagnosis_blocks'] if b['key']=='V:single')=={**before['composition']['diagnosis_blocks'][3],'needs_review':True,'acknowledged':False}
    assert c['selected_events']==[before['composition']['selected_events'][1]]
    assert c['stt_report_use']==[before['composition']['stt_report_use'][1]]
    assert after['conclusion']==before['conclusion'] and after['status']=='draft' and after['version']==before['version']+1
    assert after['reviewed_by']==''


@pytest.mark.parametrize('operation',['update','delete'])
def test_ST_reconciliation_rolls_back_text_record_links_and_receipt_on_audit_failure(api_case,monkeypatch,operation):
    from contextlib import closing
    client,base=api_case;target,_,_=saved_normal_text_report(client,base);store=client.application.extensions['storage']
    def snapshot():
        with closing(store.connect()) as db:
            return {table:[dict(row) for row in db.execute('SELECT * FROM '+table)] for table in ('annotations','report_drafts','stt_review_submissions','case_review','audit_log')}
    before=snapshot()
    def fail(*args,**kwargs):raise RuntimeError('mathematical audit failure')
    monkeypatch.setattr(store,'_audit',fail)
    with pytest.raises(RuntimeError,match='mathematical audit failure'):
        if operation=='update':
            edit=payload(client,base,'st_depression');edit['expected_record_version']=1
            client.put(base+'/annotations/'+str(target['id']),json=edit)
        else:client.delete('/api/annotations/'+str(target['id']))
    assert snapshot()==before
