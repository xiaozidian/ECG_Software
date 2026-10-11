"""Synthetic workbench contract, independent of patient data and shared servers."""
import subprocess
from pathlib import Path


def test_morphology_scope_and_state_contract():
    subprocess.run(
        ['node', 'tests/browser_morphology_scope.cjs'],
        cwd=Path(__file__).resolve().parents[1], check=True, timeout=15,
    )
