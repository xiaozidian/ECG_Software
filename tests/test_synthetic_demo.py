from __future__ import annotations

from pathlib import Path

import pytest

from app import create_app
from ecg_core.ebi import load_records
from ecg_core.repository import CaseRepository
from ecg_core.waveform import ALL_LEADS, read_waveform
from scripts.generate_synthetic_demo import (
    CHANNEL_COUNT,
    SAMPLE_RATE,
    generate_dataset,
)


@pytest.fixture(scope="module")
def synthetic_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("synthetic-demo") / "demo_data"
    summaries = generate_dataset(root, duration_minutes=1, case_count=10, seed=12345)
    assert len(summaries) == 10
    return root


def test_generator_creates_ten_loadable_minimum_cases(synthetic_root: Path):
    cases = CaseRepository(synthetic_root).list_cases()
    assert len(cases) == 10
    assert [case["metadata"]["name"] for case in cases] == [
        f"演示病例{index:02d}" for index in range(1, 11)
    ]

    for case in cases:
        case_id = case["case_id"]
        assert len(case_id) == 16 and case_id.isdigit()
        case_dir = synthetic_root / case_id
        assert (case_dir / "report_image" / f"{case_id}_1.LPS").is_file()
        assert (case_dir / "data" / f"{case_id}.DATA").is_file()
        assert (case_dir / "DGS" / f"{case_id}.EBI").is_file()
        assert not any(
            path.suffix.lower() in {".pdf", ".png", ".zip"}
            for path in case_dir.rglob("*")
        )
        assert case["metadata"]["patient_id"] == case_id
        assert "纯数学合成" in case["conclusion"]
        assert case["technical"]["sample_rate_hz"] == SAMPLE_RATE
        assert case["technical"]["independent_channels"] == CHANNEL_COUNT
        assert case["technical"]["duration_seconds_raw"] == pytest.approx(60)


def test_generated_signals_include_demo_events_and_waveforms(synthetic_root: Path):
    for case in CaseRepository(synthetic_root).list_cases():
        records = load_records(case["paths"]["ebi"])
        groups = {record[2] for record in records}
        assert {1, 2, 3, 34}.issubset(groups)
        assert max(record[6] for record in records) >= 2500
        assert case["summary"]["total_beats"] == sum(record[2] != 34 for record in records)
        assert case["summary"]["supraventricular_beats"] == sum(record[2] == 2 for record in records)
        assert case["summary"]["ventricular_beats"] == sum(record[2] == 3 for record in records)

    first = CaseRepository(synthetic_root).list_cases()[0]
    waveform = read_waveform(Path(first["paths"]["data"]), 0, 5, ALL_LEADS, 1000, False)
    assert list(waveform["leads"]) == ALL_LEADS
    assert max(waveform["leads"]["II"]) - min(waveform["leads"]["II"]) > 500
    assert all(len(values) == 1000 for values in waveform["leads"].values())


def test_generation_is_repeatable_without_deleting_unrelated_files(synthetic_root: Path):
    outside = synthetic_root.parent / "outside-sentinel.txt"
    inside = synthetic_root / "keep-this-file.txt"
    outside.write_text("outside", encoding="utf-8")
    inside.write_text("inside", encoding="utf-8")
    before = (synthetic_root / "9900000000000001" / "data" / "9900000000000001.DATA").read_bytes()

    generate_dataset(synthetic_root, duration_minutes=1, case_count=10, seed=12345)

    after = (synthetic_root / "9900000000000001" / "data" / "9900000000000001.DATA").read_bytes()
    assert after == before
    assert outside.read_text(encoding="utf-8") == "outside"
    assert inside.read_text(encoding="utf-8") == "inside"


def test_key_http_apis_work_with_synthetic_cases(synthetic_root: Path, tmp_path: Path):
    application = create_app(
        data_root=synthetic_root,
        db_path=tmp_path / "synthetic-test.db",
        testing=True,
    )
    client = application.test_client()

    health = client.get("/api/health")
    assert health.status_code == 200
    case_response = client.get("/api/cases")
    assert case_response.status_code == 200
    items = case_response.json["items"]
    assert len(items) == 10
    case_id = items[0]["case_id"]

    detail = client.get(f"/api/cases/{case_id}")
    assert detail.status_code == 200
    waveform = client.get(
        f"/api/cases/{case_id}/waveform?start=0&duration=5&leads=II,V1,V5"
    )
    assert waveform.status_code == 200
    assert set(waveform.json["leads"]) == {"II", "V1", "V5"}
    events = client.get(f"/api/cases/{case_id}/events?type=all&limit=100")
    assert events.status_code == 200
    assert {item["type"] for item in events.json["items"]}.issuperset({"S", "V", "noise", "pause"})
    trend = client.get(f"/api/cases/{case_id}/trend?bin_seconds=60")
    assert trend.status_code == 200
    assert trend.json["points"]
