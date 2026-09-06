from __future__ import annotations

import hashlib
import re
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
    assert re.search(r'static/js/demo-api.js\?v=[a-f0-9]{12}', html)
    html = re.sub(r'\?v=[a-f0-9]{12}', '', html)
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
    assert 'id="leadPickerDialog"' in html
    assert 'id="toggleWaveformFullscreen"' in html
    assert 'data-lead-choice' in html
    assert 'data-lead-preset' not in html
    assert "右键最近心搏重标注" in html
    assert "双击全屏查看全部 12 导联" in html
    assert 'data-page="stt"' in html
    assert 'id="page-stt"' in html
    assert 'id="sttWaveformCanvas"' in html
    assert 'id="sttGuidanceDialog"' in html
    assert "定量 ST 分析尚未启用" in html
    assert "不生成缺血或心肌梗死诊断" in html
    assert 'data-page="edit"' in html
    assert 'id="page-edit"' in html
    assert 'id="editWaveformCanvas"' in html
    assert 'id="editClassPopover"' in html
    assert 'id="caseWorkflow"' in html
    assert 'data-workflow-page="review"' in html
    assert 'data-workflow-page="report"' in html
    assert '<span>1</span>' not in html
    assert "第 1 步" not in html
    assert ">1　聚类分型<" not in html
    assert ">2　逐搏模板库<" not in html
    assert 'class="nav-item workflow-nav-item"' in html
    assert '<svg aria-hidden="true" viewBox="0 0 24 24">' in html
    assert html.index('data-page="review"') < html.index('data-page="edit"') < html.index('data-page="trends"')
    assert 'id="editClassSwitcher"' in html
    assert "先聚类分型，再逐搏改型" in html
    assert "不改写源 DATA / EBI" in html
    assert 'id="editMorphCanvasWrap"' in html
    assert "拖动框选 · 右键取消" in html
    assert "右键或按 Escape 取消框选" in html
    assert 'id="editRangeTop"' in html
    assert 'id="editRangeBottom"' in html
    assert 'id="editLibraryWorkbench"' in html
    assert 'id="editLibraryMatrix"' in html
    assert 'id="editLibraryWaveformCanvas"' in html
    assert 'aria-keyshortcuts="N S V X P O Backspace"' in html
    assert 'id="reportPageChecklist"' in html
    assert 'id="reportActivePageSelect"' in html
    assert 'id="reportSettingsDialog"' in html
    assert "最快最慢心率图条打印模式" in html
    assert (output / "static" / "js" / "demo-api.js").is_file()
    demo_api = (output / "static" / "js" / "demo-api.js").read_text(encoding="utf-8")
    assert "ASSET_BASE" in demo_api
    assert "waveformBuffer" in demo_api
    assert "COUNT=1" in demo_api
    app_js = (output / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert 'addEventListener("contextmenu"' in app_js
    assert "requestFullscreen" in app_js
    assert "waveformExpanded ? ALL_LEADS" in app_js
    assert "selected.length > 3" in app_js
    assert "async function loadStt()" in app_js
    assert 'filter:"raw"' in app_js
    assert "设备原始单位" in app_js
    assert "async function loadEdit()" in app_js
    assert "CASE_WORKFLOW_STEPS" in app_js
    assert "Math.max(300, canvas.parentElement.clientWidth" not in app_js
    clinical_js = (output / "static/js/clinical-workflow.js").read_text(encoding="utf-8")
    assert "review-workflow" in clinical_js and "event-reviews" in clinical_js
    assert "beforeunload" in clinical_js
    assert "function advanceCaseWorkflow" in app_js
    assert 'numberShortcut={1:"source-N",2:"source-S",3:"source-V",4:"source-X"}' in app_js
    assert "function applyMorphologySelection" in app_js
    assert 'morphCanvas.addEventListener("contextmenu"' in app_js
    assert 'morphTooltip.hidden=true;clearEditSelection()' in app_js
    assert "beat-templates" in app_js
    assert "beat-overrides" in app_js
    assert 'id="beatRelabelMenu"' in html
    assert 'data-beat-relabel-code="N"' in html
    assert 'data-beat-relabel-code="O"' in html
    assert 'openBeatRelabelMenu(event,canvas,state.waveform,"review")' in app_js
    assert 'openBeatRelabelMenu(event,waveCanvas,state.editWaveform,"edit")' in app_js
    assert "function restoreBeatRelabelTarget" in app_js
    assert "仅写入医生覆盖层，不改写源 DATA / EBI" in html
    assert 'key:"source-X"' in app_js
    assert "HRV 时域报告" in app_js
    assert "reportFastSlowCandidates" in app_js
    case_data = output / "static" / "demo-data" / "uploaded-sim-af-001" / "case-data.js"
    waveform_data = output / "static" / "demo-data" / "uploaded-sim-af-001" / "waveform.bin"
    assert case_data.is_file()
    assert waveform_data.stat().st_size == 1_920_000
    assert hashlib.sha256(waveform_data.read_bytes()).hexdigest() == "2896758a256a50670f464a33d280d23b763cb8746236da5e115b2f519899f4ff"
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
const browserStore = new Map();
global.localStorage = {getItem(key) { return browserStore.get(key)||null; }, setItem(key, value) {browserStore.set(key,value);}};
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

  const hrv = await (await window.fetch(`/api/cases/${caseId}/hrv`)).json();
  if (hrv.source.sdann_ms !== 130 || hrv.source.sdnn_index_ms !== 43 || hrv.source.triangular_index !== 34.37) throw new Error("full source report HRV missing");
  for (const field of ["mean_nn_ms", "sdnn_ms", "sdann_ms", "sdnn_index_ms", "rmssd_ms", "pnn50_pct", "triangular_index"]) {
    if (!Number.isFinite(hrv.calculated[field])) throw new Error(`excerpt HRV calculation missing: ${field}`);
  }
  if (!hrv.calculated.method.includes("5 分钟分段") || hrv.comparison.source_duration !== "23小时04分钟") throw new Error("HRV comparison scope missing");

  const events = await (await window.fetch(`/api/cases/${caseId}/events?type=AF`)).json();
  if (events.total !== 1 || events.items[0].type !== "AF") throw new Error("AF-like event missing");
  if (events.items[0].time_s < 479 || events.items[0].time_s > 481) throw new Error("AF-like event misplaced");

  const stt = await (await window.fetch(`/api/cases/${caseId}/stt-review`)).json();
  if (stt.review_mode !== "manual_review_only" || stt.manual_review_only !== true) throw new Error("ST-T manual-only boundary missing");
  if (stt.automatic_candidates.enabled !== false || stt.measurement_protocol.case_amplitude_output.enabled !== false) throw new Error("unsafe ST-T automatic output enabled");
  if (stt.clinical_safety.diagnosis_generated !== false) throw new Error("ST-T diagnosis boundary missing");

  const reportBefore = await (await window.fetch(`/api/cases/${caseId}/report`)).json();
  if (!reportBefore.composition.included_pages.includes("event_strips")) throw new Error("report composition defaults missing");
  const reportAfter = await (await window.fetch(`/api/cases/${caseId}/report`, {method: "PUT", body: JSON.stringify({conclusion: reportBefore.conclusion, status: "draft", composition: {...reportBefore.composition, active_page: "event_strips", fast_slow_mode: "both"}})})).json();
  if (reportAfter.composition.active_page !== "event_strips" || reportAfter.composition.fast_slow_mode !== "both") throw new Error("report composition persistence missing");

  const waveform = await (await window.fetch(`/api/cases/${caseId}/waveform?start=480&duration=10&leads=II,V1,V5`)).json();
  if (waveform.leads.II.length < 200 || waveform.duration_s !== 10) throw new Error("AF-like waveform unavailable");
  if (!waveform.calibration_note.includes("已上传源 DATA 片段")) throw new Error("source waveform not used");
  if (Math.max(...waveform.leads.II) === Math.min(...waveform.leads.II)) throw new Error("flat source waveform");

  const selectedSamples = waveform.beats.slice(0, 3).map(beat => beat.sample_index);
  const parentGroup = window.__CARDIOINSIGHT_UPLOADED_CASE__.beats.find(beat => beat.sample_index === selectedSamples[0]).group;
  const sameGroupSamples = window.__CARDIOINSIGHT_UPLOADED_CASE__.beats.filter(beat => beat.group === parentGroup).slice(0, 3).map(beat => beat.sample_index);
  const sourceClass = ({1: "source-N", 2: "source-S", 3: "source-V", 34: "source-X"})[parentGroup];
  const createdTemplate = await (await window.fetch(`/api/cases/${caseId}/beat-templates`, {method: "POST", body: JSON.stringify({name: "V1", rhythm_family: "房速", lead: "II", source_class: sourceClass, sample_indices: sameGroupSamples})})).json();
  if (createdTemplate.beat_count !== 3 || createdTemplate.rhythm_family !== "房速" || createdTemplate.source_class !== sourceClass) throw new Error("demo template creation missing");
  const templateList = await (await window.fetch(`/api/cases/${caseId}/beat-templates`)).json();
  if (templateList.items.length !== 1 || templateList.items[0].name !== "V1") throw new Error("demo template list missing");
  const updatedTemplate = await (await window.fetch(`/api/beat-templates/${createdTemplate.id}`, {method: "PATCH", body: JSON.stringify({name: "房速复核类 A"})})).json();
  if (updatedTemplate.name !== "房速复核类 A") throw new Error("demo template update missing");
  const invalidSampleResponse = await window.fetch(`/api/cases/${caseId}/beat-templates`, {method: "POST", body: JSON.stringify({name: "越界模板", rhythm_family: "自定义", lead: "II", sample_indices: [selectedSamples[0] + 1]})});
  if (invalidSampleResponse.status !== 400) throw new Error("demo template accepted a non-EBI sample");
  const invalidFamilyResponse = await window.fetch(`/api/beat-templates/${createdTemplate.id}`, {method: "PATCH", body: JSON.stringify({rhythm_family: "自动确诊"})});
  if (invalidFamilyResponse.status !== 400) throw new Error("demo template accepted an unsupported family");
  const overrideResponse = await (await window.fetch(`/api/cases/${caseId}/beat-overrides`, {method: "PUT", body: JSON.stringify({sample_indices: sameGroupSamples.slice(0, 2), class_code: "O"})})).json();
  if (overrideResponse.changed !== 2 || overrideResponse.items.some(item => item.class_code !== "O" || item.source_group !== parentGroup)) throw new Error("demo beat override missing");
  const overrideList = await (await window.fetch(`/api/cases/${caseId}/beat-overrides`)).json();
  if (overrideList.items.length !== 2) throw new Error("demo beat override list missing");
  const sourceGroupAfterOverride = window.__CARDIOINSIGHT_UPLOADED_CASE__.beats.find(beat => beat.sample_index === sameGroupSamples[0]).group;
  if (sourceGroupAfterOverride !== parentGroup) throw new Error("demo override rewrote source EBI grouping");
  const restoredOverride = await (await window.fetch(`/api/cases/${caseId}/beat-overrides`, {method: "DELETE", body: JSON.stringify({sample_indices: sameGroupSamples.slice(0, 2)})})).json();
  if (restoredOverride.changed !== 2) throw new Error("demo beat override restore missing");

  const getWorkflow = async () => (await window.fetch(`/api/cases/${caseId}/review-workflow`)).json();
  const put = (suffix,payload) => window.fetch(`/api/cases/${caseId}/${suffix}`, {method:"PUT",body:JSON.stringify(payload)});
  let workflow = await getWorkflow();
  if (workflow.pending_steps.length !== 5) throw new Error("navigation silently confirmed clinical steps");
  const blocked = await put("report", {conclusion:"回归测试，不代表临床复核",status:"reviewed"});
  if (blocked.ok) throw new Error("unreviewed demo report approved");
  const event = events.items[0];
  const retained = await put("event-reviews", {items:[event],status:"retained"});
  if (!retained.ok) throw new Error("event review failed");
  for (const step of ["review","edit","trends","stt","events"]) {
    workflow = await getWorkflow();
    const confirmed = await put("review-workflow", {step,revision:workflow.revision,confirmed:true,note:"自动化交互测试"});
    if (!confirmed.ok) throw new Error("checkpoint confirmation failed: "+step);
  }
  workflow = await getWorkflow();
  if (workflow.pending_steps.length || Object.values(workflow.events)[0].status !== "retained") throw new Error("workflow state missing");
  const stale = await put("review-workflow", {step:"review",revision:workflow.revision-1,confirmed:true});
  if (stale.ok) throw new Error("stale confirmation accepted");
  const approved = await put("report",{conclusion:"回归测试，不代表临床复核",status:"reviewed"});
  if (!approved.ok) throw new Error("completed report could not be approved");
  await put("beat-overrides",{sample_indices:sameGroupSamples.slice(0,1),class_code:"V"});
  workflow = await getWorkflow();
  if (workflow.pending_steps.length !== 5 || workflow.report_status !== "draft") throw new Error("upstream edit did not invalidate approval");
  if (Object.values(workflow.events)[0].status !== "pending") throw new Error("upstream edit left stale evidence accepted");
  // Re-create the adapter, emulating reload with the same browser storage.
  delete require.cache[require.resolve(process.cwd()+"/static/js/demo-api.js")];
  require(process.cwd()+"/static/js/demo-api.js");
  const reloaded = await getWorkflow();
  if (JSON.stringify(reloaded) !== JSON.stringify(workflow)) throw new Error("review workflow lost on reload");
  const secondPage = await (await window.fetch(`/api/cases/${caseId}/events?type=all&limit=100&offset=100`)).json();
  if (!secondPage.items.length || secondPage.items.length > 100) throw new Error("event pagination failed");
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    subprocess.run(["node", "-e", browser_probe], cwd=output, check=True)
