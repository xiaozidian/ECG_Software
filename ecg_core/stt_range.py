"""Selected-range ST means in source units, separate from ST-T screening.

This version reuses the existing fixed-grid machine J and quality method.  It
does not average the screening trend, change its thresholds, identify sinus
rhythm, or infer sustained depression from a negative mean.  Explicit masks
subtract observations; they do not rebuild beat neighbours.
"""
from __future__ import annotations

import copy
import json
import math
import mmap
from bisect import bisect_left
from collections import Counter
from hashlib import sha256
from pathlib import Path

import numpy as np

from .config import CHANNEL_COUNT, SAMPLE_RATE
from .source_identity import require_waveform_file, source_read
from .stt import (DEFAULT_CONFIG, LEADS, _block_measurement, _estimate_j_sample,
                  _evenly, _normalize_records, _sample_frames)

SCHEMA_VERSION = "stt-range-mean-v1"
PROFILE_ID = "raw-200hz-fixed16s-st-perbeat-mean-v1"
BASELINE_OFFSETS = (-40, -36, -32, -28, -24)
ST_OFFSETS = (-2, -1, 0, 1, 2)
BLOCK_SAMPLES = 3200
MINIMUM_RANGE_SAMPLES = 12000
# J search is 8..28 samples, with an 18-sample fallback.  This envelope
# protects representative J/quality reads before J has been determined.  It
# intentionally protects intervening samples too; the final mean uses the
# exact baseline and ST support windows stated below.
REPRESENTATIVE_HALO = (-40, 47)


class STTRangeError(ValueError):
    """A range or explicit method input cannot be interpreted safely."""


def _integer(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise STTRangeError(f"{label} must be an integer sample")
    return int(value)


def _digest(value):
    try:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError) as error:
        raise STTRangeError("basis and method inputs must contain finite JSON values") from error
    return sha256(payload.encode("utf-8")).hexdigest()


def method_profile(measurement_ms=60):
    if type(measurement_ms) is not int or measurement_ms not in (0, 60, 80):
        raise STTRangeError("measurement_ms must be 0, 60 or 80")
    return {
        "id": PROFILE_ID, "sample_rate_hz": SAMPLE_RATE,
        "sample_rate_device_verified": False, "block_seconds": 16,
        "minimum_range_samples": MINIMUM_RANGE_SAMPLES,
        "measurement_ms": measurement_ms,
        "baseline_offsets_samples": list(BASELINE_OFFSETS),
        "baseline": "five-point pre-QRS median (-200,-180,-160,-140,-120 ms); PR surrogate, physician verification required",
        "st_window_offsets_samples": list(ST_OFFSETS),
        "st_measurement": "five-point median centred on machine J plus selected offset",
        "aggregate": "arithmetic_mean_of_used_per_beat_st_minus_baseline",
        "j_basis": "fixed_16s_machine_estimate_after_explicit_masks",
        "j_representative_limit": 7, "minimum_j_representatives": 3,
        "representative_exclusion_halo_samples": list(REPRESENTATIVE_HALO),
        "mean_beat_limit": None,
        "candidate_rules": "legacy group=1; same fixed-block neighbours not group 3/34; integer RR 350..2000 ms inclusive; source edge guard",
        "source_edge_guard": "R >=50 and R+120 < source sample count; unavailable guard is counted as missing, never clamped",
        "mask_rule": "R anchor or baseline span [R-40,R-23) or ST span [R+J+offset-2,R+J+offset+3) intersects explicit half-open mask",
        "neighbours_rebuilt_after_masks": False,
        "quality_gate": {"minimum_normal_ratio": .35, "minimum_score": .42,
                         "population": "original block non-artifact anchors outside explicit masks; candidate density after exact support masks",
                         "landmark_confidence_is_gate": False},
        "quality_note": "existing engineering block gate; labels, machine landmarks and signal quality are not physician verified",
        "unit_label": "u", "units": "device_unit", "calibration_verified": False,
        "lead_mapping_verified": False, "filter": "raw source; no display high-pass",
        "diagnosis_generated": False, "mean_proves_sustained_depression": False,
    }


def _masks(exclusions, total_samples):
    result = []
    for item in exclusions or ():
        if not isinstance(item, dict):
            raise STTRangeError("each mask must be a dictionary with integer sample boundaries")
        start = _integer(item.get("start_sample"), "mask start_sample")
        end = _integer(item.get("end_sample"), "mask end_sample")
        if not 0 <= start < end <= total_samples:
            raise STTRangeError("mask must be a nonempty half-open interval within the source")
        reason = item.get("reason")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 200:
            raise STTRangeError("each mask requires a nonempty reason of at most 200 characters")
        kind = item.get("kind", "exclusion")
        if kind not in ("exclusion", "missing"):
            raise STTRangeError("mask kind must be exclusion or explicitly known missing")
        row = {"start_sample": start, "end_sample": end, "reason": reason.strip(), "kind": kind}
        for key in ("origin", "review_status"):
            if key in item:
                if not isinstance(item[key], str) or len(item[key]) > 200:
                    raise STTRangeError(f"mask {key} must be a string")
                row[key] = item[key]
        result.append(row)
    # Stable, order-independent identity; duplicate masks have no extra effect.
    unique = {_digest(row): row for row in result}
    return sorted(unique.values(), key=lambda x: (x["start_sample"], x["end_sample"], _digest(x)))


class _MaskIndex:
    def __init__(self, intervals):
        self.rows = intervals
        self.starts = [x["start_sample"] for x in intervals]
        self.prefix_ends = []
        high = 0
        for item in intervals:
            high = max(high, item["end_sample"])
            self.prefix_ends.append(high)

    def hits(self, start, end):
        high = bisect_left(self.starts, end)
        low = bisect_left(self.prefix_ends, start + 1, 0, high)
        return [x for x in self.rows[low:high] if x["end_sample"] > start]


def _union_size(intervals):
    size, previous = 0, None
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if previous is None or start > previous[1]:
            if previous:
                size += previous[1] - previous[0]
            previous = [start, end]
        else:
            previous[1] = max(previous[1], end)
    return size + (previous[1] - previous[0] if previous else 0)


def _intersection_size(rows, start, end, kind=None):
    return _union_size((max(start, r["start_sample"]), min(end, r["end_sample"]))
                       for r in rows if kind is None or r["kind"] == kind)


def _mask_status(hits):
    if not hits:
        return None
    return "missing" if any(x["kind"] == "missing" for x in hits) else "excluded"


def _strict_records(records):
    rows = list(records)
    try:
        normalized = _normalize_records(rows)
    except (TypeError, ValueError, IndexError, AttributeError, OverflowError) as error:
        raise STTRangeError("invalid beat record") from error
    if len(normalized) != len(rows) or any(type(row[0]) is not int or type(row[1]) is not int for row in normalized):
        raise STTRangeError("beat sample and group must be integer values")
    if any(a[0] == b[0] for a, b in zip(normalized, normalized[1:])):
        raise STTRangeError("duplicate beat sample anchors are ambiguous")
    return normalized


def _calculate(buffer, total_samples, records, *, start_sample, end_sample,
               leads=None, measurement_ms=60, exclusions=(), basis=None, source_digest=None):
    start, end = _integer(start_sample, "start_sample"), _integer(end_sample, "end_sample")
    if not 0 <= start < end <= total_samples:
        raise STTRangeError("range must lie within the source; boundaries are not silently clipped")
    if end - start < MINIMUM_RANGE_SAMPLES:
        raise STTRangeError("selected range must contain at least 60 seconds (12000 samples)")
    profile = method_profile(measurement_ms)
    if leads is not None and not isinstance(leads, (list, tuple)):
        raise STTRangeError("leads must be a list or tuple")
    chosen = list(LEADS if leads is None else leads)
    if not chosen or any(not isinstance(x, str) or x not in LEADS for x in chosen) or len(set(chosen)) != len(chosen):
        raise STTRangeError("select unique supported leads")
    if basis is not None and not isinstance(basis, dict):
        raise STTRangeError("basis must be a dictionary")
    scope = copy.deepcopy(basis or {})
    _digest(scope)
    if source_digest is not None and (not isinstance(source_digest, str) or not source_digest):
        raise STTRangeError("source_digest must be a nonempty caller-supplied identity")
    normalized = _strict_records(records)
    masks = _masks(exclusions, total_samples)
    mask_index = _MaskIndex(masks)
    blocks_by_index = {}
    for row in normalized:
        if 0 <= row[0] < total_samples:
            blocks_by_index.setdefault(row[0] // BLOCK_SAMPLES, []).append(row)
    lead_indices = [LEADS.index(x) for x in chosen]
    values = {lead: [] for lead in chosen}
    reasons, statuses, mask_flags = Counter(), Counter(), Counter()
    flag_definitions = {}
    detail_blocks, used_anchors, eligible_samples = [], [], 0
    settings = {**DEFAULT_CONFIG, "st_measurement_ms": measurement_ms}

    for block_index in range(start // BLOCK_SAMPLES, (end - 1) // BLOCK_SAMPLES + 1):
        rows = blocks_by_index.get(block_index, [])
        classifications, candidates, observation_masks = {}, [], {}
        for i, row in enumerate(rows):
            sample, group, rr = row
            previous = rows[i-1][1] if i else None
            following = rows[i+1][1] if i+1 < len(rows) else None
            anchor_hits = mask_index.hits(sample, sample+1)
            baseline_hits = mask_index.hits(sample-40, sample-23)
            observation_masks[sample] = anchor_hits + baseline_hits
            if group != 1:
                classifications[sample] = ("excluded", "non_n_candidate")
            elif previous in (3, 34) or following in (3, 34):
                classifications[sample] = ("excluded", "adjacent_v_or_artifact")
            elif not 350 <= rr <= 2000:
                classifications[sample] = ("excluded", "rr_outside_legacy_bounds")
            elif anchor_hits:
                status = _mask_status(anchor_hits)
                classifications[sample] = (status, "explicit_missing_interval" if status == "missing" else "explicit_anchor_exclusion")
            elif baseline_hits:
                # Baseline support is known even when every J representative
                # is masked.  Do not relabel a known exclusion as missing J.
                status = _mask_status(baseline_hits)
                classifications[sample] = (status, "explicit_missing_support" if status == "missing" else "measurement_support_exclusion")
            elif sample < 50 or sample + 120 >= total_samples:
                classifications[sample] = ("missing", "source_edge_guard_unavailable")
            else:
                candidates.append(row)

        clean_representatives = [r for r in candidates if not mask_index.hits(
            r[0]+REPRESENTATIVE_HALO[0], r[0]+REPRESENTATIVE_HALO[1])]
        representatives = _evenly(clean_representatives, 7)
        block_start, block_end = block_index * BLOCK_SAMPLES, min(total_samples, (block_index+1) * BLOCK_SAMPLES)
        selected_rows = [r for r in rows if start <= r[0] < end]
        block = {"block_index": block_index, "start_sample": block_start, "end_sample": block_end,
                 "range_start_sample": max(start, block_start), "range_end_sample": min(end, block_end),
                 "j_representative_samples": [r[0] for r in representatives],
                 "candidate_count": len(candidates), "j_offset_samples": None,
                 "landmark_confidence": None, "quality_score": None, "eligible": False}
        actual = []
        if len(representatives) < 3:
            block["reason"] = "insufficient_uncontaminated_j_representatives"
            for row in candidates:
                classifications[row[0]] = ("missing", "j_unavailable")
        else:
            j, _ = _estimate_j_sample(buffer, representatives, total_samples)
            st_offset = j + measurement_ms * SAMPLE_RATE // 1000
            for row in candidates:
                sample = row[0]
                hits = mask_index.hits(sample-40, sample-23) + mask_index.hits(sample+st_offset-2, sample+st_offset+3)
                observation_masks[sample] += hits
                if hits:
                    status = _mask_status(hits)
                    classifications[sample] = (status, "explicit_missing_support" if status == "missing" else "measurement_support_exclusion")
                else:
                    actual.append(row)
            population = sum(r[1] != 34 and not mask_index.hits(r[0], r[0]+1) for r in rows)
            measurement = _block_measurement(buffer, representatives, population, total_samples,
                                              settings, normal_count=len(actual))
            block.update(j_offset_samples=j, j_offset_ms=j*5,
                         landmark_confidence=measurement["landmark_confidence"],
                         quality_score=measurement["quality_score"],
                         normal_beat_ratio=measurement["normal_beat_ratio"], eligible=measurement["eligible"])
            if not measurement["eligible"]:
                block["reason"] = "engineering_quality_gate"
                for row in actual:
                    classifications[row[0]] = ("excluded", "engineering_quality_gate")
            else:
                block["reason"] = None
                for row in actual:
                    classifications[row[0]] = ("used", "used")
                lo, hi = max(start, block_start), min(end, block_end)
                eligible_samples += hi - lo - _intersection_size(masks, lo, hi)

        used = [r for r in actual if start <= r[0] < end and classifications[r[0]][0] == "used"]
        block_values = {lead: [] for lead in chosen}
        if used:
            # Existing raw int16-derived values and per-beat five-point medians;
            # guards above guarantee no helper clipping can occur here.
            baseline = np.median(_sample_frames(buffer, used, BASELINE_OFFSETS, total_samples), axis=1)
            st = np.median(_sample_frames(buffer, used, range(st_offset-2, st_offset+3), total_samples), axis=1)
            differences = st - baseline
            for column, lead in zip(lead_indices, chosen):
                block_values[lead] = differences[:, column].tolist()
                values[lead].extend(block_values[lead])
            used_anchors.extend(r[0] for r in used)
        block_status, block_reasons, block_flags = Counter(), Counter(), Counter()
        for row in selected_rows:
            status, reason = classifications[row[0]]
            statuses[status] += 1; block_status[status] += 1
            if status != "used":
                reasons[reason] += 1; block_reasons[reason] += 1
            flags = {}
            for mask in observation_masks[row[0]]:
                flag = {key: mask[key] for key in ("kind", "reason", "origin", "review_status") if key in mask}
                flags[_digest(flag)] = flag
            for key, flag in flags.items():
                flag_definitions[key] = flag
                mask_flags[key] += 1; block_flags[key] += 1
        block["counts"] = {"detected_count": len(selected_rows),
                           **{f"{s}_count": block_status[s] for s in ("used", "excluded", "missing")},
                           "reason_counts": dict(sorted(block_reasons.items()))}
        block["mask_reason_counts"] = [{**flag_definitions[key], "beat_count": value}
                                       for key, value in sorted(block_flags.items())]
        block["leads"] = [{"lead": lead, "mean_units": math.fsum(v)/len(v) if v else None,
                           "used_count": len(v)} for lead, v in block_values.items()]
        detail_blocks.append(block)

    counts = {"detected_count": sum(statuses.values()),
              **{f"{s}_count": statuses[s] for s in ("used", "excluded", "missing")},
              "reason_counts": dict(sorted(reasons.items()))}
    duration = (end-start)/SAMPLE_RATE
    all_mask_samples = _intersection_size(masks, start, end)
    missing_samples = _intersection_size(masks, start, end, "missing")
    excluded_samples = all_mask_samples - missing_samples
    coverage = {
        "requested_duration_s": duration,
        "source_coverage_s": duration - missing_samples/SAMPLE_RATE,
        "explicit_excluded_s": excluded_samples/SAMPLE_RATE,
        "explicit_missing_s": missing_samples/SAMPLE_RATE,
        "engineering_eligible_block_coverage_s": eligible_samples/SAMPLE_RATE,
        "engineering_eligible_block_coverage_pct": eligible_samples*100/(end-start),
        "used_anchor_span_s": (used_anchors[-1]-used_anchors[0])/SAMPLE_RATE if used_anchors else None,
        "max_used_anchor_gap_s": max((b-a)/SAMPLE_RATE for a,b in zip(used_anchors, used_anchors[1:])) if len(used_anchors)>1 else None,
        "coverage_is_signal_quality": False,
        "definition": "intersection of eligible fixed 16s blocks with selected range, less union of explicit masks; does not certify each second or infer undetected beats",
    }
    result = {
        "schema_version": SCHEMA_VERSION, "scope": scope, "method_profile": profile,
        "range": {"start_sample": start, "end_sample": end, "start_s": start/SAMPLE_RATE,
                  "end_s": end/SAMPLE_RATE, "duration_s": duration, "half_open": True},
        "exclusions": {"intervals": masks, "digest": _digest(masks)},
        "counts": counts, "coverage": coverage,
        "mask_reason_counts": [{**flag_definitions[key], "beat_count": value}
                               for key, value in sorted(mask_flags.items())],
        "count_definition": "used/excluded/missing and primary reason counts are mutually exclusive per detected R; mask reason flags may overlap and never invent undetected beats",
        "leads": [{"lead": lead, "mean_units": math.fsum(v)/len(v) if v else None,
                   "used_count": len(v), "excluded_count": counts["excluded_count"],
                   "missing_count": counts["missing_count"], "reason_counts": counts["reason_counts"].copy()}
                  for lead, v in values.items()],
        "blocks": detail_blocks,
        "binding": {"source_digest": source_digest, "source_sample_count": total_samples,
                    "beats_digest": _digest(normalized), "scope_digest": _digest(scope),
                    "method_digest": _digest(profile), "exclusions_digest": _digest(masks),
                    "range_digest": _digest([start, end, chosen]),
                    "status": "caller_source_and_basis_bound" if scope and source_digest else "unbound_math_only"},
        "review_status": "statistics_pending_physician_review",
        "interpretation": {"diagnosis_generated": False, "sustained_depression_inferred": False,
                           "signal_quality_verified": False, "sinus_origin_verified": False},
    }
    result["result_digest"] = _digest(result)
    return result


def calculate_stt_range(raw_samples, records, **kwargs):
    """Pure-memory API for synthetic or caller-owned complete source samples.

    Array input must be a contiguous N-by-8 int16 array.  Bytes input is the
    existing little-endian source format.  The caller must supply source sample
    zero as array sample zero.  The pure API cannot detect an incorrectly
    rebased slice; production uses the guarded complete-file wrapper instead.
    """
    if isinstance(raw_samples, np.ndarray):
        if (raw_samples.ndim != 2 or raw_samples.shape[1] != CHANNEL_COUNT or
                raw_samples.dtype != np.dtype("<i2") or not raw_samples.flags.c_contiguous):
            raise STTRangeError("raw_samples must be contiguous N-by-8 little-endian int16")
        buffer = memoryview(raw_samples).cast("B")
    elif isinstance(raw_samples, (bytes, bytearray, memoryview)):
        try:
            buffer = memoryview(raw_samples).cast("B")
        except (TypeError, ValueError) as error:
            raise STTRangeError("source-format bytes must be contiguous") from error
    else:
        raise STTRangeError("raw_samples must be an int16 array or source-format bytes")
    if not len(buffer) or len(buffer) % (CHANNEL_COUNT*2):
        raise STTRangeError("source must contain complete nonempty eight-channel frames")
    return _calculate(buffer, len(buffer)//(CHANNEL_COUNT*2), records, **kwargs)


@source_read
def analyze_stt_range(waveform_path, records, **kwargs):
    """Read-only full-source wrapper; caller also guards clinical basis pre/post."""
    path = Path(waveform_path)
    stat = require_waveform_file(path)
    with path.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as buffer:
        return _calculate(buffer, stat.st_size//(CHANNEL_COUNT*2), records, **kwargs)
