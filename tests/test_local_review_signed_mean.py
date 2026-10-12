"""Signed range summaries survive the real masked local-review response chain.

Only the disposable 90-second mathematical fixture is read or edited. The
after_request observer below returns the original response untouched; neither
the server HMAC implementation nor any identity/write guard is replaced.
"""
from copy import deepcopy
import json
import math
import re
import subprocess
from types import SimpleNamespace
from uuid import uuid4

from flask import request as flask_request
import pytest

from scripts.serve_local_review import create_review_app
from test_analysis_provenance import synthetic_case
from test_stt_range import synthetic as mathematical_signal
from test_doctor_feedback_api import (
    IDENTITY_FIELDS, advance, install_zero_mean_signal, ok, range_payload, rows,
)


@pytest.fixture
def review_app(synthetic_case, tmp_path, monkeypatch, request):
    monkeypatch.setenv("ECG_ALLOW_PHI", "0")
    monkeypatch.setenv("ECG_DEMO_READONLY", "0")
    monkeypatch.setenv("ECG_DEMO_PASSWORD", "")
    monkeypatch.setenv("ECG_TRUST_PROXY_HEADERS", "0")
    install_zero_mean_signal(synthetic_case)
    root, cid, paths = synthetic_case
    options = getattr(request, "param", 1)
    if isinstance(options, dict) and options.get("signal") == "nonintegral":
        raw, anchors = mathematical_signal(seconds=90, delta=lambda _: 0)
        # A constant integer plateau after QRS yields 1/2 alternating source
        # differences at all three offsets; the 58 API-eligible beats give
        # II=1.5 and derived aVL=0.75 without asserting a clinical threshold.
        for anchor in anchors:
            sample = anchor["sample_index"]
            raw[sample + 4:sample + 60] += 1 if sample // 200 % 2 else 2
        paths["data"].write_bytes(raw.tobytes())
    # Invented strings make the masking observable without an identity lookup.
    marker = dict(name="Synthetic Name Marker", patient_id="SYNTHETIC-ID-MARKER",
                  requesting_physician="Synthetic Physician Marker")
    extra_shapes = ("<PShape>姓名:" + marker["name"] + "</PShape>"
                    "<PShape>ID号:" + marker["patient_id"] + "</PShape>"
                    "<PShape>申请医生:" + marker["requesting_physician"] + "</PShape>")
    paths["lps"].write_text(paths["lps"].read_text(encoding="utf-8").replace(
        "</root>", extra_shapes + "</root>"), encoding="utf-8")
    other_id = None
    if (options.get("case_count", 1) if isinstance(options, dict) else options) == 2:
        other_id = "8888888888888888"
        destinations = {
            "data": root / other_id / "data" / (other_id + ".DATA"),
            "ebi": root / other_id / "DGS" / (other_id + ".EBI"),
            "lps": root / other_id / "report_image" / (other_id + "_1.LPS"),
        }
        for kind, path in destinations.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(paths[kind].read_bytes())
    workspace = tmp_path / "isolated-review-workspace"
    arguments = dict(source_kind="mathematical_synthetic", purpose="isolated_verification",
                     release_id="synthetic-signed-mean-review")
    app = create_review_app(root, workspace, **arguments)
    assert app.config["ALLOW_PHI"] is False
    assert app.config["TESTING"] is False
    observed = []

    @app.after_request
    def observe_before_local_presentation(response):
        # Flask runs these functions in reverse registration order, so this
        # observes the actual signed JSON before the installed presenter runs.
        if response.is_json:
            observed.append((flask_request.path, response.status_code,
                             deepcopy(response.get_json())))
        return response

    return SimpleNamespace(app=app, client=app.test_client(), case=synthetic_case,
        base="/api/cases/" + cid, cid=cid, other_id=other_id, workspace=workspace,
        arguments=arguments, marker=marker, observed=observed)


def post(review, suffix, body, *, client=None, base=None):
    return (client or review.client).post((base or review.base) + suffix, json=body,
                                         headers={"X-CardioInsight-Request": "1"})


def signed_range(review, *, measurement_ms=60, leads=None, negative_zero=False):
    current = ok(review.client.get(review.base + "/rhythm-review"))
    assert current["display_case_id"] == review.app.config["REPORT_CASE_DISPLAY_IDS"][review.cid]
    scope = {key: current[key] for key in IDENTITY_FIELDS}
    # This fake nested value is part of the echoed, signed caller scope; the
    # presenter must not inject aliases or mutate arbitrary metadata inside it.
    scope.update(client_nonce=str(uuid4()), client_view=dict(case_id=review.cid,
        metadata=dict(name="Synthetic signed scope marker")))
    if negative_zero:
        scope["client_view"]["numeric_zero"] = -0.0
    response = post(review, "/stt-range", range_payload(
        scope, measurement_ms=measurement_ms, leads=leads or ["II"]))
    result = ok(response)
    raw = next(value for path, status, value in reversed(review.observed)
               if path == review.base + "/stt-range" and status == 200)
    assert result == raw
    assert result["scope"] == scope
    assert {key: result["server_identity"][key] for key in IDENTITY_FIELDS} == {
        key: scope[key] for key in IDENTITY_FIELDS}
    assert "display_case_id" not in result["scope"]
    assert "display_case_id" not in result["server_identity"]
    assert result["scope"]["client_view"]["metadata"]["name"] == "Synthetic signed scope marker"
    assert result["save_receipt"]["kind"] == "native-stt-range-hmac-v1"
    assert re.fullmatch("[0-9a-f]{64}", result["save_receipt"]["digest"])
    assert "blocks" not in result
    assert result["physician_document_written"] is False
    return result


def save_intent(statistics, status="pending"):
    return dict(sample_index=statistics["range"]["start_sample"], lead="II", category="note",
        label="Synthetic range review", note="Mathematical test note only",
        details=dict(kind="ST", status=status, end_sample=statistics["range"]["end_sample"] - 1,
                     finding="Synthetic source-unit mean", range_statistics=deepcopy(statistics),
                     point_measurement_sample_index=15000, submission_id=str(uuid4())))


def assert_normal_case_masked(review, client=None):
    client = client or review.client
    value = ok(client.get(review.base, query_string=dict(include_phi=1)))
    assert value["display_case_id"] == review.app.config["REPORT_CASE_DISPLAY_IDS"][review.cid]
    assert value["phi_masked"] is True
    assert {key: value["metadata"][key] for key in review.marker} == {
        key: "已遮蔽" for key in review.marker}
    serialized = str(value)
    assert all(marker not in serialized for marker in review.marker.values())
    assert "paths" not in value


@pytest.mark.parametrize("status", ["pending", "confirmed", "excluded"])
def test_masked_after_request_preserves_signed_compact_save_get_and_reopen(review_app, status):
    review = review_app
    assert_normal_case_masked(review)
    context = ok(review.client.get("/api/local-review-context"))
    assert context["source_kind"] == "mathematical_synthetic"
    assert context["phi_visible"] is False and context["source_files_readonly"] is True
    statistics = signed_range(review)
    body = save_intent(statistics, status)
    response = post(review, "/annotations", body)
    assert response.status_code == 201, response.get_json()
    saved = response.get_json()
    assert saved["display_case_id"] == "C01"
    assert saved["details"] == body["details"]
    assert saved["details"]["range_statistics"] == statistics
    raw = next(value for path, code, value in reversed(review.observed)
               if path == review.base + "/annotations" and code == 201)
    assert raw["details"]["range_statistics"] == statistics
    assert ok(review.client.get(review.base + "/annotations"))["items"] == [saved]
    store = review.app.extensions["storage"]
    after = rows(store)
    reopened = create_review_app(review.case[0], review.workspace, **review.arguments)
    reopened_client = reopened.test_client()
    assert ok(reopened_client.get(review.base + "/annotations"))["items"] == [saved]
    retry = post(review, "/annotations", body, client=reopened_client)
    assert retry.status_code == 201 and retry.get_json() == saved
    assert_normal_case_masked(review, reopened_client)
    assert rows(reopened.extensions["storage"]) == after


@pytest.mark.parametrize("change", ["mean", "scope", "server_identity", "receipt"])
def test_masked_after_request_does_not_make_tampered_summaries_saveable(review_app, change):
    review = review_app
    statistics = signed_range(review)
    body = save_intent(statistics)
    altered = body["details"]["range_statistics"]
    if change == "mean":
        altered["leads"][0]["mean_units"] = 123.25
    elif change == "scope":
        altered["scope"]["client_view"]["metadata"]["name"] += " changed"
    elif change == "server_identity":
        altered["server_identity"]["beat_revision"] += 1
    else:
        altered["save_receipt"]["digest"] = "0" * 64
    store = review.app.extensions["storage"]
    before = rows(store)
    response = post(review, "/annotations", body)
    assert response.status_code == 409, response.get_json()
    assert rows(store) == before
    assert_normal_case_masked(review)


@pytest.mark.parametrize("change", ["global", "beat", "data"])
def test_masked_review_stale_signed_mean_cannot_insert(review_app, change):
    review = review_app
    statistics = signed_range(review)
    store = review.app.extensions["storage"]
    advance(store, review.cid, change, review.case[2])
    before_annotations = rows(store)["annotations"]
    response = post(review, "/annotations", save_intent(statistics))
    assert response.status_code == 409, response.get_json()
    assert rows(store)["annotations"] == before_annotations == []
    assert not any(item["action"] == "annotation.create" for item in store.list_audit())


@pytest.mark.parametrize("review_app", [2], indirect=True)
def test_masked_review_real_signed_mean_cannot_cross_mathematical_cases(review_app):
    review = review_app
    statistics = signed_range(review)
    other_base = "/api/cases/" + review.other_id
    assert ok(review.client.get(other_base))["display_case_id"] != (
        review.app.config["REPORT_CASE_DISPLAY_IDS"][review.cid])
    store = review.app.extensions["storage"]
    before = rows(store)
    response = post(review, "/annotations", save_intent(statistics), base=other_base)
    assert response.status_code == 409, response.get_json()
    assert rows(store) == before


def test_masked_review_unsaved_receipt_is_invalid_after_app_reopen(review_app):
    review = review_app
    body = save_intent(signed_range(review))
    reopened = create_review_app(review.case[0], review.workspace, **review.arguments)
    store = reopened.extensions["storage"]
    before = rows(store)
    response = post(review, "/annotations", body, client=reopened.test_client())
    assert response.status_code == 409, response.get_json()
    assert rows(store) == before


def node_json_wire(value):
    """Actual ECMAScript number serialization, without replacing any server code."""
    result = subprocess.run(["node", "-e",
        "const fs=require('fs');process.stdout.write(JSON.stringify(JSON.parse(fs.readFileSync(0,'utf8'))));"],
        input=json.dumps(value, ensure_ascii=False, allow_nan=False),
        capture_output=True, text=True, encoding="utf-8", check=True, timeout=10)
    return result.stdout


def number_type_changes(before, after, path=""):
    if isinstance(before, dict):
        return [change for key in before for change in number_type_changes(
            before[key], after[key], path + "/" + str(key))]
    if isinstance(before, list):
        return [change for i, value in enumerate(before) for change in number_type_changes(
            value, after[i], path + "/" + str(i))]
    if type(before) in (int, float) and type(after) in (int, float):
        negative_before = before == 0 and math.copysign(1, before) < 0
        negative_after = after == 0 and math.copysign(1, after) < 0
        if type(before) is not type(after) or negative_before != negative_after:
            return [dict(path=path, before_type=type(before).__name__, after_type=type(after).__name__,
                         negative_zero_before=negative_before, negative_zero_after=negative_after)]
    return []


def test_real_node_roundtrip_60ms_zero_can_save_native_signed_mean(review_app):
    review = review_app
    statistics = signed_range(review)
    assert statistics["leads"][0]["mean_units"] == 0
    body = save_intent(statistics)
    wire = node_json_wire(body)
    decoded = json.loads(wire)
    assert decoded == body  # numerical equivalence, not Python's number spelling
    changes = number_type_changes(body, decoded)
    assert any(item["path"].endswith("/range/duration_s") for item in changes)
    before = rows(review.app.extensions["storage"])
    response = review.client.post(review.base + "/annotations", data=wire,
        content_type="application/json", headers={"X-CardioInsight-Request": "1"})
    print(json.dumps(dict(number_type_changes=changes, status=response.status_code,
                         error=response.get_json() if response.status_code != 201 else None)))
    if response.status_code != 201:
        assert rows(review.app.extensions["storage"]) == before
    assert response.status_code == 201, dict(error=response.get_json(), number_type_changes=changes)
    assert response.get_json()["details"]["range_statistics"] == decoded["details"]["range_statistics"]


ALL_LEADS = ["I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6"]


def node_save(review, statistics):
    wire = node_json_wire(save_intent(statistics))
    body = json.loads(wire)
    assert body["details"]["range_statistics"] == statistics
    response = review.client.post(review.base + "/annotations", data=wire,
        content_type="application/json", headers={"X-CardioInsight-Request": "1"})
    assert response.status_code == 201, response.get_json()
    saved = response.get_json()
    assert saved["details"] == body["details"]
    assert saved["display_case_id"] == "C01"
    assert ok(review.client.get(review.base + "/annotations"))["items"][-1] == saved
    after = rows(review.app.extensions["storage"])
    reopened = create_review_app(review.case[0], review.workspace, **review.arguments)
    returned = ok(reopened.test_client().get(review.base + "/annotations"))["items"]
    assert returned[-1] == saved
    assert returned[-1]["details"]["range_statistics"] == body["details"]["range_statistics"]
    assert rows(reopened.extensions["storage"]) == after
    return saved


@pytest.mark.parametrize("measurement", [0, 60, 80])
@pytest.mark.parametrize("empty", [False, True], ids=["known-zero", "null"])
@pytest.mark.parametrize("negative_zero", [False, True], ids=["positive-zero", "negative-zero"])
def test_real_node_roundtrip_all_leads_zero_null_and_negative_zero_are_numerically_exact(
        review_app, measurement, empty, negative_zero):
    review = review_app
    if empty:
        mask = post(review, "/annotations", dict(sample_index=0, lead="全部", category="note",
            label="Synthetic full-range rhythm mask", note="Mathematical exclusion only",
            details=dict(kind="AF", status="confirmed", end_sample=11999, finding="Synthetic mask")))
        assert mask.status_code == 201, mask.get_json()
    statistics = signed_range(review, measurement_ms=measurement, leads=ALL_LEADS,
                              negative_zero=negative_zero)
    assert [item["lead"] for item in statistics["leads"]] == ALL_LEADS
    assert all(item["mean_units"] is None if empty else item["mean_units"] == 0
               for item in statistics["leads"])
    if empty:
        assert statistics["counts"]["used_count"] == 0
        assert statistics["coverage"]["used_anchor_span_s"] is None
    if negative_zero:
        assert math.copysign(1, statistics["scope"]["client_view"]["numeric_zero"]) < 0
        decoded = json.loads(node_json_wire(statistics))
        assert decoded["scope"]["client_view"]["numeric_zero"] == 0
        assert math.copysign(1, decoded["scope"]["client_view"]["numeric_zero"]) > 0
    node_save(review, statistics)


@pytest.mark.parametrize("review_app", [{"signal": "nonintegral"}], indirect=True)
@pytest.mark.parametrize("measurement", [0, 60, 80])
def test_real_node_roundtrip_preserves_nonintegral_twelve_lead_means(review_app, measurement):
    statistics = signed_range(review_app, measurement_ms=measurement, leads=ALL_LEADS)
    assert [item["lead"] for item in statistics["leads"]] == ALL_LEADS
    leads = {item["lead"]: item for item in statistics["leads"]}
    assert leads["II"]["mean_units"] == 1.5
    assert leads["aVL"]["mean_units"] == 0.75
    assert statistics["counts"]["used_count"] == 58
    node_save(review_app, statistics)


@pytest.mark.parametrize("measurement", [0, 60, 80])
def test_real_node_roundtrip_does_not_accept_mean_plus_one_tampering(review_app, measurement):
    review = review_app
    statistics = signed_range(review, measurement_ms=measurement, leads=ALL_LEADS)
    body = save_intent(statistics)
    body["details"]["range_statistics"]["leads"][0]["mean_units"] += 1
    store = review.app.extensions["storage"]
    before = rows(store)
    response = review.client.post(review.base + "/annotations", data=node_json_wire(body),
        content_type="application/json", headers={"X-CardioInsight-Request": "1"})
    assert response.status_code == 409, response.get_json()
    assert rows(store) == before


@pytest.mark.parametrize("change", ["global", "beat", "data"])
def test_real_node_roundtrip_stale_evidence_does_not_insert(review_app, change):
    review = review_app
    body = save_intent(signed_range(review, leads=ALL_LEADS))
    store = review.app.extensions["storage"]
    advance(store, review.cid, change, review.case[2])
    before_annotations = rows(store)["annotations"]
    response = review.client.post(review.base + "/annotations", data=node_json_wire(body),
        content_type="application/json", headers={"X-CardioInsight-Request": "1"})
    assert response.status_code == 409, response.get_json()
    assert rows(store)["annotations"] == before_annotations == []
    assert not any(item["action"] == "annotation.create" for item in store.list_audit())


@pytest.mark.parametrize("field", ["analysis_revision", "beat_revision"])
@pytest.mark.parametrize("endpoint", ["range", "save", "stt-review", "rhythm"])
def test_receipt_number_canonicalization_does_not_relax_typed_revision_guards(
        review_app, field, endpoint):
    review = review_app
    statistics = signed_range(review)
    scope = {key: statistics["scope"][key] for key in IDENTITY_FIELDS}
    scope[field] = float(scope[field])
    store = review.app.extensions["storage"]
    before = rows(store)
    if endpoint == "range":
        response = post(review, "/stt-range", range_payload(scope))
        expected = 400
    elif endpoint == "save":
        body = save_intent(statistics)
        body["details"]["range_statistics"]["scope"][field] = scope[field]
        response = post(review, "/annotations", body)
        expected = 409
    elif endpoint == "stt-review":
        response = review.client.get(review.base + "/stt-review", query_string=scope)
        expected = 400 if field == "beat_revision" else 409
    else:
        current = ok(review.client.get(review.base + "/rhythm-review"))
        response = review.client.put(review.base + "/rhythm-review", json=dict(
            scope, revision=current["revision"], confirmed=True,
            document=dict(episodes=[], bookmarks={})), headers={"X-CardioInsight-Request": "1"})
        expected = 409
    assert response.status_code == expected, response.get_json()
    assert rows(store) == before


@pytest.mark.parametrize("change", ["mean_zero_to_boolean", "boolean_to_number"])
def test_receipt_canonicalization_never_equates_booleans_with_numeric_zero(review_app, change):
    review = review_app
    body = save_intent(signed_range(review))
    statistics = body["details"]["range_statistics"]
    if change == "mean_zero_to_boolean":
        assert statistics["leads"][0]["mean_units"] == 0
        statistics["leads"][0]["mean_units"] = False
    else:
        assert statistics["method_profile"]["calibration_verified"] is False
        statistics["method_profile"]["calibration_verified"] = 0
    store = review.app.extensions["storage"]
    before = rows(store)
    response = review.client.post(review.base + "/annotations", data=node_json_wire(body),
        content_type="application/json", headers={"X-CardioInsight-Request": "1"})
    assert response.status_code == 409, response.get_json()
    assert rows(store) == before
