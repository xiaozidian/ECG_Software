"""Independent raw-waveform cases for persistent morphology and real duration.

Waveform intervals below define the mathematical input before the detector is
called. These are engineering oracles, not patient/clinical performance claims.
"""
import copy
from pathlib import Path

import numpy as np
import pytest

from ecg_core.stt import analyze_stt, _lead_episodes, _t_episodes, DEFAULT_CONFIG, minute_trends
from ecg_core.stt_range import calculate_stt_range


def waveform(tmp_path, duration=240, changes=(), flatline=(), low_r=False, noise=False):
    raw=np.full((duration*200,8),4000.,dtype=float)
    records=[]
    for second in range(1,duration-1):
        sample=second*200;offset=np.arange(-50,110)
        qrs=(1000*np.exp(-.5*(offset/1.3)**2)-150*np.exp(-.5*((offset+4)/1.5)**2)-180*np.exp(-.5*((offset-5)/1.8)**2))
        if low_r:qrs*=.05
        raw[sample-50:sample+110]+=qrs[:,None]
        amplitudes=np.full(8,180.)
        st=np.zeros(8);biphasic=[]
        for lead,kind,start,end,value in changes:
            if start<=second<end:
                if kind=='T':amplitudes[lead]=value
                elif kind=='ST':st[lead]=value
                elif kind=='biphasic':amplitudes[lead]=0;biphasic.append(lead)
        raw[sample-50:sample+110]+=np.exp(-.5*((offset-62)/6)**2)[:,None]*amplitudes
        raw[sample-50:sample+110]+=((offset>=17)&(offset<=44))[:,None]*st
        for lead in biphasic:
            raw[sample-50:sample+110,lead]+=180*np.exp(-.5*((offset-55)/4)**2)-180*np.exp(-.5*((offset-78)/4)**2)
        if noise:
            # Large baseline oscillation is not a low-amplitude measurable T.
            raw[sample-40:sample-23]+=np.array([100,-100,100,-100,100,-100,100,-100,100,-100,100,-100,100,-100,100,-100,100])[:,None]
        records.append((sample,0,1,0,0,0,1000))
    for start,end in flatline:raw[start*200:end*200]=4000
    array=np.rint(raw).astype('<i2');p=tmp_path/'synthetic.DATA';p.write_bytes(array.tobytes())
    return p,records,array


def events(result,lead,kind):
    return [c for c in result['candidates'] if c['lead']==lead and c['kind']==kind]


def test_persistent_absolute_ST_and_negative_T_are_found_from_recording_start(tmp_path):
    p,records,_=waveform(tmp_path,240,[(0,'ST',1,239,-170),(4,'T',1,181,-180)])
    r=analyze_stt(p,records,240)
    st=events(r,'I','st_depression');negative=events(r,'V3','t_persistent_inversion')
    assert [(c['start_s'],c['end_s']) for c in st]==[(1,238)]
    assert st[0]['criteria']==['absolute_st_level']
    assert [(c['start_s'],c['end_s']) for c in negative]==[(1,181)]
    assert all(c['diagnosis'] is None and c['threshold_scale'].startswith('uncalibrated') for c in r['candidates'])


@pytest.mark.parametrize('seconds',[59,60,61])
def test_real_raw_waveform_duration_is_not_rounded_to_16_second_blocks(tmp_path,seconds):
    p,records,_=waveform(tmp_path,200,[(4,'T',31,31+seconds,-180),(1,'ST',31,31+seconds,170)])
    r=analyze_stt(p,records,200)
    negative=events(r,'V3','t_persistent_inversion');st=events(r,'II','st_elevation')
    if seconds<60:assert negative==[] and st==[]
    else:
        assert [(c['start_s'],c['end_s'],c['duration_s']) for c in negative]==[(31,31+seconds,seconds)]
        assert [(c['start_s'],c['end_s'],c['duration_s']) for c in st]==[(31,31+seconds,seconds)]
        assert negative[0]['boundary_resolution_s']==1


def test_ST_negative_platform_is_not_a_negative_T_lobe(tmp_path):
    p,records,_=waveform(tmp_path,240,[(0,'ST',1,239,-170),(7,'ST',61,181,-170)])
    r=analyze_stt(p,records,240)
    assert events(r,'I','st_depression') and events(r,'V6','st_depression')
    assert not events(r,'I','t_biphasic') and not events(r,'V6','t_biphasic')
    assert not events(r,'I','t_persistent_inversion')


def test_low_T_biphasic_and_dynamic_inversion_remain_distinct_and_parallel(tmp_path):
    p,records,array=waveform(tmp_path,360,[(4,'T',61,181,10),(5,'biphasic',121,241,0),(6,'T',181,301,-180),(6,'ST',181,301,-170)])
    r=analyze_stt(p,records,360)
    assert [(c['start_s'],c['end_s']) for c in events(r,'V3','t_low_flat')]==[(61,181)]
    assert [(c['start_s'],c['end_s']) for c in events(r,'V4','t_biphasic')]==[(121,241)]
    assert not events(r,'V4','t_low_flat')
    assert events(r,'V5','st_depression') and events(r,'V5','t_persistent_inversion')
    inversion=events(r,'V5','t_wave_inversion')[0]
    assert (inversion['polarity_from'],inversion['polarity_to'])==('positive','negative')
    selected=calculate_stt_range(array,records,start_sample=121*200,end_sample=241*200,leads=['V4'])['leads'][0]
    assert selected['mean_t_positive_units']>100 and selected['mean_t_negative_units']<-100
    assert selected['biphasic_beat_count']==120
    assert selected['minimum_absolute_t_units']>100
    assert selected['t_measurable_count']==120


@pytest.mark.parametrize('kind',['flatline','low_r','noise'])
def test_unmeasurable_or_low_R_is_not_T_low_flat(tmp_path,kind):
    p,records,_=waveform(tmp_path,180,[(4,'T',1,179,10)],flatline=[(1,179)] if kind=='flatline' else (),low_r=kind=='low_r',noise=kind=='noise')
    r=analyze_stt(p,records,180)
    assert events(r,'V3','t_low_flat')==[]
    if kind=='flatline':
        assert all(x['t_amplitude_units'] is None for x in r['trends']['leads']['V3'])
        assert all(x['measured_t_amplitude_units'] is None for x in r['trends']['leads']['V3'])


def test_true_gap_breaks_and_minute_warning_values_do_not_become_gap_repairs(tmp_path):
    p,records,_=waveform(tmp_path,300,[(4,'T',1,299,-180)],flatline=[(121,151)])
    r=analyze_stt(p,records,300)
    assert not any(c['start_s']<121 and c['end_s']>151 for c in events(r,'V3','t_persistent_inversion'))
    gap=r['trends']['leads']['V3'][2]
    assert gap['measured_t_amplitude_units'] is None
    # A suspect but actually measured interval keeps its values/quality apart.
    pts=[dict(start_s=0,end_s=60,time_s=0,measurable=True,eligible=False,quality_flags=['suspected_axis'],
              quality_score=.3,st_level_units=-160,t_amplitude_units=-180,reference_units=0,deviation_units=-160,t_reference_units=180)]
    row=minute_trends(pts,60,DEFAULT_CONFIG)[0]
    assert not row['eligible'] and row['measured_st_level_units']==-160 and row['measured_t_amplitude_units']==-180
    assert 'suspected_axis' in row['quality_flags']


def test_episode_functions_cross_midnight_without_joining_missing_evidence():
    points=[dict(start_s=s,end_s=s+1,time_s=s,eligible=True,measurable=True,quality_score=1,
                 st_level_units=-170,deviation_units=-170,t_amplitude_units=-180,t_reference_units=180,
                 t_positive_units=0,t_negative_units=-180,noise_units=1,r_amplitude_units=1000) for s in range(86370,86490)]
    assert _lead_episodes(points,'II',DEFAULT_CONFIG)[0]['duration_s']==120
    assert _t_episodes(points,'II',DEFAULT_CONFIG)[0]['duration_s']==120
    missing=copy.deepcopy(points);missing[60]['eligible']=False
    assert len(_lead_episodes(missing,'II',DEFAULT_CONFIG))==1  # first60 only, remainder59
    assert all(c['duration_s']==60 for c in _t_episodes(missing,'II',DEFAULT_CONFIG))


@pytest.mark.parametrize('kind',['AF','AFL'])
def test_AF_lifecycle_keeps_all_new_candidate_types_and_measured_minutes_exact(tmp_path,kind):
    import importlib.util
    from uuid import uuid4
    from app import create_app
    generator=Path(__file__).resolve().parents[1]/'scripts/generate_stt_comprehensive_math.py'
    spec=importlib.util.spec_from_file_location('independent_stt_engine_fixture',generator)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    source=tmp_path/'input';module.generate(source)
    app=create_app(data_root=source,db_path=tmp_path/'review.sqlite3',testing=True)
    client=app.test_client();base='/api/cases/'+module.CASE_ID
    initial=client.get(base+'/stt-review');assert initial.status_code==200,initial.json
    before=initial.json['analysis']
    assert {'st_depression','st_elevation','t_low_flat','t_persistent_inversion','t_biphasic','t_wave_inversion'}<=set(c['kind'] for c in before['candidates'])
    identifier=str(uuid4())
    for status in ('pending','confirmed','excluded',None):
        current=client.get(base+'/rhythm-review').json
        episodes=[dict(id=identifier,start_s=20,end_s=840,kind=kind,status=status,source='manual',note='mathematical independent rhythm')] if status else []
        response=client.put(base+'/rhythm-review',json={**{k:current[k] for k in ('case_id','analysis_basis','analysis_revision','beat_revision')},
            'revision':current['revision'],'confirmed':True,'document':dict(episodes=episodes,bookmarks={})})
        assert response.status_code==200,response.json
        after=client.get(base+'/stt-review')
        assert after.status_code==200,after.json
        assert after.json['analysis']==before
