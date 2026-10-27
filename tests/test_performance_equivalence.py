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
