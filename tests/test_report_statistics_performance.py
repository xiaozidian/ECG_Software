"""Exact report-hour indexing checks on mathematical rows, with no case files."""
import copy
import importlib.util
from pathlib import Path
import random

import pytest

from ecg_core.report_layout import report_statistics


spec = importlib.util.spec_from_file_location(
    'report_statistics_scalar', Path(__file__).parent / 'oracles/report_statistics_scalar.py')
scalar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scalar)
SETTINGS = dict(nn_min=300, nn_max=2000, pause=2.5, tachy=120, brady=50)


def math_index(duration, *, unordered=False):
    # Nonuniform intervals, artifacts, and nonbeat markers keep the populations
    # distinct. Explicit exact-hour/end rows exercise every half-open boundary.
    rows = []
    sample = 0
    for i in range(int(duration / 6) + 1):
        rr = (500, 750, 1000, 1250, 3000, 3500, 6000)[i % 7]
        sample += rr // 5
        if sample > duration * 200:
            break
        code = ('N', 'N', 'V', 'N', 'S', 'X', 'O', 'Y', 'T')[i % 9]
        rows.append(dict(sample_index=sample, class_code=code, rr_ms=rr,
                         hr=round(60000 / rr, 1)))
    for second in (0, 1, 2, 3, 3599.995, 3600, 3600.005, 7199.995, 7200,
                   86399.995, 86400, 86400.005, duration):
        if 0 <= second <= duration:
            rows.append(dict(sample_index=round(second * 200), class_code='N',
                             rr_ms=1000, hr=60.0))
    # Distinct noise population at the exact hour and record end.
    for second in (0, 3600, duration):
        if second <= duration:
            rows.append(dict(sample_index=round(second * 200), class_code='X', rr_ms=0, hr=0))
    rows.sort(key=lambda r: r['sample_index'])
    events = []
    for i, second in enumerate(range(0, int(duration) + 1, 307)):
        category = ('V', 'S', 'pause')[i % 3]
        events.append(dict(time_s=second, end_s=second + 1, category=category,
                           subtype=('single', 'couplet', 'run', 'bigeminy', 'npp')[i % 5],
                           rr_ms=3500))
    if duration > 7200:
        events.extend([
            dict(time_s=3590, end_s=3610, category='AF', subtype='AF', rhythm_status='confirmed'),
            dict(time_s=3600, end_s=3700, category='AF', subtype='AFL', rhythm_status='confirmed'),
            dict(time_s=3600, end_s=3800, category='AF', subtype='AF', rhythm_status='pending'),
            dict(time_s=7200, end_s=7201, category='pause', subtype='pause', rr_ms=4000),
        ])
    events.sort(key=lambda e: e['time_s'])
    if unordered:
        rng = random.Random(20261028)
        # Reverse complete chunks, retaining valid RR pairs within each chunk.
        rows = [r for start in reversed(range(0, len(rows), 47)) for r in rows[start:start + 47]]
        rng.shuffle(events)
    return dict(rows=rows, events=events, duration_s=duration)


@pytest.mark.parametrize('duration', [0, 9.005, 7200.005, 90005.005])
@pytest.mark.parametrize('clock', [None, 'invalid-clock', '2026-10-28T23:59:59.995+08:00'])
@pytest.mark.parametrize('unordered', [False, True])
def test_math_rows_match_scalar_for_hour_edges_multiday_and_source_order(duration, clock, unordered):
    index = math_index(duration, unordered=unordered)
    before = copy.deepcopy(index)
    expected = scalar.report_statistics(index, clock, SETTINGS, [1000, 3000, 5000])
    actual = report_statistics(index, clock, SETTINGS, [1000, 3000, 5000])
    assert actual == expected
    assert index == before
    assert sum(h['total'] for h in actual['hourly']) == actual['summary']['total']
    assert sum(h['noise'] for h in actual['hourly']) == actual['summary']['noise']


@pytest.mark.parametrize('times', [[float('nan')], [float('inf')], [float('-inf')],
                                  [float('nan'), 1, 3600, float('inf'), -1]])
def test_nonfinite_event_and_noise_times_keep_scalar_predicate(times):
    index = math_index(7201)
    index['events'] = [dict(time_s=t, end_s=t, category='V', subtype='single') for t in times]
    index['rows'].extend(dict(sample_index=t * 200, class_code='X', rr_ms=0, hr=0) for t in times)
    assert report_statistics(index, None, SETTINGS) == scalar.report_statistics(index, None, SETTINGS)


def test_first_tied_rate_and_longest_interval_follow_original_order():
    # Each pair is internally valid, while pairs deliberately arrive out of
    # timestamp order. min/max must keep the first equal entry as before.
    rows = [dict(sample_index=t * 200, class_code='N', rr_ms=1000, hr=60.0)
            for t in (100, 101, 10, 11, 200, 201)]
    index = dict(rows=rows, events=[], duration_s=7201)
    actual = report_statistics(index, None, SETTINGS)
    assert actual == scalar.report_statistics(index, None, SETTINGS)
    for key in ('fastest', 'slowest', 'longest'):
        assert actual['summary'][key]['time_s'] == 101


def test_exclusive_end_duplicate_boundary_and_noise_do_not_leak_between_hours():
    index = dict(rows=[
        dict(sample_index=t * 200, class_code=code, rr_ms=1000, hr=60.0)
        for t, code in [(3599, 'N'), (3600, 'N'), (3600, 'N'),
                        (3600, 'X'), (3601, 'N'), (7200, 'N'), (7200, 'X')]],
        events=[dict(time_s=3600, category='S', subtype='single')], duration_s=7200)
    actual = report_statistics(index, None, SETTINGS)
    assert actual == scalar.report_statistics(index, None, SETTINGS)
    assert [h['total'] for h in actual['hourly']] == [1, 3]
    assert [h['noise'] for h in actual['hourly']] == [0, 1]
    assert [h['S']['single'] for h in actual['hourly']] == [0, 1]
