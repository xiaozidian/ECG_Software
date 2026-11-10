"""Actual ST-T DOM withdrawal/readoption; mathematical inputs, no clinical services."""
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("scenario", ["membership", "ownership", "contexts"])
def test_stt_live_membership_remount_and_current_strip_readoption(scenario):
    subprocess.run(
        ["node", "tests/browser_stt_membership_remount.cjs", scenario],
        cwd=ROOT,
        check=True,
        timeout=90,
    )
