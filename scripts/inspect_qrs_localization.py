#!/usr/bin/env python3
"""Post-hoc saved-window transition audit; never tunes or reruns a detector."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
from hashlib import sha256
import json
from pathlib import Path


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def payload(path):
    with gzip.open(path,'rt') as stream:
        return json.load(stream)


def state(window):
    return window['reason'] or ('candidate' if window['candidate'] else 'negative')


def failures(window):
    # Exactly the frozen baseline thresholds, used for explanation, not tuning.
    return '+'.join(k for k, bad in (
        ('cv',window['cv'] < .12),
        ('rmssd',window['normalized_rmssd'] < .14),
        ('turning',not .45 <= window['turning_ratio'] <= .85)) if bad)


def inspect(results, prior, output):
    summary_path=results/'summary.json'; summary_hash=digest(summary_path)
    s=json.loads(summary_path.read_text())
    if s['protocol']!='bounded-qrs-localization-v1':
        raise ValueError('Unexpected experiment')
    records=['00','05','112']
    methods=['xqrs_ch0','corrected_ch0','xqrs_ch1','corrected_ch1']
    if s['records']!=records or s['methods']!=methods:
        raise ValueError('Incomplete experiment range')
    expected={(r,m) for r in records for m in methods}
    if len(s['results'])!=12 or {(r['record'],r['method']) for r in s['results']}!=expected:
        raise ValueError('Incomplete or duplicate scored combinations')
    def check():
        for root,key in ((results,'result_sha256'),(prior,'prior_sha256'),(results/'snapshot','source_sha256')):
            for name,value in s[key].items():
                if digest(root/name)!=value:raise ValueError('Evidence changed: '+name)
        if digest(summary_path)!=summary_hash:raise ValueError('Summary changed')
    check()
    transitions=[]
    for r in records:
        original=payload(prior/f'{r}-detection.json.gz')
        corrected=payload(results/f'{r}-correction.json.gz')
        for ch in (0,1):
            before=payload(results/f'{r}-xqrs_ch{ch}.json.gz')
            after=payload(results/f'{r}-corrected_ch{ch}.json.gz')
            if before['samples']!=original[ch]['samples'] or after['samples']!=corrected[ch]['samples']:
                raise ValueError('Scored points disagree with pre-reference checkpoints')
            if len(before['samples'])!=len(after['samples']):raise ValueError('Beat count changed')
            shifts=[b-a for a,b in zip(before['samples'],after['samples'])]
            if max(map(abs,shifts),default=0)>13 or any(a>=b for a,b in zip(after['samples'],after['samples'][1:])):
                raise ValueError('Position bound or order violated')
            if len(before['af_windows'])!=len(after['af_windows']):raise ValueError('Window count changed')
            if before['af_windows']!=payload(prior/f'{r}-xqrs_ch{ch}.json.gz')['af_windows']:
                raise ValueError('Original AF baseline changed')
            changes,lost,examples=Counter(),Counter(),[]
            for a,b in zip(before['af_windows'],after['af_windows']):
                if (a['start_s'],a['end_s'])!=(b['start_s'],b['end_s']):raise ValueError('Window boundaries changed')
                if state(a)==state(b):continue
                changes[state(a)+' -> '+state(b)]+=1
                if state(a)=='candidate' and state(b)=='negative':
                    reason=failures(b)
                    if not reason:raise ValueError('Negative window has no failed threshold')
                    lost[reason]+=1
                    if len(examples)<3:examples.append(dict(before=a,after=b))
            transitions.append(dict(record=r,channel=ch,beats=len(shifts),
                changed_windows=dict(changes),candidate_to_negative_thresholds=dict(lost),examples=examples))
    check()
    with output.open('x') as stream:
        json.dump(dict(completed_at=datetime.now(timezone.utc).isoformat(),
            scope='Post-hoc window transitions, not AF-only events or proof of causal physiological error',
            summary_sha256=summary_hash,inspector_sha256=digest(Path(__file__)),transitions=transitions),
            stream,indent=2,allow_nan=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results',type=Path,required=True)
    parser.add_argument('--prior',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    inspect(args.results,args.prior,args.output)
