#!/usr/bin/env python3
"""Benchmark fresh Windows request source leases using one newly generated M01.

The JSON receipt contains mathematical-source hashes and timing/count summaries.
DATA, the disposable application workspace and databases remain in a temporary
directory and are removed. No existing case, report or database is accepted.
"""
from __future__ import annotations

import argparse
from array import array
from contextlib import ExitStack
import gc
import hashlib
import inspect
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import threading
import time
from unittest.mock import patch
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CASE_ID = "9900000000000001"
RAW_BYTES = 276480000
LEADS = ("I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6")
SOURCE_PATHS = {
    "DATA": f"{CASE_ID}/data/{CASE_ID}.DATA",
    "EBI": f"{CASE_ID}/DGS/{CASE_ID}.EBI",
    "LPS": f"{CASE_ID}/report_image/{CASE_ID}_1.LPS",
}
# Only explicit top-level scalar operation guards may differ. Identity and
# diagnostic fields, including all complete beat dictionaries, are retained.
OPERATION_GUARDS = frozenset({
    "roi_nonce", "roi_expires_at", "roi_expiry",
    "request_nonce", "request_expires_at", "request_expiry", "nonce", "expires_at",
})


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def diagnostic_projection(document):
    removed = []
    result = {}
    for key, value in document.items():
        if key in OPERATION_GUARDS and not isinstance(value, (dict, list)):
            removed.append(key)
        else:
            result[key] = value
    return result, sorted(removed)


class CountedReader:
    """Count actual read bytes only inside a DATA _content_hash invocation."""
    def __init__(self, stream, event):
        self.stream, self.event = stream, event

    def read(self, *args, **kwargs):
        result = self.stream.read(*args, **kwargs)
        self.event["bytes_read"] += len(result)
        return result

    def readinto(self, buffer):
        count = self.stream.readinto(buffer)
        self.event["bytes_read"] += count or 0
        return count

    def __enter__(self):
        self.stream.__enter__()
        return self

    def __exit__(self, *args):
        return self.stream.__exit__(*args)

    def __getattr__(self, name):
        return getattr(self.stream, name)


class HashCounter:
    def __init__(self, identity, data_path, expected_sha):
        self.identity = identity
        self.data_path = data_path.resolve()
        self.expected_sha = expected_sha
        self.original_hash = identity._content_hash
        self.original_open = Path.open
        self.local = threading.local()
        self.events = []

    def reset(self):
        self.events = []

    def tracked_open(self, path, *args, **kwargs):
        stream = self.original_open(path, *args, **kwargs)
        event = getattr(self.local, "data_hash_event", None)
        if event is not None and path.resolve() == self.data_path:
            return CountedReader(stream, event)
        return stream

    def tracked_hash(self, path):
        if Path(path).resolve() != self.data_path:
            return self.original_hash(path)
        event = {"bytes_read": 0, "elapsed_seconds": 0.0, "content_matches": False}
        self.events.append(event)
        previous = getattr(self.local, "data_hash_event", None)
        self.local.data_hash_event = event
        started = time.perf_counter()
        try:
            digest = self.original_hash(path)
            event["content_matches"] = digest == self.expected_sha
            return digest
        finally:
            event["elapsed_seconds"] = time.perf_counter() - started
            self.local.data_hash_event = previous

    def install(self, stack):
        stack.enter_context(patch.object(self.identity, "_content_hash", self.tracked_hash))
        counter = self
        def tracked_open(path, *args, **kwargs):
            return counter.tracked_open(path, *args, **kwargs)
        stack.enter_context(patch.object(Path, "open", tracked_open))

    def snapshot(self):
        events = [dict(event) for event in self.events]
        return {
            "data_calls": len(events),
            "data_bytes_read": sum(event["bytes_read"] for event in events),
            "data_hash_seconds": sum(event["elapsed_seconds"] for event in events),
            "events": events,
        }


def prove_generated_math_source(root, manifest):
    require(manifest["case_id"] == CASE_ID and manifest["source_id"] == "M01",
            "unexpected generated fixture identity")
    require(manifest.get("wholly_synthetic") is True
            and manifest.get("patient_inputs_read") is False
            and manifest.get("clinical_ground_truth") is False
            and manifest.get("automatic_diagnoses") is False,
            "benchmark requires explicit mathematical-only provenance")
    require(manifest["duration_seconds"] == 86400
            and manifest["sampling_rate_hz"] == 200
            and manifest["sample_count"] == 17280000
            and manifest["channel_count"] == 8
            and manifest["expected_raw_bytes"] == RAW_BYTES,
            "benchmark requires one complete original-sampling-rate 24-hour M01")
    expected = set(SOURCE_PATHS.values()) | {"events.json", "source-manifest.json"}
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    require(actual == expected and not any(path.is_symlink() for path in root.rglob("*")),
            "generated source contains unexpected files or links")
    require([p.name for p in root.iterdir() if p.is_dir()] == [CASE_ID],
            "benchmark requires exactly one generated case")
    require({entry["path"] for entry in manifest["files"]} == expected - {"source-manifest.json"},
            "generated file manifest is incomplete")
    for entry in manifest["files"]:
        path = root / entry["path"]
        require(path.stat().st_size == entry["size_bytes"]
                and sha256_file(path) == entry["sha256"], "generated source hash/length differs")
    data_sha = next(entry["sha256"] for entry in manifest["files"]
                    if entry["path"] == SOURCE_PATHS["DATA"])
    return {
        "source_id": "M01", "case_id": CASE_ID, "source_version": manifest["source_version"],
        "seed": manifest["seed"], "wholly_synthetic": True, "patient_inputs_read": False,
        "duration_seconds": 86400, "sampling_rate_hz": 200, "stored_channels": manifest["stored_channels"],
        "sample_count": 17280000, "raw_bytes": RAW_BYTES, "data_sha256": data_sha,
        "dataset_sha256": manifest["dataset_sha256"],
        "generator_source_sha256": manifest["generator_source_sha256"],
        "source_manifest_sha256": sha256_file(root / "source-manifest.json"),
        "freshly_generated_for_this_process": True, "existing_source_accepted": False,
    }


def raw_oracle(path):
    with path.open("rb") as stream:
        payload = stream.read(2000 * 16)
    require(len(payload) == 2000 * 16, "independent raw window is truncated")
    samples = array("h")
    samples.frombytes(payload)
    if sys.byteorder != "little":
        samples.byteswap()
    channels = [list(samples[i::8]) for i in range(8)]
    a, b = channels[:2]
    derived = {"I": a, "II": b, "III": [y-x for x, y in zip(a, b)],
               "aVR": [-(x+y)/2 for x, y in zip(a, b)],
               "aVL": [x-y/2 for x, y in zip(a, b)],
               "aVF": [y-x/2 for x, y in zip(a, b)]}
    derived.update({lead: channels[i] for i, lead in enumerate(("I", "II", "V1", "V2", "V3", "V4", "V5", "V6")) if i >= 2})
    return derived


def validate_response(document, expected_leads):
    require(isinstance(document, dict), "waveform response must be a JSON object")
    require(document.get("start_s") == 0 and document.get("duration_s") == 10,
            "waveform time interval differs")
    require(document.get("sample_rate_hz") == 200
            and document.get("display_sample_rate_hz") == 200
            and document.get("stride") == 1
            and document.get("total_duration_s") == 86400
            and document.get("filter") == "raw", "waveform sampling/filter contract differs")
    require(document.get("leads") == expected_leads,
            "native waveform values/12-lead derivations differ from original int16 samples")
    require(document.get("calibration_verified") is False,
            "mathematical arbitrary units must remain uncalibrated")
    require(isinstance(document.get("beats"), list) and len(document["beats"]) > 0,
            "waveform must include its complete visible beat list")
    require(isinstance(document.get("annotations"), list), "annotation output is missing")
    require(isinstance(document.get("analysis_basis"), str) and bool(document["analysis_basis"])
            and isinstance(document.get("analysis_revision"), int),
            "cache/source analysis identity is missing")


def prove_request_handles_released(source_root):
    for relative in SOURCE_PATHS.values():
        # Opening with write access is sufficient to detect a leaked share-READ
        # handle; no byte is written and no source timestamp is deliberately altered.
        with (source_root / relative).open("r+b"):
            pass


def one_request(app, client, enabled, counter, uri, expected, phase, ordinal):
    app.config["WINDOWS_REQUEST_SOURCE_LEASES"] = enabled
    counter.reset()
    started = time.perf_counter()
    response = client.get(uri, buffered=True)
    document = response.get_json()
    wall_seconds = time.perf_counter() - started
    require(response.status_code == 200, f"{phase} request returned HTTP {response.status_code}")
    validate_response(document, expected)
    projected, ignored = diagnostic_projection(document)
    return document, {
        "phase": phase, "ordinal": ordinal, "request_source_leases": enabled,
        "wall_seconds": wall_seconds, "response_bytes": len(response.data),
        "hash": counter.snapshot(), "diagnostic_sha256": canonical_hash(projected),
        "analysis_basis": document["analysis_basis"], "analysis_revision": document["analysis_revision"],
        "ignored_operation_guard_keys": ignored,
        "lead_sample_counts": {lead: len(document["leads"][lead]) for lead in LEADS},
        "beats_count": len(document["beats"]), "all_beats_sha256": canonical_hash(document["beats"]),
        "annotations_sha256": canonical_hash(document["annotations"]),
        "raw_leads_equal_independent_samples": True, "sample_rate_hz": 200, "stride": 1,
    }


def summarize(rows, enabled):
    selected = [row for row in rows if row["phase"] == "measured"
                and row["request_source_leases"] is enabled]
    values = [row["wall_seconds"] for row in selected]
    calls = [row["hash"]["data_calls"] for row in selected]
    hashed = [row["hash"]["data_bytes_read"] for row in selected]
    return {
        "requests": len(selected), "wall_seconds": {"median": statistics.median(values),
            "minimum": min(values), "maximum": max(values), "range": max(values)-min(values)},
        "data_hash_calls": {"median": statistics.median(calls), "minimum": min(calls), "maximum": max(calls)},
        "data_hash_bytes": {"median": statistics.median(hashed), "minimum": min(hashed), "maximum": max(hashed)},
        "data_hash_seconds_median": statistics.median(row["hash"]["data_hash_seconds"] for row in selected),
    }


def run_benchmark(output: Path, *, rounds: int = 3) -> int:
    require(os.name == "nt", "this performance acceptance benchmark requires native Windows")
    require(isinstance(rounds, int) and not isinstance(rounds, bool) and rounds >= 3,
            "at least three measured requests per mode are required")
    output = Path(output).expanduser().resolve()
    require(output.suffix.lower() == ".json", "only a JSON evidence file may be written")
    started = time.perf_counter()
    result = {
        "schema_version": 1, "kind": "windows_request_source_lease_performance",
        "status": "failed", "validator_sha256": sha256_file(Path(__file__)),
        "environment": {"system": platform.system(), "release": platform.release(),
            "version": platform.version(), "machine": platform.machine(),
            "processor": platform.processor(), "python": platform.python_version()},
        "thresholds": {"each_optimized_request_seconds_strictly_below": 1.0,
            "optimized_data_hash_calls": 1, "optimized_data_bytes_read": RAW_BYTES,
            "measured_requests_per_mode": rounds},
        "scope": {"source": "one freshly generated mathematical M01, original 24h/200Hz/8ch",
            "transport": "Flask test_client, full request through JSON decoding and teardown",
            "same_app_source_hardware": True, "interleaved": True,
            "warmup_requests_each_mode": 2, "existing_patient_sources_read": False,
            "diagnostic_algorithms_modified": False, "raw_or_database_or_pdf_saved_as_evidence": False,
            "actual_windows10_hospital_smoke_test": False},
        "requests": [], "failures": [],
    }
    try:
        from ecg_core import source_identity
        require("fresh_content" in inspect.signature(source_identity.read_locked_sources).parameters,
                "read_locked_sources does not implement fresh_content")
        from scripts.generate_doctor_24h import generate_dataset
        from app import create_app
        with tempfile.TemporaryDirectory(prefix="windows-math-source-perf-") as folder, ExitStack() as stack:
            temporary = Path(folder)
            source = temporary / "Sources" / "M01"
            generation_started = time.perf_counter()
            manifest = generate_dataset(source, duration_minutes=1440, seed=20261013)
            result["source_generation_seconds"] = time.perf_counter() - generation_started
            result["source"] = prove_generated_math_source(source, manifest)
            expected = raw_oracle(source / SOURCE_PATHS["DATA"])
            stack.enter_context(patch.dict(os.environ, {
                "ECG_APP_DATA_ROOT": str(temporary / "Workspace"),
                "ECG_DEMO_PASSWORD": "", "ECG_DEMO_READONLY": "0", "ECG_ALLOW_PHI": "0",
            }))
            # SQLite context managers commit but do not close connections. Cleanup
            # runs after timings/handle assertions, including exception paths.
            stack.callback(gc.collect)
            app = create_app(data_root=source, db_path=temporary / "Workspace" / "bench.sqlite3", testing=True)
            require("WINDOWS_REQUEST_SOURCE_LEASES" in app.config,
                    "application does not expose WINDOWS_REQUEST_SOURCE_LEASES")
            # Metadata catalogue lookups are unrelated to this waveform benchmark.
            # Isolate that lookup on this repository instance to avoid other sources.
            app.extensions["case_repository"]._manifest = lambda: {}
            client = app.test_client()  # No preserved request context.
            counter = HashCounter(source_identity, source / SOURCE_PATHS["DATA"], result["source"]["data_sha256"])
            counter.install(stack)
            uri = f"/api/cases/{CASE_ID}/waveform?" + urlencode({
                "start": 0, "duration": 10, "leads": ",".join(LEADS), "max_points": 2000,
                "filter": "raw", "analysis": "edited",
            })
            result["request_contract"] = {"start_s": 0, "duration_s": 10, "leads": list(LEADS),
                "max_points": 2000, "filter": "raw", "analysis": "edited"}
            reference = None
            sequence = [("warmup", enabled) for enabled in (False, True, True, False)]
            for number in range(rounds):
                sequence.extend(("measured", enabled) for enabled in ((False, True) if number % 2 == 0 else (True, False)))
            for ordinal, (phase, enabled) in enumerate(sequence, 1):
                document, row = one_request(app, client, enabled, counter, uri, expected, phase, ordinal)
                projected, _ = diagnostic_projection(document)
                if reference is None:
                    reference = projected
                row["all_diagnostic_fields_equal"] = projected == reference
                prove_request_handles_released(source)
                row["source_handles_released_after_teardown"] = True
                result["requests"].append(row)
                if not row["all_diagnostic_fields_equal"]:
                    result["failures"].append(f"request {ordinal}: diagnostic payload differs")
                if row["analysis_basis"] != reference["analysis_basis"] or row["analysis_revision"] != reference["analysis_revision"]:
                    result["failures"].append(f"request {ordinal}: analysis identity differs")
                hashes = row["hash"]
                if not all(event["content_matches"] and event["bytes_read"] == RAW_BYTES for event in hashes["events"]):
                    result["failures"].append(f"request {ordinal}: content hash is incomplete or mismatched")
                if enabled and (hashes["data_calls"] != 1 or hashes["data_bytes_read"] != RAW_BYTES):
                    result["failures"].append(f"request {ordinal}: optimized DATA was not hashed exactly once")
                if enabled and not row["wall_seconds"] < 1.0:
                    result["failures"].append(f"request {ordinal}: optimized request exceeded unchanged 1-second threshold")
                if not enabled and hashes["data_calls"] <= 1:
                    result["failures"].append(f"request {ordinal}: fallback did not exercise repeated fresh DATA hashing")
            result["summary"] = {"fallback": summarize(result["requests"], False),
                                 "request_lease": summarize(result["requests"], True)}
            old = result["summary"]["fallback"]["wall_seconds"]["median"]
            new = result["summary"]["request_lease"]["wall_seconds"]["median"]
            result["summary"]["median_speedup_ratio"] = old / new
            require(len([r for r in result["requests"] if r["phase"] == "measured"
                         and r["request_source_leases"]]) >= 3, "too few optimized measurements")
            result["status"] = "passed" if not result["failures"] else "failed"
        result["temporary_source_and_workspace_removed"] = not temporary.exists()
    except Exception as error:
        result["failures"].append(f"{type(error).__name__}: {error}")
    result["elapsed_seconds"] = time.perf_counter() - started
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "failures": result["failures"],
                      "summary": result.get("summary", {})}, ensure_ascii=False, allow_nan=False))
    return 0 if result["status"] == "passed" else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="Windows request-source lease acceptance benchmark; mathematical M01 only.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args(argv)
    try:
        return run_benchmark(args.output, rounds=args.rounds)
    except (OSError, ValueError) as error:
        print(f"Benchmark setup failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
