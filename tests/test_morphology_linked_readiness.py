import json
import shutil
import subprocess
from pathlib import Path


def test_actual_morphology_linked_readiness_lifecycle():
    node = shutil.which('node')
    assert node, 'Node is required to execute the real JavaScript lifecycle'
    script = Path(__file__).with_name('final_template_linked_readiness.cjs')
    run = subprocess.run([node, str(script)], text=True, capture_output=True,
                         timeout=30, check=True)
    result = json.loads(run.stdout)
    assert result['passed']
    assert result['actual_check_count'] == 6
    assert len(set(result['checks'])) == result['actual_check_count']
