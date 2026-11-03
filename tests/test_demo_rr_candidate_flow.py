"""Actual mathematical Demo adapter: merged RR and independent AF strip ranges."""
from pathlib import Path
import subprocess


def test_demo_rr_candidates_and_af_middle_strip():
    root=Path(__file__).resolve().parents[1]
    subprocess.run(['node','tests/browser_demo_rr_candidate_flow.cjs'],cwd=root,check=True,timeout=90)
