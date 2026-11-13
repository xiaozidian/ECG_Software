"""Portable M01-only experimental baseline -> combo1 endpoint diagnostic.

Runs two new child processes with this interpreter, never changes source files.
Explicit in-memory monkeypatch is performance research, NOT runtime-identity or
native-PE acceptance. Only the fixed wholly synthetic M01 dataset is accepted.
"""
from pathlib import Path
import argparse,gzip,hashlib,json,platform,subprocess,sys

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source',type=Path,required=True)
parser.add_argument('--math-root',type=Path,required=True)
parser.add_argument('--out',type=Path,required=True,help='Artifact directory outside source and mathematical input')
parser.add_argument('--require-windows-pinned',action='store_true')
parser.add_argument('--verify-existing',action='store_true',help='Only re-compare already completed baseline-1/combo-1 outputs; no new analysis')
args=parser.parse_args();source=args.source.resolve();math_root=args.math_root.resolve();out=args.out.resolve();here=Path(__file__).resolve().parent
assert not out.is_relative_to(source) and not out.is_relative_to(math_root),'Artifacts must be outside source and mathematical input'
out.mkdir(parents=True,exist_ok=True)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
modules={'stt_flags_trial.py':'c475c00420199d7259d27901546cef65fb9003e132623376a879b21af3db89f8','quality_layout_trial.py':'d5b3c2a988480f5c84230b87b4eb6d89bb93b773c63347a39f73f1e408776c66'}
for name,digest in modules.items():assert sha(here/name)==digest,(name,'Trial file differs')
assert sha(source/'ecg_core/stt.py')=='870531819d6973d167e4040a48ff649357e8b4cf0384b17b6cfb7b0086c9640f'
assert sha(source/'ecg_core/stt_candidate_quality.py')=='6e37ccddfcf5fee152ac2c419d3870af3c3ad0c94565d038157a1385d51a8868'
manifest_path=math_root/'source-manifest.json';manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
assert sha(manifest_path)=='b5f6af8f6bbe1c129c3dede735ffd65f819b2738a62e31a3cb2a3698dd293376'
assert manifest['wholly_synthetic'] is True and manifest['patient_inputs_read'] is False and manifest['case_id']=='9900000000000001'
assert manifest['dataset_sha256']=='82a232872857da2ea752017c4a14c5565b43255bedc2438252eb125eaaf86bb8'
if args.require_windows_pinned:
 import numpy as np
 assert sys.platform=='win32' and sys.version_info[:3]==(3,12,10) and np.__version__=='2.2.6',(sys.platform,sys.version,np.__version__)
def fingerprints():
 files=[source/'app.py',*sorted((source/'ecg_core').glob('*.py'))]
 return {p.relative_to(source).as_posix():sha(p) for p in files}
before=fingerprints();report={'experimental_only':True,'runtime_identity_validation_claimed':False,'native_pe_acceptance_claimed':False,'patient_inputs_read':False,'python':sys.version,'platform':platform.platform(),'mode':'verify_existing' if args.verify_existing else 'new_baseline_then_combo','manifest_sha256':sha(manifest_path),'dataset_sha256':manifest['dataset_sha256'],'trial_modules':modules,'profile_runner_sha256':sha(here/'profile_combo.py'),'source_files_before':before}
(out/'portable-source-before.json').write_text(json.dumps(before,indent=2)+'\n',encoding='utf-8')
def dump():
 (out/'portable-comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
try:
 if not args.verify_existing:
  for name,extra in (('baseline-1',[]),('combo-1',['--trial-stt',str(here/'stt_flags_trial.py'),'--trial-quality',str(here/'quality_layout_trial.py')])):
   destination=out/name
   assert not (destination/'result.json').exists(),'Choose a fresh output directory; existing runs are not overwritten'
   command=[sys.executable,'-B',str(here/'profile_combo.py'),'--source',str(source),'--math-root',str(math_root),'--out',str(destination),'--save-body',*extra]
   with (out/(name+'-stdout.log')).open('w',encoding='utf-8') as log:
    subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
 b=json.loads((out/'baseline-1/result.json').read_text(encoding='utf-8'));c=json.loads((out/'combo-1/result.json').read_text(encoding='utf-8'))
 for run in (b,c):
  assert run['status']=='passed' and run['source_hashes_unchanged'] and run['cold_warm_body_equal']
  assert run['dataset_sha256']==manifest['dataset_sha256'] and run['manifest_sha256']==sha(manifest_path)
  assert run['source_hashes']=={name:before[name] for name in run['source_hashes']}
  assert all(row['status']==200 for row in run['responses'])
  if args.require_windows_pinned:
   assert run['python'].startswith('3.12.10 ') and run['numpy']=='2.2.6' and run['platform'].startswith('Windows-')
 assert c['experimental_module_sha256']==modules['stt_flags_trial.py'] and c['experimental_quality_sha256']==modules['quality_layout_trial.py']
 bb=gzip.decompress((out/'baseline-1/cold-body.json.gz').read_bytes());cb=gzip.decompress((out/'combo-1/cold-body.json.gz').read_bytes())
 x=b['timings']['stt_cold_complete_endpoint'];y=c['timings']['stt_cold_complete_endpoint']
 report.update(baseline_cold=x,combo_cold=y,wall_saved_seconds=x['wall_seconds']-y['wall_seconds'],cpu_saved_seconds=x['process_cpu_seconds']-y['process_cpu_seconds'],wall_improvement_fraction=1-y['wall_seconds']/x['wall_seconds'],cpu_improvement_fraction=1-y['process_cpu_seconds']/x['process_cpu_seconds'],full_http_body_byte_equal=bb==cb,full_json_equal=json.loads(bb)==json.loads(cb),field_exemptions=[],body_bytes={'baseline':len(bb),'combo':len(cb)},body_sha256={'baseline':hashlib.sha256(bb).hexdigest(),'combo':hashlib.sha256(cb).hexdigest()},baseline_shape=b['shape'],combo_shape=c['shape'],baseline_calls=b['cold_calls'],combo_calls=c['cold_calls'],all_cold_warm_json_equal=True,baseline_warm=b['timings']['stt_warm_complete_endpoint'],combo_warm=c['timings']['stt_warm_complete_endpoint'])
 assert report['full_http_body_byte_equal'],'Full response differs; no fields are discarded or relabelled'
 report['status']='passed'
except BaseException as error:
 report['status']='failed';report['failure_type']=type(error).__name__;report['failure_reason']=str(error)
 raise
finally:
 after=fingerprints();report['source_files_after']=after;report['source_hashes_unchanged']=before==after;report['trial_modules_unchanged']=all(sha(here/name)==digest for name,digest in modules.items())
 if not report['source_hashes_unchanged'] or not report['trial_modules_unchanged']:
  report['status']='failed';report['failure_reason']='Source or experimental module hashes changed during run'
 dump()
assert report['source_hashes_unchanged'] and report['trial_modules_unchanged']
print(json.dumps({k:v for k,v in report.items() if k not in ('source_files_before','source_files_after','baseline_calls','combo_calls')},ensure_ascii=False,indent=2))
