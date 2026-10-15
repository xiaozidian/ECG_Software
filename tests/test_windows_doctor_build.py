"""Privacy and integrity boundaries for the portable doctor package."""
import json
from pathlib import Path

import pytest

from scripts.windows_doctor_build import (
    ASSET_FILES, APP_NAME, PackageError, create_content_manifest,
    package_inventory, verify_content_manifest, validate_source,
)


def minimal_package(tmp_path):
    root = tmp_path / "package"
    root.mkdir()
    (root / (APP_NAME + ".exe")).write_bytes(b"synthetic-test-executable")
    for name in ASSET_FILES:
        path = root / "_internal" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test software asset")
    from scripts.windows_doctor_build import SOURCE_FILES
    for name in SOURCE_FILES:
        path = root / "Sources" / "M01" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic test fixture")
    return root


def test_extra_database_is_rejected_before_inventory(tmp_path):
    root = minimal_package(tmp_path)
    (root / "_internal" / "accidental.sqlite3").write_bytes(b"never package a database")
    with pytest.raises(PackageError, match="Forbidden"):
        package_inventory(root)


def test_extra_patient_source_is_rejected(tmp_path):
    root = minimal_package(tmp_path)
    path = root / "Sources" / "M01" / "unknown.DATA"
    path.write_bytes(b"unexpected input")
    with pytest.raises(PackageError, match="synthetic allowlist"):
        package_inventory(root)


def test_unlisted_static_asset_is_rejected(tmp_path):
    root = minimal_package(tmp_path)
    (root / "_internal" / "static" / "unapproved.json").write_text("{}")
    with pytest.raises(PackageError, match="software allowlist"):
        package_inventory(root)


def test_content_manifest_detects_changed_software_and_missing_source(tmp_path):
    root = minimal_package(tmp_path)
    create_content_manifest(root)
    verify_content_manifest(root)
    target = root / "_internal" / ASSET_FILES[0]
    target.write_bytes(b"modified")
    with pytest.raises(PackageError, match="full payload"):
        verify_content_manifest(root)
    target.write_bytes(b"test software asset")
    (root / "Sources" / "M01" / "events.json").unlink()
    with pytest.raises(PackageError, match="synthetic allowlist"):
        verify_content_manifest(root)


def test_content_manifest_rejects_edited_hash_list(tmp_path):
    root = minimal_package(tmp_path)
    create_content_manifest(root)
    sums = root / "SHA256SUMS.txt"
    sums.write_text("fake hashes\n")
    with pytest.raises(PackageError, match="SHA256SUMS"):
        verify_content_manifest(root)


def test_linked_data_cannot_enter_package(tmp_path):
    root = minimal_package(tmp_path)
    linked = root / "_internal" / "linked.txt"
    outside = tmp_path / "outside.txt"
    outside.write_text("unapproved")
    try:
        linked.symlink_to(outside)
    except OSError:
        # Windows users without symlink privileges can still test the rejection
        # through monkeypatch, avoiding a skipped new safety test.
        from unittest.mock import patch
        original = Path.is_symlink
        def fake_is_symlink(path):
            return path == linked or original(path)
        linked.write_text("unapproved")
        with patch.object(Path, "is_symlink", fake_is_symlink):
            with pytest.raises(PackageError, match="linked"):
                package_inventory(root)
    else:
        with pytest.raises(PackageError, match="linked"):
            package_inventory(root)


def test_source_manifest_cannot_claim_real_or_short_source(tmp_path):
    root = minimal_package(tmp_path) / "Sources" / "M01"
    (root / "source-manifest.json").write_text(json.dumps({"wholly_synthetic": False}))
    with pytest.raises(PackageError, match="wholly synthetic"):
        validate_source(root)


def test_software_only_manifest_rejects_any_source(tmp_path):
    root = minimal_package(tmp_path)
    with pytest.raises(PackageError, match="synthetic allowlist"):
        create_content_manifest(root, with_source=False)
    import shutil
    shutil.rmtree(root / "Sources")
    create_content_manifest(root, with_source=False)
    verify_content_manifest(root)
    (root / "_internal" / "accidental.DATA").write_bytes(b"unapproved raw")
    with pytest.raises(PackageError, match="Forbidden"):
        verify_content_manifest(root)
