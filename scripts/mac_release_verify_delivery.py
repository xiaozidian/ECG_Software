#!/usr/bin/env python3
"""Read-only verification of the final software archive and local installation."""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import plistlib
import stat
import subprocess
import zipfile


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def main():
    root = Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence',type=Path,default=root.parent/'mac-package')
    parser.add_argument('--production-freeze',type=Path,default=root.parent/'integration'/'frozen-production.json')
    args=parser.parse_args()
    evidence = args.evidence.resolve()
    build = json.loads((evidence / 'BUILD.json').read_text())
    frozen = json.loads(args.production_freeze.read_text())
    assert build['release_id'] == frozen['identity']
    assert build['source_sha256'] == frozen['source_sha256']
    for name, expected in frozen['files'].items():
        current = root / name
        assert current.stat().st_size == expected['bytes'] and digest(current) == expected['sha256'], name
    archive = Path(build['distribution_archive'])
    assert digest(archive) == build['archive_sha256']
    release_id = build['release_id']
    # Apple's ditto writes UTF-8 names without setting the ZIP UTF-8 bit.
    # Its native extractor (used by the installation receipt) preserves them;
    # use that observed filename encoding for this independent content audit.
    with zipfile.ZipFile(archive, metadata_encoding='utf-8') as incoming:
        assert incoming.testzip() is None
        names = incoming.namelist()
        forbidden = []
        symlinks = []
        metadata = []
        ordinary_files = []
        for entry in incoming.infolist():
            item = PurePosixPath(entry.filename)
            assert not item.is_absolute() and '..' not in item.parts, entry.filename
            if item.parts[0] == '__MACOSX':
                metadata.append(entry.filename)
                continue
            assert item.parts[0] == release_id, entry.filename
            if entry.is_dir():
                continue
            if stat.S_ISLNK(entry.external_attr >> 16):
                link = incoming.read(entry).decode()
                target = PurePosixPath(link)
                assert not target.is_absolute(), (entry.filename, link)
                effective = list(item.parent.parts)
                for part in target.parts:
                    if part == '..':
                        assert len(effective) > 1, (entry.filename, link)
                        effective.pop()
                    elif part != '.':
                        effective.append(part)
                symlinks.append(dict(path=entry.filename, target=link))
                continue
            ordinary_files.append(entry.filename)
            if item.suffix.lower() in {'.data','.ebi','.lps','.db','.sqlite','.sqlite3','.pdf','.ecgbackup','.png','.jpg','.jpeg','.heic'} or any(part.lower() in {'demo','demo_static','data','screenshots','evidence'} for part in item.parts):
                forbidden.append(entry.filename)
            content = incoming.read(entry)
            assert not content.startswith(b'SQLite format 3\x00'), entry.filename
        assert not forbidden, forbidden
        checksums = incoming.read(release_id + '/SHA256SUMS.txt').decode().splitlines()
        for item in checksums:
            expected, name = item.split('  ', 1)
            assert sha256(incoming.read(release_id + '/' + name)).hexdigest() == expected, name
        instructions = incoming.read(release_id + '/INSTALL.md').decode()
        assert 'FileProvider' in instructions and '严格签名校验失败' in instructions and '未启用云端同步' in instructions
        assert '不能据此作为正式诊断放行' in instructions and '另一台 Mac' in instructions
    installed = Path(build['verified_local_install'])
    for item in checksums:
        expected, name = item.split('  ', 1)
        assert digest(installed / name) == expected, name
    app = installed / 'CardioInsightMacCandidate.app'
    signing = subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict','--verbose=2',str(app)], capture_output=True,text=True)
    (evidence / 'final-strict-signature.txt').write_text(signing.stdout + signing.stderr)
    assert signing.returncode == 0, signing.stderr
    with (app / 'Contents' / 'Info.plist').open('rb') as stream:
        info = plistlib.load(stream)
    assert info['LSMinimumSystemVersion'] == build['runtime_min_macos'] == '14.0'
    facts = json.loads((evidence / 'macho-inventory.json').read_text())
    assert len(facts['files']) == build['macho_count'] == 44
    assert all(value['architectures'] == ['arm64'] for value in facts['files'].values())
    assert not facts['absolute_non_system_entries']
    privacy_path=root.parent/'data-audit-finalization'/('final-'+build['source_sha256'][:16])/'FINAL-PRIVACY-RECEIPT.json'
    privacy=json.loads(privacy_path.read_text()) if privacy_path.is_file() else None
    if privacy:
        assert privacy['release_id']==build['release_id'] and privacy['zip_sha256']==build['archive_sha256']
        assert privacy['checks']['absolute_co_filename_objects']==0
        assert all(value==0 for value in privacy['checks']['local_private_information_findings'].values())
    portable = json.loads((evidence / 'portable-smoke' / 'portable.json').read_text())
    timing = json.loads((evidence / 'standard-launch-timing' / 'portable.json').read_text())
    chrome = json.loads((evidence / 'portable-smoke' / 'chrome' / 'browser.json').read_text())
    explicit_path=evidence/'portable-smoke'/'chrome-explicit-source'/'browser.json'
    explicit=json.loads(explicit_path.read_text()) if explicit_path.is_file() else None
    assert portable['passed'] and timing['passed'] and not chrome['errors']
    if explicit:
        assert not explicit['errors'] and explicit['source_kind']=='hospital_real' and explicit['fixture']=='mathematical-only'
        assert explicit['external_page_request_attempts']==0 and chrome['external_page_request_attempts']==0
    failed_names=['portable-smoke-seatbelt-control-failure','portable-smoke-missing-report-category-attempt',
                  'portable-smoke-missing-write-header-attempt','desktop-fileprovider-verify-failure.txt',
                  'ditto-sandbox-partial.zip','portable-smoke-tmp-private-path-test-attempt']
    failed_names=[name for name in failed_names if (evidence/name).exists()]
    for port in (8809,8810):
        listening = subprocess.run(['/usr/sbin/lsof','-nP',f'-iTCP:{port}','-sTCP:LISTEN'], capture_output=True,text=True)
        assert listening.returncode == 1 and not listening.stdout, listening.stdout
    result = dict(checked_at_utc=datetime.now(timezone.utc).isoformat(),passed=True,
                  release_id=release_id,source_sha256=build['source_sha256'],frozen_production_files_verified=len(frozen['files']),
                  archive=str(archive),archive_sha256=build['archive_sha256'],archive_bytes=archive.stat().st_size,
                  checksummed_package_files=len(checksums),zip_regular_file_count=len(ordinary_files),
                  zip_metadata_entries=metadata,zip_symlinks=symlinks,zip_crc_verified=True,
                  zip_filename_encoding='UTF-8 emitted by macOS ditto; native ditto extraction verified Chinese launcher names.',
                  forbidden_patient_database_export_image_paths=forbidden,sqlite_file_magic_matches=0,
                  bundled_cases=0,bundled_work_databases=0,bundled_mathematical_case_files=0,
                  synthetic_generator_explicit_initialization_only=True,
                  verified_local_install=str(installed),all_installed_file_hashes_match_archive=True,
                  strict_ad_hoc_signature_verified=True,architecture='arm64',macho_count=44,runtime_min_macos='14.0',
                  absolute_non_system_macho_dependencies=[],
                  independent_privacy_receipt=str(privacy_path) if privacy else None,
                  independent_privacy_code_objects=privacy['checks']['all_recursive_code_objects'] if privacy else None,
                  independent_privacy_absolute_co_filename_objects=privacy['checks']['absolute_co_filename_objects'] if privacy else None,
                  independent_privacy_local_findings=privacy['checks']['local_private_information_findings'] if privacy else None,
                  third_party_provenance_note='Generic vendor CI build paths, library examples and compatibility directory labels may remain; local user/project paths, actual source identities and work databases were checked separately.',
                  actual_test_host='macOS 26.6.2 arm64',actual_test_browser=chrome['browser'],
                  portable_function_checks=len(portable['checks']),chrome_checks=len(chrome['checks']),chrome_page_errors=0,
                  explicit_local_source_chrome_checks=len(explicit['checks']) if explicit else 0,
                  explicit_local_source_test_fixture='Mathematical source only; no hospital data used.' if explicit else 'Not covered by this earlier attempt.',
                  browser_external_page_request_policy=chrome.get('browser_request_policy','Not constrained in this earlier attempt.'),
                  browser_external_page_request_attempts=chrome.get('external_page_request_attempts'),
                  explicit_source_browser_external_page_request_attempts=explicit.get('external_page_request_attempts') if explicit else None,
                  migrated_chinese_space_path=portable['moved_package'],cwd='/',
                  dependency_policy_scope='Actual compiled analysis server, PDF, init, offline backup/verify/restore denied original source/venv and original build-Python root; ownership controls outside that policy because macOS setuid ps cannot exec inside Seatbelt.',
                  standard_startup_scope='Three sequential public start .command invocations in ordinary supported environment; invalid Python environment, system-only PATH, no original-root/venv/Python-root entries in server lsof.',
                  timing_qualification=timing['qualification'],timing_concurrency_note=timing['concurrent_work_note'],
                  first_http200_ms=timing['first_http200_ms'],first_api_case_list_readable_ms=timing['first_case_list_readable_ms'],
                  chrome_dashboard_note='Fresh Chrome context opened after service readiness; DOM visibility/reachability is functional evidence, not process-start timing.',
                  own_test_ports_without_listener=[8809,8810],root_8804_not_controlled=True,
                  saved_report_preserved_as_draft=portable['recovery']['saved_report_preserved_as_draft'],
                  saved_annotation_preserved=portable['recovery']['saved_annotation_preserved'],display_alias_preserved=portable['recovery']['display_alias_preserved'],
                  cancelled_initialization_test_scope='Source runtime unit tests; compiled native osascript cancellation was not automated.',
                  another_mac_tested=False,macos14_tested=False,intel_tested=False,
                  developer_id_signed=False,notarized=False,another_mac_gatekeeper_tested=False,
                  independent_device_mapping_verified=False,voltage_calibrated=False,physician_gold_standard=False,clinical_release=False,
                  preserved_failed_attempts=failed_names,
                  finalization=('PyInstaller build and strict-sign staging passed. Archive creation required an approved ditto invocation after sandbox EPERM; BUILD.json and stable local installation receipt finalized from the successful archive, without any production source change.' if (evidence/'ditto-sandbox-partial.zip').exists() else
                                'Frozen PyInstaller build, private-cache analysis, clean local staging, strict ad hoc signature, archive creation and exclusive new UserSupport installation completed through the approved supported commands. Production source unchanged.'))
    (evidence / 'FINAL-VERIFICATION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    public=dict(release_id=release_id,app_version=frozen['version'],archive_name=archive.name,
                archive_sha256=build['archive_sha256'],archive_bytes=archive.stat().st_size,
                source_sha256=build['source_sha256'],architecture='arm64',runtime_min_macos='14.0',
                actual_test_host='macOS26.6.2 arm64',actual_test_browser=chrome['browser'],
                signature='ad-hoc-integrity-only',developer_id_signed=False,notarized=False,
                another_mac_gatekeeper_tested=False,another_mac_tested=False,macos14_tested=False,intel_tested=False,
                bundled_patient_data=False,bundled_work_database=False,synthetic_case_files_bundled=False,
                independent_device_mapping_verified=False,voltage_calibrated=False,physician_gold_standard=False,clinical_release=False,
                portable_function_checks=len(portable['checks']),chrome_checks=len(chrome['checks']),
                explicit_local_source_chrome_checks=len(explicit['checks']) if explicit else 0,
                external_page_request_attempts=chrome.get('external_page_request_attempts'),
                browser_network_scope='Fresh contexts block non-loopback/data/blob/file page requests; no system network changes. App dependencies bundled; macOS Gatekeeper can perform its own online checks.',
                local_privacy_audit_matches=privacy['checks']['local_private_information_findings'] if privacy else None,
                privacy_code_objects=privacy['checks']['all_recursive_code_objects'] if privacy else None,
                privacy_absolute_co_filename_objects=privacy['checks']['absolute_co_filename_objects'] if privacy else None,
                third_party_provenance='Generic vendor CI paths, library examples and compatibility directory labels retained; this is not a claim that every path-like byte is absent.',
                first_http200_ms=timing['first_http200_ms'],first_api_case_list_readable_ms=timing['first_case_list_readable_ms'],
                startup_scope='Three sequential process starts via public .command; same machine and mathematical source. OS page cache not cleared. API readability is not browser interactivity. No speedup comparison.')
    (evidence/'DISTRIBUTION.json').write_text(json.dumps(public,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({key:result[key] for key in ('passed','release_id','archive_sha256','frozen_production_files_verified','checksummed_package_files','portable_function_checks','chrome_checks','own_test_ports_without_listener')},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
