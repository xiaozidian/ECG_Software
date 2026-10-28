"""Generated test records only: no hospital files are used or uploaded."""
from hashlib import sha256
import json
from pathlib import Path
import struct

import pytest
from ecg_core import doctor_source as source
from ecg_core.repository import CaseRepository
from scripts.deidentify_patient_source import export_case
import win_doctor_eval as doctor

@pytest.fixture
def original(tmp_path):
    case='1111000000000001';root=tmp_path/'generated-input';folder=root/case
    for sub in ['data','DGS','report_image']:(folder/sub).mkdir(parents=True)
    (folder/'data'/f'{case}.DATA').write_bytes(bytes(16)*24000)
    (folder/'DGS'/f'{case}.EBI').write_bytes(b'FAKE-ID-DO-NOT-COPY'.ljust(32,b' ')+b''.join(
        struct.pack('<IHHIIII',s,0,1,0,0,0,1000) for s in [200,400,600]))
    values=['姓名：FAKE-PATIENT','ID号：FAKE-PATIENT-ID','性别：女','年龄：53',
            '床位：FAKE-BED','申请医生：FAKE-DOCTOR','申请科室：FAKE-DEPARTMENT',
            '临床诊断：FAKE-TEXT','记录时间：2024-02-28 10:12:13','记录时长：0小时2分钟',
            '总心搏数：3','平均心率：60','SDNN：5.25 ms']
    import xml.etree.ElementTree as ET
    tree=ET.Element('PrivateReport',patient='FAKE-PATIENT');page=ET.SubElement(tree,'Page')
    for i,value in enumerate(values):ET.SubElement(page,'PShape',CRECT=f'0,{i*20},1000,{i*20+18}',hidden='FAKE-SECRET').text=value
    (folder/'report_image'/f'{case}_1.LPS').write_bytes(ET.tostring(tree,encoding='utf-8'))
    (folder/'report_image'/f'{case}_1.png').write_bytes(b'FAKE-PRIVATE-REPORT-IMAGE')
    (folder/'report').mkdir();(folder/'report'/f'{case}.pdf').write_bytes(b'FAKE-NOT-A-PDF-PRIVATE-REPORT')
    return CaseRepository(root).get_case(case)

@pytest.fixture
def exported(original,tmp_path):
    target=tmp_path/'clean'/'P01'
    result=export_case(original,target,mathematical_fixture=True)
    assert result['original_inputs_unchanged']
    return target

def test_reconstruction_removes_identity_and_preserves_clinical_input(original,exported):
    actual=source.validate_source(exported)
    assert actual['kind']=='mathematical_deidentified_fixture' and actual['wholly_synthetic'] is True
    assert actual['duration_seconds']==120 and actual['sample_count']==24000
    assert (exported/source.PATHS['data']).read_bytes()==Path(original['paths']['data']).read_bytes()
    assert (exported/source.PATHS['ebi']).read_bytes()[32:]==Path(original['paths']['ebi']).read_bytes()[32:]
    parsed=source.validate_clean_lps(exported/source.PATHS['lps'])
    assert parsed['summary']==original['summary']
    assert parsed['metadata']['start_iso']=='2000-01-01T10:12:13'
    assert not any(p.suffix.lower() in {'.png','.pdf','.db'} for p in exported.rglob('*'))
    assert b'FAKE-' not in (exported/source.PATHS['lps']).read_bytes()

@pytest.mark.parametrize('change',['extra-file','extra-directory','raw','header','private-xml','hidden-root-text','mixed-provenance','integer-flag','duration','traversal'])
def test_source_rejects_incomplete_or_private_or_mismatched_payload(exported,change):
    manifest=exported/'source-manifest.json';m=json.loads(manifest.read_text())
    if change=='extra-file':(exported/'private.txt').write_text('FAKE-NAME')
    elif change=='extra-directory':(exported/'FAKE-PATIENT').mkdir()
    elif change=='raw':
        with (exported/source.PATHS['data']).open('r+b') as f:f.write(b'bad')
    elif change=='header':
        with (exported/source.PATHS['ebi']).open('r+b') as f:f.write(b'private')
    elif change in {'private-xml','hidden-root-text'}:
        p=exported/source.PATHS['lps'];text=p.read_text()
        p.write_text(text.replace('匿名病例 P01','FAKE-PATIENT') if change=='private-xml' else text.replace('<Report>','<Report>FAKE-PATIENT'))
    elif change=='mixed-provenance':m['kind']='deidentified_patient'
    elif change=='integer-flag':m['deidentification']['direct_identifiers_removed']=1
    elif change=='duration':m['duration_seconds']=86400
    elif change=='traversal':m['files'][0]['path']='../private.DATA'
    manifest.write_text(json.dumps(m))
    with pytest.raises((AssertionError,ValueError,KeyError)):source.validate_source(exported)

def program(tmp_path,monkeypatch):
    root=tmp_path/'program';root.mkdir()
    (root/'RELEASE.json').write_text(json.dumps({'source_id':'P01','minimum_source_version':source.VERSION,'packaging_version':'1.0.4'}))
    monkeypatch.setattr(doctor,'package_root',lambda:root)
    return root

def test_native_profile_does_not_reuse_synthetic_home_and_binds_one_source(exported,tmp_path,monkeypatch):
    program(tmp_path,monkeypatch)
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'app-data'))
    monkeypatch.delenv('ECG_DOCTOR_EVAL_HOME',raising=False)
    assert doctor.evaluation_home().name=='CardioInsightDoctorEvalP01'
    monkeypatch.setenv('ECG_DOCTOR_EVAL_SOURCE_ROOT',str(exported))
    assert doctor.selected_source(register=True)==exported
    binding=json.loads((doctor.evaluation_home()/'source-selection.json').read_text())
    assert binding['selected_dataset']=='P01'
    assert binding['source_manifest_sha256']==source.file_hash(exported/'source-manifest.json')
    # Even semantically unchanged JSON bytes cannot silently replace a binding.
    with (exported/'source-manifest.json').open('a') as stream:stream.write('\n')
    with pytest.raises(doctor.DoctorEvalError,match='发生变化'):doctor.selected_source()

def test_old_m01_release_cannot_open_a_p01_source(exported,tmp_path,monkeypatch):
    root=tmp_path/'m01-program';root.mkdir();monkeypatch.setattr(doctor,'package_root',lambda:root)
    with pytest.raises(doctor.DoctorEvalError):doctor.validate_source(source=exported)

def test_p01_catalog_and_diagnostic_keep_truthful_fixture_provenance(exported,tmp_path,monkeypatch):
    program(tmp_path,monkeypatch)
    catalog=doctor.WorkspaceCatalog(tmp_path/'work',exported)
    identifier=catalog.new();folder=catalog.get(identifier)
    data=json.loads((folder/'WORKSPACE.json').read_text())
    assert data['selected_dataset']=='P01' and data['source_kind']=='mathematical_deidentified_fixture'
    monkeypatch.setattr(doctor,'selected_source',lambda:exported)
    report=doctor.diagnostic()
    assert report['source_id']=='P01' and report['wholly_synthetic'] is True and report['source_version']==source.VERSION
    assert 'FAKE-' not in json.dumps(report)
