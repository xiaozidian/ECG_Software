"""Shipped scatter gates and report lead-count invariants; no clinical or output paths."""
from pathlib import Path
import subprocess


def test_scatter_categories_and_report_lead_geometry():
    root = Path(__file__).resolve().parents[1]
    subprocess.run(['node', 'tests/scatter_report_invariants.cjs'], cwd=root, check=True, timeout=30)
