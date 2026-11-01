"""Exercise the shipped PDF export with delayed network and stale context."""
import subprocess


def test_browser_report_export_interaction():
    subprocess.run(['node','tests/browser_report_export.cjs'],check=True,timeout=15)
