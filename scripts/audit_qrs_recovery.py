#!/usr/bin/env python3
"""Known-failure waveform audit. Offline only; never edits clinical inputs."""
from __future__ import annotations

import argparse
from bisect import bisect_left
from collections import Counter
from datetime import datetime, timezone
import gzip
import json
from math import isfinite
from numbers import Integral, Real
from pathlib import Path
import platform
import shutil
import time

try:
    from scripts import validate_afdb as base, validate_ltafdb as long
    from scripts.evaluate_af_local import event_scores, event_summary, native_audit
except ModuleNotFoundError:
    import validate_afdb as base
    import validate_ltafdb as long
    from evaluate_af_local import event_scores, event_summary, native_audit

RECORDS = ('00', '05', '112')
FS = 128
CORE = 1800 * FS
PAD = 10 * FS
SOURCES = list(dict.fromkeys(base.SOURCES + long.SOURCES + [
    'scripts/evaluate_af_local.py', 'scripts/develop_af_entropy.py',
    'scripts/audit_qrs_recovery.py', 'tests/test_qrs_recovery.py',
    'docs/qrs-recovery-protocol-20260930.md']))


def positions(values, length):
    if isinstance(length, bool) or not isinstance(length, Integral) or length <= 0:
        raise ValueError('Recording length must be a positive integer')
    result, previous = [], -1
    for value in values:
        if (isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value)
                or int(value) != value or not previous < value < length):
            raise ValueError('Positions must be strictly increasing integers inside the recording')
        previous = int(value)
        result.append(previous)
    return result


def match_positions(reference, detected, length, tolerance=12):
    """Earliest feasible pairs maximize ordered one-to-one cardinality.

    No nearest-neighbor or minimum localization-error claim. Neither input is
    altered and duplicate detections are rejected, not silently removed.
    """
    if isinstance(tolerance, bool) or not isinstance(tolerance, int) or tolerance < 0:
        raise ValueError('Tolerance must be a nonnegative integer')
    ref, det = positions(reference, length), positions(detected, length)
    pairs, i, j = [], 0, 0
    while i < len(ref) and j < len(det):
        if det[j] < ref[i] - tolerance:
            j += 1
        elif ref[i] < det[j] - tolerance:
            i += 1
        else:
            pairs.append((ref[i], det[j])); i += 1; j += 1
    return pairs


def count_range(values, start, end):
    return bisect_left(values, end) - bisect_left(values, start)


def match_summary(reference, detected, pairs, start, end):
    r = count_range(reference, start, end)
    d = count_range(detected, start, end)
    # Matching is global. Across a core boundary the two matched counts may
    # differ; preserve both instead of losing a correct edge match.
    mr = count_range([p[0] for p in pairs], start, end)
    md = count_range([p[1] for p in pairs], start, end)
    return dict(reference_beats=r, detected_beats=d, matched_reference=mr,
                matched_detection=md, fn=r-mr, fp=d-md,
                sensitivity=mr/r if r else None, ppv=md/d if d else None)


def chunks(length, core=CORE, pad=PAD):
    if any(isinstance(v, bool) or not isinstance(v, int) for v in (length, core, pad)) or length <= 0 or core <= 0 or pad < 0:
        raise ValueError('Invalid core/context geometry')
    return [(a, min(a+core, length), max(0, a-pad), min(a+core+pad, length))
            for a in range(0, length, core)]


def detected_rows(detected, gaps, length):
    """Unclassified QRS-as-N proxy. Never use this as normal-beat truth."""
    samples = positions(detected, length)
    barriers = []
    for a, b in gaps:
        if not 0 <= a < b <= length:
            raise ValueError('Invalid missing-signal interval')
        barriers.extend((a, b))
    annotations = sorted([(s, 'N') for s in samples] + [(s, '|') for s in barriers])
    return long.adapt([a for a, _ in annotations], [s for _, s in annotations],
                      ['']*len(annotations), length, FS, 'qrs')


def fetch_waveforms(folder):
    import requests
    catalog = base.catalog(folder)
    for record in RECORDS:
        name = record+'.dat'; target = folder/name
        if target.exists() and base.digest(target) == catalog[name]:
            continue
        if target.exists():
            raise ValueError('Existing waveform checksum mismatch: '+name)
        part = folder/(name+'.qrs-audit-download')
        if part.exists():
            raise ValueError('Incomplete download exists; inspect before retry: '+str(part))
        with requests.get(long.ORIGIN+name, stream=True, timeout=(15,45)) as response:
            response.raise_for_status()
            with part.open('xb') as stream:
                for block in response.iter_content(1024*1024):
                    stream.write(block)
        if base.digest(part) != catalog[name]:
            raise ValueError('Downloaded waveform checksum mismatch: '+name)
        part.rename(target)
        print('Verified public waveform '+name, flush=True)


def detect_record(folder, record, header):
    import numpy as np
    import wfdb
    from wfdb.processing import xqrs_detect
    length = header.sig_len
    output = [dict(samples=[], gaps=[], chunks=[]) for _ in range(2)]
    for a, b, lo, hi in chunks(length):
        wave = wfdb.rdrecord(str(folder/record), sampfrom=lo, sampto=hi, physical=True)
        for channel in range(2):
            signal = wave.p_signal[:, channel]
            finite = np.isfinite(signal)
            core = signal[a-lo:b-lo]
            valid = core[np.isfinite(core)]
            detail = dict(start_sample=a, end_sample=b, context_start=lo, context_end=hi,
                          nonfinite_samples=int((~finite).sum()),
                          core_p01_mv=float(np.quantile(valid,.01)) if len(valid) else None,
                          core_p99_mv=float(np.quantile(valid,.99)) if len(valid) else None)
            if not finite.all():
                output[channel]['gaps'].append((a,b))
                detail.update(status='withheld_nonfinite', detected_beats=0)
            else:
                start = time.perf_counter()
                local = xqrs_detect(signal, fs=FS, learn=True, verbose=False)
                candidates = positions(local, hi-lo)
                retained = [s+lo for s in candidates if a <= s+lo < b]
                output[channel]['samples'].extend(retained)
                detail.update(status='detected', detected_beats=len(retained),
                              detector_elapsed_s=time.perf_counter()-start)
            output[channel]['chunks'].append(detail)
        print(f'{record}: core end {b/FS/3600:.2f} h', flush=True)
    for result in output:
        result['samples'] = positions(result['samples'], length)
    return output


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def snapshot_sources(output, hashes):
    """Capture inputs to the computation before expensive detection starts.

    A partial run remains inspectable; only summary.json denotes completion.
    Verify the copied bytes, not just the source observed before copying.
    """
    for name, value in hashes.items():
        target = output/'snapshot'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(base.ROOT/name, target)
        if base.digest(target) != value or base.digest(base.ROOT/name) != value:
            raise ValueError('Source changed before audit: '+name)


def evaluate(folder, output):
    import numpy as np
    import scipy
    import wfdb
    if wfdb.__version__ != '4.3.1':
        raise ValueError('Protocol requires WFDB 4.3.1')
    expected = base.catalog(folder)
    input_hashes = {}
    for record in RECORDS:
        for ext in ('hea','dat','atr','qrs'):
            name = record+'.'+ext
            value = base.digest(folder/name)
            if value != expected[name]:
                raise ValueError('Input checksum mismatch: '+name)
            input_hashes[name] = value
    hashes = {name:base.digest(base.ROOT/name) for name in SOURCES}
    output.mkdir(parents=True, exist_ok=False)
    snapshot_sources(output, hashes)
    write_json(output/'inputs.json', dict(
        started_at=datetime.now(timezone.utc).isoformat(),
        completion_requires='summary.json plus matching final input/source hashes',
        input_sha256=input_hashes, source_sha256=hashes,
        versions=dict(python=platform.python_version(),wfdb=wfdb.__version__,numpy=np.__version__,scipy=scipy.__version__)))
    results = []
    for record in RECORDS:
        header = wfdb.rdheader(str(folder/record))
        if header.fs != FS or header.n_sig != 2 or header.units != ['mV','mV']:
            raise ValueError('Unexpected public waveform calibration or channel metadata')
        started = time.perf_counter()
        # The detector never receives reference annotations or original QRS.
        detected = detect_record(folder, record, header)
        # Save detector output before loading reference labels or scoring. A
        # downstream error must not erase evidence of what was actually run.
        with gzip.open(output/f'{record}-detection.json.gz','wt',encoding='utf-8') as stream:
            json.dump(detected,stream,allow_nan=False)
        ref = wfdb.rdann(str(folder/record),'atr')
        original = wfdb.rdann(str(folder/record),'qrs')
        length, duration = header.sig_len, header.sig_len/FS
        reference = positions([int(s) for s,code in zip(ref.sample,ref.symbol) if code in long.BEATS], length)
        segments = long.reference_segments(ref.sample,ref.symbol,ref.aux_note,length,FS)
        original_rows, _ = long.adapt(original.sample,original.symbol,original.aux_note,length,FS,'qrs')
        sources = [('original_qrs',[int(s) for s,code in zip(original.sample,original.symbol) if code=='N'],original_rows,[],[])]
        for ch, value in enumerate(detected):
            rows, _ = detected_rows(value['samples'], value['gaps'], length)
            sources.append((f'xqrs_ch{ch}',value['samples'],rows,value['gaps'],value['chunks']))
        for method, samples, rows, gaps, diagnostics in sources:
            pairs = match_positions(reference,samples,length)
            matches = {str(t):match_summary(reference,samples,match_positions(reference,samples,length,t),0,length) for t in (6,12,19)}
            windows = base.screen(rows,duration)['windows']
            events = event_scores(windows,segments,duration)
            score = long.score(windows,segments,duration)
            native = native_audit(windows,segments,FS,length)
            if any(abs(native[k]-score['seconds'][k]) > 1e-7 for k in base.TIME_KEYS):
                raise ValueError('Native-grid time accounting mismatch')
            hourly = [dict(start_s=a/FS,end_s=b/FS,**match_summary(reference,samples,pairs,a,b)) for a,b,_,_ in chunks(length)]
            row = dict(record=record,method=method,duration_s=duration,
                       qrs_match=matches,missing_input_intervals=gaps,chunks=diagnostics,
                       core_matching=hourly,af=score,af_events=event_summary(events),
                       quality_reasons=dict(Counter(w['reason'] for w in windows if w['reason'])))
            results.append(row)
            with gzip.open(output/f'{record}-{method}.json.gz','wt',encoding='utf-8') as stream:
                json.dump(dict(samples=samples,af_windows=windows,af_reference_events=events),stream,allow_nan=False)
            write_json(output/'records.json',results)
        print(f'Completed {record} in {time.perf_counter()-started:.1f}s',flush=True)
    for name, value in input_hashes.items():
        if base.digest(folder/name) != value:
            raise ValueError('Input changed during audit: '+name)
    for name, value in hashes.items():
        if base.digest(base.ROOT/name) != value:
            raise ValueError('Source changed during audit: '+name)
        if base.digest(output/'snapshot'/name) != value:
            raise ValueError('Snapshot changed during audit: '+name)
    write_json(output/'summary.json',dict(protocol='known-qrs-waveform-v1',
        completed_at=datetime.now(timezone.utc).isoformat(),
        interpretation='Known development failures, not independent validation or clinical deployment. XQRS positions use an unclassified-QRS-as-N proxy for RR screening.',
        records=list(RECORDS),methods=['original_qrs','xqrs_ch0','xqrs_ch1'],
        matching_samples=[6,12,19],fs=FS,core_samples=CORE,context_samples=PAD,
        versions=dict(python=platform.python_version(),wfdb=wfdb.__version__,numpy=np.__version__,scipy=scipy.__version__),
        input_sha256=input_hashes,source_sha256=hashes,
        results=[dict(record=r['record'],method=r['method'],qrs_match=r['qrs_match'],
                      af_metrics=r['af']['metrics'],af_seconds=r['af']['seconds'],
                      af_events=r['af_events']) for r in results]))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--fetch',action='store_true')
    args=parser.parse_args()
    if args.fetch:fetch_waveforms(args.data)
    if args.output:evaluate(args.data,args.output)
    elif not args.fetch:parser.error('Specify --output or --fetch')
