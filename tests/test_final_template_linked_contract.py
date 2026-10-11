import json
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).parent


@pytest.fixture(scope='module')
def contracts():
    node = shutil.which('node')
    assert node, 'Node is required to execute the real JavaScript contracts'
    results = {}
    for name in ('math', 'adapter', 'morphadapter'):
        run = subprocess.run([node, str(HERE / f'final_template_linked_{name}.cjs')],
                             text=True, capture_output=True, timeout=30, check=True)
        result = json.loads(run.stdout)
        assert result['passed'] and len(result['checks']) == result['actual_check_count']
        results[name] = result
    return results


@pytest.mark.parametrize('kind,count', [('math', 9), ('adapter', 6), ('morphadapter', 3)])
def test_actual_template_linked_contracts(contracts, kind, count):
    assert contracts[kind]['actual_check_count'] == count
    assert len(set(contracts[kind]['checks'])) == count
