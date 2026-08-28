from __future__ import annotations


def _case_and_samples(client) -> tuple[str, list[int]]:
    case_id = client.get("/api/cases").json["items"][0]["case_id"]
    points = client.get(f"/api/cases/{case_id}/scatter?mode=rr&max_points=500").json["points"]
    samples = []
    for point in points:
        if point["group"] != 1:
            continue
        sample = point["sample_index"]
        if sample not in samples:
            samples.append(sample)
        if len(samples) == 3:
            break
    assert len(samples) == 3
    return case_id, samples


def test_doctor_can_create_update_list_and_delete_a_beat_template(client):
    case_id, samples = _case_and_samples(client)

    assert client.get(f"/api/cases/{case_id}/beat-templates").json == {"items": []}
    created_response = client.post(
        f"/api/cases/{case_id}/beat-templates",
        json={
            "name": "房速复核类 1",
            "rhythm_family": "房速",
            "lead": "II",
            "source_class": "source-N",
            "sample_indices": samples,
            "note": "由波形圈选创建；仅作人工模板分组。",
        },
    )

    assert created_response.status_code == 201
    created = created_response.json
    assert created["name"] == "房速复核类 1"
    assert created["rhythm_family"] == "房速"
    assert created["lead"] == "II"
    assert created["source_class"] == "source-N"
    assert created["sample_indices"] == sorted(samples)
    assert created["beat_count"] == 3
    assert created["start_sample"] == min(samples)
    assert created["end_sample"] == max(samples)

    listed = client.get(f"/api/cases/{case_id}/beat-templates").json["items"]
    assert [item["id"] for item in listed] == [created["id"]]

    updated_response = client.patch(
        f"/api/beat-templates/{created['id']}",
        json={"name": "房速复核类 A", "rhythm_family": "自定义", "note": "医生修正名称"},
    )
    assert updated_response.status_code == 200
    assert updated_response.json["name"] == "房速复核类 A"
    assert updated_response.json["rhythm_family"] == "自定义"

    assert client.delete(f"/api/beat-templates/{created['id']}").json == {"ok": True}
    assert client.get(f"/api/cases/{case_id}/beat-templates").json == {"items": []}

    actions = {item["action"] for item in client.get("/api/audit").json["items"]}
    assert {"beat_template.create", "beat_template.update", "beat_template.delete"}.issubset(actions)


def test_beat_template_rejects_invalid_or_non_beat_samples(client):
    case_id, samples = _case_and_samples(client)
    base = {
        "name": "测试模板",
        "rhythm_family": "单发",
        "lead": "II",
        "sample_indices": samples[:2],
    }

    duplicate = client.post(
        f"/api/cases/{case_id}/beat-templates",
        json={**base, "sample_indices": [samples[0], samples[0]]},
    )
    assert duplicate.status_code == 400

    unsupported = client.post(
        f"/api/cases/{case_id}/beat-templates",
        json={**base, "rhythm_family": "自动确诊"},
    )
    assert unsupported.status_code == 400

    non_beat = client.post(
        f"/api/cases/{case_id}/beat-templates",
        json={**base, "sample_indices": [samples[0] + 1]},
    )
    assert non_beat.status_code == 400

    invalid_parent = client.post(
        f"/api/cases/{case_id}/beat-templates",
        json={**base, "source_class": "custom-999999"},
    )
    assert invalid_parent.status_code == 400


def test_beat_template_rejects_unknown_case_or_template(client):
    assert client.get("/api/cases/0000000000000000/beat-templates").status_code == 404
    assert client.patch("/api/beat-templates/999999", json={"name": "不存在"}).status_code == 404
    assert client.delete("/api/beat-templates/999999").status_code == 404
