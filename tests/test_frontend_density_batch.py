"""Exercise the actual request coalescer, including isolation and failed batches."""
import json
from pathlib import Path
import subprocess


def test_density_coalescer_preserves_complete_scope_and_cancellation():
    run = subprocess.run(['node', 'tests/browser_density_batch.cjs'],
                         cwd=Path(__file__).resolve().parents[1],
                         check=True, capture_output=True, text=True, timeout=15)
    assert json.loads(run.stdout)['passed'] is True
