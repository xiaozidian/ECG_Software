"""P01 software template in CI; real source assembly is local-only."""
from pathlib import Path, PurePosixPath
from hashlib import sha256
import argparse
import json
import os
import shutil
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from ecg_core import doctor_source as source
from scripts.windows_doctor_build import (PACKAGE_NAME,create_content_manifest,verify_content_manifest,digest)

README='''CardioInsight Windows x64 去标识化病例评估版

完整解压后双击 CardioInsightDoctorEval.exe 或“启动医生评估.cmd”。
P01来源与M01合成版使用不同的默认工作目录，原软件和工作区保持保留。
如使用软件更新包，请保留原来源目录和已保存工作，在新程序目录启动。
先保存网页中的修改，再使用软件自身的停止入口。

完整P01包的来源性质以RELEASE.json和Sources/P01/source-manifest.json为准。
真实P01会明确标为deidentified_patient，不会标为数学合成病例。
源日历日期已平移；波形和心搏记录保留，原报告图片/PDF/自由文本不随包分发。
软件包自身不包含未经本地去标识化和校验的患者输入。

目标Windows10 x64；医院实机、EDR及未签名软件认可尚未验证。
PDF导出/打印、中文PDF和设备电压校准不在本次验收范围。
功能验证不代表临床通过。仅按已授权的本地评估用途保管此包。
'''

def unpack(archive,destination):
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        seen=set()
        for info in z.infolist():
            p=PurePosixPath(info.filename)
            assert '\\' not in info.filename and not p.is_absolute() and '..' not in p.parts
            assert p.parts[0]==PACKAGE_NAME and not any(':' in v for v in p.parts)
            assert (info.external_attr>>16)&0o170000!=0o120000
            assert info.filename.casefold() not in seen;seen.add(info.filename.casefold())
        z.extractall(destination)
    return destination/PACKAGE_NAME

def archive(package,output,name):
    output.mkdir(parents=True,exist_ok=True);path=output/name
    with zipfile.ZipFile(path,'x',zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as z:
        for p in sorted(package.rglob('*')):
            assert not p.is_symlink()
            if not p.is_file():continue
            info=zipfile.ZipInfo(PACKAGE_NAME+'/'+p.relative_to(package).as_posix(),date_time=(2000,1,1,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100600<<16
            with p.open('rb') as inp,z.open(info,'w',force_zip64=True) as out:shutil.copyfileobj(inp,out,1024*1024)
    with zipfile.ZipFile(path) as z:assert z.testzip() is None
    checksum=digest(path)
    (output/(name+'.sha256')).write_text(checksum+'  '+name+'\n')
    return {'archive':name,'bytes':path.stat().st_size,'sha256':checksum}

def template(software,output):
    package=unpack(software,output/'template')
    verify_content_manifest(package)
    release=json.loads((package/'RELEASE.json').read_text())
    assert release['source_id']=='M01' and release['packaging_version']=='1.0.4'
    original_exe=digest(package/'CardioInsightDoctorEval.exe')
    for key in ['source_manifest_sha256','wholly_synthetic','patient_inputs_read','duration_seconds','raw_waveform_bytes']:
        release.pop(key,None)
    release.update(source_id='P01',source_version=source.VERSION,minimum_source_version=source.VERSION,
                   source_data_bundled=False,source_registration_required=True,
                   supported_source_profile=source.PROFILE)
    (package/'RELEASE.json').write_text(json.dumps(release,ensure_ascii=False,indent=2)+'\n')
    (package/'使用说明.txt').write_text(README,encoding='utf-8-sig')
    (package/'版本说明.txt').write_text('1.0.4：P01去标识化病例来源支持；保持既有交互和临床算法阈值。\n',encoding='utf-8-sig')
    create_content_manifest(package,with_source=False);verify_content_manifest(package)
    assert digest(package/'CardioInsightDoctorEval.exe')==original_exe
    result=archive(package,output,f'{PACKAGE_NAME}-1.0.4-P01-software.zip')
    result.update(status='passed',source_commit=release['source_commit'],production_source_identity=release['production_source_identity'],
                  exe_sha256=original_exe,patient_data_in_artifact=False,source_profile='P01',
                  note='Software only. Actual patient assembly must remain on the local host.')
    (output/'p01-software-build-report.json').write_text(json.dumps(result,indent=2)+'\n')
    return result

def assemble(software,patient_source,output):
    manifest=source.validate_source(patient_source)
    assert manifest['kind']=='deidentified_patient'
    assert os.environ.get('GITHUB_ACTIONS','').lower()!='true','Real patient source is forbidden in CI'
    package=unpack(software,output/'package')
    verify_content_manifest(package)
    release=json.loads((package/'RELEASE.json').read_text())
    assert release['source_id']=='P01' and release['packaging_version']=='1.0.4'
    original_exe=digest(package/'CardioInsightDoctorEval.exe')
    shutil.copytree(patient_source,package/'Sources/P01')
    assert source.validate_source(package/'Sources/P01')==manifest
    release.update(source_manifest_sha256=digest(package/'Sources/P01/source-manifest.json'),
                   source_kind='deidentified_patient',wholly_synthetic=False,patient_inputs_read=True,
                   source_data_bundled=True,source_registration_required=False,
                   duration_seconds=manifest['duration_seconds'],raw_waveform_bytes=manifest['expected_raw_bytes'],
                   local_deidentification=True,clinical_release=False)
    (package/'RELEASE.json').write_text(json.dumps(release,ensure_ascii=False,indent=2)+'\n')
    create_content_manifest(package);verify_content_manifest(package)
    assert digest(package/'CardioInsightDoctorEval.exe')==original_exe
    result=archive(package,output,f'{PACKAGE_NAME}-1.0.4-P01-full.zip')
    result.update(status='passed',source_commit=release['source_commit'],core_version=release['software_version'],
                  source_kind=manifest['kind'],source_id='P01',source_manifest_sha256=release['source_manifest_sha256'],
                  original_ci_exe_unchanged=True,exe_sha256=original_exe,source_data_assembled_only_locally=True,
                  windows_executable_run_on_mac=False,clinical_validation=False)
    (output/'local-build-report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['template','assemble'])
    p.add_argument('--software-archive',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--source-root',type=Path);p.add_argument('--local-patient',action='store_true')
    a=p.parse_args()
    if a.mode=='template':result=template(a.software_archive,a.output)
    else:
        assert a.local_patient and a.source_root is not None
        result=assemble(a.software_archive,a.source_root,a.output)
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
