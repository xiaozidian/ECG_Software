"""Pure Node regression; does not launch or drive a browser."""
from pathlib import Path
import shutil
import subprocess
import pytest


def test_full_record_geometry():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js unavailable")
    result = subprocess.run([node, str(Path(__file__).with_name("node_full_record_geometry.cjs"))], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
