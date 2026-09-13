from __future__ import annotations

import json
import struct

from ecg_core.stt import analyze_stt, build_stt_review, extract_stt_source_report


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


def test_review_contract_without_waveform_falls_back_to_manual_review():
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
    assert result["lead_system"]["mapping_verified"] is False
    assert result["automatic_candidates"]["enabled"] is False
    assert result["reference_thresholds"]["enabled"] is False
    assert result["reference_thresholds"]["applied_to_case"] is False
    assert result["clinical_safety"]["diagnosis_generated"] is False


def test_stt_review_endpoint_exposes_automatic_candidates_pending_physician_review(client):
    case_id = client.get("/api/cases").json["items"][0]["case_id"]
    response = client.get(f"/api/cases/{case_id}/stt-review")

    assert response.status_code == 200
    result = response.json
    assert result["schema_version"] == "stt-screening-review-v2"
    assert result["manual_review_only"] is False
    assert result["calibration"]["status"] == "unverified"
    assert result["lead_system"]["mapping_verified"] is False
    assert result["automatic_candidates"]["enabled"] is True
    assert result["automatic_candidates"]["review_status"] == "pending_physician_review"
    assert result["automatic_candidates"]["items"] == result["analysis"]["candidates"]
    assert result["analysis"]["quality"]["total_blocks"] > 0
    assert result["reference_thresholds"]["reference_only"] is True
    assert result["source_report"]["origin"] == "source_report_conclusion"

    serialized = json.dumps(result, ensure_ascii=False)
    assert '"case_st_mV"' not in serialized
    assert '"measured_st_mV"' not in serialized


def test_detector_finds_persistent_shift_but_never_emits_a_diagnosis(tmp_path):
    rate, duration = 200, 320
    waveform = tmp_path / "synthetic.DATA"
    with waveform.open("wb") as stream:
        for sample in range(rate * duration):
            second, phase = divmod(sample, rate)
            shift = 130 if 120 <= second < 205 and 18 <= phase <= 44 else 0
            qrs = {0: 900, 1: 600, 2: 250, 3: 80}.get(phase, 0)
            t_wave = 180 if 55 <= phase <= 62 else 0
            value = qrs + shift + t_wave
            stream.write(struct.pack("<8h", *(value for _ in range(8))))
    records = [(second * rate, 0, 1, 0, 0, 0, 1000) for second in range(1, duration)]

    result = analyze_stt(waveform, records, duration, analysis_revision="synthetic-v1")

    assert result["quality"]["coverage_pct"] == 100.0
    assert any(item["kind"] == "st_elevation" for item in result["candidates"])
    assert all(item["review_status"] == "pending" for item in result["candidates"])
    assert all(item["diagnosis"] is None for item in result["candidates"])
    assert all(abs(item["peak_deviation_units"]) >= 100 for item in result["candidates"])


def test_short_transient_does_not_pass_the_persistence_rule(tmp_path):
    rate, duration = 200, 180
    waveform = tmp_path / "short.DATA"
    with waveform.open("wb") as stream:
        for sample in range(rate * duration):
            second, phase = divmod(sample, rate)
            shift = -160 if 80 <= second < 105 and 18 <= phase <= 44 else 0
            qrs = {0: 900, 1: 500, 2: 150}.get(phase, 0)
            value = qrs + shift
            stream.write(struct.pack("<8h", *(value for _ in range(8))))
    records = [(second * rate, 0, 1, 0, 0, 0, 1000) for second in range(1, duration)]

    result = analyze_stt(waveform, records, duration, analysis_revision="short-v1")

    assert result["candidates"] == []


def test_stt_review_endpoint_rejects_unknown_case(client):
    response = client.get("/api/cases/0000000000000000/stt-review")

    assert response.status_code == 404
    assert response.json["error"] == "病例不存在或数据不完整"
