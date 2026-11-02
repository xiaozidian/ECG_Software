"""No clinical inputs: native dialog behavior and scoped leave decisions."""
from pathlib import Path
import subprocess


def test_unsaved_decision_dialog_in_browser():
    root=Path(__file__).resolve().parents[1]
    subprocess.run(['node','tests/browser_unsaved_navigation.cjs'],cwd=root,check=True,timeout=90)
