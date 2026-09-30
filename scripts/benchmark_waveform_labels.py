#!/usr/bin/env python3
"""Compare waveform-label reuse using generated inputs and isolated databases.

Flask test-client timing only: not browser latency or clinical performance.
Raw samples are still read on every request. No patient data is opened.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app as server
from scripts.benchmark_clinical_queries import generate


def bench(root, db, cid, beats, enabled, parallel):
    application = server.create_app(data_root=root, db_path=db, testing=True)
    cache = application.extensions['waveform_beat_cache']
    if not enabled:
        # Only disable reuse: all source/revision checks are left intact.
        cache.project = lambda key, build, project: project(build())
    original = server.EditedRecords; lock = threading.Lock(); builds = 0
    def counted(*args, **kwargs):
        nonlocal builds
        with lock:
            builds += 1
        return original(*args, **kwargs)
    server.EditedRecords = counted
    def read(n):
        start = n * beats * .8 / 10
        ranges = [dict(start=start + i * 2.4, end=start + i * 2.4 + 2.4) for i in range(24)]
        began = time.perf_counter()
        with application.test_client() as client:
            response = client.post(f'/api/cases/{cid}/event-waveforms?analysis=edited',
                json=dict(ranges=ranges, leads=['II', 'V1', 'V5'], max_points=1200))
            payload = response.get_json()
        elapsed = time.perf_counter() - began
        if response.status_code != 200:
            raise RuntimeError(f'Synthetic waveform request failed: {response.status_code}, {payload}')
        return dict(query=n, seconds=round(elapsed, 6), bytes=len(response.data),
                    result_sha256=sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest())
    try:
        if parallel:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(read, range(8)))
        else:
            results = list(map(read, range(8)))
    finally:
        server.EditedRecords = original
    times = [r['seconds'] for r in results]
    return dict(cache_enabled=enabled, parallel=parallel, requests=len(results),
        feed_builds=builds, first_seconds=times[0], median_seconds=statistics.median(times),
        warm_median_seconds=statistics.median(times[1:]) if not parallel else None,
        max_seconds=max(times), retention=cache.retention(), results=results)


def run(output, beats):
    if output.exists():
        raise ValueError('Refusing to overwrite previous benchmark evidence')
    with tempfile.TemporaryDirectory(prefix='ecg-wave-label-bench-') as location:
        folder = Path(location); root = folder / 'synthetic'; cid = generate(root, beats)
        profiles = [bench(root, folder / f'work-{enabled}-{parallel}.db', cid, beats, enabled, parallel)
                    for parallel in (False, True) for enabled in (False, True)]
    equal = all([r['result_sha256'] for r in profiles[i]['results']] ==
                [r['result_sha256'] for r in profiles[i + 1]['results']] for i in (0, 2))
    report = dict(scope='synthetic Flask batch-waveform handler; no browser/network or clinical accuracy',
        beats=beats, python=platform.python_version(), platform=platform.system(), results_equal=equal,
        source_sha256={p: sha256((ROOT / p).read_bytes()).hexdigest() for p in (
            'app.py', 'ecg_core/beat_editor.py', 'ecg_core/waveform.py',
            'ecg_core/clinical_query_cache.py', 'scripts/benchmark_waveform_labels.py',
            'scripts/benchmark_clinical_queries.py')}, profiles=profiles)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({**{k: v for k, v in report.items() if k not in ('source_sha256', 'profiles')},
        'profiles': [{k: v for k, v in p.items() if k != 'results'} for p in profiles]}, ensure_ascii=False), flush=True)
    if not equal:
        raise AssertionError('Reuse changed a waveform or beat-label response')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--beats', type=int, default=100_000)
    args = parser.parse_args()
    if not 500 <= args.beats <= 200_000:
        parser.error('--beats must be 500–200000')
    run(args.output, args.beats)
