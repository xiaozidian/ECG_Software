"""Protect template editing context when entering and leaving 12-lead viewing."""
from pathlib import Path
import subprocess


def test_edit_fullscreen_return_lifecycle_and_navigation_ownership():
    subprocess.run(['node', 'tests/browser_edit_fullscreen.cjs'],
                   cwd=Path(__file__).resolve().parents[1], check=True, timeout=15)
