"""Actual report UI/guard source with mathematical DOM fixtures and no services."""
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_simplified_report_keeps_saved_content_and_export_guards():
    subprocess.run(
        ["node", str(ROOT / "tests/browser_report_workspace_simplified.cjs")],
        cwd=ROOT,
        env=dict(os.environ),
        check=True,
        timeout=90,
    )
