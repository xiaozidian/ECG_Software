"""Run the actual editor module against delayed transport and case lifecycle changes."""
import subprocess
import pytest


@pytest.mark.parametrize('scenario', [
    'read-case', 'read-lifecycle', 'read-cancel', 'read-second',
    'preview-case', 'preview-lifecycle', 'preview-cancel', 'preview-second',
    'put-case', 'put-lifecycle', 'invoke-case', 'invoke-lifecycle',
    'confirm-case', 'confirm-lifecycle', 'confirm-cancel',
    'confirm-success', 'read-success', 'preview-success',
    'read-page', 'preview-page', 'put-page', 'invoke-page',
    'menu-success', 'menu-case', 'menu-lifecycle', 'menu-cancel', 'menu-page',
    'undo-success', 'undo-case', 'undo-lifecycle', 'confirm-replaced',
    'read-selection', 'preview-selection', 'put-selection',
    'read-focus', 'preview-focus', 'put-focus',
    'confirm-selection', 'confirm-focus', 'menu-selection', 'menu-focus',
    'invoke-selection', 'invoke-focus', 'undo-selection', 'undo-focus',
])
def test_beat_editor_preserves_operation_owner(scenario):
    subprocess.run(['node', 'tests/browser_beat_editor_races.cjs', scenario], check=True, timeout=15)
