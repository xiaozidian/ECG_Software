#!/usr/bin/env python3
"""Public reference-label counting audit, NOT detector/diagnostic validation.

See docs/mitdb-counting-protocol.md. No patient data is read or transmitted.
WFDB and requests are needed only in the separate validation environment.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
from itertools import groupby
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ecg_core.clinical_analysis import build_index, query_index
from ecg_core.report_layout import report_statistics

ORIGIN = 'https://physionet.org/files/mitdb/1.0.0/'
TABLE_URL = 'https://physionet.org/physiobank/database/html/mitdbdir/tables.htm'
MAPPING = dict(N='N', L='BL', R='BR', A='S', a='Z', J='J', S='S', V='V',
               F='F', e='W', j='G', E='E', f='PF', Q='OTHER', x='O')
MAPPING.update({'/': 'P', '|': 'X', '!': 'X'})
IGNORED = {'+', '~', '[', ']', '"', 's', 'T', '*', '=', '@', 'p', 't', 'u', '(', ')', '`', '^'}
CYCLES = {'bigeminy': 'NS', 'nnp': 'NNS', 'npp': 'NSS', 'quadrigeminy': 'NNNS'}
SETTINGS = dict(nn_min=300, nn_max=2000, pause=2.5, tachy=120, brady=50)
CLOCK = '2000-01-01 23:45:00'


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def catalog(folder):
    sums = {}
    for line in (folder/'SHA256SUMS.txt').read_text().splitlines():
        value, name = line.split(maxsplit=1)
        sums[name.removeprefix('*').removeprefix('./')] = value
    return sums


def record_names(folder):
    records = (folder/'RECORDS').read_text().split()
    if len(records) != 48 or len(set(records)) != 48 or any(not re.fullmatch(r'\d{3}', r) for r in records):
        raise ValueError('Expected all 48 unique MIT-BIH records')
    return records


def fetch(folder):
    import requests
    folder.mkdir(parents=True, exist_ok=True)

    def get(name, expected=None, url=None):
        path = folder/name
        if expected and path.exists() and digest(path) == expected:
            return
        for attempt in range(3):
            try:
                response = requests.get(url or ORIGIN+name, timeout=(15, 45))
                response.raise_for_status()
                data = response.content
                if expected and sha256(data).hexdigest() != expected:
                    raise ValueError(f'Public SHA-256 mismatch: {name}')
                part = path.with_name(name+'.part')
                part.write_bytes(data)
                part.replace(path)
                return
            except (requests.RequestException, ValueError):
                if attempt == 2:
                    raise
    get('SHA256SUMS.txt')
    sums = catalog(folder)
    get('RECORDS', sums['RECORDS'])
    names = [f'{r}.{ext}' for r in record_names(folder) for ext in ('hea', 'atr')]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda name: get(name, sums[name]), names))
    get('historical-tables.html', url=TABLE_URL)
    print(f'Checked {len(names)} public annotation/header files', flush=True)


class HistoricalTable(HTMLParser):
    """Keep first full-record table only; the second count table is five-min truncated."""
    def __init__(self):
        super().__init__()
        self.row = []
        self.cell = None
        self.records = {}

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.row = []
        if tag in ('td', 'th'):
            self.cell = []

    def handle_data(self, value):
        if self.cell is not None:
            self.cell.append(value)

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(''.join(self.cell).strip())
            self.cell = None
        if tag == 'tr' and len(self.row) == 18 and re.fullmatch(r'\d{3}', self.row[0]):
            if self.row[0] not in self.records:
                symbols = ['N', 'L', 'R', 'A', 'a', 'J', 'S', 'V', 'F', '!', 'e', 'j', 'E', '/', 'f', 'x', 'Q']
                self.records[self.row[0]] = dict(zip(symbols, [0 if x == '-' else int(x) for x in self.row[1:]]))


def adapt(samples, symbols, length, fs):
    """Timestamp-only nearest sample conversion; explicit non-QRS/gap handling."""
    if fs != 360 or len(samples) != len(symbols):
        raise ValueError('Unexpected annotation format')
    unknown = set(symbols)-set(MAPPING)-IGNORED
    if unknown:
        raise ValueError(f'Unknown annotation symbols: {sorted(unknown)}')
    rows, markers = [], []
    previous = None
    last_position = -1
    original_long = Counter()
    for n, (source, symbol) in enumerate(zip(samples, symbols)):
        if symbol not in MAPPING:
            continue
        code = MAPPING[symbol]
        position = (int(source)*5+4)//9
        if code != 'O' and position <= last_position:
            raise ValueError('Duplicate/reversed timestamp after 200 Hz conversion')
        if not 0 <= source < length:
            raise ValueError('Annotation outside recording')
        rr = (position-previous[0])*5 if previous and code not in ('O', 'X') else 0
        row = dict(id=f'm:{n}', sample_index=position, class_code=code, name=code,
                   rr_ms=rr, hr=round(60000/rr, 1) if rr else None)
        if code == 'O':
            markers.append(row)
            continue
        last_position = position
        rows.append(row)
        if code == 'X':
            previous = None
        else:
            if previous:
                original_long['over2500'] += int(source)-previous[1] > 900
                original_long['over3000'] += int(source)-previous[1] > 1080
            previous = (position, int(source))
    return SimpleNamespace(beats=rows, markers=markers, duration=length/fs,
                           document={'settings': SETTINGS}), dict(original_long)


def reference_events(codes, code):
    """Independent groupby / regular-expression oracle, not production scanner."""
    result = {}
    cursor = 0
    for value, group in groupby(codes):
        size = len(list(group))
        if value == code:
            kind = 'single' if size == 1 else 'couplet' if size == 2 else 'triplet' if size == 3 else 'run'
            result.setdefault(kind, []).append((cursor, cursor+size))
        cursor += size
    # Non-N/target labels become explicit separators, never disappear.
    text = ''.join(c if c in ('N', code) else '|' for c in codes)
    for kind, generic in CYCLES.items():
        cycle = generic.replace('S', code)
        rotations = [cycle[i:]+cycle[:i] for i in range(len(cycle))]
        expression = re.compile(r'(?P<unit>'+ '|'.join(rotations) + r')(?P=unit)+')
        cursor = 0
        spans = []
        while match := expression.search(text, cursor):
            start, end = match.span()
            unit = match['unit']
            while end < len(text) and text[end] == unit[(end-start) % len(unit)]:
                end += 1
            spans.append((start, end))
            cursor = end
        result[kind] = spans
    return result


def audit(feed, browser=True):
    index = build_index(feed)
    index['start_time'] = CLOCK
    stats = report_statistics(index, CLOCK, SETTINGS)
    rows = feed.beats
    codes = [r['class_code'] for r in rows]
    errors = []

    def check(name, actual, expected):
        if actual != expected:
            errors.append(dict(check=name, actual=actual, expected=expected))

    valid = [r for r in rows if r['class_code'] != 'X']
    check('summary.total', stats['summary']['total'], len(valid))
    check('hourly.total', sum(h['total'] for h in stats['hourly']), len(valid))
    for code in ('S', 'V'):
        refs = reference_events(codes, code)
        check(code+'.total', stats['summary'][code]['total'], codes.count(code))
        check(code+'.hourly.total', sum(h[code]['total'] for h in stats['hourly']), codes.count(code))
        for kind, spans in refs.items():
            expected = [(rows[a]['sample_index'], rows[b-1]['sample_index'],
                         [r['sample_index'] for r in rows[a:b] if r['class_code'] == code]) for a, b in spans]
            actual = [e for e in index['events'] if e['category'] == code and e['subtype'] == kind]
            check(code+'.'+kind+'.spans', [(e['start_sample'], e['end_sample'], e['target_samples']) for e in actual], expected)
            query = {'category': code, 'mode': kind, 'limit': 7}
            first = query_index(index, query)
            pages = [e for offset in range(0, first['total'], 7)
                     for e in query_index(index, {**query, 'offset': offset})['items']]
            check(code+'.'+kind+'.pagination', [e['event_id'] for e in pages], [e['event_id'] for e in actual])
            for hour in first['time_bins']:
                lo, hi = hour['start_s'], hour['end_s']
                count = sum(lo <= r[0]/200 < hi for r in expected)
                check(code+'.'+kind+f'.hour.{lo}', hour['count'], count)
                selected = query_index(index, {**query, 'time_start': lo, 'time_end': hi})
                check(code+'.'+kind+f'.filter.{lo}', selected['total'], count)
        for name, kinds in {'single':['single'], 'couplet':['couplet'], 'run':['triplet','run'],
                            'bigeminy':['bigeminy'], 'trigeminy':['nnp','npp']}.items():
            spans = [s for k in kinds for s in refs.get(k, [])]
            check(code+'.report.'+name, stats['summary'][code][name], len(spans))
            for hour in stats['hourly']:
                count = sum(hour['start_s'] <= rows[a]['sample_index']/200 < hour['end_s'] for a, _ in spans)
                check(code+'.report.'+name+f".hour.{hour['start_s']}", hour[code][name], count)
    for name, threshold in [('pause', 2500), ('pause_over3', 3000)]:
        expected = sum(r['rr_ms'] > threshold for r in valid)
        check(name, stats['summary'][name], expected)
        check(name+'.hourly', sum(h[name] for h in stats['hourly']), expected)
    if browser:
        program = "const a=require('./static/js/clinical-analysis.js'),f=JSON.parse(require('fs').readFileSync(0,'utf8'));process.stdout.write(JSON.stringify(a.buildIndex(f)));"
        value = json.loads(subprocess.check_output(['node', '-e', program], input=json.dumps(vars(feed)).encode(), cwd=ROOT))
        check('python_browser_index_equal', value == {k:v for k,v in index.items() if k != 'start_time'}, True)
    return dict(errors=errors, summary=stats['summary'], hourly=stats['hourly'],
                event_counts=dict(Counter(e['category']+':'+e['subtype'] for e in index['events'])))


def run(folder, output):
    import wfdb
    records = record_names(folder)
    sums = catalog(folder)
    names = ['RECORDS']+[f'{r}.{ext}' for r in records for ext in ('hea', 'atr')]
    actual_hashes = {name: digest(folder/name) for name in names}
    if any(actual_hashes[name] != sums[name] for name in names):
        raise ValueError('Public input SHA-256 verification failed')
    historical = HistoricalTable()
    historical.feed((folder/'historical-tables.html').read_text())
    if set(historical.records) != set(records):
        raise ValueError('Could not parse all 48 historical whole-record rows')
    output.mkdir(parents=True, exist_ok=False)
    snapshots = ['ecg_core/clinical_analysis.py', 'ecg_core/report_layout.py', 'ecg_core/rr_quality.py',
                 'static/js/clinical-analysis.js', 'static/js/rr-quality.js', 'static/js/report-engine.js', 'scripts/validate_mitdb_counts.py',
                 'docs/mitdb-counting-protocol.md']
    for name in snapshots:
        target = output/'snapshot'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT/name).read_bytes())
    results = []
    for record in records:
        header = wfdb.rdheader(str(folder/record))
        annotation = wfdb.rdann(str(folder/record), 'atr')
        counts = Counter(annotation.symbol)
        feed, original = adapt(annotation.sample, annotation.symbol, header.sig_len, header.fs)
        value = audit(feed)
        differences = [dict(symbol=s, current=counts[s], historical=n)
                       for s, n in historical.records[record].items() if counts[s] != n]
        value.update(record=record, raw_symbols=dict(counts), original_long_rr=original,
                     historical_differences=differences)
        results.append(value)
        print(f'{record}: {len(value["errors"])} counting mismatches; {len(differences)} historical differences', flush=True)
    report = dict(protocol='mitdb-counting-v1', created_at=datetime.now(timezone.utc).isoformat(),
                  dataset=ORIGIN, scope='reference-label counting, NOT automated ECG diagnostic accuracy',
                  python=platform.python_version(), wfdb=wfdb.__version__, node=subprocess.check_output(['node','--version'], text=True).strip(),
                  records=len(results), records_with_mismatch=sum(bool(r['errors']) for r in results),
                  mismatch_checks=sum(len(r['errors']) for r in results),
                  historical_differences=[dict(record=r['record'], **d) for r in results for d in r['historical_differences']],
                  input_hashes=actual_hashes,
                  historical_table_sha256=digest(folder/'historical-tables.html'),
                  checksum_catalog_sha256=digest(folder/'SHA256SUMS.txt'),
                  algorithm_hashes={name:digest(ROOT/name) for name in snapshots})
    (output/'records.json').write_text(json.dumps(results, ensure_ascii=False, indent=2)+'\n')
    (output/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('records','records_with_mismatch','mismatch_checks')}, ensure_ascii=False))
    return bool(report['mismatch_checks'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--fetch', action='store_true')
    args = parser.parse_args()
    if args.fetch:
        fetch(args.data)
    sys.exit(int(run(args.data, args.output)))
