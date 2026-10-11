"""Research print privacy races using production JavaScript and synthetic evidence."""
from pathlib import Path
import subprocess


def test_research_print_privacy_and_pending_measurement_guards():
    workspace = Path(__file__).resolve().parents[1]
    subprocess.run(
        ["node", "tests/browser_report_privacy_advanced.cjs"],
        cwd=workspace,
        check=True,
        timeout=20,
    )
