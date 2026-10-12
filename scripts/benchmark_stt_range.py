#!/usr/bin/env python3
"""Reproducible, synthetic-only ST range benchmark; never opens a case database.

Example: python benchmark_stt_range.py --module-root SOURCE --output TEMP --prepare
Then, on an otherwise quiet host: same arguments with --run.
Raw files stay in TEMP; only this script and the small JSON receipt need sharing.
Fresh Python processes are not evidence of cold OS file caches.  No OS cache is
cleared, no threshold is modified, and this measures the core API rather than an
HTTP endpoint or clinical accuracy.  The helper uses every eligible beat.
"""
from __future__ import annotations
import argparse
import gc
import hashlib
import json
import math
import os
import platform
import random
import resource
import struct
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from fractions import Fraction

SAMPLE_RATE=200
SECONDS=86400
TOTAL_SAMPLES=SAMPLE_RATE*SECONDS
FRAME_BYTES=16
SEED=20261012
EXPECTED_METHOD_SHA='a0120b25c737fa7d9110b2330e283c675a53c4bdbc788e5b073b0e0b484c2317'
CODE_FILES=('ecg_core/stt_range.py','ecg_core/stt.py','ecg_core/config.py','ecg_core/source_identity.py')
FROZEN_FILES=CODE_FILES+('static/js/stt-range-review.js','static/css/stt-range-review.css','static/js/stt-range-bridge.js')

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)

def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()

def sha_file(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block:=stream.read(1024*1024):h.update(block)
    return h.hexdigest()

def save_json(path,value):
    path=Path(path);tmp=path.with_suffix(path.suffix+'.writing')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    tmp.replace(path)

def code_hashes(module_root):
    value={rel:sha_file(Path(module_root)/rel) for rel in FROZEN_FILES}
    if value['ecg_core/stt_range.py']!=EXPECTED_METHOD_SHA:
        raise RuntimeError('This measurement profile source differs from the approved frozen module')
    return value

def stat_identity(path):
    s=Path(path).stat();return [s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns]

def input_identity(manifest):
    # Content identity is reproducible across regeneration on different inodes.
    value={k:v for k,v in manifest.items() if k not in ('created_utc','input_digest','frozen_code_hashes')}
    for name in ('waveform','ebi'):value[name]={k:v for k,v in value[name].items() if k!='stat'}
    return digest(value)

def environment():
    import numpy as np
    result={'python':platform.python_version(),'numpy':np.__version__,'platform':platform.platform(),
            'machine':platform.machine(),'os_caches':'unknown; never cleared; input generation and verification may populate caches',
            'other_host_load':'recorded by operator; no speedup claim',
            'rss_units':'MiB; ru_maxrss converted from macOS bytes or Linux KiB'}
    if sys.platform=='darwin':
        for key in ('hw.logicalcpu','hw.memsize'):
            try:
                value=subprocess.run(['sysctl','-n',key],capture_output=True,text=True)
                if value.returncode==0:result[key]=int(value.stdout.strip())
            except OSError:result[key]='unavailable in this execution sandbox'
    return result

def prepare(module_root,output):
    import numpy as np
    output.mkdir(parents=True,exist_ok=True)
    hashes=code_hashes(module_root)
    waveform=output/'mathematical-24h.DATA';ebi=output/'mathematical-24h.EBI'
    rng=random.Random(SEED);deltas=[rng.randrange(-60,61) for _ in range(16)]
    old=output/'input-manifest.json'
    if old.exists():
        manifest=json.loads(old.read_text())
        if manifest.get('seed')==SEED and waveform.exists() and ebi.exists():
            if sha_file(waveform)==manifest['waveform']['sha256'] and sha_file(ebi)==manifest['ebi']['sha256']:
                if code_hashes(module_root)!=manifest['frozen_code_hashes']:raise RuntimeError('Frozen product code changed since fixture preparation')
                manifest['input_digest']=input_identity(manifest);save_json(old,manifest)
                print(canonical({'phase':'prepared_reused_verified','input':manifest['input_digest']}),flush=True)
                return manifest
    tile=np.full((3200,8),120,dtype='<i2')
    for second,delta in enumerate(deltas):
        anchor=second*200+198
        for offset,height in enumerate((900,600,250,80)):tile[(anchor+offset)%3200]+=height
        for offset in range(18,31):tile[(anchor+offset)%3200]+=delta
    temporary=waveform.with_suffix('.DATA.writing')
    mapped=np.memmap(temporary,dtype='<i2',mode='w+',shape=(TOTAL_SAMPLES,8))
    for first in range(0,TOTAL_SAMPLES,3200):mapped[first:first+3200]=tile
    mapped.flush();del mapped;gc.collect();temporary.replace(waveform)
    record=struct.Struct('<IHHIIII')
    with ebi.open('wb') as stream:
        stream.write(b'PURE-MATH-24H-ST-MEAN-V1'.ljust(32,b'\0'))
        for beat in range(SECONDS):stream.write(record.pack(198+200*beat,0,1,0,0,0,0 if beat==0 else 1000))
    waveform.chmod(0o400);ebi.chmod(0o400)
    manifest={'schema':'synthetic-stt-benchmark-input-v1','created_utc':datetime.now(timezone.utc).isoformat(),
      'source_kind':'pure_mathematical','seed':SEED,'generator':'stdlib random.Random; repeated 16s int16 tile; streamed memmap writes',
      'duration_s':SECONDS,'sample_rate_hz':SAMPLE_RATE,'channels':8,'sample_format':'little-endian int16',
      'units':'uncalibrated device u; software fixture only','clinical_validation':False,
      'qrs_count':SECONDS,'first_qrs_sample':198,'last_qrs_sample':TOTAL_SAMPLES-2,
      'rr_ms':{'first':0,'remaining':1000,'sample_differences':200},
      'edge_definition':'first RR unknown because no preceding annotated R; last ST/J support genuinely extends beyond file end and is withheld by the inherited source guard',
      'delta_units_16beats':deltas,'expected_machine_j_sample':8,
      'waveform':{'name':waveform.name,'bytes':waveform.stat().st_size,'sha256':sha_file(waveform),'stat':stat_identity(waveform)},
      'ebi':{'name':ebi.name,'bytes':ebi.stat().st_size,'sha256':sha_file(ebi),'stat':stat_identity(ebi),'header_bytes':32,'record_bytes':24},
      'frozen_code_hashes':hashes}
    manifest['input_digest']=input_identity(manifest)
    save_json(old,manifest)
    print(canonical({'phase':'prepared_verified','raw_bytes':manifest['waveform']['bytes'],'qrs_count':SECONDS,'input':manifest['input_digest']}),flush=True)
    return manifest

def rss():
    maximum=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/(1024**2 if sys.platform=='darwin' else 1024)
    try:
        value=subprocess.run(['ps','-o','rss=','-p',str(os.getpid())],capture_output=True,text=True)
        current=int(value.stdout.strip())/1024 if value.returncode==0 and value.stdout.strip() else None
    except OSError:current=None
    return {'current_mib':current,'process_peak_mib':maximum,
            'current_rss_status':'measured' if current is not None else 'process probe unavailable in this sandbox'}

def measured(function):
    before=rss();wall=time.perf_counter();cpu=time.process_time()
    value=function();elapsed=time.perf_counter()-wall;used=time.process_time()-cpu
    return value,{'wall_s':elapsed,'cpu_s':used,'rss_before':before,'rss_after':rss()}

def expected(manifest,start,end,masks=()):
    values=[];excluded=missing=detected=0
    for k in range(SECONDS):
        anchor=198+200*k
        if not start<=anchor<end:continue
        detected+=1
        if k==0:excluded+=1;continue
        if anchor+120>=TOTAL_SAMPLES:missing+=1;continue
        support=((anchor,anchor+1),(anchor-40,anchor-23),(anchor+18,anchor+23))
        if any(a<m['end_sample'] and b>m['start_sample'] for a,b in support for m in masks):excluded+=1;continue
        values.append(manifest['delta_units_16beats'][k%16])
    raw_mean=Fraction(sum(values),len(values)) if values else None
    return {'detected_count':detected,'used_count':len(values),'excluded_count':excluded,'missing_count':missing},raw_mean

def oracle_check(result,manifest,start,end,masks=()):
    counts,mean=expected(manifest,start,end,masks)
    for key,value in counts.items():
        if result['counts'][key]!=value:raise AssertionError((key,result['counts'][key],value))
    scale={'I':1,'II':1,'III':0,'aVR':-1,'aVL':Fraction(1,2),'aVF':Fraction(1,2),**{f'V{i}':1 for i in range(1,7)}}
    error=0
    for lead in result['leads']:
        wanted=float(mean*scale[lead['lead']]) if mean is not None else None
        if wanted is None:
            if lead['mean_units'] is not None:raise AssertionError('empty is not null')
        else:error=max(error,abs(lead['mean_units']-wanted))
        if lead['used_count']!=counts['used_count']:raise AssertionError('mean population was truncated')
    if error>1e-9:raise AssertionError(('closed-form arithmetic mean mismatch',error))
    if any(b['eligible'] and b['j_offset_samples']!=8 for b in result['blocks']):raise AssertionError('fixture J differs from closed-form assumption')
    return {'closed_form_max_abs_u':error,'used_population_exact':True,'counts':counts}

def module_import(root):
    sys.path.insert(0,str(root))
    from ecg_core.ebi import load_records,_load_records
    from ecg_core.stt_range import analyze_stt_range
    from ecg_core.source_identity import file_evidence
    return load_records,_load_records,analyze_stt_range,file_evidence

def verify(module_root,output,manifest):
    load,_,analyze,_=module_import(module_root)
    records=load(str(output/manifest['ebi']['name']))
    assert len(records)==SECONDS and records[0][0]==198 and records[-1][0]==TOTAL_SAMPLES-2
    assert records[0][6]==0 and all(b[0]-a[0]==200 and b[6]==1000 for a,b in zip(records,records[1:]))
    checks=[]
    for start,end in ((43200*200,43260*200),(86340*200,86400*200),(0,60*200)):
        result=analyze(output/manifest['waveform']['name'],records,start_sample=start,end_sample=end,
          basis={'case_id':'synthetic-24h-benchmark','analysis_basis':manifest['frozen_code_hashes']['ecg_core/stt_range.py'],'analysis_revision':0,'beat_revision':0},source_digest=manifest['waveform']['sha256'])
        checks.append({'start_sample':start,'end_sample':end,'oracle':oracle_check(result,manifest,start,end),'result_digest':result['result_digest']})
    save_json(output/'input-verification.json',{'timing_is_not_a_benchmark':True,'checks':checks,'no_patient_inputs':True})
    print(canonical({'phase':'untimed_oracle_verified','checks':len(checks),'tail_missing_count':checks[1]['oracle']['counts']['missing_count']}),flush=True)

def worker(args):
    output=Path(args.output);manifest=json.loads((output/'input-manifest.json').read_text())
    if code_hashes(args.module_root)!=manifest['frozen_code_hashes']:raise RuntimeError('Product source changed')
    for name in ('waveform','ebi'):
        if stat_identity(output/manifest[name]['name'])!=manifest[name]['stat']:raise RuntimeError('Synthetic input changed')
    load,private_load,analyze,file_evidence=module_import(args.module_root)
    row={'kind':args.kind,'process_index':args.process_index,'pid':os.getpid(),'fresh_process':True,
         'os_cache_state':'unknown; no OS cache clearing','load_average_start':list(os.getloadavg()),'calls':[]}
    if args.kind=='io':
        raw=output/manifest['waveform']['name']
        for label in ('first_stream_hash','repeat_stream_hash'):
            value,metrics=measured(lambda:sha_file(raw));assert value==manifest['waveform']['sha256']
            row['calls'].append({'label':label,**metrics,'bytes_read':raw.stat().st_size,'sha256':value})
        for label in ('first_product_file_evidence','repeat_product_file_evidence_cached'):
            value,metrics=measured(lambda:file_evidence(raw));assert value['sha256']==manifest['waveform']['sha256']
            row['calls'].append({'label':label,**metrics,'sha256':value['sha256'],'cache':'Python digest cache hit' if 'cached' in label else 'first call in fresh process'})
    elif args.kind=='ebi':
        path=str(output/manifest['ebi']['name'])
        for label in ('first_parse','repeat_parse_forced_read','repeat_cached_api'):
            if label=='repeat_parse_forced_read':private_load.cache_clear()
            value,metrics=measured(lambda:load(path))
            assert len(value)==SECONDS and value[-1][0]==TOTAL_SAMPLES-2
            row['calls'].append({'label':label,**metrics,'qrs_count':len(value),'input_file_bytes':manifest['ebi']['bytes'],
                                 'cache':'Python EBI cache hit' if label=='repeat_cached_api' else 'full read and parse'})
            del value;gc.collect()
    else:
        records,parse=measured(lambda:load(str(output/manifest['ebi']['name'])))
        row['preloaded_ebi']=parse
        duration=int(args.kind)
        start=0 if duration==86400 else 43200*200
        end=start+duration*200
        scope={'case_id':'synthetic-24h-benchmark','analysis_basis':manifest['frozen_code_hashes']['ecg_core/stt_range.py'],
               'analysis_revision':0,'beat_revision':0,'data_version':manifest['input_digest']}
        for call in ('first_calculation','repeat_calculation'):
            save_json(Path(args.progress),{'phase':'calculation_running','call':call,'start_monotonic':time.perf_counter()})
            result,metrics=measured(lambda:analyze(output/manifest['waveform']['name'],records,start_sample=start,end_sample=end,
                   leads=None,measurement_ms=60,basis=scope,source_digest=manifest['waveform']['sha256']))
            save_json(Path(args.progress),{'phase':'calculation_finished','call':call,'elapsed_s':metrics['wall_s']})
            verification=oracle_check(result,manifest,start,end)
            encoded,encoding=measured(lambda:canonical(result).encode())
            row['calls'].append({'label':call,**metrics,'range':result['range'],'counts':result['counts'],
              'oracle':verification,'method_profile_id':result['method_profile']['id'],'method_digest':result['binding']['method_digest'],
              'output_digest':result['result_digest'],'blocks':len(result['blocks']),
              'j_representative_max':max(len(b['j_representative_samples']) for b in result['blocks']),
              'encoded_result_bytes':len(encoded),'json_encode_wall_s':encoding['wall_s'],'rss_after_encode':encoding['rss_after']})
            del result,encoded;gc.collect();row['calls'][-1]['rss_after_release']=rss()
            save_json(Path(args.worker_result),{**row,'partial_worker_result':True})
            save_json(Path(args.progress),{'phase':'calculation_complete','call':call,'elapsed_s':metrics['wall_s']})
            if duration>=3600 and metrics['wall_s']>20:
                row['repeat_skipped']=f'{call} exceeded 20s; no further long repetition';break
        if len(row['calls'])==2:assert row['calls'][0]['output_digest']==row['calls'][1]['output_digest']
    row['load_average_end']=list(os.getloadavg());row['rss_final']=rss()
    save_json(Path(args.worker_result),row)

def run_one(args,kind,index):
    output=Path(args.output);runs=output/'runs';runs.mkdir(exist_ok=True)
    target=runs/f'{kind}-process{index}.json';progress=runs/f'{kind}-process{index}.progress.json'
    command=[sys.executable,str(Path(__file__).resolve()),'--module-root',args.module_root,'--output',args.output,
       '--worker','--kind',str(kind),'--process-index',str(index),'--worker-result',str(target),'--progress',str(progress)]
    print(canonical({'phase':'starting_fresh_process','kind':kind,'index':index}),flush=True)
    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
    limit=None;last_progress=None
    while process.poll() is None:
        if kind in ('3600','86400') and progress.exists():
            try:last_progress=json.loads(progress.read_text())
            except (ValueError,OSError):last_progress=None
            if last_progress and last_progress['phase']=='calculation_running' and time.perf_counter()-last_progress['start_monotonic']>20:
                limit=time.perf_counter()-last_progress['start_monotonic'];process.terminate()
                try:process.wait(timeout=3)
                except subprocess.TimeoutExpired:process.kill();process.wait()
                break
        time.sleep(.2)
    stdout,stderr=process.communicate()
    if limit is not None:
        row=json.loads(target.read_text()) if target.exists() else {'kind':kind,'process_index':index,'calls':[]}
        row.update({'censored':True,'inflight_measurement_elapsed_lower_bound_s':limit,
             'limit_policy':'stop an in-flight long invocation above 20s; no output/mean claimed for the cancelled call','progress':last_progress}
        )
        save_json(target,row);print(canonical({'phase':'long_scope_stopped','kind':kind,'lower_bound_s':limit}),flush=True);return row
    if process.returncode:raise RuntimeError(f'Worker failed {kind}: {stderr}')
    row=json.loads(target.read_text());print(canonical({'phase':'fresh_process_finished','kind':kind,'index':index,
         'wall_s':[x['wall_s'] for x in row['calls']]}),flush=True);return row

def summary(rows):
    import statistics
    groups={}
    for row in rows:
        for call in row.get('calls',[]):groups.setdefault((row['kind'],call['label']),[]).append(call)
    result=[]
    for (kind,label),calls in groups.items():
        entry={'kind':kind,'call':label,'n_fresh_processes':len(calls)}
        for name in ('wall_s','cpu_s','json_encode_wall_s','encoded_result_bytes'):
            vals=[x[name] for x in calls if name in x]
            if vals:entry[name]={'median':statistics.median(vals),'min':min(vals),'max':max(vals)}
        peaks=[x['rss_after']['process_peak_mib'] for x in calls]
        entry['process_peak_mib']={'median':statistics.median(peaks),'min':min(peaks),'max':max(peaks)}
        result.append(entry)
    return result

def run(args,manifest):
    rows=[]
    for kind in ('io','ebi','60','300'):
        for index in (1,2,3):rows.append(run_one(args,kind,index))
    long=[]
    for kind in ('3600','86400'):
        first=run_one(args,kind,1);rows.append(first)
        stopped=False
        if first.get('censored') or first.get('repeat_skipped'):
            stopped=True
        else:
            for index in (2,3):
                row=run_one(args,kind,index);rows.append(row)
                if row.get('censored') or row.get('repeat_skipped'):stopped=True;break
        if stopped:
            long.append({'kind':kind,'status':'stopped_above_20s; no subsequent long repetitions'})
            if kind=='3600':long.append({'kind':'86400','status':'not attempted after hourly scope exceeded limit'});break
    after=code_hashes(args.module_root)
    assert after==manifest['frozen_code_hashes']
    assert sha_file(Path(args.output)/manifest['waveform']['name'])==manifest['waveform']['sha256']
    output_digests={}
    for row in rows:
        for call in row.get('calls',[]):
            if 'output_digest' in call:output_digests.setdefault(row['kind'],set()).add(call['output_digest'])
    if any(len(values)!=1 for values in output_digests.values()):raise AssertionError('Output changed across fresh processes/repeated calls')
    receipt={'schema':'synthetic-stt-benchmark-receipt-v1','created_utc':datetime.now(timezone.utc).isoformat(),
      'input_digest':manifest['input_digest'],'input':manifest,'environment':environment(),'methodology':{
        'fresh_process_n':3,'each_fresh_process':'first call plus repeated call after releasing result objects',
        'process_startup_and_imports':'excluded from per-call timers; EBI preload separately measured for calculations',
        'os_cold_cache_claim':False,'cleared_os_caches':False,
        'ebi_forced_read':'only private process-local EBI LRU cleared to measure equivalent repeated parsing; cached API also reported separately',
        'core_api_only':True,'http_route_or_ui_timing':False,'new_method_speedup_claim':False,
        'rss':'current RSS and lifetime absolute process peak; not stage allocation deltas',
        'long_limit_s':20,'hardware_condition':args.condition},
      'summary':summary(rows),'runs':rows,'long_scope_limits':long,'frozen_product_unchanged':True,
      'deterministic_output_digests':{key:sorted(value) for key,value in output_digests.items()},
      'clinical_validation':False,'patient_inputs_read':False,'raw_large_files_are_private_local_only':True}
    save_json(Path(args.output)/'receipt.json',receipt)
    print(canonical({'phase':'benchmark_complete','receipt':str(Path(args.output)/'receipt.json'),'summary':receipt['summary']}),flush=True)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--module-root',required=True);parser.add_argument('--output',default=str(Path(tempfile.gettempdir())/'synthetic-stt-benchmark'))
    parser.add_argument('--prepare',action='store_true');parser.add_argument('--run',action='store_true')
    parser.add_argument('--condition',default='operator did not attest hardware quiet; exploratory only')
    parser.add_argument('--worker',action='store_true');parser.add_argument('--kind');parser.add_argument('--process-index',type=int)
    parser.add_argument('--worker-result');parser.add_argument('--progress')
    args=parser.parse_args();os.environ['PYTHONDONTWRITEBYTECODE']='1';sys.dont_write_bytecode=True
    if args.worker:worker(args);return
    output=Path(args.output);manifest=prepare(args.module_root,output)
    if args.prepare:verify(args.module_root,output,manifest)
    if args.run:run(args,manifest)
    if not args.prepare and not args.run:parser.error('choose --prepare or --run')

if __name__=='__main__':main()
