"""Pure mathematical actual-browser component and integration contracts."""
import os
from pathlib import Path
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('name', ['browser_stt_range_review.cjs', 'browser_stt_range_bridge.cjs', 'browser_rhythm_range_editor_dom.cjs', 'browser_stt_mean_save_idempotency.cjs'])
def test_doctor_range_browser_contract(name):
    subprocess.run(['node', str(ROOT/'tests'/name)], cwd=ROOT, env=dict(os.environ), check=True, timeout=120)
