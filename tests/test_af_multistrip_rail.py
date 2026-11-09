"""Actual AF component/adoption helpers over mathematical transport in Chromium."""
from pathlib import Path
import os
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_af_episode_filmstrip_browse_adopt_exact_remove_and_fit():
    subprocess.run(["node", str(ROOT / "tests/browser_af_multistrip_rail.cjs")], cwd=ROOT, env=dict(os.environ), check=True, timeout=120)


def test_af_report_grouping_preserves_saved_selection_and_episode_extent():
    subprocess.run(["node", str(ROOT / "tests/browser_af_report_groups.cjs")], cwd=ROOT, env=dict(os.environ), check=True, timeout=30)


def test_af_text_adoption_is_independent_of_figures_and_tracks_true_rhythm_confirmation():
    subprocess.run(["node", str(ROOT / "tests/browser_af_text_independence.cjs")], cwd=ROOT, env=dict(os.environ), check=True, timeout=30)
