"""Conservative ambulatory ST-T screening with mandatory physician review.

The detector works in the source device scale and emits review candidates,
never a diagnosis. It uses normal-beat blocks, local references, J+60 ms
measurements, persistence rules, and signal/axis-shift quality gates.
"""

from __future__ import annotations

import copy
import math
import mmap
import re
import statistics
import struct
from collections import OrderedDict
from pathlib import Path

from .config import CHANNEL_COUNT, SAMPLE_RATE

ALGORITHM_VERSION = "stt-screening-0.1.0"
LEADS = ("I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6")
_FRAME = struct.Struct("<8h")
_CACHE: OrderedDict[tuple, dict] = OrderedDict()
_CACHE_LIMIT = 8

DEFAULT_CONFIG = {
    "block_seconds": 16,
    "minimum_normal_beats": 3,
    "maximum_beats_per_block": 7,
    "st_measurement_ms": 60,
    "entry_threshold_units": 50.0,
    "target_threshold_units": 100.0,
    "minimum_target_duration_s": 60,
    "exit_confirmation_s": 30,
    "reference_window_minutes": 20,
    "axis_shift_qrs_fraction": 0.35,
    "t_inversion_minimum_units": 75.0,
    "maximum_trend_points_per_lead": 720,
}

_ST_T_TERM = re.compile(
    r"(?:(?<![A-Za-z])S\s*[-–—－]?\s*T(?:\s*[-–—－]?\s*T)?(?![A-Za-z])"
    r"|ST段|T波|T倒置|T低平|T\s*[-–—]?\s*wave)", re.IGNORECASE,
)
_SOURCE_FRAGMENT_SPLIT = re.compile(r"(?<=[。！？；!?;])\s*|\n+")
_CASE_AMPLITUDE = re.compile(
    r"(?<![A-Za-z0-9])(?:[+\-−＋－]?\s*\d+(?:\.\d+)?)\s*(?:mV|µV|μV)", re.IGNORECASE,
)


def extract_stt_source_report(conclusion: str) -> dict:
    """Extract ST/T source wording while hiding unverified case amplitudes."""
    if not isinstance(conclusion, str):
        conclusion = ""
    fragments, redacted_any = [], False
    for raw in _SOURCE_FRAGMENT_SPLIT.split(conclusion):
        fragment = raw.strip()
        if not fragment or not _ST_T_TERM.search(fragment):
            continue
        redacted, count = _CASE_AMPLITUDE.subn("【病例幅度已隐藏】", fragment)
        redacted_any = redacted_any or count > 0
        if redacted not in fragments:
            fragments.append(redacted)
    return {
        "origin": "source_report_conclusion", "available": bool(fragments),
        "text": "\n".join(fragments), "fragments": fragments,
        "is_source_excerpt": True, "software_interpretation_added": False,
        "amplitude_values_redacted": redacted_any,
    }


def _median(values, default=0.0) -> float:
    finite = [float(value) for value in values if isinstance(value, (int, float)) and math.isfinite(value)]
    return float(statistics.median(finite)) if finite else float(default)


def _mad(values) -> float:
    center = _median(values)
    return _median(abs(float(value) - center) for value in values)


def _derived(raw: tuple[int, ...]) -> tuple[float, ...]:
    lead_i, lead_ii = raw[0], raw[1]
    return (
        lead_i, lead_ii, lead_ii - lead_i, -(lead_i + lead_ii) / 2,
        lead_i - lead_ii / 2, lead_ii - lead_i / 2,
        raw[2], raw[3], raw[4], raw[5], raw[6], raw[7],
    )


def _read_leads(buffer: mmap.mmap, sample: int, total_samples: int) -> tuple[float, ...]:
    sample = max(0, min(total_samples - 1, sample))
    return _derived(_FRAME.unpack_from(buffer, sample * CHANNEL_COUNT * 2))


def _normalize_records(records) -> list[tuple[int, int, int]]:
    normalized = []
    for row in records:
        if isinstance(row, dict):
            sample, group, rr = row.get("sample_index"), row.get("group", row.get("source_group")), row.get("rr_ms", 0)
        else:
            sample, group, rr = row[0], row[2], row[6]
        if isinstance(sample, int) and isinstance(group, int):
            normalized.append((sample, group, int(rr or 0)))
    return sorted(normalized)


def _evenly(values: list, limit: int) -> list:
    if len(values) <= limit:
        return values
    return [values[round(index * (len(values) - 1) / (limit - 1))] for index in range(limit)]


def _estimate_j_sample(buffer, beats, total_samples) -> tuple[int, float]:
    """Estimate QRS end from multi-beat, multi-lead derivative energy."""
    energies = []
    for offset in range(33):  # R to R+160 ms
        changes = []
        for beat, _group, _rr in beats:
            current = _read_leads(buffer, beat + offset, total_samples)
            previous = _read_leads(buffer, beat + offset - 1, total_samples)
            changes.extend(abs(current[index] - previous[index]) for index in (1, 6, 10))
        energies.append(_median(changes))
    peak_index = max(range(21), key=energies.__getitem__)
    peak, noise = energies[peak_index], _median(energies[-8:])
    threshold = max(2.0, noise * 2.5, peak * 0.12)
    j_sample = 18  # 90 ms fallback
    for index in range(max(8, peak_index + 2), 29):
        if all(value <= threshold for value in energies[index:index + 4]):
            j_sample = index
            break
    confidence = max(0.0, min(1.0, (peak - noise) / max(peak, 1.0)))
    return j_sample, confidence


def _block_measurement(buffer, beats, all_count, total_samples, config) -> dict:
    j_sample, landmark_confidence = _estimate_j_sample(buffer, beats, total_samples)
    st_offset = j_sample + round(config["st_measurement_ms"] * SAMPLE_RATE / 1000)
    values = {lead: {key: [] for key in ("baseline", "st", "t", "qrs", "span")} for lead in LEADS}
    for beat, _group, rr_ms in beats:
        baseline_frames = [_read_leads(buffer, beat + offset, total_samples) for offset in range(-40, -23, 4)]
        st_frames = [_read_leads(buffer, beat + st_offset + offset, total_samples) for offset in range(-2, 3)]
        qrs_frames = [_read_leads(buffer, beat + offset, total_samples) for offset in range(-8, j_sample + 1, 2)]
        rr_samples = max(round(rr_ms * SAMPLE_RATE / 1000), round(0.45 * SAMPLE_RATE))
        t_last = min(j_sample + 72, max(j_sample + 30, round(rr_samples * 0.62)))
        t_frames = [_read_leads(buffer, beat + offset, total_samples) for offset in range(j_sample + 24, t_last + 1, 2)]
        for lead_index, lead in enumerate(LEADS):
            baseline_values = [frame[lead_index] for frame in baseline_frames]
            baseline = _median(baseline_values)
            qrs_values = [frame[lead_index] for frame in qrs_frames]
            t_values = [frame[lead_index] - baseline for frame in t_frames]
            values[lead]["baseline"].append(baseline)
            values[lead]["st"].append(_median(frame[lead_index] for frame in st_frames) - baseline)
            values[lead]["t"].append(max(t_values, key=abs) if t_values else 0.0)
            values[lead]["qrs"].append(max(qrs_values) - min(qrs_values) if qrs_values else 0.0)
            values[lead]["span"].append(max(baseline_values) - min(baseline_values))

    lead_values, lead_scores = {}, []
    for lead, lead_data in values.items():
        qrs = _median(lead_data["qrs"])
        baseline_variation = _mad(lead_data["baseline"]) + _median(lead_data["span"])
        qrs_variation = _mad(lead_data["qrs"]) / max(qrs, 1.0)
        noise_ratio = baseline_variation / max(qrs, 40.0)
        score = max(0.0, min(1.0, 1.0 - min(0.65, noise_ratio) - min(0.35, qrs_variation)))
        lead_scores.append(score)
        lead_values[lead] = {
            "st_level_units": round(_median(lead_data["st"]), 2),
            "t_amplitude_units": round(_median(lead_data["t"]), 2),
            "qrs_amplitude_units": round(qrs, 2), "quality_score": round(score, 3),
        }
    normal_ratio = len(beats) / max(all_count, 1)
    overall = max(0.0, min(1.0, _median(lead_scores) * min(1.0, normal_ratio / 0.6)))
    return {
        "j_offset_ms": round(j_sample * 1000 / SAMPLE_RATE),
        "landmark_confidence": round(landmark_confidence, 3),
        "normal_beat_count": len(beats), "normal_beat_ratio": round(normal_ratio, 3),
        "quality_score": round(overall, 3),
        "eligible": normal_ratio >= 0.35 and overall >= 0.42,
        "leads": lead_values,
    }


def _rolling_reference(values: list[dict], key: str, radius: int) -> list[float | None]:
    result = []
    for index in range(len(values)):
        window = values[max(0, index - radius):min(len(values), index + radius + 1)]
        eligible = [row[key] for row in window if row.get("eligible") and row.get(key) is not None]
        result.append(round(_median(eligible), 2) if eligible else None)
    return result


def _lead_episodes(points: list[dict], lead: str, config: dict) -> list[dict]:
    episodes, block_s = [], config["block_seconds"]
    exit_blocks = max(1, math.ceil(config["exit_confirmation_s"] / block_s))
    for direction, kind, label in ((-1, "st_depression", "ST 段压低候选"), (1, "st_elevation", "ST 段抬高候选")):
        active, below = None, 0
        for point in points + [{"eligible": False, "deviation_units": 0.0}]:
            value = direction * float(point.get("deviation_units") or 0.0)
            qualifies = point.get("eligible") and not point.get("axis_shift_suspected") and value >= config["entry_threshold_units"]
            if active is None and qualifies:
                active, below = [point], 0
            elif active is not None and qualifies:
                active.append(point); below = 0
            elif active is not None:
                below += 1
                if below >= exit_blocks or not point.get("eligible"):
                    strong_s = sum(block_s for row in active if direction * row["deviation_units"] >= config["target_threshold_units"])
                    start_s, end_s = active[0]["time_s"] - block_s / 2, active[-1]["time_s"] + block_s / 2
                    peak = max(active, key=lambda row: direction * row["deviation_units"])
                    if strong_s >= config["minimum_target_duration_s"] and end_s - start_s >= config["minimum_target_duration_s"]:
                        episodes.append({
                            "kind": kind, "label": label, "start_s": max(0.0, round(start_s, 1)),
                            "end_s": round(end_s, 1), "duration_s": round(end_s - start_s, 1),
                            "peak_time_s": round(peak["time_s"], 1),
                            "peak_deviation_units": round(peak["deviation_units"], 1), "leads": [lead],
                            "quality_score": round(_median(row["quality_score"] for row in active), 3),
                            "axis_shift_suspected": False, "review_status": "pending", "diagnosis": None,
                        })
                    active, below = None, 0
    return episodes


def _t_episodes(points: list[dict], lead: str, config: dict) -> list[dict]:
    minimum, block_s, run, result = config["t_inversion_minimum_units"], config["block_seconds"], [], []
    for point in points + [{"eligible": False}]:
        value, reference = point.get("t_amplitude_units"), point.get("t_reference_units")
        inverted = (
            point.get("eligible") and not point.get("axis_shift_suspected")
            and value is not None and reference is not None
            and abs(value) >= minimum and abs(reference) >= minimum and value * reference < 0
        )
        if inverted:
            run.append(point); continue
        if len(run) * block_s >= config["minimum_target_duration_s"]:
            start_s, end_s = run[0]["time_s"] - block_s / 2, run[-1]["time_s"] + block_s / 2
            peak = max(run, key=lambda row: abs(row["t_amplitude_units"] - row["t_reference_units"]))
            result.append({
                "kind": "t_wave_inversion", "label": "T 波极性反转候选",
                "start_s": max(0.0, round(start_s, 1)), "end_s": round(end_s, 1),
                "duration_s": round(end_s - start_s, 1), "peak_time_s": round(peak["time_s"], 1),
                "peak_deviation_units": round(peak["t_amplitude_units"] - peak["t_reference_units"], 1),
                "leads": [lead], "quality_score": round(_median(row["quality_score"] for row in run), 3),
                "axis_shift_suspected": False, "review_status": "pending", "diagnosis": None,
            })
        run = []
    return result


def _merge_episodes(items: list[dict]) -> list[dict]:
    merged = []
    for item in sorted(items, key=lambda row: (row["kind"], row["start_s"])):
        target = next((row for row in reversed(merged) if row["kind"] == item["kind"] and item["start_s"] <= row["end_s"] + 30), None)
        if target is None:
            merged.append(copy.deepcopy(item)); continue
        target["start_s"], target["end_s"] = min(target["start_s"], item["start_s"]), max(target["end_s"], item["end_s"])
        target["duration_s"] = round(target["end_s"] - target["start_s"], 1)
        target["leads"] = sorted(set(target["leads"] + item["leads"]), key=LEADS.index)
        if abs(item["peak_deviation_units"]) > abs(target["peak_deviation_units"]):
            target["peak_deviation_units"], target["peak_time_s"] = item["peak_deviation_units"], item["peak_time_s"]
        target["quality_score"] = round(min(target["quality_score"], item["quality_score"]), 3)
    merged.sort(key=lambda row: row["start_s"])
    for index, item in enumerate(merged, 1):
        item["id"], item["lead_count"] = f"auto-stt-{index}", len(item["leads"])
    return merged


def analyze_stt(waveform_path: str | Path, records, duration_s: float | None = None, *, analysis_revision=None, config=None) -> dict:
    """Analyze a recording and return automatic review candidates and trends."""
    path, settings = Path(waveform_path), {**DEFAULT_CONFIG, **(config or {})}
    stat, normalized = path.stat(), _normalize_records(records)
    signature = (len(normalized), normalized[0] if normalized else None, normalized[-1] if normalized else None, analysis_revision)
    cache_key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns, signature, tuple(sorted(settings.items())))
    if cache_key in _CACHE:
        _CACHE.move_to_end(cache_key); return copy.deepcopy(_CACHE[cache_key])
    total_samples = stat.st_size // (CHANNEL_COUNT * 2)
    duration = min(float(duration_s or total_samples / SAMPLE_RATE), total_samples / SAMPLE_RATE)
    block_samples = int(settings["block_seconds"] * SAMPLE_RATE)
    by_block: dict[int, list[tuple[int, int, int]]] = {}
    for row in normalized:
        if 0 <= row[0] < total_samples:
            by_block.setdefault(row[0] // block_samples, []).append(row)
    blocks = []
    with path.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as buffer:
        for block_index in range(math.ceil(duration / settings["block_seconds"])):
            rows = by_block.get(block_index, [])
            usable = []
            for index, row in enumerate(rows):
                sample, group, rr = row
                previous_group = rows[index - 1][1] if index else None
                next_group = rows[index + 1][1] if index + 1 < len(rows) else None
                if group == 1 and previous_group not in {3, 34} and next_group not in {3, 34} and 350 <= rr <= 2000 and sample >= 50 and sample + 120 < total_samples:
                    usable.append(row)
            selected = _evenly(usable, settings["maximum_beats_per_block"])
            all_count = len([row for row in rows if row[1] != 34])
            time_s = round(min(duration, (block_index + 0.5) * settings["block_seconds"]), 1)
            if len(selected) < settings["minimum_normal_beats"]:
                blocks.append({"time_s": time_s, "eligible": False, "quality_score": 0.0,
                               "normal_beat_count": len(selected), "normal_beat_ratio": round(len(selected) / max(1, all_count), 3),
                               "j_offset_ms": None, "landmark_confidence": 0.0, "leads": {}})
                continue
            measured = _block_measurement(buffer, selected, all_count, total_samples, settings)
            measured["time_s"] = time_s; blocks.append(measured)

    radius = max(1, round(settings["reference_window_minutes"] * 60 / settings["block_seconds"] / 2))
    lead_points, episodes = {}, []
    for lead in LEADS:
        points = []
        for block in blocks:
            measure = block["leads"].get(lead, {})
            points.append({
                "time_s": block["time_s"], "eligible": block["eligible"], "quality_score": block["quality_score"],
                "j_offset_ms": block["j_offset_ms"], "landmark_confidence": block["landmark_confidence"],
                "st_level_units": measure.get("st_level_units"), "t_amplitude_units": measure.get("t_amplitude_units"),
                "qrs_amplitude_units": measure.get("qrs_amplitude_units"),
            })
        st_refs = _rolling_reference(points, "st_level_units", radius)
        t_refs = _rolling_reference(points, "t_amplitude_units", radius)
        qrs_refs = _rolling_reference(points, "qrs_amplitude_units", radius)
        for point, st_ref, t_ref, qrs_ref in zip(points, st_refs, t_refs, qrs_refs):
            point["reference_units"], point["t_reference_units"] = st_ref, t_ref
            point["deviation_units"] = round(point["st_level_units"] - st_ref, 2) if point["st_level_units"] is not None and st_ref is not None else None
            qrs_change = abs(point["qrs_amplitude_units"] - qrs_ref) / max(abs(qrs_ref), 1.0) if point["qrs_amplitude_units"] is not None and qrs_ref is not None else None
            point["qrs_change_fraction"] = round(qrs_change, 3) if qrs_change is not None else None
            point["axis_shift_suspected"] = bool(qrs_change is not None and qrs_change >= settings["axis_shift_qrs_fraction"])
        episodes.extend(_lead_episodes(points, lead, settings)); episodes.extend(_t_episodes(points, lead, settings))
        stride = max(1, math.ceil(len(points) / settings["maximum_trend_points_per_lead"]))
        lead_points[lead] = [
            {"time_s": point["time_s"], "deviation_units": point["deviation_units"],
             "eligible": point["eligible"], "quality_score": point["quality_score"],
             "axis_shift_suspected": point["axis_shift_suspected"]}
            for point in points[::stride]
        ]

    candidates = _merge_episodes(episodes)
    eligible_blocks = sum(block["eligible"] for block in blocks)
    result = {
        "algorithm_version": ALGORITHM_VERSION, "analysis_revision": analysis_revision, "status": "completed",
        "sample_rate_hz": SAMPLE_RATE, "units": "source_device_units", "unit_label": "设备原始单位",
        "calibration_status": "unverified", "parameters": copy.deepcopy(settings),
        "quality": {"total_blocks": len(blocks), "eligible_blocks": eligible_blocks,
                    "coverage_pct": round(eligible_blocks * 100 / max(1, len(blocks)), 1),
                    "analyzed_duration_s": round(min(duration, len(blocks) * settings["block_seconds"]), 1),
                    "excluded_blocks": len(blocks) - eligible_blocks,
                    "gate": "normal-beat density + baseline stability + QRS stability + landmark confidence"},
        "summary": {"candidate_count": len(candidates),
                    "st_depression_count": sum(item["kind"] == "st_depression" for item in candidates),
                    "st_elevation_count": sum(item["kind"] == "st_elevation" for item in candidates),
                    "t_wave_count": sum(item["kind"] == "t_wave_inversion" for item in candidates)},
        "candidates": candidates, "trends": {"block_seconds": settings["block_seconds"], "leads": lead_points},
    }
    _CACHE[cache_key] = copy.deepcopy(result); _CACHE.move_to_end(cache_key)
    while len(_CACHE) > _CACHE_LIMIT:
        _CACHE.popitem(last=False)
    return result


def build_stt_review(conclusion: str, waveform_path=None, records=None, duration_s=None, *, analysis_revision=None, config=None) -> dict:
    """Build the ST-T workbench contract with optional automatic analysis."""
    analysis = None
    if waveform_path is not None and records is not None:
        analysis = analyze_stt(waveform_path, records, duration_s, analysis_revision=analysis_revision, config=config)
    automatic = {
        "enabled": analysis is not None, "algorithm_version": ALGORITHM_VERSION,
        "role": "screening_candidates_only", "review_status": "pending_physician_review",
        "items": analysis["candidates"] if analysis else [],
        "summary": analysis["summary"] if analysis else {"candidate_count": 0, "st_depression_count": 0, "st_elevation_count": 0, "t_wave_count": 0},
        "quality": analysis["quality"] if analysis else None,
        "reason_code": None if analysis else "waveform_not_supplied",
        "reasons": [] if analysis else ["未向筛查引擎提供原始波形与心搏定位数据"],
    }
    return {
        "schema_version": "stt-screening-review-v2",
        "review_mode": "automatic_screening_with_physician_review" if analysis else "manual_review_only",
        "manual_review_only": analysis is None, "calibration_unverified": True,
        "measurement_protocol": {
            "default_measurement": "J+60 ms", "default_landmark": "ST60",
            "baseline": {"preferred": "PR_segment", "implemented_surrogate": "pre-QRS stable baseline (-200 to -120 ms)",
                         "fallback": "individual_stable_baseline", "label": "PR 段优先 / QRS 前稳定基线替代",
                         "requires_manual_confirmation": True,
                         "note": "医师需核对 P/QRS/T 分界、体位变化、伪差、传导异常及心率变化。"},
            "landmarks": [
                {"code": "J", "offset_from_j_ms": 0, "label": "J 点", "purpose": "多导联导数能量估计 QRS 终点，需人工确认"},
                {"code": "ST60", "offset_from_j_ms": 60, "label": "J+60 ms", "purpose": "默认 ST 筛查点"},
                {"code": "ST80", "offset_from_j_ms": 80, "label": "J+80 ms", "purpose": "人工备选复核点"},
            ],
            "case_amplitude_output": {"enabled": analysis is not None, "unit": "source_device_units", "mV_conversion_enabled": False,
                                      "reason": "仅显示设备原始尺度相对值；计量溯源前禁止解释为临床 mV 阈值。"},
        },
        "lead_system": {"status": "mapping_from_source_channels_unverified", "mapping_verified": False,
                        "electrode_placement_verified": False,
                        "message": "12 导联由 8 个源通道按现有映射派生；电极位置与导联映射尚需独立核验。"},
        "calibration": {"status": "unverified", "voltage_gain_verified": False, "filter_response_verified_for_st": False,
                        "analysis_filter": "raw source samples; block median; no 0.5 Hz display high-pass",
                        "message": "已开启自动筛查候选；幅值仅以设备原始单位表示，不直接换算 mV。"},
        "automatic_candidates": automatic, "analysis": analysis,
        "reference_thresholds": {
            "enabled": analysis is not None, "reference_only": True, "applied_as_research_screen": analysis is not None,
            "applied_to_case": analysis is not None,
            "title": "动态 ST-T 研究筛查协议（非诊断阈值）",
            "st_change": {"entry_units": DEFAULT_CONFIG["entry_threshold_units"],
                          "target_units": DEFAULT_CONFIG["target_threshold_units"], "measurement_landmark": "ST60",
                          "minimum_target_duration_s": DEFAULT_CONFIG["minimum_target_duration_s"],
                          "exit_confirmation_s": DEFAULT_CONFIG["exit_confirmation_s"]},
            "warning": "阈值应用于未溯源的设备原始尺度，只用于排列复核优先级，不得自动生成诊断。",
        },
        "source_report": extract_stt_source_report(conclusion),
        "clinical_safety": {"diagnosis_generated": False, "automatic_interpretation_generated": analysis is not None,
                            "requires_physician_review": True, "acute_care_rule_out_supported": False,
                            "statement": "软件仅生成 ST-T 自动筛查候选，医师必须回看原始波形、修正或排除后才可进入报告。"},
    }
