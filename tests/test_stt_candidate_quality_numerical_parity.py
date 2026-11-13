"""Portable, exact regression against the frozen 6e37 candidate-quality helper.

The 120 mathematical controls and 50 seeded raw-signal controls reproduce the
disposable performance experiment.  They supplement the independent semantic
shape/engine tests; agreement with an old algorithm is not a clinical oracle.
No external dataset, platform-specific path, patient data or work DB is used.
"""
from pathlib import Path
import hashlib
import importlib.util

import numpy as np
import pytest

from ecg_core.stt import DEFAULT_CONFIG
from ecg_core.stt_candidate_quality import candidate_t_support


ORACLE_SHA256 = "6e37ccddfcf5fee152ac2c419d3870af3c3ad0c94565d038157a1385d51a8868"
ORACLE_PATH = Path(__file__).with_name("fixtures")/"stt_candidate_quality_6e37_oracle.py"
QUALITY_FIELDS = frozenset({
    "t_support_valid", "t_positive_prominence_units", "t_negative_prominence_units",
    "t_positive_halfwidth_ms", "t_negative_halfwidth_ms", "t_positive_right_censored",
    "t_negative_right_censored", "t_local_noise_units", "st_local_noise_units",
    "t_roughness_ratio", "st_roughness_ratio", "t_rapid_alternation",
    "t_alignment_consistent", "t_roughness_excessive", "st_roughness_excessive",
    "t_noise_above_flat_limit", "t_positive_lobe_too_narrow", "t_negative_lobe_too_narrow",
    "t_positive_lobe_weak", "t_negative_lobe_weak", "baseline_uncertain",
    "baseline_disagreement_units", "t_shape_quality_good", "st_baseline_quality_good",
    "t_positive_lobe_supported", "t_negative_lobe_supported", "t_biphasic_supported",
    "t_flat_supported",
})
KINDS = (
    "positive", "negative", "reversal", "st_positive", "st_negative", "st_sine_noise",
    "flat", "biphasic", "late_biphasic", "late_monotonic", "plateau_ripple", "spike",
    "t_sine_noise", "t_white_noise", "pr_offset",
)


@pytest.fixture(scope="module")
def frozen_oracle():
    assert hashlib.sha256(ORACLE_PATH.read_bytes()).hexdigest() == ORACLE_SHA256
    # Its original relative .config import resolves within the tested package;
    # the fixture itself remains byte-for-byte identical to the reviewed code.
    spec = importlib.util.spec_from_file_location("ecg_core._test_quality_oracle_6e37", ORACLE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.SAMPLE_RATE == 200 and module.CHANNEL_COUNT == 8
    return module


def assert_fields_identical(expected, actual):
    assert set(expected) == set(actual)
    for key, before in expected.items():
        after = actual[key]
        assert isinstance(before, np.ndarray) and isinstance(after, np.ndarray), key
        assert before.shape == after.shape, f"{key}: shape"
        assert before.dtype == after.dtype, f"{key}: dtype"
        if np.issubdtype(before.dtype, np.floating):
            assert np.array_equal(np.isnan(before), np.isnan(after)), f"{key}: NaN mask"
            zero = np.isfinite(before) & (before == 0)
            assert np.array_equal(np.signbit(before[zero]), np.signbit(after[zero])), f"{key}: signed zero"
        # This additionally rejects differing NaN payloads.  C-order byte
        # comparison permits workspace layout changes without value changes.
        assert before.tobytes(order="C") == after.tobytes(order="C"), f"{key}: bytes"


def mathematical_source(kind, beats_count=8):
    raw = np.full(((beats_count+3)*200, 8), 4000.0)
    beats = [(second*200, 1, 1000) for second in range(1, beats_count+1)]
    offset = np.arange(-50, 110)
    rng = np.random.default_rng(7)
    for index, (anchor, _, _) in enumerate(beats):
        values = (1000*np.exp(-.5*(offset/1.3)**2)
                  -150*np.exp(-.5*((offset+4)/1.5)**2)
                  -180*np.exp(-.5*((offset-5)/1.8)**2))
        if kind in {"positive", "negative", "reversal", "st_positive", "st_negative", "st_sine_noise"}:
            sign = -1 if kind == "negative" or (kind == "reversal" and index % 2) else 1
            values += sign*180*np.exp(-.5*((offset-62)/6)**2)
        if kind == "flat":
            values += 10*np.exp(-.5*((offset-62)/6)**2)
        if kind == "biphasic":
            values += (180*np.exp(-.5*((offset-50)/4)**2)
                       -180*np.exp(-.5*((offset-72)/4)**2))
        if kind in {"late_biphasic", "late_monotonic"}:
            values += 180*np.exp(-.5*((offset-55)/4)**2)
            values -= (180*np.exp(-.5*((offset-78)/4)**2) if kind == "late_biphasic"
                       else np.clip((offset-66)/14, 0, 1)*180)
        if kind in {"st_positive", "st_negative"}:
            values += (170 if kind == "st_positive" else -170)*((offset >= 17) & (offset <= 44))
        if kind == "plateau_ripple":
            values += ((offset >= 17) & (offset <= 100))*(-110-15*np.exp(-.5*((offset-62)/6)**2))
        if kind == "spike":
            values[offset == 62] -= 180
        if kind == "t_sine_noise":
            values[(offset >= 40) & (offset < 90)] += 120*np.sin(2*np.pi*np.arange(50)/8)
        if kind == "t_white_noise":
            values[(offset >= 40) & (offset < 90)] += rng.normal(0, 100, 50)
        if kind == "st_sine_noise":
            values[(offset >= 12) & (offset <= 28)] += 120*np.sin(2*np.pi*np.arange(17)/8)
        if kind == "pr_offset":
            values[(offset >= -40) & (offset <= -24)] += 150
        raw[anchor-50:anchor+110] += values[:, None]
    return np.rint(raw).astype("<i2"), beats


def compare_call(oracle, raw, beats, *, j_sample, next_samples, alignment_groups=None):
    payload = raw.tobytes()
    config = dict(DEFAULT_CONFIG)
    kwargs = dict(j_sample=j_sample, next_samples=next_samples, alignment_groups=alignment_groups)
    expected = oracle.candidate_t_support(payload, beats, len(raw), config, **kwargs)
    actual = candidate_t_support(payload, beats, len(raw), config, **kwargs)
    assert set(expected) == QUALITY_FIELDS
    assert all(value.shape == (len(beats), 12) for value in expected.values())
    assert_fields_identical(expected, actual)
    assert payload == raw.tobytes()
    assert config == DEFAULT_CONFIG


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("j_sample", [8, 12, 20, 28])
@pytest.mark.parametrize("guarded", [False, True])
def test_120_mathematical_controls_are_byte_exact(frozen_oracle, kind, j_sample, guarded):
    raw, beats = mathematical_source(kind)
    nexts = [beat[0]+(delta if guarded else 200)
             for beat, delta in zip(beats, [70, 62, 43, 100, 150, 200, 80, 0])]
    compare_call(frozen_oracle, raw, beats, j_sample=j_sample, next_samples=nexts)


@pytest.fixture(scope="module")
def seeded_controls():
    rng = np.random.default_rng(1132026)
    controls = []
    for _ in range(50):
        n = int(rng.integers(1, 33))
        raw = rng.integers(-32000, 32001, size=((n+3)*200, 8), dtype=np.int16).astype("<i2")
        anchors = np.arange(0, n*200, 200)
        beats = [(int(anchor), 1, int(rng.integers(200, 2001))) for anchor in anchors]
        nexts = anchors+rng.integers(0, 401, size=n)
        j = int(rng.integers(8, 29))
        groups = rng.integers(0, 6, size=n)
        controls.append((raw, beats, j, nexts, groups))
    return controls


@pytest.mark.parametrize("case", range(50))
def test_50_seeded_raw_controls_are_byte_exact(frozen_oracle, seeded_controls, case):
    raw, beats, j, nexts, groups = seeded_controls[case]
    compare_call(frozen_oracle, raw, beats, j_sample=j, next_samples=nexts, alignment_groups=groups)


def test_mixed_per_beat_j_real_boundaries_and_empty_tail_match(frozen_oracle):
    rng = np.random.default_rng(9013)
    raw = rng.integers(-700, 701, size=(2050, 8), dtype=np.int16).astype("<i2")
    anchors = np.array([0, 70, 200, 430, 750, 1000, 1500, 1880, 1980])
    nexts = np.r_[anchors[1:], anchors[-1]]
    beats = [(int(anchor), 1, int(rr)) for anchor, rr in zip(anchors, np.maximum(0, nexts-anchors)*5)]
    compare_call(frozen_oracle, raw, beats, j_sample=np.array([8, 8, 8, 12, 12, 12, 28, 28, 28]),
                 next_samples=nexts, alignment_groups=np.array([11, 11, 11, 4, 4, 4, 19, 19, 19]))


@pytest.mark.parametrize("j_sample", [8, np.array([], dtype=int)])
def test_empty_batch_contract_matches(frozen_oracle, j_sample):
    kwargs = dict(j_sample=j_sample, next_samples=[], alignment_groups=[])
    assert frozen_oracle.candidate_t_support(b"", [], 0, DEFAULT_CONFIG, **kwargs) == {}
    assert candidate_t_support(b"", [], 0, DEFAULT_CONFIG, **kwargs) == {}


def test_byte_comparison_rejects_signed_zero_difference():
    with pytest.raises(AssertionError, match="signed zero"):
        assert_fields_identical({"value": np.array([0.0])}, {"value": np.array([-0.0])})


def test_byte_comparison_rejects_equal_nan_masks_with_different_nan_payloads():
    first = np.array([0x7ff8000000000001], dtype=np.uint64).view(np.float64)
    second = np.array([0x7ff8000000000002], dtype=np.uint64).view(np.float64)
    with pytest.raises(AssertionError, match="bytes"):
        assert_fields_identical({"value": first}, {"value": second})


def test_byte_comparison_rejects_dtype_change_even_for_equal_values():
    with pytest.raises(AssertionError, match="dtype"):
        assert_fields_identical({"value": np.array([1], dtype=np.float64)},
                                {"value": np.array([1], dtype=np.float32)})
