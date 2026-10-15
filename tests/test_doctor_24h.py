"""Contract tests for continuous synthetic doctor data; full DATA is built in CI."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import statistics

import numpy as np
import pytest

from ecg_core.ebi import load_records
from ecg_core.repository import CaseRepository
from ecg_core.waveform import ALL_LEADS, read_waveform
from scripts.generate_doctor_24h import (
    CASE_ID, CHANNEL_COUNT, FULL_RAW_BYTES, FULL_SAMPLES, FULL_SECONDS,
    SAMPLE_RATE, build_record, generate_dataset, render_chunk,
)


@pytest.fixture(scope="module")
def short_sources(tmp_path_factory):
    base = tmp_path_factory.mktemp("doctor-synthetic")
    first, second, different = (base / name for name in ("first", "second", "different"))
    manifests = [
        generate_dataset(first, duration_minutes=1, seed=20261013),
        generate_dataset(second, duration_minutes=1, seed=20261013),
        generate_dataset(different, duration_minutes=1, seed=20261014),
    ]
    return first, second, different, manifests


@pytest.fixture(scope="module")
def full_record():
    # Full beat metadata is small; this test never allocates the day-long raw DATA.
    return build_record(FULL_SECONDS, seed=20261013)


def _data_path(root: Path) -> Path:
    return root / CASE_ID / "data" / f"{CASE_ID}.DATA"


def _ebi_path(root: Path) -> Path:
    return root / CASE_ID / "DGS" / f"{CASE_ID}.EBI"


def test_short_fixture_loads_existing_repository_without_patient_identity(short_sources):
    root, _, _, manifests = short_sources
    manifest = manifests[0]
    case = CaseRepository(root).get_case(CASE_ID)
    assert case["metadata"]["name"] == "合成练习M01"
    assert case["metadata"]["patient_id"] == ""
    assert case["metadata"]["sex"] == ""
    assert case["metadata"]["clinical_diagnosis"] == ""
    assert "纯数学合成" in case["conclusion"]
    assert case["technical"]["duration_seconds_raw"] == 60
    assert case["technical"]["sample_rate_hz"] == 200
    assert case["technical"]["independent_channels"] == 8
    assert case["technical"]["calibration_verified"] is False
    assert manifest["source_id"] == "M01"
    assert manifest["source_version"] == "M01-test-v1"
    assert manifest["wholly_synthetic"] is True
    assert manifest["patient_inputs_read"] is False
    assert manifest["clinical_ground_truth"] is False
    assert manifest["automatic_diagnoses"] is False
    assert manifest["full_24h_fixture"] is False


def test_file_hashes_lengths_and_ebi_positions_are_self_consistent(short_sources):
    root, _, _, manifests = short_sources
    manifest = manifests[0]
    assert manifest["expected_raw_bytes"] == 60 * SAMPLE_RATE * CHANNEL_COUNT * 2
    actual_files = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    assert actual_files == {e["path"] for e in manifest["files"]} | {"source-manifest.json"}
    assert len(manifest["files"]) == 4
    for entry in manifest["files"]:
        raw = (root / entry["path"]).read_bytes()
        assert len(raw) == entry["size_bytes"]
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"]
    records = load_records(str(_ebi_path(root)))
    assert records[0][6] == 0
    assert all(0 <= row[0] < 60 * SAMPLE_RATE for row in records)
    assert all(a[0] < b[0] and b[6] == (b[0] - a[0]) * 5 for a, b in zip(records, records[1:]))
    assert len(_ebi_path(root).read_bytes()) == 32 + len(records) * 24
    raw = np.frombuffer(_data_path(root).read_bytes(), dtype="<i2").reshape(-1, CHANNEL_COUNT)
    assert raw.shape == (12000, 8)
    assert -32768 < raw.min() < raw.max() < 32767
    assert manifest["raw_range"] == {"minimum": int(raw.min()), "maximum": int(raw.max())}


def test_same_seed_reproduces_all_files_and_a_different_seed_changes_raw(short_sources):
    first, second, _, manifests = short_sources
    assert manifests[0]["files"] == manifests[1]["files"]
    assert manifests[0]["dataset_sha256"] == manifests[1]["dataset_sha256"]
    assert (first / "source-manifest.json").read_bytes() == (second / "source-manifest.json").read_bytes()
    data_hash = lambda m: next(e["sha256"] for e in m["files"] if e["path"].endswith(".DATA"))
    assert data_hash(manifests[0]) != data_hash(manifests[2])


def test_existing_native_reader_preserves_original_samples_and_twelve_derivations(short_sources):
    root = short_sources[0]
    raw = np.frombuffer(_data_path(root).read_bytes(), dtype="<i2").reshape(-1, 8)
    result = read_waveform(_data_path(root), 1, 5, ALL_LEADS, 1000, False)
    assert result["stride"] == 1
    assert result["display_sample_rate_hz"] == 200
    leads = result["leads"]
    assert list(leads) == ALL_LEADS
    np.testing.assert_array_equal(leads["I"], raw[200:1200, 0])
    np.testing.assert_array_equal(leads["II"], raw[200:1200, 1])
    i, ii = raw[200:1200, 0].astype(float), raw[200:1200, 1].astype(float)
    for lead, expected in (("III", ii - i), ("aVR", -(i + ii) / 2),
                           ("aVL", i - ii / 2), ("aVF", ii - i / 2)):
        np.testing.assert_array_equal(leads[lead], expected)
    for column, lead in enumerate(("V1", "V2", "V3", "V4", "V5", "V6"), 2):
        np.testing.assert_array_equal(leads[lead], raw[200:1200, column])


def test_full_record_has_day_and_night_nn_and_sustained_reference_events(full_record):
    assert full_record.total_samples == FULL_SAMPLES
    assert FULL_SAMPLES * 8 * 2 == FULL_RAW_BYTES == 276480000
    assert full_record.duration_seconds == 86400
    assert len(full_record.beats) > 60000
    assert all(a.sample_index < b.sample_index and b.rr_ms == (b.sample_index - a.sample_index) * 5
               for a, b in zip(full_record.beats, full_record.beats[1:]))
    events = {e.id: e for e in full_record.events}
    assert {e.kind for e in events.values()} == {"s_burst", "v_burst", "st_offset", "af_like", "artifact", "gap"}
    assert all(0 <= e.start_sample < e.end_sample <= FULL_SAMPLES for e in events.values())
    assert all(e.end_sample - e.start_sample >= SAMPLE_RATE * 60
               for e in events.values() if e.kind == "st_offset")
    normal = [b for a, b in zip(full_record.beats, full_record.beats[1:])
              if a.group == b.group == 1 and 300 <= b.rr_ms <= 2000]
    day = [b.rr_ms for b in normal if 3600 <= b.sample_index / 200 < 5400]
    night = [b.rr_ms for b in normal if 61200 <= b.sample_index / 200 < 63000]
    assert len(day) > 500 and len(night) > 500
    assert statistics.mean(night) > statistics.mean(day) * 1.15
    assert statistics.stdev([b.rr_ms for b in normal]) > 30


def test_s_and_v_bursts_and_irregular_unclassified_segment(full_record):
    for kind, group in (("s_burst", 2), ("v_burst", 3)):
        event = next(e for e in full_record.events if e.kind == kind)
        beats = [b for b in full_record.beats if event.start_sample <= b.sample_index < event.end_sample]
        assert sum(b.group == group for b in beats) >= 9
        assert any(all(b.group == group for b in beats[k:k+3]) for k in range(len(beats)-2))
    event = next(e for e in full_record.events if e.kind == "af_like")
    beats = [b for b in full_record.beats if event.start_sample <= b.sample_index < event.end_sample]
    assert {b.group for b in beats} == {8}
    rr = [b.rr_ms for b in beats]
    assert statistics.stdev(rr) / statistics.mean(rr) > 0.15
    assert len(set(rr)) > 20


def test_af_like_waveform_omits_p_without_a_diagnostic_source_label(full_record):
    af = next(e for e in full_record.events if e.kind == "af_like")
    af_beat = next(b for b in full_record.beats if af.start_sample + 2000 < b.sample_index < af.end_sample
                   and b.group == 8 and b.rr_ms >= 850)
    n_beat = next(b for b in full_record.beats if 1000 < b.sample_index < 20000
                  and b.group == 1 and b.rr_ms >= 800)
    def p_prominence(beat):
        block = render_chunk(full_record, beat.sample_index - 52, beat.sample_index - 19)[:, 1].astype(float)
        p = np.mean(block[13:20])  # -195..-165 ms
        shoulders = (np.mean(block[0:7]) + np.mean(block[26:33])) / 2
        return p - shoulders
    assert p_prominence(n_beat) > 15
    assert abs(p_prominence(af_beat)) < max(35, p_prominence(n_beat) * 0.7)
    assert af.parameters["diagnosis"] is None
    assert af.parameters["review_required"] is True


def test_st_offsets_exist_in_device_units_and_gap_is_exactly_zero(full_record):
    baseline = replace(full_record, events=tuple(e for e in full_record.events if e.kind != "st_offset"))
    for event in full_record.events:
        if event.kind != "st_offset":
            continue
        beat = next(b for b in full_record.beats if event.start_sample + 30 * SAMPLE_RATE < b.sample_index
                    < event.end_sample - 30 * SAMPLE_RATE and b.group == 1 and b.rr_ms >= 600)
        a, b = beat.sample_index + 20, beat.sample_index + 30
        shifted = render_chunk(full_record, a, b).astype(int)
        original = render_chunk(baseline, a, b).astype(int)
        difference = np.median(shifted - original, axis=0)
        for lead, amount in event.parameters["offsets_device_units"].items():
            assert difference[("I", "II", "V1", "V2", "V3", "V4", "V5", "V6").index(lead)] == pytest.approx(amount, abs=1)
        assert event.parameters["voltage_calibrated"] is False
    gap = next(e for e in full_record.events if e.kind == "gap")
    assert not np.any(render_chunk(full_record, gap.start_sample, gap.end_sample))
    assert all(b.group == 34 for b in full_record.beats
               if gap.start_sample <= b.sample_index < gap.end_sample)


def test_chunk_boundaries_do_not_reset_waveform_or_repeat_an_early_strip(full_record):
    # A boundary crossing a beat and an ST scenario must be byte-identical.
    a = 27030 * SAMPLE_RATE + 17
    whole = render_chunk(full_record, a, a + 2400)
    pieces = [render_chunk(full_record, lo, hi) for lo, hi in
              ((a, a+233), (a+233, a+2000), (a+2000, a+2400))]
    np.testing.assert_array_equal(whole, np.concatenate(pieces))
    early = render_chunk(full_record, 0, 2000)
    for seconds in (3600, 43200, 64800, 86380):
        assert not np.array_equal(early, render_chunk(full_record, seconds * SAMPLE_RATE, seconds * SAMPLE_RATE + 2000))


def test_generator_refuses_existing_destination_and_preserves_sentinels(tmp_path):
    destination = tmp_path / "existing"
    destination.mkdir()
    sentinel = destination / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="new directory"):
        generate_dataset(destination, duration_minutes=1)
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert sorted(p.name for p in destination.iterdir()) == ["keep.txt"]


@pytest.mark.parametrize("duration", [True, 0, -1, 0.09, 1440.01, float("nan"), float("inf"), "bad"])
def test_invalid_duration_writes_nothing(tmp_path, duration):
    destination = tmp_path / "invalid"
    with pytest.raises(ValueError):
        generate_dataset(destination, duration_minutes=duration)
    assert not destination.exists()


@pytest.mark.parametrize("seed", [True, 1.5, "123"])
def test_invalid_seed_writes_nothing(tmp_path, seed):
    destination = tmp_path / "invalid"
    with pytest.raises(ValueError, match="seed"):
        generate_dataset(destination, duration_minutes=1, seed=seed)
    assert not destination.exists()
