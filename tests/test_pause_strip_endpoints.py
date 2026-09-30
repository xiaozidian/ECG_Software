"""Curated long-RR evidence must contain the actual two sampled R peaks."""
import copy
import json
import subprocess
import struct
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from ecg_core.clinical_analysis import build_index, validate_report
from ecg_core.report_layout import resolve_strip
from ecg_core.ebi import HEADER_SIZE, RECORD
from test_analysis_provenance import synthetic_case

ROOT = Path(__file__).resolve().parents[1]
OPTS = dict(nn_min=300, nn_max=2000, pause=2.5, tachy=120, brady=50)


def case(first=1, rr_delta=0):
    samples = [first, first+601, first+801, first+1001, first+1201, first+1401]
    rows = [dict(id=f's:{s}', sample_index=s, class_code='N',
                 rr_ms=(s-samples[i-1])*5 if i else 0, hr=None)
            for i, s in enumerate(samples)]
    rows[1]['rr_ms'] += rr_delta  # Legacy RR accepts ±10 ms vs sample spacing.
    feed = SimpleNamespace(beats=rows, markers=[], duration=(samples[-1]+100)/200,
                           document={'settings': OPTS})
    index = build_index(feed)
    event = next(e for e in index['events'] if e['category']=='pause')
    settings = dict(range_start_s=first/200, range_end_s=(samples[-1]+1)/200)
    return feed, index, event, settings


def browser(index, event, settings):
    script = """const R=require('./static/js/report-engine.js');
const p=JSON.parse(require('fs').readFileSync(0,'utf8'));
try { console.log(JSON.stringify({result:R.resolve(p.index,p.event,p.settings)})); }
catch(e) { console.log(JSON.stringify({error:e.message})); }"""
    return json.loads(subprocess.check_output(['node','-e',script],cwd=ROOT,text=True,
        input=json.dumps(dict(index=index,event=event,settings=settings))))


@pytest.mark.parametrize('first',[1,7,201,200001,17200001])
@pytest.mark.parametrize('rr_delta',[-10,0,10])
def test_exact_first_r_boundary_is_accepted_in_both_engines(first, rr_delta):
    _, index, event, settings = case(first, rr_delta)
    spec = resolve_strip(index, event, settings)
    assert [b['sample_index'] for b in spec['visible_beats']][:2]==[first, first+601]
    assert spec['visible_beat_count']==6
    assert browser(index,event,settings)==dict(result=spec)


@pytest.mark.parametrize('rr_delta',[-10,0,10])
def test_one_sample_after_first_r_is_rejected_even_with_five_later_beats(rr_delta):
    _, index, event, settings = case(201, rr_delta)
    settings['range_start_s'] += .005
    with pytest.raises(ValueError,match='两个 R 峰'):
        resolve_strip(index,event,settings)
    assert '两个 R 峰' in browser(index,event,settings)['error']


def test_end_boundary_is_half_open_at_second_r():
    _, index, event, settings = case()
    settings['range_end_s'] = event['start_sample']/200
    with pytest.raises(ValueError,match='定位心搏'):
        resolve_strip(index,event,settings)
    assert '定位心搏' in browser(index,event,settings)['error']


@pytest.mark.parametrize('code',['O','Y','T'])
def test_non_qrs_markers_do_not_replace_the_first_r(code):
    feed,index,event,settings = case(201,-10)
    marker=dict(id='marker',sample_index=401,class_code=code,rr_ms=0,hr=None)
    feed.markers=[marker]
    index=build_index(feed)
    settings['range_start_s']=202/200
    with pytest.raises(ValueError,match='两个 R 峰'):
        resolve_strip(index,event,settings)
    assert '两个 R 峰' in browser(index,event,settings)['error']


@pytest.mark.parametrize('change',['first_noise','last_noise','rr_conflict','missing_first'])
def test_unresolvable_pause_is_rejected_not_reconstructed_from_old_event(change):
    _,index,event,settings=case()
    if change=='first_noise':index['rows'][0]['class_code']='X'
    elif change=='last_noise':index['rows'][1]['class_code']='X'
    elif change=='rr_conflict':index['rows'][1]['rr_ms']=8000
    else:index['rows'].pop(0)
    with pytest.raises(ValueError,match='R 峰依据已变化'):
        resolve_strip(index,event,settings)
    assert 'R 峰依据已变化' in browser(index,event,settings)['error']


def test_range_validation_does_not_change_samples_or_report_counts():
    _,index,event,settings=case(201,10)
    before=copy.deepcopy(index)
    chosen={**event,**settings}
    assert len(validate_report(index,{'selected_events':[chosen]},{}))==1
    assert index==before


def test_previous_pause_contract_requires_reselection_only_for_pause():
    _,index,event,settings=case()
    stale={**event,**settings,'basis_version':index['beat_version']+'-rr-gt2500-v3'}
    assert validate_report(index,{'selected_events':[stale]}, {})==[]
    with pytest.raises(ValueError,match='失效'):
        validate_report(index,{'selected_events':[stale]}, {},approving=True)


@pytest.mark.parametrize('rr_delta',[-10,0,10])
def test_auto_range_uses_sampled_first_r_not_cached_interval(rr_delta):
    feed,_,_,_=case(1000)
    for r in feed.beats[1:]:r['sample_index']+=1600
    feed.beats[1]['rr_ms']=11005+rr_delta
    feed.duration+=8
    index=build_index(feed)
    event=next(e for e in index['events'] if e['category']=='pause')
    assert event['rr_start_sample']==1000 and event['rr_end_sample']==3201
    spec=resolve_strip(index,event)
    assert spec['start_s']==4.8
    assert spec['visible_beat_count']>=5
    assert browser(index,event,{})==dict(result=spec)


def test_preview_save_export_and_relabel_use_same_sample_boundaries(synthetic_case,tmp_path,monkeypatch):
    import app as server
    root,cid,paths=synthetic_case
    samples=[1,602,802,1002,1202,1402]
    paths['ebi'].write_bytes(bytes(HEADER_SIZE)+b''.join(
        RECORD.pack(s,1,1,0,0,0,3005 if i==1 else 1000 if i else 0)
        for i,s in enumerate(samples)))
    raw=bytearray(paths['data'].read_bytes())
    for s in samples:struct.pack_into('<h',raw,s*16+2,500)
    paths['data'].write_bytes(raw)
    original={k:sha256(p.read_bytes()).hexdigest() for k,p in paths.items()}
    app=server.create_app(data_root=root,db_path=tmp_path/'pause.db',testing=True)
    client=app.test_client();base=f'/api/cases/{cid}'
    query=client.get(base+'/report-events?category=pause').json
    assert query['pause_counts']=={'all':1,'over3':1,'2.5to3':0}
    event=query['items'][0]
    assert (event['rr_start_sample'],event['rr_end_sample'])==(1,602)
    params=dict(event_id=event['event_id'],basis_version=event['basis_version'],
                range_start_s=.005,range_end_s=7.015)
    response=client.get(base+'/report-strip',query_string=params)
    assert response.status_code==200,response.json
    preview=response.json
    assert preview['strip']['visible_beat_count']==6
    assert preview['waveform']['start_s']==.005
    assert preview['waveform']['leads']['II'][0]==500
    assert preview['waveform']['leads']['II'][601]==500
    rejected=client.get(base+'/report-strip',query_string={**params,'range_start_s':.01})
    assert rejected.status_code==400 and '两个 R 峰' in rejected.json['error']
    report=client.get(base+'/report').json
    payload=dict(expected_version=report['version'],status='draft',conclusion='合成测试',
        composition=dict(page_selection_version=1,included_pages=['event_strips'],selected_events=[params]))
    saved=client.put(base+'/report',json=payload)
    assert saved.status_code==200,saved.json
    bad=copy.deepcopy(payload)
    bad['expected_version']=saved.json['version']
    bad['composition']['selected_events'][0]['range_start_s']=.01
    denied=client.put(base+'/report',json=bad)
    assert denied.status_code==400 and '两个 R 峰' in denied.json['error']
    assert client.get(base+'/report').json['version']==saved.json['version']
    captured=[];build=server.build_report_pdf
    def capture(case,calculated,report):
        captured.extend(report['selected_waveforms'])
        return build(case,calculated,report)
    monkeypatch.setattr(server,'build_report_pdf',capture)
    pdf=client.get(base+'/report.pdf')
    assert pdf.status_code==200 and pdf.data.startswith(b'%PDF'),pdf.json
    assert len(captured)==1 and captured[0]['strip']==preview['strip']
    assert captured[0]['waveform']['leads']==preview['waveform']['leads']
    revision=client.get(base+'/beat-editor').json['revision']
    changed=client.put(base+'/beat-editor',json=dict(operation='relabel',revision=revision,
        confirmed=True,selection={'samples':[1]},class_code='X'))
    assert changed.status_code==200,changed.json
    assert client.get(base+'/report-statistics').json['summary']['pause']==0
    assert client.get(base+'/report-events?category=pause').json['total']==0
    assert client.get(base+'/report-strip',query_string=params).status_code==409
    assert client.get(base+'/report.pdf').status_code==400
    assert client.get(base+'/report').json['composition']['selected_events'] # retained, not silent deletion
    undo=client.put(base+'/beat-editor',json=dict(operation='undo',revision=changed.json['revision'],confirmed=True))
    assert undo.status_code==200,undo.json
    assert client.get(base+'/report-statistics').json['summary']['pause']==1
    assert client.get(base+'/report-events?category=pause').json['pause_counts']==query['pause_counts']
    assert client.get(base+'/report-strip',query_string=params).json['strip']==preview['strip']
    assert client.get(base+'/report').json['status']=='draft'
    assert {k:sha256(p.read_bytes()).hexdigest() for k,p in paths.items()}==original
