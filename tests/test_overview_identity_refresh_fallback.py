"""The post-save full-read fallback must still reject changed source or beats."""
import subprocess

import pytest


@pytest.mark.parametrize('scenario', ['save-source-mismatch', 'save-beat-mismatch'])
def test_overview_saved_fallback_rejects_inconsistent_current_reads(scenario):
    subprocess.run(['node', 'tests/browser_overview_identity.cjs', scenario], check=True, timeout=20)
