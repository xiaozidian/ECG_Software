"""UI metadata-only saves retain validated pixels and reject unsafe transitions."""
from pathlib import Path
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("scenario", [
    "known-adapter", "unknown-adapter", "failed-adapter", "incremental-success",
    "sourceChanged", "concurrent", "endRace", "beatChanged", "badReceipt",
    "badUuid", "badWindow", "badLeads", "departed", "finish-fallback", "finish-read-failure",
])
def test_review_write_local_sync(scenario):
    subprocess.run(["node", "tests/review_write_local_sync.cjs", scenario],
                   cwd=ROOT, check=True, timeout=20)
