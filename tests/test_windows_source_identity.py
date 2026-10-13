"""Windows source evidence: changed bytes cannot be hidden by restoring mtime."""
from __future__ import annotations
from hashlib import sha256
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from ecg_core import source_identity as source

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Native Win32 metadata contract")


def test_native_change_time_rejects_same_length_bytes_with_restored_mtime(tmp_path):
    path = tmp_path / "synthetic.DATA"
    path.write_bytes(b"A" * 32)
    first = source.file_signature(path)
    old = source.file_evidence(path)
    before = path.stat()
    path.write_bytes(b"B" * 32)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    second = source.file_signature(path)
    assert first[:4] == second[:4]
    assert first[4] != second[4]
    assert source.file_evidence(path)["sha256"] == sha256(b"B" * 32).hexdigest()
    assert source.file_evidence(path)["sha256"] != old["sha256"]


def test_native_metadata_failure_does_not_fall_back_to_creation_time(tmp_path, monkeypatch):
    path = tmp_path / "synthetic-source.py"
    path.write_text("value=1\n", encoding="utf-8")
    def unavailable(*args):
        raise OSError("Native metadata unavailable")
    monkeypatch.setattr(source, "_windows_change_time_ns", unavailable)
    with pytest.raises(OSError):
        source.file_signature(path)


@pytest.mark.parametrize("flag", [0x1000, 0x40000, 0x400000])
def test_cloud_recall_is_rejected_before_reading_a_source(tmp_path, monkeypatch, flag):
    path = tmp_path / "placeholder.DATA"
    info = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_file_attributes=flag, st_size=32)
    monkeypatch.setattr(Path, "stat", lambda *a, **k: info)
    with pytest.raises(source.SourceUnavailable):
        source.require_local_file(path)
