"""Read the exact accepted17 P01 and unchanged mathematical M01 for a new18 run.

Old acceptance is provenance for an input, never a new18 test result. This file
does not launch an EXE, edit an old ZIP, read a patient, or publish an artifact.
"""
from pathlib import Path, PurePosixPath
import argparse
import json
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.windows_doctor_build import digest, validate_source
from scripts.prepare_ui15_baseline import api, download, dump, one, read

REPO = 'xiaozidian/ECG_Software'
RUN = 42676241250
HEAD = 'd1b2babb42b9d2af83d581dc6367748749ff9767'
P01 = '789833bb742b1d50341aedb2e5a122007918272d2e41164321e4a66a4d49b31a'
MATH = '3b09e147add5a794800bc0be400ec57c347077c47546cc67c5593b3bedd745d0'
ARTIFACTS = {
    'p01': dict(id=13700966623, name='CardioInsight-Windows-x64-1.0.17-P01-software-only',
                sha256='de551a56225158d1f29cc1df38326d15f32b74e3852666f10b5d6344a3adac33', bytes=38403654,
                inner='CardioInsight-DoctorEval-Windows-x64-1.0.17-P01-software.zip', inner_sha256=P01),
    'math': dict(id=13699898612, name='CardioInsight-Synthetic-M01-24h-v1-for-1.0.17',
                 sha256='cc014aeec50adbdb92740b05b58884aac9c94118a04021b2dfed1bb7e1c779aa', bytes=163882723,
                 inner='CardioInsight-Synthetic-M01-24h-v1.zip', inner_sha256=MATH),
}


def extract_math(archive, destination):
    assert not destination.exists(), 'Keep earlier source proof'
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        assert len(names) == 5 and len(set(names)) == len(names) and z.testzip() is None
        for info in z.infolist():
            # ZipInfo normalizes the host separator on Windows. Inspect the
            # original archive name as well so a raw backslash or NUL is never
            # silently accepted as a different, apparently safe member name.
            raw_name = info.orig_filename
            assert raw_name and raw_name == info.filename and '\\' not in raw_name
            name = PurePosixPath(raw_name)
            assert not info.is_dir() and name.parts[0] == 'M01'
            assert not name.is_absolute() and '..' not in name.parts
            assert not any(':' in part for part in name.parts)
            assert (info.external_attr >> 16) & 0o170000 != 0o120000
        z.extractall(destination)
    validate_source(destination / 'M01')
    return destination / 'M01'


def prepare(args):
    assert not args.output.exists(), 'Preserve original attempts'
    run = api(REPO, f'/actions/runs/{RUN}')
    assert (run['status'], run['conclusion'], run['head_sha']) == ('completed', 'success', HEAD)
    rows = api(REPO, f'/actions/runs/{RUN}/artifacts')['artifacts']
    args.output.mkdir(parents=True)
    paths, outer = {}, {}
    for role, wanted in ARTIFACTS.items():
        row = next(r for r in rows if r['id'] == wanted['id'])
        assert not row['expired'] and row['name'] == wanted['name']
        assert row['size_in_bytes'] == wanted['bytes'] and row['digest'] == 'sha256:' + wanted['sha256']
        assert row['workflow_run']['id'] == RUN and row['workflow_run']['head_sha'] == HEAD
        outer[role] = download(REPO, wanted, args.output / role)
        path = one(args.output / role, wanted['inner'])
        assert digest(path) == wanted['inner_sha256']
        assert path.with_name(path.name + '.sha256').read_text().split() == [wanted['inner_sha256'], path.name]
        paths[role] = str(path)
    paths['math_source'] = str(extract_math(Path(paths['math']), args.output / 'original-source'))
    value = dict(status='accepted17-original-inputs-verified-only', base_packaging_version='1.0.17',
                 intended_new_packaging_version='1.0.18', original_acceptance_run=RUN, original_acceptance_head=HEAD,
                 outer_artifacts=outer, paths=paths, P01_SHA256=P01, M01_archive_SHA256=MATH,
                 patient_inputs_read=False, new18_native_tests_executed=False)
    dump(args.output / 'baseline18-input.json', value)
    print(json.dumps(value))


def parity(args):
    baseline = read(args.baseline_proof)
    source, package = Path(baseline['paths']['math_source']), args.package_root / 'Sources/M01'
    files = lambda root: {p.relative_to(root).as_posix(): digest(p) for p in root.rglob('*') if p.is_file()}
    left, right = files(source), files(package)
    assert left == right and len(left) == 5
    assert digest(Path(baseline['paths']['math'])) == MATH
    dump(args.output, dict(status='passed', full18_source_payload_exactly_original_M01=True,
                          source_payload_sha256=right, delivered_source_archive_sha256=MATH,
                          delivered_archive_is_original17_and15_bytes=True, clinical_validation=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline-proof', type=Path)
    parser.add_argument('--package-root', type=Path)
    options = parser.parse_args()
    if options.package_root:
        assert options.baseline_proof is not None
        parity(options)
    else:
        prepare(options)
