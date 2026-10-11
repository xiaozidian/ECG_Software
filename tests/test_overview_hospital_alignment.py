"""Synthetic event and asynchronous navigation contracts for the overview UI."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_hospital_overview_interactions_and_navigation_races():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node unavailable")
    root = Path(__file__).resolve().parents[1]
    subprocess.run([node, str(root / "tests/browser_overview_hospital_flow.cjs")], cwd=root, check=True, capture_output=True, text=True)
