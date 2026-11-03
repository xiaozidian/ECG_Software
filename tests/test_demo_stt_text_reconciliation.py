"""Shipped Demo adapter reconciliation over independent mathematical input only."""
import json
from pathlib import Path
import subprocess


def test_demo_stt_text_reconciliation_and_atomic_replay():
    root = Path(__file__).resolve().parents[1]
    run = subprocess.run(
        ["node", "tests/browser_demo_stt_text_reconciliation.cjs"],
        cwd=root, capture_output=True, text=True, timeout=90, check=True,
    )
    result = json.loads(run.stdout)
    assert result["passed"] == 8
    assert result["patient_inputs"] is False
    assert result["servers_started"] is False
    assert result["external_network"] is False
