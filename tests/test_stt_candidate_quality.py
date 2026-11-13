"""Independent source-waveform checks for candidate-only support diagnostics.

The waveforms and expected mathematical lobes are defined before the quality
function runs.  These are engineering regression tests, not clinical accuracy
claims or calibrated voltage tests.
"""

import numpy as np
import pytest

from ecg_core.stt import DEFAULT_CONFIG, _beat_measurements
from ecg_core.stt_candidate_quality import (
    CANDIDATE_QUALITY_DEFAULTS, candidate_t_support,
)


FS = 200
J = 8
V3 = 8


def source(kind, beats_count=8):
    """One-second beats; genuine 70-ms T lobes or explicitly defined artifacts."""
    raw = np.full(((beats_count+3)*FS, 8), 4000.0)
    beats = [(second*FS, 1, 1000) for second in range(1, beats_count+1)]
    offsets = np.arange(-50, 110)
    rng = np.random.default_rng(7)
    for index, (anchor, _, _) in enumerate(beats):
        qrs = (1000*np.exp(-.5*(offsets/1.3)**2)
               -150*np.exp(-.5*((offsets+4)/1.5)**2)
               -180*np.exp(-.5*((offsets-5)/1.8)**2))
        values = qrs.copy()
        if kind in {"positive", "negative", "reversal", "st_positive", "st_negative", "st_sine_noise"}:
            sign = -1 if kind == "negative" or (kind == "reversal" and index % 2) else 1
            values += sign*180*np.exp(-.5*((offsets-62)/6)**2)
        if kind == "flat":
            values += 10*np.exp(-.5*((offsets-62)/6)**2)
        if kind == "biphasic":
            values += (180*np.exp(-.5*((offsets-50)/4)**2)
                       -180*np.exp(-.5*((offsets-72)/4)**2))
        if kind in {"late_biphasic", "late_monotonic"}:
            values += 180*np.exp(-.5*((offsets-55)/4)**2)
            if kind == "late_biphasic":
                values -= 180*np.exp(-.5*((offsets-78)/4)**2)
            else:
                values -= np.clip((offsets-66)/14, 0, 1)*180
        if kind in {"st_positive", "st_negative"}:
            values += (170 if kind == "st_positive" else -170)*((offsets >= 17) & (offsets <= 44))
        if kind == "plateau_ripple":
            values += ((offsets >= 17) & (offsets <= 100))*(-110-15*np.exp(-.5*((offsets-62)/6)**2))
        if kind == "spike":
            values[offsets == 62] -= 180
        if kind == "t_sine_noise":
            values[(offsets >= 40) & (offsets < 90)] += 120*np.sin(2*np.pi*np.arange(50)/8)
        if kind == "t_white_noise":
            values[(offsets >= 40) & (offsets < 90)] += rng.normal(0, 100, 50)
        if kind == "st_sine_noise":
            values[(offsets >= 12) & (offsets <= 28)] += 120*np.sin(2*np.pi*np.arange(17)/8)
        if kind == "pr_offset":
            values[(offsets >= -40) & (offsets <= -24)] += 150
        raw[anchor-50:anchor+110] += values[:, None]
    return np.rint(raw).astype("<i2"), beats


def support(raw, beats, **overrides):
    return candidate_t_support(raw.tobytes(), beats, len(raw), {**DEFAULT_CONFIG, **overrides},
                               j_sample=J, next_samples=[b[0]+FS for b in beats])


@pytest.mark.parametrize("kind,polarity", [("positive", "positive"), ("negative", "negative")])
def test_broad_real_lobe_has_independent_prominence_width_and_support(kind, polarity):
    raw, beats = source(kind)
    result = support(raw, beats)
    # A 180-u Gaussian with sigma=30 ms has FWHM approximately 70.6 ms.
    np.testing.assert_allclose(result[f"t_{polarity}_prominence_units"][:, V3], 178, atol=3)
    assert np.all((result[f"t_{polarity}_halfwidth_ms"][:, V3] >= 65) &
                  (result[f"t_{polarity}_halfwidth_ms"][:, V3] <= 75))
    assert np.all(result[f"t_{polarity}_lobe_supported"][:, V3])
    assert np.all(result["t_alignment_consistent"][:, V3])
    assert not np.any(result["baseline_uncertain"][:, V3])


def test_real_biphasic_lobes_survive_without_signed_cancellation():
    raw, beats = source("biphasic")
    result = support(raw, beats)
    assert np.all(result["t_positive_prominence_units"][:, V3] > 150)
    assert np.all(result["t_negative_prominence_units"][:, V3] > 150)
    assert np.all(result["t_positive_halfwidth_ms"][:, V3] >= 35)
    assert np.all(result["t_negative_halfwidth_ms"][:, V3] >= 35)
    assert np.all(result["t_biphasic_supported"][:, V3])
    assert not np.any(result["t_rapid_alternation"][:, V3])


def test_late_biphasic_has_observed_halfwidth_lower_bound_without_reading_missing_tail():
    raw, beats = source("late_biphasic")
    result = support(raw, beats)
    assert np.all(result["t_negative_right_censored"][:, V3])
    np.testing.assert_allclose(result["t_negative_prominence_units"][:, V3], 180)
    np.testing.assert_allclose(result["t_negative_halfwidth_ms"][:, V3], 35)
    assert np.all(result["t_biphasic_supported"][:, V3])
    changed = raw.copy()
    for anchor, _, _ in beats:
        changed[anchor+81:anchor+110] = 30000
    other = support(changed, beats)
    for key in result:
        np.testing.assert_array_equal(result[key], other[key], err_msg=key)


def test_late_monotonic_negative_edge_has_no_recovery_and_is_not_a_lobe():
    raw, beats = source("late_monotonic")
    result = support(raw, beats)
    assert not np.any(result["t_negative_right_censored"][:, V3])
    assert not np.any(result["t_negative_lobe_supported"][:, V3])
    assert not np.any(result["t_biphasic_supported"][:, V3])


def test_reversal_is_not_rejected_for_disagreeing_with_other_beats_polarity():
    raw, beats = source("reversal")
    result = support(raw, beats)
    assert np.all(result["t_positive_lobe_supported"][::2, V3])
    assert np.all(result["t_negative_lobe_supported"][1::2, V3])
    assert np.all(result["t_alignment_consistent"][:, V3])


@pytest.mark.parametrize("kind", ["st_positive", "st_negative"])
def test_true_wide_st_plateau_and_t_have_independent_quality_support(kind):
    raw, beats = source(kind)
    result = support(raw, beats)
    assert np.all(result["st_baseline_quality_good"][:, V3])
    assert np.all(result["t_positive_lobe_supported"][:, V3])
    assert not np.any(result["baseline_uncertain"][:, V3])


def test_genuine_low_flat_has_good_quality_without_an_invented_lobe():
    raw, beats = source("flat")
    result = support(raw, beats)
    assert np.all(result["t_flat_supported"][:, V3])
    assert np.all(result["t_shape_quality_good"][:, V3])
    assert not np.any(result["t_positive_lobe_supported"][:, V3])
    assert not np.any(result["t_negative_lobe_supported"][:, V3])


def test_one_5ms_spike_is_narrow_despite_180u_signed_amplitude():
    raw, beats = source("spike")
    result = support(raw, beats)
    np.testing.assert_allclose(result["t_negative_prominence_units"][:, V3], 180)
    np.testing.assert_allclose(result["t_negative_halfwidth_ms"][:, V3], 5)
    assert np.all(result["t_negative_lobe_too_narrow"][:, V3])
    assert not np.any(result["t_negative_lobe_supported"][:, V3])


@pytest.mark.parametrize("kind", ["t_sine_noise", "t_white_noise"])
def test_artifact_only_in_t_window_is_not_supported_by_quiet_pr(kind):
    raw, beats = source(kind)
    result = support(raw, beats)
    assert np.all(result["t_roughness_excessive"][:, V3])
    assert not np.any(result["t_shape_quality_good"][:, V3])
    assert not np.any(result["t_biphasic_supported"][:, V3])
    assert np.all(result["st_baseline_quality_good"][:, V3])
    if kind == "t_sine_noise":
        assert np.all(result["t_rapid_alternation"][:, V3])
    else:
        assert np.all(result["t_local_noise_units"][:, V3] > 20)
        assert np.all(result["t_noise_above_flat_limit"][:, V3])


def test_small_lobe_on_negative_offset_does_not_borrow_the_offset_amplitude():
    raw, beats = source("plateau_ripple")
    result = support(raw, beats)
    np.testing.assert_allclose(result["t_negative_prominence_units"][:, V3], 15, atol=1)
    assert np.all(result["t_negative_lobe_weak"][:, V3])
    assert not np.any(result["t_negative_lobe_supported"][:, V3])
    assert np.all(result["st_baseline_quality_good"][:, V3])


def test_st_only_noise_is_flagged_without_rejecting_separate_broad_t():
    raw, beats = source("st_sine_noise")
    result = support(raw, beats)
    assert np.all(result["st_roughness_excessive"][:, V3])
    assert not np.any(result["st_baseline_quality_good"][:, V3])
    assert np.all(result["t_positive_lobe_supported"][:, V3])


def test_independent_pr_observation_flags_offset_without_replacing_iso():
    raw, beats = source("pr_offset")
    result = support(raw, beats)
    np.testing.assert_allclose(result["baseline_disagreement_units"][:, V3], 150)
    assert np.all(result["baseline_uncertain"][:, V3])
    assert not np.any(result["st_baseline_quality_good"][:, V3])


def test_next_real_qrs_guard_excludes_future_noise_from_every_t_diagnostic():
    raw, beats = source("negative")
    beat = [beats[0]]
    nexts = [beat[0][0]+62]  # Last allowed offset 54; no invented RR-based extension.
    before = candidate_t_support(raw.tobytes(), beat, len(raw), DEFAULT_CONFIG,
                                 j_sample=J, next_samples=nexts)
    changed = raw.copy()
    changed[beat[0][0]+55:beat[0][0]+90] = np.where(
        np.arange(35)[:, None] % 2, 30000, -30000)
    after = candidate_t_support(changed.tobytes(), beat, len(raw), DEFAULT_CONFIG,
                                j_sample=J, next_samples=nexts)
    for key in before:
        np.testing.assert_array_equal(before[key], after[key], err_msg=key)
    too_short = candidate_t_support(raw.tobytes(), beat, len(raw), DEFAULT_CONFIG,
                                    j_sample=J, next_samples=[beat[0][0]+43])
    assert not np.any(too_short["t_support_valid"])
    assert not np.any(too_short["t_positive_lobe_supported"])
    assert not np.any(too_short["t_negative_lobe_supported"])


def test_api_is_per_beat_per_lead_and_never_mutates_measurements_source_or_config():
    raw, beats = source("plateau_ripple")
    payload = raw.tobytes()
    settings = dict(DEFAULT_CONFIG)
    nexts = [b[0]+FS for b in beats]
    before = _beat_measurements(payload, beats, len(raw), settings, j_sample=J, next_samples=nexts)
    result = candidate_t_support(payload, beats, len(raw), settings, j_sample=J, next_samples=nexts)
    after = _beat_measurements(payload, beats, len(raw), settings, j_sample=J, next_samples=nexts)
    assert settings == DEFAULT_CONFIG
    assert payload == raw.tobytes()
    assert all(array.shape == (len(beats), 12) for array in result.values())
    for key in before:
        np.testing.assert_array_equal(before[key], after[key], err_msg=key)
    np.testing.assert_allclose(after["t"][:, V3], -125)
    np.testing.assert_allclose(after["st"][:, V3], -110)


def test_new_engineering_defaults_are_separate_and_overridable_without_changing_old_config():
    assert set(CANDIDATE_QUALITY_DEFAULTS).isdisjoint(DEFAULT_CONFIG)
    raw, beats = source("spike")
    relaxed = support(raw, beats, candidate_t_minimum_halfwidth_ms=5)
    assert np.all(relaxed["t_negative_lobe_supported"][:, V3])
    assert candidate_t_support(b"", [], 0, DEFAULT_CONFIG, j_sample=J, next_samples=[]) == {}


def test_batched_multi_j_matches_each_original_block_byte_for_byte_with_real_boundaries():
    rng = np.random.default_rng(9013)
    raw = rng.integers(-700, 701, size=(2050, 8), dtype=np.int16).astype("<i2")
    anchors = np.array([0, 70, 200, 430, 750, 1000, 1500, 1880, 1980])
    nexts = np.r_[anchors[1:], anchors[-1]]  # A missing final next R gives zero support.
    intervals = np.maximum(0, nexts-anchors)*1000//FS
    beats = [(int(anchor), 1, int(rr)) for anchor, rr in zip(anchors, intervals)]
    groups = np.array([11, 11, 11, 4, 4, 4, 19, 19, 19])
    js = np.array([8, 8, 8, 12, 12, 12, 28, 28, 28])
    batched = candidate_t_support(raw.tobytes(), beats, len(raw), DEFAULT_CONFIG,
                                  j_sample=js, next_samples=nexts, alignment_groups=groups)
    expected = {key: np.empty_like(value) for key, value in batched.items()}
    for group in np.unique(groups):
        rows = np.flatnonzero(groups == group)
        original_block = candidate_t_support(raw.tobytes(), [beats[row] for row in rows], len(raw),
                                             DEFAULT_CONFIG, j_sample=int(js[rows[0]]),
                                             next_samples=nexts[rows])
        for key in expected:
            expected[key][rows] = original_block[key]
    for key in expected:
        assert expected[key].dtype == batched[key].dtype, key
        assert expected[key].tobytes() == batched[key].tobytes(), key
    assert np.all(batched["baseline_uncertain"][0])
    assert not np.any(batched["t_support_valid"][-1])


def test_scalar_j_and_broadcast_j_array_have_identical_bytes_for_all_fields():
    raw, beats = source("late_biphasic")
    nexts = [beat[0]+FS for beat in beats]
    scalar = candidate_t_support(raw.tobytes(), beats, len(raw), DEFAULT_CONFIG,
                                 j_sample=J, next_samples=nexts)
    vector = candidate_t_support(raw.tobytes(), beats, len(raw), DEFAULT_CONFIG,
                                 j_sample=np.full(len(beats), J), next_samples=nexts)
    for key in scalar:
        assert scalar[key].tobytes() == vector[key].tobytes(), key
