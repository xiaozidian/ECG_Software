"""Exact episode identity is metadata; it must not alter event bases or diagnosis."""
import json
import subprocess
from copy import deepcopy
import pytest
from ecg_core.clinical_analysis import build_index
from ecg_core.overview import initial_episodes, episode_annotations
from test_report_workspace import feed


@pytest.mark.parametrize('kind', ['AF', 'AFL'])
@pytest.mark.parametrize('origin', ['beat', 'annotation', 'saved'])
def test_report_event_points_to_exact_rhythm_document(kind, origin):
    f=feed();annotations=[]
    if origin=='beat':
        for r in f.beats[5:12]:r['class_code']='A' if kind=='AF' else 'C'
    else:
        annotations=[dict(id=71,sample_index=1000,details=dict(kind=kind,end_sample=1800,status='pending'))]
    initial=initial_episodes(f,annotations,f.duration)
    if origin=='saved':
        annotations=episode_annotations(initial)+[dict(id='rhythm-control',sample_index=0,details={'rhythm_authoritative':True})]
    before=deepcopy(annotations)
    index=build_index(f,annotations=annotations)
    episodes={e['id']:e for e in initial['episodes']}
    for event in [e for e in index['events'] if e['category']=='AF']:
        assert event['rhythm_episode_id'] in episodes
        episode=episodes[event['rhythm_episode_id']]
        assert event['subtype']==episode['kind']
        assert event['time_s']==episode['start_s'] and event['end_s']==episode['end_s']
        assert event['rhythm_status']=='pending'
    assert any(e['category']=='AF' for e in index['events'])
    assert annotations==before
    code="""const a=require('./static/js/clinical-analysis.js');const x=JSON.parse(require('fs').readFileSync(0,'utf8'));console.log(JSON.stringify(a.buildIndex(x.feed,[],x.annotations).events.filter(e=>e.category==='AF')));"""
    raw=dict(beats=f.beats,markers=f.markers,document=f.document,duration=f.duration)
    result=json.loads(subprocess.check_output(['node','-e',code],input=json.dumps(dict(feed=raw,annotations=annotations)),text=True))
    assert result==[e for e in index['events'] if e['category']=='AF']


def test_production_report_roundtrip():
    subprocess.run(['node','tests/browser_rhythm_report_return.cjs'],check=True)
