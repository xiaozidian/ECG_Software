#!/usr/bin/env python3
"""Bind compile producer, passed current-native gates, and new migration only.

No original ZIP is edited and no EXE is run here. Current-native run42667416632
really passed full software/P01/fresh ST-T+AF, but remains an overall failure:
its old15 PYZ loader failed before an old15 workspace/process was started.
Only a later actual complete15->17 migration and original M01 parity may close
that gap. The current-native QA and original failed15 bytes stay unchanged.
"""
from __future__ import annotations

import argparse
import ast
import base64
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import prepare_windows17_native_continuation as native

CURRENT_RUN = 42667416632
CURRENT_HEAD = 'e9829742f39c6b1822ab784b1db49699b1c43e1f'
CURRENT_JOB = 129334682972
WORKFLOW = native.MIGRATION_WORKFLOW
QA_ARTIFACT = dict(id=13698622313, name='Windows-doctor-eval-mathematical-validation-1.0.17',
                   sha256='724bb317140c144cf447312546d6a4a2c869a3724ec1b076d9b6a43ebd150a94', bytes=3667484)
RECEIPT_SHA = {
    'browser-validation.json': '4954f4e0d0a07e19bb200b1679d7b04eafb22298efa082189bb00b354fc1558f',
    'p01-native.json': '6182daf2d519c6324902ab207a4cfaa1cd3e61e9e4308ed6890316ff112446a3',
    'comprehensive-native.json': '796d21958d7f4375f68bcc340ca568b3f1851e9af69c0648979cd44bcee3fe7f',
    'upgrade15-to17-native.json': '1b9f1c4649999eac1ed9fad479449b775bfec777abefe4a6345e7463a2da97c1',
}
ERROR = "ModuleNotFoundError: No module named '_actual_immutable_windows15.evaluation_status'"
STEPS = {
    12: 'Actual original17 System Edge full software and retained-source update validation',
    13: 'Actual original17 P01 source save reopen and update using mathematical fixture only',
    14: 'Actual fresh17 ST-T and AF multistrip doctor flows on system Edge',
    15: 'Actual original15 to original fresh17 same-workspace reviewed report and UUID retention',
}
RECEIPTS = {12: ('browser-validation.json', b'DOCTOR_BROWSER_RECEIPT_JSON=', b'verify_windows_doctor_browser.py'),
            13: ('p01-native.json', b'P01_NATIVE_RECEIPT_JSON=', b'verify_windows_p01.py'),
            14: ('comprehensive-native.json', b'WINDOWS_AF17_NATIVE_JSON=', b'verify_windows_af_multistrip_native.py'),
            15: ('upgrade15-to17-native.json', b'WINDOWS_AF17_NATIVE_JSON=', b'verify_windows_af_multistrip_native.py')}
require, read, dump, digest = native.require, native.read, native.dump, native.digest


def current_file(root, name):
    found = [p for p in Path(root).rglob(name) if p.is_file() and 'producer-original-QA' not in p.parts]
    require(len(found) == 1 and not found[0].is_symlink(), 'Expected one current-native ' + name)
    return found[0]


def validate_metadata(run, jobs, artifacts):
    require(run['id'] == CURRENT_RUN and run['head_sha'] == CURRENT_HEAD and run['path'] == native.ACCEPTANCE_WORKFLOW and
            run['status'] == 'completed' and run['conclusion'] == 'failure' and run['run_attempt'] == 1 and
            run['repository']['full_name'] == run['head_repository']['full_name'] == native.REPO,
            'Fixed current-native run/head/overall failure differs')
    require(jobs['total_count'] == len(jobs['jobs']) == 1, 'Ambiguous current-native job')
    job = jobs['jobs'][0]
    require(job['id'] == CURRENT_JOB and job['run_id'] == CURRENT_RUN and job['head_sha'] == CURRENT_HEAD and
            job['run_attempt'] == 1 and job['name'] == native.PRODUCER_JOB_NAME and
            job['status'] == 'completed' and job['conclusion'] == 'failure', 'Fixed current-native job differs')
    steps = {s['number']: s for s in job['steps']}
    require(len(steps) == len(job['steps']) and {n for n, s in steps.items() if s['conclusion'] == 'failure'} == {15} and
            all(steps[n]['conclusion'] == 'success' for n in range(1, 15)) and steps[16]['conclusion'] == 'skipped',
            'Current-native actual passed gates/sole failed15 attribution differs')
    for number, name in STEPS.items():
        require(steps[number]['name'] == name and steps[number]['status'] == 'completed' and
                steps[number]['conclusion'] == ('failure' if number == 15 else 'success'), 'Current-native gate identity differs')
    rows = artifacts['artifacts']
    require(artifacts['total_count'] == len(rows) == 1, 'Current-native failed run must retain its sole original QA artifact')
    row = rows[0]
    require(row['id'] == QA_ARTIFACT['id'] and row['name'] == QA_ARTIFACT['name'] and row['expired'] is False and
            row['digest'] == 'sha256:' + QA_ARTIFACT['sha256'] and row['size_in_bytes'] == QA_ARTIFACT['bytes'] and
            row['workflow_run']['id'] == CURRENT_RUN and row['workflow_run']['head_sha'] == CURRENT_HEAD,
            'Current-native original QA artifact identity differs')
    return {'run_id': CURRENT_RUN, 'head_sha': CURRENT_HEAD, 'job_id': CURRENT_JOB, 'overall_conclusion': 'failure',
            'actual_passed_steps12_to14': [steps[n] for n in (12, 13, 14)], 'original_failed_step15': steps[15],
            'original_M01_parity_step16': steps[16]}


def runtime_hashes(root=ROOT):
    paths = [root / 'app.py', root / 'win_doctor_eval.py', *sorted((root / 'ecg_core').glob('*.py'))]
    require(len(paths) == 40, 'Frozen current runtime file set differs')
    return {p.relative_to(root).as_posix(): digest(p) for p in paths}


def validate_receipts(root):
    rows = {}
    for name, wanted in RECEIPT_SHA.items():
        path = current_file(root, name)
        require(digest(path) == wanted, 'Original current-native receipt bytes differ: ' + name)
        rows[name] = read(path)
    browser, p01, fresh, failed = (rows[n] for n in ('browser-validation.json', 'p01-native.json', 'comprehensive-native.json', 'upgrade15-to17-native.json'))
    require(browser['status'] == p01['status'] == fresh['status'] == 'passed', 'An actually passed native gate was changed')
    require(len(browser['checks']) == 41 and len(p01['checks']) == 8 and
            all(c['status'] == 'passed' for c in browser['checks'] + p01['checks']), 'Original native41/P01-8 checks differ')
    require(browser['platform']['system'] == 'Windows' and browser['scope']['native_frozen_runtime'] is True and
            browser['scope']['mathematical_source_only'] is True and browser['scope']['clinical_validation'] is False and
            browser['runtime']['frozen_executable'] is True and browser['runtime']['pe_machine'] == 'AMD64' and
            browser['runtime']['process_images_match_frozen_exe'] is True and browser['browser']['installed_system_browser'] is True,
            'Original full-software native runtime/source proof differs')
    require(browser['performance']['repeats'] == len(browser['performance']['rounds']) == 3 and
            browser['network']['page_errors'] == browser['network']['http_errors'] == browser['network']['resource_failures'] == [] and
            browser['network']['external_requests'] == 0, 'Original software repeat/network proof differs')
    require(p01['patient_inputs_read'] is False and p01['clinical_validation'] is False and p01['pdf_operations'] == 0 and
            p01['kind'] == 'mathematical_deidentified_fixture', 'Original P01 scope differs')
    provenance = dict(source_compile_commit=native.SOURCE_COMPILE_COMMIT, producer_run_id=native.PRODUCER,
                      controller_commit=CURRENT_HEAD, acceptance_run_id=CURRENT_RUN,
                      original_PE_recompiled=False, original_delivery_ZIPs_repacked=False)
    expected_runtime = runtime_hashes()
    for value in (fresh, failed):
        identity = value['package_identity']
        require(identity['source_commit'] == native.SOURCE_COMPILE_COMMIT and identity['new_exe_sha256'] == native.ORIGINAL_EXE_SHA and
                identity['packaging_version'] == native.VERSION and identity['application_version'] == native.APP and
                identity['production_source_identity']['source_sha256'] == native.PRODUCTION_SHA and
                identity['shared_source_fingerprint'] == native.COMMON_SHA and identity['packaged_UI_files'] == 81 and
                value['acceptance_provenance'] == provenance and value['new_archive_sha256'] == native.ORIGINAL_INNERS['p01']['sha256'],
                'Current-native producer/PE/ZIP/controller binding differs')
        require(value['embedded_new_runtime']['runtime_python_files_verified'] == 40 and
                value['embedded_new_runtime']['runtime_python_sha256'] == expected_runtime and
                value['embedded_new_runtime']['includes_new_ST_record_module'] is True and
                value['patient_inputs_read'] is False and value['clinical_validation'] is False and value['pdf_operations'] == 0,
                'Current-native original PYZ40/runtime scope differs')
    require(fresh['mode'] == 'actual-fresh17-comprehensive-STT-and-AF-multistrip-doctor-flow' and
            fresh['primary_checks'] == len(fresh['checks']) == 22 and fresh['ui']['status'] == fresh['af_multistrip_ui']['status'] == 'passed' and
            fresh['ui']['primary_checks'] == fresh['af_multistrip_ui']['primary_checks'] == 10 and
            fresh['native_frozen_runtime'] is fresh['source_hashes_unchanged'] is fresh['bundled_python_proved'] is True and
            fresh['page_errors'] == fresh['blocked_requests'] == fresh['cleanup_errors'] == [], 'Actual fresh ST-T/AF acceptance differs')
    require(failed['status'] == 'failed' and failed['mode'] == 'actual15-to17-upgrade' and failed['checks'] == [] and
            failed['error'] == ERROR and failed['package_identity']['base_exe_sha256'] == native.OLD_EXE_SHA and
            not any(k in failed for k in ('actual_processes', 'old15_baseline_ui', 'api_upgrade', 'database_upgrade')),
            'Original pre-old15-workspace loader failure was changed or promoted')
    return {'receipt_sha256': dict(RECEIPT_SHA), 'actual_passed': {'full_software': 41, 'P01': 8, 'fresh_STT_AF': 22},
            'source_compile_commit': native.SOURCE_COMPILE_COMMIT, 'current_native_head': CURRENT_HEAD,
            'current_native_run_id': CURRENT_RUN, 'original_failed15': failed,
            'original_failure_not_promoted': True, 'migration_native_pending': True}


def validate_compile_chain(qa):
    source = native.one(qa, 'continuation-prerequisites.json')
    proof = read(source)
    inputs = read(native.one(qa, 'continuation17-input.json'))
    require(inputs['producer_proof_sha256'] == digest(source) and inputs['source_compile_commit'] == native.SOURCE_COMPILE_COMMIT and
            inputs['producer_run_id'] == native.PRODUCER, 'Original current-native compile producer input binding differs')
    expected_acceptance = native.validate_acceptance(read(native.one(qa, 'acceptance-run-at-preparation.json')), CURRENT_HEAD, CURRENT_RUN)
    require(inputs['acceptance'] == proof['acceptance'] == expected_acceptance and proof['source_compile_commit'] == native.SOURCE_COMPILE_COMMIT,
            'Original compile producer/current-native acceptance roles differ')
    producer = native.validate_producer_metadata(read(native.one(qa, 'producer-run.json')), read(native.one(qa, 'producer-jobs.json')),
                                                read(native.one(qa, 'producer-artifacts.json')))
    require({k: v for k, v in proof['producer'].items() if k != 'original_failed16_log'} == producer,
            'Original compile producer failure was relabelled')
    producer_roots = [p for p in Path(qa).rglob('producer-original-QA') if p.is_dir()]
    require(len(producer_roots) == 1, 'Ambiguous original compile producer QA')
    scopes = native.validate_qa(producer_roots[0])
    require(proof['scopes'] == scopes, 'Original106/885/833/performance scopes changed')
    raw16 = native.validate_failed16_archive(native.one(qa, f'producer-{native.PRODUCER}-run-logs.zip'), read(native.one(qa, 'producer-jobs.json')))
    bound16 = native.bind_failed16_qa(raw16, scopes)
    old_log = proof['producer']['original_failed16_log']
    require(native.one(qa, 'producer-failed-step16-original.log').read_bytes() == raw16['slice'] and
            all(old_log[k] == v for k, v in bound16.items()) and old_log['sha256'] == raw16['proof']['sha256'],
            'Original producer raw failed16/independent QA binding changed')
    for role, wanted in native.ORIGINAL_INNERS.items():
        require(proof['inner_archives'][role]['sha256'] == wanted['sha256'] and proof['inner_archives'][role]['bytes'] == wanted['bytes'] and
                proof['inner_archives'][role]['original_bytes_not_repacked'] is True, 'Current-native original four ZIP identities changed')
    require(proof['compiled_runtime']['runtime_python_files_verified'] == 40 and
            proof['compiled_runtime']['runtime_python_sha256'] == runtime_hashes() and
            all(p['exe_sha256'] == native.ORIGINAL_EXE_SHA for p in proof['package_identities'].values()) and
            proof['original_ZIPs_repacked'] is False and proof['actual_EXE_executed_by_preparer'] is False,
            'Current-native original compile/PYZ/PE identity changed')
    return {'original_proof_sha256': digest(source), 'source_compile_commit': native.SOURCE_COMPILE_COMMIT,
            'compile_producer_run_id': native.PRODUCER, 'original_producer_conclusion': 'failure',
            'original_four_ZIPs': native.ORIGINAL_INNERS, 'original_PE_sha256': native.ORIGINAL_EXE_SHA,
            'compiled40': True, 'original_producer_scopes': scopes, 'original_failed16_retained': True}


def git_blob(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def validate_code_lock(index, original_controller, root=ROOT):
    files = {r['name']: r for r in index if r['type'] == 'file' and Path(r['name']).suffix in ('.py', '.js', '.cjs', '.json')}
    require(len(files) >= 50 and 'verify_windows_af_multistrip_native.py' in files, 'Incomplete original current-native script index')
    expected = original_controller
    require(expected['path'] == 'scripts/verify_windows_af_multistrip_native.py' and expected['encoding'] == 'base64',
            'Wrong original current-native controller source')
    before = base64.b64decode(expected['content'])
    require(git_blob(before) == expected['sha'] == files['verify_windows_af_multistrip_native.py']['sha'], 'Original controller Git blob differs')
    after = (root / 'scripts/verify_windows_af_multistrip_native.py').read_bytes()
    def split(raw):
        tree = ast.parse(raw)
        loaders = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == 'load_old_oracles']
        require(len(loaders) == 1, 'Expected exactly one immutable15 PYZ loader')
        tree.body = [n for n in tree.body if n is not loaders[0]]
        return ast.dump(tree, include_attributes=False), ast.dump(loaders[0], include_attributes=False)
    old_tree, old_loader = split(before)
    new_tree, new_loader = split(after)
    require(old_tree == new_tree, 'Current-native code changed outside the explicitly allowed old15 loader')
    locked = {}
    for name, row in files.items():
        native._safe(name)
        if name in ('verify_windows_af_multistrip_native.py', 'prepare_windows17_native_continuation.py'):
            continue
        path = root / 'scripts' / name
        require(path.is_file() and not path.is_symlink() and git_blob(path.read_bytes()) == row['sha'], 'Locked current-native dependency changed: ' + name)
        locked[name] = row['sha']
    return {'current_native_head': CURRENT_HEAD, 'all_other_native_controller_AST_identical': True,
            'only_allowed_changed_function': 'load_old_oracles', 'old_loader_AST_sha256': hashlib.sha256(old_loader.encode()).hexdigest(),
            'migration_loader_AST_sha256': hashlib.sha256(new_loader.encode()).hexdigest(),
            'locked_script_git_blobs': locked, 'excluded_provenance_only_helper': 'prepare_windows17_native_continuation.py'}


def _step_log_bytes(archive, inventory, number, step):
    wanted = native.PRODUCER_JOB_NAME + '/' + str(number) + '_' + STEPS[number] + '.txt'
    candidates = [n for n in inventory['files'] if PurePosixPath(n).name == PurePosixPath(wanted).name]
    if candidates:
        require(candidates == [wanted], 'Multiple/wrong current-native step log members')
        return archive.read(wanted), {'name': wanted, 'source_format': 'original_step_member'}
    combined = '0_' + native.PRODUCER_JOB_NAME + '.txt'
    candidates = [n for n in inventory['files'] if PurePosixPath(n).name == combined]
    require(candidates == [combined], 'Missing original step member and unique original combined job member')
    member = archive.read(combined)
    records, offset = [], 0
    for line in member.splitlines(keepends=True):
        match = re.match(rb'^(?:\xef\xbb\xbf)?(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z) (.*?)(?:\r?\n)?$', line)
        records.append((offset, line, datetime.fromisoformat(match.group(1).decode().replace('Z', '+00:00')) if match else None,
                        match.group(2) if match else None))
        offset += len(line)
    start = datetime.fromisoformat(step['started_at'].replace('Z', '+00:00'))
    groups = [i for i, (_, _, stamp, body) in enumerate(records) if stamp is not None and
              stamp.replace(microsecond=0) == start and body.startswith(b'##[group]Run ')]
    require(len(groups) == 1, 'Missing/multiple original current-native command group in combined log')
    first = groups[0]
    following = next((i for i in range(first + 1, len(records)) if records[i][3] is not None and
                      records[i][3].startswith(b'##[group]')), len(records))
    begin = records[first][0]
    stop = records[following][0] if following < len(records) else len(member)
    return member[begin:stop], {'name': combined, 'source_format': 'exact_original_combined_member_byte_slice',
                               'source_member_sha256': inventory['files'][combined]['sha256'],
                               'source_member_bytes': len(member), 'slice_offsets': {'start': begin, 'end_exclusive': stop}}


def step_log_bytes(archive, row):
    raw = archive.read(row['name'])
    if row['source_format'] == 'exact_original_combined_member_byte_slice':
        raw = raw[row['slice_offsets']['start']:row['slice_offsets']['end_exclusive']]
    return raw


def validate_run_logs(path, jobs, qa):
    inventory = native.validate_zip(path)
    job = jobs['jobs'][0]
    require(job['id'] == CURRENT_JOB and job['run_id'] == CURRENT_RUN and job['head_sha'] == CURRENT_HEAD,
            'Wrong current-native log job')
    steps = {s['number']: s for s in job['steps']}
    result = {}
    with zipfile.ZipFile(path) as archive:
        for number, (filename, marker, script) in RECEIPTS.items():
            raw, source = _step_log_bytes(archive, inventory, number, steps[number])
            start = datetime.fromisoformat(steps[number]['started_at'].replace('Z', '+00:00'))
            end = datetime.fromisoformat(steps[number]['completed_at'].replace('Z', '+00:00')) + timedelta(seconds=1)
            bodies = []
            for line in raw.splitlines():
                match = re.match(rb'^(?:\xef\xbb\xbf)?(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z) (.*)$', line)
                require(match is not None, 'Unattributed original current-native step log line')
                stamp = datetime.fromisoformat(match.group(1).decode().replace('Z', '+00:00'))
                require(start <= stamp < end, 'Original current-native log outside its actual step interval')
                bodies.append(match.group(2))
            require(script in raw, 'Wrong original current-native command')
            embedded = [native.loads(line[len(marker):]) for line in bodies if line.startswith(marker)]
            require(len(embedded) == 1 and embedded[0] == read(current_file(qa, filename)), 'Original native log/QA full JSON object differs')
            errors = [line for line in bodies if line.startswith(b'##[error]')]
            require(errors == ([b'##[error]Process completed with exit code 1.'] if number == 15 else []), 'Original current-native exit attribution differs')
            if number == 15:
                require(ERROR.encode() in raw and b'--base-software-archive' in raw,
                        'Original failed15 error/old15 command missing')
            result[str(number)] = {**source, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw),
                                   'QA_sha256': RECEIPT_SHA[filename], 'original_QA_JSON_equal': True,
                                   'conclusion': steps[number]['conclusion']}
    return {'sha256': inventory['sha256'], 'bytes': inventory['bytes'], 'crc_verified': True, 'step_members': result}


def prepare(output, acceptance_commit, acceptance_run_id):
    require(re.fullmatch(r'[0-9a-f]{40}', acceptance_commit or '') is not None and
            type(acceptance_run_id) is int and acceptance_run_id > 0 and
            acceptance_commit not in (native.SOURCE_COMPILE_COMMIT, CURRENT_HEAD) and acceptance_run_id not in (native.PRODUCER, CURRENT_RUN),
            'New migration controller/run must differ from compile and current-native roles')
    output = Path(output).expanduser().resolve()
    require(not output.exists(), 'Preserve original migration preparation attempts')
    output.mkdir(parents=True, exist_ok=False)
    evidence = output / 'evidence'
    evidence.mkdir()
    meta = {}
    for key, endpoint in [('run', f'/actions/runs/{CURRENT_RUN}'), ('jobs', f'/actions/runs/{CURRENT_RUN}/attempts/1/jobs?per_page=100'),
                          ('artifacts', f'/actions/runs/{CURRENT_RUN}/artifacts?per_page=100')]:
        raw = native._api(endpoint)
        (evidence / ('current-native-' + key + '.json')).write_bytes(raw)
        meta[key] = native.loads(raw)
    current = validate_metadata(meta['run'], meta['jobs'], meta['artifacts'])
    archive = evidence / 'current-native-original-QA.artifact.zip'
    with archive.open('xb') as stream:
        process = subprocess.run(['gh', 'api', '--hostname', 'github.com', f'/repos/{native.REPO}/actions/artifacts/{QA_ARTIFACT["id"]}/zip'],
                                 stdout=stream, stderr=subprocess.PIPE, timeout=900, check=False)
    require(process.returncode == 0, 'Current-native original QA download failed')
    inventory = native.validate_zip(archive, QA_ARTIFACT['sha256'], QA_ARTIFACT['bytes'])
    qa = evidence / 'current-native-original-QA'
    native.extract_original(archive, qa, inventory)
    receipts = validate_receipts(qa)
    compile_chain = validate_compile_chain(qa)
    logs = evidence / f'current-native-{CURRENT_RUN}-run-logs.zip'
    logs.write_bytes(native._api(f'/actions/runs/{CURRENT_RUN}/logs'))
    log_proof = validate_run_logs(logs, meta['jobs'], qa)
    with zipfile.ZipFile(logs) as source:
        for number, row in log_proof['step_members'].items():
            (evidence / f'current-native-step{number}-original.log').write_bytes(step_log_bytes(source, row))
    index = native.loads(native._api(f'/contents/scripts?ref={CURRENT_HEAD}'))
    controller = native.loads(native._api(f'/contents/scripts/verify_windows_af_multistrip_native.py?ref={CURRENT_HEAD}'))
    index = [{k: row[k] for k in ('name', 'path', 'type', 'sha')} for row in index]
    controller = {k: controller[k] for k in ('path', 'sha', 'encoding', 'content')}
    dump(evidence / 'current-native-script-index.json', index)
    dump(evidence / 'current-native-af-controller-source.json', controller)
    lock = validate_code_lock(index, controller)
    original = native.prepare(output / 'original-producer', acceptance_commit, acceptance_run_id, WORKFLOW)
    paths = dict(original['paths'])
    paths.update(current_native_qa_root=str(qa), evidence=str(evidence),
                 original_compile_evidence=str(output / 'original-producer/evidence'),
                 compile_producer_binding_root=str(output / 'original-producer'))
    migration_acceptance = dict(original['acceptance'])
    require(migration_acceptance['workflow'] == WORKFLOW, 'Wrong actual migration acceptance workflow')
    proof = {'schema_version': 1, 'status': 'compile_and_actual_current_native_bound_migration_still_pending',
             'source_compile_commit': native.SOURCE_COMPILE_COMMIT, 'compile_producer_run_id': native.PRODUCER,
             'current_native': current, 'current_native_receipts': receipts, 'current_native_logs': log_proof,
             'current_native_QA_artifact': {**QA_ARTIFACT, 'path': str(archive), 'files': inventory['files']},
             'current_native_compile_chain': compile_chain, 'current_native_code_lock': lock,
             'migration_acceptance': migration_acceptance, 'original_compile_producer_proof_sha256': original['producer_proof_sha256'],
             'paths': paths, 'actual_EXE_executed_by_preparer': False, 'actual_prior_native_gates_rerun': False,
             'new_actual_migration_claimed_passed': False, 'clinical_validation': False, 'patient_inputs_read': False}
    proof_path = evidence / 'migration-continuation-prerequisites.json'
    dump(proof_path, proof)
    paths['current_native_proof'] = str(proof_path)
    result = {'schema_version': 1, 'source_compile_commit': native.SOURCE_COMPILE_COMMIT, 'compile_producer_run_id': native.PRODUCER,
              'current_native_run_id': CURRENT_RUN, 'current_native_head': CURRENT_HEAD,
              'migration_acceptance': migration_acceptance, 'paths': paths, 'migration_proof_sha256': digest(proof_path)}
    dump(output / 'migration17-input.json', result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--acceptance-commit', required=True)
    parser.add_argument('--acceptance-run-id', type=int, required=True)
    args = parser.parse_args(argv)
    print('WINDOWS17_MIGRATION_INPUT_JSON=' + json.dumps(prepare(args.output, args.acceptance_commit, args.acceptance_run_id), ensure_ascii=False))


if __name__ == '__main__':
    main()
