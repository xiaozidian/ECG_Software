"use strict";
/* Public mathematical Demo only. Mirrors ecg_core/rr_review.py over ORIGINAL
 * adjacent QRS rows; no clinical data, automatic classification or NN authority.
 * Integration: ECGDemoRR.build(feed, scope), .query(index, params), .resolve(index, target).
 * scope carries case_id/caseId, analysis_basis, analysis_revision, beat_revision;
 * sample_rate_hz (or sample_rate) is optional and defaults to 200 Hz.
 * Fingerprints are FNV-1a 64-bit over UTF-8, explicitly named, never called SHA.
 */
((root) => {
  const METHOD_VERSION = "rr-review-original-qrs-v1";
  const SCHEMA = "cardioinsight.rr-review.v1";
  const IDENTITY_FIELDS = ["case_id", "analysis_basis", "analysis_revision", "beat_revision"];
  const NONBEATS = new Set(["O", "Y", "T"]);
  const SOURCE_GROUP_CODES = new Map([[1, "N"], [2, "S"], [3, "V"], [34, "X"]]);
  const MODES = Object.freeze({rr: ["ms", 25, 2600, "rr_ms"], ratio: ["%", 2.5, 300, "ratio_pct"], hr: ["bpm", 1, 300, "hr_bpm"]});
  const privateTargets = new WeakMap();
  const has = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
  const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
  const finite = value => typeof value === "number" && Number.isFinite(value);
  const sample = value => finite(value) && Number.isSafeInteger(value) && value >= 0;
  const safe = value => value === null || typeof value === "string" || typeof value === "boolean" || finite(value) ? value : null;
  const clone = value => JSON.parse(JSON.stringify(value));
  const pyString = value => value === null || value === undefined ? "None" : value === true ? "True" : value === false ? "False" : String(value);
  const fallbackNames = Object.freeze({N: "正常", S: "房性早搏", V: "室性早搏", J: "交界性早搏", G: "交界性逸搏", P: "起搏（未细分）", PA: "心房起搏", PV: "心室起搏", PD: "双腔起搏", PF: "起搏融合波", B: "束支传导阻滞（未细分）", BL: "左束支传导阻滞", BR: "右束支传导阻滞", A: "房颤", C: "房扑", F: "融合波", E: "室性逸搏", R: "室内差异性传导", W: "房性逸搏", O: "房早未下传", Z: "房早伴室内差异性传导", M: "房颤伴室内差异性传导", H: "房扑伴室内差异性传导", Y: "P波", T: "T波", X: "伪差", OTHER: "其他／未分类"});

  class RRReviewConflict extends Error {
    constructor(message) { super(message); this.name = "RRReviewConflict"; this.status = 409; }
  }
  const conflict = message => { throw new RRReviewConflict(message); };

  // Sorted keys make identity independent of property insertion order. JSON
  // non-finite values are represented as null, matching public RR JSON safety.
  function canonical(value) {
    if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
    if (object(value)) return "{" + Object.keys(value).sort().map(key => JSON.stringify(key) + ":" + canonical(value[key])).join(",") + "}";
    return JSON.stringify(value === undefined || typeof value === "number" && !Number.isFinite(value) ? null : value);
  }
  function fingerprint(value) {
    let hi = 0xcbf29ce4, lo = 0x84222325;
    const byte = value => {
      lo = (lo ^ value) >>> 0;
      const carry = Math.floor(lo * 435 / 4294967296);
      hi = (Math.imul(hi, 435) + carry + ((lo << 8) >>> 0)) >>> 0;
      lo = Math.imul(lo, 435) >>> 0;
    };
    for (let i = 0; i < value.length; i++) {
      let point = value.charCodeAt(i);
      if (point >= 0xd800 && point <= 0xdbff && i + 1 < value.length) {
        const next = value.charCodeAt(i + 1);
        if (next >= 0xdc00 && next <= 0xdfff) { point = 0x10000 + ((point - 0xd800) << 10) + next - 0xdc00; i++; }
        else point = 0xfffd;
      } else if (point >= 0xd800 && point <= 0xdfff) point = 0xfffd;
      if (point < 0x80) byte(point);
      else if (point < 0x800) { byte(0xc0 | point >> 6); byte(0x80 | point & 63); }
      else if (point < 0x10000) { byte(0xe0 | point >> 12); byte(0x80 | point >> 6 & 63); byte(0x80 | point & 63); }
      else { byte(0xf0 | point >> 18); byte(0x80 | point >> 12 & 63); byte(0x80 | point >> 6 & 63); byte(0x80 | point & 63); }
    }
    return "fnv1a64:" + hi.toString(16).padStart(8, "0") + lo.toString(16).padStart(8, "0");
  }
  function identity(input) {
    const scope = object(input) ? {...input} : {};
    if (!has(scope, "case_id") && has(scope, "caseId")) scope.case_id = scope.caseId;
    if (has(scope, "case_id") && has(scope, "caseId") && scope.case_id !== scope.caseId) conflict("RR 病例标识不一致");
    if (!has(scope, "beat_revision") && has(scope, "beatRevision")) scope.beat_revision = scope.beatRevision;
    if (has(scope, "beat_revision") && has(scope, "beatRevision") && scope.beat_revision !== scope.beatRevision) conflict("RR 逐搏修订标识不一致");
    return Object.freeze(Object.fromEntries(IDENTITY_FIELDS.filter(key => has(scope, key)).map(key => [key, scope[key]])));
  }
  function assertIdentity(expected, current) {
    if (has(expected, "caseId") && (!has(current, "case_id") || expected.caseId !== current.case_id)) conflict("RR 目标属于其他病例，未进行定位");
    if (has(expected, "beatRevision") && (!has(current, "beat_revision") || typeof expected.beatRevision === "boolean" || String(expected.beatRevision) !== String(current.beat_revision))) conflict("RR 分析或逐搏修订已变化，请重新载入；未改定位到其他心搏");
    for (const key of IDENTITY_FIELDS) {
      if (has(expected, key) && (typeof expected[key] === "boolean" || !has(current, key) || String(expected[key]) !== String(current[key]))) conflict("RR 分析或逐搏修订已变化，请重新载入；未改定位到其他心搏");
    }
  }
  function spans(excluded) {
    const rows = (Array.isArray(excluded) ? excluded : []).filter(row => Array.isArray(row) && row.length === 2 && row.every(finite) && row[1] > row[0]).map(row => [row[0], row[1]]).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    const merged = [];
    for (const [a, b] of rows) {
      if (merged.length && a <= merged[merged.length - 1][1]) merged[merged.length - 1][1] = Math.max(b, merged[merged.length - 1][1]);
      else merged.push([a, b]);
    }
    return merged;
  }
  function overlaps(a, b, merged) {
    let lo = 0, hi = merged.length;
    while (lo < hi) { const mid = (lo + hi) >>> 1; if (merged[mid][0] < b) lo = mid + 1; else hi = mid; }
    return lo > 0 && merged[lo - 1][1] > a;
  }
  function endpoint(row, document) {
    const code = typeof row.class_code === "string" && row.class_code ? row.class_code : "UNKNOWN";
    const at = row.sample_index;
    const id = row.id !== null && row.id !== undefined ? pyString(row.id) : "s:" + pyString(at);
    const namespace = has(row, "symbol_namespace") ? row.symbol_namespace : "cardioinsight-local";
    const types = object(root.ECGBeatEngine?.types) ? root.ECGBeatEngine.types : fallbackNames;
    const known = has(types, code) && code !== "OTHER" && namespace === "cardioinsight-local";
    const changes = object(document.changes) ? document.changes : {};
    let source = row.classification_source;
    if (!source) {
      if (has(changes, id)) source = "physician_edit";
      else if (id.startsWith("i:")) source = "physician_insert";
      else if (namespace === "cardioinsight-local" && row.source_group !== null && row.source_group !== undefined && code !== (SOURCE_GROUP_CODES.get(row.source_group) || "OTHER")) source = "physician_override";
      else if (row.source_sample !== null && row.source_sample !== undefined && row.source_sample !== at) source = "physician_position_edit";
      else if (row.source_sample !== null && row.source_sample !== undefined || row.source_group !== null && row.source_group !== undefined) source = "source_label";
      else source = "provided_annotation";
    }
    const typeName = object(types[code]) ? types[code].name : types[code];
    const label = row.name || row.label || (known ? typeName : code);
    return Object.freeze({id, sample_index: sample(at) ? at : safe(at), class_code: code, label: pyString(label), source_sample: safe(row.source_sample), source_group: safe(row.source_group), source_symbol: safe(has(row, "source_symbol") ? row.source_symbol : row.source_class_code), classification_source: pyString(source), symbol_namespace: pyString(namespace), type_known: known, review_status: pyString(has(row, "review_status") ? row.review_status : "not_recorded"), label_authority: "原有／人工标签；N 标签本身未证明窦性", kind: row.kind ?? null, group: safe(row.group)});
  }
  function build(feed, scope = {}) {
    if (!object(feed) || !Array.isArray(feed.beats) || feed.beats.some(row => !object(row))) throw new TypeError("RR 源心搏必须为逐搏对象数组");
    if (!object(scope)) throw new TypeError("RR 分析依据必须为对象");
    const fs = has(scope, "sample_rate_hz") ? scope.sample_rate_hz : has(scope, "sample_rate") ? scope.sample_rate : 200;
    if (!finite(fs) || fs <= 0) throw new TypeError("采样率必须为正的有限数值");
    const duration = (has(feed, "duration") ? feed.duration : feed.duration_s) ?? null;
    if (duration !== null && (!finite(duration) || duration < 0)) throw new TypeError("记录时长必须为非负有限数值");
    const document = object(feed.document) ? feed.document : {};
    const settings = object(document.settings) ? document.settings : {};
    const nnMin = settings.nn_min, nnMax = settings.nn_max;
    const settingsKnown = finite(nnMin) && finite(nnMax) && nnMin > 0 && nnMin < nnMax;
    const basis = identity(scope), merged = spans(feed.excluded_rhythm_intervals);
    const qrs = feed.beats.filter(row => !NONBEATS.has(row.class_code) && row.kind !== "nonbeat");
    const sides = qrs.map(row => endpoint(row, document));
    const counts = new Map();
    for (const side of sides) if (sample(side.sample_index)) counts.set(side.sample_index, (counts.get(side.sample_index) || 0) + 1);
    // Include the full ordered original population, source/classification context,
    // settings and rhythm scope. Filtering/pagination never participates in it.
    const indexKey = fingerprint(canonical([METHOD_VERSION, basis, fs, duration, sides.map((side, i) => [side.id, side.sample_index, side.class_code, side.classification_source, safe(qrs[i].rr_ms), side.group, side.kind, side.source_group, side.source_symbol, side.symbol_namespace, side.review_status]), safe(nnMin), safe(nnMax), merged, feed.nn_verification ?? null]));
    const common = Object.freeze({...basis, ...(has(basis, "case_id") ? {caseId: basis.case_id} : {}), index_key: indexKey});
    const clinical = Object.freeze({sinus_verified: false, quality_verified: false, scope_verified: false, status: "not_established", reason: "sinus_and_quality_not_verified"});
    const intervals = [], targets = new Map();
    const qualityPool = new Map();
    for (let i = 1; i < qrs.length; i++) {
      const left = sides[i - 1], right = sides[i];
      const s = left.sample_index, t = right.sample_index;
      const storedPresent = has(qrs[i], "rr_ms") && qrs[i].rr_ms !== null && qrs[i].rr_ms !== undefined;
      const stored = qrs[i].rr_ms;
      const computed = sample(s) && sample(t) ? (t - s) * 1000 / fs : null;
      const start = sample(s) ? s / fs : null, end = sample(t) ? t / fs : null;
      const reasons = [];
      if (!sample(s) || !sample(t)) reasons.push("invalid_sample");
      else if (t <= s) reasons.push("non_increasing_samples");
      if (sample(s) && sample(t) && (counts.get(s) !== 1 || counts.get(t) !== 1)) reasons.push("duplicate_sample");
      if (duration !== null && (sample(s) && s / fs >= duration || sample(t) && t / fs >= duration)) reasons.push("outside_recording");
      if ([left, right].some(side => side.class_code === "X" || side.group === 34 || side.kind === "artifact")) reasons.push("artifact_boundary");
      if ([left, right].some(side => side.class_code === "!")) reasons.push("flutter_no_ordinary_rr");
      if (storedPresent && (!finite(stored) || stored <= 0)) reasons.push("invalid_stored_rr");
      else if (storedPresent && computed !== null && Math.abs(computed - stored) > 10) reasons.push("stored_sample_mismatch");
      const valid = reasons.length === 0 && computed !== null && computed > 0;
      const normal = left.class_code === "N" && right.class_code === "N";
      const excluded = start !== null && end !== null && end > start && overlaps(start, end, merged);
      const nnGeometry = !reasons.some(reason => reason !== "outside_recording") && computed !== null && computed > 0;
      const nnInside = duration !== null && end !== null && end <= duration;
      let nnReason = null;
      if (!nnGeometry) nnReason = reasons[0] || "invalid_interval";
      else if (!storedPresent) nnReason = "missing_stored_rr";
      else if (!normal) nnReason = left.type_known && right.type_known ? "non_normal_label" : "unknown_type";
      else if (!settingsKnown) nnReason = "nn_settings_unknown";
      else if (!nnInside) nnReason = "nn_recording_scope_unknown_or_outside";
      else if (!(nnMin <= stored && stored <= nnMax)) nnReason = "outside_current_nn_bounds";
      else if (excluded) nnReason = "excluded_rhythm_interval";
      const candidate = nnReason === null, known = left.type_known && right.type_known;
      const interpretation = reasons.includes("flutter_no_ordinary_rr") ? "flutter_no_ordinary_rr" : "annotation_timing_not_diagnosis";
      const qualityKey = canonical([reasons, storedPresent, !known, interpretation]);
      let quality = qualityPool.get(qualityKey);
      if (!quality) { quality = Object.freeze({valid, reason: reasons[0] || null, reasons: Object.freeze(reasons), stored_available: storedPresent, classification_unknown: !known, ordinary_rr_interpretation: interpretation}); qualityPool.set(qualityKey, quality); }
      const intervalId = "rr:" + fingerprint(canonical([left.id, right.id, s, t]));
      const targetPossible = sample(s) && sample(t) && counts.get(s) === 1 && counts.get(t) === 1 && (duration === null || t / fs < duration);
      const previous = intervals[intervals.length - 1];
      const ratio = valid && previous && previous.quality.valid ? computed / previous.rr_ms * 100 : null;
      const row = {id: intervalId, index: i - 1, start_sample: s, end_sample: t, time_s: end, left, right, left_type: left.class_code, right_type: right.class_code, pair_type: JSON.stringify([left.class_code, right.class_code]), stored_rr_ms: safe(stored), computed_rr_ms: computed, rr_ms: valid ? computed : null, ratio_pct: ratio, hr_bpm: valid ? 60000 / computed : null, type_known: known, quality, normal_pair: normal, normal_label_pair: normal, nn_candidate_compat: candidate, nn_eligible_current_rules: candidate, nn_reason: nnReason, nn_rule_rr_ms: safe(stored), nn_eligible_verified: false, nn_verified_reason: nnReason || (!valid ? "outside_recording" : clinical.reason), clinical_verification: clinical};
      // Generate the complete exact target only when a result is expanded.
      Object.defineProperty(row, "target", {enumerable: true, get: () => targetPossible ? {...common, sample_index: t, beat_id: right.id, interval_id: intervalId, interval_start_sample: s, interval_end_sample: t} : null});
      if (ratio !== null) { row.ratio_previous_interval_id = previous.id; row.ratio_previous_start_sample = previous.start_sample; }
      else row.ratio_reason = previous ? "preceding_original_interval_unavailable" : "no_preceding_original_interval";
      Object.freeze(row); intervals.push(row);
      if (targetPossible) targets.set(t, row);
    }
    const method = Object.freeze({rr: "RR = 原始相邻 QRS 样本差 × 1000 / 采样率；保留输入 RR，沿用 10 ms 一致性容差。首搏无间期。", ratio: "R/R = RR(i) / RR(i−1) × 100%；沿用现有工程方向，医院定义尚未核实。使用原序列前一间期。", hr: "逐间期心率 = 60000 / RR(ms)，单位 bpm；展示未舍入值分箱，不判定诊断。", normal_pair: "normal_label_pair 仅表示原标签两端为 N；源 N 未证明窦性。", nn: "nn_candidate_compat / nn_eligible_current_rules 仅沿用当前 NN 范围、存储 RR 与完整间期节律排除；属于工程筛选候选。", verified_nn: "公开数学 Demo 不提供窦性或质量核实证据；nn_eligible_verified 始终为 false。", classification: "有序类型按原符号分组；不采用历史 WFDB map1 将起搏、Q 或其他类型归 N；不推断医院亚型。", manual_review: "公开数学 Demo，只读演示；原标签、筛选候选及分布不构成诊断或医生复核完成，也不是金标准。", unknown: "未知类型保留原符号；! 保留边界但无普通 RR 解释；O/Y/T 不作 QRS 边界；伪差不被删去桥接。", population: "RR 按终搏时间归属左闭右开窗口；NN 兼容规则保留终点≤记录时长的原有边界，记录外目标不可定位。", nn_min_ms: safe(nnMin), nn_max_ms: safe(nnMax), nn_settings_known: settingsKnown, duration_known: duration !== null, hospital_mapping_verified: false, fingerprint_algorithm: "FNV-1a 64-bit UTF-8; deterministic identity fingerprint, not SHA or clinical evidence", references: Object.freeze(["https://physionet.org/physiotools/wag/ann2rr-1.htm", "https://physionet.org/content/wfdb/10.7.0/lib/ecgmap.h"])});
    const summary = Object.freeze({qrs_count: qrs.length, non_qrs_marker_count: feed.beats.length - qrs.length + (Array.isArray(feed.markers) ? feed.markers.length : 0), interval_count: intervals.length, valid_rr_count: intervals.filter(row => row.quality.valid).length, invalid_count: intervals.filter(row => !row.quality.valid).length, unknown_type_count: intervals.filter(row => !row.type_known).length, normal_pair_count: intervals.filter(row => row.normal_pair).length, nn_eligible_count: intervals.filter(row => row.nn_candidate_compat).length, nn_verified_count: 0});
    const index = Object.freeze({schema: SCHEMA, method_version: METHOD_VERSION, method, basis, index_key: indexKey, sample_rate_hz: fs, duration_s: duration, summary, intervals: Object.freeze(intervals)});
    privateTargets.set(index, targets);
    return index;
  }
  function number(query, name, fallback = null) {
    const value = has(query, name) ? query[name] : fallback;
    if (value === null || value === undefined || value === "") return fallback;
    if (typeof value === "boolean" || !(typeof value === "number" || typeof value === "string") || typeof value === "string" && !value.trim()) throw new TypeError(name + " 必须为有限数值");
    const parsed = Number(value);
    if (!finite(parsed)) throw new TypeError(name + " 必须为有限数值");
    return parsed;
  }
  function integer(query, name, fallback, low = 0, high = null) {
    const value = number(query, name, fallback);
    if (!Number.isSafeInteger(value) || value < low || high !== null && value > high) throw new TypeError(name + " 整数范围无效");
    return value;
  }
  function histogram(rows, mode) {
    const [unit, step, ceiling, field] = MODES[mode];
    const bins = Array.from({length: ceiling / step}, (_, i) => ({start: i * step, end: (i + 1) * step, count: 0, overflow: false}));
    bins.push({start: ceiling, end: null, count: 0, overflow: true});
    for (const row of rows) { const value = row[field]; if (finite(value) && value >= 0) bins[Math.min(Math.floor(value / step), bins.length - 1)].count++; }
    return {mode, unit, bin_width: step, bins, measurement_count: bins.reduce((sum, bin) => sum + bin.count, 0), population_count: rows.length};
  }
  function assertIndex(index) {
    if (!privateTargets.has(index)) throw new TypeError("RR 索引必须由当前 Demo 适配器构建");
  }
  function resolve(index, target) {
    assertIndex(index);
    if (!object(target)) throw new TypeError("精确 RR 目标必须为对象");
    if (IDENTITY_FIELDS.some(key => has(index.basis, key) && !has(target, key))) conflict("精确目标缺少完整病例／修订依据，请重新选择");
    for (const key of ["analysis_revision", "beat_revision"]) if (has(index.basis, key) && (!Number.isSafeInteger(target[key]) || !Number.isSafeInteger(index.basis[key]))) conflict("目标修订必须为当前整数修订");
    if (["beat_id", "interval_id", "interval_start_sample", "interval_end_sample", "index_key"].some(key => !has(target, key))) conflict("精确目标缺少原心搏与双端点身份，请重新选择");
    assertIdentity(target, index.basis);
    if (target.index_key !== index.index_key) conflict("RR 源间期已变化，请重新选择目标");
    if (!sample(target.sample_index)) throw new TypeError("目标样本必须为非负整数");
    const row = privateTargets.get(index).get(target.sample_index);
    if (!row) conflict("目标心搏不存在或已移除；未改定位到最近心搏");
    const exact = row.target;
    for (const key of ["beat_id", "interval_id", "interval_start_sample", "interval_end_sample"]) if (target[key] !== exact[key] || ["interval_start_sample", "interval_end_sample"].includes(key) && !sample(target[key])) conflict("目标心搏或原始间期端点已变化，请重新选择");
    return {...exact};
  }
  function query(index, params = {}) {
    assertIndex(index);
    if (params instanceof URLSearchParams) params = Object.fromEntries(params.entries());
    if (!object(params)) throw new TypeError("RR 查询必须为对象");
    const input = {...params};
    assertIdentity(input, index.basis);
    if (has(input, "index_key") && input.index_key !== index.index_key) conflict("RR 源间期已变化，请重新载入");
    const mode = has(input, "mode") ? input.mode : "rr";
    const population = has(input, "population") ? input.population : "all", quality = has(input, "quality") ? input.quality : "all";
    if (typeof mode !== "string" || !has(MODES, mode)) throw new TypeError("RR 模式必须为 rr、ratio 或 hr");
    if (!["all", "normal_pair", "nn_eligible", "nn_verified", "unknown"].includes(population)) throw new TypeError("RR 总体筛选无效");
    if (!["all", "valid", "invalid"].includes(quality)) throw new TypeError("RR 质量筛选无效");
    const start = number(input, "start_s", 0), end = number(input, "end_s", index.duration_s);
    if (start < 0 || end !== null && (end < start || index.duration_s !== null && end > index.duration_s)) throw new TypeError("RR 时间窗口超出记录或顺序无效");
    const lo = number(input, "range_min"), hi = number(input, "range_max");
    if (lo !== null && lo < 0 || hi !== null && hi < 0 || lo !== null && hi !== null && hi <= lo) throw new TypeError("RR 数值范围必须为非负左闭右开区间");
    const offset = integer(input, "offset", 0), limit = integer(input, "limit", 20, 1, 200);
    let pairType = input.pair_type ?? "all";
    if (pairType === "") pairType = "all";
    if (typeof pairType !== "string") throw new TypeError("间期类型必须为原符号二元 JSON 或 all");
    if (pairType !== "all") {
      let pair;
      try { pair = JSON.parse(pairType); } catch (_) { throw new TypeError("间期类型必须为原符号二元 JSON"); }
      if (!Array.isArray(pair) || pair.length !== 2 || pair.some(value => typeof value !== "string")) throw new TypeError("间期类型必须为原符号二元 JSON");
      pairType = JSON.stringify(pair);
    }
    const base = index.intervals.filter(row => {
      const at = row.time_s;
      if (at !== null && (at < start || end !== null && at >= end)) return false;
      if (at === null && (start !== 0 || end !== index.duration_s)) return false;
      if (population === "normal_pair" && !row.normal_pair || population === "nn_eligible" && !row.nn_candidate_compat || population === "nn_verified" && !row.nn_eligible_verified || population === "unknown" && row.type_known) return false;
      return !(quality === "valid" && !row.quality.valid || quality === "invalid" && row.quality.valid);
    });
    const counts = new Map();
    for (const row of base) {
      let facet = counts.get(row.pair_type);
      if (!facet) { facet = {code: row.pair_type, left_type: row.left_type, right_type: row.right_type, total: 0, valid_rr_count: 0, unknown_count: 0}; counts.set(row.pair_type, facet); }
      facet.total++; facet.valid_rr_count += Number(row.quality.valid); facet.unknown_count += Number(!row.type_known);
    }
    const cohort = base.filter(row => pairType === "all" || row.pair_type === pairType);
    const field = MODES[mode][3];
    const selected = cohort.filter(row => lo === null && hi === null || finite(row[field]) && (lo === null || row[field] >= lo) && (hi === null || row[field] < hi));
    const total = selected.length;
    // Copy page values so a consumer cannot mutate the immutable original index.
    const items = selected.slice(offset, offset + limit).map((row, i) => ({...row, left: {...row.left}, right: {...row.right}, quality: {...row.quality, reasons: [...row.quality.reasons]}, clinical_verification: {...row.clinical_verification}, match_index: offset + i}));
    let target = null;
    if (has(input, "target_sample_index")) {
      const wanted = integer(input, "target_sample_index", 0), original = privateTargets.get(index).get(wanted);
      if (!original) conflict("目标心搏不存在或已移除；未改定位到最近心搏");
      target = resolve(index, {...original.target, ...Object.fromEntries(["index_key", "beat_id", "interval_id", "interval_start_sample", "interval_end_sample"].filter(key => has(input, key)).map(key => [key, input[key]]))});
    }
    return {schema: SCHEMA, method_version: METHOD_VERSION, method: clone(index.method), ...index.basis, ...(has(index.basis, "case_id") ? {caseId: index.basis.case_id} : {}), index_key: index.index_key, sample_rate_hz: index.sample_rate_hz, duration_s: index.duration_s, summary: {...index.summary}, query: {mode, population, quality, pair_type: pairType, start_s: start, end_s: end, range_min: lo, range_max: hi, offset, limit}, total, offset, limit, has_previous: offset > 0 && total > 0, has_next: offset + limit < total, items, target, pair_types: [...counts.values()], histogram: histogram(cohort, mode), selected_histogram: histogram(selected, mode)};
  }
  const api = Object.freeze({build, query, resolve, RRReviewConflict, fingerprint, METHOD_VERSION, SCHEMA});
  root.ECGDemoRR = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(globalThis);
"use strict";
/* Browser-only mathematical review state. No patient, sinus gold standard or clinical certification. */
globalThis.ECGDemoReviewAPI = (() => {
  const PROFILE = 'fixed-300s-fft-compat-v1', SCOPE = ['case_id','source_digest','data_version','analysis_basis','beat_revision','analysis_revision'], SOURCE=SCOPE.filter(k=>k!=='analysis_revision');
  const STT_SAVE_KIND='browser-math-content-digest-v1', STT_IDENTITY=['case_id','analysis_basis','analysis_revision','beat_revision'];
  const clone=value=>JSON.parse(JSON.stringify(value));
  const sorted=value=>Array.isArray(value)?value.map(sorted):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(key=>[key,sorted(value[key])])):value;
  const encode=value=>JSON.stringify(sorted(value));
  async function digest(value){const bytes=new TextEncoder().encode(encode(value));const hash=await globalThis.crypto.subtle.digest('SHA-256',bytes);return Array.from(new Uint8Array(hash),b=>b.toString(16).padStart(2,'0')).join('');}
  function error(message,status=400){const e=new Error(message);e.status=status;throw e;}
  function integer(value,label,low=0,high=Number.MAX_SAFE_INTEGER){if(!Number.isSafeInteger(value)||value<low||value>high)error(label+'整数范围无效');return value;}
  function object(value,keys,label){if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).some(k=>!keys.includes(k)))error(label+'字段无效');return value;}
  function text(value,label,max=4000,empty=false){if(typeof value!=='string'||value.length>max||(!empty&&!value.trim())||/[<>]|&(?:#(?:x[0-9a-f]+|[0-9]+)|[a-z]+);|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u202a-\u202e\u2066-\u2069]/i.test(value))error(label+'必须为受支持的纯文本');return value;}
  function ident(value,label,pattern=/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$/){if(typeof value!=='string'||!pattern.test(value))error(label+'标识格式无效');return value;}
  function sourceUrl(value,label){text(value,label,1000,true);if(!value)return '';let url;try{url=new URL(value);}catch{error(label+'来源URL无效');}if(url.protocol!=='https:'||url.username||url.password||/^https:\/\/[^/?#]*@/i.test(value)||url.port||!/^[A-Za-z][A-Za-z-]{1,62}$/.test(url.hostname.split('.').at(-1))||!url.hostname.includes('.')||/\.(local|localhost|internal)$/i.test(url.hostname)||/[\s\\<>\x00-\x1f]/.test(decodeURIComponent(value)))error(label+'须为公开HTTPS URL，不能含凭据或本地地址');return value;}
  function source(value){object(value,['name','url','verification'],'source');if(value.verification!=='declared')error('来源仅支持文件声明，软件未独立验证');return {name:text(value.name,'source.name',300),url:sourceUrl(value.url,'source.url'),verification:'declared'};}
  function license(value){object(value,['name','url','text'],'license');return {name:text(value.name,'license.name',160),url:sourceUrl(value.url,'license.url'),text:text(value.text,'license.text',8000)};}
  function scope(value){object(value,['population','recording'],'scope');const result={};for(const [key,allowed]of [['population',['adult','pediatric']],['recording',['resting_12lead','holter']]]){const items=value[key];if(!Array.isArray(items)||!items.length||items.length>allowed.length||new Set(items).size!==items.length||items.some(x=>!allowed.includes(x)))error('术语适用范围无效');result[key]=items.slice();}return result;}
  function approval(value){if(!['draft','approved','rejected'].includes(value))error('术语审核状态无效');return value;}
  function review(value){object(value,['reviewer','reviewed_at'],'review');const result={reviewer:text(value.reviewer,'reviewer',160,true),reviewed_at:text(value.reviewed_at,'reviewed_at',40,true)};if(result.reviewed_at&&(!/(?:Z|[+-]\d\d:\d\d)$/.test(result.reviewed_at)||!Number.isFinite(Date.parse(result.reviewed_at))))error('审核时间须为含时区ISO时间');return result;}
  async function validateCatalog(raw){
    if(new TextEncoder().encode(JSON.stringify(raw)).length>1048576)error('目录超过1MiB大小限制');
    object(raw,['schema_version','namespace','version','sha256','title','description','completeness','approval','source','license','scope','nodes'],'catalog');if(raw.schema_version!==1||!['example','partial','complete'].includes(raw.completeness))error('目录schema或完整性声明无效');if(!Array.isArray(raw.nodes)||raw.nodes.length<1||raw.nodes.length>1200)error('目录必须包含1至1200个节点');
    const result={schema_version:1,namespace:ident(raw.namespace,'namespace',/^[A-Za-z][A-Za-z0-9_.-]{2,95}$/),version:ident(raw.version,'version',/^[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}$/),title:text(raw.title,'title',160),description:text(raw.description,'description',2000),completeness:raw.completeness,approval:approval(raw.approval),source:source(raw.source),license:license(raw.license),scope:scope(raw.scope),nodes:[]},lookup=new Map();
    for(const item of raw.nodes){object(item,['stable_id','parent_id','kind','label','text','aliases','approval','source','license','scope','deprecated','replacement_id','review'],'node');const id=ident(item.stable_id,'stable_id');if(lookup.has(id))error('stable_id重复');if(!['group','term'].includes(item.kind))error('节点kind无效');if(item.parent_id!==null)ident(item.parent_id,'parent_id');if(item.replacement_id!==null)ident(item.replacement_id,'replacement_id');const value=text(item.text,'text',4000,item.kind==='group');if(item.kind==='group'&&value)error('分组不可包含插入正文');if(!Array.isArray(item.aliases)||item.aliases.length>20||new Set(item.aliases).size!==item.aliases.length)error('aliases无效');if(typeof item.deprecated!=='boolean'||item.replacement_id!==null&&(!item.deprecated||item.kind!=='term'))error('废弃或替代标识无效');const node={stable_id:id,parent_id:item.parent_id,kind:item.kind,label:text(item.label,'label',160),text:value,aliases:item.aliases.map(a=>text(a,'alias',160)),approval:approval(item.approval),source:source(item.source),license:license(item.license),scope:scope(item.scope),deprecated:item.deprecated,replacement_id:item.replacement_id,review:review(item.review)};result.nodes.push(node);lookup.set(id,node);}
    for(const node of result.nodes){if(node.parent_id!==null&&lookup.get(node.parent_id)?.kind!=='group')error('父节点须为存在的分组');const seen=new Set();let cursor=node,depth=0;while(cursor){if(seen.has(cursor.stable_id))error('术语树循环');if(++depth>8)error('术语树深度超过8');seen.add(cursor.stable_id);cursor=lookup.get(cursor.parent_id);}if(node.replacement_id!==null){const next=lookup.get(node.replacement_id);if(!next||next===node||next.kind!=='term'||next.deprecated)error('替代词条不存在或无效');}}
    if(!result.nodes.some(n=>n.kind==='term'))error('至少需要一个词条');result.sha256=await digest(result);if(raw.sha256!==undefined&&raw.sha256!==null&&raw.sha256!==result.sha256)error('sha256与目录内容不匹配');return result;
  }
  function normalizeUsages(value){if(value===undefined||value===null)return [];if(!Array.isArray(value)||value.length>500)error('术语使用记录最多500条');const seen=new Set();return value.map(raw=>{object(raw,['usage_id','namespace','version','catalog_hash','stable_id','label','inserted_text','approval','source','license','scope','review','inserted_at'],'terminology_usages');const uid=ident(raw.usage_id,'usage_id');if(seen.has(uid))error('usage_id重复');seen.add(uid);if(!/^[0-9a-f]{64}$/.test(raw.catalog_hash))error('catalog_hash无效');const inserted=review({reviewer:'',reviewed_at:raw.inserted_at}).reviewed_at;if(!inserted)error('inserted_at不能为空');return {usage_id:uid,namespace:ident(raw.namespace,'namespace',/^[A-Za-z][A-Za-z0-9_.-]{2,95}$/),version:ident(raw.version,'version',/^[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}$/),catalog_hash:raw.catalog_hash,stable_id:ident(raw.stable_id,'stable_id'),label:text(raw.label,'label',160),inserted_text:text(raw.inserted_text,'inserted_text'),approval:approval(raw.approval),source:source(raw.source),license:license(raw.license),scope:scope(raw.scope),review:review(raw.review||{reviewer:'',reviewed_at:''}),inserted_at:inserted};});}
  const profile={id:PROFILE,sample_rate_hz:200,block_seconds:300,minimum_nn_count:30,minimum_nn_coverage_s:240,quality_status:'unknown',eligibility_basis:'existing N labels, saved NN bounds and rhythm exclusions; no verified sinus or signal gold standard',eligibility_standard:'existing engineering compatibility protocol, not a universal guideline',pnn50:{threshold_ms:50,comparison:'strictly_greater',denominator:'eligible consecutive NN differences',unit:'percent'},sdnn:{unit:'ms',variance_ddof:1,minimum_count:3},spectrum:{method:'FFT',resample_hz:4,samples:1024,window:'symmetric Hann',density_unit:'ms²/Hz',band_unit:'ms²',gap_limit_s:5,aggregation:'mean of qualified fixed-grid short-segment spectra',vlf_interpretation:'exploratory',ulf_available:false,lf_hf_ratio:'ratio of bands rounded to 4 decimals; null when rounded HF is zero'},exclusion_interval:'half-open sample intervals; preserve original NN adjacency and 300-second grid',confirmation_scope:'browser mathematical review declaration for one current window; not clinical validation or sinus-rhythm gold standard'};
  const mean=a=>a.length?a.reduce((s,x)=>s+x,0)/a.length:null,sd=a=>a.length>1?Math.sqrt(a.reduce((s,x)=>s+(x-mean(a))**2,0)/(a.length-1)):null,round=(x,n=4)=>x===null||!Number.isFinite(x)?null:Math.round(x*10**n)/10**n;
  function spans(exclusions){const result=[];for(const e of [...exclusions].sort((a,b)=>a.start_sample-b.start_sample||a.end_sample-b.end_sample)){const a=e.start_sample/200,b=e.end_sample/200;if(result.length&&a<=result.at(-1)[1])result.at(-1)[1]=Math.max(b,result.at(-1)[1]);else result.push([a,b]);}return result;}
  const seconds=(items,a,b)=>items.reduce((sum,[x,y])=>sum+Math.max(0,Math.min(y,b)-Math.max(x,a)),0);
  function spectralReason(nn,excluded){const times=nn.map(r=>r[2]);if(times.length<2)return 'too_few_nn_observations';if(nn.some(r=>!Number.isFinite(r[2])||!Number.isFinite(r[3]))||times.some((t,i)=>i&&t<=times[i-1]))return 'invalid_nn_time_order';if(times.at(-1)-times[0]<255.75)return 'insufficient_spectral_observation_span';const start=(times[0]+times.at(-1)-255.75)/2;let k=1;for(let i=0;i<1024;i++){const t=start+i/4;while(k<times.length-1&&times[k]<=t)k++;if(times[k]-times[k-1]>5)return 'spectral_gap_over_5s';if(excluded.some(([a,b])=>a<times[k]&&b>times[k-1]))return 'spectral_interpolation_crosses_exclusion';}return '';}
  function block(nn,a,b,gridEnd,excluded){const values=nn.map(r=>r[3]),diffs=[],bins=new Map();for(let i=1;i<nn.length;i++)if(nn[i][0]===nn[i-1][0]+1)diffs.push(nn[i][3]-nn[i-1][3]);for(const v of values){const key=Math.floor(v/7.8125);bins.set(key,(bins.get(key)||0)+1);}const reasons=[];if(b<gridEnd)reasons.push('incomplete_300s_block');if(nn.length<30)reasons.push('nn_count_below_30');if(values.reduce((s,v)=>s+v,0)<240000)reasons.push('nn_coverage_below_240s');const qualified=!reasons.length;let reason=qualified?spectralReason(nn,excluded):'block_not_qualified',psd=qualified&&!reason?ECGHrvAnalysis.spectrum(nn,excluded):null;if(!psd&&!reason)reason='spectrum_unavailable';const band=(lo,hi)=>psd?round(psd.reduce((s,p,k)=>s+(k*4/1024>=lo&&k*4/1024<hi?p*4/1024:0),0)):null,lf=band(.04,.15),hf=band(.15,.4);return {nn_count:values.length,coverage_s:round(b-a,3),valid_nn_s:round(values.reduce((s,v)=>s+v,0)/1000,3),mean_nn_ms:round(mean(values),2),sdnn_ms:values.length>=3?round(sd(values),2):null,rmssd_ms:diffs.length?round(Math.sqrt(mean(diffs.map(v=>v*v))),2):null,pnn50_pct:diffs.length?round(100*diffs.filter(v=>Math.abs(v)>50).length/diffs.length,2):null,nn50_count:diffs.filter(v=>Math.abs(v)>50).length,consecutive_difference_count:diffs.length,sdann_ms:null,sdnn_index_ms:qualified?round(sd(values)):null,triangular_index:bins.size?round(values.length/Math.max(...bins.values())):null,histogram:[...bins].sort((x,y)=>x[0]-y[0]).map(([k,count])=>({rr_ms:round(k*7.8125),count})),qualified,qualification_reasons:reasons,spectral_qualified:!!psd,spectral_reason:reason,psd:psd?psd.map((p,k)=>({hz:k*4/1024,power:round(p)})):[],frequency:{total_ms2:band(.0033,.4),vlf_ms2:band(.0033,.04),lf_ms2:lf,hf_ms2:hf,lf_hf:hf?round(lf/hf):null},five_minute_blocks:Number(qualified),spectral_blocks:Number(!!psd),spectral_coverage_s:psd?256:0,nn_eligible_count:nn.length,quality_status:'unknown',sinus_verified:false,nn_verified_count:0};}
  function analyze(feed,startTime,window=0,exclusions=[]){const masks=spans(exclusions),projected={...feed,excluded_rhythm_intervals:[...(feed.excluded_rhythm_intervals||[]),...masks]},baseline=ECGHrvAnalysis.analyze(feed,startTime,window),reviewed=masks.length?ECGHrvAnalysis.analyze(projected,startTime,window):clone(baseline),original=ECGRRQuality.nnIntervals(feed),changed=ECGRRQuality.nnIntervals(projected),lo=baseline.start_s,hi=baseline.end_s,blocks=[];for(let k=0;k<Math.ceil((hi-lo)/300);k++){const a=lo+k*300,gridEnd=a+300,b=Math.min(hi,gridEnd),excludedS=seconds(masks,a,b);blocks.push({id:'5m-'+Math.round(a*200)+'-'+Math.round(gridEnd*200),window_index:window,grid_index:k,start_sample:Math.round(a*200),end_sample:Math.round(b*200),grid_end_sample:Math.round(gridEnd*200),start_s:a,end_s:b,duration_s:b-a,complete:b===gridEnd,excluded_s:round(excludedS,6),retained_s:round(b-a-excludedS,6),baseline:block(original.filter(r=>r[1]>=a&&r[2]<=b),a,b,gridEnd,feed.excluded_rhythm_intervals||[]),reviewed:block(changed.filter(r=>r[1]>=a&&r[2]<=b),a,b,gridEnd,projected.excluded_rhythm_intervals),hour_overlaps:baseline.hourly.map((h,i)=>h.start_s<b&&h.end_s>a?i:null).filter(i=>i!==null)});}return {baseline,reviewed,blocks,coverage:{record_start_s:0,record_end_s:feed.duration,window_start_s:lo,window_end_s:hi,excluded_s:round(seconds(masks,lo,hi),6),retained_s:round(hi-lo-seconds(masks,lo,hi),6),clock_available:baseline.clock_available,hourly:baseline.hourly.map(h=>({start_s:h.start_s,end_s:h.end_s,partial:h.partial}))},profile:clone(profile),exclusions:clone(exclusions),simulation:{browser_computed:true,real_patient_inputs_read:false,clinical_validation:false,quality_status:'unknown',verified_nn_count:0}};}
  function create(env){
    const blank=()=>({schema_version:1,profile:PROFILE,exclusions:[]});let builtinPromise=null;
    const assertScope=(expected,current,complete=false)=>{if(complete)object(expected,SCOPE,'scope');for(const k of SCOPE){const v=expected?.[k];if(complete&&(v===undefined||typeof v!==typeof current[k]))error('缺少完整复核scope');if(v!==undefined&&String(v)!==String(current[k]))error('数学Demo复核依据已变化，请重新读取',409);}};
    const currentScope=()=>clone(env.scope());
    const windowIndex=value=>{if(typeof value==='string'){if(!/^\d+$/.test(value))error('HRV窗口须为非负整数');value=Number(value);}return integer(value===undefined?0:value,'HRV窗口',0,Math.max(0,Math.ceil(env.duration/86400)-1));};
    const document=value=>{object(value,['schema_version','profile','exclusions'],'HRV文档');if(value.schema_version!==1||value.profile!==PROFILE||!Array.isArray(value.exclusions)||value.exclusions.length>500)error('HRV文档或排除列表无效');const seen=new Set(),exclusions=value.exclusions.map(raw=>{object(raw,['id','start_sample','end_sample','reason'],'HRV排除');const id=ident(raw.id,'排除id',/^[A-Za-z0-9_-]{1,100}$/);if(seen.has(id))error('排除id重复');seen.add(id);const a=integer(raw.start_sample,'排除起点',0,Math.round(env.duration*200)),b=integer(raw.end_sample,'排除终点',0,Math.round(env.duration*200));if(a>=b)error('排除起点须早于终点');return {id,start_sample:a,end_sample:b,reason:text(raw.reason,'排除原因',500).trim()};}).sort((a,b)=>a.start_sample-b.start_sample||a.end_sample-b.end_sample||a.id.localeCompare(b.id));return {schema_version:1,profile:PROFILE,exclusions};};
    const state=scope=>clone(env.saved().hrvReviews?.[env.caseId]||{revision:0,document:blank(),document_scope:scope,confirmations:{},undo:[],redo:[],updated_at:null});
    const same=(a,b,keys=SCOPE)=>!!a&&!!b&&keys.every(k=>a[k]===b[k]);
    async function publicState(value,scope,window){const hash=await digest(value.document),confirmations=clone(value.confirmations||{}),region={window_index:window,start_sample:window*86400*200,end_sample:Math.min(Math.round(env.duration*200),(window+1)*86400*200)};for(const entry of Object.values(confirmations))entry.valid=same(entry.scope,scope)&&entry.hrv_revision===value.revision&&entry.document_digest===hash;return {scope,hrv_revision:value.revision,document:clone(value.document),document_scope:clone(value.document_scope),document_stale:!same(value.document_scope,scope,SOURCE),digest:hash,document_digest:hash,confirmations,confirmation:confirmations[String(window)]||{valid:false,status:'pending',...region},can_undo:!!value.undo?.length,can_redo:!!value.redo?.length,updated_at:value.updated_at,profile:PROFILE,...region,simulation:{browser_computed:true,real_patient_inputs_read:false,clinical_validation:false,verified_nn_count:0}};}
    const expected=(payload,scope,value)=>{assertScope(payload.scope,scope,true);integer(payload.expected_hrv_revision,'HRV版本');if(payload.expected_hrv_revision!==value.revision)error('HRV已有新修订，请重新读取',409);};
    const saveState=value=>{(env.saved().hrvReviews||(env.saved().hrvReviews={}))[env.caseId]=clone(value);};
    async function read(window=0,query={}){window=windowIndex(window);const scope=currentScope();assertScope(query,scope);const value=state(scope),result=await publicState(value,scope,window);const evidence=analyze(env.feed(),env.startTime,window,result.document_stale?[]:value.document.exclusions);if(result.document_stale){evidence.reviewed=null;evidence.reason='document_stale';}assertScope(scope,currentScope(),true);return {...result,evidence};}
    async function reference(window=0){const result=await read(window);return {hrv_revision:result.hrv_revision,document_digest:result.digest,window_index:result.window_index,profile:PROFILE,scope:result.scope};}
    async function analysis(window=0,query={}){const result=await read(window,query);if(result.document_stale)error('HRV排除区间来自旧数学依据，请预览并保存当前区间',409);const data=result.evidence.reviewed;return {...data,hrv_review:result,hrv_review_reference:{hrv_revision:result.hrv_revision,document_digest:result.digest,window_index:result.window_index,profile:PROFILE,scope:result.scope},review_profile:result.evidence.profile,review_coverage:result.evidence.coverage,simulation:result.simulation};}
    async function hrvRoute(action,method,payload,query){const scope=currentScope(),value=state(scope),window=windowIndex(method==='GET'?query.window:payload.window);if(action==='hrv-review'&&method==='GET')return read(window,query);expected(payload,scope,value);
      if(action==='hrv-review/preview'&&method==='POST'){const operation=payload.operation;let target;if(operation==='replace')target=document(payload.document);else if(operation==='reset')target=blank();else if(['undo','redo'].includes(operation)){if(!value[operation]?.length)error('没有可撤销或重做的HRV修订');target=document(value[operation].at(-1));}else error('HRV操作不受支持');const body={scope,expected_hrv_revision:value.revision,operation,before_digest:await digest(value.document),document:target,window,profile:PROFILE},hash=await digest(body),token=globalThis.crypto.randomUUID();assertScope(scope,currentScope(),true);if(state(scope).revision!==value.revision)error('HRV预览期间已有新修订',409);(env.saved().hrvPreviews||(env.saved().hrvPreviews={}))[env.caseId]={token,hash,body,created_at:Date.now()};env.persist();return {preview_token:token,preview_digest:hash,scope,expected_hrv_revision:value.revision,operation,before:value.document,after:target,window_index:window,expires_in_s:900,profile:PROFILE,evidence_preview:analyze(env.feed(),env.startTime,window,target.exclusions)};}
      if(action==='hrv-review/cancel'&&method==='POST'){if(typeof payload.preview_token!=='string')error('缺少预览凭证');if(env.saved().hrvPreviews?.[env.caseId]?.token===payload.preview_token)delete env.saved().hrvPreviews[env.caseId];env.persist();return publicState(value,scope,window);}
      if(action==='hrv-review'&&method==='PUT'){if(payload.confirmed!==true)error('请明确确认预览后保存');const preview=env.saved().hrvPreviews?.[env.caseId];if(!preview||preview.token!==payload.preview_token||Date.now()-preview.created_at>900000||Date.now()<preview.created_at||!same(preview.body.scope,scope)||preview.body.expected_hrv_revision!==value.revision||preview.body.window!==window||preview.hash!==payload.preview_digest||await digest(preview.body)!==preview.hash)error('HRV预览已过期、取消或依据变化',409);const target=document(preview.body.document);assertScope(scope,currentScope(),true);const changed=encode(target)!==encode(value.document)||!same(value.document_scope,scope,SOURCE);delete env.saved().hrvPreviews[env.caseId];if(changed){const operation=preview.body.operation;if(['undo','redo'].includes(operation)){value[operation].pop();value[operation==='undo'?'redo':'undo'].push(value.document);}else{value.undo.push(value.document);value.redo=[];}value.undo=value.undo.slice(-20);value.redo=value.redo.slice(-20);value.document=target;value.revision++;value.confirmations={};value.updated_at=new Date().toISOString();env.changed('hrv_review.changed');value.document_scope=currentScope();saveState(value);}env.persist();return publicState(value,currentScope(),window);}
      if(action==='hrv-review/confirm'&&method==='POST'){if(payload.confirmed!==true||payload.nn_rhythm_artifact_reviewed!==true)error('请明确核对当前数学窗口NN候选、节律和伪差');const note=text(payload.note??'','note',1200,true),hash=await digest(value.document);if(payload.expected_document_digest!==hash||!same(value.document_scope,scope,SOURCE))error('HRV文档或来源依据已变化，请重新预览',409);assertScope(scope,currentScope(),true);const kept=Object.fromEntries(Object.entries(value.confirmations).filter(([,e])=>same(e.scope,scope)&&e.hrv_revision===value.revision&&e.document_digest===hash));env.changed('hrv_review.confirmed');const next=currentScope();for(const entry of Object.values(kept))entry.scope=next;kept[String(window)]={status:'confirmed',actor:'browser-demo-user',note:note.trim(),updated_at:new Date().toISOString(),scope:next,hrv_revision:value.revision,document_digest:hash,nn_rhythm_artifact_reviewed:true,confirmation_scope:'browser_demo_review_declaration_current_window',clinical_validation:false,quality_status:'unknown',window_index:window,start_sample:window*86400*200,end_sample:Math.min(Math.round(env.duration*200),(window+1)*86400*200)};value.confirmations=kept;value.updated_at=new Date().toISOString();value.document_scope=next;saveState(value);if(env.saved().hrvPreviews)delete env.saved().hrvPreviews[env.caseId];env.persist();return publicState(value,next,window);}
      error('HRV接口方法不受支持',405);
    }
    async function getBuiltin(){if(!builtinPromise)builtinPromise=(async()=>{const response=await env.nativeFetch('static/terminology/builtin-draft-v1.json');if(!response.ok)error('原创示例目录未加载');return validateCatalog(await response.json());})().catch(e=>{builtinPromise=null;throw e;});return clone(await builtinPromise);}
    function summary(value,builtin=false){const result=clone(value);delete result.nodes;return {...result,builtin,node_count:value.nodes.length,term_count:value.nodes.filter(n=>n.kind==='term').length,verification:'declared',publication_scope:'browser-local'};}
    const catalogState=()=>env.saved().terminologyCatalogs||{revision:0,items:[]};
    async function catalogs(){const built=await getBuiltin(),current=catalogState();return {catalog_revision:current.revision,items:[summary(built,true),...current.items.map(value=>summary(value))]};}
    async function terminology(path,method,payload,query){if(path==='/api/terminology/catalogs'&&method==='GET')return catalogs();const built=await getBuiltin();if(path==='/api/terminology/catalog'&&method==='GET'){const found=[built,...catalogState().items].find(value=>value.namespace===query.namespace&&value.version===query.version&&(!query.hash||value.sha256===query.hash));if(!found)error('该目录版本不存在或hash不匹配',404);return validateCatalog(found);}if(path==='/api/terminology/import'&&method==='POST'){const value=await validateCatalog(payload.catalog),current=catalogState();integer(payload.expected_catalog_revision,'目录版本');if(payload.expected_catalog_revision!==current.revision)error('目录列表已变化，请重新预览',409);if(payload.confirm!==undefined&&typeof payload.confirm!=='boolean')error('confirm须为布尔值');const existing=[built,...current.items].find(item=>item.namespace===value.namespace&&item.version===value.version);if(existing&&existing.sha256!==value.sha256)error('相同namespace/version不能覆盖，请使用新版本',409);if(payload.confirm){if(payload.preview_hash!==value.sha256)error('明确发布须匹配预览hash');if(!existing){current.items.push(value);current.revision++;env.saved().terminologyCatalogs=current;env.persist();}}return {preview_only:payload.confirm!==true,catalog_revision:current.revision,catalog:value,summary:summary(value,existing===built),preview_hash:value.sha256,warnings:['此为纯数学浏览器Demo，目录仅存本浏览器；没有患者输入或临床金标准。','来源、许可、适用范围、完整性和核准状态仅按文件声明，软件未独立验证；本地发布不代表医生核准。']};}error('术语接口方法不受支持',405);}
    async function validateReport(composition,approving=false){if(Object.hasOwn(composition,'terminology_usages'))composition.terminology_usages=normalizeUsages(composition.terminology_usages);if(!composition.include_hrv&&!(composition.included_pages||[]).some(k=>String(k).startsWith('hrv_')))return;const result=await read(composition.hrv_window||0),expected={hrv_revision:result.hrv_revision,document_digest:result.digest,window_index:result.window_index,profile:PROFILE,scope:result.scope};if(result.document_stale)error('HRV排除来自旧数学依据，请重新预览保存',409);if(!composition.hrv_review_reference){if(result.hrv_revision!==0)error('报告缺少当前HRV引用，请重新载入保存',409);}else if(encode(composition.hrv_review_reference)!==encode(expected))error('报告HRV引用已失效，请重新载入保存',409);if(approving&&!result.confirmation.valid)error('请先确认当前数学HRV窗口复核声明',409);}
    function assertSttIdentity(expected,actual){
      if(!expected||typeof expected!=='object'||Array.isArray(expected)||STT_IDENTITY.some(key=>!Object.hasOwn(expected,key)))error('区间统计缺少完整病例与逐搏依据');
      for(const key of SCOPE)if(Object.hasOwn(expected,key)){
        let value=expected[key];
        if(['analysis_revision','beat_revision'].includes(key)){
          integer(value,key);
        }
        if(value!==actual[key])error('区间统计病例或修订已变化，请重新计算后保存',409);
      }
    }
    function assertSttRangeSaveCurrent(checked){
      if(checked.saved!==encode(env.saved()))error('验证期间病例已变化，未保存；请重新计算后核对',409);
      assertScope(checked.identity,currentScope(),true);
    }
    function assertSttRangeSavedSource(statistics){
      const actual=currentScope(),scope=statistics?.scope;
      if(!scope||typeof scope!=='object'||STT_IDENTITY.some(key=>!Object.hasOwn(scope,key)))error('已保存区间统计缺少来源依据');
      for(const key of ['case_id','analysis_basis','beat_revision']){
        const expected=scope[key];if(key==='beat_revision')integer(expected,key);
        if(expected!==actual[key])error('已保存统计的来源或逐搏修订已变化，请核对标注',409);
      }
      let revision=scope.analysis_revision;
      integer(revision,'已保存统计复核版本');
      if(actual.analysis_revision!==revision+1)error('已保存统计之后已有其他复核修订，请回看标注并重新计算',409);
    }
    async function validateSttRangeSave(payload){
      const details=payload.details,statistics=details?.range_statistics,total=Math.round(env.duration*200);
      if(!details||details.kind!=='ST'||!['pending','confirmed','excluded'].includes(details.status)
          ||!statistics||typeof statistics!=='object'||Array.isArray(statistics)
          ||statistics.schema_version!=='stt-range-mean-v1'||Object.hasOwn(statistics,'blocks'))error('ST区间统计须为当前完整计算摘要');
      const identity=currentScope();
      assertSttIdentity(statistics.scope,identity);assertSttIdentity(statistics.server_identity,identity);
      assertSttIdentity(statistics,identity);
      const range=statistics.range;
      if(!range||!Number.isSafeInteger(range.start_sample)||!Number.isSafeInteger(range.end_sample)
          ||range.start_sample<0||range.end_sample>total||range.end_sample-range.start_sample<12000
          ||payload.sample_index!==range.start_sample||details.end_sample!==range.end_sample-1)error('标注范围与已计算的半开样本范围不一致');
      if(Object.hasOwn(details,'point_measurement_sample_index'))integer(details.point_measurement_sample_index,'手工点测量位置',0,total-1);
      if(statistics.physician_document_written!==false||statistics.binding?.status!=='mathematical_raw_source_and_basis_bound'
          ||statistics.binding.source_kind!=='pure_mathematical'||statistics.simulation?.browser_computed!==true
          ||statistics.simulation.real_patient_inputs_read!==false||statistics.simulation.clinical_validation!==false)error('缺少纯数学范围统计来源声明');
      const receipt=statistics.save_receipt;
      if(!receipt||receipt.kind!==STT_SAVE_KIND||typeof receipt.digest!=='string'||!/^[a-f0-9]{64}$/.test(receipt.digest))error('区间统计保存凭据缺失或来源不符');
      const compact=clone(statistics);delete compact.save_receipt;
      if(new TextEncoder().encode(encode(statistics)).byteLength>262144)error('区间统计摘要过大，请精简已保存的排除区间后重新计算');
      const checked={identity,saved:encode(env.saved())};
      // This public content digest detects altered snapshots; it is not a
      // private native HMAC or a clinical authentication statement.
      if(await digest(compact)!==receipt.digest)error('区间统计摘要已被修改，请重新计算后保存');
      assertSttRangeSaveCurrent(checked);return checked;
    }
    async function sttRangeRoute(method,payload){
      if(method!=='POST')error('ST范围统计仅支持只读POST计算',405);
      if(Object.hasOwn(payload,'exclusions'))error('范围统计仅采用当前已保存的节律排除区间，请先复核并保存节律标注');
      const requested=payload.scope,required=['case_id','analysis_basis','analysis_revision','beat_revision'];
      if(!requested||typeof requested!=='object'||Array.isArray(requested)||required.some(k=>!Object.hasOwn(requested,k)))error('范围统计须提供病例、分析及逐搏修订依据');
      const actual=currentScope();
      if(Object.hasOwn(payload,'case_id')&&payload.case_id!==env.caseId)error('范围统计请求来自另一病例',409);
      for(const key of SCOPE)if(Object.hasOwn(requested,key)){
        let expected=requested[key];
        if(['analysis_revision','beat_revision'].includes(key)){
          integer(expected,key);
        }
        if(expected!==actual[key])error('病例、原始来源或复核修订已变化，请重新读取',409);
      }
      if(!globalThis.ECGSTTRangeMath||typeof env.rawWaveform!=='function'||typeof env.annotations!=='function')error('全原始数学范围计算模块未加载，请刷新');
      const savedBefore=encode(env.saved()),feed=env.feed(),masks=[];
      for(const row of env.annotations()){
        const details=row.details||{};
        if(!['AF','AFL'].includes(details.kind)||details.status==='excluded')continue;
        if(!Number.isSafeInteger(row.sample_index)||!Number.isSafeInteger(details.end_sample))error('节律排除区间须使用完整原始样本范围');
        const status=details.status===undefined?'unclassified':details.status===null?'None':details.status===true?'True':details.status===false?'False':String(details.status);
        masks.push({start_sample:row.sample_index,end_sample:details.end_sample+1,reason:'rhythm_'+details.kind,origin:'stored_annotation',review_status:status});
      }
      const raw=await env.rawWaveform();
      if(raw.byteLength!==Math.round(env.duration*200)*16)error('完整数学波形长度与病例范围不一致');
      const result=await ECGSTTRangeMath.calculate(raw,feed.beats,{start_sample:payload.start_sample,end_sample:payload.end_sample,leads:payload.leads,measurement_ms:payload.measurement_ms===undefined?60:payload.measurement_ms,exclusions:masks,basis:clone(requested)});
      if(savedBefore!==encode(env.saved()))error('计算期间病例已变化，请重新读取',409);
      assertScope(actual,currentScope(),true);
      const compact={...result,...Object.fromEntries(STT_IDENTITY.map(key=>[key,actual[key]])),server_identity:actual,physician_document_written:false};
      delete compact.blocks;
      const saveReceipt={kind:STT_SAVE_KIND,digest:await digest(compact)};
      if(savedBefore!==encode(env.saved()))error('生成摘要期间病例已变化，请重新读取',409);
      assertScope(actual,currentScope(),true);
      return {...compact,save_receipt:saveReceipt};
    }
    async function route(url,method,payload){const path=url.pathname,query=Object.fromEntries(url.searchParams);if(path.startsWith('/api/terminology/'))return terminology(path,method,payload,query);const match=path.match(/^\/api\/cases\/([^/]+)\/(rr-review(?:\/locate)?|hrv-review(?:\/(preview|confirm|cancel))?|stt-range)$/);if(!match)return null;if(decodeURIComponent(match[1])!==env.caseId)error('数学病例不存在',404);const action=match[2];if(action==='stt-range')return sttRangeRoute(method,payload);if(action.startsWith('hrv-review'))return hrvRoute(action,method,payload,query);const scope=currentScope();assertScope(query,scope);const index=ECGDemoRR.build(env.feed(),scope);if(action==='rr-review'&&method==='GET')return {...ECGDemoRR.query(index,query),simulation:{browser_computed:true,real_patient_inputs_read:false,clinical_validation:false,verified_nn_count:0}};if(action==='rr-review/locate'&&method==='POST'){const target=payload.target||payload;if(['case_id','analysis_basis','analysis_revision','beat_revision','sample_index'].some(k=>!Object.hasOwn(target,k)))error('缺少完整RR目标身份');assertScope(target,scope);const exact=ECGDemoRR.resolve(index,target),start=Math.max(0,exact.sample_index/200-3.5),end=Math.min(env.duration,start+7),wave=await env.waveform(new URLSearchParams({whole:'1',filter:'raw'}),{start,duration:end-start,leads:['II','V1','V5'],maxPoints:2800,filter:'raw'});assertScope(scope,currentScope(),true);wave.beats=env.feed().beats.filter(b=>b.sample_index/200>=wave.start_s&&b.sample_index/200<=wave.start_s+wave.duration_s);if(!wave.beats.some(b=>b.sample_index===exact.sample_index))error('数学波形缺少精确目标；未用最近邻替代',409);return {target:exact,waveform:{...wave,...scope},located:true,...scope,simulation:{browser_computed:true,real_patient_inputs_read:false,clinical_validation:false}};}error('RR接口方法不受支持',405);}
    return {route,read,reference,analysis,validateReport,validateSttRangeSave,assertSttRangeSaveCurrent,assertSttRangeSavedSource};
  }
  return {create,analyze,validateCatalog,normalizeUsages,digest,profile};
})();
if(typeof module!=='undefined'&&module.exports)module.exports=globalThis.ECGDemoReviewAPI;
