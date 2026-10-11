"""Focused report view lifecycle and range status coverage with synthetic inputs."""
import subprocess
from test_analysis_reads import run_browser_vm_fixture


def test_report_local_views_preserve_and_isolate_evidence():
    subprocess.run(['node', 'tests/browser_report_local_update.cjs'], check=True, timeout=20)


def test_range_status_distinguishes_drafts_from_applied_times():
    subprocess.run(['node', 'tests/browser_range_status.cjs'], check=True, timeout=20)


def test_first_range_apply_on_unselected_candidate_commits_new_baseline():
    subprocess.run(['node', 'tests/browser_report_local_first_apply.cjs'], check=True, timeout=20)


def test_hrv_print_rechecks_case_and_window_after_styles_and_fonts():
    run_browser_vm_fixture('tests/browser_report_local_hrv_print.cjs')
