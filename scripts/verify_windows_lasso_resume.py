"""Resume native acceptance only when the complete tested source tree is unchanged.

This one-release receipt is deliberately pinned. It cannot reuse regression for a
production, dependency, test, build, or release-manifest change.
"""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import shutil
import subprocess
import zipfile

REPOSITORY = 'xiaozidian/ECG_Software'
RUN = 38710973555
COMMIT = 'f86d81f38ea62ef40dd6e0ab3809f7eb1098b34d'
ARTIFACT = 11962854727
DIGEST = '4ae31f5f53c18f619fa52e776d05e9395db3026a7c2704fdbc4c8e7507c0f826'
ALLOWED = {
    'scripts/verify_lasso_browser.py',
    'scripts/verify_windows_lasso_resume.py',
    '.github/workflows/windows-lasso-acceptance.yml',
}
NATIVE = 'Native directory build, generated 24h source and final ZIP smoke'
BROWSER = 'System Edge full software interaction and retained-source update validation'


def api(path):
    return json.loads(subprocess.check_output(['gh', 'api', f'repos/{REPOSITORY}/{path}']))


def verify(output):
    subprocess.run(['git', 'merge-base', '--is-ancestor', COMMIT, 'HEAD'], check=True)
    changed = set(subprocess.check_output(['git', 'diff', '--name-only', COMMIT, 'HEAD'], text=True).splitlines())
    assert changed and changed <= ALLOWED, f'Regression reuse forbidden for changed source: {sorted(changed - ALLOWED)}'
    assert not subprocess.check_output(['git', 'diff', '--name-only'], text=True).strip(), 'Dirty checkout is not verifiable'
    assert not subprocess.check_output(['git', 'diff', '--cached', '--name-only'], text=True).strip()
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    run = api(f'actions/runs/{RUN}')
    assert run['head_sha'] == COMMIT and run['status'] == 'completed' and run['conclusion'] == 'failure'
    assert run['path'] == '.github/workflows/windows-doctor-eval.yml'
    jobs = api(f'actions/runs/{RUN}/jobs')['jobs']
    assert len(jobs) == 1
    steps = jobs[0]['steps']
    native_index = next(i for i, s in enumerate(steps) if s['name'] == NATIVE)
    assert all(s['conclusion'] == 'success' for s in steps[:native_index+1]), 'A prior prerequisite failed'
    assert [s['name'] for s in steps if s['conclusion'] == 'failure'] == [BROWSER]
    artifact = api(f'actions/artifacts/{ARTIFACT}')
    assert artifact['workflow_run']['id'] == RUN
    assert artifact['name'] == 'Windows-doctor-eval-public-validation-1.0.2'
    assert not artifact['expired'] and artifact['digest'] == 'sha256:' + DIGEST
    output.mkdir(parents=True, exist_ok=True)
    archive = output / 'pinned-regression-evidence.zip'
    with archive.open('wb') as stream:
        subprocess.run(['gh', 'api', f'repos/{REPOSITORY}/actions/artifacts/{ARTIFACT}/zip'], stdout=stream, check=True)
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == DIGEST
    extracted = output / 'prior-run'
    with zipfile.ZipFile(archive) as package:
        assert package.testzip() is None
        names = set()
        for info in package.infolist():
            name = PurePosixPath(info.filename.replace('\\', '/'))
            assert not name.is_absolute() and '..' not in name.parts and not any(':' in part for part in name.parts)
            assert (info.external_attr >> 16) & 0o170000 != 0o120000
            assert name.as_posix() not in names
            names.add(name.as_posix())
        package.extractall(extracted)
    regression = json.loads((extracted / 'doctor-regression/regression-comparison.json').read_text())
    candidate = json.loads((extracted / 'doctor-regression/candidate-scopes.json').read_text())
    expected = {'total': 2149, 'passed': 2146, 'failed': 2, 'error': 0, 'skipped': 1}
    assert regression['comparison_passed'] is True and regression['full_suite_green'] is False
    assert not regression['regressions'] and not regression['missing_baseline_tests']
    assert regression['current'] == candidate['combined'] == expected
    assert candidate['day'] == {'total': 4, 'passed': 4, 'failed': 0, 'error': 0, 'skipped': 0}
    assert candidate['source_hashes_verified_before_and_after'] is True
    assert candidate['day_assertions_modified'] is False
    for directory in ['doctor-regression', 'doctor-core']:
        shutil.copytree(extracted / directory, output / directory, dirs_exist_ok=True)
    for xml in extracted.glob('doctor-*.xml'):
        shutil.copy2(xml, output / xml.name)
    shutil.copy2(extracted / 'doctor-eval/evidence/browser-validation.json', output / 'doctor-regression/prior-browser-failure.json')
    receipt = {
        'status': 'passed', 'kind': 'unchanged-source-regression-reuse-only',
        'prior_run': RUN, 'prior_commit': COMMIT, 'current_commit': head,
        'prior_run_conclusion': 'failure', 'prior_failed_step': BROWSER,
        'prior_verified_steps': [s['name'] for s in steps[:native_index+1]],
        'changed_paths': sorted(changed), 'all_other_tracked_files_byte_identical': True,
        'evidence_artifact_id': ARTIFACT, 'evidence_sha256': DIGEST,
        'candidate': expected, 'full_suite_green': False,
        'native_build_and_entire_browser_suite_must_run_again': True,
        'clinical_acceptance': False,
    }
    (output / 'doctor-regression/resume-attestation.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    verify(parser.parse_args().output)
