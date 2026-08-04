from __future__ import annotations

import math
import statistics
import struct
from collections import Counter
from functools import lru_cache
from pathlib import Path

from .config import SAMPLE_RATE

HEADER_SIZE = 32
RECORD = struct.Struct("<IHHIIII")
GROUP_LABELS = {1: "N", 2: "S", 3: "V", 34: "噪声"}


@lru_cache(maxsize=3)
def load_records(path_text: str) -> tuple[tuple[int, int, int, int, int, int, int], ...]:
    data = Path(path_text).read_bytes()
    payload = data[HEADER_SIZE:]
    if len(payload) % RECORD.size:
        raise ValueError("EBI记录长度不是24字节的整数倍")
    return tuple(RECORD.iter_unpack(payload))


def _valid(records):
    return [record for record in records if record[2] != 34]


def metrics(path: Path, duration_seconds: float) -> dict:
    records = load_records(str(path))
    valid = _valid(records)
    rr = [record[6] for record in valid if 250 <= record[6] <= 5000]
    longest = max(valid, key=lambda item: item[6]) if valid else None
    groups = Counter(record[2] for record in records)
    return {
        "record_count": len(records),
        "valid_beats": len(valid),
        "first_beat_time_s": round(valid[0][0] / SAMPLE_RATE, 3) if valid else None,
        "group_counts": {str(key): value for key, value in sorted(groups.items())},
        "avg_hr_from_duration": round(len(valid) * 60 / max(duration_seconds, 1), 2),
        "avg_hr_from_rr": round(60000 / statistics.mean(rr), 2) if rr else None,
        "longest_rr_ms": longest[6] if longest else None,
        "longest_rr_time_s": round(longest[0] / SAMPLE_RATE, 3) if longest else None,
        "min_rr_ms": min(rr) if rr else None,
        "format_verified": True,
    }


def heart_rate_trend(path: Path, duration_seconds: float, bin_seconds: int = 60) -> dict:
    bin_seconds = max(10, min(int(bin_seconds), 600))
    bin_samples = SAMPLE_RATE * bin_seconds
    bins = [0] * (int(math.ceil(duration_seconds / bin_seconds)) or 1)
    for record in load_records(str(path)):
        if record[2] == 34:
            continue
        index = min(record[0] // bin_samples, len(bins) - 1)
        bins[index] += 1
    points = [
        {"time_s": i * bin_seconds + bin_seconds / 2, "hr": round(count * 60 / bin_seconds, 2)}
        for i, count in enumerate(bins)
        if count
    ]
    values = [point["hr"] for point in points]
    return {
        "bin_seconds": bin_seconds,
        "points": points,
        "min_hr": round(min(values), 1) if values else None,
        "max_hr": round(max(values), 1) if values else None,
    }


def hrv(path: Path) -> dict:
    records = load_records(str(path))
    nn: list[tuple[int, int]] = []
    previous_group = None
    for record in records:
        group = record[2]
        rr = record[6]
        if group == 1 and previous_group == 1 and 300 <= rr <= 2000:
            nn.append((record[0], rr))
        previous_group = group
    if len(nn) < 3:
        return {}
    values = [item[1] for item in nn]
    diffs = [values[i] - values[i - 1] for i in range(1, len(values))]
    five_minute: dict[int, list[int]] = {}
    for sample_index, value in nn:
        five_minute.setdefault(sample_index // (SAMPLE_RATE * 300), []).append(value)
    segment_means = [statistics.mean(group) for group in five_minute.values() if len(group) >= 30]
    segment_sd = [statistics.stdev(group) for group in five_minute.values() if len(group) >= 30]
    histogram = Counter(round(value / 7.8125) for value in values)
    return {
        "nn_count": len(values),
        "mean_nn_ms": round(statistics.mean(values), 2),
        "sdnn_ms": round(statistics.stdev(values), 2),
        "sdann_ms": round(statistics.stdev(segment_means), 2) if len(segment_means) > 1 else None,
        "sdnn_index_ms": round(statistics.mean(segment_sd), 2) if segment_sd else None,
        "rmssd_ms": round(math.sqrt(statistics.mean(value * value for value in diffs)), 2),
        "pnn50_pct": round(sum(abs(value) > 50 for value in diffs) * 100 / len(diffs), 2),
        "triangular_index": round(len(values) / max(histogram.values()), 2),
        "method": "仅使用相邻N-N间期，300–2000 ms；研究演示算法",
    }


def rr_visuals(path: Path, max_points: int = 4000) -> dict:
    records = load_records(str(path))
    values = [record[6] for record in records if record[2] == 1 and 300 <= record[6] <= 2000]
    bins = list(range(300, 2050, 50))
    counts = [0] * (len(bins) - 1)
    for value in values:
        index = min((value - 300) // 50, len(counts) - 1)
        if index >= 0:
            counts[index] += 1
    stride = max(1, (len(values) - 1) // max_points)
    poincare = [[values[i - 1], values[i]] for i in range(1, len(values), stride)][:max_points]
    return {
        "histogram": [{"start_ms": bins[i], "end_ms": bins[i + 1], "count": counts[i]} for i in range(len(counts))],
        "poincare": poincare,
    }


def visible_beats(path: Path, start_s: float, duration_s: float) -> list[dict]:
    start_sample = int(start_s * SAMPLE_RATE)
    end_sample = int((start_s + duration_s) * SAMPLE_RATE)
    result = []
    for record in load_records(str(path)):
        if record[0] < start_sample:
            continue
        if record[0] > end_sample:
            break
        result.append({
            "sample_index": record[0],
            "time_s": round(record[0] / SAMPLE_RATE, 3),
            "group": record[2],
            "label": GROUP_LABELS.get(record[2], "?"),
            "rr_ms": record[6],
            "hr": round(60000 / record[6], 1) if record[6] else None,
        })
    return result


def list_events(
    path: Path,
    event_type: str = "all",
    offset: int = 0,
    limit: int = 200,
    brady_threshold: int = 50,
    tachy_threshold: int = 120,
    pause_seconds: float = 2.5,
) -> dict:
    events: list[dict] = []
    summary = Counter()
    for record in load_records(str(path)):
        sample, _, group, _, _, _, rr = record
        if group == 2:
            kind, label, severity = "S", "室上性候选心搏", "medium"
        elif group == 3:
            kind, label, severity = "V", "室性候选心搏", "high"
        elif group == 34:
            kind, label, severity = "noise", "噪声/待确认心搏", "low"
        elif rr >= pause_seconds * 1000:
            kind, label, severity = "pause", f"长RR间期 {rr / 1000:.2f}s", "high"
        elif rr and 60000 / rr >= tachy_threshold:
            kind, label, severity = "tachy", f"心动过速候选 {60000 / rr:.0f} bpm", "medium"
        elif rr and 60000 / rr <= brady_threshold:
            kind, label, severity = "brady", f"心动过缓候选 {60000 / rr:.0f} bpm", "medium"
        else:
            continue
        summary[kind] += 1
        if event_type not in ("all", kind):
            continue
        events.append({
            "type": kind,
            "label": label,
            "severity": severity,
            "sample_index": sample,
            "time_s": round(sample / SAMPLE_RATE, 3),
            "rr_ms": rr,
            "hr": round(60000 / rr, 1) if rr else None,
            "group": group,
            "review_status": "待复核",
        })
    events.sort(key=lambda item: item["sample_index"])
    return {
        "summary": dict(summary),
        "total": len(events),
        "offset": offset,
        "limit": limit,
        "items": events[offset: offset + limit],
    }
