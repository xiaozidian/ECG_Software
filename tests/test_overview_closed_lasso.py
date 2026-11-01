from pathlib import Path
import subprocess


def test_closed_lasso_uses_whole_path_to_distinguish_click():
    root=Path(__file__).resolve().parents[1]
    subprocess.run(['node',str(root/'tests/browser_overview_closed_lasso.cjs')],cwd=root,check=True,timeout=30)
