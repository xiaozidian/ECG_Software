"""Bind the exact fresh14 producer and completed49; execute remaining23 without repacking.

No original package is edited or rebuilt. No previously passed gate is relabelled as a new execution; original41+P01=49
remain linked to their failed producer while supplemental14+upgrade9 run now.
"""
from pathlib import Path, PurePosixPath
from concurrent.futures import ThreadPoolExecutor
import argparse, hashlib, json, marshal, os, shutil, subprocess, sys, types, zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_public_release import verify
from scripts.shared_source import snapshot
from scripts.windows_deidentified_package import unpack
from scripts.windows_doctor_build import (verify_content_manifest, digest, SOURCE_FILES)
from PyInstaller.archive.readers import CArchiveReader

REPO = 'xiaozidian/ECG_Software'
PRODUCER = 41782148683
HEAD = '8dd2c80d0712535bc5a8b7eec0fb6f336bbcc3d0'
EXE = 'f5283fc6a670e4d6dd9553797035458f31d0ea059ef81516f06fcc3ea9c24a73'
COMMON = '37519667ee1c075e4f299e75510712d68fcbadc7d67d901d7fc2e4497c367c0a'
NAMES = {'CardioInsight-Windows-x64-1.0.14-P01-software-only':'p01',
 'CardioInsight-Windows-x64-1.0.14-M01-full':'full',
 'CardioInsight-Windows-x64-1.0.14-software-update':'update',
 'CardioInsight-Synthetic-M01-24h-v1-for-1.0.14':'math',
 'Windows-doctor-eval-mathematical-validation-1.0.14':'original-evidence'}


def api(path): return json.loads(subprocess.check_output(['gh','api','repos/'+REPO+path],stderr=subprocess.PIPE))
def read(path): return json.loads(path.read_text(encoding='utf-8-sig'))
def dump(path,value): path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def one(root,name):
    found=list(root.rglob(name));assert len(found)==1,(name,len(found));return found[0]
def normalized(code):
    return code.replace(co_filename='<reviewed>',co_consts=tuple(normalized(v) for v in code.co_consts)) if isinstance(code,types.CodeType) else code


def download(row,root,label):
    path=root/(label+'.artifact.zip')
    with path.open('xb') as stream:
        subprocess.run(['gh','api',f'repos/{REPO}/actions/artifacts/{row["id"]}/zip'],stdout=stream,stderr=subprocess.PIPE,check=True,timeout=360)
    assert row['digest']=='sha256:'+digest(path)
    with zipfile.ZipFile(path) as archive:
        names=archive.namelist();assert len(names)==len(set(names))==len({n.casefold() for n in names})
        assert archive.testzip() is None
        for item in archive.infolist():
            name=PurePosixPath(item.filename)
            assert not name.is_absolute() and '..' not in name.parts and '\\' not in item.filename
            assert not any(':' in part for part in name.parts)
            assert (item.external_attr>>16)&0o170000!=0o120000
        archive.extractall(root/label)
    return {'id':row['id'],'name':row['name'],'GitHub_digest_verified':digest(path),
            'workflow_run':row['workflow_run'],'bytes':path.stat().st_size,'extracted':str(root/label)}


def program(path,destination,profile,shared,contract):
    assert digest(path)==contract['package_bytes'][profile]['sha256']
    assert path.stat().st_size==contract['package_bytes'][profile]['bytes']
    assert path.with_name(path.name+'.sha256').read_text().split()==[digest(path),path.name]
    package=unpack(path,destination);verify_content_manifest(package)
    release=read(package/'RELEASE.json')
    assert release['source_commit']==HEAD and release['packaging_version']=='1.0.14'
    assert release['app_version']=='0.12.29-stt-independent.20261104'
    assert release['source_id']==('P01' if profile=='p01' else 'M01')
    assert release['production_source_identity']==verify(ROOT)
    assert not release.get('binary_reused_without_rebuild') and not release.get('ui_repack_only')
    assert read(package/'_internal/shared-source-build.json')==shared
    assets=[n for n,r in shared['files'].items() if r['component']=='ui'];assert len(assets)==80
    for name in assets: assert (package/'_internal'/name).read_bytes()==(ROOT/name).read_bytes(),name
    assert digest(package/'CardioInsightDoctorEval.exe')==EXE
    return package


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    assert os.name=='nt' and not args.output.exists();args.output.mkdir(parents=True)
    contract=read(ROOT/'scripts/stt-independent-continuation-contract.json')
    assert contract['producing_run']==PRODUCER and contract['producing_commit']==HEAD and contract['EXE_sha256']==EXE
    qa_changed=subprocess.check_output(['git','diff','--name-only',HEAD,'HEAD'],cwd=ROOT,text=True).splitlines()
    assert set(qa_changed)<=set(contract['QA_allowed_paths']) and 'scripts/verify_stt_independence_api.py' in qa_changed,qa_changed
    for name,expected in contract['native49_success']['helper_source_sha256'].items():assert digest(ROOT/name)==expected,name
    assert digest(ROOT/'scripts/verify_stt_independence_api.py')==contract['corrected_API_helper_sha256']
    run=api(f'/actions/runs/{PRODUCER}');assert run['status']=='completed' and run['conclusion']=='failure' and run['head_sha']==HEAD
    jobs=api(f'/actions/runs/{PRODUCER}/jobs')['jobs'];assert len(jobs)==1
    steps={s['number']:s for s in jobs[0]['steps']}
    assert {n for n,s in steps.items() if s['conclusion']=='failure'}=={17}
    assert all(steps[n]['conclusion']=='success' for n in range(1,17))
    assert steps[18]['conclusion']==steps[19]['conclusion']=='skipped'
    rows=api(f'/actions/runs/{PRODUCER}/artifacts')['artifacts'];assert {r['name'] for r in rows}==set(NAMES)
    for row in rows:
        assert not row['expired'] and row['workflow_run']['id']==PRODUCER and row['workflow_run']['head_sha']==HEAD
        expected=contract['outer_artifacts'][row['name']]
        assert row['id']==expected['id'] and row['digest']==expected['digest'] and row['size_in_bytes']==expected['bytes']
    artifacts=args.output/'original-artifacts';artifacts.mkdir()
    with ThreadPoolExecutor(max_workers=3) as pool:
        proofs=list(pool.map(lambda row:download(row,artifacts,NAMES[row['name']]),rows))
    shared,_=snapshot(ROOT);assert shared['source_fingerprint']==COMMON
    assert shared['core_version']=='core-9875ef91ba671541' and shared['ui_version']=='ui-9700556846beaf5f'
    assert verify(ROOT)['source_sha256']=='1ad384a31dd573d56d3145483757125eecb46e6cdd5fedaf3f1e25596a46b257'
    paths={kind:one(artifacts/kind,name) for kind,name in {
        'p01':'CardioInsight-DoctorEval-Windows-x64-1.0.14-P01-software.zip',
        'full':'CardioInsight-DoctorEval-Windows-x64-1.0.14-full.zip',
        'update':'CardioInsight-DoctorEval-Windows-x64-1.0.14-software.zip',
        'math':'CardioInsight-Synthetic-M01-24h-v1.zip'}.items()}
    build=read(one(artifacts/'full','build-report.json'))
    assert build['source_commit']==HEAD and build['production_source_identity']==verify(ROOT)
    assert build['packaging_version']=='1.0.14' and build['source_id']=='M01' and build['patient_inputs_read'] is False
    assert build['final_zip_crc_and_content_hashes_verified'] and build['final_unpacked_exe_self_check_passed'] and build['final_unpacked_exe_process_smoke_passed']
    for kind,hashkey,sizekey in [('full','archive_sha256','archive_size_bytes'),('update','software_archive_sha256','software_archive_size_bytes'),('math','source_archive_sha256','source_archive_size_bytes')]:
        assert contract['package_bytes'][kind]==dict(sha256=build[hashkey],bytes=build[sizekey])
    programs={kind:program(paths[kind],args.output/('unpacked-'+kind),kind,shared,contract) for kind in ('p01','full','update')}
    def internal(package):return {n:v for n,v in read(package/'CONTENTS.json')['files'].items() if n.startswith('_internal/')}
    assert internal(programs['p01'])==internal(programs['full'])==internal(programs['update'])
    for name,expected in contract['runtime_python_sha256'].items():assert digest(ROOT/name)==expected,name
    modules=['app.py','win_doctor_eval.py']+sorted(p.relative_to(ROOT).as_posix() for p in (ROOT/'ecg_core').glob('*.py'))
    assert set(modules)==set(contract['runtime_python_sha256']) and len(modules)==40
    reader=CArchiveReader(programs['p01']/'CardioInsightDoctorEval.exe')
    pyz=reader.open_embedded_archive(next(n for n,r in reader.toc.items() if r[-1]=='z'))
    for name in modules:
        module=name[:-3].replace('/','.');module=module[:-9] if module.endswith('.__init__') else module
        actual=marshal.loads(reader.extract('win_doctor_eval')) if name=='win_doctor_eval.py' else pyz.extract(module)
        assert normalized(actual)==normalized(compile((ROOT/name).read_bytes(),name,'exec',optimize=0,dont_inherit=True)),name
    assert digest(paths['math'])==contract['package_bytes']['math']['sha256'] and paths['math'].stat().st_size==contract['package_bytes']['math']['bytes']
    assert paths['math'].with_name(paths['math'].name+'.sha256').read_text().split()==[digest(paths['math']),paths['math'].name]
    with zipfile.ZipFile(paths['math']) as archive:
        assert archive.testzip() is None and {n for n in archive.namelist() if not n.endswith('/')}=={'M01/'+n for n in SOURCE_FILES}
        for name in SOURCE_FILES:assert hashlib.sha256(archive.read('M01/'+name)).hexdigest()==digest(programs['full']/'Sources/M01'/name)
    original=artifacts/'original-evidence'
    scope=read(one(original,'test-summary.json'));ui=read(one(original,'ui-test-summary.json'));perf=read(one(original,'windows-request-source-perf.json'))
    assert scope['status']=='passed' and scope['current']=={'total':873,'passed':872,'failed':0,'error':0,'skipped':1}
    cases=list(ET.parse(one(original,'scoped-tests.xml')).getroot().iter('testcase'))
    assert len(cases)==873 and not any(n.find('failure') is not None or n.find('error') is not None for n in cases)
    skipped=[n for n in cases if n.find('skipped') is not None]
    assert len(skipped)==1 and skipped[0].get('name')=='test_native_xattr_does_not_interrupt_unchanged_build'
    assert skipped[0].find('skipped').get('message')=='Native macOS xattr reproduction'
    assert ui['status']=='passed' and ui['declared_test_functions']==289 and ui['file_count']==115
    assert ui['current']=={'total':829,'passed':829,'failed':0,'error':0,'skipped':0}
    assert perf['status']=='passed' and perf['environment']['system']=='Windows' and perf['environment']['python']=='3.12.10'
    assert perf['summary']['fallback']['requests']==perf['summary']['request_lease']['requests']==3
    reused=contract['native49_success']
    for name,expected in reused['receipt_sha256'].items():assert digest(one(original,name))==expected,name
    native=read(one(original,'browser-validation.json'));p01=read(one(original,'p01-native.json'))
    assert native['status']==p01['status']=='passed' and len(native['checks'])==41 and len(p01['checks'])==8
    assert all(c['status']=='passed' for c in native['checks']+p01['checks'])
    assert native['scope']['native_frozen_runtime'] and native['scope']['mathematical_source_only'] and not native['scope']['pdf_open_export_download_run']
    assert native['network']['external_requests']==0 and native['network']['page_errors']==native['network']['http_errors']==native['network']['resource_failures']==[]
    assert p01['patient_inputs_read'] is False and p01['pdf_operations']==0
    failed=read(one(original,'report-evidence-native.json'))
    assert failed['status']=='failed' and failed['source_commit']==HEAD and failed['exe_sha256']==EXE and failed['archive_sha256']==contract['package_bytes']['p01']['sha256']
    assert failed['error']=='AssertionError: ' and failed['ui']['checks']==contract['failed_supplemental_checks']
    assert failed['page_errors']==failed['blocked_requests']==failed['cleanup_errors']==[]
    evidence=args.output/'evidence';shutil.copytree(original,evidence)
    prior=one(evidence,'report-evidence-native.json');prior.rename(prior.with_name('prior-report-evidence-native-failure.json'))
    oldrun=api('/actions/runs/41682881701');assert oldrun['conclusion']=='success' and oldrun['head_sha']=='6c53768e684f6bdda38fc01382e040157cf3bff6'
    old=next(r for r in api('/actions/runs/41682881701/artifacts')['artifacts'] if r['name']=='CardioInsight-Windows-x64-1.0.13-P01-software-only')
    assert not old['expired'] and old['workflow_run']['id']==41682881701 and old['workflow_run']['head_sha']==oldrun['head_sha']
    oldproof=download(old,artifacts,'base13');base=one(artifacts/'base13','CardioInsight-DoctorEval-Windows-x64-1.0.13-P01-software.zip')
    assert digest(base)=='9189488b0c953381011568a598b75330e2113561ed6755b1c2affb5661c671e5'
    native49={**reused,'run':PRODUCER,'head':HEAD,'passed_steps':[15,16],
        'all_raw_receipt_hashes_verified':True,'all_49_helper_sources_and_package_inputs_unchanged':True}
    report={'status':'fresh_producer_and_completed49_verified_remaining23_pending','producing_run':PRODUCER,'producing_commit':HEAD,
        'original_sole_failure':'step17 external request episode order expectation; original provider failure preserved',
        'source_identity':verify(ROOT),'common_source_fingerprint':COMMON,'core_version':shared['core_version'],'ui_version':shared['ui_version'],
        'EXE_sha256':EXE,'compiled_modules_verified':modules,'UI_assets_verified':80,
        'original_gates_reused':{'fresh_backend':scope['current'],'fresh_UI':ui['current'],'request_performance_repeats':3},
        'actual_native_gates_reused':True,'native49_reused_proof':native49,
        'all_original_outer_artifact_hashes_verified':proofs,'base13_fixture_proof':oldproof,
        'package_bytes':{k:{'path':str(v),'sha256':digest(v),'bytes':v.stat().st_size} for k,v in paths.items()},
        'no_original_package_repack_or_metadata_rewrite':True,'QA_only_changed_paths':qa_changed,
        'remaining_required':['ST_AF_independent14','old13_to_new14_9'],'clinical_validation':False}
    dump(evidence/'continuation-prerequisites.json',report)
    dump(args.output/'continuation-input.json',{'paths':{**{k:str(v) for k,v in paths.items()},'base13':str(base),'evidence':str(evidence)},'producing_commit':HEAD,'producing_run':PRODUCER})


if __name__=='__main__':main()

