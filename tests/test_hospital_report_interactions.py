"""Browser gestures on mathematical inputs; no case database or hospital images."""
import subprocess


def test_hospital_report_range_and_fullscreen_interactions():
    subprocess.run(['node', 'tests/browser_hospital_report_interactions.cjs'], check=True, timeout=45)
