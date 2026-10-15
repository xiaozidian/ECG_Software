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


def _message(value: str, checkout_root: Path | None = None) -> str:
    # Normalize only known checkout paths and unstable diagnostic identifiers.
    if checkout_root is not None:
        for prefix in (str(checkout_root.resolve()), checkout_root.resolve().as_posix(),
                       str(checkout_root.resolve()).replace("\\", "\\\\")):
            value = value.replace(prefix, "<checkout>")
    value = re.sub(r"(?:[A-Za-z]:)?[/\\][^\s'\"]*pytest-of-[^\s'\"]*", "<pytest-temp>", value)
    value = re.sub(r"0x[0-9A-Fa-f]{6,}", "<address>", value)
    value = re.sub(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\b", "<timestamp>", value)
    value = re.sub(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", "<uuid>", value)
    return " ".join(value.split())


def read_junit(path: Path, checkout_root: Path | None = None) -> dict[str, dict[str, str]]:
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
                message = _message(element.get("message", ""), checkout_root)
                break
        result[node_id] = {
            "status": status, "type": failure_type, "message": message,
        }
    if not result:
        raise ValueError("JUnit contains no testcases")
    # Real collection failures have no testcase class. Fixture errors remain
    # explicit outcomes and are allowed only when unchanged in the baseline.
    if any(case.find("error") is not None and not case.get("classname")
           for case in root.iter("testcase")):
        raise ValueError("JUnit contains a collection failure")
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
        elif old["status"] in {"failed", "error"}:
            if new["status"] == "passed":
                improvements.append(node_id)
            elif new != old:
                regressions.append({"node": node_id, "reason": "baseline failure changed"})
            else:
                unchanged_failures.append(node_id)
        elif old["status"] == "skipped" and new["status"] in {"failed", "error"}:
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
    parser.add_argument("--baseline-root", type=Path)
    parser.add_argument("--current-root", type=Path)
    args = parser.parse_args()
    try:
        report = compare(read_junit(args.baseline, args.baseline_root),
                         read_junit(args.current, args.current_root))
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
