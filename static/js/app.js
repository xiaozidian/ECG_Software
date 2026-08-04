"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const ALL_LEADS = ["I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6"];
const LEAD_PRESETS = {
  3: ["II", "V1", "V5"],
  6: ["I", "II", "III", "aVR", "V1", "V5"],
  12: ALL_LEADS,
};
const STATUS_TEXT = {draft: "未审核", reviewed: "已审核", returned: "已驳回"};
const UI_FONT = '"SF Pro Text", "PingFang SC", "Microsoft YaHei UI", sans-serif';
const ACTION_TEXT = {
  "privacy.phi_view": "查看身份信息", "case.open": "打开病例",
  "annotation.create": "创建标注", "annotation.delete": "删除标注",
  "patient.update": "修改患者", "report.draft": "保存报告草稿",
  "report.reviewed": "审核报告", "report.returned": "驳回报告",
  "report.export_pdf": "导出 PDF",
};

const state = {
  includePhi: false,
  cases: [],
  dashboard: null,
  settings: null,
  caseId: null,
  caseData: null,
  start: 0,
  duration: 10,
  gain: 10,
  filter: "display",
  leadPreset: 3,
  leads: LEAD_PRESETS[3],
  trend: null,
  waveform: null,
  rr: null,
  hrv: null,
  events: null,
  eventType: "all",
  report: null,
  reportDirty: false,
  search: "",
  currentPage: "dashboard",
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {"Content-Type": "application/json", "X-Actor": "demo-analyst", "X-CardioInsight-Request": "1", ...(options.headers || {})},
    ...options,
  });
  const type = response.headers.get("content-type") || "";
  const payload = type.includes("application/json") ? await response.json() : null;
  if (!response.ok) throw new Error(payload?.error || `请求失败（${response.status}）`);
  return payload;
}

function toast(message, type = "success", timeout = 2800) {
  const item = document.createElement("div");
  item.className = `toast ${type}`;
  item.textContent = message;
  $("#toastStack").appendChild(item);
  setTimeout(() => item.remove(), timeout);
}

function fmtNumber(value) {
  return Number(value || 0).toLocaleString("zh-CN");
}

function formatElapsed(seconds, withDay = true) {
  const safe = Math.max(0, Math.round(Number(seconds) || 0));
  const day = Math.floor(safe / 86400) + 1;
  const within = safe % 86400;
  const hh = String(Math.floor(within / 3600)).padStart(2, "0");
  const mm = String(Math.floor((within % 3600) / 60)).padStart(2, "0");
  const ss = String(within % 60).padStart(2, "0");
  return `${withDay ? `D${day} ` : ""}${hh}:${mm}:${ss}`;
}

function applyPlatformIdentity(platformName = "") {
  const isMac = /darwin|mac/i.test(platformName);
  const isWindows = /windows|win32|win64/i.test(platformName);
  const key = isMac ? "mac" : isWindows ? "windows" : "other";
  const label = isMac ? "macOS" : isWindows ? "Windows" : "桌面系统";
  document.documentElement.dataset.platform = key;
  $("#searchShortcut").textContent = isMac ? "⌘ K" : "Ctrl K";
  $("#platformEdition").textContent = `${label} 研究版`;
  $("#platformHeading").textContent = `${label} 运行环境`;
  $("#platformIcon").textContent = isMac ? "⌘" : isWindows ? "⊞" : "◫";
  $("#displayOptimization").textContent = `${isMac ? "Retina" : "HiDPI"} · 系统字体`;
}

function sourceHint(conclusion) {
  return String(conclusion || "未填写源报告结论").split(/\n/).filter(Boolean).slice(0, 2).join("；");
}

function withPhi(path) {
  const join = path.includes("?") ? "&" : "?";
  return `${path}${join}include_phi=${state.includePhi ? 1 : 0}`;
}

function filteredCases() {
  const q = state.search.trim().toLowerCase();
  const filter = $("#worklistFilter")?.value || "all";
  return state.cases.filter(item => {
    const text = [item.case_id, item.metadata.name, item.metadata.patient_id, item.metadata.clinical_diagnosis, item.conclusion].join(" ").toLowerCase();
    const matchesSearch = !q || text.includes(q);
    const summary = item.summary;
    const matchesFilter = filter === "all"
      || (filter === "abnormal" && ((summary.ventricular_beats || 0) + (summary.supraventricular_beats || 0) > 0))
      || (filter === "brady" && (summary.avg_hr || 999) < 60);
    return matchesSearch && matchesFilter;
  });
}

async function loadDashboard() {
  const data = await api(withPhi("/api/dashboard"));
  state.dashboard = data;
  state.cases = data.cases;
  $("#metricCases").textContent = fmtNumber(data.totals.cases);
  $("#metricHours").textContent = fmtNumber(data.totals.recording_hours);
  $("#metricBeats").textContent = fmtNumber(data.totals.beats);
  $("#metricPending").textContent = fmtNumber(data.totals.pending_reports);
  const count = data.totals.cases;
  $("#qualityStatus").textContent = count ? `${count} / ${count} 通过` : "等待数据";
  $("#qualityStatus").className = `status-pill ${count ? "success" : "warning"}`;
  $("#qualityPercent").textContent = count ? "100%" : "—";
  $("#sourceReportPages").textContent = count
    ? `源报告共 ${fmtNumber(data.cases.reduce((sum, item) => sum + (item.technical.report_pages || 0), 0))} 页`
    : "源报告页数待读取";
  renderWorklist();
  renderPatients();
}

function renderWorklist() {
  const body = $("#worklistBody");
  const rows = filteredCases();
  body.innerHTML = rows.map(item => {
    const m = item.metadata, s = item.summary;
    return `<tr data-case-id="${item.case_id}">
      <td><div class="patient-cell"><span class="patient-badge">${escapeHtml((m.name || "病").slice(0, 1))}</span><div><strong>${escapeHtml(m.name || "未命名")}</strong><small>${item.case_id} · ${escapeHtml(m.patient_id || "无患者ID")}</small></div></div></td>
      <td>${escapeHtml(m.start_time || "—")}</td>
      <td>${escapeHtml(m.duration_text || "—")}</td>
      <td><div class="hr-range"><strong>${s.avg_hr ?? "—"}</strong> bpm<small>${s.min_hr ?? "—"}–${s.max_hr ?? "—"}</small></div></td>
      <td class="candidate-count"><span class="status-pill ${s.ventricular_beats ? "danger" : "neutral"}">V ${fmtNumber(s.ventricular_beats)}</span> <span class="status-pill neutral">S ${fmtNumber(s.supraventricular_beats)}</span></td>
      <td><span class="source-hint" title="${escapeHtml(sourceHint(item.conclusion))}">${escapeHtml(sourceHint(item.conclusion))}</span></td>
      <td><button class="row-action" data-open-case="${item.case_id}">复核 →</button></td>
    </tr>`;
  }).join("") || `<tr><td colspan="7" class="empty-state">没有符合条件的病例</td></tr>`;
}

function renderPatients() {
  const showDeleted = $("#showDeleted")?.checked;
  const rows = state.cases.filter(item => showDeleted || item.active).filter(item => {
    if (!state.search) return true;
    return [item.case_id, item.metadata.name, item.metadata.patient_id, item.metadata.clinical_diagnosis].join(" ").toLowerCase().includes(state.search.toLowerCase());
  });
  $("#patientCount").textContent = `${rows.length} 条`;
  $("#patientBody").innerHTML = rows.map(item => {
    const m = item.metadata;
    return `<tr class="${item.active ? "" : "inactive-row"}">
      <td><div class="patient-cell"><span class="patient-badge">${escapeHtml((m.name || "病").slice(0, 1))}</span><div><strong>${escapeHtml(m.name)}</strong><small>${item.case_id}</small></div></div></td>
      <td>${escapeHtml(m.patient_id)}</td><td>${escapeHtml(m.sex)} / ${m.age ?? "—"}岁</td>
      <td>${escapeHtml(m.clinical_diagnosis || "—")}</td><td>${escapeHtml(m.start_time || "—")}</td>
      <td><span class="status-pill ${item.active ? "success" : "neutral"}">${item.active ? "在用" : "已停用"}</span></td>
      <td><button class="row-action" data-edit-patient="${item.case_id}">编辑</button></td>
    </tr>`;
  }).join("") || `<tr><td colspan="7" class="empty-state">没有患者记录</td></tr>`;
}

async function selectCase(caseId, destination = "review") {
  state.caseId = caseId;
  state.start = 0;
  state.waveform = state.trend = state.rr = state.hrv = state.events = null;
  await api(`/api/cases/${caseId}/open`, {method: "POST", body: "{}"});
  await loadCase();
  goPage(destination);
}

async function loadCase() {
  if (!state.caseId) return;
  const [caseData, trend] = await Promise.all([
    api(withPhi(`/api/cases/${state.caseId}`)),
    api(`/api/cases/${state.caseId}/trend?bin_seconds=60`),
  ]);
  state.caseData = caseData;
  state.trend = trend;
  state.report = caseData.report_workflow;
  state.reportDirty = false;
  if (state.start === 0 && caseData.calculated.first_beat_time_s > state.duration) {
    state.start = Math.max(0, caseData.calculated.first_beat_time_s - 2);
  }
  const m = caseData.metadata, s = caseData.summary;
  $("#caseHero").classList.remove("empty-case");
  $("#caseHero").innerHTML = `<div><p class="eyebrow">当前病例 · ${caseData.case_id}</p><h1>${escapeHtml(m.name)}　${escapeHtml(m.sex)}　${m.age ?? "—"} 岁</h1><p>${escapeHtml(m.clinical_diagnosis || "未提供临床诊断")} · ${escapeHtml(m.start_time)} · ${escapeHtml(m.duration_text)}</p></div><div class="case-meta-chips"><span>平均心率<strong>${s.avg_hr ?? "—"} bpm</strong></span><span>有效心搏<strong>${fmtNumber(s.total_beats)}</strong></span><span>V / S<strong>${fmtNumber(s.ventricular_beats)} / ${fmtNumber(s.supraventricular_beats)}</strong></span><span>最长 RR<strong>${s.longest_rr_s ?? "—"} s</strong></span></div>`;
  $("#trendCaseLabel").textContent = `${caseData.case_id} · ${m.name} · ${m.duration_text}`;
  $("#eventCaseLabel").textContent = `${caseData.case_id} · ${m.name}`;
  $("#reportCaseLabel").textContent = `${caseData.case_id} · ${m.name} · ${m.start_time}`;
  const duration = caseData.technical.duration_seconds_raw;
  $("#timeSlider").max = Math.max(0, Math.floor(duration - state.duration));
  $("#timeSlider").value = state.start;
  renderOverview();
  renderReport();
  if (state.currentPage === "review") await loadWaveform();
}

function goPage(name) {
  const needsCase = ["review", "trends", "events", "report"].includes(name);
  if (needsCase && !state.caseId) {
    toast("请先从工作列表选择病例", "error");
    name = "dashboard";
  }
  state.currentPage = name;
  $$(".page").forEach(page => page.classList.toggle("active", page.id === `page-${name}`));
  $$(".nav-item").forEach(item => item.classList.toggle("active", item.dataset.page === name));
  window.scrollTo({top: 0, behavior: "instant"});
  if (name === "review") loadWaveform().catch(handleError);
  if (name === "trends") loadTrends().catch(handleError);
  if (name === "events") loadEvents().catch(handleError);
  if (name === "report") renderReport();
  if (name === "audit") loadAudit().catch(handleError);
  if (name === "settings") loadSettings().catch(handleError);
}

async function loadWaveform() {
  if (!state.caseId) return;
  const params = new URLSearchParams({
    start: state.start.toFixed(3), duration: state.duration, leads: state.leads.join(","),
    max_points: 5000, filter: state.filter,
  });
  $("#waveMeta").textContent = "正在读取窗口…";
  const data = await api(`/api/cases/${state.caseId}/waveform?${params}`);
  state.waveform = data;
  state.start = data.start_s;
  $("#timeSlider").value = Math.round(state.start);
  $("#cursorTimeLabel").textContent = `${formatElapsed(state.start)}–${formatElapsed(state.start + data.duration_s)}`;
  $("#waveMeta").textContent = `${data.sample_rate_hz} Hz · ${data.filter} · ${formatElapsed(data.start_s)}`;
  $("#calibrationNote").textContent = data.calibration_note;
  renderWaveform();
  renderVisibleEvents();
  renderAnnotations(data.annotations || state.caseData?.annotations || []);
  renderOverview();
}

function canvasContext(canvas, height = null) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const width = Math.max(300, canvas.parentElement.clientWidth - (canvas.id === "waveformCanvas" ? 0 : 2));
  const cssHeight = height || Number(canvas.getAttribute("height")) || 200;
  canvas.style.width = `${width}px`;
  canvas.style.height = `${cssHeight}px`;
  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(cssHeight * dpr);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return {ctx, width, height: cssHeight};
}

function renderWaveform() {
  if (!state.waveform) return;
  const canvas = $("#waveformCanvas");
  const leadNames = Object.keys(state.waveform.leads);
  const height = Math.max(500, leadNames.length * 82);
  const {ctx, width, height: h} = canvasContext(canvas, height);
  ctx.fillStyle = "#fffefd";
  ctx.fillRect(0, 0, width, h);
  const leadHeight = h / leadNames.length;
  const duration = state.waveform.duration_s;
  const smallX = width * 0.04 / duration;
  const smallY = Math.max(7, leadHeight / 10);
  ctx.lineWidth = 1;
  for (let x = 0, i = 0; x <= width; x += smallX, i++) {
    if (smallX < 3 && i % 5) continue;
    ctx.strokeStyle = i % 5 === 0 ? "rgba(232,130,116,.34)" : "rgba(244,181,170,.24)";
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
  }
  for (let y = 0, i = 0; y <= h; y += smallY, i++) {
    ctx.strokeStyle = i % 5 === 0 ? "rgba(232,130,116,.34)" : "rgba(244,181,170,.24)";
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke();
  }
  const amplitudeScale = (leadHeight * 0.31 / 1000) * (state.gain / 10);
  const displayRate = state.waveform.display_sample_rate_hz;
  leadNames.forEach((name, leadIndex) => {
    const values = state.waveform.leads[name];
    const baseline = leadHeight * (leadIndex + 0.53);
    ctx.fillStyle = "#075f70"; ctx.font = `700 12px ${UI_FONT}`; ctx.fillText(name, 8, leadHeight * leadIndex + 18);
    ctx.strokeStyle = "#1f2c32"; ctx.lineWidth = 1.15; ctx.beginPath();
    values.forEach((value, index) => {
      const x = index / Math.max(values.length - 1, 1) * width;
      const y = baseline - Number(value) * amplitudeScale;
      if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.strokeStyle = "#087777"; ctx.lineWidth = 1.4;
    const pulseX = 20, pulseBase = baseline + leadHeight * .27, pulseHeight = amplitudeScale * 1000;
    ctx.beginPath(); ctx.moveTo(pulseX, pulseBase); ctx.lineTo(pulseX + 5, pulseBase); ctx.lineTo(pulseX + 5, pulseBase - pulseHeight); ctx.lineTo(pulseX + 20, pulseBase - pulseHeight); ctx.lineTo(pulseX + 20, pulseBase); ctx.lineTo(pulseX + 27, pulseBase); ctx.stroke();
    if (leadIndex < leadNames.length - 1) {
      ctx.strokeStyle = "rgba(78,98,109,.18)"; ctx.beginPath(); ctx.moveTo(0, leadHeight * (leadIndex + 1)); ctx.lineTo(width, leadHeight * (leadIndex + 1)); ctx.stroke();
    }
  });
  const markerColors = {1: "#168ba0", 2: "#7d55a7", 3: "#c94d46", 34: "#7b858a"};
  (state.waveform.beats || []).forEach(beat => {
    const x = (beat.time_s - state.waveform.start_s) / duration * width;
    if (x < 0 || x > width) return;
    ctx.strokeStyle = markerColors[beat.group] || "#777";
    ctx.lineWidth = beat.group === 1 ? .6 : 1.25;
    ctx.globalAlpha = beat.group === 1 ? .28 : .68;
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
    ctx.globalAlpha = 1;
    ctx.fillStyle = markerColors[beat.group] || "#777"; ctx.font = "700 9px sans-serif";
    ctx.fillText(beat.label, Math.min(x + 2, width - 12), 11);
  });
  (state.waveform.annotations || []).forEach(annotation => {
    const time = annotation.sample_index / 200;
    const x = (time - state.waveform.start_s) / duration * width;
    ctx.fillStyle = "rgba(238,153,44,.18)"; ctx.fillRect(x - 5, 0, 10, h);
    ctx.fillStyle = "#a45e12"; ctx.font = `700 9px ${UI_FONT}`; ctx.fillText("人工", Math.min(x + 3, width - 26), h - 8);
  });
  canvas.dataset.displayRate = displayRate;
}

function renderOverview() {
  if (!state.trend || !state.caseData) return;
  const {ctx, width, height} = canvasContext($("#overviewCanvas"), 88);
  const margin = {l: 26, r: 9, t: 7, b: 15};
  const w = width - margin.l - margin.r, h = height - margin.t - margin.b;
  ctx.clearRect(0, 0, width, height); ctx.fillStyle = "#fbfdfd"; ctx.fillRect(0, 0, width, height);
  [50,100,150].forEach(value => {
    const y = margin.t + h - value / 180 * h;
    ctx.strokeStyle = "#e7edef"; ctx.beginPath(); ctx.moveTo(margin.l, y); ctx.lineTo(width - margin.r, y); ctx.stroke();
    ctx.fillStyle = "#82919a"; ctx.font = "8px sans-serif"; ctx.fillText(value, 2, y + 3);
  });
  const total = state.caseData.technical.duration_seconds_raw;
  ctx.strokeStyle = "#177ab8"; ctx.lineWidth = 1.25; ctx.beginPath();
  state.trend.points.forEach((point, index) => {
    const x = margin.l + point.time_s / total * w;
    const y = margin.t + h - Math.min(point.hr, 180) / 180 * h;
    index ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  }); ctx.stroke();
  const x1 = margin.l + state.start / total * w;
  const x2 = margin.l + (state.start + state.duration) / total * w;
  ctx.fillStyle = "rgba(11,146,144,.16)"; ctx.fillRect(x1, margin.t, Math.max(3, x2 - x1), h);
  ctx.strokeStyle = "#0b9290"; ctx.strokeRect(x1, margin.t, Math.max(3, x2 - x1), h);
  ctx.fillStyle = "#7a8a93"; ctx.font = "8px sans-serif";
  [0,.25,.5,.75,1].forEach(part => ctx.fillText(formatElapsed(total * part), margin.l + w * part - 12, height - 3));
}

function renderVisibleEvents() {
  const beats = state.waveform?.beats || [];
  $("#visibleBeatCount").textContent = `${beats.length} 搏`;
  const abnormal = beats.filter(item => item.group !== 1);
  $("#visibleEventList").classList.toggle("empty-state", !abnormal.length);
  $("#visibleEventList").innerHTML = abnormal.length ? abnormal.slice(0, 50).map(item => `<div class="mini-event" data-jump-time="${item.time_s}"><span class="event-marker ${item.label}"></span><div><strong>${escapeHtml(item.label === "噪声" ? "噪声 / 待确认" : `${item.label} 候选心搏`)}</strong><small>${formatElapsed(item.time_s)} · RR ${item.rr_ms} ms · ${item.hr ?? "—"} bpm</small></div></div>`).join("") : "当前窗口无异常候选";
}

function renderAnnotations(items) {
  const box = $("#annotationList");
  box.classList.toggle("empty-state", !items.length);
  box.innerHTML = items.length ? items.map(item => `<article class="annotation-item"><header><strong>${escapeHtml(item.label)}</strong><button data-delete-annotation="${item.id}">删除</button></header><p>${formatElapsed(item.sample_index / 200)} · ${escapeHtml(item.lead || "全部")} · ${escapeHtml(item.note || "无备注")}</p><small>${escapeHtml(item.created_by)} · ${escapeHtml(item.created_at)}</small></article>`).join("") : "暂无人工标注";
}

async function loadTrends() {
  if (!state.caseId) return;
  if (!state.trend) state.trend = await api(`/api/cases/${state.caseId}/trend?bin_seconds=60`);
  if (!state.rr || !state.hrv) [state.rr, state.hrv] = await Promise.all([api(`/api/cases/${state.caseId}/rr-visuals`), api(`/api/cases/${state.caseId}/hrv`)]);
  renderTrendMetrics(); renderTrendChart(); renderHistogram(); renderPoincare(); renderHrv();
}

function renderTrendMetrics() {
  const source = state.caseData.summary, calc = state.caseData.calculated;
  const cells = [
    ["有效心搏", fmtNumber(calc.valid_beats), `源报告 ${fmtNumber(source.total_beats)}`],
    ["平均心率", `${source.avg_hr} bpm`, `重算 ${calc.avg_hr_from_rr} bpm`],
    ["最慢 / 最快", `${source.min_hr} / ${source.max_hr}`, "源报告分钟统计"],
    ["最长 RR", `${source.longest_rr_s} s`, `全部记录最大 ${(calc.longest_rr_ms / 1000).toFixed(3)} s`],
  ];
  $("#trendMetrics").innerHTML = cells.map(([label,value,note], index) => `<article class="metric-card"><div class="metric-icon ${["teal","blue","violet","amber"][index]}">${label.slice(0,1)}</div><div><span>${label}</span><strong>${value}</strong><small>${note}</small></div></article>`).join("");
}

function drawAxes(ctx, width, height, margin, yTicks, xLabels = []) {
  const w = width - margin.l - margin.r, h = height - margin.t - margin.b;
  ctx.font = `9px ${UI_FONT}`; ctx.fillStyle = "#71828c"; ctx.strokeStyle = "#e4eaed"; ctx.lineWidth = 1;
  yTicks.forEach(tick => {const y = margin.t + h * (1 - tick.pos); ctx.beginPath();ctx.moveTo(margin.l,y);ctx.lineTo(width-margin.r,y);ctx.stroke();ctx.fillText(tick.label,3,y+3);});
  xLabels.forEach(tick => ctx.fillText(tick.label, margin.l + w * tick.pos - 10, height - 5));
  return {w,h};
}

function renderTrendChart() {
  const {ctx,width,height} = canvasContext($("#trendCanvas"),250), m={l:38,r:15,t:14,b:26};
  ctx.clearRect(0,0,width,height); const {w,h}=drawAxes(ctx,width,height,m,[0,50,100,150,200].map(v=>({pos:v/200,label:v})),[{pos:0,label:"D1 00h"},{pos:.25,label:"D1 06h"},{pos:.5,label:"D1 12h"},{pos:.75,label:"D1 18h"},{pos:1,label:"D2"}]);
  const total=state.caseData.technical.duration_seconds_raw; const gradient=ctx.createLinearGradient(0,m.t,0,m.t+h); gradient.addColorStop(0,"rgba(23,122,184,.22)");gradient.addColorStop(1,"rgba(23,122,184,0)");
  ctx.beginPath(); state.trend.points.forEach((p,i)=>{const x=m.l+p.time_s/total*w,y=m.t+h-Math.min(p.hr,200)/200*h;i?ctx.lineTo(x,y):ctx.moveTo(x,y)}); ctx.lineTo(m.l+w,m.t+h);ctx.lineTo(m.l,m.t+h);ctx.closePath();ctx.fillStyle=gradient;ctx.fill();
  ctx.beginPath(); state.trend.points.forEach((p,i)=>{const x=m.l+p.time_s/total*w,y=m.t+h-Math.min(p.hr,200)/200*h;i?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.strokeStyle="#197fbd";ctx.lineWidth=1.4;ctx.stroke();
}

function renderHistogram() {
  const {ctx,width,height}=canvasContext($("#histogramCanvas"),260),m={l:40,r:10,t:15,b:27};ctx.clearRect(0,0,width,height);
  const data=state.rr.histogram,max=Math.max(...data.map(x=>x.count),1);const {w,h}=drawAxes(ctx,width,height,m,[0,.5,1].map(p=>({pos:p,label:Math.round(max*p)})),[{pos:0,label:"300"},{pos:.5,label:"1150"},{pos:1,label:"2000 ms"}]);
  const bar=w/data.length;data.forEach((item,i)=>{const bh=item.count/max*h;ctx.fillStyle=i%2?"#42b7b1":"#239e9a";ctx.fillRect(m.l+i*bar+1,m.t+h-bh,Math.max(1,bar-2),bh)});
}

function renderPoincare() {
  const {ctx,width,height}=canvasContext($("#poincareCanvas"),260),m={l:38,r:12,t:15,b:27};ctx.clearRect(0,0,width,height);const {w,h}=drawAxes(ctx,width,height,m,[0,.5,1].map(p=>({pos:p,label:Math.round(300+1700*p)})),[{pos:0,label:"300"},{pos:.5,label:"1150"},{pos:1,label:"2000 ms"}]);
  ctx.strokeStyle="#d8e1e5";ctx.beginPath();ctx.moveTo(m.l,m.t+h);ctx.lineTo(m.l+w,m.t);ctx.stroke();ctx.fillStyle="rgba(13,119,119,.25)";
  state.rr.poincare.forEach(([xv,yv])=>{const x=m.l+(xv-300)/1700*w,y=m.t+h-(yv-300)/1700*h;if(x>=m.l&&x<=m.l+w&&y>=m.t&&y<=m.t+h)ctx.fillRect(x,y,1.5,1.5)});
}

function renderHrv() {
  const source=state.hrv.source,calc=state.hrv.calculated;
  const values=[["Mean NN",null,calc.mean_nn_ms],["SDNN",source.sdnn_ms,calc.sdnn_ms],["SDANN",source.sdann_ms,calc.sdann_ms],["SDNN index",source.sdnn_index_ms,calc.sdnn_index_ms],["rMSSD",source.rmssd_ms,calc.rmssd_ms],["pNN50",source.pnn50_pct,calc.pnn50_pct],["三角指数",source.triangular_index,calc.triangular_index]];
  $("#hrvTable").innerHTML=values.map(([label,a,b])=>`<div class="compare-cell"><span>${label}</span><strong>${b ?? "—"}${label==="pNN50"?"%":label==="三角指数"?"":" ms"}</strong><small>源报告 ${a ?? "—"}</small></div>`).join("");
}

async function loadEvents(type = state.eventType) {
  if (!state.caseId) return;
  state.eventType=type;
  $$("[data-event-type]").forEach(button=>button.classList.toggle("active",button.dataset.eventType===type));
  const p=new URLSearchParams({type,limit:500,brady:$("#bradyThreshold").value,tachy:$("#tachyThreshold").value,pause:$("#pauseThreshold").value});
  state.events=await api(`/api/cases/${state.caseId}/events?${p}`);renderEvents();
}

function renderEvents() {
  const labels={V:"室性候选",S:"室上性候选",pause:"长 RR",tachy:"过速候选",brady:"过缓候选",noise:"噪声"};
  $("#eventSummary").innerHTML=Object.entries(labels).map(([key,label])=>`<article class="event-summary-card"><span>${label}</span><strong>${fmtNumber(state.events.summary[key]||0)}</strong></article>`).join("");
  $("#eventTotal").textContent=`显示 ${state.events.items.length} / ${fmtNumber(state.events.total)}`;
  $("#eventTableBody").innerHTML=state.events.items.map(item=>`<tr><td>${formatElapsed(item.time_s)}</td><td><span class="severity-dot ${item.severity}"></span>${escapeHtml(item.label)}</td><td>${item.hr??"—"} bpm / ${item.rr_ms} ms</td><td>${item.group}</td><td><span class="status-pill warning">${item.review_status}</span></td><td><button class="row-action" data-jump-time="${item.time_s}">查看波形</button></td></tr>`).join("")||`<tr><td colspan="6" class="empty-state">当前筛选没有候选事件</td></tr>`;
}

function renderReport() {
  if (!state.caseData || !state.report) return;
  const source=state.caseData.summary,calc=state.caseData.calculated;
  $("#reportStatus").className=`status-pill ${state.report.status==="reviewed"?"success":state.report.status==="returned"?"danger":"warning"}`;
  $("#reportStatus").textContent=STATUS_TEXT[state.report.status]||state.report.status;
  $("#reportVersion").textContent=`v${state.report.version}`;
  $("#conclusionEditor").value=state.report.conclusion||""; updateConclusionCount();
  $("#reportSaveState").textContent=state.report.updated_at?`上次保存 ${state.report.updated_at}`:"源报告导入，尚未编辑";
  const stats=[["有效心搏",fmtNumber(source.total_beats),`重算 ${fmtNumber(calc.valid_beats)}`],["平均心率",`${source.avg_hr} bpm`,`RR重算 ${calc.avg_hr_from_rr} bpm`],["最长 RR",`${source.longest_rr_s} s`,`全部记录 ${(calc.longest_rr_ms/1000).toFixed(3)} s`],["室性心搏",fmtNumber(source.ventricular_beats),`源分组3：${fmtNumber(calc.group_counts["3"]||0)}`],["室上性心搏",fmtNumber(source.supraventricular_beats),`源分组2：${fmtNumber(calc.group_counts["2"]||0)}`],["伪差 / 排除",fmtNumber(calc.group_counts["34"]||0),"不计入有效心搏"]];
  $("#reportStats").innerHTML=stats.map(([label,value,note])=>`<div class="report-stat"><span>${label}</span><strong>${value}</strong><small>${note}</small></div>`).join("");
  const select=$("#reportPageSelect");select.innerHTML=Array.from({length:state.caseData.technical.report_pages},(_,i)=>`<option value="${i}">第 ${i+1} 页</option>`).join("");
  select.value="0"; showReportPage(0);
}

function showReportPage(index) {
  const image=$("#sourceReportImage"),privacy=$("#sourceReportPrivacy");
  if(!state.includePhi){image.hidden=true;image.removeAttribute("src");image.dataset.url="";privacy.hidden=false;return;}
  const url=state.caseData?.report_image_urls?.[index];if(!url)return;privacy.hidden=true;image.hidden=false;image.src=url;image.dataset.url=url;
}

function updateConclusionCount() {const value=$("#conclusionEditor").value;$("#conclusionCount").textContent=`${value.length} / 12000`;}

async function saveReport(status="draft") {
  if (!state.caseId) return;
  if(status==="reviewed"&&state.reportDirty){await saveReport("draft");}
  const conclusion=$("#conclusionEditor").value;
  const saved=await api(`/api/cases/${state.caseId}/report`,{method:"PUT",body:JSON.stringify({conclusion,status})});
  state.report=saved;state.caseData.report_workflow=saved;state.reportDirty=false;renderReport();
  toast(status==="reviewed"?"报告已标记为审核通过":status==="returned"?"报告已驳回并保留版本":"草稿已保存");
}

async function loadAudit() {
  const data=await api("/api/audit?limit=300");
  $("#auditBody").innerHTML=data.items.map(item=>`<tr><td>${escapeHtml(item.created_at)}</td><td>${escapeHtml(item.actor)}</td><td>${escapeHtml(item.case_id||"—")}</td><td>${escapeHtml(ACTION_TEXT[item.action]||item.action)}</td><td>${escapeHtml(item.detail||"—")}</td></tr>`).join("")||`<tr><td colspan="5" class="empty-state">尚无审计记录</td></tr>`;
}

async function loadSettings() {
  if(!state.settings)state.settings=await api("/api/settings");
  $("#settingsDataRoot").textContent=state.settings.data_root;$("#settingsCaseCount").textContent=`${state.settings.case_count} 例`;$("#settingsIntegrity").textContent=state.settings.integrity_manifest.available?`SHA-256 · ${state.settings.integrity_manifest.case_count} 例`:"未生成";
  const platform=state.settings.platform||{};
  applyPlatformIdentity(platform.name||"");
  $("#settingsStorageRoot").textContent=platform.storage_root||"—";
  $("#settingsPlatform").textContent=[platform.name,platform.release].filter(Boolean).join(" ")||"—";
  $("#settingsArchitecture").textContent=platform.machine||"—";
  $("#settingsConfigPath").textContent=platform.config_path||"—";
  $("#setupConfigPath").textContent=platform.config_path||"CardioInsightHolter/config.json";
}

function openAnnotation(time = state.start + state.duration/2) {
  if(!state.caseId)return;const sample=Math.round(time*200);$("#annotationSample").value=sample;$("#annotationTime").value=formatElapsed(time);$("#annotationLead").value=state.leads[0]||"II";$("#annotationDialog").showModal();
}

async function createAnnotation() {
  const payload={sample_index:Number($("#annotationSample").value),lead:$("#annotationLead").value,category:$("#annotationCategory").value,label:$("#annotationLabel").value,note:$("#annotationNote").value};
  await api(`/api/cases/${state.caseId}/annotations`,{method:"POST",body:JSON.stringify(payload)});$("#annotationDialog").close();toast("人工标注已保存");await loadCase();await loadWaveform();
}

function openPatientEditor(caseId) {
  if(!state.includePhi){toast("为避免在掩码上误编辑，请先点击右上角显示身份信息", "error",4200);return;}
  const item=state.cases.find(x=>x.case_id===caseId);if(!item)return;const m=item.metadata;
  $("#patientCaseId").value=caseId;$("#patientName").value=m.name||"";$("#patientId").value=m.patient_id||"";$("#patientSex").value=m.sex||"未知";$("#patientAge").value=m.age??"";$("#patientBed").value=m.bed||"";$("#patientActive").value=String(item.active);$("#patientDiagnosis").value=m.clinical_diagnosis||"";$("#patientDialog").showModal();
}

async function savePatient() {
  const id=$("#patientCaseId").value,payload={name:$("#patientName").value,patient_id:$("#patientId").value,sex:$("#patientSex").value,age:Number($("#patientAge").value)||null,bed:$("#patientBed").value,active:$("#patientActive").value==="true",clinical_diagnosis:$("#patientDiagnosis").value};
  await api(`/api/cases/${id}/patient`,{method:"PATCH",body:JSON.stringify(payload)});$("#patientDialog").close();toast("患者本地覆盖已保存");await loadDashboard();if(state.caseId===id)await loadCase();
}

function jumpTo(time) {if(!state.caseId)return;state.start=Math.max(0,Math.min(Number(time)-state.duration*.35,state.caseData.technical.duration_seconds_raw-state.duration));goPage("review");loadWaveform().catch(handleError);}

function bindCanvasInteraction() {
  const canvas=$("#waveformCanvas"),scroller=$("#waveformScroller"),tooltip=$("#waveTooltip");let down=null;
  canvas.addEventListener("pointerdown",event=>{down={x:event.clientX,start:state.start};scroller.classList.add("dragging");canvas.setPointerCapture(event.pointerId)});
  canvas.addEventListener("pointerup",event=>{if(!down)return;const rect=canvas.getBoundingClientRect(),dx=event.clientX-down.x;if(Math.abs(dx)>6){state.start=Math.max(0,Math.min(down.start-dx/rect.width*state.duration,state.caseData.technical.duration_seconds_raw-state.duration));loadWaveform().catch(handleError)}down=null;scroller.classList.remove("dragging")});
  canvas.addEventListener("pointermove",event=>{if(!state.waveform)return;const rect=canvas.getBoundingClientRect(),fraction=Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width)),time=state.waveform.start_s+fraction*state.waveform.duration_s;tooltip.hidden=false;tooltip.style.left=`${event.clientX-rect.left+12}px`;tooltip.style.top=`${Math.max(8,event.clientY-rect.top-28+scroller.scrollTop)}px`;tooltip.textContent=formatElapsed(time)});
  canvas.addEventListener("pointerleave",()=>tooltip.hidden=true);
  canvas.addEventListener("dblclick",event=>{const rect=canvas.getBoundingClientRect(),time=state.waveform.start_s+(event.clientX-rect.left)/rect.width*state.waveform.duration_s;openAnnotation(time)});
  canvas.addEventListener("wheel",event=>{if(!state.caseId)return;event.preventDefault();state.start=Math.max(0,Math.min(state.start+Math.sign(event.deltaY)*state.duration,state.caseData.technical.duration_seconds_raw-state.duration));loadWaveform().catch(handleError)},{passive:false});
  $("#overviewCanvas").addEventListener("click",event=>{if(!state.caseData)return;const rect=event.currentTarget.getBoundingClientRect(),time=(event.clientX-rect.left)/rect.width*state.caseData.technical.duration_seconds_raw;jumpTo(time)});
  $("#trendCanvas").addEventListener("click",event=>{if(!state.caseData)return;const rect=event.currentTarget.getBoundingClientRect(),time=(event.clientX-rect.left)/rect.width*state.caseData.technical.duration_seconds_raw;jumpTo(time)});
}

function handleError(error) {console.error(error);toast(error.message||"操作失败","error",4500);}

function bindEvents() {
  $$(".nav-item").forEach(button=>button.addEventListener("click",()=>goPage(button.dataset.page)));
  $$('[data-go]').forEach(button=>button.addEventListener("click",()=>goPage(button.dataset.go)));
  $("#dismissSafety").addEventListener("click",()=>$(".safety-banner").classList.add("hidden"));
  $("#globalSearch").addEventListener("input",event=>{state.search=event.target.value;renderWorklist();renderPatients()});
  $("#worklistFilter").addEventListener("change",renderWorklist);$("#showDeleted").addEventListener("change",renderPatients);
  document.addEventListener("click",event=>{
    const open=event.target.closest("[data-open-case]");if(open)selectCase(open.dataset.openCase).catch(handleError);
    const edit=event.target.closest("[data-edit-patient]");if(edit)openPatientEditor(edit.dataset.editPatient);
    const jump=event.target.closest("[data-jump-time]");if(jump)jumpTo(jump.dataset.jumpTime);
    const del=event.target.closest("[data-delete-annotation]");if(del&&confirm("删除这条人工标注？"))api(`/api/annotations/${del.dataset.deleteAnnotation}`,{method:"DELETE"}).then(()=>loadWaveform()).catch(handleError);
  });
  $("#openFirstCase").addEventListener("click",()=>{const first=filteredCases()[0];if(first)selectCase(first.case_id).catch(handleError)});
  $("#privacyToggle").addEventListener("click",async()=>{try{const enabling=!state.includePhi;if(enabling&&!confirm("身份信息包含真实健康数据。仅应在授权环境中查看，是否继续？"))return;await api("/api/privacy/view",{method:"POST",body:JSON.stringify({enabled:enabling})});state.includePhi=enabling;$("#privacyToggle").classList.toggle("visible",state.includePhi);$("#privacyToggle").setAttribute("aria-pressed",String(state.includePhi));$("#privacyText").textContent=state.includePhi?"身份信息正在显示":"身份信息已遮蔽";await loadDashboard();if(state.caseId)await loadCase()}catch(error){handleError(error)}});
  $$('[data-lead-preset]').forEach(button=>button.addEventListener("click",()=>{state.leadPreset=Number(button.dataset.leadPreset);state.leads=LEAD_PRESETS[state.leadPreset];$$('[data-lead-preset]').forEach(b=>b.classList.toggle("active",b===button));loadWaveform().catch(handleError)}));
  $("#durationSelect").addEventListener("change",event=>{state.duration=Number(event.target.value);$("#timeSlider").max=Math.max(0,state.caseData.technical.duration_seconds_raw-state.duration);loadWaveform().catch(handleError)});
  $("#gainSelect").addEventListener("change",event=>{state.gain=Number(event.target.value);renderWaveform()});
  $("#filterSelect").addEventListener("change",event=>{state.filter=event.target.value;loadWaveform().catch(handleError)});
  $("#prevWindow").addEventListener("click",()=>jumpTo(state.start-state.duration*.65));$("#nextWindow").addEventListener("click",()=>jumpTo(state.start+state.duration*1.35));
  let sliderTimer;$("#timeSlider").addEventListener("input",event=>{clearTimeout(sliderTimer);state.start=Number(event.target.value);renderOverview();sliderTimer=setTimeout(()=>loadWaveform().catch(handleError),120)});
  $("#addAnnotation").addEventListener("click",()=>openAnnotation());$("#confirmAnnotation").addEventListener("click",event=>{event.preventDefault();createAnnotation().catch(handleError)});
  $("#confirmPatient").addEventListener("click",event=>{event.preventDefault();savePatient().catch(handleError)});
  $$('[data-event-type]').forEach(button=>button.addEventListener("click",()=>loadEvents(button.dataset.eventType).catch(handleError)));$("#refreshEvents").addEventListener("click",()=>loadEvents().catch(handleError));
  $("#conclusionEditor").addEventListener("input",()=>{state.reportDirty=true;$("#reportSaveState").textContent="有未保存修改";updateConclusionCount()});
  $("#saveReport").addEventListener("click",()=>saveReport("draft").catch(handleError));$("#approveReport").addEventListener("click",()=>saveReport("reviewed").catch(handleError));$("#returnReport").addEventListener("click",()=>saveReport("returned").catch(handleError));
  $("#downloadReport").addEventListener("click",()=>{if(state.caseId)window.location.href=withPhi(`/api/cases/${state.caseId}/report.pdf`)});
  $("#reportPageSelect").addEventListener("change",event=>showReportPage(Number(event.target.value)));$("#openReportImage").addEventListener("click",()=>{const url=$("#sourceReportImage").dataset.url;if(url)window.open(url,"_blank","noopener");else toast("请先使用右上角隐私开关显示身份信息","error")});
  $("#refreshAudit").addEventListener("click",()=>loadAudit().catch(handleError));
  document.addEventListener("keydown",event=>{if(["INPUT","TEXTAREA","SELECT"].includes(document.activeElement.tagName))return;if(event.key==="ArrowLeft"&&state.currentPage==="review"){event.preventDefault();jumpTo(state.start-state.duration*.65)}if(event.key==="ArrowRight"&&state.currentPage==="review"){event.preventDefault();jumpTo(state.start+state.duration*1.35)}if(event.key.toLowerCase()==="a"&&state.currentPage==="review")openAnnotation();if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==="k"){event.preventDefault();$("#globalSearch").focus()}});
  bindCanvasInteraction();
  let resizeTimer;window.addEventListener("resize",()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{if(state.currentPage==="review"){renderOverview();renderWaveform()}if(state.currentPage==="trends"){renderTrendChart();renderHistogram();renderPoincare()}},120)});
}

async function init() {
  bindEvents();
  try {
    const platformName=navigator.userAgentData?.platform||navigator.platform||"";
    applyPlatformIdentity(platformName);
    const health=await api("/api/health");
    await Promise.all([loadDashboard(),loadSettings()]);
    $("#dataSetupPanel").hidden=health.data_root_found;
    $("#openFirstCase").disabled=!health.data_root_found;
    if(!health.data_root_found)toast("尚未连接病例数据，请按工作台提示设置本地数据目录","error",5200);
  } catch(error) {handleError(error);}
  finally {setTimeout(()=>$("#loading").classList.add("hidden"),180);}
}

document.addEventListener("DOMContentLoaded",init);
