"""Independent mathematical oracles. No imports from ecg_core.

This profile reproduces the product's existing estimators; it is not a
clinical validity statement or a Task Force compliance assertion.
"""
from __future__ import annotations

from math import fsum, sqrt, isfinite

NON_QRS = frozenset(("O", "Y", "T"))


def reference_rr(rows, fs):
    if isinstance(fs, bool) or not isinstance(fs, (int, float)) or not isfinite(fs) or fs <= 0:
        raise ValueError("Invalid sample rate")
    selected = [r for r in rows if r.get("class_code") not in NON_QRS]
    result = []
    for index, row in enumerate(selected):
        sample = row.get("sample_index")
        valid = (not isinstance(sample, bool) and isinstance(sample, (int, float))
                 and isfinite(sample) and sample >= 0 and int(sample) == sample)
        previous = selected[index - 1].get("sample_index") if index else None
        previous_valid = (not isinstance(previous, bool) and isinstance(previous, (int, float))
                          and isfinite(previous) and previous >= 0 and int(previous) == previous)
        interval = ((sample - previous) * 1000 / fs
                    if valid and previous_valid and sample > previous else None)
        result.append({"index": index, "sample": sample, "previous_sample": previous, "rr_ms": interval,
                       "code": row.get("class_code"), "previous_code": selected[index - 1].get("class_code") if index else None})
    return result


def reference_nn(rows, fs, min_ms=300, max_ms=2000, excluded=(), duration=float("inf")):
    result = []
    for item in reference_rr(rows, fs):
        rr = item["rr_ms"]
        if rr is None or item["code"] != "N" or item["previous_code"] != "N" or not min_ms <= rr <= max_ms:
            continue
        end = item["sample"] / fs
        start = item["previous_sample"] / fs
        if end > duration or any(start < b and end > a for a, b in excluded):
            continue
        result.append((item["index"] - 1, start, end, rr))
    return result


def reference_time_domain(intervals):
    values = [r[3] for r in intervals]
    n = len(values)
    mean = fsum(values) / n if n else None
    variance = fsum((v - mean) ** 2 for v in values) / (n - 1) if n > 1 else None
    differences = [b[3] - a[3] for a, b in zip(intervals, intervals[1:]) if b[0] == a[0] + 1]
    nn50 = sum(abs(v) > 50 for v in differences)
    return {"nn_count": n, "diff_count": len(differences), "mean_nn_ms": mean,
            "sdnn_ms": sqrt(variance) if variance is not None else None,
            "variance_ms2": variance,
            "rmssd_ms": sqrt(fsum(v * v for v in differences) / len(differences)) if differences else None,
            "nn50": nn50, "pnn50_pct": 100 * nn50 / len(differences) if differences else None,
            "task_force_nn_count_pnn50_pct": 100 * nn50 / n if n else None}


def reference_spectrum(intervals, excluded=()):
    """SciPy density periodogram with explicit product estimator settings."""
    import numpy as np
    from scipy.signal import periodogram
    times = np.asarray([r[2] for r in intervals], dtype=float)
    values = np.asarray([r[3] for r in intervals], dtype=float)
    if (len(times) < 2 or not np.isfinite(times).all() or not np.isfinite(values).all()
            or (np.diff(times) <= 0).any() or times[-1] - times[0] < 255.75):
        return None
    grid = (times[0] + times[-1] - 255.75) / 2 + np.arange(1024) / 4
    indices = np.searchsorted(times, grid, side="right").clip(1, len(times) - 1)
    for left, right in zip(times[indices - 1], times[indices]):
        if right - left > 5 or any(a < right and b > left for a, b in excluded):
            return None
    sampled = np.interp(grid, times, values)
    # Product explicitly removes the unweighted mean before applying a
    # symmetric Hann. detrend=False prevents a second or weighted detrend.
    frequencies, density = periodogram(sampled - sampled.mean(), fs=4,
                                      window=np.hanning(1024), nfft=1024,
                                      detrend=False, return_onesided=True,
                                      scaling="density")
    return frequencies[:129], density[:129]


def band_powers(frequencies, density):
    import numpy as np
    step = 4 / 1024
    def band(lo, hi):
        mask = (frequencies >= lo) & (frequencies < hi)
        return float(np.sum(density[mask]) * step)
    lf, hf = band(.04, .15), band(.15, .4)
    return {"total_ms2": band(.0033, .4), "vlf_ms2": band(.0033, .04),
            "lf_ms2": lf, "hf_ms2": hf, "lf_hf": lf / hf if hf else None}
