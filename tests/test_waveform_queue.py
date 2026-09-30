"""Off-screen queued thumbnails must not delay the current viewport or reports."""
import subprocess
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('scenario', [
    'backlog', 'shared-report', 'multiple-owners', 'reenter', 'inflight', 'priority', 'clear',
])
def test_thumbnail_demand(scenario):
    result=subprocess.run(['node','tests/browser_waveform_queue.cjs',scenario],
                          cwd=ROOT,capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
