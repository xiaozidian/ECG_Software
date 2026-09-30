"""Optional, deterministic candidate projection; never changes clinical evidence."""
import json
import subprocess
from copy import deepcopy

import pytest

from ecg_core.clinical_analysis import build_index, query_index
from test_rate_candidates import candidate_feed
from test_report_navigation import browser_query


@pytest.mark.parametrize('category', ['fastest', 'slowest'])
@pytest.mark.parametrize('spacing', [0, 7, 30, 60])
def test_spacing_parity_rank_priority_sort_independence_and_no_mutation(category, spacing):
    index = build_index(candidate_feed())
    before = deepcopy(index)
    params = dict(category=category, fast_slow_mode='both', candidate_spacing_s=spacing, limit=200)
    original = query_index(index, dict(params, candidate_spacing_s=0))
    kept = []
    for e in sorted((e for e in index['events'] if e['category']==category), key=lambda e:(e['candidate_rank'], e['start_sample'], e['event_id'])):
        if all(e['subtype']!=k['subtype'] or abs(e['time_s']-k['time_s'])>=spacing-1e-9 for k in kept):
            kept.append(e)
    expected = {e['event_id'] for e in kept}
    for sort in ['hr_desc', 'hr_asc', 'time']:
        p = dict(params, sort=sort)
        result = query_index(index, p)
        assert json.loads(json.dumps(result)) == browser_query(index, p)
        pages = [query_index(index, dict(p, offset=i, limit=50)) for i in range(0, result['total'], 50)]
        assert {e['event_id'] for page in pages for e in page['items']} == expected
        assert result['candidate_unspaced_total'] == 400
        assert result['candidate_hidden_count'] == 400-len(expected)
        for field in ['time_bins', 'category_counts', 'basis_versions', 'confirmed_category_counts']:
            assert result[field] == original[field]
    assert index == before


def test_time_filter_before_spacing_and_exact_boundary_and_sequence_independence():
    index = build_index(candidate_feed(20))
    events = [e for e in index['events'] if e['category']=='fastest']
    index['events'] = [dict(events[0], event_id=str(i), subtype=seq, candidate_rank=rank,
                            start_sample=t*200, sample_index=t*200, time_s=t)
                       for i,(t,rank,seq) in enumerate([(0,1,'RR'),(6,2,'RR'),(7,3,'RR'),(14,4,'RR'),(0,1,'NN')])]
    p = dict(category='fastest', candidate_spacing_s=7, fast_slow_mode='both')
    result = query_index(index,p)
    assert {e['event_id'] for e in result['items']} == {'0','2','3','4'}
    p.update(time_start=6,time_end=15)
    result = query_index(index,p)
    assert {e['event_id'] for e in result['items']} == {'1','3'}
    assert result['candidate_unspaced_total']==3 and result['candidate_hidden_count']==1
    assert json.loads(json.dumps(result)) == browser_query(index,p)
    assert query_index(index,dict(p, time_start=6,time_end=7))['total']==1


@pytest.mark.parametrize('value', [True, False, None, '', '7.0', ' 7', 'nan', -1, 1, 7.1, 61, [], {}])
def test_malformed_spacing_rejected_in_both_engines(value):
    index = build_index(candidate_feed(10))
    p=dict(category='fastest',candidate_spacing_s=value)
    with pytest.raises(ValueError,match='定位点间隔') as error:
        query_index(index,p)
    assert browser_query(index,p)=={'error':str(error.value)}


def test_saved_ids_bypass_spacing_and_hidden_target_not_replaced():
    index = build_index(candidate_feed())
    p=dict(category='fastest',limit=200)
    full=query_index(index,p)
    filtered=query_index(index,dict(p,candidate_spacing_s=60))
    target=next(e for e in full['items'] if e['event_id'] not in {x['event_id'] for x in filtered['items']})
    focus=dict(p,candidate_spacing_s=60,locate_event=target['event_id'],locate_basis=target['basis_version'])
    with pytest.raises(ValueError,match='不在当前筛选内'):query_index(index,focus)
    restored=query_index(index,dict(focus,candidate_spacing_s=0))
    assert restored['items'][restored['focus_index']]['event_id']==target['event_id']
    resolved=query_index(index,dict(p,candidate_spacing_s=60,ids=target['event_id']))
    assert resolved['items']==[target] and resolved['candidate_spacing_s']==0
    assert query_index(index,dict(category='all',candidate_spacing_s=60))['candidate_spacing_s']==0
    assert query_index(build_index(candidate_feed(1)),dict(p,candidate_spacing_s=60))['total']==0


def test_browser_exact_return_clears_spacing_before_query():
    subprocess.run(['node','tests/browser_report_freshness.cjs','focus'],check=True)


def test_live_endpoint_projects_before_pagination_without_changing_basis(client):
    case=client.get('/api/cases').json['items'][0]['case_id']
    path=f'/api/cases/{case}/report-events'
    full=client.get(path,query_string=dict(category='fastest',limit=200)).json
    params=dict(category='fastest',candidate_spacing_s=7,limit=50)
    response=client.get(path,query_string=params)
    assert response.status_code==200
    data=response.json
    assert data['candidate_unspaced_total']==full['total']==200
    assert data['total']<=200 and data['basis_versions']==full['basis_versions']
    assert data['time_bins']==full['time_bins']
    ids=[]
    for offset in range(0,data['total'],50):
        ids.extend(e['event_id'] for e in client.get(path,query_string=dict(params,offset=offset)).json['items'])
    assert len(set(ids))==data['total']
    assert set(ids)<={e['event_id'] for e in full['items']}
    assert client.get(path,query_string=dict(params,candidate_spacing_s='NaN')).status_code==400
