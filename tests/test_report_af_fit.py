"""Shipped AF report frame fits 3/12 leads without losing source samples."""
from pathlib import Path
import subprocess


def test_report_af_frame_fits_three_and_twelve_leads():
    root=Path(__file__).resolve().parents[1]
    subprocess.run(['node','tests/browser_report_af_fit.cjs'],cwd=root,check=True,timeout=90)
