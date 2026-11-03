"""Repack existing80 UI files, retaining exact previously built Windows runtime.

No compiler/PyInstaller invocation. Baseline ZIPs are verified before extraction;
all non-UI internal files and the EXE must remain byte-for-byte unchanged.
"""
from pathlib import Path
import argparse,hashlib,json,os,shutil,subprocess,sys,tempfile
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from windows_deidentified_package import unpack,archive
from windows_doctor_build import create_content_manifest,verify_content_manifest,regular_files,PACKAGE_NAME,digest
from scripts.shared_source import snapshot
from scripts.verify_public_release import verify
APP='0.12.27-report-evidence.20261103';UI=APP+'-ui2'
BASE_PRODUCTION='45162d78cd5aa35bde8487d421cd34c9700d5ee7e4a58e8550fc107091f55fe2'

def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def find(root,name):
 values=list(root.rglob(name));assert len(values)==1,(name,len(values));return values[0]
def hashes(root):return {n:digest(p) for n,p in regular_files(root).items()}
def sidecar(p):assert p.with_name(p.name+'.sha256').read_text().strip().split()==[digest(p),p.name]

def patch(args,kind,input_zip,shared,ui_assets):
 sidecar(input_zip)
 folder=args.output/('repack-'+kind);package=unpack(input_zip,folder);verify_content_manifest(package)
 release=json.loads((package/'RELEASE.json').read_text(encoding='utf-8'))
 assert release['packaging_version']=='1.0.11' and release['app_version']==release['software_version']==APP
 assert release['production_source_identity']['source_sha256']==BASE_PRODUCTION
 assert release['source_commit']==args.base_commit
 before=hashes(package);exe=before['CardioInsightDoctorEval.exe'];assert exe==args.base_exe_sha256
 oldstamp=json.loads((package/'_internal/shared-source-build.json').read_text())
 assert oldstamp['core_version']==shared['core_version']=='core-109535b780dbfc0a'
 assert {n for n,v in oldstamp['files'].items() if v['component']=='ui'}==set(ui_assets)
 for name in ui_assets:
  destination=package/'_internal'/name;assert destination.is_file();destination.write_bytes((ROOT/name).read_bytes())
 (package/'_internal/shared-source-build.json').write_bytes((ROOT/'shared-source-build.json').read_bytes())
 release.update(packaging_version='1.0.12',release_version='1.0.12',ui_release_id=UI,
  source_commit=args.source_commit,production_source_identity=verify(ROOT),
  base_binary_source_commit=args.base_commit,base_binary_ci_run=args.base_run,
  base_binary_exe_sha256=exe,binary_reused_without_rebuild=True,
  ui_repack_only=True,release_notes='报告波形高度与显示增益修订；原分析引擎、工作库和已审核图条依据保持。',
  ci_run_url=args.ci_run_url)
 dump(package/'RELEASE.json',release)
 (package/'版本说明.txt').write_text('1.0.12 / UI2：报告波形高度与显示增益修订；复用1.0.11分析引擎。\n',encoding='utf-8-sig')
 with_source=kind=='full';create_content_manifest(package,with_source=with_source);verify_content_manifest(package)
 after=hashes(package);allowed={'_internal/'+n for n in ui_assets}|{'_internal/shared-source-build.json','RELEASE.json','版本说明.txt','CONTENTS.json','SHA256SUMS.txt'}
 assert set(before)==set(after),'Repack added/removed a package file'
 changed={n for n in before if before[n]!=after[n]};assert changed<=allowed,sorted(changed-allowed)
 assert after['CardioInsightDoctorEval.exe']==exe
 non_ui={n for n in before if n.startswith('_internal/') and n not in allowed}
 assert non_ui and all(before[n]==after[n] for n in non_ui)
 if with_source:assert all(before[n]==after[n] for n in before if n.startswith('Sources/'))
 suffix={'full':'full','update':'software','p01':'P01-software'}[kind]
 result=archive(package,args.output,f'{PACKAGE_NAME}-1.0.12-{suffix}.zip')
 result.update(kind=kind,base_archive_sha256=digest(input_zip),base_source_commit=args.base_commit,
  source_commit=args.source_commit,exe_sha256=exe,production_source_identity=verify(ROOT),
  changed_files=sorted(changed),unchanged_non_UI_internal_files=len(non_ui),
  every_non_UI_internal_file_byte_equal=True,exact_exe_reused=True,patient_data_in_artifact=False)
 return package,release,result

def main():
 p=argparse.ArgumentParser();p.add_argument('--base-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
 p.add_argument('--source-commit',required=True);p.add_argument('--base-commit',required=True);p.add_argument('--base-run',required=True)
 p.add_argument('--base-exe-sha256',required=True);p.add_argument('--ci-run-url',required=True);a=p.parse_args()
 assert os.name=='nt','Repack runs on native Windows; no claim from local draft'
 assert not a.output.exists(),'Preserve prior output';a.output.mkdir(parents=True)
 assert len(a.base_exe_sha256)==64
 shared,payload=snapshot(ROOT);assert shared==json.loads((ROOT/'shared-source-build.json').read_text())
 assets=[n for n,v in shared['files'].items() if v['component']=='ui'];assert len(assets)==80
 results={};packages={};releases={}
 for kind,name in [('full',PACKAGE_NAME+'-1.0.11-full.zip'),('update',PACKAGE_NAME+'-1.0.11-software.zip'),('p01',PACKAGE_NAME+'-1.0.11-P01-software.zip')]:
  packages[kind],releases[kind],results[kind]=patch(a,kind,find(a.base_root,name),shared,assets)
 # Retain the original synthetic input without regeneration or transformation.
 data=find(a.base_root,'CardioInsight-Synthetic-M01-24h-v1.zip');sidecar(data)
 for item in [data,data.with_name(data.name+'.sha256')]:shutil.copyfile(item,a.output/item.name)
 # Original full native acceptance expects an extracted M01 program and a
 # later packaging-only fixture. Both keep the same newly patched UI/runtime.
 shutil.copytree(packages['full'],a.output/'verify-package'/PACKAGE_NAME)
 fixture=a.output/'upgrade-fixture'/PACKAGE_NAME;shutil.copytree(packages['update'],fixture)
 release=dict(releases['update'],packaging_version='1.0.13',release_version='1.0.13',verification_fixture_only=True,
  verification_scope='same frozen binary/schema and UI; CI packaging fixture only')
 dump(fixture/'RELEASE.json',release);create_content_manifest(fixture,with_source=False);verify_content_manifest(fixture)
 fixture_result=archive(fixture,a.output,PACKAGE_NAME+'-1.0.13-upgrade-fixture.zip')
 # Copy the already verified synthetic M01 source for retained native helpers.
 source_target=Path(os.environ['ECG_DATA_ROOT'])
 if source_target.exists():assert hashes(source_target)==hashes(packages['full']/'Sources/M01'),'Generated full-day source differs from baseline'
 else:shutil.copytree(packages['full']/'Sources/M01',source_target)
 # Actual EXE self-check under stripped runtime PATH; compilation is forbidden.
 env={k:v for k,v in os.environ.items() if not k.startswith(('PYTHON','ECG_'))};system=os.environ['SystemRoot'];env['PATH']=str(Path(system)/'System32')+os.pathsep+system
 with tempfile.TemporaryDirectory(prefix='ui2-exe-smoke-',dir=a.output) as temp:
  for flag in ['--self-check','--smoke-test']:subprocess.run([str((a.output/'verify-package'/PACKAGE_NAME/'CardioInsightDoctorEval.exe').resolve()),flag],cwd=temp,env=env,check=True)
 build={**releases['full'],'archive':results['full']['archive'],'archive_sha256':results['full']['sha256'],
  'software_archive':results['update']['archive'],'software_archive_sha256':results['update']['sha256'],
  'source_archive':data.name,'source_archive_sha256':digest(data),'verification_upgrade_fixture':{
   'archive':fixture_result['archive'],'sha256':fixture_result['sha256'],'from_packaging_version':'1.0.12','to_packaging_version':'1.0.13','same_production_source':True,'user_deliverable':False,'scope':'fixture_same_schema_upgrade'},
  'final_zip_crc_and_content_hashes_verified':True,'final_unpacked_exe_self_check_passed':True,'final_unpacked_exe_process_smoke_passed':True,
  'python_removed_from_runtime_path':True,'ui_repack_results':results,'no_PyInstaller_or_compiler_invoked':True}
 dump(a.output/'build-report.json',build)
 p01dir=a.output.parent/'doctor-p01';p01dir.mkdir(exist_ok=False)
 for name in [results['p01']['archive'],results['p01']['archive']+'.sha256']:shutil.copyfile(a.output/name,p01dir/name)
 dump(p01dir/'p01-software-build-report.json',dict(results['p01'],status='passed',source_profile='P01',patient_data_in_artifact=False))
 dump(a.output/'ui-repack-verification.json',{'status':'passed','app_version':APP,'ui_release_id':UI,'packaging_version':'1.0.12','base_run':a.base_run,'base_commit':a.base_commit,'base_exe_sha256':a.base_exe_sha256,'core_version':shared['core_version'],'ui_version':shared['ui_version'],'assets':len(assets),'results':results,'no_binary_rebuild':True,'actual_native_feature_acceptance':'separate required workflow steps'})
 print(json.dumps({'status':'repacked','base_exe_sha256':a.base_exe_sha256,'no_binary_rebuild':True,'native_acceptance':'pending'}))
if __name__=='__main__':main()
