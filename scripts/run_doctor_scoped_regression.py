"""Run short and day-input scopes without changing or dropping original assertions.

Both frozen baseline and candidate receive the same two genuine synthetic inputs.
The four day-only tests are selected once on day data, never counted as skips.
All remaining tests run on the short input; merged JUnit rejects overlaps or gaps.
"""
from __future__ import annotations

import argparse
import collections
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

DAY_TESTS = (
    "tests/test_dataset.py::test_raw_format_duration_and_report_match",
    "tests/test_dataset.py::test_ebi_structure_counts_and_rr_timing",
    "tests/test_dataset.py::test_twelve_lead_window_is_derived_without_loading_whole_file",
    "tests/test_api.py::test_waveform_events_trend_and_hrv_endpoints",
)


def junit_key(case):
    return case.get("classname", "") + "::" + case.get("name", "")


def day_keys():
    return {path.removesuffix(".py").replace("/", ".") + "::" + name
            for path, name in (node.split("::", 1) for node in DAY_TESTS)}


def merge_scopes(short_path: Path, day_path: Path, output: Path) -> dict:
    expected_day = day_keys()
    short_root, day_root = ET.parse(short_path).getroot(), ET.parse(day_path).getroot()
    short_cases, day_cases = list(short_root.iter("testcase")), list(day_root.iter("testcase"))
    short_keys, actual_day = [junit_key(c) for c in short_cases], [junit_key(c) for c in day_cases]
    if not short_cases or len(short_keys) != len(set(short_keys)):
        raise ValueError("Short-scope JUnit is empty or contains duplicates")
    if len(actual_day) != len(set(actual_day)) or set(actual_day) != expected_day:
        raise ValueError("Day scope did not execute every original day-only test exactly once")
    if set(short_keys) & expected_day:
        raise ValueError("A day-only test was executed against short data")
    combined = ET.Element("testsuites")
    for root in (short_root, day_root):
        if root.tag == "testsuite":
            combined.append(copy.deepcopy(root))
        elif root.tag == "testsuites":
            for suite in root:
                if suite.tag != "testsuite":
                    raise ValueError("Unexpected JUnit child")
                combined.append(copy.deepcopy(suite))
        else:
            raise ValueError("Invalid JUnit root")
    if any(case.find("error") is not None and not case.get("classname")
           for case in combined.iter("testcase")):
        raise ValueError("Collection error cannot be accepted as a scoped test result")
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(combined).write(output, encoding="utf-8", xml_declaration=True)
    def outcomes(cases):
        counts = collections.Counter(
            "error" if case.find("error") is not None else
            "failed" if case.find("failure") is not None else
            "skipped" if case.find("skipped") is not None else "passed"
            for case in cases)
        return {"total": len(cases), **{name: counts[name] for name in
                ("passed", "failed", "error", "skipped")}}
    return {"short": outcomes(short_cases), "day": outcomes(day_cases),
            "combined": outcomes(short_cases + day_cases),
            "day_nodes_executed_once": sorted(expected_day),
            "day_assertions_modified": False, "clinical_acceptance": False}


def verify_shared_inputs(short_data: Path, day_data: Path, receipt_path: Path):
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt["duration_seconds_per_case"] != 86400 or receipt["case_count"] != 10:
        raise ValueError("Day input profile is not ten genuine day records")
    if receipt["short_input"]["duration_seconds_per_case"] != 1800:
        raise ValueError("Short input profile changed")
    for root, entries in ((short_data, receipt["short_input"]["files"]), (day_data, receipt["files"])):
        if len(entries) != 30:
            raise ValueError("Synthetic input inventory changed")
        actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
        if actual != {entry["path"] for entry in entries}:
            raise ValueError("Synthetic input membership changed")
        for entry in entries:
            path = root / entry["path"]
            if path.stat().st_size != entry["size_bytes"]:
                raise ValueError("Synthetic input size changed")
            value = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    value.update(chunk)
            if value.hexdigest() != entry["sha256"]:
                raise ValueError("Shared synthetic input content changed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--short-data", type=Path, required=True)
    parser.add_argument("--day-data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--input-receipt", type=Path, required=True)
    parser.add_argument("--expected-tests", type=int, required=True)
    args = parser.parse_args()
    checkout = args.checkout.resolve()
    output = args.output.resolve()
    short_xml = output.with_name(output.stem + "-short.xml")
    day_xml = output.with_name(output.stem + "-day.xml")
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    verify_shared_inputs(args.short_data, args.day_data, args.input_receipt)
    base_env = dict(os.environ)
    scopes = (
        ("short", args.short_data, short_xml, ["--deselect=" + node for node in DAY_TESTS]),
        ("day", args.day_data, day_xml, list(DAY_TESTS)),
    )
    durations = {}
    for name, data, xml, selection in scopes:
        env = dict(base_env, ECG_DATA_ROOT=str(data.resolve()))
        before = time.perf_counter()
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--junitxml=" + str(xml), *selection],
            cwd=checkout, env=env, check=False,
        )
        durations[name] = time.perf_counter() - before
        if completed.returncode not in (0, 1):
            raise RuntimeError("Pytest " + name + " scope did not complete: " + str(completed.returncode))
    verify_shared_inputs(args.short_data, args.day_data, args.input_receipt)
    receipt = merge_scopes(short_xml, day_xml, output)
    if receipt["combined"]["total"] != args.expected_tests:
        raise ValueError("Complete scoped test count changed: " + str(receipt["combined"]["total"]))
    receipt.update({"method": "Identical short/day inputs on the same runner for baseline and candidate; "
                              "all original tests retained; four day-only tests run once on genuine day DATA.",
                    "short_input_seconds": 1800, "day_input_seconds": 86400,
                    "synthetic_case_count_per_scope": 10,
                    "source_hashes_verified_before_and_after": True,
                    "expected_complete_test_count": args.expected_tests,
                    "seconds_by_scope": durations, "total_seconds": time.perf_counter() - started})
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("DOCTOR_SCOPED_REGRESSION_JSON=" + json.dumps(receipt, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
