"""Scope accounting must preserve every day assertion and reject missing tests."""
from pathlib import Path
import hashlib
import json

import pytest

from scripts.run_doctor_scoped_regression import DAY_TESTS, day_keys, merge_scopes, verify_shared_inputs


def write_xml(path: Path, keys, status=""):
    path.write_text("<testsuite>" + "".join(
        '<testcase classname="' + key.split("::")[0] + '" name="' + key.split("::")[1] + '">'
        + status + "</testcase>" for key in keys) + "</testsuite>", encoding="utf-8")


def test_original_day_nodes_are_preserved_once_and_failure_is_visible(tmp_path):
    short, day, output = [tmp_path / name for name in ("short.xml", "day.xml", "merged.xml")]
    write_xml(short, ["tests.test_dataset::test_dataset_discovery_uses_pseudonymous_directory_ids"])
    write_xml(day, sorted(day_keys()), '<failure type="AssertionError" message="original day assertion"/>')
    receipt = merge_scopes(short, day, output)
    assert len(DAY_TESTS) == receipt["day"]["total"] == receipt["day"]["failed"] == 4
    assert receipt["short"]["passed"] == 1
    assert receipt["combined"] == {"total": 5, "passed": 1, "failed": 4, "error": 0, "skipped": 0}
    assert receipt["day_assertions_modified"] is False
    assert receipt["clinical_acceptance"] is False
    assert output.read_text().count("original day assertion") == 4


@pytest.mark.parametrize("problem", ["missing", "duplicate", "wrong_scope", "collection_error"])
def test_missing_or_misrouted_original_day_checks_block_acceptance(tmp_path, problem):
    short, day, output = [tmp_path / name for name in ("short.xml", "day.xml", "merged.xml")]
    keys = sorted(day_keys())
    write_xml(short, ["tests.short::test_normal"])
    if problem == "missing":
        keys.pop()
    elif problem == "duplicate":
        keys.append(keys[0])
    elif problem == "wrong_scope":
        write_xml(short, ["tests.short::test_normal", keys[0]])
    elif problem == "collection_error":
        short.write_text('<testsuite><testcase name="collection"><error/></testcase></testsuite>')
    write_xml(day, keys)
    with pytest.raises(ValueError):
        merge_scopes(short, day, output)
    assert not output.exists()


@pytest.mark.parametrize("mutation", ["same_size", "size", "membership"])
def test_baseline_or_candidate_cannot_change_shared_synthetic_input(tmp_path, mutation):
    short, day = tmp_path / "short", tmp_path / "day"
    inventories = []
    for root in (short, day):
        root.mkdir()
        inventory = []
        for index in range(30):
            name = str(index) + ".fixture"
            payload = b"original"
            (root / name).write_bytes(payload)
            inventory.append({"path": name, "size_bytes": len(payload),
                              "sha256": hashlib.sha256(payload).hexdigest()})
        inventories.append(inventory)
    receipt = tmp_path / "input.json"
    receipt.write_text(json.dumps({"duration_seconds_per_case": 86400, "case_count": 10,
        "files": inventories[1], "short_input": {"duration_seconds_per_case": 1800,
        "files": inventories[0]}}), encoding="utf-8")
    verify_shared_inputs(short, day, receipt)
    if mutation == "same_size":
        (day / "0.fixture").write_bytes(b"modified")
    elif mutation == "size":
        (short / "0.fixture").write_bytes(b"changed length")
    else:
        (day / "unexpected.fixture").write_bytes(b"new")
    with pytest.raises(ValueError):
        verify_shared_inputs(short, day, receipt)
