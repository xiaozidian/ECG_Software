"""Production report preview/callback races with disposable metadata; no patient data."""
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("scenario", ["lifecycle", "races", "guards"])
def test_report_preview_preserves_live_controls_and_output_guards(scenario):
    subprocess.run(
        ["node", "tests/browser_report_preview_interactions.cjs", scenario],
        cwd=ROOT,
        check=True,
        timeout=20,
    )
