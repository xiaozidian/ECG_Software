"""Exercise shipped browser lifecycle functions using controlled async responses."""
import subprocess
import pytest


@pytest.mark.parametrize("scenario", [
    "last-intent", "cancel-before-open", "cancel-after-open", "replace-case",
    "failed-load", "dirty-refresh", "saving-refresh", "clean-refresh", "saving-navigation",
])
def test_browser_case_lifecycle(scenario):
    subprocess.run(["node", "tests/browser_case_lifecycle.cjs", scenario], check=True, timeout=15)


@pytest.mark.parametrize("scenario", ["stable", "typed", "selection", "saving", "new-base", "case-switch", "case-reopen"])
def test_report_reload_keeps_edits_made_while_waiting(scenario):
    subprocess.run(["node", "tests/browser_report_reload.cjs", scenario], check=True, timeout=15)


def test_report_shell_synchronizes_preflight_state():
    subprocess.run(["node", "tests/browser_report_shell.cjs"], check=True, timeout=15)
