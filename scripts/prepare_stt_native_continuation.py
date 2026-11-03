"""Bind this release's fresh PE and passed scopes; rerun every native gate.

No original package is edited or rebuilt. The separate wrapper-version fixture
is only the original native test's same-core upgrade input, never a deliverable.
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
from scripts.windows_doctor_build import (verify_content_manifest, digest, SOURCE_FILES,
    create_content_manifest, archive_and_extract, write_json)
from PyInstaller.archive.readers import CArchiveReader

REPO = 'xiaozidian/ECG_Software'
PRODUCER = 41668322230
HEAD = '8f275e793134ce9f51992609d90bbdefe4eccf2c'
EXE = '881e82ef8d9490a54e2642e0a0d94178cef0c6f1e27385e5a98e18154a2a1737'
COMMON = '20336a25ae1f52a023370f6992a21a1f4a463fa91bc08365431cf441e90ebba3'
NAMES = {'CardioInsight-Windows-x64-1.0.13-P01-software-only':'p01',
 'CardioInsight-Windows-x64-1.0.13-M01-full':'full',
 'CardioInsight-Windows-x64-1.0.13-software-update':'update',
 'CardioInsight-Synthetic-M01-24h-v1-for-1.0.13':'math',
 'Windows-doctor-eval-mathematical-validation-1.0.13':'original-evidence'}


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
    assert release['source_commit']==HEAD and release['packaging_version']=='1.0.13'
    assert release['app_version']=='0.12.28-stt-hospital.20261103'
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
    contract=read(ROOT/'scripts/stt-native-continuation-contract.json')
    assert contract['producing_run']==PRODUCER and contract['producing_commit']==HEAD and contract['EXE_sha256']==EXE
    run=api(f'/actions/runs/{PRODUCER}');assert run['status']=='completed' and run['conclusion']=='failure' and run['head_sha']==HEAD
    jobs=api(f'/actions/runs/{PRODUCER}/jobs')['jobs'];assert len(jobs)==1
    steps={s['number']:s for s in jobs[0]['steps']}
    assert {n for n,s in steps.items() if s['conclusion']=='failure'}=={15}
    assert all(steps[n]['conclusion']=='success' for n in range(1,15))
    rows=api(f'/actions/runs/{PRODUCER}/artifacts')['artifacts'];assert {r['name'] for r in rows}==set(NAMES)
    for row in rows:
        assert not row['expired'] and row['workflow_run']['id']==PRODUCER and row['workflow_run']['head_sha']==HEAD
        expected=contract['outer_artifacts'][row['name']]
        assert row['id']==expected['id'] and row['digest']==expected['digest'] and row['size_in_bytes']==expected['bytes']
    artifacts=args.output/'original-artifacts';artifacts.mkdir()
    with ThreadPoolExecutor(max_workers=3) as pool:
        proofs=list(pool.map(lambda row:download(row,artifacts,NAMES[row['name']]),rows))
    shared,_=snapshot(ROOT);assert shared['source_fingerprint']==COMMON
    assert shared['core_version']=='core-4151b74942843a73' and shared['ui_version']=='ui-d28fa0b393dd4bfa'
    assert verify(ROOT)['source_sha256']=='13eb6d79462cbc335200d66ba817c924e8ca9eb9085518a38aa38ad901c6e5b9'
    paths={kind:one(artifacts/kind,name) for kind,name in {
        'p01':'CardioInsight-DoctorEval-Windows-x64-1.0.13-P01-software.zip',
        'full':'CardioInsight-DoctorEval-Windows-x64-1.0.13-full.zip',
        'update':'CardioInsight-DoctorEval-Windows-x64-1.0.13-software.zip',
        'math':'CardioInsight-Synthetic-M01-24h-v1.zip'}.items()}
    build=read(one(artifacts/'full','build-report.json'))
    assert build['source_commit']==HEAD and build['production_source_identity']==verify(ROOT)
    assert build['packaging_version']=='1.0.13' and build['source_id']=='M01'
    assert build['patient_inputs_read'] is False and build['final_zip_crc_and_content_hashes_verified']
    assert build['final_unpacked_exe_self_check_passed'] and build['final_unpacked_exe_process_smoke_passed']
    for kind,hashkey,sizekey in [('full','archive_sha256','archive_size_bytes'),
            ('update','software_archive_sha256','software_archive_size_bytes'),
            ('math','source_archive_sha256','source_archive_size_bytes')]:
        contract['package_bytes'][kind]={'sha256':build[hashkey],'bytes':build[sizekey]}
    programs={kind:program(paths[kind],args.output/('unpacked-'+kind),kind,shared,contract) for kind in ('p01','full','update')}
    def internal(package): return {n:v for n,v in read(package/'CONTENTS.json')['files'].items() if n.startswith('_internal/')}
    assert internal(programs['p01'])==internal(programs['full'])==internal(programs['update'])
    for name,expected in contract['runtime_python_sha256'].items():assert digest(ROOT/name)==expected,name
    modules=['app.py','win_doctor_eval.py']+sorted(p.relative_to(ROOT).as_posix() for p in (ROOT/'ecg_core').glob('*.py'))
    assert set(modules)==set(contract['runtime_python_sha256']) and len(modules)==40
    reader=CArchiveReader(programs['p01']/'CardioInsightDoctorEval.exe')
    pyz=reader.open_embedded_archive(next(n for n,r in reader.toc.items() if r[-1]=='z'))
    for name in modules:
        module=name[:-3].replace('/','.');module=module[:-9] if module.endswith('.__init__') else module
        actual=marshal.loads(reader.extract('win_doctor_eval')) if name=='win_doctor_eval.py' else pyz.extract(module)
        assert normalized(actual)==normalized(compile((ROOT/name).read_bytes(),name,'exec',optimize=0)),name
    assert digest(paths['math'])==contract['package_bytes']['math']['sha256']
    assert paths['math'].stat().st_size==contract['package_bytes']['math']['bytes']
    assert paths['math'].with_name(paths['math'].name+'.sha256').read_text().split()==[digest(paths['math']),paths['math'].name]
    with zipfile.ZipFile(paths['math']) as archive:
        assert archive.testzip() is None and {n for n in archive.namelist() if not n.endswith('/')}=={'M01/'+n for n in SOURCE_FILES}
        for name in SOURCE_FILES:assert hashlib.sha256(archive.read('M01/'+name)).hexdigest()==digest(programs['full']/'Sources/M01'/name)
    original=artifacts/'original-evidence'
    scope=read(one(original,'test-summary.json'));ui=read(one(original,'ui-test-summary.json'));perf=read(one(original,'windows-request-source-perf.json'))
    assert scope['status']=='passed' and scope['current']=={'total':851,'passed':850,'failed':0,'error':0,'skipped':1}
    testcases=list(ET.parse(one(original,'scoped-tests.xml')).getroot().iter('testcase'))
    assert len(testcases)==851 and not any(n.find('failure') is not None or n.find('error') is not None for n in testcases)
    skipped=[n for n in testcases if n.find('skipped') is not None]
    assert len(skipped)==1 and skipped[0].get('name')=='test_native_xattr_does_not_interrupt_unchanged_build'
    assert skipped[0].find('skipped').get('message')=='Native macOS xattr reproduction'
    assert ui['status']=='passed' and ui['declared_test_functions']==280 and ui['file_count']==113
    assert ui['current']=={'total':807,'passed':807,'failed':0,'error':0,'skipped':0}
    assert perf['status']=='passed' and perf['environment']['system']=='Windows' and perf['environment']['python']=='3.12.10'
    assert perf['summary']['fallback']['requests']==perf['summary']['request_lease']['requests']==3
    failed=read(one(original,'browser-validation.json'))
    assert failed['status']=='failed' and len(failed['checks'])==4
    assert [c['status'] for c in failed['checks']]==['passed']*3+['failed']
    error=failed['checks'][-1]['evidence']['error']
    assert 'Locator.fill' in error and '[data-sttr-start]' in error and 'not visible' in error
    assert failed['network']['page_errors']==failed['network']['http_errors']==failed['network']['resource_failures']==[]
    assert failed['network']['external_requests']==0
    evidence=args.output/'evidence';shutil.copytree(original,evidence)
    prior=one(evidence,'browser-validation.json');prior.rename(prior.with_name('prior-browser-validation-failure.json'))
    completed=contract['native61_success']
    completed_run=api(f'/actions/runs/{completed["run"]}')
    assert completed_run['head_sha']==completed['head'] and completed_run['status']=='completed' and completed_run['conclusion']=='failure'
    completed_jobs=api(f'/actions/runs/{completed["run"]}/jobs')['jobs'];assert len(completed_jobs)==1
    completed_steps={s['number']:s for s in completed_jobs[0]['steps']}
    assert {n for n,s in completed_steps.items() if s['conclusion']=='failure'}=={10}
    assert all(completed_steps[n]['conclusion']=='success' for n in [6,7,8,9])
    completed_row=next(r for r in api(f'/actions/runs/{completed["run"]}/artifacts')['artifacts'] if r['name']==completed['artifact']['name'])
    assert completed_row['id']==completed['artifact']['id'] and completed_row['digest']==completed['artifact']['digest']
    assert completed_row['size_in_bytes']==completed['artifact']['bytes'] and not completed_row['expired']
    assert completed_row['workflow_run']['id']==completed['run'] and completed_row['workflow_run']['head_sha']==completed['head']
    completed_outer=download(completed_row,artifacts,'native61')
    for name,expected in completed['helper_source_sha256'].items():assert digest(ROOT/name)==expected,name
    for name,expected in completed['receipt_sha256'].items():
        saved=one(artifacts/'native61',name);assert digest(saved)==expected,name
        shutil.copy2(saved,evidence/name)
    saved_native=read(evidence/'browser-validation.json');saved_P01=read(evidence/'p01-native.json');saved_ST=read(evidence/'report-evidence-native.json')
    assert saved_native['status']==saved_P01['status']==saved_ST['status']=='passed'
    assert len(saved_native['checks'])==41 and all(c['status']=='passed' for c in saved_native['checks'])
    assert len(saved_P01['checks'])==8 and all(c['status']=='passed' for c in saved_P01['checks'])
    assert saved_ST['source_commit']==HEAD and saved_ST['exe_sha256']==EXE
    assert saved_ST['archive_sha256']==contract['package_bytes']['p01']['sha256']
    assert saved_ST['ui']['status']=='passed' and len(saved_ST['ui']['checks'])==12
    assert all(digest(paths[k])==expected for k,expected in completed['input_package_SHA'].items())
    failed_upgrade=read(one(artifacts/'native61','stt-hospital-upgrade-native.json'))
    assert failed_upgrade['status']=='failed' and failed_upgrade['checks']==[]
    assert completed['prior_error'] in failed_upgrade['error']
    assert all(failed_upgrade.get(k) is None for k in ['before_reviewed','api_upgrade','database_upgrade'])
    shutil.copy2(one(artifacts/'native61','stt-hospital-upgrade-native.json'),evidence/'prior-stt-hospital-upgrade-failure.json')
    native61_proof={**completed,'outer_download':completed_outer,'passed_steps':[7,8,9],
        'all_raw_receipt_hashes_verified':True,'all_61_helper_sources_and_package_inputs_unchanged':True}
    oldrun=api('/actions/runs/41614325648');assert oldrun['conclusion']=='success' and oldrun['head_sha']=='b681f6a52c9746ebfd9502deab5a5a38cac10a8e'
    old=next(r for r in api('/actions/runs/41614325648/artifacts')['artifacts'] if r['name']=='CardioInsight-Windows-x64-1.0.12-P01-software-only')
    assert not old['expired'] and old['workflow_run']['id']==41614325648
    assert old['workflow_run']['head_sha']==oldrun['head_sha']
    oldproof=download(old,artifacts,'base12');base=one(artifacts/'base12','CardioInsight-DoctorEval-Windows-x64-1.0.12-P01-software.zip')
    assert digest(base)=='5628021c052a035103a4999e2b41d7c5969a3da4a1e8fd5aad6802fe443f213b'
    fixture=args.output/'wrapper-upgrade-fixture/CardioInsight-DoctorEval-Windows-x64'
    shutil.copytree(programs['update'],fixture)
    release=read(fixture/'RELEASE.json');release.update(packaging_version='1.0.14',release_version='1.0.14',verification_fixture_only=True,verification_scope='same frozen algorithm and schema; packaging version upgrade only')
    write_json(fixture/'RELEASE.json',release)
    (fixture/'版本说明.txt').write_text('仅CI同冻结算法包装版本升级夹具，不是用户发布。\n',encoding='utf-8-sig')
    create_content_manifest(fixture,with_source=False)
    fixture_zip,fixture_sha,_=archive_and_extract(fixture,args.output,'CardioInsight-DoctorEval-Windows-x64-1.0.14-upgrade-fixture.zip',with_source=False,verify_subdir='verify-upgrade-fixture')
    original_files=read(programs['update']/'CONTENTS.json')['files'];fixture_files=read(fixture/'CONTENTS.json')['files']
    assert set(original_files)==set(fixture_files)
    assert {n for n in original_files if original_files[n]!=fixture_files[n]}=={'RELEASE.json','版本说明.txt'}
    report={'status':'fresh_producer_and_completed61_verified_upgrade9_pending','producing_run':PRODUCER,'producing_commit':HEAD,
        'original_sole_failure':'step15 obsolete hidden ST range selector; no native completion claim',
        'source_identity':verify(ROOT),'common_source_fingerprint':COMMON,'core_version':shared['core_version'],'ui_version':shared['ui_version'],
        'EXE_sha256':EXE,'compiled_modules_verified':modules,'UI_assets_verified':80,
        'original_gates_reused':{'fresh_backend':scope['current'],'fresh_UI':ui['current'],'request_performance_repeats':3},
        'actual_native_gates_reused':True,'native61_reused_proof':native61_proof,
        'all_original_outer_artifact_hashes_verified':proofs,'base12_fixture_proof':oldproof,
        'package_bytes':{k:{'path':str(v),'sha256':digest(v),'bytes':v.stat().st_size} for k,v in paths.items()},
        'no_original_package_repack_or_metadata_rewrite':True,'wrapper_upgrade_fixture':{'sha256':fixture_sha,'user_deliverable':False,'allowed_changed_payloads':['RELEASE.json','版本说明.txt']},
        'remaining_required':['old12_to_new13_9'],'clinical_validation':False}
    dump(evidence/'continuation-prerequisites.json',report)
    dump(args.output/'continuation-input.json',{'paths':{**{k:str(v) for k,v in paths.items()},'base12':str(base),'evidence':str(evidence),
        'full_root':str(programs['full']),'math_root':str(programs['full']/'Sources/M01'),'upgrade_fixture':str(fixture_zip)},'producing_commit':HEAD,'producing_run':PRODUCER})
    print(json.dumps({'status':'strict_fresh_producer_and_completed61_prerequisites_passed','source_commit':HEAD,'compiled40':True,'completed_native61_raw_bytes_verified':True,'actual_upgrade9_pending':True}))


if __name__=='__main__':main()
