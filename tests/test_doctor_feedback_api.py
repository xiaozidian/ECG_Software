"""Doctor-feedback API contracts over disposable 90-second mathematics only.

All waveform changes, annotations, revisions and reopen operations below target
the synthetic_case/synthetic_app fixtures, never a patient source or work DB.
"""
import os
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest

from app import create_app
from ecg_core.beat_editor import BeatEditorStore
from test_analysis_provenance import (
    replace_preserving_mtime,
    synthetic_app,
    synthetic_case,
)
from test_stt_range import synthetic as mathematical_signal


IDENTITY_FIELDS = ("case_id", "analysis_basis", "analysis_revision", "beat_revision")


def ok(response):
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def base_for(case):
    return "/api/cases/" + case[1]


def identity(client, base):
    value = ok(client.get(base + "/rhythm-review"))
    return {key: value[key] for key in IDENTITY_FIELDS}


def extended_identity(client, base):
    # The legacy RR projection deliberately omits these optional identities.
    # Negotiate them from this endpoint's actual current server projection,
    # rather than guessing a field in a different API or synthesizing a token.
    current = identity(client, base)
    value = ok(client.post(base + "/stt-range", json=range_payload(current)))["server_identity"]
    return {key: value[key] for key in (*IDENTITY_FIELDS, "source_digest", "data_version")}


def range_payload(scope, **changes):
    result = dict(scope=deepcopy(scope), start_sample=0, end_sample=12000,
                  leads=["II"], measurement_ms=60)
    result.update(changes)
    return result


def rows(store):
    """Full logical snapshot, including audit/version/history, in test memory."""
    with store.connect() as db:
        names = [row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {name: sorted((tuple(row) for row in db.execute(
            'SELECT * FROM "' + name.replace('"', '""') + '"')), key=repr)
                for name in names}


def install_zero_mean_signal(case):
    raw, _ = mathematical_signal(seconds=90, delta=lambda _: 0)
    # Same fixed 90-second fixture and anchors; only disposable mathematical
    # QRS/flat-ST samples are supplied to make a genuine known zero observable.
    case[2]["data"].write_bytes(raw.tobytes())


def annotation(store, cid, *, kind="AF", status="pending", start=2000, end=2000):
    return store.create_annotation(cid, dict(
        sample_index=start, lead="全部", category="note", label="数学节律片段",
        note="Synthetic review only", details=dict(kind=kind, status=status,
        end_sample=end, finding="Mathematical mask")), "synthetic-reviewer")


def advance(store, cid, which, paths):
    if which == "global":
        store.audit("synthetic-reviewer", "beat_override.editor", cid)
    elif which == "beat":
        # Isolate the fine-grained revision guard from the global review guard.
        # This is an intentionally independent synthetic DB race, not a write
        # path added to production and not a clinical edit fixture.
        with store.connect() as db:
            present = db.execute(
                "SELECT revision FROM beat_edit_documents WHERE case_id=?", (cid,)
            ).fetchone()
            if present:
                db.execute("UPDATE beat_edit_documents SET revision=revision+1 WHERE case_id=?", (cid,))
            else:
                editor = BeatEditorStore(store)
                document = editor.snapshot(cid)["document"]
                import json
                db.execute("INSERT INTO beat_edit_documents VALUES(?,?,?,?,?)",
                           (cid, 1, json.dumps(document), "[]", "[]"))
    else:
        path = paths[which]
        content = path.read_bytes()
        changed = (content.replace(b":89", b":88") if which == "lps"
                   else b"\1" + content[1:])
        assert changed != content
        replace_preserving_mtime(path, changed)


@pytest.mark.parametrize("measurement", [0, 60, 80])
@pytest.mark.parametrize("start", [0, 201, 6000])
def test_stt_range_binds_exact_four_scope_and_half_open_samples(
        synthetic_app, synthetic_case, measurement, start):
    client = synthetic_app.test_client()
    base = base_for(synthetic_case)
    scope = identity(client, base)
    before = rows(synthetic_app.extensions["storage"])
    result = ok(client.post(base + "/stt-range", json=range_payload(
        scope, start_sample=start, end_sample=start + 12000, measurement_ms=measurement)))
    assert result["scope"] == scope
    assert {key: result["server_identity"][key] for key in IDENTITY_FIELDS} == scope
    assert result["range"] == dict(start_sample=start, end_sample=start + 12000,
        start_s=start / 200, end_s=(start + 12000) / 200, duration_s=60, half_open=True)
    assert result["binding"]["source_sample_count"] == 18000
    assert result["binding"]["status"] == "caller_source_and_basis_bound"
    assert result["physician_document_written"] is False
    assert result["method_profile"]["measurement_ms"] == measurement
    assert result["method_profile"]["units"] == "device_unit"
    assert result["method_profile"]["calibration_verified"] is False
    assert result["interpretation"]["diagnosis_generated"] is False
    assert rows(synthetic_app.extensions["storage"]) == before


def test_stt_range_preserves_extra_scope_and_mirrors_current_source_and_data_version(
        synthetic_app, synthetic_case):
    client = synthetic_app.test_client()
    base = base_for(synthetic_case)
    scope = extended_identity(client, base)
    assert all(key in scope for key in (*IDENTITY_FIELDS, "source_digest", "data_version"))
    scope = {**scope, "client_nonce": str(uuid4()), "client_view": {"selection": "math-only"}}
    before = rows(synthetic_app.extensions["storage"])
    result = ok(client.post(base + "/stt-range", json=range_payload(scope)))
    assert result["scope"] == scope
    for key in (*IDENTITY_FIELDS, "source_digest", "data_version"):
        assert result["server_identity"][key] == scope[key]
    assert result["binding"]["source_digest"] == scope["source_digest"]
    assert rows(synthetic_app.extensions["storage"]) == before


@pytest.mark.parametrize("missing", IDENTITY_FIELDS)
def test_stt_range_requires_every_identity_field(synthetic_app, synthetic_case, missing):
    client = synthetic_app.test_client()
    base = base_for(synthetic_case)
    scope = identity(client, base)
    del scope[missing]
    before = rows(synthetic_app.extensions["storage"])
    response = client.post(base + "/stt-range", json=range_payload(scope))
    assert response.status_code == 400, response.get_json()
    assert rows(synthetic_app.extensions["storage"]) == before


@pytest.mark.parametrize("field,value", [
    ("scope", None), ("scope", []), ("scope", "not-an-object"),
    ("start_sample", False), ("end_sample", True),
    ("start_sample", 0.0), ("start_sample", 0.2), ("end_sample", 12000.0),
    ("end_sample", 11999), ("end_sample", 18001), ("start_sample", -1),
    ("start_sample", 12000), ("measurement_ms", True), ("measurement_ms", 60.0),
    ("measurement_ms", 61), ("leads", []), ("leads", ["II", "II"]),
])
def test_stt_range_invalid_requests_are_not_clipped_or_rounded(
        synthetic_app, synthetic_case, field, value):
    client = synthetic_app.test_client()
    base = base_for(synthetic_case)
    body = range_payload(identity(client, base))
    body[field] = value
    before = rows(synthetic_app.extensions["storage"])
    response = client.post(base + "/stt-range", json=body)
    assert response.status_code == 400, response.get_json()
    assert rows(synthetic_app.extensions["storage"]) == before


@pytest.mark.parametrize("which", ["case_id", "analysis_basis", "analysis_revision",
                                  "beat_revision", "source_digest", "data_version", "body_case_id"])
def test_stt_range_wrong_or_stale_identity_is_rejected_before_compute(
        synthetic_app, synthetic_case, monkeypatch, which):
    import ecg_core.stt_range as range_engine
    client = synthetic_app.test_client()
    base = base_for(synthetic_case)
    scope = extended_identity(client, base)
    body = range_payload(scope)
    if which == "body_case_id":
        body["case_id"] = "synthetic-other-case"
    elif which in ("analysis_revision", "beat_revision"):
        body["scope"][which] += 1
    else:
        body["scope"][which] = "synthetic-stale-or-other"
    monkeypatch.setattr(range_engine, "analyze_stt_range",
                        lambda *a, **k: pytest.fail("must reject before calculating"))
    before = rows(synthetic_app.extensions["storage"])
    response = client.post(base + "/stt-range", json=body)
    assert response.status_code == 409, response.get_json()
    assert rows(synthetic_app.extensions["storage"]) == before


def test_stt_range_known_zero_and_no_eligible_observations_are_distinct(
        synthetic_app, synthetic_case):
    install_zero_mean_signal(synthetic_case)
    client = synthetic_app.test_client()
    base = base_for(synthetic_case)
    store = synthetic_app.extensions["storage"]
    scope = identity(client, base)
    before = rows(store)
    zero = ok(client.post(base + "/stt-range", json=range_payload(scope)))
    # The edited feed has no preceding anchor for its first detected beat.
    # It therefore has RR=0, unlike the standalone range-test record fixture.
    assert zero["counts"] == dict(detected_count=59, used_count=58,
        excluded_count=1, missing_count=0, reason_counts={"rr_outside_legacy_bounds": 1})
    assert zero["leads"][0]["mean_units"] == 0
    assert rows(store) == before
    annotation(store, synthetic_case[1], start=0, end=17999)
    scope = identity(client, base)
    before = rows(store)
    empty = ok(client.post(base + "/stt-range", json=range_payload(scope)))
    assert empty["counts"]["detected_count"] == 59
    assert empty["counts"]["used_count"] == 0
    assert empty["leads"][0]["mean_units"] is None
    assert empty["coverage"]["used_anchor_span_s"] is None
    assert rows(store) == before


@pytest.mark.parametrize("kind", ["AF", "AFL"])
@pytest.mark.parametrize("status", ["pending", "confirmed", "excluded"])
def test_stt_range_stored_rhythm_mask_uses_inclusive_end_and_actual_status(
        synthetic_app, synthetic_case, kind, status):
    client = synthetic_app.test_client()
    store = synthetic_app.extensions["storage"]
    annotation(store, synthetic_case[1], kind=kind, status=status, start=2000, end=2000)
    base = base_for(synthetic_case)
    scope = identity(client, base)
    before = rows(store)
    result = ok(client.post(base + "/stt-range", json=range_payload(scope)))
    expected = [] if status == "excluded" else [dict(
        start_sample=2000, end_sample=2001, reason="rhythm_" + kind,
        origin="stored_annotation", review_status=status, kind="exclusion")]
    assert result["exclusions"]["intervals"] == expected
    assert result["coverage"]["explicit_excluded_s"] == (0 if status == "excluded" else .005)
    assert rows(store) == before


def test_stt_range_uses_authoritative_saved_document_not_old_annotation_masks(
        synthetic_app, synthetic_case):
    client = synthetic_app.test_client()
    store = synthetic_app.extensions["storage"]
    cid = synthetic_case[1]
    base = base_for(synthetic_case)
    annotation(store, cid, kind="AF", status="confirmed", start=1000, end=4000)
    current = ok(client.get(base + "/rhythm-review"))
    document = dict(episodes=[dict(id=str(uuid4()), start_s=10.005, end_s=10.01,
        kind="AFL", status="pending", source="manual", note="synthetic")], bookmarks={})
    saved = ok(client.put(base + "/rhythm-review", json=dict(
        **{key: current[key] for key in IDENTITY_FIELDS}, revision=current["revision"],
        confirmed=True, document=document)))
    scope = {key: saved[key] for key in IDENTITY_FIELDS}
    before = rows(store)
    result = ok(client.post(base + "/stt-range", json=range_payload(scope)))
    assert result["exclusions"]["intervals"] == [dict(
        start_sample=2001, end_sample=2002, reason="rhythm_AFL", origin="stored_annotation",
        review_status="pending", kind="exclusion")]
    assert rows(store) == before


@pytest.mark.parametrize("which", ["global", "beat", "data", "ebi", "lps"])
def test_stt_range_mid_calculation_changes_never_return_mixed_identity(
        synthetic_app, synthetic_case, monkeypatch, which):
    import ecg_core.stt_range as range_engine
    client = synthetic_app.test_client()
    base = base_for(synthetic_case)
    scope = identity(client, base)
    store = synthetic_app.extensions["storage"]
    original = range_engine.analyze_stt_range
    def racing(*args, **kwargs):
        result = original(*args, **kwargs)
        advance(store, synthetic_case[1], which, synthetic_case[2])
        return result
    monkeypatch.setattr(range_engine, "analyze_stt_range", racing)
    response = client.post(base + "/stt-range", json=range_payload(scope))
    assert response.status_code == 409, response.get_json()
    assert not any(x["action"].startswith("report.") for x in store.list_audit())


@pytest.mark.parametrize("which", ["data", "ebi", "lps", "engine"])
def test_stt_range_real_synthetic_source_change_rejects_former_scope_before_compute(
        synthetic_app, synthetic_case, monkeypatch, which):
    import ecg_core.stt_range as range_engine
    client = synthetic_app.test_client()
    base = base_for(synthetic_case)
    scope = identity(client, base)
    store = synthetic_app.extensions["storage"]
    if which == "engine":
        synthetic_app.extensions["analysis_runtime"].engine_id = "changed-synthetic-engine"
    else:
        advance(store, synthetic_case[1], which, synthetic_case[2])
    before = rows(store)
    monkeypatch.setattr(range_engine, "analyze_stt_range",
                        lambda *a, **k: pytest.fail("old source must not reach the calculator"))
    response = client.post(base + "/stt-range", json=range_payload(scope))
    assert response.status_code == 409, response.get_json()
    # Source invalidation may update basis/review/audit, but must never
    # introduce or replace a physician document as a side effect of the read.
    after = rows(store)
    for table in ("annotations", "beat_templates", "report_drafts", "rhythm_reviews"):
        assert after[table] == before[table]


@pytest.mark.parametrize("field", IDENTITY_FIELDS)
def test_stt_review_checks_all_four_identity_fields_before_work(
        synthetic_app, synthetic_case, monkeypatch, field):
    import app as server
    client = synthetic_app.test_client()
    base = base_for(synthetic_case)
    scope = identity(client, base)
    scope[field] = (scope[field] + 1 if field in ("analysis_revision", "beat_revision")
                    else "synthetic-stale-or-other")
    monkeypatch.setattr(server, "build_stt_review",
                        lambda *a, **k: pytest.fail("must reject before computing ST review"))
    before = rows(synthetic_app.extensions["storage"])
    response = client.get(base + "/stt-review", query_string=scope)
    assert response.status_code == 409, response.get_json()
    assert rows(synthetic_app.extensions["storage"]) == before


@pytest.mark.parametrize("which", ["global", "beat", "data", "ebi", "lps"])
def test_stt_review_checks_identity_again_after_work(
        synthetic_app, synthetic_case, monkeypatch, which):
    import app as server
    client = synthetic_app.test_client()
    base = base_for(synthetic_case)
    scope = identity(client, base)
    original = server.build_stt_review
    store = synthetic_app.extensions["storage"]
    def racing(*args, **kwargs):
        result = original(*args, **kwargs)
        advance(store, synthetic_case[1], which, synthetic_case[2])
        return result
    monkeypatch.setattr(server, "build_stt_review", racing)
    response = client.get(base + "/stt-review", query_string=scope)
    assert response.status_code == 409, response.get_json()


def test_stt_review_current_read_is_fully_bound_and_writes_no_doctor_document(
        synthetic_app, synthetic_case):
    client = synthetic_app.test_client()
    base = base_for(synthetic_case)
    scope = identity(client, base)
    before = rows(synthetic_app.extensions["storage"])
    result = ok(client.get(base + "/stt-review", query_string=scope))
    assert {key: result[key] for key in IDENTITY_FIELDS} == scope
    assert result["calibration_unverified"] is True
    assert rows(synthetic_app.extensions["storage"]) == before


@pytest.mark.parametrize("beat_changes", [0, 3])
def test_rhythm_uuid_document_reopens_with_separate_document_and_global_revisions(
        synthetic_app, synthetic_case, tmp_path, beat_changes):
    client = synthetic_app.test_client()
    store = synthetic_app.extensions["storage"]
    cid = synthetic_case[1]
    base = base_for(synthetic_case)
    # Global revision already differs from both document and beat revisions.
    ok(client.get(base + "/analysis-basis"))
    editor = BeatEditorStore(store)
    for revision in range(beat_changes):
        editor.commit(cid, revision, "synthetic-reviewer", lambda doc: doc, "settings")
    for _ in range(3):
        store.audit("synthetic-reviewer", "beat_override.editor", cid)
    before = ok(client.get(base + "/rhythm-review"))
    assert before["revision"] == 0 and before["beat_revision"] == beat_changes
    assert before["analysis_revision"] == beat_changes + 3
    document = dict(episodes=[dict(id=str(uuid4()), start_s=10.005, end_s=20.01,
        kind="AF", status="pending", source="manual", note="Synthetic UUID note")],
        bookmarks={"fastest": 40.005, "slowest": 70.0})
    payload = dict(**{key: before[key] for key in IDENTITY_FIELDS},
        revision=before["revision"], confirmed=True, document=document)
    saved = ok(client.put(base + "/rhythm-review", json=payload))
    assert saved["revision"] == 1
    assert saved["analysis_revision"] == beat_changes + 4
    assert saved["beat_revision"] == beat_changes
    assert saved["case_id"] == cid and saved["analysis_basis"] == before["analysis_basis"]
    assert saved["document"] == document
    after_save = rows(store)
    reopened = create_app(data_root=synthetic_case[0], db_path=tmp_path / "case.db", testing=True)
    reopened_client = reopened.test_client()
    current = ok(reopened_client.get(base + "/rhythm-review", query_string={
        key: saved[key] for key in IDENTITY_FIELDS}))
    assert current == saved
    assert rows(reopened.extensions["storage"]) == after_save
    old = reopened_client.put(base + "/rhythm-review", json=payload)
    assert old.status_code == 409, old.get_json()
    assert rows(reopened.extensions["storage"]) == after_save


@pytest.mark.parametrize("which", ["global", "beat", "data"])
def test_rhythm_conflict_does_not_replace_uuid_document_or_history(
        synthetic_app, synthetic_case, monkeypatch, which):
    client = synthetic_app.test_client()
    base = base_for(synthetic_case)
    current = ok(client.get(base + "/rhythm-review"))
    payload = dict(**{key: current[key] for key in IDENTITY_FIELDS},
        revision=current["revision"], confirmed=True,
        document=dict(episodes=[dict(id=str(uuid4()), start_s=15, end_s=25,
            kind="AFL", status="confirmed", source="manual", note="synthetic")],
            bookmarks={"slowest": 25}))
    saved = ok(client.put(base + "/rhythm-review", json=payload))
    pending = dict(**{key: saved[key] for key in IDENTITY_FIELDS}, revision=saved["revision"],
        confirmed=True, document=dict(episodes=[], bookmarks={"fastest": 30}))
    store = synthetic_app.extensions["storage"]
    advance(store, synthetic_case[1], which, synthetic_case[2])
    before = rows(store)["rhythm_reviews"]
    response = client.put(base + "/rhythm-review", json=pending)
    assert response.status_code == 409, response.get_json()
    assert rows(store)["rhythm_reviews"] == before


def mean_save_payload(client, base, *, status="pending", point=15000):
    result = ok(client.post(base + "/stt-range", json=range_payload(identity(client, base))))
    compact = deepcopy(result)
    compact.pop("blocks", None)
    assert compact["save_receipt"]["kind"] == "native-stt-range-hmac-v1"
    assert len(compact["save_receipt"]["digest"]) == 64
    details = dict(kind="ST", status=status, end_sample=compact["range"]["end_sample"] - 1,
        finding="Mathematical source-unit range mean", range_statistics=compact)
    if point is not None:
        details["point_measurement_sample_index"] = point
    return dict(sample_index=compact["range"]["start_sample"], lead="II", category="note",
        label="数学区间统计", note="Synthetic review note; not a patient or diagnosis.", details=details)


@pytest.mark.parametrize("status", ["pending", "confirmed", "excluded"])
@pytest.mark.parametrize("point", [None, 15000])
def test_mean_signed_compact_save_get_reopen_preserves_full_provenance(
        synthetic_app, synthetic_case, tmp_path, status, point):
    client = synthetic_app.test_client()
    base = base_for(synthetic_case)
    store = synthetic_app.extensions["storage"]
    payload = mean_save_payload(client, base, status=status, point=point)
    compact = payload["details"]["range_statistics"]
    assert "blocks" not in compact
    before_review = store.get_review(synthetic_case[1])["revision"]
    response = client.post(base + "/annotations", json=payload)
    assert response.status_code == 201, response.get_json()
    saved = response.get_json()
    assert saved["sample_index"] == 0 and saved["details"]["end_sample"] == 11999
    assert saved["details"] == payload["details"]
    assert saved["note"] == payload["note"]
    assert store.get_review(synthetic_case[1])["revision"] == before_review + 1
    assert ok(client.get(base + "/annotations"))["items"] == [saved]
    after_save = rows(store)
    repeated = client.post(base + "/annotations", json=payload)
    assert repeated.status_code == 409, repeated.get_json()
    assert rows(store) == after_save
    reopened = create_app(data_root=synthetic_case[0], db_path=tmp_path / "case.db", testing=True)
    returned = ok(reopened.test_client().get(base + "/annotations"))["items"]
    assert returned == [saved]
    assert returned[0]["details"]["range_statistics"] == compact
    assert rows(reopened.extensions["storage"]) == after_save


@pytest.mark.parametrize("change", ["mean", "range", "scope", "mask", "method", "coverage",
                                   "missing_receipt", "wrong_receipt", "unattested_blocks"])
def test_mean_changed_or_unsigned_provenance_cannot_insert(
        synthetic_app, synthetic_case, change):
    client = synthetic_app.test_client()
    base = base_for(synthetic_case)
    store = synthetic_app.extensions["storage"]
    body = mean_save_payload(client, base)
    statistics = body["details"]["range_statistics"]
    if change == "mean":
        statistics["leads"][0]["mean_units"] = 123.25
    elif change == "range":
        statistics["range"]["end_sample"] -= 1
    elif change == "scope":
        statistics["scope"]["case_id"] = "synthetic-other-case"
    elif change == "mask":
        statistics["exclusions"]["intervals"] = []
        statistics["exclusions"]["digest"] = "tampered-mathematical-mask"
    elif change == "method":
        statistics["method_profile"]["calibration_verified"] = True
    elif change == "coverage":
        statistics["coverage"]["source_coverage_s"] = 1
    elif change == "missing_receipt":
        statistics.pop("save_receipt")
    elif change == "wrong_receipt":
        statistics["save_receipt"]["digest"] = "0" * 64
    else:
        statistics["blocks"] = []
    before = rows(store)
    response = client.post(base + "/annotations", json=body)
    assert response.status_code == (400 if change == "unattested_blocks" else 409), response.get_json()
    assert rows(store) == before


@pytest.mark.parametrize("field,value", [
    ("sample_index", 1), ("end_sample", 12000),
    ("point_measurement_sample_index", False), ("point_measurement_sample_index", 1.0),
    ("point_measurement_sample_index", -1), ("point_measurement_sample_index", 18000),
])
def test_mean_saved_annotation_bounds_and_separate_point_are_strict(
        synthetic_app, synthetic_case, field, value):
    client = synthetic_app.test_client()
    base = base_for(synthetic_case)
    store = synthetic_app.extensions["storage"]
    body = mean_save_payload(client, base)
    (body if field == "sample_index" else body["details"])[field] = value
    before = rows(store)
    response = client.post(base + "/annotations", json=body)
    assert response.status_code == 400, response.get_json()
    assert rows(store) == before


@pytest.mark.parametrize("which", ["global", "beat", "data", "ebi", "lps"])
def test_mean_saved_snapshot_rejects_changed_evidence_without_doctor_insert(
        synthetic_app, synthetic_case, which):
    client = synthetic_app.test_client()
    base = base_for(synthetic_case)
    store = synthetic_app.extensions["storage"]
    body = mean_save_payload(client, base)
    advance(store, synthetic_case[1], which, synthetic_case[2])
    before = rows(store)
    response = client.post(base + "/annotations", json=body)
    assert response.status_code == 409, response.get_json()
    assert rows(store)["annotations"] == before["annotations"] == []
    assert not any(x["action"] == "annotation.create" for x in store.list_audit())


@pytest.mark.parametrize("which", ["global", "beat", "data", "stored_basis"])
def test_mean_save_checks_again_under_the_sqlite_write_lock(
        synthetic_app, synthetic_case, monkeypatch, which):
    from ecg_core.storage import Storage
    client = synthetic_app.test_client()
    base = base_for(synthetic_case)
    store = synthetic_app.extensions["storage"]
    body = mean_save_payload(client, base)
    original = Storage.create_annotation
    entered = []
    def race_before_transaction(self, cid, payload, actor, **kwargs):
        assert callable(kwargs.get("guard")) and callable(kwargs.get("source_guard"))
        entered.append(True)
        if which == "stored_basis":
            import json
            with store.connect() as db:
                row = db.execute("SELECT basis FROM case_analysis_basis WHERE case_id=?", (cid,)).fetchone()
                value = json.loads(row[0])
                value["digest"] = "synthetic-replaced-stored-basis"
                db.execute("UPDATE case_analysis_basis SET basis=? WHERE case_id=?", (json.dumps(value), cid))
        else:
            advance(store, cid, which, synthetic_case[2])
        return original(self, cid, payload, actor, **kwargs)
    monkeypatch.setattr(Storage, "create_annotation", race_before_transaction)
    response = client.post(base + "/annotations", json=body)
    assert entered == [True]
    assert response.status_code == 409, response.get_json()
    assert rows(store)["annotations"] == []
    assert not any(x["action"] == "annotation.create" for x in store.list_audit())


def test_mean_source_change_after_own_audit_rolls_back_annotation_and_review(
        synthetic_app, synthetic_case, monkeypatch):
    client = synthetic_app.test_client()
    base = base_for(synthetic_case)
    store = synthetic_app.extensions["storage"]
    body = mean_save_payload(client, base)
    before = rows(store)
    original = store._audit
    def race_after_audit(db, *args, **kwargs):
        original(db, *args, **kwargs)
        advance(store, synthetic_case[1], "data", synthetic_case[2])
    monkeypatch.setattr(store, "_audit", race_after_audit)
    response = client.post(base + "/annotations", json=body)
    assert response.status_code == 409, response.get_json()
    assert rows(store) == before


def test_mean_attestation_cannot_reopen_under_a_reused_session_secret(
        synthetic_case, tmp_path, monkeypatch):
    # Stable session-cookie keys must not make a previous process's range
    # attestation reusable. This is a made-up key in an isolated math App.
    monkeypatch.setenv("ECG_SECRET_KEY", "synthetic-stable-session-key-only")
    root, _, _ = synthetic_case
    original = create_app(data_root=root, db_path=tmp_path / "restart.db", testing=True)
    base = base_for(synthetic_case)
    body = mean_save_payload(original.test_client(), base)
    reopened = create_app(data_root=root, db_path=tmp_path / "restart.db", testing=True)
    before = rows(reopened.extensions["storage"])
    response = reopened.test_client().post(base + "/annotations", json=body)
    assert response.status_code == 409, response.get_json()
    assert rows(reopened.extensions["storage"]) == before


@pytest.mark.parametrize("value", [[], None, {}])
def test_stt_range_caller_masks_cannot_replace_authoritative_saved_rhythm(
        synthetic_app, synthetic_case, value):
    client = synthetic_app.test_client()
    base = base_for(synthetic_case)
    before = rows(synthetic_app.extensions["storage"])
    body = range_payload(identity(client, base), exclusions=value)
    # Prime the source identity before the no-mutation comparison.
    before = rows(synthetic_app.extensions["storage"])
    response = client.post(base + "/stt-range", json=body)
    assert response.status_code == 400, response.get_json()
    assert rows(synthetic_app.extensions["storage"]) == before


@pytest.mark.parametrize("field", ["analysis_revision", "beat_revision"])
@pytest.mark.parametrize("value", [False, -1, 0.0, "0"])
def test_stt_range_scope_revisions_are_nonnegative_integers(
        synthetic_app, synthetic_case, field, value):
    client = synthetic_app.test_client()
    base = base_for(synthetic_case)
    scope = identity(client, base)
    scope[field] = value
    before = rows(synthetic_app.extensions["storage"])
    response = client.post(base + "/stt-range", json=range_payload(scope))
    assert response.status_code == 400, response.get_json()
    assert rows(synthetic_app.extensions["storage"]) == before


def uuid_mean_payload(client, base):
    body = mean_save_payload(client, base)
    body["details"]["submission_id"] = str(uuid4())
    return body


@pytest.mark.parametrize("reopen", [False, True])
def test_mean_uuid_saved_retry_is_exact_ack_without_duplicate_or_audit(
        synthetic_app, synthetic_case, tmp_path, reopen):
    client = synthetic_app.test_client()
    base = base_for(synthetic_case)
    body = uuid_mean_payload(client, base)
    response = client.post(base + "/annotations", json=body)
    assert response.status_code == 201, response.get_json()
    saved = response.get_json()
    assert saved["details"] == body["details"]
    app = (create_app(data_root=synthetic_case[0], db_path=tmp_path / "case.db", testing=True)
           if reopen else synthetic_app)
    store = app.extensions["storage"]
    before = rows(store)
    retry = app.test_client().post(base + "/annotations", json=deepcopy(body))
    assert retry.status_code == 201, retry.get_json()
    assert retry.get_json() == saved
    assert rows(store) == before
    assert ok(app.test_client().get(base + "/annotations"))["items"] == [saved]
    assert len([item for item in store.list_audit() if item["action"] == "annotation.create"]) == 1


def test_mean_uuid_unsaved_receipt_cannot_survive_app_reopen(
        synthetic_app, synthetic_case, tmp_path):
    base = base_for(synthetic_case)
    body = uuid_mean_payload(synthetic_app.test_client(), base)
    app = create_app(data_root=synthetic_case[0], db_path=tmp_path / "case.db", testing=True)
    before = rows(app.extensions["storage"])
    response = app.test_client().post(base + "/annotations", json=body)
    assert response.status_code == 409, response.get_json()
    assert rows(app.extensions["storage"]) == before


def test_mean_valid_process_receipt_cannot_save_into_another_mathematical_case(
        synthetic_case, tmp_path):
    root, cid, source_paths = synthetic_case
    other_id = "8888888888888888"
    destinations = {
        "data": root / other_id / "data" / (other_id + ".DATA"),
        "ebi": root / other_id / "DGS" / (other_id + ".EBI"),
        "lps": root / other_id / "report_image" / (other_id + "_1.LPS"),
    }
    for kind, path in destinations.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(source_paths[kind].read_bytes())
    app = create_app(data_root=root, db_path=tmp_path / "two-mathematical-cases.db", testing=True)
    client = app.test_client()
    body = uuid_mean_payload(client, "/api/cases/" + cid)
    other_base = "/api/cases/" + other_id
    identity(client, other_base)
    store = app.extensions["storage"]
    before = rows(store)
    response = client.post(other_base + "/annotations", json=body)
    assert response.status_code == 409, response.get_json()
    assert rows(store) == before


@pytest.mark.parametrize("which", ["global", "beat", "data", "ebi", "lps"])
def test_mean_uuid_saved_retry_rejects_changed_source_or_beat_identity(
        synthetic_app, synthetic_case, which):
    client = synthetic_app.test_client()
    base = base_for(synthetic_case)
    store = synthetic_app.extensions["storage"]
    body = uuid_mean_payload(client, base)
    saved_response = client.post(base + "/annotations", json=body)
    assert saved_response.status_code == 201, saved_response.get_json()
    advance(store, synthetic_case[1], which, synthetic_case[2])
    before = rows(store)
    response = client.post(base + "/annotations", json=body)
    assert response.status_code == 409, response.get_json()
    assert rows(store)["annotations"] == before["annotations"]
    if which in ("global", "beat"):
        assert rows(store) == before
    assert len([item for item in store.list_audit() if item["action"] == "annotation.create"]) == 1


@pytest.mark.parametrize("field", ["note", "label", "status", "point", "statistics"])
def test_mean_uuid_same_identifier_different_intent_never_overwrites(
        synthetic_app, synthetic_case, field):
    client = synthetic_app.test_client()
    base = base_for(synthetic_case)
    store = synthetic_app.extensions["storage"]
    body = uuid_mean_payload(client, base)
    saved = client.post(base + "/annotations", json=body)
    assert saved.status_code == 201, saved.get_json()
    changed = deepcopy(body)
    if field in ("note", "label"):
        changed[field] += " changed mathematical intent"
    elif field == "status":
        changed["details"]["status"] = "confirmed"
    elif field == "point":
        changed["details"]["point_measurement_sample_index"] += 1
    else:
        changed["details"]["range_statistics"]["leads"][0]["mean_units"] = 123.25
    before = rows(store)
    response = client.post(base + "/annotations", json=changed)
    assert response.status_code == 409, response.get_json()
    assert rows(store) == before


@pytest.mark.parametrize("identifier", [False, 1, None, "not-a-uuid",
    "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA", "aaaaaaaaaaaa4aaa8aaaaaaaaaaaaaaa"])
def test_mean_uuid_is_canonical_lowercase_and_strictly_typed(
        synthetic_app, synthetic_case, identifier):
    client = synthetic_app.test_client()
    base = base_for(synthetic_case)
    store = synthetic_app.extensions["storage"]
    body = mean_save_payload(client, base)
    body["details"]["submission_id"] = identifier
    before = rows(store)
    response = client.post(base + "/annotations", json=body)
    assert response.status_code == 400, response.get_json()
    assert rows(store) == before


@pytest.mark.parametrize("receipt", ["\u6570" * 64, "A" * 64, "a" * 63])
def test_mean_receipt_malformed_hex_is_conflict_without_server_error(
        synthetic_app, synthetic_case, receipt):
    client = synthetic_app.test_client()
    base = base_for(synthetic_case)
    store = synthetic_app.extensions["storage"]
    body = mean_save_payload(client, base)
    body["details"]["range_statistics"]["save_receipt"]["digest"] = receipt
    before = rows(store)
    response = client.post(base + "/annotations", json=body)
    assert response.status_code == 409, response.get_json()
    assert rows(store) == before


def test_mean_concurrent_same_uuid_inserts_once_and_advances_review_once(
        synthetic_app, synthetic_case, monkeypatch):
    from ecg_core.storage import Storage
    base = base_for(synthetic_case)
    store = synthetic_app.extensions["storage"]
    body = uuid_mean_payload(synthetic_app.test_client(), base)
    before_revision = store.get_review(synthetic_case[1])["revision"]
    barrier = Barrier(2)
    original = Storage.create_annotation
    def both_valid_before_lock(self, cid, payload, actor, **kwargs):
        assert self is store
        barrier.wait(timeout=20)
        return original(self, cid, payload, actor, **kwargs)
    monkeypatch.setattr(Storage, "create_annotation", both_valid_before_lock)
    def submit():
        with synthetic_app.test_client() as client:
            response = client.post(base + "/annotations", json=deepcopy(body))
            return response.status_code, response.get_json()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit) for _ in range(2)]
        responses = [future.result(timeout=30) for future in futures]
    assert [status for status, _ in responses] == [201, 201], responses
    assert responses[0][1] == responses[1][1]
    assert len(rows(store)["annotations"]) == 1
    assert store.get_review(synthetic_case[1])["revision"] == before_revision + 1
    assert len([item for item in store.list_audit() if item["action"] == "annotation.create"]) == 1


@pytest.mark.parametrize("which", ["global", "beat", "data", "stored_basis"])
def test_mean_uuid_lock_reconciliation_rechecks_current_evidence(
        synthetic_app, synthetic_case, monkeypatch, which):
    from ecg_core.storage import Storage
    client = synthetic_app.test_client()
    base = base_for(synthetic_case)
    store = synthetic_app.extensions["storage"]
    body = uuid_mean_payload(client, base)
    if which == "data":
        # Keep the original late-source mutation and every reconciliation assert.
        # Default Windows sharing prevents the write before that checkpoint;
        # its denial and preserved winner are independently tested below.
        monkeypatch.setitem(synthetic_app.config, "WINDOWS_REQUEST_SOURCE_LEASES", False)
    original = Storage.create_annotation
    checkpoint = []
    def another_submit_finishes_after_preflight(self, cid, payload, actor, **kwargs):
        # Both intents passed the outer read before either save existed. The
        # first request commits; evidence changes before the second gets its
        # SQLite write lock. A same-UUID lookup must still validate that evidence.
        first = original(self, cid, payload, actor, **kwargs)
        assert first["details"] == body["details"]
        if which == "stored_basis":
            import json
            with store.connect() as db:
                value = json.loads(db.execute(
                    "SELECT basis FROM case_analysis_basis WHERE case_id=?", (cid,)).fetchone()[0])
                value["digest"] = "synthetic-raced-persisted-basis"
                db.execute("UPDATE case_analysis_basis SET basis=? WHERE case_id=?", (json.dumps(value), cid))
        else:
            advance(store, cid, which, synthetic_case[2])
        checkpoint.append(rows(store))
        return original(self, cid, payload, actor, **kwargs)
    monkeypatch.setattr(Storage, "create_annotation", another_submit_finishes_after_preflight)
    response = client.post(base + "/annotations", json=body)
    assert len(checkpoint) == 1
    assert response.status_code == 409, response.get_json()
    assert rows(store) == checkpoint[0]
    assert len(rows(store)["annotations"]) == 1
    assert len([item for item in store.list_audit() if item["action"] == "annotation.create"]) == 1


@pytest.mark.skipif(os.name != "nt", reason="requires actual Windows request share-mode lease")
def test_windows_default_source_lease_blocks_uuid_reconciliation_source_write(
        synthetic_app, synthetic_case, monkeypatch):
    from ecg_core.storage import Storage
    assert synthetic_app.config["WINDOWS_REQUEST_SOURCE_LEASES"] is True
    client = synthetic_app.test_client()
    base = base_for(synthetic_case)
    store = synthetic_app.extensions["storage"]
    cid, paths = synthetic_case[1:]
    body = uuid_mean_payload(client, base)
    before_source = {key: sha256(path.read_bytes()).hexdigest() for key, path in paths.items()}
    original = Storage.create_annotation
    calls = {"original": 0, "denied": 0}
    checkpoint, winner = [], []

    def call_original(self, case_id, payload, actor, **kwargs):
        calls["original"] += 1
        return original(self, case_id, payload, actor, **kwargs)

    def first_wins_then_source_write_is_attempted(self, case_id, payload, actor, **kwargs):
        assert self is store
        first = call_original(self, case_id, payload, actor, **kwargs)
        assert first["details"] == body["details"]
        winner.append(first)
        checkpoint.append(rows(store))
        try:
            advance(store, case_id, "data", paths)
        except PermissionError:
            calls["denied"] += 1
            raise
        return call_original(self, case_id, payload, actor, **kwargs)

    monkeypatch.setattr(Storage, "create_annotation", first_wins_then_source_write_is_attempted)
    response = client.post(base + "/annotations", json=body)
    assert response.status_code == 409, response.get_json()
    assert response.get_json()["code"] == "report_conflict"
    assert calls == {"original": 1, "denied": 1}
    assert len(checkpoint) == len(winner) == 1
    assert rows(store) == checkpoint[0]
    assert store.list_annotations(cid) == winner
    assert len([item for item in store.list_audit()
                if item["action"] == "annotation.create"]) == 1
    assert {key: sha256(path.read_bytes()).hexdigest() for key, path in paths.items()} == before_source
    with paths["data"].open("r+b"):
        pass  # Actual teardown must release the write-denying source handle.


@pytest.mark.parametrize("which", ["global", "beat", "stored_basis"])
def test_mean_after_own_audit_revalidates_all_locked_revisions_and_rolls_back(
        synthetic_app, synthetic_case, monkeypatch, which):
    import json
    client = synthetic_app.test_client()
    base = base_for(synthetic_case)
    cid = synthetic_case[1]
    store = synthetic_app.extensions["storage"]
    body = uuid_mean_payload(client, base)
    document = BeatEditorStore(store).snapshot(cid)["document"]
    before = rows(store)
    original = store._audit
    def change_locked_revision(db, *args, **kwargs):
        original(db, *args, **kwargs)
        if which == "global":
            original(db, "synthetic-reviewer", "beat_override.editor", cid)
        elif which == "beat":
            existing = db.execute(
                "SELECT revision FROM beat_edit_documents WHERE case_id=?", (cid,)).fetchone()
            if existing:
                db.execute("UPDATE beat_edit_documents SET revision=revision+1 WHERE case_id=?", (cid,))
            else:
                db.execute("INSERT INTO beat_edit_documents VALUES(?,?,?,?,?)",
                           (cid, 1, json.dumps(document), "[]", "[]"))
        else:
            value = json.loads(db.execute(
                "SELECT basis FROM case_analysis_basis WHERE case_id=?", (cid,)).fetchone()[0])
            value["digest"] = "synthetic-late-persisted-basis"
            db.execute("UPDATE case_analysis_basis SET basis=? WHERE case_id=?", (json.dumps(value), cid))
    monkeypatch.setattr(store, "_audit", change_locked_revision)
    response = client.post(base + "/annotations", json=body)
    assert response.status_code == 409, response.get_json()
    assert rows(store) == before
