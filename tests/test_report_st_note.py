"""Original mathematical saved notes and shipped ST report ownership guards."""
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_saved_st_note_appends_only_to_owned_report_draft():
    subprocess.run(
        ["node", str(ROOT / "tests/browser_report_st_note.cjs")],
        cwd=ROOT, env=dict(os.environ), check=True, timeout=90,
    )
