"""Bind exact freshly compiled21 bytes and passed producer gates to new native tests.

This preparer never executes an EXE, repacks a deliverable, or claims new native
acceptance. Original failed15 and incomplete three-round timing remain failures.
Only an internal packaging22 updater fixture is assembled from original21 bytes.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import marshal
from pathlib import Path
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prepare_windows17_native_continuation import (
    require, digest, loads, read, dump, one, validate_zip, extract_original,
)

REPO = 'xiaozidian/ECG_Software'
PRODUCER = 43295463674
COMPILE_COMMIT = '0c7b634ef77297d388d1e9075b01c58809e0c0aa'
JOB = 131452481364
JOB_NAME = 'Native Windows x64 package and current workstation acceptance'
WORKFLOW = '.github/workflows/windows-performance-preserve.yml'
CONTINUATION = '.github/workflows/windows-performance-continuation.yml'
APP = '0.12.32-stt-report-buttons.20261110'
VERSION = '1.0.21'
PACKAGE = 'CardioInsight-DoctorEval-Windows-x64'
PRODUCTION_SHA = '307f0d89a26c0bdbf1171343bf100d43f0e25a0a1a97e3fa8a32a1d49c145d68'
COMMON_SHA = '06a6290f14e00a652dd29cad9d81a8ac4f8423b2a3cf417071a2a5bb72c7097e'
PE_SHA = 'bb1b6d277e0fa85bdb265efa4077641fdf15f2c6e5a0b71d84e4b09ae32b225a'
POLICY_SHA = '9f925b041bce51016ac720666f2107e1d47c5f8164aae21fe13c3ebac4469ed0'
M01_SHA = '3b09e147add5a794800bc0be400ec57c347077c47546cc67c5593b3bedd745d0'
OLD20_P01_SHA = '440bdc5960387ff34f08b6e8539840d36c7ef0acdbe715a894d1cd352a7b078b'
FAILED15_SHA = '1a52820b88906c53f2d428af1cb5420aa380e26e3169a3b61b8fb00d06aa39ec'
FAILED_RECEIPT_SHA = '2b641535c84172f572e0a5c356fe591a5f52495261dea73630145876cdf3e368'
ORIGINAL_INNERS = {
    'p01': ('d59e378e28feabbf338032133a6efccbf728227f97076542eee31493c7649e41', 38444661),
    'software': ('0b6aaff2a156ce03635766dbbdb2decf6619962b77dd2863e9fe5a5681d362ae', 38437184),
    'full': ('da39c7b22ca6ce2dc68c7cb9a7a05cfb65e482c731c0cf296bfe14fe4b05fdb5', 202320459),
    'source': (M01_SHA, 163882245),
}
ARTIFACTS = {
    'p01': dict(id=13981260016, name='CardioInsight-Windows-x64-1.0.21-P01-software-only',
                bytes=38446164, sha256='5304f5384463145477b20a31a00559e1740c0f2a66ea381ce67e153ec52495fa',
                inner='CardioInsight-DoctorEval-Windows-x64-1.0.21-P01-software.zip'),
    'full': dict(id=13980755644, name='CardioInsight-Windows-x64-1.0.21-M01-full',
                 bytes=202325033, sha256='e912582aea712a0b31b9284fe0030d4e740f940c9a1de32436a0c6ddda8b8b1d',
                 inner='CardioInsight-DoctorEval-Windows-x64-1.0.21-full.zip'),
    'software': dict(id=13980980373, name='CardioInsight-Windows-x64-1.0.21-software-update',
                     bytes=38437752, sha256='b551d430cd6f7858cc2234dc65608bfb6c0c701616d6a17dc8bd1e47f9f50846',
                     inner='CardioInsight-DoctorEval-Windows-x64-1.0.21-software.zip'),
    'source': dict(id=13980730606, name='CardioInsight-Synthetic-M01-24h-v1-for-1.0.21',
                   bytes=163882723, sha256='0fe66e74323591fdacc6addf28c93313903790537e64f6a4dfca68095a00a3b8',
                   inner='CardioInsight-Synthetic-M01-24h-v1.zip'),
    'qa': dict(id=13979563406, name='Windows-doctor-eval-mathematical-validation-1.0.21',
               bytes=2094201, sha256='0734316eb1ca07b1e74a409762fcd7809418ab4ac4403cd6ccbd75770ae356cb'),
}
STEP_NAMES = {
    7: 'Windows backup ACL and committed WAL smoke',
    9: 'Regenerate exact platform policy on pinned Windows Python',
    10: 'Verify release production source fingerprint',
    11: 'Fetch exact accepted20 P01 and unchanged original mathematical M01',
    12: 'Frontend save-flow and retained report guards on actual system Edge',
    13: 'Native directory build, generated 24h source and final ZIP smoke',
    14: 'Create source-free P01 native software template',
    15: 'System Edge full software interaction and retained-source update validation',
    16: 'Actual frozen P01 source save reopen and update using mathematical fixture only',
    17: 'Actual fresh21 ST-T and AF incremental save and report card interactions on system Edge',
    18: 'Actual original20 to fresh21 same-workspace reviewed report and UUID retention',
    19: 'Prove full21 source payload equals original unchanged source archive',
}


def validate_producer(run, jobs, artifacts):
    require((run['id'], run['head_sha'], run['path'], run['status'], run['conclusion'], run['run_attempt']) ==
            (PRODUCER, COMPILE_COMMIT, WORKFLOW, 'completed', 'failure', 1), 'Producer identity/failure differs')
    require(run['repository']['full_name'] == run['head_repository']['full_name'] == REPO,
            'Producer is not the fixed repository')
    require(jobs['total_count'] == len(jobs['jobs']) == 1, 'Producer job count differs')
    job = jobs['jobs'][0]
    require((job['id'], job['run_id'], job['head_sha'], job['run_attempt'], job['name'], job['status'], job['conclusion']) ==
            (JOB, PRODUCER, COMPILE_COMMIT, 1, JOB_NAME, 'completed', 'failure'), 'Producer job identity differs')
    steps = {s['number']: s for s in job['steps']}
    require(len(steps) == len(job['steps']) and {n for n, s in steps.items() if s['conclusion'] == 'failure'} == {15},
            'Original failure is not solely step15')
    require(all(steps[n]['status'] == 'completed' and steps[n]['conclusion'] == 'success' for n in range(1, 15)),
            'Source/ACL/418/build/template prerequisites did not all pass')
    for number, name in STEP_NAMES.items():
        wanted = 'success' if number < 15 else 'failure' if number == 15 else 'skipped'
        require(steps[number]['name'] == name and steps[number]['status'] == 'completed' and
                steps[number]['conclusion'] == wanted, 'Producer step attribution differs: ' + str(number))
    require(all(steps[n]['conclusion'] == 'success' for n in range(20, 25)), 'Original artifacts were not all uploaded')
    rows = artifacts['artifacts']
    require(artifacts['total_count'] == len(rows) == 5 and
            {r['name'] for r in rows} == {r['name'] for r in ARTIFACTS.values()}, 'Original artifact set differs')
    for role, wanted in ARTIFACTS.items():
        found = [r for r in rows if r['id'] == wanted['id']]
        require(len(found) == 1, 'Original artifact identity missing/ambiguous: ' + role)
        row = found[0]
        require(row['name'] == wanted['name'] and row['size_in_bytes'] == wanted['bytes'] and
                row['digest'] == 'sha256:' + wanted['sha256'] and row['expired'] is False and
                row['workflow_run']['id'] == PRODUCER and row['workflow_run']['head_sha'] == COMPILE_COMMIT,
                'Original artifact metadata/digest differs: ' + role)
    return dict(run_id=PRODUCER, head_sha=COMPILE_COMMIT, conclusion='failure', job_id=JOB,
                passed_steps1_to14=[steps[n] for n in range(1, 15)], failed_step15=steps[15],
                skipped_native_steps16_to19=[steps[n] for n in range(16, 20)])


def validate_acceptance(run, commit, run_id):
    require(re.fullmatch('[0-9a-f]{40}', commit or '') and type(run_id) is int and run_id != PRODUCER and
            commit != COMPILE_COMMIT, 'Validator and producer must be separate explicit identities')
    require((run['id'], run['head_sha'], run['path'], run['status'], run['conclusion']) ==
            (run_id, commit, CONTINUATION, 'in_progress', None) and
            run['repository']['full_name'] == run['head_repository']['full_name'] == REPO,
            'Current validator workflow/run/commit differs')
    return dict(run_id=run_id, commit=commit, workflow=CONTINUATION, native_gates='pending')


def junit(path, expected):
    root = ET.parse(path).getroot()
    cases = list(root.iter('testcase'))
    require(len(cases) == expected and all(c.find(n) is None for c in cases for n in ('failure', 'error', 'skipped')),
            'Original JUnit has missing, failed or skipped cases: ' + Path(path).name)
    suites = list(root.iter('testsuite'))
    require(suites and sum(int(s.get('tests', -1)) for s in suites) == expected and
            all(int(s.get(k, -1)) == 0 for s in suites for k in ('errors', 'failures', 'skipped')),
            'Original JUnit counts disagree: ' + Path(path).name)
    return dict(tests=expected, passed=expected, failed=0, skipped=0, sha256=digest(path), rerun=False)


def validate_qa(qa):
    scopes = {n: junit(one(qa, n), count) for n, count in
              [('doctor21-backup-acl-smoke.xml', 1), ('doctor21-performance-tests.xml', 418)]}
    path = one(qa, 'browser-validation.json')
    require(digest(path) == FAILED_RECEIPT_SHA, 'Original failed browser receipt bytes differ')
    receipt = read(path)
    require(receipt['status'] == 'failed' and [r['status'] for r in receipt['checks']] == ['passed'] * 12 + ['failed'] and
            receipt['checks'][-1] == dict(name='browser-verification-completion', status='failed',
                                         evidence={'error': 'AssertionError: '}), 'Original failure was washed away')
    require(receipt['performance']['required_repeats'] == 3 and receipt['performance']['completed_repeats'] == 1 and
            len(receipt['performance']['rounds']) == 1, 'Original partial timing was relabelled complete')
    require(receipt['network']['external_requests'] == 0 and all(receipt['network'][n] == [] for n in
            ('external_hosts', 'resource_failures', 'page_errors', 'http_errors')), 'Original failure has unrelated errors')
    baseline = read(one(qa, 'baseline21-input.json'))
    require(baseline['status'] == 'accepted20-original-inputs-verified-only' and
            baseline['P01_SHA256'] == OLD20_P01_SHA and baseline['M01_archive_SHA256'] == M01_SHA and
            baseline['original_acceptance_run'] == 43079683855 and
            baseline['original_acceptance_head'] == 'aa18e5405e7c1a6da61d9468b147fdf9477ad234',
            'Original20/M01 baseline attribution differs')
    return dict(junit=scopes, original_failed_browser=receipt, original_failed_browser_sha256=FAILED_RECEIPT_SHA,
                completed_timing_rounds=1, required_new_timing_rounds=3, prior_passes_are_not_new_native_acceptance=True)


def validate_logs(path, receipt):
    inventory = validate_zip(path)
    failed = JOB_NAME + '/15_' + STEP_NAMES[15] + '.txt'
    freeze = JOB_NAME + '/6_Install pinned doctor build dependencies and CI-only browser test tools.txt'
    require(failed in inventory['files'] and freeze in inventory['files'], 'Authenticated original step logs missing')
    with zipfile.ZipFile(path) as z:
        raw = z.read(failed)
        require(hashlib.sha256(raw).hexdigest() == FAILED15_SHA, 'Original failed15 raw log differs')
        rows = [loads(line.split(b' DOCTOR_BROWSER_RECEIPT_JSON=', 1)[1]) for line in raw.splitlines()
                if b' DOCTOR_BROWSER_RECEIPT_JSON=' in line]
        require(rows == [receipt] and b'##[error]Process completed with exit code 1.' in raw,
                'Original failed15 log and archived QA disagree')
        rows = [loads(line.split(b' DOCTOR_BUILD_FREEZE_JSON=', 1)[1]) for line in z.read(freeze).splitlines()
                if b' DOCTOR_BUILD_FREEZE_JSON=' in line]
        require(len(rows) == 1 and rows[0] and len(rows[0]) == len(set(rows[0])), 'Original dependency freeze missing')
    return dict(raw_run_log_zip_sha256=inventory['sha256'], original_failed15_member=failed,
                original_failed15_sha256=FAILED15_SHA, _original_failed15_bytes=raw,
                resolved_build_dependencies=sorted(rows[0]))


def verify_runtime(exe):
    from PyInstaller.archive.readers import CArchiveReader
    from scripts.verify_windows_stt_independent_upgrade import normalized_code
    from ecg_core.performance_compatibility import code_value, digest as semantic_digest
    reader = CArchiveReader(exe)
    names = [n for n, row in reader.toc.items() if row[-1] == 'z']
    require(len(names) == 1, 'Expected one embedded PYZ')
    pyz = reader.open_embedded_archive(names[0])
    paths = [ROOT / 'app.py', ROOT / 'win_doctor_eval.py', *sorted((ROOT / 'ecg_core').glob('*.py'))]
    require(len(paths) == 42, 'Expected exactly all42 runtime modules')
    hashes, semantics = {}, {}
    for path in paths:
        name = path.relative_to(ROOT).as_posix()
        if name == 'win_doctor_eval.py':
            actual = marshal.loads(reader.extract('win_doctor_eval'))
        else:
            module = name[:-3].replace('/', '.')
            if module.endswith('.__init__'): module = module[:-9]
            require(module in pyz.toc, 'Embedded module absent: ' + module)
            actual = pyz.extract(module)
            semantics[module] = semantic_digest(code_value(actual))
        expected = compile(path.read_bytes(), name, 'exec', optimize=0, dont_inherit=True)
        require(normalized_code(actual) == normalized_code(expected), 'Embedded runtime source differs: ' + name)
        hashes[name] = digest(path)
    policy = read(ROOT / 'performance-compatibility.json')
    require({n: semantics.get(n) for n in policy['current_code']} == policy['current_code'],
            'Actual PE/PYZ does not implement the sealed compatibility policy')
    return dict(runtime_python_files_verified=42, runtime_source_sha256=hashes,
                packaged_policy_code_modules_verified=len(policy['current_code']), policy_code_equal=True)


def verify_program(archive, destination, role, shared, production, freeze):
    from scripts.windows_doctor_build import verify_content_manifest
    inventory = validate_zip(archive)
    require({n.split('/')[0] for n in inventory['files']} == {PACKAGE}, 'Package root differs')
    extract_original(archive, destination, inventory)
    program = destination / PACKAGE
    verify_content_manifest(program)
    release = read(program / 'RELEASE.json')
    require(release['packaging_version'] == release['release_version'] == VERSION and
            release['app_version'] == release['software_version'] == APP and release['source_commit'] == COMPILE_COMMIT and
            release['production_source_identity'] == production and release['build_python'].split()[0] == '3.12.10' and
            release['ci_run_url'] == f'https://github.com/{REPO}/actions/runs/{PRODUCER}', 'Compiled release provenance differs')
    require(not any(release.get(n, False) for n in ('verification_fixture_only', 'ui_repack_only', 'binary_reused_without_rebuild')),
            'Original delivery was a reused/relabelled fixture')
    require(sorted(release['resolved_build_dependency_freeze']) == freeze, 'Package build dependencies differ from producer log')
    require(read(program / '_internal/shared-source-build.json') == shared, 'Packaged common source differs')
    assets = [n for n, row in shared['files'].items() if row['component'] == 'ui']
    require(len(assets) >= 81, 'Complete UI assets missing')
    for name in assets:
        require((program / '_internal' / name).read_bytes() == (ROOT / name).read_bytes(), 'Packaged UI differs: ' + name)
    require(digest(program / '_internal/performance-compatibility.json') == POLICY_SHA and
            (program / '_internal/performance-compatibility.json').read_bytes() == (ROOT / 'performance-compatibility.json').read_bytes(),
            'Packaged compatibility policy bytes differ')
    sources = [n for n in inventory['files'] if n.startswith(PACKAGE + '/Sources/')]
    require(bool(sources) == (role == 'full') and release['source_id'] == ('P01' if role == 'p01' else 'M01'),
            'Unexpected source inclusion/profile')
    if role == 'p01':
        require(release['source_data_bundled'] is False and release['source_registration_required'] is True,
                'P01 must remain source-free')
    else:
        require(release['wholly_synthetic'] is True and release['patient_inputs_read'] is False, 'Unexpected clinical input')
    exe = program / 'CardioInsightDoctorEval.exe'
    with exe.open('rb') as stream:
        header = stream.read(64)
        require(header[:2] == b'MZ', 'Original EXE lacks MZ')
        stream.seek(int.from_bytes(header[60:64], 'little'))
        require(stream.read(6) == b'PE\0\0\x64\x86', 'Original EXE is not AMD64 PE')
    require(digest(exe) == PE_SHA, 'Original freshly compiled21 PE differs')
    return program, dict(release=release, exe_sha256=PE_SHA, original_archive_sha256=inventory['sha256'],
                         original_archive_bytes=inventory['bytes'], contents_verified=True,
                         policy_sha256=POLICY_SHA, UI_assets_verified=len(assets))


def make_fixture(original, output):
    from scripts.windows_doctor_build import create_content_manifest, verify_content_manifest, archive_and_extract
    fixture = output / 'internal22-only' / PACKAGE
    shutil.copytree(original, fixture)
    before = read(original / 'CONTENTS.json')['files']
    release = read(fixture / 'RELEASE.json')
    release.update(packaging_version='1.0.22', release_version='1.0.22', verification_fixture_only=True,
                   verification_scope='same frozen algorithm and schema; packaging version upgrade only')
    (fixture / 'RELEASE.json').write_text(json.dumps(release, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (fixture / '版本说明.txt').write_text('仅CI验收夹具：同一冻结算法和数据库结构，包装版本升级验证；不是第二正式发布。\n', encoding='utf-8-sig')
    create_content_manifest(fixture, with_source=False)
    verify_content_manifest(fixture)
    after = read(fixture / 'CONTENTS.json')['files']
    require(set(before) == set(after) and {n for n in before if before[n] != after[n]} == {'RELEASE.json', '版本说明.txt'},
            'Internal updater fixture changed software/runtime payload')
    archive, checksum, unpacked = archive_and_extract(fixture, output, PACKAGE + '-1.0.22-upgrade-fixture.zip',
                                                    with_source=False, verify_subdir='verify-internal22-only')
    require(digest(unpacked / 'CardioInsightDoctorEval.exe') == PE_SHA, 'Internal fixture changed original PE')
    return archive, dict(sha256=checksum, user_deliverable=False, application_release=False,
                         only_changed_payloads=['RELEASE.json', '版本说明.txt'], original_PE_and_other_payloads_identical=True)


def api(endpoint):
    result = subprocess.run(['gh', 'api', '--hostname', 'github.com', '/repos/' + REPO + endpoint],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=900)
    require(result.returncode == 0, 'Authenticated GitHub read failed: ' + endpoint)
    return result.stdout


def archived_original_logs(output, evidence):
    """Use the exact earlier authenticated raw ZIP after official consolidation.

    The earlier step9 truly verified these original bytes. No log lines are
    reconstructed from the combined presentation or assigned its timestamps.
    """
    run_id, head = 43301246400, '503f37fbe75d814d6546c54c7c838e1068abda16'
    raw = {n: api(p) for n, p in [('run', f'/actions/runs/{run_id}'),
        ('jobs', f'/actions/runs/{run_id}/attempts/1/jobs?per_page=100'),
        ('artifacts', f'/actions/runs/{run_id}/artifacts?per_page=100')]}
    for name, value in raw.items(): (evidence/('archived-log-origin-'+name+'.json')).write_bytes(value)
    run, jobs, artifacts = (loads(raw[n]) for n in ('run', 'jobs', 'artifacts'))
    require((run['id'], run['head_sha'], run['path'], run['status'], run['conclusion'], run['run_attempt']) ==
            (run_id, head, CONTINUATION, 'completed', 'failure', 1) and
            run['repository']['full_name'] == run['head_repository']['full_name'] == REPO, 'Archived log run differs')
    require(jobs['total_count'] == len(jobs['jobs']) == 1, 'Archived log job is ambiguous')
    job = jobs['jobs'][0]
    require((job['id'], job['run_id'], job['head_sha'], job['run_attempt']) ==
            (131472709504, run_id, head, 1), 'Archived log job identity differs')
    steps = {s['number']: s for s in job['steps']}
    require(len(steps) == len(job['steps']) and all(steps[n]['conclusion'] == 'success' for n in range(1, 10)) and
            steps[9]['name'] == 'Bind exact original21 compiled ZIPs and passed producer prerequisites',
            'Archived original bytes were not actually verified by earlier step9')
    rows = artifacts['artifacts']
    require(artifacts['total_count'] == len(rows) == 1, 'Archived log artifact is ambiguous')
    row = rows[0]
    checksum = '32139bb895393aa3277871c054d8999c3491cf1af7a90e3bb2ecb98e79831a60'
    require((row['id'], row['name'], row['size_in_bytes'], row['digest'], row['expired']) ==
            (13984056455, 'Windows-doctor-eval-mathematical-validation-1.0.21', 6813244, 'sha256:'+checksum, False) and
            row['workflow_run']['id'] == run_id and row['workflow_run']['head_sha'] == head, 'Archived log artifact differs')
    archive = output/'archived-log-proof.artifact.zip'
    with archive.open('xb') as stream:
        result = subprocess.run(['gh', 'api', '--hostname', 'github.com',
            f'/repos/{REPO}/actions/artifacts/13984056455/zip'], stdout=stream,
            stderr=subprocess.PIPE, timeout=900, check=False)
    require(result.returncode == 0, 'Archived log artifact download failed')
    inventory = validate_zip(archive, checksum, 6813244)
    destination = output/'archived-log-proof'
    extract_original(archive, destination, inventory)
    old = destination/'PERF21-producer/evidence'
    original = old/'original-producer-run-logs.zip'
    require(original.stat().st_size == 78187 and digest(original) ==
            'c280039daeadbb621baa64de2d73e43c2a6266538eb4ce8f47700a57943fb2ce' and
            digest(old/'original-failed15.log') == FAILED15_SHA, 'Archived exact original raw log bytes differ')
    return original, dict(run_id=run_id, head_sha=head, verified_step=9, artifact_id=row['id'],
                          artifact_sha256=checksum, original_raw_log_zip_sha256=digest(original))


def prepare(output, validator_commit, validator_run_id):
    require(sys.version_info[:3] == (3, 12, 10), 'Use pinned Python3.12.10 to inspect original PYZ')
    output = Path(output).resolve()
    require(not output.exists(), 'Keep original attempts; output exists')
    output.mkdir(parents=True)
    evidence = output / 'evidence'
    evidence.mkdir()
    meta = {n: api(path) for n, path in [('run', f'/actions/runs/{PRODUCER}'),
            ('jobs', f'/actions/runs/{PRODUCER}/attempts/1/jobs?per_page=100'),
            ('artifacts', f'/actions/runs/{PRODUCER}/artifacts?per_page=100')]}
    for name, value in meta.items(): (evidence / ('producer-' + name + '.json')).write_bytes(value)
    producer = validate_producer(*(loads(meta[n]) for n in ('run', 'jobs', 'artifacts')))
    current_raw = api(f'/actions/runs/{validator_run_id}')
    (evidence / 'validator-run-at-preparation.json').write_bytes(current_raw)
    validator = validate_acceptance(loads(current_raw), validator_commit, validator_run_id)
    from scripts.verify_public_release import verify
    from scripts.shared_source import snapshot
    production, shared = verify(ROOT), snapshot(ROOT)[0]
    require(production['source_sha256'] == PRODUCTION_SHA and production['production_files_verified'] == 135 and
            shared['source_fingerprint'] == COMMON_SHA and len(shared['files']) == 127 and
            digest(ROOT / 'performance-compatibility.json') == POLICY_SHA, 'Frozen135/common127/policy differs')
    paths, outer, inner = {}, {}, {}
    for role, wanted in ARTIFACTS.items():
        archive = output / (role + '.artifact.zip')
        # Stream large original artifacts, never route their bytes to stdout.
        with archive.open('xb') as stream:
            result = subprocess.run(['gh', 'api', '--hostname', 'github.com',
                                     f'/repos/{REPO}/actions/artifacts/{wanted["id"]}/zip'],
                                    stdout=stream, stderr=subprocess.PIPE, timeout=900, check=False)
        require(result.returncode == 0, 'Original artifact download failed: ' + role)
        inventory = validate_zip(archive, wanted['sha256'], wanted['bytes'])
        destination = output / 'original-artifacts' / role
        extract_original(archive, destination, inventory)
        outer[role] = dict(id=wanted['id'], sha256=inventory['sha256'], bytes=inventory['bytes'])
        if role != 'qa':
            original = one(destination, wanted['inner'])
            require((digest(original), original.stat().st_size) == ORIGINAL_INNERS[role],
                    'Original exact inner ZIP identity differs: ' + role)
            require(original.with_name(original.name + '.sha256').read_text().split() == [digest(original), original.name],
                    'Original inner ZIP sidecar differs')
            paths[role] = str(original)
            inner[role] = dict(sha256=digest(original), bytes=original.stat().st_size)
    qa = output / 'original-artifacts/qa'
    scopes = validate_qa(qa)
    logs = evidence / 'original-producer-run-logs.zip'
    logs.write_bytes(api(f'/actions/runs/{PRODUCER}/logs'))
    with zipfile.ZipFile(logs) as current:
        per_step = JOB_NAME+'/15_'+STEP_NAMES[15]+'.txt'
        consolidated = per_step not in current.namelist()
        if consolidated:
            combined = '0_'+JOB_NAME+'.txt'
            require(set(current.namelist()) == {combined, JOB_NAME+'/system.txt'} and
                    hashlib.sha256(current.read(combined)).hexdigest() ==
                    '3626c6b506dd48d6d0cfb233e68bb44ac089f6ffeaff01f13dfb76a25515e0eb',
                    'Official producer log layout/content is not the known exact consolidation')
    if consolidated:
        current_path = evidence/'current-official-consolidated-logs.zip'
        logs.rename(current_path)
        original, origin = archived_original_logs(output, evidence)
        shutil.copyfile(original, logs)
    log_proof = validate_logs(logs, scopes['original_failed_browser'])
    if consolidated:
        log_proof['authenticated_archived_source'] = origin
        log_proof['official_consolidated_zip_sha256'] = digest(current_path)
    raw_failed = log_proof.pop('_original_failed15_bytes')
    (evidence / 'original-failed15.log').write_bytes(raw_failed)
    freeze = log_proof['resolved_build_dependencies']
    current_freeze = subprocess.check_output([sys.executable, '-m', 'pip', 'freeze', '--all'], text=True).splitlines()
    require(sorted(current_freeze) == freeze, 'Validator pinned dependencies differ from original compiler')
    programs, identities = {}, {}
    for role in ('p01', 'full', 'software'):
        programs[role], identities[role] = verify_program(Path(paths[role]), output / ('unpacked-' + role),
                                                        role, shared, production, freeze)
    require(len({v['exe_sha256'] for v in identities.values()}) == 1, 'Three original21 PE files differ')
    runtime = verify_runtime(programs['p01'] / 'CardioInsightDoctorEval.exe')
    require(inner['source']['sha256'] == M01_SHA, 'Delivered M01 is not the original unchanged source')
    from scripts.windows_doctor_build import SOURCE_FILES
    with zipfile.ZipFile(paths['source']) as z:
        inventory = validate_zip(paths['source'])
        require(set(inventory['files']) == {'M01/' + n for n in SOURCE_FILES}, 'Original M01 source set differs')
        payload = {n: hashlib.sha256(z.read('M01/' + n)).hexdigest() for n in SOURCE_FILES}
    require(len(payload) == 5 and payload == {n: digest(programs['full'] / 'Sources/M01' / n) for n in SOURCE_FILES},
            'Full package M01 payload changed')
    build = read(one(output / 'original-artifacts/full', 'build-report.json'))
    p01_build = read(one(output / 'original-artifacts/p01', 'p01-software-build-report.json'))
    require(p01_build['status'] == 'passed' and p01_build['sha256'] == inner['p01']['sha256'] and
            p01_build['bytes'] == inner['p01']['bytes'] and p01_build['exe_sha256'] == PE_SHA and
            p01_build['source_commit'] == build['source_commit'] == COMPILE_COMMIT and
            p01_build['production_source_identity'] == build['production_source_identity'] == production,
            'Original compile/template reports differ')
    require(all(v['release']['build_python'] == build['build_python'] for v in identities.values()),
            'Three package Python builds differ from original build report')
    require(build['archive_sha256'] == inner['full']['sha256'] and build['archive_size_bytes'] == inner['full']['bytes'] and
            build['software_archive_sha256'] == inner['software']['sha256'] and
            build['software_archive_size_bytes'] == inner['software']['bytes'], 'Original build reports changed package bytes')
    require(all(build[n] is True for n in ('final_zip_crc_and_content_hashes_verified',
            'final_unpacked_exe_self_check_passed', 'final_unpacked_exe_process_smoke_passed',
            'python_removed_from_runtime_path')), 'Producer native PE/ZIP smoke gates did not pass')
    fixture, fixture_proof = make_fixture(programs['software'], output)
    paths.update(full_root=str(programs['full']), math_root=str(programs['full'] / 'Sources/M01'),
                 p01_build_report=str(one(output / 'original-artifacts/p01', 'p01-software-build-report.json')),
                 build_report=str(one(output / 'original-artifacts/full', 'build-report.json')),
                 verification_upgrade_fixture=str(fixture), producer_qa_root=str(qa))
    require(all(digest(paths[n]) == inner[n]['sha256'] for n in inner), 'Original deliverables changed during fixture preparation')
    proof = dict(schema=1, status='original_compiler_gates_verified_new_native_pending', producer=producer,
                 validator=validator, source_compile_commit=COMPILE_COMMIT, expected_windows_build_commit=COMPILE_COMMIT,
                 production_source_identity=production, common_source_fingerprint=COMMON_SHA,
                 outer_artifacts=outer, inner_archives=inner, package_identities=identities,
                 compiled_runtime=runtime, original_source_payload_sha256=payload, original_QA=scopes,
                 original_failed15_log=log_proof, original_build_report=build,
                 original_p01_build_report=p01_build, internal_updater_fixture=fixture_proof,
                 original_deliverables_repacked=False, preparer_executed_EXE=False,
                 new_native_acceptance_claimed=False, patient_inputs_read=False,
                 prepared_utc=datetime.now(timezone.utc).isoformat())
    proof_path = evidence / 'continuation-prerequisites.json'
    dump(proof_path, proof)
    value = dict(schema=1, producer_run_id=PRODUCER, source_compile_commit=COMPILE_COMMIT,
                 expected_windows_build_commit=COMPILE_COMMIT, validator=validator,
                 producer_proof_sha256=digest(proof_path), paths={**paths, 'producer_proof': str(proof_path)})
    dump(output / 'continuation21-input.json', value)
    return value


def finalize(output, native_evidence):
    """Accept new native receipts only after all gates, preserving producer failure."""
    output, native_evidence = Path(output).resolve(), Path(native_evidence).resolve()
    inputs = read(output / 'continuation21-input.json')
    proof_path = Path(inputs['paths']['producer_proof'])
    require(digest(proof_path) == inputs['producer_proof_sha256'], 'Producer proof changed after preparation')
    proof = read(proof_path)
    require(inputs['source_compile_commit'] == proof['source_compile_commit'] == COMPILE_COMMIT and
            inputs['producer_run_id'] == proof['producer']['run_id'] == PRODUCER and
            proof['validator'] == inputs['validator'], 'Continuation provenance differs')
    for role, (checksum, size) in ORIGINAL_INNERS.items():
        original = Path(inputs['paths'][role])
        require((digest(original), original.stat().st_size) == (checksum, size), 'Original deliverable changed: ' + role)
    names = ('browser-validation.json', 'p01-native.json', 'comprehensive-native.json',
             'upgrade20-to21-native.json', 'original-M01-payload-parity.json')
    receipts = {name: read(native_evidence / name) for name in names}
    require(all(r['status'] == 'passed' for r in receipts.values()), 'A new native acceptance gate did not pass')
    browser = receipts['browser-validation.json']
    require(browser['performance']['repeats'] == 3 and len(browser['performance']['rounds']) == 3 and
            all(c['status'] == 'passed' for c in browser['checks']), 'M01 three native rounds incomplete')
    for prefix in ('native-24h-M01-actual-PDF-performance', 'native-24h-M01-actual-HRV-save-undo-performance'):
        checks = [c for c in browser['checks'] if c['name'].startswith(prefix)]
        require(len(checks) == 3 and all(c['status'] == 'passed' and c['evidence']['actual_duration_s'] == 86400 for c in checks) and
                {c['evidence']['repeat'] for c in checks} == {1, 2, 3}, 'Missing three actual operations: ' + prefix)
        for check in checks:
            item = check['evidence']
            if 'PDF' in prefix:
                require(item['report_status'] == 'draft' and item['bytes'] > 1000 and item['page_count'] > 0 and
                        re.fullmatch('[0-9a-f]{64}', item['sha256']) and item['native_integrity_header_matches'] is True and
                        item['report_version'] >= 1 and item['review_revision'] >= 0 and item['seconds'] > 0,
                        'Actual M01 draft PDF evidence is incomplete')
            else:
                require(item['status'] == 'passed' and item['actual_exclusion_saved_and_undone'] is True and
                        item['original_document_restored'] is True and
                        item['original_hrv_revision'] < item['saved_hrv_revision'] < item['restored_hrv_revision'] and
                        item['preview_seconds'] > 0 and item['saved_update_seconds'] > 0,
                        'Actual M01 persisted HRV save/undo evidence is incomplete')
    fresh, upgraded = receipts['comprehensive-native.json'], receipts['upgrade20-to21-native.json']
    require(fresh['mode'] == 'actual-fresh21-UI-saveflow' and upgraded['mode'] == 'actual-original20-to21' and
            all(r['native_frozen_runtime'] and r['source_hashes_unchanged'] and r['bundled_python_proved'] and
                not r['page_errors'] and not r['blocked_requests'] for r in (fresh, upgraded)), 'Fresh/old20 native scope differs')
    require(upgraded['API_upgrade']['status'] == upgraded['database_upgrade']['status'] == upgraded['formal_PDF']['status'] == 'passed' and
            upgraded['formal_PDF']['old_approved_report_exported_without_reapproval'] is True and
            upgraded['formal_PDF']['report_status'] == 'reviewed' and
            upgraded['pdf_operations'] == 1, 'Original reviewed signature/UUID/formal PDF continuity incomplete')
    require(receipts['original-M01-payload-parity.json']['delivered_source_archive_sha256'] == M01_SHA,
            'Old20/original21 source parity differs')
    result = dict(schema=1, status='passed', producer_run_id=PRODUCER, source_compile_commit=COMPILE_COMMIT,
                  validator=inputs['validator'], original_failed15_preserved=True,
                  producer_proof_sha256=digest(proof_path), original_deliverables_repacked=False,
                  production_source_sha256=PRODUCTION_SHA, common_source_fingerprint=COMMON_SHA,
                  original_exe_sha256=PE_SHA, actual_native_receipts={n: digest(native_evidence / n) for n in names},
                  completed_M01_core_rounds=3, actual_M01_draft_PDF_downloads=3,
                  actual_M01_HRV_save_undo_rounds=3, formal_PDF_evidence='original20-reviewed-report-after-actual21-upgrade',
                  formal_reviewed_PDF_without_reapproval=upgraded['formal_PDF'], patient_inputs_read=False,
                  clinical_validation=False, completed_utc=datetime.now(timezone.utc).isoformat())
    dump(native_evidence / 'continuation21-final-acceptance.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--validator-commit')
    parser.add_argument('--validator-run-id', type=int)
    parser.add_argument('--finalize-evidence', type=Path)
    args = parser.parse_args()
    if args.finalize_evidence:
        result = finalize(args.output, args.finalize_evidence)
    else:
        require(args.validator_commit is not None and args.validator_run_id is not None, 'Explicit validator identity required')
        result = prepare(args.output, args.validator_commit, args.validator_run_id)
    print('WINDOWS21_CONTINUATION_INPUT_JSON=' + json.dumps(result, ensure_ascii=False))
