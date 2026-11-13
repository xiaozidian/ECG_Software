"""Fetch one authenticated producer's original22 archives for independent native checks.
No compilation/repackaging, no clinical input discovery and no inference from old acceptance.
"""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.prepare_ui15_baseline import api,download,dump,one
from scripts.windows_doctor_build import digest,verify_content_manifest
from scripts.windows_deidentified_package import unpack
REPO='xiaozidian/ECG_Software'
EXPECTED_WORKFLOW='Windows1.0.22 ST-T screening candidate producer'
NAMES={'p01':'CardioInsight-Windows-x64-1.0.22-P01-software-only',
       'software_full':'CardioInsight-Windows-x64-1.0.22-M01-software-and-full'}
def prepare(args):
    assert not args.output.exists(),'Preserve previous candidate attempts'
    assert len(args.commit)==40 and all(c in '0123456789abcdef' for c in args.commit)
    run=api(REPO,f'/actions/runs/{args.run}')
    assert (run['status'],run['conclusion'],run['head_sha'],run['name'])==('completed','success',args.commit,EXPECTED_WORKFLOW)
    assert run['event']=='workflow_dispatch'
    rows=api(REPO,f'/actions/runs/{args.run}/artifacts')['artifacts']
    args.output.mkdir(parents=True);outer={};paths={}
    for role,name in NAMES.items():
        selected=[r for r in rows if not r['expired'] and r['name']==name];assert len(selected)==1,name
        row=selected[0];assert row['workflow_run']['id']==args.run and row['workflow_run']['head_sha']==args.commit
        assert row['digest'].startswith('sha256:') and len(row['digest'])==71
        wanted={**row,'bytes':row['size_in_bytes']}
        outer[role]=download(REPO,wanted,args.output/role)
    for role,outerrole in [('p01','p01'),('full','software_full'),('software','software_full')]:
        name=f'CardioInsight-DoctorEval-Windows-x64-1.0.22-'+('P01-software' if role=='p01' else role)+'.zip'
        f=one(args.output/outerrole,name);side=f.with_name(f.name+'.sha256')
        assert side.read_text(encoding='utf-8-sig').split()==[digest(f),f.name]
        paths[role]=str(f)
    full=unpack(Path(paths['full']),args.output/'full-program')
    verify_content_manifest(full)
    release=json.loads((full/'RELEASE.json').read_text(encoding='utf-8-sig'))
    assert release['packaging_version']=='1.0.22' and release['source_commit']==args.commit
    identity=release['production_source_identity']
    verify=__import__('scripts.verify_public_release',fromlist=['verify']).verify(ROOT)
    assert identity['release_id']==verify['release_id']=='0.12.33-stt-candidate-quality.20261113'
    assert identity['source_sha256']==verify['source_sha256'] and identity['production_files_verified']==141
    p01=unpack(Path(paths['p01']),args.output/'p01-program');verify_content_manifest(p01)
    assert digest(p01/'CardioInsightDoctorEval.exe')==digest(full/'CardioInsightDoctorEval.exe')
    for resource in ['screening-parent-engines.json','screening-refinement-compatibility.json']:
        assert (full/'_internal'/resource).read_bytes()==(ROOT/resource).read_bytes(),resource
    paths['full_root']=str(full);paths['p01_root']=str(p01)
    value={'status':'producer22-original-inputs-verified-only','producer_run':args.run,'producer_commit':args.commit,
           'producer_run_record':run,'artifacts':outer,'paths':paths,'expected_production':verify,
           'new22_native_tests_executed':False,'clinical_inputs_read':False}
    dump(args.output/'candidate22-input.json',value)
    print(json.dumps({'producer_run':args.run,'producer_commit':args.commit,'paths':paths}))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=int,required=True);p.add_argument('--commit',required=True);p.add_argument('--output',type=Path,required=True);prepare(p.parse_args())
