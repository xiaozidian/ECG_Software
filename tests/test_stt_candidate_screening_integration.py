"""Full-engine synthetic acceptance for conservative candidate screening.

The source functions define the inputs before analyze_stt runs.  No patient
data, detector-internal measurements, or clinical voltage assumptions are used
as an oracle.  Numeric trends must remain observable when candidates are cut.
"""

from pathlib import Path
import struct
from uuid import uuid4

import numpy as np
import pytest

from app import create_app
from ecg_core.stt import analyze_stt


FS = 200


def mathematical_recording(tmp_path, *, duration=240, changes=(), flatline=()):
    """Changes are (source channel, kind, start second, end second, value)."""
    raw = np.full((duration*FS, 8), 4000.0)
    records = []
    rng = np.random.default_rng(37)
    offset = np.arange(-50, 110)
    qrs = (1000*np.exp(-.5*(offset/1.3)**2)
           -150*np.exp(-.5*((offset+4)/1.5)**2)
           -180*np.exp(-.5*((offset-5)/1.8)**2))
    normal_t = np.exp(-.5*((offset-62)/6)**2)
    for second in range(1, duration-1):
        anchor = second*FS
        values = np.repeat(qrs[:, None], 8, axis=1)
        amplitudes = np.full(8, 180.0)
        selected = [change for change in changes if change[2] <= second < change[3]]
        for channel, kind, _, _, value in selected:
            if kind == "T":
                amplitudes[channel] = value
            elif kind in {"spike", "t_sine_noise", "t_white_noise", "plateau_ripple", "biphasic"}:
                amplitudes[channel] = 0.0
        values += normal_t[:, None]*amplitudes[None, :]
        for channel, kind, _, _, value in selected:
            if kind == "ST":
                values[:, channel] += value*((offset >= 17) & (offset <= 44))
            elif kind == "spike":
                values[offset == 62, channel] -= 180
            elif kind == "t_sine_noise":
                values[(offset >= 40) & (offset < 90), channel] += 120*np.sin(2*np.pi*np.arange(50)/8)
            elif kind == "t_white_noise":
                values[(offset >= 40) & (offset < 90), channel] += rng.normal(0, 100, 50)
            elif kind == "plateau_ripple":
                values[:, channel] += ((offset >= 17) & (offset <= 100))*(-110-15*normal_t)
            elif kind == "pr_offset":
                values[(offset >= -40) & (offset <= -24), channel] += value
            elif kind == "biphasic":
                # Late negative lobe deliberately matches the pre-existing
                # independent engineering acceptance waveform (55 / 78).
                values[:, channel] += (180*np.exp(-.5*((offset-55)/4)**2)
                                       -180*np.exp(-.5*((offset-78)/4)**2))
        raw[anchor-50:anchor+110] += values
        records.append((anchor, 0, 1, 0, 0, 0, 1000))
    for start, end in flatline:
        raw[start*FS:end*FS] = 4000
    path = tmp_path/"independent-candidate-math.DATA"
    path.write_bytes(np.rint(raw).astype("<i2").tobytes())
    return path, records


def events(result, lead, kinds=None):
    return [event for event in result["candidates"]
            if event["lead"] == lead and (kinds is None or event["kind"] in kinds)]


def t_events(result, lead):
    return [event for event in events(result, lead) if event["kind"].startswith("t_")]


def analyze(tmp_path, **specification):
    path, records = mathematical_recording(tmp_path, **specification)
    return analyze_stt(path, records, specification.get("duration", 240))


@pytest.mark.parametrize("kind", ["spike", "t_sine_noise", "t_white_noise"])
def test_full_engine_rejects_t_only_artifacts_without_hiding_measured_trends(tmp_path, kind):
    result = analyze(tmp_path, duration=180, changes=[(4, kind, 1, 179, 0)])
    assert t_events(result, "V3") == []
    minute = result["trends"]["leads"]["V3"][1]
    assert minute["measured_t_amplitude_units"] is not None
    assert minute["coverage_pct"] == 100
    assert result["quality"]["coverage_pct"] == 100
    if kind == "spike":
        assert minute["measured_t_amplitude_units"] == -180


def test_full_engine_does_not_call_small_ripple_on_negative_st_platform_inverted_t(tmp_path):
    result = analyze(tmp_path, duration=180, changes=[(4, "plateau_ripple", 1, 179, 0)])
    assert t_events(result, "V3") == []
    assert events(result, "V3", {"st_depression"})
    minute = result["trends"]["leads"]["V3"][1]
    assert minute["measured_t_amplitude_units"] == -125
    assert minute["measured_st_level_units"] == -110
    assert minute["coverage_pct"] == 100


def test_independent_baseline_disagreement_rejects_false_st_but_keeps_numeric_level(tmp_path):
    result = analyze(tmp_path, duration=180, changes=[(4, "pr_offset", 1, 179, 150)])
    assert events(result, "V3", {"st_depression", "st_elevation"}) == []
    minute = result["trends"]["leads"]["V3"][1]
    assert minute["measured_st_level_units"] == -150
    assert minute["coverage_pct"] == 100


def test_true_broad_st_t_controls_all_survive_complete_engine(tmp_path):
    result = analyze(tmp_path, duration=360, changes=[
        (0, "ST", 1, 359, -170), (1, "ST", 61, 181, 170),
        (4, "T", 1, 121, -180), (5, "biphasic", 121, 241, 0),
        (6, "T", 181, 301, 10),
        (7, "T", 181, 301, -180), (7, "ST", 181, 301, -170),
    ])
    assert events(result, "I", {"st_depression"})
    assert events(result, "II", {"st_elevation"})
    assert events(result, "V3", {"t_persistent_inversion", "t_wave_inversion"})
    assert events(result, "V4", {"t_biphasic"})
    assert events(result, "V5", {"t_low_flat"})
    assert events(result, "V6", {"st_depression"})
    assert events(result, "V6", {"t_wave_inversion"})
    assert all(event["diagnosis"] is None and event["review_status"] == "pending"
               for event in result["candidates"])
    assert all(event["continuous_target_s"] >= 60 for event in result["candidates"])


@pytest.mark.parametrize("lead,channel", [("V1", 2), ("aVL", 0)])
def test_stable_variable_lead_negative_background_is_not_automatic_abnormality(tmp_path, lead, channel):
    result = analyze(tmp_path, duration=240, changes=[(channel, "T", 1, 239, -180)])
    assert t_events(result, lead) == []
    assert result["trends"]["leads"][lead][1]["measured_t_amplitude_units"] < -75


def test_upright_lead_broad_negative_t_from_start_is_still_a_candidate(tmp_path):
    result = analyze(tmp_path, changes=[(4, "T", 1, 239, -180)])
    found = events(result, "V3", {"t_persistent_inversion"})
    assert len(found) == 1
    assert found[0]["start_s"] == 1 and found[0]["duration_s"] >= 200


def test_variable_negative_background_dynamic_deepening_retains_true_candidate(tmp_path):
    # aVL = I-II/2: background -30-90=-120; deepening -210-90=-300.
    result = analyze(tmp_path, duration=360, changes=[
        (0, "T", 1, 359, -30), (0, "T", 121, 241, -210),
    ])
    found = events(result, "aVL", {"t_persistent_inversion"})
    assert len(found) == 1
    assert (found[0]["start_s"], found[0]["end_s"]) == (121, 241)


def test_reversal_is_one_event_not_duplicate_persistent_negative_candidate(tmp_path):
    result = analyze(tmp_path, duration=360, changes=[(4, "T", 121, 241, -180)])
    found = events(result, "V3", {"t_wave_inversion", "t_persistent_inversion"})
    assert len(found) == 1
    assert found[0]["kind"] == "t_wave_inversion"
    assert (found[0]["start_s"], found[0]["end_s"], found[0]["duration_s"]) == (121, 241, 120)


@pytest.mark.parametrize("seconds", [59, 60, 61])
def test_full_engine_requires_exact_sixty_continuous_seconds_for_st_and_t(tmp_path, seconds):
    result = analyze(tmp_path, duration=240, changes=[
        (1, "ST", 31, 31+seconds, 170), (4, "T", 31, 31+seconds, -180),
    ])
    st = events(result, "II", {"st_elevation"})
    t = events(result, "V3", {"t_wave_inversion", "t_persistent_inversion"})
    if seconds == 59:
        assert st == [] and t == []
    else:
        assert [(event["start_s"], event["end_s"], event["continuous_target_s"])
                for event in st] == [(31, 31+seconds, seconds)]
        assert [(event["start_s"], event["end_s"], event["continuous_target_s"])
                for event in t] == [(31, 31+seconds, seconds)]


def test_real_flatline_breaks_both_events_and_is_not_bridged_by_minute_averaging(tmp_path):
    result = analyze(tmp_path, duration=300, changes=[
        (1, "ST", 1, 299, 170), (4, "T", 1, 299, -180),
    ], flatline=[(121, 151)])
    for lead, kinds in [("II", {"st_elevation"}),
                        ("V3", {"t_persistent_inversion", "t_wave_inversion"})]:
        found = events(result, lead, kinds)
        assert len(found) >= 2
        assert not any(event["start_s"] < 121 and event["end_s"] > 151 for event in found)
        assert all(event["continuous_target_s"] >= 60 for event in found)
    minute = result["trends"]["leads"]["V3"][2]
    assert not minute["eligible"] and minute["coverage_pct"] < 100


@pytest.mark.parametrize("kind", ["AF", "AFL"])
def test_AF_lifecycle_does_not_change_new_candidate_selection_or_numeric_trends(tmp_path, kind):
    source = tmp_path/"synthetic-only"
    cid = "9900000000000041"
    folder = source/cid
    path, records = mathematical_recording(tmp_path, duration=240, changes=[
        (1, "ST", 31, 181, 170), (4, "T", 31, 181, -180),
        (5, "t_white_noise", 1, 239, 0),
    ])
    data = folder/"data"/(cid+".DATA")
    ebi = folder/"DGS"/(cid+".EBI")
    lps = folder/"report_image"/(cid+"_1.LPS")
    for target in (data, ebi, lps):
        target.parent.mkdir(parents=True, exist_ok=True)
    data.write_bytes(path.read_bytes())
    ebi.write_bytes(bytes(32)+b"".join(struct.pack("<IHHIIII", r[0], 1, 1, 0, 0, 0, r[6]) for r in records))
    lps.write_text("<LrScriptPage><ShapeList><PShape>记录时间：2026-01-01 08:00:00</PShape>"
                   f"<PShape>总心搏数：{len(records)}</PShape></ShapeList></LrScriptPage>", encoding="utf-8")
    app = create_app(data_root=source, db_path=tmp_path/"candidate-independence.sqlite3", testing=True)
    client = app.test_client()
    base = "/api/cases/"+cid
    response = client.get(base+"/stt-review")
    assert response.status_code == 200, response.json
    before = response.json["analysis"]
    assert events(before, "II", {"st_elevation"})
    assert events(before, "V3", {"t_wave_inversion", "t_persistent_inversion"})
    assert t_events(before, "V4") == []
    identifier = str(uuid4())
    for status in ("pending", "confirmed", "excluded", None):
        current = client.get(base+"/rhythm-review").json
        document = {"episodes": ([dict(id=identifier, start_s=20, end_s=220,
                                      kind=kind, status=status, source="manual", note="合成独立性验证")]
                                 if status else []), "bookmarks": {}}
        saved = client.put(base+"/rhythm-review", json={
            **{key: current[key] for key in ("case_id", "analysis_basis", "analysis_revision", "beat_revision")},
            "revision": current["revision"], "confirmed": True, "document": document,
        })
        assert saved.status_code == 200, saved.json
        after = client.get(base+"/stt-review")
        assert after.status_code == 200, after.json
        assert after.json["analysis"] == before
