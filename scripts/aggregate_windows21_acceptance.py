"""Compose separately executed native stages; no application runs in this job.

M01/P01 are reused only from their fixed actual successful stages in a failed
run. Fresh21 and original20-to21 must each be actual successful independent
runs. Exact original compiler proof, source parity and the existing final gate
remain mandatory before the original four ZIPs may be delivered.
"""
from pathlib import Path
import argparse
import json
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import prepare_windows21_continuation as c

STAGES = {
    'M01_P01': dict(run=43301246400, head='503f37fbe75d814d6546c54c7c838e1068abda16',
        branch='codex/windows-performance-preserve-20261113', conclusion='failure',
        artifact='Windows-doctor-eval-mathematical-validation-1.0.21', id=13984056455,
        sha256='32139bb895393aa3277871c054d8999c3491cf1af7a90e3bb2ecb98e79831a60', bytes=6813244),
    'fresh21': dict(run=43306728498, head='2d64601b3a8b95b52b2a1117aa51235cabddd581',
        branch='codex/windows21-priority-fresh-20261113', conclusion='success',
        artifact='Windows21-priority-fresh21-only', id=13983398889, bytes=3621178,
        sha256='81e4a9eb7fb8671b7d306ceec06c612c5ddf8baf1fba3939854d691bc4418e7b',
        business='Actual fresh21 ST-T AF incremental saving and report card operations'),
    'original20_to21': dict(run=43306519725, head='d8fd8b647b2f070387d7a93d1d26fc37e05f435f',
        branch='codex/windows21-priority-upgrade-20261113', conclusion='success',
        artifact='Windows21-priority-original20-upgrade-only', id=13984710901, bytes=2846049,
        sha256='71fd0d6248a95c0ad1cc99e47d67f1e8bffc8e8a1267360b5ed4d4f6a87c828b',
        business='Actual original20 to original21 same-workspace reviewed signature UUID and formal PDF retention'),
}
M01_RECEIPT = 'e50d3c422795b0ac164e739c28fd3260f9fb04efcdc7f5a785680fef0ca1d2ab'
P01_RECEIPT = '8e58cbf3b607f126a92b665259aa30dc4a99e4ac464ea71ea091621409f9fe84'
FAILED_FRESH_RECEIPT = '808c2d5f452702e4d0a87049280fb3deb73efdc97cf3076594b8c059633b3566'
ORIGINAL_PREPARATION = 'b771f789fcd1f5ed57cd6cc6d2beeffd596f1562da7801c4debfeed903a92fb1'


def validate_stage(role, run, jobs, artifacts):
    wanted = STAGES[role]
    c.require((run['id'], run['head_sha'], run['head_branch'], run['status'], run['conclusion'], run['run_attempt'], run['path']) ==
              (wanted['run'], wanted['head'], wanted['branch'], 'completed', wanted['conclusion'], 1, c.CONTINUATION) and
              run['repository']['full_name'] == run['head_repository']['full_name'] == c.REPO,
              'Native stage run/head/verdict differs: ' + role)
    c.require(jobs['total_count'] == len(jobs['jobs']) == 1, 'Native stage job count differs')
    job = jobs['jobs'][0]
    c.require((job['run_id'], job['head_sha'], job['run_attempt'], job['status'], job['conclusion']) ==
              (wanted['run'], wanted['head'], 1, 'completed', wanted['conclusion']), 'Native stage job identity differs')
    steps = {s['number']: s for s in job['steps']}
    c.require(len(steps) == len(job['steps']), 'Duplicate native stage step number')
    if role == 'M01_P01':
        c.require(job['id'] == 131472709504 and {n for n, s in steps.items() if s['conclusion'] == 'failure'} == {14},
                  'Original fresh14 failure was changed')
        c.require(all(steps[n]['status'] == 'completed' and steps[n]['conclusion'] == 'success' for n in range(1, 14)) and
                  steps[12]['name'] == 'Complete original21 M01 three native rounds plus actual draft PDF and HRV operations' and
                  steps[13]['name'] == 'Actual original21 P01 source save reopen and packaging update' and
                  all(steps[n]['conclusion'] == 'skipped' for n in range(15, 22)) and steps[22]['conclusion'] == 'success',
                  'Actual M01/P01 pass scope or later skipped scope differs')
    else:
        c.require(all(s['conclusion'] in ('success', 'skipped') for s in steps.values()) and
                  all(steps[n]['status'] == 'completed' and steps[n]['conclusion'] == 'success' for n in range(1, 13)),
                  'A new priority native prerequisite/business gate did not pass')
        c.require(steps[9]['name'] == 'Bind exact original21 compiled ZIPs and passed producer prerequisites' and
                  steps[11]['name'] == wanted['business'], 'Priority native command scope differs')
    rows = artifacts['artifacts']
    c.require(artifacts['total_count'] == len(rows) == 1 and rows[0]['name'] == wanted['artifact'],
              'Single exact native QA artifact required: ' + role)
    row = rows[0]
    c.require(row['expired'] is False and row['workflow_run']['id'] == wanted['run'] and
              row['workflow_run']['head_sha'] == wanted['head'] and row['size_in_bytes'] > 0 and
              row['digest'].startswith('sha256:') and len(row['digest']) == 71, 'QA artifact provenance differs')
    c.require((row['id'], row['digest'], row['size_in_bytes']) ==
              (wanted['id'], 'sha256:'+wanted['sha256'], wanted['bytes']), 'Fixed passed-stage artifact differs')
    return row


def download_stage(role, output):
    wanted = STAGES[role]
    output.mkdir(parents=True, exist_ok=False)
    raw = {name: c.api(endpoint) for name, endpoint in [('run', f'/actions/runs/{wanted["run"]}'),
        ('jobs', f'/actions/runs/{wanted["run"]}/attempts/1/jobs?per_page=100'),
        ('artifacts', f'/actions/runs/{wanted["run"]}/artifacts?per_page=100')]}
    for name, data in raw.items(): (output/(name+'.json')).write_bytes(data)
    row = validate_stage(role, *(c.loads(raw[n]) for n in ('run', 'jobs', 'artifacts')))
    archive = output/'original-QA.artifact.zip'
    with archive.open('xb') as stream:
        result = subprocess.run(['gh', 'api', '--hostname', 'github.com',
            f'/repos/{c.REPO}/actions/artifacts/{row["id"]}/zip'], stdout=stream,
            stderr=subprocess.PIPE, timeout=900, check=False)
    c.require(result.returncode == 0, 'Native QA download failed')
    inventory = c.validate_zip(archive, row['digest'][7:], row['size_in_bytes'])
    qa = output/'original-QA'
    c.extract_original(archive, qa, inventory)
    return qa, dict(run_id=wanted['run'], head_sha=wanted['head'], conclusion=wanted['conclusion'],
                    artifact_id=row['id'], artifact_sha256=inventory['sha256'], artifact_bytes=inventory['bytes'],
                    reused_without_rerun=role == 'M01_P01')


def stage_proof(qa):
    path = qa/'PERF21-producer/evidence/continuation-prerequisites.json'
    proof = c.read(path)
    c.require(proof['source_compile_commit'] == c.COMPILE_COMMIT and proof['producer']['run_id'] == c.PRODUCER and
              proof['production_source_identity']['source_sha256'] == c.PRODUCTION_SHA and
              proof['production_source_identity']['production_files_verified'] == 135 and
              proof['common_source_fingerprint'] == c.COMMON_SHA and
              proof['compiled_runtime']['runtime_python_files_verified'] == 42 and
              proof['compiled_runtime']['policy_code_equal'] is True and proof['original_deliverables_repacked'] is False,
              'Native stage did not bind the same compiler/135/127/42 runtime')
    for role, (checksum, size) in c.ORIGINAL_INNERS.items():
        c.require(proof['inner_archives'][role] == dict(sha256=checksum, bytes=size), 'Stage original ZIP identity differs')
    c.require(all(p['exe_sha256'] == c.PE_SHA and p['policy_sha256'] == c.POLICY_SHA for p in proof['package_identities'].values()),
              'Native stage PE/policy differs')
    c.require(proof['original_QA']['junit']['doctor21-performance-tests.xml']['passed'] == 418 and
              proof['original_QA']['junit']['doctor21-backup-acl-smoke.xml']['passed'] == 1,
              'Stage did not retain actual418/ACL proof')
    return path, proof


def aggregate(producer_input, output):
    output = Path(output).resolve()
    c.require(not output.exists(), 'Preserve earlier aggregation attempts')
    output.mkdir(parents=True)
    inputs = c.read(producer_input)
    producer_root = Path(producer_input).resolve().parent
    c.require(c.digest(inputs['paths']['producer_proof']) == inputs['producer_proof_sha256'], 'Current original producer proof changed')
    producer = c.read(inputs['paths']['producer_proof'])
    c.require(inputs['source_compile_commit'] == c.COMPILE_COMMIT and inputs['producer_run_id'] == c.PRODUCER,
              'Aggregator original compiler identity differs')
    accepted = output/'accepted-qa'
    accepted.mkdir()
    lineage = dict(producer_compile=dict(run_id=c.PRODUCER, head_sha=c.COMPILE_COMMIT))
    for role in STAGES:
        qa, identity = download_stage(role, output/'reused-runs'/role)
        original_proof_path, original_proof = stage_proof(qa)
        c.require(original_proof['compiled_runtime'] == producer['compiled_runtime'] and
                  original_proof['original_failed15_log']['resolved_build_dependencies'] == producer['original_failed15_log']['resolved_build_dependencies'],
                  'Stage actual runtime/compiled dependency identity differs')
        native = qa/'doctor-native/evidence'
        if role == 'M01_P01':
            c.require(c.digest(original_proof_path) == ORIGINAL_PREPARATION and
                      c.digest(native/'browser-validation.json') == M01_RECEIPT and
                      c.digest(native/'p01-native.json') == P01_RECEIPT and
                      c.digest(native/'comprehensive-native.json') == FAILED_FRESH_RECEIPT,
                      'Original passed stages or failed fresh receipt changed')
            c.require(c.read(native/'browser-validation.json')['status'] == c.read(native/'p01-native.json')['status'] == 'passed' and
                      c.read(native/'comprehensive-native.json')['status'] == 'failed', 'Original native verdict was relabelled')
            names = ['browser-validation.json', 'p01-native.json']
        else:
            names = ['comprehensive-native.json' if role == 'fresh21' else 'upgrade20-to21-native.json']
            result = c.read(native/names[0])
            c.require(result['status'] == 'passed' and result['native_frozen_runtime'] is True,
                      'New native controller did not actually pass')
            package = result['package_identity']
            c.require(package['source_compile_commit'] == c.COMPILE_COMMIT and
                      package['acceptance_controller_commit'] == STAGES[role]['head'] and
                      package['new_exe_sha256'] == c.PE_SHA and
                      package['production_source_identity'] == producer['production_source_identity'] and
                      package['common_source_fingerprint'] == c.COMMON_SHA,
                      'Native receipt compiler/controller/source identity differs')
        for name in names:
            shutil.copyfile(native/name, accepted/name)
            c.require(c.digest(native/name) == c.digest(accepted/name), 'Copying native receipt changed bytes')
        lineage[role] = identity
    # Compute parity again from the actual original full package and the actual
    # original M01 ZIP; its SHA is the accepted20/21 unchanged M01 SHA, not a label.
    source_zip = Path(inputs['paths']['source'])
    c.require(c.digest(source_zip) == c.M01_SHA, 'Original mathematical input changed')
    source = output/'original-M01'
    c.extract_original(source_zip, source, c.validate_zip(source_zip))
    from scripts.prepare_windows21_baseline import parity
    baseline = output/'parity-current-paths.json'
    c.dump(baseline, dict(paths=dict(math_source=str(source/'M01'), math=str(source_zip))))
    parity(argparse.Namespace(baseline_proof=baseline, package_root=Path(inputs['paths']['full_root']),
                              output=accepted/'original-M01-payload-parity.json'))
    final = c.finalize(producer_root, accepted)
    aggregator = final.pop('validator')
    lineage['aggregation'] = aggregator
    final.update(aggregator=aggregator, lineage=lineage,
                 acceptance_scope='composed_from_exact_independently_executed_native_stages',
                 native_stages_reused_without_rerun=['M01_three_rounds_actual_draft_PDF_HRV', 'P01_source_save_reopen_update'],
                 native_stages_executed_independently=['fresh21_complete_doctor_flow', 'actual_original20_to21_reviewed_signature_UUID_formal_PDF'],
                 original_failed_fresh14_preserved=dict(run_id=STAGES['M01_P01']['run'],
                                                       receipt_sha256=FAILED_FRESH_RECEIPT, status='failed'))
    path = accepted/'continuation21-final-acceptance.json'
    path.write_text(json.dumps(final, ensure_ascii=False, sort_keys=True, indent=2)+'\n', encoding='utf-8', newline='\n')
    return final


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--producer-input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print('WINDOWS21_AGGREGATE_JSON='+json.dumps(aggregate(args.producer_input, args.output), ensure_ascii=False))
