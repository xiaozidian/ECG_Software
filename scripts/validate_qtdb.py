#!/usr/bin/env python3
"""Offline QT endpoint audit against QTDB q1c/q2c, never patient case imports.

Optional validation-only dependencies: wfdb==4.3.1 and scipy. See the fixed
protocol in docs/qtdb-validation-protocol.md. Exits nonzero on corrupt/missing
inputs; low accuracy is reported, never represented as a clinical pass.
"""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import platform
import re
import shutil
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def split_for(record):
    return 'development' if sha256(record.encode()).digest()[0] % 5 == 0 else 'evaluation'


def reference_beats(samples, symbols, nums):
    """Match audited wave num fields, not closest end or automated annotations."""
    if not len(samples) == len(symbols) == len(nums):
        raise ValueError('Annotation arrays differ in length')
    if any(b < a for a, b in zip(samples, samples[1:])):
        raise ValueError('Annotations are not time ordered')
    normal = [i for i, s in enumerate(symbols) if s == 'N']
    beats = []
    for order, i in enumerate(normal):
        left = normal[order-1]+1 if order else 0
        right = normal[order+1] if order+1 < len(normal) else len(samples)
        starts = [j for j in range(left, i) if symbols[j] == '(' and nums[j] == 1]
        ends = [j for j in range(i+1, right) if symbols[j] == ')' and nums[j] == 2]
        q = int(samples[starts[-1]]) if len(starts) == 1 else None
        t = int(samples[ends[0]]) if len(ends) == 1 else None
        r = int(samples[i])
        if q is not None and not q < r:
            raise ValueError('Q onset does not precede R')
        if t is not None and not r < t:
            raise ValueError('T end does not follow R')
        beats.append(dict(r_sample=r, q_sample=q, t_sample=t))
    return beats


def eligible_reason(beats, i, fs):
    b = beats[i]
    if b['q_sample'] is None or b['t_sample'] is None:
        return 'missing_reference_endpoints'
    if i == 0 or i == len(beats)-1:
        return 'reference_neighbor_unavailable'
    before = (b['r_sample']-beats[i-1]['r_sample'])*1000/fs
    after = (beats[i+1]['r_sample']-b['r_sample'])*1000/fs
    if before > 2000 or after > 2000:
        return 'sparse_reference_gap'
    if min(before, after) < 700 or abs(after/before-1) > .2:
        return 'rr_outside_current_qt_conditions'
    return ''


def metrics(errors):
    x = np.array(errors, dtype=float)
    if not len(x):
        return dict(n=0, bias_ms=None, sd_ms=None, mae_ms=None,
                    median_ae_ms=None, p95_ae_ms=None, over_50ms=0)
    return dict(n=len(x), bias_ms=round(float(x.mean()), 3),
                sd_ms=round(float(x.std(ddof=1)), 3) if len(x)>1 else None,
                mae_ms=round(float(np.abs(x).mean()), 3),
                median_ae_ms=round(float(np.median(np.abs(x))), 3),
                p95_ae_ms=round(float(np.percentile(np.abs(x), 95)), 3),
                over_50ms=int((np.abs(x)>50).sum()))


def summarize(rows):
    attempted = [r for r in rows if r['status'] != 'excluded']
    accepted = [r for r in rows if r['status'] == 'accepted']
    return dict(lead_beat_rows=len(rows), attempted=len(attempted), accepted=len(accepted),
                algorithm_errors=sum(r['status'] == 'error' for r in rows),
                coverage_of_attempts=round(len(accepted)/len(attempted), 6) if attempted else None,
                reasons=dict(Counter(r['reason'] for r in rows if r['status'] != 'accepted')),
                q=metrics([r['q_error_ms'] for r in accepted]),
                t=metrics([r['t_error_ms'] for r in accepted]),
                qt=metrics([r['qt_error_ms'] for r in accepted]))


def load_delineator(path):
    spec = importlib.util.spec_from_file_location('ecg_core.qtdb_validation_snapshot', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.FS != 200:
        raise ValueError('Protocol expects 200 Hz delineation')
    return module.delineate, module.VERSION


def validate(args):
    import scipy
    from scipy.signal import resample_poly
    import wfdb
    data = args.data.resolve()
    records = (data/'RECORDS').read_text().split()
    if len(records) != 105 or len(set(records)) != 105 or any(not re.fullmatch(r'sel\w+', r) for r in records):
        raise ValueError('Expected original QTDB RECORDS list of 105 records')
    expected = {}
    for line in (data/'SHA256SUMS.txt').read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        expected[name.removeprefix('*').removeprefix('./')] = digest
    hashes = {}
    def verify(name):
        digest = sha256((data/name).read_bytes()).hexdigest()
        if expected.get(name) != digest:
            raise ValueError(f'Input checksum mismatch: {name}')
        hashes[name] = digest
    verify('RECORDS')
    selected = [r for r in records if args.split == 'all' or split_for(r) == args.split]
    algorithm_bytes = args.algorithm_source.read_bytes()
    delineate, version = load_delineator(args.algorithm_source)
    rows, record_reports = [], []
    for record in selected:
        for suffix in ('hea', 'dat', args.annotator):
            if suffix == 'q2c' and not (data/f'{record}.{suffix}').exists():
                break
            verify(f'{record}.{suffix}')
        else:
            rec = wfdb.rdrecord(str(data/record), physical=True)
            if rec.fs != 250 or rec.n_sig != 2 or rec.units != ['mV', 'mV']:
                raise ValueError(f'Unexpected signal format in {record}')
            ann = wfdb.rdann(str(data/record), args.annotator)
            beats = reference_beats(ann.sample, ann.symbol, ann.num)
            # Polyphase anti-aliasing, zero-phase alignment, both leads retained.
            signal = resample_poly(rec.p_signal*1000, 4, 5, axis=0)
            record_rows = []
            for i, beat in enumerate(beats):
                reason = eligible_reason(beats, i, rec.fs)
                center = int(round(beat['r_sample']*200/rec.fs))
                if not 50 <= center < len(signal)-130:
                    reason = reason or 'signal_edge'
                for lead in range(2):
                    row = dict(record=record, split=split_for(record), annotator=args.annotator,
                               lead=rec.sig_name[lead], lead_index=lead,
                               r_sample_250=beat['r_sample'], status='excluded', reason=reason)
                    if not reason:
                        rr = (beat['r_sample']-beats[i-1]['r_sample'])*1000/rec.fs
                        y = signal[center-50:center+130, lead].copy()
                        y -= np.median(y[15:25])
                        try:
                            d = delineate(y, rr)
                        except (ValueError, IndexError, FloatingPointError) as error:
                            row.update(status='error', reason=f'algorithm_exception: {type(error).__name__}: {error}')
                            record_rows.append(row)
                            continue
                        row.update(status='accepted' if d['valid'] else 'rejected', reason=d['reason'])
                        if d['valid']:
                            # Absolute times retain sub-sample reference offsets.
                            q_error = center*5+d['q_ms']-beat['q_sample']*4
                            t_error = center*5+d['t_ms']-beat['t_sample']*4
                            row.update(q_error_ms=q_error, t_error_ms=t_error,
                                       qt_error_ms=t_error-q_error,
                                       reference_qt_ms=(beat['t_sample']-beat['q_sample'])*4,
                                       measured_qt_ms=d['qt_ms'])
                    record_rows.append(row)
            rows.extend(record_rows)
            record_reports.append(dict(record=record, split=split_for(record), reference_n=len(beats),
                                       complete_qt=sum(b['q_sample'] is not None and b['t_sample'] is not None for b in beats),
                                       **summarize(record_rows)))
    if args.algorithm_source.read_bytes() != algorithm_bytes:
        raise ValueError('Algorithm changed during the audit; rerun with stable source')
    algorithm_hash = sha256(algorithm_bytes).hexdigest()
    summary = dict(protocol='qtdb-endpoints-v1', clinical_validation=False,
                   created_at=datetime.now(timezone.utc).isoformat(),
                   validation_script_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
                   source_manifest_sha256=sha256((data/'SHA256SUMS.txt').read_bytes()).hexdigest(),
                   source='https://physionet.org/content/qtdb/1.0.0/',
                   annotator=args.annotator, split=args.split,
                   requested_records=len(selected), evaluated_records=len(record_reports),
                   reference_n=sum(r['reference_n'] for r in record_reports),
                   complete_qt=sum(r['complete_qt'] for r in record_reports),
                   algorithm_version=version, algorithm_sha256=algorithm_hash,
                   versions=dict(python=platform.python_version(), numpy=np.__version__,
                                 scipy=scipy.__version__, wfdb=wfdb.__version__),
                   input_sha256=hashes, **summarize(rows), records=record_reports)
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    if any((out/name).exists() for name in ('summary.json', 'beats.csv', 'algorithm_snapshot.py')):
        raise ValueError('Output files exist; choose a new directory to preserve evidence')
    (out/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with (out/'beats.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    shutil.copy2(args.algorithm_source, out/'algorithm_snapshot.py')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('input_sha256', 'records')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--split', choices=['development', 'evaluation', 'all'], default='development')
    p.add_argument('--annotator', choices=['q1c', 'q2c'], default='q1c')
    p.add_argument('--algorithm-source', type=Path, default=ROOT/'ecg_core/advanced_analysis.py')
    validate(p.parse_args())
