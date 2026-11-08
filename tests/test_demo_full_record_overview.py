"""Compare the actual Demo adapter with the native raw min/max reader; no UI."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

import pytest

from ecg_core.waveform import read_waveform_overview

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def original_math_overviews(tmp_path_factory):
    folder = tmp_path_factory.mktemp('demo-full-record-original-math')
    cases = []
    for name, samples in [('one-frame', 1), ('one-second', 200),
                          ('fractional-tail', 801), ('long-uneven-bins', 120007)]:
        raw = bytearray()
        for sample in range(samples):
            values = [((sample * (channel + 3) * 37 + channel * 149) % 6001) - 3000
                      for channel in range(8)]
            if sample in {0, 17, samples // 2, samples - 1}:
                values[1], values[2], values[6] = 32767, -32768, 32767 if sample % 2 else -32768
            raw.extend(struct.pack('<8h', *values))
        path = folder / f'{name}.bin'
        path.write_bytes(raw)
        cases.append({'name': name, 'raw_path': str(path),
                      'raw_sha256': hashlib.sha256(raw).hexdigest(),
                      'rows': [{'sample_index': n, 'group': 1, 'rr_ms': 1000}
                               for n in (200, 400, 800) if n < samples],
                      'expected': {str(bins): read_waveform_overview(path, ['II', 'V1', 'V5'], bins)
                                   for bins in (50, 63, 1000, 1600)}})
    fixture = folder / 'fixture.json'
    fixture.write_text(json.dumps({'cases': cases}, ensure_ascii=False), encoding='utf-8')
    return fixture


@pytest.mark.parametrize('case', ['parity', 'validation', 'identity', 'concurrency', 'abort'])
def test_actual_demo_full_record_overview(original_math_overviews, case):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js unavailable')
    result = subprocess.run([node, 'tests/node_demo_full_record_overview.cjs',
                             str(original_math_overviews), case], cwd=ROOT,
                            env={**os.environ, 'ECG_DEMO_SOURCE': str(ROOT)},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads(result.stdout)
    assert evidence['passed'] is True
    assert evidence['nativeParity'] is True
    assert evidence['patient_inputs'] is False
    assert evidence['services_started'] is False
    assert evidence['browser_ui'] is False
