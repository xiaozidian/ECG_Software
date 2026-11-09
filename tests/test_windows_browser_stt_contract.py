"""Current native controller must retain independent raw ST arithmetic guards."""
import copy
import json
from pathlib import Path

import pytest

from scripts.verify_windows_doctor_browser import assert_native_stt_contract


def fixture():
    evidence = json.loads((Path(__file__).parent / "fixtures/windows17_m01_st_scalar_oracle.json").read_text())
    assert evidence["patient_inputs_read"] is False
    expected = evidence["result"]
    leads = ["II", "V1", "V5"]
    request = dict(start_sample=0, end_sample=12000, measurement_ms=60, leads=leads)
    profile = dict(id="raw-200hz-fixed16s-st-perbeat-morphology-v3", sample_rate_hz=200,
                   rhythm_policy="independent_of_AF_AFL_reviews", measurement_ms=60,
                   block_seconds=16, baseline_offsets_samples=[-40, -36, -32, -28, -24],
                   st_window_offsets_samples=[-2, -1, 0, 1, 2], filter="raw source; no display high-pass",
                   mean_beat_limit=None, aggregate="arithmetic_mean_of_used_per_beat_st_minus_baseline",
                   unit_label="u", calibration_verified=False, diagnosis_generated=False,
                   t_measurement="qualifying prominence; before next real R",
                   t_shape_statistics="separate extrema", slope="raw u/s")
    native = dict(schema_version="stt-range-mean-v1", range=copy.deepcopy(expected["range"]),
                  method_profile=profile, counts=copy.deepcopy(expected["counts"]),
                  exclusions={"intervals": []}, blocks=copy.deepcopy(expected["blocks"]),
                  leads=[copy.deepcopy(row) for row in expected["leads"] if row["lead"] in leads],
                  save_receipt={"kind": "native-stt-range-hmac-v1"})
    return native, request, expected


def test_current_native_contract_requires_v3_and_independent_numeric_ST_evidence():
    native, request, expected = fixture()
    proof = assert_native_stt_contract(native, request, expected)
    assert proof["counts"] == dict(detected_count=68, used_count=67, excluded_count=1,
                                  missing_count=0, reason_counts={"rr_outside_legacy_bounds": 1})
    assert proof["means_units"]["II"] == -5.029850746268656
    assert proof["j_offsets_samples"] == [14, 14, 14, 14]


@pytest.mark.parametrize("fault", ["v2", "AF_mask", "wrong_range", "wrong_offset",
                                  "sampled_mean", "display_filter", "calibrated",
                                  "wrong_baseline", "wrong_ST_support", "missing_T_method",
                                  "zero_replaced_mean", "wrong_mean", "nan_mean", "missing_mean",
                                  "wrong_count", "wrong_lead_count", "wrong_lead", "wrong_J",
                                  "wrong_representatives", "wrong_receipt"])
def test_native_contract_rejects_metadata_or_arithmetic_substitution(fault):
    native, request, expected = fixture()
    p = native["method_profile"]
    if fault == "v2": p["id"] = "raw-200hz-fixed16s-st-perbeat-mean-v2"
    elif fault == "AF_mask": native["exclusions"]["intervals"] = [{"reason": "AF"}]
    elif fault == "wrong_range": native["range"]["end_sample"] -= 1
    elif fault == "wrong_offset": p["measurement_ms"] = 80
    elif fault == "sampled_mean": p["mean_beat_limit"] = 7
    elif fault == "display_filter": p["filter"] = "highpass"
    elif fault == "calibrated": p["calibration_verified"] = True
    elif fault == "wrong_baseline": p["baseline_offsets_samples"][0] = -39
    elif fault == "wrong_ST_support": p["st_window_offsets_samples"][0] = -3
    elif fault == "missing_T_method": p["t_measurement"] = "signed mean"
    elif fault == "zero_replaced_mean": native["leads"][0]["mean_units"] = 0
    elif fault == "wrong_mean": native["leads"][0]["mean_units"] += 0.0001
    elif fault == "nan_mean": native["leads"][0]["mean_units"] = float("nan")
    elif fault == "missing_mean": native["leads"][0]["mean_units"] = None
    elif fault == "wrong_count": native["counts"]["used_count"] -= 1
    elif fault == "wrong_lead_count": native["leads"].append(copy.deepcopy(native["leads"][0]))
    elif fault == "wrong_lead": native["leads"][0]["lead"] = "I"
    elif fault == "wrong_J": native["blocks"][0]["j_offset_samples"] += 1
    elif fault == "wrong_representatives": native["blocks"][0]["j_representative_samples"].pop()
    else: native["save_receipt"]["kind"] = "unsigned"
    with pytest.raises(AssertionError):
        assert_native_stt_contract(native, request, expected)
