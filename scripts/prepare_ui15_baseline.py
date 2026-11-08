"""Fetch exact accepted14 bytes for UI15; do not repack, compile or re-sign.

Original producer49 and continuation23 remain separately attributed. This
controller runs on native Windows CI; its evidence is reused baseline evidence,
never fresh execution of those72 checks.
"""
from pathlib import Path, PurePosixPath
from concurrent.futures import ThreadPoolExecutor
import argparse, hashlib, json, os, subprocess, sys, zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.windows_doctor_build import digest, verify_content_manifest
from scripts.windows_deidentified_package import unpack

def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def dump(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def one(root,name):
    paths=list(root.rglob(name));assert len(paths)==1,(name,len(paths));return paths[0]
def api(repository,path):return json.loads(subprocess.check_output(['gh','api','repos/'+repository+path],stderr=subprocess.PIPE))

def download(repository,row,destination):
    assert not destination.exists();destination.mkdir(parents=True)
    outer=destination.with_suffix('.artifact.zip')
    with outer.open('xb') as stream:subprocess.run(['gh','api',f'repos/{repository}/actions/artifacts/{row["id"]}/zip'],stdout=stream,stderr=subprocess.PIPE,check=True,timeout=360)
    expected=row.get('digest','sha256:'+row.get('sha256',''))
    assert digest(outer)==expected.removeprefix('sha256:') and outer.stat().st_size==row['bytes']
    with zipfile.ZipFile(outer) as archive:
        names=archive.namelist();assert len(names)==len(set(names))==len({n.casefold() for n in names}) and archive.testzip() is None
        for item in archive.infolist():
            name=PurePosixPath(item.filename)
            assert not name.is_absolute() and '..' not in name.parts and '\\' not in item.filename and not any(':' in p for p in name.parts)
            assert (item.external_attr>>16)&0o170000!=0o120000
        archive.extractall(destination)
    return dict(id=row['id'],sha256=digest(outer),bytes=outer.stat().st_size,path=str(destination))

def verify_runtime_source(contract):
    paths={'app.py','win_doctor_eval.py'}|{p.relative_to(ROOT).as_posix() for p in (ROOT/'ecg_core').glob('*.py')}
    expected=contract['immutable_Windows_runtime_python_source_sha256']
    assert paths==set(expected) and len(paths)==40
    for name,wanted in expected.items():assert digest(ROOT/name)==wanted,'Immutable clinical runtime changed: '+name
    return sorted(paths)

def main():
    p=argparse.ArgumentParser();p.add_argument('--repository',default='xiaozidian/ECG_Software');p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    assert os.name=='nt','Actual baseline composition is a native Windows CI step'
    assert not a.output.exists();a.output.mkdir(parents=True)
    c=read(ROOT/'scripts/ui15-baseline-contract.json');verify_runtime_source(c)
    producer=c['producer_contract'];run=api(a.repository,f'/actions/runs/{c["base_binary_ci_run"]}')
    assert (run['status'],run['conclusion'],run['head_sha'])==('completed','failure',c['base_binary_source_commit'])
    jobs=api(a.repository,f'/actions/runs/{run["id"]}/jobs')['jobs'];assert len(jobs)==1
    steps={s['number']:s for s in jobs[0]['steps']};assert {n for n,s in steps.items() if s['conclusion']=='failure'}=={17}
    assert all(steps[n]['conclusion']=='success' for n in range(1,17))
    validation=api(a.repository,f'/actions/runs/{c["accepted_base_validation_run"]}')
    assert (validation['status'],validation['conclusion'],validation['head_sha'])==('completed','success',c['accepted_base_validation_commit'])
    rows=api(a.repository,f'/actions/runs/{run["id"]}/artifacts')['artifacts'];assert {r['name'] for r in rows}==set(producer['outer_artifacts'])
    tasks=[]
    for row in rows:
        expected=producer['outer_artifacts'][row['name']]
        assert not row['expired'] and all(row[k]==expected[k] for k in ('id','digest')) and row['size_in_bytes']==expected['bytes']
        assert row['workflow_run']['id']==run['id'] and row['workflow_run']['head_sha']==run['head_sha']
        tasks.append((expected,a.output/('artifact-'+str(row['id']))))
    accepted=c['accepted_validation_outer_artifact'];rows2=api(a.repository,f'/actions/runs/{validation["id"]}/artifacts')['artifacts']
    row=next(r for r in rows2 if r['id']==accepted['id'])
    assert not row['expired'] and row['digest']=='sha256:'+accepted['sha256'] and row['size_in_bytes']==accepted['bytes']
    assert row['workflow_run']['id']==validation['id'] and row['workflow_run']['head_sha']==validation['head_sha']
    tasks.append((accepted,a.output/'accepted-validation'))
    with ThreadPoolExecutor(max_workers=3) as pool:proofs=list(pool.map(lambda item:download(a.repository,*item),tasks))
    final=a.output/'accepted-validation'
    actual={p.relative_to(final).as_posix():dict(sha256=digest(p),bytes=p.stat().st_size) for p in final.rglob('*') if p.is_file()}
    assert actual==c['accepted_validation_member_hashes'],'Accepted continuation contents differ'
    for name,wanted in c['raw_native_receipt_sha256'].items():assert digest(one(final,name))==wanted,name
    native=read(one(final,'browser-validation.json'));p01=read(one(final,'p01-native.json'));supp=read(one(final,'report-evidence-native.json'));upgrade=read(one(final,'stt-independent-upgrade-native.json'))
    assert native['status']==p01['status']==supp['status']==upgrade['status']=='passed'
    assert len(native['checks'])==41 and len(p01['checks'])==8 and len(supp['ui']['checks'])==14 and len(upgrade['checks'])==9
    assert all(r['status']=='passed' for r in native['checks']+p01['checks'])
    paths={}
    for kind,description in c['base_archives'].items():
        archive=one(a.output,description['filename']);assert digest(archive)==description['sha256'] and archive.stat().st_size==description['bytes']
        assert archive.with_name(archive.name+'.sha256').read_text().split()==[digest(archive),archive.name]
        paths[kind]=str(archive)
    with zipfile.ZipFile(Path(paths['M01_math_data'])) as archive:assert archive.testzip() is None
    for kind in ('P01_software','M01_full','M01_update'):
        program=unpack(Path(paths[kind]),a.output/('verify-'+kind));verify_content_manifest(program)
        release=read(program/'RELEASE.json');shared=read(program/'_internal/shared-source-build.json')
        assert release['packaging_version']=='1.0.14' and release['app_version']==c['base_application_version']
        assert release['source_commit']==c['base_binary_source_commit'] and shared==c['base_common_stamp']
        assert release['production_source_identity']['source_sha256']==c['base_Windows_production_source_sha256']
        assert digest(program/'CardioInsightDoctorEval.exe')==c['base_EXE_sha256']
    proof=dict(status='verified_baseline14_reused_not_new_UI15_acceptance',producer_run=run['id'],producer_conclusion='failure',producer49_reused=True,
        accepted_validation_run=validation['id'],continuation23_reused=True,original72_composed_not_rerun=True,outer_artifact_proofs=proofs,
        immutable_runtime_files=verify_runtime_source(c),base_EXE_sha256=c['base_EXE_sha256'],paths=paths,
        new_UI15_native_acceptance='pending',clinical_validation=False)
    dump(a.output/'baseline-proof.json',proof);print(json.dumps({k:v for k,v in proof.items() if k not in ('outer_artifact_proofs','paths','immutable_runtime_files')}))

if __name__=='__main__':main()
