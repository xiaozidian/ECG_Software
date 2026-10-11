import subprocess


def test_occurrence_thumbnails_bind_case_token_and_basis():
    subprocess.run(['node', 'tests/browser_occurrence_scope.cjs'], check=True, timeout=15)
