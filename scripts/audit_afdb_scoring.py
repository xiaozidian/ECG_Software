#!/usr/bin/env python3
"""Independent native-250-Hz confusion-time audit of AFDB baseline output.

Unlike validate_afdb's interval intersection, this uses a dense reference and
prediction vector on the original sample grid. It does not call its scorer.
"""
import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path

import numpy as np


def native_seconds(length, samples, labels, windows):
    mapping={'(AFIB':1,'(AFL':2,'(J':3,'(N':4}
    ref=np.zeros(length,dtype=np.uint8)
    for i,(sample,label) in enumerate(zip(samples,labels)):
        stop=int(samples[i+1]) if i+1<len(samples) else length
        ref[int(sample):stop]=mapping[label.strip().rstrip('\x00')]
    prediction=np.zeros(length,dtype=np.uint8)
    covered=np.zeros(length,dtype=bool)
    for window in windows:
        a,b=(round(float(window[k])*250) for k in ('start_s','end_s'))
        if not 0<=a<b<=length or covered[a:b].any():
            raise ValueError('Invalid/overlapping output windows')
        covered[a:b]=True
        evaluated=window['evaluated'] in (True,'True')
        candidate=window['candidate'] in (True,'True')
        prediction[a:b]=0 if not evaluated else 2 if candidate else 1
    if not covered.all():
        raise ValueError('Missing output windows')
    counts=np.bincount(ref.astype(np.int16)*3+prediction,minlength=15)
    return dict(tp_s=float(counts[5])/250,fn_s=float(counts[4])/250,
                fp_s=float(counts[[8,11,14]].sum())/250,tn_s=float(counts[[7,10,13]].sum())/250,
                withheld_af_s=float(counts[3])/250,withheld_non_af_s=float(counts[[6,9,12]].sum())/250,
                unknown_s=float(counts[:3].sum())/250)


def audit(data,results):
    import wfdb
    records=json.loads((results/'records.json').read_text())
    with (results/'windows.csv').open() as stream:
        windows=list(csv.DictReader(stream))
    errors=[];maximum=0
    for record in records:
        name=record['record'];header=wfdb.rdheader(str(data/name));ann=wfdb.rdann(str(data/name),'atr')
        if header.fs!=250:raise ValueError('Native audit expects 250 Hz')
        subset=[w for w in windows if w['record']==name and w['annotator']==record['annotator']]
        actual=native_seconds(header.sig_len,ann.sample,ann.aux_note,subset)
        for key,value in actual.items():
            difference=abs(value-record['seconds'][key]);maximum=max(maximum,difference)
            if difference>1e-6:errors.append(dict(record=name,annotator=record['annotator'],metric=key,difference_s=difference))
    return dict(method='native 250 Hz dense labels vs interval-intersection scorer',
                record_runs=len(records),metric_comparisons=len(records)*7,max_abs_difference_s=maximum,
                errors=errors,auditor_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
                records_sha256=sha256((results/'records.json').read_bytes()).hexdigest(),
                windows_sha256=sha256((results/'windows.csv').read_bytes()).hexdigest())


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',type=Path,required=True);p.add_argument('--results',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    result=audit(args.data,args.results)
    with args.output.open('x') as stream:json.dump(result,stream,indent=2)
    print(json.dumps(result,indent=2))
    raise SystemExit(bool(result['errors']))
