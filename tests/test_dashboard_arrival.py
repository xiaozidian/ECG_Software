"""Worklist entry tests run shipped JavaScript, without browser or patient writes."""
import subprocess
import pytest


@pytest.mark.parametrize('scenario', [
    'bootstrap', 'health-retry', 'scan-retry-epoch', 'empty-filter', 'filtered-open',
    'filter-during-load', 'clinical-filters', 'empty-index', 'missing-root',
    'late-health', 'late-success', 'late-error', 'timeout', 'invalid-response',
    'settings-failure', 'settings-slow', 'duplicate-open', 'failure-no-focus', 'network-copy',
])
def test_dashboard_arrival(scenario):
    subprocess.run(['node', 'tests/browser_dashboard_arrival.cjs', scenario], check=True, timeout=15)
