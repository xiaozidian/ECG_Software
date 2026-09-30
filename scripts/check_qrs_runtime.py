#!/usr/bin/env python3
"""Offline actual-library smoke test; synthetic geometry, no clinical claims."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile

import numpy as np
import scipy
import wfdb

try:
    from scripts import audit_qrs_recovery as audit
except ModuleNotFoundError:
    import audit_qrs_recovery as audit


def check(output):
    if wfdb.__version__ != '4.3.1':
        raise ValueError('Expected frozen WFDB 4.3.1 runtime')
    fs=128;length=1805*fs
    reference=[];sample=fs
    while sample < length-fs:
        reference.append(sample)
        # Deterministic rate transitions; exact integer sample positions.
        sample += 128 if sample < 600*fs else 96 if sample < 1200*fs else 160
    time=np.arange(length)/fs
    wave=.015*np.sin(2*np.pi*.17*time)
    offsets=np.arange(-64,65)
    t=offsets/fs
    morphology=(np.exp(-.5*(t/.012)**2)-.2*np.exp(-.5*((t+.026)/.008)**2)
                -.3*np.exp(-.5*((t-.028)/.01)**2)+.08*np.exp(-.5*((t+.18)/.025)**2)
                +.2*np.exp(-.5*((t-.28)/.045)**2))
    for sample in reference:
        wave[sample+offsets]+=morphology
    signal=np.column_stack((.8*wave,-1.2*wave))
    with tempfile.TemporaryDirectory(prefix='ecg-qrs-synthetic-') as temporary:
        wfdb.wrsamp('synthetic',fs=fs,units=['mV','mV'],sig_name=['positive','inverted'],
                     p_signal=signal,fmt=['16','16'],adc_gain=[1000,1000],baseline=[0,0],write_dir=temporary)
        header=wfdb.rdheader(str(Path(temporary)/'synthetic'))
        result=audit.detect_record(Path(temporary),'synthetic',header)
        matches=[audit.match_summary(reference,r['samples'],
            audit.match_positions(reference,r['samples'],length),0,length) for r in result]
        passed=all(m['fn']==0 and m['fp']==0 for m in matches)
        evidence=dict(completed_at=datetime.now(timezone.utc).isoformat(),
            purpose='Synthetic actual-library and chunk-boundary check; not clinical validation',
            passed=passed,fs=fs,length=length,reference_samples=reference,
            qrs_match=matches,channels=result,
            versions=dict(wfdb=wfdb.__version__,numpy=np.__version__,scipy=scipy.__version__),
            source_sha256={name:audit.base.digest(audit.base.ROOT/name) for name in (
                'scripts/check_qrs_runtime.py','scripts/audit_qrs_recovery.py')})
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x') as stream:
        json.dump(evidence,stream,indent=2,allow_nan=False)
    print(json.dumps(dict(passed=passed,qrs_match=matches),indent=2),flush=True)
    return passed


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    raise SystemExit(0 if check(parser.parse_args().output) else 1)
