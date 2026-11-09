#!/usr/bin/env python3
"""Bind original fresh17 packages and passed producer scopes to new native gates.

Producer 42643976501 compiled the frozen production source and passed steps
10--15. Step16 failed in an obsolete TESTONLY ST method-profile assertion.
This helper preserves that failure and reuses the original package ZIP bytes;
it neither starts an EXE nor claims that any native gate has now passed.

The independent internal 1.0.18 wrapper fixture is ONLY a same-core updater
test input. It is not an application release or a user deliverable.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import unicodedata
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
REPO = 'xiaozidian/ECG_Software'
PRODUCER = 42643976501
SOURCE_COMPILE_COMMIT = 'bdcdf2343a0fb2cecbb157b4a3fba54de6a13333'
PRODUCER_JOB = 129252134201
WORKFLOW = '.github/workflows/windows-af-multistrip.yml'
ACCEPTANCE_WORKFLOW = '.github/workflows/windows-af17-native-continuation.yml'
APP = '0.12.31-af-multistrip.20261109'
VERSION = '1.0.17'
PACKAGE = 'CardioInsight-DoctorEval-Windows-x64'
PRODUCTION_SHA = '93e95d395e1fbd7a10ca5e3239df1bbf11a133e80b496c36f98e78ef772ddb27'
COMMON_SHA = '570d7ef2717cae89e8729c3d58ca6fd433115be41b5df2c193044977d723e5e8'
M01_SHA = '3b09e147add5a794800bc0be400ec57c347077c47546cc67c5593b3bedd745d0'
OLD_EXE_SHA = 'f5283fc6a670e4d6dd9553797035458f31d0ea059ef81516f06fcc3ea9c24a73'
ORIGINAL_EXE_SHA = '9d24382691cfd9ccc7a537877d90fe9237468a1a4d6b0acbbd7f3b9ec3c3ce8f'
ORIGINAL_INNERS = {
    'p01': {'sha256': '789833bb742b1d50341aedb2e5a122007918272d2e41164321e4a66a4d49b31a', 'bytes': 38402149},
    'full': {'sha256': '61c4dae08e46e6c90465e7fbff99bf3b42c2ecd6301ad527be98cee40af81574', 'bytes': 202277981},
    'software': {'sha256': 'dd15488bff12176aef1f0a5b9f62a70091a9119ff9c4efddc4b1043eb84440a7', 'bytes': 38394701},
    'source': {'sha256': M01_SHA, 'bytes': 163882245},
}
ADAPTER_SHA = {'win_doctor_eval.py': '755cfef85ebe20851c7a04e6a95521865daf47472d72a57776b6f68e42c4fe6e',
               'ecg_core/doctor_source.py': '037a07a91510210207dc2fd6d0af0b2630593ed302daf3852151deb7c1c8801d'}
ARTIFACTS = {
    'p01': dict(name='CardioInsight-Windows-x64-1.0.17-P01-software-only', id=13689147752,
                sha256='b9658f6c8d1599a30bfe02fdc2d226d9a92b846ef55f25429c87456bcbd2f990', bytes=38403654,
                inner='CardioInsight-DoctorEval-Windows-x64-1.0.17-P01-software.zip'),
    'full': dict(name='CardioInsight-Windows-x64-1.0.17-M01-full', id=13689456907,
                 sha256='1c339b65913e872b13ca4d591bfa0aeef71ee2f3d1018f7d87dfe2644af59263', bytes=202282547,
                 inner='CardioInsight-DoctorEval-Windows-x64-1.0.17-full.zip'),
    'software': dict(name='CardioInsight-Windows-x64-1.0.17-software-update', id=13688783339,
                     sha256='18097dc376c3a94bda19535209673ad2b37cd9a4fa72e6811000c73ac3eb0c9c', bytes=38395269,
                     inner='CardioInsight-DoctorEval-Windows-x64-1.0.17-software.zip'),
    'source': dict(name='CardioInsight-Synthetic-M01-24h-v1-for-1.0.17', id=13688393617,
                   sha256='6d03438b53188df402139fd6d2ef231948378fc6512de0ea243c239975e63858', bytes=163882723,
                   inner='CardioInsight-Synthetic-M01-24h-v1.zip'),
    'qa': dict(name='Windows-doctor-eval-mathematical-validation-1.0.17', id=13689790600,
               sha256='8d172dcae62fe6b81c27d706dff3a034c16034e6d25f1d177854bb2df5a6b72e', bytes=381096),
}
STEP_NAMES = {
    10: 'New comprehensive raw-waveform, exact scalar, records and browser Demo oracles',
    11: 'Current workstation and Windows protection scope without PDF operations',
    12: 'Fresh complete Windows UI wrappers including hospital ST-T and retained report protections',
    13: 'Original-source Windows request latency and full-output equivalence',
    14: 'Native directory build, generated 24h source and final ZIP smoke',
    15: 'Create source-free P01 native software template',
    16: 'System Edge full software interaction and retained-source update validation',
}
HISTORICAL = {'test_candidate_thresholds_match_unchanged_frozen_development',
              'test_current_workstation_cannot_masquerade_as_frozen_development'}


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def _pairs(rows):
    result = {}
    for key, value in rows:
        require(key not in result, 'Duplicate JSON key: ' + key)
        result[key] = value
    return result


def loads(raw):
    return json.loads(raw.decode('utf-8-sig') if isinstance(raw, bytes) else raw,
                      object_pairs_hook=_pairs)


def read(path):
    return loads(Path(path).read_bytes())


def dump(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')


def one(root, name):
    found = [p for p in Path(root).rglob(name) if p.is_file()]
    require(len(found) == 1 and not found[0].is_symlink(), 'Expected one original ' + name)
    return found[0]


def _safe(name):
    require(name and '\\' not in name and '\x00' not in name and not name.startswith('/') and '//' not in name,
            'Unsafe ZIP path: ' + repr(name))
    parts = name.rstrip('/').split('/')
    reserved = {'con', 'prn', 'aux', 'nul', *('com' + str(i) for i in range(1, 10)),
                *('lpt' + str(i) for i in range(1, 10))}
    for part in parts:
        require(part not in ('', '.', '..') and ':' not in part and not part.endswith(('.', ' ')) and
                not any(ord(c) < 32 for c in part), 'Unsafe ZIP component: ' + repr(name))
        require(part.split('.', 1)[0].casefold() not in reserved, 'Reserved Windows ZIP path')
    return unicodedata.normalize('NFC', '/'.join(parts)).casefold()


def validate_zip(path, expected_sha=None, expected_bytes=None):
    """Read-only byte/CRC/path inspection, without running any package member."""
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'Missing regular ZIP')
    actual = digest(path)
    require(expected_sha is None or actual == expected_sha, 'Original ZIP SHA256 mismatch: ' + path.name)
    require(expected_bytes is None or path.stat().st_size == expected_bytes, 'Original ZIP size mismatch: ' + path.name)
    files, keys = {}, {}
    with zipfile.ZipFile(path) as archive:
        require(0 < len(archive.infolist()) <= 100000, 'Invalid ZIP entry count')
        require(sum(i.file_size for i in archive.infolist()) <= 16 * 1024**3, 'ZIP exceeds uncompressed limit')
        for info in archive.infolist():
            _safe(info.orig_filename)
            key = _safe(info.filename)
            require(key not in keys, 'Duplicate/colliding ZIP member: ' + info.filename)
            require(stat.S_IFMT(info.external_attr >> 16) in (0, stat.S_IFREG, stat.S_IFDIR) and not info.flag_bits & 1,
                    'Symlink, special or encrypted ZIP member')
            keys[key] = info.is_dir()
            if info.is_dir():
                require(info.file_size == 0, 'Nonempty ZIP directory')
                continue
            value, size = hashlib.sha256(), 0
            with archive.open(info) as source:
                for block in iter(lambda: source.read(1024 * 1024), b''):
                    value.update(block)
                    size += len(block)
            require(size == info.file_size, 'ZIP member size mismatch')
            files[info.filename] = {'sha256': value.hexdigest(), 'size_bytes': size}
        for key in keys:
            for index in range(1, len(key.split('/'))):
                require(keys.get('/'.join(key.split('/')[:index]), True), 'ZIP file shadows directory')
    return {'sha256': actual, 'bytes': path.stat().st_size, 'files': files,
            'crc_verified': True, 'safe_paths_verified': True}


def extract_original(path, destination, inventory):
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(path) as archive:
        for name, row in inventory['files'].items():
            target = destination.joinpath(*PurePosixPath(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as source, target.open('xb') as output:
                shutil.copyfileobj(source, output, 1024 * 1024)
            require(digest(target) == row['sha256'] and target.stat().st_size == row['size_bytes'],
                    'Extraction changed original bytes')
    require(digest(path) == inventory['sha256'], 'Original ZIP changed during extraction')


def validate_producer_metadata(run, jobs, artifacts):
    require(run['id'] == PRODUCER and run['head_sha'] == SOURCE_COMPILE_COMMIT and run['path'] == WORKFLOW and
            run['status'] == 'completed' and run['conclusion'] == 'failure' and run['run_attempt'] == 1 and
            run['repository']['full_name'] == run['head_repository']['full_name'] == REPO,
            'Fixed fresh17 producer identity/actual failure differs')
    require(jobs['total_count'] == len(jobs['jobs']) == 1, 'Unexpected producer job count')
    job = jobs['jobs'][0]
    require(job['id'] == PRODUCER_JOB and job['run_id'] == PRODUCER and job['head_sha'] == SOURCE_COMPILE_COMMIT and
            job['run_attempt'] == 1 and job['status'] == 'completed' and job['conclusion'] == 'failure',
            'Producer job identity differs')
    steps = {s['number']: s for s in job['steps']}
    require(len(steps) == len(job['steps']), 'Duplicate producer step number')
    require({n for n, s in steps.items() if s['conclusion'] == 'failure'} == {16}, 'Original sole failure is not step16')
    for number, name in STEP_NAMES.items():
        require(steps[number]['name'] == name and steps[number]['status'] == 'completed' and
                steps[number]['conclusion'] == ('failure' if number == 16 else 'success'),
                'Producer passed-step/failure attribution differs: ' + str(number))
    require(all(steps[n]['conclusion'] == 'success' for n in range(1, 16)), 'Producer setup/preconditions did not pass')
    require(all(steps[n]['conclusion'] == 'skipped' for n in range(17, 21)), 'Unexpected original native17--20 verdict')
    rows = artifacts['artifacts']
    require(artifacts['total_count'] == len(rows) == 5 and
            {r['name'] for r in rows} == {r['name'] for r in ARTIFACTS.values()}, 'Expected five original producer artifacts')
    for role, expected in ARTIFACTS.items():
        matching = [r for r in rows if r['name'] == expected['name']]
        require(len(matching) == 1, 'Ambiguous original artifact: ' + role)
        row = matching[0]
        require(row['id'] == expected['id'] and row['digest'] == 'sha256:' + expected['sha256'] and
                row['size_in_bytes'] == expected['bytes'] and row['expired'] is False and
                row['workflow_run']['id'] == PRODUCER and row['workflow_run']['head_sha'] == SOURCE_COMPILE_COMMIT,
                'Fixed original artifact identity/digest/size differs: ' + role)
    return {'run_id': PRODUCER, 'head_sha': SOURCE_COMPILE_COMMIT, 'conclusion': 'failure',
            'passed_steps10_to15': [steps[n] for n in range(10, 16)], 'original_failed_step16': steps[16],
            'native_steps17_to20_originally_skipped': [steps[n] for n in range(17, 21)]}


def validate_acceptance(run, commit, run_id):
    require(run['id'] == run_id != PRODUCER and run['head_sha'] == commit != SOURCE_COMPILE_COMMIT and
            run['path'] == ACCEPTANCE_WORKFLOW and run['repository']['full_name'] == REPO and
            run['head_repository']['full_name'] == REPO and run['status'] == 'in_progress' and
            run['conclusion'] is None, 'Current native acceptance run/head/workflow differs')
    return {'commit': commit, 'run_id': run_id, 'workflow': ACCEPTANCE_WORKFLOW,
            'native_gates_status': 'pending', 'source_compile_commit': SOURCE_COMPILE_COMMIT,
            'producer_run_id': PRODUCER}


def junit(path):
    raw = Path(path).read_bytes()
    require(b'<!DOCTYPE' not in raw.upper() and b'<!ENTITY' not in raw.upper(), 'Unsafe JUnit declarations')
    root = ET.fromstring(raw)
    cases = list(root.iter('testcase'))
    counts = dict(total=len(cases), passed=0, failed=0, error=0, skipped=0)
    for case in cases:
        states = [n for n in ('failure', 'error', 'skipped') if case.find(n) is not None]
        require(len(states) <= 1, 'Ambiguous JUnit testcase status')
        counts[{'failure': 'failed', 'error': 'error', 'skipped': 'skipped'}.get(states[0] if states else '', 'passed')] += 1
    return counts, cases


def validate_qa(original):
    expected = {'doctor17-new-tests.xml': dict(total=106, passed=106, failed=0, error=0, skipped=0),
                'scoped-tests.xml': dict(total=885, passed=884, failed=0, error=0, skipped=1),
                'ui-regressions-tests.xml': dict(total=833, passed=833, failed=0, error=0, skipped=0)}
    scopes = {}
    for name, wanted in expected.items():
        path = one(original, name)
        counts, cases = junit(path)
        require(counts == wanted, 'Original passed scope differs: ' + name)
        scopes[name] = {'counts': counts, 'original_sha256': digest(path), 'rerun_in_continuation': False}
        if name == 'scoped-tests.xml':
            skipped = [c for c in cases if c.find('skipped') is not None]
            require(skipped[0].get('name') == 'test_native_xattr_does_not_interrupt_unchanged_build' and
                    skipped[0].find('skipped').get('message') == 'Native macOS xattr reproduction', 'Unexpected normal skip')
            for module, total in (('test_windows_source_identity', 6), ('test_windows_request_source_lease', 10)):
                protected = [c for c in cases if c.get('classname') == 'tests.' + module]
                require(len(protected) == total and all(not any(c.find(k) is not None for k in ('failure', 'error', 'skipped'))
                                                       for c in protected), 'Actual Windows OS protection scope was weakened')
    core, ui = read(one(original, 'test-summary.json')), read(one(original, 'ui-test-summary.json'))
    require(core['status'] == ui['status'] == 'passed' and core['current'] == expected['scoped-tests.xml'] and
            ui['current'] == expected['ui-regressions-tests.xml'], 'Original summary/JUnit disagreement')
    require(ui['declared_test_functions'] == 289 and ui['file_count'] == 115, 'Original UI selection size changed')
    hcounts, hcases = junit(one(original, 'historical-af.xml'))
    require(hcounts == dict(total=2, passed=0, failed=2, error=0, skipped=0) and
            {c.get('name') for c in hcases} == HISTORICAL and core['full_suite_green'] is False and
            core['unexplained_af_failures'] == [] and len(core['historical_af']) == 2 and
            {r['name'] for r in core['historical_af']} == HISTORICAL and
            all(r['status'] == 'missing_historical_material' for r in core['historical_af']), 'Historical AF attribution changed')
    for case in hcases:
        failure = case.find('failure')
        text = (failure.text or '') + ' ' + failure.get('message', '')
        require('FileNotFoundError' in text and 'summary.json' in text, 'Historical material absence was relabelled')
    perf = read(one(original, 'windows-request-source-perf.json'))
    require(perf['status'] == 'passed' and perf['failures'] == [] and perf['environment']['system'] == 'Windows' and
            perf['environment']['python'] == '3.12.10' and perf['scope']['existing_patient_sources_read'] is False and
            perf['scope']['diagnostic_algorithms_modified'] is False and perf['temporary_source_and_workspace_removed'] is True,
            'Original native performance verdict/scope differs')
    require(perf['summary']['fallback']['requests'] == perf['summary']['request_lease']['requests'] == 3,
            'Original performance measured rounds differ')
    require(perf['thresholds'] == {'each_optimized_request_seconds_strictly_below': 1.0,
                                  'optimized_data_hash_calls': 1, 'optimized_data_bytes_read': 276480000,
                                  'measured_requests_per_mode': 3}, 'Original performance thresholds differ')
    requests = perf['requests']
    require(len(requests) == 10 and sum(r['phase'] == 'measured' for r in requests) == 6, 'Original performance requests differ')
    for request in requests:
        require(request['all_diagnostic_fields_equal'] is True and request['raw_leads_equal_independent_samples'] is True and
                request['source_handles_released_after_teardown'] is True, 'Original performance equivalence/lease proof failed')
        require(all(e['content_matches'] is True and e['bytes_read'] == 276480000 for e in request['hash']['events']),
                'Original full-source hash proof failed')
        if request['request_source_leases']:
            require(request['wall_seconds'] < 1.0 and request['hash']['data_calls'] == 1 and
                    request['hash']['data_bytes_read'] == 276480000, 'Original performance threshold was weakened')
        else:
            require(request['hash']['data_calls'] > 1, 'Original fallback hash control was weakened')
    require(len({r['diagnostic_sha256'] for r in requests}) == 1 and
            len({r['analysis_basis'] for r in requests}) == 1, 'Original performance full-output/basis mismatch')
    prior = read(one(original, 'browser-validation.json'))
    require(prior['status'] == 'failed' and [r['status'] for r in prior['checks']] == ['passed'] * 3 + ['failed'] and
            prior['checks'][-1]['name'] == 'browser-verification-completion' and
            prior['checks'][-1]['evidence']['error'] == 'AssertionError: Native ST method profile changed',
            'Original TESTONLY browser failure differs')
    require(prior['network']['page_errors'] == prior['network']['http_errors'] == prior['network']['resource_failures'] == [] and
            prior['network']['external_requests'] == 0, 'Original browser failure contains unexplained network/page errors')
    return {'junit_scopes': scopes, 'historical_af': core['historical_af'], 'historical_af_counts': hcounts,
            'historical_missing_material_in_new17_passes': False, 'counts_are_distinct_scopes_not_unique_total': True,
            'core_summary': core, 'ui_summary': ui, 'performance': perf,
            'original_failed_browser16': prior, 'original_failed_browser16_sha256': digest(one(original, 'browser-validation.json'))}


def verify_program(path, destination, role, shared, production):
    from scripts.windows_doctor_build import verify_content_manifest
    inventory = validate_zip(path)
    extract_original(path, destination, inventory)
    require({n.split('/')[0] for n in inventory['files']} == {PACKAGE}, 'Unexpected original package root')
    program = destination / PACKAGE
    verify_content_manifest(program)
    release = read(program / 'RELEASE.json')
    require(release['packaging_version'] == release['release_version'] == VERSION and
            release['app_version'] == release['software_version'] == APP and
            release['source_commit'] == SOURCE_COMPILE_COMMIT and release['production_source_identity'] == production and
            release['ci_run_url'] == f'https://github.com/{REPO}/actions/runs/{PRODUCER}', 'Original compiled package provenance differs')
    require(not release.get('ui_repack_only') and not release.get('binary_reused_without_rebuild'), 'Fresh17 PE was not freshly built')
    require(read(program / '_internal/shared-source-build.json') == shared, 'Original packaged shared source stamp differs')
    assets = [n for n, row in shared['files'].items() if row['component'] == 'ui']
    require(len(assets) == 81, 'Expected all 81 frozen UI assets')
    for name in assets:
        require((program / '_internal' / name).read_bytes() == (ROOT / name).read_bytes(), 'Original packaged UI asset differs: ' + name)
    sources = [n for n in inventory['files'] if n.startswith(PACKAGE + '/Sources/')]
    require(release['source_id'] == ('P01' if role == 'p01' else 'M01') and bool(sources) == (role == 'full'), 'Original source inclusion differs')
    if role == 'p01':
        require(release['source_data_bundled'] is False and release['source_registration_required'] is True, 'P01 not source free')
    else:
        require(release['wholly_synthetic'] is True and release['patient_inputs_read'] is False, 'M01 source kind changed')
    exe = program / 'CardioInsightDoctorEval.exe'
    with exe.open('rb') as stream:
        header = stream.read(64)
        require(header[:2] == b'MZ', 'Original executable lacks MZ header')
        stream.seek(int.from_bytes(header[60:64], 'little'))
        require(stream.read(6) == b'PE\0\0\x64\x86', 'Original executable is not AMD64 PE')
    require(digest(exe) == ORIGINAL_EXE_SHA != OLD_EXE_SHA, 'Original fresh17 PE identity differs or reuses immutable15')
    return program, {'release': release, 'exe_sha256': digest(exe), 'amd64_PE_verified': True,
                     'UI_assets_verified': 81, 'original_inner_sha256': inventory['sha256'],
                     'original_inner_bytes': inventory['bytes']}


def make_wrapper_fixture(original, output):
    """Only the internal updater fixture is assembled; original ZIPs stay intact."""
    from scripts.windows_doctor_build import create_content_manifest, archive_and_extract, verify_content_manifest
    fixture = output / 'internal18-wrapper' / PACKAGE
    shutil.copytree(original, fixture)
    before = read(original / 'CONTENTS.json')['files']
    release = read(fixture / 'RELEASE.json')
    release.update(packaging_version='1.0.18', release_version='1.0.18', verification_fixture_only=True,
                   verification_scope='same frozen algorithm and schema; packaging version upgrade only')
    (fixture / 'RELEASE.json').write_text(json.dumps(release, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (fixture / '版本说明.txt').write_text('仅CI验收夹具：同一冻结算法和数据库结构，包装版本升级验证；不是第二正式发布。\n', encoding='utf-8-sig')
    create_content_manifest(fixture, with_source=False)
    verify_content_manifest(fixture)
    after = read(fixture / 'CONTENTS.json')['files']
    require(set(before) == set(after) and {n for n in before if before[n] != after[n]} == {'RELEASE.json', '版本说明.txt'},
            'Internal18 fixture changed frozen payload or PE')
    archive, checksum, unpacked = archive_and_extract(fixture, output, PACKAGE + '-1.0.18-upgrade-fixture.zip',
                                                    with_source=False, verify_subdir='verify-internal18-fixture')
    require(digest(unpacked / 'CardioInsightDoctorEval.exe') == digest(original / 'CardioInsightDoctorEval.exe'), 'Internal18 PE differs')
    return archive, {'path': str(archive), 'sha256': checksum, 'bytes': archive.stat().st_size,
                     'user_deliverable': False, 'application_release': False, 'packaging_version': '1.0.18',
                     'source_compile_commit': SOURCE_COMPILE_COMMIT,
                     'allowed_changed_payloads': ['RELEASE.json', '版本说明.txt'],
                     'all_other_payload_and_PE_identical': True, 'same_frozen_algorithm_and_schema': True}


def _gh(arguments):
    result = subprocess.run(['gh', *arguments], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600, check=False)
    require(result.returncode == 0, 'GitHub read failed: ' + ' '.join(arguments[:3]))
    return result.stdout


def _api(path):
    return _gh(['api', '--hostname', 'github.com', '/repos/' + REPO + path])


def prepare(output, acceptance_commit, acceptance_run_id):
    require(re.fullmatch(r'[0-9a-f]{40}', acceptance_commit or '') and acceptance_commit != SOURCE_COMPILE_COMMIT and
            type(acceptance_run_id) is int and acceptance_run_id > 0 and acceptance_run_id != PRODUCER,
            'Acceptance commit/run must be explicit and separate from original source compile provenance')
    output = Path(output).expanduser().resolve()
    require(not output.exists(), 'Preserve original continuation attempts; output already exists')
    output.mkdir(parents=True, exist_ok=False)
    evidence = output / 'evidence'
    evidence.mkdir()
    raw = {'run': _api(f'/actions/runs/{PRODUCER}'),
           'jobs': _api(f'/actions/runs/{PRODUCER}/attempts/1/jobs?per_page=100'),
           'artifacts': _api(f'/actions/runs/{PRODUCER}/artifacts?per_page=100')}
    for name, value in raw.items():
        (evidence / ('producer-' + name + '.json')).write_bytes(value)
    producer = validate_producer_metadata(*(loads(raw[k]) for k in ('run', 'jobs', 'artifacts')))
    acceptance_raw = _api(f'/actions/runs/{acceptance_run_id}')
    (evidence / 'acceptance-run-at-preparation.json').write_bytes(acceptance_raw)
    acceptance = validate_acceptance(loads(acceptance_raw), acceptance_commit, acceptance_run_id)
    log = _gh(['run', 'view', str(PRODUCER), '--repo', REPO, '--log-failed'])
    require(log and b'Native ST method profile changed' in log and STEP_NAMES[16].encode() in log,
            'Missing original failed16 raw log')
    log_path = evidence / 'producer-failed-step16-original.log'
    log_path.write_bytes(log)
    producer['original_failed16_log'] = {'path': str(log_path), 'sha256': digest(log_path),
                                        'bytes': len(log), 'origin': 'gh run view --log-failed; exact stdout bytes'}
    from scripts.verify_public_release import verify
    from scripts.shared_source import snapshot
    production = verify(ROOT)
    shared, _ = snapshot(ROOT)
    require(production['source_sha256'] == PRODUCTION_SHA and production['production_files_verified'] == 130 and
            shared['source_fingerprint'] == COMMON_SHA and len(shared['files']) == 123, 'Current frozen production/common source changed')
    require(all(digest(ROOT / n) == checksum for n, checksum in ADAPTER_SHA.items()), 'Retained Windows adapter source changed')
    originals = output / 'original-artifacts'
    originals.mkdir()
    paths, outer, inner = {}, {}, {}
    for role, expected in ARTIFACTS.items():
        archive = originals / (role + '.artifact.zip')
        with archive.open('xb') as stream:
            result = subprocess.run(['gh', 'api', '--hostname', 'github.com',
                                     f'/repos/{REPO}/actions/artifacts/{expected["id"]}/zip'],
                                    stdout=stream, stderr=subprocess.PIPE, timeout=900, check=False)
        require(result.returncode == 0, 'Original artifact download failed: ' + role)
        inventory = validate_zip(archive, expected['sha256'], expected['bytes'])
        extracted = output / 'extracted' / role
        extract_original(archive, extracted, inventory)
        outer[role] = {**expected, 'original_outer_path': str(archive), 'extracted': str(extracted),
                       'original_member_sha256': inventory['files'], 'GitHub_digest_size_CRC_verified': True}
        if role != 'qa':
            path = one(extracted, expected['inner'])
            checksum = digest(path)
            require(path.with_name(path.name + '.sha256').read_text(encoding='utf-8-sig').split() == [checksum, path.name],
                    'Original inner sidecar differs: ' + role)
            inventory = validate_zip(path, ORIGINAL_INNERS[role]['sha256'], ORIGINAL_INNERS[role]['bytes'])
            paths[role] = str(path)
            inner[role] = {'path': str(path), 'sha256': checksum, 'bytes': path.stat().st_size,
                           'sidecar': str(path.with_name(path.name + '.sha256')), 'original_bytes_not_repacked': True,
                           'files': inventory['files']}
    original_qa = evidence / 'producer-original-QA'
    shutil.copytree(output / 'extracted/qa', original_qa)
    require({p.relative_to(original_qa).as_posix(): digest(p) for p in original_qa.rglob('*') if p.is_file()} ==
            {p.relative_to(output / 'extracted/qa').as_posix(): digest(p) for p in (output / 'extracted/qa').rglob('*') if p.is_file()},
            'Copying original producer QA changed bytes')
    scopes = validate_qa(original_qa)
    programs, identities = {}, {}
    for role in ('p01', 'full', 'software'):
        programs[role], identities[role] = verify_program(Path(paths[role]), output / ('unpacked-' + role), role, shared, production)
    require(len({p['exe_sha256'] for p in identities.values()}) == 1, 'Three original17 PE bytes differ')
    from scripts.windows_doctor_build import SOURCE_FILES
    with zipfile.ZipFile(paths['source']) as archive:
        require(set(inner['source']['files']) == {'M01/' + n for n in SOURCE_FILES}, 'Original source ZIP file set differs')
        payload = {n: hashlib.sha256(archive.read('M01/' + n)).hexdigest() for n in SOURCE_FILES}
    require(payload == {n: digest(programs['full'] / 'Sources/M01' / n) for n in SOURCE_FILES} and len(payload) == 5,
            'Original full17 M01 payload differs from unchanged original15 M01 ZIP')
    p01_build = read(one(output / 'extracted/p01', 'p01-software-build-report.json'))
    build = read(one(output / 'extracted/full', 'build-report.json'))
    require(p01_build['status'] == 'passed' and p01_build['sha256'] == inner['p01']['sha256'] and
            p01_build['bytes'] == inner['p01']['bytes'] and p01_build['exe_sha256'] == identities['p01']['exe_sha256'] and
            p01_build['source_commit'] == build['source_commit'] == SOURCE_COMPILE_COMMIT and
            p01_build['production_source_identity'] == build['production_source_identity'] == production, 'Original build reports differ')
    require(build['archive_sha256'] == inner['full']['sha256'] and build['archive_size_bytes'] == inner['full']['bytes'] and
            build['software_archive_sha256'] == inner['software']['sha256'] and build['software_archive_size_bytes'] == inner['software']['bytes'],
            'Original full/software byte proof differs')
    require(all(build[k] is True for k in ('final_zip_crc_and_content_hashes_verified', 'final_unpacked_exe_self_check_passed',
                                          'final_unpacked_exe_process_smoke_passed', 'python_removed_from_runtime_path')),
            'Original fresh native build/smoke prerequisites did not pass')
    require(sys.version_info[:2] == (3, 12), 'Inspect original Python3.12 PYZ with Python3.12; no foreign-version marshal fallback')
    from scripts.verify_windows_stt_independent_upgrade import embedded_modules
    runtime = embedded_modules(programs['p01'] / 'CardioInsightDoctorEval.exe', ROOT)
    require(runtime['runtime_python_files_verified'] == 40 and runtime['includes_new_ST_record_module'] is True,
            'Actual original PE/PYZ did not match all40 current frozen runtime source files')
    fixture, fixture_proof = make_wrapper_fixture(programs['software'], output)
    paths.update(full_root=str(programs['full']), p01_root=str(programs['p01']), software_root=str(programs['software']),
                 math_root=str(programs['full'] / 'Sources/M01'), original_qa=str(original_qa), evidence=str(evidence),
                 producer_qa_root=str(original_qa), p01_build_report=str(one(output / 'extracted/p01', 'p01-software-build-report.json')),
                 build_report=str(one(output / 'extracted/full', 'build-report.json')),
                 verification_upgrade_fixture=str(fixture))
    for role in inner:
        require(digest(paths[role]) == inner[role]['sha256'], 'Original package ZIP changed while preparing internal fixture')
    proof = {'schema_version': 1, 'status': 'producer_bound_originals_verified_native_continuation_pending',
             'source_compile_commit': SOURCE_COMPILE_COMMIT, 'producer': producer, 'acceptance': acceptance,
             'production_source_identity': production, 'shared_source_fingerprint': COMMON_SHA,
             'outer_artifacts': outer, 'inner_archives': inner, 'package_identities': identities,
             'compiled_runtime': runtime, 'source_payload_sha256': payload, 'scopes': scopes,
             'verification_upgrade_fixture': fixture_proof, 'original_package_build_reports': {'p01': p01_build, 'full': build},
             'paths': paths, 'original_ZIPs_repacked': False, 'actual_EXE_executed_by_preparer': False,
             'new_native_gates_claimed_passed': False, 'clinical_validation': False, 'patient_inputs_read': False,
             'physical_hospital_Windows10_verified': False, 'prepared_at_utc': datetime.now(timezone.utc).isoformat()}
    proof_path = evidence / 'continuation-prerequisites.json'
    dump(proof_path, proof)
    paths['producer_proof'] = str(proof_path)
    result = {'schema_version': 1, 'source_compile_commit': SOURCE_COMPILE_COMMIT,
              'producer_run_id': PRODUCER, 'acceptance': acceptance, 'paths': paths,
              'producer_proof_sha256': digest(proof_path), 'verification_upgrade_fixture_user_deliverable': False}
    dump(output / 'continuation17-input.json', result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--acceptance-commit', required=True)
    parser.add_argument('--acceptance-run-id', type=int, required=True)
    args = parser.parse_args(argv)
    result = prepare(args.output, args.acceptance_commit, args.acceptance_run_id)
    print('WINDOWS17_CONTINUATION_INPUT_JSON=' + json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
