"""Actual report handlers with mathematical state/transport; no clinical service."""
from pathlib import Path
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("script", [
    "browser_report_candidate_scopes.cjs",
    "browser_report_af_confirmation.cjs",
    "browser_report_wave_actions.cjs",
    "browser_report_selection_normalization.cjs",
])
def test_report_multistrip_and_temporary_wave_handlers(script):
    subprocess.run(["node", str(ROOT / "tests" / script)], cwd=ROOT, check=True, timeout=30)
