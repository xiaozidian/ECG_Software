"""ST print reactivation and candidate withdrawal use production UI guards."""
from pathlib import Path
import subprocess


def test_ST_multiple_representatives_reactivate_print_and_withdraw_without_dangling_selection():
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(['node','tests/browser_stt_multistrip_reactivation.cjs'],cwd=root,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    assert '"passed":true' in result.stdout
