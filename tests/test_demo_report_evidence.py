"""Native-generated ST evidence and real mathematical fetch/storage adapter."""
import json
import os
from pathlib import Path
import struct
import subprocess
from ecg_core.stt import build_stt_review
from scripts.build_math_payload import generate

ROOT = Path(__file__).resolve().parents[1]


def test_math_payload_contains_native_minute_st_evidence(tmp_path):
    output = tmp_path / 'generated'
    generate(output, 'math-test-only')
    case = json.loads((output / 'case-data.js').read_text().split(' = ', 1)[1].rstrip(';\n'))
    review = case['stt_review']
    assert review['analysis']['algorithm_version'] == 'stt-screening-0.5.0-morphology-qualified'
    assert review['analysis']['trends']['block_seconds'] == 60
    assert set(review['analysis']['trends']['leads']) == {'I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6'}
    assert all(len(rows) == 10 for rows in review['analysis']['trends']['leads'].values())
    assert all('whole_statistics' in item for item in review['automatic_candidates']['items'])
    assert case['stt_review_binding']['python_precomputed'] is True
    assert case['stt_review_binding']['beat_revision'] == 0
    assert 'rhythm_exclusions' not in case['stt_review_binding']
    assert case['stt_review_binding']['rhythm_policy'] == 'independent_of_AF_AFL_reviews'
    assert case['stt_review_binding']['data_version'] == case['stt_review_binding']['beat_version'] + '-stt-comprehensive-v3'
    assert case['stt_review_binding']['patient_inputs_read'] is False


def test_actual_demo_adapter_multi_af_readonly_strips_and_native_st(tmp_path):
    duration = 320
    raw = bytearray()
    for sample in range(200 * duration):
        second, phase = divmod(sample, 200)
        shift = 130 if 120 <= second < 205 and 18 <= phase <= 44 else 0
        value = {0:900,1:600,2:250,3:80}.get(phase,0) + shift + (180 if 55 <= phase <= 62 else 0)
        raw.extend(struct.pack('<8h', *(value for _ in range(8))))
    data = tmp_path / 'waveform.bin'
    data.write_bytes(raw)
    rows = [{'sample_index':s*200,'group':1,'rr_ms':1000} for s in range(1,duration)]
    review = build_stt_review('Mathematics only', data, rows, duration,
        analysis_revision='editor-0|overrides-none')
    assert review['automatic_candidates']['items']
    fixture = tmp_path / 'fixture.json'
    fixture.write_text(json.dumps({'raw_path':str(data),'rows':rows,'stt_review':review}))
    subprocess.run(['node',str(ROOT/'tests/browser_demo_report_evidence.cjs'),str(fixture)],
        cwd=ROOT,env=dict(os.environ),check=True,timeout=90)
