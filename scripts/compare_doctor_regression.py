"""Compare full synthetic regressions with an unchanged public-source baseline.

This utility does not read case files or physician work. It compares JUnit XML
from the same runner, dependencies and independently isolated work directories.
Known baseline failures remain visible; they are never described as a green
suite. New failures, missing baseline tests, skipped formerly passing tests,
or changed failure messages fail the comparison.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path


def _message(value: str) -> str:
    # Only unstable pytest temporary paths and memory addresses are normalized.
    value = re.sub(r"(?:[A-Za-z]:)?[/\\][^\s'\"]*pytest-of-[^\s'\"]*", "<pytest-temp>", value)
    value = re.sub(r"0x[0-9A-Fa-f]{6,}", "<address>", value)
    return " ".join(value.split())


def read_junit(path: Path) -> dict[str, dict[str, str]]:
    root = ET.parse(path).getroot()
    if root.tag not in {"testsuites", "testsuite"}:
        raise ValueError("Not a JUnit testsuite document")
    result: dict[str, dict[str, str]] = {}
    for case in root.iter("testcase"):
        class_name = case.get("classname", "")
        name = case.get("name", "")
        if not name:
            raise ValueError("JUnit testcase has no name")
        node_id = class_name + "::" + name
        if node_id in result:
            raise ValueError("Duplicate JUnit testcase: " + node_id)
        status, failure_type, message = "passed", "", ""
        for tag in ("error", "failure", "skipped"):
            element = case.find(tag)
            if element is not None:
                status = {"error": "error", "failure": "failed", "skipped": "skipped"}[tag]
                failure_type = element.get("type", "")
                message = _message(element.get("message", ""))
                break
        result[node_id] = {
            "status": status, "type": failure_type, "message": message,
        }
    if not result:
        raise ValueError("JUnit contains no testcases")
    # Pytest interruption/collection failures may appear as a synthetic testcase.
    if any(node.get("status") == "error" for node in result.values()):
        raise ValueError("JUnit contains collection or execution errors")
    return result


def compare(baseline: dict, current: dict) -> dict:
    missing = sorted(set(baseline) - set(current))
    added = sorted(set(current) - set(baseline))
    regressions: list[dict[str, str]] = []
    improvements: list[str] = []
    unchanged_failures: list[str] = []
    for node_id in sorted(set(baseline) & set(current)):
        old, new = baseline[node_id], current[node_id]
        if old["status"] == "passed" and new["status"] != "passed":
            regressions.append({"node": node_id, "reason": "formerly passing test no longer passes"})
        elif old["status"] == "failed":
            if new["status"] == "passed":
                improvements.append(node_id)
            elif new != old:
                regressions.append({"node": node_id, "reason": "baseline failure changed"})
            else:
                unchanged_failures.append(node_id)
        elif old["status"] == "skipped" and new["status"] == "failed":
            regressions.append({"node": node_id, "reason": "formerly skipped test now fails"})
    for node_id in added:
        if current[node_id]["status"] != "passed":
            regressions.append({"node": node_id, "reason": "new test does not pass"})

    def counts(tests: dict) -> dict:
        counted = collections.Counter(node["status"] for node in tests.values())
        return {"total": len(tests), **{status: counted[status]
                for status in ("passed", "failed", "skipped", "error")}}

    success = not missing and not regressions
    return {
        "schema_version": 1,
        "comparison_passed": success,
        "full_suite_green": all(node["status"] == "passed" for node in current.values()),
        "clinical_acceptance": False,
        "method": "Same runner and synthetic input; test identities and outcomes compared to frozen public baseline.",
        "baseline": counts(baseline),
        "current": counts(current),
        "added_tests": added,
        "missing_baseline_tests": missing,
        "unchanged_baseline_failures": unchanged_failures,
        "improved_baseline_failures": improvements,
        "regressions": regressions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = compare(read_junit(args.baseline), read_junit(args.current))
    except (OSError, ValueError, ET.ParseError) as exc:
        report = {
            "schema_version": 1,
            "comparison_passed": False,
            "full_suite_green": False,
            "clinical_acceptance": False,
            "comparison_error": type(exc).__name__ + ": " + str(exc),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["comparison_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
