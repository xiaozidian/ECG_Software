"""Exercise request races and unchanged HRV evidence in production JavaScript."""
from pathlib import Path
import subprocess


def test_hospital_measurement_request_races_and_shared_hrv_evidence():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ['node', 'tests/hospital_st_hrv_contract.cjs'], cwd=root,
        capture_output=True, text=True, check=True, timeout=30,
    )
    assert 'identical screen/paper plotting coordinates passed' in result.stdout
