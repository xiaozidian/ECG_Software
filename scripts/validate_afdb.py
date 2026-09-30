#!/usr/bin/env python3
"""Frozen AFDB RR-screen baseline; no private input or clinical pass claim."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = 'https://physionet.org/files/afdb/1.0.0/'
RHYTHMS = {'(AFIB': 'AFIB', '(AFL': 'AFL', '(J': 'J', '(N': 'N'}
SOURCES = ['scripts/validate_afdb.py', 'docs/afdb-validation-protocol.md',
           'static/js/overview-engine.js', 'static/js/rr-quality.js',
           'static/js/beat-engine.js']
TIME_KEYS = ['tp_s', 'fn_s', 'fp_s', 'tn_s', 'withheld_af_s', 'withheld_non_af_s', 'unknown_s']


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def catalog(folder):
    result = {}
    for line in (folder/'SHA256SUMS.txt').read_text().splitlines():
        value, name = line.split(maxsplit=1)
        result[name.removeprefix('*').removeprefix('./')] = value
    return result


def names(folder):
    records = (folder/'RECORDS').read_text().split()
    if len(records) != 25 or len(set(records)) != 25 or any(not re.fullmatch(r'\d{5}', r) for r in records):
        raise ValueError('Expected all 25 unique AFDB records')
    return records


def inputs(folder):
    sums = catalog(folder)
    result = ['RECORDS', 'notes.txt']
    for record in names(folder):
        result += [record+'.'+ext for ext in ('hea', 'atr', 'qrs')]
        if record+'.qrsc' in sums:
            result.append(record+'.qrsc')
    return result


def fetch(folder):
    import requests
    folder.mkdir(parents=True, exist_ok=True)

    def get(name, expected=None):
        path = folder/name
        if expected and path.exists() and digest(path) == expected:
            return
        for attempt in range(3):
            try:
                response = requests.get(ORIGIN+name, timeout=(15, 45))
                response.raise_for_status()
                if expected and sha256(response.content).hexdigest() != expected:
                    raise ValueError('Checksum mismatch: '+name)
                part = path.with_name(name+'.part')
                part.write_bytes(response.content)
                part.replace(path)
                return
            except (requests.RequestException, ValueError):
                if attempt == 2:
                    raise
    get('SHA256SUMS.txt')
    sums = catalog(folder)
    get('RECORDS', sums['RECORDS'])
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda name: get(name, sums[name]), inputs(folder)))
    print(f'Checked {len(inputs(folder))} public input files', flush=True)


def adapt(samples, symbols, length, fs):
    if fs != 250 or len(samples) != len(symbols) or set(symbols)-{'N'}:
        raise ValueError('Expected 250 Hz AFDB QRS-only N markers')
    rows, previous, error = [], None, 0
    for sample in samples:
        source = int(sample)
        if not 0 <= source < length:
            raise ValueError('QRS outside record')
        position = (source*4+2)//5
        if previous is not None and position <= previous:
            raise ValueError('Duplicate or reversed mapped QRS')
        error = max(error, abs(position*5-source*4))
        rows.append(dict(sample_index=position, time_s=position/200,
                         rr_ms=0 if previous is None else (position-previous)*5, class_code='N'))
        previous = position
    return rows, error


def rhythm_segments(samples, labels, length, fs):
    if len(samples) != len(labels) or fs != 250 or length <= 0:
        raise ValueError('Invalid reference input')
    segments, previous, current = [], 0, 'unknown'
    for sample, label in zip(samples, labels):
        sample = int(sample)
        label = label.strip().rstrip('\x00')
        if label not in RHYTHMS or not previous <= sample < length:
            raise ValueError(f'Unsupported reference label or position: {sample} {label!r}')
        if sample > previous:
            segments.append(dict(start_s=previous/fs, end_s=sample/fs, rhythm=current))
        current, previous = RHYTHMS[label], sample
    if previous < length:
        segments.append(dict(start_s=previous/fs, end_s=length/fs, rhythm=current))
    return segments


def ratio(a, b):
    return a/b if b else None


def metrics(seconds):
    tp, fn, fp, tn, wa, wn, unknown = [seconds[k] for k in TIME_KEYS]
    assessed, af, nonaf = tp+fn+fp+tn, tp+fn+wa, fp+tn+wn
    known = af+nonaf
    return dict(known_reference_s=known, total_s=known+unknown,
                evaluated_coverage=ratio(assessed, known), af_evaluated_coverage=ratio(tp+fn, af),
                conditional_sensitivity=ratio(tp, tp+fn), conditional_specificity=ratio(tn, tn+fp),
                positive_predictive_value=ratio(tp, tp+fp), all_af_candidate_capture=ratio(tp, af),
                reference_af_burden=ratio(af, known), candidate_burden=ratio(tp+fp, known),
                burden_error=ratio(tp+fp-af, known))


def score(windows, segments):
    seconds = dict.fromkeys(TIME_KEYS, 0.)
    by_rhythm = {r: dict(candidate_s=0., negative_s=0., withheld_s=0.) for r in RHYTHMS.values()}
    pure = Counter()
    for w in windows:
        labels = set()
        for ref in segments:
            overlap = max(0., min(w['end_s'], ref['end_s'])-max(w['start_s'], ref['start_s']))
            if not overlap:
                continue
            r = ref['rhythm'];labels.add(r)
            if r == 'unknown':
                seconds['unknown_s'] += overlap
                continue
            prediction = 'withheld' if not w['evaluated'] else 'candidate' if w['candidate'] else 'negative'
            by_rhythm[r][prediction+'_s'] += overlap
            if prediction == 'withheld':
                key = 'withheld_af_s' if r == 'AFIB' else 'withheld_non_af_s'
            elif prediction == 'candidate':
                key = 'tp_s' if r == 'AFIB' else 'fp_s'
            else:
                key = 'fn_s' if r == 'AFIB' else 'tn_s'
            seconds[key] += overlap
        if len(labels) == 1 and 'unknown' not in labels and w['end_s']-w['start_s'] == 30:
            outcome = 'withheld' if not w['evaluated'] else 'candidate' if w['candidate'] else 'negative'
            pure[next(iter(labels))+':'+outcome] += 1
        else:
            pure['mixed_unknown_or_partial'] += 1
    return dict(seconds=seconds, metrics=metrics(seconds), by_rhythm=by_rhythm, windows=dict(pure))


def screen(rows, duration):
    code = "const fs=require('fs'),E=require('./static/js/overview-engine.js'),v=JSON.parse(fs.readFileSync(0,'utf8'));process.stdout.write(JSON.stringify(E.screenAFResult(v.rows,v.duration)));"
    result = subprocess.run(['node', '-e', code], cwd=ROOT, input=json.dumps(dict(rows=rows,duration=duration)),
                            capture_output=True, text=True, check=True, timeout=120)
    return json.loads(result.stdout)


def aggregate(records):
    seconds = {k: sum(r['seconds'][k] for r in records) for k in TIME_KEYS}
    macro = {}
    for key in ('conditional_sensitivity', 'conditional_specificity', 'positive_predictive_value', 'all_af_candidate_capture'):
        values = [r['metrics'][key] for r in records if r['metrics'][key] is not None]
        macro[key] = dict(value=sum(values)/len(values) if values else None, records=len(values))
    by_rhythm = {rh: {k: sum(r['by_rhythm'][rh][k] for r in records) for k in ('candidate_s','negative_s','withheld_s')} for rh in RHYTHMS.values()}
    return dict(records=len(records),seconds=seconds,metrics=metrics(seconds),record_macro=macro,by_rhythm=by_rhythm)


def evaluate(folder, output):
    import wfdb
    import numpy
    sums = catalog(folder)
    for name in inputs(folder):
        if digest(folder/name) != sums[name]:
            raise ValueError('Input checksum mismatch: '+name)
    output.mkdir(parents=True, exist_ok=False)
    before = {name: digest(ROOT/name) for name in SOURCES}
    results, excluded, all_windows = [], [], []
    notes = (folder/'notes.txt').read_text()
    for record in names(folder):
        header = wfdb.rdheader(str(folder/record))
        if header.fs != 250:
            raise ValueError('Unexpected frequency')
        if not header.sig_len:
            excluded.append(dict(record=record,reason='header_duration_zero',duration_inferred=False))
            continue
        reference = wfdb.rdann(str(folder/record),'atr')
        segments = rhythm_segments(reference.sample,reference.aux_note,header.sig_len,header.fs)
        for annotator in ('qrs','qrsc'):
            if record+'.'+annotator not in sums:
                continue
            beats = wfdb.rdann(str(folder/record),annotator)
            rows, error = adapt(beats.sample,beats.symbol,header.sig_len,header.fs)
            duration = header.sig_len/header.fs
            result = screen(rows,duration)
            measured = score(result['windows'],segments)
            if abs(sum(measured['seconds'].values())-duration) > 1e-6:
                raise ValueError('Reference/window time partition is incomplete')
            measured.update(record=record,annotator=annotator,duration_s=duration,beats=len(rows),
                            max_timestamp_error_ms=error,evaluated_windows=result['evaluated_windows'],
                            skipped_windows=result['skipped_windows'],candidate_episodes=len(result['episodes']),
                            quality_reasons=dict(Counter(w['reason'] for w in result['windows'] if w['reason'])),
                            source_note='; '.join(line for line in notes.splitlines() if line.startswith(record)))
            results.append(measured)
            for window in result['windows']:
                all_windows.append(dict(record=record,annotator=annotator,**window))
            print(record,annotator,json.dumps(measured['metrics'],ensure_ascii=False),flush=True)
    if {r['record'] for r in excluded} != {'00735','03665'}:
        raise ValueError('Unexpected exclusions')
    primary = [r for r in results if r['annotator']=='qrs']
    corrected = [r for r in results if r['annotator']=='qrsc']
    if len(primary) != 23 or {r['record'] for r in corrected} != {'05091','07859'}:
        raise ValueError('Unexpected evaluation coverage')
    after = {name: digest(ROOT/name) for name in SOURCES}
    if before != after:
        raise ValueError('Algorithm or validation code changed during evaluation')
    paired = [r for r in primary if r['record'] in {c['record'] for c in corrected}]
    summary = dict(protocol='afdb-rr-baseline-v1',completed_at=datetime.now(timezone.utc).isoformat(),
                   interpretation='RR-only baseline; not clinical validation or QRS/type detector validation',
                   primary=aggregate(primary),corrected_qrsc=aggregate(corrected),paired_automatic_qrs=aggregate(paired),
                   excluded=excluded,source_sha256=before,
                   input_sha256={name:digest(folder/name) for name in ['SHA256SUMS.txt']+inputs(folder)},
                   runtime=dict(python=platform.python_version(),wfdb=wfdb.__version__,numpy=numpy.__version__,
                                node=subprocess.check_output(['node','--version'],text=True).strip()))
    for filename, value in [('records.json',results),('summary.json',summary)]:
        (output/filename).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    with (output/'windows.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(all_windows[0]));writer.writeheader();writer.writerows(all_windows)
    for name in SOURCES:
        target=output/'snapshot'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,target)
    print('Results:',output,flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--fetch',action='store_true')
    args=parser.parse_args()
    if args.fetch:
        fetch(args.data)
    evaluate(args.data,args.output)
