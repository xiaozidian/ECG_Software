from pathlib import Path
import subprocess


def test_chart_source_render():
    root = Path(__file__).resolve().parents[1]
    subprocess.run(['node', str(root / 'tests/chart_source_render.cjs')], cwd=root, check=True, timeout=30)


def test_chart_inspection_lifecycle():
    root = Path(__file__).resolve().parents[1]
    subprocess.run(['node', str(root / 'tests/chart_inspection_lifecycle.cjs')], cwd=root, check=True, timeout=30)


def test_chart_owner_render():
    root = Path(__file__).resolve().parents[1]
    subprocess.run(['node', str(root / 'tests/chart_owner_render.cjs')], cwd=root, check=True, timeout=30)
