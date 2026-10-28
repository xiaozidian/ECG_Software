"""The published P01 artifact must contain software, never a patient source."""
import json
from pathlib import Path
import zipfile
import pytest
from scripts.windows_doctor_build import ASSET_FILES,PACKAGE_NAME,create_content_manifest,verify_content_manifest,digest
from scripts.windows_deidentified_package import archive,template,unpack,assemble

def test_p01_template_retains_exact_binary_and_excludes_source(tmp_path):
    root=tmp_path/'input'/PACKAGE_NAME;root.mkdir(parents=True)
    (root/'CardioInsightDoctorEval.exe').write_bytes(b'generated-test-executable-not-run')
    for relative in ASSET_FILES:
        p=root/'_internal'/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('generated-test-asset')
    (root/'RELEASE.json').write_text(json.dumps({'source_id':'M01','source_version':'M01-24h-v1',
        'minimum_source_version':'M01-24h-v1','packaging_version':'1.0.4','source_commit':'a'*40,
        'production_source_identity':{'release_id':'test-only'},'source_manifest_sha256':'b'*64,
        'wholly_synthetic':True,'patient_inputs_read':False,'duration_seconds':86400,'raw_waveform_bytes':276480000}))
    create_content_manifest(root,with_source=False)
    raw=archive(root,tmp_path/'input-archive','software.zip')
    result=template(tmp_path/'input-archive'/raw['archive'],tmp_path/'p01')
    assert result['status']=='passed' and result['patient_data_in_artifact'] is False
    p01=unpack(tmp_path/'p01'/result['archive'],tmp_path/'verify')
    verify_content_manifest(p01)
    release=json.loads((p01/'RELEASE.json').read_text())
    assert release['source_id']=='P01' and release['source_data_bundled'] is False
    assert 'patient_inputs_read' not in release and 'duration_seconds' not in release
    assert not (p01/'Sources').exists()
    assert digest(p01/'CardioInsightDoctorEval.exe')==digest(root/'CardioInsightDoctorEval.exe')
