from pathlib import Path
import subprocess


def test_actual_stt_report_adoption_handlers():
    result=subprocess.run(['node','tests/browser_stt_report_adoption.cjs'],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,check=True,timeout=30)
    assert '"math_only":true' in result.stdout
    assert '"actual_handlers":true' in result.stdout
