from __future__ import annotations

import json

from ecg_core.stt import build_stt_review, extract_stt_source_report


def test_source_report_extraction_is_explicit_and_redacts_case_voltage():
    result = extract_stt_source_report(
        "窦性心律。ST-T 改变：II 导联 ST 段压低 -0.15 mV，T 波低平。\n"
        "偶发室性早搏。"
    )

    assert result["available"] is True
    assert result["origin"] == "source_report_conclusion"
    assert result["is_source_excerpt"] is True
    assert result["software_interpretation_added"] is False
    assert result["amplitude_values_redacted"] is True
    assert result["fragments"] == [
        "ST-T 改变：II 导联 ST 段压低 【病例幅度已隐藏】，T 波低平。"
    ]
    assert "0.15" not in result["text"]
    assert "室性早搏" not in result["text"]


def test_review_contract_keeps_measurement_and_diagnosis_disabled():
    result = build_stt_review("未见明显 ST-T 异常。")

    assert result["review_mode"] == "manual_review_only"
    assert result["manual_review_only"] is True
    assert result["calibration_unverified"] is True
    assert result["measurement_protocol"]["default_measurement"] == "J+60 ms"
    assert result["measurement_protocol"]["default_landmark"] == "ST60"
    assert [item["code"] for item in result["measurement_protocol"]["landmarks"]] == [
        "J",
        "ST60",
        "ST80",
    ]
    assert result["measurement_protocol"]["baseline"]["preferred"] == "PR_segment"
    assert result["measurement_protocol"]["case_amplitude_output"]["enabled"] is False
    assert result["lead_system"]["status"] == "unknown"
    assert result["automatic_candidates"]["enabled"] is False
    assert result["reference_thresholds"]["enabled"] is False
    assert result["reference_thresholds"]["applied_to_case"] is False
    assert result["clinical_safety"]["diagnosis_generated"] is False


def test_stt_review_endpoint_exposes_only_the_manual_review_contract(client):
    case_id = client.get("/api/cases").json["items"][0]["case_id"]
    response = client.get(f"/api/cases/{case_id}/stt-review")

    assert response.status_code == 200
    result = response.json
    assert result["schema_version"] == "manual-stt-review-v1"
    assert result["manual_review_only"] is True
    assert result["calibration"]["status"] == "unverified"
    assert result["lead_system"]["mapping_verified"] is False
    assert result["automatic_candidates"]["reason_code"] == "measurement_chain_not_validated"
    assert result["reference_thresholds"]["reference_only"] is True
    assert result["source_report"]["origin"] == "source_report_conclusion"

    serialized = json.dumps(result, ensure_ascii=False)
    assert '"case_st_mV"' not in serialized
    assert '"measured_st_mV"' not in serialized


def test_stt_review_endpoint_rejects_unknown_case(client):
    response = client.get("/api/cases/0000000000000000/stt-review")

    assert response.status_code == 404
    assert response.json["error"] == "病例不存在或数据不完整"
