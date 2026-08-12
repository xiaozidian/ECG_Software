from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_static_demo_builder(tmp_path: Path) -> None:
    assert not (PROJECT_ROOT / "static" / "js" / "demo-api.js").exists()
    assert not (PROJECT_ROOT / "static" / "demo-data").exists()
    assert (PROJECT_ROOT / "demo" / "static" / "js" / "demo-api.js").is_file()
    assert (PROJECT_ROOT / "demo" / "static" / "demo-data" / "uploaded-sim-af-001" / "case-data.js").is_file()
    output = tmp_path / "pages"
    subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "build_static_demo.py"), "--output", str(output)],
        cwd=PROJECT_ROOT,
        check=True,
    )
    html = (output / "index.html").read_text(encoding="utf-8")
    assert "病例数据在线演示" in html
    assert 'data-demo-readonly="true"' in html
    assert 'data-allow-phi="false"' in html
    assert "{{" not in html and "{%" not in html
    assert 'href="static/css/app.css"' in html
    assert 'src="static/demo-data/uploaded-sim-af-001/case-data.js"' in html
    assert 'src="static/js/demo-api.js"' in html
    assert html.index('src="static/demo-data/uploaded-sim-af-001/case-data.js"') < html.index('src="static/js/demo-api.js"')
    assert html.index('src="static/js/demo-api.js"') < html.index('src="static/js/app.js"')
    assert 'data-event-type="AF"' in html
    assert "房颤样候选" in html
    assert (output / "static" / "js" / "demo-api.js").is_file()
    demo_api = (output / "static" / "js" / "demo-api.js").read_text(encoding="utf-8")
    assert "ASSET_BASE" in demo_api
    assert "waveformBuffer" in demo_api
    assert "COUNT=1" in demo_api
    case_data = output / "static" / "demo-data" / "uploaded-sim-af-001" / "case-data.js"
    waveform_data = output / "static" / "demo-data" / "uploaded-sim-af-001" / "waveform.bin"
    assert case_data.is_file()
    assert waveform_data.stat().st_size == 1_920_000
    for public_text in (html, demo_api, case_data.read_text(encoding="utf-8")):
        assert "合成" not in public_text
    assert (output / ".nojekyll").is_file()
    headers = (output / "_headers").read_text(encoding="utf-8")
    assert "Content-Security-Policy:" in headers
    assert "frame-ancestors 'none'" in headers
    assert "X-Content-Type-Options: nosniff" in headers

    browser_probe = r"""
const fs = require("fs");
const path = require("path");
global.document = {addEventListener() {}};
global.localStorage = {getItem() { return null; }, setItem() {}};
global.location = {href: "https://demo.invalid/"};
global.window = {};
require(path.join(process.cwd(), "static/demo-data/uploaded-sim-af-001/case-data.js"));
global.window = {
  ...global.window,
  fetch: async input => String(input).endsWith("waveform.bin")
    ? new Response(fs.readFileSync(path.join(process.cwd(), "static/demo-data/uploaded-sim-af-001/waveform.bin")))
    : new Response("not intercepted", {status: 404}),
  location: global.location,
};
require(process.cwd() + "/static/js/demo-api.js");

(async () => {
  const caseId = window.__CARDIOINSIGHT_UPLOADED_CASE__.case_id;
  const caseList = await (await window.fetch("/api/cases")).json();
  if (caseList.total !== 1 || caseList.items.length !== 1) throw new Error("public demo must contain one case");
  if (caseList.items[0].metadata.name !== "徐有德" || caseList.items[0].case_id !== caseId) throw new Error("unexpected public case");
  if (JSON.stringify(caseList).includes("合成")) throw new Error("forbidden public wording");
  const detail = await (await window.fetch(`/api/cases/${caseId}`)).json();
  if (detail.technical.duration_seconds_raw !== 600) throw new Error("unexpected disease demo duration");
  if (detail.integrity.raw_patient_data !== false) throw new Error("raw data boundary missing");
  if (detail.integrity.user_confirmed_synthetic !== true) throw new Error("synthetic confirmation missing");
  if (detail.simulation_profile.source_waveform_copied !== true) throw new Error("waveform provenance missing");

  const events = await (await window.fetch(`/api/cases/${caseId}/events?type=AF`)).json();
  if (events.total !== 1 || events.items[0].type !== "AF") throw new Error("AF-like event missing");
  if (events.items[0].time_s < 479 || events.items[0].time_s > 481) throw new Error("AF-like event misplaced");

  const waveform = await (await window.fetch(`/api/cases/${caseId}/waveform?start=480&duration=10&leads=II,V1,V5`)).json();
  if (waveform.leads.II.length < 200 || waveform.duration_s !== 10) throw new Error("AF-like waveform unavailable");
  if (!waveform.calibration_note.includes("已上传源 DATA 片段")) throw new Error("source waveform not used");
  if (Math.max(...waveform.leads.II) === Math.min(...waveform.leads.II)) throw new Error("flat source waveform");
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    subprocess.run(["node", "-e", browser_probe], cwd=output, check=True)
