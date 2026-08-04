from __future__ import annotations

import math
import statistics
from pathlib import Path

import pytest

from ecg_core.config import CHANNEL_COUNT, SAMPLE_RATE
from ecg_core.ebi import load_records, metrics
from ecg_core.repository import CaseRepository
from ecg_core.waveform import ALL_LEADS, read_waveform


@pytest.fixture(scope="module")
def cases(data_root: Path):
    return CaseRepository(data_root).list_cases()


def test_dataset_discovery_uses_pseudonymous_directory_ids(cases):
    ids = [item["case_id"] for item in cases]
    assert len(cases) == 10
    assert len(ids) == len(set(ids))
    assert all(len(case_id) == 16 and case_id.isdigit() for case_id in ids)


def test_raw_format_duration_and_report_match(cases):
    for case in cases:
        data_path = Path(case["paths"]["data"])
        assert data_path.stat().st_size % (CHANNEL_COUNT * 2) == 0
        duration = data_path.stat().st_size / (CHANNEL_COUNT * 2 * SAMPLE_RATE)
        reported = case["metadata"]["duration_seconds_reported"]
        assert reported is not None
        assert abs(duration - reported) < 90
        assert 22 * 3600 < duration < 25 * 3600


def test_ebi_structure_counts_and_rr_timing(cases):
    for case in cases:
        records = load_records(case["paths"]["ebi"])
        assert len(records) > 70_000
        valid = [record for record in records if record[2] != 34]
        assert len(valid) == case["summary"]["total_beats"]
        groups = {code: sum(record[2] == code for record in records) for code in (1, 2, 3, 34)}
        assert groups[3] == case["summary"]["ventricular_beats"]
        assert groups[2] >= case["summary"]["supraventricular_beats"]
        assert set(record[2] for record in records).issubset({1, 2, 3, 34})

        stride = max(1, len(records) // 1000)
        errors = []
        for index in range(stride, len(records), stride):
            previous, current = records[index - 1], records[index]
            expected = (current[0] - previous[0]) * 1000 / SAMPLE_RATE
            errors.append(abs(expected - current[6]))
        assert statistics.median(errors) <= 2
        assert sorted(errors)[math.floor(len(errors) * 0.95)] <= 4


def test_metrics_are_internally_consistent(cases):
    case = cases[0]
    result = metrics(Path(case["paths"]["ebi"]), case["technical"]["duration_seconds_raw"])
    assert result["valid_beats"] == case["summary"]["total_beats"]
    assert result["group_counts"]["3"] == case["summary"]["ventricular_beats"]
    assert result["longest_rr_ms"] > 0
    assert 20 < result["avg_hr_from_rr"] < 250


def test_twelve_lead_window_is_derived_without_loading_whole_file(cases):
    case = cases[-1]
    result = read_waveform(Path(case["paths"]["data"]), 3600, 2, ALL_LEADS, 1000, False)
    assert list(result["leads"]) == ALL_LEADS
    assert all(len(values) == 400 for values in result["leads"].values())
    assert result["sample_rate_hz"] == 200
    i, ii, iii = result["leads"]["I"], result["leads"]["II"], result["leads"]["III"]
    assert all(iii[index] == ii[index] - i[index] for index in range(400))
