from __future__ import annotations

from io import BytesIO
import time

from app import create_app


def _case_id(client, *, prefer_ventricular: bool = False) -> str:
    items = client.get("/api/cases").json["items"]
    assert items
    if prefer_ventricular:
        return max(items, key=lambda item: item["summary"].get("ventricular_beats") or 0)["case_id"]
    return items[0]["case_id"]


def test_health_and_dashboard_default_to_masked_phi(client):
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json["case_count"] == 10
    dashboard = client.get("/api/dashboard").json
    assert dashboard["totals"]["cases"] == 10
    assert dashboard["totals"]["beats"] > 0
    first = dashboard["cases"][0]
    assert first["phi_masked"] is True
    assert "*" in first["metadata"]["name"]


def test_phi_requires_explicit_query_and_is_audited(client):
    masked = client.get("/api/cases").json["items"][0]
    assert masked["report_image_urls"] == []

    query_without_session_grant = client.get("/api/cases?include_phi=1").json["items"][0]
    assert query_without_session_grant["phi_masked"] is True
    assert client.post("/api/privacy/view", json={"enabled": True}).status_code == 200
    raw = client.get("/api/cases?include_phi=1").json["items"][0]
    assert raw["phi_masked"] is False
    assert "*" not in raw["metadata"]["name"]
    assert raw["report_image_urls"]
    assert client.post("/api/privacy/view", json={"enabled": False}).status_code == 200
    assert client.get("/api/cases?include_phi=1").json["items"][0]["phi_masked"] is True
    audit = client.get("/api/audit").json["items"]
    assert any(item["action"] == "privacy.phi_view" for item in audit)
    assert any(item["action"] == "privacy.phi_hide" for item in audit)


def test_production_mutations_require_local_ui_header(data_root, tmp_path):
    production = create_app(data_root=data_root, db_path=tmp_path / "guard.db", testing=False)
    client = production.test_client()
    blocked = client.post("/api/privacy/view", json={"enabled": True})
    assert blocked.status_code == 403
    allowed = client.post(
        "/api/privacy/view",
        json={"enabled": True},
        headers={"X-CardioInsight-Request": "1"},
    )
    assert allowed.status_code == 200


def test_source_report_image_requires_explicit_phi_access(client):
    case_id = _case_id(client)
    blocked = client.get(f"/api/cases/{case_id}/source-report/page/1")
    assert blocked.status_code == 403
    assert client.get(f"/api/cases/{case_id}/source-report/page/1?include_phi=1").status_code == 403
    client.post("/api/privacy/view", json={"enabled": True})
    allowed = client.get(f"/api/cases/{case_id}/source-report/page/1?include_phi=1")
    assert allowed.status_code == 200
    assert allowed.mimetype == "image/png"
    assert allowed.data.startswith(b"\x89PNG")


def test_integrity_manifest_state_is_consistent(client):
    settings = client.get("/api/settings").json
    details = [client.get(f"/api/cases/{item['case_id']}").json for item in client.get("/api/cases").json["items"]]
    manifest = settings["integrity_manifest"]
    if manifest["available"]:
        assert manifest["case_count"] == 10
        assert len(manifest["dataset_sha256"]) == 64
        assert all(detail["integrity"]["manifest_available"] is True for detail in details)
    else:
        assert manifest["case_count"] == 0
        assert all(detail["integrity"]["manifest_available"] is False for detail in details)


def test_mutation_endpoints_reject_invalid_json_and_ranges(client):
    case_id = _case_id(client)
    assert client.post("/api/privacy/view", json=["bad"]).status_code == 400
    assert client.post("/api/privacy/view", json={"enabled": "yes"}).status_code == 400
    assert client.patch(f"/api/cases/{case_id}/patient", json=["bad"]).status_code == 400
    assert client.put(f"/api/cases/{case_id}/report", json=["bad"]).status_code == 400
    assert client.put(f"/api/cases/{case_id}/report", json={"conclusion": [], "status": "draft"}).status_code == 400
    assert client.post(f"/api/cases/{case_id}/annotations", json={"sample_index": -1}).status_code == 400
    assert client.post(f"/api/cases/{case_id}/annotations", json={"sample_index": 999_999_999}).status_code == 400
    assert client.post(f"/api/cases/{case_id}/annotations", json={"sample_index": 100, "lead": "BAD"}).status_code == 400
    assert client.get("/api/dashboard").status_code == 200


def test_waveform_events_trend_and_hrv_endpoints(client):
    case_id = _case_id(client, prefer_ventricular=True)
    start = time.perf_counter()
    response = client.get(f"/api/cases/{case_id}/waveform?start=60&duration=10&leads=II,V1,V5")
    elapsed = time.perf_counter() - start
    assert response.status_code == 200
    assert elapsed < 1.0
    assert all(len(values) == 2000 for values in response.json["leads"].values())
    assert response.json["beats"]

    events = client.get(f"/api/cases/{case_id}/events?type=V&limit=20").json
    assert events["total"] >= len(events["items"]) > 0
    assert len(events["items"]) <= 20
    trend = client.get(f"/api/cases/{case_id}/trend?bin_seconds=60").json
    assert len(trend["points"]) > 1_400
    hrv = client.get(f"/api/cases/{case_id}/hrv").json
    assert abs(hrv["calculated"]["sdnn_ms"] - hrv["source"]["sdnn_ms"]) < 2


def test_scatter_modes_exact_lasso_and_virtual_strip_batch(client):
    case_id = _case_id(client, prefer_ventricular=True)
    payloads = {}
    for mode in ("rr", "n", "nn", "s", "v", "hour"):
        response = client.get(f"/api/cases/{case_id}/scatter?mode={mode}&max_points=1000")
        assert response.status_code == 200
        data = response.json
        payloads[mode] = data
        assert data["mode"] == mode
        assert data["returned_count"] == len(data["points"])
        assert data["returned_count"] <= 1000
        assert data["candidate_count"] >= data["returned_count"]
        assert all({"sample_index", "time_s", "x", "y", "group", "label", "rr_ms"} <= set(point) for point in data["points"])

    hourly = client.get(f"/api/cases/{case_id}/scatter?mode=hour&hour_start_s=3601&max_points=1000").json
    assert hourly["hour_start_s"] == 3600
    assert hourly["axis"]["x_unit"] == hourly["axis"]["y_unit"] == "ms"
    assert all(3600 <= point["time_s"] < 7200 for point in hourly["points"])

    assert client.get(f"/api/cases/{case_id}/scatter?mode=bad").status_code == 400
    ventricular = payloads["v"]
    assert ventricular["candidate_count"] > 0
    target = ventricular["points"][0]
    radius = 2
    polygon = [
        [target["x"] - radius, target["y"] - radius],
        [target["x"] + radius, target["y"] - radius],
        [target["x"] + radius, target["y"] + radius],
        [target["x"] - radius, target["y"] + radius],
    ]
    selected = client.post(
        f"/api/cases/{case_id}/scatter-selection",
        json={"mode": "v", "polygon": polygon},
    )
    assert selected.status_code == 200
    assert selected.json["exact"] is True
    assert selected.json["total"] == len(selected.json["sample_indices"]) > 0
    assert target["sample_index"] in selected.json["sample_indices"]

    samples = selected.json["sample_indices"][:3]
    strips = client.post(
        f"/api/cases/{case_id}/waveform-strips",
        json={
            "sample_indices": samples,
            "pre_s": 1.5,
            "post_s": 2.5,
            "leads": ["II", "V1", "V5"],
            "max_points": 800,
            "filter": "display",
        },
    )
    assert strips.status_code == 200
    assert len(strips.json["items"]) == len(samples)
    for item, sample in zip(strips.json["items"], samples):
        assert item["sample_index"] == sample
        assert item["label"] == "V"
        assert set(item["leads"]) == {"II", "V1", "V5"}
        assert 0 <= item["anchor_offset_s"] <= item["duration_s"]
        assert all(1 <= len(values) <= 800 for values in item["leads"].values())


def test_scatter_and_strip_validation(client):
    case_id = _case_id(client, prefer_ventricular=True)
    selection_url = f"/api/cases/{case_id}/scatter-selection"
    strips_url = f"/api/cases/{case_id}/waveform-strips"
    assert client.post(selection_url, json={"mode": "rr", "polygon": []}).status_code == 400
    assert client.post(selection_url, json={"mode": "rr", "polygon": [[0, 0], [1, 1], [False, 2]]}).status_code == 400
    assert client.post(selection_url, json={"mode": "rr", "polygon": [[0, 0], [1, 1], [10 ** 400, 2]]}).status_code == 400
    assert client.post(selection_url, json={"mode": "rr", "polygon": [[0, 0]] * 129}).status_code == 400
    assert client.post(selection_url, json={"mode": "bad", "polygon": [[0, 0], [1, 0], [1, 1]]}).status_code == 400
    assert client.post(strips_url, json={"sample_indices": []}).status_code == 400
    assert client.post(strips_url, json={"sample_indices": [True]}).status_code == 400
    assert client.post(strips_url, json={"sample_indices": list(range(33))}).status_code == 400
    assert client.post(strips_url, json={"sample_indices": [999_999_999]}).status_code == 400

    sample = client.get(f"/api/cases/{case_id}/scatter?mode=v&max_points=500").json["points"][0]["sample_index"]
    assert client.post(strips_url, json={"sample_indices": [sample], "leads": ["BAD"]}).status_code == 400
    assert client.post(strips_url, json={"sample_indices": [sample], "pre_s": 3, "post_s": 5}).status_code == 400
    assert client.post(strips_url, json={"sample_indices": [sample], "pre_s": 10 ** 400}).status_code == 400
    assert client.post(strips_url, json={"sample_indices": [sample], "max_points": 800.5}).status_code == 400


def test_annotation_patient_override_report_workflow_and_pdf(client):
    case_id = _case_id(client)
    created = client.post(f"/api/cases/{case_id}/annotations", json={
        "sample_index": 2000, "lead": "II", "category": "note",
        "label": "自动化测试标注", "note": "不修改原始波形",
    })
    assert created.status_code == 201
    annotation_id = created.json["id"]
    assert client.get(f"/api/cases/{case_id}/annotations").json["items"][0]["label"] == "自动化测试标注"

    override = client.patch(f"/api/cases/{case_id}/patient", json={"clinical_diagnosis": "测试覆盖", "active": False})
    assert override.status_code == 200
    detail = client.get(f"/api/cases/{case_id}?include_phi=1").json
    assert detail["metadata"]["clinical_diagnosis"] == "测试覆盖"
    assert detail["active"] is False

    source = client.get(f"/api/cases/{case_id}/report").json
    draft = client.put(f"/api/cases/{case_id}/report", json={"conclusion": source["conclusion"] + "\n自动化测试。", "status": "draft"}).json
    assert draft["status"] == "draft"
    reviewed = client.put(f"/api/cases/{case_id}/report", json={"conclusion": draft["conclusion"], "status": "reviewed"}).json
    assert reviewed["status"] == "reviewed"
    assert reviewed["reviewed_by"]
    pdf = client.get(f"/api/cases/{case_id}/report.pdf")
    assert pdf.status_code == 200
    assert pdf.headers["X-Privacy-Mode"] == "masked"
    assert pdf.data.startswith(b"%PDF")
    assert len(pdf.data) > 3_000

    client.post("/api/privacy/view", json={"enabled": True})
    phi_pdf = client.get(f"/api/cases/{case_id}/report.pdf?include_phi=1")
    assert phi_pdf.status_code == 200
    assert phi_pdf.headers["X-Privacy-Mode"] == "phi-visible"

    assert client.delete(f"/api/annotations/{annotation_id}").status_code == 200
    actions = {item["action"] for item in client.get("/api/audit").json["items"]}
    assert {"annotation.create", "annotation.delete", "patient.update", "report.draft", "report.reviewed", "report.export_pdf"}.issubset(actions)


def test_patient_patch_validation_merge_and_pdf_uses_override(client, monkeypatch):
    case_id = _case_id(client)
    invalid = client.patch(f"/api/cases/{case_id}/patient", json={"name": ["not", "text"]})
    assert invalid.status_code == 400
    assert client.get("/api/dashboard").status_code == 200

    first = client.patch(f"/api/cases/{case_id}/patient", json={"name": "QA姓名", "active": False})
    assert first.status_code == 200
    second = client.patch(f"/api/cases/{case_id}/patient", json={"clinical_diagnosis": "AUDIT_SENTINEL"})
    assert second.status_code == 200
    detail = client.get(f"/api/cases/{case_id}?include_phi=0").json
    assert detail["metadata"]["clinical_diagnosis"] == "AUDIT_SENTINEL"
    assert detail["active"] is False

    captured = {}

    def fake_report(case, calculated, report):
        captured.clear()
        captured.update(case)
        return BytesIO(b"%PDF-1.4\n%%EOF")

    monkeypatch.setattr("app.build_report_pdf", fake_report)
    masked_pdf = client.get(f"/api/cases/{case_id}/report.pdf")
    assert masked_pdf.headers["X-Privacy-Mode"] == "masked"
    assert captured["metadata"]["name"] == "已遮蔽"
    assert captured["metadata"]["clinical_diagnosis"] == "AUDIT_SENTINEL"

    client.post("/api/privacy/view", json={"enabled": True})
    phi_pdf = client.get(f"/api/cases/{case_id}/report.pdf?include_phi=1")
    assert phi_pdf.headers["X-Privacy-Mode"] == "phi-visible"
    assert captured["metadata"]["name"] == "QA姓名"


def test_pdf_accepts_maximum_length_wrapped_metadata(client):
    case_id = _case_id(client)
    long_diagnosis = "长诊断复核内容" * 71
    assert len(long_diagnosis) <= 500
    updated = client.patch(f"/api/cases/{case_id}/patient", json={
        "name": "长姓名字段复核测试",
        "patient_id": "ID-" + "9" * 70,
        "clinical_diagnosis": long_diagnosis,
    })
    assert updated.status_code == 200
    pdf = client.get(f"/api/cases/{case_id}/report.pdf")
    assert pdf.status_code == 200
    assert pdf.headers["X-Privacy-Mode"] == "masked"
    assert pdf.data.startswith(b"%PDF")
    assert len(pdf.data) > 4_000
