"""Strict, local-only source contract for one deidentified evaluation record.

P01 is distinct from synthetic M01. The same contract has an explicitly named
mathematical fixture kind so native CI never needs a patient's files.
"""
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
import math
from pathlib import Path, PurePosixPath
import re
import struct
import xml.etree.ElementTree as ET

CASE_ID = '9000000000000001'
SOURCE_ID = 'P01'
VERSION = 'P01-deidentified-v1'
PROFILE = 'cardioinsight-doctor-eval-deidentified-v1'
CHANNELS = ['I','II','V1','V2','V3','V4','V5','V6']
PATHS = {'data':f'{CASE_ID}/data/{CASE_ID}.DATA',
         'ebi':f'{CASE_ID}/DGS/{CASE_ID}.EBI',
         'lps':f'{CASE_ID}/report_image/{CASE_ID}_1.LPS'}
DEIDENTIFICATION = {key:True for key in ['direct_identifiers_removed','dates_shifted',
    'source_paths_replaced','free_text_and_report_images_excluded',
    'original_waveform_preserved','ebi_records_preserved','lps_numeric_summary_preserved']}
SUMMARY = {
    'total_beats':('总心搏数',''),'ventricular_beats':('室性心搏',''),
    'supraventricular_beats':('室上性心搏',''),'min_hr':('最慢心率',''),
    'avg_hr':('平均心率',''),'max_hr':('最快心率',''),'longest_rr_s':('最长RR间期',''),
    'tachy_beats':('心动过速中的心搏总和',''),'brady_beats':('心动过缓中的心搏总和',''),
    'sdnn_ms':('SDNN',' ms'),'sdann_ms':('SDANN',' ms'),
    'sdnn_index_ms':('SDNNIndex',' ms'),'rmssd_ms':('rMSSD',' ms'),
    'pnn50_pct':('pNN50',' %'),'lf_hf':('LF/HF',''),
    'triangular_index':('三角指数',''),'lf':('LF',''),'hf':('HF','')}

def file_hash(path):
    h=sha256()
    with Path(path).open('rb') as stream:
        while chunk:=stream.read(1024*1024):h.update(chunk)
    return h.hexdigest()

def clean_lps(parsed):
    """Reconstruct recognized numerical fields; copy no original XML/free text."""
    start=datetime.fromisoformat(parsed['metadata']['start_iso']).replace(year=2000,month=1,day=1)
    reported=parsed['metadata']['duration_seconds_reported']
    duration='' if reported is None else f'{reported//3600}小时{reported%3600//60}分钟'
    texts=['姓名：匿名病例 P01','性别：','年龄：','ID号：'+CASE_ID,'床位：',
           '申请医生：','申请科室：','临床诊断：','起搏器：',
           '记录时间：'+start.strftime('%Y-%m-%d %H:%M:%S'),
           '记录时长：'+duration]
    for key,(label,suffix) in SUMMARY.items():
        value=parsed['summary'].get(key)
        if value is not None:
            assert isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)
            texts.append(label+'：'+format(Decimal(str(value)),'f')+suffix)
    root=ET.Element('Report');page=ET.SubElement(root,'Page')
    for i,text in enumerate(texts):
        # Keep every metric outside the source conclusion's coordinate band.
        ET.SubElement(page,'PShape',CRECT=f'0,{i*20},1000,{i*20+18}').text=text
    return ET.tostring(root,encoding='utf-8',xml_declaration=True)

def validate_clean_lps(path):
    from .lps_parser import parse_lps
    data=Path(path).read_bytes()
    assert len(data)<64_000 and b'<!DOCTYPE' not in data.upper() and b'<!ENTITY' not in data.upper()
    root=ET.fromstring(data)
    assert root.tag=='Report' and not root.attrib
    assert len(root)==1 and root[0].tag=='Page' and not root[0].attrib
    allowed={'姓名：匿名病例 P01','性别：','年龄：','ID号：'+CASE_ID,'床位：',
             '申请医生：','申请科室：','临床诊断：','起搏器：'}
    labels={label+':' for label,_ in SUMMARY.values()}
    for node in root.iter():
        assert not (node.tail or '').strip()
        if node.tag in {'Report','Page'}:
            assert not (node.text or '').strip()
            continue
        assert node.tag=='PShape' and len(node)==0 and set(node.attrib)=={'CRECT'}
        assert re.fullmatch(r'0,\d+,1000,\d+',node.attrib['CRECT'])
        text=node.text or ''
        if text in allowed:continue
        if text.startswith('记录时间：'):
            stamp=datetime.strptime(text.split('：',1)[1],'%Y-%m-%d %H:%M:%S')
            assert (stamp.year,stamp.month,stamp.day)==(2000,1,1)
        elif text.startswith('记录时长：'):
            assert re.fullmatch(r'记录时长：(?:\d+\s*小时)?\s*(?:\d+\s*分钟)?',text)
        else:
            normalized=text.replace('：',':',1)
            label=normalized.split(':',1)[0]+':'
            assert label in labels
            assert re.fullmatch(r'[0-9]+(?:\.[0-9]+)?(?: ms| %)?',normalized.split(':',1)[1])
    parsed=parse_lps(path);metadata=parsed['metadata']
    assert metadata['name']=='匿名病例 P01' and metadata['patient_id']==CASE_ID
    assert metadata['age'] is None
    assert all(not metadata[k] for k in ['sex','bed','requesting_physician','department','clinical_diagnosis','pacemaker'])
    assert not parsed['conclusion']
    return parsed

def validate_source(source,hash_file=file_hash):
    source=Path(source)
    for path in [source,*source.parents,*source.rglob('*')]:
        assert not path.is_symlink() and not getattr(path.lstat(),'st_file_attributes',0)&0x400
    manifest_path=source/'source-manifest.json'
    assert manifest_path.stat().st_size<16_000
    m=json.loads(manifest_path.read_text())
    keys={'schema_version','source_id','case_id','profile','kind','source_version',
        'wholly_synthetic','patient_inputs_read','clinical_validation','sampling_rate_hz',
        'channel_count','stored_channels','sample_format','sample_count','duration_seconds',
        'expected_raw_bytes','deidentification','files','dataset_sha256'}
    assert set(m)==keys and type(m['schema_version']) is int and m['schema_version']==1
    assert m['source_id']==SOURCE_ID and m['case_id']==CASE_ID and m['profile']==PROFILE and m['source_version']==VERSION
    assert m['clinical_validation'] is False and m['deidentification']==DEIDENTIFICATION
    assert all(type(v) is bool for v in m['deidentification'].values())
    if m['kind']=='deidentified_patient':
        assert m['wholly_synthetic'] is False and m['patient_inputs_read'] is True
    else:
        assert m['kind']=='mathematical_deidentified_fixture' and m['wholly_synthetic'] is True and m['patient_inputs_read'] is False
    assert m['sampling_rate_hz']==200 and m['channel_count']==8 and m['stored_channels']==CHANNELS
    assert m['sample_format']=='little-endian int16'
    assert type(m['sample_count']) is int and 0<m['sample_count']<=200*86400*7
    assert type(m['expected_raw_bytes']) is int and m['expected_raw_bytes']==m['sample_count']*16
    assert type(m['duration_seconds']) in (int,float) and math.isfinite(m['duration_seconds'])
    assert abs(m['duration_seconds']-m['sample_count']/200)<1e-7
    rows=m['files'];assert isinstance(rows,list) and len(rows)==3
    assert {r.get('path') for r in rows}==set(PATHS.values())
    dataset=sha256()
    for row in sorted(rows,key=lambda r:r['path']):
        assert set(row)=={'path','size_bytes','sha256'} and type(row['size_bytes']) is int and row['size_bytes']>0
        assert re.fullmatch('[0-9a-f]{64}',row['sha256'])
        path=source/row['path']
        assert path.is_file() and path.stat().st_size==row['size_bytes'] and hash_file(path)==row['sha256']
        dataset.update(row['path'].encode());dataset.update(row['sha256'].encode('ascii'))
    assert dataset.hexdigest()==m['dataset_sha256']
    assert {p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file()}==set(PATHS.values())|{'source-manifest.json'}
    allowed_dirs={parent.as_posix() for name in PATHS.values() for parent in PurePosixPath(name).parents if parent.as_posix()!='.'}
    assert {p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_dir()}==allowed_dirs
    assert (source/PATHS['data']).stat().st_size==m['expected_raw_bytes']
    ebi=source/PATHS['ebi']
    with ebi.open('rb') as stream:assert stream.read(32)==bytes(32)
    from .ebi import load_records
    records=load_records(str(ebi))
    assert records[-1][0]<m['sample_count']
    validate_clean_lps(source/PATHS['lps'])
    return m
