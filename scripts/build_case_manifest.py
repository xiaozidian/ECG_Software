from __future__ import annotations

import hashlib
import json
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ecg_core.config import resolve_data_root, user_data_root  # noqa: E402


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def iso_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")


def main() -> None:
    parser = argparse.ArgumentParser(description="为本地病例目录生成 SHA-256 完整性清单")
    parser.add_argument("data_root", nargs="?", help="病例数据目录；省略时使用应用配置")
    parser.add_argument("--output", type=Path, help="输出路径；默认写入应用用户数据目录")
    args = parser.parse_args()
    root = resolve_data_root(args.data_root)
    if root is None:
        raise SystemExit("未找到病例数据目录")
    output = args.output.expanduser().resolve() if args.output else user_data_root() / "data" / "case_manifest.json"
    cases = {}
    dataset_digest = hashlib.sha256()
    for case_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        entries = []
        for path in sorted(case_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            digest = sha256_file(path)
            dataset_digest.update(relative.encode("utf-8"))
            dataset_digest.update(digest.encode("ascii"))
            entries.append({
                "path": relative,
                "size_bytes": path.stat().st_size,
                "modified_utc": iso_mtime(path),
                "sha256": digest,
            })
        report_times = [path.stat().st_mtime for path in case_dir.glob("report/**/*") if path.is_file()]
        analysis_times = [path.stat().st_mtime for path in case_dir.glob("DGS/*") if path.is_file()]
        version_warning = bool(report_times and analysis_times and max(analysis_times) > max(report_times) + 24 * 3600)
        case_hash = hashlib.sha256("".join(item["sha256"] for item in entries).encode("ascii")).hexdigest()
        cases[case_dir.name] = {
            "file_count": len(entries),
            "total_bytes": sum(item["size_bytes"] for item in entries),
            "case_sha256": case_hash,
            "source_version_warning": version_warning,
            "files": entries,
        }
        print(f"{case_dir.name}: {len(entries)} files, {case_hash[:12]}…")
    payload = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "algorithm": "SHA-256",
        "data_root_name": root.name,
        "case_count": len(cases),
        "dataset_sha256": dataset_digest.hexdigest(),
        "cases": cases,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Manifest: {output}")


if __name__ == "__main__":
    main()
