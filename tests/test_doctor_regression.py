"""Regression gate tests: known failures remain visible without hiding new ones."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.compare_doctor_regression import compare, read_junit


def _case(status="passed", message=""):
    return {"status": status, "type": "AssertionError" if status == "failed" else "",
            "message": message}


def test_known_failure_stays_visible_and_new_passing_test_is_counted():
    before = {"test::ok": _case(), "test::known": _case("failed", "expected fixed source ID")}
    after = {**before, "doctor::new": _case()}
    report = compare(before, after)
    assert report["comparison_passed"]
    assert not report["full_suite_green"]
    assert report["current"] == {"total": 3, "passed": 2, "failed": 1, "skipped": 0, "error": 0}
    assert report["unchanged_baseline_failures"] == ["test::known"]


@pytest.mark.parametrize("replacement", ["failed", "skipped"])
def test_formerly_passing_test_cannot_be_hidden_by_a_failure_or_skip(replacement):
    report = compare({"test::ok": _case()}, {"test::ok": _case(replacement)})
    assert not report["comparison_passed"]
    assert report["regressions"][0]["node"] == "test::ok"


def test_missing_test_and_changed_baseline_failure_block_delivery():
    report = compare({"test::missing": _case(), "test::known": _case("failed", "old")},
                     {"test::known": _case("failed", "new")})
    assert not report["comparison_passed"]
    assert report["missing_baseline_tests"] == ["test::missing"]
    assert report["regressions"][0]["reason"] == "baseline failure changed"


@pytest.mark.parametrize("status", ["failed", "skipped"])
def test_new_test_must_pass(status):
    report = compare({"test::ok": _case()}, {"test::ok": _case(), "doctor::new": _case(status)})
    assert not report["comparison_passed"]


@pytest.mark.parametrize("xml", [
    "<testsuites/>",
    "<invalid/>",
    '<testsuite><testcase name="a" classname="t"/><testcase name="a" classname="t"/></testsuite>',
    '<testsuite><testcase name="a" classname="t"><error type="ImportError"/></testcase></testsuite>',
])
def test_invalid_or_interrupted_junit_cannot_be_accepted(tmp_path: Path, xml: str):
    source = tmp_path / "junit.xml"
    source.write_text(xml, encoding="utf-8")
    with pytest.raises(ValueError):
        read_junit(source)
