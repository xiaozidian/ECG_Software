"""Exact return-to-evidence positioning, not just first-page rendering."""
import json
import subprocess
from copy import deepcopy

import pytest
from ecg_core.clinical_analysis import build_index, query_index
from test_report_workspace import feed


def browser_query(index, params):
    script = """const a=require('./static/js/clinical-analysis.js');
const x=JSON.parse(require('fs').readFileSync(0,'utf8'));
try{console.log(JSON.stringify(a.queryIndex(x.index,x.params)))}
catch(e){console.log(JSON.stringify({error:e.message}))}"""
    return json.loads(subprocess.check_output(['node', '-e', script],
        input=json.dumps(dict(index=index, params=params)), text=True))


@pytest.mark.parametrize('category,mode,sort', [
    ('S','single','time'), ('fastest','RR','hr_desc'),
    ('slowest','NN','hr_asc'), ('fastest','NN','hr_desc')])
@pytest.mark.parametrize('position', [0, 49, 50, 149])
def test_return_loads_target_page_without_mutating_or_changing_counts(category, mode, sort, position):
    index = build_index(feed())
    index['start_time'] = '2026-09-29 08:00:00'
    params = dict(category=category, mode=mode, sort=sort, fast_slow_mode='both', limit=200)
    base = query_index(index, params)
    target = base['items'][position]
    before = deepcopy(index)
    located = dict(params, limit=50, locate_event=target['event_id'], locate_basis=target['basis_version'])
    result = query_index(index, located)
    assert json.loads(json.dumps(result)) == browser_query(index, located)
    assert result['focus_index'] == position
    assert result['offset'] == position//50*50
    assert result['items'][position%50]['event_id'] == target['event_id']
    assert result['total'] == base['total']
    assert result['time_bins'] == base['time_bins']
    assert index == before


@pytest.mark.parametrize('condition', ['missing', 'stale', 'no_basis', 'filtered', 'ids'])
def test_invalid_return_never_silently_selects_first_candidate(condition):
    index = build_index(feed())
    target = query_index(index, dict(category='S'))['items'][0]
    params = dict(category='S', locate_event=target['event_id'], locate_basis=target['basis_version'])
    if condition == 'missing': params['locate_event'] = 'removed'
    if condition == 'stale': params['locate_basis'] = 'older'
    if condition == 'no_basis': del params['locate_basis']
    if condition == 'filtered': params.update(time_start=0, time_end=target['time_s'])
    if condition == 'ids': params['ids'] = target['event_id']
    with pytest.raises(ValueError) as error: query_index(index, params)
    assert browser_query(index, params) == {'error': str(error.value)}


def test_locate_applies_after_time_filter_and_respects_half_open_end():
    index=build_index(feed())
    all_items=query_index(index, dict(category='S',limit=200))['items']
    first,target,last=all_items[20],all_items[90],all_items[120]
    params=dict(category='S',limit=50,time_start=first['time_s'],time_end=last['time_s'],
                locate_event=target['event_id'],locate_basis=target['basis_version'])
    result=query_index(index,params)
    assert json.loads(json.dumps(result))==browser_query(index,params)
    assert result['focus_index']==70 and result['offset']==50 and result['total']==100


def test_production_navigation_functions():
    subprocess.run(['node','tests/browser_report_navigation.cjs'],check=True)
