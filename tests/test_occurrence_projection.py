"""Pagination must keep complete counts without allocating invisible cards."""
from collections import Counter
from copy import deepcopy
import json
import subprocess

import pytest

from ecg_core import clinical_analysis as analysis
from test_clinical_analysis import feed


def index_fixture():
    source=feed('NNSSNVVXNNAA'*400)
    source.markers=[dict(id='m:200',sample_index=200,class_code='Y',name='P波')]
    source.beats[3]['source_sample']=399  # Edited position.
    source.beats[4]['source_group']=3     # Edited class.
    templates=[dict(id=1,name='测试模板',sample_indices=[r['sample_index'] for r in source.beats[::13]]),
               dict(id=2,name='空模板',sample_indices=[])]
    result=analysis.build_index(source,templates)
    result['start_time']='2000-01-01 23:37:00'
    return result


def expected_page(index,params):
    """Simple independent reference, deliberately builds every visible item."""
    code=params.get('class_code','S');template_id=str(params.get('template_id','all'))
    template=next((t for t in index['templates'] if str(t['id'])==template_id),None)
    selected=set(template['sample_indices']) if template else None
    rows=sorted((r for r in index['rows'] if (code=='all' or r['class_code']==code)
                 and (selected is None or r['sample_index'] in selected)),
                key=lambda r:(r['sample_index'],'beat:'+r['id']))
    count=len(rows);hours=Counter(str(int((r['sample_index']/200)//3600)) for r in rows)
    if 'time_start' in params:
        rows=[r for r in rows if params['time_start']<=r['sample_index']/200<params['time_end']]
    total=len(rows);offset=max(0,params.get('offset',0));limit=max(1,min(200,params.get('limit',100)))
    items=[]
    for r in rows:
        sample=r['sample_index']
        items.append(dict(event_id='beat:'+r['id'],category=code,subtype='beat',label=r.get('name',r['class_code']),
            sample_index=sample,start_sample=sample,end_sample=sample,time_s=sample/200,end_s=sample/200,
            target_samples=[sample],beat_count=1,hr=r.get('hr'),rr_ms=r.get('rr_ms'),
            basis_version=index['beat_version'],templates=[{'id':str(template['id']),'name':template['name']}] if template else [],
            diagnosis_status='pending' if r.get('source_sample')==sample and
                r['class_code']=={1:'N',2:'S',3:'V',34:'X'}.get(r.get('source_group'),'OTHER') else 'edited'))
    return items[offset:offset+limit],total,count,dict(hours)


@pytest.mark.parametrize('clock',[None,'2000-01-01 23:37:00'])
def test_projection_reference_and_browser_parity(clock):
    index=index_fixture();index['start_time']=clock;before=deepcopy(index)
    queries=[dict(class_code=c,template_id=t,offset=o,limit=3)
             for c in ('N','S','V','A','X','Y','all') for t in ('all',1,2) for o in (0,1,4000)]
    queries += [dict(class_code='all',time_start=a,time_end=b,limit=200)
                for a,b in ((0,1),(1,2),(1379,1383),(1380,4800))]
    queries += [dict(class_code='all',limit=1000,offset=-1)]
    script="""
const a=require('./static/js/clinical-analysis.js'),x=JSON.parse(require('fs').readFileSync(0,'utf8'));
let labels=0;
for(const row of x.index.rows){const name=row.name;Object.defineProperty(row,'name',{get(){labels++;return name}})}
const outputs=x.queries.map(params=>{const before=labels;const result=a.queryIndex(x.index,params,true);return {result,materialized:labels-before}});
process.stdout.write(JSON.stringify(outputs));
"""
    browser=json.loads(subprocess.check_output(['node','-e',script],input=json.dumps(dict(index=index,queries=queries)),text=True))
    for params,observed in zip(queries,browser):
        actual=analysis.query_index(index,params,True)
        expected,total,unfiltered,hours=expected_page(index,params)
        assert actual['items']==expected and actual['total']==total
        assert actual['unfiltered_total']==unfiltered
        assert {str(k):v for k,v in actual['time_counts'].items()}==hours
        assert sum(b['count'] for b in actual['time_bins'])==unfiltered
        assert observed['result']==json.loads(json.dumps(actual))
        assert observed['materialized']==len(actual['items'])
    assert index==before


def test_python_materializes_only_current_page(monkeypatch):
    index=index_fixture();calls=[];original=analysis.occurrence_item
    def counted(*args):
        calls.append(args[0]['id'])
        return original(*args)
    monkeypatch.setattr(analysis,'occurrence_item',counted)
    result=analysis.query_index(index,dict(class_code='N',offset=240,limit=24),True)
    assert result['total']==2000 and len(result['items'])==len(calls)==24
    assert ['beat:'+x for x in calls]==[e['event_id'] for e in result['items']]
    calls.clear()
    assert not analysis.query_index(index,dict(class_code='N',offset=100000),True)['items']
    assert calls==[]


def test_resume_by_sample_browser_parity_and_filtered_successor():
    index=index_fixture();before=deepcopy(index)
    queries=[dict(class_code=c,template_id=t,near_sample=s,limit=48)
             for c in ('N','S','all') for t in ('all',1,2)
             for s in (0,200,201,20000,999999)]
    queries += [dict(class_code='V',mode='pair',near_sample=20000,limit=3),
                dict(class_code='N',near_sample=0,time_start=100,time_end=150,limit=3)]
    script="""const a=require('./static/js/clinical-analysis.js'),x=JSON.parse(require('fs').readFileSync(0,'utf8'));process.stdout.write(JSON.stringify(x.queries.map(p=>a.queryIndex(x.index,p,true))));"""
    outputs=json.loads(subprocess.check_output(['node','-e',script],input=json.dumps(dict(index=index,queries=queries)),text=True))
    for p,js in zip(queries,outputs):
        result=analysis.query_index(index,p,True)
        assert js==json.loads(json.dumps(result))
        # Independent full-page collection, not the production binary search.
        base={k:v for k,v in p.items() if k!='near_sample'}
        rows=[]
        for offset in range(0,result['total'],200):rows+=analysis.query_index(index,dict(base,offset=offset,limit=200),True)['items']
        target=next((i for i,r in enumerate(rows) if r['start_sample']>=p['near_sample']),len(rows)-1) if rows else None
        assert result['resume_index']==target
        if rows:
            assert result['resume_sample']==rows[target]['start_sample']
            assert result['items'][target-result['offset']]['start_sample']==rows[target]['start_sample']
        else:assert result['resume_sample'] is None and result['resume_exact'] is False
    assert index==before


@pytest.mark.parametrize('raw',[-1,True,None,{},[],1.5,'','1.2',' 1','1e3','１２',9007199254740992])
def test_resume_rejects_invalid_sample(raw):
    with pytest.raises(ValueError,match='非负整数'):analysis.query_index(index_fixture(),{'near_sample':raw},True)


def test_resume_not_accepted_for_report_candidates():
    with pytest.raises(ValueError,match='仅支持'):analysis.query_index(index_fixture(),{'near_sample':0})
