"""Generate strict regression scopes using the unchanged frozen legacy generator.

No patient inputs, waveform tiling, padding or EBI rewriting are used. Destinations
must be new. Each of ten independent profiles is rendered across all 24 hours.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generator", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--short-data", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Regression destination must be new; existing files are preserved")
    generator_path = args.generator.resolve()
    spec = importlib.util.spec_from_file_location("frozen_regression_generator", generator_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    original_write = module._write_waveform
    generation_started = time.perf_counter()
    case_timings = []
    def write_with_progress(path, profile, samples):
        before = time.perf_counter()
        print("WHOLEDAY_GENERATE_START=" + profile.case_id, flush=True)
        original_write(path, profile, samples)
        elapsed = time.perf_counter() - before
        case_timings.append({"case_id": profile.case_id, "seconds": elapsed})
        print("WHOLEDAY_GENERATE_FINISH=" + json.dumps(case_timings[-1]), flush=True)
    module._write_waveform = write_with_progress
    summaries = module.generate_dataset(args.output, duration_minutes=1440, case_count=10, seed=20260812)
    assert len(summaries) == 10
    files = []
    for case in summaries:
        assert case["duration_seconds"] == 86400
        assert case["data_bytes"] == 276480000
        assert case["beat_count"] > 70000
        folder = args.output / case["case_id"]
        owned = sorted(p for p in folder.rglob("*") if p.is_file())
        assert len(owned) == 3
        for path in owned:
            files.append({"path": path.relative_to(args.output).as_posix(),
                          "size_bytes": path.stat().st_size, "sha256": digest(path)})
    short_files = []
    short_ids = {case["case_id"] for case in summaries}
    assert {p.name for p in args.short_data.iterdir() if p.is_dir()} == short_ids
    for case_id in sorted(short_ids):
        owned = sorted(p for p in (args.short_data / case_id).rglob("*") if p.is_file())
        assert len(owned) == 3
        raw = args.short_data / case_id / "data" / (case_id + ".DATA")
        assert raw.stat().st_size == 5760000
        for path in owned:
            short_files.append({"path": path.relative_to(args.short_data).as_posix(),
                                "size_bytes": path.stat().st_size, "sha256": digest(path)})
    receipt = {"schema_version": 1, "wholly_synthetic": True, "patient_inputs_read": False,
               "clinical_ground_truth": False, "generator_sha256": digest(generator_path),
               "seed": 20260812, "case_count": 10, "duration_seconds_per_case": 86400,
               "total_raw_bytes": sum(c["data_bytes"] for c in summaries),
               "generation_seconds": time.perf_counter() - generation_started,
               "case_timings": case_timings, "profiles": summaries, "files": files,
               "short_input": {"duration_seconds_per_case": 1800, "case_count": 10, "files": short_files},
               "method": "Unmodified frozen legacy generator; independent full-length profiles; "
                         "same read-only input files reused by baseline and candidate."}
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("WHOLEDAY_INPUT_RECEIPT_JSON=" + json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()
