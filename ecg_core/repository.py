from __future__ import annotations

import re
import json
from functools import lru_cache
from pathlib import Path

from .config import CHANNEL_COUNT, SAMPLE_RATE, runtime_root, source_root, user_data_root
from .lps_parser import parse_lps

CASE_ID_RE = re.compile(r"^\d{16}$")


class CaseNotFound(KeyError):
    pass


class CaseRepository:
    def __init__(self, data_root: Path | None):
        self.data_root = data_root

    def _case_dirs(self) -> list[Path]:
        if not self.data_root or not self.data_root.is_dir():
            return []
        return sorted(
            path for path in self.data_root.iterdir()
            if path.is_dir() and CASE_ID_RE.match(path.name)
        )

    @staticmethod
    @lru_cache(maxsize=1)
    def _manifest() -> dict:
        for path in (
            user_data_root() / "data" / "case_manifest.json",
            runtime_root() / "data" / "case_manifest.json",
            source_root() / "data" / "case_manifest.json",
        ):
            if not path.exists():
                continue
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
        return {}

    @lru_cache(maxsize=32)
    def get_case(self, case_id: str) -> dict:
        if not CASE_ID_RE.match(case_id) or not self.data_root:
            raise CaseNotFound(case_id)
        case_dir = (self.data_root / case_id).resolve()
        if case_dir.parent != self.data_root.resolve() or not case_dir.is_dir():
            raise CaseNotFound(case_id)

        lps_path = case_dir / "report_image" / f"{case_id}_1.LPS"
        data_path = case_dir / "data" / f"{case_id}.DATA"
        ebi_path = case_dir / "DGS" / f"{case_id}.EBI"
        report_path = case_dir / "report" / f"{case_id}.pdf"
        if not lps_path.exists() or not data_path.exists() or not ebi_path.exists():
            raise CaseNotFound(case_id)

        parsed = parse_lps(lps_path)
        page_paths = sorted(
            (case_dir / "report_image").glob(f"{case_id}_*.png"),
            key=lambda p: int(p.stem.rsplit("_", 1)[-1]),
        )
        duration_seconds_raw = data_path.stat().st_size / (CHANNEL_COUNT * 2 * SAMPLE_RATE)
        manifest_entry = self._manifest().get("cases", {}).get(case_id, {})
        return {
            "case_id": case_id,
            **parsed,
            "technical": {
                "sample_rate_hz": SAMPLE_RATE,
                "independent_channels": CHANNEL_COUNT,
                "derived_leads": 12,
                "sample_format": "little-endian int16",
                "units": "µV（设备原始标度，未做临床校准声明）",
                "duration_seconds_raw": round(duration_seconds_raw, 3),
                "raw_size_bytes": data_path.stat().st_size,
                "report_pages": len(page_paths),
            },
            "integrity": {
                "manifest_available": bool(manifest_entry),
                "algorithm": "SHA-256" if manifest_entry else "",
                "file_count": manifest_entry.get("file_count"),
                "case_sha256": manifest_entry.get("case_sha256", ""),
                "source_version_warning": manifest_entry.get("source_version_warning", False),
            },
            "paths": {
                "case_dir": str(case_dir),
                "data": str(data_path),
                "ebi": str(ebi_path),
                "report_pdf": str(report_path) if report_path.exists() else "",
                "report_images": [str(path) for path in page_paths],
            },
        }

    def list_cases(self) -> list[dict]:
        cases: list[dict] = []
        for case_dir in self._case_dirs():
            try:
                case = self.get_case(case_dir.name)
            except (CaseNotFound, ET.ParseError, OSError):  # type: ignore[name-defined]
                continue
            cases.append(case)
        cases.sort(key=lambda item: item["metadata"].get("start_iso") or item["case_id"])
        return cases

    def invalidate(self) -> None:
        self.get_case.cache_clear()


# Avoid importing ElementTree throughout the module while keeping the scan resilient.
import xml.etree.ElementTree as ET  # noqa: E402
