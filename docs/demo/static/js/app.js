"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const ALL_LEADS = ["I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6"];
const DEFAULT_PREVIEW_LEADS = ["II", "V1", "V5"];
const PREVIEW_LEADS_STORAGE_KEY = "cardioinsight.preview-leads";
const TIME_ZOOM_STEPS = [1, 2, 5, 10, 20, 30, 60, 120];
const GAIN_ZOOM_STEPS = [5, 10, 20];
const SCATTER_MODES = {rr:"R-R散点图",n:"N散点图",nn:"N-N散点图",s:"S散点图",v:"V散点图",hour:"小时散点图"};
const BEAT_COLORS = {1:"#168ba0",2:"#7464c8",3:"#c9544c",34:"#7b858a"};
const EDIT_SOURCE_CLASSES = [
  {key:"source-N",group:1,code:"N",name:"正常搏",description:"源 EBI 分组 1",color:"#168ba0"},
  {key:"source-S",group:2,code:"S",name:"室上性候选",description:"源 EBI 分组 2",color:"#7464c8"},
  {key:"source-V",group:3,code:"V",name:"室性候选",description:"源 EBI 分组 3",color:"#c9544c"},
  {key:"source-X",group:34,code:"X",name:"噪声 / 待确认",description:"源 EBI 分组 34",color:"#7b858a"},
];
const EDIT_BEAT_TYPES = {
  N:{code:"N",name:"正常",color:"#168ba0"},S:{code:"S",name:"室上性候选",color:"#7464c8"},
  V:{code:"V",name:"室性候选",color:"#c9544c"},X:{code:"X",name:"噪声 / 待确认",color:"#7b858a"},
  P:{code:"P",name:"起搏",color:"#c77a1d"},O:{code:"O",name:"房早未下传",color:"#405563"},
};
const EDIT_FAMILY_DEFAULT_NAMES = {"全部":"全部复核类","单发":"单发复核类","成对":"成对复核类","房速":"房速复核类","二联律":"二联律复核类","三联律(NPN)":"三联律 NPN 复核类","三联律(NPP)":"三联律 NPP 复核类","四联律":"四联律复核类","自定义":"自建类别"};
const SCATTER_STRIP_HEIGHT = 156;
const SCATTER_STRIP_CACHE_LIMIT = 240;
const STATUS_TEXT = {draft: "未审核", reviewed: "已审核", returned: "已驳回"};
const REPORT_PAGES = [
  {key:"cover",label:"封面",available:true}, {key:"summary",label:"首页报告",available:true},
  {key:"hourly",label:"小时统计表格",available:true}, {key:"scatter",label:"散点图",available:true},
  {key:"st_trend",label:"ST 趋势图",available:false}, {key:"t_trend",label:"T 波趋势图",available:false},
  {key:"event_strips",label:"事件图条",available:true}, {key:"st_events",label:"ST 事件",available:false},
  {key:"pacing",label:"起搏报告",available:false}, {key:"af",label:"房颤 / 房扑",available:true},
  {key:"hrv_time",label:"HRV 时域报告",available:true}, {key:"hrv_frequency",label:"HRV 频域报告",available:false},
  {key:"hrv_overview",label:"HRV 概述",available:true}, {key:"hrt",label:"心率震荡 (HRT) 报告",available:false},
  {key:"qtd",label:"QT 离散度 (QTd) 报告",available:false}, {key:"vcg",label:"心电向量 (VCG) 报告",available:false},
  {key:"dc",label:"心率减速力 (DC) 报告",available:false}, {key:"twa",label:"T 波电交替 (TWA) 报告",available:false},
  {key:"vlp",label:"心室晚电位 (VLP) 报告",available:false}, {key:"sap",label:"睡眠窒息 (SAP) 报告",available:false},
];
const REPORT_TEMPLATES = {
  comprehensive:["cover","summary","hourly","event_strips","hrv_time","hrv_overview"],
  rhythm:["summary","event_strips","af","hrv_time"],
  concise:["cover","summary","event_strips"],
};
const DEFAULT_REPORT_COMPOSITION = {template:"comprehensive",included_pages:[...REPORT_TEMPLATES.comprehensive],active_page:"summary",preview_mode:"compose",fast_slow_mode:"rr",paper:{size:"A4",orientation:"portrait",show_grid:true,show_labels:true,speed:"25 mm/s",gain:"10 mm/mV"}};
const UI_FONT = '"SF Pro Text", "PingFang SC", "Microsoft YaHei UI", sans-serif';
const APP_MODE = Object.freeze({
  demoReadonly: document.documentElement.dataset.demoReadonly === "true",
  allowPhi: document.documentElement.dataset.allowPhi === "true",
});
const CASE_WORKFLOW_STEPS = Object.freeze([
  {page:"review",label:"波形复核",next:"模板编辑"},
  {page:"edit",label:"模板编辑",next:"趋势与 HRV"},
  {page:"trends",label:"趋势与 HRV",next:"ST‑T 复核"},
  {page:"stt",label:"ST‑T 复核",next:"事件候选"},
  {page:"events",label:"事件候选",next:"报告"},
  {page:"report",label:"报告",next:"工作台"},
]);
const CASE_WORKFLOW_PAGES = new Set(CASE_WORKFLOW_STEPS.map(step=>step.page));
const CASE_WORKFLOW_STORAGE_PREFIX = "cardioinsight.case-workflow.";
const ACTION_TEXT = {
  "privacy.phi_view": "查看身份信息", "case.open": "打开病例",
  "annotation.create": "创建标注", "annotation.delete": "删除标注",
  "patient.update": "修改患者", "report.draft": "保存报告草稿",
  "report.reviewed": "审核报告", "report.returned": "驳回报告",
  "report.export_pdf": "导出 PDF",
  "beat_template.create": "创建心搏模板", "beat_template.update": "修改心搏模板",
  "beat_template.delete": "删除心搏模板",
  "beat_override.reclassify": "人工修改心搏类型", "beat_override.restore": "恢复源心搏类型",
};

function initialPreviewLeads() {
  try {
    const stored = JSON.parse(localStorage.getItem(PREVIEW_LEADS_STORAGE_KEY) || "null");
    if (Array.isArray(stored) && stored.length >= 1 && stored.length <= 3 && stored.every(lead => ALL_LEADS.includes(lead)) && new Set(stored).size === stored.length) return [...stored].sort((a, b) => ALL_LEADS.indexOf(a) - ALL_LEADS.indexOf(b));
  } catch (error) {
    console.warn("无法读取已保存的导联选择", error);
  }
  return [...DEFAULT_PREVIEW_LEADS];
}

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
  leads: initialPreviewLeads(),
  waveformExpanded: false,
  waveformFullscreenFallback: false,
  trend: null,
  waveform: null,
  waveformRequestId: 0,
  sttReview: null,
  sttWaveform: null,
  sttRequestId: 0,
  sttStart: 0,
  sttDuration: 10,
  sttMeasurementMs: 60,
  sttIsoFraction: .34,
  sttJFraction: .52,
  editMode: "cluster",
  editStart: 0,
  editDuration: 20,
  editLead: "II",
  editRequestId: 0,
  editStripRequestId: 0,
  editScatterData: null,
  editRr: null,
  editWaveform: null,
  editTemplates: [],
  editBeatOverrides: new Map(),
  beatRelabelTarget: null,
  editSelectedSamples: new Set(),
  editSelectionAnchor: null,
  editLibraryFilter: "all",
  editTemplateStrips: [],
  editSelectionStrips: [],
  editMorphTraceGeometry: [],
  editMorphDraft: null,
  editSelectedClass: "source-N",
  editSelectedSample: null,
  editSelection: null,
  editEditingTemplateId: null,
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
  reportRequestId: 0,
  reportComposer: null,
  reportComposition: null,
  reportEventFilter: "all",
  reportFocusedSample: null,
  search: "",
  currentPage: "dashboard",
  workflowVisited: new Set(),
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
}

async function api(path, options = {}) {
  if(path.startsWith("/api/cases/"))path+=(path.includes("?")?"&":"?")+"analysis=edited";
  const requestCase=state.caseId;
  const response = await fetch(path, {
    headers: {"Content-Type": "application/json", "X-Actor": "demo-analyst", "X-CardioInsight-Request": "1", ...(options.headers || {})},
    ...options,
  });
  const type = response.headers.get("content-type") || "";
  const payload = type.includes("application/json") ? await response.json() : null;
  if (!response.ok) throw new Error(payload?.error || `请求失败（${response.status}）`);
  if(requestCase===state.caseId&&/^(PUT|PATCH|DELETE|POST)$/.test(options.method||"")&&/\/(beat-overrides|beat-templates|annotations|patient)(\/|$)/.test(path)){
    state.reportComposer=null;
    await clinicalWorkflow.refresh(requestCase).catch(()=>{clinicalWorkflow.receive(null);toast("修改已保存，但复核状态读取失败，请刷新后继续审核","error",6000);});
  }
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
      <td><button class="row-action" data-open-case="${item.case_id}">${item.review_workflow?.report_status==="reviewed"?"查看报告":item.review_workflow?.steps&&Object.keys(item.review_workflow.steps).length?"继续复核 →":"开始复核 →"}</button></td>
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

function loadCaseWorkflow(caseId) {
  try {
    const stored=JSON.parse(localStorage.getItem(`${CASE_WORKFLOW_STORAGE_PREFIX}${caseId}`)||"[]");
    return new Set(Array.isArray(stored)?stored.filter(page=>CASE_WORKFLOW_PAGES.has(page)):[]);
  } catch(error) {
    console.warn("无法读取病例复核导航进度",error);
    return new Set();
  }
}

function persistCaseWorkflow() {
  if(!state.caseId)return;
  try {localStorage.setItem(`${CASE_WORKFLOW_STORAGE_PREFIX}${state.caseId}`,JSON.stringify([...state.workflowVisited]));}
  catch(error) {console.warn("无法保存病例复核导航进度",error);}
}

function markWorkflowVisited(page) {
  if(!state.caseId||!CASE_WORKFLOW_PAGES.has(page)||state.workflowVisited.has(page))return;
  state.workflowVisited.add(page);persistCaseWorkflow();
}

function renderCaseWorkflow() {
  clinicalWorkflow.render();
}

function advanceCaseWorkflow() {
  if(state.currentPage==="report"&&state.report?.status==="reviewed"){goPage("dashboard");return;}
  clinicalWorkflow.confirmStep();
}

async function selectCase(caseId, destination = "review") {
  if(!clinicalWorkflow.allowLeave())return;
  clinicalWorkflow.reset();
  const requestId=++state.caseRequestId;
  state.caseId = caseId;
  state.workflowVisited = loadCaseWorkflow(caseId);
  state.caseData = null;
  state.report = null;
  state.start = 0;
  state.waveformRequestId += 1;
  state.sttRequestId += 1;
  state.editRequestId += 1;
  state.editStripRequestId += 1;
  state.trendsRequestId += 1;
  state.eventsRequestId += 1;
  state.reportRequestId += 1;
  state.scatterRequestId += 1;
  state.scatterSelectionRequestId += 1;
  state.waveform = state.sttReview = state.sttWaveform = state.trend = state.rr = state.hrv = state.events = null;
  state.reportComposer = null;
  state.reportComposition = null;
  state.reportEventFilter = "all";
  state.reportFocusedSample = null;
  state.sttStart = 0;
  state.editStart = 0;
  state.editScatterData = state.editRr = state.editWaveform = null;
  state.editTemplates = state.editTemplateStrips = [];
  state.editBeatOverrides = new Map();
  state.beatRelabelTarget = null;
  state.editSelectedSamples = new Set();
  state.editSelectionAnchor = null;
  state.editLibraryFilter = "all";
  state.editSelectionStrips = [];
  state.editMorphTraceGeometry = [];
  state.editMorphDraft = null;
  state.editSelectedClass = "source-N";
  state.editSelectedSample = null;
  state.editSelection = null;
  state.editEditingTemplateId = null;
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
  const [caseData, trend, overrides] = await Promise.all([
    api(withPhi(`/api/cases/${caseId}`)),
    api(`/api/cases/${caseId}/trend?bin_seconds=60`),
    api(`/api/cases/${caseId}/beat-overrides`),
  ]);
  if(activeRequestId!==state.caseRequestId||caseId!==state.caseId)return false;
  state.caseData = caseData;
  for(const key of ["brady","tachy","pause"]){
    if(caseData.beat_editor_settings?.[key]!==undefined)$("#"+key+"Threshold").value=caseData.beat_editor_settings[key];
  }
  state.trend = trend;
  state.editBeatOverrides = new Map((overrides.items || []).map(item => [Number(item.sample_index), item]));
  state.report = caseData.report_workflow;
  clinicalWorkflow.receive(caseData.review_workflow);
  state.reportDirty = false;
  if (state.start === 0 && caseData.calculated.first_beat_time_s > state.duration) {
    state.start = Math.max(0, caseData.calculated.first_beat_time_s - 2);
  }
  if (state.sttStart === 0) state.sttStart = state.start;
  if (state.editStart === 0) state.editStart = state.start;
  const m = caseData.metadata, calc=caseData.calculated, s = {...caseData.summary,avg_hr:calc.avg_hr_from_rr,total_beats:calc.valid_beats,ventricular_beats:calc.group_counts?.["3"]||0,supraventricular_beats:calc.group_counts?.["2"]||0,longest_rr_s:(calc.longest_rr_ms||0)/1000};
  $("#caseHero").classList.remove("empty-case");
  $("#caseHero").innerHTML = `<div><p class="eyebrow">当前病例 · ${caseData.case_id}</p><h1>${escapeHtml(m.name)}　${escapeHtml(m.sex)}　${m.age ?? "—"} 岁</h1><p>${escapeHtml(m.clinical_diagnosis || "未提供临床诊断")} · ${escapeHtml(m.start_time)} · ${escapeHtml(m.duration_text)}</p></div><div class="case-meta-chips"><span>平均心率<strong>${s.avg_hr ?? "—"} bpm</strong></span><span>有效心搏<strong>${fmtNumber(s.total_beats)}</strong></span><span>V / S<strong>${fmtNumber(s.ventricular_beats)} / ${fmtNumber(s.supraventricular_beats)}</strong></span><span>最长 RR<strong>${s.longest_rr_s ?? "—"} s</strong></span></div>`;
  $("#trendCaseLabel").textContent = `${caseData.case_id} · ${m.name} · ${m.duration_text}`;
  $("#sttCaseLabel").textContent = `${caseData.case_id} · ${m.name} · ${m.duration_text}`;
  $("#editCaseLabel").textContent = `${caseData.case_id} · ${m.name} · ${m.duration_text}`;
  $("#eventCaseLabel").textContent = `${caseData.case_id} · ${m.name}`;
  $("#reportCaseLabel").textContent = `${caseData.case_id} · ${m.name} · ${m.start_time}`;
  renderCaseWorkflow();
  const duration = caseData.technical.duration_seconds_raw;
  $("#timeSlider").max = Math.max(0, Math.floor(duration - state.duration));
  $("#timeSlider").value = state.start;
  $("#sttTimeSlider").max = Math.max(0, Math.floor(duration - state.sttDuration));
  $("#sttTimeSlider").value = state.sttStart;
  updateZoomControls();
  renderOverview();
  renderReport();
  if (state.currentPage === "review") await loadWaveform();
  return activeRequestId===state.caseRequestId&&caseId===state.caseId;
}

function goPage(name) {
  if(name!==state.currentPage&&state.reportDirty&&!clinicalWorkflow.allowLeave())return;
  if (state.demoReadonly && ["audit", "settings"].includes(name)) name = "dashboard";
  const needsCase = ["edit", "review", "trends", "stt", "events", "report"].includes(name);
  if (needsCase && !state.caseId) {
    toast("请先从工作列表选择病例", "error");
    name = "dashboard";
  }
  if(name==="edit"&&state.currentPage!=="edit")setEditMode("cluster",false);
  state.currentPage = name;
  markWorkflowVisited(name);
  $$(".page").forEach(page => page.classList.toggle("active", page.id === `page-${name}`));
  $$(".nav-item").forEach(item => item.classList.toggle("active", item.dataset.page === name));
  renderCaseWorkflow();
  window.scrollTo({top: 0, behavior: "instant"});
  if (name === "dashboard") loadDashboard().catch(handleError);
  if (name === "review") {loadWaveform().catch(handleError);loadScatter().catch(handleError);}
  if (name === "trends") loadTrends().catch(handleError);
  if (name === "stt") loadStt().catch(handleError);
  if (name === "edit") loadEdit().catch(handleError);
  if (name === "events") loadEvents().catch(handleError);
  if (name === "report") loadReport().catch(handleError);
  if (name === "audit") loadAudit().catch(handleError);
  if (name === "settings") loadSettings().catch(handleError);
}

function waveformRequestLeads() {
  return state.waveformExpanded ? ALL_LEADS : state.leads.slice(0, 3);
}

function persistPreviewLeads() {
  try {
    localStorage.setItem(PREVIEW_LEADS_STORAGE_KEY, JSON.stringify(state.leads));
  } catch (error) {
    console.warn("无法保存导联选择", error);
  }
}

function updateWaveformModeUI() {
  const title = $("#waveformTitle"), button = $("#toggleWaveformFullscreen"), buttonLabel = $("em", button), canvas = $("#waveformCanvas"), hint = $("#waveInteractionHint"), selected = $("#selectedLeadLabel");
  if (selected) selected.textContent = state.leads.join(" · ");
  if (title) title.textContent = state.waveformExpanded ? "全导联连续波形" : `连续波形 · ${state.leads.length} 导联复核`;
  if (buttonLabel) buttonLabel.textContent = state.waveformExpanded ? "退出全屏" : "全屏多导联";
  if (button) {
    button.classList.toggle("active", state.waveformExpanded);
    button.setAttribute("aria-pressed", String(state.waveformExpanded));
    button.setAttribute("aria-label", state.waveformExpanded ? "退出全屏多导联" : "全屏查看全部十二导联");
  }
  if (canvas) canvas.setAttribute("aria-label", state.waveformExpanded
    ? "十二导联连续心电波形；右键最近心搏可重标注，双击或按 F 退出全屏，移动指针可查看时间、导联和电压坐标"
    : "最多三导联连续心电波形；右键最近心搏可重标注，双击或按 F 全屏查看全部十二导联，滚轮缩放时间轴，按住 Shift 滚轮缩放电压增益，移动指针可查看时间、导联和电压坐标");
  if (hint) hint.textContent = state.waveformExpanded
    ? "全部 12 导联 · 右键最近心搏重标注 · 双击或按 F 退出 · 滚轮缩放 · 拖动平移"
    : "右键最近心搏重标注 · 双击或按 F 全屏查看全部 12 导联 · 滚轮缩放 · 拖动平移 · 悬停查坐标";
}

function updateLeadPickerState() {
  const choices = $$('[data-lead-choice]'), selectedCount = choices.filter(choice => choice.checked).length;
  choices.forEach(choice => { choice.disabled = !choice.checked && selectedCount >= 3; });
  const count = $("#leadSelectionCount"), apply = $("#applyLeadSelection");
  if (count) count.textContent = `已选 ${selectedCount} / 3`;
  if (apply) apply.disabled = selectedCount === 0;
}

function setLeadPickerSelection(leads) {
  $$('[data-lead-choice]').forEach(choice => { choice.checked = leads.includes(choice.value); });
  updateLeadPickerState();
}

function openLeadPicker() {
  const dialog = $("#leadPickerDialog");
  if (!dialog || dialog.open) return;
  setLeadPickerSelection(state.leads);
  dialog.showModal();
}

function applyLeadSelection() {
  const selected = $$('[data-lead-choice]:checked').map(choice => choice.value).sort((a, b) => ALL_LEADS.indexOf(a) - ALL_LEADS.indexOf(b));
  if (!selected.length || selected.length > 3) return;
  state.leads = selected;
  persistPreviewLeads();
  updateWaveformModeUI();
  $("#leadPickerDialog").close();
  if (!state.waveformExpanded) loadWaveform().catch(handleError);
  else toast(`主界面导联已设为 ${selected.join(" / ")}，退出全屏后生效`);
}

function finishWaveformFullscreenExit() {
  if (!state.waveformExpanded) return;
  state.waveformExpanded = false;
  state.waveformFullscreenFallback = false;
  $("#waveformCard")?.classList.remove("waveform-expanded", "waveform-fullscreen-fallback");
  document.body.classList.remove("waveform-overlay-open");
  updateWaveformModeUI();
  if (state.currentPage === "review") loadWaveform().catch(handleError);
}

async function enterWaveformFullscreen() {
  if (!state.caseId || state.waveformExpanded) return;
  const card = $("#waveformCard");
  state.waveformExpanded = true;
  state.waveformFullscreenFallback = false;
  card.classList.add("waveform-expanded");
  document.body.classList.add("waveform-overlay-open");
  updateWaveformModeUI();
  try {
    if (card.requestFullscreen) await card.requestFullscreen({navigationUI: "hide"});
    else throw new Error("Fullscreen API unavailable");
  } catch (error) {
    state.waveformFullscreenFallback = true;
    card.classList.add("waveform-fullscreen-fallback");
  }
  await loadWaveform();
}

async function exitWaveformFullscreen() {
  if (!state.waveformExpanded) return;
  if (document.fullscreenElement === $("#waveformCard")) {
    await document.exitFullscreen();
    return;
  }
  finishWaveformFullscreenExit();
}

function toggleWaveformFullscreen() {
  const action = state.waveformExpanded ? exitWaveformFullscreen() : enterWaveformFullscreen();
  action.catch(handleError);
}

async function loadWaveform() {
  if (!state.caseId) return;
  const requestId=++state.waveformRequestId;
  const requestedLeads = waveformRequestLeads();
  const params = new URLSearchParams({
    start: state.start.toFixed(3), duration: state.duration, leads: requestedLeads.join(","),
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
  const visibleLeads = Object.keys(data.leads);
  $("#waveMeta").textContent = `${visibleLeads.length} 导联 · ${data.sample_rate_hz} Hz · ${data.filter} · ${formatElapsed(data.start_s)}`;
  $("#calibrationNote").textContent = data.calibration_note;
  renderWaveform();
  renderVisibleEvents();
  renderAnnotations(data.annotations || state.caseData?.annotations || []);
  renderOverview();
  syncHourScatter();
}

function canvasContext(canvas, height = null) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  // Measure the CSS slot, not a minimum backing-store size: small strip cards
  // must show the whole time window rather than clipping a 300 px canvas.
  canvas.style.width = "100%";
  const width = Math.max(1, Math.floor(canvas.getBoundingClientRect().width || canvas.parentElement.clientWidth - 2));
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
  const scroller = $("#waveformScroller");
  const leadNames = Object.keys(state.waveform.leads);
  const height = state.waveformExpanded
    ? Math.max(560, scroller.clientHeight, leadNames.length * 56)
    : Math.max(360, leadNames.length * 138);
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
    const code=editEffectiveCode(beat),type=editBeatType(code),isNormal=code==="N";
    ctx.strokeStyle = type.color;
    ctx.lineWidth = isNormal ? .6 : 1.25;
    ctx.globalAlpha = isNormal ? .28 : .68;
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
    ctx.globalAlpha = 1;
    ctx.fillStyle = type.color; ctx.font = "700 9px sans-serif";
    ctx.fillText(code, Math.min(x + 2, width - 12), 11);
    if((typeof beatEditor!=="undefined"&&beatEditor.selected(Number(beat.sample_index)))||(state.beatRelabelTarget?.surface==="review"&&Number(state.beatRelabelTarget.sample_index)===Number(beat.sample_index))){
      ctx.fillStyle="rgba(239,140,33,.14)";ctx.fillRect(x-8,0,16,h);ctx.strokeStyle="#ef8c21";ctx.lineWidth=1.4;ctx.strokeRect(x-8+.5,.5,15,h-1);
    }
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
  const abnormal = beats.filter(item => editEffectiveCode(item) !== "N");
  $("#visibleEventList").classList.toggle("empty-state", !abnormal.length);
  $("#visibleEventList").innerHTML = abnormal.length ? abnormal.slice(0, 50).map(item => {const code=editEffectiveCode(item),manual=state.editBeatOverrides.has(Number(item.sample_index)),type=editBeatType(code);return `<div class="mini-event" data-jump-time="${item.time_s}"><span class="event-marker ${code}"></span><div><strong>${escapeHtml(`${code} · ${type.name}${manual?"（人工）":""}`)}</strong><small>${formatElapsed(item.time_s)} · RR ${item.rr_ms} ms · ${item.hr ?? "—"} bpm</small></div></div>`;}).join("") : "当前窗口无异常候选";
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
  virtual.innerHTML=visible.map((sample,offset)=>{const index=start+offset,strip=state.scatterStripCache.get(sample),failed=state.scatterStripFailed.has(sample),time=strip?.time_s??sample/200,label=strip?editEffectiveCode(strip):"…",rr=strip?.rr_ms?`RR ${strip.rr_ms} ms`:failed?"加载失败":"波形加载中",active=sample===state.scatterFocusedSample;return `<button type="button" class="scatter-strip-card${active?" active":""}" style="top:${index*SCATTER_STRIP_HEIGHT+4}px" data-scatter-sample="${sample}" data-jump-time="${time}"${active?' aria-current="true"':""} aria-label="第 ${index+1} 个圈选片段，${formatElapsed(time)}，${label}，${rr}"><div class="scatter-strip-meta"><span class="scatter-beat-badge ${label}">${escapeHtml(label)}</span><strong>${formatElapsed(time)}</strong><small>${escapeHtml(rr)} · ${index+1}/${samples.length}</small></div>${strip?`<canvas data-strip-canvas="${sample}" aria-hidden="true"></canvas>`:`<div class="scatter-strip-placeholder">${failed?"片段加载失败，单击重试":"正在加载三导联波形…"}</div>`}</button>`;}).join("");
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
  const comparison=state.hrv.comparison||{},sourceLabel=comparison.source_label||"源报告";
  const note=$("#hrvComparisonNote");
  if(note)note.textContent=comparison.calculated_label
    ? `${sourceLabel}（${comparison.source_duration||"完整记录"}）与${comparison.calculated_label}（${comparison.calculated_duration||"当前记录"}）；${comparison.warning||"差异不自动替代医生结论。"}`
    : "源报告与本软件重算结果并列，差异不自动替代医生结论";
  const values=[["Mean NN",null,calc.mean_nn_ms],["SDNN",source.sdnn_ms,calc.sdnn_ms],["SDANN",source.sdann_ms,calc.sdann_ms],["SDNN index",source.sdnn_index_ms,calc.sdnn_index_ms],["rMSSD",source.rmssd_ms,calc.rmssd_ms],["pNN50",source.pnn50_pct,calc.pnn50_pct],["三角指数",source.triangular_index,calc.triangular_index]];
  values[0][1]=source.mean_nn_ms;
  $("#hrvTable").innerHTML=values.map(([label,a,b])=>`<div class="compare-cell"><span>${label}</span><strong>${b ?? "—"}${label==="pNN50"?"%":label==="三角指数"?"":" ms"}</strong><small>${label==="Mean NN"&&source.mean_nn_derived?"完整报告心率换算 ≈":`${sourceLabel} `}${a ?? "—"}</small></div>`).join("");
}

function sttLandmarkFractions() {
  const duration=Math.max(.001,Number(state.sttWaveform?.duration_s)||state.sttDuration);
  const offsetFraction=(Number(state.sttMeasurementMs)||0)/1000/duration;
  const iso=Math.max(.04,Math.min(state.sttIsoFraction,state.sttJFraction-.025));
  const j=Math.max(iso+.025,Math.min(state.sttJFraction,.96-offsetFraction));
  return {iso,j,st:Math.min(.97,j+offsetFraction),offsetFraction};
}

function sttMeasurementValues() {
  const waveform=state.sttWaveform;
  if(!waveform)return [];
  const marks=sttLandmarkFractions();
  return Object.entries(waveform.leads||{}).map(([lead,values])=>{
    const last=Math.max(0,values.length-1),isoIndex=Math.round(marks.iso*last),pointIndex=Math.round(marks.st*last);
    const baseline=Number(values[isoIndex]),point=Number(values[pointIndex]);
    return {lead,baseline,point,delta:Number.isFinite(baseline)&&Number.isFinite(point)?point-baseline:null};
  });
}

function renderSttCapability() {
  const review=state.sttReview;
  if(!review)return;
  $("#sttCapabilityBadge").textContent=review.manual_review_only?"人工复核模式":"能力待确认";
  $("#sttSafetyText").textContent=review.calibration?.message||"当前病例只允许人工定性复核，不生成自动 ST-T 诊断。";
  $("#sttLeadSystem").textContent=review.lead_system?.message||"导联体系待核验";
  $("#sttBaselineMethod").textContent=review.measurement_protocol?.baseline?.label||"手工 ISO / 个体稳定基线";
  const reasons=review.automatic_candidates?.reasons||[];
  $("#sttCandidateCount").textContent="0 条";
  $("#sttCandidateList").innerHTML=`<div class="stt-unavailable-state"><span aria-hidden="true">∿</span><strong>未生成自动 ST‑T 候选</strong><p>${escapeHtml(reasons.slice(0,2).join("；")||"当前测量链尚未验证。")}</p><button type="button" class="row-action" data-stt-current-window>从当前时间窗人工复核</button></div>`;
  const fragments=review.source_report?.fragments||[];
  $("#sttSourceNotes").innerHTML=fragments.length
    ? fragments.map(text=>`<blockquote><span>源报告</span><p>${escapeHtml(text)}</p></blockquote>`).join("")
    : `<div class="stt-source-empty">源报告结论中没有可提取的 ST‑T 文字线索</div>`;
}

function renderSttTrendRows() {
  if(!state.caseData)return;
  const total=Math.max(1,Number(state.caseData.technical.duration_seconds_raw)||1);
  const left=Math.max(0,Math.min(100,state.sttStart/total*100));
  const width=Math.max(.35,Math.min(100-left,state.sttDuration/total*100));
  $("#sttTrendRows").innerHTML=ALL_LEADS.map(lead=>`<div class="stt-trend-row"><strong>${lead}</strong><div class="stt-disabled-track" style="--window-left:${left}%;--window-width:${width}%"><span></span><i></i></div><small>待标定</small></div>`).join("");
}

function renderSttOverview() {
  if(!state.caseData||!state.trend)return;
  const canvas=$("#sttOverviewCanvas"),{ctx,width,height}=canvasContext(canvas,94),m={l:40,r:13,t:10,b:20};
  ctx.clearRect(0,0,width,height);ctx.fillStyle="#fff";ctx.fillRect(0,0,width,height);
  const plotW=width-m.l-m.r,plotH=height-m.t-m.b,total=Math.max(1,state.caseData.technical.duration_seconds_raw),points=state.trend.points||[];
  const values=points.map(point=>Number(point.hr)).filter(Number.isFinite),minHr=Math.max(20,Math.floor((Math.min(...values,50)-10)/10)*10),maxHr=Math.min(240,Math.ceil((Math.max(...values,120)+10)/10)*10),range=Math.max(20,maxHr-minHr);
  ctx.strokeStyle="#e4eaed";ctx.lineWidth=1;[0,.5,1].forEach(fraction=>{const y=m.t+plotH*fraction;ctx.beginPath();ctx.moveTo(m.l,y);ctx.lineTo(width-m.r,y);ctx.stroke();});
  const startX=m.l+state.sttStart/total*plotW,endX=m.l+Math.min(total,state.sttStart+state.sttDuration)/total*plotW;
  ctx.fillStyle="rgba(11,146,144,.12)";ctx.fillRect(startX,m.t,Math.max(3,endX-startX),plotH);ctx.strokeStyle="#0b9290";ctx.strokeRect(startX+.5,m.t+.5,Math.max(2,endX-startX-1),plotH-1);
  ctx.beginPath();points.forEach((point,index)=>{const x=m.l+point.time_s/total*plotW,y=m.t+plotH-(Math.max(minHr,Math.min(maxHr,Number(point.hr)))-minHr)/range*plotH;index?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.strokeStyle="#2678b9";ctx.lineWidth=1.35;ctx.stroke();
  ctx.font=`9px ${UI_FONT}`;ctx.fillStyle="#71828c";ctx.fillText(`${maxHr}`,3,m.t+4);ctx.fillText(`${minHr}`,3,m.t+plotH);ctx.fillText("D1 00h",m.l,height-5);ctx.fillText(formatElapsed(total),Math.max(m.l,width-m.r-62),height-5);
  $("#sttWindowTime").textContent=`${formatElapsed(state.sttStart)}–${formatElapsed(state.sttStart+state.sttDuration)}`;
}

function renderSttMeasurements() {
  const values=sttMeasurementValues(),pointLabel=state.sttMeasurementMs===0?"J 点":`J+${state.sttMeasurementMs} ms`;
  $("#sttPointMethod").textContent=pointLabel;
  $("#sttMeasurementList").innerHTML=values.length?values.map(item=>{
    const value=item.delta===null?"—":`${item.delta>=0?"+":""}${item.delta.toFixed(0)}`;
    return `<div><strong>${item.lead}</strong><span><small>ISO → ${escapeHtml(pointLabel)}</small><b>${value} <em>设备单位</em></b></span></div>`;
  }).join(""):`<div class="stt-measurement-empty">拖动游标后显示各导联相对差值</div>`;
}

function renderSttWaveform() {
  const waveform=state.sttWaveform;if(!waveform)return;
  const canvas=$("#sttWaveformCanvas"),{ctx,width,height}=canvasContext(canvas,438),leads=Object.entries(waveform.leads||{}),m={l:54,r:18,t:24,b:22},plotW=width-m.l-m.r,plotH=height-m.t-m.b,leadHeight=plotH/Math.max(1,leads.length);
  ctx.clearRect(0,0,width,height);ctx.fillStyle="#fff";ctx.fillRect(0,0,width,height);
  for(let x=m.l;x<=width-m.r;x+=10){ctx.strokeStyle=(x-m.l)%50===0?"rgba(219,104,91,.24)":"rgba(219,104,91,.10)";ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(x,m.t);ctx.lineTo(x,m.t+plotH);ctx.stroke();}
  for(let y=m.t;y<=m.t+plotH;y+=10){ctx.strokeStyle=(y-m.t)%50===0?"rgba(219,104,91,.24)":"rgba(219,104,91,.10)";ctx.beginPath();ctx.moveTo(m.l,y);ctx.lineTo(width-m.r,y);ctx.stroke();}
  leads.forEach(([lead,values],leadIndex)=>{
    const baseline=m.t+leadHeight*(leadIndex+.52),sampleStep=Math.max(1,Math.ceil(values.length/500)),magnitudes=values.filter((_,index)=>index%sampleStep===0).map(value=>Math.abs(Number(value)||0)).sort((a,b)=>a-b),limit=Math.max(80,magnitudes[Math.floor(magnitudes.length*.96)]||80),scale=leadHeight*.33/limit;
    ctx.strokeStyle="#d9e2e6";ctx.beginPath();ctx.moveTo(m.l,baseline);ctx.lineTo(width-m.r,baseline);ctx.stroke();ctx.fillStyle="#087777";ctx.font=`700 11px ${UI_FONT}`;ctx.fillText(lead,14,baseline+4);
    ctx.strokeStyle="#243b46";ctx.lineWidth=1.05;ctx.beginPath();values.forEach((value,index)=>{const x=m.l+index/Math.max(1,values.length-1)*plotW,y=baseline-(Number(value)||0)*scale;index?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.stroke();
    if(leadIndex<leads.length-1){ctx.strokeStyle="#cad6db";ctx.beginPath();ctx.moveTo(0,m.t+leadHeight*(leadIndex+1));ctx.lineTo(width,m.t+leadHeight*(leadIndex+1));ctx.stroke();}
  });
  const marks=sttLandmarkFractions(),markerData=[{label:"ISO",fraction:marks.iso,color:"#2678b9"},{label:"J",fraction:marks.j,color:"#c9544c"},{label:state.sttMeasurementMs===0?"J":`ST${state.sttMeasurementMs}`,fraction:marks.st,color:"#0b9290"}];
  markerData.forEach((marker,index)=>{const x=m.l+marker.fraction*plotW;ctx.fillStyle=marker.color;ctx.fillRect(x-1,m.t,2,plotH);ctx.fillStyle=marker.color;ctx.font=`700 9px ${UI_FONT}`;ctx.fillText(marker.label,Math.min(width-m.r-35,x+4),m.t+10+index*11);});
  ctx.font=`9px ${UI_FONT}`;ctx.fillStyle="#71828c";ctx.fillText(formatElapsedPrecise(waveform.start_s),m.l,height-6);ctx.fillText(formatElapsedPrecise(waveform.start_s+waveform.duration_s),Math.max(m.l,width-m.r-105),height-6);
  $("#sttWaveMeta").textContent=`${leads.length} 导联 · ${waveform.sample_rate_hz} Hz · 原始波形 · 各导联自适应显示 · ${formatElapsed(waveform.start_s)}`;
  $("#sttSelectedLeadLabel").textContent=leads.map(([lead])=>lead).join(" · ");
  renderSttMeasurements();
}

async function loadStt() {
  if(!state.caseId||!state.caseData)return;
  const requestId=++state.sttRequestId,caseId=state.caseId,total=Number(state.caseData.technical.duration_seconds_raw)||state.sttDuration;
  state.sttStart=Math.max(0,Math.min(state.sttStart,Math.max(0,total-state.sttDuration)));
  $("#sttWaveMeta").textContent="正在读取原始波形…";
  const params=new URLSearchParams({start:state.sttStart.toFixed(3),duration:state.sttDuration,leads:state.leads.slice(0,3).join(","),max_points:4000,filter:"raw"});
  const [review,waveform]=await Promise.all([state.sttReview||api(`/api/cases/${caseId}/stt-review`),api(`/api/cases/${caseId}/waveform?${params}`)]);
  if(requestId!==state.sttRequestId||caseId!==state.caseId)return;
  state.sttReview=review;state.sttWaveform=waveform;state.sttStart=waveform.start_s;
  $("#sttTimeSlider").max=Math.max(0,Math.floor(total-state.sttDuration));$("#sttTimeSlider").value=Math.round(state.sttStart);
  renderSttCapability();renderSttOverview();renderSttTrendRows();renderSttWaveform();
}

function setSttStart(value) {
  if(!state.caseData)return;
  const total=Number(state.caseData.technical.duration_seconds_raw)||state.sttDuration;
  state.sttStart=Math.max(0,Math.min(Number(value)||0,Math.max(0,total-state.sttDuration)));
  renderSttOverview();renderSttTrendRows();loadStt().catch(handleError);
}

function updateSttLeadPickerState() {
  const choices=$$('[data-stt-lead-choice]'),count=choices.filter(choice=>choice.checked).length;
  choices.forEach(choice=>{choice.disabled=!choice.checked&&count>=3;});
  $("#sttLeadSelectionCount").textContent=`已选 ${count} / 3`;$("#applySttLeadSelection").disabled=count===0;
}

function setSttLeadPickerSelection(leads) {$$('[data-stt-lead-choice]').forEach(choice=>{choice.checked=leads.includes(choice.value);});updateSttLeadPickerState();}
function openSttLeadPicker() {const dialog=$("#sttLeadDialog");if(!dialog||dialog.open)return;setSttLeadPickerSelection(state.leads);dialog.showModal();}
function applySttLeadSelection() {
  const selected=$$('[data-stt-lead-choice]:checked').map(choice=>choice.value).sort((a,b)=>ALL_LEADS.indexOf(a)-ALL_LEADS.indexOf(b));if(!selected.length||selected.length>3)return;
  state.leads=selected;persistPreviewLeads();updateWaveformModeUI();$("#sttLeadDialog").close();loadStt().catch(handleError);
}

async function openSttTwelveLead() {
  if(!state.caseId)return;
  state.start=state.sttStart;state.duration=state.sttDuration;state.filter="raw";$("#filterSelect").value="raw";updateZoomControls();goPage("review");await enterWaveformFullscreen();
}

async function saveSttReviewAnnotation() {
  if(state.demoReadonly){toast("在线 Demo 不保存复核意见","error");return;}
  if(!state.caseId||!state.sttWaveform)return;
  const finding=$("#sttFinding").value,qualityChecked=$("#sttSignalChecked").checked;
  if(finding!=="无法判读"&&!qualityChecked){toast("形成复核描述前，请先核对信号质量与伪差","error",4200);$("#sttSignalChecked").focus();return;}
  const pointLabel=state.sttMeasurementMs===0?"J 点":`J+${state.sttMeasurementMs} ms`,values=sttMeasurementValues(),rawValues=values.map(item=>`${item.lead} ${item.delta===null?"—":`${item.delta>=0?"+":""}${item.delta.toFixed(0)}`}`).join("，"),freeNote=$("#sttReviewNote").value.trim();
  const sampleRate=Number(state.sttWaveform.sample_rate_hz)||200,sampleIndex=Math.round((state.sttStart+sttLandmarkFractions().j*state.sttDuration)*sampleRate),note=[`方法：手工 ISO → ${pointLabel}`,`显示导联：${state.leads.join(" / ")}`,`相对差值（设备原始单位）：${rawValues}`,`信号质量核对：${qualityChecked?"已核对":"未核对"}`,freeNote].filter(Boolean).join("；").slice(0,2000);
  await api(`/api/cases/${state.caseId}/annotations`,{method:"POST",body:JSON.stringify({sample_index:sampleIndex,lead:state.leads.length===1?state.leads[0]:"全部",category:"note",label:`ST-T 人工复核：${finding}`,note})});
  toast("ST‑T 复核意见已保存为人工标注");$("#sttReviewNote").value="";
}

function setEditMode(mode, rerender=true) {
  state.editMode=mode==="library"?"library":"cluster";
  const workbench=$("#editWorkbench"),library=$("#editLibraryWorkbench");if(workbench)workbench.hidden=state.editMode!=="cluster";if(library)library.hidden=state.editMode!=="library";
  $$('[data-edit-mode]').forEach(button=>button.setAttribute("aria-selected",String(button.dataset.editMode===state.editMode)));
  if(rerender&&state.currentPage==="edit")requestAnimationFrame(()=>{if(state.editMode==="cluster"){renderEditOverview();renderEditScatter();renderEditGallery();renderEditWaveform();renderEditDensity();}else renderEditLibrary();});
}

function editDescriptor() {
  const source=EDIT_SOURCE_CLASSES.find(item=>item.key===state.editSelectedClass);
  if(source)return {...source,type:"source",count:Number(state.caseData?.calculated?.group_counts?.[String(source.group)]||0)};
  const id=Number(String(state.editSelectedClass).replace("custom-","")),item=state.editTemplates.find(template=>template.id===id);
  return item?{...item,key:`custom-${item.id}`,type:"custom",code:"自",description:`${item.rhythm_family} · 医生自建模板`,color:"#1a8a70",count:item.beat_count}:EDIT_SOURCE_CLASSES[0];
}

function editClassSamples(descriptor=editDescriptor()) {
  if(descriptor.type==="custom")return descriptor.sample_indices||[];
  return (state.editScatterData?.points||[]).filter(point=>point.group===descriptor.group).map(point=>point.sample_index);
}

function evenEditSamples(samples,limit) {
  const unique=[...new Set(samples)].sort((a,b)=>a-b);if(unique.length<=limit)return unique;
  return Array.from({length:limit},(_,index)=>unique[Math.round(index*(unique.length-1)/(limit-1))]);
}

function editCanvasHeight(canvas,fallback,minimum=48) {
  canvas.style.height="";const measured=Math.round(canvas.getBoundingClientRect().height);return Math.max(minimum,measured||fallback);
}

function editClassLabel(key) {
  const source=EDIT_SOURCE_CLASSES.find(item=>item.key===key);if(source)return source.code;
  const id=Number(String(key||"").replace("custom-","")),template=state.editTemplates.find(item=>item.id===id);return template?.name||"上级模板";
}

function nextEditTemplateName() {
  const descriptor=editDescriptor(),raw=descriptor.type==="source"?descriptor.code:String(descriptor.name||"T").match(/^[A-Za-z]+/)?.[0]||"T",prefix=raw.slice(0,4);let index=1;const names=new Set(state.editTemplates.map(item=>item.name));while(names.has(`${prefix}${index}`))index+=1;return `${prefix}${index}`;
}

function renderEditClasses() {
  if(!state.caseData)return;
  const groups=state.caseData.calculated?.group_counts||{};
  $("#editSourceClassList").innerHTML=EDIT_SOURCE_CLASSES.map(item=>`<button class="edit-class-item source-${item.code==='X'?'noise':item.code}" type="button" data-edit-class="${item.key}" aria-pressed="${state.editSelectedClass===item.key}"><span>${item.code}</span><div><strong>${item.name}</strong><small>${item.description}</small></div><em>${fmtNumber(groups[String(item.group)]||0)}</em></button>`).join("");
  $("#editCustomClassList").innerHTML=state.editTemplates.length?state.editTemplates.map(item=>`<button class="edit-class-item custom" type="button" title="来自 ${escapeHtml(editClassLabel(item.source_class))} · ${escapeHtml(item.rhythm_family)}" data-edit-class="custom-${item.id}" aria-pressed="${state.editSelectedClass===`custom-${item.id}`}"><span>${escapeHtml(item.name.slice(0,3))}</span><div><strong>${escapeHtml(item.name)}</strong><small>来自 ${escapeHtml(editClassLabel(item.source_class))} · ${escapeHtml(item.lead)}</small></div><em>${fmtNumber(item.beat_count)}</em></button>`).join(""):`<div class="edit-class-empty">尚无医生模板。<br>在下方形态集合中框选创建。</div>`;
  $("#editClassCount").textContent=`4 + ${state.editTemplates.length}`;
  const descriptor=editDescriptor();
  $("#editGalleryTitle").textContent=`${descriptor.name} · 代表片段`;
  $("#editGalleryDescription").textContent=descriptor.type==="custom"?`来自 ${editClassLabel(descriptor.source_class)} · ${descriptor.rhythm_family} · 点击定位`:`${descriptor.description} · 点击片段定位`;
  $("#editGalleryCount").textContent=`${fmtNumber(descriptor.count||editClassSamples(descriptor).length)} 搏`;
  $("#editTemplateInfo").hidden=descriptor.type!=="custom";
  $("#editDensityPrimaryLabel").textContent=descriptor.name||"当前类别";
  const switcher=$("#editClassSwitcher");
  if(switcher)switcher.innerHTML=EDIT_SOURCE_CLASSES.map((item,index)=>{const active=state.editSelectedClass===item.key,count=Number(groups[String(item.group)]||0);return `<button type="button" role="tab" data-edit-class="${item.key}" aria-selected="${active}" aria-pressed="${active}" aria-keyshortcuts="${item.code}" class="type-${item.code.toLowerCase()}"><kbd>${item.code}</kbd><span>${escapeHtml(item.name)}</span><em>${fmtNumber(count)}</em><small>${index+1}</small></button>`}).join("");
  $("#editActiveClassName").textContent=descriptor.name||"当前类别";
  $("#editActiveClassCount").textContent=`${fmtNumber(descriptor.count||editClassSamples(descriptor).length)} 搏 · ${descriptor.type==="custom"?"医生模板":"源 EBI"}`;
}

function renderEditOverview() {
  if(!state.caseData||!state.trend||!state.editRr)return;
  const trendCanvas=$("#editTrendCanvas"),trendContext=canvasContext(trendCanvas,editCanvasHeight(trendCanvas,90,48)),trendCtx=trendContext.ctx,tw=trendContext.width,th=trendContext.height,tm={l:38,r:12,t:7,b:17},plotW=tw-tm.l-tm.r,plotH=th-tm.t-tm.b,total=Math.max(1,state.caseData.technical.duration_seconds_raw),points=state.trend.points||[];
  trendCtx.clearRect(0,0,tw,th);trendCtx.fillStyle="#fff";trendCtx.fillRect(0,0,tw,th);trendCtx.strokeStyle="#e4eaed";[0,.5,1].forEach(f=>{const y=tm.t+plotH*f;trendCtx.beginPath();trendCtx.moveTo(tm.l,y);trendCtx.lineTo(tw-tm.r,y);trendCtx.stroke();});
  const hrs=points.map(point=>Number(point.hr)).filter(Number.isFinite),minHr=Math.max(20,Math.min(...hrs,50)-10),maxHr=Math.min(240,Math.max(...hrs,120)+10),range=Math.max(20,maxHr-minHr),startX=tm.l+state.editStart/total*plotW,endX=tm.l+Math.min(total,state.editStart+state.editDuration)/total*plotW;
  trendCtx.fillStyle="rgba(11,146,144,.12)";trendCtx.fillRect(startX,tm.t,Math.max(3,endX-startX),plotH);trendCtx.strokeStyle="#0b9290";trendCtx.strokeRect(startX+.5,tm.t+.5,Math.max(2,endX-startX-1),plotH-1);trendCtx.beginPath();points.forEach((point,index)=>{const x=tm.l+point.time_s/total*plotW,y=tm.t+plotH-(Number(point.hr)-minHr)/range*plotH;index?trendCtx.lineTo(x,y):trendCtx.moveTo(x,y)});trendCtx.strokeStyle="#2678b9";trendCtx.lineWidth=1.25;trendCtx.stroke();trendCtx.fillStyle="#71828c";trendCtx.font=`9px ${UI_FONT}`;trendCtx.fillText(`${Math.round(maxHr)}`,3,tm.t+5);trendCtx.fillText(`${Math.round(minHr)}`,3,tm.t+plotH);trendCtx.fillText("D1 00h",tm.l,th-5);trendCtx.fillText(formatElapsed(total),Math.max(tm.l,tw-tm.r-63),th-5);
  $("#editWindowLabel").textContent=`${formatElapsed(state.editStart)}–${formatElapsed(state.editStart+state.editDuration)}`;
  const histogram=$("#editHistogramCanvas"),histContext=canvasContext(histogram,editCanvasHeight(histogram,90,48)),ctx=histContext.ctx,w=histContext.width,h=histContext.height,m={l:34,r:10,t:7,b:17},data=state.editRr.histogram||[],max=Math.max(1,...data.map(item=>item.count)),barW=(w-m.l-m.r)/Math.max(1,data.length),plotHeight=h-m.t-m.b;
  ctx.clearRect(0,0,w,h);ctx.fillStyle="#fff";ctx.fillRect(0,0,w,h);ctx.strokeStyle="#e4eaed";ctx.beginPath();ctx.moveTo(m.l,m.t+plotHeight+.5);ctx.lineTo(w-m.r,m.t+plotHeight+.5);ctx.stroke();data.forEach((item,index)=>{const bh=item.count/max*plotHeight;ctx.fillStyle=index%2?"#42b7b1":"#168f8b";ctx.fillRect(m.l+index*barW+1,m.t+plotHeight-bh,Math.max(1,barW-2),bh)});ctx.font=`9px ${UI_FONT}`;ctx.fillStyle="#71828c";ctx.fillText("300",m.l,h-5);ctx.fillText("2000 ms",Math.max(m.l,w-m.r-48),h-5);$("#editHistogramRange").textContent="300–2000 ms";
}

function renderEditScatter() {
  const data=state.editScatterData;if(!data)return;
  const canvas=$("#editScatterCanvas"),canvasData=canvasContext(canvas,editCanvasHeight(canvas,190,88)),ctx=canvasData.ctx,width=canvasData.width,height=canvasData.height,m={l:31,r:9,t:10,b:22},plotW=width-m.l-m.r,plotH=height-m.t-m.b,bounds=data.bounds||{x_min:0,x_max:2000,y_min:0,y_max:2000},selected=editDescriptor(),selectedSet=new Set(selected.type==="custom"?selected.sample_indices:[]);
  ctx.clearRect(0,0,width,height);ctx.fillStyle="#f8fafb";ctx.fillRect(0,0,width,height);ctx.strokeStyle="#dbe5e8";[0,.25,.5,.75,1].forEach(f=>{const x=m.l+plotW*f,y=m.t+plotH*f;ctx.beginPath();ctx.moveTo(x,m.t);ctx.lineTo(x,m.t+plotH);ctx.moveTo(m.l,y);ctx.lineTo(m.l+plotW,y);ctx.stroke();});ctx.strokeStyle="#adc0c7";ctx.setLineDash([4,4]);ctx.beginPath();ctx.moveTo(m.l,m.t+plotH);ctx.lineTo(m.l+plotW,m.t);ctx.stroke();ctx.setLineDash([]);
  for(const point of data.points||[]){const x=m.l+(point.x-bounds.x_min)/Math.max(1,bounds.x_max-bounds.x_min)*plotW,y=m.t+plotH-(point.y-bounds.y_min)/Math.max(1,bounds.y_max-bounds.y_min)*plotH,isSelected=selected.type==="source"?point.group===selected.group:selectedSet.has(point.sample_index);ctx.fillStyle=isSelected?selected.color:"rgba(113,130,140,.18)";const radius=isSelected?2.1:1.05;ctx.beginPath();ctx.arc(x,y,radius,0,Math.PI*2);ctx.fill();}
  ctx.fillStyle="#71828c";ctx.font=`9px ${UI_FONT}`;ctx.fillText("RR(i+1)",3,10);ctx.fillText("0",m.l-10,m.t+plotH+3);ctx.fillText(`${Math.round(bounds.x_max)}`,Math.max(m.l,width-m.r-30),height-9);ctx.fillText("RR(i) ms",Math.max(m.l,width-m.r-49),height-9);
}

function drawEditStrip(canvas,item) {
  const height=editCanvasHeight(canvas,state.editMode==="library"?100:76,12),{ctx,width}=canvasContext(canvas,height),values=item?.leads?.[state.editLead]||Object.values(item?.leads||{})[0]||[],m={l:7,r:7,t:3,b:3},plotW=width-m.l-m.r,plotH=height-m.t-m.b;
  ctx.clearRect(0,0,width,height);ctx.fillStyle="#fbfdfd";ctx.fillRect(0,0,width,height);ctx.strokeStyle="#e3eaed";[.25,.5,.75].forEach(f=>{const y=m.t+plotH*f;ctx.beginPath();ctx.moveTo(m.l,y);ctx.lineTo(width-m.r,y);ctx.stroke();});
  const magnitudes=values.map(value=>Math.abs(Number(value)||0)).sort((a,b)=>a-b),limit=Math.max(40,magnitudes[Math.floor(magnitudes.length*.96)]||40),scale=plotH*.42/limit,baseline=m.t+plotH*.53;ctx.strokeStyle="#263f49";ctx.lineWidth=1.05;ctx.beginPath();values.forEach((value,index)=>{const x=m.l+index/Math.max(1,values.length-1)*plotW,y=baseline-(Number(value)||0)*scale;index?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.stroke();const anchor=Math.max(0,Math.min(1,Number(item?.anchor_offset_s||.6)/Math.max(.001,Number(item?.duration_s)||1.6)));ctx.strokeStyle="#0b9290";ctx.beginPath();ctx.moveTo(m.l+anchor*plotW,m.t);ctx.lineTo(m.l+anchor*plotW,m.t+plotH);ctx.stroke();
}

function editSourceCode(item) {return ({1:"N",2:"S",3:"V",34:"X"})[Number(item?.group)]||String(item?.label||"O").toUpperCase();}
function editEffectiveCode(item) {return item?.class_code||state.editBeatOverrides.get(Number(item?.sample_index))?.class_code||editSourceCode(item);}
function editBeatType(code){const type=ECGBeatEngine.types[code];return type?{...type,color:BEAT_COLORS[type.group]||"#a37827"}:(EDIT_BEAT_TYPES[code]||EDIT_BEAT_TYPES.O);}
function editSelected(sample) {return state.editSelectedSamples.has(Number(sample));}

function refreshBeatOverrideViews() {
  if(state.currentPage==="review"){renderWaveform();renderVisibleEvents();renderScatterSelectionList();}
  if(state.currentPage==="edit"){renderEditGallery();renderEditWaveform();if(state.editMode==="library")renderEditLibrary();}
}

function closeBeatRelabelMenu({keepTarget=false}={}) {
  if(typeof beatEditor!=="undefined")beatEditor.invalidate();
  const menu=$("#beatRelabelMenu");if(!menu)return;
  try{if(menu.matches(":popover-open"))menu.hidePopover();}catch(_){/* fallback uses hidden */}
  menu.hidden=true;
  if(!keepTarget){state.beatRelabelTarget=null;refreshBeatOverrideViews();}
}

function nearestBeatForRelabel(canvas,waveform,clientX,surface,maxDistance=44) {
  const beats=waveform?.beats||[];if(!beats.length)return null;
  const rect=canvas.getBoundingClientRect(),geometry=surface==="review"?{l:0,w:rect.width}:editWaveGeometry(rect.width,rect.height),localX=Math.max(geometry.l,Math.min(geometry.l+geometry.w,clientX-rect.left)),fraction=(localX-geometry.l)/Math.max(1,geometry.w),time=waveform.start_s+fraction*waveform.duration_s;
  const nearest=beats.reduce((best,beat)=>!best||Math.abs(beat.time_s-time)<Math.abs(best.time_s-time)?beat:best,null),beatX=geometry.l+(nearest.time_s-waveform.start_s)/Math.max(.001,waveform.duration_s)*geometry.w;
  return Math.abs(beatX-localX)<=maxDistance?nearest:null;
}

function positionBeatRelabelMenu(menu,clientX,clientY) {
  const gap=8,proposedLeft=clientX+8,proposedTop=clientY+8;
  menu.style.left=`${Math.max(12,Math.min(window.innerWidth-304,proposedLeft))}px`;
  menu.style.top=`${Math.max(70,proposedTop)}px`;
  requestAnimationFrame(()=>{const rect=menu.getBoundingClientRect();menu.style.left=`${Math.max(12,Math.min(window.innerWidth-rect.width-12,rect.left))}px`;menu.style.top=`${Math.max(70,Math.min(window.innerHeight-rect.height-gap,rect.top))}px`;});
}

function openBeatRelabelMenu(event,canvas,waveform,surface="review",keyboard=false) {
  if(typeof beatEditor!=="undefined")return beatEditor.open(event,canvas,waveform,surface,keyboard);
  if(!state.caseId||!canvas||!waveform)return;
  const rect=canvas.getBoundingClientRect(),clientX=keyboard?rect.left+rect.width/2:event.clientX,clientY=keyboard?rect.top+Math.min(rect.height/2,180):event.clientY,nearest=nearestBeatForRelabel(canvas,waveform,clientX,surface,keyboard?Infinity:44);
  if(!nearest){toast("请在心搏标记附近右击","error");return;}
  const sample=Number(nearest.sample_index),sourceCode=editSourceCode(nearest),effectiveCode=editEffectiveCode(nearest),type=EDIT_BEAT_TYPES[effectiveCode]||EDIT_BEAT_TYPES.O,menu=$("#beatRelabelMenu");
  closeBeatRelabelMenu({keepTarget:true});
  state.beatRelabelTarget={caseId:state.caseId,sample_index:sample,time_s:Number(nearest.time_s),sourceCode,effectiveCode,surface};
  if(surface!=="review"){state.editSelectedSamples=new Set([sample]);state.editSelectionAnchor=sample;state.editSelectedSample=sample;}
  $("#beatRelabelCurrentCode").textContent=effectiveCode;
  $("#beatRelabelCurrentCode").style.cssText=`background:${type.color}1f;color:${type.color}`;
  $("#beatRelabelMeta").textContent=`${formatElapsedPrecise(nearest.time_s)} · RR ${nearest.rr_ms??"—"} ms · 当前 ${effectiveCode}`;
  $("#beatRelabelSource").textContent=`源 EBI：${sourceCode}`;
  $("#restoreBeatRelabel").disabled=!state.editBeatOverrides.has(sample);
  $("#beatRelabelLeadSettings").hidden=surface!=="review";
  $$('[data-beat-relabel-code]').forEach(button=>button.setAttribute("aria-current",String(button.dataset.beatRelabelCode===effectiveCode)));
  menu.hidden=false;positionBeatRelabelMenu(menu,clientX,clientY);
  try{if(!menu.matches(":popover-open"))menu.showPopover();}catch(_){/* fallback uses hidden */}
  refreshBeatOverrideViews();
  setTimeout(()=>($(`[data-beat-relabel-code="${effectiveCode}"]`,menu)||$('[data-beat-relabel-code]',menu))?.focus({preventScroll:true}),0);
}

async function applyBeatRelabelTarget(classCode) {
  const target=state.beatRelabelTarget,type=EDIT_BEAT_TYPES[classCode];if(!target||!type)return;
  const result=await api(`/api/cases/${state.caseId}/beat-overrides`,{method:"PUT",body:JSON.stringify({sample_indices:[target.sample_index],class_code:type.code})});
  if(target.caseId!==state.caseId)return;
  (result.items||[]).forEach(item=>state.editBeatOverrides.set(Number(item.sample_index),item));
  closeBeatRelabelMenu();toast(`已人工改为 ${type.code} · ${type.name}`);
}

async function restoreBeatRelabelTarget() {
  const target=state.beatRelabelTarget;if(!target)return;
  const result=await api(`/api/cases/${state.caseId}/beat-overrides`,{method:"DELETE",body:JSON.stringify({sample_indices:[target.sample_index]})});
  if(target.caseId!==state.caseId)return;
  state.editBeatOverrides.delete(target.sample_index);closeBeatRelabelMenu();toast(result.changed?`已恢复源类型 ${target.sourceCode}`:"当前心搏已是源类型");
}

function selectEditSample(sample,time,event=null,items=state.editTemplateStrips) {
  const value=Number(sample),ordered=items.map(item=>Number(item.sample_index));
  if(event?.shiftKey&&state.editSelectionAnchor!==null&&ordered.includes(state.editSelectionAnchor)&&ordered.includes(value)){
    const start=ordered.indexOf(state.editSelectionAnchor),end=ordered.indexOf(value);for(const item of ordered.slice(Math.min(start,end),Math.max(start,end)+1))state.editSelectedSamples.add(item);
  }else if(event&&(event.metaKey||event.ctrlKey)){state.editSelectedSamples.has(value)?state.editSelectedSamples.delete(value):state.editSelectedSamples.add(value);state.editSelectionAnchor=value;
  }else{state.editSelectedSamples=new Set([value]);state.editSelectionAnchor=value;}
  state.editSelectedSample=value;renderEditGallery();renderEditWaveform();renderEditLibrary();
  if(Number.isFinite(Number(time))&&(Number(time)<state.editStart||Number(time)>state.editStart+state.editDuration))setEditStart(Number(time)-state.editDuration*.35);
}

async function applyEditBeatType(classCode) {
  if(typeof beatEditor!=="undefined")return beatEditor.quickEdit(classCode);
  if(!state.caseId||!state.editSelectedSamples.size)return toast("请先选中一个或多个心搏","error");
  const type=EDIT_BEAT_TYPES[classCode];if(!type)return;
  const caseId=state.caseId,samples=[...state.editSelectedSamples];const result=await api(`/api/cases/${caseId}/beat-overrides`,{method:"PUT",body:JSON.stringify({sample_indices:samples,class_code:type.code})});
  if(caseId!==state.caseId)return;
  (result.items||[]).forEach(item=>state.editBeatOverrides.set(Number(item.sample_index),item));refreshBeatOverrideViews();toast(`${samples.length} 搏已人工改为 ${type.code} · ${type.name}`);
}

async function restoreEditBeatType() {
  if(typeof beatEditor!=="undefined")return beatEditor.restore();
  if(!state.caseId||!state.editSelectedSamples.size)return toast("请先选中心搏","error");
  const caseId=state.caseId,samples=[...state.editSelectedSamples];const result=await api(`/api/cases/${caseId}/beat-overrides`,{method:"DELETE",body:JSON.stringify({sample_indices:samples})});
  if(caseId!==state.caseId)return;
  samples.forEach(sample=>state.editBeatOverrides.delete(sample));refreshBeatOverrideViews();toast(`已恢复 ${result.changed||0} 搏的源 EBI 类型`);
}

function renderEditGallery() {
  const gallery=$("#editTemplateGallery");if(!gallery)return;
  if(!state.editTemplateStrips.length){gallery.innerHTML=`<div class="edit-gallery-empty">当前类别没有可读取的代表片段</div>`;renderEditDensity();return;}
  const shown=state.editTemplateStrips.slice(0,10);gallery.innerHTML=shown.map((item,index)=>{const code=editEffectiveCode(item),override=state.editBeatOverrides.has(Number(item.sample_index));return `<button class="edit-template-strip ${editSelected(item.sample_index)?"active":""} ${override?"manual-override":""}" type="button" data-edit-sample="${item.sample_index}" data-edit-time="${item.time_s}" aria-pressed="${editSelected(item.sample_index)}"><canvas height="76" aria-label="${escapeHtml(editDescriptor().name)}代表片段 ${index+1}"></canvas><span><strong>${code}${override?" · 人工":""}</strong><small>${formatElapsed(item.time_s)}</small></span></button>`}).join("");
  $$(".edit-template-strip",gallery).forEach((button,index)=>drawEditStrip($("canvas",button),shown[index]));renderEditDensity();
}

function drawEditDensityCanvas(canvas,items,color,interactive=false) {
  const height=editCanvasHeight(canvas,interactive?190:92,54),canvasData=canvasContext(canvas,height),ctx=canvasData.ctx,width=canvasData.width,m={l:8,r:8,t:8,b:8},plotW=width-m.l-m.r,plotH=height-m.t-m.b;
  ctx.clearRect(0,0,width,height);ctx.fillStyle="#07181f";ctx.fillRect(0,0,width,height);ctx.strokeStyle="#1d3741";ctx.lineWidth=1;[.25,.5,.75].forEach(f=>{const y=m.t+plotH*f;ctx.beginPath();ctx.moveTo(m.l,y);ctx.lineTo(width-m.r,y);ctx.stroke();});[.25,.5,.75].forEach(f=>{const x=m.l+plotW*f;ctx.beginPath();ctx.moveTo(x,m.t);ctx.lineTo(x,m.t+plotH);ctx.stroke();});
  if(!items?.length){if(interactive)state.editMorphTraceGeometry=[];ctx.fillStyle="#748b94";ctx.font=`10px ${UI_FONT}`;ctx.textAlign="center";ctx.fillText("当前类别暂无可框选的形态片段",width/2,height/2);ctx.textAlign="left";return;}
  const all=items.flatMap(item=>item?.leads?.[state.editLead]||Object.values(item?.leads||{})[0]||[]),magnitudes=all.map(value=>Math.abs(Number(value)||0)).sort((a,b)=>a-b),limit=Math.max(40,magnitudes[Math.floor(magnitudes.length*.97)]||40),scale=plotH*.43/limit,baseline=m.t+plotH*.53,selectedSet=new Set(state.editSelection?.source==="morphology"?state.editSelection.samples:[]),traces=items.map(item=>{const values=item?.leads?.[state.editLead]||Object.values(item?.leads||{})[0]||[],points=values.map((value,index)=>({x:m.l+index/Math.max(1,values.length-1)*plotW,y:baseline-(Number(value)||0)*scale}));return {item,points};});
  const strokeTrace=(trace,selected=false,representative=false)=>{ctx.strokeStyle=selected?"#f4c74e":color;ctx.globalAlpha=selected?0.96:(representative?0.82:0.16);ctx.lineWidth=selected?1.55:representative?1.1:.75;ctx.beginPath();trace.points.forEach((point,index)=>{index?ctx.lineTo(point.x,point.y):ctx.moveTo(point.x,point.y)});ctx.stroke();};
  traces.filter(trace=>!selectedSet.has(trace.item.sample_index)).forEach(trace=>strokeTrace(trace));if(!selectedSet.size&&traces.length)strokeTrace(traces[Math.floor(traces.length/2)],false,true);traces.filter(trace=>selectedSet.has(trace.item.sample_index)).forEach(trace=>strokeTrace(trace,true));ctx.globalAlpha=1;
  if(interactive){state.editMorphTraceGeometry=traces;const box=state.editMorphDraft||state.editSelection?.source==="morphology"&&state.editSelection;if(box){const x1=Math.min(box.x1,box.x2)*width,x2=Math.max(box.x1,box.x2)*width,y1=Math.min(box.y1,box.y2)*height,y2=Math.max(box.y1,box.y2)*height;ctx.fillStyle="rgba(35,197,184,.13)";ctx.fillRect(x1,y1,Math.max(1,x2-x1),Math.max(1,y2-y1));ctx.strokeStyle="#46d1c4";ctx.lineWidth=1.3;ctx.setLineDash([5,3]);ctx.strokeRect(x1+.5,y1+.5,Math.max(1,x2-x1-1),Math.max(1,y2-y1-1));ctx.setLineDash([]);ctx.fillStyle="#d8fffb";ctx.font=`700 9px ${UI_FONT}`;ctx.fillText(`${state.editSelection?.source==="morphology"?state.editSelection.samples.length:0} 搏`,Math.min(width-38,x1+5),Math.max(13,y1+13));}}
}

function renderEditDensity() {
  if(!$("#editDensityPrimary"))return;drawEditDensityCanvas($("#editDensityPrimary"),state.editTemplateStrips,"#79e18b",true);drawEditDensityCanvas($("#editDensitySelection"),state.editSelectionStrips,"#f0c85a");$("#editMorphologyCount").textContent=`${state.editTemplateStrips.length} 代表搏`;$("#editMorphSelectionLabel").textContent=state.editSelection?.source==="morphology"?`${state.editSelection.samples.length} 搏 · 可派生新模板`:"尚未选择";$("#clearEditSelection").disabled=!state.editSelection;
}

function editWaveGeometry(rectWidth,rectHeight) {return {l:50,r:15,t:27,b:24,w:Math.max(1,rectWidth-65),h:Math.max(1,rectHeight-51)};}

function renderEditWaveform(target="#editWaveformCanvas",metaTarget="#editWaveMeta") {
  const waveform=state.editWaveform;if(!waveform)return;
  const canvas=$(target);if(!canvas)return;const canvasData=canvasContext(canvas,editCanvasHeight(canvas,target.includes("Library")?250:320,170)),ctx=canvasData.ctx,width=canvasData.width,height=canvasData.height,g=editWaveGeometry(width,height),leads=Object.entries(waveform.leads||{}),leadHeight=g.h/Math.max(1,leads.length);
  ctx.clearRect(0,0,width,height);ctx.fillStyle="#fff";ctx.fillRect(0,0,width,height);for(let x=g.l;x<=g.l+g.w;x+=10){ctx.strokeStyle=(x-g.l)%50===0?"rgba(214,101,88,.22)":"rgba(214,101,88,.09)";ctx.beginPath();ctx.moveTo(x,g.t);ctx.lineTo(x,g.t+g.h);ctx.stroke();}for(let y=g.t;y<=g.t+g.h;y+=10){ctx.strokeStyle=(y-g.t)%50===0?"rgba(214,101,88,.22)":"rgba(214,101,88,.09)";ctx.beginPath();ctx.moveTo(g.l,y);ctx.lineTo(g.l+g.w,y);ctx.stroke();}
  leads.forEach(([lead,values],leadIndex)=>{const baseline=g.t+leadHeight*(leadIndex+.53),sampled=values.filter((_,index)=>index%Math.max(1,Math.ceil(values.length/600))===0).map(value=>Math.abs(Number(value)||0)).sort((a,b)=>a-b),limit=Math.max(60,sampled[Math.floor(sampled.length*.96)]||60),scale=leadHeight*.34/limit;ctx.strokeStyle="#d7e1e5";ctx.beginPath();ctx.moveTo(g.l,baseline);ctx.lineTo(g.l+g.w,baseline);ctx.stroke();ctx.fillStyle=lead===state.editLead?"#087777":"#405563";ctx.font=`700 10px ${UI_FONT}`;ctx.fillText(lead,14,baseline+3);ctx.strokeStyle=lead===state.editLead?"#1d3944":"#526873";ctx.lineWidth=lead===state.editLead?1.15:.95;ctx.beginPath();values.forEach((value,index)=>{const x=g.l+index/Math.max(1,values.length-1)*g.w,y=baseline-(Number(value)||0)*scale;index?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.stroke();});
  (waveform.beats||[]).forEach(beat=>{const fraction=(beat.time_s-waveform.start_s)/Math.max(.001,waveform.duration_s);if(fraction<0||fraction>1)return;const x=g.l+fraction*g.w,code=editEffectiveCode(beat),color=EDIT_BEAT_TYPES[code]?.color||"#7b858a",selected=editSelected(beat.sample_index);ctx.fillStyle=color;ctx.fillRect(x-1,g.t,2,9);ctx.font=`700 8px ${UI_FONT}`;ctx.fillText(code,x+2,g.t+8);if(selected){ctx.fillStyle="rgba(239,140,33,.13)";ctx.fillRect(x-10,g.t,20,g.h);ctx.strokeStyle="#ef8c21";ctx.strokeRect(x-10+.5,g.t+.5,19,g.h-1);}});
  ctx.fillStyle="#71828c";ctx.font=`9px ${UI_FONT}`;ctx.fillText(formatElapsedPrecise(waveform.start_s),g.l,height-6);ctx.fillText(formatElapsedPrecise(waveform.start_s+waveform.duration_s),Math.max(g.l,width-g.r-105),height-6);const meta=$(metaTarget);if(meta)meta.textContent=`${leads.length} 导联 · ${waveform.sample_rate_hz} Hz · 0.5–40 Hz 显示滤波 · ${formatElapsed(waveform.start_s)}`;
}

function renderEditLibraryAnalytics() {
  const histogram=$("#editLibraryHistogramCanvas"),data=state.editRr?.histogram||[];
  if(histogram){const {ctx,width,height}=canvasContext(histogram,editCanvasHeight(histogram,92,54)),m={l:20,r:7,t:7,b:14},max=Math.max(1,...data.map(item=>item.count)),bar=(width-m.l-m.r)/Math.max(1,data.length);ctx.clearRect(0,0,width,height);ctx.fillStyle="#fff";ctx.fillRect(0,0,width,height);data.forEach((item,index)=>{const h=item.count/max*(height-m.t-m.b);ctx.fillStyle="#29a7a2";ctx.fillRect(m.l+index*bar+1,height-m.b-h,Math.max(1,bar-2),h)});ctx.fillStyle="#71828c";ctx.font=`8px ${UI_FONT}`;ctx.fillText("300",m.l,height-3);ctx.fillText("2000",width-32,height-3);}
  const trend=$("#editLibraryTrendCanvas"),points=state.trend?.points||[];
  if(trend){const {ctx,width,height}=canvasContext(trend,editCanvasHeight(trend,54,42)),total=Math.max(1,Number(state.caseData?.technical?.duration_seconds_raw)||1),values=points.map(item=>Number(item.hr)).filter(Number.isFinite),min=Math.min(...values,40),max=Math.max(...values,120),range=Math.max(1,max-min);ctx.clearRect(0,0,width,height);ctx.strokeStyle="#dce6e9";ctx.beginPath();ctx.moveTo(0,height-8);ctx.lineTo(width,height-8);ctx.stroke();ctx.strokeStyle="#2780b8";ctx.beginPath();points.forEach((item,index)=>{const x=Number(item.time_s)/total*width,y=4+(max-Number(item.hr))/range*(height-14);index?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.stroke();}
  const scatter=$("#editLibraryScatterCanvas"),scatterData=state.editScatterData;
  if(scatter&&scatterData){const {ctx,width,height}=canvasContext(scatter,editCanvasHeight(scatter,146,74)),m={l:20,r:6,t:6,b:16},bounds=scatterData.bounds,plotW=width-m.l-m.r,plotH=height-m.t-m.b,descriptor=editDescriptor(),custom=new Set(descriptor.sample_indices||[]);ctx.clearRect(0,0,width,height);ctx.fillStyle="#f8fafb";ctx.fillRect(0,0,width,height);ctx.strokeStyle="#dce6e9";[0,.5,1].forEach(f=>{ctx.beginPath();ctx.moveTo(m.l+plotW*f,m.t);ctx.lineTo(m.l+plotW*f,m.t+plotH);ctx.moveTo(m.l,m.t+plotH*f);ctx.lineTo(m.l+plotW,m.t+plotH*f);ctx.stroke()});for(const point of scatterData.points||[]){const x=m.l+(point.x-bounds.x_min)/Math.max(1,bounds.x_max-bounds.x_min)*plotW,y=m.t+plotH-(point.y-bounds.y_min)/Math.max(1,bounds.y_max-bounds.y_min)*plotH,active=descriptor.type==="source"?point.group===descriptor.group:custom.has(point.sample_index);ctx.fillStyle=active?descriptor.color:"rgba(113,130,140,.18)";ctx.fillRect(x,y,active?2:1,active?2:1);}}
}

function renderEditLibraryDeck() {
  const deck=$("#editLibraryDeck");if(!deck)return;const groups=state.caseData?.calculated?.group_counts||{},items=[...EDIT_SOURCE_CLASSES.map(item=>({...item,count:Number(groups[String(item.group)]||0),type:"source"})),...state.editTemplates.map(item=>({...item,key:`custom-${item.id}`,code:(item.name||"自").slice(0,3),color:"#1a8a70",count:item.beat_count,type:"custom"}))];
  deck.innerHTML=items.map((item,index)=>`<button type="button" class="edit-library-deck-card ${state.editSelectedClass===item.key?"active":""}" data-edit-class="${item.key}" aria-pressed="${state.editSelectedClass===item.key}"><span><strong>${escapeHtml(item.code)}</strong><small>${fmtNumber(item.count||0)} 搏</small></span><canvas height="52" aria-hidden="true"></canvas><em>${escapeHtml(item.name)}</em></button>`).join("");
  $$(".edit-library-deck-card",deck).forEach((button,index)=>drawEditStrip($("canvas",button),state.editTemplateStrips[index%Math.max(1,state.editTemplateStrips.length)]));$("#editLibraryDeckCount").textContent=`${items.length} 类`;
}

function renderEditLibraryMatrix() {
  const matrix=$("#editLibraryMatrix");if(!matrix)return;const filter=state.editLibraryFilter,shown=state.editTemplateStrips.filter(item=>filter==="all"||editEffectiveCode(item)===filter).slice(0,18);$("#editLibraryFilterCount").textContent=`${shown.length} 个代表搏`;$("#editLibraryMatrixTitle").textContent=`${editDescriptor().name} · 代表心搏库`;
  $$('[data-edit-library-filter]').forEach(button=>button.setAttribute("aria-pressed",String(button.dataset.editLibraryFilter===filter)));
  matrix.innerHTML=shown.length?shown.map((item,index)=>{const code=editEffectiveCode(item),manual=state.editBeatOverrides.has(Number(item.sample_index));return `<button class="edit-library-beat ${editSelected(item.sample_index)?"selected":""} ${manual?"manual":""}" type="button" data-edit-sample="${item.sample_index}" data-edit-time="${item.time_s}" aria-pressed="${editSelected(item.sample_index)}"><span><b>${code}</b><small>${manual?"人工":"源类型"}</small></span><canvas height="70" aria-label="代表心搏 ${index+1}"></canvas><em>${formatElapsed(item.time_s)}</em></button>`}).join(""):`<div class="edit-gallery-empty">当前筛选没有代表心搏</div>`;
  $$(".edit-library-beat",matrix).forEach((button,index)=>drawEditStrip($("canvas",button),shown[index]));const count=state.editSelectedSamples.size;$("#editLibrarySelectionCount").textContent=count?`已选 ${count} 搏 · 可键盘改型`:"未选择";$("#restoreEditBeatType").disabled=!count;
}

function renderEditLibraryNavigator() {
  const canvas=$("#editLibraryNavigatorCanvas"),wave=state.editWaveform;if(!canvas||!wave)return;const values=wave.leads?.[state.editLead]||Object.values(wave.leads||{})[0]||[],{ctx,width,height}=canvasContext(canvas,editCanvasHeight(canvas,34,20)),middle=height/2,magnitude=Math.max(50,...values.filter((_,i)=>i%20===0).map(value=>Math.abs(Number(value)||0))),scale=height*.36/magnitude;ctx.clearRect(0,0,width,height);ctx.fillStyle="#f2f6f7";ctx.fillRect(0,0,width,height);ctx.strokeStyle="#2e5d68";ctx.beginPath();values.forEach((value,index)=>{const x=index/Math.max(1,values.length-1)*width,y=middle-Number(value||0)*scale;index?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.stroke();ctx.strokeStyle="#0b9290";ctx.strokeRect(.5,.5,width-1,height-1);
}

function renderEditLibrary() {
  if(!$("#editLibraryWorkbench")||state.editMode!=="library")return;renderEditLibraryDeck();renderEditLibraryAnalytics();renderEditLibraryMatrix();renderEditWaveform("#editLibraryWaveformCanvas","#editLibraryWaveMeta");renderEditLibraryNavigator();const selected=state.editTemplateStrips.filter(item=>editSelected(item.sample_index));drawEditDensityCanvas($("#editLibraryDensityPrimary"),state.editTemplateStrips,"#79e18b");drawEditDensityCanvas($("#editLibraryDensitySelection"),selected,"#f0c85a");$("#editLibraryDensityLabel").textContent=editDescriptor().name;$("#editLibraryDensitySelectionLabel").textContent=selected.length?`${selected.length} 搏`:`尚未选择`;
}

async function loadEditTemplateStrips() {
  if(!state.caseId)return;
  const requestId=++state.editStripRequestId,caseId=state.caseId,samples=evenEditSamples(editClassSamples(),32);
  state.editTemplateStrips=[];renderEditGallery();if(!samples.length)return;
  const result=await api(`/api/cases/${caseId}/waveform-strips`,{method:"POST",body:JSON.stringify({sample_indices:samples.slice(0,32),pre_s:.6,post_s:1,leads:[state.editLead],max_points:500,filter:"display"})});
  if(requestId!==state.editStripRequestId||caseId!==state.caseId)return;state.editTemplateStrips=result.items||[];renderEditGallery();renderEditLibrary();
}

async function loadEditWaveform() {
  if(!state.caseId||!state.caseData)return;
  const requestId=++state.editRequestId,caseId=state.caseId,total=Number(state.caseData.technical.duration_seconds_raw)||state.editDuration;state.editStart=Math.max(0,Math.min(state.editStart,Math.max(0,total-state.editDuration)));const leads=[state.editLead,...DEFAULT_PREVIEW_LEADS].filter((lead,index,array)=>array.indexOf(lead)===index).slice(0,3),params=new URLSearchParams({start:state.editStart.toFixed(3),duration:state.editDuration,leads:leads.join(","),max_points:5000,filter:"display"});$("#editWaveMeta").textContent="正在读取编辑波形…";const waveform=await api(`/api/cases/${caseId}/waveform?${params}`);if(requestId!==state.editRequestId||caseId!==state.caseId)return;state.editWaveform=waveform;state.editStart=waveform.start_s;renderEditOverview();renderEditWaveform();renderEditLibrary();
}

async function loadEdit() {
  if(!state.caseId||!state.caseData)return;
  const requestId=++state.editRequestId,caseId=state.caseId,total=Number(state.caseData.technical.duration_seconds_raw)||state.editDuration;state.editStart=Math.max(0,Math.min(state.editStart,Math.max(0,total-state.editDuration)));const leads=[state.editLead,...DEFAULT_PREVIEW_LEADS].filter((lead,index,array)=>array.indexOf(lead)===index).slice(0,3),params=new URLSearchParams({start:state.editStart.toFixed(3),duration:state.editDuration,leads:leads.join(","),max_points:5000,filter:"display"});
  $("#editWaveMeta").textContent="正在建立模板编辑工作区…";
  const [scatter,rr,waveform,templates,overrides]=await Promise.all([api(`/api/cases/${caseId}/scatter?mode=rr&max_points=10000`),api(`/api/cases/${caseId}/rr-visuals?max_points=5000`),api(`/api/cases/${caseId}/waveform?${params}`),api(`/api/cases/${caseId}/beat-templates`),api(`/api/cases/${caseId}/beat-overrides`)]);
  if(requestId!==state.editRequestId||caseId!==state.caseId)return;state.editScatterData=scatter;state.editRr=rr;state.editWaveform=waveform;state.editStart=waveform.start_s;state.editTemplates=templates.items||[];state.editBeatOverrides=new Map((overrides.items||[]).map(item=>[Number(item.sample_index),item]));if(!EDIT_SOURCE_CLASSES.some(item=>item.key===state.editSelectedClass)&&!state.editTemplates.some(item=>`custom-${item.id}`===state.editSelectedClass))state.editSelectedClass="source-N";renderEditClasses();renderEditOverview();renderEditScatter();renderEditWaveform();await loadEditTemplateStrips();
}

function setEditStart(value) {if(!state.caseData)return;const total=Number(state.caseData.technical.duration_seconds_raw)||state.editDuration;state.editStart=Math.max(0,Math.min(Number(value)||0,Math.max(0,total-state.editDuration)));loadEditWaveform().catch(handleError);}

function selectEditClass(key) {if(key===state.editSelectedClass)return;state.editSelectedClass=key;state.editSelectedSample=null;state.editSelectedSamples=new Set();state.editSelectionAnchor=null;state.editSelection=null;state.editSelectionStrips=[];state.editMorphDraft=null;closeEditClassPopover();renderEditClasses();renderEditScatter();loadEditTemplateStrips().catch(handleError);}

function closeEditClassPopover() {const popover=$("#editClassPopover");if(!popover)return;try{if(popover.matches(":popover-open"))popover.hidePopover();}catch(_){/* fallback */}popover.hidden=true;state.editEditingTemplateId=null;}

function openEditClassPopover(clientX=window.innerWidth/2,clientY=180,template=null) {
  const popover=$("#editClassPopover");if(!popover)return;state.editEditingTemplateId=template?.id||null;const family=template?.rhythm_family||"自定义",nameInput=$("#editClassName"),parentLabel=editClassLabel(template?.source_class||state.editSelectedClass);$(".edit-popover-heading strong",popover).textContent=template?"编辑模板信息":`从 ${parentLabel} 派生新模板`;$("#editRhythmFamily").value=family;nameInput.value=template?.name||nextEditTemplateName();nameInput.dataset.autoGenerated=template?"false":"true";$("#editClassNote").value=template?.note||"";$("#editSelectionSummary").textContent=template?`来自 ${parentLabel} · ${template.beat_count} 搏 · ${template.lead}`:`来自 ${parentLabel} · 框选 ${state.editSelection?.samples?.length||0} 个代表心搏 · ${state.editLead}`;$("#saveEditClass").textContent=template?"保存模板信息":state.demoReadonly?"保存到当前浏览器":"派生新模板";popover.hidden=false;const width=380,left=Math.max(12,Math.min(window.innerWidth-width-12,clientX+12)),top=Math.max(76,Math.min(window.innerHeight-430,clientY+12));popover.style.left=`${left}px`;popover.style.top=`${top}px`;try{if(!popover.matches(":popover-open"))popover.showPopover();}catch(_){/* fallback uses hidden */}setTimeout(()=>nameInput.focus(),0);
}

function applyMorphologySelection(x1,y1,x2,y2,anchorX=window.innerWidth/2,anchorY=window.innerHeight/2) {
  const canvas=$("#editDensityPrimary"),width=canvas.getBoundingClientRect().width,height=canvas.getBoundingClientRect().height,left=Math.max(0,Math.min(x1,x2))*width,right=Math.min(1,Math.max(x1,x2))*width,top=Math.max(0,Math.min(y1,y2))*height,bottom=Math.min(1,Math.max(y1,y2))*height;if(right-left<8||bottom-top<8){state.editMorphDraft=null;renderEditDensity();toast("请在形态集合中框出一个更大的波形区域","error");return;}
  const chosen=state.editMorphTraceGeometry.filter(trace=>{const inX=trace.points.filter(point=>point.x>=left&&point.x<=right);if(!inX.length)return false;const hits=inX.filter(point=>point.y>=top&&point.y<=bottom).length;return hits>=Math.max(1,Math.ceil(inX.length*.025));}),samples=[...new Set(chosen.map(trace=>trace.item.sample_index))].slice(0,500);state.editMorphDraft=null;if(!samples.length){renderEditDensity();toast("矩形没有命中波形，请框住目标波形的一段轮廓","error");return;}const times=chosen.map(trace=>Number(trace.item.time_s)).filter(Number.isFinite);state.editSelection={source:"morphology",x1:left/width,x2:right/width,y1:top/height,y2:bottom/height,samples,startTime:times.length?Math.min(...times):state.editStart,endTime:times.length?Math.max(...times):state.editStart};state.editSelectionStrips=chosen.map(trace=>trace.item);renderEditDensity();openEditClassPopover(anchorX,anchorY);
}

function clearEditSelection() {state.editSelection=null;state.editSelectionStrips=[];state.editMorphDraft=null;closeEditClassPopover();renderEditDensity();}

async function saveEditClass() {
  if(!state.caseId)return;const name=$("#editClassName").value.trim(),rhythmFamily=$("#editRhythmFamily").value,note=$("#editClassNote").value.trim();if(!name){toast("请填写模板类别名称","error");$("#editClassName").focus();return;}
  if(state.editEditingTemplateId){const updated=await api(`/api/beat-templates/${state.editEditingTemplateId}`,{method:"PATCH",body:JSON.stringify({name,rhythm_family:rhythmFamily,note})});state.editTemplates=state.editTemplates.map(item=>item.id===updated.id?updated:item);state.editSelectedClass=`custom-${updated.id}`;closeEditClassPopover();renderEditClasses();await loadEditTemplateStrips();toast("模板信息已更新");return;}
  if(!state.editSelection?.samples?.length){toast("请先在左侧形态集合中框选波形","error");return;}const sourceClass=state.editSelectedClass,created=await api(`/api/cases/${state.caseId}/beat-templates`,{method:"POST",body:JSON.stringify({name,rhythm_family:rhythmFamily,lead:state.editLead,source_class:sourceClass,sample_indices:state.editSelection.samples,note})});state.editTemplates.unshift(created);state.editSelectedClass=`custom-${created.id}`;state.editSelectedSample=created.sample_indices[0]||null;state.editSelection=null;state.editSelectionStrips=[];state.editMorphDraft=null;closeEditClassPopover();renderEditClasses();renderEditScatter();renderEditWaveform();await loadEditTemplateStrips();toast(state.demoReadonly?`${created.name} 已保存到当前浏览器`:`已从 ${editClassLabel(sourceClass)} 派生 ${created.name}`);
}

function bindEditInteraction() {
  const canvas=$("#editWaveformCanvas"),tooltip=$("#editWaveTooltip"),fractionFor=event=>{const rect=canvas.getBoundingClientRect(),g=editWaveGeometry(rect.width,rect.height);return Math.max(0,Math.min(1,(event.clientX-rect.left-g.l)/g.w));};
  canvas.addEventListener("pointermove",event=>{if(!state.editWaveform)return;const rect=canvas.getBoundingClientRect(),g=editWaveGeometry(rect.width,rect.height),fraction=fractionFor(event),leads=Object.keys(state.editWaveform.leads||{}),localY=Math.max(g.t,Math.min(g.t+g.h,event.clientY-rect.top)),leadIndex=Math.max(0,Math.min(leads.length-1,Math.floor((localY-g.t)/(g.h/Math.max(1,leads.length))))),lead=leads[leadIndex],values=state.editWaveform.leads[lead]||[],index=Math.max(0,Math.min(values.length-1,Math.round(fraction*Math.max(0,values.length-1)))),value=Number(values[index]),time=state.editWaveform.start_s+fraction*state.editWaveform.duration_s;tooltip.hidden=false;tooltip.classList.toggle("flip",event.clientX-rect.left>rect.width-190);tooltip.style.left=`${event.clientX-rect.left}px`;tooltip.style.top=`${Math.max(5,localY-42)}px`;tooltip.textContent=`${formatElapsedPrecise(time)}\n${lead||"—"}  ${Number.isFinite(value)?`${value.toFixed(0)} 设备单位`:"—"}`;});canvas.addEventListener("pointerleave",()=>{tooltip.hidden=true;});
  const libraryCanvas=$("#editLibraryWaveformCanvas"),libraryTooltip=$("#editLibraryWaveTooltip");
  libraryCanvas.addEventListener("pointermove",event=>{if(!state.editWaveform)return;const rect=libraryCanvas.getBoundingClientRect(),g=editWaveGeometry(rect.width,rect.height),fraction=Math.max(0,Math.min(1,(event.clientX-rect.left-g.l)/g.w)),time=state.editWaveform.start_s+fraction*state.editWaveform.duration_s,nearest=(state.editWaveform.beats||[]).reduce((best,beat)=>!best||Math.abs(beat.time_s-time)<Math.abs(best.time_s-time)?beat:best,null);libraryTooltip.hidden=false;libraryTooltip.style.left=`${event.clientX-rect.left}px`;libraryTooltip.style.top="8px";libraryTooltip.textContent=`${formatElapsedPrecise(time)}${nearest?`\n最近心搏 ${editEffectiveCode(nearest)} · 点击选中`:""}`;});libraryCanvas.addEventListener("pointerleave",()=>{libraryTooltip.hidden=true;});
  [canvas,libraryCanvas].forEach(waveCanvas=>{
    waveCanvas.addEventListener("click",event=>{if(!state.editWaveform?.beats?.length)return;const rect=waveCanvas.getBoundingClientRect(),g=editWaveGeometry(rect.width,rect.height),fraction=Math.max(0,Math.min(1,(event.clientX-rect.left-g.l)/g.w)),time=state.editWaveform.start_s+fraction*state.editWaveform.duration_s,nearest=state.editWaveform.beats.reduce((best,beat)=>!best||Math.abs(beat.time_s-time)<Math.abs(best.time_s-time)?beat:best,null);if(nearest)selectEditSample(nearest.sample_index,nearest.time_s,event,state.editWaveform.beats);});
    waveCanvas.addEventListener("contextmenu",event=>{event.preventDefault();(waveCanvas===canvas?tooltip:libraryTooltip).hidden=true;openBeatRelabelMenu(event,waveCanvas,state.editWaveform,"edit");waveCanvas.focus({preventScroll:true});});
  });

  const morphCanvas=$("#editDensityPrimary"),morphWrap=$("#editMorphCanvasWrap"),morphTooltip=$("#editMorphTooltip");let morphPointer=null,morphStart={x:0,y:0},morphCurrent={x:0,y:0};const morphPosition=event=>{const rect=morphCanvas.getBoundingClientRect();return {x:Math.max(0,Math.min(1,(event.clientX-rect.left)/Math.max(1,rect.width))),y:Math.max(0,Math.min(1,(event.clientY-rect.top)/Math.max(1,rect.height)))};};
  morphCanvas.addEventListener("pointerdown",event=>{if(morphPointer!==null||!state.editTemplateStrips.length||event.pointerType==="mouse"&&event.button!==0)return;event.preventDefault();morphPointer=event.pointerId;morphStart=morphCurrent=morphPosition(event);state.editMorphDraft={x1:morphStart.x,y1:morphStart.y,x2:morphStart.x,y2:morphStart.y};try{morphCanvas.setPointerCapture(event.pointerId)}catch(_){/* capture is progressive enhancement */}morphWrap.classList.add("selecting");morphTooltip.hidden=true;renderEditDensity();});
  morphCanvas.addEventListener("pointermove",event=>{if(morphPointer===event.pointerId){event.preventDefault();morphCurrent=morphPosition(event);state.editMorphDraft={x1:morphStart.x,y1:morphStart.y,x2:morphCurrent.x,y2:morphCurrent.y};renderEditDensity();return;}const point=morphPosition(event);morphTooltip.hidden=false;morphTooltip.classList.toggle("flip",point.x>.62);morphTooltip.style.left=`${point.x*100}%`;morphTooltip.style.top=`${Math.max(5,point.y*morphCanvas.getBoundingClientRect().height-34)}px`;morphTooltip.textContent=`${editDescriptor().name} · ${state.editTemplateStrips.length} 个代表搏\n拖动框选 · 右键取消`;});
  morphCanvas.addEventListener("contextmenu",event=>{event.preventDefault();if(morphPointer!==null){try{if(morphCanvas.hasPointerCapture(morphPointer))morphCanvas.releasePointerCapture(morphPointer)}catch(_){/* pointer capture may already be released */}morphPointer=null;}morphWrap.classList.remove("selecting");morphTooltip.hidden=true;clearEditSelection();morphCanvas.focus({preventScroll:true});});
  const finishMorph=event=>{if(morphPointer!==event.pointerId)return;event.preventDefault();morphPointer=null;if(morphCanvas.hasPointerCapture(event.pointerId))morphCanvas.releasePointerCapture(event.pointerId);morphWrap.classList.remove("selecting");applyMorphologySelection(morphStart.x,morphStart.y,morphCurrent.x,morphCurrent.y,event.clientX,event.clientY);};morphCanvas.addEventListener("pointerup",finishMorph);morphCanvas.addEventListener("pointercancel",event=>{if(morphPointer!==event.pointerId)return;morphPointer=null;state.editMorphDraft=null;morphWrap.classList.remove("selecting");renderEditDensity();});morphCanvas.addEventListener("pointerleave",()=>{if(morphPointer===null)morphTooltip.hidden=true;});morphCanvas.addEventListener("keydown",event=>{if(event.key==="Escape"){event.preventDefault();clearEditSelection();}if(event.key==="Enter"&&state.editSelection?.samples?.length){event.preventDefault();openEditClassPopover();}});
  $("#editTrendCanvas").addEventListener("click",event=>{if(!state.caseData)return;const rect=event.currentTarget.getBoundingClientRect(),time=(event.clientX-rect.left)/rect.width*state.caseData.technical.duration_seconds_raw;setEditStart(time-state.editDuration*.45);});
  $("#editScatterCanvas").addEventListener("click",event=>{const data=state.editScatterData;if(!data)return;const rect=event.currentTarget.getBoundingClientRect(),m={l:31,r:9,t:10,b:22},w=rect.width-m.l-m.r,h=rect.height-m.t-m.b,b=data.bounds,bx=b.x_max-b.x_min,by=b.y_max-b.y_min,x=event.clientX-rect.left,y=event.clientY-rect.top;let nearest=null,distance=Infinity;for(const point of data.points||[]){const px=m.l+(point.x-b.x_min)/bx*w,py=m.t+h-(point.y-b.y_min)/by*h,d=Math.hypot(px-x,py-y);if(d<distance){distance=d;nearest=point;}}if(nearest&&distance<=14){state.editSelectedSample=nearest.sample_index;setEditStart(nearest.time_s-state.editDuration*.35);}});
}

async function loadEvents(type = state.eventType) {
  if (!state.caseId) return;
  if(type!==state.eventType)clinicalWorkflow.resetEvents();
  const requestId=++state.eventsRequestId,caseId=state.caseId;
  state.eventType=type;
  $$("[data-event-type]").forEach(button=>button.classList.toggle("active",button.dataset.eventType===type));
  const p=new URLSearchParams({type,offset:clinicalWorkflow.offset,limit:100,brady:$("#bradyThreshold").value,tachy:$("#tachyThreshold").value,pause:$("#pauseThreshold").value});
  const events=await api(`/api/cases/${caseId}/events?${p}`);
  if(requestId!==state.eventsRequestId||caseId!==state.caseId)return;
  state.events=events;renderEvents();
  clinicalWorkflow.updatedEvents();
}

function renderEvents() {
  const labels={V:"室性候选",S:"室上性候选",pause:"长 RR",tachy:"过速候选",brady:"过缓候选",noise:"噪声"};
  if(Object.prototype.hasOwnProperty.call(state.events.summary,"AF"))labels.AF="房颤样候选";
  $("#eventSummary").innerHTML=Object.entries(labels).map(([key,label])=>`<article class="event-summary-card"><span>${label}</span><strong>${fmtNumber(state.events.summary[key]||0)}</strong></article>`).join("");
  $("#eventTotal").textContent=`显示 ${state.events.items.length} / ${fmtNumber(state.events.total)}`;
  $("#eventTableBody").innerHTML=state.events.items.map(item=>`<tr><td>${formatElapsed(item.time_s)}</td><td><span class="severity-dot ${item.severity}"></span>${escapeHtml(item.label)}</td><td>${item.hr??"—"} bpm / ${item.rr_ms} ms</td><td>${item.group}</td><td>${clinicalWorkflow.eventCell(item)}</td><td><button class="row-action" data-jump-time="${item.time_s}">查看波形</button></td></tr>`).join("")||`<tr><td colspan="6" class="empty-state">当前筛选没有候选事件</td></tr>`;
}

function normalizedReportComposition(value=state.report?.composition) {
  const raw=value&&typeof value==="object"?value:{};
  const pages=[...new Set(Array.isArray(raw.included_pages)?raw.included_pages:DEFAULT_REPORT_COMPOSITION.included_pages)].filter(key=>REPORT_PAGES.some(page=>page.key===key));
  if(!pages.length)pages.push("summary");
  const active=pages.includes(raw.active_page)?raw.active_page:pages[0];
  const paper=raw.paper&&typeof raw.paper==="object"?raw.paper:{};
  return {
    template:["comprehensive","rhythm","concise","custom"].includes(raw.template)?raw.template:"custom",
    included_pages:pages,active_page:active,
    preview_mode:["compose","event","twelve"].includes(raw.preview_mode)?raw.preview_mode:"compose",
    fast_slow_mode:["rr","nn","both"].includes(raw.fast_slow_mode)?raw.fast_slow_mode:"rr",
    paper:{size:["A4","A3"].includes(paper.size)?paper.size:"A4",orientation:["portrait","landscape"].includes(paper.orientation)?paper.orientation:"portrait",show_grid:paper.show_grid!==false,show_labels:paper.show_labels!==false,speed:["12.5 mm/s","25 mm/s","50 mm/s"].includes(paper.speed)?paper.speed:"25 mm/s",gain:["5 mm/mV","10 mm/mV","20 mm/mV"].includes(paper.gain)?paper.gain:"10 mm/mV"},
  };
}

function reportLocalCompositionKey(){return `cardioinsight.report-composition.${state.caseId||"none"}`;}
function loadLocalReportComposition(){if(!state.demoReadonly||clinicalWorkflow.writable())return null;try{return JSON.parse(localStorage.getItem(reportLocalCompositionKey())||"null")}catch(_){return null}}
function reportPage(key){return REPORT_PAGES.find(item=>item.key===key)||REPORT_PAGES[1];}
function reportIncludedPages(){return state.reportComposition?.included_pages||[];}

function markReportCompositionDirty(message="有未保存的编排修改") {
  if(state.demoReadonly&&!clinicalWorkflow.writable()){$("#reportSaveState").textContent="只读编排预览";}
  else{state.reportDirty=true;$("#reportSaveState").textContent=message;}
}

function renderReport() {
  if (!state.caseData || !state.report) return;
  if(!state.reportComposition)state.reportComposition=normalizedReportComposition(loadLocalReportComposition()||state.report.composition);
  const source=state.caseData.summary,calc=state.caseData.calculated,composition=state.reportComposition;
  $("#reportStatus").className=`status-pill ${state.report.status==="reviewed"?"success":state.report.status==="returned"?"danger":"warning"}`;
  $("#reportStatus").textContent=STATUS_TEXT[state.report.status]||state.report.status;
  $("#reportVersion").textContent=`v${state.report.version}`;
  if(!state.reportDirty)$("#conclusionEditor").value=state.report.conclusion||"";updateConclusionCount();
  if(!state.reportDirty)$("#reportSaveState").textContent=state.demoReadonly?"编排可保存在当前浏览器":state.report.updated_at?`上次保存 ${state.report.updated_at}`:"源报告导入，尚未编辑";
  const stats=[["有效心搏",fmtNumber(calc.valid_beats),`源报告 ${fmtNumber(source.total_beats)}`],["平均心率",`${calc.avg_hr_from_rr??"—"} bpm`,`源报告 ${source.avg_hr??"—"}`],["心率范围",`${source.min_hr??"—"}–${source.max_hr??"—"} bpm`,"源报告分钟统计，非逐搏极值"],["最长 RR",`${calc.longest_rr_ms==null?"—":(calc.longest_rr_ms/1000).toFixed(3)} s`,`源报告 ${source.longest_rr_s??"—"} s`],["室性心搏",fmtNumber(calc.group_counts?.["3"]||0),`源报告 ${fmtNumber(source.ventricular_beats)}`],["室上性心搏",fmtNumber(calc.group_counts?.["2"]||0),`源报告 ${fmtNumber(source.supraventricular_beats)}`],["伪差 / 排除",fmtNumber(calc.group_counts?.["34"]||0),"不计入有效心搏"]];
  $("#reportStats").innerHTML=stats.map(([label,value,note])=>`<div class="report-stat"><span>${label}</span><strong>${value}</strong><small>${note}</small></div>`).join("");
  const eventSummary=state.reportComposer?.events?.summary||{};
  const eventRows=[['tachy','最快心率'],['brady','最慢心率'],['V','室性候选'],['S','室上性候选'],['AF','房颤样候选'],['pause','长 RR'],['noise','其他 / 噪声']];
  $("#reportEventClasses").innerHTML=eventRows.map(([key,label])=>`<button type="button" data-report-event="${key}" class="${state.reportEventFilter===key?"active":""}"><span>${escapeHtml(label)}</span><em>${fmtNumber(eventSummary[key]||0)}</em></button>`).join("");
  $("#reportEventTotal").textContent=`${fmtNumber(Object.values(eventSummary).reduce((sum,value)=>sum+Number(value||0),0))} 项`;
  $("#reportPageChecklist").innerHTML=REPORT_PAGES.map(item=>`<label class="${item.available?"":"report-page-unavailable"}" title="${item.available?"点击名称可预览；取消勾选可排除":"当前数据链未提供结构化结果，仍可选入空态说明页"}"><input type="checkbox" value="${item.key}" data-report-page ${composition.included_pages.includes(item.key)?"checked":""}><span data-report-activate="${item.key}">${escapeHtml(item.label)}</span>${item.available?"":`<em>未解析</em>`}</label>`).join("");
  $("#reportPageCount").textContent=`${composition.included_pages.length} 项`;
  $("#reportTemplateSelect").value=composition.template;
  $$('input[name="reportFastMode"]').forEach(input=>input.checked=input.value===composition.fast_slow_mode);
  $$('[data-report-preview-mode]').forEach(button=>button.classList.toggle("active",button.dataset.reportPreviewMode===composition.preview_mode));
  $$('[data-report-page-target]').forEach(button=>button.classList.toggle("active",composition.preview_mode==="compose"&&button.dataset.reportPageTarget===composition.active_page));
  const included=composition.included_pages.map(reportPage);$("#reportActivePageSelect").innerHTML=included.map(item=>`<option value="${item.key}">${escapeHtml(item.label)}</option>`).join("");$("#reportActivePageSelect").value=composition.active_page;
  $("#reportPaperSize").value=composition.paper.size;$("#reportPaperOrientation").value=composition.paper.orientation;$("#reportPaperSpeed").value=composition.paper.speed;$("#reportPaperGain").value=composition.paper.gain;$("#reportShowGrid").checked=composition.paper.show_grid;$("#reportShowLabels").checked=composition.paper.show_labels;
  const sourceSelect=$("#reportPageSelect"),pageCount=Number(state.caseData.technical.report_pages)||0;sourceSelect.innerHTML=pageCount?Array.from({length:pageCount},(_,i)=>`<option value="${i}">原报告第 ${i+1} 页</option>`).join(""):`<option>无原报告影像</option>`;if(pageCount){sourceSelect.value="0";showReportPage(0);}
  renderReportHrvSummary();renderReportPreview();clinicalWorkflow.render();
}

async function loadReport() {
  if(!state.caseId||!state.caseData||!state.report)return;
  const caseId=state.caseId,requestId=++state.reportRequestId;
  renderReport();
  if(state.reportComposer?.caseId===caseId){renderReport();return;}
  $("#reportRenderStatus").textContent="读取数据";
  const start=Math.max(0,Math.min(Number(state.caseData.manual_longest?.time_s||state.caseData.calculated?.longest_rr_time_s||state.caseData.calculated?.first_beat_time_s||0)-2,Math.max(0,state.caseData.technical.duration_seconds_raw-8)));
  const [hrv,events,scatter,scatterNn,waveform]=await Promise.all([
    api(`/api/cases/${caseId}/hrv`),api(`/api/cases/${caseId}/events?type=all&limit=160`),api(`/api/cases/${caseId}/scatter?mode=rr&max_points=5000`),
    api(`/api/cases/${caseId}/scatter?mode=nn&max_points=5000`),
    api(`/api/cases/${caseId}/waveform?start=${start.toFixed(3)}&duration=8&leads=${ALL_LEADS.join(",")}&max_points=2600&filter=display`),
  ]);
  if(requestId!==state.reportRequestId||caseId!==state.caseId)return;
  const candidates=[];const seen=new Set();
  if(state.caseData.manual_longest){const item=state.caseData.manual_longest;candidates.push({...item,report_caption:"医生指定最长 RR 图条"});seen.add(item.sample_index)}
  for(const item of clinicalWorkflow.retained().slice(0,20)){
    candidates.push({...item,time_s:item.sample_index/200,report_caption:"医生保留 · "+item.type});seen.add(item.sample_index);
  }
  const extremes=[];
  for(const [kind,data] of [["RR",scatter],["NN",scatterNn]]){const points=(data.points||[]).filter(point=>Number.isFinite(point.rr_ms));if(points.length){extremes.push({...points.reduce((best,item)=>item.rr_ms<best.rr_ms?item:best),report_caption:`${kind} 最快`});extremes.push({...points.reduce((best,item)=>item.rr_ms>best.rr_ms?item:best),report_caption:`${kind} 最慢`});}}
  for(const item of extremes){if(!seen.has(item.sample_index)){candidates.push(item);seen.add(item.sample_index)}}
  for(const item of events.items||[]){if(clinicalWorkflow.decision(item)!=="excluded"&&!seen.has(item.sample_index)){candidates.push({...item,report_caption:"源候选 · "+item.type});seen.add(item.sample_index)}if(candidates.length>=8)break;}
  for(const item of waveform.beats||[]){if(item.kind==="nonbeat")continue;if(!seen.has(item.sample_index)){candidates.push(item);seen.add(item.sample_index)}if(candidates.length>=8)break;}
  let strips={items:[]};
  if(candidates.length){strips=await api(`/api/cases/${caseId}/waveform-strips`,{method:"POST",body:JSON.stringify({sample_indices:candidates.map(item=>item.sample_index),leads:["I","II","III","V1","V3","V5"],pre_s:.8,post_s:1.8,max_points:520,filter:"display"})});}
  if(requestId!==state.reportRequestId||caseId!==state.caseId)return;
  const captions=new Map(candidates.map(item=>[item.sample_index,item.report_caption]));
  strips.items=(strips.items||[]).map(item=>({...item,report_caption:captions.get(item.sample_index)}));
  state.reportComposer={caseId,hrv,events,scatter,scatterNn,waveform,strips,extremes};
  renderReport();
}

function renderReportHrvSummary(){
  const data=state.reportComposer?.hrv;if(!data){$("#reportHrvStats").innerHTML=`<div class="report-rail-empty">正在读取 HRV 数据…</div>`;return;}
  const c=data.calculated||{},s=data.source||{};const rows=[["Mean NN",c.mean_nn_ms,"ms",s.mean_nn_ms],["SDNN",c.sdnn_ms,"ms",s.sdnn_ms],["SDANN",c.sdann_ms,"ms",s.sdann_ms],["SDNN index",c.sdnn_index_ms,"ms",s.sdnn_index_ms],["rMSSD",c.rmssd_ms,"ms",s.rmssd_ms],["pNN50",c.pnn50_pct,"%",s.pnn50_pct],["三角指数",c.triangular_index,"",s.triangular_index]];
  $("#reportHrvStats").innerHTML=rows.map(([label,value,unit,sourceValue])=>`<div><dt>${label}</dt><dd>${value??"—"}${value!==null&&value!==undefined?` ${unit}`:""}</dd><small>源报告 ${sourceValue??"—"}</small></div>`).join("");
}

function reportUnavailableBody(page){return `<div class="report-module-empty"><span>◇</span><strong>${escapeHtml(page.label)}未生成</strong><p>当前数据链没有经验证的结构化 ${escapeHtml(page.label)} 结果。本页可保留在编排中作为缺项提示，但不会填入推算值或自动诊断。</p><small>如需启用，需补齐源格式解析、算法验证与医学复核流程。</small></div>`;}
function reportHrvRows(){const d=state.reportComposer?.hrv||{},c=d.calculated||{},s=d.source||{};return [["Mean NN",c.mean_nn_ms,s.mean_nn_ms,"ms"],["SDNN",c.sdnn_ms,s.sdnn_ms,"ms"],["SDANN",c.sdann_ms,s.sdann_ms,"ms"],["SDNN index",c.sdnn_index_ms,s.sdnn_index_ms,"ms"],["rMSSD",c.rmssd_ms,s.rmssd_ms,"ms"],["pNN50",c.pnn50_pct,s.pnn50_pct,"%"],["三角指数",c.triangular_index,s.triangular_index,""]];}

function renderReportPreview(){
  if(!state.caseData||!state.reportComposition)return;
  const body=$("#reportPreviewBody"),composition=state.reportComposition,index=Math.max(0,composition.included_pages.indexOf(composition.active_page));
  $("#reportNavigatorLabel").textContent=`第 ${index+1} / ${composition.included_pages.length} 页`;
  if(!state.reportComposer){body.innerHTML=`<div class="report-loading-state"><span></span><strong>正在组织报告内容</strong><small>读取趋势、事件图条与复核统计…</small></div>`;return;}
  const page=reportPage(composition.active_page),mode=composition.preview_mode;
  $("#reportPageTitle").textContent=mode==="event"?"事件图条":mode==="twelve"?"全导联图条":page.label;
  $("#reportPageSubtitle").textContent=mode==="compose"?(page.available?"实际可用数据预览":"缺项说明页"):mode==="event"?`最快最慢模式：${composition.fast_slow_mode.toUpperCase()}`:"12 导联同步复核图条";
  $("#reportRenderStatus").textContent=page.available||mode!=="compose"?"真实数据":"未解析";
  body.className=`report-preview-body report-preview-${mode} report-paper-${composition.paper.orientation}${composition.paper.show_grid?" show-grid":""}${composition.paper.show_labels?" show-labels":""}`;
  if(mode==="event")body.innerHTML=reportEventPageHtml();
  else if(mode==="twelve")body.innerHTML=`<div class="report-twelve-page"><div class="report-wave-meta"><strong>${escapeHtml(state.caseData.metadata.start_time||"")}</strong><span>${formatElapsed(state.reportComposer.waveform.start_s)} · ${state.reportComposer.waveform.filter}</span></div><canvas id="reportTwelveCanvas" height="480"></canvas><footer>${escapeHtml(composition.paper.speed)} · ${escapeHtml(composition.paper.gain)}（显示设置） · 幅值标定状态见病例技术说明</footer></div>`;
  else body.innerHTML=reportPageHtml(page);
  requestAnimationFrame(drawReportPreviewCanvases);
}

function reportCoverValue(value,suffix=""){
  if(value===null||value===undefined||value==="")return "—";
  return `${escapeHtml(String(value))}${suffix}`;
}

function reportCoverNumber(value){
  if(value===null||value===undefined||value==="")return "—";
  const number=Number(value);
  return Number.isFinite(number)?number.toLocaleString("zh-CN"):escapeHtml(String(value));
}

function reportCoverPercent(value,total){
  const count=Number(value),denominator=Number(total);
  if(!Number.isFinite(count)||!Number.isFinite(denominator)||denominator<=0)return "";
  const ratio=count/denominator*100;
  return ratio>0&&ratio<.1?"（<0.1%）":`（${ratio.toFixed(2)}%）`;
}

function reportCoverPageHtml(metadata,summary,calculated){
  const source=state.caseData.source_report_summary||summary||{},hrv=state.reportComposer?.hrv?.source||source;
  const conclusion=state.reportDirty?$("#conclusionEditor")?.value:state.report?.conclusion;
  const conclusionHtml=escapeHtml(conclusion||state.caseData.conclusion||"尚未填写报告结论").replace(/\n/g,"<br>");
  const displayNumber=(value,suffix="")=>`${reportCoverNumber(value)}${value===null||value===undefined||value===""?"":suffix}`;
  const fact=(label,value,wide="")=>`<div class="report-patient-fact ${wide}"><span>${label}</span><strong>${reportCoverValue(value)}</strong></div>`;
  const metric=(label,value,note="")=>`<div><dt>${label}</dt><dd>${value}</dd>${note?`<small>${note}</small>`:""}</div>`;
  return `<div class="report-cover-page"><article class="report-cover-sheet">
    <header class="report-document-title"><h2>动态心电图检测报告</h2><p>源报告摘要 · 未随逐搏修订更新</p></header>
    <section class="report-patient-grid" aria-label="检查信息">
      ${fact("姓名",metadata.name)}${fact("性别",metadata.sex)}${fact("年龄",metadata.age===null||metadata.age===undefined?null:`${metadata.age} 岁`)}${fact("起搏器",metadata.pacemaker)}
      ${fact("患者 ID",metadata.patient_id||state.caseData.case_id)}${fact("床位",metadata.bed)}${fact("记录时间",metadata.start_time,"span-2")}
      ${fact("申请医生",metadata.requesting_physician)}${fact("申请科室",metadata.department)}${fact("记录时长",metadata.source_record_duration_text||metadata.duration_text,"span-2")}
      ${fact("临床诊断",metadata.source_clinical_diagnosis||metadata.clinical_diagnosis,"span-4")}
    </section>
    <h3 class="report-cover-section-title">分析统计</h3>
    <section class="report-analysis-sheet" aria-label="分析统计">
      <div class="report-analysis-row report-analysis-overview">
        <section><h4>概要</h4><dl>
          ${metric("总心搏数",displayNumber(source.total_beats," 次"))}
          ${metric("室性心搏",`${displayNumber(source.ventricular_beats," 次")} ${reportCoverPercent(source.ventricular_beats,source.total_beats)}`)}
          ${metric("室上性心搏",`${displayNumber(source.supraventricular_beats," 次")} ${reportCoverPercent(source.supraventricular_beats,source.total_beats)}`)}
          ${metric("最长 RR 间期",displayNumber(source.longest_rr_s," 秒"))}
        </dl></section>
        <section><h4>心率</h4><dl>
          ${metric("最慢心率",displayNumber(source.min_hr," 次/分"))}
          ${metric("平均心率",displayNumber(source.avg_hr," 次/分"))}
          ${metric("最快心率",displayNumber(source.max_hr," 次/分"))}
          ${metric("过速 / 过缓心搏",`${displayNumber(source.tachy_beats," 次")} / ${displayNumber(source.brady_beats," 次")}`)}
        </dl></section>
      </div>
      <div class="report-analysis-row report-rhythm-breakdown">
        <section><h4>室性（V, F, E, I）</h4><dl>
          ${metric("室性心搏总数",displayNumber(source.ventricular_beats," 次"))}
          ${metric("单发 / 成对",`— / —`,"源报告未提供结构化分型")}
          ${metric("二联律 / 三联律",`— / —`)}
          ${metric("当前记录聚类候选",displayNumber(calculated?.group_counts?.["3"]," 次"),"仅供医生复核")}
        </dl></section>
        <section><h4>室上性（S, J, A）</h4><dl>
          ${metric("室上性心搏总数",displayNumber(source.supraventricular_beats," 次"))}
          ${metric("单发 / 成对",`— / —`,"源报告未提供结构化分型")}
          ${metric("二联律 / 三联律",`— / —`)}
          ${metric("当前记录聚类候选",displayNumber(calculated?.group_counts?.["2"]," 次"),"仅供医生复核")}
        </dl></section>
      </div>
      <section class="report-hrv-band"><h4>心率变异性</h4><dl>
        ${metric("SDNN",displayNumber(hrv.sdnn_ms," ms"))}${metric("SDANN",displayNumber(hrv.sdann_ms," ms"))}${metric("SDNN Index",displayNumber(hrv.sdnn_index_ms," ms"))}${metric("rMSSD",displayNumber(hrv.rmssd_ms," ms"))}${metric("pNN50",displayNumber(hrv.pnn50_pct,"%"))}
        ${metric("LF/HF",displayNumber(hrv.lf_hf))}${metric("三角指数",displayNumber(hrv.triangular_index))}${metric("LF",displayNumber(hrv.lf))}${metric("HF",displayNumber(hrv.hf))}
      </dl></section>
    </section>
    <h3 class="report-cover-section-title">报告结论</h3>
    <section class="report-cover-conclusion"><p>${conclusionHtml}</p></section>
    <footer><span>研究与软件功能验证用途</span><span>最终结论须由医生审核</span></footer>
  </article></div>`;
}

function reportPageHtml(page){
  const m=state.caseData.metadata,s=state.caseData.summary,c=state.caseData.calculated;
  if(!page.available)return reportUnavailableBody(page);
  if(page.key==="cover")return reportCoverPageHtml(m,s,c);
  if(page.key==="summary")return `<div class="report-summary-page"><div class="report-dual-trends"><figure><figcaption>全程心率趋势</figcaption><canvas id="reportTrendCanvas" height="54"></canvas></figure><figure><figcaption>RR 间期趋势</figcaption><canvas id="reportRrTrendCanvas" height="42"></canvas></figure></div><div class="report-summary-workspace"><section class="report-summary-gallery"><header><div><strong>代表图条</strong><small>最快、最慢与主要候选事件</small></div><span>点击图条切换右侧全导联</span></header><div class="report-strip-grid report-strip-grid-compact">${reportStripCards(4,null,reportFastSlowCandidates(),"compact")}</div></section><section class="report-detail-sheet"><header><div><strong>同步全导联复核</strong><small>${formatElapsed(state.reportComposer.waveform.start_s)} · ${state.reportComposer.waveform.filter}</small></div><span>${escapeHtml(state.reportComposition.paper.speed)} · ${escapeHtml(state.reportComposition.paper.gain)}</span></header><canvas id="reportSummaryTwelveCanvas" height="360"></canvas><footer>当前图条仅用于报告编排与医生复核 · 幅值标定状态见病例技术说明</footer></section></div><dl class="report-summary-bottom"><div><dt>修订有效心搏</dt><dd>${fmtNumber(c.valid_beats)}</dd></div><div><dt>平均心率</dt><dd>${c.avg_hr_from_rr??"—"} bpm</dd></div><div><dt>V / S</dt><dd>${fmtNumber(c.group_counts?.["3"]||0)} / ${fmtNumber(c.group_counts?.["2"]||0)}</dd></div><div><dt>最长 RR</dt><dd>${c.longest_rr_ms==null?"—":(c.longest_rr_ms/1000).toFixed(3)} s</dd></div></dl></div>`;
  if(page.key==="hourly"){const points=state.trend?.points||[],rows=points.slice(0,24);return `<div class="report-hourly-page"><canvas id="reportHourlyCanvas" height="155"></canvas><div class="report-hourly-table"><table><thead><tr><th>时段</th><th>平均心率</th><th>记录范围</th></tr></thead><tbody>${rows.map((point,i)=>`<tr><td>${formatElapsed(point.time_s,false)}</td><td>${point.hr??"—"} bpm</td><td>${i===0?"起始时段":"连续统计"}</td></tr>`).join("")}</tbody></table></div></div>`;}
  if(page.key==="scatter")return `<div class="report-scatter-page"><div><strong>R‑R 散点图</strong><small>${fmtNumber(state.reportComposer.scatter?.candidate_count||0)} 个候选点</small></div><canvas id="reportScatterCanvas" height="430"></canvas></div>`;
  if(page.key==="event_strips")return reportEventPageHtml();
  if(page.key==="af"){const af=(state.reportComposer.events.items||[]).filter(item=>item.type==="AF"||item.af_candidate);return af.length?`<div class="report-af-page"><div class="report-module-note"><strong>房颤 / 房扑候选复核</strong><p>以下为源标记或规则产生的候选片段，不等同于诊断。</p></div>${reportStripCards(8,af.map(item=>item.sample_index))}</div>`:`<div class="report-module-empty"><span>◇</span><strong>无可展示的房颤 / 房扑候选</strong><p>当前导入数据未提供可定位的结构化房颤 / 房扑事件。</p></div>`;}
  if(page.key==="hrv_time"||page.key==="hrv_overview")return `<div class="report-hrv-page"><div class="report-module-note"><strong>${escapeHtml(page.label)}</strong><p>${escapeHtml(state.reportComposer.hrv.comparison?.warning||"源报告与当前记录重算结果并列展示。")}</p></div><div class="report-hrv-grid">${reportHrvRows().map(([label,value,sourceValue,unit])=>`<article><span>${label}</span><strong>${value??"—"}${value!==null&&value!==undefined?` ${unit}`:""}</strong><small>源报告 ${sourceValue??"—"}</small></article>`).join("")}</div></div>`;
  return reportUnavailableBody(page);
}

function reportFastSlowCandidates(){const mode=state.reportComposition?.fast_slow_mode||"rr",allowed=mode==="both"?["RR","NN"]:[mode.toUpperCase()],items=(state.reportComposer?.extremes||[]).filter(item=>allowed.some(kind=>item.report_caption.startsWith(kind))),merged=new Map();for(const item of items){const previous=merged.get(item.sample_index);merged.set(item.sample_index,previous?{...item,report_caption:`${previous.report_caption.split(" ")[0]} / ${item.report_caption}`} : item)}return [...merged.values()];}
function reportEventPageHtml(){const all=state.reportComposer?.events?.items||[],filter=state.reportEventFilter,items=filter==="all"?all:all.filter(item=>item.type===filter),extremes=reportFastSlowCandidates();return `<div class="report-event-page"><aside><div><strong>事件索引</strong><small>${fmtNumber(items.length)} 条候选</small></div>${items.slice(0,28).map((item,index)=>`<button type="button" data-report-event-sample="${item.sample_index}" class="${state.reportFocusedSample===item.sample_index?"active":""}"><span>${index+1}</span><strong>${formatElapsed(item.time_s)}</strong><em>${escapeHtml(item.label)}</em></button>`).join("")||`<p>当前类别没有候选事件</p>`}</aside><div class="report-event-trends report-dual-trends"><figure><figcaption>全程心率趋势</figcaption><canvas id="reportTrendCanvas" height="54"></canvas></figure><figure><figcaption>事件定位趋势</figcaption><canvas id="reportRrTrendCanvas" height="42"></canvas></figure></div><section class="report-event-gallery"><header><strong>代表图条</strong><small>点击后在右侧同步展开</small></header><div class="report-strip-grid report-strip-grid-event">${reportStripCards(6,null,extremes,"event")}</div></section><section class="report-detail-sheet report-event-detail"><header><div><strong>全导联事件页</strong><small>${formatElapsed(state.reportComposer.waveform.start_s)} · 8 秒</small></div><span>12 导联同步</span></header><canvas id="reportEventTwelveCanvas" height="500"></canvas><footer>${escapeHtml(state.reportComposition.paper.speed)} · ${escapeHtml(state.reportComposition.paper.gain)} · 当前粉色定位带对应选中事件</footer></section></div>`;}
function reportStripCards(limit=6,filterSamples=null,priority=[],variant="standard"){let strips=state.reportComposer?.strips?.items||[],captionBySample=new Map(priority.map(item=>[item.sample_index,item.report_caption]));if(filterSamples)strips=strips.filter(item=>filterSamples.includes(item.sample_index));if(priority.length){const rank=new Map(priority.map((item,index)=>[item.sample_index,index]));strips=[...strips].sort((a,b)=>(rank.get(a.sample_index)??999)-(rank.get(b.sample_index)??999));}const leadCaption="I · II · III · V1 · V3 · V5";return strips.slice(0,limit).map((item,index)=>`<article class="report-strip-card report-strip-card-${variant}${state.reportFocusedSample===item.sample_index?" active":""}" data-report-strip-sample="${item.sample_index}"><header><strong>${escapeHtml(item.report_caption||captionBySample.get(item.sample_index)||item.label||"N")}</strong><span>${formatElapsed(item.time_s)} · ${item.hr??"—"} bpm</span></header><canvas id="reportStrip${index}" data-report-strip-index="${(state.reportComposer.strips.items||[]).indexOf(item)}" data-report-strip-height="${variant==="event"?108:96}" height="${variant==="event"?108:96}"></canvas><footer>${leadCaption} · RR ${item.rr_ms??"—"} ms</footer></article>`).join("")||`<div class="report-module-empty compact"><strong>当前没有可定位的事件图条</strong></div>`;}

function drawReportSeries(canvas,points,xValue,yValue,color="#267db1",fill=false){if(!canvas||!points?.length)return;const {ctx,width,height}=canvasContext(canvas,Number(canvas.getAttribute("height"))||80),m={l:28,r:8,t:8,b:15},w=width-m.l-m.r,h=height-m.t-m.b,xs=points.map(xValue),ys=points.map(yValue).filter(Number.isFinite),xMin=Math.min(...xs),xMax=Math.max(...xs),yMin=Math.min(...ys),yMax=Math.max(...ys),dy=Math.max(1,yMax-yMin),dx=Math.max(1,xMax-xMin);ctx.fillStyle="#fff";ctx.fillRect(0,0,width,height);ctx.strokeStyle="#dce5e8";ctx.lineWidth=.7;[0,.5,1].forEach(f=>{const y=m.t+h*f;ctx.beginPath();ctx.moveTo(m.l,y);ctx.lineTo(m.l+w,y);ctx.stroke()});ctx.beginPath();points.forEach((point,index)=>{const x=m.l+(xValue(point)-xMin)/dx*w,y=m.t+h-(yValue(point)-yMin)/dy*h;index?ctx.lineTo(x,y):ctx.moveTo(x,y)});if(fill){ctx.lineTo(m.l+w,m.t+h);ctx.lineTo(m.l,m.t+h);ctx.closePath();ctx.fillStyle="rgba(38,125,177,.12)";ctx.fill();ctx.beginPath();points.forEach((point,index)=>{const x=m.l+(xValue(point)-xMin)/dx*w,y=m.t+h-(yValue(point)-yMin)/dy*h;index?ctx.lineTo(x,y):ctx.moveTo(x,y)})}ctx.strokeStyle=color;ctx.lineWidth=1.2;ctx.stroke();}
function drawReportWaveform(canvas,waveform,leadNames,height){if(!canvas||!waveform)return;const {ctx,width,height:h}=canvasContext(canvas,height),names=(leadNames||Object.keys(waveform.leads)).filter(name=>waveform.leads[name]),leadHeight=h/Math.max(1,names.length);ctx.fillStyle="#fffefd";ctx.fillRect(0,0,width,h);if(state.reportComposition.paper.show_grid){for(let x=0;x<width;x+=10){ctx.strokeStyle=x%50===0?"rgba(231,133,117,.25)":"rgba(241,181,169,.16)";ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,h);ctx.stroke()}for(let y=0;y<h;y+=10){ctx.strokeStyle=y%50===0?"rgba(231,133,117,.25)":"rgba(241,181,169,.16)";ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(width,y);ctx.stroke()}}names.forEach((name,row)=>{const values=waveform.leads[name],base=leadHeight*(row+.52),range=Math.max(200,...values.map(value=>Math.abs(Number(value)||0))),scale=leadHeight*.36/range;if(state.reportComposition.paper.show_labels){ctx.fillStyle="#0a7180";ctx.font=`700 9px ${UI_FONT}`;ctx.fillText(name,5,row*leadHeight+12)}ctx.beginPath();values.forEach((value,index)=>{const x=index/Math.max(1,values.length-1)*width,y=base-Number(value)*scale;index?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.strokeStyle="#28383f";ctx.lineWidth=.9;ctx.stroke()});}
function drawReportEventHighlight(canvas){if(!canvas)return;const ctx=canvas.getContext("2d"),x=canvas.width*.5,w=Math.max(14,canvas.width*.035);ctx.fillStyle="rgba(220,73,109,.14)";ctx.fillRect(x-w/2,0,w,canvas.height);ctx.strokeStyle="rgba(210,54,91,.55)";ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(x-w/2,0);ctx.lineTo(x-w/2,canvas.height);ctx.moveTo(x+w/2,0);ctx.lineTo(x+w/2,canvas.height);ctx.stroke();}
function drawReportScatter(canvas){const data=state.reportComposer?.scatter;if(!canvas||!data)return;const {ctx,width,height}=canvasContext(canvas,430),m={l:38,r:12,t:12,b:25},w=width-m.l-m.r,h=height-m.t-m.b,b=data.bounds||{x_min:0,x_max:2000,y_min:0,y_max:2000};ctx.fillStyle="#fdfefe";ctx.fillRect(0,0,width,height);ctx.strokeStyle="#dce5e8";for(let i=0;i<=4;i++){const x=m.l+w*i/4,y=m.t+h*i/4;ctx.beginPath();ctx.moveTo(x,m.t);ctx.lineTo(x,m.t+h);ctx.stroke();ctx.beginPath();ctx.moveTo(m.l,y);ctx.lineTo(m.l+w,y);ctx.stroke()}ctx.fillStyle="rgba(20,145,143,.42)";(data.points||[]).forEach(point=>{const x=m.l+(point.x-b.x_min)/(b.x_max-b.x_min)*w,y=m.t+h-(point.y-b.y_min)/(b.y_max-b.y_min)*h;ctx.fillRect(x-1,y-1,2,2)});ctx.fillStyle="#617681";ctx.font=`10px ${UI_FONT}`;ctx.fillText("RR(i) ms",width-58,height-6);ctx.save();ctx.translate(10,66);ctx.rotate(-Math.PI/2);ctx.fillText("RR(i+1) ms",0,0);ctx.restore();}
function drawReportPreviewCanvases(){const c=state.reportComposer;if(!c)return;drawReportSeries($("#reportTrendCanvas"),state.trend?.points||[],p=>p.time_s,p=>p.hr,"#247eb6",true);drawReportSeries($("#reportRrTrendCanvas"),c.scatter?.points||[],p=>p.time_s,p=>p.rr_ms,"#2a9b78",false);drawReportSeries($("#reportHourlyCanvas"),state.trend?.points||[],p=>p.time_s,p=>p.hr,"#247eb6",true);drawReportScatter($("#reportScatterCanvas"));drawReportWaveform($("#reportTwelveCanvas"),c.waveform,ALL_LEADS,480);drawReportWaveform($("#reportSummaryTwelveCanvas"),c.waveform,ALL_LEADS,360);const eventCanvas=$("#reportEventTwelveCanvas");drawReportWaveform(eventCanvas,c.waveform,ALL_LEADS,500);drawReportEventHighlight(eventCanvas);$$('[data-report-strip-index]').forEach(canvas=>{const item=c.strips.items[Number(canvas.dataset.reportStripIndex)];if(item)drawReportWaveform(canvas,item,["I","II","III","V1","V3","V5"],Number(canvas.dataset.reportStripHeight)||96)});}

function setReportActivePage(key){if(!REPORT_PAGES.some(page=>page.key===key))return;if(!state.reportComposition.included_pages.includes(key))state.reportComposition.included_pages.push(key);state.reportComposition.active_page=key;state.reportComposition.preview_mode="compose";state.reportComposition.template="custom";markReportCompositionDirty();renderReport();}
function moveReportPage(direction){const pages=reportIncludedPages(),index=pages.indexOf(state.reportComposition.active_page),next=(index+direction+pages.length)%pages.length;setReportActivePage(pages[next]);}
function applyReportTemplate(){const key=$("#reportTemplateSelect").value,pages=REPORT_TEMPLATES[key];if(!pages)return;state.reportComposition={...state.reportComposition,template:key,included_pages:[...pages],active_page:pages.includes(state.reportComposition.active_page)?state.reportComposition.active_page:pages[0],preview_mode:"compose"};markReportCompositionDirty("模板已应用，尚未保存");renderReport();toast("报告模板已应用");}
async function focusReportEvent(sample){if(!state.caseId||!Number.isFinite(sample))return;const start=Math.max(0,Math.min(sample/200-2,Math.max(0,state.caseData.technical.duration_seconds_raw-8)));$("#reportRenderStatus").textContent="定位事件";const waveform=await api(`/api/cases/${state.caseId}/waveform?start=${start.toFixed(3)}&duration=8&leads=${ALL_LEADS.join(",")}&max_points=2600&filter=display`);if(!state.reportComposer)return;state.reportComposer.waveform=waveform;state.reportFocusedSample=sample;renderReport();}
function applyReportSettings(){const paper={size:$("#reportPaperSize").value,orientation:$("#reportPaperOrientation").value,show_grid:$("#reportShowGrid").checked,show_labels:$("#reportShowLabels").checked,speed:$("#reportPaperSpeed").value,gain:$("#reportPaperGain").value};state.reportComposition={...state.reportComposition,paper};markReportCompositionDirty("页面设置已修改，尚未保存");$("#reportSettingsDialog").close();renderReport();toast("报告页面设置已应用");}
function printReportPreview(){document.body.classList.add("report-printing");const cleanup=()=>{document.body.classList.remove("report-printing");window.removeEventListener("afterprint",cleanup)};window.addEventListener("afterprint",cleanup);window.print();setTimeout(cleanup,1200);}

function showReportPage(index) {
  const image=$("#sourceReportImage"),privacy=$("#sourceReportPrivacy");
  if(!state.includePhi){image.hidden=true;image.removeAttribute("src");image.dataset.url="";privacy.hidden=false;return;}
  const url=state.caseData?.report_image_urls?.[index];if(!url)return;privacy.hidden=true;image.hidden=false;image.src=url;image.dataset.url=url;
}

function updateConclusionCount() {const value=$("#conclusionEditor").value;$("#conclusionCount").textContent=`${value.length} / 12000`;}

async function saveReport(status="draft") {
  if (!clinicalWorkflow.writable()) {toast("当前服务为只读模式", "error");return;}
  if (!state.caseId) return;
  if(status==="reviewed"&&(state.reportDirty||!clinicalWorkflow.readiness())){toast("请先完成复核环节并保存当前草稿","error");return;}
  const caseId=state.caseId;
  const conclusion=$("#conclusionEditor").value;
  const saved=await api(`/api/cases/${state.caseId}/report`,{method:"PUT",body:JSON.stringify({conclusion,status,composition:state.reportComposition})});
  if(caseId!==state.caseId)return;
  state.report=saved;state.caseData.report_workflow=saved;state.reportDirty=false;renderReport();renderCaseWorkflow();
  await clinicalWorkflow.refresh(caseId);
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

function jumpTo(time) {if(!state.caseId)return;clinicalWorkflow.sourceJump(time);state.start=Math.max(0,Math.min(Number(time)-state.duration*.35,state.caseData.technical.duration_seconds_raw-state.duration));if(state.currentPage==="review")loadWaveform().catch(handleError);else goPage("review");}

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
  canvas.addEventListener("pointerdown",event=>{if(event.pointerType==="mouse"&&event.button!==0)return;down={x:event.clientX,start:state.start};scroller.classList.add("dragging");canvas.setPointerCapture(event.pointerId)});
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
  canvas.addEventListener("contextmenu",event=>{event.preventDefault();hideCursor();openBeatRelabelMenu(event,canvas,state.waveform,"review")});
  canvas.addEventListener("dblclick",event=>{event.preventDefault();toggleWaveformFullscreen()});
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

function nudgeSttMarker(marker,direction) {
  if(!state.sttWaveform)return;
  const step=.005/Math.max(.001,state.sttWaveform.duration_s),marks=sttLandmarkFractions();
  if(marker==="iso")state.sttIsoFraction=Math.max(.04,Math.min(marks.j-.025,marks.iso+step*direction));
  else state.sttJFraction=Math.max(marks.iso+.025,Math.min(.96-marks.offsetFraction,marks.j+step*direction));
  renderSttWaveform();
}

function bindSttInteraction() {
  const canvas=$("#sttWaveformCanvas"),wrapper=$("#sttWaveCanvasWrap"),tooltip=$("#sttWaveTooltip");let dragging=null,sliderTimer=null;
  const geometry=()=>{const rect=canvas.getBoundingClientRect(),l=54,r=18,w=Math.max(1,rect.width-l-r),marks=sttLandmarkFractions();return {rect,l,w,marks,isoX:l+marks.iso*w,jX:l+marks.j*w};};
  const hideTooltip=()=>{tooltip.hidden=true;};
  canvas.addEventListener("pointerdown",event=>{
    if(event.pointerType==="mouse"&&event.button!==0||!state.sttWaveform)return;
    const g=geometry(),x=event.clientX-g.rect.left,isoDistance=Math.abs(x-g.isoX),jDistance=Math.abs(x-g.jX);
    if(Math.min(isoDistance,jDistance)>13)return;
    event.preventDefault();dragging=isoDistance<=jDistance?"iso":"j";canvas.setPointerCapture(event.pointerId);wrapper.classList.add("dragging-marker");hideTooltip();
  });
  canvas.addEventListener("pointermove",event=>{
    if(!state.sttWaveform)return;
    const g=geometry(),localX=Math.max(g.l,Math.min(g.l+g.w,event.clientX-g.rect.left));
    if(dragging){
      event.preventDefault();const fraction=(localX-g.l)/g.w,marks=sttLandmarkFractions();
      if(dragging==="iso")state.sttIsoFraction=Math.max(.04,Math.min(marks.j-.025,fraction));
      else state.sttJFraction=Math.max(marks.iso+.025,Math.min(.96-marks.offsetFraction,fraction));
      renderSttWaveform();return;
    }
    const localY=Math.max(24,Math.min(g.rect.height-22,event.clientY-g.rect.top)),leads=Object.keys(state.sttWaveform.leads||{}),leadHeight=(g.rect.height-46)/Math.max(1,leads.length),leadIndex=Math.max(0,Math.min(leads.length-1,Math.floor((localY-24)/leadHeight))),lead=leads[leadIndex],values=state.sttWaveform.leads[lead]||[],fraction=(localX-g.l)/g.w,valueIndex=Math.max(0,Math.min(values.length-1,Math.round(fraction*Math.max(0,values.length-1)))),time=state.sttWaveform.start_s+fraction*state.sttWaveform.duration_s,value=Number(values[valueIndex]);
    tooltip.hidden=false;tooltip.classList.toggle("flip",localX>g.rect.width-190);tooltip.style.left=`${localX}px`;tooltip.style.top=`${Math.max(6,localY-40)}px`;tooltip.textContent=`${formatElapsedPrecise(time)}\n${lead||"—"}  ${Number.isFinite(value)?`${value.toFixed(0)} 设备单位`:"—"}`;
  });
  const finish=event=>{if(!dragging)return;dragging=null;wrapper.classList.remove("dragging-marker");if(canvas.hasPointerCapture(event.pointerId))canvas.releasePointerCapture(event.pointerId);renderSttWaveform();};
  canvas.addEventListener("pointerup",finish);canvas.addEventListener("pointercancel",finish);canvas.addEventListener("pointerleave",()=>{if(!dragging)hideTooltip();});
  canvas.addEventListener("contextmenu",event=>{event.preventDefault();hideTooltip();openSttLeadPicker();});
  canvas.addEventListener("dblclick",event=>{event.preventDefault();openSttTwelveLead().catch(handleError);});
  canvas.addEventListener("keydown",event=>{if(event.key.toLowerCase()==="f"){event.preventDefault();openSttTwelveLead().catch(handleError);}else if(event.key==="ArrowLeft"||event.key==="ArrowRight"){event.preventDefault();nudgeSttMarker(event.shiftKey?"iso":"j",event.key==="ArrowLeft"?-1:1);}});
  $("#sttOverviewCanvas").addEventListener("click",event=>{if(!state.caseData)return;const rect=event.currentTarget.getBoundingClientRect(),time=(event.clientX-rect.left)/rect.width*state.caseData.technical.duration_seconds_raw;setSttStart(time-state.sttDuration*.45);});
  $("#sttTimeSlider").addEventListener("input",event=>{clearTimeout(sliderTimer);state.sttStart=Number(event.target.value);renderSttOverview();renderSttTrendRows();sliderTimer=setTimeout(()=>loadStt().catch(handleError),120);});
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
  $$('[data-workflow-page]').forEach(button=>button.addEventListener("click",()=>goPage(button.dataset.workflowPage)));
  $("#workflowNext").addEventListener("click",advanceCaseWorkflow);
  $("#dismissSafety").addEventListener("click",()=>$(".safety-banner").classList.add("hidden"));
  $("#globalSearch").addEventListener("input",event=>{state.search=event.target.value;renderWorklist();renderPatients()});
  $("#worklistFilter").addEventListener("change",renderWorklist);$("#showDeleted").addEventListener("change",renderPatients);
  document.addEventListener("click",event=>{
    const open=event.target.closest("[data-open-case]");if(open){const progress=state.cases.find(item=>item.case_id===open.dataset.openCase)?.review_workflow;selectCase(open.dataset.openCase,progress?.next_step||"review").catch(handleError);}
    const edit=event.target.closest("[data-edit-patient]");if(edit)openPatientEditor(edit.dataset.editPatient);
    const strip=event.target.closest("[data-scatter-sample]");if(strip){const sample=Number(strip.dataset.scatterSample);if(state.scatterStripFailed.has(sample)){state.scatterStripFailed.delete(sample);renderScatterSelectionList();}focusScatterWaveform(Number(strip.dataset.jumpTime),sample);}
    else {const jump=event.target.closest("[data-jump-time]");if(jump)jumpTo(jump.dataset.jumpTime);}
    const del=event.target.closest("[data-delete-annotation]");if(del&&confirm("删除这条人工标注？"))api(`/api/annotations/${del.dataset.deleteAnnotation}`,{method:"DELETE"}).then(()=>loadWaveform()).catch(handleError);
    const editClass=event.target.closest("[data-edit-class]");if(editClass)selectEditClass(editClass.dataset.editClass);
    const editSample=event.target.closest("[data-edit-sample]");if(editSample){selectEditSample(editSample.dataset.editSample,editSample.dataset.editTime,event);}
    const libraryFilter=event.target.closest("[data-edit-library-filter]");if(libraryFilter){state.editLibraryFilter=libraryFilter.dataset.editLibraryFilter;renderEditLibrary();}
    if(event.target.closest("[data-stt-current-window]")){$("#sttWaveformCanvas")?.focus();$("#sttWaveformCanvas")?.scrollIntoView({behavior:"smooth",block:"center"});}
  });
  $("#openFirstCase").addEventListener("click",()=>{const first=filteredCases()[0];if(first)selectCase(first.case_id).catch(handleError)});
  if(state.allowPhi)$("#privacyToggle").addEventListener("click",async()=>{try{const enabling=!state.includePhi;if(enabling&&!confirm("身份信息包含真实健康数据。仅应在授权环境中查看，是否继续？"))return;await api("/api/privacy/view",{method:"POST",body:JSON.stringify({enabled:enabling})});state.includePhi=enabling;$("#privacyToggle").classList.toggle("visible",state.includePhi);$("#privacyToggle").setAttribute("aria-pressed",String(state.includePhi));$("#privacyText").textContent=state.includePhi?"身份信息正在显示":"身份信息已遮蔽";await loadDashboard();if(state.caseId)await loadCase()}catch(error){handleError(error)}});
  $("#leadPickerButton").addEventListener("click",openLeadPicker);
  $$('[data-lead-choice]').forEach(choice=>choice.addEventListener("change",updateLeadPickerState));
  $("#resetLeadSelection").addEventListener("click",()=>setLeadPickerSelection(DEFAULT_PREVIEW_LEADS));
  $("#applyLeadSelection").addEventListener("click",applyLeadSelection);
  $$('[data-beat-relabel-code]').forEach(button=>button.addEventListener("click",()=>applyBeatRelabelTarget(button.dataset.beatRelabelCode).catch(handleError)));
  $("#restoreBeatRelabel").addEventListener("click",()=>restoreBeatRelabelTarget().catch(handleError));
  $("#closeBeatRelabelMenu").addEventListener("click",()=>closeBeatRelabelMenu());
  $("#beatRelabelLeadSettings").addEventListener("click",()=>{closeBeatRelabelMenu();openLeadPicker();});
  $("#beatRelabelMenu").addEventListener("contextmenu",event=>event.preventDefault());
  $("#beatRelabelMenu").addEventListener("keydown",event=>{const menu=$("#beatRelabelMenu"),items=$$('button:not([hidden]):not(:disabled)',menu),index=items.indexOf(document.activeElement);if(event.key==="Escape"){event.preventDefault();event.stopPropagation();closeBeatRelabelMenu();return;}if(["ArrowDown","ArrowUp","Home","End"].includes(event.key)){event.preventDefault();event.stopPropagation();const next=event.key==="Home"?0:event.key==="End"?items.length-1:Math.max(0,(index<0?0:index+(event.key==="ArrowDown"?1:-1)+items.length)%items.length);items[next]?.focus();return;}const code=event.key.toUpperCase();if(!event.ctrlKey&&!event.metaKey&&!event.altKey&&EDIT_BEAT_TYPES[code]){event.preventDefault();event.stopPropagation();applyBeatRelabelTarget(code).catch(handleError);}});
  document.addEventListener("pointerdown",event=>{const menu=$("#beatRelabelMenu");if(menu&&!menu.hidden&&!menu.contains(event.target))closeBeatRelabelMenu();});
  $("#sttLeadPickerButton").addEventListener("click",openSttLeadPicker);
  $$('[data-stt-lead-choice]').forEach(choice=>choice.addEventListener("change",updateSttLeadPickerState));
  $("#resetSttLeadSelection").addEventListener("click",()=>setSttLeadPickerSelection(DEFAULT_PREVIEW_LEADS));
  $("#applySttLeadSelection").addEventListener("click",applySttLeadSelection);
  $("#sttMeasurementPoint").addEventListener("change",event=>{state.sttMeasurementMs=Number(event.target.value);renderSttWaveform();});
  $("#sttPrevWindow").addEventListener("click",()=>setSttStart(state.sttStart-state.sttDuration*.8));
  $("#sttNextWindow").addEventListener("click",()=>setSttStart(state.sttStart+state.sttDuration*.8));
  $("#sttOpenTwelveLead").addEventListener("click",()=>openSttTwelveLead().catch(handleError));
  $("#openSttGuidance").addEventListener("click",()=>$("#sttGuidanceDialog").showModal());
  $("#openSttLimitations").addEventListener("click",()=>$("#sttGuidanceDialog").showModal());
  $("#sttIsoEarlier").addEventListener("click",()=>nudgeSttMarker("iso",-1));$("#sttIsoLater").addEventListener("click",()=>nudgeSttMarker("iso",1));
  $("#sttJEarlier").addEventListener("click",()=>nudgeSttMarker("j",-1));$("#sttJLater").addEventListener("click",()=>nudgeSttMarker("j",1));
  $("#sttReviewForm").addEventListener("submit",event=>{event.preventDefault();saveSttReviewAnnotation().catch(handleError);});
  $$('[data-edit-mode]').forEach(button=>button.addEventListener("click",()=>setEditMode(button.dataset.editMode)));
  $("#editLeadSelect").addEventListener("change",event=>{state.editLead=event.target.value;$("#editLibraryLeadSelect").value=state.editLead;state.editSelection=null;state.editSelectionStrips=[];state.editMorphDraft=null;closeEditClassPopover();loadEditWaveform().catch(handleError);loadEditTemplateStrips().catch(handleError);});
  $("#editLibraryLeadSelect").addEventListener("change",event=>{state.editLead=event.target.value;$("#editLeadSelect").value=state.editLead;state.editSelection=null;state.editSelectionStrips=[];loadEditWaveform().catch(handleError);loadEditTemplateStrips().catch(handleError);});
  $("#editPrevWindow").addEventListener("click",()=>setEditStart(state.editStart-state.editDuration*.75));
  $("#editNextWindow").addEventListener("click",()=>setEditStart(state.editStart+state.editDuration*.75));
  $("#editLibraryPrevWindow").addEventListener("click",()=>setEditStart(state.editStart-state.editDuration*.75));
  $("#editLibraryNextWindow").addEventListener("click",()=>setEditStart(state.editStart+state.editDuration*.75));
  $("#restoreEditBeatType").addEventListener("click",()=>restoreEditBeatType().catch(handleError));
  $("#clearEditSelection").addEventListener("click",clearEditSelection);
  const updateEditRange=()=>{let start=Number($("#editRangeStart").value),end=Number($("#editRangeEnd").value),top=Number($("#editRangeTop").value),bottom=Number($("#editRangeBottom").value);if(start>end)[start,end]=[end,start];if(top>bottom)[top,bottom]=[bottom,top];$("#editRangeOutput").textContent=`X ${start}–${end}% · Y ${top}–${bottom}%`;};
  ["#editRangeStart","#editRangeEnd","#editRangeTop","#editRangeBottom"].forEach(selector=>$(selector).addEventListener("input",updateEditRange));
  $("#applyEditRange").addEventListener("click",()=>{const rect=$("#editDensityPrimary").getBoundingClientRect();applyMorphologySelection(Number($("#editRangeStart").value)/100,Number($("#editRangeTop").value)/100,Number($("#editRangeEnd").value)/100,Number($("#editRangeBottom").value)/100,rect.left+rect.width*.62,rect.top+rect.height*.38);});
  $("#editClassForm").addEventListener("submit",event=>{event.preventDefault();saveEditClass().catch(handleError);});
  $("#closeEditClassPopover").addEventListener("click",closeEditClassPopover);$("#cancelEditClass").addEventListener("click",closeEditClassPopover);
  $("#editClassName").addEventListener("input",event=>{event.target.dataset.autoGenerated="false";});
  $("#editRhythmFamily").addEventListener("change",()=>{const input=$("#editClassName");if(!state.editEditingTemplateId&&!input.value.trim()){input.value=nextEditTemplateName();input.dataset.autoGenerated="true";}});
  $("#editTemplateInfo").addEventListener("click",()=>{const descriptor=editDescriptor();if(descriptor.type==="custom")openEditClassPopover(window.innerWidth-430,150,descriptor);});
  $("#toggleWaveformFullscreen").addEventListener("click",toggleWaveformFullscreen);
  document.addEventListener("fullscreenchange",()=>{if(state.waveformExpanded&&!document.fullscreenElement&&!state.waveformFullscreenFallback)finishWaveformFullscreenExit()});
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
  $$('[data-event-type]').forEach(button=>button.addEventListener("click",()=>loadEvents(button.dataset.eventType).catch(handleError)));$("#refreshEvents").addEventListener("click",()=>{clinicalWorkflow.resetEvents();loadEvents().catch(handleError);});
  $("#conclusionEditor").addEventListener("input",()=>{state.reportDirty=true;$("#reportSaveState").textContent="有未保存修改";updateConclusionCount()});
  $("#saveReport").addEventListener("click",()=>saveReport("draft").catch(handleError));$("#approveReport").addEventListener("click",()=>saveReport("reviewed").catch(handleError));$("#returnReport").addEventListener("click",()=>saveReport("returned").catch(handleError));
  $("#downloadReport").addEventListener("click",()=>{if(state.caseId)window.location.href=withPhi(`/api/cases/${state.caseId}/report.pdf`)});
  $("#openSourceReport").addEventListener("click",()=>$("#sourceReportDialog").showModal());$("#openReportSettings").addEventListener("click",()=>$("#reportSettingsDialog").showModal());$("#applyReportSettings").addEventListener("click",applyReportSettings);$("#printReport").addEventListener("click",printReportPreview);$("#applyReportTemplate").addEventListener("click",applyReportTemplate);
  $("#reportActivePageSelect").addEventListener("change",event=>setReportActivePage(event.target.value));$("#reportPrevPage").addEventListener("click",()=>moveReportPage(-1));$("#reportNextPage").addEventListener("click",()=>moveReportPage(1));
  $("#reportPageChecklist").addEventListener("change",event=>{const input=event.target.closest?.("[data-report-page]");if(!input)return;const pages=new Set(state.reportComposition.included_pages);input.checked?pages.add(input.value):pages.delete(input.value);if(!pages.size){input.checked=true;toast("报告至少保留一个页面","error");return}state.reportComposition.included_pages=REPORT_PAGES.map(page=>page.key).filter(key=>pages.has(key));if(!pages.has(state.reportComposition.active_page))state.reportComposition.active_page=state.reportComposition.included_pages[0];state.reportComposition.template="custom";markReportCompositionDirty();renderReport();});
  $("#reportPageChecklist").addEventListener("click",event=>{const target=event.target.closest?.("[data-report-activate]");if(target){event.preventDefault();setReportActivePage(target.dataset.reportActivate)}});
  $("#reportEventClasses").addEventListener("click",event=>{const button=event.target.closest?.("[data-report-event]");if(!button)return;state.reportEventFilter=button.dataset.reportEvent;state.reportComposition.preview_mode="event";markReportCompositionDirty();renderReport()});
  $$('[data-report-preview-mode]').forEach(button=>button.addEventListener("click",()=>{state.reportComposition.preview_mode=button.dataset.reportPreviewMode;markReportCompositionDirty();renderReport()}));
  $$('[data-report-page-target]').forEach(button=>button.addEventListener("click",()=>setReportActivePage(button.dataset.reportPageTarget)));
  $$('input[name="reportFastMode"]').forEach(input=>input.addEventListener("change",()=>{if(!input.checked)return;state.reportComposition.fast_slow_mode=input.value;markReportCompositionDirty();renderReport()}));
  $("#reportPreviewBody").addEventListener("click",event=>{const target=event.target.closest?.("[data-report-event-sample],[data-report-strip-sample]");if(target)focusReportEvent(Number(target.dataset.reportEventSample||target.dataset.reportStripSample)).catch(handleError)});
  $("#reportPageSelect").addEventListener("change",event=>showReportPage(Number(event.target.value)));$("#openReportImage").addEventListener("click",()=>{const url=$("#sourceReportImage").dataset.url;if(url)window.open(url,"_blank","noopener");else toast("请先使用右上角隐私开关显示身份信息","error")});
  $("#refreshAudit")?.addEventListener("click",()=>loadAudit().catch(handleError));
  document.addEventListener("keydown",event=>{const contextKey=event.key==="ContextMenu"||event.shiftKey&&event.key==="F10";if(contextKey&&document.activeElement===$("#waveformCanvas")){event.preventDefault();openBeatRelabelMenu(event,$("#waveformCanvas"),state.waveform,"review",true);return}if(contextKey&&[$("#editWaveformCanvas"),$("#editLibraryWaveformCanvas")].includes(document.activeElement)){event.preventDefault();openBeatRelabelMenu(event,document.activeElement,state.editWaveform,"edit",true);return}if(contextKey&&document.activeElement===$("#sttWaveformCanvas")){event.preventDefault();openSttLeadPicker();return}if(event.key==="Escape"&&!$("#beatRelabelMenu").hidden){event.preventDefault();closeBeatRelabelMenu();return}if(event.key==="Escape"&&state.waveformFullscreenFallback){event.preventDefault();exitWaveformFullscreen().catch(handleError);return}if(["INPUT","TEXTAREA","SELECT"].includes(document.activeElement.tagName)||document.activeElement.closest?.(".scatter-review-card")||$("#leadPickerDialog").open||$("#sttLeadDialog").open||$("#sttGuidanceDialog").open)return;const editKey=event.key.toUpperCase(),noModifier=!event.ctrlKey&&!event.metaKey&&!event.altKey;if(noModifier&&state.currentPage==="edit"){const sourceShortcut={N:"source-N",S:"source-S",V:"source-V",X:"source-X"},numberShortcut={1:"source-N",2:"source-S",3:"source-V",4:"source-X"},switchClass=numberShortcut[event.key]||(!state.editSelectedSamples.size?sourceShortcut[editKey]:null);if(switchClass){event.preventDefault();selectEditClass(switchClass);return}if(EDIT_BEAT_TYPES[editKey]){event.preventDefault();applyEditBeatType(editKey).catch(handleError);return}if(event.key==="Backspace"){event.preventDefault();restoreEditBeatType().catch(handleError);return}if(event.key==="Escape"&&state.editSelectedSamples.size){event.preventDefault();state.editSelectedSamples=new Set();state.editSelectionAnchor=null;renderEditGallery();renderEditWaveform();renderEditLibrary();toast("已清除心搏选择");return}}if(event.key==="ArrowLeft"&&state.currentPage==="review"){event.preventDefault();jumpTo(state.start-state.duration*.65)}if(event.key==="ArrowRight"&&state.currentPage==="review"){event.preventDefault();jumpTo(state.start+state.duration*1.35)}if(noModifier&&state.currentPage==="review"&&(event.key==="+"||event.key==="=")){event.preventDefault();zoomWaveform(true,.5)}if(noModifier&&state.currentPage==="review"&&(event.key==="-"||event.key==="_")){event.preventDefault();zoomWaveform(false,.5)}if(noModifier&&state.currentPage==="review"&&event.key==="0"){event.preventDefault();resetWaveformZoom()}if(noModifier&&state.currentPage==="review"&&event.key.toLowerCase()==="f"){event.preventDefault();toggleWaveformFullscreen()}if(noModifier&&state.currentPage==="stt"&&event.key.toLowerCase()==="f"){event.preventDefault();openSttTwelveLead().catch(handleError)}if(event.key.toLowerCase()==="a"&&state.currentPage==="review")openAnnotation();if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==="k"){event.preventDefault();$("#globalSearch").focus()}});
  bindCanvasInteraction();
  bindSttInteraction();
  bindScatterInteraction();
  bindEditInteraction();
  let resizeTimer;window.addEventListener("resize",()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{if(state.currentPage==="review"){renderOverview();renderWaveform();renderScatter();renderScatterSelectionList()}if(state.currentPage==="trends"){renderTrendChart();renderHistogram();renderPoincare()}if(state.currentPage==="stt"){renderSttOverview();renderSttWaveform()}if(state.currentPage==="edit"){if(state.editMode==="library")renderEditLibrary();else{renderEditOverview();renderEditScatter();renderEditGallery();renderEditWaveform();renderEditDensity()}}if(state.currentPage==="report")drawReportPreviewCanvases()},120)});
}

async function init() {
  bindEvents();
  updateWaveformModeUI();
  setLeadPickerSelection(state.leads);
  setSttLeadPickerSelection(state.leads);
  setEditMode("cluster",false);
  renderCaseWorkflow();
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
