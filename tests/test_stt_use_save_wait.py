"""Production ST-T checkbox/save races using disposable metadata, not real case tests."""
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("scenario", ["wait", "intents", "changed", "failures"])
def test_stt_checkbox_intent_waits_for_save_and_rechecks_context(scenario):
    subprocess.run(
        ["node", "tests/browser_stt_use_save_wait.cjs", scenario],
        cwd=ROOT,
        check=True,
        timeout=20,
    )
