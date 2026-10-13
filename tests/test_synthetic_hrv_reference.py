"""Independent NN examples protect fictional source references, not clinical rules."""
from __future__ import annotations

import math
import statistics

from scripts.generate_synthetic_demo import Beat, _statistics_for


def beats_for(groups, intervals):
    sample = 0
    result = []
    for group, interval in zip(groups, intervals):
        sample += interval // 5
        result.append(Beat(sample, interval, group))
    return tuple(result)


def test_synthetic_source_hrv_excludes_n_after_non_n_and_preserves_sample_formula():
    beats = beats_for([1, 1, 2, 1, 1, 1, 34, 1, 1, 1],
                      [0, 800, 500, 1400, 900, 1000, 700, 1500, 800, 900])
    # Independently hand-enumerated five adjacent NN intervals:
    # [800, 900, 1000, 800, 900], sample variance 7000.
    result = _statistics_for(beats, 60)
    assert result["sdnn_ms"] == 83.67
    assert result["rmssd_ms"] == 132.29
    assert result["pnn50_pct"] == 100.0
    # The previous endpoint-only population [800,1400,900,1000,1500,800,900]
    # produces 287.85; keep this counterexample explicit, never relax <2 ms.
    assert round(statistics.stdev([800, 1400, 900, 1000, 1500, 800, 900]), 2) == 287.85


def test_synthetic_source_hrv_keeps_original_nn_bounds_and_rejects_other_endpoints():
    beats = beats_for([1, 1, 1, 1, 2, 1, 1, 3, 1, 1, 34, 1, 1],
                      [0, 300, 2000, 295, 600, 1000, 800, 600, 1200, 900, 700, 1000, 2005])
    expected = [300, 2000, 800, 900]
    differences = [1700, -1200, 100]
    result = _statistics_for(beats, 60)
    assert result["sdnn_ms"] == round(statistics.stdev(expected), 2)
    assert result["rmssd_ms"] == round(math.sqrt(sum(value * value for value in differences) / 3), 2)
    assert result["pnn50_pct"] == 100.0
