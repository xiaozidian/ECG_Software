"""Actual report CSS/source handlers with normal mouse and mathematical input."""
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_saved_st_note_remains_clickable_above_report_slider():
    subprocess.run(
        ["node", str(ROOT / "tests/browser_report_saved_st_note_layout.cjs")],
        cwd=ROOT, env=dict(os.environ), check=True, timeout=90,
    )
