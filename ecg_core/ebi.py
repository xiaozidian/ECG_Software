from __future__ import annotations

import math
import statistics
import struct
from bisect import bisect_left
from collections import Counter
from functools import lru_cache
from pathlib import Path

from .config import SAMPLE_RATE

HEADER_SIZE = 32
RECORD = struct.Struct("<IHHIIII")
GROUP_LABELS = {1: "N", 2: "S", 3: "V", 34: "噪声"}
SCATTER_MODES = frozenset({"rr", "n", "nn", "s", "v", "hour"})
SCATTER_DEFINITIONS = {
    "rr": "全部有效心搏的 RR(i)–RR(i+1)",
    "n": "以 N 心搏为中心的 RR(i)–RR(i+1)",
    "nn": "前、中、后三搏均为 N 的严格 N-N 散点",
    "s": "以 S 心搏为中心的 RR(i)–RR(i+1)",
    "v": "以 V 心搏为中心的 RR(i)–RR(i+1)",
    "hour": "主波形所在一小时内全部有效心搏的 RR(i)–RR(i+1)",
}
VALID_BEAT_GROUPS = frozenset({1, 2, 3})


@lru_cache(maxsize=3)
def load_records(path_text: str) -> tuple[tuple[int, int, int, int, int, int, int], ...]:
    data = Path(path_text).read_bytes()
    payload = data[HEADER_SIZE:]
    if len(payload) % RECORD.size:
        raise ValueError("EBI记录长度不是24字节的整数倍")
    return tuple(RECORD.iter_unpack(payload))


@lru_cache(maxsize=3)
def _record_sample_indexes(path_text: str) -> tuple[int, ...]:
    return tuple(record[0] for record in load_records(path_text))


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


def _validate_scatter_mode(mode: str) -> str:
    normalized = str(mode or "").lower()
    if normalized not in SCATTER_MODES:
        raise ValueError("散点图模式必须是 rr、n、nn、s、v 或 hour")
    return normalized


def _normalize_hour_start(hour_start_s: float) -> float:
    try:
        value = float(hour_start_s)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("小时散点起始时间必须为有效数字") from exc
    if not math.isfinite(value) or value < 0:
        raise ValueError("小时散点起始时间必须为非负有限数字")
    return float(math.floor(value / 3600) * 3600)


def iter_scatter_points(records, mode: str, hour_start_s: float = 0):
    """Yield scatter points anchored on the middle beat without crossing noise."""
    mode = _validate_scatter_mode(mode)
    hour_start_s = _normalize_hour_start(hour_start_s)
    hour_start_sample = int(hour_start_s * SAMPLE_RATE)
    hour_end_sample = hour_start_sample + 3600 * SAMPLE_RATE
    wanted_group = {"n": 1, "s": 2, "v": 3}.get(mode)
    for index in range(1, len(records) - 1):
        previous, current, following = records[index - 1], records[index], records[index + 1]
        if mode == "hour" and not hour_start_sample <= current[0] < hour_end_sample:
            continue
        groups = (previous[2], current[2], following[2])
        if any(group not in VALID_BEAT_GROUPS for group in groups):
            continue
        rr_ms, next_rr_ms = current[6], following[6]
        if mode == "nn":
            if groups != (1, 1, 1) or not (300 <= rr_ms <= 2000 and 300 <= next_rr_ms <= 2000):
                continue
        elif not (0 < rr_ms <= 5000 and 0 < next_rr_ms <= 5000):
            continue
        if wanted_group is not None and current[2] != wanted_group:
            continue
        yield {
            "sample_index": current[0],
            "time_s": round(current[0] / SAMPLE_RATE, 3),
            "x": rr_ms,
            "y": next_rr_ms,
            "rr_ms": rr_ms,
            "next_rr_ms": next_rr_ms,
            "previous_group": previous[2],
            "group": current[2],
            "next_group": following[2],
            "label": GROUP_LABELS.get(current[2], "?"),
        }


def _even_sample(items: list[dict], limit: int) -> list[dict]:
    if limit >= len(items):
        return list(items)
    if limit <= 1:
        return [items[len(items) // 2]] if items else []
    return [items[round(index * (len(items) - 1) / (limit - 1))] for index in range(limit)]


def _sample_scatter_points(points: list[dict], mode: str, max_points: int) -> list[dict]:
    if len(points) <= max_points:
        return points
    if mode not in {"rr", "hour"}:
        return _even_sample(points, max_points)

    abnormal = [point for point in points if point["group"] != 1]
    normal = [point for point in points if point["group"] == 1]
    abnormal_limit = min(len(abnormal), max(1, max_points * 35 // 100))
    normal_limit = min(len(normal), max_points - abnormal_limit)
    abnormal_limit = min(len(abnormal), abnormal_limit + max_points - abnormal_limit - normal_limit)
    selected = _even_sample(abnormal, abnormal_limit)
    selected.extend(_even_sample(normal, normal_limit))
    selected.sort(key=lambda point: point["sample_index"])
    return selected


def _nice_upper(value: float, minimum: float) -> float:
    value = max(float(value), float(minimum))
    magnitude = 10 ** math.floor(math.log10(value))
    scaled = value / magnitude
    step = 1 if scaled <= 1 else 2 if scaled <= 2 else 5 if scaled <= 5 else 10
    return float(step * magnitude)


def scatter_points(path: Path, mode: str = "rr", max_points: int = 12000, hour_start_s: float = 0) -> dict:
    mode = _validate_scatter_mode(mode)
    hour_start_s = _normalize_hour_start(hour_start_s)
    max_points = max(500, min(int(max_points), 20000))
    candidates = list(iter_scatter_points(load_records(str(path)), mode, hour_start_s))
    returned = _sample_scatter_points(candidates, mode, max_points)
    max_x = max((point["x"] for point in candidates), default=1)
    max_y = max((point["y"] for point in candidates), default=1)
    axis = {"x_label": "RR(i)", "y_label": "RR(i+1)", "x_unit": "ms", "y_unit": "ms"}
    upper = _nice_upper(max(max_x, max_y), 2000)
    bounds = {"x_min": 0, "x_max": upper, "y_min": 0, "y_max": upper}
    return {
        "mode": mode,
        "definition": SCATTER_DEFINITIONS[mode],
        "candidate_count": len(candidates),
        "returned_count": len(returned),
        "sampled": len(returned) < len(candidates),
        "sampling": "deterministic-temporal-stratified-v1",
        "hour_start_s": hour_start_s if mode == "hour" else None,
        "hour_end_s": hour_start_s + 3600 if mode == "hour" else None,
        "axis": axis,
        "bounds": bounds,
        "points": returned,
    }


def _point_in_polygon(x: float, y: float, polygon: list[tuple[float, float]]) -> bool:
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous
        x2, y2 = current
        cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
        tolerance = 1e-9 * max(1.0, abs(x), abs(y), abs(x1), abs(y1), abs(x2), abs(y2))
        if (
            abs(cross) <= tolerance
            and min(x1, x2) - tolerance <= x <= max(x1, x2) + tolerance
            and min(y1, y2) - tolerance <= y <= max(y1, y2) + tolerance
        ):
            return True
        if (y1 > y) != (y2 > y):
            crossing = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x <= crossing:
                inside = not inside
        previous = current
    return inside


def select_scatter_points(
    path: Path,
    mode: str,
    polygon: list[tuple[float, float]],
    hour_start_s: float = 0,
) -> dict:
    mode = _validate_scatter_mode(mode)
    hour_start_s = _normalize_hour_start(hour_start_s)
    if len(polygon) < 3 or len(polygon) > 128:
        raise ValueError("圈选边界必须包含 3–128 个点")
    if any(not math.isfinite(x) or not math.isfinite(y) for x, y in polygon):
        raise ValueError("圈选边界包含无效坐标")
    min_x = min(point[0] for point in polygon)
    max_x = max(point[0] for point in polygon)
    min_y = min(point[1] for point in polygon)
    max_y = max(point[1] for point in polygon)
    samples: list[int] = []
    groups = Counter()
    for point in iter_scatter_points(load_records(str(path)), mode, hour_start_s):
        if not (min_x <= point["x"] <= max_x and min_y <= point["y"] <= max_y):
            continue
        if _point_in_polygon(point["x"], point["y"], polygon):
            samples.append(point["sample_index"])
            groups[str(point["group"])] += 1
    return {
        "mode": mode,
        "total": len(samples),
        "sample_indices": samples,
        "group_counts": dict(groups),
        "exact": True,
        "hour_start_s": hour_start_s if mode == "hour" else None,
        "hour_end_s": hour_start_s + 3600 if mode == "hour" else None,
    }


def beat_details(path: Path, sample_indices: list[int]) -> dict[int, dict]:
    records = load_records(str(path))
    indexes = _record_sample_indexes(str(path))
    result: dict[int, dict] = {}
    for sample_index in sample_indices:
        position = bisect_left(indexes, sample_index)
        if position >= len(indexes) or indexes[position] != sample_index:
            continue
        record = records[position]
        result[sample_index] = {
            "sample_index": sample_index,
            "time_s": round(sample_index / SAMPLE_RATE, 3),
            "group": record[2],
            "label": GROUP_LABELS.get(record[2], "?"),
            "rr_ms": record[6],
            "hr": round(60000 / record[6], 1) if record[6] else None,
        }
    return result


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
