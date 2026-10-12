"""Independent sample/time/count oracles; no clinical files or service needed."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from ecg_core.rr_review import (METHOD_VERSION, RRReviewConflict, build_rr_index,
                                query_rr, resolve_rr_target)

BASIS = dict(case_id='synthetic-case-rr', analysis_basis='synthetic-rr', analysis_revision=7, beat_revision=3)


def feed(intervals, codes=None, sample_rate=200, duration=None, first_sample=0):
    codes = codes or ['N']*(len(intervals)+1)
    sample = first_sample
    rows = [dict(id='s:'+str(sample), sample_index=sample, source_sample=sample,
                 class_code=codes[0], rr_ms=None)]
    for i, rr in enumerate(intervals):
        sample += round(rr*sample_rate/1000)
        rows.append(dict(id='s:'+str(sample), sample_index=sample, source_sample=sample,
                         class_code=codes[i+1], rr_ms=rr))
    return SimpleNamespace(beats=rows, markers=[], duration=duration if duration is not None else sample/sample_rate+1,
        document=dict(settings=dict(nn_min=300, nn_max=2000), changes={}), excluded_rhythm_intervals=[])


def build(value, fs=200):
    return build_rr_index(value, sample_rate=fs, basis=BASIS)


def test_known_endpoints_types_rr_ratio_hr_and_no_fictitious_first_interval():
    index = build(feed([800,1000,800,1000], ['N','N','V','N','N'], first_sample=1000))
    result = query_rr(index)
    assert result['total'] == 4 and result['summary']['qrs_count'] == 5
    assert [r['start_sample'] for r in result['items']] == [1000,1160,1360,1520]
    assert [r['end_sample'] for r in result['items']] == [1160,1360,1520,1720]
    assert [r['rr_ms'] for r in result['items']] == [800,1000,800,1000]
    assert [r['ratio_pct'] for r in result['items']] == [None,125,80,125]
    assert [r['hr_bpm'] for r in result['items']] == [75,60,75,60]
    assert {x['code']:x['total'] for x in result['pair_types']} == {'["N","N"]':2,'["N","V"]':1,'["V","N"]':1}
    assert [(b['start'],b['count']) for b in result['histogram']['bins'] if b['count']] == [(800,2),(1000,2)]
    assert query_rr(index,dict(mode='ratio'))['histogram']['measurement_count'] == 3
    for row in result['items']:
        assert row['target']['sample_index'] == row['right']['sample_index'] == row['end_sample']
        assert row['target']['beat_id'] == row['right']['id']
        assert resolve_rr_target(index,row['target']) == row['target']
    assert result['method']['hospital_mapping_verified'] is False
    json.dumps(result,allow_nan=False)


@pytest.mark.parametrize('fs,samples,expected',[(250,[0,250,400,700],[1000,600,1200]),(360,[0,361,578,1007],[361000/360,217000/360,429000/360])])
def test_actual_sampling_frequency_and_fractional_ms_are_preserved(fs,samples,expected):
    rows = [dict(id='q:'+str(s),sample_index=s,class_code='N') for s in samples]
    index = build(dict(beats=rows,duration=4,document=dict(settings=dict(nn_min=300,nn_max=2000))),fs)
    result = query_rr(index)
    assert [x['computed_rr_ms'] for x in result['items']] == expected
    assert [x['rr_ms'] for x in result['items']] == expected
    assert all(x['stored_rr_ms'] is None for x in result['items'])
    assert all(not x['nn_candidate_compat'] for x in result['items'])
    assert result['items'][1]['ratio_pct'] == pytest.approx(expected[1]/expected[0]*100)


@pytest.mark.parametrize('bad',[0,-200,True,float('inf'),float('nan'),'200'])
def test_invalid_frequency_is_explicit(bad):
    with pytest.raises(ValueError): build_rr_index(feed([1000]),sample_rate=bad)


def test_ordinary_rr_skips_non_qrs_markers_but_noise_remains_boundary():
    f = feed([800,1000,700,1000,900,900],['N','N','S','X','N','N','N'])
    # Original sample700 follows artifact500; materialized RR correctly resets.
    f.beats[4]['rr_ms'] = 0
    f.beats[1:1] = [dict(id='m:o',sample_index=20,class_code='O'),dict(id='m:y',sample_index=40,class_code='Y'),dict(id='m:t',sample_index=60,class_code='T')]
    result = query_rr(build(f))
    assert result['summary']['qrs_count'] == 7 and result['summary']['non_qrs_marker_count'] == 3
    assert result['total'] == 6
    assert [r['rr_ms'] for r in result['items']] == [800,1000,None,None,900,900]
    assert [r['ratio_pct'] for r in result['items']] == [None,125,None,None,None,100]
    assert result['items'][3]['left_type'] == 'X' and result['items'][3]['right_type'] == 'N'
    assert query_rr(build(f),{'population':'normal_pair','mode':'ratio'})['histogram']['measurement_count'] == 1


def test_unknown_j_q_pacing_are_not_mapped_to_normal_and_flutter_has_no_ordinary_rr():
    index = build(feed([1000]*7,['N','J','Q','N','P','N','!','N']))
    rows = query_rr(index)['items']
    assert [(r['left_type'],r['right_type']) for r in rows] == [('N','J'),('J','Q'),('Q','N'),('N','P'),('P','N'),('N','!'),('!','N')]
    assert all(not r['normal_pair'] and not r['nn_candidate_compat'] and not r['nn_eligible_verified'] for r in rows)
    assert [r['rr_ms'] for r in rows] == [1000]*5+[None,None]
    assert rows[1]['type_known'] is False and rows[2]['type_known'] is False
    assert rows[5]['quality']['reason'] == 'flutter_no_ordinary_rr'
    assert rows[6]['ratio_pct'] is None and rows[6]['hr_bpm'] is None
    unknown = query_rr(index,{'population':'unknown'})
    assert unknown['total'] == 4


def test_three_normal_and_nn_layers_never_upgrade_source_n_into_verified_sinus():
    f = feed([800,2200,1000])
    index = build(f)
    rows = query_rr(index)['items']
    assert all(r['normal_label_pair'] for r in rows)
    assert [r['nn_candidate_compat'] for r in rows] == [True,False,True]
    assert [r['nn_eligible_current_rules'] for r in rows] == [True,False,True]
    assert all(not r['nn_eligible_verified'] for r in rows)
    assert all(r['clinical_verification']['status']=='not_established' for r in rows)
    assert query_rr(index,dict(population='nn_eligible'))['total'] == 2
    assert query_rr(index,dict(population='nn_verified'))['total'] == 0
    assert index['summary']['nn_verified_count'] == 0


def confirmation():
    return {**BASIS,'status':'confirmed','evidence_ref':'synthetic-scoped-doctor-review',
        'method_version':METHOD_VERSION,'sinus_verified':True,'quality_verified':True,'start_s':0,'end_s':4}


def test_verified_nn_requires_same_full_scope_method_and_explicit_quality_and_sinus_evidence():
    f = feed([1000]*3);f.nn_verification = confirmation()
    assert query_rr(build(f),dict(population='nn_verified'))['total'] == 3
    for field,value in [('beat_revision',2),('analysis_revision',8),('analysis_basis','old'),('quality_verified',False),
                        ('sinus_verified',False),('method_version','other'),('evidence_ref',''),('status','pending')]:
        f.nn_verification = {**confirmation(),field:value}
        assert query_rr(build(f),dict(population='nn_verified'))['total'] == 0, field
    f.nn_verification = {**confirmation(),'start_s':1,'end_s':2}
    rows = query_rr(build(f))['items']
    assert [r['nn_eligible_verified'] for r in rows] == [False,True,False]
    f.nn_verification = {'sinus_verified':True,'quality_verified':True}
    assert query_rr(build(f),dict(population='nn_verified'))['total'] == 0


def test_complete_interval_rhythm_exclusion_preserves_timing_but_withholds_nn():
    f = feed([1000]*4);f.excluded_rhythm_intervals=[(1.2,1.4)]
    rows = query_rr(build(f))['items']
    assert [r['rr_ms'] for r in rows] == [1000]*4
    assert [r['nn_candidate_compat'] for r in rows] == [True,False,True,True]
    assert rows[1]['nn_reason'] == 'excluded_rhythm_interval'
    f.excluded_rhythm_intervals=[(1,2)]
    assert [r['nn_candidate_compat'] for r in query_rr(build(f))['items']] == [True,False,True,True]


@pytest.mark.parametrize('bad',[True,'800',float('nan'),float('inf'),-800,0])
def test_bad_stored_rr_is_visible_unknown_not_zero_or_a_valid_rate(bad):
    f=feed([800]*3);f.beats[2]['rr_ms']=bad
    rows=query_rr(build(f))['items']
    assert rows[1]['rr_ms'] is None and rows[1]['computed_rr_ms']==800
    assert rows[1]['hr_bpm'] is None and rows[1]['ratio_pct'] is None and rows[2]['ratio_pct'] is None
    assert rows[1]['quality']['reason']=='invalid_stored_rr'
    assert rows[1]['target']['sample_index']==320
    json.dumps(query_rr(build(f)),allow_nan=False)


def test_invalid_samples_duplicates_and_order_are_never_repaired_or_used_as_new_neighbours():
    f=feed([800]*3);f.beats[2]['sample_index']=160
    index=build(f);rows=query_rr(index)['items']
    assert [r['end_sample'] for r in rows]==[160,160,480]
    assert all(not r['quality']['valid'] for r in rows)
    assert rows[0]['target'] is None and rows[1]['target'] is None
    assert rows[2]['left']['id']=='s:320'
    f=feed([800]*2);f.beats[1]['sample_index']=-1
    rows=query_rr(build(f))['items']
    assert all(not r['quality']['valid'] for r in rows)
    assert rows[0]['target'] is None
    f=feed([800]*2);f.beats[1]['sample_index']=float('nan')
    result=query_rr(build(f));assert result['total']==2
    assert result['items'][0]['end_sample'] is None
    json.dumps(result,allow_nan=False)


def test_stored_sample_tolerance_is_the_existing_10ms_rule_and_boundaries_are_disclosed():
    f=feed([800,800]);f.beats[1]['rr_ms']=810
    assert query_rr(build(f))['items'][0]['quality']['valid']
    f.beats[1]['rr_ms']=811
    assert query_rr(build(f))['items'][0]['quality']['reason']=='stored_sample_mismatch'
    f=feed([1000]*2,duration=2)
    index=build(f)
    assert index['summary']['interval_count']==2 and index['summary']['valid_rr_count']==1
    assert index['summary']['nn_eligible_count']==2  # Existing NN <= duration rule.
    assert query_rr(index)['total']==1             # Review window is half-open.
    assert index['intervals'][-1]['target'] is None


def test_ranges_use_raw_values_half_open_edges_and_overflow_not_visual_sampling():
    index=build(feed([800,825,2600,2625]))
    result=query_rr(index)
    assert [(b['start'],b['count']) for b in result['histogram']['bins'] if b['count']]==[(800,1),(825,1),(2600,2)]
    assert result['histogram']['bins'][-1]==dict(start=2600,end=None,count=2,overflow=True)
    assert query_rr(index,dict(range_min=800,range_max=825))['total']==1
    assert query_rr(index,dict(range_min=2600))['total']==2
    assert query_rr(index,dict(range_max=2600))['total']==2
    empty=query_rr(index,dict(range_min=900,range_max=1000))
    assert empty['total']==0 and empty['selected_histogram']['measurement_count']==0
    assert empty['histogram']['measurement_count']==4
    hr=query_rr(build(feed([200,1000])),dict(mode='hr',range_min=300))
    assert hr['total']==1 and hr['histogram']['bins'][-1]['count']==1
    ratio=query_rr(build(feed([1000,3000])),dict(mode='ratio',range_min=300))
    assert ratio['total']==1 and ratio['histogram']['bins'][-1]['count']==1


def test_pair_filter_and_time_window_do_not_reform_original_ratio_predecessors():
    index=build(feed([800,1000,1200,600],['N','V','N','N','N']))
    result=query_rr(index,dict(pair_type='["N", "N"]',mode='ratio',start_s=2,end_s=4))
    assert [r['end_sample'] for r in result['items']]==[600,720]
    assert [r['ratio_pct'] for r in result['items']]==[120,50]
    assert result['query']['pair_type']=='["N","N"]'
    assert result['items'][0]['ratio_previous_start_sample']==160


def test_all_pages_cover_the_full_cohort_once_with_stable_order_and_exact_targets():
    index=build(feed([1000]*205))
    ids=[];samples=[]
    for offset in range(0,205,25):
        result=query_rr(index,dict(offset=offset,limit=25))
        assert result['total']==205
        assert result['histogram']['measurement_count']==205
        assert [r['match_index'] for r in result['items']]==list(range(offset,min(offset+25,205)))
        ids.extend(r['id'] for r in result['items']);samples.extend(r['target']['sample_index'] for r in result['items'])
    assert len(set(ids))==len(ids)==205
    assert samples==list(range(200,41200,200))
    assert result['has_next'] is False


def test_thirty_hour_full_count_and_last_page_are_not_capped_to_plot_or_strip_limits():
    f=feed([1000]*107999,duration=108000)
    index=build(f)
    first=query_rr(index,dict(limit=200))
    tail=query_rr(index,dict(offset=107900,limit=200))
    ratio=query_rr(index,dict(mode='ratio',offset=107998,limit=1))
    assert first['summary']['qrs_count']==108000
    assert first['total']==tail['total']==107999
    assert first['histogram']['measurement_count']==107999
    assert len(tail['items'])==99 and tail['has_next'] is False
    assert tail['items'][-1]['match_index']==107998
    assert tail['items'][-1]['target']['sample_index']==107999*200
    assert ratio['histogram']['measurement_count']==107998
    assert resolve_rr_target(index,tail['items'][-1]['target'])['sample_index']==107999*200


def test_deleted_moved_or_revised_endpoint_rejects_exact_target_and_never_substitutes():
    f=feed([800]*4);index=build(f);target=query_rr(index)['items'][1]['target']
    for field,value in [('sample_index',321),('beat_id','other'),('interval_start_sample',159),('interval_id','other')]:
        with pytest.raises(RRReviewConflict): resolve_rr_target(index,{**target,field:value})
    with pytest.raises(RRReviewConflict): resolve_rr_target(index,{**target,'beat_revision':2})
    moved=deepcopy(f);moved.beats[2]['sample_index']+=1
    with pytest.raises(RRReviewConflict): resolve_rr_target(build(moved),target)
    deleted=deepcopy(f);del deleted.beats[2]
    with pytest.raises(RRReviewConflict): resolve_rr_target(build(deleted),target)
    assert query_rr(index,dict(target_sample_index=320,**BASIS))['target']==target
    with pytest.raises(RRReviewConflict): query_rr(index,dict(beat_revision=4))
    with pytest.raises(RRReviewConflict): query_rr(index,dict(analysis_basis='old'))


@pytest.mark.parametrize('query',[dict(mode='bad'),dict(population='bad'),dict(quality='bad'),dict(pair_type='N-N'),
    dict(pair_type='["N"]'),dict(offset=-1),dict(limit=0),dict(limit=201),dict(offset=True),dict(start_s=-1),
    dict(end_s=100),dict(range_min=1000,range_max=900),dict(range_min='NaN')])
def test_query_rejects_unsupported_or_malformed_contract(query):
    with pytest.raises(ValueError): query_rr(build(feed([1000]*3)),query)


def test_legacy_override_and_unknown_source_groups_retain_provenance():
    f=feed([1000]*2,['N','J','OTHER'])
    f.beats[0]['source_group']=1
    f.beats[1]['source_group']=2  # Legacy physician override S -> J.
    f.beats[2]['source_group']=5  # Source broad pacing group is not a confirmed subtype.
    rows=query_rr(build(f))['items']
    assert rows[0]['right']['classification_source']=='physician_override'
    assert rows[1]['right']['classification_source']=='source_label'
    assert rows[1]['right']['class_code']=='OTHER'
    assert rows[1]['right']['type_known'] is False
    assert not rows[1]['normal_label_pair'] and not rows[1]['nn_candidate_compat']


def test_identical_analysis_digest_never_allows_cross_case_or_loose_json_revision_targets():
    index=build(feed([1000]*2));target=query_rr(index)['items'][0]['target']
    assert target['case_id']==target['caseId']=='synthetic-case-rr'
    for changes in ({'case_id':'other'}, {'caseId':'other'}, {'beat_revision':'3'}, {'analysis_revision':'7'}, {'beat_revision':True}):
        with pytest.raises(RRReviewConflict): resolve_rr_target(index,{**target,**changes})
    for field in ('case_id','analysis_basis','analysis_revision','beat_revision'):
        old=dict(target);del old[field]
        with pytest.raises(RRReviewConflict): resolve_rr_target(index,old)
    with pytest.raises(ValueError): resolve_rr_target(index,{**target,'sample_index':200.0})
    with pytest.raises(RRReviewConflict): resolve_rr_target(index,{**target,'interval_end_sample':200.0})
    with pytest.raises(RRReviewConflict): query_rr(index,{'case_id':'other'})


def test_every_emitted_target_resolves_even_when_interval_measurement_is_invalid():
    f=feed([800]*3);f.beats[1]['sample_index']=None
    index=build(f)
    assert index['intervals'][0]['target'] is None and index['intervals'][1]['target'] is None
    for row in index['intervals']:
        if row['target'] is not None:
            assert resolve_rr_target(index,row['target'])==row['target']
    f=feed([800]*3);f.beats[1]['rr_ms']=0
    index=build(f)
    assert index['intervals'][0]['quality']['valid'] is False
    assert resolve_rr_target(index,index['intervals'][0]['target'])['sample_index']==160
    assert query_rr(index,{'target_sample_index':'160','analysis_revision':'7','beat_revision':'3','case_id':BASIS['case_id']})['target']['sample_index']==160


def test_exact_navigation_cannot_drop_original_beat_or_pair_identity():
    index=build(feed([1000]*2));target=query_rr(index)['items'][0]['target']
    for field in ('beat_id','interval_id','interval_start_sample','interval_end_sample','index_key'):
        incomplete=dict(target);del incomplete[field]
        with pytest.raises(RRReviewConflict): resolve_rr_target(index,incomplete)
    f=feed([1000]*2);f.beats[1]['id']='i:200:new'
    replacement=build(f)
    with pytest.raises(RRReviewConflict): resolve_rr_target(replacement,target)
