"""Run production-core checks on explicit mathematical fixtures only."""
from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent

# Every selected function builds values in memory or uses pytest's tmp_path.
# In particular, the repository's real-case `client` fixture is not selected.
CHECKS = (
    ("portable-beats", "python-js", "tests/test_beat_editor.py::test_portable_engine_matches_python_operations_hrv_events_and_qrs"),
    ("clinical-index", "python-js", "tests/test_clinical_analysis.py::test_python_browser_parity"),
    ("hrv-day-night", "python-js", "tests/test_review_hrv_ranges.py::test_hrv_browser_backend_parity_and_day_night"),
    ("frequency-peak-energy", "python-oracle", "tests/test_review_hrv_ranges.py::test_frequency_peak_and_energy_are_measured"),
    ("frequency-gap", "python-oracle", "tests/test_review_hrv_ranges.py::test_gaps_are_not_interpolated_into_frequency"),
    ("missing-clock-noise", "python-oracle", "tests/test_review_hrv_ranges.py::test_short_noise_and_unknown_clock_do_not_fabricate_metrics"),
    ("frequency-af-boundary", "python-oracle", "tests/test_rr_quality.py::test_hrv_frequency_never_interpolates_across_short_af_span"),
    ("frequency-time-axis-dc", "python-oracle", "tests/test_rr_quality.py::test_spectrum_rejects_invalid_time_axis_and_dc_bin_is_not_doubled"),
    ("alternation-kors", "python-oracle", "tests/test_advanced_analysis.py::test_known_alternation_and_kors"),
    ("measurement-cache-markers", "python-oracle", "tests/test_advanced_analysis.py::test_full_measurement_quality_manual_and_cache"),
    ("af-flat-invalid", "python-oracle", "tests/test_advanced_analysis.py::test_empty_af_flat_and_bad_data"),
    ("clipping-af-boundary", "python-oracle", "tests/test_advanced_analysis.py::test_clipped_vcg_and_af_boundary_are_rejected"),
    ("invalid-options", "python-oracle", "tests/test_advanced_analysis.py::test_options_reject_invalid"),
    ("rr-periodicity-gaps", "python-oracle", "tests/test_advanced_analysis.py::test_rr_screen_periodicity_missing_and_not_ahi"),
    ("supplied-evidence-documents-pdf", "python-js-presentation-and-python-pdf", "tests/test_advanced_analysis.py::test_documents_pdf_and_browser_share_evidence"),
)


def run(output: Path) -> int:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node is required; a skipped parity check is not a verification pass")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="core-mathematical-") as temporary:
        workspace = Path(temporary)
        empty_input = workspace / "empty-input"
        empty_input.mkdir()
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
                           ECG_DATA_ROOT=str(empty_input), ECG_APP_DATA_ROOT=str(workspace / "runtime"),
                           ECG_CONFIG_PATH=str(workspace / "unused-config.json"))

        # This verifier reads only manifest-listed software, never a case input.
        identity_process = subprocess.run(
            [sys.executable, "scripts/verify_public_release.py"], cwd=ROOT, env=environment,
            capture_output=True, text=True, check=True, timeout=30,
        )
        identity = json.loads(identity_process.stdout)
        xml_path = workspace / "junit.xml"
        command = [sys.executable, "-m", "pytest", "-q", *[row[2] for row in CHECKS],
                   "-p", "no:cacheprovider", "--basetemp", str(workspace / "pytest"),
                   "--junitxml", str(xml_path)]
        completed = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True,
                                   text=True, timeout=180)

        def public_text(value: str) -> str:
            return value.replace(str(ROOT), "[source-root]").replace(str(workspace), "[synthetic-workspace]")

        log = public_text(completed.stdout + completed.stderr)
        (output / "pytest.log").write_text(log, encoding="utf-8")
        if not xml_path.exists():
            print(log)
            raise RuntimeError("The synthetic run produced no JUnit result")
        tree = ET.fromstring(public_text(xml_path.read_text(encoding="utf-8")))
        for element in tree.iter():
            element.attrib.pop("hostname", None)
        suites = list(tree.iter("testsuite"))
        counts = {key: sum(int(suite.get(key, "0")) for suite in suites)
                  for key in ("tests", "failures", "errors", "skipped")}
        ET.ElementTree(tree).write(output / "junit.xml", encoding="utf-8", xml_declaration=True)
        passed = completed.returncode == 0 and counts["tests"] > 0 and all(
            counts[key] == 0 for key in ("failures", "errors", "skipped"))
        result = {
            "schema": 1, "status": "passed" if passed else "failed",
            "input_kind": "mathematical_and_temporary_synthetic_fixtures",
            "execution_kind": "github_actions" if os.environ.get("GITHUB_ACTIONS") == "true" else "local",
            "source_identity": identity, "runtime": {
                "python": sys.version.split()[0],
                "node": subprocess.check_output([node, "--version"], text=True).strip(),
                "numpy": metadata.version("numpy"), "pytest": metadata.version("pytest"),
                "reportlab": metadata.version("reportlab"),
            },
            "counts": counts,
            "verification_code_sha256": {relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
                                         for relative in sorted({"scripts/verify_core_synthetic.py",
                                                                 "scripts/verify_public_release.py",
                                                                 *[row[2].split("::")[0] for row in CHECKS]})},
            "checks": [{"name": name, "evidence_kind": kind, "selector": selector}
                       for name, kind, selector in CHECKS],
            "scope": {
                "python_core_executed": True,
                "browser_python_executed": False,
                "advanced_analysis_browser_compute_parity": False,
                "clinical_validation": False,
            },
        }
        (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                            encoding="utf-8")
        print(json.dumps({"status": result["status"], "source_identity": identity, "counts": counts},
                         ensure_ascii=False))
        if not passed:
            print(log)
        return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/core-verification")
    return run(parser.parse_args().output.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
