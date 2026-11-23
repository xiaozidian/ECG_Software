"""Create one private P01 source locally; never copy reports, DBs or free text."""
from pathlib import Path
from hashlib import sha256
import argparse
import json
import os
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from ecg_core import doctor_source as contract
from ecg_core.ebi import load_records
from ecg_core.repository import CaseRepository

def export_case(case,output,*,mathematical_fixture=False):
    output=Path(output).resolve()
    original=Path(case['paths']['case_dir']).resolve()
    assert output!=original and original not in output.parents and output not in original.parents
    assert not output.exists(),'Use a new output directory; original and previous output are retained'
    sources={key:Path(case['paths'][key]) for key in ['data','ebi','lps']}
    before={key:contract.file_hash(path) for key,path in sources.items()}
    original_records=load_records(str(sources['ebi']))
    output.mkdir(parents=True,mode=0o700)
    for key,name in contract.PATHS.items():
        target=output/name;target.parent.mkdir(parents=True,exist_ok=True)
        if key=='data':shutil.copyfile(sources[key],target)
        elif key=='ebi':
            with sources[key].open('rb') as source,target.open('xb') as destination:
                assert len(source.read(32))==32
                destination.write(bytes(32));shutil.copyfileobj(source,destination)
        else:target.write_bytes(contract.clean_lps(case))
        target.chmod(0o600)
    assert contract.file_hash(output/contract.PATHS['data'])==before['data']
    assert load_records(str(output/contract.PATHS['ebi']))==original_records
    cleaned=contract.validate_clean_lps(output/contract.PATHS['lps'])
    assert cleaned['summary']==case['summary'],'Recognized clinical summary changed'
    raw_bytes=(output/contract.PATHS['data']).stat().st_size
    assert raw_bytes%16==0
    rows=[{'path':name,'size_bytes':(output/name).stat().st_size,
           'sha256':contract.file_hash(output/name)} for name in sorted(contract.PATHS.values())]
    dataset=sha256()
    for row in rows:dataset.update(row['path'].encode());dataset.update(row['sha256'].encode('ascii'))
    manifest={'schema_version':1,'source_id':contract.SOURCE_ID,'case_id':contract.CASE_ID,
        'profile':contract.PROFILE,'source_version':contract.VERSION,
        'kind':'mathematical_deidentified_fixture' if mathematical_fixture else 'deidentified_patient',
        'wholly_synthetic':mathematical_fixture,'patient_inputs_read':not mathematical_fixture,
        'clinical_validation':False,'sampling_rate_hz':200,'channel_count':8,
        'stored_channels':contract.CHANNELS,'sample_format':'little-endian int16',
        'sample_count':raw_bytes//16,'duration_seconds':raw_bytes/3200,'expected_raw_bytes':raw_bytes,
        'deidentification':contract.DEIDENTIFICATION,'files':rows,'dataset_sha256':dataset.hexdigest()}
    (output/'source-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    # Search only text/paths. Raw headerless int16 and structured EBI records are
    # not interpreted as text or modified to eliminate coincidental byte matches.
    texts=(output/'source-manifest.json').read_text()+(output/contract.PATHS['lps']).read_text()+''.join(contract.PATHS.values())
    protected=[case['case_id'],*[str(case['metadata'].get(key) or '').strip() for key in
               ['name','patient_id','bed','requesting_physician','department','clinical_diagnosis']]]
    assert all(token not in texts for token in protected if len(token)>=2),'Original identifier survived in export text'
    assert before=={key:contract.file_hash(path) for key,path in sources.items()},'Original input changed during export'
    contract.validate_source(output)
    return {'status':'passed','source_id':'P01','kind':manifest['kind'],
        'duration_seconds':manifest['duration_seconds'],'raw_bytes':raw_bytes,
        'waveform_bytes_unchanged':True,'all_ebi_records_unchanged':True,
        'ebi_header_replaced':True,'recognized_summary_unchanged':True,
        'original_inputs_unchanged':True,'identifier_text_scan_passed':True,
        'original_reports_images_databases_excluded':True,'files':4,
        'clinical_validation':False,'output':str(output)}

def main():
    p=argparse.ArgumentParser();p.add_argument('--local-config',type=Path,required=True)
    p.add_argument('--case-index',type=int,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--receipt',type=Path,required=True)
    args=p.parse_args();config=json.loads(args.local_config.read_text())
    cases,issues=CaseRepository(Path(config['data_root'])).scan_cases()
    assert not issues and 1<=args.case_index<=len(cases)
    result=export_case(cases[args.case_index-1],args.output)
    result['software_case_index']=args.case_index
    args.receipt.parent.mkdir(parents=True,exist_ok=True)
    with args.receipt.open('x') as stream:json.dump(result,stream,ensure_ascii=False,indent=2);stream.write('\n')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
    try:main()
    except Exception as error:
        print(type(error).__name__+': deidentification did not finish; originals retained; private values omitted',file=sys.stderr)
        raise SystemExit(1)
