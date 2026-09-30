"""Paper-report data contract. No diagnosis, source-data mutation or invented leads."""
from __future__ import annotations

from bisect import bisect_left
from datetime import datetime, timedelta
import math
from .rr_quality import qrs_rows, interval_mask, valid_rr_rows, consistent_rate, rhythm_episodes, rhythm_summary

LEADS = ["I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6"]
DEFAULT_LEADS = ["II", "V1", "V5"]


def strip_review_note(entry):
    """Episode confirmation is independent of beat review and report approval."""
    if entry.get('category') != 'AF':
        return ''
    name = '房扑' if entry.get('subtype') == 'AFL' else '房颤'
    status = entry.get('rhythm_status')
    if status == 'confirmed':
        return f'{name}片段已确认 · 不代表报告已审核'
    if status == 'excluded':
        return f'{name}片段已排除 · 不应入报'
    return f'{name}片段待复核 · 非确诊'


def valid_rr_pairs(rows, duration):
    """Project exact endpoints using the unchanged shared interval quality rules.

    A cached RR can differ by up to 10 ms under that contract; it is not an
    exact coordinate. Keep original row references and never bridge artifacts.
    """
    qrs = qrs_rows(rows)
    valid = interval_mask(qrs)
    return [(qrs[i-1], r) for i, r in enumerate(qrs)
            if valid[i] and r['sample_index']/200 < duration]


def paper_segments(entry, paper=None):
    """Split only the rendered paper, never the curated event or its samples.

    Half-open sample-aligned windows assign boundary beats exactly once.
    Legacy reports retain their full-window fit until explicitly switched.
    """
    paper = paper or {}
    if paper.get('time_scale', 'fit') != 'fixed':
        return [entry]
    speed = float(str(paper.get('speed', '25 mm/s')).split()[0])
    if speed not in (12.5, 25, 50):
        raise ValueError('不支持的固定纸速')
    wave = entry['waveform']
    first = round(wave['start_s'] * 200)
    count = round(wave['duration_s'] * 200)
    capacity = int(175 / speed * 200)
    total = math.ceil(count / capacity)
    result = []
    for i, offset in enumerate(range(0, count, capacity)):
        duration = min(capacity, count - offset) / 200
        start = (first + offset) / 200
        beats = sum(first + offset <= b['sample_index'] < first + offset + round(duration * 200)
                    for b in wave.get('beats', []))
        result.append({**entry, 'paper_segment': {'index': i + 1, 'count': total,
            'start_s': start, 'duration_s': duration, 'width_mm': duration * speed,
            'beat_count': beats}})
    return result


def strip_settings(raw=None):
    raw = raw or {}
    leads = raw.get("leads", DEFAULT_LEADS)
    if not isinstance(leads, list) or not leads or len(leads) > 12 or any(x not in LEADS for x in leads) or len(set(leads)) != len(leads):
        raise ValueError("请选择 1–12 个不重复的有效导联")
    seconds = raw.get("duration_s", 7)
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or not 1 <= seconds <= 120:
        raise ValueError("入报时长须为 1–120 秒；不足 5 搏将自动延长")
    result = {"leads": [x for x in LEADS if x in leads], "duration_s": seconds}
    if 'range_start_s' in raw or 'range_end_s' in raw:
        a, b = raw.get('range_start_s'), raw.get('range_end_s')
        if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in (a,b)) or a<0 or not 1<=b-a<=120:
            raise ValueError('人工入报区间须为非负起点、1–120 秒，并同时提供起止时间')
        result.update(range_start_s=math.floor(a*200+.5)/200,range_end_s=math.floor(b*200+.5)/200)
    return result


def beat_rows(index):
    return sorted((r for r in index["rows"] if r.get("class_code") not in ("X", "O", "Y", "T") and 0 <= r["sample_index"] < index["duration_s"] * 200), key=lambda r: r["sample_index"])


def resolve_strip(index, event, settings=None):
    settings = strip_settings(settings)
    total = max(.005, index["duration_s"])
    anchor = min(max(0, event["start_sample"] / 200), total)
    length = min(total, settings["duration_s"])
    start = max(0, min(anchor - length / 2, total - length))
    end = start + length
    pause_start_sample = None
    if event.get('category') == 'pause':
        # Re-read the current endpoints rather than trusting a saved event's
        # cached RR or supplied coordinates. Noise remains an interval boundary.
        pairs = [(a,b) for a,b in valid_rr_pairs(index['rows'], index['duration_s'])
                 if b['sample_index'] == event['start_sample'] and b['rr_ms'] > 2500]
        if len(pairs) != 1:
            raise ValueError('长 RR 的 R 峰依据已变化，请重新选择事件')
        pause_start_sample = pairs[0][0]['sample_index']
        start = max(0, min(start, pause_start_sample / 200 - .2))
        end = min(total, max(end, anchor + .3))
    rows = beat_rows(index)
    times = [r["sample_index"] / 200 for r in rows]
    # Keep a little ECG on each side of each R peak, including at record edges.
    count = lambda a, b: sum(a <= t < b for t in times)
    manual = 'range_start_s' in settings
    if manual:
        start,end=settings['range_start_s'],settings['range_end_s']
        if end>total or not start<=anchor<end:
            raise ValueError('人工区间须在记录范围内，并包含当前事件定位心搏')
        if pause_start_sample is not None and round(start*200)>pause_start_sample:
            raise ValueError('停搏候选入图须包含完整长 RR 间期的两个 R 峰')
        if count(start,end)<min(5,len(times)):
            raise ValueError('人工入报区间至少包含 5 个可用心搏，请向外拖动橘色边界')
    if not manual and count(start, end) < 5 and times:
        n = min(5, len(times))
        pivot = min(len(times) - 1, bisect_left(times, anchor))
        candidates = []
        for i in range(max(0, pivot - n), min(pivot + 1, len(times) - n + 1)):
            lo, hi = max(0, min(start, times[i] - .2)), min(total, max(end, times[i + n - 1] + .3))
            candidates.append((hi - lo, abs((hi + lo) / 2 - anchor), lo, hi))
        if candidates:
            _, _, start, end = min(candidates)
    start = math.floor(start * 200 + 1e-7) / 200
    end = min(total, math.ceil(end * 200 - 1e-7) / 200)
    visible = [{k: r.get(k) for k in ("sample_index", "class_code", "hr", "rr_ms")} for r in rows if start <= r["sample_index"] / 200 < end]
    actual = round(end - start, 3)
    warning = f"记录可用心搏不足 5 个，当前仅 {len(visible)} 搏" if len(visible) < 5 else ""
    if not manual and actual > settings["duration_s"] + .01:
        reason = '覆盖完整 RR 间期并包含至少 5 搏' if event.get('category') == 'pause' else '包含至少 5 搏'
        warning = f"为{reason}，已由 {settings['duration_s']:g} 秒延长至 {actual:g} 秒" + (f"；{warning}" if warning else "")
    return {**settings, "start_s": start, "end_s": end, "actual_duration_s": actual,
            "visible_beats": visible, "visible_beat_count": len(visible), "warning": warning,
            "context_start_s": max(0, min(anchor - max(30, actual * 3) / 2, total - min(total, max(30, actual * 3)))),
            "context_duration_s": min(total, max(30, actual * 3))}


def prepare_strip(index, event, settings, reader):
    spec = resolve_strip(index, event, settings)
    wave = reader(spec["start_s"], spec["end_s"], spec["leads"], 12000)
    wave["beats"] = spec["visible_beats"]
    context = reader(spec["context_start_s"], spec["context_start_s"] + spec["context_duration_s"], ["II"], 1600)
    return {**event, "strip": spec, "waveform": wave, "context": context}


def report_statistics(index, start_time, settings):
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
            result[code] = {"total": total, "pct": round(total / len(beats) * 100, 2) if beats else 0,
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
    return {"summary": aggregate(0, index["duration_s"]), "hourly": hourly, "settings": settings,
            "method": "当前修订逐搏统计；心率由有效 RR 计算。成对、短阵和联律按起点计次，模式可重叠，不与总心搏相加；长 RR 为阈值候选，房颤/房扑仅计医生已确认片段。"}
