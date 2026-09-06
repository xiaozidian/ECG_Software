from __future__ import annotations

from ecg_core.storage import Storage
from io import BytesIO


def complete_all(client, case_id):
    for step in ("review", "edit", "trends", "stt", "events"):
        progress = client.get(f"/api/cases/{case_id}/review-workflow").json
        result = client.put(f"/api/cases/{case_id}/review-workflow", json={
            "step": step, "revision": progress["revision"], "confirmed": True, "note": "已核对源数据限制",
        })
        assert result.status_code == 200


def test_review_requires_explicit_confirmation_and_current_revision(client):
    case_id = client.get("/api/cases").json["items"][0]["case_id"]
    base = f"/api/cases/{case_id}"
    progress = client.get(base + "/review-workflow").json
    client.post(base + "/open", json={})
    client.get(base + "/waveform?duration=5")
    assert client.get(base + "/review-workflow").json["pending_steps"] == progress["pending_steps"]
    assert client.put(base + "/review-workflow", json={"step": "review", "revision": 0}).status_code == 400
    assert client.put(base + "/review-workflow", json={"step": "review", "revision": False, "confirmed": True}).status_code == 400
    assert client.put(base + "/review-workflow", json={"step": "review", "revision": 0, "confirmed": True}).status_code == 200
    assert client.put(base + "/review-workflow", json={"step": "edit", "revision": 0, "confirmed": True}).status_code == 400
    assert client.put(base + "/report", json={"conclusion": "测试结论", "status": "reviewed"}).status_code == 400
    assert client.get("/api/cases/nonexistent/review-workflow").status_code == 404


def test_edit_invalidates_checkpoints_and_previously_approved_report(client):
    case_id = client.get("/api/cases").json["items"][0]["case_id"]
    base = f"/api/cases/{case_id}"
    source = client.get(base).json["calculated"]
    event = client.get(base + "/events?limit=1").json["items"][0]
    retained = client.put(base + "/event-reviews", json={"items": [event], "status": "retained"})
    assert retained.status_code == 200
    complete_all(client, case_id)
    assert client.put(base + "/report", json={"conclusion": "复核测试", "status": "draft"}).status_code == 200
    approved = client.put(base + "/report", json={"conclusion": "复核测试", "status": "reviewed"})
    assert approved.json["status"] == "reviewed"
    changed = client.put(base + "/beat-overrides", json={"sample_indices": [event["sample_index"]], "class_code": "N"})
    assert changed.status_code == 200
    progress = client.get(base + "/review-workflow").json
    assert len(progress["pending_steps"]) == 5
    assert all(item["status"] == "stale" for item in progress["steps"].values())
    assert all(item["status"] == "pending" for item in progress["events"].values())
    assert progress["report_status"] == "draft"
    assert client.get(base + "/report").json["version"] == approved.json["version"] + 1
    assert client.get(base).json["calculated"] == source
    assert client.put(base + "/report", json={"conclusion": "复核测试", "status": "reviewed"}).status_code == 400


def test_events_validate_samples_and_persist_separately_from_source(client):
    cases = client.get("/api/cases").json["items"]
    base = f"/api/cases/{cases[0]['case_id']}"
    event = client.get(base + "/events?limit=1").json["items"][0]
    invalid = {"items": [{"sample_index": -1, "type": "V"}], "status": "retained"}
    assert client.put(base + "/event-reviews", json=invalid).status_code == 400
    invalid["items"][0]["sample_index"] = True
    assert client.put(base + "/event-reviews", json=invalid).status_code == 400
    payload = {"items": [event], "status": "excluded"}
    assert client.put(base + "/event-reviews", json=payload).status_code == 200
    progress = client.get(base + "/review-workflow").json
    assert progress["events"][f"{event['type']}:{event['sample_index']}"]["status"] == "excluded"
    assert client.get(base + "/events?limit=1").json["items"][0]["review_status"] == "待复核"
    assert not client.get(f"/api/cases/{cases[1]['case_id']}/review-workflow").json["events"]
    assert any(item["action"] == "event.review" for item in client.get("/api/audit").json["items"])


def test_review_survives_storage_restart_and_blank_report_is_blocked(tmp_path):
    path = tmp_path / "review.db"
    store = Storage(path)
    for index, step in enumerate(("review", "edit", "trends", "stt", "events")):
        store.complete_review("test", {"step": step, "revision": index, "confirmed": True}, "tester")
    reopened = Storage(path)
    assert reopened.get_review("test")["pending_steps"] == []
    import pytest
    with pytest.raises(ValueError, match="结论"):
        reopened.save_report("test", "  ", "reviewed", "tester")


def test_pdf_receives_current_review_and_evidence_snapshot(client, monkeypatch):
    case_id = client.get("/api/cases").json["items"][0]["case_id"]
    base = f"/api/cases/{case_id}"
    event = client.get(base + "/events?limit=1").json["items"][0]
    assert client.put(base + "/event-reviews", json={"items": [event], "status": "retained"}).status_code == 200
    complete_all(client, case_id)
    captured = {}

    def fake_pdf(case, calculated, report):
        captured.update(report)
        return BytesIO(b"%PDF-test")

    monkeypatch.setattr("app.build_report_pdf", fake_pdf)
    assert client.get(base + "/report.pdf").status_code == 200
    review = captured["review_snapshot"]
    assert len(review["steps"]) == 5
    assert all(item["status"] == "done" for item in review["steps"].values())
    assert review["events"][f"{event['type']}:{event['sample_index']}"]["status"] == "retained"
    assert captured["override_count"] == 0
