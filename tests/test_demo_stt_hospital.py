"""Actual mathematical browser storage/fetch adapter, no service or patient source."""
from pathlib import Path
import subprocess

def test_actual_demo_stt_hospital_save_history_and_report_contract():
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(['node','tests/browser_demo_stt_hospital.cjs'],cwd=root,capture_output=True,text=True,check=True,timeout=90)
    assert '"servers_started":false' in result.stdout
