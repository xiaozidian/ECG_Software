#!/usr/bin/env python3
"""Reproducible event-list latency comparison using ONLY generated inputs.

No patient data or formal database is opened. Measures Flask handler latency,
not browser rendering, waveform loading, network time or clinical accuracy.
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

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import app as server
from ecg_core.ebi import HEADER_SIZE, RECORD


def generate(root, beats):
    cid='9999999999999999';folder=root/cid
    for name in ('data','DGS','report_image'):
        (folder/name).mkdir(parents=True)
    sample=0;content=[]
    for i in range(beats):
        interval=160+(i%7-3)*2
        sample+=interval
        group=34 if i%997==996 else 3 if i%23==22 else 2 if i%61==60 else 1
        content.append(RECORD.pack(sample,1,group,0,0,0,interval*5))
    (folder/'DGS'/f'{cid}.EBI').write_bytes(bytes(HEADER_SIZE)+b''.join(content))
    # Sparse, explicitly synthetic zero waveform; we benchmark event indexes only.
    with (folder/'data'/f'{cid}.DATA').open('wb') as stream:
        stream.truncate((sample+200)*16)
    (folder/'report_image'/f'{cid}_1.LPS').write_text(
        '<root><PShape>记录时间:2000-01-01 08:00:00</PShape>'
        f'<PShape>总心搏数:{beats}</PShape></root>',encoding='utf-8')
    return cid


def bench(root, db, cid, enabled, concurrent):
    application=server.create_app(data_root=root,db_path=db,testing=True)
    cache=application.extensions['clinical_query_cache']
    if not enabled:
        # Disable reuse only, retaining all existing before/after identity guards.
        cache.project=lambda key,build,project:project(build())
    original=server.build_index;lock=threading.Lock();builds=0
    def counted(*args,**kwargs):
        nonlocal builds
        with lock:builds+=1
        return original(*args,**kwargs)
    server.build_index=counted
    jobs=list(range(12 if not concurrent else 8))
    def query(n):
        t=time.perf_counter()
        with application.test_client() as client:
            response=client.get(f'/api/cases/{cid}/template-occurrences',query_string=dict(class_code='N',offset=n*24,limit=24))
            data=response.get_json()
        if response.status_code!=200:
            raise RuntimeError(f'Synthetic query failed: {response.status_code}, {data}')
        elapsed=time.perf_counter()-t
        data.pop('analysis_basis',None);data.pop('analysis_revision',None)
        identity=sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
        return dict(query=n,seconds=round(elapsed,6),result_sha256=identity)
    try:
        if concurrent:
            with ThreadPoolExecutor(max_workers=4) as pool:
                results=list(pool.map(query,jobs))
        else:
            results=list(map(query,jobs))
    finally:
        server.build_index=original
    times=[r['seconds'] for r in results]
    return dict(cache_enabled=enabled,parallel=concurrent,requests=len(results),index_builds=builds,
                first_seconds=times[0],median_seconds=statistics.median(times),max_seconds=max(times),
                warm_median_seconds=statistics.median(times[1:]) if not concurrent else None,
                retention=cache.retention(),results=results)


def run(output, beats):
    if output.exists():
        raise ValueError('Refusing to overwrite previous benchmark evidence')
    with tempfile.TemporaryDirectory(prefix='ecg-query-benchmark-') as location:
        folder=Path(location);root=folder/'synthetic';cid=generate(root,beats)
        profiles=[bench(root,folder/f'work-{enabled}-{concurrent}.sqlite3',cid,enabled,concurrent)
                  for concurrent in (False,True) for enabled in (False,True)]
    equal=all([r['result_sha256'] for r in profiles[n]['results']]==[r['result_sha256'] for r in profiles[n+1]['results']]
              for n in (0,2))
    report=dict(scope='synthetic event-list handler latency, not full page or clinical performance',
                beats=beats,python=platform.python_version(),platform=platform.system(),results_equal=equal,
                source_sha256={p:sha256((ROOT/p).read_bytes()).hexdigest() for p in
                               ('app.py','ecg_core/clinical_analysis.py','ecg_core/clinical_query_cache.py',
                                'scripts/benchmark_clinical_queries.py')},profiles=profiles)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({**{k:v for k,v in report.items() if k not in ('profiles','source_sha256')},
                      'profiles':[{k:v for k,v in p.items() if k!='results'} for p in profiles]},ensure_ascii=False),flush=True)
    if not equal:
        raise AssertionError('Cache changed an event-list response')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--beats',type=int,default=100_000)
    args=parser.parse_args()
    if not 500<=args.beats<=200_000:
        parser.error('--beats must be 500–200000')
    run(args.output,args.beats)
