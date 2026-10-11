"""Module-only synthetic checks; integrated viewport acceptance is separate."""
import subprocess


def test_o6_o7_module_contracts():
    subprocess.run(['node', 'tests/browser_report_workspace_o67.cjs'], check=True)
