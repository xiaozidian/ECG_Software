"""Actual report card and ST-T controls over isolated mathematical DOM fixtures."""
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("scenario", ["menu", "stt"])
def test_report_card_context_and_stt_unavailable_controls(scenario):
    subprocess.run(
        ["node", "tests/browser_report_card_and_stt_controls.cjs", scenario],
        cwd=ROOT,
        check=True,
        timeout=90,
    )
