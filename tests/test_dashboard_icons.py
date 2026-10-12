"""Home-only geometry over the real template/styles and authored display values."""
import os
from pathlib import Path
import re
import subprocess

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_svg_icons_and_structural_ring_layout(tmp_path):
    environment = Environment(
        loader=FileSystemLoader(ROOT / "templates"),
        autoescape=select_autoescape(["html"]), undefined=StrictUndefined,
    )
    environment.globals["url_for"] = lambda endpoint, filename: "static/" + filename
    html = environment.get_template("index.html").render(
        app_name="Mathematical home layout", app_version="synthetic-layout",
        app_version_short="Mathematical", demo_readonly=True, allow_phi=False,
    )
    # Layout verification executes no application transport or event handlers.
    # Replace the actual ordered stylesheet links with their unchanged bytes.
    html = re.sub(r"<script\b[^>]*>[\s\S]*?</script>", "", html)
    html = re.sub(
        r'<link rel="stylesheet" href="(static/css/[^"]+)">',
        lambda match: '<style data-source="' + match[1] + '">'
        + (ROOT / match[1]).read_text(encoding="utf-8") + "</style>", html,
    )
    html = re.sub(r'<img\b[^>]*>', "", html)
    target = tmp_path / "mathematical-home.html"
    target.write_text(html, encoding="utf-8")
    # The child needs browser/path configuration only. Do not put unrelated
    # runner credentials into a failed subprocess argument representation.
    child_environment = {
        key: value for key, value in os.environ.items()
        if key in {"PATH", "TMPDIR", "TEMP", "TMP", "SystemRoot", "SYSTEMROOT",
                   "WINDIR", "LANG", "LC_ALL", "NODE_PATH", "ECG_PLAYWRIGHT_CORE",
                   "PLAYWRIGHT_CORE", "ECG_CHROME", "ECG_DASHBOARD_ICON_EVIDENCE"}
    }
    subprocess.run(
        ["node", str(ROOT / "tests/browser_dashboard_icons.cjs"), str(target)],
        cwd=ROOT, env=child_environment, check=True, timeout=90,
    )
