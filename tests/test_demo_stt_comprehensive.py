"""Actual browser fetch/storage and Python raw morphology on independent math bytes."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
from ecg_core.stt import build_stt_review
from ecg_core.stt_range import analyze_stt_range
from ecg_core.beat_editor import EditedRecords,blank

ROOT=Path(__file__).resolve().parents[1]


def test_demo_new_T_types_compound_review_and_source_morphology(tmp_path):
    spec=importlib.util.spec_from_file_location('stt_comprehensive_math',ROOT/'scripts/generate_stt_comprehensive_math.py')
    generator=importlib.util.module_from_spec(spec);spec.loader.exec_module(generator)
    out=tmp_path/'source';generator.generate(out)
    data=out/generator.CASE_ID/'data'/f'{generator.CASE_ID}.DATA'
    rows=[dict(sample_index=i*200,group=1,rr_ms=1000) for i in range(1,899)]
    feed=EditedRecords([(r['sample_index'],0,1,0,0,0,r['rr_ms']) for r in rows],blank(),[],900)
    review=build_stt_review('Mathematical independent morphology',data,feed.records,900,analysis_revision='editor-0|overrides-none')
    expected={}
    for kind,lead in [('t_persistent_inversion','V2'),('t_low_flat','V3'),('t_biphasic','V4'),('t_wave_inversion','V5')]:
        candidate=next(c for c in review['automatic_candidates']['items'] if c['kind']==kind and c['leads']==[lead])
        expected[kind]=analyze_stt_range(data,feed.records,start_sample=round(candidate['start_s']*200),end_sample=round(candidate['end_s']*200),leads=[lead])
    payload=tmp_path/'fixture.json';payload.write_text(json.dumps(dict(raw_path=str(data),raw_sha256=hashlib.sha256(data.read_bytes()).hexdigest(),rows=rows,review=review,expected=expected)))
    run=subprocess.run(['node','tests/browser_demo_stt_comprehensive.cjs',str(payload)],cwd=ROOT,text=True,capture_output=True,timeout=90)
    assert run.returncode==0,run.stdout+run.stderr
    result=json.loads(run.stdout)
    assert result['passed'] and result['new_T_types']==4 and result['patient_inputs_read'] is False
    assert result['services_started'] is False and result['external_network'] is False
