"""Resume acceptance after a browser-fixture repair with immutable regression evidence.

No production, dependency, test, build or source-manifest change can reuse this
receipt. All native build, performance and complete browser gates run again.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile

REPOSITORY = 'xiaozidian/ECG_Software'
RUN = 40503048920
COMMIT = 'bdf0a851d9512f6e4bcddf5162313423a75cdefe'
ARTIFACT = 12734996225
DIGEST = '595035113ddeadcf4d16d6285f983e9ebb3e799e9e97b4d25fa7df3b09ffd992'
ALLOWED = {
    'scripts/verify_windows_doctor_browser.py',
    'scripts/verify_windows_latest_resume.py',
    '.github/workflows/windows-latest-acceptance.yml',
}
NATIVE = 'Native directory build, generated 24h source and final ZIP smoke'
BROWSER = 'System Edge full software interaction and retained-source update validation'
EXPECTED = {'total': 603, 'passed': 602, 'failed': 0, 'error': 0, 'skipped': 1}
HISTORICAL = {
    'test_candidate_thresholds_match_unchanged_frozen_development',
    'test_current_workstation_cannot_masquerade_as_frozen_development',
}

def api(path):
    return json.loads(subprocess.check_output(['gh', 'api', f'repos/{REPOSITORY}/{path}']))

def verify(output):
    subprocess.run(['git', 'merge-base', '--is-ancestor', COMMIT, 'HEAD'], check=True)
    changed = set(subprocess.check_output(['git', 'diff', '--name-only', COMMIT, 'HEAD'], text=True).splitlines())
    assert changed and changed <= ALLOWED, f'Regression reuse forbidden: {sorted(changed - ALLOWED)}'
    assert not subprocess.check_output(['git', 'status', '--porcelain'], text=True).strip(), 'Dirty checkout is not verifiable'
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    run = api(f'actions/runs/{RUN}')
    assert run['head_sha'] == COMMIT and run['status'] == 'completed' and run['conclusion'] == 'failure'
    assert run['path'] == '.github/workflows/windows-doctor-latest.yml'
    jobs = api(f'actions/runs/{RUN}/jobs')['jobs']
    assert len(jobs) == 1
    steps = jobs[0]['steps']
    native_index = next(i for i, step in enumerate(steps) if step['name'] == NATIVE)
    assert all(step['conclusion'] == 'success' for step in steps[:native_index+1])
    assert [step['name'] for step in steps if step['conclusion'] == 'failure'] == [BROWSER]
    artifact = api(f'actions/artifacts/{ARTIFACT}')
    assert artifact['workflow_run']['id'] == RUN and artifact['workflow_run']['head_sha'] == COMMIT
    assert artifact['name'] == 'Windows-doctor-eval-public-validation-1.0.3'
    assert not artifact['expired'] and artifact['digest'] == 'sha256:' + DIGEST
    output.mkdir(parents=True, exist_ok=True)
    archive = output / 'pinned-regression-evidence.zip'
    with archive.open('wb') as stream:
        subprocess.run(['gh', 'api', f'repos/{REPOSITORY}/actions/artifacts/{ARTIFACT}/zip'], stdout=stream, check=True)
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == DIGEST
    extracted = output / 'prior-run'
    with zipfile.ZipFile(archive) as package:
        assert package.testzip() is None
        assert sum(info.file_size for info in package.infolist()) < 20_000_000
        names = set()
        for info in package.infolist():
            name = PurePosixPath(info.filename.replace(chr(92), '/'))
            assert not name.is_absolute() and '..' not in name.parts and not any(':' in part for part in name.parts)
            assert (info.external_attr >> 16) & 0o170000 != 0o120000
            assert name.as_posix() not in names
            names.add(name.as_posix())
        package.extractall(extracted)
    core = extracted / 'doctor-core'
    summary = json.loads((core / 'test-summary.json').read_text())
    assert summary['status'] == 'passed' and summary['current'] == EXPECTED
    assert summary['full_suite_green'] is False and not summary['unexplained_af_failures']
    assert summary['pdf_open_export_download_run'] is False
    assert {item['name'] for item in summary['historical_af']} == HISTORICAL
    assert all(item['status'] == 'missing_historical_material' for item in summary['historical_af'])
    nodes = list(ET.parse(core / 'scoped-tests.xml').getroot().iter('testcase'))
    counts = {'total':len(nodes),
        'passed':sum(not any(n.find(k) is not None for k in ['failure','error','skipped']) for n in nodes),
        'failed':sum(n.find('failure') is not None for n in nodes),
        'error':sum(n.find('error') is not None for n in nodes),
        'skipped':sum(n.find('skipped') is not None for n in nodes)}
    assert counts == EXPECTED
    historical = list(ET.parse(core / 'historical-af.xml').getroot().iter('testcase'))
    assert len(historical) == 2 and {n.get('name') for n in historical} == HISTORICAL
    for node in historical:
        failure = node.find('failure')
        assert failure is not None
        text = (failure.text or '') + failure.get('message', '')
        assert 'FileNotFoundError' in text and 'summary.json' in text
    scope = json.loads((core / 'test-scope.json').read_text())
    assert scope['pdf_operations_permitted'] is False and scope['full_repository_suite_run'] is False
    assert len(scope['selected']) == EXPECTED['total']
    perf = json.loads((core / 'windows-request-source-perf.json').read_text())
    assert perf['status'] == 'passed' and not perf['failures']
    browser = json.loads((extracted / 'doctor-eval/evidence/browser-validation.json').read_text())
    assert browser['status'] == 'failed' and browser['scope']['pdf_open_export_download_run'] is False
    failures = [item for item in browser['checks'] if item['status'] == 'failed']
    assert len(failures) == 1 and failures[0]['name'] == 'browser-verification-completion'
    assert 'Locator.scroll_into_view_if_needed' in failures[0]['evidence']['error']
    assert 'data-occ-index=' in failures[0]['evidence']['error']
    latest = next(item for item in browser['checks'] if item['name'] == 'latest-workstation-ui-and-report-curation')
    assert latest['status'] == 'passed' and len(latest['evidence']['checks']) == 18
    shutil.copytree(core, output / 'doctor-core', dirs_exist_ok=True)
    regression = output / 'doctor-regression'
    regression.mkdir(exist_ok=True)
    shutil.copy2(extracted / 'doctor-eval/evidence/browser-validation.json', regression / 'prior-browser-failure.json')
    receipt = {
        'status':'passed', 'kind':'unchanged-source-regression-reuse-only',
        'prior_run':RUN, 'prior_commit':COMMIT, 'current_commit':head,
        'prior_run_conclusion':'failure', 'prior_failed_step':BROWSER,
        'prior_verified_steps':[step['name'] for step in steps[:native_index+1]],
        'changed_paths':sorted(changed), 'all_other_tracked_files_byte_identical':True,
        'evidence_artifact_id':ARTIFACT, 'evidence_sha256':DIGEST,
        'current':EXPECTED, 'historical_af':summary['historical_af'], 'full_suite_green':False,
        'native_build_performance_and_entire_browser_suite_must_run_again':True,
        'clinical_acceptance':False, 'pdf_operations':0,
    }
    (regression / 'resume-attestation.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    verify(parser.parse_args().output)
