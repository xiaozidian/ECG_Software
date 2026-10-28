"""Frozen scalar report statistics from dd6d4ed, before 2026-10-28 indexing.

Only the import paths differ; aggregate predicates and all formulas are intact.
This mathematical differential oracle does not contain or load patient data.
"""
from datetime import datetime, timedelta
from ecg_core.report_layout import beat_rows
from ecg_core.rr_quality import valid_rr_rows, consistent_rate, rhythm_episodes, rhythm_summary


def report_statistics(index, start_time, settings, pause_edges_ms=None):
    """Beat counts by actual clock hour; pattern episodes assigned to onset hour.

    Runs and repeating patterns are overlapping descriptors, not extra beats or
    automatic diagnoses. Noise never becomes a valid heartbeat or a heart rate.
    """
    rows = beat_rows(index)
    rr_rows = valid_rr_rows(index['rows'], index['duration_s'])
    rate_rows = [r for r in rr_rows if consistent_rate(r)]
    episodes = rhythm_episodes(index['events'])
    try:
        clock = datetime.fromisoformat(str(start_time).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        clock = None
    def aggregate(lo, hi):
        beats = [r for r in rows if lo <= r["sample_index"] / 200 < hi]
        rates = [r for r in rate_rows if lo <= r['sample_index']/200 < hi]
        intervals = [r for r in rr_rows if lo <= r['sample_index']/200 < hi]
        events = [e for e in index["events"] if lo <= e["time_s"] < hi]
        slow = min(rates, key=lambda r: r["hr"]) if rates else None
        fast = max(rates, key=lambda r: r["hr"]) if rates else None
        longest = max(intervals, key=lambda r: r["rr_ms"]) if intervals else None
        rhythm = rhythm_summary(episodes, index['duration_s'], lo, hi)
        def point(r):
            return {"hr": r['hr'] if consistent_rate(r) else None, "time_s": r["sample_index"] / 200, "rr_ms": r["rr_ms"]} if r else None
        result = {"total": len(beats), "noise": sum(lo <= r["sample_index"] / 200 < hi and r["class_code"] == "X" for r in index["rows"]),
                  "rr_interval_count": len(intervals), "rate_interval_count": len(rates),
                  "min_hr": slow["hr"] if slow else None, "max_hr": fast["hr"] if fast else None,
                  "avg_hr": round(60000 / (sum(r["rr_ms"] for r in rates) / len(rates)), 2) if rates else None,
                  "fastest": point(fast), "slowest": point(slow), "longest": point(longest),
                  "tachy_beats": sum(r["hr"] >= settings["tachy"] for r in rates),
                  "brady_beats": sum(r["hr"] <= settings["brady"] for r in rates),
                  "pause": sum(e["category"] == "pause" for e in events),
                  "pause_over3": sum(e["category"] == "pause" and e["rr_ms"] > 3000 for e in events),
                  "af": rhythm['confirmed_any']['count'], "rhythm": rhythm}
        for code in ("V", "S"):
            total = sum(r["class_code"] == code for r in beats)
            result[code] = {"total": total, "pct": round(total / len(beats) * 100, 2) if beats else None,
                **{kind: sum(e["category"] == code and e["subtype"] in subtypes for e in events) for kind, subtypes in {
                    "single": ["single"], "couplet": ["couplet"], "run": ["triplet", "run"],
                    "bigeminy": ["bigeminy"], "trigeminy": ["nnp", "npp"]}.items()}}
        return result
    hourly = []
    t = 0
    while t < index["duration_s"]:
        dt = clock + timedelta(seconds=t) if clock else None
        length = min(index["duration_s"] - t, 3600 - (dt.minute * 60 + dt.second + dt.microsecond / 1e6 if dt else t % 3600))
        end = t + length
        hourly.append({"label": dt.strftime("%m-%d %H:%M") if dt else f"+{t / 3600:g}h", "start_s": t, "end_s": end, **aggregate(t, end)})
        t = end
    from ecg_core.review_candidates import rr_distribution
    distribution=rr_distribution(index['rows'],index['duration_s'],pause_edges_ms)
    for bucket in distribution['bins']:bucket.pop('samples')
    return {"pause_distribution":distribution,"summary": aggregate(0, index["duration_s"]), "hourly": hourly, "settings": settings,
            "method": "当前修订逐搏统计；心率由有效 RR 计算。成对、短阵和联律按起点计次，模式可重叠，不与总心搏相加；长 RR 为阈值候选，房颤/房扑仅计医生已确认片段。"}
