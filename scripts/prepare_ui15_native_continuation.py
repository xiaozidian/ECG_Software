"""Bind original C5 bytes and passed scopes; run all remaining native UI15 gates.

The producer remains a failed run. Its backend scope is attributed only to that
run; fresh UI/oracle/performance/native checks belong to this QA continuation.
Never rewrite, rebuild, or re-upload any of the four original delivery ZIPs.
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
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prepare_ui15_baseline import api, download, dump, one, read, verify_runtime_source
from scripts.repack_windows_ui15 import compare_programs, hashes
from scripts.shared_source import snapshot
from scripts.verify_public_release import verify
from scripts.verify_windows_stt_independent_upgrade import embedded_modules
from scripts.windows_deidentified_package import archive, unpack
from scripts.windows_doctor_build import PACKAGE_NAME, SOURCE_FILES, create_content_manifest, digest, verify_content_manifest

REPO = 'xiaozidian/ECG_Software'
CONTRACT = ROOT / 'scripts/ui15-native-continuation-contract.json'


def xml_counts(path, *, total, skip_name=None, modes=None):
    cases = list(ET.parse(path).getroot().iter('testcase'))
    assert len(cases) == total, (path, len(cases))
    assert not any(c.find('failure') is not None or c.find('error') is not None for c in cases), path
    skipped = [c for c in cases if c.find('skipped') is not None]
    if skip_name:
        assert len(skipped) == 1 and skipped[0].get('name') == skip_name
        assert skipped[0].get('classname') == 'tests.test_runtime_metadata'
        assert skipped[0].find('skipped').get('message') == 'Native macOS xattr reproduction'
    else:
        assert not skipped, path
    if modes:
        assert {c.get('name') for c in cases} == {'test_actual_demo_full_record_overview[' + m + ']' for m in modes}
    return dict(total=total, passed=total-len(skipped), failed=0, error=0, skipped=len(skipped))


def producer_proof(c):
    run = api(REPO, f'/actions/runs/{c["producing_run"]}')
    assert (run['status'], run['conclusion'], run['head_sha'], run['path'], run['run_attempt']) == (
        'completed', 'failure', c['producing_commit'], '.github/workflows/windows-ui-source-render.yml', 1)
    jobs = api(REPO, f'/actions/runs/{run["id"]}/jobs')['jobs']
    assert len(jobs) == 1 and jobs[0]['id'] == c['producing_job']
    actual = {str(s['number']): dict(name=s['name'], conclusion=s['conclusion']) for s in jobs[0]['steps']}
    assert actual == c['producer_steps'], 'Producer step truth changed'
    assert {n for n, s in actual.items() if s['conclusion'] == 'failure'} == {'10'}
    log = subprocess.check_output(['gh', 'api', f'repos/{REPO}/actions/jobs/{jobs[0]["id"]}/logs'], stderr=subprocess.PIPE, timeout=120)
    normalized = log.decode('utf-8-sig').replace('\r\n', '\n').rstrip() + '\n'
    assert hashlib.sha256(normalized.encode()).hexdigest() == c['producer_normalized_log_sha256']
    errors = [line.split('Z ', 1)[-1] for line in normalized.splitlines() if '##[error]' in line]
    assert errors == ['##[error]Process completed with exit code 1.']
    for fragment in c['sole_failure_log_fragments']:
        assert fragment in normalized, fragment
    rows = api(REPO, f'/actions/runs/{run["id"]}/artifacts')['artifacts']
    assert {r['name'] for r in rows} == set(c['outer_artifacts']) and len(rows) == 5
    for row in rows:
        expected = c['outer_artifacts'][row['name']]
        assert not row['expired'] and row['workflow_run']['id'] == run['id'] and row['workflow_run']['head_sha'] == c['producing_commit']
        assert row['id'] == expected['id'] and row['digest'] == expected['digest'] and row['size_in_bytes'] == expected['bytes']
    return run, rows, normalized


def validate_original_scopes(original, c):
    actual = {p.relative_to(original).as_posix(): dict(sha256=digest(p), bytes=p.stat().st_size) for p in original.rglob('*') if p.is_file()}
    assert actual == c['producer_receipt_files'], 'Original C5 raw receipts differ'
    backend = read(one(original, 'test-summary.json'))
    ui = read(one(original, 'ui-test-summary.json'))
    assert backend['status'] == ui['status'] == 'passed'
    assert backend['current'] == dict(total=873, passed=872, failed=0, error=0, skipped=1)
    assert ui['current'] == dict(total=829, passed=829, failed=0, error=0, skipped=0)
    assert ui['declared_test_functions'] == 289 and ui['file_count'] == 115
    xml_counts(one(original, 'scoped-tests.xml'), total=873, skip_name='test_native_xattr_does_not_interrupt_unchanged_build')
    xml_counts(one(original, 'ui-regressions-tests.xml'), total=829)
    historical = list(ET.parse(one(original, 'historical-af.xml')).getroot().iter('testcase'))
    assert len(historical) == 2 and {c.get('name') for c in historical} == set(c['historical_missing_tests'])
    for case in historical:
        error = case.find('failure')
        assert error is not None and 'FileNotFoundError' in error.get('message', '') and 'summary.json' in error.get('message', '')
    assert all(row['status'] == 'missing_historical_material' for row in backend['historical_af'])
    return backend, ui


def verify_current(c):
    changed = subprocess.check_output(['git', 'diff', '--name-only', c['producing_commit'], 'HEAD'], cwd=ROOT, text=True).splitlines()
    assert set(changed) == set(c['QA_allowed_paths']), changed
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip(), 'QA checkout must be clean'
    shared, _ = snapshot(ROOT)
    assert shared == read(ROOT/'shared-source-build.json')
    assert shared['source_fingerprint'] == c['common_source_fingerprint']
    assert shared['core_version'] == c['core_version'] and shared['ui_version'] == c['ui_version']
    identity = verify(ROOT)
    assert identity['production_files_verified'] == 129 and identity['source_sha256'] == c['production129_sha256']
    assert identity['release_id'] == c['ui_release_id']
    verify_runtime_source(read(ROOT/'scripts/ui15-baseline-contract.json'))
    return shared, identity, changed


def prepare(args):
    assert os.name == 'nt' and not args.output.exists()
    args.output.mkdir(parents=True)
    c = read(CONTRACT)
    shared, identity, changed = verify_current(c)
    run, rows, log = producer_proof(c)
    originals = args.output/'original-artifacts'
    with ThreadPoolExecutor(max_workers=3) as pool:
        proofs = list(pool.map(lambda row: download(REPO, {**row, 'bytes':row['size_in_bytes']}, originals/c['outer_artifacts'][row['name']]['role']), rows))
    original = originals/'original-C5'
    backend, ui = validate_original_scopes(original, c)
    evidence = args.output/'evidence'
    shutil.copytree(original, evidence/'original-C5')
    (evidence/'original-C5'/'producer-job.log').write_text(log, encoding='utf-8')
    dump(evidence/'original-C5'/'run.json', {k:run[k] for k in ('id','path','head_sha','status','conclusion','html_url','run_attempt')})
    dump(evidence/'original-C5'/'artifacts.json', rows)
    base = read(args.baseline_proof)
    assert base['status'] == 'verified_baseline14_reused_not_new_UI15_acceptance'
    assert base['producer49_reused'] is base['continuation23_reused'] is base['original72_composed_not_rerun'] is True
    baseline = read(ROOT/'scripts/ui15-baseline-contract.json')
    assets = {name for name, row in shared['files'].items() if row['component'] == 'ui'}
    assert len(assets) == 80
    paths, programs, payloads = {}, {}, {}
    kinds = {'p01':'P01_software', 'full':'M01_full', 'update':'M01_update'}
    for role, expected in c['package_bytes'].items():
        path = one(originals/role, expected['filename'])
        assert digest(path) == expected['sha256'] and path.stat().st_size == expected['bytes']
        assert path.with_name(path.name+'.sha256').read_text().split() == [digest(path),path.name]
        paths[role] = str(path)
        payloads[role] = dict(path=str(path), sha256=digest(path), bytes=path.stat().st_size)
        if role == 'math':
            continue
        package = unpack(path, args.output/('unpacked-'+role)); verify_content_manifest(package)
        old = unpack(Path(base['paths'][kinds[role]]), args.output/('old14-'+role)); verify_content_manifest(old)
        release = read(package/'RELEASE.json')
        assert release['source_commit'] == c['producing_commit'] and release['packaging_version'] == '1.0.15'
        assert release['app_version'] == release['software_version'] == '0.12.29-stt-independent.20261104'
        assert release['ui_release_id'] == c['ui_release_id'] and release['production_source_identity'] == identity
        assert release['ui_repack_only'] is release['binary_reused_without_rebuild'] is True
        assert release['source_id'] == ('P01' if role == 'p01' else 'M01')
        assert digest(package/'CardioInsightDoctorEval.exe') == c['EXE_sha256']
        assert read(package/'_internal/shared-source-build.json') == shared
        for name in assets:
            assert (package/'_internal'/name).read_bytes() == (ROOT/name).read_bytes(), name
        compare_programs(hashes(old), hashes(package), assets)
        assert not (package/'Sources').exists() if role != 'full' else (package/'Sources/M01').is_dir()
        programs[role] = package
    compiled = embedded_modules(programs['p01']/'CardioInsightDoctorEval.exe', ROOT)
    assert compiled['runtime_python_sha256'] == baseline['immutable_Windows_runtime_python_source_sha256']
    def internals(package):
        return {n:r for n,r in read(package/'CONTENTS.json')['files'].items() if n.startswith('_internal/')}
    assert internals(programs['p01']) == internals(programs['full']) == internals(programs['update'])
    with zipfile.ZipFile(paths['math']) as data:
        assert data.testzip() is None and {n for n in data.namelist() if not n.endswith('/')} == {'M01/'+n for n in SOURCE_FILES}
        for name in SOURCE_FILES:
            assert hashlib.sha256(data.read('M01/'+name)).hexdigest() == digest(programs['full']/'Sources/M01'/name)
    build = read(one(originals/'full','build-report.json'))
    assert build['source_commit'] == c['producing_commit'] and build['production_source_identity'] == identity
    assert build['final_zip_crc_and_content_hashes_verified'] and build['final_unpacked_exe_self_check_passed'] and build['final_unpacked_exe_process_smoke_passed']
    assert build['python_removed_from_runtime_path'] and build['no_PyInstaller_or_compiler_invoked']
    assert build['embedded_runtime'] == compiled
    # The only newly created archive is an explicitly non-deliverable updater fixture.
    fixture = args.output/'CI-only-16-fixture'/PACKAGE_NAME
    shutil.copytree(programs['update'], fixture)
    release = read(fixture/'RELEASE.json')
    dump(fixture/'RELEASE.json', {**release, 'packaging_version':'1.0.16', 'release_version':'1.0.16',
        'verification_fixture_only':True, 'verification_scope':'same exact29 binary and15 UI; packaging-only16 fixture, not a user deliverable'})
    create_content_manifest(fixture, with_source=False); verify_content_manifest(fixture)
    left,right = hashes(programs['update']),hashes(fixture)
    assert set(left) == set(right) and {n for n in left if left[n] != right[n]} <= {'RELEASE.json','CONTENTS.json','SHA256SUMS.txt'}
    fixture_archive = archive(fixture, args.output, PACKAGE_NAME+'-1.0.16-upgrade-fixture.zip')
    paths['upgrade16_fixture'] = str(args.output/fixture_archive['archive'])
    paths['full_root'] = str(programs['full'])
    paths['base14_p01'] = base['paths']['P01_software']
    source = Path(os.environ['ECG_DATA_ROOT']); assert not source.exists()
    shutil.copytree(programs['full']/'Sources/M01', source)
    for role,row in payloads.items():
        assert digest(Path(row['path'])) == row['sha256'], role
    proof = dict(status='C5_original_failed_producer_inputs_verified_QA_native_pending', producing_run=c['producing_run'],
        producing_commit=c['producing_commit'], producer_conclusion='failure', sole_producer_failure='bare demo Node invocation omitted required fixture path and mode',
        C5_backend_reused=backend['current'], C5_UI_original_attributed=ui['current'], fresh_UI_and_all_native_required=True,
        baseline14_72='49 plus23 reused baseline only; not fresh15 checks', old_baseline_proof=base,
        source_identity=identity, common_source_fingerprint=shared['source_fingerprint'], core_version=shared['core_version'], ui_version=shared['ui_version'],
        EXE_sha256=c['EXE_sha256'], UI_assets_verified=80, compiled_modules=compiled, every_non_UI_byte_exact14=True,
        original_four_ZIPs_immutable=payloads, outer_artifact_proofs=proofs, QA_only_changed_paths=changed,
        CI_only16_fixture={**fixture_archive,'user_deliverable':False}, clinical_validation=False)
    dump(evidence/'continuation-prerequisites.json', proof)
    dump(args.output/'continuation-input.json', dict(paths=paths, producing_run=c['producing_run'], producing_commit=c['producing_commit']))


def finalize(args):
    c = read(CONTRACT); verify_current(c)
    evidence = args.output/'evidence'; proof = read(evidence/'continuation-prerequisites.json')
    assert proof['status'] == 'C5_original_failed_producer_inputs_verified_QA_native_pending'
    for row in proof['original_four_ZIPs_immutable'].values():
        p=Path(row['path']); assert digest(p)==row['sha256'] and p.stat().st_size==row['bytes']
    fresh = read(one(evidence/'fresh-ui','ui-test-summary.json'))
    assert fresh['status']=='passed' and fresh['current']==dict(total=829,passed=829,failed=0,error=0,skipped=0)
    xml_counts(one(evidence/'fresh-ui','ui-regressions-tests.xml'),total=829)
    oracle = xml_counts(evidence/'demo-full-record.xml', total=5, modes=c['demo_modes'])
    commands = read(evidence/'render-contracts.json')
    assert [r['script'] for r in commands] == c['standalone_Node_commands'] and len(commands)==6
    assert all(r['exit_code']==0 and r['stdout'] for r in commands)
    perf = read(evidence/'windows-request-source-perf.json')
    assert perf['status']=='passed' and perf['environment']['system']=='Windows' and perf['environment']['python']=='3.12.10'
    assert perf['summary']['fallback']['requests']==perf['summary']['request_lease']['requests']==3
    native=read(evidence/'native/browser-validation.json'); p01=read(evidence/'native/p01-native.json')
    report=read(evidence/'native/report-evidence-native.json'); upgrade=read(evidence/'native/ui15-upgrade-native.json')
    assert native['status']==p01['status']==report['status']==upgrade['status']=='passed'
    assert len(native['checks'])==41 and len(p01['checks'])==8 and all(r['status']=='passed' for r in native['checks']+p01['checks'])
    assert report['native_frozen_runtime'] is True and report['source_commit']==c['producing_commit'] and report['packaging_version']=='1.0.15'
    assert report['ui']['actual_UI_checks']==12 and report['ui']['actual_PE_API_lifecycle_checks']==2 and len(report['ui']['checks'])==14
    assert upgrade['native_frozen_runtime'] is True and upgrade['reviewed_evidence']['report_status']=='reviewed'
    assert upgrade['reviewed_evidence']['composition_provenance_valid'] is True and upgrade['existing_UUID_ledger_rows_preserved']>=2
    assert upgrade['package_identity']['base_packaging_version']=='1.0.14' and upgrade['package_identity']['new_packaging_version']=='1.0.15'
    before=read(evidence/'native/ui-upgrade-before-report.json'); after=read(evidence/'native/ui-upgrade-after-report.json')
    assert before==after and before['status']=='reviewed'
    exception=upgrade['metadata_table_exceptions']; assert len(exception)==1 and exception[0]['appended_row_count']==1 and exception[0]['all_other_tables_identical'] is True
    assert upgrade['database']['tables']['stt_review_submissions']['row_count']==upgrade['existing_UUID_ledger_rows_preserved']
    assert len(upgrade['source_chart_inspection'])==15
    for chart in upgrade['source_chart_inspection']:
        assert chart['readonly_source_state_identical'] is True and [z['factor'] for z in chart['zooms']]==[1,1.5,2,3]
    for value in (report,upgrade):
        assert not value['page_errors'] and not value['blocked_requests'] and not value.get('cleanup_errors')
    assert all(r['method'] not in ('PUT','PATCH','DELETE') for r in upgrade['after_reopen_requests'])
    counts=dict(full_native=len(native['checks']),P01=len(p01['checks']),ST_AF_UI_and_API=len(report['ui']['checks']),actual14_to15_upgrade=len(upgrade['checks']))
    result=dict(status='UI15_strict_composite_QA_passed_original_four_ZIPs_unchanged', producer_run=c['producing_run'],producer_commit=c['producing_commit'],
        producer_conclusion='failure',QA_commit=os.environ['GITHUB_SHA'],QA_run=int(os.environ['GITHUB_RUN_ID']),
        backend873_origin='fresh C5 producer only; 872passed plus one native macOS xattr skip', fresh_UI=fresh['current'],fresh_demo_oracle=oracle,
        fresh_standalone_Node_commands=6,named_contract_outputs=7,request_performance_rounds=3,
        fresh_primary_native_checks=counts,fresh_primary_native_check_total=sum(counts.values()),
        source_chart_zoom_cases_nested_in_upgrade=60,old14_72_reused_only=True,all_original_four_ZIPs_unchanged=True,
        accepted_package_bytes=c['package_bytes'],existing_reviewed_report_basis_acknowledgements_and_UUID_ledger_preserved=True,
        historical_AF_materials_missing=True,full_repository_green_claimed=False,clinical_validation=False,hospital_physical_Windows10_verified=False)
    dump(evidence/'UI15-ACCEPTANCE.json',result); print(json.dumps(result))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--baseline-proof',type=Path)
    parser.add_argument('--finalize',action='store_true')
    args=parser.parse_args()
    if args.finalize:
        assert os.name=='nt'; finalize(args)
    else:
        assert args.baseline_proof is not None; prepare(args)


if __name__=='__main__':
    main()
