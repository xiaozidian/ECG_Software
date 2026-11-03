"""Hospital report-wave actions run on actual DOM and mathematical traces."""
from pathlib import Path
import subprocess


def test_report_wave_menu_and_inline_tools():
    root = Path(__file__).resolve().parents[1]
    subprocess.run(['node', 'tests/browser_report_wave_menu.cjs'], cwd=root, check=True, timeout=90)
