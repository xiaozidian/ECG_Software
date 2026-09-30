"""Shared interval quality rules for measured NN statistics, HRT and DC.

An RR belongs to its ending beat. Non-QRS markers are not RR boundaries;
artifact beats are boundaries and must never be removed to join two intervals.
"""
from bisect import bisect_left
from math import isfinite

NONBEATS = frozenset(('O', 'Y', 'T'))


def rhythm_episodes(events):
    return [dict(start_s=e['time_s'], end_s=e['end_s'], kind=e.get('subtype', 'AF'),
                 status=e.get('rhythm_status', e.get('diagnosis_status', 'pending')))
            for e in events if e['category'] == 'AF' and e['end_s'] > e['time_s']]


def rhythm_summary(episodes, duration, start=0, end=None):
    """Saved episode coverage, not AF detection or assessable-signal coverage.

    Counts belong to the start bucket. Durations are clipped interval unions;
    pending coverage can overlap confirmed coverage and is never added to it.
    """
    end = duration if end is None else end
    if not all(finite(v) for v in (duration, start, end)) or not 0 <= start <= end <= duration:
        raise ValueError('节律统计范围无效')
    groups = {'confirmed_af': [], 'confirmed_afl': [], 'confirmed_any': [], 'pending_any': []}
    counts = {key: 0 for key in groups}
    for e in episodes:
        a, b, kind, status = e['start_s'], e['end_s'], e['kind'], e['status']
        if not all(finite(v) for v in (a, b)) or b <= a or kind not in ('AF', 'AFL') or status not in ('pending', 'confirmed', 'excluded'):
            raise ValueError('节律片段格式无效')
        keys = (['confirmed_any', 'confirmed_af' if kind == 'AF' else 'confirmed_afl']
                if status == 'confirmed' else ['pending_any'] if status == 'pending' else [])
        for key in keys:
            counts[key] += int(start <= a < end)
            lo, hi = max(start, a), min(end, b)
            if hi > lo:
                groups[key].append((lo, hi))
    result = dict(start_s=start, end_s=end, denominator_s=end-start)
    for key, spans in groups.items():
        merged = []
        for a, b in sorted(spans):
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
            else:
                merged.append((a, b))
        seconds = round(sum(b-a for a, b in merged), 6)
        result[key] = dict(count=counts[key], intersecting_count=len(spans), seconds=seconds,
                           pct=round(seconds/(end-start)*100, 6) if end > start else None)
    return result


def finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and isfinite(value)


def qrs_rows(rows):
    return [r for r in rows if r.get('class_code') not in NONBEATS]


def annotation_exclusions(annotations):
    """Convert inclusive stored samples to half-open sinus-exclusion spans.

    Pending and confirmed AF/AFL both withhold sinus-only measurements.
    A one-sample annotation occupies 5 ms; it must not become an empty span.
    """
    return [(a['sample_index'] / 200, (a['details']['end_sample'] + 1) / 200)
            for a in annotations if a.get('details', {}).get('kind') in ('AF', 'AFL')
            and a['details'].get('status') != 'excluded'
            and finite(a.get('sample_index')) and finite(a['details'].get('end_sample'))]


def interval_mask(rows, excluded=()):
    spans = sorted((a, b) for a, b in excluded if finite(a) and finite(b) and b > a)
    merged = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    starts = [a for a, _ in merged]
    mask = [False] * len(rows)
    for i in range(1, len(rows)):
        a, b = rows[i-1], rows[i]
        s, t, rr = a.get('sample_index'), b.get('sample_index'), b.get('rr_ms')
        if (a.get('class_code') in NONBEATS | {'X'} or b.get('class_code') in NONBEATS | {'X'}
                or not all(finite(x) for x in (s, t, rr)) or s < 0 or t <= s or rr <= 0
                or abs((t-s)*5 - rr) > 10):
            continue
        # Test the complete half-open interval, not only the ending R peak.
        j = bisect_left(starts, t/200) - 1
        mask[i] = j < 0 or merged[j][1] <= s/200
    return mask


def nn_intervals(feed):
    rows = qrs_rows(feed.beats)
    valid = interval_mask(rows, getattr(feed, 'excluded_rhythm_intervals', ()))
    opts = feed.document['settings']
    return [(i-1, rows[i-1]['sample_index']/200, r['sample_index']/200, r['rr_ms'])
            for i, r in enumerate(rows) if valid[i]
            and rows[i-1]['class_code'] == r['class_code'] == 'N'
            and opts['nn_min'] <= r['rr_ms'] <= opts['nn_max']
            and r['sample_index']/200 <= feed.duration]


def valid_rr_rows(rows, duration):
    """Measured RR endings for report screening, not a sinus-only NN filter.

    Keep artifacts as boundaries and ignore non-QRS markers. Do not repair,
    sort or bridge malformed intervals. The recording domain is [0, duration).
    Return original row references; consumers must not mutate them.
    """
    qrs = qrs_rows(rows)
    valid = interval_mask(qrs)
    return [r for i, r in enumerate(qrs) if valid[i] and r['sample_index']/200 < duration]


def consistent_rate(row):
    """The materializer caches instantaneous HR to one decimal place.

    Reject stale/foreign HR rather than mixing its extrema with RR averages.
    This is a cache consistency check, not a physiological heart-rate cutoff.
    """
    hr, rr = row.get('hr'), row.get('rr_ms')
    return (finite(hr) and hr > 0 and finite(rr) and rr > 0
            and abs(hr - 60000 / rr) <= .051)


def five_minute_blocks(nn, end_s, start_s=0):
    buckets = {}
    for r in nn:
        k = int((r[1]-start_s)//300)
        if k >= 0 and r[2] <= min(end_s, start_s+(k+1)*300):
            buckets.setdefault(k, []).append(r)
    return [(start_s+k*300, start_s+(k+1)*300, chosen)
            for k, chosen in sorted(buckets.items())
            if start_s+(k+1)*300 <= end_s and len(chosen) >= 30
            and sum(r[3] for r in chosen) >= 240000]
