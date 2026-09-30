"""Run the production browser panel, not a reimplementation of its state rules."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_retained_panel_lifecycle_and_output_gates():
    result = subprocess.run(['node', 'tests/browser_advanced_session.cjs'], cwd=ROOT,
                            text=True, capture_output=True, check=True)
    assert '7 lifecycle scenarios and 5 output-entry gates passed' in result.stdout


def test_measurement_requests_bind_the_displayed_basis():
    result = subprocess.run(['node', 'tests/browser_advanced_basis.cjs'], cwd=ROOT,
                            text=True, capture_output=True, check=True)
    assert '8 displayed-basis scenarios passed' in result.stdout
