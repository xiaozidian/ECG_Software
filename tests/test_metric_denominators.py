"""Cross-surface denominators use the same measured RR, not hidden cutoffs."""
import json
from pathlib import Path
import subprocess

import pytest

from ecg_core.beat_editor import EditedRecords, blank, edited_hrv
from ecg_core.clinical_analysis import build_index
from ecg_core.ebi import metrics, HEADER_SIZE, RECORD
from ecg_core.report_layout import report_statistics
from test_analysis_provenance import synthetic_case, synthetic_app

ROOT=Path(__file__).parents[1]


def make(samples,groups=None,duration=None):
    source=[(s,0,(groups or [1]*len(samples))[i],0,0,0,0) for i,s in enumerate(samples)]
    return EditedRecords(source,blank(),[],duration if duration is not None else (max(samples,default=0)+1)/200)


def browser(f):
    script="""const fs=require('fs'),B=require('./static/js/beat-engine.js'),O=require('./static/js/overview-engine.js');
const f=JSON.parse(fs.readFileSync(0,'utf8')),rows=O.decode({duration_s:f.duration,rows:f.beats.map(r=>[r.sample_index,r.rr_ms,r.class_code])});
console.log(JSON.stringify({metrics:B.metrics(f,f.duration),overview:O.stats(rows,f.document.settings.pause,f.duration),histogram:O.histogram(rows).bins.reduce((n,b)=>n+b.count,0)}));"""
    payload={k:getattr(f,k) for k in ('beats','duration','document')}
    return json.loads(subprocess.check_output(['node','-e',script],cwd=ROOT,text=True,input=json.dumps(payload)))


@pytest.mark.parametrize('samples,groups,duration',[
    ([0,500,1001,1601,2202,4402],None,None),
    ([0,200,400,1000,1200,1400],[1,3,34,1,2,1],None),
    ([0,160,200,240],None,None), # No hidden 250 ms lower cutoff either.
    ([0,200,400],None,2),
    ([0],None,2),([],None,2),([0,200],[34,34],2),
])
def test_overview_editor_report_and_demo_share_measured_rr(samples,groups,duration):
    f=make(samples,groups,duration);m=metrics(f,f.duration)
    r=report_statistics(build_index(f),None,f.document['settings'])['summary']
    b=browser(f);o=b['overview']
    assert b['metrics']==m
    assert m['valid_beats']==o['valid']==r['total']
    assert m['rr_interval_count']==o['rr_interval_count']==b['histogram']==r['rr_interval_count']
    assert m['rate_interval_count']==r['rate_interval_count']
    assert m['avg_hr_from_rr']==r['avg_hr']
    assert m['longest_rr_ms']==(r['longest']['rr_ms'] if r['longest'] else None)
    assert o['pauses']==r['pause'] and o['pause_over3']==r['pause_over3']


@pytest.mark.parametrize('threshold',[2.5,3,5])
def test_report_pause_is_strict_fixed_threshold_editor_alert_is_configurable(threshold):
    f=make([0,500,1001,1601,2202,4402]);f.document['settings']['pause']=threshold
    b=browser(f)
    assert b['overview']['pauses']==4 and b['overview']['pause_over3']==2
    assert b['overview']['alert_pauses']==sum(r['rr_ms']>=threshold*1000 for r in f.beats)
    assert b['metrics']['avg_hr_from_rr']==round(60000/(22010/5),2)
    assert edited_hrv(f)['nn_count']==0 # NN has different intentional inclusion rules.


def test_noise_and_first_beat_are_not_counted_as_measured_intervals():
    f=make([0,200,400,1000,1200,1400],[1,3,34,1,2,1]);b=browser(f)
    assert b['overview']['total']==6 and b['overview']['valid']==5
    assert b['overview']['counts']['X']==1
    assert b['metrics']['rr_interval_count']==3
    assert b['metrics']['avg_hr_from_rr']==60 and b['overview']['pauses']==0


def test_missing_or_inconsistent_cached_hr_does_not_remove_long_rr():
    f=make([0,2200]);f.beats[-1]['hr']=999
    m=metrics(f,f.duration);b=browser(f)
    assert m==b['metrics']
    assert m['rate_interval_count']==0 and m['avg_hr_from_rr'] is None
    assert m['rr_interval_count']==1 and m['longest_rr_ms']==11000


def test_overview_decode_rejects_bad_rr_in_histogram_and_trends():
    script="""const E=require('./static/js/overview-engine.js');
const rows=E.decode({duration_s:5,rows:[[0,1000,'N'],[200,1000,'N'],[400,9000,'N'],[600,1000,'X'],[800,1000,'N']]});
console.log(JSON.stringify({valid:rows.filter(E.valid).map(r=>r.sample_index),hist:E.histogram(rows).bins.reduce((n,b)=>n+b.count,0),pairs:E.pairs(rows)}));"""
    r=json.loads(subprocess.check_output(['node','-e',script],cwd=ROOT,text=True))
    assert r==dict(valid=[200],hist=1,pairs=[])


def test_real_api_detail_editor_overview_and_report_match(synthetic_app,synthetic_case):
    _,cid,paths=synthetic_case
    samples=[200,700,1201,1801,2402,4602]
    paths['ebi'].write_bytes(bytes(HEADER_SIZE)+b''.join(RECORD.pack(s,0,1,0,0,0,1000) for s in samples))
    c=synthetic_app.test_client();base='/api/cases/'+cid
    def get(url):
        response=c.get(url);assert response.status_code==200,response.json
        return response.json
    detail=get(base+'?analysis=edited');editor=get(base+'/beat-editor')
    report=get(base+'/report-statistics')['summary'];overview=get(base+'/overview')
    assert detail['calculated']==editor['metrics']
    assert detail['calculated']['avg_hr_from_rr']==report['avg_hr']==13.63
    assert detail['calculated']['rr_interval_count']==report['rr_interval_count']==5
    assert len(overview['rows'])==report['total']==6
    assert sum(r[1]>2500 for r in overview['rows'])==report['pause']==4
    assert get(base+'/hrv?analysis=edited')['calculated']['nn_count']==0
