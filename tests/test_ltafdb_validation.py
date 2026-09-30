"""External adapter and independent accounting, not clinical pass thresholds."""
import random

import pytest

from scripts.validate_ltafdb import adapt, reference_segments, score, native_seconds, summarize, frozen_parameters


def test_128_to_200_mapping_bound_and_interval_consistency():
    samples = list(range(16))
    rows, meta = adapt(samples, ['N']*16, ['']*16, 128, 128, 'qrs')
    assert [r['sample_index'] for r in rows] == [(s*25+8)//16 for s in samples]
    assert meta['max_timestamp_error_ms'] == 2.5
    for i, r in enumerate(rows):
        assert abs(r['time_s']-samples[i]/128) <= .0025 + 1e-15
        if i:
            assert r['rr_ms'] == (r['sample_index']-rows[i-1]['sample_index'])*5
    assert rows[0]['rr_valid'] is False


def test_manual_termination_markers_cannot_change_qrs_input():
    original, _ = adapt([0, 100, 200, 300], ['N']*4, ['']*4, 400, 128, 'qrs')
    changed, meta = adapt([0, 50, 100, 150, 200, 300, 400],
                          ['N', 'T', 'N', 'T', 'N', 'N', 'T'], ['']*7, 400, 128, 'qrs')
    assert changed == original
    assert meta['ignored'] == {'manual_termination_T': 3}


@pytest.mark.parametrize('barrier', [100, 150, 200])
def test_artifact_point_invalidates_intersecting_intervals_without_fake_beats(barrier):
    annotations = sorted([(0, 'N'), (100, 'N'), (200, 'N'), (300, 'N'), (barrier, '|')])
    rows, meta = adapt([a for a, _ in annotations], [b for _, b in annotations], ['']*5, 400, 128, 'qrs')
    assert len(rows) == 4 and meta['barriers'] == 1
    assert rows[2]['rr_valid'] is False
    assert rows[1]['rr_valid'] is (barrier != 100)
    assert rows[3]['rr_valid'] is (barrier != 200)
    assert [r['rr_ms'] for r in rows] == [0, 780, 785, 780]


def test_typed_beats_and_missb_are_not_af_labels_or_synthetic_qrs():
    samples = [0, 1, 100, 150, 200, 300, 400]
    symbols = ['+', 'N', 'A', '"', 'N', 'V', 'Q']
    labels = ['(AFIB', '', '', 'MISSB', '', '', '']
    rows, meta = adapt(samples, symbols, labels, 500, 128, 'atr')
    assert [r['class_code'] for r in rows] == ['N', 'S', 'N', 'V', 'X']
    assert rows[2]['rr_valid'] is False and len(rows) == 5
    labels[0] = '(N'
    assert adapt(samples, symbols, labels, 500, 128, 'atr')[0] == rows
    assert meta['ignored'] == {'rhythm_change': 1}


@pytest.mark.parametrize('note', ['\x01 Aux', 'M', 'MB', 'PSE'])
def test_opaque_comments_are_counted_but_never_used_as_model_features(note):
    original, _ = adapt([0, 100, 200], ['N']*3, ['']*3, 400, 128, 'atr')
    rows, meta = adapt([0, 50, 100, 200], ['N', '"', 'N', 'N'], ['', note, '', ''], 400, 128, 'atr')
    assert rows == original
    assert meta['ignored'] == {'opaque_note:'+note: 1}


@pytest.mark.parametrize('samples,symbols,aux,length,fs,mode', [
    ([0], ['N'], [''], 0, 128, 'qrs'), ([0], ['N'], [''], 100, 200, 'qrs'),
    ([-1], ['N'], [''], 100, 128, 'qrs'), ([100], ['N'], [''], 100, 128, 'qrs'),
    ([2, 1], ['N', 'N'], ['', ''], 100, 128, 'qrs'), ([1, 1], ['N', 'N'], ['', ''], 100, 128, 'qrs'),
    ([1.2], ['N'], [''], 100, 128, 'qrs'), ([1], ['N'], [], 100, 128, 'qrs'),
    ([1], ['V'], [''], 100, 128, 'qrs'), ([1], ['N'], ['AFIB'], 100, 128, 'qrs'),
    ([1], ['?'], [''], 100, 128, 'atr'), ([1], ['"'], ['UNSUPPORTED'], 100, 128, 'atr'),
    ([1], ['+'], ['(UNKNOWN'], 100, 128, 'atr'), ([1], ['N'], [''], 100, 128, 'bad')])
def test_unsupported_or_corrupt_inputs_fail_closed(samples, symbols, aux, length, fs, mode):
    with pytest.raises(ValueError): adapt(samples, symbols, aux, length, fs, mode)


def test_trailing_aux_note_does_not_extend_record_or_generate_interval():
    samples, symbols, labels = [0, 1, 100, 800], ['+', 'N', 'N', '"'], ['(N', '', '', '\x01 Aux']
    rows, meta = adapt(samples, symbols, labels, 400, 128, 'atr')
    assert len(rows) == 2 and meta['ignored']['out_of_bounds_aux_note'] == 1
    assert reference_segments(samples, symbols, labels, 400, 128) == [dict(start_s=0, end_s=3.125, rhythm='N')]
    for symbol, label in [('N', ''), ('+', '(N'), ('"', 'MISSB'), ('"', 'M')]:
        with pytest.raises(ValueError): adapt([800], [symbol], [label], 400, 128, 'atr')


def test_reference_only_uses_rhythm_changes_unknown_prefix_and_terminal_marker():
    got = reference_segments([0, 128, 200, 256, 400, 512], ['N', '+', 'A', '+', '"', '+'],
                             ['', '(N', '', '(AFIB\x00', 'MISSB', '(SBR'], 512, 128)
    assert got == [dict(start_s=0, end_s=1, rhythm='unknown'), dict(start_s=1, end_s=2, rhythm='N'),
                   dict(start_s=2, end_s=4, rhythm='AFIB')]
    with pytest.raises(ValueError): reference_segments([0], ['+'], ['(UNKNOWN'], 128, 128)


def test_all_rhythm_strata_and_mixed_windows_match_independent_native_grid():
    samples = [64, 160, 288, 384, 512, 640, 768, 896, 1024]
    labels = ['(N', '(AFIB', '(SVTA', '(VT', '(B', '(T', '(IVR', '(AB', '(SBR']
    symbols = ['+']*len(samples)
    refs = reference_segments(samples, symbols, labels, 1152, 128)
    windows = [dict(start_s=0, end_s=2, evaluated=True, candidate=True),
               dict(start_s=2, end_s=5, evaluated=True, candidate=False),
               dict(start_s=5, end_s=9, evaluated=False, candidate=False)]
    actual = score(windows, refs, 9)
    assert actual['seconds'] == native_seconds(samples, symbols, labels, 1152, windows)
    assert actual['seconds'] == dict(tp_s=.75, fp_s=.75, fn_s=.25, tn_s=2.75,
                                    withheld_af_s=0, withheld_non_af_s=4, unknown_s=.5)
    assert actual['by_rhythm']['IVR']['withheld_s'] == 1


def test_random_native_grid_and_intersection_parity():
    rng = random.Random(291029)
    for _ in range(20):
        points = sorted(rng.sample(range(1, 4096), 30))
        labels = [rng.choice(['(AFIB', '(N', '(VT', '(SBR']) for _ in points]
        windows = [dict(start_s=i*4, end_s=(i+1)*4, evaluated=bool(rng.randrange(2)),
                        candidate=bool(rng.randrange(2))) for i in range(8)]
        measured = score(windows, reference_segments(points, ['+']*30, labels, 4096, 128), 32)
        assert measured['seconds'] == native_seconds(points, ['+']*30, labels, 4096, windows)
        assert sum(measured['seconds'].values()) == 32


def test_missing_partition_rejected_and_zero_denominators_stay_missing():
    ref = [dict(start_s=0, end_s=2, rhythm='N')]
    window = dict(start_s=0, end_s=1, evaluated=True, candidate=False)
    with pytest.raises(ValueError): score([window], ref, 2)
    window['end_s'] = 2
    measured = score([window], ref, 2)
    assert measured['metrics']['conditional_sensitivity'] is None
    measured['candidate_episodes'] = 0
    summary = summarize([measured])
    assert summary['record_macro']['all_af_candidate_capture'] == dict(value=None, records=0)
    assert summary['metrics']['positive_predictive_value'] is None


def test_candidate_thresholds_match_unchanged_frozen_development(monkeypatch):
    from scripts import validate_ltafdb as validation
    # Reproduction uses its original build, not today's evolving workstation.
    monkeypatch.setattr(validation, 'ROOT', validation.FREEZE/'snapshot')
    development, thresholds = frozen_parameters()
    assert development['protocol'] == 'af-entropy-development-v1'
    assert thresholds == {'entropy': -1.35, 'entropy-turning': -1.35}


def test_current_workstation_cannot_masquerade_as_frozen_development():
    # The guard is intentionally retained: changing review boundary conversion
    # must not silently attach old external-validation claims to a new build.
    with pytest.raises(ValueError, match='Frozen development source drift:'):
        frozen_parameters()
