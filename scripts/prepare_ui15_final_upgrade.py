"""Pin producer887's actual passed1–14 and immutable4 ZIPs; execute only upgrade.

The producer stays failure15. Its raw failed upgrade JSON proves the obsolete
ST global-button entry. No job-log API, package rewrite, approval seed or extra
physician checkpoint is used. Fresh upgrade evidence is separately attributed.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.prepare_ui15_baseline import api,download,dump,one,read,verify_runtime_source
from scripts.prepare_ui15_native_continuation import xml_counts,validate_original_scopes
from scripts.repack_windows_ui15 import compare_programs,hashes
from scripts.shared_source import snapshot
from scripts.verify_public_release import verify
from scripts.verify_windows_stt_independent_upgrade import embedded_modules
from scripts.windows_deidentified_package import unpack
from scripts.windows_doctor_build import SOURCE_FILES,digest,verify_content_manifest

REPO='xiaozidian/ECG_Software'
CONTRACT=ROOT/'scripts/ui15-final-upgrade-contract.json'


def current(c):
    changed=subprocess.check_output(['git','diff','--name-only',c['producing_commit'],'HEAD'],cwd=ROOT,text=True).splitlines()
    assert set(changed)==set(c['QA_allowed_paths']),changed
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()
    shared,_=snapshot(ROOT);identity=verify(ROOT)
    assert shared==read(ROOT/'shared-source-build.json')
    assert shared['core_version']==c['core_version'] and shared['ui_version']==c['ui_version'] and shared['source_fingerprint']==c['common_source_fingerprint']
    assert identity['source_sha256']==c['production129_sha256'] and identity['production_files_verified']==129 and identity['release_id']==c['ui_release_id']
    verify_runtime_source(read(ROOT/'scripts/ui15-baseline-contract.json'))
    assert digest(ROOT/'scripts/verify_windows_ui15_upgrade.py')==c['corrected_upgrade_helper_sha256']
    return shared,identity,changed


def producer(c):
    run=api(REPO,f'/actions/runs/{c["producing_run"]}')
    assert (run['status'],run['conclusion'],run['head_sha'],run['path'],run['event'],run['run_attempt'])==(
        'completed','failure',c['producing_commit'],'.github/workflows/windows-ui-source-render.yml','workflow_dispatch',1)
    jobs=api(REPO,f'/actions/runs/{run["id"]}/jobs')['jobs'];assert len(jobs)==1 and jobs[0]['id']==c['producing_job']
    steps={str(s['number']):dict(name=s['name'],conclusion=s['conclusion']) for s in jobs[0]['steps']}
    assert steps==c['producer_steps'] and {n for n,s in steps.items() if s['conclusion']=='failure'}=={'15'}
    assert all(steps[str(n)]['conclusion']=='success' for n in range(1,15))
    rows=api(REPO,f'/actions/runs/{run["id"]}/artifacts')['artifacts']
    assert len(rows)==5 and {r['name'] for r in rows}==set(c['outer_artifacts'])
    for row in rows:
        wanted=c['outer_artifacts'][row['name']]
        assert not row['expired'] and row['id']==wanted['id'] and row['digest']==wanted['digest'] and row['size_in_bytes']==wanted['bytes']
        assert row['workflow_run']['id']==run['id'] and row['workflow_run']['head_sha']==c['producing_commit']
    return run,rows


def bound_scopes(original,c):
    backend,ui=validate_original_scopes(original,c)
    oracle=xml_counts(one(original,'demo-full-record.xml'),total=5,modes=c['demo_modes'])
    perf=read(one(original,'windows-request-source-perf.json'))
    assert perf['status']=='passed' and perf['environment']['system']=='Windows' and perf['environment']['python']=='3.12.10'
    assert perf['summary']['fallback']['requests']==perf['summary']['request_lease']['requests']==3
    native=read(one(original,'browser-validation.json'));p01=read(one(original,'p01-native.json'));report=read(one(original,'report-evidence-native.json'))
    assert native['status']==p01['status']==report['status']=='passed'
    assert len(native['checks'])==41 and len(p01['checks'])==8 and all(r['status']=='passed' for r in native['checks']+p01['checks'])
    assert native['scope']['native_frozen_runtime'] is True and native['scope']['mathematical_source_only'] is True
    assert native['network']['external_requests']==0 and native['network']['page_errors']==native['network']['http_errors']==native['network']['resource_failures']==[]
    assert p01['patient_inputs_read'] is False and p01['pdf_operations']==0
    assert report['source_commit']==c['producing_commit'] and report['packaging_version']=='1.0.15' and report['archive_sha256']==c['package_bytes']['p01']['sha256'] and report['exe_sha256']==c['EXE_sha256']
    assert report['native_frozen_runtime'] is True and report['ui']['actual_UI_checks']==12 and report['ui']['actual_PE_API_lifecycle_checks']==2 and len(report['ui']['checks'])==14
    assert not report['page_errors'] and not report['blocked_requests'] and not report.get('cleanup_errors')
    failed=read(one(original,'ui15-upgrade-native.json'))
    assert failed['status']=='failed' and failed['native_frozen_runtime'] is False and failed['checks']==[]
    assert failed['base_ui']['status']=='passed' and len(failed['base_ui']['checks'])==14
    assert failed['error']==c['exact_failed_upgrade_error']
    assert 'locator("#workflowNext")' in failed['error'] and 'hidden=""' in failed['error'] and 'element is not visible' in failed['error']
    assert failed['page_errors']==failed['blocked_requests']==[] and failed['cleanup_errors']==c['original_failure_cleanup_errors']
    return dict(backend=backend['current'],UI=ui['current'],demo_oracle=oracle,standalone_Node_commands=6,named_contract_outputs=7,
        request_perf_rounds=3,native=dict(full=41,P01=8,ST_AF_UI_and_API=14,total=63),
        attribution='Actual original887 producer steps1–14 only; not fresh executions in this continuation',historical_AF_materials_missing=True)


def prepare(args):
    assert os.name=='nt' and not args.output.exists();args.output.mkdir(parents=True)
    c=read(CONTRACT);shared,identity,changed=current(c);run,rows=producer(c)
    original_artifacts=args.output/'original-artifacts'
    with ThreadPoolExecutor(max_workers=3) as pool:
        proofs=list(pool.map(lambda row:download(REPO,{**row,'bytes':row['size_in_bytes']},original_artifacts/c['outer_artifacts'][row['name']]['role']),rows))
    original=original_artifacts/'original887';scopes=bound_scopes(original,c)
    evidence=args.output/'evidence';shutil.copytree(original,evidence/'original887')
    dump(evidence/'original887'/'producer-run.json',{k:run[k] for k in ('id','head_sha','status','conclusion','path','event','html_url','run_attempt')})
    dump(evidence/'original887'/'producer-artifacts.json',rows)
    base=read(args.baseline_proof);assert base['status']=='verified_baseline14_reused_not_new_UI15_acceptance'
    baseline=read(ROOT/'scripts/ui15-baseline-contract.json')
    assets={n for n,r in shared['files'].items() if r['component']=='ui'};assert len(assets)==80
    paths={};programs={};payloads={}
    for role,description in c['package_bytes'].items():
        path=one(original_artifacts/role,description['filename'])
        assert digest(path)==description['sha256'] and path.stat().st_size==description['bytes']
        assert path.with_name(path.name+'.sha256').read_text().split()==[digest(path),path.name]
        paths[role]=str(path);payloads[role]=dict(path=str(path),sha256=digest(path),bytes=path.stat().st_size)
        if role=='math':continue
        package=unpack(path,args.output/('unpacked-'+role));verify_content_manifest(package)
        kind={'p01':'P01_software','full':'M01_full','update':'M01_update'}[role]
        before=unpack(Path(base['paths'][kind]),args.output/('old14-'+role));verify_content_manifest(before)
        release=read(package/'RELEASE.json')
        assert release['source_commit']==c['producing_commit'] and release['packaging_version']=='1.0.15' and release['app_version']==release['software_version']=='0.12.29-stt-independent.20261104'
        assert release['production_source_identity']==identity and release['ui_release_id']==c['ui_release_id']
        assert release['binary_reused_without_rebuild'] is release['ui_repack_only'] is True
        assert release['source_id']==('P01' if role=='p01' else 'M01') and digest(package/'CardioInsightDoctorEval.exe')==c['EXE_sha256']
        assert read(package/'_internal/shared-source-build.json')==shared
        for name in assets:assert (package/'_internal'/name).read_bytes()==(ROOT/name).read_bytes(),name
        compare_programs(hashes(before),hashes(package),assets)
        assert not (package/'Sources').exists() if role!='full' else (package/'Sources/M01').is_dir()
        programs[role]=package
    compiled=embedded_modules(programs['p01']/'CardioInsightDoctorEval.exe',ROOT)
    assert compiled['runtime_python_sha256']==baseline['immutable_Windows_runtime_python_source_sha256']
    def internal(p):return {n:r for n,r in read(p/'CONTENTS.json')['files'].items() if n.startswith('_internal/')}
    assert internal(programs['p01'])==internal(programs['full'])==internal(programs['update'])
    with zipfile.ZipFile(paths['math']) as data:
        assert data.testzip() is None and {n for n in data.namelist() if not n.endswith('/')}=={'M01/'+n for n in SOURCE_FILES}
        for name in SOURCE_FILES:assert hashlib.sha256(data.read('M01/'+name)).hexdigest()==digest(programs['full']/'Sources/M01'/name)
    build=read(one(original_artifacts/'full','build-report.json'))
    assert build['source_commit']==c['producing_commit'] and build['production_source_identity']==identity and build['embedded_runtime']==compiled
    assert build['final_zip_crc_and_content_hashes_verified'] and build['final_unpacked_exe_self_check_passed'] and build['final_unpacked_exe_process_smoke_passed'] and build['no_PyInstaller_or_compiler_invoked']
    paths['base14_p01']=base['paths']['P01_software']
    proof=dict(status='producer887_passed1to14_and_exact_four_ZIPs_verified_upgrade_pending',producer_run=c['producing_run'],producer_commit=c['producing_commit'],producer_conclusion='failure',
        original_sole_failure='step15 obsolete hidden global ST-T confirmation entry on original14; preserved raw JSON',
        original_gates_attributed=scopes,source_identity=identity,common_source_fingerprint=shared['source_fingerprint'],core_version=shared['core_version'],ui_version=shared['ui_version'],
        compiled_runtime40=compiled,every_non_UI_runtime_byte_exact14=True,UI80_verified=True,original_four_ZIPs_immutable=payloads,outer_artifact_proofs=proofs,
        old14_72_reused_baseline_only=True,QA_only_changed_paths=changed,no_original_ZIP_repack_or_metadata_rewrite=True,clinical_validation=False)
    dump(evidence/'final-upgrade-prerequisites.json',proof)
    dump(args.output/'final-upgrade-input.json',dict(paths=paths,producer_run=c['producing_run'],producer_commit=c['producing_commit']))


def finalize(args):
    c=read(CONTRACT);current(c);evidence=args.output/'evidence';proof=read(evidence/'final-upgrade-prerequisites.json')
    assert proof['status']=='producer887_passed1to14_and_exact_four_ZIPs_verified_upgrade_pending' and proof['producer_conclusion']=='failure'
    for row in proof['original_four_ZIPs_immutable'].values():
        path=Path(row['path']);assert digest(path)==row['sha256'] and path.stat().st_size==row['bytes']
    upgrade=read(evidence/'upgrade/ui15-upgrade-native.json')
    assert upgrade['status']=='passed' and upgrade['native_frozen_runtime'] is True and len(upgrade['checks'])==8
    assert upgrade['package_identity']['base_packaging_version']=='1.0.14' and upgrade['package_identity']['new_packaging_version']=='1.0.15'
    assert upgrade['ui_archive_sha256']==c['package_bytes']['p01']['sha256'] and upgrade['reviewed_evidence']['report_status']=='reviewed' and upgrade['reviewed_evidence']['composition_provenance_valid'] is True
    assert upgrade['existing_UUID_ledger_rows_preserved']>=2 and upgrade['database']['tables']['stt_review_submissions']['row_count']==upgrade['existing_UUID_ledger_rows_preserved']
    before=read(evidence/'upgrade/ui-upgrade-before-report.json');after=read(evidence/'upgrade/ui-upgrade-after-report.json');assert before==after and before['status']=='reviewed'
    exception=upgrade['metadata_table_exceptions'];assert len(exception)==1 and exception[0]['appended_row_count']==1 and exception[0]['all_other_tables_identical'] is True
    assert not upgrade['page_errors'] and not upgrade['blocked_requests'] and not upgrade.get('cleanup_errors')
    assert len(upgrade['source_chart_inspection'])==15
    for chart in upgrade['source_chart_inspection']:
        assert chart['readonly_source_state_identical'] is True and [z['factor'] for z in chart['zooms']]==[1,1.5,2,3]
        assert all(z['width']>0 and z['height']>0 and z['dpr']>0 for z in chart['zooms'])
    assert all(r['method'] not in ('PUT','PATCH','DELETE') for r in upgrade['after_reopen_requests'])
    result=dict(status='UI15_original887_four_ZIPs_accepted_by_strict_final_upgrade_composite',producer_run=c['producing_run'],producer_commit=c['producing_commit'],producer_conclusion='failure',
        QA_run=int(os.environ['GITHUB_RUN_ID']),QA_commit=os.environ['GITHUB_SHA'],original_gates_attributed=proof['original_gates_attributed'],
        new_actual14_to15_primary_checks=8,combined_native_primary_count=71,source_chart_zoom_cases_nested_in_new_upgrade=60,
        reviewed_report_basis_manual_acknowledgements_UUID_ledger_and_all_non_audit_tables_unchanged=True,
        original_four_ZIPs_unchanged=True,accepted_package_bytes=c['package_bytes'],old14_72_reused_baseline_only=True,
        full_repository_green_claimed=False,clinical_validation=False,hospital_physical_Windows10_verified=False)
    dump(evidence/'UI15-ACCEPTANCE.json',result);print(json.dumps(result))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--baseline-proof',type=Path);p.add_argument('--finalize',action='store_true');a=p.parse_args()
    assert os.name=='nt'
    if a.finalize:finalize(a)
    else:assert a.baseline_proof is not None;prepare(a)


if __name__=='__main__':main()
