#!/usr/bin/env python3
"""Record-held-out AFDB entropy experiment. No application changes or clinical pass."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import platform
import shutil
import subprocess
import time

try:
    from scripts import validate_afdb as base
except ModuleNotFoundError:
    import validate_afdb as base

ROOT = base.ROOT
GRID = [i / 100 for i in range(-300, 1, 5)]
MODELS = ('entropy', 'entropy-turning')
SOURCES = list(dict.fromkeys(base.SOURCES + [
    'scripts/af_entropy_features.cjs', 'scripts/develop_af_entropy.py',
    'docs/af-entropy-development-protocol.md', 'tests/test_af_entropy.py']))


def predict(windows, threshold, model):
    if model not in MODELS or not math.isfinite(threshold):
        raise ValueError('Unsupported candidate or threshold')
    result = []
    for w in windows:
        evaluated = bool(w['evaluated'] and w['entropy'] is not None)
        candidate = evaluated and w['entropy'] >= threshold
        if model == 'entropy-turning':
            candidate = candidate and w['turning_ratio'] is not None and .45 <= w['turning_ratio'] <= .85
        result.append(dict(w, evaluated=evaluated, candidate=bool(candidate),
                           reason=w['entropy_reason']))
    return result


def reference_weights(windows, segments):
    """AF/non-AF seconds per window, including mixed windows, excluding unknown."""
    result = []
    for w in windows:
        af = nonaf = 0.
        for s in segments:
            overlap = max(0., min(w['end_s'], s['end_s']) - max(w['start_s'], s['start_s']))
            if s['rhythm'] == 'AFIB':
                af += overlap
            elif s['rhythm'] != 'unknown':
                nonaf += overlap
        result.append((af, nonaf))
    return result


def threshold_scores(windows, weights, model):
    """Per-record scores, never counting withheld time as a correct decision."""
    import numpy as np
    w = np.asarray(weights, dtype=float)
    if w.shape != (len(windows), 2):
        raise ValueError('Window/reference shape mismatch')
    evaluated = np.array([x['evaluated'] and x['entropy'] is not None for x in windows])
    values = np.array([x['entropy'] if x['entropy'] is not None else -np.inf for x in windows])
    gate = np.ones(len(windows), dtype=bool)
    if model == 'entropy-turning':
        gate = np.array([x['turning_ratio'] is not None and .45 <= x['turning_ratio'] <= .85 for x in windows])
    elif model != 'entropy':
        raise ValueError('Unsupported candidate')
    totals = w.sum(axis=0)
    if not np.any(totals > 0):
        raise ValueError('No known reference for training record')
    scores = []
    for threshold in GRID:
        positive = evaluated & gate & (values >= threshold)
        negative = evaluated & ~positive
        correct = (w[positive, 0].sum(), w[negative, 1].sum())
        scores.append(float(np.mean([correct[i] / totals[i] for i in range(2) if totals[i] > 0])))
    return scores


def choose_threshold(scores_by_record, excluded=None):
    """Equal record weight, tie -> higher threshold. Same-record qrsc never enters."""
    training = sorted(k for k in scores_by_record if k != excluded)
    if not training:
        raise ValueError('No training records')
    if any(len(scores_by_record[k]) != len(GRID) or
           any(not math.isfinite(v) for v in scores_by_record[k]) for k in training):
        raise ValueError('Invalid training scores')
    scores = [sum(scores_by_record[k][i] for k in training) / len(training) for i in range(len(GRID))]
    best = max(range(len(GRID)), key=lambda i: (scores[i], GRID[i]))
    return dict(threshold=GRID[best], training_records=training, training_score=scores[best])


def candidate_episodes(windows):
    count, previous_end = 0, None
    for w in windows:
        if w['evaluated'] and w['candidate']:
            if previous_end != w['start_s']:
                count += 1
            previous_end = w['end_s']
        else:
            previous_end = None
    return count


def evaluate(folder, output):
    import numpy as np
    import wfdb
    sums = base.catalog(folder)
    file_names = ['SHA256SUMS.txt'] + base.inputs(folder)
    for name in file_names[1:]:
        if base.digest(folder / name) != sums[name]:
            raise ValueError('Input checksum mismatch: ' + name)
    before = {p: base.digest(ROOT / p) for p in SOURCES}
    input_hashes = {p: base.digest(folder / p) for p in file_names}
    output.mkdir(parents=True, exist_ok=False)
    datasets, excluded, feature_rows = [], [], []
    for record in base.names(folder):
        header = wfdb.rdheader(str(folder / record))
        if not header.sig_len:
            excluded.append(record)
            continue
        ann = wfdb.rdann(str(folder / record), 'atr')
        segments = base.rhythm_segments(ann.sample, ann.aux_note, header.sig_len, header.fs)
        for annotator in ('qrs', 'qrsc'):
            if record + '.' + annotator not in sums:
                continue
            beats = wfdb.rdann(str(folder / record), annotator)
            rows, error = base.adapt(beats.sample, beats.symbol, header.sig_len, header.fs)
            duration = header.sig_len / header.fs
            begin = time.perf_counter()
            run = subprocess.run(['node', 'scripts/af_entropy_features.cjs'], cwd=ROOT,
                                 input=json.dumps(dict(rows=rows, duration=duration)),
                                 text=True, capture_output=True, check=True, timeout=120)
            elapsed = time.perf_counter() - begin
            windows = json.loads(run.stdout)
            weights = reference_weights(windows, segments)
            datasets.append(dict(record=record, annotator=annotator, duration=duration,
                                 segments=segments, windows=windows, weights=weights,
                                 feature_elapsed_s=elapsed, max_timestamp_error_ms=error))
            feature_rows.extend(dict(record=record, annotator=annotator, **w) for w in windows)
            print(f'Features {record} {annotator}: {len(windows)} windows, {elapsed:.3f}s', flush=True)
    if set(excluded) != {'00735', '03665'} or len(datasets) != 25:
        raise ValueError('Unexpected evaluation coverage')
    primary = [d for d in datasets if d['annotator'] == 'qrs']
    training = {model: {d['record']: threshold_scores(d['windows'], d['weights'], model)
                        for d in primary} for model in MODELS}
    folds = {model: {d['record']: choose_threshold(training[model], d['record'])
                     for d in primary} for model in MODELS}
    final = {model: choose_threshold(training[model]) for model in MODELS}
    results, predictions = [], []
    for d in datasets:
        for model in ('baseline', *MODELS):
            threshold = None if model == 'baseline' else folds[model][d['record']]['threshold']
            windows = d['windows'] if model == 'baseline' else predict(d['windows'], threshold, model)
            measured = base.score(windows, d['segments'])
            if abs(sum(measured['seconds'].values()) - d['duration']) > 1e-6:
                raise ValueError('Incomplete time accounting')
            measured.update(record=d['record'], annotator=d['annotator'], model=model, threshold=threshold,
                            candidate_episodes=candidate_episodes(windows),
                            quality_reasons=dict(Counter(w['reason'] for w in windows if w['reason'])))
            results.append(measured)
            predictions.extend(dict(record=d['record'], annotator=d['annotator'], model=model,
                                    threshold=threshold, **{k: w[k] for k in ('start_s', 'end_s', 'evaluated', 'candidate', 'reason')})
                               for w in windows)
    summary_models = {}
    for model in ('baseline', *MODELS):
        main = [r for r in results if r['model'] == model and r['annotator'] == 'qrs']
        corrected = [r for r in results if r['model'] == model and r['annotator'] == 'qrsc']
        value = base.aggregate(main)
        value['candidate_episodes'] = sum(r['candidate_episodes'] for r in main)
        value['false_positive_hours'] = value['seconds']['fp_s'] / 3600
        summary_models[model] = dict(primary=value, corrected_qrsc=base.aggregate(corrected))
    if before != {p: base.digest(ROOT / p) for p in SOURCES}:
        raise ValueError('Source changed during experiment')
    if input_hashes != {p: base.digest(folder / p) for p in file_names}:
        raise ValueError('Inputs changed during experiment')
    summary = dict(protocol='af-entropy-development-v1', completed_at=datetime.now(timezone.utc).isoformat(),
                   interpretation='AFDB known development set, record-held-out thresholds; NOT external validation',
                   models=summary_models, folds=folds, final_development_fit=final, excluded=excluded,
                   source_sha256=before, input_sha256=input_hashes,
                   runtime=dict(python=platform.python_version(), numpy=np.__version__, wfdb=wfdb.__version__,
                                node=subprocess.check_output(['node', '--version'], text=True).strip()),
                   feature_timing=[{k: d[k] for k in ('record', 'annotator', 'feature_elapsed_s')} for d in datasets])
    for name, value in [('summary.json', summary), ('records.json', results)]:
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    for name, rows in [('features.csv', feature_rows), ('predictions.csv', predictions)]:
        with (output / name).open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    for name in SOURCES:
        target = output / 'snapshot' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    print(json.dumps(summary_models, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    evaluate(args.data, args.output)
