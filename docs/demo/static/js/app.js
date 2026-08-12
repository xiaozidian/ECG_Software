"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const ALL_LEADS = ["I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6"];
const LEAD_PRESETS = {
  3: ["II", "V1", "V5"],
  6: ["I", "II", "III", "aVR", "V1", "V5"],
  12: ALL_LEADS,
};
const TIME_ZOOM_STEPS = [1, 2, 5, 10, 20, 30, 60, 120];
const GAIN_ZOOM_STEPS = [5, 10, 20];
const SCATTER_MODES = {rr:"R-R散点图",n:"N散点图",nn:"N-N散点图",s:"S散点图",v:"V散点图",hour:"小时散点图"};
const BEAT_COLORS = {1:"#168ba0",2:"#7464c8",3:"#c9544c",34:"#7b858a"};
const SCATTER_STRIP_HEIGHT = 156;
const SCATTER_STRIP_CACHE_LIMIT = 240;
const STATUS_TEXT = {draft: "未审核", reviewed: "已审核", returned: "已驳回"};
const UI_FONT = '"SF Pro Text", "PingFang SC", "Microsoft YaHei UI", sans-serif';
const APP_MODE = Object.freeze({
  demoReadonly: document.documentElement.dataset.demoReadonly === "true",
  allowPhi: document.documentElement.dataset.allowPhi === "true",
});
const ACTION_TEXT = {
  "privacy.phi_view": "查看身份信息", "case.open": "打开病例",
  "annotation.create": "创建标注", "annotation.delete": "删除标注",
  "patient.update": "修改患者", "report.draft": "保存报告草稿",
  "report.reviewed": "审核报告", "report.returned": "驳回报告",
  "report.export_pdf": "导出 PDF",
};

const state = {
  includePhi: false,
  demoReadonly: APP_MODE.demoReadonly,
  allowPhi: APP_MODE.allowPhi,
  cases: [],
  dashboard: null,
  settings: null,
  caseId: null,
  caseData: null,
  caseRequestId: 0,
  start: 0,
  duration: 10,
  gain: 10,
  filter: "display",
  leadPreset: 3,
  leads: LEAD_PRESETS[3],
  trend: null,
  waveform: null,
  waveformRequestId: 0,
  trendsRequestId: 0,
  eventsRequestId: 0,
  scatterMode: "rr",
  scatterCache: {},
  scatterData: null,
  scatterRequestId: 0,
  scatterSelectionRequestId: 0,
  scatterStripGeneration: 0,
  scatterProjectedPoints: [],
  scatterLasso: [],
  scatterSelectionPolygon: null,
  scatterSelectedSamples: [],
  scatterSelectedSet: new Set(),
  scatterStripCache: new Map(),
  scatterStripPending: new Set(),
  scatterStripFailed: new Set(),
  scatterStripQueue: [],
  scatterStripActive: 0,
  scatterStripControllers: new Set(),
  scatterFocusedSample: null,
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

function formatElapsedPrecise(seconds) {
  const totalMilliseconds = Math.max(0, Math.round((Number(seconds) || 0) * 1000));
  const day = Math.floor(totalMilliseconds / 86400000) + 1;
  const withinDay = totalMilliseconds % 86400000;
  const hh = String(Math.floor(withinDay / 3600000)).padStart(2, "0");
  const mm = String(Math.floor((withinDay % 3600000) / 60000)).padStart(2, "0");
  const ss = String(Math.floor((withinDay % 60000) / 1000)).padStart(2, "0");
  const milliseconds = String(withinDay % 1000).padStart(3, "0");
  return `D${day} ${hh}:${mm}:${ss}.${milliseconds}`;
}

function applyPlatformIdentity(platformName = "") {
  const isMac = /darwin|mac/i.test(platformName);
  const isWindows = /windows|win32|win64/i.test(platformName);
  const key = isMac ? "mac" : isWindows ? "windows" : "other";
  const label = isMac ? "macOS" : isWindows ? "Windows" : "桌面系统";
  document.documentElement.dataset.platform = key;
  $("#searchShortcut").textContent = isMac ? "⌘ K" : "Ctrl K";
  $("#platformEdition").textContent = `${label} 研究版`;
  if ($("#platformHeading")) $("#platformHeading").textContent = `${label} 运行环境`;
  if ($("#platformIcon")) $("#platformIcon").textContent = isMac ? "⌘" : isWindows ? "⊞" : "◫";
  if ($("#displayOptimization")) $("#displayOptimization").textContent = `${isMac ? "Retina" : "HiDPI"} · 系统字体`;
}

function sourceHint(conclusion) {
  return String(conclusion || "未填写源报告结论").split(/\n/).filter(Boolean).slice(0, 2).join("；");
}

function withPhi(path) {
  const join = path.includes("?") ? "&" : "?";
  return `${path}${join}include_phi=${state.allowPhi && state.includePhi ? 1 : 0}`;
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
      <td>${state.demoReadonly ? '<span class="status-pill neutral">只读</span>' : `<button class="row-action" data-edit-patient="${item.case_id}">编辑</button>`}</td>
    </tr>`;
  }).join("") || `<tr><td colspan="7" class="empty-state">没有患者记录</td></tr>`;
}

async function selectCase(caseId, destination = "review") {
  const requestId=++state.caseRequestId;
  state.caseId = caseId;
  state.caseData = null;
  state.report = null;
  state.start = 0;
  state.waveformRequestId += 1;
  state.trendsRequestId += 1;
  state.eventsRequestId += 1;
  state.scatterRequestId += 1;
  state.scatterSelectionRequestId += 1;
  state.waveform = state.trend = state.rr = state.hrv = state.events = null;
  state.scatterCache = {};
  state.scatterData = null;
  state.scatterMode = "rr";
  clearScatterSelection();
  await api(`/api/cases/${caseId}/open`, {method: "POST", body: "{}"});
  if(requestId!==state.caseRequestId||caseId!==state.caseId)return;
  const loaded=await loadCase(caseId,requestId);
  if(!loaded)return;
  goPage(destination);
}

async function loadCase(caseId=state.caseId, requestId=null) {
  if (!caseId) return false;
  const activeRequestId=requestId??++state.caseRequestId;
  const [caseData, trend] = await Promise.all([
    api(withPhi(`/api/cases/${caseId}`)),
    api(`/api/cases/${caseId}/trend?bin_seconds=60`),
  ]);
  if(activeRequestId!==state.caseRequestId||caseId!==state.caseId)return false;
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
  updateZoomControls();
  renderOverview();
  renderReport();
  if (state.currentPage === "review") await loadWaveform();
  return activeRequestId===state.caseRequestId&&caseId===state.caseId;
}

function goPage(name) {
  if (state.demoReadonly && ["audit", "settings"].includes(name)) name = "dashboard";
  const needsCase = ["review", "trends", "events", "report"].includes(name);
  if (needsCase && !state.caseId) {
    toast("请先从工作列表选择病例", "error");
    name = "dashboard";
  }
  state.currentPage = name;
  $$(".page").forEach(page => page.classList.toggle("active", page.id === `page-${name}`));
  $$(".nav-item").forEach(item => item.classList.toggle("active", item.dataset.page === name));
  window.scrollTo({top: 0, behavior: "instant"});
  if (name === "review") {loadWaveform().catch(handleError);loadScatter().catch(handleError);}
  if (name === "trends") loadTrends().catch(handleError);
  if (name === "events") loadEvents().catch(handleError);
  if (name === "report") renderReport();
  if (name === "audit") loadAudit().catch(handleError);
  if (name === "settings") loadSettings().catch(handleError);
}

async function loadWaveform() {
  if (!state.caseId) return;
  const requestId=++state.waveformRequestId;
  const params = new URLSearchParams({
    start: state.start.toFixed(3), duration: state.duration, leads: state.leads.join(","),
    max_points: 5000, filter: state.filter,
  });
  $("#waveMeta").textContent = "正在读取窗口…";
  const data = await api(`/api/cases/${state.caseId}/waveform?${params}`);
  if(requestId!==state.waveformRequestId)return;
  state.waveform = data;
  state.start = data.start_s;
  updateZoomControls();
  $("#timeSlider").value = Math.round(state.start);
  $("#cursorTimeLabel").textContent = `${formatElapsed(state.start)}–${formatElapsed(state.start + data.duration_s)}`;
  $("#waveMeta").textContent = `${data.sample_rate_hz} Hz · ${data.filter} · ${formatElapsed(data.start_s)}`;
  $("#calibrationNote").textContent = data.calibration_note;
  renderWaveform();
  renderVisibleEvents();
  renderAnnotations(data.annotations || state.caseData?.annotations || []);
  renderOverview();
  syncHourScatter();
}

function canvasContext(canvas, height = null) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const isWaveform = canvas.id === "waveformCanvas";
  let width;
  if (isWaveform) {
    canvas.style.width = "100%";
    width = Math.max(720, Math.floor(canvas.getBoundingClientRect().width));
  } else {
    width = Math.max(300, canvas.parentElement.clientWidth - 2);
    canvas.style.width = `${width}px`;
  }
  const cssHeight = height || Number(canvas.getAttribute("height")) || 200;
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
  (state.waveform.beats || []).forEach(beat => {
    const x = (beat.time_s - state.waveform.start_s) / duration * width;
    if (x < 0 || x > width) return;
    ctx.strokeStyle = BEAT_COLORS[beat.group] || "#777";
    ctx.lineWidth = beat.group === 1 ? .6 : 1.25;
    ctx.globalAlpha = beat.group === 1 ? .28 : .68;
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
    ctx.globalAlpha = 1;
    ctx.fillStyle = BEAT_COLORS[beat.group] || "#777"; ctx.font = "700 9px sans-serif";
    ctx.fillText(beat.label, Math.min(x + 2, width - 12), 11);
  });
  if(state.scatterFocusedSample!==null){
    const focusedTime=state.scatterFocusedSample/200,focusedX=(focusedTime-state.waveform.start_s)/duration*width;
    if(focusedX>=0&&focusedX<=width){ctx.fillStyle="rgba(239,140,33,.18)";ctx.fillRect(focusedX-6,0,12,h);ctx.strokeStyle="#dd7916";ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(focusedX,0);ctx.lineTo(focusedX,h);ctx.stroke();ctx.fillStyle="#a95b0d";ctx.font=`700 10px ${UI_FONT}`;ctx.fillText("圈选",Math.min(focusedX+4,width-30),25);}
  }
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
  box.innerHTML = items.length ? items.map(item => `<article class="annotation-item"><header><strong>${escapeHtml(item.label)}</strong>${state.demoReadonly ? "" : `<button data-delete-annotation="${item.id}">删除</button>`}</header><p>${formatElapsed(item.sample_index / 200)} · ${escapeHtml(item.lead || "全部")} · ${escapeHtml(item.note || "无备注")}</p><small>${escapeHtml(item.created_by)} · ${escapeHtml(item.created_at)}</small></article>`).join("") : "暂无人工标注";
}

function setScatterSelectionEmpty(title, detail) {
  const empty=$("#scatterSelectionEmpty");
  if(!empty)return;
  empty.innerHTML=`<span>◯</span><strong>${escapeHtml(title)}</strong><p>${escapeHtml(detail)}</p>`;
}

function invalidateScatterStripLoads() {
  state.scatterStripGeneration+=1;
  state.scatterStripControllers.forEach(controller=>controller.abort());
  state.scatterStripControllers.clear();
  state.scatterStripQueue=[];
  state.scatterStripActive=0;
  state.scatterStripPending.clear();
}

function clearScatterSelection() {
  invalidateScatterStripLoads();
  state.scatterSelectionRequestId+=1;
  state.scatterLasso=[];
  state.scatterSelectionPolygon=null;
  state.scatterSelectedSamples=[];
  state.scatterSelectedSet=new Set();
  state.scatterStripCache.clear();
  state.scatterStripFailed.clear();
  state.scatterFocusedSample=null;
  const count=$("#scatterSelectionCount"),clear=$("#clearScatterSelection");
  if(count)count.textContent="未圈选";
  if(clear)clear.disabled=true;
  setScatterSelectionEmpty("尚未圈选","在散点图密集区画一个闭合圈，片段会在这里按时间排列。");
  renderScatterSelectionList();
  renderScatter();
  if(state.waveform)renderWaveform();
}

function updateScatterModeButtons() {
  $$('[data-scatter-mode]').forEach(button=>{
    const active=button.dataset.scatterMode===state.scatterMode;
    button.classList.toggle("active",active);
    button.setAttribute("aria-pressed",String(active));
  });
}

function currentScatterHourStart() {return Math.floor(Math.max(0,(Number(state.start)||0)+state.duration*.35)/3600)*3600;}
function scatterCacheKey(mode=state.scatterMode) {return mode==="hour"?`hour:${currentScatterHourStart()}`:mode;}

async function loadScatter(mode=state.scatterMode) {
  if(!state.caseId)return;
  state.scatterMode=SCATTER_MODES[mode]?mode:"rr";
  updateScatterModeButtons();
  const hourStart=currentScatterHourStart(),cacheKey=scatterCacheKey(state.scatterMode),cached=state.scatterCache[cacheKey];
  if(cached){state.scatterData=cached;$("#scatterLoading").hidden=true;initializeScatterRangeInputs(cached.bounds);renderScatter();return;}
  const requestId=++state.scatterRequestId,caseId=state.caseId,currentMode=state.scatterMode;
  $("#scatterLoading").hidden=false;
  try{
    const params=new URLSearchParams({mode:currentMode,max_points:12000});
    if(currentMode==="hour")params.set("hour_start_s",hourStart);
    const data=await api(`/api/cases/${caseId}/scatter?${params}`);
    if(requestId!==state.scatterRequestId||caseId!==state.caseId||currentMode!==state.scatterMode||currentMode==="hour"&&hourStart!==currentScatterHourStart())return;
    state.scatterCache[cacheKey]=data;
    state.scatterData=data;
    initializeScatterRangeInputs(data.bounds);
    renderScatter();
  }finally{if(requestId===state.scatterRequestId&&caseId===state.caseId&&currentMode===state.scatterMode&&!(currentMode==="hour"&&hourStart!==currentScatterHourStart()))$("#scatterLoading").hidden=true;}
}

async function switchScatterMode(mode) {
  if(!SCATTER_MODES[mode]||mode===state.scatterMode&&state.scatterData)return;
  state.scatterRequestId+=1;
  state.scatterMode=mode;
  state.scatterData=state.scatterCache[scatterCacheKey(mode)]||null;
  clearScatterSelection();
  updateScatterModeButtons();
  await loadScatter(mode);
}

function syncHourScatter() {
  if(state.currentPage!=="review"||state.scatterMode!=="hour")return;
  if(Number(state.scatterData?.hour_start_s)===currentScatterHourStart())return;
  state.scatterRequestId+=1;
  state.scatterData=state.scatterCache[scatterCacheKey("hour")]||null;
  clearScatterSelection();
  loadScatter("hour").catch(handleError);
}

function scatterGeometry(width,height) {
  const margin={l:42,r:12,t:16,b:42};
  return {...margin,w:Math.max(1,width-margin.l-margin.r),h:Math.max(1,height-margin.t-margin.b)};
}

function scatterScreenPoint(point,bounds,geometry) {
  const x=geometry.l+(point.x-bounds.x_min)/Math.max(1e-9,bounds.x_max-bounds.x_min)*geometry.w;
  const y=geometry.t+geometry.h-(point.y-bounds.y_min)/Math.max(1e-9,bounds.y_max-bounds.y_min)*geometry.h;
  return {x,y};
}

function scatterDataPoint(point,bounds,geometry) {
  return [
    bounds.x_min+(point.x-geometry.l)/geometry.w*(bounds.x_max-bounds.x_min),
    bounds.y_min+(geometry.t+geometry.h-point.y)/geometry.h*(bounds.y_max-bounds.y_min),
  ];
}

function drawScatterMarker(ctx,point,x,y,selected) {
  const color=BEAT_COLORS[point.group]||"#52666f";
  ctx.fillStyle=color;
  if(point.group===2){ctx.beginPath();ctx.moveTo(x,y-3.2);ctx.lineTo(x-3.2,y+2.8);ctx.lineTo(x+3.2,y+2.8);ctx.closePath();ctx.fill();}
  else if(point.group===3)ctx.fillRect(x-2.7,y-2.7,5.4,5.4);
  else ctx.fillRect(x-1.1,y-1.1,2.2,2.2);
  if(selected){ctx.strokeStyle="#ef8c21";ctx.lineWidth=1.8;ctx.beginPath();ctx.arc(x,y,5.5,0,Math.PI*2);ctx.stroke();}
}

function renderScatter() {
  const canvas=$("#scatterCanvas");
  if(!canvas)return;
  const cssHeight=window.matchMedia("(max-width: 980px)").matches?350:390;
  const {ctx,width,height}=canvasContext(canvas,cssHeight),geometry=scatterGeometry(width,height);
  ctx.clearRect(0,0,width,height);ctx.fillStyle="#f9fbfb";ctx.fillRect(0,0,width,height);
  const data=state.scatterData;
  if(!data){ctx.fillStyle="#87969e";ctx.font=`10px ${UI_FONT}`;ctx.textAlign="center";ctx.fillText(state.caseId?"正在读取散点…":"请选择病例",width/2,height/2);ctx.textAlign="left";return;}
  const bounds=data.bounds;
  ctx.font=`9px ${UI_FONT}`;ctx.lineWidth=1;
  for(let index=0;index<=4;index+=1){
    const fraction=index/4,x=geometry.l+geometry.w*fraction,y=geometry.t+geometry.h*(1-fraction);
    ctx.strokeStyle="#dfe7ea";ctx.beginPath();ctx.moveTo(x,geometry.t);ctx.lineTo(x,geometry.t+geometry.h);ctx.stroke();ctx.beginPath();ctx.moveTo(geometry.l,y);ctx.lineTo(geometry.l+geometry.w,y);ctx.stroke();
    const xv=bounds.x_min+(bounds.x_max-bounds.x_min)*fraction,yv=bounds.y_min+(bounds.y_max-bounds.y_min)*fraction;
    ctx.fillStyle="#75868f";ctx.textAlign="center";ctx.fillText(Math.round(xv),x,height-24);ctx.textAlign="right";ctx.fillText(Math.round(yv),geometry.l-5,y+3);
  }
  ctx.strokeStyle="#647983";ctx.strokeRect(geometry.l,geometry.t,geometry.w,geometry.h);
  ctx.save();ctx.beginPath();ctx.rect(geometry.l,geometry.t,geometry.w,geometry.h);ctx.clip();ctx.strokeStyle="rgba(88,111,121,.35)";ctx.setLineDash([4,4]);ctx.beginPath();ctx.moveTo(geometry.l,geometry.t+geometry.h);ctx.lineTo(geometry.l+geometry.w,geometry.t);ctx.stroke();ctx.restore();ctx.setLineDash([]);
  ctx.fillStyle="#516670";ctx.font=`9px ${UI_FONT}`;ctx.textAlign="center";ctx.fillText(`${data.axis.x_label} (${data.axis.x_unit})`,geometry.l+geometry.w/2,height-6);ctx.save();ctx.translate(11,geometry.t+geometry.h/2);ctx.rotate(-Math.PI/2);ctx.fillText(`${data.axis.y_label} (${data.axis.y_unit})`,0,0);ctx.restore();ctx.textAlign="left";
  state.scatterProjectedPoints=[];
  ctx.save();ctx.beginPath();ctx.rect(geometry.l,geometry.t,geometry.w,geometry.h);ctx.clip();
  for(const point of data.points){
    const projected=scatterScreenPoint(point,bounds,geometry);
    if(projected.x<geometry.l||projected.x>geometry.l+geometry.w||projected.y<geometry.t||projected.y>geometry.t+geometry.h)continue;
    state.scatterProjectedPoints.push({...projected,point});
    drawScatterMarker(ctx,point,projected.x,projected.y,state.scatterSelectedSet.has(point.sample_index));
  }
  const polygon=state.scatterLasso.length?state.scatterLasso:state.scatterSelectionPolygon?.map(([x,y])=>scatterScreenPoint({x,y},bounds,geometry))||[];
  if(polygon.length>=2){ctx.fillStyle="rgba(239,140,33,.12)";ctx.strokeStyle="#e47c13";ctx.lineWidth=2;ctx.setLineDash([5,3]);ctx.beginPath();polygon.forEach((point,index)=>index?ctx.lineTo(point.x,point.y):ctx.moveTo(point.x,point.y));if(state.scatterSelectionPolygon)ctx.closePath();if(state.scatterSelectionPolygon)ctx.fill();ctx.stroke();ctx.setLineDash([]);}
  ctx.restore();
  const pointCount=$("#scatterPointCount");
  const hourLabel=data.mode==="hour"?`${formatElapsed(data.hour_start_s)}–${formatElapsed(data.hour_end_s)} · `:"";
  pointCount.textContent=`${hourLabel}显示 ${fmtNumber(data.returned_count)} / 全部 ${fmtNumber(data.candidate_count)} 点`;
  $("#scatterHelp").textContent=data.sampled?"画圈或键盘范围选择后按完整数据精确计算，不受显示抽样影响":"鼠标画圈或展开键盘范围选择；均按完整数据精确计算";
  canvas.setAttribute("aria-label",`${SCATTER_MODES[data.mode]}；显示 ${data.returned_count} 点，共 ${data.candidate_count} 点；鼠标或触控笔可画圈，键盘用户可使用上方范围选择`);
  if(!data.candidate_count){ctx.fillStyle="#87969e";ctx.font=`10px ${UI_FONT}`;ctx.textAlign="center";ctx.fillText("本病例没有该类候选点",geometry.l+geometry.w/2,geometry.t+geometry.h/2);ctx.textAlign="left";}
}

function pointInPolygon(point,polygon) {
  let inside=false,previous=polygon[polygon.length-1];
  for(const current of polygon){if((previous.y>point.y)!==(current.y>point.y)&&point.x<=(current.x-previous.x)*(point.y-previous.y)/(current.y-previous.y)+previous.x)inside=!inside;previous=current;}
  return inside;
}

function simplifyLasso(points,limit=128) {
  if(points.length<=limit)return points;
  return Array.from({length:limit},(_,index)=>points[Math.round(index*(points.length-1)/(limit-1))]);
}

function initializeScatterRangeInputs(bounds) {
  if(!bounds)return;
  [["#scatterXMin",bounds.x_min,bounds.x_min,bounds.x_max],["#scatterXMax",bounds.x_max,bounds.x_min,bounds.x_max],["#scatterYMin",bounds.y_min,bounds.y_min,bounds.y_max],["#scatterYMax",bounds.y_max,bounds.y_min,bounds.y_max]].forEach(([selector,value,minimum,maximum])=>{
    const input=$(selector);if(!input)return;input.min=String(minimum);input.max=String(maximum);input.value=String(Math.round(value));
  });
}

async function applyScatterSelectionPolygon(polygon) {
  const data=state.scatterData;
  if(!data||polygon.length<3)return;
  invalidateScatterStripLoads();
  state.scatterSelectionRequestId+=1;
  state.scatterSelectionPolygon=polygon;
  state.scatterSelectedSamples=[];state.scatterStripCache.clear();state.scatterStripFailed.clear();state.scatterFocusedSample=null;
  const objectPolygon=polygon.map(([x,y])=>({x,y}));
  state.scatterSelectedSet=new Set(data.points.filter(point=>pointInPolygon({x:point.x,y:point.y},objectPolygon)).map(point=>point.sample_index));
  const requestId=state.scatterSelectionRequestId,caseId=state.caseId,mode=state.scatterMode,hourStart=data.hour_start_s??0;
  $("#scatterSelectionCount").textContent="正在精确圈选…";$("#clearScatterSelection").disabled=false;
  setScatterSelectionEmpty("正在生成片段列表","正在完整逐搏数据中计算圈内心搏。");renderScatterSelectionList();renderScatter();
  try{
    const result=await api(`/api/cases/${caseId}/scatter-selection`,{method:"POST",body:JSON.stringify({mode,polygon,hour_start_s:hourStart})});
    if(requestId!==state.scatterSelectionRequestId||caseId!==state.caseId||mode!==state.scatterMode)return;
    state.scatterSelectedSamples=result.sample_indices;
    state.scatterSelectedSet=new Set(result.sample_indices);
    $("#scatterSelectionCount").textContent=`圈中 ${fmtNumber(result.total)} 段`;
    if(result.total)setScatterSelectionEmpty("正在加载片段","滚动列表将按需加载三导联波形。");else setScatterSelectionEmpty("圈内没有数据点","请重新在散点密集区画一个更大的圈。");
    renderScatterSelectionList();renderScatter();
  }catch(error){
    if(requestId===state.scatterSelectionRequestId){clearScatterSelection();handleError(error);}
  }
}

async function applyScatterRangeSelection() {
  if(!state.scatterData)return;
  const values=["#scatterXMin","#scatterXMax","#scatterYMin","#scatterYMax"].map(selector=>Number($(selector)?.value));
  if(values.some(value=>!Number.isFinite(value))||values[0]>=values[1]||values[2]>=values[3])throw new Error("请输入有效的横轴和纵轴最小、最大范围");
  await applyScatterSelectionPolygon([[values[0],values[2]],[values[1],values[2]],[values[1],values[3]],[values[0],values[3]]]);
}

async function finishScatterLasso() {
  const canvas=$("#scatterCanvas"),data=state.scatterData;
  if(!canvas||!data)return;
  const points=simplifyLasso(state.scatterLasso);
  state.scatterLasso=[];
  if(points.length<3){renderScatter();return;}
  const xs=points.map(point=>point.x),ys=points.map(point=>point.y);
  if(Math.max(...xs)-Math.min(...xs)<8||Math.max(...ys)-Math.min(...ys)<8){renderScatter();return;}
  const rect=canvas.getBoundingClientRect(),geometry=scatterGeometry(rect.width,rect.height);
  await applyScatterSelectionPolygon(points.map(point=>scatterDataPoint(point,data.bounds,geometry)));
}

function cacheScatterStrip(item) {
  if(state.scatterStripCache.has(item.sample_index))state.scatterStripCache.delete(item.sample_index);
  state.scatterStripCache.set(item.sample_index,item);
  while(state.scatterStripCache.size>SCATTER_STRIP_CACHE_LIMIT){const oldest=state.scatterStripCache.keys().next().value;state.scatterStripCache.delete(oldest);}
}

async function loadScatterStrips(job,controller) {
  try{
    const result=await api(`/api/cases/${job.caseId}/waveform-strips`,{method:"POST",signal:controller.signal,body:JSON.stringify({sample_indices:job.samples,pre_s:1.5,post_s:2.5,leads:["II","V1","V5"],max_points:800,filter:job.filter})});
    if(job.generation!==state.scatterStripGeneration||job.caseId!==state.caseId||job.filter!==state.filter)return;
    result.items.forEach(cacheScatterStrip);
  }catch(error){if(error?.name!=="AbortError"&&job.generation===state.scatterStripGeneration){job.samples.forEach(sample=>state.scatterStripFailed.add(sample));handleError(error);}}
  finally{
    if(job.generation===state.scatterStripGeneration){job.samples.forEach(sample=>state.scatterStripPending.delete(sample));state.scatterStripActive=Math.max(0,state.scatterStripActive-1);state.scatterStripControllers.delete(controller);renderScatterSelectionList();pumpScatterStripQueue();}
  }
}

function pumpScatterStripQueue() {
  while(state.scatterStripActive<2&&state.scatterStripQueue.length){
    const job=state.scatterStripQueue.shift();
    if(job.generation!==state.scatterStripGeneration||job.caseId!==state.caseId||job.filter!==state.filter){job.samples.forEach(sample=>state.scatterStripPending.delete(sample));continue;}
    const controller=new AbortController();state.scatterStripControllers.add(controller);state.scatterStripActive+=1;loadScatterStrips(job,controller);
  }
}

function queueScatterStrips(sampleIndices) {
  const generation=state.scatterStripGeneration;
  state.scatterStripQueue=state.scatterStripQueue.filter(job=>{
    if(job.generation!==generation)return true;
    job.samples.forEach(sample=>state.scatterStripPending.delete(sample));return false;
  });
  const samples=sampleIndices.filter(sample=>!state.scatterStripCache.has(sample)&&!state.scatterStripPending.has(sample)&&!state.scatterStripFailed.has(sample));
  if(!samples.length)return;
  samples.forEach(sample=>state.scatterStripPending.add(sample));
  state.scatterStripQueue.push({generation,caseId:state.caseId,filter:state.filter,samples});
  pumpScatterStripQueue();
}

function renderStripCanvas(canvas,strip) {
  const dpr=Math.min(window.devicePixelRatio||1,2),width=Math.max(120,Math.floor(canvas.getBoundingClientRect().width)),height=116;
  canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);const ctx=canvas.getContext("2d");ctx.setTransform(dpr,0,0,dpr,0,0);ctx.fillStyle="#fff";ctx.fillRect(0,0,width,height);
  const entries=Object.entries(strip.leads||{}),leadHeight=height/Math.max(entries.length,1),duration=Math.max(strip.duration_s,.001),anchorX=strip.anchor_offset_s/duration*width;
  ctx.strokeStyle="rgba(228,141,127,.17)";ctx.lineWidth=1;for(let x=0;x<width;x+=width/20){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,height);ctx.stroke();}
  ctx.fillStyle="rgba(239,140,33,.13)";ctx.fillRect(anchorX-3,0,6,height);ctx.strokeStyle="#dd7916";ctx.beginPath();ctx.moveTo(anchorX,0);ctx.lineTo(anchorX,height);ctx.stroke();
  entries.forEach(([lead,values],leadIndex)=>{const baseline=leadHeight*(leadIndex+.55),scale=leadHeight*.27/1000;ctx.fillStyle="#087777";ctx.font=`700 8px ${UI_FONT}`;ctx.fillText(lead,3,leadHeight*leadIndex+9);ctx.strokeStyle="#1f2c32";ctx.lineWidth=.85;ctx.beginPath();values.forEach((value,index)=>{const x=index/Math.max(values.length-1,1)*width,y=baseline-Number(value)*scale;index?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.stroke();if(leadIndex<entries.length-1){ctx.strokeStyle="#e5ebed";ctx.beginPath();ctx.moveTo(0,leadHeight*(leadIndex+1));ctx.lineTo(width,leadHeight*(leadIndex+1));ctx.stroke();}});
}

function renderScatterSelectionList() {
  const viewport=$("#scatterSelectionList"),empty=$("#scatterSelectionEmpty"),virtual=$("#scatterSelectionVirtual");
  if(!viewport||!empty||!virtual)return;
  const focusedButton=document.activeElement?.closest?.("[data-scatter-sample]"),focusedSample=focusedButton?Number(focusedButton.dataset.scatterSample):null;
  const samples=state.scatterSelectedSamples;
  if(!samples.length){empty.hidden=false;virtual.hidden=true;virtual.innerHTML="";virtual.style.height="0";return;}
  empty.hidden=true;virtual.hidden=false;virtual.style.height=`${samples.length*SCATTER_STRIP_HEIGHT}px`;
  const start=Math.max(0,Math.floor(viewport.scrollTop/SCATTER_STRIP_HEIGHT)-2),visibleCount=Math.ceil(viewport.clientHeight/SCATTER_STRIP_HEIGHT)+5,end=Math.min(samples.length,start+visibleCount);
  const visible=samples.slice(start,end);
  virtual.innerHTML=visible.map((sample,offset)=>{const index=start+offset,strip=state.scatterStripCache.get(sample),failed=state.scatterStripFailed.has(sample),time=strip?.time_s??sample/200,label=strip?.label||"…",rr=strip?.rr_ms?`RR ${strip.rr_ms} ms`:failed?"加载失败":"波形加载中",active=sample===state.scatterFocusedSample;return `<button type="button" class="scatter-strip-card${active?" active":""}" style="top:${index*SCATTER_STRIP_HEIGHT+4}px" data-scatter-sample="${sample}" data-jump-time="${time}"${active?' aria-current="true"':""} aria-label="第 ${index+1} 个圈选片段，${formatElapsed(time)}，${label}，${rr}"><div class="scatter-strip-meta"><span class="scatter-beat-badge ${label}">${escapeHtml(label)}</span><strong>${formatElapsed(time)}</strong><small>${escapeHtml(rr)} · ${index+1}/${samples.length}</small></div>${strip?`<canvas data-strip-canvas="${sample}" aria-hidden="true"></canvas>`:`<div class="scatter-strip-placeholder">${failed?"片段加载失败，单击重试":"正在加载三导联波形…"}</div>`}</button>`;}).join("");
  if(focusedSample!==null){const replacement=$(`[data-scatter-sample="${focusedSample}"]`,virtual)||$("[data-scatter-sample]",virtual);if(replacement)replacement.focus({preventScroll:true});else viewport.focus({preventScroll:true});}
  $$('canvas[data-strip-canvas]',virtual).forEach(canvas=>{const strip=state.scatterStripCache.get(Number(canvas.dataset.stripCanvas));if(strip)renderStripCanvas(canvas,strip)});
  const missing=visible.filter(sample=>!state.scatterStripCache.has(sample)&&!state.scatterStripPending.has(sample)&&!state.scatterStripFailed.has(sample)).slice(0,16);
  if(missing.length)queueScatterStrips(missing);
}

async function loadTrends() {
  if (!state.caseId) return;
  const requestId=++state.trendsRequestId,caseId=state.caseId;
  const trend=state.trend||await api(`/api/cases/${caseId}/trend?bin_seconds=60`);
  const [rr,hrv]=state.rr&&state.hrv?[state.rr,state.hrv]:await Promise.all([api(`/api/cases/${caseId}/rr-visuals`),api(`/api/cases/${caseId}/hrv`)]);
  if(requestId!==state.trendsRequestId||caseId!==state.caseId)return;
  state.trend=trend;state.rr=rr;state.hrv=hrv;
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
  const requestId=++state.eventsRequestId,caseId=state.caseId;
  state.eventType=type;
  $$("[data-event-type]").forEach(button=>button.classList.toggle("active",button.dataset.eventType===type));
  const p=new URLSearchParams({type,limit:500,brady:$("#bradyThreshold").value,tachy:$("#tachyThreshold").value,pause:$("#pauseThreshold").value});
  const events=await api(`/api/cases/${caseId}/events?${p}`);
  if(requestId!==state.eventsRequestId||caseId!==state.caseId)return;
  state.events=events;renderEvents();
}

function renderEvents() {
  const labels={V:"室性候选",S:"室上性候选",pause:"长 RR",tachy:"过速候选",brady:"过缓候选",noise:"噪声"};
  if(Object.prototype.hasOwnProperty.call(state.events.summary,"AF"))labels.AF="房颤样候选";
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
  if (state.demoReadonly) {toast("公网演示为只读模式", "error");return;}
  if (!state.caseId) return;
  if(status==="reviewed"&&state.reportDirty){await saveReport("draft");}
  const conclusion=$("#conclusionEditor").value;
  const saved=await api(`/api/cases/${state.caseId}/report`,{method:"PUT",body:JSON.stringify({conclusion,status})});
  state.report=saved;state.caseData.report_workflow=saved;state.reportDirty=false;renderReport();
  toast(status==="reviewed"?"报告已标记为审核通过":status==="returned"?"报告已驳回并保留版本":"草稿已保存");
}

async function loadAudit() {
  if (state.demoReadonly) return;
  const data=await api("/api/audit?limit=300");
  $("#auditBody").innerHTML=data.items.map(item=>`<tr><td>${escapeHtml(item.created_at)}</td><td>${escapeHtml(item.actor)}</td><td>${escapeHtml(item.case_id||"—")}</td><td>${escapeHtml(ACTION_TEXT[item.action]||item.action)}</td><td>${escapeHtml(item.detail||"—")}</td></tr>`).join("")||`<tr><td colspan="5" class="empty-state">尚无审计记录</td></tr>`;
}

async function loadSettings() {
  if (state.demoReadonly) return;
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
  if(state.demoReadonly){toast("公网演示不保存人工标注", "error");return;}
  if(!state.caseId)return;const sample=Math.round(time*200);$("#annotationSample").value=sample;$("#annotationTime").value=formatElapsed(time);$("#annotationLead").value=state.leads[0]||"II";$("#annotationDialog").showModal();
}

async function createAnnotation() {
  if(state.demoReadonly)return;
  const payload={sample_index:Number($("#annotationSample").value),lead:$("#annotationLead").value,category:$("#annotationCategory").value,label:$("#annotationLabel").value,note:$("#annotationNote").value};
  await api(`/api/cases/${state.caseId}/annotations`,{method:"POST",body:JSON.stringify(payload)});$("#annotationDialog").close();toast("人工标注已保存");await loadCase();await loadWaveform();
}

function openPatientEditor(caseId) {
  if(state.demoReadonly){toast("公网演示不允许修改患者资料", "error");return;}
  if(!state.includePhi){toast("为避免在掩码上误编辑，请先点击右上角显示身份信息", "error",4200);return;}
  const item=state.cases.find(x=>x.case_id===caseId);if(!item)return;const m=item.metadata;
  $("#patientCaseId").value=caseId;$("#patientName").value=m.name||"";$("#patientId").value=m.patient_id||"";$("#patientSex").value=m.sex||"未知";$("#patientAge").value=m.age??"";$("#patientBed").value=m.bed||"";$("#patientActive").value=String(item.active);$("#patientDiagnosis").value=m.clinical_diagnosis||"";$("#patientDialog").showModal();
}

async function savePatient() {
  if(state.demoReadonly)return;
  const id=$("#patientCaseId").value,payload={name:$("#patientName").value,patient_id:$("#patientId").value,sex:$("#patientSex").value,age:Number($("#patientAge").value)||null,bed:$("#patientBed").value,active:$("#patientActive").value==="true",clinical_diagnosis:$("#patientDiagnosis").value};
  await api(`/api/cases/${id}/patient`,{method:"PATCH",body:JSON.stringify(payload)});$("#patientDialog").close();toast("患者本地覆盖已保存");await loadDashboard();if(state.caseId===id)await loadCase();
}

function jumpTo(time) {if(!state.caseId)return;state.start=Math.max(0,Math.min(Number(time)-state.duration*.35,state.caseData.technical.duration_seconds_raw-state.duration));if(state.currentPage==="review")loadWaveform().catch(handleError);else goPage("review");}

function focusScatterWaveform(time,sample) {
  state.scatterFocusedSample=sample;renderScatterSelectionList();renderWaveform();
  $("#waveMeta").textContent=`正在定位圈选片段 ${formatElapsedPrecise(time)}…`;
  jumpTo(time);
  const card=$(".waveform-card");if(!card)return;
  card.classList.remove("scatter-linked-focus");void card.offsetWidth;card.classList.add("scatter-linked-focus");
  card.scrollIntoView({behavior:"smooth",block:"center"});
  setTimeout(()=>card.classList.remove("scatter-linked-focus"),1000);
}

function availableTimeZoomSteps() {
  const total=Number(state.caseData?.technical?.duration_seconds_raw)||TIME_ZOOM_STEPS[TIME_ZOOM_STEPS.length-1];
  const steps=TIME_ZOOM_STEPS.filter(value=>value<=total);
  if(total<TIME_ZOOM_STEPS[TIME_ZOOM_STEPS.length-1]&&!steps.includes(total))steps.push(Math.max(1,total));
  return steps.length?steps:[Math.max(1,total)];
}

function updateZoomControls() {
  const label=$("#zoomWindowLabel"),select=$("#durationSelect"),steps=availableTimeZoomSteps();
  if(label)label.textContent=`${state.duration} s`;
  if(select&&[...select.options].some(option=>Number(option.value)===state.duration))select.value=String(state.duration);
  const index=steps.indexOf(state.duration),hasCase=Boolean(state.caseData);
  if($("#zoomIn"))$("#zoomIn").disabled=!hasCase||index<=0;
  if($("#zoomOut"))$("#zoomOut").disabled=!hasCase||index<0||index>=steps.length-1;
  const resetDuration=Math.min(10,Number(state.caseData?.technical?.duration_seconds_raw)||10);
  if($("#zoomReset"))$("#zoomReset").disabled=!hasCase||state.duration===resetDuration;
}

function setWaveformDuration(nextDuration, anchorFraction=.5) {
  if(!state.caseData)return;
  const total=Number(state.caseData.technical.duration_seconds_raw)||nextDuration;
  const duration=Math.max(1,Math.min(Number(nextDuration)||10,total));
  const anchor=Math.max(0,Math.min(1,Number(anchorFraction)||0));
  const anchorTime=state.start+state.duration*anchor;
  state.duration=duration;
  state.start=Math.max(0,Math.min(anchorTime-duration*anchor,Math.max(0,total-duration)));
  $("#timeSlider").max=Math.max(0,total-duration);
  updateZoomControls();
  loadWaveform().catch(handleError);
}

function zoomWaveform(zoomIn, anchorFraction=.5) {
  const steps=availableTimeZoomSteps();
  let index=steps.indexOf(state.duration);
  if(index<0)index=steps.reduce((best,value,current)=>Math.abs(value-state.duration)<Math.abs(steps[best]-state.duration)?current:best,0);
  const nextIndex=Math.max(0,Math.min(steps.length-1,index+(zoomIn?-1:1)));
  if(nextIndex!==index)setWaveformDuration(steps[nextIndex],anchorFraction);
}

function resetWaveformZoom() {setWaveformDuration(Math.min(10,Number(state.caseData?.technical?.duration_seconds_raw)||10),.5);}

function zoomWaveformGain(zoomIn) {
  let index=GAIN_ZOOM_STEPS.indexOf(state.gain);
  if(index<0)index=1;
  const nextIndex=Math.max(0,Math.min(GAIN_ZOOM_STEPS.length-1,index+(zoomIn?1:-1)));
  if(nextIndex===index)return;
  state.gain=GAIN_ZOOM_STEPS[nextIndex];
  $("#gainSelect").value=String(state.gain);
  renderWaveform();
}

function bindCanvasInteraction() {
  const canvas=$("#waveformCanvas"),scroller=$("#waveformScroller"),tooltip=$("#waveTooltip"),cursor=$("#waveCursor");let down=null,wheelTimer=null,wheelIntent=null;
  const cursorX=$(".wave-cursor-x",cursor),cursorY=$(".wave-cursor-y",cursor),cursorDot=$("i",cursor);
  const hideCursor=()=>{tooltip.hidden=true;cursor.hidden=true};
  const finishDrag=event=>{
    if(!down)return;
    const rect=canvas.getBoundingClientRect(),dx=event.clientX-down.x;
    if(Math.abs(dx)>6){state.start=Math.max(0,Math.min(down.start-dx/rect.width*state.duration,state.caseData.technical.duration_seconds_raw-state.duration));loadWaveform().catch(handleError)}
    down=null;scroller.classList.remove("dragging");
  };
  canvas.addEventListener("pointerdown",event=>{down={x:event.clientX,start:state.start};scroller.classList.add("dragging");canvas.setPointerCapture(event.pointerId)});
  canvas.addEventListener("pointerup",finishDrag);
  canvas.addEventListener("pointercancel",event=>{down=null;scroller.classList.remove("dragging");hideCursor();if(canvas.hasPointerCapture(event.pointerId))canvas.releasePointerCapture(event.pointerId)});
  canvas.addEventListener("pointermove",event=>{
    if(!state.waveform)return;
    const rect=canvas.getBoundingClientRect();
    const localX=Math.max(0,Math.min(rect.width,event.clientX-rect.left));
    const localY=Math.max(0,Math.min(rect.height-1,event.clientY-rect.top));
    const fraction=rect.width?localX/rect.width:0;
    const time=state.waveform.start_s+fraction*state.waveform.duration_s;
    const leadNames=Object.keys(state.waveform.leads);
    const leadIndex=Math.min(leadNames.length-1,Math.max(0,Math.floor(localY/(rect.height/leadNames.length))));
    const lead=leadNames[leadIndex]||"—";
    const values=state.waveform.leads[lead]||[];
    const valueIndex=Math.min(values.length-1,Math.max(0,Math.round(fraction*Math.max(0,values.length-1))));
    const millivolts=Number(values[valueIndex]||0)/1000;
    const signedVoltage=`${millivolts>=0?"+":""}${millivolts.toFixed(3)} mV`;

    cursor.hidden=false;tooltip.hidden=false;
    cursorX.style.left=`${localX}px`;cursorX.style.top=`${scroller.scrollTop}px`;cursorX.style.height=`${scroller.clientHeight}px`;
    cursorY.style.top=`${localY}px`;cursorY.style.left=`${scroller.scrollLeft}px`;cursorY.style.width=`${scroller.clientWidth}px`;
    cursorDot.style.left=`${localX}px`;cursorDot.style.top=`${localY}px`;
    tooltip.classList.toggle("flip",localX>rect.width-190);
    tooltip.style.left=`${localX}px`;tooltip.style.top=`${Math.max(6,localY-42)}px`;
    tooltip.textContent=`${formatElapsedPrecise(time)}\n${lead}  ${signedVoltage}`;
  });
  canvas.addEventListener("pointerleave",()=>{if(!down)hideCursor()});
  canvas.addEventListener("dblclick",event=>{const rect=canvas.getBoundingClientRect(),time=state.waveform.start_s+(event.clientX-rect.left)/rect.width*state.waveform.duration_s;openAnnotation(time)});
  canvas.addEventListener("wheel",event=>{
    if(!state.caseData)return;
    event.preventDefault();
    const rect=canvas.getBoundingClientRect();
    const delta=Math.abs(event.deltaY)>=Math.abs(event.deltaX)?event.deltaY:event.deltaX;
    if(!delta)return;
    wheelIntent={gain:event.shiftKey,zoomIn:delta<0,anchor:Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width))};
    clearTimeout(wheelTimer);
    wheelTimer=setTimeout(()=>{if(wheelIntent.gain)zoomWaveformGain(wheelIntent.zoomIn);else zoomWaveform(wheelIntent.zoomIn,wheelIntent.anchor);wheelIntent=null},80);
  },{passive:false});
  $("#overviewCanvas").addEventListener("click",event=>{if(!state.caseData)return;const rect=event.currentTarget.getBoundingClientRect(),time=(event.clientX-rect.left)/rect.width*state.caseData.technical.duration_seconds_raw;jumpTo(time)});
  $("#trendCanvas").addEventListener("click",event=>{if(!state.caseData)return;const rect=event.currentTarget.getBoundingClientRect(),time=(event.clientX-rect.left)/rect.width*state.caseData.technical.duration_seconds_raw;jumpTo(time)});
}

function bindScatterInteraction() {
  const canvas=$("#scatterCanvas"),viewport=$("#scatterSelectionList");
  let activePointer=null,drawFrame=null,scrollFrame=null;
  const localPoint=event=>{
    const rect=canvas.getBoundingClientRect(),geometry=scatterGeometry(rect.width,rect.height);
    return {x:Math.max(geometry.l,Math.min(geometry.l+geometry.w,event.clientX-rect.left)),y:Math.max(geometry.t,Math.min(geometry.t+geometry.h,event.clientY-rect.top))};
  };
  canvas.addEventListener("pointerdown",event=>{
    if(activePointer!==null||!state.scatterData||!state.scatterData.candidate_count||event.pointerType==="mouse"&&event.button!==0)return;
    const rect=canvas.getBoundingClientRect(),geometry=scatterGeometry(rect.width,rect.height),raw={x:event.clientX-rect.left,y:event.clientY-rect.top};
    if(raw.x<geometry.l||raw.x>geometry.l+geometry.w||raw.y<geometry.t||raw.y>geometry.t+geometry.h)return;
    event.preventDefault();activePointer=event.pointerId;state.scatterLasso=[localPoint(event)];canvas.setPointerCapture(event.pointerId);renderScatter();
  });
  canvas.addEventListener("pointermove",event=>{
    if(activePointer!==event.pointerId)return;
    event.preventDefault();const point=localPoint(event),previous=state.scatterLasso[state.scatterLasso.length-1];
    if(previous&&Math.hypot(point.x-previous.x,point.y-previous.y)<3)return;
    state.scatterLasso.push(point);if(!drawFrame)drawFrame=requestAnimationFrame(()=>{drawFrame=null;renderScatter()});
  });
  const finish=event=>{
    if(activePointer!==event.pointerId)return;
    event.preventDefault();const point=localPoint(event),previous=state.scatterLasso[state.scatterLasso.length-1];if(!previous||Math.hypot(point.x-previous.x,point.y-previous.y)>=2)state.scatterLasso.push(point);
    activePointer=null;if(canvas.hasPointerCapture(event.pointerId))canvas.releasePointerCapture(event.pointerId);finishScatterLasso();
  };
  canvas.addEventListener("pointerup",finish);
  canvas.addEventListener("pointercancel",event=>{if(activePointer!==event.pointerId)return;activePointer=null;state.scatterLasso=[];if(canvas.hasPointerCapture(event.pointerId))canvas.releasePointerCapture(event.pointerId);renderScatter()});
  canvas.addEventListener("lostpointercapture",event=>{if(activePointer!==event.pointerId)return;activePointer=null;state.scatterLasso=[];renderScatter()});
  canvas.addEventListener("keydown",event=>{event.stopPropagation();if(event.key==="Escape"){event.preventDefault();activePointer=null;clearScatterSelection();}});
  viewport.addEventListener("scroll",()=>{if(!scrollFrame)scrollFrame=requestAnimationFrame(()=>{scrollFrame=null;renderScatterSelectionList()})},{passive:true});
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
    const strip=event.target.closest("[data-scatter-sample]");if(strip){const sample=Number(strip.dataset.scatterSample);if(state.scatterStripFailed.has(sample)){state.scatterStripFailed.delete(sample);renderScatterSelectionList();}focusScatterWaveform(Number(strip.dataset.jumpTime),sample);}
    else {const jump=event.target.closest("[data-jump-time]");if(jump)jumpTo(jump.dataset.jumpTime);}
    const del=event.target.closest("[data-delete-annotation]");if(del&&confirm("删除这条人工标注？"))api(`/api/annotations/${del.dataset.deleteAnnotation}`,{method:"DELETE"}).then(()=>loadWaveform()).catch(handleError);
  });
  $("#openFirstCase").addEventListener("click",()=>{const first=filteredCases()[0];if(first)selectCase(first.case_id).catch(handleError)});
  if(state.allowPhi)$("#privacyToggle").addEventListener("click",async()=>{try{const enabling=!state.includePhi;if(enabling&&!confirm("身份信息包含真实健康数据。仅应在授权环境中查看，是否继续？"))return;await api("/api/privacy/view",{method:"POST",body:JSON.stringify({enabled:enabling})});state.includePhi=enabling;$("#privacyToggle").classList.toggle("visible",state.includePhi);$("#privacyToggle").setAttribute("aria-pressed",String(state.includePhi));$("#privacyText").textContent=state.includePhi?"身份信息正在显示":"身份信息已遮蔽";await loadDashboard();if(state.caseId)await loadCase()}catch(error){handleError(error)}});
  $$('[data-lead-preset]').forEach(button=>button.addEventListener("click",()=>{state.leadPreset=Number(button.dataset.leadPreset);state.leads=LEAD_PRESETS[state.leadPreset];$$('[data-lead-preset]').forEach(b=>b.classList.toggle("active",b===button));loadWaveform().catch(handleError)}));
  $("#durationSelect").addEventListener("change",event=>setWaveformDuration(Number(event.target.value),.5));
  $("#gainSelect").addEventListener("change",event=>{state.gain=Number(event.target.value);renderWaveform()});
  $("#filterSelect").addEventListener("change",event=>{state.filter=event.target.value;invalidateScatterStripLoads();state.scatterStripCache.clear();state.scatterStripFailed.clear();renderScatterSelectionList();loadWaveform().catch(handleError)});
  $$('[data-scatter-mode]').forEach(button=>button.addEventListener("click",()=>switchScatterMode(button.dataset.scatterMode).catch(handleError)));
  $("#clearScatterSelection").addEventListener("click",clearScatterSelection);
  $("#applyScatterRange").addEventListener("click",()=>applyScatterRangeSelection().catch(handleError));
  $("#zoomIn").addEventListener("click",()=>zoomWaveform(true,.5));$("#zoomOut").addEventListener("click",()=>zoomWaveform(false,.5));$("#zoomReset").addEventListener("click",resetWaveformZoom);
  $("#prevWindow").addEventListener("click",()=>jumpTo(state.start-state.duration*.65));$("#nextWindow").addEventListener("click",()=>jumpTo(state.start+state.duration*1.35));
  let sliderTimer;$("#timeSlider").addEventListener("input",event=>{clearTimeout(sliderTimer);state.start=Number(event.target.value);renderOverview();sliderTimer=setTimeout(()=>loadWaveform().catch(handleError),120)});
  $("#addAnnotation").addEventListener("click",()=>openAnnotation());$("#confirmAnnotation").addEventListener("click",event=>{event.preventDefault();createAnnotation().catch(handleError)});
  $("#confirmPatient").addEventListener("click",event=>{event.preventDefault();savePatient().catch(handleError)});
  $$('[data-event-type]').forEach(button=>button.addEventListener("click",()=>loadEvents(button.dataset.eventType).catch(handleError)));$("#refreshEvents").addEventListener("click",()=>loadEvents().catch(handleError));
  $("#conclusionEditor").addEventListener("input",()=>{state.reportDirty=true;$("#reportSaveState").textContent="有未保存修改";updateConclusionCount()});
  $("#saveReport").addEventListener("click",()=>saveReport("draft").catch(handleError));$("#approveReport").addEventListener("click",()=>saveReport("reviewed").catch(handleError));$("#returnReport").addEventListener("click",()=>saveReport("returned").catch(handleError));
  $("#downloadReport").addEventListener("click",()=>{if(state.caseId)window.location.href=withPhi(`/api/cases/${state.caseId}/report.pdf`)});
  $("#reportPageSelect").addEventListener("change",event=>showReportPage(Number(event.target.value)));$("#openReportImage").addEventListener("click",()=>{const url=$("#sourceReportImage").dataset.url;if(url)window.open(url,"_blank","noopener");else toast("请先使用右上角隐私开关显示身份信息","error")});
  $("#refreshAudit")?.addEventListener("click",()=>loadAudit().catch(handleError));
  document.addEventListener("keydown",event=>{if(["INPUT","TEXTAREA","SELECT"].includes(document.activeElement.tagName)||document.activeElement.closest?.(".scatter-review-card"))return;if(event.key==="ArrowLeft"&&state.currentPage==="review"){event.preventDefault();jumpTo(state.start-state.duration*.65)}if(event.key==="ArrowRight"&&state.currentPage==="review"){event.preventDefault();jumpTo(state.start+state.duration*1.35)}if(!event.ctrlKey&&!event.metaKey&&!event.altKey&&state.currentPage==="review"&&(event.key==="+"||event.key==="=")){event.preventDefault();zoomWaveform(true,.5)}if(!event.ctrlKey&&!event.metaKey&&!event.altKey&&state.currentPage==="review"&&(event.key==="-"||event.key==="_")){event.preventDefault();zoomWaveform(false,.5)}if(!event.ctrlKey&&!event.metaKey&&!event.altKey&&state.currentPage==="review"&&event.key==="0"){event.preventDefault();resetWaveformZoom()}if(event.key.toLowerCase()==="a"&&state.currentPage==="review")openAnnotation();if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==="k"){event.preventDefault();$("#globalSearch").focus()}});
  bindCanvasInteraction();
  bindScatterInteraction();
  let resizeTimer;window.addEventListener("resize",()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{if(state.currentPage==="review"){renderOverview();renderWaveform();renderScatter();renderScatterSelectionList()}if(state.currentPage==="trends"){renderTrendChart();renderHistogram();renderPoincare()}},120)});
}

async function init() {
  bindEvents();
  updateZoomControls();
  try {
    const platformName=navigator.userAgentData?.platform||navigator.platform||"";
    applyPlatformIdentity(platformName);
    const health=await api("/api/health");
    await Promise.all([loadDashboard(),...(state.demoReadonly?[]:[loadSettings()])]);
    $("#dataSetupPanel").hidden=health.data_root_found;
    $("#openFirstCase").disabled=!health.data_root_found;
    if(!health.data_root_found)toast("尚未连接病例数据，请按工作台提示设置本地数据目录","error",5200);
  } catch(error) {handleError(error);}
  finally {setTimeout(()=>$("#loading").classList.add("hidden"),180);}
}

document.addEventListener("DOMContentLoaded",init);
