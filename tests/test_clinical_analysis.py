import json
import subprocess
from types import SimpleNamespace
from pathlib import Path
import pytest
from ecg_core.clinical_analysis import build_index,query_index,hrv_windows,validate_report,normalize_selection
from ecg_core.storage import Storage


def feed(codes,duration=None):
    rows=[dict(id=f's:{i*200}',sample_index=i*200,class_code=c,name=c,rr_ms=1000 if i else 0,hr=60 if i else None,source_sample=i*200,source_group={'N':1,'S':2,'V':3,'X':34}.get(c,4)) for i,c in enumerate(codes)]
    return SimpleNamespace(beats=rows,markers=[],duration=duration or len(rows),document={'settings':dict(nn_min=300,nn_max=2000,pause=2.5,tachy=120,brady=50)})

REVIEW={'steps':{'edit':{'status':'done'},'stt':{'status':'done'}}}

@pytest.mark.parametrize('codes,mode,count',[('NSSN','couplet',1),('NVVN','couplet',1),('NSSSN','triplet',1),('NSSSSN','run',1),('NSNS','bigeminy',1),('NNSNNS','nnp',1),('NSSNSS','npp',1),('NNNSNNNS','quadrigeminy',1),('SNS','couplet',0),('NS','bigeminy',0)])
def test_patterns_on_unfiltered_timeline(codes,mode,count):
    code='V' if 'V' in codes else 'S'
    value=query_index(build_index(feed(codes)),{'class_code':code,'mode':mode},True)
    assert value['total']==count
    assert not any(e['subtype']=='tachycardia' for e in build_index(feed(codes))['events'])


def test_cross_template_and_all_occurrences():
    f=feed('NSSN'+'SNN'*50)
    t=[{'id':1,'name':'S1','sample_indices':[200]+[i*200 for i,r in enumerate(f.beats) if i>3 and r['class_code']=='S']},{'id':2,'name':'S2','sample_indices':[400]}]
    index=build_index(f,t)
    pair=query_index(index,{'class_code':'S','mode':'couplet','template_id':1},True)['items'][0]
    assert pair['target_samples']==[200,400]
    assert {x['name'] for x in pair['templates']}=={'S1','S2'}
    for offset in (12,32,50):
        page=query_index(index,{'class_code':'S','template_id':1,'offset':offset,'limit':1},True)
        assert page['total']==51 and len(page['items'])==1
    assert query_index(index,{'class_code':'V'},True)['total']==0


def test_report_example_statistics_and_selection_are_independent():
    index=build_index(feed('NSNNSNNSNNSSSN'),review=REVIEW)
    data=query_index(index,{'category':'S'})
    assert data['total']==4 and data['beat_counts']['S']==6
    picks=[data['items'][i] for i in (0,1,3)]
    comp=normalize_selection({'selected_events':[{'event_id':e['event_id'],'basis_version':e['basis_version']} for e in picks],'category_reviews':index['basis_versions']})
    chosen=validate_report(index,comp,REVIEW,True)
    assert len(chosen)==3 and len({e['subtype'] for e in chosen})==2
    assert query_index(index,{'category':'S'})['total']==4
    comp['selected_events']=[]
    assert validate_report(index,comp,REVIEW,True)==[]
    comp['category_reviews']={}
    with pytest.raises(ValueError,match='分类筛选'):validate_report(index,comp,REVIEW,True)


def test_annotation_basis_is_scoped_and_stale_selection_rejected():
    f=feed('NSSNN')
    original=build_index(f,review=REVIEW)
    annotation={'id':1,'sample_index':200,'details':{'kind':'ST','status':'confirmed','end_sample':600,'finding':'ST改变'}}
    changed=build_index(f,annotations=[annotation],review=REVIEW)
    assert original['basis_versions']['S']==changed['basis_versions']['S']
    assert original['basis_versions']['ST']!=changed['basis_versions']['ST']
    comp={'selected_events':[{'event_id':'missing','basis_version':'old'}],'category_reviews':changed['basis_versions']}
    with pytest.raises(ValueError,match='失效'):validate_report(changed,comp,REVIEW,True)


def test_hrv_boundaries_gaps_and_windows():
    f=feed('NNNXNNNNNN',duration=10)
    h=hrv_windows(f,'2026-09-12 05:59:55')
    assert h['actual_duration_s']==10 and len(h['hourly'])==2
    assert h['periods']['full']['nn_count']==7
    assert h['periods']['day']['coverage_s']==5
    assert h['periods']['night']['coverage_s']==5
    assert h['periods']['full']['sdnn_ms']==0
    long=feed('NNNN',duration=86410)
    second=hrv_windows(long,'2026-09-12 09:00:00',1)
    assert second['window_count']==2 and second['actual_duration_s']==10
    assert second['periods']['full']['sdnn_ms'] is None


def test_python_browser_parity():
    f=feed('NNSSNNNSSSNNSNNSNNVNVVNNXNNNN')
    templates=[{'id':1,'name':'S1','sample_indices':[400,1400]}]
    annotation={'id':3,'sample_index':400,'details':{'kind':'ST','status':'confirmed','end_sample':800,'finding':'ST改变'}}
    payload={'feed':vars(f),'templates':templates,'annotations':[annotation],'review':REVIEW}
    program="const a=require('./static/js/clinical-analysis.js');const x=JSON.parse(require('fs').readFileSync(0,'utf8'));console.log(JSON.stringify({index:a.buildIndex(x.feed,x.templates,x.annotations,x.review),hrv:a.hrvWindows(x.feed,'2026-09-12 21:59:55')}));"
    js=json.loads(subprocess.check_output(['node','-e',program],input=json.dumps(payload).encode(),cwd=Path(__file__).parents[1]))
    py=build_index(f,templates,[annotation],REVIEW)
    assert js['index']==py
    assert js['hrv']==hrv_windows(f,'2026-09-12 21:59:55')


def test_storage_keeps_composition_and_conflict(tmp_path):
    s=Storage(tmp_path/'db');c={'selected_events':[{'event_id':'S:single:s:1:s:1','caption':'测试','basis_version':'abc'}],'category_reviews':{'S':'abc'},'diagnosis_blocks':[{'key':'S:single','text':'医生修改','manual':True}]}
    r=s.save_report('test','原结论','draft','tester',c,1)
    assert Storage(tmp_path/'db').get_report('test','')['composition']['selected_events']==r['composition']['selected_events']
    with pytest.raises(ValueError,match='版本'):s.save_report('test','原结论','draft','tester',c,99)
    assert s.get_review('test')['pending_steps']==['edit','stt']
    with pytest.raises(ValueError):s.complete_review('test',{'step':'review','revision':0,'confirmed':True},'tester')


def test_day_window_does_not_discard_nn_at_hour_boundary():
    f=feed('NNNN',duration=5)
    for r in f.beats:r['sample_index']+=100
    result=hrv_windows(f,'2026-09-12 10:59:59')
    assert result['periods']['day']['nn_count']==3
    assert result['periods']['day']['rmssd_ms']==0
    assert sum(r['nn_count'] for r in result['hourly'])<3


def test_api_occurrences_selection_and_structured_st(client):
    case_id=client.get('/api/cases').json['items'][0]['case_id'];base=f'/api/cases/{case_id}'
    original=client.get(base+'/template-occurrences?class_code=N&offset=32&limit=1').json
    assert original['total']>32 and len(original['items'])==1
    assert client.get(base+'/report-events').status_code==200
    assert client.get(base+'/hrv-windows').json['actual_duration_s']<=86400
    sample=original['items'][0]['sample_index']
    a=client.post(base+'/annotations',json={'sample_index':sample,'lead':'II','category':'note','label':'测试ST发现','details':{'kind':'ST','status':'confirmed','end_sample':sample+200,'finding':'测试ST改变'}})
    assert a.status_code==201 and a.json['details']['end_sample']==sample+200
    st=client.get(base+'/report-events?category=ST').json
    assert st['total']==1 and st['items'][0]['diagnosis_status']=='pending'
    assert client.get(base+'/event-waveform?start=0&end=180&max_points=1000').json['duration_s']==180
    draft=client.get(base+'/report').json
    assert draft['composition']['selected_events']==[]


def test_timed_af_candidate_requires_explicit_confirmation():
    f=feed('NNNSNNN')
    candidate={'id':-1,'sample_index':200,'details':{'kind':'AF','status':'pending','end_sample':800,'finding':'房颤候选'}}
    index=build_index(f,annotations=[candidate],review=REVIEW)
    item=query_index(index,{'class_code':'A','mode':'AF'},True)['items'][0]
    assert item['target_samples']==[200,400,600,800]
    assert item['diagnosis_status']=='pending'
    confirmed={**candidate,'id':5,'details':{**candidate['details'],'status':'confirmed','finding':'房颤'}}
    index=build_index(f,annotations=[candidate,confirmed],review=REVIEW)
    result=query_index(index,{'category':'AF'})
    assert result['total']==1 and result['items'][0]['diagnosis_status']=='confirmed'
    payload={'feed':vars(f),'annotations':[candidate,confirmed],'review':REVIEW}
    script="const a=require('./static/js/clinical-analysis.js'),p=JSON.parse(require('fs').readFileSync(0,'utf8'));console.log(JSON.stringify(a.buildIndex(p.feed,[],p.annotations,p.review)))"
    actual=json.loads(subprocess.check_output(['node','-e',script],input=json.dumps(payload).encode(),cwd=Path(__file__).parents[1]))
    assert actual==index
