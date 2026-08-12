#!/usr/bin/env python3
"""Publish one user-confirmed synthetic ECG case as a compact web excerpt."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from ecg_core.ebi import load_records  # noqa: E402
from ecg_core.lps_parser import parse_lps  # noqa: E402


DEFAULT_OUTPUT = PROJECT_ROOT / "static" / "demo-data" / "uploaded-sim-af-001"
SAMPLE_RATE = 200
CHANNEL_COUNT = 8
FRAME_BYTES = CHANNEL_COUNT * 2
GROUP_LABELS = {1: "N", 2: "S", 3: "V", 34: "噪声"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _segment_summary(records: list[tuple[int, ...]], duration_seconds: float) -> dict:
    valid = [record for record in records if record[2] != 34]
    rr = [record[6] for record in valid if 250 <= record[6] <= 5000]
    groups = Counter(record[2] for record in records)
    nn = [record[6] for record in records if record[2] == 1 and 300 <= record[6] <= 2000]
    diffs = [nn[index] - nn[index - 1] for index in range(1, len(nn))]
    return {
        "total_beats": len(valid),
        "avg_hr": round(60000 / statistics.mean(rr), 1) if rr else None,
        "min_hr": round(60000 / max(rr)) if rr else None,
        "max_hr": round(60000 / min(rr)) if rr else None,
        "ventricular_beats": groups[3],
        "supraventricular_beats": groups[2],
        "longest_rr_s": round(max(rr, default=0) / 1000, 3),
        "sdnn_ms": round(statistics.stdev(nn), 2) if len(nn) > 1 else None,
        "sdann_ms": None,
        "sdnn_index_ms": None,
        "rmssd_ms": round(math.sqrt(statistics.mean(value * value for value in diffs)), 2) if diffs else None,
        "pnn50_pct": round(sum(abs(value) > 50 for value in diffs) * 100 / len(diffs), 2) if diffs else None,
        "triangular_index": None,
        "segment_rate_from_count": round(len(valid) * 60 / max(duration_seconds, 1), 2),
        "group_counts": {str(key): value for key, value in sorted(groups.items())},
    }


def import_case(
    source_case: Path,
    output: Path,
    *,
    start_seconds: float,
    duration_seconds: float,
    candidate_start_seconds: float,
    candidate_end_seconds: float,
    confirmed_synthetic: bool,
) -> dict:
    if not confirmed_synthetic:
        raise ValueError("refusing export without --confirm-synthetic")
    source_case = source_case.expanduser().resolve()
    case_id = source_case.name
    data_path = source_case / "data" / f"{case_id}.DATA"
    ebi_path = source_case / "DGS" / f"{case_id}.EBI"
    lps_path = source_case / "report_image" / f"{case_id}_1.LPS"
    for path in (data_path, ebi_path, lps_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    start_sample = round(float(start_seconds) * SAMPLE_RATE)
    requested_samples = round(float(duration_seconds) * SAMPLE_RATE)
    total_samples = data_path.stat().st_size // FRAME_BYTES
    if start_sample < 0 or requested_samples <= 0 or start_sample + requested_samples > total_samples:
        raise ValueError("requested excerpt is outside the source waveform")
    end_sample = start_sample + requested_samples

    output = output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    waveform_path = output / "waveform.bin"
    with data_path.open("rb") as source:
        source.seek(start_sample * FRAME_BYTES)
        waveform = source.read(requested_samples * FRAME_BYTES)
    if len(waveform) != requested_samples * FRAME_BYTES:
        raise ValueError("source waveform ended before the requested excerpt")
    waveform_path.write_bytes(waveform)

    source_records = [
        record for record in load_records(str(ebi_path))
        if start_sample <= record[0] < end_sample
    ]
    rebased = [
        (record[0] - start_sample, *record[1:])
        for record in source_records
    ]
    candidate_start = max(0.0, candidate_start_seconds - start_seconds)
    candidate_end = min(duration_seconds, candidate_end_seconds - start_seconds)
    if not 0 <= candidate_start < candidate_end <= duration_seconds:
        raise ValueError("candidate window does not overlap the exported excerpt")

    beats = []
    candidate_seen = False
    for record in rebased:
        time_s = round(record[0] / SAMPLE_RATE, 3)
        in_candidate = candidate_start <= time_s < candidate_end
        beats.append({
            "sample_index": record[0],
            "time_s": time_s,
            "group": record[2],
            "label": GROUP_LABELS.get(record[2], "?"),
            "rr_ms": record[6],
            "hr": round(60000 / record[6], 1) if record[6] else None,
            "af_candidate": in_candidate,
            "af_onset": in_candidate and not candidate_seen,
        })
        candidate_seen = candidate_seen or in_candidate

    parsed = parse_lps(lps_path)
    metadata = dict(parsed["metadata"])
    source_diagnosis = metadata.get("clinical_diagnosis", "")
    original_start = datetime.fromisoformat(metadata["start_iso"])
    excerpt_start = original_start + timedelta(seconds=start_seconds)
    metadata.update({
        "start_time": excerpt_start.strftime("%Y-%m-%d %H:%M:%S"),
        "start_iso": excerpt_start.isoformat(),
        "duration_text": f"{duration_seconds / 60:g}分钟公开模拟片段",
        "source_record_duration_text": parsed["metadata"]["duration_text"],
        "source_clinical_diagnosis": source_diagnosis,
        "clinical_diagnosis": f"{source_diagnosis}（模拟源报告：阵发性心房颤动）",
        "data_classification": "用户确认：全部身份及心电内容均为模拟数据",
    })
    summary = _segment_summary(rebased, duration_seconds)
    waveform_sha256 = _sha256(waveform_path)
    payload = {
        "case_id": case_id,
        "metadata": metadata,
        "summary": summary,
        "source_report_summary": parsed["summary"],
        "conclusion": (
            "用户确认的模拟病例源报告摘要（对应完整模拟记录）：\n"
            f"{parsed['conclusion']}\n\n"
            f"当前在线版本直接使用该模拟病例从 {start_seconds / 3600:.2f} 小时起的 "
            f"{duration_seconds / 60:g} 分钟原始波形片段；候选节律仍须人工复核。"
        ),
        "technical": {
            "sample_rate_hz": SAMPLE_RATE,
            "independent_channels": CHANNEL_COUNT,
            "derived_leads": 12,
            "sample_format": "source excerpt · little-endian int16 · 8-channel interleaved",
            "units": "µV（源模拟数据标度，未建立计量学溯源）",
            "duration_seconds_raw": duration_seconds,
            "raw_size_bytes": waveform_path.stat().st_size,
            "report_pages": 0,
        },
        "integrity": {
            "manifest_available": True,
            "algorithm": "SHA-256",
            "file_count": 2,
            "case_sha256": waveform_sha256,
            "waveform_sha256": waveform_sha256,
            "source_data_sha256": _sha256(data_path),
            "source_ebi_sha256": _sha256(ebi_path),
            "source_version_warning": False,
            "raw_patient_data": False,
            "user_confirmed_synthetic": True,
        },
        "simulation_profile": {
            "kind": "uploaded-user-confirmed-synthetic-excerpt",
            "source_waveform_copied": True,
            "source_case_id": case_id,
            "source_window_start_s": start_seconds,
            "source_window_end_s": start_seconds + duration_seconds,
            "rhythm_candidate_windows_s": [[round(candidate_start, 3), round(candidate_end, 3)]],
            "note": "身份、报告与波形均由用户确认属于模拟数据；在线版本是源 DATA 的直接裁剪。",
        },
        "beats": beats,
        "active": True,
        "phi_masked": False,
        "report_image_urls": [],
        "generated_report_url": "#uploaded-simulated-case",
    }
    case_script = output / "case-data.js"
    case_script.write_text(
        '"use strict";\nwindow.__CARDIOINSIGHT_UPLOADED_CASE__ = '
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )
    return {
        "case_id": case_id,
        "waveform": str(waveform_path),
        "waveform_bytes": waveform_path.stat().st_size,
        "beats": len(beats),
        "case_script": str(case_script),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_case", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--start-seconds", type=float, default=82380)
    parser.add_argument("--duration-seconds", type=float, default=600)
    parser.add_argument("--candidate-start-seconds", type=float, default=82860)
    parser.add_argument("--candidate-end-seconds", type=float, default=82980)
    parser.add_argument("--confirm-synthetic", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = import_case(
            args.source_case,
            args.output,
            start_seconds=args.start_seconds,
            duration_seconds=args.duration_seconds,
            candidate_start_seconds=args.candidate_start_seconds,
            candidate_end_seconds=args.candidate_end_seconds,
            confirmed_synthetic=args.confirm_synthetic,
        )
    except (OSError, ValueError) as exc:
        print(f"导入失败：{exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
