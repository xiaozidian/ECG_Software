from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_static_demo_builder(tmp_path: Path) -> None:
    output = tmp_path / "pages"
    subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "build_static_demo.py"), "--output", str(output)],
        cwd=PROJECT_ROOT,
        check=True,
    )
    html = (output / "index.html").read_text(encoding="utf-8")
    assert "纯合成数据在线演示" in html
    assert 'data-demo-readonly="true"' in html
    assert 'data-allow-phi="false"' in html
    assert "{{" not in html and "{%" not in html
    assert 'href="static/css/app.css"' in html
    assert 'src="static/js/demo-api.js"' in html
    assert html.index('src="static/js/demo-api.js"') < html.index('src="static/js/app.js"')
    assert (output / "static" / "js" / "demo-api.js").is_file()
    assert (output / ".nojekyll").is_file()
