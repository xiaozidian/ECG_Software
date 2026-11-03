"""The AF editor uses a bounded display frame without height-driven gain."""
from pathlib import Path
import subprocess


def test_af_canvas_height_and_viewing_gain_stay_bounded():
    root = Path(__file__).resolve().parents[1]
    subprocess.run(['node', 'tests/browser_af_wave_height.cjs'], cwd=root, check=True, timeout=90)
