"""Development candidate math, time partitions and short-event accounting."""
import json
import math
import random
import subprocess

import pytest

from scripts.evaluate_af_local import (ROOT, MODELS, THRESHOLD, partition, predict,
    reference_events, event_scores, event_summary, time_score, native_audit, summarize)
from tests.test_af_entropy import oracle


def node(code, data):
    source = "const F=require('./scripts/af_local_entropy.cjs'),input=JSON.parse(require('fs').readFileSync(0,'utf8'));" + code
    return json.loads(subprocess.check_output(['node', '-e', source], cwd=ROOT,
                                             input=json.dumps(data), text=True))


def test_quantile_interpolation_and_empty():
    assert node('process.stdout.write(JSON.stringify(input.map(x=>F.quantile(x,.75))));',
                [[], [1], [1, 5], [1, 2, 3, 4, 5], [-3, -2, -1, 0]]) == [None, 1, 4, 4, -.75]


@pytest.mark.parametrize('values,p', [([2, 1], .5), ([None], .5), ([True], .5), ([1], -1), ([1], 1.01), ([1], None)])
def test_quantile_rejects_invalid(values, p):
    assert node('let rejected=false;try{F.quantile(input[0],input[1])}catch(e){rejected=true}process.stdout.write(JSON.stringify(rejected));', [values, p])


def beat_rows(intervals):
    rows = [dict(sample_index=0, rr_ms=0, class_code='N')]
    for rr in intervals:
        rows.append(dict(sample_index=rows[-1]['sample_index'] + rr // 5, rr_ms=rr, class_code='N'))
    return rows


def test_local_statistics_against_independent_enumerated_blocks():
    rng = random.Random(30092026)
    rows = beat_rows([rng.randrange(80, 200)*5 for _ in range(150)])
    rows[25]['rr_valid'] = False
    rows[60]['class_code'] = 'X'
    duration = rows[-1]['sample_index']/200 + 1
    actual = node('process.stdout.write(JSON.stringify(F.features(input.rows,input.duration)));',
                  dict(rows=rows, duration=duration))
    for window in actual:
        values = []
        if window['evaluated']:
            for i in range(12, len(rows)):
                block = rows[i-12:i+1]
                if block[0]['sample_index']/200 < window['start_s'] or block[-1]['sample_index']/200 >= window['end_s']:
                    continue
                if any(r['class_code'] != 'N' for r in block) or any(r.get('rr_valid') is False for r in block[1:]):
                    continue
                values.append(oracle([r['rr_ms'] for r in block[1:]])['value'])
        assert len(values) == window['entropy_blocks']
        if not values:
            assert window['upper_quartile'] is None and window['maximum'] is None
            continue
        values.sort()
        # Weighted order statistics, separately from JS helper.
        h = .75*(len(values)-1)
        expected = values[math.floor(h)]*(1-h%1) + values[math.ceil(h)]*(h%1)
        assert window['upper_quartile'] == pytest.approx(expected, abs=1e-12)
        assert window['maximum'] == pytest.approx(max(values), abs=1e-12)
        assert window['entropy'] <= window['upper_quartile'] <= window['maximum']


def test_no_contiguous_run_is_withheld_for_every_new_model():
    rows = beat_rows([500]*126)
    for i in (10, 20, 30, 40, 50):
        rows[i]['rr_valid'] = False
    actual = node('process.stdout.write(JSON.stringify(F.features(input,63)));', rows)
    assert actual[0]['evaluated'] is True
    assert actual[0]['entropy_reason'] == 'no_contiguous_twelve'
    for model in MODELS[1:]:
        result = predict(actual, model)
        assert result[0]['evaluated'] is False and result[0]['candidate'] is False
        assert result[-1]['reason'] == 'incomplete_window'
        assert not result[-1]['evaluated']


def test_features_do_not_leak_other_windows():
    rows = beat_rows([500]*180)
    changed = [dict(r) for r in rows]
    for r in changed:
        if r['sample_index']/200 >= 30:
            r['class_code'] = 'X'
    code = 'process.stdout.write(JSON.stringify(F.features(input,90)[0]));'
    assert node(code, rows) == node(code, changed)


def window(start, end, evaluated=True, candidate=False):
    return dict(start_s=start, end_s=end, evaluated=evaluated, candidate=candidate,
                entropy=THRESHOLD, upper_quartile=THRESHOLD, maximum=THRESHOLD, entropy_reason=None)


def ref(start, end, rhythm):
    return dict(start_s=start, end_s=end, rhythm=rhythm)


def test_fixed_threshold_gate_and_containment():
    w = window(0, 30)
    w['entropy'] -= .01
    assert [predict([w], model)[0]['candidate'] for model in MODELS] == [False, False, True, True]
    w['evaluated'] = False
    assert not any(predict([w], m)[0]['candidate'] for m in MODELS[1:])
    w.update(entropy=None, upper_quartile=None, maximum=None)
    assert not any(predict([w], m)[0]['evaluated'] for m in MODELS[1:])
    with pytest.raises(ValueError): predict([w], 'unplanned')
    w['maximum'] = float('nan')
    with pytest.raises(ValueError): predict([w], 'maximum')


def test_reference_events_merge_only_adjacent_af_and_duration_bands():
    segments = [ref(0, 10, 'AFIB'), ref(10, 20, 'AFIB'), ref(20, 21, 'unknown'),
                ref(21, 51, 'AFIB'), ref(51, 52, 'N'), ref(52, 172, 'AFIB')]
    events = reference_events(segments, 172)
    assert [e['duration_s'] for e in events] == [20, 30, 120]
    assert [e['band'] for e in events] == ['under_30s', '30_to_under_120s', '120s_or_longer']
    assert [e['touches_record_boundary'] for e in events] == [True, False, True]


def test_half_open_events_do_not_count_touching_positive_window():
    windows = [window(0, 10, candidate=True), window(10, 20), window(20, 30, candidate=True)]
    events = event_scores(windows, [ref(0, 10, 'N'), ref(10, 20, 'AFIB'), ref(20, 30, 'N')], 30)
    assert events[0]['captured_s'] == 0
    assert events[0]['negative_s'] == 10
    assert not events[0]['any_overlap'] and not events[0]['half_captured'] and not events[0]['fully_captured']


def test_partial_event_withheld_and_capture_thresholds():
    windows = [window(0, 10, candidate=True), window(10, 20), window(20, 30, evaluated=False),
               window(30, 40, candidate=True)]
    refs = [ref(0, 20, 'AFIB'), ref(20, 21, 'N'), ref(21, 31, 'AFIB'), ref(31, 32, 'unknown'), ref(32, 40, 'AFIB')]
    events = event_scores(windows, refs, 40)
    assert [e['captured_s'] for e in events] == [10, 1, 8]
    assert [e['withheld_s'] for e in events] == [0, 9, 0]
    assert [e['half_captured'] for e in events] == [True, False, True]
    assert [e['fully_captured'] for e in events] == [False, False, True]
    summary = event_summary(events)
    assert summary['all']['events'] == 3 and summary['all']['captured_s'] == 19
    assert summary['all']['half_captured'] == 2 and summary['all']['fully_captured'] == 1
    assert summary['120s_or_longer']['events'] == 0


@pytest.mark.parametrize('items,duration', [([], 30), ([window(1, 30)], 30),
    ([window(0, 10), window(9, 30)], 30), ([window(0, 10), window(11, 30)], 30),
    ([window(0, 31)], 30), ([window(0, 30)], float('nan')),
    ([window(0, float('inf'))], 30)])
def test_bad_partitions_rejected(items, duration):
    with pytest.raises(ValueError): partition(items, duration)


def test_time_scores_against_native_grid_and_event_totals():
    rng = random.Random(20260930)
    for fs in (128, 250):
        for _ in range(20):
            boundaries = [0] + sorted(rng.sample(range(1, 119*fs), 20)) + [120*fs]
            segments = [ref(a/fs, b/fs, rng.choice(['N', 'AFIB', 'unknown', 'AFL', 'SVTA']))
                        for a, b in zip(boundaries, boundaries[1:])]
            windows = [window(i*30, (i+1)*30, bool(rng.randrange(2)), bool(rng.randrange(2))) for i in range(4)]
            scored = time_score(windows, segments, 120)
            assert scored['seconds'] == pytest.approx(native_audit(windows, segments, fs, 120*fs), abs=1e-9)
            ev = event_summary(event_scores(windows, segments, 120))['all']
            assert ev['captured_s'] == pytest.approx(scored['seconds']['tp_s'], abs=1e-9)
            assert ev['negative_s'] == pytest.approx(scored['seconds']['fn_s'], abs=1e-9)
            assert ev['withheld_s'] == pytest.approx(scored['seconds']['withheld_af_s'], abs=1e-9)
    with pytest.raises(ValueError): native_audit([window(0, .001)], [ref(0, .001, 'AFIB')], 128, 1)


def test_summaries_keep_withheld_denominator_and_zero_af():
    refs = [ref(0, 30, 'AFIB'), ref(30, 60, 'N')]
    windows = [window(0, 30, evaluated=False), window(30, 60, candidate=True)]
    r = time_score(windows, refs, 60)
    r.update(events=event_summary(event_scores(windows, refs, 60)), candidate_episodes=1)
    s = summarize([r])
    assert s['metrics']['all_af_candidate_capture'] == 0
    assert s['metrics']['conditional_sensitivity'] is None
    assert s['false_positive_hours'] == 30/3600 and s['events']['all']['withheld_s'] == 30
    assert summarize([])['macro_af_capture'] is None
