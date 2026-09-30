"""Production range-editor state and write-entry protection, mathematical inputs only."""
import subprocess


def test_temporary_range_lifecycle_and_report_entry_guards():
    subprocess.run(['node', 'tests/browser_range_drafts.cjs'], check=True, timeout=20)


def test_temporary_ranges_during_async_output_and_reload():
    subprocess.run(['node', 'tests/browser_range_output_races.cjs'], check=True, timeout=20)
