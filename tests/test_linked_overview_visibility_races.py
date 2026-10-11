"""Verify visible linked mini reads and stale outcomes without browser or network."""
import json
from pathlib import Path
import subprocess


def test_linked_overview_visibility_and_async_races():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ['node', 'tests/linked_overview_visibility_races.cjs'],
        cwd=root, check=True, capture_output=True, text=True, timeout=30,
    )
    evidence = json.loads(result.stdout)
    assert evidence['passed'] is True
    assert evidence['total'] == 8
    assert evidence['sourceStable'] is True
    assert evidence['noNetwork'] is True
    assert all(item['issuePresent'] is False for item in evidence['observations'])
