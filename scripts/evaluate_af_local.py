#!/usr/bin/env python3
"""Known-data development experiment: local entropy aggregation, not deployment."""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter
import csv
from datetime import datetime, timezone
import gzip
import json
import math
from pathlib import Path
import platform
import shutil
import subprocess

try:
    from scripts import validate_afdb as base, validate_ltafdb as long
    from scripts.develop_af_entropy import candidate_episodes
except ModuleNotFoundError:
    import validate_afdb as base
    import validate_ltafdb as long
    from develop_af_entropy import candidate_episodes

ROOT = base.ROOT
THRESHOLD = -1.35
MODELS = ('baseline', 'median', 'upper-quartile', 'maximum')
BANDS = ('under_30s', '30_to_under_120s', '120s_or_longer')
SOURCES = list(dict.fromkeys(base.SOURCES + long.SOURCES + [
    'scripts/develop_af_entropy.py', 'scripts/af_entropy_features.cjs',
    'scripts/af_local_entropy.cjs', 'scripts/evaluate_af_local.py',
    'docs/af-local-aggregation-protocol.md', 'tests/test_af_local.py']))


def partition(items, duration):
    end = 0.
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Invalid duration')
    for item in items:
        a, b = item['start_s'], item['end_s']
        if not math.isfinite(a) or not math.isfinite(b) or a != end or not a < b <= duration:
            raise ValueError('Partition gap, overlap or invalid boundary')
        end = b
    if end != duration:
        raise ValueError('Incomplete partition')


def predict(windows, model):
    if model not in MODELS:
        raise ValueError('Unknown model')
    if model == 'baseline':
        return [dict(w) for w in windows]
    key = {'median': 'entropy', 'upper-quartile': 'upper_quartile', 'maximum': 'maximum'}[model]
    output = []
    for w in windows:
        value = w[key]
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
            raise ValueError('Nonfinite or invalid feature')
        evaluated = bool(w['evaluated'] and value is not None)
        output.append(dict(w, evaluated=evaluated, candidate=bool(evaluated and value >= THRESHOLD),
                           reason=w['entropy_reason']))
    return output


def reference_events(segments, duration):
    partition(segments, duration)
    events = []
    for s in segments:
        if s['rhythm'] != 'AFIB':
            continue
        if events and events[-1]['end_s'] == s['start_s']:
            events[-1]['end_s'] = s['end_s']
        else:
            events.append(dict(start_s=s['start_s'], end_s=s['end_s']))
    for e in events:
        length = e['end_s'] - e['start_s']
        e.update(duration_s=length, band=BANDS[0 if length < 30 else 1 if length < 120 else 2],
                 touches_record_boundary=e['start_s'] == 0 or e['end_s'] == duration)
    return events


def event_scores(windows, segments, duration):
    partition(windows, duration)
    ends = [w['end_s'] for w in windows]
    output = []
    for e in reference_events(segments, duration):
        positive = withheld = negative = 0.
        k = bisect_right(ends, e['start_s'])
        while k < len(windows) and windows[k]['start_s'] < e['end_s']:
            w = windows[k]; k += 1
            overlap = min(w['end_s'], e['end_s']) - max(w['start_s'], e['start_s'])
            if not w['evaluated']:
                withheld += overlap
            elif w['candidate']:
                positive += overlap
            else:
                negative += overlap
        if abs(positive + withheld + negative - e['duration_s']) > 1e-7:
            raise ValueError('Incomplete event accounting')
        output.append(dict(e, captured_s=positive, withheld_s=withheld, negative_s=negative,
                           any_overlap=positive > 0, half_captured=positive >= .5 * e['duration_s'],
                           fully_captured=negative == 0 and withheld == 0))
    return output


def event_summary(events):
    result = {}
    for band in ('all', *BANDS):
        rows = [e for e in events if band == 'all' or e['band'] == band]
        result[band] = dict(events=len(rows), **{k: sum(e[k] for e in rows) for k in (
            'duration_s', 'captured_s', 'withheld_s', 'negative_s', 'any_overlap',
            'half_captured', 'fully_captured', 'touches_record_boundary')})
    return result


def time_score(windows, segments, duration):
    partition(windows, duration); partition(segments, duration)
    seconds = dict.fromkeys(base.TIME_KEYS, 0.)
    strata = {s['rhythm']: dict(candidate_s=0., negative_s=0., withheld_s=0.)
              for s in segments if s['rhythm'] != 'unknown'}
    j = 0
    for w in windows:
        while segments[j]['end_s'] <= w['start_s']:
            j += 1
        k = j
        while k < len(segments) and segments[k]['start_s'] < w['end_s']:
            s = segments[k]; k += 1
            overlap = min(w['end_s'], s['end_s']) - max(w['start_s'], s['start_s'])
            if s['rhythm'] == 'unknown':
                seconds['unknown_s'] += overlap
                continue
            af = s['rhythm'] == 'AFIB'
            state = 'withheld' if not w['evaluated'] else 'candidate' if w['candidate'] else 'negative'
            strata[s['rhythm']][state + '_s'] += overlap
            key = ('withheld_af_s' if af else 'withheld_non_af_s') if state == 'withheld' else (
                'tp_s' if af else 'fp_s') if state == 'candidate' else ('fn_s' if af else 'tn_s')
            seconds[key] += overlap
    return dict(seconds=seconds, metrics=base.metrics(seconds), by_rhythm=strata)


def native_audit(windows, segments, fs, length):
    """Independent native-sample labels and counts; no interval intersection."""
    import numpy as np
    reference = np.zeros(length, dtype=np.uint8)
    prediction = np.zeros(length, dtype=np.uint8)
    for items, array, is_reference in ((segments, reference, True), (windows, prediction, False)):
        previous = 0
        for item in items:
            a, b = round(item['start_s'] * fs), round(item['end_s'] * fs)
            if abs(a / fs - item['start_s']) > 1e-9 or abs(b / fs - item['end_s']) > 1e-9 or not previous == a < b <= length:
                raise ValueError('Invalid native partition')
            value = (0 if item['rhythm'] == 'unknown' else 1 if item['rhythm'] == 'AFIB' else 2) if is_reference else (
                0 if not item['evaluated'] else 2 if item['candidate'] else 1)
            array[a:b] = value
            previous = b
        if previous != length:
            raise ValueError('Incomplete native partition')
    counts = np.bincount(reference * 3 + prediction, minlength=9)
    return dict(tp_s=float(counts[5])/fs, fn_s=float(counts[4])/fs,
                fp_s=float(counts[8])/fs, tn_s=float(counts[7])/fs,
                withheld_af_s=float(counts[3])/fs, withheld_non_af_s=float(counts[6])/fs,
                unknown_s=float(counts[:3].sum())/fs)


def summarize(results):
    seconds = {k: sum(r['seconds'][k] for r in results) for k in base.TIME_KEYS}
    capture = [r['metrics']['all_af_candidate_capture'] for r in results
               if r['metrics']['all_af_candidate_capture'] is not None]
    return dict(records=len(results), seconds=seconds, metrics=base.metrics(seconds),
                macro_af_capture=sum(capture)/len(capture) if capture else None,
                macro_af_records=len(capture), false_positive_hours=seconds['fp_s']/3600,
                candidate_episodes=sum(r['candidate_episodes'] for r in results),
                events={band: {k: sum(r['events'][band][k] for r in results)
                               for k in ('events', 'duration_s', 'captured_s', 'withheld_s', 'negative_s',
                                         'any_overlap', 'half_captured', 'fully_captured', 'touches_record_boundary')}
                        for band in ('all', *BANDS)})


def append_csv(stream, writer, row):
    if writer is None:
        writer = csv.DictWriter(stream, fieldnames=list(row)); writer.writeheader()
    writer.writerow(row)
    return writer


def evaluate(afdb, ltafdb, output):
    import numpy as np
    import wfdb
    # Verify prior frozen source identity before using its math or adapters.
    development, _ = long.frozen_parameters()
    sources = list(dict.fromkeys(SOURCES + list(development['source_sha256'])))
    before = {n: base.digest(ROOT/n) for n in sources}
    inputs = {}
    for label, folder, adapter in (('afdb', afdb, base), ('ltafdb', ltafdb, long)):
        sums = base.catalog(folder)
        names = adapter.inputs(folder)
        for name in names:
            if base.digest(folder/name) != sums[name]:
                raise ValueError('Input checksum mismatch: ' + label + '/' + name)
        inputs[label] = {n: base.digest(folder/n) for n in ['SHA256SUMS.txt', *names]}
    output.mkdir(parents=True, exist_ok=False)
    results, exclusions = [], []
    comparisons, max_delta = 0, 0.
    with gzip.open(output/'features.csv.gz', 'wt', newline='') as features_file, gzip.open(
            output/'predictions.csv.gz', 'wt', newline='') as predictions_file, gzip.open(
            output/'events.csv.gz', 'wt', newline='') as events_file:
        fw = pw = ew = None
        for database, folder in (('afdb', afdb), ('ltafdb', ltafdb)):
            names = base.names(folder) if database == 'afdb' else long.records(folder)
            for name in names:
                header = wfdb.rdheader(str(folder/name))
                if database == 'afdb' and not header.sig_len:
                    exclusions.append(name); continue
                expected_fs = 250 if database == 'afdb' else 128
                if header.fs != expected_fs or header.sig_len <= 0:
                    raise ValueError('Unexpected recording shape')
                ref = wfdb.rdann(str(folder/name), 'atr')
                duration = header.sig_len/header.fs
                segments = base.rhythm_segments(ref.sample, ref.aux_note, header.sig_len, header.fs) if database == 'afdb' else (
                    long.reference_segments(ref.sample, ref.symbol, ref.aux_note, header.sig_len, header.fs))
                modes = ['qrs'] + (['qrsc'] if name + '.qrsc' in inputs[database] else []) if database == 'afdb' else ['qrs', 'atr']
                for mode in modes:
                    beats = wfdb.rdann(str(folder/name), mode)
                    rows, metadata = base.adapt(beats.sample, beats.symbol, header.sig_len, header.fs) if database == 'afdb' else (
                        long.adapt(beats.sample, beats.symbol, beats.aux_note, header.sig_len, header.fs, mode))
                    run = subprocess.run(['node', 'scripts/af_local_entropy.cjs'], cwd=ROOT,
                                         input=json.dumps(dict(rows=rows, duration=duration)),
                                         text=True, capture_output=True, check=True, timeout=120)
                    windows = json.loads(run.stdout)
                    identity = dict(database=database, record=name, input=mode)
                    for w in windows:
                        fw = append_csv(features_file, fw, dict(identity, **w))
                    predictions = {m: predict(windows, m) for m in MODELS}
                    for a, b, c in zip(*(predictions[m] for m in MODELS[1:])):
                        if not a['evaluated'] == b['evaluated'] == c['evaluated'] or not a['candidate'] <= b['candidate'] <= c['candidate']:
                            raise ValueError('Aggregation coverage or monotonicity violation')
                    for model, predicted in predictions.items():
                        measured = time_score(predicted, segments, duration)
                        native = native_audit(predicted, segments, header.fs, header.sig_len)
                        for key in base.TIME_KEYS:
                            delta = abs(native[key]-measured['seconds'][key]); comparisons += 1
                            max_delta = max(max_delta, delta)
                            if delta > 1e-6:
                                raise ValueError('Native audit mismatch')
                        events = event_scores(predicted, segments, duration)
                        totals = event_summary(events)
                        for event_key, time_key in (('captured_s', 'tp_s'), ('negative_s', 'fn_s'), ('withheld_s', 'withheld_af_s')):
                            if abs(totals['all'][event_key] - measured['seconds'][time_key]) > 1e-6:
                                raise ValueError('Event and time totals disagree')
                        measured.update(identity, model=model, threshold=None if model == 'baseline' else THRESHOLD,
                                        candidate_episodes=candidate_episodes(predicted), events=totals,
                                        quality_reasons=dict(Counter(w['reason'] for w in predicted if w['reason'])))
                        results.append(measured)
                        for event in events:
                            ew = append_csv(events_file, ew, dict(identity, model=model, **event))
                        for w in predicted:
                            pw = append_csv(predictions_file, pw, dict(identity, model=model,
                                **{k: w[k] for k in ('start_s', 'end_s', 'evaluated', 'candidate', 'reason')}))
                    print(f'{database} {name} {mode}: {len(windows)} windows, all four native audits passed', flush=True)
    if len(results) != (25 + 168) * 4 or set(exclusions) != {'00735', '03665'}:
        raise ValueError('Incomplete evaluation')
    if before != {n: base.digest(ROOT/n) for n in sources}:
        raise ValueError('Source changed during evaluation')
    for label, folder in (('afdb', afdb), ('ltafdb', ltafdb)):
        if inputs[label] != {n: base.digest(folder/n) for n in inputs[label]}:
            raise ValueError('Inputs changed during evaluation')
    summary = dict(protocol='af-local-aggregation-v1', completed_at=datetime.now(timezone.utc).isoformat(),
                   interpretation='Both databases are known development data. NOT independent validation or deployment approval.',
                   threshold=THRESHOLD, exclusions=exclusions, source_sha256=before, input_sha256=inputs,
                   native_audit=dict(comparisons=comparisons, max_difference_s=max_delta),
                   groups={db: {mode: {model: summarize([r for r in results if r['database'] == db and r['input'] == mode and r['model'] == model])
                                       for model in MODELS} for mode in modes}
                           for db, modes in (('afdb', ('qrs', 'qrsc')), ('ltafdb', ('qrs', 'atr')))},
                   runtime=dict(python=platform.python_version(), numpy=np.__version__, wfdb=wfdb.__version__,
                                node=subprocess.check_output(['node', '--version'], text=True).strip()))
    for name, value in [('summary.json', summary), ('records.json', results)]:
        (output/name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    for name in sources:
        target = output/'snapshot'/name; target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(ROOT/name, target)
    print('Completed development experiment:', output, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--afdb', required=True, type=Path)
    parser.add_argument('--ltafdb', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    evaluate(args.afdb, args.ltafdb, args.output)
