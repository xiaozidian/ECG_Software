"""A failed mathematical raw read must recover without reloading saved browser work."""
from pathlib import Path
import subprocess


def test_demo_waveform_failed_pending_read_can_retry_without_altering_successful_bytes():
    subprocess.run(
        ['node', 'tests/browser_demo_waveform_retry.cjs'],
        cwd=Path(__file__).resolve().parents[1], check=True, timeout=15,
    )
