"""Actual episode ranges and measured extremes, independently of AF state."""
import json
from pathlib import Path
import subprocess

import pytest

from ecg_core.report_layout import stt_representatives, resolve_strip
from test_stt_comprehensive_records import comprehensive_api
from test_analysis_provenance import synthetic_case


def model(start=20, end=200, peak=113.5):
    index = dict(duration_s=300, rows=[dict(sample_index=i*200, class_code='N',
                 hr=60, rr_ms=1000) for i in range(1, 300)])
    event = dict(category='ST', event_id='annotation:math', basis_version='math',
                 start_sample=round(start*200), end_sample=round(end*200)-1,
                 time_s=start, end_s=end, stt_event_evidence=dict(peak_time_s=peak))
    return index, event


@pytest.mark.parametrize('start,end,peak,count', [(20,25,22,1), (20,30,23.5,2),
                         (20,200,113.5,3), (20,200,23.5,2)])
def test_recommendation_count_and_actual_peak(start,end,peak,count):
    index, event = model(start,end,peak)
    result = stt_representatives(index,event,dict(leads=['II'],duration_s=7))
    assert len(result['items']) == count
    assert result['positions']['middle']['anchor_kind'] == 'extreme'
    assert result['positions']['middle']['start_s'] <= peak < result['positions']['middle']['end_s']
    assert result['positions']['start']['start_s'] <= start + .01
    assert result['positions']['end']['end_s'] >= end - .01
    assert (event['time_s'],event['end_s']) == (start,end)
    for p in result['items']:
        spec=resolve_strip(index,event,dict(leads=['II'],duration_s=p['duration_s'],
                  range_start_s=p['start_s'],range_end_s=p['end_s']))
        assert spec['visible_beat_count'] >= 5


def test_missing_extreme_is_labelled_middle_and_child_peak_is_supported():
    index,event=model();event['stt_event_evidence']={}
    result=stt_representatives(index,event)
    assert result['positions']['middle']['anchor_kind']=='middle'
    assert result['positions']['middle']['label']=='段中'
    event['stt_event_evidence']['findings']=[dict(peak_time_s=170)]
    result=stt_representatives(index,event)
    assert result['positions']['middle']['anchor_kind']=='extreme'
    assert result['positions']['middle']['start_s'] <=170<result['positions']['middle']['end_s']


@pytest.mark.parametrize('start,end,peak', [(20,25,22),(20,30,23.5),(20,200,113.5),(20,200,None)])
def test_python_and_pages_resolve_identical_actual_recommendations(start,end,peak):
    index,event=model(start,end,peak)
    payload=dict(index=index,event=event,settings=dict(leads=['II','V1','V5'],duration_s=7))
    root=Path(__file__).resolve().parents[1]
    js="const fs=require('fs'),vm=require('vm');vm.runInThisContext(fs.readFileSync('static/js/report-engine.js','utf8'));const x=JSON.parse(fs.readFileSync(0,'utf8'));process.stdout.write(JSON.stringify(ECGReportEngine.sttRepresentatives(x.index,x.event,x.settings)));"
    value=json.loads(subprocess.check_output(['node','-e',js],input=json.dumps(payload),text=True,cwd=root))
    assert value==stt_representatives(index,event,payload['settings'])


def test_distinct_same_parent_ST_strips_survive_server_and_pages_normalization(comprehensive_api):
    from test_stt_comprehensive_records import review,checked
    client,base=comprehensive_api
    saved=checked(client.post(base+'/annotations',json=review(client,base,'t_low_flat',start=20,end=200)))
    receipt=saved['stt_review_receipt'];eid=receipt['event_id'];basis=receipt['basis_version']
    report=checked(client.get(base+'/report'))
    picks=[dict(event_id=eid,basis_version=basis,strip_id='math-strip:'+str(i),representative_role=role,
        leads=['II'],duration_s=7,range_start_s=start,range_end_s=start+7,caption=role)
        for i,(role,start) in enumerate([('start',20),('middle',80),('end',193)])]
    uses=[dict(event_id=eid,basis_version=basis,table=True,text=True,strip=True)]
    composition={**report['composition'],'schema_version':3,'included_pages':['st_events','event_strips'],
        'stt_report_use':uses,'selected_events':picks}
    response=checked(client.put(base+'/report',json=dict(status='draft',expected_version=report['version'],composition=composition)))
    assert len(response['composition']['selected_events'])==3
    reopened=checked(client.get(base+'/report'))
    assert [p['strip_id'] for p in reopened['composition']['selected_events']]==[p['strip_id'] for p in picks]
    events=checked(client.get(base+'/report-events?category=ST'))['items']
    from ecg_core.rr_report import deduplicate_rr_selections
    index=dict(events=events,rows=[dict(sample_index=i*200,class_code='N',rr_ms=1000,hr=60) for i in range(1,360)],duration_s=360)
    assert len(deduplicate_rr_selections(index,picks)[0])==3
    # Exactly duplicate geometry is still merged, preserving the first curation.
    duplicate={**picks[0],'strip_id':'different-ID-same-geometry'}
    assert len(deduplicate_rr_selections(index,picks+[duplicate])[0])==3
    root=Path(__file__).resolve().parents[1]
    js="const fs=require('fs');require('./static/js/rr-quality.js');require('./static/js/report-engine.js');const a=require('./static/js/clinical-analysis.js');const x=JSON.parse(fs.readFileSync(0,'utf8'));console.log(JSON.stringify(a.normalizeReportSelections(x.index,x.picks)));"
    browser=json.loads(subprocess.check_output(['node','-e',js],input=json.dumps(dict(index=index,picks=picks+[duplicate])),text=True,cwd=root))
    assert [p['strip_id'] for p in browser]==[p['strip_id'] for p in picks]
