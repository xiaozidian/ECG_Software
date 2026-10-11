import subprocess


def test_group_source_navigation_preserves_targets_and_refuses_stale_or_strided_evidence():
    subprocess.run(['node','tests/browser_source_group_evidence.cjs'],check=True,
                   capture_output=True,text=True)
