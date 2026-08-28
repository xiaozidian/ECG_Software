from __future__ import annotations


def _case_and_beats(client) -> tuple[str, list[dict]]:
    case_id = client.get("/api/cases").json["items"][0]["case_id"]
    points = client.get(f"/api/cases/{case_id}/scatter?mode=rr&max_points=500").json["points"]
    assert len(points) >= 2
    return case_id, points[:2]


def test_doctor_can_reclassify_and_restore_beats_without_changing_source_group(client):
    case_id, beats = _case_and_beats(client)
    samples = [beat["sample_index"] for beat in beats]
    source_groups = {beat["sample_index"]: beat["group"] for beat in beats}

    assert client.get(f"/api/cases/{case_id}/beat-overrides").json == {"items": []}
    changed = client.put(
        f"/api/cases/{case_id}/beat-overrides",
        json={"sample_indices": samples, "class_code": "V"},
    )
    assert changed.status_code == 200
    assert changed.json["changed"] == 2
    assert {item["class_code"] for item in changed.json["items"]} == {"V"}
    assert {item["sample_index"]: item["source_group"] for item in changed.json["items"]} == source_groups

    listed = client.get(f"/api/cases/{case_id}/beat-overrides").json["items"]
    assert [item["sample_index"] for item in listed] == sorted(samples)
    source_after = client.get(f"/api/cases/{case_id}/scatter?mode=rr&max_points=500").json["points"]
    after_groups = {item["sample_index"]: item["group"] for item in source_after if item["sample_index"] in samples}
    assert after_groups == source_groups

    restored = client.delete(
        f"/api/cases/{case_id}/beat-overrides", json={"sample_indices": samples}
    )
    assert restored.json == {"ok": True, "changed": 2}
    assert client.get(f"/api/cases/{case_id}/beat-overrides").json == {"items": []}
    actions = {item["action"] for item in client.get("/api/audit").json["items"]}
    assert {"beat_override.reclassify", "beat_override.restore"}.issubset(actions)


def test_beat_override_rejects_invalid_codes_duplicates_and_non_beats(client):
    case_id, beats = _case_and_beats(client)
    sample = beats[0]["sample_index"]
    assert client.put(
        f"/api/cases/{case_id}/beat-overrides",
        json={"sample_indices": [sample], "class_code": "diagnosis"},
    ).status_code == 400
    assert client.put(
        f"/api/cases/{case_id}/beat-overrides",
        json={"sample_indices": [sample, sample], "class_code": "N"},
    ).status_code == 400
    assert client.put(
        f"/api/cases/{case_id}/beat-overrides",
        json={"sample_indices": [sample + 1], "class_code": "O"},
    ).status_code == 400
