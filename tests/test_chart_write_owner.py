"""Real API owner checks with controlled acknowledgements; no patient input."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


def test_late_clinical_write_does_not_invalidate_new_chart_owner():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js unavailable')
    result = subprocess.run([node, str(Path(__file__).with_name('node_chart_write_owner.cjs'))],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads(result.stdout)
    assert evidence['passed'] is True
    assert len(evidence['checks']) == 6
    assert evidence['patient_inputs'] is False
    assert evidence['services_started'] is False
    assert evidence['browser_ui'] is False
