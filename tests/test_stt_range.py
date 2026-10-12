"""Independent synthetic oracle; no patient recordings or clinical thresholds."""
import copy
import hashlib
import json
import statistics
from fractions import Fraction

import numpy as np
import pytest

from ecg_core.stt import analyze_stt
from ecg_core.stt_range import STTRangeError, analyze_stt_range, calculate_stt_range


def synthetic(seconds=80, delta=None, baseline=None):
    raw = np.zeros((seconds*200, 8), dtype='<i2')
    records = []
    for second in range(1, seconds):
        sample = second*200
        base = baseline(second) if baseline else 120
        raw[sample-60:sample+140] = base
        # The first quiet four derivatives at/after offset 8 make J exactly 8.
        raw[sample:sample+4] += np.array([900, 600, 250, 80], dtype='<i2')[:, None]
        d = delta(second) if delta else (second % 5 - 2)*7
        raw[sample+18:sample+23] += d
        raw[sample+22:sample+29] += 2*d
        # The overlapping boundary has no effect on the 60-ms five-point median.
        records.append({'sample_index': sample, 'group': 1, 'rr_ms': 1000})
    return raw, records


def evaluate(raw, records, **kwargs):
    return calculate_stt_range(raw, records, start_sample=0, end_sample=12000,
                               leads=['II'], **kwargs)


def derived(frame, lead):
    # Deliberately independent of stt._derived and all range helpers.
    i, ii = int(frame[0]), int(frame[1])
    return {'I':i, 'II':ii, 'III':ii-i, 'aVR':Fraction(-i-ii, 2),
            'aVL':i-Fraction(ii,2), 'aVF':ii-Fraction(i,2),
            **{f'V{k+1}':int(frame[k+2]) for k in range(6)}}[lead]


def oracle(raw, anchors, lead, offset_ms, j=8):
    differences = []
    for anchor in anchors:
        baseline = statistics.median([derived(raw[anchor+x], lead) for x in (-40,-36,-32,-28,-24)])
        point = anchor+j+offset_ms//5
        st = statistics.median([derived(raw[point+x], lead) for x in (-2,-1,0,1,2)])
        differences.append(st-baseline)
    return float(sum(map(Fraction, differences), Fraction(0))/len(differences)) if differences else None


@pytest.mark.parametrize('offset', [0,60,80])
def test_all_beats_arithmetic_mean_matches_independent_exact_oracle(offset):
    raw, records = synthetic(delta=lambda s: 97 if s == 11 else -13)
    original = hashlib.sha256(raw.tobytes()).hexdigest()
    result = calculate_stt_range(raw, records, start_sample=0, end_sample=12000,
                                 leads=['I','II','aVR','aVL','III'], measurement_ms=offset,
                                 basis={'case_id':'math','beat_revision':2}, source_digest='math-source-v1')
    anchors = [r['sample_index'] for r in records if r['sample_index'] < 12000]
    assert result['counts'] == {'detected_count':59,'used_count':59,'excluded_count':0,'missing_count':0,'reason_counts':{}}
    for block in result['blocks']:
        assert block['j_offset_samples'] == 8
        assert len(block['j_representative_samples']) <= 7
    for lead in result['leads']:
        assert lead['mean_units'] == pytest.approx(oracle(raw, anchors, lead['lead'], offset), abs=1e-12)
        assert lead['used_count'] == 59
    assert result['method_profile']['mean_beat_limit'] is None
    assert result['interpretation']['sustained_depression_inferred'] is False
    assert result['binding']['status'] == 'caller_source_and_basis_bound'
    assert hashlib.sha256(raw.tobytes()).hexdigest() == original


def test_mean_is_not_a_block_median_or_average_of_block_means():
    raw, records = synthetic(delta=lambda s: 300 if s == 11 else -10)
    # Unequal block populations, while retaining three representative candidates.
    records = [r for r in records if not (3200 <= r['sample_index'] < 6400 and r['sample_index'] % 600)]
    result = evaluate(raw, records)
    anchors = [r['sample_index'] for r in records if r['sample_index'] < 12000]
    mean = result['leads'][0]['mean_units']
    assert mean == pytest.approx(oracle(raw, anchors, 'II', 60), abs=1e-12)
    assert mean != -10
    unweighted = statistics.mean(b['leads'][0]['mean_units'] for b in result['blocks'])
    assert mean != pytest.approx(unweighted)


def test_zero_and_empty_have_distinct_values():
    raw, records = synthetic(delta=lambda _:0)
    assert evaluate(raw, records)['leads'][0]['mean_units'] == 0
    empty = evaluate(raw, [])
    assert empty['leads'][0]['mean_units'] is None
    assert empty['counts']['detected_count'] == 0
    assert empty['coverage']['used_anchor_span_s'] is None
    assert empty['coverage']['max_used_anchor_gap_s'] is None


@pytest.mark.parametrize('start,end', [(0,11999),(0,12000.0),(False,12000),(-1,12000),(0,16001),(12000,0)])
def test_invalid_range_not_clipped_or_rounded(start,end):
    raw, records = synthetic()
    with pytest.raises(STTRangeError):
        calculate_stt_range(raw, records, start_sample=start, end_sample=end)


def test_half_open_anchor_and_fixed_grid_crossing():
    raw, records = synthetic()
    result = calculate_stt_range(raw, records, start_sample=201, end_sample=12201, leads=['II'])
    anchors = [r['sample_index'] for r in records if 201 <= r['sample_index'] < 12201]
    assert result['counts']['detected_count'] == len(anchors) == 60
    assert result['leads'][0]['mean_units'] == pytest.approx(oracle(raw, anchors, 'II',60))
    assert result['blocks'][0]['start_sample'] == 0
    assert result['blocks'][0]['j_representative_samples'][0] == 200
    assert result['blocks'][-1]['range_end_sample'] == 12201
    exact = evaluate(raw, records)
    assert exact['counts']['detected_count'] == 59  # R at 12000 belongs to next range.


@pytest.mark.parametrize('which', ['baseline','st'])
def test_mask_intersecting_support_but_not_anchor_excludes_one(which):
    raw, records = synthetic()
    anchor = 2000
    point = anchor-40 if which == 'baseline' else anchor+20
    mask = {'start_sample':point,'end_sample':point+1,'reason':'math artifact','origin':'test'}
    result = evaluate(raw, records, exclusions=[mask])
    anchors = [r['sample_index'] for r in records if r['sample_index'] < 12000 and r['sample_index'] != anchor]
    assert result['counts']['used_count'] == 58
    assert result['counts']['excluded_count'] == 1
    assert result['counts']['reason_counts'] == {'measurement_support_exclusion':1}
    assert result['leads'][0]['mean_units'] == pytest.approx(oracle(raw, anchors, 'II',60))
    assert anchor not in result['blocks'][0]['j_representative_samples']


def test_half_open_support_touch_does_not_exclude_but_halo_protects_j():
    raw, records = synthetic()
    # Baseline ends at R-23; an interval beginning there does not touch support.
    mask = {'start_sample':1977,'end_sample':1978,'reason':'between samples'}
    result = evaluate(raw, records, exclusions=[mask])
    assert result['counts']['excluded_count'] == 0
    assert result['counts']['used_count'] == 59
    assert 2000 not in result['blocks'][0]['j_representative_samples']


def test_known_baseline_masks_keep_exclusion_reason_when_no_j_is_available():
    raw, records = synthetic()
    masks = [{'start_sample':r['sample_index']-40,'end_sample':r['sample_index']-39,
              'reason':'baseline artifact'} for r in records]
    result = evaluate(raw, records, exclusions=masks)
    assert result['counts']['excluded_count'] == 59
    assert result['counts']['missing_count'] == 0
    assert result['counts']['reason_counts'] == {'measurement_support_exclusion':59}
    assert result['leads'][0]['mean_units'] is None


def test_contaminated_representatives_removed_then_machine_j_reestimated():
    raw, records = synthetic(delta=lambda _:0)
    # A large late transient on several would-be representatives changes the
    # unmasked machine J.  The explicit support masks remove it from new J.
    for s in (200,600,1000,1600,2000,2400,3000):
        raw[s+8:s+30] += 25000
    masks = [{'start_sample':s+8,'end_sample':s+30,'reason':'known synthetic transient'}
             for s in (200,600,1000,1600,2000,2400,3000)]
    result = evaluate(raw, records, exclusions=masks)
    assert result['blocks'][0]['j_offset_samples'] == 8
    assert not any(s in result['blocks'][0]['j_representative_samples']
                   for s in (200,600,1000,1600,2000,2400,3000))
    assert result['leads'][0]['mean_units'] == 0
    assert result['counts']['excluded_count'] == 7


def test_mask_union_coverage_and_known_missing_are_distinct_and_order_independent():
    raw, records = synthetic()
    masks = [dict(start_sample=2000,end_sample=2400,reason='AF candidate',origin='rhythm_review'),
             dict(start_sample=2200,end_sample=2600,reason='doctor artifact'),
             dict(start_sample=2400,end_sample=2800,reason='known gap',kind='missing')]
    result = evaluate(raw, records, exclusions=masks)
    repeated = evaluate(raw, records, exclusions=list(reversed(masks))+[masks[0]])
    assert result == repeated
    assert result['coverage']['explicit_excluded_s'] == 2
    assert result['coverage']['explicit_missing_s'] == 2
    assert result['coverage']['source_coverage_s'] == 58
    assert result['coverage']['engineering_eligible_block_coverage_s'] == 56
    counts = result['counts']
    assert counts['detected_count'] == counts['used_count']+counts['excluded_count']+counts['missing_count']
    assert counts['missing_count'] > 0
    assert {x['reason'] for x in result['mask_reason_counts']} == {'AF candidate','doctor artifact','known gap'}
    assert sum(x['beat_count'] for x in result['mask_reason_counts']) > counts['excluded_count']+counts['missing_count']
    assert result['interpretation']['sinus_origin_verified'] is False


def test_quality_failure_excludes_finite_measurements():
    raw, records = synthetic(delta=lambda _:30, baseline=lambda s:(s%16)*500-4000)
    result = evaluate(raw, records)
    assert result['counts']['excluded_count'] == 59
    assert result['counts']['reason_counts'] == {'engineering_quality_gate':59}
    assert result['leads'][0]['mean_units'] is None
    assert result['coverage']['engineering_eligible_block_coverage_s'] == 0


def test_unknown_landmark_confidence_is_not_invented_quality_verification():
    raw = np.zeros((16000,8), dtype='<i2')
    records = [{'sample_index':s,'group':1,'rr_ms':1000} for s in range(200,15800,200)]
    result = evaluate(raw, records)
    assert result['blocks'][0]['landmark_confidence'] == 0
    assert result['blocks'][0]['eligible'] is True  # Explicit inherited engineering rule.
    assert result['method_profile']['quality_gate']['landmark_confidence_is_gate'] is False
    assert result['interpretation']['signal_quality_verified'] is False


def test_masks_do_not_rebuild_neighbours_and_s_labels_keep_legacy_rule():
    raw, records = synthetic(delta=lambda _:0)
    records[9]['group'] = 3  # R=2000, neighbours remain excluded after the V mask.
    records[19]['group'] = 2  # R=4000, neighbouring N candidates are retained.
    records[29]['rr_ms'] = 349
    records[30]['rr_ms'] = 350
    records[31]['rr_ms'] = 2000
    records[32]['rr_ms'] = 2001
    result = evaluate(raw, records, exclusions=[{'start_sample':2000,'end_sample':2001,'reason':'V excluded'}])
    assert result['counts']['excluded_count'] == 6
    assert result['counts']['reason_counts'] == {'adjacent_v_or_artifact':2,'non_n_candidate':2,'rr_outside_legacy_bounds':2}


def test_source_tail_and_insufficient_representatives_are_missing_not_clamped():
    raw, records = synthetic(seconds=60, delta=lambda _:0)
    records += [{'sample_index':11950,'group':1,'rr_ms':750}]
    result = evaluate(raw, records)
    assert result['counts']['missing_count'] == 1
    assert result['counts']['reason_counts'] == {'source_edge_guard_unavailable':1}
    sparse = evaluate(raw, records[:2])
    assert sparse['counts']['missing_count'] == 2
    assert sparse['leads'][0]['mean_units'] is None


@pytest.mark.parametrize('kwargs', [
    {'measurement_ms':61}, {'measurement_ms':True}, {'leads':[]}, {'leads':['II','II']},
    {'leads':['bogus']}, {'leads':'II'}, {'leads':[{}]}, {'basis':{'bad':float('nan')}},
    {'exclusions':[{'start_sample':0,'end_sample':16001,'reason':'bad'}]},
    {'exclusions':[{'start_sample':0,'end_sample':1,'reason':''}]},
    {'exclusions':[{'start_sample':0,'end_sample':1,'reason':'bad','kind':'guess'}]},
])
def test_reject_invalid_method_and_explicit_masks(kwargs):
    raw, records = synthetic()
    with pytest.raises(STTRangeError):
        calculate_stt_range(raw, records, start_sample=0,end_sample=12000,**kwargs)


def test_input_and_scope_immutable_and_binding_changes_with_each_basis_dimension():
    raw, records = synthetic()
    original = copy.deepcopy(records)
    basis = {'case_id':'math','data_version':'v1','analysis_basis':'a1',
             'analysis_revision':1,'beat_revision':1,'review_revision':2}
    baseline = evaluate(raw, records, basis=basis, source_digest='source-v1')
    for key in basis:
        changed = {**basis,key:str(basis[key])+'changed'}
        assert evaluate(raw, records, basis=changed, source_digest='source-v1')['result_digest'] != baseline['result_digest']
    assert evaluate(raw, records, basis=basis, source_digest='source-v2')['result_digest'] != baseline['result_digest']
    edited = copy.deepcopy(records); edited[10]['rr_ms'] += 1
    assert evaluate(raw,edited,basis=basis,source_digest='source-v1')['binding']['beats_digest'] != baseline['binding']['beats_digest']
    assert records == original
    baseline['scope']['case_id'] = 'mutated-return'
    assert basis['case_id'] == 'math'
    with pytest.raises(STTRangeError):
        evaluate(raw, records+[records[0]])


def test_file_wrapper_equals_memory_and_legacy_screening_unchanged(tmp_path):
    raw, records = synthetic(seconds=160)
    path = tmp_path/'pure-mathematical.DATA'
    path.write_bytes(raw.tobytes())
    legacy_before = analyze_stt(path, records, analysis_revision='math-unchanged')
    kwargs = dict(start_sample=201,end_sample=12201,leads=['II','aVR'],measurement_ms=80,
                  basis={'case_id':'math'},source_digest=hashlib.sha256(raw.tobytes()).hexdigest())
    assert analyze_stt_range(path,records,**kwargs) == calculate_stt_range(raw,records,**kwargs)
    assert analyze_stt(path,records,analysis_revision='math-unchanged') == legacy_before
    # Bytes and arrays expose exactly the same API for Demo fixture reference.
    assert calculate_stt_range(raw.tobytes(),records,**kwargs) == calculate_stt_range(raw,records,**kwargs)
    assert json.loads(json.dumps(legacy_before)) == legacy_before


def test_source_changed_during_calculation_rejected(tmp_path, monkeypatch):
    import ecg_core.stt_range as module
    from ecg_core.review_workflow import ReportConflict
    raw, records = synthetic()
    path = tmp_path/'mathematical-source.DATA'; path.write_bytes(raw.tobytes())
    calculate = module._calculate
    def changed(*args, **kwargs):
        result = calculate(*args, **kwargs)
        with path.open('r+b') as stream:
            stream.write(b'\x01\x00')
        return result
    monkeypatch.setattr(module, '_calculate', changed)
    with pytest.raises(ReportConflict):
        module.analyze_stt_range(path,records,start_sample=0,end_sample=12000)
