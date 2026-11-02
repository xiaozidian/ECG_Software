"""User-entered recording clocks retain dates and exact relative sample positions."""
from pathlib import Path
import subprocess


def test_recorded_clock_dates_and_relative_fallback():
    subprocess.run(['node', str(Path(__file__).with_name('browser_af_boundary_clock.cjs'))],
                   cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True, text=True)
