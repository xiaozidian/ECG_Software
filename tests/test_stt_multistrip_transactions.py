"""Actual ST/T UI controller transactions with deterministic delayed transport."""
from pathlib import Path
import json
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('scenario',[
    'atomicBulk','waitsForExistingSave','doubleClickAndFailure',
    'printingAndUndo','staleUndoBlocked','cancellationOwnsDraftKeys','duplicateReenablePreservesCuration',
])
def test_stt_multistrip_transaction_handlers(scenario):
    result=subprocess.run(['node',str(ROOT/'tests/browser_stt_multistrip_transactions.cjs'),scenario],
        cwd=ROOT,text=True,capture_output=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    proof=json.loads(result.stdout)
    assert proof['status']=='passed' and proof['scenario']==scenario
    assert proof['actual_function_extraction'] is True
