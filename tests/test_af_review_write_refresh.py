"""Own metadata writes refresh visible evidence without reloading the all-day cohort."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_af_review_write_refresh_and_conflict_guards():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    subprocess.run([node, "tests/af_review_write_refresh.cjs"],
                   cwd=Path(__file__).resolve().parents[1], check=True, timeout=20)
