"""Independent arithmetic and topology regression tests, with no external data.

Public WFDB/SciPy comparisons are executed by the private validation runner.
These tests deliberately require neither SciPy nor WFDB in production.
"""
import math
import random
import copy
from types import SimpleNamespace

import pytest

from ecg_core.clinical_analysis import hrv_windows
from ecg_core.hrv_analysis import sd, mean, spectrum
from ecg_core.rr_quality import nn_intervals
from ecg_core.rr_review import build_rr_index,query_rr
from ecg_core.hrv_analysis import analyze_hrv,analyze_hrv_review,_review_time_metrics,_review_block
from ecg_core.terminology import get_builtin_catalog,validate_catalog,parse_catalog_json,normalize_terminology_usages
from validation.three_feature_reference import reference_nn, reference_time_domain, reference_rr


def feed_from_ms(intervals, codes=None, excluded=()):
    samples=[0]
    for value in intervals:
        assert value % 5 == 0
        samples.append(samples[-1]+value//5)
    codes=codes or ['N']*len(samples)
    rows=[dict(id=str(i),sample_index=s,class_code=c,rr_ms=0 if not i else intervals[i-1])
          for i,(s,c) in enumerate(zip(samples,codes))]
    return SimpleNamespace(beats=rows,duration=samples[-1]/200+1,
        document={'settings':{'nn_min':300,'nn_max':2000}},excluded_rhythm_intervals=excluded)


@pytest.mark.parametrize('values,expected_sd,expected_rmssd,expected_pnn',[
    ([800,850,900],50,50,0),
    ([800,900,800,900],math.sqrt(10000/3),100,100),
])
def test_hand_computed_time_domain_and_strict_50ms(values,expected_sd,expected_rmssd,expected_pnn):
    feed=feed_from_ms(values)
    result=hrv_windows(feed,'2026-10-12T08:00:00')['periods']['full']
    assert result['mean_nn_ms']==850
    assert result['sdnn_ms']==pytest.approx(expected_sd,abs=.005)
    assert result['rmssd_ms']==expected_rmssd
    assert result['pnn50_pct']==expected_pnn
    oracle=reference_time_domain(reference_nn(feed.beats,200))
    assert sd(values)==pytest.approx(oracle['sdnn_ms'],abs=1e-6)
    if expected_pnn:
        assert oracle['task_force_nn_count_pnn50_pct']==75


def test_excluded_interval_preserves_gap_for_successive_differences():
    # N,N,N,V,N,N,N => NN runs [800,800] and [1200,1200].
    feed=feed_from_ms([800,800,800,1200,1200,1200],list('NNNVNNN'))
    result=hrv_windows(feed,'2026-10-12T08:00:00')['periods']['full']
    assert result['nn_count']==4
    assert result['mean_nn_ms']==1000
    assert result['rmssd_ms']==0
    assert result['pnn50_pct']==0


def test_sample_rate_hand_arithmetic_and_unknown_types_remain_original_boundaries():
    oracle=reference_rr([dict(sample_index=s,class_code=c) for s,c in zip([0,250,400,700],'NNNN')],250)
    assert [r['rr_ms'] for r in oracle]==[None,1000,600,1200]
    assert oracle[2]['rr_ms']/oracle[1]['rr_ms']==.6
    rows=[dict(sample_index=s,class_code=c) for s,c in zip([0,301,602],'NQN')]
    assert [r['rr_ms'] for r in reference_rr(rows,360)][1:]==[301000/360]*2
    assert reference_nn(rows,360)==[]
    for samples,codes,fs in [([0,250,400,700],'NNNN',250),([0,301,602],'NQN',360)]:
        rows=[dict(id=str(i),sample_index=s,class_code=c,rr_ms=0 if i==0 else (s-samples[i-1])*1000/fs)
              for i,(s,c) in enumerate(zip(samples,codes))]
        source=SimpleNamespace(beats=rows,duration=samples[-1]/fs+1,
                               document={'settings':{'nn_min':300,'nn_max':2000}})
        product=build_rr_index(source,sample_rate=fs)
        expected=reference_rr(rows,fs)[1:]
        assert [r['rr_ms'] for r in product['intervals']]==[r['rr_ms'] for r in expected]
        assert product['summary']['nn_verified_count']==0
        if codes=='NNNN':assert product['intervals'][1]['ratio_pct']==60
        else:assert product['summary']['nn_eligible_count']==0


def test_non_qrs_markers_do_not_compress_or_add_qrs_boundaries():
    feed=feed_from_ms([800,900,800,900])
    feed.beats.insert(2,dict(id='marker',sample_index=200,class_code='T',rr_ms=None))
    expected=reference_nn(feed.beats,200)
    assert nn_intervals(feed)==expected
    assert [r[3] for r in expected]==[800,900,800,900]


def test_spectrum_rejects_missing_gap_and_rhythm_overlap():
    regular=[(i,i,i+1,1000.) for i in range(300)]
    assert spectrum(regular) is not None
    assert all(value==0 for value in spectrum(regular))
    gap=[r for r in regular if not 100<=r[2]<=106]
    assert spectrum(gap) is None
    assert spectrum(regular,[(100.1,100.2)]) is None
    assert spectrum(regular[:255]) is None


def test_five_minute_default_compatibility_and_exclusion_does_not_bridge():
    feed=feed_from_ms([1000]*600)
    feed.duration=600
    for row in feed.beats:row['hr']=60 if row['rr_ms'] else 0
    original=analyze_hrv(feed,'2026-10-12T08:00:00')
    empty=analyze_hrv_review(feed,'2026-10-12T08:00:00')
    assert empty['baseline']==empty['reviewed']==original
    changed=analyze_hrv_review(feed,'2026-10-12T08:00:00',exclusions=[
        dict(id='gap',start_sample=20000,end_sample=22000,reason='synthetic reference gap')])
    assert changed['baseline']==original
    assert changed['blocks'][0]['reviewed']['nn_count']==290
    assert changed['blocks'][0]['reviewed']['rmssd_ms']==0
    assert changed['blocks'][0]['reviewed']['spectral_reason']=='spectral_gap_over_5s'
    assert changed['blocks'][1]['reviewed']==changed['blocks'][1]['baseline']
    assert changed['coverage']['excluded_s']==10


@pytest.mark.parametrize('count,value,end,qualified,reasons',[
    (30,8000,300,True,[]),
    (29,8280,300,False,['nn_count_below_30']),
    (30,7995,300,False,['nn_coverage_below_240s']),
    (30,8000,299,False,['incomplete_300s_block']),
])
def test_declared_engineering_qualification_boundaries(count,value,end,qualified,reasons):
    # Artificial long NN values isolate the two independent engineering gates;
    # they are not clinical normal-interval thresholds or patient examples.
    chosen=[(i,i*value/1000,(i+1)*value/1000,value) for i in range(count)]
    block=_review_block(chosen,0,end,300,())
    assert block['qualified'] is qualified
    assert block['qualification_reasons']==reasons
    assert block['sdann_ms'] is None


def test_rr_pagination_counts_every_interval_before_page_slice():
    feed=feed_from_ms([1000]*1001)
    index=build_rr_index(feed)
    first=query_rr(index,{'limit':200})
    final=query_rr(index,{'limit':200,'offset':1000})
    assert first['total']==final['total']==1001
    assert len(final['items'])==1
    assert first['histogram']['measurement_count']==1001
    assert sum(r['total'] for r in first['pair_types'])==1001
    assert final['items'][0]['end_sample']==200200


def test_terminology_draft_identity_tree_and_snapshot_text_are_independent():
    catalog=get_builtin_catalog()
    assert catalog['completeness']=='example' and catalog['approval']=='draft'
    assert all(node['approval']=='draft' for node in catalog['nodes'])
    lookup={node['stable_id']:node for node in catalog['nodes']}
    assert len(lookup)==len(catalog['nodes'])
    assert all(node['parent_id'] is None or node['parent_id'] in lookup for node in catalog['nodes'])
    term=next(n for n in catalog['nodes'] if n['kind']=='term')
    snapshot=dict(usage_id='independent-reference',namespace=catalog['namespace'],version=catalog['version'],
        catalog_hash=catalog['sha256'],stable_id=term['stable_id'],label=term['label'],
        inserted_text='医生保留的原始文本',approval=term['approval'],source=term['source'],
        license=term['license'],scope=term['scope'],review=term['review'],inserted_at='2026-10-12T08:00:00Z')
    assert normalize_terminology_usages([snapshot])[0]['inserted_text']=='医生保留的原始文本'
    altered=copy.deepcopy(catalog);altered.pop('sha256')
    altered['nodes'].append(copy.deepcopy(altered['nodes'][0]))
    with pytest.raises(ValueError,match='重复'):validate_catalog(altered)
    altered=copy.deepcopy(catalog);altered.pop('sha256')
    group=next(n for n in altered['nodes'] if n['kind']=='group');group['parent_id']=group['stable_id']
    with pytest.raises(ValueError,match='循环'):validate_catalog(altered)
    with pytest.raises(ValueError,match='重复'):parse_catalog_json('{"schema_version":1,"schema_version":1}')


def test_ten_thousand_fixed_seed_vectors_against_independent_statistics():
    rng=random.Random(431420261012)
    for trial in range(10000):
        count=rng.randrange(3,100)
        values=[rng.randrange(80,300)*5 for _ in range(count)]
        codes=rng.choices(['N','S','V','Q','X'],weights=[95,1,1,1,2],k=count+1)
        feed=feed_from_ms(values,codes)
        if trial%4==0 and count>5:
            k=rng.randrange(1,count-2)
            feed.excluded_rhythm_intervals=[(feed.beats[k]['sample_index']/200,feed.beats[k+1]['sample_index']/200)]
        chosen=reference_nn(feed.beats,200,excluded=feed.excluded_rhythm_intervals,duration=feed.duration)
        oracle=reference_time_domain(chosen)
        actual=hrv_windows(feed,'2026-10-12T08:00:00')['periods']['full']
        block=_review_time_metrics(chosen,0,feed.duration)
        assert actual['nn_count']==oracle['nn_count'],trial
        assert block['nn_count']==oracle['nn_count']
        assert block['nn50_count']==oracle['nn50']
        assert block['consecutive_difference_count']==oracle['diff_count']
        for key in ('mean_nn_ms','sdnn_ms','rmssd_ms','pnn50_pct'):
            expected=oracle[key]
            if key=='sdnn_ms' and oracle['nn_count']<3:expected=None
            if expected is None:assert actual[key] is block[key] is None,(trial,key)
            else:
                assert abs(actual[key]-expected)<=.0050000001,(trial,key)
                assert abs(block[key]-expected)<=.0050000001,(trial,key,'5-minute block')
        accepted=[r[3] for r in chosen]
        if accepted:assert abs(mean(accepted)-oracle['mean_nn_ms'])<=1e-6
        if len(accepted)>1:assert abs(sd(accepted)-oracle['sdnn_ms'])<=1e-6
