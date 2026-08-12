#!/usr/bin/env python3
"""Generate deterministic, wholly synthetic ECG demo cases.

The generator never reads an existing case or patient file.  It creates only
mathematical waveforms and fictional report text that match the minimum file
contract consumed by :class:`ecg_core.repository.CaseRepository`.
"""

from __future__ import annotations

import argparse
import math
import os
import random
import statistics
import struct
import sys
import xml.etree.ElementTree as ET
from array import array
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


SAMPLE_RATE = 200
CHANNEL_COUNT = 8
DEFAULT_CASE_COUNT = 10
DEFAULT_DURATION_MINUTES = 30.0
DEFAULT_OUTPUT = Path("demo_data")
DEFAULT_SEED = 20260812
DEMO_ID_PREFIX = "990000000000"
BASE_HEART_RATES = (52, 58, 64, 68, 72, 76, 82, 88, 96, 108)
EBI_HEADER_SIZE = 32
EBI_RECORD = struct.Struct("<IHHIIII")
CHANNEL_SCALES = (0.68, 1.0, -0.48, -0.12, 0.36, 0.96, 0.82, 0.62)
TEMPLATE_START = -70
TEMPLATE_END = 111
CHUNK_SECONDS = 10


@dataclass(frozen=True)
class Beat:
    sample_index: int
    rr_ms: int
    group: int


@dataclass(frozen=True)
class CaseProfile:
    case_number: int
    case_id: str
    base_hr: int
    phase: float
    beats: tuple[Beat, ...]


def demo_case_id(case_number: int) -> str:
    """Return a reserved, deterministic 16-digit demo identifier."""
    if not 1 <= case_number <= 9999:
        raise ValueError("case_number must be between 1 and 9999")
    return f"{DEMO_ID_PREFIX}{case_number:04d}"


def _beat_group(beat_number: int, case_number: int) -> int:
    """Assign sparse N/S/V/noise labels, including early demo events."""
    s_first = 4 + case_number % 2
    v_first = 7 + case_number % 3
    noise_first = 11 + case_number % 4
    if beat_number >= noise_first and (beat_number - noise_first) % (131 + case_number) == 0:
        return 34
    if beat_number >= v_first and (beat_number - v_first) % (83 + case_number) == 0:
        return 3
    if beat_number >= s_first and (beat_number - s_first) % (47 + case_number) == 0:
        return 2
    return 1


def _build_beats(
    total_samples: int,
    base_hr: int,
    case_number: int,
    phase: float,
) -> tuple[Beat, ...]:
    beats: list[Beat] = []
    sample_index = SAMPLE_RATE // 2
    previous_sample: int | None = None
    beat_number = 0
    long_rr_beat = 15 + case_number % 3

    while sample_index < total_samples:
        rr_ms = 0 if previous_sample is None else round(
            (sample_index - previous_sample) * 1000 / SAMPLE_RATE
        )
        beats.append(Beat(sample_index, rr_ms, _beat_group(beat_number, case_number)))
        previous_sample = sample_index
        beat_number += 1

        next_group = _beat_group(beat_number, case_number)
        modulation = 1 + 0.055 * math.sin(beat_number * 0.31 + phase)
        modulation += 0.025 * math.sin(beat_number * 0.071 + phase / 2)
        next_rr_ms = 60000 / base_hr * modulation
        if beat_number == long_rr_beat:
            next_rr_ms = 2600 + case_number * 35
        elif next_group == 2:
            next_rr_ms *= 0.74
        elif next_group == 3:
            next_rr_ms *= 0.78
        elif beats[-1].group == 3:
            next_rr_ms *= 1.22
        next_rr_ms = max(320, min(round(next_rr_ms / 5) * 5, 4500))
        sample_index += max(1, round(next_rr_ms * SAMPLE_RATE / 1000))

    return tuple(beats)


def _gaussian(value: float, center: float, width: float) -> float:
    return math.exp(-0.5 * ((value - center) / width) ** 2)


def _template_value(group: int, offset_seconds: float, channel: int) -> float:
    scale = CHANNEL_SCALES[channel]
    if group == 34:
        envelope = _gaussian(offset_seconds, 0.04, 0.12)
        artifact = 720 * math.sin(2 * math.pi * (16 + channel * 0.7) * offset_seconds)
        return artifact * envelope + 180 * scale * _gaussian(offset_seconds, 0, 0.025)

    if group == 3:
        qrs = 1120 * _gaussian(offset_seconds, 0.015, 0.045)
        qrs -= 820 * _gaussian(offset_seconds, 0.105, 0.065)
        t_wave = -260 * _gaussian(offset_seconds, 0.32, 0.095)
        return scale * (qrs + t_wave)

    p_scale = 0.72 if group == 2 else 1.0
    qrs_scale = 0.88 if group == 2 else 1.0
    waveform = p_scale * 82 * _gaussian(offset_seconds, -0.18, 0.035)
    waveform -= qrs_scale * 125 * _gaussian(offset_seconds, -0.035, 0.012)
    waveform += qrs_scale * 1120 * _gaussian(offset_seconds, 0.0, 0.012)
    waveform -= qrs_scale * 260 * _gaussian(offset_seconds, 0.038, 0.017)
    waveform += 285 * _gaussian(offset_seconds, 0.26, 0.075)
    return scale * waveform


def _build_templates() -> dict[int, tuple[tuple[int, ...], ...]]:
    templates: dict[int, tuple[tuple[int, ...], ...]] = {}
    for group in (1, 2, 3, 34):
        channels: list[tuple[int, ...]] = []
        for channel in range(CHANNEL_COUNT):
            channels.append(tuple(
                round(_template_value(group, offset / SAMPLE_RATE, channel))
                for offset in range(TEMPLATE_START, TEMPLATE_END)
            ))
        templates[group] = tuple(channels)
    return templates


TEMPLATES = _build_templates()


def _write_waveform(path: Path, profile: CaseProfile, total_samples: int) -> None:
    temp_path = path.with_name(f".{path.name}.tmp")
    beat_cursor = 0
    with temp_path.open("wb") as stream:
        for chunk_start in range(0, total_samples, SAMPLE_RATE * CHUNK_SECONDS):
            chunk_end = min(total_samples, chunk_start + SAMPLE_RATE * CHUNK_SECONDS)
            frame_count = chunk_end - chunk_start
            values = [0] * (frame_count * CHANNEL_COUNT)

            for local_index in range(frame_count):
                sample_index = chunk_start + local_index
                time_s = sample_index / SAMPLE_RATE
                baseline = 18 * math.sin(2 * math.pi * 0.18 * time_s + profile.phase)
                baseline += 4 * math.sin(2 * math.pi * 47 * time_s + profile.phase / 3)
                baseline += 3 * math.sin(2 * math.pi * 6.7 * time_s + profile.phase)
                frame_offset = local_index * CHANNEL_COUNT
                for channel in range(CHANNEL_COUNT):
                    channel_drift = 3 * math.sin(
                        2 * math.pi * (0.07 + channel * 0.009) * time_s + channel
                    )
                    values[frame_offset + channel] = round(
                        baseline * (0.72 + channel * 0.035) + channel_drift
                    )

            while (
                beat_cursor < len(profile.beats)
                and profile.beats[beat_cursor].sample_index + TEMPLATE_END <= chunk_start
            ):
                beat_cursor += 1
            index = beat_cursor
            while index < len(profile.beats):
                beat = profile.beats[index]
                if beat.sample_index + TEMPLATE_START >= chunk_end:
                    break
                template = TEMPLATES[beat.group]
                first_offset = max(TEMPLATE_START, chunk_start - beat.sample_index)
                last_offset = min(TEMPLATE_END, chunk_end - beat.sample_index)
                for offset in range(first_offset, last_offset):
                    local_index = beat.sample_index + offset - chunk_start
                    frame_offset = local_index * CHANNEL_COUNT
                    template_index = offset - TEMPLATE_START
                    for channel in range(CHANNEL_COUNT):
                        values[frame_offset + channel] += template[channel][template_index]
                index += 1

            samples = array("h", (max(-32768, min(32767, value)) for value in values))
            if sys.byteorder != "little":
                samples.byteswap()
            stream.write(samples.tobytes())
    os.replace(temp_path, path)


def _write_ebi(path: Path, beats: tuple[Beat, ...]) -> None:
    temp_path = path.with_name(f".{path.name}.tmp")
    header = b"SYNTHETIC_ECG_DEMO_V1"
    header = header.ljust(EBI_HEADER_SIZE, b"\0")
    with temp_path.open("wb") as stream:
        stream.write(header)
        for template_index, beat in enumerate(beats):
            stream.write(EBI_RECORD.pack(
                beat.sample_index,
                0,
                beat.group,
                0,
                template_index,
                0,
                beat.rr_ms,
            ))
    os.replace(temp_path, path)


def _duration_text(total_seconds: int) -> str:
    total_minutes = total_seconds // 60
    hours, minutes = divmod(total_minutes, 60)
    if hours:
        return f"{hours}小时{minutes}分钟"
    return f"{minutes}分钟"


def _statistics_for(beats: tuple[Beat, ...], total_seconds: int) -> dict[str, float | int]:
    valid = [beat for beat in beats if beat.group != 34]
    rr_values = [beat.rr_ms for beat in valid if beat.rr_ms > 0]
    heart_rates = [60000 / rr for rr in rr_values]
    nn = [beat.rr_ms for beat in beats if beat.group == 1 and 300 <= beat.rr_ms <= 2000]
    nn_diffs = [nn[index] - nn[index - 1] for index in range(1, len(nn))]
    return {
        "total_beats": len(valid),
        "s_beats": sum(beat.group == 2 for beat in beats),
        "v_beats": sum(beat.group == 3 for beat in beats),
        "noise_beats": sum(beat.group == 34 for beat in beats),
        "min_hr": round(min(heart_rates)) if heart_rates else 0,
        "avg_hr": round(len(valid) * 60 / max(total_seconds, 1)),
        "max_hr": round(max(heart_rates)) if heart_rates else 0,
        "longest_rr_s": round(max(rr_values, default=0) / 1000, 3),
        "tachy_beats": sum(hr >= 120 for hr in heart_rates),
        "brady_beats": sum(hr <= 50 for hr in heart_rates),
        "sdnn_ms": round(statistics.stdev(nn), 2) if len(nn) > 1 else 0.0,
        "rmssd_ms": round(
            math.sqrt(statistics.mean(value * value for value in nn_diffs)), 2
        ) if nn_diffs else 0.0,
        "pnn50_pct": round(
            sum(abs(value) > 50 for value in nn_diffs) * 100 / len(nn_diffs), 2
        ) if nn_diffs else 0.0,
    }


def _add_text(parent: ET.Element, text: str, y: int) -> None:
    node = ET.SubElement(
        parent,
        "PShape",
        {"SPTYPE": "3", "CRECT": f"100,{y},2200,{y + 60}"},
    )
    node.text = text


def _write_lps(
    path: Path,
    profile: CaseProfile,
    total_seconds: int,
    start_time: datetime,
) -> None:
    stats = _statistics_for(profile.beats, total_seconds)
    root = ET.Element("LrScriptPage")
    shapes = ET.SubElement(root, "ShapeList")
    report_lines = [
        f"姓名：演示病例{profile.case_number:02d}",
        f"ID号：{profile.case_id}",
        f"记录时间：{start_time:%Y-%m-%d %H:%M:%S}",
        f"记录时长：{_duration_text(total_seconds)}",
        "数据属性：纯数学合成演示数据",
        f"总心搏数：{stats['total_beats']}",
        f"室性心搏：{stats['v_beats']}",
        f"室上性心搏：{stats['s_beats']}",
        f"噪声标记：{stats['noise_beats']}",
        f"最慢心率：{stats['min_hr']}",
        f"平均心率：{stats['avg_hr']}",
        f"最快心率：{stats['max_hr']}",
        f"最长RR间期：{stats['longest_rr_s']}s",
        f"心动过速中的心搏总和：{stats['tachy_beats']}",
        f"心动过缓中的心搏总和：{stats['brady_beats']}",
        f"SDNN：{stats['sdnn_ms']} ms",
        f"rMSSD：{stats['rmssd_ms']} ms",
        f"pNN50：{stats['pnn50_pct']}%",
    ]
    for index, line in enumerate(report_lines):
        _add_text(shapes, line, 100 + index * 80)
    _add_text(shapes, "报告结论", 2050)
    _add_text(
        shapes,
        "本报告由纯数学合成信号生成，仅供软件功能演示；不对应任何真实人员，不用于医疗诊断。",
        2140,
    )

    temp_path = path.with_name(f".{path.name}.tmp")
    ET.ElementTree(root).write(temp_path, encoding="utf-16", xml_declaration=True)
    os.replace(temp_path, path)


def _prepare_case_directories(output_root: Path, case_id: str) -> tuple[Path, Path, Path]:
    """Create exact destinations without removing any existing directories."""
    resolved_root = output_root.resolve()
    case_dir = (resolved_root / case_id).resolve()
    if case_dir.parent != resolved_root:
        raise ValueError("generated case path escaped the output directory")
    report_image = case_dir / "report_image"
    data = case_dir / "data"
    dgs = case_dir / "DGS"
    for directory in (report_image, data, dgs):
        directory.mkdir(parents=True, exist_ok=True)
    return report_image, data, dgs


def generate_dataset(
    output: str | os.PathLike[str] = DEFAULT_OUTPUT,
    *,
    duration_minutes: float = DEFAULT_DURATION_MINUTES,
    case_count: int = DEFAULT_CASE_COUNT,
    seed: int = DEFAULT_SEED,
) -> list[dict[str, object]]:
    """Generate demo cases and return a compact build summary.

    Repeated runs overwrite only the three files owned by this generator in
    each reserved demo case directory.  Unrelated files and directories are
    never deleted.
    """
    try:
        duration_minutes = float(duration_minutes)
    except (TypeError, ValueError) as exc:
        raise ValueError("duration_minutes must be a number") from exc
    if not math.isfinite(duration_minutes) or not 0 < duration_minutes <= 1440:
        raise ValueError("duration_minutes must be greater than 0 and no more than 1440")
    if isinstance(case_count, bool) or not isinstance(case_count, int) or not 1 <= case_count <= 100:
        raise ValueError("case_count must be an integer between 1 and 100")

    output_root = Path(output).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    total_samples = max(1, round(duration_minutes * 60 * SAMPLE_RATE))
    total_seconds = round(total_samples / SAMPLE_RATE)
    rng = random.Random(seed)
    summaries: list[dict[str, object]] = []

    for case_number in range(1, case_count + 1):
        case_id = demo_case_id(case_number)
        base_hr = BASE_HEART_RATES[(case_number - 1) % len(BASE_HEART_RATES)]
        phase = rng.uniform(0, 2 * math.pi)
        beats = _build_beats(total_samples, base_hr, case_number, phase)
        profile = CaseProfile(case_number, case_id, base_hr, phase, beats)
        report_image, data, dgs = _prepare_case_directories(output_root, case_id)
        data_path = data / f"{case_id}.DATA"
        ebi_path = dgs / f"{case_id}.EBI"
        lps_path = report_image / f"{case_id}_1.LPS"

        _write_waveform(data_path, profile, total_samples)
        _write_ebi(ebi_path, beats)
        _write_lps(
            lps_path,
            profile,
            total_seconds,
            datetime(2026, 1, 1, 8, 0) + timedelta(days=case_number - 1),
        )
        summaries.append({
            "case_id": case_id,
            "name": f"演示病例{case_number:02d}",
            "base_hr": base_hr,
            "duration_seconds": total_samples / SAMPLE_RATE,
            "beat_count": len(beats),
            "data_bytes": data_path.stat().st_size,
        })
    return summaries


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="生成完全由数学信号构造的心电软件演示数据（不读取真实病例）。"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="输出数据根目录（默认：demo_data）",
    )
    parser.add_argument(
        "--duration-minutes",
        type=float,
        default=DEFAULT_DURATION_MINUTES,
        help="每例时长，分钟（默认：30）",
    )
    parser.add_argument(
        "--cases",
        type=int,
        default=DEFAULT_CASE_COUNT,
        help="演示病例数（默认：10）",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help="可复现生成种子",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        summaries = generate_dataset(
            args.output,
            duration_minutes=args.duration_minutes,
            case_count=args.cases,
            seed=args.seed,
        )
    except (OSError, ValueError) as exc:
        print(f"生成失败：{exc}", file=sys.stderr)
        return 2
    total_bytes = sum(int(item["data_bytes"]) for item in summaries)
    print(
        f"已生成 {len(summaries)} 例纯合成演示数据："
        f"{Path(args.output).expanduser().resolve()}"
    )
    print(f"每例 {args.duration_minutes:g} 分钟，DATA 合计 {total_bytes / 1024 / 1024:.1f} MiB。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
