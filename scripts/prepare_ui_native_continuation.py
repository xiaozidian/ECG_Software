"""Reuse immutable UI2 packages and passed gates; require the remaining native gates."""
from pathlib import Path,PurePosixPath
from concurrent.futures import ThreadPoolExecutor
import argparse,hashlib,json,marshal,os,shutil,subprocess,tempfile,types,zipfile,sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts.verify_public_release import verify as verify_source
from scripts.shared_source import snapshot
from scripts.windows_deidentified_package import unpack
from scripts.windows_doctor_build import verify_content_manifest,digest,SOURCE_FILES
from PyInstaller.archive.readers import CArchiveReader
REPO='xiaozidian/ECG_Software';PRODUCER=41608552963;HEAD='7a9ab5fce1a39908090e26d3f051a45b57bad3c5'
EXE='6f6de01b7935c9da8a63cfb5f140289335e8636590b4aa04ce0f1c6729b79a7d'
NAMES={'CardioInsight-Windows-x64-1.0.12-P01-software-only':'p01','CardioInsight-Windows-x64-1.0.12-M01-full':'full','CardioInsight-Windows-x64-1.0.12-software-update':'update','CardioInsight-Synthetic-M01-24h-v1-for-1.0.12':'math','Windows-doctor-eval-mathematical-validation-1.0.12':'original-evidence'}
def api(path):return json.loads(subprocess.check_output(['gh','api','repos/'+REPO+path],stderr=subprocess.PIPE))
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def dump(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def one(root,name):
 p=list(root.rglob(name));assert len(p)==1,(name,len(p));return p[0]
def normalized(c):return c.replace(co_filename='<reviewed>',co_consts=tuple(normalized(x) for x in c.co_consts)) if isinstance(c,types.CodeType) else c

def download(row,root,label):
 p=root/(label+'.artifact.zip')
 with p.open('wb') as stream:subprocess.run(['gh','api',f'repos/{REPO}/actions/artifacts/{row["id"]}/zip'],stdout=stream,stderr=subprocess.PIPE,check=True,timeout=240)
 assert row['digest']=='sha256:'+digest(p),'Whole GitHub artifact digest mismatch'
 dst=root/label
 with zipfile.ZipFile(p) as z:
  names=z.namelist();assert len(names)==len(set(names))==len({n.casefold() for n in names}) and z.testzip() is None
  for v in z.infolist():
   q=PurePosixPath(v.filename);assert not q.is_absolute() and '..' not in q.parts and '\\' not in v.filename and not any(':' in x for x in q.parts)
   assert (v.external_attr>>16)&0o170000!=0o120000
  z.extractall(dst)
 return {'id':row['id'],'name':row['name'],'GitHub_digest_verified':digest(p),'workflow_run':row['workflow_run'],'extracted':str(dst)}

def check_program(path,destination,profile,shared):
 assert path.with_name(path.name+'.sha256').read_text().strip().split()==[digest(path),path.name]
 package=unpack(path,destination);verify_content_manifest(package);r=read(package/'RELEASE.json')
 assert r['source_commit']==HEAD and r['packaging_version']=='1.0.12' and r['app_version']=='0.12.27-report-evidence.20261103'
 assert r['production_source_identity']==verify_source(ROOT) and r['source_id']==profile
 assert read(package/'_internal/shared-source-build.json')==shared
 assets=[n for n,v in shared['files'].items() if v['component']=='ui'];assert len(assets)==80
 for n in assets:assert (package/'_internal'/n).read_bytes()==(ROOT/n).read_bytes(),n
 assert digest(package/'CardioInsightDoctorEval.exe')==EXE and r['binary_reused_without_rebuild']
 return package,r

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();assert os.name=='nt';assert not a.output.exists();a.output.mkdir(parents=True)
 run=api(f'/actions/runs/{PRODUCER}');assert run['status']=='completed' and run['conclusion']=='failure' and run['head_sha']==HEAD
 jobs=api(f'/actions/runs/{PRODUCER}/jobs')['jobs'];assert len(jobs)==1;steps={s['number']:s for s in jobs[0]['steps']}
 assert {s['number'] for s in steps.values() if s['conclusion']=='failure'}=={16}
 assert all(steps[n]['conclusion']=='success' for n in [11,12,13,14,15])
 rows=api(f'/actions/runs/{PRODUCER}/artifacts')['artifacts'];assert {r['name'] for r in rows}==set(NAMES)
 assert all(r['workflow_run']['head_sha']==HEAD and r['workflow_run']['id']==PRODUCER and not r['expired'] for r in rows)
 root=a.output/'original-artifacts';root.mkdir();
 with ThreadPoolExecutor(max_workers=3) as pool:proofs=list(pool.map(lambda row:download(row,root,NAMES[row['name']]),rows))
 old=api('/actions/runs/41598666103/artifacts')['artifacts'];row=next(r for r in old if r['name']=='CardioInsight-Windows-x64-1.0.11-P01-software-only');assert row['workflow_run']['id']==41598666103 and row['workflow_run']['head_sha']=='cfb5d732eae7fbf938bd8fab6a31ca4cd2b9bc3b';baseproof=download(row,root,'base27')
 oldzip=one(root/'base27','CardioInsight-DoctorEval-Windows-x64-1.0.11-P01-software.zip');assert digest(oldzip)=='a1f6d3962d25fef65517c67bda119b4e9d0878bec272fabccdebd25518bd5670'
 shared,_=snapshot(ROOT);assert shared['source_fingerprint']=='140751b696bf22aa1a2eae53b684c17a5af48a605406c1658ff9178ebe6db150' and shared['core_version']=='core-109535b780dbfc0a'
 paths={k:one(root/k,n) for k,n in {'p01':'CardioInsight-DoctorEval-Windows-x64-1.0.12-P01-software.zip','full':'CardioInsight-DoctorEval-Windows-x64-1.0.12-full.zip','update':'CardioInsight-DoctorEval-Windows-x64-1.0.12-software.zip','math':'CardioInsight-Synthetic-M01-24h-v1.zip'}.items()}
 programs={};releases={}
 for k in ['p01','full','update']:programs[k],releases[k]=check_program(paths[k],a.output/('unpacked-'+k),'P01' if k=='p01' else 'M01',shared)
 def non_ui(package):return {n:v for n,v in read(package/'CONTENTS.json')['files'].items() if n.startswith('_internal/') and not n.startswith(('_internal/static/','_internal/templates/')) and n!='_internal/shared-source-build.json'}
 immutable=non_ui(programs['p01']);assert len(immutable)==341
 oldpackage=unpack(oldzip,a.output/'unpacked-base27');verify_content_manifest(oldpackage)
 assert digest(oldpackage/'CardioInsightDoctorEval.exe')==EXE and non_ui(oldpackage)==immutable,'Base27 non-UI runtime differs'
 for k in ['full','update']:assert non_ui(programs[k])==immutable,k
 assert paths['math'].with_name(paths['math'].name+'.sha256').read_text().strip().split()==[digest(paths['math']),paths['math'].name]
 with zipfile.ZipFile(paths['math']) as z:
  assert z.testzip() is None and {n for n in z.namelist() if not n.endswith('/')}=={'M01/'+n for n in SOURCE_FILES}
  for n in SOURCE_FILES:assert hashlib.sha256(z.read('M01/'+n)).hexdigest()==digest(programs['full']/'Sources/M01'/n)
 contract=read(ROOT/'scripts/ui-repack-baseline-contract.json');assert all(digest(ROOT/n)==h for n,h in contract['runtime_python_sha256'].items())
 e=CArchiveReader(programs['p01']/'CardioInsightDoctorEval.exe');pyz=e.open_embedded_archive(next(n for n,v in e.toc.items() if v[-1]=='z'));modules=[]
 for n in contract['runtime_python_sha256']:
  if n=='win_doctor_eval.py':c=marshal.loads(e.extract('win_doctor_eval'))
  else:
   name=n[:-3].replace('/','.');name=name[:-9] if name.endswith('.__init__') else name;c=pyz.extract(name)
  assert normalized(c)==normalized(compile((ROOT/n).read_bytes(),n,'exec',optimize=0)),n;modules.append(n)
 original=root/'original-evidence';native=read(one(original,'browser-validation.json'));ui=read(one(original,'ui-test-summary.json'));p01=read(one(original,'p01-native.json'));failed=read(one(original,'report-evidence-native.json'))
 assert native['status']==p01['status']==ui['status']=='passed'
 assert len(native['checks'])==41 and all(c['status']=='passed' for c in native['checks']) and native['performance']['repeats']==3
 by={c['name']:c['evidence'] for c in native['checks']};assert len(by['latest-workstation-ui-and-report-curation']['checks'])==18 and len(by['rr-candidate-selection-and-final-approval']['checks'])==10 and by['native-af-afl-single-screen-editor']['passed']==22
 assert len(p01['checks'])==8 and all(c['status']=='passed' for c in p01['checks'])
 assert ui['current']=={'total':750,'passed':750,'failed':0,'error':0,'skipped':0}
 assert failed['status']=='failed' and 'ReferenceError: state is not defined' in failed['error'] and not failed.get('ui',{}).get('checks',[])
 assert native['network']['page_errors']==native['network']['http_errors']==[] and native['network']['external_requests']==0
 evidence=a.output/'evidence';shutil.copytree(original,evidence)
 prior=one(evidence,'report-evidence-native.json');prior.rename(prior.with_name('prior-report-evidence-failure.json'))
 package_sha={k:{'path':str(v),'sha256':digest(v),'bytes':v.stat().st_size} for k,v in paths.items()}
 report={'status':'original_passed_gates_and_exact_packages_verified_remaining_native_pending','producing_run':PRODUCER,'producing_commit':HEAD,'original_sole_failure':'step16 current APP document not loaded; ReferenceError stateundefined; no target check executed','source_identity':verify_source(ROOT),'common_source_fingerprint':shared['source_fingerprint'],'core_version':shared['core_version'],'ui_version':shared['ui_version'],'EXE_sha256':EXE,'compiled_modules_verified':modules,'UI_assets_verified':80,'non_UI_internal_files_equal':len(immutable),'original_gates_reused':{'UI_tests':750,'native':41,'latest_UI':18,'RR':10,'AF':22,'P01_upgrade':8,'performance_repeats':3},'all_original_outer_artifact_hashes_verified':proofs,'base27_outer_artifact_hash_verified':baseproof,'package_bytes':package_sha,'no_package_repack_or_metadata_rewrite':True,'remaining_required':['actual600s_ST_AF8','actualsameworkspace_reviewed6_UIupgrade'],'clinical_validation':False}
 dump(evidence/'continuation-prerequisites.json',report);dump(a.output/'continuation-input.json',{'paths':{**{k:str(v) for k,v in paths.items()},'base27':str(oldzip),'evidence':str(evidence)},'producing_commit':HEAD,'producing_run':PRODUCER})
 print(json.dumps({'status':'strict_continuation_prerequisites_passed','producing_run':PRODUCER,'producing_commit':HEAD,'native_reused':41,'UI_reused':750,'P01_reused':8,'remaining_actual_native':True}))
if __name__=='__main__':main()
