"""Continuous HRV screen coverage and frozen A4-output regression checks."""

from pathlib import Path
import os
import shutil
import subprocess

import pytest


def test_hrv_continuous_screen_and_a4_equivalence():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node unavailable")
    environment = dict(os.environ)
    # The CJS test has stable inline SHA oracles; an optional manual baseline
    # from a developer's session must never be required by the pytest suite.
    environment.pop("HRV_CONTINUOUS_BASELINE", None)
    subprocess.run(
        [node, "tests/browser_hrv_continuous.cjs"],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        check=True,
        timeout=30,
    )
