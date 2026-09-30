"""Bounded physician episode queue, draft protection and late-navigation isolation."""
from pathlib import Path
import subprocess
import pytest

ROOT = Path(__file__).parents[1]

@pytest.mark.parametrize('scenario', [
    'bounded', 'filter', 'sort', 'empty', 'empty-filter', 'navigation',
    'after-confirm', 'retain-form', 'retain-navigation', 'case-isolation',
    'stale-draft', 'save-clears-draft', 'discard', 'discard-stale', 'removed-draft',
    'race-case', 'race-beats', 'race-rhythm', 'race-source', 'race-close',
    'race-navigation', 'summary-saved-only',
])
def test_shipped_episode_queue(scenario):
    subprocess.run(['node', 'tests/browser_af_queue.cjs', scenario], cwd=ROOT, check=True)
