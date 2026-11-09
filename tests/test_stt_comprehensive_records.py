"""Real API/DB/report contracts for independent compound ST/T physician reviews.

These synthetic cases exercise decision persistence and projections. The detector
has separate waveform classification oracles; these tests do not assert that a
physician's selected description is an automatically established diagnosis.
"""
import copy
from uuid import uuid4
import numpy as np
import pytest

from app import create_app
from ecg_core.ebi import HEADER_SIZE, RECORD
from ecg_core.stt_records import METHOD, RHYTHM_POLICY, review_metadata
from ecg_core.report_sections_pdf import documents
from test_analysis_provenance import synthetic_case


@pytest.fixture
def comprehensive_api(synthetic_case,tmp_path):
    root,cid,paths=synthetic_case
    duration=360
    phase=np.arange(duration*200)%200
    qrs=np.select([phase==0,phase==1,phase==2,phase==3],[900,600,250,80],default=0)
    raw=np.repeat(qrs[:,None],8,axis=1)
    raw[(phase>=18)&(phase<=44),1]=-130
    raw[(phase>=55)&(phase<=62),1]=-180
    raw[(phase>=55)&(phase<=62),6]=10
    raw[(phase>=55)&(phase<=58),2]=150
    raw[(phase>=59)&(phase<=62),2]=-150
    paths['data'].write_bytes(raw.astype('<i2').tobytes())
    paths['ebi'].write_bytes(bytes(HEADER_SIZE)+b''.join(RECORD.pack(i*200,1,1,0,0,0,1000) for i in range(1,duration)))
    app=create_app(data_root=root,db_path=tmp_path/'comprehensive.sqlite3',testing=True)
    return app.test_client(),'/api/cases/'+cid


def checked(response,status=(200,201)):
    assert response.status_code in status,response.json
    return response.json


def review(client,base,code,*,findings=None,start=20,end=100,leads=None):
    identity=checked(client.get(base+'/stt-review'))
    d=dict(kind='ST',reviewed=True,result_code=code,finding='数学医生复核 '+code,
        submission_id=str(uuid4()),review_extent='whole',review_leads=leads or ['II'],
        end_sample=end*200-1,review_scope={k:identity[k] for k in ('case_id','analysis_basis','analysis_revision','beat_revision')},
        measurement_protocol=dict(measurement_ms=60,extent='whole'),physician_note='保留医生原文')
    if findings is not None:d['findings']=findings
    return dict(sample_index=start*200,lead='全部',category='note',label='数学ST-T',note='原备注',details=d)


@pytest.mark.parametrize('code',['t_wave_inversion','t_persistent_inversion','t_low_flat','t_biphasic','t_change'])
def test_each_T_subtype_survives_save_history_report_table_text_and_PDF(comprehensive_api,code):
    client,base=comprehensive_api
    p=review(client,base,code)
    saved=checked(client.post(base+'/annotations',json=p))
    receipt=saved['stt_review_receipt'];eid=receipt['event_id']
    assert receipt['result_codes']==[code] and receipt['result_kind']=='T'
    assert receipt['findings']==[dict(result_code=code,leads=['II'],start_sample=4000,end_sample=19999)]
    assert saved['details']['stt_event_evidence']['kind']==code
    assert receipt['report_eligibility']==dict(table=True,text=True,strip=True)
    history=checked(client.get(base+'/stt-review'))['review_records']
    assert next(a for a in history if a['id']==saved['id'])['details']==saved['details']
    event=checked(client.get(base+'/report-events?category=ST&stt_group=T'))['items'][0]
    assert event['event_id']==eid
    sections=checked(client.get(base+'/report-sections'))
    assert len(sections['t_events'])==1 and sections['t_events'][0]['kind']==code
    assert sections['t_events'][0]['selection_event_id']==eid
    report=checked(client.get(base+'/report'))
    comp={**report['composition'],'included_pages':['st_events','event_strips'],
          'stt_report_use':[dict(event_id=eid,basis_version=receipt['basis_version'],table=True,text=True,strip=True)],
          'selected_events':[dict(event_id=eid,basis_version=receipt['basis_version'])]}
    checked(client.put(base+'/report',json=dict(expected_version=report['version'],status='draft',composition=comp,conclusion='数学验证')))
    reopened=checked(client.get(base+'/report'))
    assert reopened['composition']['stt_report_use'][0]['table']
    assert reopened['composition']['selected_events'][0]['leads']==['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6']
    docs=documents({'metadata':{}},{**reopened,'section_evidence':sections},['st_events'])
    label={'t_wave_inversion':'T极性反转','t_persistent_inversion':'T持续倒置','t_low_flat':'T低平','t_biphasic':'双相T','t_change':'T改变（未细分）'}[code]
    assert any(label in line for doc in docs for line in doc['rows'])
    assert any('保留医生原文' in line for doc in docs for line in doc['rows'])
    # Withdrawing only the strip must retain explicit table/text uses, with no
    # dangling selection that will fail to read later.
    row=reopened['composition']['stt_report_use'][0]
    comp={**reopened['composition'],'selected_events':[],'stt_report_use':[{**row,'strip':False}]}
    checked(client.put(base+'/report',json=dict(expected_version=reopened['version'],status='draft',composition=comp)))
    after=checked(client.get(base+'/report'))
    assert after['composition']['selected_events']==[]
    assert after['composition']['stt_report_use'][0]['table'] and after['composition']['stt_report_use'][0]['text']
    again=checked(client.post(base+'/annotations',json=p))
    assert again['id']==saved['id'] and again['details']==saved['details']
    assert len(checked(client.get(base+'/annotations'))['items'])==1


def test_compound_ST_T_review_keeps_child_lead_ranges_and_one_report_identity(comprehensive_api):
    client,base=comprehensive_api
    findings=[dict(result_code='st_depression',leads=['II'],start_sample=4000,end_sample=27999),
        dict(result_code='t_persistent_inversion',leads=['II'],start_sample=6000,end_sample=21999),
        dict(result_code='t_low_flat',leads=['V5'],start_sample=8000,end_sample=23999)]
    p=review(client,base,'st_depression',findings=findings,start=20,end=140,leads=['II','V5'])
    saved=checked(client.post(base+'/annotations',json=p));r=saved['stt_review_receipt'];eid=r['event_id']
    assert r['result_kind']==r['report_group']=='ST_T' and r['findings']==findings
    assert r['result_codes']==['st_depression','t_persistent_inversion','t_low_flat']
    for family in ('ST','T','ST_T'):
        rows=checked(client.get(base+'/report-events?category=ST&stt_group='+family))['items']
        assert len(rows)==1 and rows[0]['event_id']==eid
    e=checked(client.get(base+'/report-sections'))
    assert len(e['st_events'])==1 and len(e['t_events'])==2
    rows=e['st_events']+e['t_events']
    assert len({row['row_id'] for row in rows})==3
    assert {row['selection_event_id'] for row in rows}=={eid}
    assert [(row['start_s'],row['end_s']) for row in rows]==[(20,140),(30,110),(40,120)]
    assert e['st_summary']['confirmed_record_count']==1 and e['t_summary']['confirmed_record_count']==1
    assert e['t_summary']['confirmed_union_duration_s']==90
    assert saved['details']['stt_event_evidence']['findings'][1]['kind']=='t_persistent_inversion'
    # Update one parent withdraws its single report use and exact selection.
    report=checked(client.get(base+'/report'))
    comp={**report['composition'],'included_pages':['st_events'],
        'stt_report_use':[dict(event_id=eid,basis_version=r['basis_version'],table=True,text=True,strip=False)]}
    checked(client.put(base+'/report',json=dict(expected_version=report['version'],status='draft',composition=comp)))
    edit=review(client,base,'t_low_flat',leads=['V5']);edit['expected_record_version']=1
    updated=checked(client.put(base+'/annotations/'+str(saved['id']),json=edit))
    assert updated['id']==saved['id'] and updated['stt_review_receipt']['record_version']==2
    assert checked(client.get(base+'/report'))['composition']['stt_report_use']==[]


@pytest.mark.parametrize('problem',['outside','lead','duplicate','forged','primary'])
def test_invalid_or_forged_child_evidence_never_writes(comprehensive_api,problem):
    client,base=comprehensive_api
    item=dict(result_code='t_low_flat',leads=['II'])
    findings=[item]
    if problem=='outside':item['start_sample']=1
    if problem=='lead':item['leads']=['V6']
    if problem=='duplicate':findings.append(copy.deepcopy(item))
    if problem=='forged':item['metrics']=[dict(mean_t_amplitude_units=0)]
    if problem=='primary':item['result_code']='st_depression'
    p=review(client,base,'t_low_flat',findings=findings)
    checked(client.post(base+'/annotations',json=p),status=(400,))
    assert checked(client.get(base+'/annotations'))['items']==[]


def test_historical_independent_method_readable_without_relabelling_or_resigning():
    old=dict(method_version='stt-hospital-review-v2',measurement_ms=60,extent='whole',baseline_method='pre_qrs_stable',
        rhythm_policy=RHYTHM_POLICY,units='source_device_units',calibration_verified=False)
    row=dict(id=3,sample_index=1000,lead='II',details=dict(kind='ST',reviewed=True,result_code='t_change',status='confirmed',
        end_sample=15000,review_extent='whole',review_leads=['II'],measurement_protocol=copy.deepcopy(old),
        stt_event_evidence=dict(kind='t_wave_inversion',start_s=5,end_s=75,duration_s=70,leads=['II'],
            rhythm_policy=RHYTHM_POLICY,measurement_protocol={**old,'range_profile':dict(id='raw-200hz-fixed16s-st-perbeat-mean-v2',rhythm_policy=RHYTHM_POLICY)})))
    before=copy.deepcopy(row);r=review_metadata(row)
    assert r['review_state']=='reviewed' and r['measurement_protocol']['method_version']=='stt-hospital-review-v2'
    assert r['measurement_protocol']['method_version']!=METHOD and row==before


def test_actual_compound_ST_T_report_PDF_generation_uses_selected_findings(comprehensive_api,tmp_path):
    client,base=comprehensive_api
    f=[dict(result_code='st_depression',leads=['II']),dict(result_code='t_persistent_inversion',leads=['II']),
       dict(result_code='t_low_flat',leads=['V5']),dict(result_code='t_biphasic',leads=['V1'])]
    saved=checked(client.post(base+'/annotations',json=review(client,base,'st_depression',findings=f,leads=['II','V5','V1'])))
    r=saved['stt_review_receipt'];report=checked(client.get(base+'/report'))
    comp={**report['composition'],'page_selection_version':1,'included_pages':['st_trend','t_trend','st_events','event_strips'],
        'stt_report_use':[dict(event_id=r['event_id'],basis_version=r['basis_version'],table=True,text=True,strip=True)],
        'selected_events':[dict(event_id=r['event_id'],basis_version=r['basis_version'],duration_s=7)]}
    checked(client.put(base+'/report',json=dict(expected_version=report['version'],status='draft',composition=comp,conclusion='数学合成数据验证')))
    response=client.get(base+'/report.pdf')
    assert response.status_code==200,response.json
    assert response.mimetype=='application/pdf' and response.data.startswith(b'%PDF-')
    assert len(response.data)>6000
    import hashlib,os
    assert response.headers['X-Report-SHA256']==hashlib.sha256(response.data).hexdigest()
    if os.environ.get('STT_PDF_ARTIFACT_DIR'):
        from pathlib import Path
        out=Path(os.environ['STT_PDF_ARTIFACT_DIR']);out.mkdir(parents=True,exist_ok=True)
        (out/'stt-comprehensive-math-report.pdf').write_bytes(response.data)
        (out/'stt-comprehensive-math-report-sections.json').write_text(__import__('json').dumps(checked(client.get(base+'/report-sections')),ensure_ascii=False,indent=2))


@pytest.mark.parametrize('kind',['AF','AFL'])
def test_new_ST_T_compound_findings_and_report_use_are_independent_of_rhythm_lifecycle(comprehensive_api,kind):
    client,base=comprehensive_api
    f=[dict(result_code='st_depression',leads=['II']),dict(result_code='t_persistent_inversion',leads=['II']),
       dict(result_code='t_low_flat',leads=['V5']),dict(result_code='t_biphasic',leads=['V1'])]
    saved=checked(client.post(base+'/annotations',json=review(client,base,'st_depression',findings=f,leads=['II','V5','V1'])))
    r=saved['stt_review_receipt'];report=checked(client.get(base+'/report'))
    comp={**report['composition'],'included_pages':['st_events','event_strips'],
        'stt_report_use':[dict(event_id=r['event_id'],basis_version=r['basis_version'],table=True,text=True,strip=True)],
        'selected_events':[dict(event_id=r['event_id'],basis_version=r['basis_version'],duration_s=7,caption='原图注')]}
    stored_report=checked(client.put(base+'/report',json=dict(expected_version=report['version'],status='draft',composition=comp,conclusion='原结论')))
    before_analysis=checked(client.get(base+'/stt-review'))['analysis']
    before_sections=checked(client.get(base+'/report-sections'))
    episode=dict(id=str(uuid4()),start_s=10,end_s=220,kind=kind,status='pending',source='manual',note='数学独立节律')
    for current_episode in [episode,{**episode,'start_s':30,'end_s':260}, {**episode,'status':'confirmed'}, {**episode,'status':'excluded'},None]:
        current=checked(client.get(base+'/rhythm-review'))
        checked(client.put(base+'/rhythm-review',json={**{k:current[k] for k in ('case_id','analysis_basis','analysis_revision','beat_revision')},
            'revision':current['revision'],'confirmed':True,'document':dict(episodes=[current_episode] if current_episode else [],bookmarks={})}))
        assert checked(client.get(base+'/stt-review'))['analysis']==before_analysis
        after_sections=checked(client.get(base+'/report-sections'))
        for key in ('st_trends','st_events','t_events','st_summary','t_summary','st_representatives','t_representatives'):
            assert after_sections[key]==before_sections[key]
        after_report=checked(client.get(base+'/report'))
        assert after_report['composition']==stored_report['composition'] and after_report['conclusion']=='原结论'
        again=next(a for a in checked(client.get(base+'/annotations'))['items'] if a['id']==saved['id'])
        assert again['details']==saved['details'] and again['stt_review_receipt']['basis_version']==r['basis_version']
