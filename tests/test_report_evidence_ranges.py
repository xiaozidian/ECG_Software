"""Mathematical-only representative ranges and report selection compatibility."""
import copy
import json
import subprocess
from pathlib import Path
import pytest
from ecg_core.clinical_analysis import normalize_selection, validate_report
from ecg_core.report_layout import af_representatives, LEADS
from ecg_core.rr_report import deduplicate_rr_selections
from ecg_core.review_candidates import prepare_candidate
from test_report_layout import index_for
from test_review_candidates import identity
from test_analysis_provenance import synthetic_app, synthetic_case


def rhythm(index,a,b):
    event=dict(event_id='AF:math',category='AF',subtype='AF',basis_version='math-basis',
        start_sample=round(a*200),end_sample=round(b*200)-1,time_s=a,end_s=b,
        label='数学片段',diagnosis_status='confirmed',rhythm_status='confirmed')
    index['events'].append(event)
    return event


@pytest.mark.parametrize('a,b,number',[(10,13,1),(10,20,2),(10,90,3),(0,100,3)])
def test_af_actual_coverage_recommends_one_two_or_three_without_mutation(a,b,number):
    index=index_for(list(range(100)),duration=100);event=rhythm(index,a,b)
    original=copy.deepcopy(index)
    result=af_representatives(index,event)
    assert len(result['items'])==number
    assert set(result['positions'])=={'start','middle','end'}
    assert all(p['visible_beat_count']>=5 and p['selectable'] for p in result['items'])
    assert index==original


def test_af_slow_rate_recommendation_uses_real_expanded_ranges_and_js_parity():
    index=index_for(list(range(0,100,2)),duration=100);event=rhythm(index,10,26)
    opts={'duration_s':3,'leads':['II'],'range_start_s':10,'range_end_s':12}
    result=af_representatives(index,event,opts)
    assert all(p['duration_s']>3 for p in result['items'])
    script="const R=require('./static/js/report-engine.js'),x=JSON.parse(require('fs').readFileSync(0));console.log(JSON.stringify(R.afRepresentatives(x.index,x.event,x.settings)))"
    js=json.loads(subprocess.check_output(['node','-e',script],input=json.dumps(dict(index=index,event=event,settings=opts)).encode(),cwd=Path(__file__).parents[1]))
    assert js==result


def test_af_multiple_strips_keep_identity_and_current_actual_range_deduplicates():
    index=index_for(list(range(100)),duration=100);event=rhythm(index,10,90)
    first=dict(event_id=event['event_id'],basis_version=event['basis_version'],strip_id='start',representative_role='start',range_start_s=10,range_end_s=17,caption='保留原图注',leads=['II'])
    second={**first,'strip_id':'middle','representative_role':'middle','range_start_s':40,'range_end_s':47}
    duplicate={**first,'strip_id':'duplicate','caption':'不得覆盖','leads':LEADS}
    stale={**first,'strip_id':'stale','basis_version':'old'}
    comp=normalize_selection(dict(selected_events=[first,second,duplicate,stale]))
    assert comp['schema_version']==3 and len(comp['selected_events'])==4
    kept,merged=deduplicate_rr_selections(index,comp['selected_events'])
    assert [p['strip_id'] for p in kept]==['start','middle','stale'] and len(merged)==1
    assert kept[0]['caption']=='保留原图注' and kept[0]['leads']==['II']
    with pytest.raises(ValueError):validate_report(index,{**comp,'selected_events':kept}, {},True)
    assert 'strip_category_defaults' not in normalize_selection({})
    assert normalize_selection({'strip_category_defaults':{'AF':{'leads':LEADS,'duration_s':7}}})['strip_category_defaults']['AF']['leads']==LEADS


def test_strip_auto_pick_uses_actual_range_and_twelve_leads_but_rr_keeps_three():
    index=index_for(list(range(0,100,2)),duration=100)
    checked=prepare_candidate(index,identity(),dict(kind='strip',time_s=30,settings={'duration_s':3}))
    p=checked['payload'];assert p['settings']['leads']==LEADS and p['end_s']-p['start_s']>3
    same=prepare_candidate(index,identity(),dict(kind='strip',settings=p['settings']))
    assert same['candidate_key']==checked['candidate_key']
    rr=prepare_candidate(index,identity(),dict(kind='rr',sample_index=index['rows'][10]['sample_index'],settings={'leads':LEADS}))
    assert rr['payload']['settings']['leads']==['II','V1','V5']


def test_preview_is_read_only_and_af_recommendations_enforce_scope(synthetic_app,synthetic_case):
    _,cid,_=synthetic_case;client=synthetic_app.test_client();base=f'/api/cases/{cid}'
    before=client.get(base+'/evidence-candidates').json;report=client.get(base+'/report').json
    scope={k:before[k] for k in ('case_id','analysis_basis','analysis_revision','beat_revision')}
    scoped=client.get(base+'/evidence-candidates',query_string=scope)
    assert scoped.status_code==200 and scoped.json==before
    assert client.get(base+'/evidence-candidates',query_string={**scope,'beat_revision':scope['beat_revision']+1}).status_code==409
    assert client.get(base+'/evidence-candidates',query_string={**scope,'beat_revision':'0.5'}).status_code==400
    preview=client.get(base+'/report-strip-preview',query_string={**scope,'time_s':10,'duration':3,'leads':','.join(LEADS)})
    assert preview.status_code==200,preview.json
    assert preview.json['preview_only'] and preview.json['strip']['visible_beat_count']>=5
    default_preview=client.get(base+'/report-strip-preview',query_string={**scope,'time_s':10,'duration':3})
    assert default_preview.status_code==200 and default_preview.json['strip']['leads']==LEADS
    explicit_three=client.get(base+'/report-strip-preview',query_string={**scope,'time_s':10,'duration':3,'leads':'II,V1,V5'})
    assert explicit_three.status_code==200 and explicit_three.json['strip']['leads']==['II','V1','V5']
    assert client.get(base+'/evidence-candidates').json==before
    assert client.get(base+'/report').json==report
    assert client.get(base+'/report-strip-preview',query_string={**scope,'time_s':'NaN'}).status_code==400
    assert client.get(base+'/report-strip-preview',query_string={**scope,'beat_revision':99}).status_code==409
