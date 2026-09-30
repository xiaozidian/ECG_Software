#!/usr/bin/env python3
"""Independent sparse-graph verification of fixed QRS experiment counts."""
import argparse
from datetime import datetime, timezone
import gzip
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import scipy
from scipy.sparse import csr_array
from scipy.sparse.csgraph import maximum_bipartite_matching
import wfdb


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def maximum_match_count(reference, detected, tolerance):
    """Solve the full proximity graph; no ordered greedy matcher is reused."""
    ref=np.asarray(reference,dtype=np.int64)
    det=np.asarray(detected,dtype=np.int64)
    lo=np.searchsorted(det,ref-tolerance,side='left')
    hi=np.searchsorted(det,ref+tolerance,side='right')
    counts=hi-lo
    indptr=np.r_[0,np.cumsum(counts)].astype(np.int64)
    indices=np.concatenate([np.arange(a,b,dtype=np.int64) for a,b in zip(lo,hi)]) if len(ref) else np.array([],dtype=np.int64)
    graph=csr_array((np.ones(len(indices),dtype=np.int8),indices,indptr),shape=(len(ref),len(det)))
    matching=maximum_bipartite_matching(graph,perm_type='column')
    return int(np.count_nonzero(matching>=0))


def self_test():
    from functools import lru_cache
    import random
    rng=random.Random(930)
    for _ in range(400):
        ref=sorted(rng.sample(range(30),rng.randrange(7)))
        det=sorted(rng.sample(range(30),rng.randrange(7)))
        tolerance=rng.randrange(6)
        @lru_cache(None)
        def exhaustive(i,used):
            if i==len(ref):return 0
            result=exhaustive(i+1,used)
            for j,d in enumerate(det):
                if not used&(1<<j) and abs(ref[i]-d)<=tolerance:
                    result=max(result,1+exhaustive(i+1,used|(1<<j)))
            return result
        assert maximum_match_count(ref,det,tolerance)==exhaustive(0,0)
    assert maximum_match_count([100,200,300],[112,212,313],12)==2
    print('Sparse-graph matcher: 400 exhaustive checks and boundary case passed',flush=True)


def verify(folder, results, output):
    summary_hash=digest(results/'summary.json')
    verifier_hash=digest(Path(__file__))
    summary=json.loads((results/'summary.json').read_text())
    if summary['records']!=['00','05','112'] or summary['matching_samples']!=[6,12,19]:
        raise ValueError('Not the fixed complete development protocol')
    methods=['original_qrs','xqrs_ch0','xqrs_ch1']
    expected={(r,m) for r in summary['records'] for m in methods}
    rows=summary['results']
    if len(rows)!=len(expected) or {(r['record'],r['method']) for r in rows}!=expected:
        raise ValueError('Incomplete or duplicate result combinations')
    checked={}
    for name,hash_value in summary['input_sha256'].items():
        if digest(folder/name)!=hash_value:raise ValueError('Input changed: '+name)
    for name,hash_value in summary['source_sha256'].items():
        if digest(results/'snapshot'/name)!=hash_value:raise ValueError('Snapshot changed: '+name)
    matches=[]
    for row in rows:
        record=row['record'];method=row['method']
        reference=wfdb.rdann(str(folder/record),'atr')
        ref=reference.sample[np.isin(reference.symbol,['N','A','V','Q'])]
        path=results/f'{record}-{method}.json.gz'
        checked[path.name]=digest(path)
        with gzip.open(path,'rt') as stream: payload=json.load(stream)
        detected=payload['samples']
        if method=='original_qrs':
            original=wfdb.rdann(str(folder/record),'qrs')
            expected_samples=original.sample[np.isin(original.symbol,['N'])].tolist()
        else:
            checkpoint=results/f'{record}-detection.json.gz'
            checksum=digest(checkpoint)
            if checked.setdefault(checkpoint.name,checksum)!=checksum:
                raise ValueError('Detection checkpoint changed during verification')
            with gzip.open(checkpoint,'rt') as stream: channels=json.load(stream)
            channel=channels[int(method[-1])]
            expected_samples=channel['samples']
            if sum(c['detected_beats'] for c in channel['chunks'])!=len(expected_samples):
                raise ValueError('Detection chunks do not sum to saved input')
        if detected!=expected_samples:
            raise ValueError('Scored peaks differ from original or reference-blind checkpoint')
        for tolerance in (6,12,19):
            count=maximum_match_count(ref,detected,tolerance)
            reported=row['qrs_match'][str(tolerance)]
            actual=dict(reference_beats=len(ref),detected_beats=len(detected),
                matched_reference=count,matched_detection=count,fp=len(detected)-count,fn=len(ref)-count)
            if any(actual[k]!=reported[k] for k in actual):
                raise ValueError(f'Count disagreement: {record} {method} tolerance={tolerance}')
            matches.append(dict(record=record,method=method,tolerance_samples=tolerance,**actual))
        print('Verified graph counts '+record+' '+method,flush=True)
    # Catch files changing while they were being verified.
    for name,value in checked.items():
        if digest(results/name)!=value:raise ValueError('Result changed during verification: '+name)
    for name,value in summary['input_sha256'].items():
        if digest(folder/name)!=value:raise ValueError('Input changed during verification: '+name)
    for name,value in summary['source_sha256'].items():
        if digest(results/'snapshot'/name)!=value:raise ValueError('Snapshot changed during verification: '+name)
    if digest(results/'summary.json')!=summary_hash or digest(Path(__file__))!=verifier_hash:
        raise ValueError('Summary or verifier changed during verification')
    with output.open('x') as stream:
        json.dump(dict(completed_at=datetime.now(timezone.utc).isoformat(),
            scope='Independent maximum-cardinality graph match counts only; not clinical validation',
            methods=methods,checks=matches,result_sha256=checked,
            summary_sha256=summary_hash,verifier_sha256=verifier_hash,
            versions=dict(wfdb=wfdb.__version__,numpy=np.__version__,scipy=scipy.__version__)),
            stream,indent=2,allow_nan=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test',action='store_true')
    parser.add_argument('--data',type=Path)
    parser.add_argument('--results',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.self_test:self_test()
    if args.data and args.results and args.output:verify(args.data,args.results,args.output)
    elif any((args.data,args.results,args.output)) or not args.self_test:
        parser.error('Provide all of --data/--results/--output, or --self-test')
