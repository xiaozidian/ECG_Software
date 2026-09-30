#!/usr/bin/env python3
"""Frozen external LTAFDB RR evaluation; no patient data or model training."""
from __future__ import annotations

import argparse
from bisect import bisect_left
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
import gzip
from hashlib import sha256
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess

try:
    from scripts import validate_afdb as base
    from scripts.develop_af_entropy import predict, candidate_episodes, MODELS
except ModuleNotFoundError:
    import validate_afdb as base
    from develop_af_entropy import predict, candidate_episodes, MODELS

ROOT = base.ROOT
ORIGIN = 'https://physionet.org/files/ltafdb/1.0.0/'
RHYTHMS = ('N', 'SVTA', 'VT', 'AFIB', 'B', 'T', 'IVR', 'AB', 'SBR')
BEATS = {'N': 'N', 'A': 'S', 'V': 'V', 'Q': 'X'}
# Observed NOTE payloads, not QRS or rhythm labels. Do not infer semantics.
OPAQUE_NOTES = {'\x01 Aux', 'M', 'MB', 'PSE'}
FREEZE = ROOT/'docs/validation/af-entropy-20260929/development-v1'
SOURCES = ['scripts/validate_ltafdb.py', 'docs/ltafdb-validation-protocol.md', 'tests/test_ltafdb_validation.py']


def records(folder):
    names = (folder/'RECORDS').read_text().split()
    if len(names) != 84 or len(set(names)) != 84 or any(not re.fullmatch(r'\d{2,3}', n) for n in names):
        raise ValueError('Expected all 84 unique LTAFDB records')
    return names


def inputs(folder):
    return ['RECORDS', 'tables.shtml'] + [r+'.'+ext for r in records(folder) for ext in ('hea', 'qrs', 'atr')]


def fetch(folder):
    import requests
    folder.mkdir(parents=True, exist_ok=True)
    def get(name, expected=None):
        target = folder/name
        if expected and target.exists() and base.digest(target) == expected:
            return
        for attempt in range(3):
            try:
                response = requests.get(ORIGIN+name, timeout=(15, 45)); response.raise_for_status()
                if expected and sha256(response.content).hexdigest() != expected:
                    raise ValueError('Checksum mismatch: '+name)
                part = target.with_suffix(target.suffix+'.part'); part.write_bytes(response.content); part.replace(target)
                return
            except (requests.RequestException, ValueError):
                if attempt == 2:
                    raise
    get('SHA256SUMS.txt')
    sums = base.catalog(folder); get('RECORDS', sums['RECORDS'])
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda name: get(name, sums[name]), inputs(folder)))
    print(f'Verified {len(inputs(folder))} public input files', flush=True)


def clean_aux(value):
    return value.strip().rstrip('\x00').strip()


def checked_annotations(samples, symbols, labels, length, fs):
    if fs != 128 or length <= 0 or not len(samples) == len(symbols) == len(labels):
        raise ValueError('Expected valid 128 Hz annotation input')
    previous = -1
    for s, symbol, label in zip(samples, symbols, labels):
        sample = int(s)
        label = clean_aux(label)
        # Record 30 has a trailing opaque Aux NOTE beyond the signal. It is
        # counted and ignored, never allowed to extend the observation period.
        trailing_aux = symbol == '"' and label == '\x01 Aux'
        if sample != s or sample < 0 or sample < previous or (sample > length and not trailing_aux):
            raise ValueError('Annotation time out of order or record bounds')
        previous = sample
        yield sample, symbol, label


def adapt(samples, symbols, labels, length, fs, mode):
    if mode not in ('qrs', 'atr'):
        raise ValueError('Unsupported input mode')
    beats, barriers, ignored = [], [], Counter()
    for sample, symbol, label in checked_annotations(samples, symbols, labels, length, fs):
        if mode == 'qrs':
            if label or symbol not in ('N', '|', 'T'):
                raise ValueError(f'Unsupported qrs annotation: {symbol!r} {label!r}')
            if symbol == 'N':
                beats.append((sample, 'N'))
            elif symbol == '|':
                barriers.append(sample)
            else:
                ignored['manual_termination_T'] += 1
        elif symbol in BEATS:
            if label:
                raise ValueError('Unexpected aux on typed QRS')
            beats.append((sample, BEATS[symbol]))
        elif symbol == '"' and label == 'MISSB':
            barriers.append(sample)
        elif symbol == '"' and label in OPAQUE_NOTES:
            ignored['opaque_note:'+label] += 1
            if sample > length:
                ignored['out_of_bounds_aux_note'] += 1
        elif symbol == '+' and label in {'('+r for r in RHYTHMS}:
            ignored['rhythm_change'] += 1
        else:
            raise ValueError(f'Unsupported atr annotation: {symbol!r} {label!r}')
    rows, previous_source, previous_mapped, error = [], None, None, 0
    for source, code in beats:
        position = (source*25+8)//16
        if source >= length or (previous_source is not None and (source <= previous_source or position <= previous_mapped)):
            raise ValueError('Duplicate, reversed, terminal or collapsed QRS')
        error = max(error, abs(position*16-source*25))
        valid = False
        if previous_source is not None:
            k = bisect_left(barriers, previous_source)
            valid = k == len(barriers) or barriers[k] > source
        rows.append(dict(sample_index=position, time_s=position/200,
                         rr_ms=0 if previous_mapped is None else (position-previous_mapped)*5,
                         class_code=code, rr_valid=valid))
        previous_source, previous_mapped = source, position
    return rows, dict(beats=len(rows), barriers=len(barriers), ignored=dict(ignored),
                      max_timestamp_error_ms=error*.3125,
                      source_symbol_counts=dict(Counter(symbols)))


def reference_segments(samples, symbols, labels, length, fs):
    segments, current, start = [], 'unknown', 0
    for sample, symbol, label in checked_annotations(samples, symbols, labels, length, fs):
        if symbol != '+':
            continue
        if label not in {'('+r for r in RHYTHMS}:
            raise ValueError('Unknown reference rhythm: '+label)
        if sample > start:
            segments.append(dict(start_s=start/fs, end_s=sample/fs, rhythm=current))
        current, start = label[1:], sample
    if start < length:
        segments.append(dict(start_s=start/fs, end_s=length/fs, rhythm=current))
    return segments


def score(windows, segments, duration):
    """Linear half-open time intersection; preserve every non-AF stratum."""
    seconds = dict.fromkeys(base.TIME_KEYS, 0.)
    by_rhythm = {r: dict(candidate_s=0., negative_s=0., withheld_s=0.) for r in RHYTHMS}
    for sequence in (windows, segments):
        end = 0.
        for item in sequence:
            if item['start_s'] != end or not end < item['end_s'] <= duration:
                raise ValueError('Partition gap, overlap or invalid boundary')
            end = item['end_s']
        if end != duration:
            raise ValueError('Incomplete time partition')
    j = 0
    for w in windows:
        while j < len(segments) and segments[j]['end_s'] <= w['start_s']:
            j += 1
        k = j
        while k < len(segments) and segments[k]['start_s'] < w['end_s']:
            s = segments[k]; k += 1
            overlap = min(s['end_s'], w['end_s'])-max(s['start_s'], w['start_s'])
            rhythm = s['rhythm']
            if rhythm == 'unknown':
                seconds['unknown_s'] += overlap
                continue
            state = 'withheld' if not w['evaluated'] else 'candidate' if w['candidate'] else 'negative'
            by_rhythm[rhythm][state+'_s'] += overlap
            key = ('withheld_af_s' if rhythm == 'AFIB' else 'withheld_non_af_s') if state == 'withheld' else (
                'tp_s' if rhythm == 'AFIB' else 'fp_s') if state == 'candidate' else ('fn_s' if rhythm == 'AFIB' else 'tn_s')
            seconds[key] += overlap
    return dict(seconds=seconds, metrics=base.metrics(seconds), by_rhythm=by_rhythm)


def native_seconds(samples, symbols, labels, length, windows):
    """Independent sample-grid counting, not segment-intersection code."""
    import numpy as np
    reference = np.zeros(length, dtype=np.uint8)
    changes = [(int(s), clean_aux(a)) for s, c, a in zip(samples, symbols, labels) if c == '+']
    for i, (start, rhythm) in enumerate(changes):
        stop = changes[i+1][0] if i+1 < len(changes) else length
        if rhythm not in {'('+r for r in RHYTHMS}:
            raise ValueError('Unknown native reference rhythm')
        reference[start:stop] = 1 if rhythm == '(AFIB' else 2
    prediction = np.zeros(length, dtype=np.uint8)
    covered = np.zeros(length, dtype=bool)
    for w in windows:
        a, b = [round(w[key]*128) for key in ('start_s', 'end_s')]
        if not 0 <= a < b <= length or covered[a:b].any():
            raise ValueError('Invalid native prediction partition')
        covered[a:b] = True
        prediction[a:b] = 0 if not w['evaluated'] else 2 if w['candidate'] else 1
    if not covered.all():
        raise ValueError('Incomplete native output')
    counts = np.bincount(reference*3+prediction, minlength=9)
    return dict(tp_s=float(counts[5])/128, fn_s=float(counts[4])/128,
                fp_s=float(counts[8])/128, tn_s=float(counts[7])/128,
                withheld_af_s=float(counts[3])/128, withheld_non_af_s=float(counts[6])/128,
                unknown_s=float(counts[:3].sum())/128)


def frozen_parameters():
    development = json.loads((FREEZE/'summary.json').read_text())
    for name, expected in development['source_sha256'].items():
        if base.digest(ROOT/name) != expected or base.digest(FREEZE/'snapshot'/name) != expected:
            raise ValueError('Frozen development source drift: '+name)
    thresholds = {name: development['final_development_fit'][name]['threshold'] for name in MODELS}
    if any(value != -1.35 for value in thresholds.values()):
        raise ValueError('Unexpected frozen thresholds')
    return development, thresholds


def summarize(records):
    seconds = {k: sum(r['seconds'][k] for r in records) for k in base.TIME_KEYS}
    macro = {}
    for key in ('conditional_sensitivity', 'conditional_specificity', 'positive_predictive_value', 'all_af_candidate_capture'):
        values = [r['metrics'][key] for r in records if r['metrics'][key] is not None]
        macro[key] = dict(value=sum(values)/len(values) if values else None, records=len(values))
    return dict(records=len(records), seconds=seconds, metrics=base.metrics(seconds), record_macro=macro,
                by_rhythm={r: {k: sum(x['by_rhythm'][r][k] for x in records)
                               for k in ('candidate_s', 'negative_s', 'withheld_s')} for r in RHYTHMS},
                candidate_episodes=sum(r['candidate_episodes'] for r in records), false_positive_hours=seconds['fp_s']/3600)


def schema(folder):
    """Inspect only annotation vocabulary before algorithm execution."""
    import wfdb
    counts = {mode: Counter() for mode in ('qrs', 'atr')}
    for name in records(folder):
        for mode in counts:
            ann = wfdb.rdann(str(folder/name), mode)
            counts[mode].update((s, clean_aux(a)) for s, a in zip(ann.symbol, ann.aux_note))
    return {mode: [dict(symbol=s, aux=a, count=n) for (s, a), n in sorted(c.items())] for mode, c in counts.items()}


def preflight(folder):
    """Validate every input before computing any model outputs."""
    import wfdb
    sums = base.catalog(folder)
    for name in inputs(folder):
        if base.digest(folder/name) != sums[name]:
            raise ValueError('Input hash mismatch: '+name)
    inventory = []
    for name in records(folder):
        header = wfdb.rdheader(str(folder/name))
        ref = wfdb.rdann(str(folder/name), 'atr')
        try:
            reference_segments(ref.sample, ref.symbol, ref.aux_note, header.sig_len, header.fs)
        except ValueError as error:
            raise ValueError(f'{name} reference: {error}') from error
        for mode in ('qrs', 'atr'):
            ann = ref if mode == 'atr' else wfdb.rdann(str(folder/name), mode)
            try:
                _, metadata = adapt(ann.sample, ann.symbol, ann.aux_note, header.sig_len, header.fs, mode)
            except ValueError as error:
                raise ValueError(f'{name} {mode}: {error}') from error
            inventory.append(dict(record=name, input=mode, duration_s=header.sig_len/header.fs, **metadata))
    return inventory


def evaluate(folder, output):
    import numpy as np
    import wfdb
    development, thresholds = frozen_parameters()
    sums = base.catalog(folder)
    for name in inputs(folder):
        if base.digest(folder/name) != sums[name]:
            raise ValueError('Input hash mismatch: '+name)
    source_names = list(dict.fromkeys(list(development['source_sha256'])+SOURCES))
    before = {name: base.digest(ROOT/name) for name in source_names}
    input_hashes = {name: base.digest(folder/name) for name in ['SHA256SUMS.txt']+inputs(folder)}
    output.mkdir(parents=True, exist_ok=False)
    results, inventory, comparisons, max_delta = [], [], 0, 0.
    with gzip.open(output/'features.csv.gz', 'wt', newline='') as features_file, gzip.open(output/'predictions.csv.gz', 'wt', newline='') as predictions_file:
        feature_writer = prediction_writer = None
        for name in records(folder):
            header = wfdb.rdheader(str(folder/name))
            if header.fs != 128 or header.sig_len <= 0:
                raise ValueError('Unsupported header: '+name)
            reference = wfdb.rdann(str(folder/name), 'atr')
            segments = reference_segments(reference.sample, reference.symbol, reference.aux_note, header.sig_len, header.fs)
            duration = header.sig_len/header.fs
            for mode in ('qrs', 'atr'):
                ann = wfdb.rdann(str(folder/name), mode)
                rows, metadata = adapt(ann.sample, ann.symbol, ann.aux_note, header.sig_len, header.fs, mode)
                inventory.append(dict(record=name, input=mode, duration_s=duration, **metadata))
                run = subprocess.run(['node', 'scripts/af_entropy_features.cjs'], cwd=ROOT,
                                     input=json.dumps(dict(rows=rows, duration=duration)),
                                     text=True, capture_output=True, check=True, timeout=120)
                windows = json.loads(run.stdout)
                for w in windows:
                    row = dict(record=name, input=mode, **w)
                    if feature_writer is None:
                        feature_writer = csv.DictWriter(features_file, fieldnames=list(row)); feature_writer.writeheader()
                    feature_writer.writerow(row)
                for model in ('baseline', *MODELS):
                    threshold = None if model == 'baseline' else thresholds[model]
                    predicted = windows if model == 'baseline' else predict(windows, threshold, model)
                    measured = score(predicted, segments, duration)
                    native = native_seconds(reference.sample, reference.symbol, reference.aux_note, header.sig_len, predicted)
                    for key, value in native.items():
                        delta = abs(value-measured['seconds'][key]); max_delta = max(max_delta, delta); comparisons += 1
                        if delta > 1e-6:
                            raise ValueError(f'Native-grid audit failed: {name} {mode} {model} {key}')
                    measured.update(record=name, input=mode, model=model, threshold=threshold,
                                    candidate_episodes=candidate_episodes(predicted),
                                    quality_reasons=dict(Counter(w['reason'] for w in predicted if w['reason'])))
                    results.append(measured)
                    for w in predicted:
                        row = dict(record=name, input=mode, model=model, threshold=threshold,
                                   **{k: w[k] for k in ('start_s', 'end_s', 'evaluated', 'candidate', 'reason')})
                        if prediction_writer is None:
                            prediction_writer = csv.DictWriter(predictions_file, fieldnames=list(row)); prediction_writer.writeheader()
                        prediction_writer.writerow(row)
                print(f'Completed {name} {mode}: {len(windows)} windows; native-grid audit passed', flush=True)
    if len(results) != 84*2*3:
        raise ValueError('Incomplete external evaluation')
    if before != {name: base.digest(ROOT/name) for name in source_names}:
        raise ValueError('Evaluation source changed')
    if input_hashes != {name: base.digest(folder/name) for name in input_hashes}:
        raise ValueError('Evaluation inputs changed')
    summary = dict(protocol='ltafdb-frozen-rr-v1', completed_at=datetime.now(timezone.utc).isoformat(),
                   interpretation='External RR-only evaluation, automatic and reference QRS separately; not clinical validation',
                   thresholds=thresholds, development_summary_sha256=base.digest(FREEZE/'summary.json'),
                   groups={mode: {model: summarize([r for r in results if r['input'] == mode and r['model'] == model])
                                  for model in ('baseline', *MODELS)} for mode in ('qrs', 'atr')},
                   native_audit=dict(comparisons=comparisons, max_abs_difference_s=max_delta, errors=[]),
                   source_sha256=before, input_sha256=input_hashes,
                   runtime=dict(python=platform.python_version(), numpy=np.__version__, wfdb=wfdb.__version__,
                                node=subprocess.check_output(['node', '--version'], text=True).strip()))
    for filename, value in [('summary.json', summary), ('records.json', results), ('inventory.json', inventory)]:
        (output/filename).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    for name in source_names:
        target = output/'snapshot'/name; target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(ROOT/name, target)
    shutil.copy2(FREEZE/'summary.json', output/'development-summary.json')
    print('External evaluation complete:', output, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--fetch', action='store_true')
    parser.add_argument('--schema-only', action='store_true')
    parser.add_argument('--preflight-only', action='store_true')
    args = parser.parse_args()
    if args.fetch:
        fetch(args.data)
    if args.preflight_only:
        print(json.dumps(preflight(args.data), indent=2))
    elif args.schema_only:
        print(json.dumps(schema(args.data), indent=2))
    elif args.output:
        evaluate(args.data, args.output)
    elif not args.fetch:
        parser.error('--output, --fetch, --preflight-only or --schema-only required')
