#!/usr/bin/env python3
"""Create one continuous mathematical 24-hour ECG exercise, without patient inputs.

The default output is a CaseRepository root (for example Sources/M01), not
another M01 directory inside it. DATA is generated at every original 200 Hz
sample; no recording or short clip is read, repeated, or concatenated.
Synthetic EBI groups and events are construction references, not diagnoses.
"""
from __future__ import annotations

import argparse
from bisect import bisect_left
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import random
import sys
import xml.etree.ElementTree as ET

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.generate_synthetic_demo import (  # noqa: E402
    EBI_HEADER_SIZE, EBI_RECORD, TEMPLATES, TEMPLATE_START, TEMPLATE_END,
)

SOURCE_ID = "M01"
CASE_ID = "9900000000000001"
SAMPLE_RATE = 200
CHANNEL_COUNT = 8
STORED_CHANNELS = ("I", "II", "V1", "V2", "V3", "V4", "V5", "V6")
FULL_SECONDS = 86400
FULL_SAMPLES = 17280000
FULL_RAW_BYTES = 276480000
DEFAULT_SEED = 20261013
GENERATOR_VERSION = "continuous-doctor-exercise-v1"
CHUNK_SAMPLES = SAMPLE_RATE * 60

# Reuse the established mathematical beat shapes, never any recorded input.
_BEAT_TEMPLATES = {
    group: np.asarray(TEMPLATES[group], dtype=np.float64).T
    for group in (1, 2, 3, 34)
}
_OFFSETS_S = np.arange(TEMPLATE_START, TEMPLATE_END, dtype=np.float64) / SAMPLE_RATE
_P_SHAPE = 82 * np.exp(-0.5 * ((_OFFSETS_S + 0.18) / 0.035) ** 2)
_SCALES = np.asarray((0.68, 1.0, -0.48, -0.12, 0.36, 0.96, 0.82, 0.62))
# Group 8 deliberately means unclassified, not an automatic AF diagnosis.
_BEAT_TEMPLATES[8] = _BEAT_TEMPLATES[1] - _P_SHAPE[:, None] * _SCALES[None, :]
_ST_RISE = np.clip((_OFFSETS_S - 0.060) / 0.020, 0, 1)
_ST_FALL = np.clip((0.210 - _OFFSETS_S) / 0.030, 0, 1)
_ST_SHAPE = (0.5 - 0.5 * np.cos(np.pi * _ST_RISE)) * (
    0.5 - 0.5 * np.cos(np.pi * _ST_FALL)
)


@dataclass(frozen=True)
class SyntheticBeat:
    sample_index: int
    rr_ms: int
    group: int
    amplitude: float


@dataclass(frozen=True)
class SyntheticEvent:
    id: str
    kind: str
    start_sample: int
    end_sample: int
    label: str
    parameters: dict

    def as_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind,
            "start_sample": self.start_sample, "end_sample": self.end_sample,
            "start_s": self.start_sample / SAMPLE_RATE,
            "end_s": self.end_sample / SAMPLE_RATE,
            "duration_s": (self.end_sample - self.start_sample) / SAMPLE_RATE,
            "label": self.label, "reference_only": True,
            "parameters": self.parameters,
        }


@dataclass(frozen=True)
class ContinuousRecord:
    seed: int
    total_samples: int
    phase: float
    beats: tuple[SyntheticBeat, ...]
    positions: tuple[int, ...]
    events: tuple[SyntheticEvent, ...]

    @property
    def duration_seconds(self) -> float:
        return self.total_samples / SAMPLE_RATE


def _event_schedule(total_samples: int) -> tuple[SyntheticEvent, ...]:
    """Absolute 24-hour timeline; short test recordings truncate it, never scale it."""
    specs = (
        ("s-run", "s_burst", 4500, 4590, "窄QRS提前搏动/短阵练习",
         {"source_group": 2, "pattern": "three S construction labels per eleven beats"}),
        ("v-run", "v_burst", 19800, 19870, "宽QRS提前搏动/短阵练习",
         {"source_group": 3, "pattern": "three V construction labels per eight beats"}),
        ("st-down", "st_offset", 27000, 27240, "持续ST负偏移练习",
         {"offsets_device_units": {"II": -180, "V4": -180, "V5": -180, "V6": -180},
          "template_offset_seconds": [0.060, 0.210], "plateau_offset_seconds": [0.080, 0.180],
          "ramp_seconds": 10, "unit": "device_unit", "voltage_calibrated": False}),
        ("st-up", "st_offset", 37800, 38100, "持续ST正偏移练习",
         {"offsets_device_units": {"V2": 160, "V3": 160, "V4": 160},
          "template_offset_seconds": [0.060, 0.210], "plateau_offset_seconds": [0.080, 0.180],
          "ramp_seconds": 10, "unit": "device_unit", "voltage_calibrated": False}),
        ("irregular", "af_like", 43200, 44400, "无P波/不规则RR的房颤样标注练习",
         {"source_group": 8, "p_wave_omitted": True, "rr_multiplier_range": [0.52, 1.45],
          "diagnosis": None, "review_required": True}),
        ("motion", "artifact", 55800, 55920, "运动/肌电伪差练习",
         {"source_group": 34, "muscle_amplitude_device_units": 360,
          "wander_amplitude_device_units": 250}),
        ("dropout", "gap", 68400, 68412, "零填充缺失信号练习",
         {"source_group": 34, "fill": "zero_all_eight_channels",
          "ebi_markers": "nonbeat group 34 at underlying synthetic beat instants",
          "physiological_beat_labels_available": False}),
    )
    result = []
    for identifier, kind, a, b, label, parameters in specs:
        start = a * SAMPLE_RATE
        end = min(b * SAMPLE_RATE, total_samples)
        if start < end:
            result.append(SyntheticEvent(identifier, kind, start, end, label, parameters))
    return tuple(result)


def _active(events: tuple[SyntheticEvent, ...], sample: int, kind: str) -> SyntheticEvent | None:
    return next((e for e in events if e.kind == kind and e.start_sample <= sample < e.end_sample), None)


def _base_hr(time_s: float) -> float:
    # Recording clock starts 08:00; peak at 14:00, trough at 02:00.
    rate = 68 + 15 * math.cos(2 * math.pi * (time_s - 21600) / FULL_SECONDS)
    for center, width, height in ((3600, 600, 25), (21600, 800, 28), (36000, 500, 20)):
        rate += height * math.exp(-0.5 * ((time_s - center) / width) ** 2)
    return rate


def build_record(duration_seconds: float = FULL_SECONDS, *, seed: int = DEFAULT_SEED) -> ContinuousRecord:
    """Build lightweight beat/event metadata; waveform samples remain streamed."""
    if isinstance(duration_seconds, bool):
        raise ValueError("duration_seconds must be finite and between 6 and 86400")
    try:
        seconds = float(duration_seconds)
    except (TypeError, ValueError) as exc:
        raise ValueError("duration_seconds must be a number") from exc
    if not math.isfinite(seconds) or not 6 <= seconds <= FULL_SECONDS:
        raise ValueError("duration_seconds must be finite and between 6 and 86400")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    total = round(seconds * SAMPLE_RATE)
    events = _event_schedule(total)
    rng = random.Random(seed)
    phase = rng.uniform(0, 2 * math.pi)
    beats = []
    sample, previous, drift = SAMPLE_RATE // 2, None, 0.0
    s_counter = v_counter = 0
    while sample < total:
        time_s = sample / SAMPLE_RATE
        group = 1
        if _active(events, sample, "gap") or _active(events, sample, "artifact"):
            group = 34
        elif _active(events, sample, "af_like"):
            group = 8
        elif _active(events, sample, "s_burst"):
            group = 2 if s_counter % 11 < 3 else 1
            s_counter += 1
        elif _active(events, sample, "v_burst"):
            group = 3 if v_counter % 8 < 3 else 1
            v_counter += 1
        rr_ms = 0 if previous is None else (sample - previous) * 5
        amplitude = 1 + 0.027 * math.sin(time_s / 379 + phase)
        amplitude += rng.uniform(-0.016, 0.016)
        beats.append(SyntheticBeat(sample, rr_ms, group, amplitude))
        previous = sample
        drift = 0.85 * drift + rng.gauss(0, 0.007)
        modulation = 1 + 0.045 * math.sin(2 * math.pi * 0.23 * time_s + phase)
        modulation += 0.028 * math.sin(2 * math.pi * 0.075 * time_s + phase / 2) + drift
        next_rr = 60000 / _base_hr(time_s) * modulation
        if group == 8:
            next_rr *= rng.uniform(0.52, 1.45)
        elif group == 2:
            next_rr *= 0.72
        elif group == 3:
            next_rr *= 0.63
        elif len(beats) > 1 and beats[-2].group == 3:
            next_rr *= 1.36
        sample += max(56, min(400, round(next_rr / 5)))
    frozen = tuple(beats)
    return ContinuousRecord(seed, total, phase, frozen, tuple(b.sample_index for b in frozen), events)


def _event_envelope(event: SyntheticEvent, sample: int) -> float:
    ramp = event.parameters.get("ramp_seconds", 0) * SAMPLE_RATE
    if not ramp:
        return 1.0
    factor = min(1.0, (sample - event.start_sample) / ramp, (event.end_sample - sample) / ramp)
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, factor))


def render_chunk(record: ContinuousRecord, start_sample: int, end_sample: int) -> np.ndarray:
    """Render any original-sample interval; boundaries and call order do not alter it."""
    if (type(start_sample) is not int or type(end_sample) is not int
            or not 0 <= start_sample < end_sample <= record.total_samples):
        raise ValueError("render interval must be inside the record")
    samples = np.arange(start_sample, end_sample, dtype=np.float64)
    time_s = samples / SAMPLE_RATE
    baseline = 18 * np.sin(2 * np.pi * 0.173 * time_s + record.phase)
    baseline += 4 * np.sin(2 * np.pi * 47.031 * time_s + record.phase / 3)
    baseline += 3 * np.sin(2 * np.pi * 6.719 * time_s + 0.0000013 * time_s ** 2)
    values = np.empty((end_sample - start_sample, CHANNEL_COUNT), dtype=np.float64)
    for channel in range(CHANNEL_COUNT):
        values[:, channel] = baseline * (0.72 + channel * 0.035)
        values[:, channel] += 3 * np.sin(
            2 * np.pi * (0.071 + channel * 0.00817) * time_s + channel + record.phase
        )

    first = bisect_left(record.positions, start_sample - TEMPLATE_END + 1)
    last = bisect_left(record.positions, end_sample - TEMPLATE_START)
    for beat in record.beats[first:last]:
        # Group-34 gap markers have no physiological waveform.
        if _active(record.events, beat.sample_index, "gap"):
            continue
        a = max(start_sample, beat.sample_index + TEMPLATE_START)
        b = min(end_sample, beat.sample_index + TEMPLATE_END)
        if a >= b:
            continue
        ta = a - beat.sample_index - TEMPLATE_START
        tb = b - beat.sample_index - TEMPLATE_START
        values[a - start_sample:b - start_sample] += _BEAT_TEMPLATES[beat.group][ta:tb] * beat.amplitude
        event = _active(record.events, beat.sample_index, "st_offset")
        if event:
            offsets = np.asarray([event.parameters["offsets_device_units"].get(lead, 0)
                                  for lead in STORED_CHANNELS])
            values[a - start_sample:b - start_sample] += (
                _ST_SHAPE[ta:tb, None] * offsets[None, :] * _event_envelope(event, beat.sample_index)
            )

    for event in record.events:
        a, b = max(start_sample, event.start_sample), min(end_sample, event.end_sample)
        if a >= b:
            continue
        if event.kind == "artifact":
            local_t = time_s[a - start_sample:b - start_sample]
            for channel in range(CHANNEL_COUNT):
                values[a - start_sample:b - start_sample, channel] += (
                    360 * np.sin(2 * np.pi * (17.13 + channel * 0.15) * local_t
                                 + 0.00012 * local_t ** 2)
                    + 110 * np.sin(2 * np.pi * (37.91 + channel * 0.071) * local_t + record.phase)
                    + 250 * np.sin(2 * np.pi * 0.32 * local_t + channel * 0.2)
                )
        elif event.kind == "gap":
            values[a - start_sample:b - start_sample] = 0
    return np.clip(np.rint(values), -32768, 32767).astype("<i2")


def _write_waveform(path: Path, record: ContinuousRecord) -> dict:
    digest = hashlib.sha256()
    minimum, maximum = 32767, -32768
    temp = path.with_name("." + path.name + ".tmp")
    with temp.open("xb") as stream:
        for a in range(0, record.total_samples, CHUNK_SAMPLES):
            block = render_chunk(record, a, min(a + CHUNK_SAMPLES, record.total_samples))
            minimum, maximum = min(minimum, int(block.min())), max(maximum, int(block.max()))
            raw = block.tobytes(order="C")
            digest.update(raw)
            stream.write(raw)
    os.replace(temp, path)
    return {"sha256": digest.hexdigest(), "minimum": minimum, "maximum": maximum}


def _write_ebi(path: Path, record: ContinuousRecord) -> None:
    with path.open("xb") as stream:
        stream.write(b"SYNTHETIC_DOCTOR_24H_V1".ljust(EBI_HEADER_SIZE, b"\0"))
        for index, beat in enumerate(record.beats):
            stream.write(EBI_RECORD.pack(beat.sample_index, 0, beat.group, 0, index, 0, beat.rr_ms))


def _write_lps(path: Path, record: ContinuousRecord) -> None:
    root = ET.Element("LrScriptPage")
    shapes = ET.SubElement(root, "ShapeList")
    minutes = round(record.duration_seconds / 60)
    hours, rest = divmod(minutes, 60)
    valid = [b for b in record.beats if b.group != 34]
    rr = [b.rr_ms for b in valid if b.rr_ms > 0]
    lines = [
        "姓名：合成练习M01",
        # No patient ID, sex, age, bed, hospital, physician or clinical diagnosis.
        "记录时间：2026-01-01 08:00:00",
        f"记录时长：{hours}小时{rest}分钟",
        "数据属性：纯数学合成；全部源标注为练习参考，未作临床验证",
        f"总心搏数：{len(valid)}",
        f"室性心搏：{sum(b.group == 3 for b in record.beats)}",
        f"室上性心搏：{sum(b.group == 2 for b in record.beats)}",
        f"最慢心率：{round(60000 / max(rr)) if rr else 0}",
        f"平均心率：{round(len(valid) * 60 / record.duration_seconds)}",
        f"最快心率：{round(60000 / min(rr)) if rr else 0}",
        f"最长RR间期：{max(rr, default=0) / 1000}s",
    ]
    for index, text in enumerate(lines):
        node = ET.SubElement(shapes, "PShape", {"SPTYPE": "3", "CRECT": f"100,{100+index*80},2200,{160+index*80}"})
        node.text = text
    for y, text in (
        (2050, "报告结论"),
        (2140, "纯数学合成连续记录，仅用于医师操作练习，不对应真实人员，不用于医疗诊断。"),
        (2220, "S/V/未知/噪声组为生成器指定参考标签，房颤样与ST偏移场景需人工复核，不是自动诊断。"),
        (2300, "幅值为任意设备单位，电压与导联映射未作设备验证；统计不构成临床金标准。"),
    ):
        ET.SubElement(shapes, "PShape", {"SPTYPE": "3", "CRECT": f"100,{y},2200,{y+60}"}).text = text
    ET.ElementTree(root).write(path, encoding="utf-16", xml_declaration=True)


def _json_file(path: Path, payload: dict) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n")


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def generate_dataset(output: str | os.PathLike[str], *, duration_minutes: float = 1440,
                     seed: int = DEFAULT_SEED) -> dict:
    """Create a new root and return its reproducible source manifest.

    Existing destinations (including empty directories) are refused. This
    prevents accidental replacement or inclusion of pre-existing case files.
    Short durations are developer fixtures; the doctor package uses 1440 only.
    """
    if isinstance(duration_minutes, bool):
        raise ValueError("duration_minutes must be a number")
    try:
        seconds = float(duration_minutes) * 60
    except (TypeError, ValueError) as exc:
        raise ValueError("duration_minutes must be a number") from exc
    record = build_record(seconds, seed=seed)
    root = Path(output).expanduser()
    if root.is_symlink() or root.exists():
        raise ValueError("output must be a new directory; existing sources are never overwritten")
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    case = root / CASE_ID
    for folder in ("data", "DGS", "report_image"):
        (case / folder).mkdir(parents=True, exist_ok=False)
    data = case / "data" / f"{CASE_ID}.DATA"
    ebi = case / "DGS" / f"{CASE_ID}.EBI"
    lps = case / "report_image" / f"{CASE_ID}_1.LPS"
    wave_summary = _write_waveform(data, record)
    _write_ebi(ebi, record)
    _write_lps(lps, record)
    events = {
        "schema_version": 1, "kind": "mathematical_reference_events",
        "clinical_ground_truth": False, "automatic_diagnoses": False,
        "interval_semantics": "half_open_samples",
        "events": [event.as_dict() for event in record.events],
    }
    events_path = root / "events.json"
    _json_file(events_path, events)
    files = []
    for path in sorted((data, ebi, lps, events_path), key=lambda p: p.relative_to(root).as_posix()):
        files.append({"path": path.relative_to(root).as_posix(), "size_bytes": path.stat().st_size,
                      "sha256": wave_summary["sha256"] if path == data else _hash_file(path)})
    dataset_hash = hashlib.sha256()
    for item in files:
        dataset_hash.update(item["path"].encode("utf-8"))
        dataset_hash.update(item["sha256"].encode("ascii"))
    manifest = {
        "schema_version": 1, "source_id": SOURCE_ID, "case_id": CASE_ID,
        "profile": "cardioinsight-doctor-eval-synthetic-24h-v1",
        "source_version": "M01-24h-v1" if record.total_samples == FULL_SAMPLES else "M01-test-v1",
        "kind": "mathematical_synthetic", "wholly_synthetic": True,
        "patient_inputs_read": False, "clinical_ground_truth": False, "automatic_diagnoses": False,
        "generator": GENERATOR_VERSION, "generator_script": "scripts/generate_doctor_24h.py",
        "generator_source_sha256": _hash_file(Path(__file__)),
        "seed": seed, "duration_seconds": record.duration_seconds,
        "sampling_rate_hz": SAMPLE_RATE, "stored_channels": list(STORED_CHANNELS),
        "channel_count": CHANNEL_COUNT, "sample_format": "little-endian int16",
        "sample_layout": "sample-major interleaved I,II,V1,V2,V3,V4,V5,V6",
        "sample_count": record.total_samples,
        "expected_raw_bytes": record.total_samples * CHANNEL_COUNT * 2,
        "full_24h_fixture": record.total_samples == FULL_SAMPLES,
        "start_time": "2026-01-01T08:00:00",
        "raw_range": {"minimum": wave_summary["minimum"], "maximum": wave_summary["maximum"]},
        "beat_count": len(record.beats),
        "source_group_counts": {str(group): sum(b.group == group for b in record.beats)
                                for group in (1, 2, 3, 8, 34)},
        "derived_leads": {"III": "II-I", "aVR": "-(I+II)/2", "aVL": "I-II/2", "aVF": "II-I/2"},
        "known_unit_unvalidated": {"units": "device_unit", "voltage_calibrated": False,
                                  "device_verified": False, "electrode_placement_verified": False,
                                  "clinical_labels_validated": False},
        "continuity": {"construction": "absolute-sample waveform + seeded evolving RR and beat amplitude",
                       "recorded_inputs": 0, "repeated_short_clips": False, "downsampled": False,
                       "chunk_samples": CHUNK_SAMPLES, "chunk_boundaries_reset_state": False},
        "formats": {"data": "headerless signed int16 little-endian; 8 interleaved channels",
                    "ebi": {"header_bytes": EBI_HEADER_SIZE, "record_struct": "<IHHIIII",
                            "record_bytes": EBI_RECORD.size,
                            "fields": ["sample_index", "reserved", "group", "reserved", "template_index", "reserved", "rr_ms"],
                            "groups": {"1": "N mathematical template", "2": "S mathematical template",
                                       "3": "V mathematical template", "8": "unclassified irregular no-P exercise",
                                       "34": "artifact/gap nonbeat reference"}},
                    "lps": "UTF-16 XML with PShape text; fictional exercise, no patient identifier",
                    "events": "events.json half-open sample intervals; mathematical references only"},
        "events": events["events"], "files": files, "dataset_sha256": dataset_hash.hexdigest(),
        "repeatability": {"scope": "same generator source and Python/NumPy numeric environment",
                          "python": ".".join(map(str, sys.version_info[:3])), "numpy": np.__version__},
    }
    _json_file(root / "source-manifest.json", manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成一例原采样率连续24小时纯数学合成医师练习数据。")
    parser.add_argument("--output", type=Path, required=True, help="新的病例根目录，例如 Sources/M01")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--duration-minutes", type=float, default=1440,
                        help="默认1440；短时长仅用于开发测试，场景保持原绝对时间")
    args = parser.parse_args(argv)
    try:
        result = generate_dataset(args.output, duration_minutes=args.duration_minutes, seed=args.seed)
    except (ValueError, OSError) as error:
        print(f"生成失败：{error}", file=sys.stderr)
        return 2
    print(json.dumps({"source_id": SOURCE_ID, "case_id": CASE_ID,
                      "duration_seconds": result["duration_seconds"],
                      "raw_bytes": result["expected_raw_bytes"],
                      "dataset_sha256": result["dataset_sha256"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
