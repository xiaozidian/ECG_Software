from __future__ import annotations

import re
import json
from functools import lru_cache
from pathlib import Path

from .config import CHANNEL_COUNT, SAMPLE_RATE, runtime_root, source_root, user_data_root
from .lps_parser import parse_lps
from .source_identity import (file_signature, require_local_file, require_waveform_file,
                              SourceInvalid, SourceReadError, SourceUnavailable)
from .review_workflow import ReportConflict
from .ebi import load_records
from .signal_profile import raw_signal_metadata

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

    def get_case(self, case_id: str) -> dict:
        if not CASE_ID_RE.match(case_id) or not self.data_root:
            raise CaseNotFound(case_id)
        case_dir = (self.data_root / case_id).resolve()
        if case_dir.parent != self.data_root.resolve() or not case_dir.is_dir():
            raise CaseNotFound(case_id)

        paths = [case_dir / 'data' / f'{case_id}.DATA',
                 case_dir / 'DGS' / f'{case_id}.EBI',
                 case_dir / 'report_image' / f'{case_id}_1.LPS']
        try:
            for path in paths:
                require_local_file(path)
            signature = tuple(file_signature(p) for p in paths)
            result = self._get_case(case_id, signature)
            if tuple(file_signature(p) for p in paths) != signature:
                raise ReportConflict('病例文件在读取期间发生变化，请稍后重试')
        except OSError as error:
            raise SourceReadError('病例文件无法读取，请检查文件完整性、存储设备及读取权限后重试。') from error
        return result

    @lru_cache(maxsize=32)
    def _get_case(self, case_id: str, signature) -> dict:
        case_dir = (self.data_root / case_id).resolve()

        lps_path = case_dir / "report_image" / f"{case_id}_1.LPS"
        data_path = case_dir / "data" / f"{case_id}.DATA"
        ebi_path = case_dir / "DGS" / f"{case_id}.EBI"
        report_path = case_dir / "report" / f"{case_id}.pdf"
        data_stat = require_waveform_file(data_path)
        records = load_records(str(ebi_path))
        if records[-1][0] >= data_stat.st_size // (CHANNEL_COUNT * 2):
            raise SourceInvalid('EBI 心搏位置超出 DATA 波形范围，文件可能截断或不属于同一记录；请重新核对完整病例。')
        parsed = parse_lps(lps_path)
        page_paths = sorted(
            (case_dir / "report_image").glob(f"{case_id}_*.png"),
            key=lambda p: int(p.stem.rsplit("_", 1)[-1]),
        )
        duration_seconds_raw = data_stat.st_size / (CHANNEL_COUNT * 2 * SAMPLE_RATE)
        manifest_entry = self._manifest().get("cases", {}).get(case_id, {})
        return {
            "case_id": case_id,
            **parsed,
            "technical": {
                "sample_rate_hz": SAMPLE_RATE,
                "independent_channels": CHANNEL_COUNT,
                "derived_leads": 12,
                "sample_format": "little-endian int16",
                **raw_signal_metadata(),
                "duration_seconds_raw": round(duration_seconds_raw, 3),
                "raw_size_bytes": data_stat.st_size,
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
                "lps": str(lps_path),
                "report_pdf": str(report_path) if report_path.exists() else "",
                "report_images": [str(path) for path in page_paths],
            },
        }

    def scan_cases(self) -> tuple[list[dict], list[dict]]:
        cases: list[dict] = []
        issues: list[dict] = []
        for case_dir in self._case_dirs():
            try:
                case = self.get_case(case_dir.name)
            except (SourceInvalid, SourceReadError, SourceUnavailable, ReportConflict) as error:
                issues.append({'case_id': case_dir.name, 'code': getattr(error, 'code', 'source_changed'),
                               'error': str(error)})
                continue
            except (CaseNotFound, OSError):
                issues.append({'case_id': case_dir.name, 'code': 'source_unreadable',
                               'error': '病例目录或文件无法读取，请核对完整性及读取权限。'})
                continue
            cases.append(case)
        cases.sort(key=lambda item: item["metadata"].get("start_iso") or item["case_id"])
        return cases, issues

    def list_cases(self) -> list[dict]:
        return self.scan_cases()[0]

    def invalidate(self) -> None:
        self._get_case.cache_clear()
