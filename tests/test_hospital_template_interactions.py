"""Hospital template UI contracts using only synthetic Node fixtures."""
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "script",
    [
        "hospital_template_group_selection.cjs",
        "hospital_template_master_inspection.cjs",
    ],
    ids=["group-view", "master-inspection"],
)
def test_hospital_template_interactions(script):
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        ["node", str(root / "tests" / script)],
        cwd=root, check=True, timeout=15,
    )
