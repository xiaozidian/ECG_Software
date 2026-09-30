#!/usr/bin/env python3
"""Native-grid audit and baseline replay check for the offline entropy experiment."""
import argparse
import csv
from collections import defaultdict
import json
from pathlib import Path

try:
    from scripts.audit_afdb_scoring import native_seconds
    from scripts.validate_afdb import digest
except ModuleNotFoundError:
    from audit_afdb_scoring import native_seconds
    from validate_afdb import digest


def audit(data, results, baseline):
    import wfdb
    measured = json.loads((results/'records.json').read_text())
    original = {(r['record'], r['annotator']): r for r in json.loads((baseline/'records.json').read_text())}
    grouped = defaultdict(list)
    with (results/'predictions.csv').open() as stream:
        for row in csv.DictReader(stream):
            grouped[(row['record'], row['annotator'], row['model'])].append(row)
    expected = {(r['record'], r['annotator'], r['model']) for r in measured}
    if len(expected) != len(measured) or set(grouped) != expected:
        raise ValueError('Unexpected/duplicate record-model groups')
    differences, max_delta, baseline_runs = [], 0., 0
    for r in measured:
        name = r['record']; header = wfdb.rdheader(str(data/name)); ann = wfdb.rdann(str(data/name), 'atr')
        if header.fs != 250:
            raise ValueError('Expected native 250 Hz')
        native = native_seconds(header.sig_len, ann.sample, ann.aux_note,
                                grouped[(name, r['annotator'], r['model'])])
        for metric, value in native.items():
            delta = abs(value-r['seconds'][metric]); max_delta = max(max_delta, delta)
            if delta > 1e-6:
                differences.append(dict(record=name, annotator=r['annotator'], model=r['model'],
                                        metric=metric, delta_s=delta))
        if r['model'] == 'baseline':
            old = original[(name, r['annotator'])]
            for key in ('seconds', 'metrics', 'by_rhythm', 'candidate_episodes'):
                if old[key] != r[key]:
                    raise ValueError(f'Baseline changed: {name} {r["annotator"]} {key}')
            baseline_runs += 1
    if baseline_runs != len(original):
        raise ValueError('Missing baseline comparisons')
    return dict(method='native 250 Hz vectors; baseline byte-value equality',
                record_model_runs=len(measured), metric_comparisons=len(measured)*7,
                baseline_runs_matched=baseline_runs, max_abs_difference_s=max_delta, errors=differences,
                auditor_sha256=digest(Path(__file__)),
                native_auditor_sha256=digest(Path(__file__).with_name('audit_afdb_scoring.py')),
                inputs_sha256={str(p): digest(p) for p in [results/'records.json', results/'predictions.csv', baseline/'records.json']})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('data', 'results', 'baseline', 'output'):
        parser.add_argument('--'+name, required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.data, args.results, args.baseline)
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(result, indent=2))
    raise SystemExit(bool(result['errors']))
