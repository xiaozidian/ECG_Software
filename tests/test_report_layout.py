from __future__ import annotations

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import pytest
from ecg_core.clinical_analysis import build_index, normalize_selection, validate_report
from ecg_core.report_layout import LEADS, report_statistics, resolve_strip, strip_settings
from ecg_core.storage import Storage

ROOT = Path(__file__).parents[1]
SETTINGS = dict(nn_min=300, nn_max=2000, pause=2.5, tachy=120, brady=50)


def index_for(times, codes=None, duration=60):
    codes = codes or ['N'] * len(times)
    rows = [dict(id=f's:{int(t*200)}',sample_index=int(t*200),class_code=c,rr_ms=(t-times[i-1])*1000 if i else 0,
                 hr=60000/((t-times[i-1])*1000) if i else None) for i,(t,c) in enumerate(zip(times,codes))]
    return build_index(SimpleNamespace(beats=rows,markers=[],duration=duration,document={'settings':SETTINGS}))


@pytest.mark.parametrize('anchor',[0,2,29.9,58,59.9])
def test_default_window_has_at_least_five_beats_and_stays_in_record(anchor):
    index=index_for(list(range(60)))
    spec=resolve_strip(index,{'start_sample':round(anchor*200)})
    assert spec['duration_s']==7 and spec['actual_duration_s']==7
    assert 0<=spec['start_s']<spec['end_s']<=60
    assert spec['visible_beat_count']>=5


def test_slow_rhythm_extends_and_short_record_is_honest():
    index=index_for(list(range(0,60,2)))
    spec=resolve_strip(index,{'start_sample':30*200})
    assert spec['actual_duration_s']>7 and spec['visible_beat_count']>=5
    assert '延长' in spec['warning']
    small=resolve_strip(index_for([0,2,4],duration=5),{'start_sample':800})
    assert small['start_s']==0 and small['end_s']==5
    assert small['visible_beat_count']==3 and '不足 5' in small['warning']


def test_artifact_and_nonbeat_markers_cannot_satisfy_minimum():
    index=index_for([0,1,2,3,4,5,6,7,8,9],list('NOYTXNNNNN'),duration=10)
    spec=resolve_strip(index,{'start_sample':200})
    assert all(r['class_code']=='N' for r in spec['visible_beats'])
    assert spec['visible_beat_count']>=5


@pytest.mark.parametrize('raw',[{'leads':[]},{'leads':['II','II']},{'leads':['bad']},{'duration_s':0},{'duration_s':True},{'duration_s':float('nan')},{'duration_s':121}])
def test_settings_validation(raw):
    with pytest.raises(ValueError):strip_settings(raw)


def test_leads_duration_persist_and_resolve_without_changing_event(tmp_path):
    index=index_for([0,1,2,3,4,5,6,7],list('NNVNNNNN'))
    event=next(e for e in index['events'] if e['category']=='V')
    comp=normalize_selection({'selected_events':[dict(event_id=event['event_id'],basis_version=event['basis_version'],leads=LEADS,duration_s=7,caption='测试')], 'strip_defaults':{'leads':['V1','II'],'duration_s':9}})
    storage=Storage(tmp_path/'test.db')
    saved=storage.save_report('test','测试','draft','tester',comp,1)
    pick=storage.get_report('test','')['composition']['selected_events'][0]
    assert pick['leads']==LEADS and pick['duration_s']==7
    assert saved['composition']['strip_defaults']['leads']==['II','V1']
    resolved=validate_report(index,saved['composition'],{})[0]
    assert resolved['leads']==LEADS and resolved['target_samples']==[400]


def test_python_demo_window_statistics_parity():
    index=index_for([0,1,2,4,6,8,10,12,14,18],list('NNVNNNSNNN'),duration=20)
    opts={'leads':LEADS,'duration_s':7}
    event={'start_sample':1200}
    program="const R=require('./static/js/report-engine.js'),x=JSON.parse(require('fs').readFileSync(0,'utf8'));console.log(JSON.stringify({spec:R.resolve(x.index,x.event,x.opts),stats:R.statistics(x.index,'2026-09-19 23:59:55',x.settings)}))"
    js=json.loads(subprocess.check_output(['node','-e',program],input=json.dumps(dict(index=index,event=event,opts=opts,settings=SETTINGS)).encode(),cwd=ROOT))
    assert js['spec']==resolve_strip(index,event,opts)
    assert js['stats']==report_statistics(index,'2026-09-19 23:59:55',SETTINGS)
    assert len(js['stats']['hourly'])==2
    assert sum(r['total'] for r in js['stats']['hourly'])==js['stats']['summary']['total']


def test_report_strip_api_resolves_actual_leads_and_five_beats(client):
    case=client.get('/api/cases').json['items'][0]['case_id']
    event=client.get(f'/api/cases/{case}/report-events?category=fastest').json['items'][0]
    response=client.get(f'/api/cases/{case}/report-strip',query_string={'event_id':event['event_id'],'basis_version':event['basis_version'],'leads':','.join(LEADS),'duration':7})
    assert response.status_code==200
    data=response.json
    assert set(data['waveform']['leads'])==set(LEADS)
    assert data['strip']['visible_beat_count']>=5
    assert data['waveform']['duration_s']==data['strip']['actual_duration_s']
    assert client.get(f'/api/cases/{case}/report-strip',query_string={'event_id':event['event_id'],'basis_version':'stale'}).status_code==409
    stats=client.get(f'/api/cases/{case}/report-statistics').json
    assert sum(r['total'] for r in stats['hourly'])==stats['summary']['total']


def test_unverified_voltage_is_not_labeled_or_clipped_as_millivolts():
    program="""require('./static/js/report-paper.js');
    const entry={strip:{leads:['II'],visible_beat_count:5},waveform:{start_s:0,duration_s:7,display_sample_rate_hz:200,leads:{II:[-32768,0,32767]},beats:[]}};
    console.log(ECGReportPaper.stripSvg(entry));"""
    svg=subprocess.check_output(['node','-e',program],cwd=ROOT).decode()
    assert '设备单位，电压未校准' in svg
    assert 'mm/mV' not in svg and '幅度超框' not in svg
    assert '25 mm/s' in svg and 'NaN' not in svg
