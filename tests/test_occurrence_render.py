"""Real frontend renderer, isolated DOM model: reuse must not reuse stale targets."""
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('scenario', [
    'reuse', 'rows', 'scope', 'selection', 'focus', 'resize',
    'replaced-item', 'late-response', 'failure-retry', 'demand', 'inactive', 'navigation',
    'jump-reset', 'jump-draft', 'jump-validation', 'jump-enter', 'jump-empty',
    'jump-failure', 'jump-filter-race', 'jump-case-race', 'jump-late-error',
    'jump-lazy-focus', 'jump-focus-abandoned', 'jump-focus-scrolled',
    'jump-lazy-filter', 'jump-lazy-arrow',
    'resume-exact', 'resume-nearby', 'resume-no-focus', 'resume-empty',
    'resume-filter', 'resume-case', 'resume-lifecycle', 'resume-token',
    'resume-page', 'resume-late-lifecycle', 'resume-scrolled',
])
def test_occurrence_renderer(scenario):
    subprocess.run(['node', 'tests/browser_occurrence_render.cjs', scenario],
                   cwd=ROOT, check=True, capture_output=True, text=True)
