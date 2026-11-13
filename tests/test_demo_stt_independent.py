"""Eight independent actual-formula Demo cases; mathematical source only."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess

import pytest

from ecg_core.stt import build_stt_review

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def independent_math(tmp_path_factory):
    folder=tmp_path_factory.mktemp('demo-stt-independent-math')
    duration=320
    raw=bytearray()
    for sample in range(duration*200):
        second,phase=divmod(sample,200)
        shift=130 if 120<=second<205 and 18<=phase<=44 else 0
        value={0:900,1:600,2:250,3:80}.get(phase,0)+shift+(180 if 55<=phase<=62 else 0)
        raw.extend(struct.pack('<8h',*(value for _ in range(8))))
    data=folder/'waveform.bin'
    data.write_bytes(raw)
    rows=[{'sample_index':second*200,'group':1,'rr_ms':1000} for second in range(1,duration)]
    review=build_stt_review('Original mathematical signal; no clinical conclusion',data,rows,duration,
                            analysis_revision='editor-0|overrides-none')
    assert review['analysis']['algorithm_version']=='stt-screening-0.5.0-morphology-qualified'
    assert review['automatic_candidates']['items']
    fixture=folder/'fixture.json'
    fixture.write_text(json.dumps({'raw_path':str(data),'raw_sha256':hashlib.sha256(raw).hexdigest(),
                                  'rows':rows,'review':review}))
    return fixture


@pytest.mark.parametrize('case',[
    'af-add','af-update','af-delete','afl-add','afl-update','afl-delete',
    'source-beat-method-guards','quality-uuid-concurrency-guards',
])
def test_actual_demo_stt_is_independent_of_rhythm_review(independent_math,case):
    result=subprocess.run(['node','tests/browser_demo_stt_independent.cjs',str(independent_math),case],
                          cwd=ROOT,capture_output=True,text=True,timeout=90)
    assert result.returncode==0,result.stdout+result.stderr
    evidence=json.loads(result.stdout)
    assert evidence['passed'] is True
    assert evidence['policy']=='independent_of_AF_AFL_reviews'
    assert evidence['patient_inputs'] is False and evidence['services_started'] is False
    assert evidence['external_network'] is False
