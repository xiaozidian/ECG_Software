#!/usr/bin/env python3
"""Diagnostic plots of development-set errors, not a clinical report."""
import argparse
import csv
from pathlib import Path
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import resample_poly
import wfdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.validate_qtdb import reference_beats


def plot(args):
    rows = list(csv.DictReader((args.results/'beats.csv').open()))
    rows = [r for r in rows if r['split'] == 'development' and r['status'] == 'accepted']
    rows.sort(key=lambda r: abs(float(r['qt_error_ms'])), reverse=True)
    examples, seen = [], set()
    for r in rows:
        key = (r['record'], r['lead_index'])
        if key not in seen:
            seen.add(key)
            examples.append(r)
        if len(examples) == args.count:
            break
    fig, axes = plt.subplots(len(examples), 1, figsize=(11, max(3, len(examples)*2.6)), squeeze=False)
    for ax, row in zip(axes[:, 0], examples):
        name = row['record']
        record = wfdb.rdrecord(str(args.data/name))
        ann = wfdb.rdann(str(args.data/name), row['annotator'])
        beat = next(b for b in reference_beats(ann.sample, ann.symbol, ann.num)
                    if b['r_sample'] == int(row['r_sample_250']))
        signal = resample_poly(record.p_signal*1000, 4, 5, axis=0)
        center = int(round(beat['r_sample']*.8))
        y = signal[center-50:center+130, int(row['lead_index'])].copy()
        y -= np.median(y[15:25])
        x = np.arange(-50, 130)*5
        ax.plot(x, y, color='#202830', linewidth=1)
        for kind, color in [('q', '#247ba0'), ('t', '#c25035')]:
            ref = beat[f'{kind}_sample']*4-center*5
            measured = ref+float(row[f'{kind}_error_ms'])
            ax.axvline(ref, color=color, linestyle='--', label=f'Reference {kind.upper()}')
            ax.axvline(measured, color=color, label=f'Measured {kind.upper()}')
        ax.axhline(0, color='#aaa', linewidth=.6)
        ax.set_title(f"{name} / lead {row['lead']} / R {row['r_sample_250']} / QT error {row['qt_error_ms']} ms")
        ax.set(xlabel='Relative to resampled R (ms)', ylabel='Header-scaled microvolts')
        ax.legend(loc='upper right', fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(args.output, dpi=140)
    plt.close(fig)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--results', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--count', type=int, default=6)
    plot(p.parse_args())
