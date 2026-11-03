"""Exact differential checks against the pre-turn scalar ST-T implementation."""
import importlib.util
from pathlib import Path
import random
import subprocess

import numpy as np
import pytest

from ecg_core import stt
from ecg_core.rr_quality import NNWindowIndex

spec = importlib.util.spec_from_file_location('stt_scalar', Path(__file__).parent/'oracles/stt_scalar.py')
scalar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scalar)


@pytest.mark.parametrize('kind', ['random', 'extreme', 'flat', 'ties'])
@pytest.mark.parametrize('measurement_ms', [0, 60, 80])
def test_batched_landmarks_and_all_leads_match_scalar(kind, measurement_ms):
    rng = np.random.default_rng(20261002)
    frames = rng.integers(-1800, 1801, size=(600, 8), dtype=np.int16)
    if kind == 'extreme':
        frames = rng.choice(np.array([-32768, 32767], dtype=np.int16), size=(600, 8))
    elif kind == 'flat':
        frames[:] = -120
    elif kind == 'ties':
        frames[:] = 0
        frames[::2] = 200
        frames[1::2] = -200
    buffer = frames.astype('<i2').tobytes()
    config = {**stt.DEFAULT_CONFIG, 'st_measurement_ms': measurement_ms}
    # Includes no beats, odd/even median counts, repeated beats, clipped source
    # ends, and the RR-dependent rounding boundaries used by T sampling.
    cases = [[], [(0, 1, 350)], [(599, 1, 2000)],
             [(0, 1, 350), (599, 1, 2000)],
             [(100, 1, 999), (100, 1, 1001), (222, 1, 1123)],
             [(int(s), 1, int(rr)) for s, rr in zip(rng.integers(0, 600, 7), rng.integers(350, 2001, 7))]]
    for beats in cases:
        assert stt._estimate_j_sample(buffer, beats, 600) == scalar._estimate_j_sample(buffer, beats, 600)
        assert stt._block_measurement(buffer, beats, max(9, len(beats)), 600, config) == scalar._block_measurement(buffer, beats, max(9, len(beats)), 600, config)


def lead_availability_fixture():
    frames = np.full((1000, 8), 100, dtype='<i2')
    beats = [(sample, 1, 1000) for sample in (200, 400, 600, 800)]
    for sample, _, _ in beats:
        frames[sample:sample+4] += np.array([1000, 600, 250, 80], dtype='<i2')[:, None]
    return frames, beats


def compare_availability(frames, beats):
    buffer = frames.astype('<i2').tobytes()
    actual = stt._block_measurement(buffer, beats, len(beats), len(frames), stt.DEFAULT_CONFIG)
    expected = scalar._block_measurement(buffer, beats, len(beats), len(frames), stt.DEFAULT_CONFIG)
    assert actual == expected  # Keep every original numeric and boundary field.
    return actual['leads']


def test_independent_oracle_marks_flat_source_leads_unavailable_without_erasing_zero_values():
    frames, beats = lead_availability_fixture(); frames[:] = 100
    leads = compare_availability(frames, beats)
    for name in ('I', 'II', 'V1', 'V2', 'V3', 'V4', 'V5', 'V6'):
        assert leads[name]['eligible'] is False
        assert leads[name]['availability_reasons'] == ['flatline']
        assert leads[name]['st_level_units'] == leads[name]['t_amplitude_units'] == leads[name]['qrs_amplitude_units'] == 0
    for name in ('III', 'aVR', 'aVL', 'aVF'):
        assert leads[name]['eligible'] is False and leads[name]['availability_reasons'] == ['source_limb_unavailable']


def test_zero_derived_limb_projection_is_available_when_measured_inputs_are_valid():
    frames, beats = lead_availability_fixture()
    leads = compare_availability(frames, beats)
    assert leads['I']['eligible'] is True and leads['II']['eligible'] is True
    assert leads['III']['qrs_amplitude_units'] == leads['III']['st_level_units'] == leads['III']['t_amplitude_units'] == 0
    assert leads['III']['eligible'] is True and leads['III']['availability_reasons'] == []


def test_missing_measured_limb_disables_all_derived_leads_but_not_other_sources():
    frames, beats = lead_availability_fixture(); frames[:, 0] = 100
    leads = compare_availability(frames, beats)
    assert leads['I']['availability_reasons'] == ['flatline'] and leads['II']['eligible'] is True
    assert leads['III']['qrs_amplitude_units'] > 0
    for name in ('III', 'aVR', 'aVL', 'aVF'):
        assert leads[name]['eligible'] is False and leads[name]['availability_reasons'] == ['source_limb_unavailable']
    assert all(leads[name]['eligible'] for name in ('V1','V2','V3','V4','V5','V6'))


@pytest.mark.parametrize('level,clipped', [(32767,True),(-32768,True),(32766,False),(-32767,False)])
def test_int16_source_clipping_limits_are_inclusive_and_near_limits_stay_available(level, clipped):
    frames, beats = lead_availability_fixture(); frames[200, 0] = level
    leads = compare_availability(frames, beats)
    assert leads['I']['qrs_amplitude_units'] > 0 and leads['I']['quality_score'] == 1
    assert leads['I']['eligible'] is not clipped
    assert leads['I']['availability_reasons'] == (['source_clipping'] if clipped else [])
    assert leads['II']['eligible'] is True and leads['V1']['eligible'] is True
    if clipped:
        assert all(leads[name]['availability_reasons'] == ['source_limb_unavailable'] for name in ('III','aVR','aVL','aVF'))


def test_noisy_baseline_has_finite_measurements_but_fails_the_lead_quality_gate():
    frames, beats = lead_availability_fixture()
    for sample, _, _ in beats:
        frames[[sample-40,sample-36,sample-32,sample-28,sample-24],1] = [2000,-2000,2000,-2000,2000]
    leads = compare_availability(frames, beats)
    assert leads['II']['qrs_amplitude_units'] > 0 and leads['II']['quality_score'] == .35
    assert leads['II']['eligible'] is False and leads['II']['availability_reasons'] == ['lead_engineering_quality']
    assert leads['II']['st_level_units'] == -1900
    assert leads['I']['eligible'] is True and leads['V1']['eligible'] is True


@pytest.mark.parametrize('radius', [0, 1, 4, 75, 1000])
def test_exact_centered_reference_with_duplicates_missing_and_nonfinite(radius):
    rng = random.Random(20261002)
    pool = [None, -100, -1.005, 0, 0, 0.5, 2.675, 100, float('nan'), float('inf'), -float('inf')]
    values = [{'eligible': rng.choice([True, True, False]), 'level': rng.choice(pool)} for _ in range(160)]
    assert stt._rolling_reference(values, 'level', radius) == scalar._rolling_reference(values, 'level', radius)
    assert stt._rolling_reference([], 'level', radius) == []
    invalid = [{'eligible': True, 'level': float('nan')} for _ in range(4)]
    assert stt._rolling_reference(invalid, 'level', radius) == scalar._rolling_reference(invalid, 'level', radius)


@pytest.mark.parametrize('ordered', [True, False])
def test_nn_window_index_preserves_scalar_boundaries_order_and_gaps(ordered):
    rng = random.Random(20261002)
    intervals = [(rng.randint(350, 1800), i+.125, i+.975) for i in range(200)]
    if not ordered:
        rng.shuffle(intervals)
    index = NNWindowIndex(intervals)
    cases = [[], [(0, 200)], [(10.125, 10.975)], [(10.2, 10.975)],
             [(0, 1), (1, 2)], [(0, 3), (2, 5)], [(9, 11), (0, 3)]]
    for _ in range(25):
        edges = sorted(rng.uniform(0, 200) for _ in range(8))
        cases.append(list(zip(edges[::2], edges[1::2])))
    for spans in cases:
        expected = [r for r in intervals if any(r[1] >= a and r[2] <= b for a, b in spans)]
        assert index.contained(spans) == expected


def test_read_ownership_retry_revision_and_case_isolation():
    subprocess.run(['node', 'tests/browser_read_requests.cjs'], check=True, timeout=15)
