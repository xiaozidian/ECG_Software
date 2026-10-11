"""Thumbnail source points, physical geometry, grouped selection and lead identity."""
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('scenario', [
    'source-points', 'stride-and-anchor', 'whole-group', 'record-boundary',
    'lead-identity', 'mixed-selection',
])
def test_occurrence_card_source_and_selection(scenario):
    subprocess.run(['node', 'tests/browser_occurrence_card.cjs', scenario],
                   cwd=ROOT, check=True, capture_output=True, text=True)
