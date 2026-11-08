"""Exercise shipped template renderers without browser or clinical data."""
from pathlib import Path
import subprocess


def test_template_charts_redraw_source_without_mutating_selection():
    subprocess.run(["node", "tests/template_source_render.cjs"],
                   cwd=Path(__file__).resolve().parents[1], check=True, timeout=30)
