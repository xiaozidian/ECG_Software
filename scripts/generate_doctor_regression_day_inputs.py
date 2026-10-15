"""Generate strict regression scopes with corrected fictional NN references.

No patient inputs, waveform tiling, padding or EBI rewriting are used. Destinations
must be new. The frozen waveform/beat engine is preserved, while only fictional
LPS SDNN/rMSSD/pNN50 references use adjacent NN. Equivalence is verified first.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
import tempfile
import xml.etree.ElementTree as ET


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def load_generator(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def verify_reference_equivalence(current, frozen, current_path, frozen_path, parent):
    old_ast, new_ast = (ast.parse(path.read_text(encoding="utf-8"))
                        for path in (frozen_path, current_path))
    for tree in (old_ast, new_ast):
        tree.body = [node for node in tree.body if not
                     (isinstance(node, ast.FunctionDef) and node.name == "_statistics_for")]
    assert ast.dump(old_ast) == ast.dump(new_ast), "Waveform/beat engine changed"
    proof = []
    allowed = ("SDNN：", "rMSSD：", "pNN50：")
    def canonical_report(path):
        tree = ET.parse(path)
        for node in tree.iter():
            if (node.text or "").startswith(allowed):
                node.text = "<adjacent-NN-reference>"
        return ET.tostring(tree.getroot(), encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="synthetic-reference-proof-", dir=parent) as scratch:
        roots = [Path(scratch) / name for name in ("frozen", "corrected")]
        old_summaries = frozen.generate_dataset(roots[0], duration_minutes=1, case_count=10, seed=20260812)
        new_summaries = current.generate_dataset(roots[1], duration_minutes=1, case_count=10, seed=20260812)
        assert old_summaries == new_summaries
        for case in new_summaries:
            case_id = case["case_id"]
            entry = {"case_id": case_id, "duration_seconds": 60, "raw_and_ebi_identical": True}
            for folder, suffix in (("data", ".DATA"), ("DGS", ".EBI")):
                relative = Path(case_id) / folder / (case_id + suffix)
                before, after = (digest(root / relative) for root in roots)
                assert before == after
                entry[folder + "_sha256"] = after
            relative = Path(case_id) / "report_image" / (case_id + "_1.LPS")
            assert canonical_report(roots[0] / relative) == canonical_report(roots[1] / relative)
            entry["only_three_hrv_reference_fields_may_differ"] = True
            proof.append(entry)
    return {"frozen_generator_sha256": digest(frozen_path),
            "corrected_generator_sha256": digest(current_path),
            "outside_statistics_ast_identical": True,
            "short_equivalence_profiles": proof,
            "native_algorithm_modified": False, "diagnostic_thresholds_modified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generator", type=Path, required=True)
    parser.add_argument("--baseline-generator", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--short-data", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Regression destination must be new; existing files are preserved")
    generator_path = args.generator.resolve()
    module = load_generator("corrected_regression_generator", generator_path)
    frozen_path = args.baseline_generator.resolve()
    frozen = load_generator("frozen_regression_generator", frozen_path)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    equivalence = verify_reference_equivalence(module, frozen, generator_path, frozen_path, args.output.parent)
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
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ecg_core.ebi import hrv
    from ecg_core.lps_parser import parse_lps
    hrv_checks = []
    for case in summaries:
        folder = args.output / case["case_id"]
        native = hrv(folder / "DGS" / (case["case_id"] + ".EBI"))
        reported = parse_lps(folder / "report_image" / (case["case_id"] + "_1.LPS"))["summary"]
        fields = ("sdnn_ms", "rmssd_ms", "pnn50_pct")
        assert all(reported[field] == native[field] for field in fields)
        hrv_checks.append({"case_id": case["case_id"], "nn_count": native["nn_count"],
                           **{field: reported[field] for field in fields},
                           "reported_native_reference_equal": True})
    receipt = {"schema_version": 1, "wholly_synthetic": True, "patient_inputs_read": False,
               "clinical_ground_truth": False, "generator_sha256": digest(generator_path),
               "seed": 20260812, "case_count": 10, "duration_seconds_per_case": 86400,
               "total_raw_bytes": sum(c["data_bytes"] for c in summaries),
               "generation_seconds": time.perf_counter() - generation_started,
               "case_timings": case_timings, "profiles": summaries, "files": files,
               "short_input": {"duration_seconds_per_case": 1800, "case_count": 10, "files": short_files},
               "reference_equivalence": equivalence, "whole_day_hrv_reference_checks": hrv_checks,
               "method": "Frozen waveform/beat engine with byte-equivalent short proofs; adjacent-NN correction "
                         "only in fictional LPS HRV references; independent full-length profiles; "
                         "same byte-verified input files used by baseline and candidate. "
                         "No reuse of the prior running CI DATA; this new commit generates fresh day sources."}
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("WHOLEDAY_INPUT_RECEIPT_JSON=" + json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()
