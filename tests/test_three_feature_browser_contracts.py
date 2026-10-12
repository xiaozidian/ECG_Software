"""Reproducible mathematical frontend state and cross-runtime contracts."""
import os
from pathlib import Path
import subprocess
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]
@pytest.mark.parametrize("script",["browser_rr_review.cjs","browser_rr_review_selection.cjs","browser_hrv_review_editor.cjs","browser_stt_twelve_readability.cjs","browser_terminology_tree.cjs","browser_demo_review_api.cjs"])
def test_three_feature_controller_contract(script):
    environment=dict(os.environ,ECG_DEMO_PYTHON=sys.executable,PYTHONDONTWRITEBYTECODE="1")
    subprocess.run(["node",str(ROOT/"tests"/script)],cwd=ROOT,env=environment,check=True,timeout=60)
