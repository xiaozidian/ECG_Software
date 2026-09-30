"""Independent numerical/boundary oracles, not only Python/JavaScript parity."""
import copy
import json
import math
import subprocess
from types import SimpleNamespace

import pytest

from ecg_core.beat_editor import edited_hrv
from ecg_core.clinical_analysis import build_index, query_index
from ecg_core.hrv_analysis import analyze_hrv, spectrum
from ecg_core.report_sections import rr_derivatives, evidence
from ecg_core.rr_quality import interval_mask, nn_intervals, annotation_exclusions

OPTS = dict(nn_min=300, nn_max=2000, pause=2.5, tachy=120, brady=50)


def recording(intervals, codes=None, duration=None, excluded=()):
    rows=[dict(id='s:0',sample_index=0,time_s=0,rr_ms=0,class_code='N',hr=None)]
    sample=0
    for i,rr in enumerate(intervals):
        sample+=round(rr/5)
        rows.append(dict(id=f's:{sample}',sample_index=sample,time_s=sample/200,
                         rr_ms=rr,class_code=codes[i] if codes else 'N',hr=60000/rr))
    return SimpleNamespace(beats=rows,markers=[],document={'settings':OPTS},
                           duration=duration or sample/200,excluded_rhythm_intervals=excluded)


def browser(expression, payload):
    script="""
require('./static/js/rr-quality.js');require('./static/js/beat-engine.js');
require('./static/js/clinical-analysis.js');require('./static/js/hrv-analysis.js');
require('./static/js/report-sections.js');
const x=JSON.parse(require('fs').readFileSync(0,'utf8'));
console.log(JSON.stringify(EXPRESSION));
""".replace('EXPRESSION',expression)
    return json.loads(subprocess.check_output(['node','-e',script],input=json.dumps(payload),text=True))


def test_complete_interval_overlap_and_half_open_boundaries():
    rows=recording([1000]*4).beats
    # Neither endpoint lies within this excluded span, but the RR crosses it.
    spans=[(1.2,1.4)]
    assert interval_mask(rows,spans)==[False,True,False,True,True]
    assert interval_mask(rows,[(1,2)])==[False,True,False,True,True]
    assert interval_mask(rows,[(2,3),(1,2),(1.4,1.5)])==[False,True,False,False,True]
    assert browser('ECGRRQuality.intervalMask(x.rows,x.spans)',dict(rows=rows,spans=spans))==interval_mask(rows,spans)


@pytest.mark.parametrize('bad',[None,True,'800',float('nan'),float('inf'),-800,0])
def test_invalid_rr_cannot_enter_sinus_measurements(bad):
    f=recording([800]*100);f.beats[50]['rr_ms']=bad
    assert not interval_mask(f.beats)[50]
    assert len(nn_intervals(f))==99
    assert all(math.isfinite(r[3]) for r in nn_intervals(f))
    rr_derivatives(f.beats)  # Must not crash while building jump prefixes.


def test_timestamp_mismatch_artifact_and_duplicate_break_interval():
    f=recording([800]*6);f.beats[2]['sample_index']+=40
    assert interval_mask(f.beats)==[False,True,False,False,True,True,True]
    f=recording([800]*6);f.beats[2]['class_code']='X'
    assert interval_mask(f.beats)==[False,True,False,False,True,True,True]
    f.beats[4]['sample_index']=f.beats[3]['sample_index']
    assert not interval_mask(f.beats)[4]


def test_known_nn_statistics_do_not_bridge_excluded_span():
    # NN values retained: 800,900,1100,1200; successive deltas: 100,100 (not 200).
    f=recording([800,900,1000,1100,1200],excluded=[(2,2.1)])
    h=edited_hrv(f);detail=analyze_hrv(f,None)['periods']['full']
    assert h['nn_count']==4 and h['successive_nn_pairs']==2
    assert h['mean_nn_ms']==1000 and h['sdnn_ms']==pytest.approx(math.sqrt(100000/3),abs=.005)
    assert h['rmssd_ms']==100 and h['pnn50_pct']==100
    for key in ('nn_count','mean_nn_ms','sdnn_ms','rmssd_ms','pnn50_pct'):
        assert h[key]==detail[key]
    other=browser('ECGBeatEngine.hrv(x,x.duration)',vars(f))
    assert other==h


def test_five_minute_coverage_and_boundary_contract_is_shared():
    sparse=recording([1000]*60,duration=600)
    summary=edited_hrv(sparse);detail=analyze_hrv(sparse,None)['periods']['full']
    assert summary['completed_five_minute_blocks']==detail['five_minute_blocks']==0
    assert summary['sdnn_index_ms'] is detail['sdnn_index_ms'] is None
    full=recording([1000]*600)
    summary=edited_hrv(full);detail=analyze_hrv(full,None)['periods']['full']
    assert summary['completed_five_minute_blocks']==detail['five_minute_blocks']==2
    assert summary['sdann_ms']==detail['sdann_ms']==0
    assert summary['nn_count']==detail['nn_count']==600
    assert browser('ECGBeatEngine.hrv(x,x.duration)',vars(full))==summary


def test_browser_summary_work_is_linear_not_repeated_full_array_means():
    f=recording([800+(i%7)*5 for i in range(5000)])
    result=browser("""(()=>{
      const original=Array.prototype.reduce;let visits=0;
      Array.prototype.reduce=function(...args){visits+=this.length;return original.apply(this,args)};
      try{const a=ECGBeatEngine.hrv(x,x.duration),b=ECGClinicalAnalysis.hrvWindows(x,'2026-09-28 08:00:00');return {visits,a:a.nn_count,b:b.periods.full.nn_count}}
      finally{Array.prototype.reduce=original}
    })()""",vars(f))
    assert result['a']==result['b']==5000
    assert result['visits']<5000*100  # Structural budget, independent of CPU speed.


def test_hrv_frequency_never_interpolates_across_short_af_span():
    # Two seconds is shorter than the generic 5 s interpolation limit.
    f=recording([1000]*600,excluded=[(100.2,102.2)])
    result=analyze_hrv(f,'2026-09-28 12:00:00')
    assert result['periods']['full']['nn_count']==597
    assert result['periods']['full']['five_minute_blocks']==2
    assert result['periods']['full']['spectral_blocks']==1
    js=browser("ECGHrvAnalysis.analyze(x,'2026-09-28 12:00:00')",vars(f))
    assert js['periods']['full']==result['periods']['full']
    assert all(math.isfinite(p['power']) for p in result['periods']['full']['psd'])


def test_spectrum_rejects_invalid_time_axis_and_dc_bin_is_not_doubled():
    nn=[(i,i,i+1,800+20*(i/300)**2) for i in range(300)]
    for bad in (float('nan'),99):
        modified=copy.deepcopy(nn);modified[100]=(100,100,bad,800)
        assert spectrum(modified) is None
    # Direct DFT at 0 Hz (windowing after demeaning leaves a residual DC term).
    start=(1+300-255.75)/2
    values=[]
    for j in range(1024):
        t=start+j/4;k=math.floor(t);f=t-k
        values.append(nn[k-1][3]*(1-f)+nn[k][3]*f)
    avg=sum(values)/1024;w=[.5-.5*math.cos(2*math.pi*i/1023) for i in range(1024)]
    expected=sum((v-avg)*weight for v,weight in zip(values,w))**2/(4*sum(x*x for x in w))
    assert spectrum(nn)[0]==pytest.approx(expected,rel=1e-9)
    assert browser('ECGHrvAnalysis.spectrum(x)',nn)[0]==pytest.approx(expected,rel=1e-9)


def pvc_recording(count=6):
    intervals=([800]*10+[500,1100]+list(range(760,901,10))+[800]*30)*count
    codes=['V' if i%57==10 else 'N' for i in range(len(intervals))]
    return recording(intervals,codes)


def test_hrt_coupling_and_pause_exclusions_are_not_overlooked():
    f=pvc_recording();baseline=rr_derivatives(f.beats)
    assert baseline['hrt']['eligible_pvc']==6
    assert baseline['hrt']['to_pct']==-4.375 and baseline['hrt']['ts_ms_per_rr']==10
    for index in (11,12,13):
        end=f.beats[index]['time_s'];span=[(end-.2,end-.1)]
        result=rr_derivatives(f.beats,span)
        assert result['hrt']['eligible_pvc']==5
        assert browser('ECGReportSections.derivatives(x.rows,x.spans)',dict(rows=f.beats,spans=span))==result


@pytest.mark.parametrize('base,post',[(1500,[1250]*20),(800,[900,1000]+[1000]*18)])
def test_hrt_rejects_absolute_jump_or_drift_from_sinus_reference(base,post):
    intervals=[base]*10+[base*.6,base*1.4]+post+[base]*5
    codes=['V' if i==10 else 'N' for i in range(len(intervals))]
    f=recording(intervals,codes)
    result=rr_derivatives(f.beats)
    assert result['hrt']['eligible_pvc']==0
    assert browser('ECGReportSections.derivatives(x)',f.beats)==result


def test_nn_extrema_exclude_reviewed_rhythm_without_suppressing_rr_extrema():
    f=recording([800]*30)
    f.duration+=.005  # Last R must be a sample inside the half-open recording.
    original=build_index(f)
    a=dict(id=1,sample_index=0,details=dict(kind='AF',status='confirmed',end_sample=int(f.duration*200)))
    index=build_index(f,annotations=[a])
    assert query_index(index,{'category':'fastest','fast_slow_mode':'nn'})['total']==0
    assert query_index(index,{'category':'fastest','fast_slow_mode':'rr'})['total']==30
    assert index['basis_versions']['fastest']!=original['basis_versions']['fastest']
    assert index['basis_versions']['S']==original['basis_versions']['S']
    assert browser('ECGClinicalAnalysis.buildIndex(x.f,[],[x.a])',dict(f=vars(f),a=a))==index


@pytest.mark.parametrize('kind,label',[('AF','房颤'),('AFL','房扑'),('ST','ST 改变'),('STRIP','人工图条'),('AT','房速'),('VT','室速')])
def test_explicit_annotation_kind_has_correct_default_label(kind,label):
    f=recording([800]*10)
    a=dict(id=1,sample_index=0,details=dict(kind=kind,status='confirmed',end_sample=1000))
    index=build_index(f,annotations=[a])
    event=next(e for e in index['events'] if e['event_id']=='annotation:1')
    assert event['label']==label
    assert event['diagnosis_status']=='pending'  # Label is not implicit approval.
    assert browser('ECGClinicalAnalysis.buildIndex(x.f,[],[x.a])',dict(f=vars(f),a=a))==index


@pytest.mark.parametrize('anchor,expected',[(820,5),(840,10)])
def test_dc_last_complete_window_and_known_amplitude(anchor,expected):
    f=recording(([800]*30+[anchor]+[800]*29)*20)
    result=rr_derivatives(f.beats)
    assert result['dc']['anchor_count']==20  # Last window ends at the final RR.
    assert result['dc']['dc_ms']==expected  # (anchor+800-800-800)/4, exactly.
    assert browser('ECGReportSections.derivatives(x)',f.beats)==result
    short=recording([800]*30+[820]+[800]*29)
    assert rr_derivatives(short.beats)['dc']['anchor_count']==1
    assert rr_derivatives(short.beats)['dc']['dc_ms'] is None


def test_p_and_t_annotations_do_not_become_rr_boundaries():
    f=pvc_recording();original=rr_derivatives(f.beats)
    rows=copy.deepcopy(f.beats)
    for code in ('O','Y','T'):
        rows.append(dict(sample_index=1630+(ord(code)%7),class_code=code,rr_ms=0))
    rows.sort(key=lambda r:r['sample_index'])
    assert rr_derivatives(rows)==original
    base=dict(rows=f.beats,events=[]);with_markers=dict(rows=rows,events=[])
    assert evidence(base)['scatter']==evidence(with_markers)['scatter']
    assert browser('ECGReportSections.evidence(x)',with_markers)==evidence(with_markers)


def test_rhythm_annotation_policy_and_api_hrv_use_current_review(client):
    annotations=[dict(sample_index=0,details=dict(kind='AF',end_sample=200,status=s)) for s in ('pending','confirmed','excluded')]
    assert annotation_exclusions(annotations)==[(0,1.005),(0,1.005)]
    assert browser('ECGRRQuality.annotationExclusions(x)',annotations)==[[0,1.005],[0,1.005]]
    case=client.get('/api/cases').json['items'][0];base=f"/api/cases/{case['case_id']}"
    end=math.floor(case['technical']['duration_seconds_raw']*200)-1
    before=client.get(base+'/hrv-windows').json['periods']['full']['nn_count']
    assert before>0
    response=client.post(base+'/annotations',json=dict(sample_index=0,lead='全部',category='note',label='合成测试区间',details=dict(kind='AF',status='confirmed',end_sample=end)))
    assert response.status_code==201,response.json
    assert client.get(base+'/hrv-windows').json['periods']['full']['nn_count']==0
    assert client.get(base+'/hrv?analysis=edited').json['calculated']['nn_count']==0
    assert client.get(base+'/report-statistics').json['hrv']['nn_count']==0
