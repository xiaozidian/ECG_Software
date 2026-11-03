"""Fail closed when composing unchanged27 backend/perf with freshly run UI2 tests."""
from pathlib import Path
import argparse,hashlib,json,marshal,subprocess,tempfile,types,zipfile
ROOT=Path(__file__).resolve().parents[1]
from PyInstaller.archive.readers import CArchiveReader

def sha(b):return hashlib.sha256(b).hexdigest()
def one(root,name):
 found=list(root.rglob(name));assert len(found)==1,(name,len(found));return found[0]
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def normalized(c):
 return c.replace(co_filename='<unchanged-source>',co_consts=tuple(normalized(x) for x in c.co_consts)) if isinstance(c,types.CodeType) else c

def verify(a):
 c=read(ROOT/'scripts/ui-repack-baseline-contract.json')
 run=json.loads(subprocess.check_output(['gh','api',f"repos/{a.repository}/actions/runs/{c['base_run']}"],stderr=subprocess.PIPE))
 assert run['conclusion']=='failure' and run['status']=='completed' and run['head_sha']==c['base_commit']
 jobs=json.loads(subprocess.check_output(['gh','api',f"repos/{a.repository}/actions/runs/{c['base_run']}/jobs"],stderr=subprocess.PIPE))['jobs'];assert len(jobs)==1
 steps={v['number']:v for v in jobs[0]['steps']}
 assert {v['number'] for v in steps.values() if v['conclusion']=='failure'}=={14}
 assert all(steps[n]['conclusion']=='success' for n in [10,11,12,13]),'Scope/perf/build/P01 template did not pass'
 assert c['base_production_manifest']['production_file_count']==len(c['base_production_manifest']['files'])==128
 m=c['base_production_manifest'];assert sha(json.dumps(m['files'],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())==m['source_sha256']=='45162d78cd5aa35bde8487d421cd34c9700d5ee7e4a58e8550fc107091f55fe2'
 assert all(sha((ROOT/n).read_bytes())==h for n,h in c['runtime_python_sha256'].items()),'Existing runtime Python changed'
 assert sha((ROOT/'requirements-doctor-build.txt').read_bytes())==c['pinned_build_requirements_sha256']
 old=one(a.base_root,'CardioInsight-DoctorEval-Windows-x64-1.0.11-P01-software.zip');new=a.software_archive
 with zipfile.ZipFile(old) as b,zipfile.ZipFile(new) as n:
  assert b.testzip() is None and n.testzip() is None;prefix='CardioInsight-DoctorEval-Windows-x64/'
  before=read(one(a.base_root,'p01-software-build-report.json'));assert before['source_commit']==c['base_commit'] and before['production_source_identity']=={'release_id':m['release_id'],'source_sha256':m['source_sha256'],'production_files_verified':128,'clinical_acceptance':False}
  assert sha(old.read_bytes())==before['sha256'] and old.stat().st_size==before['bytes']
  old_release=json.loads(b.read(prefix+'RELEASE.json'));new_release=json.loads(n.read(prefix+'RELEASE.json'))
  assert old_release['app_version']==new_release['app_version']==new_release['software_version']==c['base_application_version']
  assert old_release['packaging_version']=='1.0.11' and new_release['packaging_version']=='1.0.12'
  for key in ['runtime_dependencies','resolved_build_dependency_freeze','source_id','source_version','minimum_source_version','supported_source_profile']:
   assert old_release[key]==new_release[key],key
  assert old_release['source_id']=='P01' and not old_release['source_data_bundled'] and not new_release['source_data_bundled']
  oldstamp=json.loads(b.read(prefix+'_internal/shared-source-build.json'));newstamp=json.loads(n.read(prefix+'_internal/shared-source-build.json'))
  assert oldstamp==c['base_common_stamp'] and oldstamp['core_version']==newstamp['core_version']=='core-109535b780dbfc0a'
  ui={k for k,v in newstamp['files'].items() if v['component']=='ui'};assert len(ui)==80
  allowed={prefix+'_internal/'+k for k in ui}|{prefix+'_internal/shared-source-build.json',prefix+'RELEASE.json',prefix+'CONTENTS.json',prefix+'SHA256SUMS.txt',prefix+'版本说明.txt'}
  names={k for k in b.namelist() if not k.endswith('/')};assert names=={k for k in n.namelist() if not k.endswith('/')}
  identical={}
  for k in sorted(names-allowed):
   first,second=sha(b.read(k)),sha(n.read(k));assert first==second,k;identical[k[len(prefix):]]=first
  exe=sha(b.read(prefix+'CardioInsightDoctorEval.exe'));assert exe==before['exe_sha256']==a.base_exe_sha256
  with tempfile.TemporaryDirectory(prefix='ui2-PYZ-readonly-') as tmp:
   path=Path(tmp)/'CardioInsightDoctorEval.exe';path.write_bytes(n.read(prefix+path.name));exe_reader=CArchiveReader(path);pyzs=[k for k,row in exe_reader.toc.items() if row[-1]=='z'];assert len(pyzs)==1;pyz=exe_reader.open_embedded_archive(pyzs[0]);modules=[]
   for file in c['runtime_python_sha256']:
    if file=='win_doctor_eval.py':
     assert 'win_doctor_eval' in exe_reader.toc;actual=marshal.loads(exe_reader.extract('win_doctor_eval'))
    else:
     name=file[:-3].replace('/','.');name=name[:-9] if name.endswith('.__init__') else name
     assert name in pyz.toc,name;actual=pyz.extract(name)
    expected=compile((ROOT/file).read_bytes(),file,'exec',optimize=0)
    assert normalized(actual)==normalized(expected),file;modules.append(file)
 native=read(one(a.base_root,'browser-validation.json'));scope=read(one(a.base_root,'test-summary.json'));perf=read(one(a.base_root,'windows-request-source-perf.json'))
 assert scope['status']==perf['status']=='passed'
 assert native['status']=='failed' and native['checks'][-1]['name']=='browser-verification-completion'
 assert native['checks'][-1]['evidence']['error']=='AssertionError: Missing V6 trend was presented as a normal numeric trend'
 assert all(v['status']=='passed' for v in native['checks'][:-1])
 assert native['network']['page_errors']==native['network']['http_errors']==[]
 assert scope['current']['failed']==scope['current']['error']==0
 assert exe==c['base_exe_sha256'] and before['sha256']==c['base_P01_archive_sha256']
 return {'status':'passed','scope':'composed unchanged backend/performance27; UI2 wrappers and actual native checks are separate fresh stages','base_run':c['base_run'],'base_commit':c['base_commit'],'base_production128_sha256':m['source_sha256'],'existing_runtime_python_files_identical':len(modules),'embedded_runtime_modules_match_reviewed_source':modules,'actual_EXE_identical':exe,'all_other_non_UI_payload_identical':identical,'runtime_dependencies_equal':True,'source_profiles_equal':True,'original_scope_tests':scope['current'],'original_scope_historical_AF_status':scope['historical_af'],'original_request_perf':perf['status'],'original_native_checks_passed':len(native['checks'])-1,'original_native_runtime_status':'failed/superseded known old ST renderer-text assertion; remaining protection checks are mandatory fresh UI2 stages','UI2_full_backend_scope_rerun':False,'further_required':['fresh all UI wrapper regressions','actual native41/UI18/AF22/RR10/P01upgrade8/report8','same-workspace reviewed report/basis/recovery_epoch/source/DB preservation'],'clinical_validation':False}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--base-root',type=Path,required=True);p.add_argument('--software-archive',type=Path,required=True);p.add_argument('--base-exe-sha256',required=True);p.add_argument('--repository',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=verify(a);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in r.items() if k!='all_other_non_UI_payload_identical'}))
