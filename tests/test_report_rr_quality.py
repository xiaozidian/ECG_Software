"""Report screening must reject malformed intervals without becoming NN-only."""
import copy
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from ecg_core.clinical_analysis import build_index, query_index, validate_report
from ecg_core.report_layout import report_statistics
from ecg_core.rr_quality import valid_rr_rows
from ecg_core.beat_editor import EditedRecords, blank

ROOT = Path(__file__).parents[1]
OPTS = dict(nn_min=300, nn_max=2000, pause=2.5, tachy=120, brady=50)


def feed(intervals, codes=None):
    rows=[dict(id='s:0',sample_index=0,class_code='N',rr_ms=0,hr=None)]
    sample=0
    for i,rr in enumerate(intervals):
        sample+=int(rr/5)
        rows.append(dict(id=f's:{sample}',sample_index=sample,
                         class_code=codes[i] if codes else 'N',rr_ms=rr,hr=round(60000/rr,1)))
    return SimpleNamespace(beats=rows,markers=[],duration=sample/200+.005,document={'settings':OPTS})


def browser(f):
    script="""const C=require('./static/js/clinical-analysis.js'),R=require('./static/js/report-engine.js');
const f=JSON.parse(require('fs').readFileSync(0,'utf8')),i=C.buildIndex(f);
console.log(JSON.stringify({index:i,stats:R.statistics(i,'2026-09-29 23:59:58',f.document.settings)}));"""
    return json.loads(subprocess.check_output(['node','-e',script],cwd=ROOT,text=True,input=json.dumps(vars(f))))


def stats(f):
    i=build_index(f)
    return i,report_statistics(i,'2026-09-29 23:59:58',OPTS)


def test_noise_breaks_both_sides_and_does_not_remove_real_beats():
    f=feed([1000,3000,3000,1000],['N','X','N','N'])
    original=copy.deepcopy(vars(f))
    i,s=stats(f)
    assert s['summary']['total']==4 and s['summary']['noise']==1
    assert s['summary']['rr_interval_count']==2
    assert s['summary']['rate_interval_count']==2
    assert s['summary']['pause']==0 and s['summary']['longest']['rr_ms']==1000
    assert s['summary']['min_hr']==s['summary']['max_hr']==s['summary']['avg_hr']==60
    assert query_index(i,{'category':'fastest'})['total']==2
    assert query_index(i,{'category':'rate','mode':'brady'})['total']==0
    assert vars(f)==original
    assert browser(f)==dict(index=i,stats=s)


@pytest.mark.parametrize('bad',[None,True,'500',0,-5,2000])
def test_invalid_or_inconsistent_rr_never_enters_extrema_or_report(bad):
    f=feed([1000]*4);f.beats[2].update(rr_ms=bad,hr=300)
    i,s=stats(f)
    assert s['summary']['rr_interval_count']==3
    assert s['summary']['max_hr']==60 and s['summary']['avg_hr']==60
    assert query_index(i,{'category':'fastest'})['total']==3
    assert query_index(i,{'category':'rate','mode':'tachy'})['total']==0
    assert browser(f)==dict(index=i,stats=s)


@pytest.mark.parametrize('bad',[float('nan'),float('inf')])
def test_nonfinite_rr_rejected_without_nonfinite_statistics(bad):
    f=feed([1000]*4);f.beats[2].update(rr_ms=bad,hr=300)
    _,s=stats(f)
    json.dumps(s,allow_nan=False)
    assert s['summary']['rr_interval_count']==3 and s['summary']['max_hr']==60


def test_longest_rr_and_pause_do_not_depend_on_missing_cached_hr():
    f=feed([11000]);f.beats[1]['hr']=None
    i,s=stats(f)
    assert s['summary']['pause']==s['summary']['pause_over3']==1
    assert s['summary']['longest']==dict(hr=None,time_s=11,rr_ms=11000)
    assert s['summary']['rr_interval_count']==1 and s['summary']['rate_interval_count']==0
    assert s['summary']['avg_hr'] is None and s['summary']['fastest'] is None
    assert browser(f)==dict(index=i,stats=s)


@pytest.mark.parametrize('bad',[None,True,'60',0,-1,300])
def test_stale_or_invalid_cached_hr_is_not_mixed_with_valid_rr(bad):
    f=feed([1000]*4);f.beats[2]['hr']=bad
    i,s=stats(f)
    assert s['summary']['rr_interval_count']==4
    assert s['summary']['rate_interval_count']==3
    assert s['summary']['min_hr']==s['summary']['max_hr']==s['summary']['avg_hr']==60
    assert query_index(i,{'category':'fastest'})['total']==3
    assert query_index(i,{'category':'rate','mode':'tachy'})['total']==0
    assert browser(f)==dict(index=i,stats=s)


def test_browser_script_order_can_load_report_engine_before_rr_quality():
    script="""const vm=require('vm'),fs=require('fs');
for(const name of ['report-engine','rr-quality','clinical-analysis'])vm.runInThisContext(fs.readFileSync('static/js/'+name+'.js','utf8'));
const f=JSON.parse(fs.readFileSync(0,'utf8'));
console.log(JSON.stringify(ECGReportEngine.statistics(ECGClinicalAnalysis.buildIndex(f),null,f.document.settings)));"""
    result=json.loads(subprocess.check_output(['node','-e',script],cwd=ROOT,text=True,input=json.dumps(vars(feed([1000]*4)))))
    assert result['summary']['avg_hr']==60


def test_rr_is_not_nn_and_does_not_drop_true_long_intervals():
    f=feed([1000,500,3000,3005,11000],['S','V','A','N','N'])
    i,s=stats(f)
    assert s['summary']['rr_interval_count']==5
    assert s['summary']['avg_hr']==round(60000/(18505/5),2)
    assert s['summary']['pause']==3 and s['summary']['pause_over3']==2
    assert s['summary']['longest']['rr_ms']==11000
    assert query_index(i,{'category':'fastest'})['total']==5
    assert query_index(i,{'category':'fastest','fast_slow_mode':'nn'})['total']==0
    assert sum(h['rr_interval_count'] for h in s['hourly'])==5
    assert browser(f)==dict(index=i,stats=s)


def test_non_qrs_markers_do_not_split_interval_and_outside_end_is_not_counted():
    f=feed([1000]*4);f.duration=4
    marker=dict(id='m:300',sample_index=300,class_code='Y',rr_ms=0,hr=None)
    f.markers=[marker]
    i,s=stats(f)
    assert [r['sample_index'] for r in valid_rr_rows([*f.beats[:2],marker,*f.beats[2:]],4)]==[200,400,600]
    assert s['summary']['total']==4 and s['summary']['rr_interval_count']==3
    assert query_index(i,{'category':'fastest'})['total']==3
    assert browser(f)==dict(index=i,stats=s)


@pytest.mark.parametrize('samples,expected',[([0,200,200,400],[1,3]),([0,400,200,600],[])])
def test_duplicate_or_reversed_intervals_are_not_reordered_to_look_valid(samples,expected):
    f=feed([1000]*3)
    for r,s in zip(f.beats,samples):r['sample_index']=s
    good=valid_rr_rows(f.beats,10)
    assert [id(r) for r in good]==[id(f.beats[i]) for i in expected]


def test_old_rate_pause_selection_requires_reselection_but_ectopy_basis_is_unchanged():
    f=feed([3000,1000],['N','V']);i=build_index(f)
    for category in ('fastest','slowest','pause','rate'):
        e=next(e for e in i['events'] if e['category']==category)
        old=copy.deepcopy(e);old['basis_version']=i['beat_version']+('-rr-gt2500-v2' if category=='pause' else '-nn-quality-v2-old' if category in ('fastest','slowest') else '')
        assert validate_report(i,{'selected_events':[old]}, {})==[]
        with pytest.raises(ValueError,match='失效'):
            validate_report(i,{'selected_events':[old]}, {},approving=True)
    assert i['basis_versions']['V'].startswith(i['beat_version']+'-')
    assert 'rr-quality-v3' not in i['basis_versions']['V']


def test_materialized_source_and_report_use_same_noise_boundaries():
    source=[(s,0,g,0,0,0,999) for s,g in [(0,1),(200,1),(800,34),(1400,1),(1600,1)]]
    f=EditedRecords(source,blank(),[],9)
    i=build_index(f);s=report_statistics(i,None,f.document['settings'])['summary']
    assert s['rr_interval_count']==2 and s['avg_hr']==60
    assert s['pause']==0 and query_index(i,{'category':'fastest'})['total']==2
