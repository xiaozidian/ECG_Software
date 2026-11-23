"""Read-only RR review over the original QRS topology, never a classifier.

Ordinary RR ignores non-QRS O/Y/T markers. Artifacts and ventricular flutter
symbols remain boundaries; no filter is allowed to join new neighbours.
N-labelled, legacy NN candidates and verified NN are deliberately different.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import Counter
from collections.abc import Mapping
from hashlib import sha256
import json
from math import isfinite
from types import MappingProxyType

from .beat_editor import TYPES
from .rr_quality import NONBEATS

METHOD_VERSION = "rr-review-original-qrs-v1"
SCHEMA = "cardioinsight.rr-review.v1"
MODES = {"rr": ("ms", 25.0, 2600.0), "ratio": ("%", 2.5, 300.0), "hr": ("bpm", 1.0, 300.0)}
IDENTITY_FIELDS = ("case_id", "analysis_basis", "analysis_revision", "beat_revision")


class RRReviewConflict(ValueError):
    """An exact target or its analysis scope no longer matches."""


def _get(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and isfinite(value)


def _sample(value):
    return _finite(value) and value >= 0 and int(value) == value


def _safe(value):
    return value if value is None or isinstance(value, (str, bool)) or _finite(value) else None


def _identity(basis):
    basis = dict(basis or {})
    if "case_id" not in basis and "caseId" in basis:
        basis["case_id"] = basis["caseId"]
    if "case_id" in basis and "caseId" in basis and basis["case_id"] != basis["caseId"]:
        raise RRReviewConflict("RR 病例标识不一致")
    if "beat_revision" not in basis and "beatRevision" in basis:
        basis["beat_revision"] = basis["beatRevision"]
    return {key: basis[key] for key in IDENTITY_FIELDS if key in basis}


def _assert_identity(expected, current):
    if "caseId" in expected and ("case_id" not in current or expected["caseId"] != current["case_id"]):
        raise RRReviewConflict("RR 目标属于其他病例，未进行定位")
    for key in IDENTITY_FIELDS:
        if key in expected and (isinstance(expected[key], bool) or key not in current or str(expected[key]) != str(current[key])):
            raise RRReviewConflict("RR 分析或逐搏修订已变化，请重新载入；未改定位到其他心搏")


def _spans(excluded):
    merged = []
    for a, b in sorted((x[0], x[1]) for x in (excluded or ()) if isinstance(x, (tuple, list)) and len(x) == 2 and all(_finite(v) for v in x) and x[1] > x[0]):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    return merged, [a for a, _ in merged]


def _overlaps(a, b, merged, starts):
    i = bisect_left(starts, b) - 1
    return i >= 0 and merged[i][1] > a


def _endpoint(row, document):
    code = row.get("class_code")
    code = code if isinstance(code, str) and code else "UNKNOWN"
    sample = row.get("sample_index")
    ident = row.get("id")
    ident = str(ident) if ident is not None else "s:" + str(sample)
    source = row.get("classification_source")
    namespace = row.get("symbol_namespace", "cardioinsight-local")
    changes = document.get("changes", {}) if isinstance(document, dict) else {}
    if not source:
        if ident in changes:
            source = "physician_edit"
        elif ident.startswith("i:"):
            source = "physician_insert"
        elif namespace == "cardioinsight-local" and row.get("source_group") is not None and code != {1:"N",2:"S",3:"V",34:"X"}.get(row["source_group"], "OTHER"):
            source = "physician_override"
        elif row.get("source_sample") is not None and row["source_sample"] != sample:
            source = "physician_position_edit"
        elif row.get("source_sample") is not None or row.get("source_group") is not None:
            source = "source_label"
        else:
            source = "provided_annotation"
    known = code in TYPES and code != "OTHER" and namespace == "cardioinsight-local"
    label = row.get("name") or row.get("label") or (TYPES[code]["name"] if known else code)
    return dict(id=ident, sample_index=int(sample) if _sample(sample) else _safe(sample), class_code=code, label=str(label),
                source_sample=_safe(row.get("source_sample")), source_group=_safe(row.get("source_group")),
                source_symbol=_safe(row.get("source_symbol", row.get("source_class_code"))),
                classification_source=str(source), symbol_namespace=str(namespace), type_known=known,
                review_status=str(row.get("review_status", "not_recorded")),
                label_authority="原有／人工标签；N 标签本身未证明窦性", kind=row.get("kind"),
                group=_safe(row.get("group")))


def _verified_context(context, basis, start, end):
    empty = dict(sinus_verified=False, quality_verified=False, scope_verified=False,
                 status="not_established", reason="sinus_and_quality_not_verified")
    if not isinstance(context, dict):
        return empty
    result = {**empty, "sinus_verified": context.get("sinus_verified") is True,
              "quality_verified": context.get("quality_verified") is True}
    if context.get("status") != "confirmed" or not isinstance(context.get("evidence_ref"), str) or not context["evidence_ref"]:
        return {**result, "reason": "no_confirmed_verification_evidence"}
    if any(k not in basis or k not in context or isinstance(context[k], bool) or str(context[k]) != str(basis[k]) for k in IDENTITY_FIELDS):
        return {**result, "reason": "verification_scope_mismatch"}
    if context.get("method_version") != METHOD_VERSION:
        return {**result, "reason": "verification_method_mismatch"}
    a, b = context.get("start_s"), context.get("end_s")
    if not all(_finite(v) for v in (a, b, start, end)) or not a <= start < end <= b:
        return {**result, "reason": "interval_outside_verified_scope"}
    result["scope_verified"] = True
    if not result["sinus_verified"] or not result["quality_verified"]:
        return {**result, "reason": "sinus_and_quality_not_verified"}
    return {**result, "status": "confirmed", "reason": None, "evidence_ref": context["evidence_ref"]}



class _RRInterval(Mapping):
    """Compact private record. Public JSON is expanded only for a result page.

    Neighbour endpoints and provenance states are shared. Exact target objects
    are generated on demand rather than duplicated for the whole recording.
    """
    __slots__ = ("_id", "_index", "_left", "_right", "_time", "_stored", "_computed",
                 "_rr", "_hr", "_quality", "_normal", "_candidate", "_nn_reason",
                 "_clinical", "_verified", "_target_possible", "_common", "_ratio",
                 "_previous_id", "_previous_start", "_ratio_reason", "_pair", "_known")
    _FIELDS = ("id", "index", "start_sample", "end_sample", "time_s", "left", "right",
               "left_type", "right_type", "pair_type", "stored_rr_ms", "computed_rr_ms",
               "rr_ms", "ratio_pct", "hr_bpm", "type_known", "quality", "normal_pair",
               "normal_label_pair", "nn_candidate_compat", "nn_eligible_current_rules",
               "nn_reason", "nn_rule_rr_ms", "nn_eligible_verified", "nn_verified_reason",
               "clinical_verification", "target")
    _ATTRS = {"id":"_id", "index":"_index", "time_s":"_time", "left":"_left", "right":"_right",
              "stored_rr_ms":"_stored", "computed_rr_ms":"_computed", "rr_ms":"_rr", "hr_bpm":"_hr",
              "ratio_pct":"_ratio", "type_known":"_known", "pair_type":"_pair", "quality":"_quality",
              "normal_pair":"_normal", "normal_label_pair":"_normal", "nn_candidate_compat":"_candidate",
              "nn_eligible_current_rules":"_candidate", "nn_reason":"_nn_reason", "nn_rule_rr_ms":"_stored",
              "nn_eligible_verified":"_verified", "clinical_verification":"_clinical"}

    def __init__(self, ident, rank, left, right, time_s, stored, computed, quality, normal,
                 candidate, nn_reason, clinical, verified, target_possible, common, pair,
                 known, ratio, previous_id, previous_start, ratio_reason):
        self._id, self._index, self._left, self._right = ident, rank, left, right
        self._time, self._stored, self._computed = time_s, stored, computed
        self._rr = computed if quality["valid"] else None
        self._hr = 60000/computed if quality["valid"] else None
        self._quality, self._normal, self._candidate = quality, normal, candidate
        self._nn_reason, self._clinical, self._verified = nn_reason, clinical, verified
        self._target_possible, self._common, self._pair, self._known = target_possible, common, pair, known
        self._ratio, self._previous_id, self._previous_start = ratio, previous_id, previous_start
        self._ratio_reason = ratio_reason

    def __getitem__(self, name):
        attr = self._ATTRS.get(name)
        if attr is not None: return getattr(self, attr)
        if name == "start_sample": return self._left["sample_index"]
        if name == "end_sample": return self._right["sample_index"]
        if name == "left_type": return self._left["class_code"]
        if name == "right_type": return self._right["class_code"]
        if name == "nn_verified_reason":
            return None if self._verified else self._nn_reason or ("outside_recording" if not self._quality["valid"] else self._clinical["reason"])
        if name == "target":
            if not self._target_possible: return None
            return {**self._common, "sample_index":self._right["sample_index"], "beat_id":self._right["id"],
                    "interval_id":self._id, "interval_start_sample":self._left["sample_index"],
                    "interval_end_sample":self._right["sample_index"]}
        if name == "ratio_previous_interval_id" and self._ratio is not None: return self._previous_id
        if name == "ratio_previous_start_sample" and self._ratio is not None: return self._previous_start
        if name == "ratio_reason" and self._ratio is None: return self._ratio_reason
        raise KeyError(name)

    def __iter__(self):
        yield from self._FIELDS
        yield from (("ratio_previous_interval_id", "ratio_previous_start_sample") if self._ratio is not None else ("ratio_reason",))

    def __len__(self):
        return len(self._FIELDS)+(2 if self._ratio is not None else 1)


def _index_digest(scope, sample_rate, duration, sides, rows, nn_min, nn_max, merged, verification):
    """Hash the previous exact JSON encoding in bounded chunks, without a full copy."""
    encode = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, allow_nan=False)
    digest = sha256()
    digest.update(encode([METHOD_VERSION, scope, sample_rate, duration])[:-1].encode())
    digest.update(b", [")
    for offset in range(0, len(rows), 1024):
        chunk = [[x["id"], x["sample_index"], x["class_code"], x["classification_source"], _safe(r.get("rr_ms")),
                  x["group"], x["kind"], x["source_group"], x["source_symbol"]]
                 for x, r in zip(sides[offset:offset+1024], rows[offset:offset+1024])]
        if offset: digest.update(b", ")
        digest.update(encode(chunk)[1:-1].encode())
    digest.update(b"], ")
    digest.update(encode([_safe(nn_min), _safe(nn_max), merged, verification])[1:].encode())
    return digest.hexdigest()


def _expand_interval(row):
    # Do not expose shared immutable internal states to JSON encoders or callers.
    value = dict(row)
    value["left"], value["right"] = dict(row["left"]), dict(row["right"])
    value["quality"] = {**row["quality"], "reasons":list(row["quality"]["reasons"])}
    value["clinical_verification"] = dict(row["clinical_verification"])
    return value

def build_rr_index(feed, sample_rate=200, basis=None):
    """Index every original adjacent QRS pair without reading files or editing feed.

    Input is the existing edited feed (beats, duration, document.settings and
    excluded_rhythm_intervals). Fractional milliseconds are retained. Missing
    stored RR can be displayed as sample-derived timing but cannot satisfy the
    legacy NN compatibility test. Supplied invalid/mismatched RR is withheld.
    """
    if not _finite(sample_rate) or sample_rate <= 0:
        raise ValueError("采样率必须为正的有限数值")
    rows = _get(feed, "beats", ())
    if not isinstance(rows, (list, tuple)) or any(not isinstance(r, dict) for r in rows):
        raise ValueError("RR 源心搏必须为逐搏对象数组")
    document = _get(feed, "document", {}) or {}
    settings = document.get("settings", {}) if isinstance(document, dict) else {}
    nn_min, nn_max = settings.get("nn_min"), settings.get("nn_max")
    settings_known = _finite(nn_min) and _finite(nn_max) and 0 < nn_min < nn_max
    duration = _get(feed, "duration", _get(feed, "duration_s"))
    if duration is not None and (not _finite(duration) or duration < 0):
        raise ValueError("记录时长必须为非负有限数值")
    scope = _identity(basis)
    merged, starts = _spans(_get(feed, "excluded_rhythm_intervals", ()))
    verification = _get(feed, "nn_verification")
    qrs = [r for r in rows if r.get("class_code") not in NONBEATS and r.get("kind") != "nonbeat"]
    sides = [_endpoint(r, document) for r in qrs]
    sample_counts = Counter(s["sample_index"] for s in sides if _sample(s["sample_index"]))
    index_key = _index_digest(scope, sample_rate, duration, sides, qrs, nn_min, nn_max, merged, verification)
    common_target = MappingProxyType({**scope, **({"caseId":scope["case_id"]} if "case_id" in scope else {}), "index_key":index_key})
    quality_pool, clinical_pool, pair_pool = {}, {}, {}
    unverified = MappingProxyType(_verified_context(None, scope, None, None))
    intervals = []
    for i in range(1, len(qrs)):
        left, right = sides[i-1], sides[i]
        s, t = left["sample_index"], right["sample_index"]
        stored_present = "rr_ms" in qrs[i] and qrs[i]["rr_ms"] is not None
        stored = qrs[i].get("rr_ms")
        computed = (t-s)*1000/sample_rate if _sample(s) and _sample(t) else None
        start, end = s/sample_rate if _sample(s) else None, t/sample_rate if _sample(t) else None
        reasons = []
        if not _sample(s) or not _sample(t): reasons.append("invalid_sample")
        elif t <= s: reasons.append("non_increasing_samples")
        if _sample(s) and _sample(t) and (sample_counts[s] != 1 or sample_counts[t] != 1): reasons.append("duplicate_sample")
        if duration is not None and (_sample(s) and s/sample_rate >= duration or _sample(t) and t/sample_rate >= duration): reasons.append("outside_recording")
        if any(x["class_code"] == "X" or x["group"] == 34 or x["kind"] == "artifact" for x in (left, right)): reasons.append("artifact_boundary")
        if any(x["class_code"] == "!" for x in (left, right)): reasons.append("flutter_no_ordinary_rr")
        if stored_present and (not _finite(stored) or stored <= 0): reasons.append("invalid_stored_rr")
        elif stored_present and computed is not None and abs(computed-stored) > 10: reasons.append("stored_sample_mismatch")
        valid = not reasons and computed is not None and computed > 0
        normal = left["class_code"] == right["class_code"] == "N"
        excluded = start is not None and end is not None and end > start and _overlaps(start, end, merged, starts)
        # The current NN engine permits a terminal annotation exactly at duration.
        # Keep that compatibility fact separate from ordinary RR/locatable bounds.
        nn_geometry = not any(x != "outside_recording" for x in reasons) and computed is not None and computed > 0
        nn_inside = duration is not None and end is not None and end <= duration
        if not nn_geometry: nn_reason = reasons[0] if reasons else "invalid_interval"
        elif not stored_present: nn_reason = "missing_stored_rr"
        elif not normal: nn_reason = "non_normal_label" if left["type_known"] and right["type_known"] else "unknown_type"
        elif not settings_known: nn_reason = "nn_settings_unknown"
        elif not nn_inside: nn_reason = "nn_recording_scope_unknown_or_outside"
        elif not nn_min <= stored <= nn_max: nn_reason = "outside_current_nn_bounds"
        elif excluded: nn_reason = "excluded_rhythm_interval"
        else: nn_reason = None
        candidate = nn_reason is None
        if not isinstance(verification, dict):
            clinical = unverified
        else:
            state = _verified_context(verification, scope, start, end)
            state_key = tuple(sorted(state.items()))
            clinical = clinical_pool.get(state_key)
            if clinical is None:
                clinical = clinical_pool[state_key] = MappingProxyType(state)
        verified = candidate and valid and clinical["status"] == "confirmed"
        interval_id = "rr:" + sha256(json.dumps([left["id"], right["id"], s, t], ensure_ascii=False).encode()).hexdigest()[:24]
        target_possible = _sample(s) and _sample(t) and sample_counts[s] == sample_counts[t] == 1 and (duration is None or t/sample_rate < duration)
        known = left["type_known"] and right["type_known"]
        interpretation = "flutter_no_ordinary_rr" if "flutter_no_ordinary_rr" in reasons else "annotation_timing_not_diagnosis"
        quality_key = (tuple(reasons), stored_present, not known, interpretation)
        quality_state = quality_pool.get(quality_key)
        if quality_state is None:
            quality_state = quality_pool[quality_key] = MappingProxyType(dict(valid=valid, reason=reasons[0] if reasons else None,
                reasons=tuple(reasons), stored_available=stored_present, classification_unknown=not known,
                ordinary_rr_interpretation=interpretation))
        pair_key = (left["class_code"], right["class_code"])
        pair = pair_pool.get(pair_key)
        if pair is None:
            pair = pair_pool[pair_key] = json.dumps(pair_key, separators=(",", ":"), ensure_ascii=False)
        # Ratios use the preceding ORIGINAL interval, never a filtered predecessor.
        previous = intervals[-1] if intervals else None
        ratio = computed/previous._rr*100 if valid and previous is not None and previous._quality["valid"] else None
        ratio_reason = "no_preceding_original_interval" if previous is None else "preceding_original_interval_unavailable"
        intervals.append(_RRInterval(interval_id, i-1, left, right, end, _safe(stored), computed, quality_state,
            normal, candidate, nn_reason, clinical, verified, target_possible, common_target, pair, known, ratio,
            previous._id if ratio is not None else None, previous._left["sample_index"] if ratio is not None else None, ratio_reason))
    method = dict(rr="RR = 原始相邻 QRS 样本差 × 1000 / 采样率；保留输入 RR，沿用 10 ms 一致性容差。首搏无间期。",
        ratio="R/R = RR(i) / RR(i−1) × 100%；沿用现有工程方向，医院定义尚未核实。使用原序列前一间期。",
        hr="逐间期心率 = 60000 / RR(ms)，单位 bpm；展示未舍入值分箱，不判定诊断。",
        normal_pair="normal_label_pair 仅表示原标签两端为 N；源 N 未证明窦性。",
        nn="nn_candidate_compat / nn_eligible_current_rules 仅沿用当前 NN 范围、存储 RR 与完整间期节律排除；属于工程筛选候选。",
        verified_nn="nn_eligible_verified 还需同分析与逐搏修订、同方法、覆盖完整间期的明确窦性和质量确认；缺失时 false。",
        classification="有序类型按原符号分组；不采用历史 WFDB map1 将起搏、Q 或其他类型归 N；不推断医院亚型。",
        manual_review="只读证据工作台；原标签、筛选候选及分布不构成诊断或医生复核完成。",
        unknown="未知类型保留原符号；! 保留边界但无普通 RR 解释；O/Y/T 不作 QRS 边界；伪差不被删去桥接。",
        population="RR 按终搏时间归属左闭右开窗口；NN 兼容规则保留终点≤记录时长的原有边界，记录外目标不可定位。",
        nn_min_ms=_safe(nn_min), nn_max_ms=_safe(nn_max), nn_settings_known=settings_known,
        duration_known=duration is not None, hospital_mapping_verified=False,
        references=["https://physionet.org/physiotools/wag/ann2rr-1.htm", "https://physionet.org/content/wfdb/10.7.0/lib/ecgmap.h"])
    summary = dict(qrs_count=len(qrs), non_qrs_marker_count=len(rows)-len(qrs)+len(_get(feed, "markers", ()) or ()),
        interval_count=len(intervals), valid_rr_count=sum(x["quality"]["valid"] for x in intervals),
        invalid_count=sum(not x["quality"]["valid"] for x in intervals),
        unknown_type_count=sum(not x["type_known"] for x in intervals),
        normal_pair_count=sum(x["normal_pair"] for x in intervals),
        nn_eligible_count=sum(x["nn_eligible_current_rules"] for x in intervals),
        nn_verified_count=sum(x["nn_eligible_verified"] for x in intervals))
    return dict(schema=SCHEMA, method_version=METHOD_VERSION, method=method, basis=scope,
        index_key=index_key, sample_rate_hz=sample_rate, duration_s=duration, summary=summary,
        intervals=tuple(intervals), targets={x["end_sample"]: x for x in intervals if x._target_possible})


def _number(query, name, default=None):
    value = query.get(name, default)
    if value is None or value == "": return default
    if isinstance(value, bool): raise ValueError(name + " 必须为有限数值")
    try: value = float(value)
    except (TypeError, ValueError): raise ValueError(name + " 必须为有限数值") from None
    if not isfinite(value): raise ValueError(name + " 必须为有限数值")
    return value


def _integer(query, name, default, low=0, high=None):
    value = _number(query, name, default)
    if value != int(value) or value < low or high is not None and value > high:
        raise ValueError(name + " 整数范围无效")
    return int(value)


def _histogram(rows, mode):
    unit, step, ceiling = MODES[mode]
    bins = [dict(start=i*step, end=(i+1)*step, count=0, overflow=False) for i in range(int(ceiling/step))]
    bins.append(dict(start=ceiling, end=None, count=0, overflow=True))
    field = {"rr": "rr_ms", "ratio": "ratio_pct", "hr": "hr_bpm"}[mode]
    for row in rows:
        value = row[field]
        if _finite(value) and value >= 0:
            bins[min(int(value//step), len(bins)-1)]["count"] += 1
    return dict(mode=mode, unit=unit, bin_width=step, bins=bins,
                measurement_count=sum(x["count"] for x in bins), population_count=len(rows))


def resolve_rr_target(index, target):
    """Resolve an exact existing endpoint or reject; never seek a nearest beat."""
    if not isinstance(target, dict): raise ValueError("精确 RR 目标必须为对象")
    if any(k not in target for k in IDENTITY_FIELDS if k in index["basis"]):
        raise RRReviewConflict("精确目标缺少完整病例／修订依据，请重新选择")
    for key in ("analysis_revision", "beat_revision"):
        if key in index["basis"] and (type(target.get(key)) is not int or type(index["basis"][key]) is not int):
            raise RRReviewConflict("目标修订必须为当前整数修订")
    if any(k not in target for k in ("beat_id", "interval_id", "interval_start_sample", "interval_end_sample", "index_key")):
        raise RRReviewConflict("精确目标缺少原心搏与双端点身份，请重新选择")
    _assert_identity(target, index["basis"])
    if target.get("index_key") is not None and target["index_key"] != index["index_key"]:
        raise RRReviewConflict("RR 源间期已变化，请重新选择目标")
    sample = target.get("sample_index")
    if type(sample) is not int or sample < 0: raise ValueError("目标样本必须为非负整数")
    item = index["targets"].get(sample)
    if item is None: raise RRReviewConflict("目标心搏不存在或已移除；未改定位到最近心搏")
    exact = item["target"]
    for field in ("beat_id", "interval_id", "interval_start_sample", "interval_end_sample"):
        if field in target and (target[field] != exact[field] or field in ("interval_start_sample", "interval_end_sample") and type(target[field]) is not int):
            raise RRReviewConflict("目标心搏或原始间期端点已变化，请重新选择")
    return dict(exact)


def query_rr(index, query=None):
    """Full-count facets and histograms plus a stable, bounded result page."""
    query = dict(query or {})
    _assert_identity(query, index["basis"])
    mode = query.get("mode", "rr")
    population, quality = query.get("population", "all"), query.get("quality", "all")
    if mode not in MODES: raise ValueError("RR 模式必须为 rr、ratio 或 hr")
    if population not in ("all", "normal_pair", "nn_eligible", "nn_verified", "unknown"):
        raise ValueError("RR 总体筛选无效")
    if quality not in ("all", "valid", "invalid"): raise ValueError("RR 质量筛选无效")
    start, end = _number(query, "start_s", 0), _number(query, "end_s", index["duration_s"])
    if start < 0 or end is not None and (end < start or index["duration_s"] is not None and end > index["duration_s"]):
        raise ValueError("RR 时间窗口超出记录或顺序无效")
    lo, hi = _number(query, "range_min"), _number(query, "range_max")
    if lo is not None and lo < 0 or hi is not None and hi < 0 or lo is not None and hi is not None and hi <= lo:
        raise ValueError("RR 数值范围必须为非负左闭右开区间")
    offset, limit = _integer(query, "offset", 0), _integer(query, "limit", 20, 1, 200)
    pair_type = query.get("pair_type", "all")
    if pair_type is None or pair_type == "": pair_type = "all"
    if not isinstance(pair_type, str): raise ValueError("间期类型必须为原符号二元 JSON 或 all")
    if pair_type != "all":
        try: pair = json.loads(pair_type)
        except (ValueError, TypeError): raise ValueError("间期类型必须为原符号二元 JSON") from None
        if not isinstance(pair, list) or len(pair) != 2 or any(not isinstance(x, str) for x in pair):
            raise ValueError("间期类型必须为原符号二元 JSON")
        pair_type = json.dumps(pair, ensure_ascii=False, separators=(",", ":"))
    base = []
    for row in index["intervals"]:
        at = row["time_s"]
        # Malformed endpoints remain visible in an unbounded all-record view.
        if at is not None and (at < start or end is not None and at >= end): continue
        if at is None and (start != 0 or end != index["duration_s"]): continue
        if population == "normal_pair" and not row["normal_pair"]: continue
        if population == "nn_eligible" and not row["nn_eligible_current_rules"]: continue
        if population == "nn_verified" and not row["nn_eligible_verified"]: continue
        if population == "unknown" and row["type_known"]: continue
        if quality == "valid" and not row["quality"]["valid"] or quality == "invalid" and row["quality"]["valid"]: continue
        base.append(row)
    counts = {}
    for row in base:
        facet = counts.setdefault(row["pair_type"], dict(code=row["pair_type"], left_type=row["left_type"], right_type=row["right_type"], total=0, valid_rr_count=0, unknown_count=0))
        facet["total"] += 1; facet["valid_rr_count"] += int(row["quality"]["valid"]); facet["unknown_count"] += int(not row["type_known"])
    cohort = [row for row in base if pair_type == "all" or row["pair_type"] == pair_type]
    field = {"rr": "rr_ms", "ratio": "ratio_pct", "hr": "hr_bpm"}[mode]
    selected = [row for row in cohort if (lo is None and hi is None) or
        _finite(row[field]) and (lo is None or row[field] >= lo) and (hi is None or row[field] < hi)]
    total = len(selected)
    items = [{**_expand_interval(row), "match_index": offset+i} for i, row in enumerate(selected[offset:offset+limit])]
    target = None
    if "target_sample_index" in query:
        wanted = _integer(query, "target_sample_index", 0)
        original = index["targets"].get(wanted)
        if original is None:
            raise RRReviewConflict("目标心搏不存在或已移除；未改定位到最近心搏")
        target = resolve_rr_target(index, {**original["target"], **{k:query[k] for k in ("index_key", "beat_id", "interval_id", "interval_start_sample", "interval_end_sample") if k in query}})
    normalized = dict(mode=mode, population=population, quality=quality, pair_type=pair_type,
                      start_s=start, end_s=end, range_min=lo, range_max=hi, offset=offset, limit=limit)
    return dict(schema=SCHEMA, method_version=METHOD_VERSION, method=dict(index["method"]),
        **index["basis"], index_key=index["index_key"], sample_rate_hz=index["sample_rate_hz"],
        duration_s=index["duration_s"], summary=dict(index["summary"]), query=normalized,
        total=total, offset=offset, limit=limit, has_previous=offset > 0 and total > 0,
        has_next=offset+limit < total, items=items, target=target, pair_types=list(counts.values()),
        histogram=_histogram(cohort, mode), selected_histogram=_histogram(selected, mode))
