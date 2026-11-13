"""Read-only M01-only complete ST-T endpoint profile. No generator or patient lookup.

Accepts only the already verified, wholly synthetic M01-24h-v1 manifest + bytes.
Writes a temporary empty work DB, then times the real create_app GET endpoint.
Default mode only wraps counters; --trial-stt deliberately injects a disposable
experimental module in memory. That mode is not a runtime-identity validation.
"""
from pathlib import Path
import argparse,cProfile,faulthandler,hashlib,io,json,os,platform,pstats,sys,tempfile,time
from collections import defaultdict

parser=argparse.ArgumentParser()
parser.add_argument('--source',type=Path,required=True)
parser.add_argument('--math-root',type=Path,required=True)
parser.add_argument('--out',type=Path,required=True)
parser.add_argument('--cprofile',action='store_true')
parser.add_argument('--trial-stt',type=Path)
parser.add_argument('--trial-quality',type=Path)
parser.add_argument('--save-body',action='store_true')
args=parser.parse_args()
source=args.source.resolve();data=args.math_root.resolve();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
manifest_path=data/'source-manifest.json'
manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
assert manifest['source_id']=='M01' and manifest['source_version']=='M01-24h-v1'
assert manifest['wholly_synthetic'] is True and manifest['patient_inputs_read'] is False
assert manifest['kind']=='mathematical_synthetic' and manifest['full_24h_fixture'] is True
assert manifest['duration_seconds']==86400 and manifest['sample_count']==17280000 and manifest['sampling_rate_hz']==200
assert manifest['beat_count']==100051 and manifest['case_id']=='9900000000000001'
assert manifest['dataset_sha256']=='82a232872857da2ea752017c4a14c5565b43255bedc2438252eb125eaaf86bb8'
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(2**20),b''):h.update(b)
 return h.hexdigest()
checked={}
for row in manifest['files']:
 n=Path(row['path']);assert not n.is_absolute() and '..' not in n.parts
 f=data/n;assert f.is_file() and not f.is_symlink() and f.stat().st_size==row['size_bytes'] and sha(f)==row['sha256']
 checked[row['path']]=row['sha256']
case_id=manifest['case_id'];assert {p.name for p in data.iterdir() if p.is_dir() and p.name.isdecimal()}=={case_id}
result={'synthetic_only':True,'patient_inputs_read':False,'manifest_sha256':sha(manifest_path),'dataset_sha256':manifest['dataset_sha256'],'source_root_name':source.name,'python':sys.version,'platform':platform.platform(),'pid':os.getpid(),'source_hashes':{},'timings':{},'calls':{},'responses':[],'faults':[]}
for n in ['app.py','ecg_core/stt.py','ecg_core/stt_candidate_quality.py','ecg_core/storage.py']:
 result['source_hashes'][n]=sha(source/n)
def dump():
 (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def event(stage,**more):
 print(json.dumps({'stage':stage,**more}),flush=True)
def timed(label,fn):
 wall=time.perf_counter();cpu=time.process_time();v=fn()
 result['timings'][label]={'wall_seconds':time.perf_counter()-wall,'process_cpu_seconds':time.process_time()-cpu};dump();event(label,**result['timings'][label]);return v
calls=defaultdict(lambda:{'count':0,'wall_seconds':0.,'process_cpu_seconds':0.})
def wrap(module,name):
 original=getattr(module,name)
 def traced(*a,**kw):
  t=time.perf_counter();c=time.process_time()
  try:return original(*a,**kw)
  finally:
   entry=calls[module.__name__+'.'+name];entry['count']+=1;entry['wall_seconds']+=time.perf_counter()-t;entry['process_cpu_seconds']+=time.process_time()-c
 traced.__name__=original.__name__;traced.__doc__=original.__doc__
 setattr(module,name,traced)
 return lambda:setattr(module,name,original)
with tempfile.TemporaryDirectory(prefix='m01-stt-perf-') as temp:
 work=Path(temp)
 os.environ.update(ECG_DATA_ROOT=str(data),ECG_APP_DATA_ROOT=str(work/'appdata'),ECG_CONFIG_PATH=str(work/'private-config.json'),ECG_DEMO_READONLY='0',ECG_ALLOW_PHI='0')
 sys.path.insert(0,str(source))
 import app as server
 import ecg_core.stt as stt
 import ecg_core.stt_candidate_quality as quality
 import numpy as np
 if args.trial_quality:
  import importlib.util
  trial_quality=args.trial_quality.resolve()
  spec_quality=importlib.util.spec_from_file_location('ecg_core._quality_combo',trial_quality)
  quality_module=importlib.util.module_from_spec(spec_quality);spec_quality.loader.exec_module(quality_module)
  quality.candidate_t_support=quality_module.candidate_t_support
  result['experimental_quality_module']=trial_quality.name
  result['experimental_quality_sha256']=sha(trial_quality)
  result['runtime_identity_validation_claimed']=False
 if args.trial_stt:
  import importlib.util
  trial=args.trial_stt.resolve()
  spec=importlib.util.spec_from_file_location('ecg_core.stt_trial',trial)
  module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  server.build_stt_review=module.build_stt_review
  stt=module
  result['experimental_in_memory_module']=str(trial.name)
  result['experimental_module_sha256']=sha(trial)
  result['runtime_identity_validation_claimed']=False
 result['numpy']=np.__version__
 # Frozen source bytes stay unchanged. Wrappers observe either original code
 # or the explicitly labelled disposable in-memory trial when requested.
 undo=[wrap(server,'build_stt_review'),wrap(stt,'analyze_stt')]
 for name in ['_block_measurement','_beat_measurements','minute_trends','_lead_episodes','_t_episodes']:
  undo.append(wrap(stt,name))
 undo.append(wrap(quality,'candidate_t_support'))
 app=timed('create_app',lambda:server.create_app(data_root=data,db_path=work/'work.sqlite3'))
 client=app.test_client()
 def get(path,label):
  response=client.get(path)
  result['responses'].append({'stage':label,'status':response.status_code,'bytes':response.calculate_content_length()})
  assert response.status_code==200,(path,response.status_code,response.get_data(as_text=True)[:300])
  return response
 timed('warm_case_header',lambda:get('/api/cases/'+case_id,'case_header'))
 timed('warm_analysis_basis',lambda:get('/api/cases/'+case_id+'/analysis-basis','basis'))
 stack_file=(out/'live-stacks.txt').open('w',encoding='utf-8')
 faulthandler.dump_traceback_later(30,repeat=True,file=stack_file)
 try:
  profiler=cProfile.Profile()
  def cold():
   if args.cprofile:profiler.enable()
   try:return get('/api/cases/'+case_id+'/stt-review','stt_cold')
   finally:
    if args.cprofile:profiler.disable()
  cold_response=timed('stt_cold_complete_endpoint',cold)
  result['cold_calls']=dict(calls);result['calls']={}
  if args.save_body:
   import gzip
   with gzip.open(out/'cold-body.json.gz','wb') as g:g.write(cold_response.get_data())
  shape=cold_response.get_json();result['body_sha256']=hashlib.sha256(cold_response.get_data()).hexdigest();result['shape']={'candidates':len(shape['automatic_candidates']['items']),'review_records':len(shape['review_records']),'blocks':shape['analysis'].get('quality',{}).get('total_blocks'),'raw_seconds':shape['analysis'].get('duration_s')}
  # cProfile data are code/timing only; --save-body separately saves only the
  # strictly verified mathematical M01 response for exact comparison.
  if args.cprofile:
   buf=io.StringIO();pstats.Stats(profiler,stream=buf).strip_dirs().sort_stats('cumtime').print_stats(90)
   (out/'cprofile.txt').write_text(buf.getvalue(),encoding='utf-8');profiler.dump_stats(out/'profile.pstats')
  calls.clear()
  warm_response=timed('stt_warm_complete_endpoint',lambda:get('/api/cases/'+case_id+'/stt-review','stt_warm'))
  result['warm_calls']=dict(calls)
  result['cold_warm_body_equal']=cold_response.get_json()==warm_response.get_json()
  assert result['cold_warm_body_equal']
 finally:
  faulthandler.cancel_dump_traceback_later();stack_file.close()
  for restore in reversed(undo):restore()
 result['source_hashes_unchanged']=all(sha(source/n)==v for n,v in result['source_hashes'].items())
 assert result['source_hashes_unchanged']
 result['status']='passed';dump()
