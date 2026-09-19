"""Rate candidates are ranked evidence, not additional diagnoses or summary extrema."""
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from ecg_core.clinical_analysis import build_index, query_index, normalize_selection, validate_report


def candidate_feed(count=701):
    rows=[]
    sample=0
    for i in range(count):
        rr=300+(i*37%301)*5 if i else 0
        sample+=rr//5
        rows.append(dict(id=f's:{sample}',sample_index=sample,class_code='N',name='N',rr_ms=rr,hr=round(60000/rr,1) if rr else None))
    return SimpleNamespace(beats=rows,markers=[],duration=sample/200+1,
                           document={'settings':dict(nn_min=300,nn_max=2000,pause=2.5,tachy=120,brady=50)})


@pytest.mark.parametrize('category,direction',[('fastest',1),('slowest',-1)])
def test_two_hundred_real_candidates_sorted_before_pagination(category,direction):
    feed=candidate_feed()
    index=build_index(feed)
    expected=sorted(feed.beats[1:],key=lambda r:(direction*r['rr_ms'],r['sample_index'],r['id']))[:200]
    pages=[query_index(index,{'category':category,'offset':offset,'limit':50}) for offset in range(0,200,50)]
    rows=[item for page in pages for item in page['items']]
    assert all(p['total']==200 and p['category_counts'][category]==200 for p in pages)
    assert all(p['sort_order']=='hr_desc' and p['candidate_limit']==200 for p in pages)
    assert len({r['event_id'] for r in rows})==200
    assert {r['sample_index'] for r in rows}=={r['sample_index'] for r in expected}
    assert [r['hr'] for r in rows]==sorted([r['hr'] for r in rows],reverse=True)
    reverse=query_index(index,{'category':category,'sort':'hr_asc','limit':200})
    assert [r['hr'] for r in reverse['items']]==sorted(r['hr'] for r in rows)
    assert query_index(index,{'category':category,'offset':200})['items']==[]


def test_short_invalid_noise_nn_and_deterministic_ties():
    feed=candidate_feed(10)
    feed.beats[1].update(class_code='X',hr=600,rr_ms=100)
    feed.beats[2].update(hr=None)
    feed.beats[3].update(hr=float('inf'))
    feed.beats[4].update(hr=0)
    feed.beats[5].update(class_code='S')
    feed.beats[7].update(hr=60,rr_ms=1000)
    feed.beats[8].update(hr=60,rr_ms=1000)
    index=build_index(feed)
    rr=query_index(index,{'category':'fastest'})
    assert rr['total']==5
    tied=[r['sample_index'] for r in rr['items'] if r['rr_ms']==1000]
    assert tied==sorted(tied)
    nn=query_index(index,{'category':'slowest','fast_slow_mode':'nn'})
    assert nn['total']==3
    assert {r['sample_index'] for r in nn['items']}=={r['sample_index'] for r in feed.beats[7:]}
    assert query_index(build_index(candidate_feed(1)),{'category':'fastest'})['total']==0
    with pytest.raises(ValueError,match='排序'):query_index(index,{'category':'fastest','sort':'bad'})


def test_saved_ids_and_cross_page_selection_stay_resolvable():
    review={'steps':{'edit':{'status':'done'},'stt':{'status':'done'}}}
    feed=candidate_feed()
    index=build_index(feed,review=review)
    original=min(feed.beats[1:],key=lambda r:r['rr_ms'])
    original_id=f"fastest:RR:{original['id']}:{original['id']}"
    assert original_id in {e['event_id'] for e in index['events']}
    picks=query_index(index,{'category':'fastest','offset':150,'limit':50})['items'][::49]
    selection=normalize_selection({'selected_events':picks,'category_reviews':index['basis_versions']})
    assert len(validate_report(index,selection,review,True))==2
    resolved=query_index(index,{'ids':'|'.join(e['event_id'] for e in picks)})
    assert {e['event_id'] for e in resolved['items']}=={e['event_id'] for e in picks}
    assert query_index(index,{'category':'fastest','fast_slow_mode':'both'})['total']==400


def test_demo_python_index_and_rate_query_parity():
    feed=candidate_feed()
    params=[dict(category=c,sort=s,offset=o,limit=50,fast_slow_mode=m)
            for c in ('fastest','slowest') for s in ('hr_desc','hr_asc')
            for o in (0,150,350) for m in ('rr','nn','both')]
    script="const a=require('./static/js/clinical-analysis.js'),x=JSON.parse(require('fs').readFileSync(0,'utf8')),i=a.buildIndex(x.feed);console.log(JSON.stringify({index:i,queries:x.params.map(p=>a.queryIndex(i,new URLSearchParams(p)))}))"
    actual=json.loads(subprocess.check_output(['node','-e',script],input=json.dumps({'feed':vars(feed),'params':params}).encode(),cwd=Path(__file__).parents[1]))
    index=build_index(feed)
    assert actual['index']==index
    assert actual['queries']==json.loads(json.dumps([query_index(index,p) for p in params]))


def test_api_rate_candidates_and_report_strip(client):
    case=client.get('/api/cases').json['items'][0]['case_id']
    path=f'/api/cases/{case}'
    for category in ('fastest','slowest'):
        result=client.get(path+'/report-events',query_string={'category':category,'limit':200}).json
        assert result['total']==200 and len(result['items'])==200
        assert result['items'][0]['hr']>=result['items'][-1]['hr']
        candidate=result['items'][190]
        strip=client.get(path+'/report-strip',query_string={'event_id':candidate['event_id'],'basis_version':candidate['basis_version'],'duration':7,'leads':'II,V1,V5'})
        assert strip.status_code==200
        assert strip.json['strip']['visible_beat_count']>=5
        assert strip.json['waveform']['duration_s']>=7


def test_rate_controls_are_wired_to_backend_sort_and_pagination():
    text=(Path(__file__).parents[1]/'static/js/clinical-ui.js').read_text()
    for expected in ('sort:reportSort','id="v2RateSort"','id="v2ReportPage"','从快到慢','从慢到快','candidate-rate','reportStrip(e,selected().find'):
        assert expected in text
