"""Assemble15 from exact14 EXE/runtime bytes and frozen UI80; no compilation."""
from pathlib import Path
import argparse, json, os, shutil, subprocess, sys, tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.windows_deidentified_package import unpack, archive
from scripts.windows_doctor_build import create_content_manifest, verify_content_manifest, regular_files, PACKAGE_NAME, digest
from scripts.shared_source import snapshot
from scripts.verify_public_release import verify
from scripts.prepare_ui15_baseline import read, dump, verify_runtime_source
from scripts.verify_windows_stt_independent_upgrade import embedded_modules

APP='0.12.29-stt-independent.20261104';UI='0.12.29-ui-source-render.20261108';VERSION='1.0.15'

def hashes(root):return {name:digest(path) for name,path in regular_files(root).items()}

def compare_programs(before,after,assets):
    assert set(before)==set(after),'Repack added or removed package members'
    allowed={'_internal/'+name for name in assets}|{'_internal/shared-source-build.json','RELEASE.json','版本说明.txt','CONTENTS.json','SHA256SUMS.txt'}
    changed=sorted(name for name in before if before[name]!=after[name]);assert set(changed)<=allowed,sorted(set(changed)-allowed)
    assert any(name.startswith(('_internal/static/','_internal/templates/')) for name in changed),'No changed UI assets'
    immutable={name:value for name,value in before.items() if name not in allowed}
    assert immutable and all(after[name]==value for name,value in immutable.items())
    return changed,immutable

def patch(a,c,kind,path,shared,assets):
    description=c['base_archives'][kind];assert digest(path)==description['sha256'] and path.stat().st_size==description['bytes']
    assert path.with_name(path.name+'.sha256').read_text().split()==[digest(path),path.name]
    package=unpack(path,a.output/('repack-'+kind));verify_content_manifest(package)
    release=read(package/'RELEASE.json');old=read(package/'_internal/shared-source-build.json');before=hashes(package)
    assert release['packaging_version']=='1.0.14' and release['app_version']==release['software_version']==APP
    assert release['source_commit']==c['base_binary_source_commit'] and release['production_source_identity']['source_sha256']==c['base_Windows_production_source_sha256']
    assert before['CardioInsightDoctorEval.exe']==c['base_EXE_sha256'] and old==c['base_common_stamp']
    assert old['core_version']==shared['core_version']==c['base_core_version'] and old['ui_version']!=shared['ui_version']
    assert {n for n,v in old['files'].items() if v['component']=='ui'}==set(assets)
    for name in assets:
        destination=package/'_internal'/name;assert destination.is_file();destination.write_bytes((ROOT/name).read_bytes())
    (package/'_internal/shared-source-build.json').write_bytes((ROOT/'shared-source-build.json').read_bytes())
    # Keep original binary-built/dependency metadata. These additions describe
    # only the UI assembly and its independently accepted binary baseline.
    release.update(packaging_version=VERSION,release_version=VERSION,ui_release_id=UI,source_commit=a.source_commit,
        production_source_identity=verify(ROOT),base_binary_source_commit=c['base_binary_source_commit'],
        base_binary_ci_run=c['base_binary_ci_run'],base_binary_ci_conclusion='failure',
        accepted_base_validation_commit=c['accepted_base_validation_commit'],accepted_base_validation_run=c['accepted_base_validation_run'],
        base_binary_exe_sha256=c['base_EXE_sha256'],base_archive_sha256=digest(path),binary_reused_without_rebuild=True,ui_repack_only=True,
        ui_repack_ci_run_url=a.ci_run_url,ci_run_url=a.ci_run_url,
        release_notes='界面按源数据重新绘制；复用1.0.14原EXE与全部非界面运行文件，既有临床依据不变。')
    dump(package/'RELEASE.json',release)
    (package/'版本说明.txt').write_text('1.0.15 / Render UI 2026.11.08：界面源数据重绘更新。\n核心仍0.12.29-stt-independent.20261104；原1.0.14 EXE和运行环境原字节复用，未重新编译算法。\n',encoding='utf-8-sig')
    create_content_manifest(package,with_source=kind=='M01_full');verify_content_manifest(package)
    changed,immutable=compare_programs(before,hashes(package),assets)
    suffix={'P01_software':'P01-software','M01_full':'full','M01_update':'software'}[kind]
    result=archive(package,a.output,f'{PACKAGE_NAME}-{VERSION}-{suffix}.zip')
    result.update(kind=kind,base_archive_sha256=digest(path),base_source_commit=c['base_binary_source_commit'],source_commit=a.source_commit,
        exe_sha256=c['base_EXE_sha256'],changed_files=changed,unchanged_file_count=len(immutable),
        every_non_UI_file_byte_equal=True,exact_EXE_reused=True,no_binary_rebuild=True,patient_data_in_artifact=False)
    # Verify actual final ZIP, not only the staging directory.
    final=unpack(a.output/result['archive'],a.output/('final-'+kind));verify_content_manifest(final)
    assert hashes(final)==hashes(package)
    return final,release,result

def main():
    p=argparse.ArgumentParser();p.add_argument('--baseline-proof',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--source-commit',required=True);p.add_argument('--ci-run-url',required=True);a=p.parse_args()
    assert os.name=='nt','Assembly and real EXE smoke run in native Windows CI'
    assert not a.output.exists();a.output.mkdir(parents=True)
    assert len(a.source_commit)==40 and all(c in '0123456789abcdef' for c in a.source_commit)
    c=read(ROOT/'scripts/ui15-baseline-contract.json');verify_runtime_source(c)
    base=read(a.baseline_proof);assert base['status']=='verified_baseline14_reused_not_new_UI15_acceptance'
    assert base['base_EXE_sha256']==c['base_EXE_sha256'] and base['producer_run']==c['base_binary_ci_run'] and base['accepted_validation_run']==c['accepted_base_validation_run']
    shared,_=snapshot(ROOT);assert shared==read(ROOT/'shared-source-build.json') and shared['core_version']==c['base_core_version']
    identity=verify(ROOT);assert identity['release_id']==UI and identity['production_files_verified']==129
    assets=[name for name,row in shared['files'].items() if row['component']=='ui'];assert len(assets)==80
    packages={};releases={};results={}
    for kind in ('P01_software','M01_full','M01_update'):packages[kind],releases[kind],results[kind]=patch(a,c,kind,Path(base['paths'][kind]),shared,assets)
    embedded=embedded_modules(packages['P01_software']/'CardioInsightDoctorEval.exe',ROOT)
    assert embedded['runtime_python_sha256']==c['immutable_Windows_runtime_python_source_sha256']
    data=Path(base['paths']['M01_math_data']);assert digest(data)==c['base_archives']['M01_math_data']['sha256']
    for item in (data,data.with_name(data.name+'.sha256')):shutil.copyfile(item,a.output/item.name)
    shutil.copytree(packages['M01_full'],a.output/'verify-package'/PACKAGE_NAME)
    # The16 fixture tests the existing15 updater only; it is not a16 release.
    fixture=a.output/'upgrade-fixture'/PACKAGE_NAME;shutil.copytree(packages['M01_update'],fixture)
    fixture_release={**releases['M01_update'],'packaging_version':'1.0.16','release_version':'1.0.16',
        'verification_fixture_only':True,'verification_scope':'same exact29 binary and15 UI; packaging-only16 fixture, not a user deliverable'}
    dump(fixture/'RELEASE.json',fixture_release);create_content_manifest(fixture,with_source=False);verify_content_manifest(fixture)
    upgrade=archive(fixture,a.output,PACKAGE_NAME+'-1.0.16-upgrade-fixture.zip')
    source=Path(os.environ['ECG_DATA_ROOT']);assert not source.exists();shutil.copytree(packages['M01_full']/'Sources/M01',source)
    env={k:v for k,v in os.environ.items() if not k.startswith(('PYTHON','ECG_'))};system=os.environ['SystemRoot'];env['PATH']=str(Path(system)/'System32')+os.pathsep+system
    with tempfile.TemporaryDirectory(prefix='ui15-PE-smoke-',dir=a.output) as temp:
        exe=(a.output/'verify-package'/PACKAGE_NAME/'CardioInsightDoctorEval.exe').resolve()
        for flag in ('--self-check','--smoke-test'):subprocess.run([str(exe),flag],cwd=temp,env=env,check=True)
    full,update=results['M01_full'],results['M01_update']
    report={**releases['M01_full'],'archive':full['archive'],'archive_sha256':full['sha256'],'software_archive':update['archive'],'software_archive_sha256':update['sha256'],
        'source_archive':data.name,'source_archive_sha256':digest(data),'verification_upgrade_fixture':{**upgrade,'user_deliverable':False},
        'final_zip_crc_and_content_hashes_verified':True,'final_unpacked_exe_self_check_passed':True,'final_unpacked_exe_process_smoke_passed':True,
        'python_removed_from_runtime_path':True,'ui_repack_results':results,'no_PyInstaller_or_compiler_invoked':True,'embedded_runtime':embedded,
        'actual_UI15_native_feature_acceptance':'pending separate workflow stages'}
    dump(a.output/'build-report.json',report)
    p01=a.output.parent/'doctor-p01';p01.mkdir(exist_ok=False)
    for name in (results['P01_software']['archive'],results['P01_software']['archive']+'.sha256'):shutil.copyfile(a.output/name,p01/name)
    dump(p01/'p01-software-build-report.json',{**results['P01_software'],'source_profile':'P01','status':'assembled_native_acceptance_pending'})
    print(json.dumps(dict(status='UI15_assembled_native_acceptance_pending',binary_reused_without_rebuild=True,EXE_sha256=c['base_EXE_sha256'],UI_assets=80)))

if __name__=='__main__':main()
