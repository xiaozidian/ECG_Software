"""Successful writes retire only their current scoped overview evidence."""
import subprocess

import pytest


@pytest.mark.parametrize("scenario", [
    "template-ack", "failed-write", "ordinary-reads", "late-other-case",
    "late-same-case-reopen", "late-success", "late-error", "episode-draft", "write-kinds",
])
def test_browser_overview_write_invalidation(scenario):
    subprocess.run(["node", "tests/browser_overview_write_invalidation.cjs", scenario],
                   check=True, timeout=20)
