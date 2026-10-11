"""Identity-output races with synthetic metadata; no browser or case database writes."""
import pytest
from test_analysis_reads import run_browser_vm_fixture


@pytest.mark.parametrize("scenario", ["hrv", "preview", "frame", "views", "download"])
def test_report_identity_output_guards_and_snapshot_cleanup(scenario):
    run_browser_vm_fixture('tests/browser_report_privacy_outputs.cjs', scenario)
