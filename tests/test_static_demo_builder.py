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
    assert 'data-event-type="AF"' in html
    assert "房颤样候选" in html
    assert (output / "static" / "js" / "demo-api.js").is_file()
    demo_api = (output / "static" / "js" / "demo-api.js").read_text(encoding="utf-8")
    assert "DISEASE_DURATION=600" in demo_api
    assert "source_waveform_copied:false" in demo_api
    assert "raw_patient_data:false" in demo_api
    assert (output / ".nojekyll").is_file()
    headers = (output / "_headers").read_text(encoding="utf-8")
    assert "Content-Security-Policy:" in headers
    assert "frame-ancestors 'none'" in headers
    assert "X-Content-Type-Options: nosniff" in headers

    browser_probe = r"""
global.document = {addEventListener() {}};
global.localStorage = {getItem() { return null; }, setItem() {}};
global.location = {href: "https://demo.invalid/"};
global.window = {
  fetch: async () => new Response("not intercepted"),
  location: global.location,
};
require(process.cwd() + "/static/js/demo-api.js");

(async () => {
  const detail = await (await window.fetch("/api/cases/SYNTH-005")).json();
  if (detail.technical.duration_seconds_raw !== 600) throw new Error("unexpected disease demo duration");
  if (detail.integrity.raw_patient_data !== false) throw new Error("raw data boundary missing");
  if (detail.simulation_profile.source_waveform_copied !== false) throw new Error("waveform provenance missing");

  const events = await (await window.fetch("/api/cases/SYNTH-005/events?type=AF")).json();
  if (events.total !== 1 || events.items[0].type !== "AF") throw new Error("AF-like event missing");
  if (events.items[0].time_s < 239 || events.items[0].time_s > 241) throw new Error("AF-like event misplaced");

  const waveform = await (await window.fetch("/api/cases/SYNTH-005/waveform?start=240&duration=10&leads=II")).json();
  if (waveform.leads.II.length < 200 || waveform.duration_s !== 10) throw new Error("AF-like waveform unavailable");
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    subprocess.run(["node", "-e", browser_probe], cwd=output, check=True)
