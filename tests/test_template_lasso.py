import subprocess
from pathlib import Path


def test_free_lasso_geometry_and_density_style():
    root = Path(__file__).resolve().parents[1]
    subprocess.run(['node', str(root / 'tests/template_lasso_geometry.cjs')], cwd=root, check=True, timeout=15)
