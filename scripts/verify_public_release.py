"""Verify the immutable production source identity without opening clinical data."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "docs/releases/0.12.9-doctor-evaluation.20261009/source-manifest.json"


def verify(root: Path = ROOT) -> dict:
    manifest = json.loads((root / MANIFEST.relative_to(ROOT)).read_text(encoding="utf-8"))
    files = manifest["files"]
    if len(files) != manifest["production_file_count"] or len(files) != 94:
        raise ValueError("production file count changed")
    fingerprint = hashlib.sha256(json.dumps(
        files, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    if fingerprint != manifest["source_sha256"]:
        raise ValueError("manifest fingerprint does not match frozen release")
    for relative, expected in files.items():
        path = root / relative
        if Path(relative).is_absolute() or ".." in Path(relative).parts or path.is_symlink():
            raise ValueError("unsafe production path")
        contents = path.read_bytes()
        if len(contents) != expected["bytes"] or hashlib.sha256(contents).hexdigest() != expected["sha256"]:
            raise ValueError(f"production bytes differ: {relative}")
    return {"release_id": manifest["release_id"], "source_sha256": fingerprint,
            "production_files_verified": len(files), "clinical_acceptance": False}


if __name__ == "__main__":
    print(json.dumps(verify(), ensure_ascii=False))
