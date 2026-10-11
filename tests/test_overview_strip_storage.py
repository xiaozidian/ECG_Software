"""Manual overview strips through real storage and API, using mathematical files."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import struct
import time

import pytest

from app import create_app
from ecg_core.ebi import HEADER_SIZE, RECORD
from ecg_core.storage import Storage
from ecg_core.waveform import ALL_LEADS


CASE_ID = "9999999999999917"
TARGETS = [800, 1000, 1200, 1400, 1600]


def payload(status="confirmed"):
    return dict(sample_index=700, lead="II", category="note", label="数学人工图条",
                note="Only a mathematical interval, not a diagnosis.",
                details=dict(kind="STRIP", status=status, end_sample=1700,
                             finding="数学范围 3.5–8.5 秒"))


def database_rows(storage):
    """Logical snapshot includes clinical values, review state and audit rows."""
    with storage.connect() as db:
        names = [r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {name: sorted((tuple(row) for row in db.execute(
            'SELECT * FROM "' + name.replace('"', '""') + '"')), key=repr)
                for name in names}


def get_ok(client, path, **kwargs):
    response = client.get(path, **kwargs)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


@pytest.fixture
def strip_case(tmp_path):
    root = tmp_path / "mathematical-source"
    folder = root / CASE_ID
    paths = [folder / "data" / (CASE_ID + ".DATA"),
             folder / "DGS" / (CASE_ID + ".EBI"),
             folder / "report_image" / (CASE_ID + "_1.LPS")]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
    frames = [tuple((sample * (channel + 3) + channel * 7) % 1000 - 500
                    for channel in range(8)) for sample in range(6000)]
    paths[0].write_bytes(b"".join(struct.pack("<8h", *frame) for frame in frames))
    paths[1].write_bytes(bytes(HEADER_SIZE) + b"".join(
        RECORD.pack(second * 200, 1, {4: 2, 6: 3}.get(second, 1), 0, 0, 0, 1000)
        for second in range(1, 30)))
    paths[2].write_text("<root><PShape>记录时间:2026-01-01 08:00:00</PShape>"
                        "<PShape>总心搏数:29</PShape></root>", encoding="utf-8")
    # Let macOS finish stamping only these newly generated disposable files.
    # Production source checks stay active, including changes during reads.
    for path in paths:
        path.read_bytes()
    started = stable = time.monotonic()
    signature = [(p.stat().st_mtime_ns, p.stat().st_ctime_ns) for p in paths]
    while time.monotonic() - started < 1:
        time.sleep(.025)
        current = [(p.stat().st_mtime_ns, p.stat().st_ctime_ns) for p in paths]
        if current != signature:
            stable, signature = time.monotonic(), current
        if time.monotonic() - stable >= .25:
            break
    original = [sha256(p.read_bytes()).hexdigest() for p in paths]
    db_path = tmp_path / "mathematical-work.db"
    application = create_app(data_root=root, db_path=db_path, testing=True)
    client = application.test_client()
    base = "/api/cases/" + CASE_ID
    get_ok(client, base + "/analysis-basis")
    yield application, client, base, root, db_path, frames
    assert [sha256(p.read_bytes()).hexdigest() for p in paths] == original


@pytest.mark.parametrize("status", ["confirmed", "pending", "excluded"])
def test_overview_strip_api_persists_and_preserves_diagnostic_counts(strip_case, status):
    app, client, base, root, db_path, frames = strip_case
    store = app.extensions["storage"]
    before = get_ok(client, base + "/report-events")
    stats = get_ok(client, base + "/report-statistics")
    review = store.get_review(CASE_ID)
    audits = len(store.list_audit())
    response = client.post(base + "/annotations", json=payload(status))
    assert response.status_code == 201, response.get_json()
    created = response.get_json()
    assert created["details"] == payload(status)["details"]
    assert created["sample_index"] == 700 and created["category"] == "note"
    assert len(store.list_audit()) == audits + 1
    assert store.list_audit()[0]["action"] == "annotation.create"
    assert store.get_review(CASE_ID)["revision"] == review["revision"] + 1
    assert store.get_review(CASE_ID)["pending_steps"] == ["edit", "stt"]

    # A new application/Storage instance must recover the committed interval.
    reopened = create_app(data_root=root, db_path=db_path, testing=True)
    client = reopened.test_client()
    assert get_ok(client, base + "/annotations")["items"] == [created]
    events = get_ok(client, base + "/report-events")
    assert events["analysis_basis"] == before["analysis_basis"]
    assert events["analysis_revision"] == review["revision"] + 1
    assert events["basis_versions"]["other"] != before["basis_versions"]["other"]
    assert {k: v for k, v in events["basis_versions"].items() if k != "other"} == {
        k: v for k, v in before["basis_versions"].items() if k != "other"}
    current_stats = get_ok(client, base + "/report-statistics")
    assert {k: v for k, v in current_stats.items() if k != "analysis_revision"} == {
        k: v for k, v in stats.items() if k != "analysis_revision"}
    strips = [e for e in events["items"] if e["subtype"] == "STRIP"]
    if status != "confirmed":
        assert strips == []
        assert events["items"] == before["items"]
        return

    assert len(strips) == 1
    event = strips[0]
    assert event["event_id"] == "annotation:" + str(created["id"])
    assert event["category"] == "other" and event["target_samples"] == TARGETS
    assert event["beat_count"] == 5 and event["start_sample"] == 700 and event["end_sample"] == 1700
    assert event["diagnosis_status"] == "pending" and event["pattern_only"] is False
    assert event["basis_version"] == events["basis_versions"]["other"]
    selection = dict(event_id=event["event_id"], basis_version=event["basis_version"],
                     caption="Mathematical manual strip", leads=ALL_LEADS,
                     duration_s=5, range_start_s=3.5, range_end_s=8.5)
    strip = get_ok(client, base + "/report-strip", query_string={
        **{k: selection[k] for k in ("event_id", "basis_version", "range_start_s", "range_end_s")},
        "leads": ",".join(ALL_LEADS), "duration": 5,
        "analysis_basis": events["analysis_basis"], "analysis_revision": events["analysis_revision"]})
    assert strip["target_samples"] == TARGETS and strip["category"] == "other"
    assert [b["sample_index"] for b in strip["waveform"]["beats"]] == TARGETS
    assert [b["class_code"] for b in strip["waveform"]["beats"]] == ["S", "N", "V", "N", "N"]
    assert strip["waveform"]["start_s"] == 3.5 and strip["waveform"]["duration_s"] == 5
    assert strip["waveform"]["stride"] == 1 and len(strip["waveform"]["leads"]["II"]) == 1000
    assert strip["waveform"]["leads"]["II"] == [frame[1] for frame in frames[700:1700]]
    assert strip["analysis_basis"] == events["analysis_basis"]
    assert strip["analysis_revision"] == events["analysis_revision"]
    report = get_ok(client, base + "/report")
    composition = deepcopy(report["composition"])
    composition["selected_events"] = [selection]
    save = dict(expected_version=report["version"], expected_review_revision=report["review_revision"],
                conclusion="Mathematical-only draft", status="draft", composition=composition)
    response = client.put(base + "/report", json=save)
    assert response.status_code == 200, response.get_json()
    saved = response.get_json()
    assert saved["status"] == "draft" and saved["reviewed_by"] == ""
    reopened = create_app(data_root=root, db_path=db_path, testing=True)
    persisted = get_ok(reopened.test_client(), base + "/report")
    assert persisted["composition"]["selected_events"] == saved["composition"]["selected_events"]
    assert persisted["composition"]["selected_events"][0]["event_id"] == event["event_id"]
    assert persisted["status"] == "draft" and persisted["reviewed_by"] == ""
    denied = reopened.test_client().put(base + "/report", json={
        **save, "status": "reviewed", "expected_version": persisted["version"],
        "expected_review_revision": persisted["review_revision"]})
    assert denied.status_code == 400
    assert reopened.extensions["storage"].get_review(CASE_ID)["pending_steps"] == ["edit", "stt"]


def reviewed_mathematical_draft(store):
    for step in ("edit", "stt"):
        store.complete_review(CASE_ID, dict(step=step, confirmed=True,
            revision=store.get_review(CASE_ID)["revision"]), "math-reviewer")
    composition = dict(diagnosis_blocks=[dict(key="manual-math", text="Retain mathematical prose",
        manual=True, acknowledged=True, needs_review=False)])
    draft = store.save_report(CASE_ID, "Mathematical draft text", "draft", "math-reviewer", composition)
    return store.save_report(CASE_ID, draft["conclusion"], "reviewed", "math-reviewer",
                             draft["composition"], expected_version=draft["version"])


def test_strip_storage_keeps_existing_annotation_audit_and_review_invalidation(strip_case):
    app, _, _, _, db_path, _ = strip_case
    store = app.extensions["storage"]
    approved = reviewed_mathematical_draft(store)
    review = store.get_review(CASE_ID)
    audits = len(store.list_audit())
    created = store.create_annotation(CASE_ID, payload(), "math-reviewer")
    reopened = Storage(db_path)
    assert reopened.list_annotations(CASE_ID) == [created]
    current = reopened.get_review(CASE_ID)
    assert current["revision"] == review["revision"] + 1
    assert current["steps"]["edit"]["status"] == "done"
    assert current["steps"]["stt"]["status"] == "stale"
    assert current["steps"]["stt"]["reason"] == "annotation.create"
    report = reopened.get_report(CASE_ID, "")
    assert report["status"] == "draft" and report["reviewed_by"] == ""
    assert report["version"] == approved["version"] + 1
    assert report["conclusion"] == approved["conclusion"]
    assert report["composition"]["diagnosis_blocks"] == [dict(
        key="manual-math", text="Retain mathematical prose", manual=True,
        acknowledged=False, needs_review=True)]
    assert len(reopened.list_audit()) == audits + 1
    assert reopened.list_audit()[0]["action"] == "annotation.create"


INVALID_DETAILS = [
    pytest.param("kind", "UNSUPPORTED", id="unsupported-kind"),
    pytest.param("kind", "strip", id="kind-case-mismatch"),
    pytest.param("status", "reviewed", id="unsupported-status"),
    pytest.param("status", None, id="null-status"),
    pytest.param("end_sample", 699, id="inverted-end"),
    pytest.param("end_sample", True, id="boolean-end"),
    pytest.param("end_sample", 1700.0, id="float-end"),
]


@pytest.mark.parametrize("field,value", INVALID_DETAILS)
@pytest.mark.parametrize("route", ["storage", "api"])
def test_invalid_strip_is_rejected_without_clinical_or_audit_writes(strip_case, route, field, value):
    app, client, base, _, _, _ = strip_case
    store = app.extensions["storage"]
    reviewed_mathematical_draft(store)
    before = database_rows(store)
    raw = payload()
    raw["details"][field] = value
    if route == "storage":
        with pytest.raises(ValueError):
            store.create_annotation(CASE_ID, raw, "math-reviewer")
    else:
        response = client.post(base + "/annotations", json=raw)
        assert response.status_code == 400, response.get_json()
    assert database_rows(store) == before
    assert store.list_annotations(CASE_ID) == []
    assert store.get_review(CASE_ID)["pending_steps"] == []
    assert store.get_report(CASE_ID, "")["status"] == "reviewed"
