"""Real-browser lifecycle contracts using mathematical records and waveforms only."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


def test_template_twelve_linkage_in_sandboxed_chrome():
    node = shutil.which("node")
    assert node, "Node is required for the production browser contract"
    if not os.environ.get("ECG_PLAYWRIGHT_CORE") or not os.environ.get("ECG_CHROME"):
        pytest.skip("Set ECG_PLAYWRIGHT_CORE and ECG_CHROME for sandboxed browser validation")
    run = subprocess.run(
        [node, str(Path(__file__).with_name("browser_template_twelve_linkage.cjs"))],
        text=True, capture_output=True, timeout=180,
    )
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout)
    assert result["passed"] and result["chrome_sandbox"]
    assert result["external_requests"] == 0 and not result["page_errors"]
    assert result["actual_check_count"] == 24
    assert result["actual_check_count"] == len(set(result["checks"]))
    assert len(result["source_sha256"]) == 4
