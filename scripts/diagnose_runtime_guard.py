"""Bounded, read-only source probe; all clinical workspace writes are temporary.

Output contains status/timing and program-module metadata only, never case IDs,
source paths, waveform values, report text or patient source hashes. It does not
connect to, restart or write the running workstation's database.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import logging
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app
from ecg_core.analysis_provenance import LOGGER


class ChangeCapture(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.changes = []

    def emit(self, record):
        message = record.getMessage()
        if record.name == LOGGER.name and message.startswith('analysis_runtime_changed '):
            self.changes.append(json.loads(message.split(' ', 1)[1]))


def probe(app, rounds=2):
    if not isinstance(rounds, int) or isinstance(rounds, bool) or not 1 <= rounds <= 10:
        raise ValueError('rounds must be an integer between 1 and 10')
    capture = ChangeCapture()
    LOGGER.addHandler(capture)
    try:
        client = app.test_client()
        listing = client.get('/api/cases')
        if listing.status_code != 200:
            raise RuntimeError('病例列表读取失败；诊断未执行，不记录响应正文。')
        items = listing.json['items']
        requests = []
        for turn in range(rounds):
            for ordinal, item in enumerate(items, 1):
                endpoint = '/api/cases/' + item['case_id'] + '/advanced-analysis'
                for kind, options, expected in [('valid', {'duration_s': 60}, 200),
                                                ('invalid', {'start_s': -1}, 400)]:
                    start = time.perf_counter()
                    response = client.post(endpoint, json={'options': options})
                    requests.append({'round': turn + 1, 'case_ordinal': ordinal,
                        'kind': kind, 'expected_status': expected, 'status': response.status_code,
                        'seconds': round(time.perf_counter() - start, 6)})
        return {'schema': 1, 'source_policy': 'read-only; isolated temporary clinical database',
            'case_count': len(items), 'rounds': rounds, 'request_count': len(requests),
            'status_counts': dict(Counter(str(r['status']) for r in requests)),
            'unexpected_count': sum(r['status'] != r['expected_status'] for r in requests),
            'runtime_changes': capture.changes, 'requests': requests,
            'engine': app.extensions['analysis_runtime'].manifest}
    finally:
        LOGGER.removeHandler(capture)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--data-root', type=Path)
    parser.add_argument('--rounds', type=int, choices=range(1, 11), default=2)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('输出已存在；请使用新的文件名，不覆盖既有诊断证据。')
    with tempfile.TemporaryDirectory(prefix='ecg-runtime-probe-') as folder:
        app = create_app(data_root=args.data_root, db_path=Path(folder) / 'probe.db', testing=True)
        result = probe(app, args.rounds)
        with args.output.open('x', encoding='utf-8') as output:
            json.dump(result, output, ensure_ascii=False, indent=2)
            output.write('\n')
    print(json.dumps({k: result[k] for k in ('case_count', 'request_count', 'status_counts', 'unexpected_count')},
                     ensure_ascii=False))
    if result['unexpected_count'] or not result['request_count']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
