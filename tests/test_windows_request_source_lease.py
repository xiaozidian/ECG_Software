"""Windows request source leases: synthetic temporary bytes only, no real cases."""
from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import struct

import pytest

from ecg_core import source_identity as identity
from ecg_core.review_workflow import ReportConflict
from ecg_core.source_identity import SourceReadError
from ecg_core.waveform import read_waveform

pytestmark = pytest.mark.skipif(os.name != "nt", reason="requires native Windows share-mode handles")


def _token(path):
    return identity.file_signature(path)[4][1]


def _replace_restoring_mtime(path, payload):
    before = path.stat()
    path.write_bytes(payload)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert path.stat().st_size == before.st_size
    assert path.stat().st_mtime_ns == before.st_mtime_ns


def _assert_write_rejected(path):
    before = path.read_bytes()
    with pytest.raises(OSError):
        with path.open("r+b") as stream:
            stream.write(b"changed")
    assert path.read_bytes() == before


def _assert_released(path):
    with path.open("r+b"):
        pass
    key = str(path.resolve()).casefold()
    with identity._SOURCE_LEASE_LOCK:
        assert not any(str(item).casefold() == key for item in identity._SOURCE_LEASES)


@pytest.fixture
def sample_file(tmp_path):
    path = tmp_path / "mathematical-source.DATA"
    path.write_bytes(b"aaaa" * 1024)
    yield path
    _assert_released(path)


def _hash_spy(monkeypatch, target):
    target = target.resolve()
    calls = []
    original = identity._content_hash
    def counted(path):
        if Path(path).resolve() == target:
            calls.append(Path(path).stat().st_size)
        return original(path)
    monkeypatch.setattr(identity, "_content_hash", counted)
    return calls


def test_fresh_lease_hashes_once_and_uses_content_cache_identity(sample_file, monkeypatch):
    calls = _hash_spy(monkeypatch, sample_file)
    expected = sha256(sample_file.read_bytes()).hexdigest()
    identity._digest.cache_clear()
    duplicate_digest_reads = []
    original_digest = identity._digest
    def counted_digest(*args):
        duplicate_digest_reads.append(args)
        return original_digest(*args)
    monkeypatch.setattr(identity, "_digest", counted_digest)
    with identity.read_locked_sources([sample_file], fresh_content=True):
        signature = identity.file_signature(sample_file)
        assert _token(sample_file) == ("content", expected)
        assert all(identity.file_signature(sample_file) == signature for _ in range(5))
        first = identity.file_evidence(sample_file)
        second = identity.file_evidence(sample_file)
        assert first == second == {"sha256": expected, "bytes": 4096}
        assert calls == [4096]
        _assert_write_rejected(sample_file)
    _assert_released(sample_file)
    with identity.read_locked_sources([sample_file], fresh_content=True):
        assert identity.file_signature(sample_file) == signature
        assert identity.file_evidence(sample_file) == first
    assert calls == [4096, 4096]  # Fresh evidence again for the next request.
    assert duplicate_digest_reads == []  # Completed locked SHA is reused, not a second full read.


def test_same_size_restored_mtime_and_repeated_change_clock_cannot_reuse_content(sample_file, monkeypatch):
    original_clock = identity._windows_change_time_ns
    fixed_clock = original_clock(sample_file)
    target = sample_file.resolve()
    monkeypatch.setattr(identity, "_windows_change_time_ns",
                        lambda path: fixed_clock if Path(path).resolve() == target else original_clock(path))
    calls = _hash_spy(monkeypatch, sample_file)
    with identity.read_locked_sources([sample_file], fresh_content=True):
        before_signature = identity.file_signature(sample_file)
        before = identity.file_evidence(sample_file)
    _replace_restoring_mtime(sample_file, b"bbbb" * 1024)
    with identity.read_locked_sources([sample_file], fresh_content=True):
        after_signature = identity.file_signature(sample_file)
        after = identity.file_evidence(sample_file)
        assert before_signature[:4] == after_signature[:4]
        assert before_signature[4][0] == after_signature[4][0]
        assert _token(sample_file) == ("content", sha256(b"bbbb" * 1024).hexdigest())
    assert after != before and after["sha256"] != before["sha256"]
    assert calls == [4096, 4096]
    _assert_released(sample_file)


def test_immutable_outer_is_not_upgraded_or_weakened_by_nested_fresh(sample_file, monkeypatch):
    calls = _hash_spy(monkeypatch, sample_file)
    with identity.read_locked_sources([sample_file]):
        original = identity.file_signature(sample_file)
        assert _token(sample_file)[0] == "read_locked"
        with identity.read_locked_sources([sample_file], fresh_content=True):
            assert identity.file_signature(sample_file) == original
            _assert_write_rejected(sample_file)
        assert identity.file_signature(sample_file) == original
        assert calls == []
        _assert_write_rejected(sample_file)
    _assert_released(sample_file)
    sample_file.write_bytes(b"after" * 100)
    assert sample_file.read_bytes() == b"after" * 100


def test_fresh_outer_keeps_content_token_through_nested_immutable_and_duplicates(sample_file, monkeypatch):
    calls = _hash_spy(monkeypatch, sample_file)
    expected = ("content", sha256(sample_file.read_bytes()).hexdigest())
    with identity.read_locked_sources([sample_file, sample_file], fresh_content=True):
        assert _token(sample_file) == expected
        with identity.read_locked_sources([sample_file]):
            assert _token(sample_file) == expected
            with identity.read_locked_sources([sample_file], fresh_content=True):
                assert _token(sample_file) == expected
            _assert_write_rejected(sample_file)
        assert _token(sample_file) == expected
        _assert_write_rejected(sample_file)
    assert calls == [4096]
    _assert_released(sample_file)


def test_exception_in_lease_body_releases_all_handles(sample_file, tmp_path):
    another = tmp_path / "another-mathematical-source.EBI"
    another.write_bytes(b"synthetic-index")
    with pytest.raises(RuntimeError, match="injected body"):
        with identity.read_locked_sources([sample_file, another], fresh_content=True):
            _assert_write_rejected(sample_file)
            _assert_write_rejected(another)
            raise RuntimeError("injected body")
    for path in (sample_file, another):
        _assert_released(path)
        path.write_bytes(b"replacement")
        assert path.read_bytes() == b"replacement"


def test_partial_acquisition_failure_releases_already_open_handle(sample_file, tmp_path):
    missing = tmp_path / "never-created-synthetic.EBI"
    with pytest.raises((OSError, SourceReadError, ReportConflict)):
        with identity.read_locked_sources([sample_file, missing], fresh_content=True):
            pytest.fail("missing source unexpectedly acquired")
    _assert_released(sample_file)
    sample_file.write_bytes(b"can-change-after-failed-acquisition")
    assert sample_file.read_bytes() == b"can-change-after-failed-acquisition"


def test_fresh_hash_failure_closes_new_handle(sample_file, monkeypatch):
    original = identity._content_hash
    def failed(path):
        if Path(path).resolve() == sample_file.resolve():
            raise OSError("injected mathematical hash read")
        return original(path)
    monkeypatch.setattr(identity, "_content_hash", failed)
    with pytest.raises((OSError, SourceReadError, ReportConflict)):
        with identity.read_locked_sources([sample_file], fresh_content=True):
            pytest.fail("injected hash failure unexpectedly acquired")
    _assert_released(sample_file)
    sample_file.write_bytes(b"can-change-after-failed-hash")
    assert sample_file.read_bytes() == b"can-change-after-failed-hash"


def test_fresh_signature_matches_mutable_content_key_and_preserves_original_samples(tmp_path, monkeypatch):
    path = tmp_path / "small-mathematical-wave.DATA"
    # Original 200 Hz / eight-channel frames, without an imported recording.
    path.write_bytes(b"".join(struct.pack("<8h", *(frame+i for i in range(8)))
                              for frame in range(400)))
    mutable = identity.file_signature(path)
    assert _token(path)[0] == "content"
    expected = read_waveform(path, 0, 1, ["I", "II"], 200, False)
    calls = _hash_spy(monkeypatch, path)
    with identity.read_locked_sources([path], fresh_content=True):
        assert identity.file_signature(path) == mutable
        assert read_waveform(path, 0, 1, ["I", "II"], 200, False) == expected
    assert calls == [400 * 16]
    _assert_released(path)
    before = path.stat()
    original = path.read_bytes()
    changed = struct.pack("<h", 2222) + original[2:]
    path.write_bytes(changed)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    with identity.read_locked_sources([path], fresh_content=True):
        actual = read_waveform(path, 0, 1, ["I", "II"], 200, False)
        assert actual["leads"]["I"][0] == 2222
        assert actual["leads"]["I"] != expected["leads"]["I"]
        assert actual["leads"]["II"] == expected["leads"]["II"]
    _assert_released(path)


@pytest.fixture
def lease_app(tmp_path, monkeypatch):
    from app import create_app
    from scripts.generate_doctor_24h import CASE_ID, generate_dataset
    source = tmp_path / "M01"
    generate_dataset(source, duration_minutes=0.1, seed=20261013)
    monkeypatch.setenv("ECG_APP_DATA_ROOT", str(tmp_path / "isolated-workspace"))
    monkeypatch.setenv("ECG_DEMO_PASSWORD", "")
    monkeypatch.setenv("ECG_DEMO_READONLY", "0")
    app = create_app(data_root=source, db_path=tmp_path / "isolated-workspace" / "request.sqlite3", testing=True)
    app.extensions["case_repository"]._manifest = lambda: {}
    app.config["WINDOWS_REQUEST_SOURCE_LEASES"] = True
    paths = [source / CASE_ID / "data" / f"{CASE_ID}.DATA",
             source / CASE_ID / "DGS" / f"{CASE_ID}.EBI",
             source / CASE_ID / "report_image" / f"{CASE_ID}_1.LPS"]
    yield app, CASE_ID, paths
    for path in paths:
        _assert_released(path)


def test_application_requests_refresh_content_and_release_handles(lease_app, monkeypatch):
    app, case_id, paths = lease_app
    client = app.test_client()
    uri = f"/api/cases/{case_id}/waveform?start=0&duration=1&leads=I,II&max_points=200&filter=raw&analysis=edited"
    calls = _hash_spy(monkeypatch, paths[0])
    first = client.get(uri)
    assert first.status_code == 200
    before = first.get_json()
    assert len(calls) == 1
    for path in paths:
        _assert_released(path)
    payload = paths[0].read_bytes()
    value = struct.unpack_from("<h", payload)[0]
    _replace_restoring_mtime(paths[0], struct.pack("<h", value + 101) + payload[2:])
    second = client.get(uri)
    assert second.status_code == 200
    after = second.get_json()
    assert len(calls) == 2
    assert before["analysis_basis"] != after["analysis_basis"]
    assert after["leads"]["I"][0] == value + 101
    assert after["leads"]["II"] == before["leads"]["II"]
    assert after["sample_rate_hz"] == before["sample_rate_hz"] == 200
    for path in paths:
        _assert_released(path)


def test_application_error_teardown_releases_request_handles(lease_app):
    from flask import request
    app, case_id, paths = lease_app
    @app.before_request
    def injected_failure():
        if request.path == f"/api/cases/{case_id}/waveform":
            _assert_write_rejected(paths[0])  # Prove the real case hook already owns the lease.
            raise RuntimeError("injected leased request")
    with pytest.raises(RuntimeError, match="injected leased request"):
        app.test_client().get(f"/api/cases/{case_id}/waveform?filter=raw")
    for path in paths:
        _assert_released(path)
    paths[0].write_bytes(paths[0].read_bytes())
    assert paths[0].stat().st_size == 6 * 200 * 8 * 2
