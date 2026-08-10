from __future__ import annotations

from pathlib import Path

from ecg_core.ebi import (
    RECORD,
    beat_details,
    iter_scatter_points,
    scatter_points,
    select_scatter_points,
)
def _record(sample: int, group: int, rr_ms: int):
    return (sample, 0, group, 0, 0, 0, rr_ms)


def _synthetic_records():
    groups = [1, 1, 1, 2, 1, 3, 1, 34, 1, 1, 1]
    rr_values = [500, 600, 700, 800, 900, 1000, 1100, 1200, 1300, 1400, 1500]
    return tuple(_record(index * 200, group, rr_values[index]) for index, group in enumerate(groups))


def _write_ebi(path: Path, records) -> Path:
    path.write_bytes(b"\0" * 32 + b"".join(RECORD.pack(*record) for record in records))
    return path


def test_scatter_modes_anchor_middle_beat_and_strict_nn(tmp_path: Path):
    records = _synthetic_records()
    rr = list(iter_scatter_points(records, "rr"))
    normal = list(iter_scatter_points(records, "n"))
    nn = list(iter_scatter_points(records, "nn"))
    supra = list(iter_scatter_points(records, "s"))
    ventricular = list(iter_scatter_points(records, "v"))

    assert [(point["sample_index"], point["x"], point["y"]) for point in nn] == [
        (records[1][0], 600, 700),
        (records[9][0], 1400, 1500),
    ]
    assert [point["sample_index"] for point in supra] == [records[3][0]]
    assert [point["sample_index"] for point in ventricular] == [records[5][0]]
    assert {point["sample_index"] for point in normal} == {
        records[1][0], records[2][0], records[4][0], records[9][0]
    }
    assert all(point["sample_index"] != records[6][0] for point in rr)

    path = _write_ebi(tmp_path / "synthetic.EBI", records)
    details = beat_details(path, [records[3][0], records[5][0], 999_999])
    assert details[records[3][0]]["label"] == "S"
    assert details[records[5][0]]["label"] == "V"
    assert 999_999 not in details


def test_scatter_sampling_is_deterministic_and_polygon_selection_is_exact(tmp_path: Path):
    records = tuple(_record(index * 200, 3 if index % 37 == 0 else 1, 600 + index % 700) for index in range(2000))
    path = _write_ebi(tmp_path / "many.EBI", records)
    first = scatter_points(path, "rr", 500)
    second = scatter_points(path, "rr", 500)

    assert first["candidate_count"] > first["returned_count"] == 500
    assert first["points"] == second["points"]
    assert any(point["group"] == 3 for point in first["points"])

    selected = select_scatter_points(path, "v", [(0, 0), (5000, 0), (5000, 5000), (0, 5000)])
    expected = [point["sample_index"] for point in iter_scatter_points(records, "v")]
    assert selected["exact"] is True
    assert selected["sample_indices"] == expected

    dense_records = tuple(_record(index * 200, 3, 650 + index % 20) for index in range(16_002))
    dense_path = _write_ebi(tmp_path / "dense-abnormal.EBI", dense_records)
    dense = scatter_points(dense_path, "rr", 12_000)
    assert dense["candidate_count"] > dense["returned_count"] == 12_000


def test_hour_scatter_is_rr_lorenz_for_selected_hour(tmp_path: Path):
    records = tuple(
        _record(int(time_s * 200), 1, rr_ms)
        for time_s, rr_ms in [(0, 500), (3599, 600), (3600, 700), (3601, 800), (7200, 900)]
    )
    path = _write_ebi(tmp_path / "hour-window.EBI", records)
    result = scatter_points(path, "hour", 500, 3700)

    assert result["hour_start_s"] == 3600
    assert result["hour_end_s"] == 7200
    assert result["axis"] == {"x_label": "RR(i)", "y_label": "RR(i+1)", "x_unit": "ms", "y_unit": "ms"}
    assert [(point["time_s"], point["x"], point["y"]) for point in result["points"]] == [
        (3600.0, 700, 800),
        (3601.0, 800, 900),
    ]


def test_polygon_selection_includes_points_on_every_boundary(tmp_path: Path):
    records = _synthetic_records()
    path = _write_ebi(tmp_path / "boundary.EBI", records)
    selected = select_scatter_points(path, "rr", [(600, 700), (800, 700), (800, 900), (600, 900)])
    assert records[1][0] in selected["sample_indices"]
    assert records[2][0] in selected["sample_indices"]
    assert records[3][0] in selected["sample_indices"]
