import subprocess


def test_workspace_loading_is_independent_of_new_wave_reads():
    subprocess.run(['node', 'tests/browser_edit_workspace_reads.cjs'], check=True, timeout=15)
