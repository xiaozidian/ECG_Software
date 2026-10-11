"""Execute the coordinator's stale-response and exact-membership contract."""
from pathlib import Path
import subprocess


def test_real_coordinator_membership_and_lifecycle():
    subprocess.run(['node', 'tests/linked_selection_contract.cjs'], cwd=Path(__file__).parents[1], check=True, timeout=20)
