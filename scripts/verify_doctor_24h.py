#!/usr/bin/env python3
"""Independently inspect the M01 mathematical 24-hour source and native core.

This script never imports the generator. Hashes cover each entire source file;
waveform/native ST checks use bounded raw excerpts. The complete EBI and native
NN feed are used for HRV. A passing report is engineering evidence, not clinical
validation or proof that every possible repeating period has been excluded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import re
import statistics
import struct
import sys
import tempfile
import time
from array import array
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CASE_ID = "9900000000000001"
FS = 200
CHANNELS = ("I", "II", "V1", "V2", "V3", "V4", "V5", "V6")
LEADS = ("I", "II", "III", "aVR", "aVL", "aVF",
         "V1", "V2", "V3", "V4", "V5", "V6")
FRAME_BYTES = 16
EBI_RECORD = struct.Struct("<IHHIIII")
EVENT_KINDS = {"st_offset", "af_like", "s_burst", "v_burst", "artifact", "gap"}
SOURCE_PATHS = {
    "data": f"{CASE_ID}/data/{CASE_ID}.DATA",
    "ebi": f"{CASE_ID}/DGS/{CASE_ID}.EBI",
    "lps": f"{CASE_ID}/report_image/{CASE_ID}_1.LPS",
    "events": "events.json",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def finite(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_source_path(root, text):
    require(isinstance(text, str) and "\\" not in text, "invalid manifest path")
    relative = PurePosixPath(text)
    require(not relative.is_absolute() and relative.parts
            and ".." not in relative.parts and "." not in relative.parts,
            "manifest path must be a normalized relative path")
    require(str(relative) == text, "manifest path is not canonical")
    path = root.joinpath(*relative.parts)
    require(not path.is_symlink(), f"source file must not be a symlink: {text}")
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"source path escapes root: {text}") from error
    require(path.is_file(), f"missing source file: {text}")
    return path


class Checks:
    def __init__(self):
        self.rows = []

    def run(self, name, function, *args):
        started = time.perf_counter()
        try:
            result = function(*args)
        except Exception as error:
            self.rows.append(dict(name=name, status="failed",
                                 error=f"{type(error).__name__}: {error}",
                                 elapsed_s=round(time.perf_counter() - started, 3)))
            return None
        self.rows.append(dict(name=name, status="passed", evidence=result,
                             elapsed_s=round(time.perf_counter() - started, 3)))
        return result

    def blocked(self, name, reason):
        self.rows.append(dict(name=name, status="blocked", error=reason))


def inspect_manifest(root, allow_short):
    manifest = json.loads((root / "source-manifest.json").read_text(encoding="utf-8"))
    require(manifest.get("schema_version") == 1, "manifest schema_version must be 1")
    require(manifest.get("source_id") == "M01", "source_id must be M01")
    require(manifest.get("case_id") == CASE_ID, "unexpected source case_id")
    require(manifest.get("wholly_synthetic") is True, "synthetic provenance flag is missing")
    require(manifest.get("patient_inputs_read") is False
            and manifest.get("clinical_ground_truth") is False
            and manifest.get("automatic_diagnoses") is False,
            "source must explicitly withhold patient inputs, clinical truth, and diagnoses")
    require(manifest.get("profile") == "cardioinsight-doctor-eval-synthetic-24h-v1",
            "unexpected doctor source profile")
    require(manifest.get("sample_format") == "little-endian int16"
            and manifest.get("channel_count") == 8, "unexpected raw sample format")
    require(manifest.get("sampling_rate_hz") == FS, "sampling rate must be 200 Hz")
    require(manifest.get("stored_channels") == list(CHANNELS), "stored channel order differs")
    samples = manifest.get("sample_count")
    duration = manifest.get("duration_seconds")
    require(integer(samples) and samples > 0, "sample_count must be a positive integer")
    require(finite(duration) and 0 < duration <= 86400,
            "duration_seconds must be finite and at most 24 hours")
    require(abs(samples / FS - duration) < 1e-9, "duration/sample_count mismatch")
    require(allow_short or (duration == 86400 and samples == 17_280_000),
            "doctor package requires exactly 24 hours; --allow-short is fixture-only")
    require(manifest.get("source_version") ==
            ("M01-24h-v1" if duration == 86400 else "M01-test-v1"), "source version mismatch")
    require(manifest.get("full_24h_fixture") is (duration == 86400), "full-day fixture flag mismatch")
    require(manifest.get("expected_raw_bytes") == samples * FRAME_BYTES,
            "expected_raw_bytes differs from the sample count")
    require(integer(manifest.get("seed")), "manifest seed must be an integer")
    rows = manifest.get("files")
    require(isinstance(rows, list) and len(rows) == 4, "manifest must list four source files")
    require(all(isinstance(row, dict) for row in rows), "invalid file manifest row")
    require({row.get("path") for row in rows} == set(SOURCE_PATHS.values()),
            "manifest source paths differ from the M01 contract")
    require(len({row["path"] for row in rows}) == len(rows), "duplicate manifest path")
    cases = [p.name for p in root.iterdir() if p.is_dir() and re.fullmatch(r"\d{16}", p.name)]
    require(cases == [CASE_ID], "M01 must contain exactly the reserved synthetic case")
    for row in rows:
        safe_source_path(root, row["path"])
        require(integer(row.get("size_bytes")) and row["size_bytes"] > 0,
                "file size must be a positive integer")
        require(isinstance(row.get("sha256"), str)
                and re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is not None,
                "file sha256 must be a lowercase SHA-256 digest")
    return manifest


def inspect_hashes(root, manifest):
    evidence = []
    for row in manifest["files"]:
        path = safe_source_path(root, row["path"])
        size = path.stat().st_size
        digest = sha256_file(path)
        require(size == row["size_bytes"], f"size mismatch: {row['path']}")
        require(digest == row["sha256"], f"SHA-256 mismatch: {row['path']}")
        evidence.append(dict(path=row["path"], size_bytes=size, sha256=digest))
    dataset = hashlib.sha256()
    for row in sorted(manifest["files"], key=lambda item: item["path"]):
        dataset.update(row["path"].encode("utf-8"))
        dataset.update(row["sha256"].encode("ascii"))
    require(dataset.hexdigest() == manifest.get("dataset_sha256"), "dataset digest mismatch")
    raw_size = (root / SOURCE_PATHS["data"]).stat().st_size
    require(raw_size == manifest["sample_count"] * FRAME_BYTES,
            "raw DATA does not contain the declared complete samples")
    return dict(algorithm="SHA-256", complete_file_hashes=True, files=evidence,
                dataset_sha256=dataset.hexdigest(), raw_size_bytes=raw_size,
                actual_duration_s=raw_size / (FRAME_BYTES * FS))


def inspect_ebi(root, manifest):
    payload = (root / SOURCE_PATHS["ebi"]).read_bytes()
    require(len(payload) >= 32 + EBI_RECORD.size, "EBI is empty or truncated")
    require((len(payload) - 32) % EBI_RECORD.size == 0, "EBI record tail is truncated")
    records = tuple(EBI_RECORD.iter_unpack(payload[32:]))
    require(records[0][6] == 0, "first stored RR must be zero")
    require(all(0 <= row[0] < manifest["sample_count"] for row in records),
            "EBI position is outside the raw recording")
    require(all(row[2] in (1, 2, 3, 8, 34) for row in records),
            "source uses an unexpected synthetic beat group")
    require(all(left[0] < right[0] for left, right in zip(records, records[1:])),
            "EBI positions must be strictly increasing")
    require(all(right[6] == (right[0] - left[0]) * 5
                for left, right in zip(records, records[1:])),
            "stored RR must exactly equal adjacent sample delta times 5 ms")
    return dict(record_count=len(records),
                group_counts={str(k): v for k, v in sorted(Counter(r[2] for r in records).items())},
                first_sample=records[0][0], last_sample=records[-1][0],
                header_ascii=payload[:32].rstrip(b"\0").decode("ascii", errors="replace"),
                monotonic=True, bounds_verified=True, stored_rr_delta_mismatches=0)


def independent_records(root):
    payload = (root / SOURCE_PATHS["ebi"]).read_bytes()
    return tuple(EBI_RECORD.iter_unpack(payload[32:]))


def inspect_events(root, manifest, allow_short):
    document = json.loads((root / "events.json").read_text(encoding="utf-8"))
    require(document.get("schema_version") == 1, "events schema_version must be 1")
    require(document.get("kind") == "mathematical_reference_events",
            "events must be mathematical references")
    require(document.get("clinical_ground_truth") is False
            and document.get("automatic_diagnoses") is False,
            "events must not claim clinical truth or automatic diagnoses")
    require(document.get("interval_semantics") == "half_open_samples",
            "events must use half-open sample intervals")
    events = document.get("events")
    require(isinstance(events, list), "events must be a list")
    identifiers = set()
    previous_end = 0
    for event in events:
        require(isinstance(event, dict), "event must be an object")
        identifier = event.get("id")
        require(isinstance(identifier, str) and identifier and identifier not in identifiers,
                "event IDs must be nonempty and unique")
        identifiers.add(identifier)
        require(event.get("kind") in EVENT_KINDS, "unsupported mathematical event kind")
        require(event.get("reference_only") is True, "event reference_only must be true")
        start, end = event.get("start_sample"), event.get("end_sample")
        require(integer(start) and integer(end) and 0 <= start < end <= manifest["sample_count"],
                "event is outside the raw sample bounds")
        require(start >= previous_end, "event ranges must be ordered and nonoverlapping")
        previous_end = end
        require(finite(event.get("start_s")) and finite(event.get("end_s"))
                and abs(event["start_s"] - start / FS) < 1e-9
                and abs(event["end_s"] - end / FS) < 1e-9,
                "event seconds/sample coordinates disagree")
        require(isinstance(event.get("label"), str) and event["label"],
                "event label must be explicit")
        require(isinstance(event.get("parameters"), dict), "event parameters must be an object")
        if event["kind"] == "st_offset":
            require(allow_short or (end - start) / FS >= 60,
                    "ST reference must last at least one minute")
            offsets = event["parameters"].get("offsets_device_units")
            require(isinstance(offsets, dict) and offsets
                    and all(k in CHANNELS and finite(v) and v != 0 for k, v in offsets.items()),
                    "ST reference requires nonzero stored-lead device offsets")
    if not allow_short:
        require({event["kind"] for event in events} == EVENT_KINDS,
                "full doctor source must include all six mathematical event kinds")
        require(sum(event["kind"] == "st_offset" for event in events) >= 2,
                "full doctor source must include both sustained ST offsets")
    return dict(event_count=len(events), events=events,
                reference_only=True, clinical_ground_truth=False, automatic_diagnoses=False)


def native_modules():
    from ecg_core import ebi
    from ecg_core.beat_editor import EditedRecords, blank
    from ecg_core.hrv_analysis import analyze_hrv
    from ecg_core.repository import CaseRepository
    from ecg_core.rr_quality import nn_intervals
    from ecg_core.storage import Storage
    from ecg_core.stt import analyze_stt
    from ecg_core.waveform import read_waveform
    return dict(ebi=ebi, EditedRecords=EditedRecords, blank=blank,
                analyze_hrv=analyze_hrv, CaseRepository=CaseRepository,
                nn_intervals=nn_intervals, Storage=Storage,
                analyze_stt=analyze_stt, read_waveform=read_waveform)


def inspect_native_case(root, manifest, modules):
    class SyntheticOnlyRepository(modules["CaseRepository"]):
        @staticmethod
        def _manifest():
            # Only the supplied M01 root is in scope. Do not inspect a workstation's
            # global imported-case catalog or repository patient manifest.
            return {}

    case = SyntheticOnlyRepository(root).get_case(CASE_ID)
    require(case["technical"]["duration_seconds_raw"] == manifest["duration_seconds"],
            "native repository duration differs")
    require(case["technical"]["raw_size_bytes"] == manifest["expected_raw_bytes"],
            "native repository raw size differs")
    require(case["metadata"]["patient_id"] == "", "synthetic source must omit a patient ID")
    require(all(case["metadata"].get(key) in ("", None) for key in
                ("sex", "age", "bed", "department", "requesting_physician")),
            "synthetic source must omit personal and hospital fields")
    require(bool(case["metadata"]["start_iso"]), "native LPS lacks a usable start time")
    require(case["metadata"]["duration_seconds_reported"] == round(manifest["duration_seconds"] / 60) * 60,
            "LPS reported duration differs from the raw source")
    require(case["metadata"]["clinical_diagnosis"] == "",
            "mathematical source must not prepopulate a clinical diagnosis")
    records = modules["ebi"].load_records(str(root / SOURCE_PATHS["ebi"]))
    require(records == independent_records(root), "native EBI reader differs from direct records")
    require("合成" in case["conclusion"] and "不" in case["conclusion"],
            "LPS must explicitly identify synthetic nonclinical report text")
    return dict(case_id=case["case_id"], metadata=case["metadata"],
                technical=case["technical"], native_ebi_parity=True,
                global_case_manifest_lookup=False,
                conclusion=case["conclusion"])


def read_frames(path, start_sample, count):
    require(start_sample >= 0 and count > 0, "invalid excerpt")
    with path.open("rb") as stream:
        stream.seek(start_sample * FRAME_BYTES)
        payload = stream.read(count * FRAME_BYTES)
    require(len(payload) == count * FRAME_BYTES, "raw excerpt is truncated")
    values = array("h")
    values.frombytes(payload)
    if sys.byteorder != "little":
        values.byteswap()
    return payload, [list(values[i::8]) for i in range(8)]


def independent_leads(channels):
    a, b = channels[0], channels[1]
    result = dict(I=a, II=b,
                  III=[y - x for x, y in zip(a, b)],
                  aVR=[-(x + y) / 2 for x, y in zip(a, b)],
                  aVL=[x - y / 2 for x, y in zip(a, b)],
                  aVF=[y - x / 2 for x, y in zip(a, b)])
    result.update({name: channels[i] for i, name in enumerate(CHANNELS) if i >= 2})
    return result


def inspect_windows(root, manifest, modules, native_case):
    total = manifest["sample_count"]
    duration = manifest["duration_seconds"]
    count = min(10 * FS, max(FS, total // 6))
    clock = datetime.fromisoformat(native_case["metadata"]["start_iso"])
    if duration == 86400:
        starts = [round((hour * 3600 + 900) * FS) for hour in range(24)]
    else:
        starts = sorted({round((total - count) * i / 5) for i in range(6)})
    evidence = []
    for start in starts:
        payload, channels = read_frames(root / SOURCE_PATHS["data"], start, count)
        expected = independent_leads(channels)
        native = modules["read_waveform"](root / SOURCE_PATHS["data"], start / FS,
                                         count / FS, list(LEADS), 12000, False)
        require(native["stride"] == 1 and native["filter"] == "raw",
                "12-lead comparison must use full-resolution raw samples")
        require(native["leads"] == expected,
                f"native 12-lead formulas differ at sample {start}")
        wall_clock = clock + timedelta(seconds=start / FS)
        evidence.append(dict(start_sample=start, end_sample=start + count,
                             start_s=start / FS, duration_s=count / FS,
                             clock=wall_clock.isoformat(),
                             clock_period="day" if 6 <= wall_clock.hour < 22 else "night",
                             raw_sha256=hashlib.sha256(payload).hexdigest(),
                             raw_sample_count=count, lead_count=12,
                             derived_formula_mismatches=0,
                             channel_min=[min(values) for values in channels],
                             channel_max=[max(values) for values in channels]))
    unique = len({row["raw_sha256"] for row in evidence})
    require(unique == len(evidence), "sampled day/night raw windows are identical")
    if duration == 86400:
        periods = Counter(row["clock_period"] for row in evidence)
        require(periods["day"] >= 2 and periods["night"] >= 2,
                "multiple independent day and night windows are required")
        require(len(evidence) == 24, "full-day source requires 24 raw windows")
    return dict(windows=evidence, all_windows_distinct=True,
                raw_full_resolution=True, independent_derived_leads=True)


def correlation(a, b):
    left, right = statistics.mean(a), statistics.mean(b)
    numerator = sum((x - left) * (y - right) for x, y in zip(a, b))
    denominator = math.sqrt(sum((x - left) ** 2 for x in a)
                            * sum((y - right) ** 2 for y in b))
    return round(numerator / denominator, 6) if denominator else None


def inspect_lags(root, manifest):
    total = manifest["sample_count"]
    count = min(10 * FS, max(1, total - 5 * FS))
    observations = []
    for lag_s in (5, 10, 30, 60, 300, 600, 1800, 3600):
        lag = lag_s * FS
        maximum = total - count - lag
        if maximum < 0:
            continue
        for start in sorted({0, maximum // 2, maximum}):
            left, a = read_frames(root / SOURCE_PATHS["data"], start, count)
            right, b = read_frames(root / SOURCE_PATHS["data"], start + lag, count)
            changed = sum(x != y for x, y in zip(a[1], b[1]))
            require(left != right, f"exact raw repeat found at {lag_s}s lag/sample {start}")
            observations.append(dict(lag_s=lag_s, start_sample=start,
                                     comparison_sample=start + lag,
                                     raw_equal=False, ii_changed_fraction=round(changed / count, 6),
                                     ii_pearson=correlation(a[1], b[1])))
    require(observations, "record is too short for any repetition probe")
    return dict(observations=observations, exact_repeat_detected=False,
                exhaustive_periodicity_proof=False,
                scope="Eight candidate lags at up to three locations, using 10-second raw excerpts")


def inspect_native_hrv(root, manifest, modules, native_case, context):
    records = modules["ebi"].load_records(str(root / SOURCE_PATHS["ebi"]))
    feed = modules["EditedRecords"](records, modules["blank"](), (), manifest["duration_seconds"])
    nn = modules["nn_intervals"](feed)
    context.update(feed=feed, nn=nn)
    require(len(nn) >= 3, "too few complete native NN intervals")
    require(all(math.isfinite(row[3]) and row[3] > 0 for row in nn),
            "native NN intervals contain invalid values")
    hrv = modules["analyze_hrv"](feed, native_case["metadata"]["start_iso"])
    require(hrv["actual_duration_s"] == manifest["duration_seconds"]
            and hrv["start_s"] == 0 and hrv["end_s"] == manifest["duration_seconds"],
            "native HRV did not analyze the complete source duration")
    full = hrv["periods"]["full"]
    require(full["nn_count"] == len(nn), "native full HRV lost NN intervals")
    require(all(finite(full.get(key)) for key in ("mean_nn_ms", "sdnn_ms", "rmssd_ms", "pnn50_pct")),
            "native full HRV time metrics are missing")
    require(full["sdnn_ms"] > 0 and full["rmssd_ms"] > 0, "RR variation is absent")
    if manifest["duration_seconds"] == 86400:
        require(len(nn) >= 60_000, "full-day source must retain at least 60000 native NN intervals")
        require(nn[0][1] <= 10 and nn[-1][2] >= 86390,
                "NN evidence does not reach both ends of the day")
        require(full["five_minute_blocks"] > 0 and full["spectral_blocks"] > 0,
                "native HRV has no eligible short spectra")
        require(hrv["periods"]["day"]["nn_count"] > 0
                and hrv["periods"]["night"]["nn_count"] > 0,
                "native day/night HRV is empty")
        require(abs(hrv["periods"]["day"]["mean_nn_ms"]
                    - hrv["periods"]["night"]["mean_nn_ms"]) > 10,
                "native day/night mean NN does not show the intended modulation")
    compact_periods = {name: {key: value for key, value in period.items()
                             if key not in ("histogram", "psd")}
                       for name, period in hrv["periods"].items()}
    return dict(actual_duration_s=hrv["actual_duration_s"],
                nn_count=len(nn), nn_start_s=nn[0][1], nn_end_s=nn[-1][2],
                valid_nn_duration_s=round(sum(row[3] for row in nn) / 1000, 3),
                hourly_count=len(hrv["hourly"]), periods=compact_periods,
                native_schema=hrv["schema_version"], native_method=hrv["method"],
                source_group_8_is_unclassified=True,
                native_full_nn_sha256=hashlib.sha256(
                    json.dumps(nn, separators=(",", ":"), allow_nan=False).encode("ascii")).hexdigest(),
                spectral_scope="Mean of eligible native short-segment spectra; not a concatenated 24-hour spectrum")


def inspect_review_workflow(modules):
    with tempfile.TemporaryDirectory(prefix="doctor24h-review-") as folder:
        from ecg_core.workspace_backup import _DetachedConnection
        storage = modules["Storage"](Path(folder) / "review.sqlite3", connection_factory=_DetachedConnection)
        review = storage.get_review(CASE_ID)
        require(set(review["pending_steps"]) == {"edit", "stt"}
                and review["report_status"] == "draft",
                "new synthetic source must start with pending physician review")
        require(review["steps"] == {} and review["events"] == {},
                "mathematical references must not create physician review decisions")
        return dict(pending_steps=review["pending_steps"], report_status=review["report_status"],
                    revision=review["revision"], isolated_temporary_workspace=True,
                    no_phantom_physician_review=True)


def inspect_native_environment(modules):
    loaded = native_modules()
    modules.update(loaded)
    import numpy
    return dict(python=platform.python_version(), numpy=numpy.__version__,
                native_apis=sorted(loaded), generator_imported=False)


def evenly(rows, limit=128):
    if len(rows) <= limit:
        return rows
    return [rows[round(index * (len(rows) - 1) / (limit - 1))] for index in range(limit)]


def rows_in(records, start, end, group=None):
    return [row for row in records if start <= row[0] < end
            and (group is None or row[2] == group)]


def baseline_rows(records, event, total, margin_s=30, extent_s=150):
    start, end = event["start_sample"], event["end_sample"]
    return [row for row in records if row[2] == 1 and
            (max(52, start - extent_s * FS) <= row[0] < start - margin_s * FS
             or end + margin_s * FS <= row[0] < min(total - 40, end + extent_s * FS))]


def beat_levels(path, rows, channels):
    levels = {name: [] for name in channels}
    for row in evenly(rows):
        _, raw = read_frames(path, row[0] - 52, 92)
        for name in channels:
            values = raw[CHANNELS.index(name)]
            # This independent reference measurement is not the native J+60-ms algorithm.
            baseline = statistics.median(values[30:37])  # R-110..80 ms
            plateau = statistics.median(values[72:82])   # R+100..145 ms
            levels[name].append((row[0], plateau - baseline))
    return levels


def consecutive_seconds(indices, bin_s=10):
    best = current = 0
    previous = None
    for value in sorted(set(indices)):
        current = current + 1 if previous is not None and value == previous + 1 else 1
        best = max(best, current)
        previous = value
    return best * bin_s


def inspect_st_samples(root, manifest, event, records):
    path = root / SOURCE_PATHS["data"]
    offsets = event["parameters"]["offsets_device_units"]
    interior = rows_in(records, event["start_sample"] + 10 * FS,
                       event["end_sample"] - 10 * FS, 1)
    controls = baseline_rows(records, event, manifest["sample_count"])
    require(len(interior) >= 30 and len(controls) >= 30, "ST reference lacks enough normal controls")
    levels = beat_levels(path, interior, offsets)
    base = beat_levels(path, controls, offsets)
    evidence = {}
    for lead, declared in offsets.items():
        control_level = statistics.median(value for _, value in base[lead])
        event_level = statistics.median(value for _, value in levels[lead])
        deviation = event_level - control_level
        require(deviation * declared > 0 and abs(deviation) >= abs(declared) * 0.35,
                f"ST {event['id']} {lead} raw deviation {deviation:.3f} lacks expected polarity/amplitude")
        bins = {}
        for sample, value in levels[lead]:
            bins.setdefault((sample - event["start_sample"]) // (10 * FS), []).append(value)
        strong = [key for key, values in bins.items()
                  if (statistics.median(values) - control_level) * declared > 0
                  and abs(statistics.median(values) - control_level) >= abs(declared) * 0.35]
        sustained = consecutive_seconds(strong)
        require(sustained >= 60, f"ST {event['id']} {lead} is not sustained for one minute")
        evidence[lead] = dict(declared_offset_device_units=declared,
                             control_level_device_units=round(control_level, 3),
                             event_level_device_units=round(event_level, 3),
                             independent_deviation_device_units=round(deviation, 3),
                             qualified_contiguous_bin_duration_s=sustained,
                             observed_beats=len(levels[lead]))
    return dict(id=event["id"], kind="st_offset", leads=evidence,
                measurement="Median R+100..145 ms minus median R-110..80 ms; local N controls",
                voltage_calibrated=False, clinical_validation=False)


def p_prominences(path, rows):
    observations = []
    for row in evenly([row for row in rows if row[6] >= 800]):
        _, channels = read_frames(path, row[0] - 52, 34)
        values = channels[1]
        left = statistics.median(values[0:7])    # R-260..230 ms
        center = statistics.median(values[13:20])  # R-195..165 ms
        right = statistics.median(values[26:33])   # R-130..100 ms
        observations.append(center - (left + right) / 2)
    return observations


def inspect_af_samples(root, manifest, event, records):
    selected = rows_in(records, event["start_sample"], event["end_sample"])
    require(len(selected) >= 30 and all(row[2] == 8 for row in selected),
            "AF-like construction labels must all be unclassified group 8")
    require(event["parameters"].get("p_wave_omitted") is True
            and event["parameters"].get("diagnosis") is None,
            "AF-like reference must declare omitted P and no diagnosis")
    rr = [row[6] for row in selected[1:]]
    cv = statistics.stdev(rr) / statistics.mean(rr)
    require(cv > 0.08 and len(set(rr)) >= 10,
            f"AF-like RR does not show intended irregularity: CV={cv:.4f}")
    controls = baseline_rows(records, event, manifest["sample_count"])
    af_p = p_prominences(root / SOURCE_PATHS["data"], selected[1:])
    normal_p = p_prominences(root / SOURCE_PATHS["data"], controls)
    require(len(af_p) >= 10 and len(normal_p) >= 10, "too few isolated P-region controls")
    af_median, normal_median = statistics.median(af_p), statistics.median(normal_p)
    require(normal_median > 5 and af_median < max(35, normal_median * 0.7),
            f"AF-like P-region prominence not reduced: AF={af_median:.3f}, N={normal_median:.3f}")
    return dict(id=event["id"], kind="af_like", source_group=8,
                beat_count=len(selected), rr_cv=round(cv, 6), distinct_rr=len(set(rr)),
                rr_min_ms=min(rr), rr_max_ms=max(rr),
                p_region_prominence_device_units=round(af_median, 3),
                control_p_prominence_device_units=round(normal_median, 3),
                p_region_observations=len(af_p), control_observations=len(normal_p),
                p_measurement="II R-195..165 ms relative to flanking shoulders, stored RR >=800 ms",
                diagnosis=None, clinical_ground_truth=False)


def inspect_burst(event, records):
    group = 2 if event["kind"] == "s_burst" else 3
    selected = rows_in(records, event["start_sample"], event["end_sample"])
    require(event["parameters"].get("source_group") == group, "burst source group mismatch")
    require(all(row[2] in (1, group) for row in selected), "unexpected labels inside burst")
    count = sum(row[2] == group for row in selected)
    best = current = runs = 0
    for row in selected:
        if row[2] == group:
            current += 1
            if current == 3:
                runs += 1
            best = max(best, current)
        else:
            current = 0
    require(count >= 3 and best >= 3 and runs >= 1,
            "construction burst requires at least three consecutive selected labels")
    return dict(id=event["id"], kind=event["kind"], source_group=group,
                beat_count=len(selected), selected_group_count=count,
                longest_selected_group_run=best, runs_reaching_three=runs,
                labels_are_mathematical_references=True)


def difference_rms(values):
    return math.sqrt(statistics.mean((b - a) ** 2 for a, b in zip(values, values[1:])))


def inspect_artifact(root, manifest, event, records):
    selected = rows_in(records, event["start_sample"], event["end_sample"])
    require(selected and all(row[2] == 34 for row in selected),
            "artifact must use group 34 construction markers")
    count = min(10 * FS, event["end_sample"] - event["start_sample"])
    start = event["start_sample"] + (event["end_sample"] - event["start_sample"] - count) // 2
    control_start = max(0, event["start_sample"] - 30 * FS)
    _, artifact = read_frames(root / SOURCE_PATHS["data"], start, count)
    _, control = read_frames(root / SOURCE_PATHS["data"], control_start, count)
    observations = {}
    for name in ("II", "V5"):
        index = CHANNELS.index(name)
        amplitude = difference_rms(artifact[index])
        reference = difference_rms(control[index])
        require(amplitude > reference * 1.5,
                f"artifact {name} first-difference RMS {amplitude:.3f} lacks intended noise")
        observations[name] = dict(first_difference_rms_device_units=round(amplitude, 3),
                                  control_first_difference_rms_device_units=round(reference, 3),
                                  rms_ratio=round(amplitude / max(reference, 1e-9), 3))
    return dict(id=event["id"], kind="artifact", source_group=34,
                construction_marker_count=len(selected), sampled_start_sample=start,
                sampled_duration_s=count / FS, noise_evidence=observations)


def inspect_gap(root, manifest, event, records):
    first, last = event["start_sample"], event["end_sample"]
    payload, _ = read_frames(root / SOURCE_PATHS["data"], first, last - first)
    require(not any(payload), "gap must contain exact zeros in every stored channel/sample")
    selected = rows_in(records, first, last)
    require(selected and all(row[2] == 34 for row in selected),
            "gap must have group 34 markers and no physiological beat labels")
    before, _ = read_frames(root / SOURCE_PATHS["data"], max(0, first - FS), min(FS, first))
    require(any(before), "zero gap unexpectedly extends into its preceding control")
    if last + FS <= manifest["sample_count"]:
        after, _ = read_frames(root / SOURCE_PATHS["data"], last, FS)
        require(any(after), "zero gap unexpectedly extends into its following control")
    return dict(id=event["id"], kind="gap", start_sample=first, end_sample=last,
                sample_count=last - first, zero_sample_frames=last - first,
                zero_values=(last - first) * 8, construction_marker_count=len(selected),
                physiological_beat_labels=0)


def inspect_event(root, manifest, event, records):
    if event["kind"] == "st_offset":
        return inspect_st_samples(root, manifest, event, records)
    if event["kind"] == "af_like":
        return inspect_af_samples(root, manifest, event, records)
    if event["kind"] in ("s_burst", "v_burst"):
        return inspect_burst(event, records)
    if event["kind"] == "artifact":
        return inspect_artifact(root, manifest, event, records)
    return inspect_gap(root, manifest, event, records)


def inspect_native_exclusions(events, context):
    require("feed" in context and "nn" in context, "native NN feed is unavailable")
    feed, nn = context["feed"], context["nn"]
    evidence = []
    for event in events:
        if event["kind"] not in ("af_like", "artifact", "gap"):
            continue
        start, end = event["start_s"], event["end_s"]
        crossings = sum(a < end and b > start for _, a, b, _ in nn)
        require(crossings == 0, f"native NN bridges {event['kind']} reference")
        codes = Counter(row["class_code"] for row in feed.beats
                        if event["start_sample"] <= row["sample_index"] < event["end_sample"])
        expected = "OTHER" if event["kind"] == "af_like" else "X"
        require(set(codes) == {expected}, "native labels do not preserve conservative source classes")
        evidence.append(dict(id=event["id"], native_class_counts=dict(codes),
                             overlapping_native_nn_intervals=crossings,
                             automatic_rhythm_annotation_created=False))
    return dict(events=evidence, source_labels_only=True,
                automatic_diagnoses=False, native_nn_does_not_bridge_reference_ranges=True)


def inspect_native_stt(root, manifest, event, records, modules):
    start = max(0, event["start_sample"] - 180 * FS)
    end = min(manifest["sample_count"], event["end_sample"] + 180 * FS)
    payload, _ = read_frames(root / SOURCE_PATHS["data"], start, end - start)
    selected = rows_in(records, start, end)
    rebased = tuple((row[0] - start, *row[1:]) for row in selected)
    with tempfile.TemporaryDirectory(prefix="doctor24h-stt-") as folder:
        path = Path(folder) / "bounded-stt.DATA"
        path.write_bytes(payload)
        result = modules["analyze_stt"](path, rebased, (end - start) / FS)
    require(result["status"] == "completed", "native ST analysis did not complete")
    require(result["quality"]["eligible_blocks"] > 0, "native ST has no eligible blocks")
    offsets = event["parameters"]["offsets_device_units"]
    signs = {1 if value > 0 else -1 for value in offsets.values()}
    desired = {"st_elevation" if sign > 0 else "st_depression" for sign in signs}
    matches = [candidate for candidate in result["candidates"]
               if candidate["kind"] in desired
               and set(candidate["leads"]) & set(offsets)
               and candidate["start_s"] + start / FS < event["end_s"]
               and candidate["end_s"] + start / FS > event["start_s"]]
    require(matches, f"native ST found no overlapping expected candidate for {event['id']}")
    for candidate in result["candidates"]:
        require(candidate.get("diagnosis") is None and candidate.get("review_status") == "pending",
                "native ST must emit pending review candidates")
    projected = [{**candidate, "record_start_s": candidate["start_s"] + start / FS,
                  "record_end_s": candidate["end_s"] + start / FS}
                 for candidate in result["candidates"]]
    return dict(id=event["id"], algorithm_version=result["algorithm_version"],
                raw_excerpt_start_sample=start, raw_excerpt_end_sample=end,
                raw_excerpt_duration_s=(end - start) / FS,
                raw_excerpt_sha256=hashlib.sha256(payload).hexdigest(),
                quality=result["quality"], summary=result["summary"],
                matching_reference_candidates=len(matches), candidates=projected,
                units=result["units"], calibration_status=result["calibration_status"],
                algorithm_modified=False, clinical_validation=False)


def verify(source_root, output, allow_short=False):
    started = time.perf_counter()
    source_root, output = source_root.expanduser().resolve(), output.expanduser().resolve()
    try:
        output.relative_to(source_root)
    except ValueError:
        pass
    else:
        raise ValueError("validation output must be outside the immutable source root")
    checks = Checks()
    manifest = checks.run("source_manifest", inspect_manifest, source_root, allow_short)
    raw = ebi = events = native_case = windows = lags = native_hrv = workflow = exclusions = None
    event_evidence, stt_evidence = [], []
    modules, context = {}, {}
    if manifest is not None:
        raw = checks.run("complete_source_sha256", inspect_hashes, source_root, manifest)
        ebi = checks.run("complete_ebi_rr_and_bounds", inspect_ebi, source_root, manifest)
        events = checks.run("mathematical_event_schema", inspect_events, source_root, manifest, allow_short)
        lags = checks.run("sampled_raw_repeat_lags", inspect_lags, source_root, manifest)
        if ebi is not None and events is not None:
            records = independent_records(source_root)
            for event in events["events"]:
                evidence = checks.run(f"raw_event_{event['id']}", inspect_event,
                                      source_root, manifest, event, records)
                if evidence is not None:
                    event_evidence.append(evidence)
        environment = checks.run("native_environment", inspect_native_environment, modules)
        if environment is not None and ebi is not None:
            native_case = checks.run("native_repository_and_readers", inspect_native_case,
                                     source_root, manifest, modules)
            workflow = checks.run("native_pending_review_workflow", inspect_review_workflow, modules)
            if native_case is not None:
                windows = checks.run("raw_12_lead_day_night_windows", inspect_windows,
                                     source_root, manifest, modules, native_case)
                native_hrv = checks.run("native_full_duration_nn_hrv", inspect_native_hrv,
                                        source_root, manifest, modules, native_case, context)
            if events is not None:
                if "nn" in context:
                    exclusions = checks.run("native_nn_reference_exclusions", inspect_native_exclusions,
                                            events["events"], context)
                else:
                    checks.blocked("native_nn_reference_exclusions", "native NN feed is unavailable")
                for event in events["events"]:
                    if event["kind"] == "st_offset":
                        evidence = checks.run(f"native_stt_{event['id']}", inspect_native_stt,
                                              source_root, manifest, event,
                                              independent_records(source_root), modules)
                        if evidence is not None:
                            stt_evidence.append(evidence)
        else:
            checks.blocked("native_repository_and_analysis", "native environment or EBI contract failed")
    else:
        checks.blocked("source_and_native_analysis", "source manifest contract failed")
    passed = all(row["status"] == "passed" for row in checks.rows)
    result = dict(
        schema_version=1, kind="doctor_24h_engineering_validation",
        status="passed" if passed else "failed",
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        elapsed_s=round(time.perf_counter() - started, 3),
        validator_sha256=sha256_file(Path(__file__)),
        source=dict(source_id="M01", case_id=CASE_ID,
                    source_version=manifest.get("source_version") if manifest else None,
                    duration_seconds=manifest.get("duration_seconds") if manifest else None,
                    sample_count=manifest.get("sample_count") if manifest else None,
                    dataset_sha256=manifest.get("dataset_sha256") if manifest else None),
        full_day_requirement_met=bool(manifest and manifest["duration_seconds"] == 86400),
        fixture_mode=allow_short, raw=raw, ebi=ebi, raw_windows=windows, repeat_lags=lags,
        reference_events=event_evidence, native_case=native_case, native_hrv=native_hrv,
        native_stt=stt_evidence, native_review_workflow=workflow, native_nn_exclusions=exclusions,
        checks=checks.rows,
        scope=dict(complete_source_hashes=raw is not None,
                   complete_ebi_checked=ebi is not None,
                   full_native_nn_feed=native_hrv is not None,
                   native_analysis_algorithms_modified=False,
                   whole_day_waveform_loaded_into_browser=False,
                   mathematical_reference_events_are_clinical_truth=False,
                   clinical_validation=False, actual_windows10_smoke_test=False,
                   exhaustive_nonperiodicity_proof=False,
                   repetition_evidence="24 deterministic 10-second raw day/night windows for a full day; eight candidate lags at three sites",
                   stt_evidence="Native unchanged algorithm on event windows with 180-second context; not an entire-day ST analysis",
                   hrv_evidence="Complete native NN feed; spectra retain native eligible short-segment aggregation",
                   source_provenance="Manifest declaration, file hashes, reserved fixture identity, and independent mathematical event observations"),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                      encoding="utf-8")
    print(json.dumps(dict(status=result["status"], source=result["source"],
                          output=str(output), passed_checks=sum(row["status"] == "passed"
                                                               for row in checks.rows),
                          failed_checks=[{"name": row["name"], "error": row.get("error", "")} for row in checks.rows
                                         if row["status"] != "passed"]),
                     ensure_ascii=False, allow_nan=False))
    return 0 if passed else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path("Sources/M01"))
    parser.add_argument("--output", type=Path, default=Path("validation.json"))
    parser.add_argument("--allow-short", action="store_true",
                        help="Allow developer fixtures; never satisfies the doctor package full-day requirement")
    args = parser.parse_args(argv)
    try:
        from ecg_core.source_identity import read_locked_sources
        root = args.source_root.resolve()
        source_files = [root / CASE_ID / "data" / (CASE_ID + ".DATA"),
                        root / CASE_ID / "DGS" / (CASE_ID + ".EBI"),
                        root / CASE_ID / "report_image" / (CASE_ID + "_1.LPS")]
        with read_locked_sources(source_files):
            return verify(args.source_root, args.output, args.allow_short)
    except (OSError, ValueError) as error:
        print(f"Validation could not write a report: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
