from pathlib import Path
import subprocess

def test_actual_stt_hospital_record_handlers():
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(['node','tests/browser_stt_hospital_records.cjs'],cwd=root,capture_output=True,text=True,check=True,timeout=20)
    assert '"passed":8' in result.stdout
