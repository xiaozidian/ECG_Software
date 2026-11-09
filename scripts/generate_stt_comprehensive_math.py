"""Deterministic source waveform for ST/T engineering acceptance, never a patient.

The design intervals are independent waveform inputs, not detector outputs or
clinical annotations. Verification must inspect measured events on these bytes.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import struct
import xml.etree.ElementTree as ET

import numpy as np

CASE_ID = '9900000000000030'
RATE = 200
DURATION = 900


def generate(output: Path) -> dict:
    output = Path(output)
    if output.exists():
        raise ValueError('Preserve previous mathematical fixture; use a new directory')
    folder = output / CASE_ID
    files = {kind: folder / sub / filename for kind, sub, filename in (
        ('data', 'data', CASE_ID + '.DATA'),
        ('ebi', 'DGS', CASE_ID + '.EBI'),
        ('lps', 'report_image', CASE_ID + '_1.LPS'),
    )}
    for path in files.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    count = DURATION * RATE
    values = np.full((count, 8), 4000., dtype=np.float64)
    beats = list(range(RATE, count - RATE, RATE))
    for sample in beats:
        second = sample // RATE
        low, high = max(0, sample - 50), min(count, sample + 110)
        offsets = np.arange(low, high) - sample
        qrs = (1000 * np.exp(-.5 * (offsets / 1.3) ** 2)
               - 150 * np.exp(-.5 * ((offsets + 4) / 1.5) ** 2)
               - 180 * np.exp(-.5 * ((offsets - 5) / 1.8) ** 2))
        values[low:high] += qrs[:, None]
        t = np.exp(-.5 * ((offsets - 62) / 6) ** 2)
        t_amplitudes = np.full(8, 180.)
        t_amplitudes[2] = -160.  # V1: expected-polarity context, not a missing trace.
        if second < 181:
            t_amplitudes[3] = -180.  # V2: inversion present from recording start.
        if 61 <= second < 241:
            t_amplitudes[4] = 10.  # V3: genuine low T with preserved R.
        if 361 <= second < 541:
            t_amplitudes[6] = -180.  # V5: positive -> negative -> positive.
        values[low:high] += t[:, None] * t_amplitudes
        if 181 <= second < 301:
            # V4: two distinct lobes; averaging the lobes is not a flat T.
            values[low:high, 5] -= t * 180
            values[low:high, 5] += (180 * np.exp(-.5 * ((offsets - 55) / 4) ** 2)
                                    - 180 * np.exp(-.5 * ((offsets - 78) / 4) ** 2))
        plateau = ((offsets >= 17) & (offsets <= 44)).astype(float)
        values[low:high, 0] -= plateau * 170  # I: persistent absolute ST offset.
        if 121 <= second < 241:
            values[low:high, 1] += plateau * 170
        if 421 <= second < 601:
            values[low:high, 7] -= plateau * 170
    files['data'].write_bytes(np.rint(values).astype('<i2').tobytes())
    record = struct.Struct('<IHHIIII')
    files['ebi'].write_bytes(bytes(32) + b''.join(
        record.pack(sample, 1, 1, 0, 0, 0, 1000) for sample in beats))
    document = ET.Element('LrScriptPage')
    shapes = ET.SubElement(document, 'ShapeList')
    texts = ['姓名：ST-T数学验收', '记录时间：2026-01-01 08:00:00',
             '记录时长：0小时15分钟', '总心搏数：' + str(len(beats)),
             '室性心搏：0', '室上性心搏：0', '最慢心率：60', '平均心率：60',
             '最快心率：60', '报告结论', '数学函数生成，不对应患者，不构成临床金标准。']
    for i, text in enumerate(texts):
        ET.SubElement(shapes, 'PShape', SPTYPE='3',
                      CRECT=f'100,{100+i*80},2200,{160+i*80}').text = text
    ET.ElementTree(document).write(files['lps'], encoding='utf-16', xml_declaration=True)
    manifest = {
        'profile': 'comprehensive-stt-mathematical-900s-v1',
        'case_id': CASE_ID, 'wholly_synthetic': True, 'patient_inputs_read': False,
        'clinical_validation': False, 'duration_s': DURATION, 'sample_rate_hz': RATE,
        'stored_leads': ['I', 'II', 'V1', 'V2', 'V3', 'V4', 'V5', 'V6'],
        'design_intervals_s': {
            'I_ST_depression_from_start': [1, 899], 'II_ST_elevation': [121, 241],
            'V2_persistent_inversion_from_start': [1, 181], 'V3_low_T': [61, 241],
            'V4_biphasic_T': [181, 301], 'V5_dynamic_inversion': [361, 541],
            'V6_ST_depression': [421, 601],
        },
        'files': {str(p.relative_to(output)): {'bytes': p.stat().st_size,
                  'sha256': sha256(p.read_bytes()).hexdigest()} for p in files.values()},
    }
    (output / 'source-manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    print(json.dumps(generate(parser.parse_args().output), ensure_ascii=False))
