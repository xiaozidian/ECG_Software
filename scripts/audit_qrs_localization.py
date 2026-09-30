#!/usr/bin/env python3
"""Offline, fixed-geometry localization experiment. No production integration."""
from __future__ import annotations

import argparse
from bisect import bisect_left
from collections import Counter
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import platform
import time

import numpy as np

try:
    from scripts import audit_qrs_recovery as qrs
except ModuleNotFoundError:
    import audit_qrs_recovery as qrs

RADIUS, WINDOW = 13, 19
METHODS = ('xqrs_ch0', 'corrected_ch0', 'xqrs_ch1', 'corrected_ch1')
SOURCES = list(dict.fromkeys(qrs.SOURCES + [
    'scripts/audit_qrs_localization.py', 'scripts/verify_qrs_results.py',
    'tests/test_qrs_localization.py', 'docs/qrs-localization-protocol-20260930.md']))


def correct_peaks(signal, peaks, radius=RADIUS, window=WINDOW):
    """Reference-blind, count-preserving residual extrema in disjoint cells.

    Returns one corrected position per original position, in the same order.
    Uses actual support at record edges. Reject nonfinite samples explicitly.
    """
    x = np.asarray(signal, dtype=float)
    if x.ndim != 1 or not len(x) or not np.isfinite(x).all():
        raise ValueError('Signal must be nonempty, one-dimensional and finite')
    if (type(radius) is not int or radius < 0 or type(window) is not int
            or window < 1 or window % 2 != 1):
        raise ValueError('Invalid search or odd smoothing geometry')
    original = qrs.positions(peaks, len(x))
    # Full convolution with an explicit center slice also works for signals
    # shorter than the kernel; numpy mode="same" does not preserve that size.
    half = window // 2
    kernel = np.ones(window)
    with np.errstate(over='ignore', invalid='ignore'):
        sums = np.convolve(x, kernel, mode='full')[half:half+len(x)]
        support = np.convolve(np.ones(len(x)), kernel, mode='full')[half:half+len(x)]
        residual = np.abs(x - sums / support)
    if not np.isfinite(residual).all():
        raise ValueError('Nonfinite residual after smoothing')
    corrected = []
    for i, p in enumerate(original):
        left, right = max(0, p-radius), min(len(x), p+radius+1)
        if i:
            left = max(left, (original[i-1]+p)//2+1)
        if i+1 < len(original):
            right = min(right, (p+original[i+1])//2+1)
        values = residual[left:right]
        candidates = np.flatnonzero(values == np.max(values)) + left
        best = min(candidates.tolist(), key=lambda s: (abs(s-p), s))
        corrected.append(int(best))
    qrs.positions(corrected, len(x))
    if len(corrected) != len(original):
        raise ValueError('Localization changed beat count')
    return corrected


def displacement(original, corrected):
    if len(original) != len(corrected):
        raise ValueError('Different beat counts')
    shifts = [b-a for a, b in zip(original, corrected)]
    return dict(beats=len(shifts), unchanged=shifts.count(0),
                at_radius=sum(abs(s) == RADIUS for s in shifts),
                histogram_samples=dict(sorted(Counter(shifts).items())),
                max_absolute_samples=max(map(abs, shifts), default=0))


def correct_record(folder, record, header, channels):
    """Only waveform plus saved detections enter here; no annotation reads."""
    length = header.sig_len
    if len(channels) != 2:
        raise ValueError('Expected two saved detector channels')
    originals = [qrs.positions(c['samples'], length) for c in channels]
    for c in channels:
        # Also validate original gap geometry using the shared RR adapter.
        qrs.detected_rows(c['samples'], c['gaps'], length)
        if sum(chunk['detected_beats'] for chunk in c['chunks']) != len(c['samples']):
            raise ValueError('Saved chunk counts disagree with detection input')
    import wfdb
    output = [dict(samples=[], gaps=c['gaps'], chunks=[]) for c in channels]
    for a, b, lo, hi in qrs.chunks(length):
        wave = wfdb.rdrecord(str(folder/record), sampfrom=lo, sampto=hi, physical=True)
        for ch in range(2):
            original = originals[ch]
            core = original[bisect_left(original, a):bisect_left(original, b)]
            signal = wave.p_signal[:, ch]
            finite = np.isfinite(signal).all()
            gap = any(start <= a and b <= end for start, end in channels[ch]['gaps'])
            if not finite or gap:
                if finite or not gap or core:
                    raise ValueError('Nonfinite waveform conflicts with saved detector evidence')
                output[ch]['chunks'].append(dict(start_sample=a, end_sample=b,
                    status='withheld_nonfinite', beats=0))
                continue
            context = original[bisect_left(original, lo):bisect_left(original, hi)]
            local = correct_peaks(signal, [p-lo for p in context])
            retained = [p+lo for old, p in zip(context, local) if a <= old < b]
            output[ch]['samples'].extend(retained)
            output[ch]['chunks'].append(dict(start_sample=a, end_sample=b,
                status='corrected', **displacement(core, retained)))
    for ch, c in enumerate(output):
        qrs.positions(c['samples'], length)
        c['displacement'] = displacement(originals[ch], c['samples'])
        if c['displacement']['max_absolute_samples'] > RADIUS:
            raise ValueError('Correction exceeded search radius')
    return output


def read_gzip(path):
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        return json.load(stream)


def write_gzip(path, value):
    with gzip.open(path, 'xt', encoding='utf-8') as stream:
        json.dump(value, stream, allow_nan=False)


def check_hashes(root, expected):
    for name, value in expected.items():
        if qrs.base.digest(root/name) != value:
            raise ValueError('Changed or incorrect file: '+str(root/name))


def evaluate(folder, prior, output):
    import scipy
    import wfdb
    from scripts.verify_qrs_results import maximum_match_count, self_test

    if wfdb.__version__ != '4.3.1':
        raise ValueError('Protocol requires WFDB 4.3.1')
    old = json.loads((prior/'summary.json').read_text())
    if old['records'] != list(qrs.RECORDS) or old['protocol'] != 'known-qrs-waveform-v1':
        raise ValueError('Not the fixed prior experiment')
    check_hashes(folder, old['input_sha256'])
    official = qrs.base.catalog(folder)
    if any(official[k] != v for k, v in old['input_sha256'].items()):
        raise ValueError('Prior inputs disagree with official checksums')
    check_hashes(prior/'snapshot', old['source_sha256'])
    # Reject a changed baseline rather than interpreting it as localization gain.
    check_hashes(qrs.base.ROOT, old['source_sha256'])
    prior_files = ['summary.json'] + [r+'-detection.json.gz' for r in qrs.RECORDS]
    prior_files += [f'{r}-xqrs_ch{ch}.json.gz' for r in qrs.RECORDS for ch in (0, 1)]
    prior_hashes = {p:qrs.base.digest(prior/p) for p in prior_files}
    source_hashes = {p:qrs.base.digest(qrs.base.ROOT/p) for p in SOURCES}
    versions = dict(python=platform.python_version(), numpy=np.__version__,
                    scipy=scipy.__version__, wfdb=wfdb.__version__)
    output.mkdir(parents=True, exist_ok=False)
    qrs.snapshot_sources(output, source_hashes)
    qrs.write_json(output/'inputs.json', dict(started_at=datetime.now(timezone.utc).isoformat(),
        input_sha256=old['input_sha256'], source_sha256=source_hashes,
        prior_sha256=prior_hashes, versions=versions, radius_samples=RADIUS, smooth_samples=WINDOW))
    self_test()
    results, agreement, independent, result_hashes = [], [], [], {}
    for record in qrs.RECORDS:
        started = time.perf_counter()
        header = wfdb.rdheader(str(folder/record))
        if header.fs != qrs.FS or header.n_sig != 2 or header.units != ['mV','mV']:
            raise ValueError('Unexpected calibrated public waveform geometry')
        raw = read_gzip(prior/f'{record}-detection.json.gz')
        corrected = correct_record(folder, record, header, raw)
        checkpoint = f'{record}-correction.json.gz'
        write_gzip(output/checkpoint, corrected)  # Saved BEFORE reference reads.
        result_hashes[checkpoint] = qrs.base.digest(output/checkpoint)
        length, duration = header.sig_len, header.sig_len/qrs.FS
        for label, sources in [('original', raw), ('corrected', corrected)]:
            a, b = [c['samples'] for c in sources]
            pairs = qrs.match_positions(a, b, length, 12)
            independent_count = maximum_match_count(a, b, 12)
            if len(pairs) != independent_count:
                raise ValueError('Lead agreement independent count mismatch')
            agreement.append(dict(record=record, method=label, matched=len(pairs),
                lead0_beats=len(a), lead1_beats=len(b),
                agreement=2*len(pairs)/(len(a)+len(b)) if a or b else None))
        ref = wfdb.rdann(str(folder/record), 'atr')
        reference = qrs.positions([int(s) for s,c in zip(ref.sample,ref.symbol) if c in qrs.long.BEATS], length)
        segments = qrs.long.reference_segments(ref.sample, ref.symbol, ref.aux_note, length, qrs.FS)
        for ch in (0, 1):
            for prefix, source in [('xqrs', raw[ch]), ('corrected', corrected[ch])]:
                method = f'{prefix}_ch{ch}'
                samples = source['samples']
                rows, _ = qrs.detected_rows(samples, source['gaps'], length)
                matches = {}
                for tolerance in (6, 12, 19):
                    pairs = qrs.match_positions(reference, samples, length, tolerance)
                    count = maximum_match_count(reference, samples, tolerance)
                    if count != len(pairs):
                        raise ValueError('Independent graph matching disagrees')
                    matches[str(tolerance)] = qrs.match_summary(reference, samples, pairs, 0, length)
                    independent.append(dict(record=record, method=method, tolerance_samples=tolerance, count=count))
                windows = qrs.base.screen(rows, duration)['windows']
                if prefix == 'xqrs' and windows != read_gzip(prior/f'{record}-{method}.json.gz')['af_windows']:
                    raise ValueError('Original AF windows differ from frozen prior results')
                score = qrs.long.score(windows, segments, duration)
                native = qrs.native_audit(windows, segments, qrs.FS, length)
                if any(abs(native[k]-score['seconds'][k]) > 1e-7 for k in qrs.base.TIME_KEYS):
                    raise ValueError('Independent native time audit disagrees')
                events = qrs.event_scores(windows, segments, duration)
                pairs = qrs.match_positions(reference, samples, length, 12)
                result = dict(record=record, method=method, duration_s=duration,
                    qrs_match=matches, af=score, af_events=qrs.event_summary(events),
                    quality_reasons=dict(Counter(w['reason'] for w in windows if w['reason'])),
                    displacement=source.get('displacement'),
                    core_matching=[dict(start_s=a/qrs.FS, end_s=b/qrs.FS,
                        **qrs.match_summary(reference,samples,pairs,a,b)) for a,b,_,_ in qrs.chunks(length)])
                results.append(result)
                name = f'{record}-{method}.json.gz'
                write_gzip(output/name, dict(samples=samples, af_windows=windows, af_reference_events=events))
                result_hashes[name] = qrs.base.digest(output/name)
                qrs.write_json(output/'records.json', results)
        print(f'Completed {record}: corrected both leads and checked four methods in {time.perf_counter()-started:.1f}s', flush=True)
    check_hashes(folder, old['input_sha256'])
    check_hashes(prior, prior_hashes)
    check_hashes(qrs.base.ROOT, source_hashes)
    check_hashes(output/'snapshot', source_hashes)
    check_hashes(output, result_hashes)
    qrs.write_json(output/'summary.json', dict(protocol='bounded-qrs-localization-v1',
        completed_at=datetime.now(timezone.utc).isoformat(), records=list(qrs.RECORDS),
        methods=list(METHODS), radius_samples=RADIUS, smooth_samples=WINDOW,
        interpretation='Known development data. No deployment; unclassified QRS-as-N proxy for unchanged AF baseline.',
        versions=versions, input_sha256=old['input_sha256'], source_sha256=source_hashes,
        prior_sha256=prior_hashes, result_sha256=result_hashes,
        independent_matches=independent, lead_agreement=agreement, results=results))


if __name__ == '__main__':
    # Allow direct script execution while the package imports remain explicit.
    import sys
    sys.path.insert(0, str(qrs.base.ROOT))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--prior', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.data, args.prior, args.output)
