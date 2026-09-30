"""Offline algorithm math and record isolation; no clinical accuracy assertions."""
import json
import math
import random
import subprocess

import pytest

from scripts.develop_af_entropy import (ROOT, GRID, choose_threshold, predict,
    threshold_scores, reference_weights, candidate_episodes)


def node(code, data):
    script = "const F=require('./scripts/af_entropy_features.cjs'),input=JSON.parse(require('fs').readFileSync(0,'utf8'));" + code
    return json.loads(subprocess.check_output(['node', '-e', script], input=json.dumps(data), text=True, cwd=ROOT))


def oracle(rr):
    # Deliberately enumerate all directed pairs and search each tolerance, not order statistics.
    r = 30
    while True:
        a = b = 0
        for i in range(11):
            for j in range(11):
                if i == j:
                    continue
                if abs(rr[i] - rr[j]) < r:
                    b += 1
                    if abs(rr[i + 1] - rr[j + 1]) < r:
                        a += 1
        if a >= 10:
            break
        r += 1
    return dict(value=-math.log(a/b) + math.log(2*r/(sum(rr)/12)), r_ms=r, a=a//2, b=b//2)


def test_cosen_against_independent_exhaustive_oracle():
    rng = random.Random(291026)
    series = [[800]*12, [500, 1000]*6, list(range(400, 1600, 100)),
              [300, 330, 360, 390, 420, 450, 480, 510, 540, 570, 600, 2000]]
    series += [[rng.randint(300, 2000) for _ in range(12)] for _ in range(100)]
    actual = node('process.stdout.write(JSON.stringify(input.map(F.cosen12)));', series)
    for rr, got in zip(series, actual):
        expected = oracle(rr)
        assert got == pytest.approx(expected, abs=1e-12)
        assert 5 <= got['a'] <= got['b'] <= 55
    assert actual[0]['value'] == pytest.approx(math.log(.06/.8))


@pytest.mark.parametrize('rr', [[], [800]*11, [800]*13, [None]*12, [299]*12, [2001]*12, ['800']*12])
def test_invalid_entropy_input_is_rejected(rr):
    assert node('let threw=false;try{F.cosen12(input)}catch(e){threw=true}process.stdout.write(JSON.stringify(threw));', rr)


def rows(count=100):
    return [dict(sample_index=i*160, rr_ms=800 if i else 0, class_code='N') for i in range(count)]


def test_feature_quality_matches_baseline_and_never_crosses_gaps():
    beats = [dict(sample_index=i*100, rr_ms=500 if i else 0, class_code='N') for i in range(126)]
    # Five invalid intervals leave exactly 90% good and 27s coverage but no 12-run.
    for i in (10, 20, 30, 40, 50):
        beats[i]['rr_valid'] = False
    result = node('process.stdout.write(JSON.stringify(F.features(input,63)));', beats)
    assert result[0]['evaluated'] is True
    assert result[0]['entropy'] is None
    assert result[0]['entropy_reason'] == 'no_contiguous_twelve'
    assert result[1]['entropy_blocks'] > 0
    assert result[2]['reason'] == 'incomplete_window' and result[2]['entropy'] is None
    new = predict(result, -2, 'entropy')
    assert not new[0]['evaluated'] and not new[0]['candidate']
    assert new[0]['reason'] == 'no_contiguous_twelve'


def test_window_feature_does_not_read_previous_or_future_window():
    original = rows(100)
    changed = [dict(x) for x in original]
    for r in changed:
        if r['sample_index'] / 200 >= 30:
            r['class_code'] = 'X'
    code = 'process.stdout.write(JSON.stringify(F.features(input,80)[0]));'
    assert node(code, original) == node(code, changed)


def w(start, entropy=-1, evaluated=True, turning=.6):
    return dict(start_s=start, end_s=start+30, entropy=entropy, evaluated=evaluated,
                candidate=False, turning_ratio=turning, entropy_reason=None if evaluated else 'quality')


def test_threshold_strictness_turning_and_missing():
    windows = [w(0), w(30, turning=.9), w(60, entropy=None), w(90, evaluated=False)]
    assert [x['candidate'] for x in predict(windows, -1, 'entropy')] == [True, True, False, False]
    assert [x['candidate'] for x in predict(windows, -1, 'entropy-turning')] == [True, False, False, False]
    assert not any(x['candidate'] for x in predict(windows, -.95, 'entropy'))


def test_mixed_reference_weights_and_unknown():
    refs = [dict(start_s=0, end_s=5, rhythm='unknown'), dict(start_s=5, end_s=40, rhythm='AFIB'),
            dict(start_s=40, end_s=60, rhythm='AFL')]
    assert reference_weights([w(0), w(30)], refs) == [(25, 0), (10, 20)]


def test_training_score_does_not_reward_withheld_non_af_or_af():
    windows = [w(0), w(30, evaluated=False), w(60, evaluated=False), w(90, entropy=-2)]
    scores = threshold_scores(windows, [(30, 0), (30, 0), (0, 30), (0, 30)], 'entropy')
    assert scores[GRID.index(-1.5)] == .5  # Both full-reference recalls are 1/2.
    assert scores[GRID.index(-3)] == .25
    with pytest.raises(ValueError): threshold_scores(windows, [(0, 0)]*4, 'entropy')


def test_leave_record_out_never_uses_its_labels_and_tie_prefers_higher():
    increasing = [i/len(GRID) for i in range(len(GRID))]
    decreasing = list(reversed(increasing))
    first = choose_threshold({'a': increasing, 'b': decreasing, 'held': increasing}, 'held')
    second = choose_threshold({'a': increasing, 'b': decreasing, 'held': [float('nan')]*len(GRID)}, 'held')
    assert first == second and first['training_records'] == ['a', 'b']
    assert choose_threshold({'a': [1]*len(GRID)})['threshold'] == 0
    with pytest.raises(ValueError): choose_threshold({'a': increasing}, 'a')


def test_review_episode_count_breaks_at_negative_withheld_or_gap():
    windows = [w(0), w(30), w(60, evaluated=False), w(90), w(150)]
    assert candidate_episodes(predict(windows, -2, 'entropy')) == 3
