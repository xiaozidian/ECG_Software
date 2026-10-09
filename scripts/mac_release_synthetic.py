"""Deterministic mathematical ECG-shaped fixtures. No patient inputs are read."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

CASE_ID = '9999999999999999'


def generate(destination: Path) -> dict:
    import numpy as np
    from ecg_core.ebi import HEADER_SIZE, RECORD

    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('合成数据目标必须是新目录；不会覆盖任何现有来源。')
    destination.mkdir(mode=0o700, parents=True)
    case = destination / CASE_ID
    for folder in ('data', 'DGS', 'report_image'):
        (case / folder).mkdir(mode=0o700, parents=True)
    sample_rate, seconds = 200, 180
    sample = np.arange(sample_rate * seconds, dtype=np.float64)
    phase = np.mod(sample, sample_rate) / sample_rate
    # Arbitrary device units, deliberately not a voltage calibration or clinical model.
    base = (800 * np.exp(-((phase - .22) / .018) ** 2)
            - 220 * np.exp(-((phase - .245) / .022) ** 2)
            + 110 * np.exp(-((phase - .10) / .035) ** 2)
            + 170 * np.exp(-((phase - .50) / .09) ** 2)
            + 20 * np.sin(2 * np.pi * sample / (sample_rate * 7)))
    channels = np.stack([base * (.6 + i * .09) + 8 * np.sin(sample / (61 + i))
                         for i in range(8)], axis=1)
    data = case / 'data' / f'{CASE_ID}.DATA'
    data.write_bytes(np.rint(channels).astype('<i2').tobytes())
    ebi = case / 'DGS' / f'{CASE_ID}.EBI'
    ebi.write_bytes(bytes(HEADER_SIZE) + b''.join(
        RECORD.pack(i * sample_rate + 44, 1, 1, 0, 0, 0, 1000)
        for i in range(1, seconds - 1)))
    lps = case / 'report_image' / f'{CASE_ID}_1.LPS'
    lps.write_text('<root><PShape>记录时间:2026-01-01 08:00:00</PShape>'
                   '<PShape>总心搏数:178</PShape></root>', encoding='utf-8')
    manifest = dict(kind='mathematical_synthetic', generator='mac_release_synthetic-v1',
                    patient_inputs_read=False, clinical_ground_truth=False,
                    voltage_calibrated=False, sample_rate_hz=sample_rate,
                    storage_channels=8, seconds=seconds,
                    files={str(p.relative_to(destination)): sha256(p.read_bytes()).hexdigest()
                           for p in (data, ebi, lps)})
    (destination / 'SYNTHETIC.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    return manifest
