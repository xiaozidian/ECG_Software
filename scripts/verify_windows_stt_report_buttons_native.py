"""Actual fresh18 PE ST-T controls, or exact original17 ->18 workspace upgrade.

This controller never relabels a packaging-only fixture as delivered18, never
patches an executable and never imports old clinical code into a new namespace.
Both application phases run real AMD64 PE files with bundled Python and Edge.
All generated inputs and publicly retained screenshots are mathematical only.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
APP = '0.12.32-stt-report-buttons.20261110'
VERSION = '1.0.18'
BASE_APP = '0.12.31-af-multistrip.20261109'
BASE_VERSION = '1.0.17'
BASE_CORE = 'core-94352009c80e551e'
BASE_P01_SHA = '789833bb742b1d50341aedb2e5a122007918272d2e41164321e4a66a4d49b31a'
BASE_PE_SHA = '9d24382691cfd9ccc7a537877d90fe9237468a1a4d6b0acbbd7f3b9ec3c3ce8f'
READONLY_POSTS = {'open', 'scatter-selection', 'waveform-strips', 'event-waveforms',
                  'waveform-density', 'advanced-analysis', 'rr-locate', 'stt-range'}


def require(value, message):
    if not value:
        raise AssertionError(message)


def fingerprint(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                            separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def exact(left, right, message):
    require(fingerprint(left) == fingerprint(right), message)


def files(root):
    return {p.relative_to(root).as_posix(): sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def metadata_identity(release, shared, *, old_release=None, old_shared=None,
                      new_PE_sha256, old_PE_sha256=None):
    require(release['packaging_version'] == VERSION, 'Expected a real delivered18, not an upgrade fixture')
    require(release['app_version'] == release['software_version'] == APP, 'Current application version differs')
    require(shared['core_version'] == BASE_CORE, 'The accepted clinical core must remain unchanged')
    require(release['source_id'] == 'P01' and release['source_data_bundled'] is False, 'Expected source-free P01 software')
    require(not any(release.get(k, False) for k in ('ui_repack_only', 'binary_reused_without_rebuild',
                                                   'verification_fixture_only')), 'A reused binary or internal upgrade fixture is not delivered18')
    if old_release is not None:
        require(old_release['packaging_version'] == BASE_VERSION and old_release['app_version'] == BASE_APP,
                'The baseline must be original delivered17')
        require(old_release['source_id'] == 'P01' and old_release['source_data_bundled'] is False,
                'Original17 baseline must be source-free P01')
        require(old_PE_sha256 == BASE_PE_SHA and old_PE_sha256 != new_PE_sha256,
                'Expected distinct original17 and fresh18 actual executables')
        require(old_shared['core_version'] == shared['core_version'], 'This UI repair must not change the clinical core')
        require(old_shared['ui_version'] != shared['ui_version'], 'The delivered18 UI was not updated')
    return dict(application_version=APP, packaging_version=VERSION, new_exe_sha256=new_PE_sha256,
                base_application_version=BASE_APP if old_release else None,
                base_packaging_version=BASE_VERSION if old_release else None,
                base_exe_sha256=old_PE_sha256, same_clinical_core=True,
                core_version=shared['core_version'], ui_version=shared['ui_version'])


def program_identity(new, old=None):
    from scripts.shared_source import snapshot
    from scripts.verify_public_release import verify
    read = lambda p: json.loads(p.read_text(encoding='utf-8-sig'))
    release, shared = read(new / 'RELEASE.json'), read(new / '_internal/shared-source-build.json')
    if os.environ.get('GITHUB_SHA'):
        require(release['source_commit'] == os.environ['GITHUB_SHA'], 'Package was not compiled from this actual CI commit')
    require(release['production_source_identity'] == verify(ROOT), 'Actual package differs from production130 manifest')
    require(shared == snapshot(ROOT)[0], 'Actual package shared stamp differs from frozen current source')
    assets = {name: row for name, row in shared['files'].items() if row['component'] == 'ui'}
    require(len(assets) == 81, 'Expected all current81 UI resources')
    for name, row in assets.items():
        require(sha256((new / '_internal' / name).read_bytes()).hexdigest() == row['sha256'],
                'Actual packaged UI bytes differ: ' + name)
    old_release = read(old / 'RELEASE.json') if old else None
    old_shared = read(old / '_internal/shared-source-build.json') if old else None
    proof = metadata_identity(release, shared, old_release=old_release, old_shared=old_shared,
                              new_PE_sha256=sha256((new / 'CardioInsightDoctorEval.exe').read_bytes()).hexdigest(),
                              old_PE_sha256=sha256((old / 'CardioInsightDoctorEval.exe').read_bytes()).hexdigest() if old else None)
    proof.update(source_compile_commit=release['source_commit'], production_source_identity=release['production_source_identity'],
                 common_source_fingerprint=shared['source_fingerprint'], actual_UI_files_verified=len(assets))
    return proof


def compare_api(before, after, package):
    from scripts.verify_windows_stt_independent_upgrade import current_basis, invalidated_composition
    old, new = before['report'], after['report']
    b0, b1 = old['current_analysis_basis'], new['current_analysis_basis']
    current_basis(b0, BASE_APP, package['base_exe_sha256'])
    current_basis(b1, APP, package['new_exe_sha256'])
    require(b0['engine_id'] != b1['engine_id'] and b0['digest'] != b1['digest'], 'Fresh executable identity was not applied')
    exact(b0['inputs'], b1['inputs'], 'Original source inputs changed')
    require(old['status'] == 'reviewed' and bool(old['reviewed_by']), 'Original17 report was not visibly approved')
    require(new['status'] == 'draft' and not new['reviewed_by'] and new['version'] == old['version'] + 1,
            'New program must invalidate old program-bound approval exactly once')
    require(new['review_revision'] == old['review_revision'] + 1, 'Unexpected review revision change')
    allowed = {'current_analysis_basis', 'current_hrv_reference', 'review_revision', 'reviewed_by',
               'status', 'updated_at', 'version', 'composition'}
    exact({k: v for k, v in old.items() if k not in allowed},
          {k: v for k, v in new.items() if k not in allowed}, 'Old conclusion, historical proof or report identity changed')
    exact(new['composition'], invalidated_composition(old['composition']), 'Saved figures, notes or output choices changed')
    exact(new['analysis_provenance'], old['analysis_provenance'], 'The original17 signature was rewritten or re-signed')
    require(new['analysis_provenance']['basis']['digest'] == b0['digest'] != b1['digest'], 'Old signature silently became a new approval')
    stored = lambda value: [{k: v for k, v in item.items() if k != 'stt_review_receipt'}
                            for item in value['annotations']['items']]
    exact(stored(before), stored(after), 'Stored physician annotations or measurement proofs changed')
    require(before['beat_editor']['revision'] == after['beat_editor']['revision'], 'The beat editor changed during upgrade')
    previous = {e['event_id']: e for e in before['events']['items']}
    current = {e['event_id']: e for e in after['events']['items']}
    ids = [eid for eid, e in previous.items() if e['category'] == 'ST']
    require(ids, 'Actual original17 baseline had no adopted ST-T evidence')
    for eid in ids:
        require(eid in current and current[eid]['stt_review_state'] == 'stale', 'Old program-bound ST-T proof was not retained as stale')
        exact(previous[eid]['stt_event_evidence'], current[eid]['stt_event_evidence'], 'Historical v3 evidence was relabelled')
    require(after['stt']['analysis']['algorithm_version'] == before['stt']['analysis']['algorithm_version'] ==
            'stt-screening-0.4.0-comprehensive-independent', 'Clinical ST-T algorithm changed in a UI repair')
    return dict(status='passed', old_report_version=old['version'], new_report_version=new['version'],
                retained_selected_figures=len(old['composition']['selected_events']), retained_STT_records=ids,
                historical_signature_preserved_not_resigned=True, clinical_core_same=True)


async def approve_original17(page, case_id):
    from scripts.verify_windows_ui15_upgrade import get
    async def settled():
        await page.wait_for_function("()=>state.currentPage==='report'&&!state.reportDirty&&!state.reportSaving&&!state.reportEvidenceLoading&&!state.reportViewLoading")
    await page.locator('.nav-item[data-page="report"]').click()
    await settled()
    await page.locator('#reportV2Nav [data-category="ST"]').click()
    await settled()
    events = await get(page, case_id, 'report-events?category=ST&stt_group=all&limit=1000')
    event = next(e for e in reversed(events['items']) if e.get('stt_review_state') == 'reviewed')
    await page.locator('tr[data-report-event-id="' + event['event_id'] + '"] [data-locate]').click()
    await page.locator('[data-stt-include-recommended]').wait_for()
    await page.locator('[data-stt-include-recommended]').click()
    await page.wait_for_function('()=>!state.sttReportAdding')
    await settled()
    await page.locator('#reportV2Nav [data-category="final"]').click()
    await settled()
    if not await page.locator('#conclusionEditor').is_visible():
        await page.locator('.rw-conclusion-disclosure>summary').click()
    note = 'Original17 mathematical physician workflow baseline; retained through actual18 upgrade.'
    await page.locator('#conclusionEditor').fill(note)
    await page.locator('#conclusionEditor').press('Tab')
    await settled()
    await page.wait_for_function('note=>state.report.conclusion===note', arg=note)
    await page.locator('#approveReport').click()
    await page.wait_for_function("()=>state.report?.status==='reviewed'&&!state.reportSaving")
    report = await get(page, case_id, 'report')
    require(report['conclusion'] == note and len(report['composition']['selected_events']) >= 4,
            'Visible original17 baseline must contain real saved ST-T and AF figures')


async def run(args, result):
    require(os.name == 'nt' and platform.machine().upper() in ('AMD64', 'X86_64'), 'Actual native Windows x64 required')
    from playwright.async_api import async_playwright
    from scripts.windows_deidentified_package import unpack
    from scripts.windows_doctor_build import verify_content_manifest
    from scripts.verify_windows_doctor_browser import (launch, stop, live_state, manager_page, resume,
        worklist_ready, pe_is_x64, process_modules, safe_error)
    from scripts.verify_windows_ui15_upgrade import cleanup_owned, get
    from scripts.verify_windows_stt_independent_upgrade import embedded_modules, database_state, public_database, compare_database, capture
    from scripts.generate_stt_comprehensive_math import generate
    from scripts.deidentify_patient_source import export_case
    from ecg_core.repository import CaseRepository
    from ecg_core import doctor_source
    checks = result['checks']
    with tempfile.TemporaryDirectory(prefix='STT-buttons-actual18-') as temporary:
        work = Path(temporary)
        new = unpack(args.software_archive, work / 'new')
        verify_content_manifest(new)
        old = None
        if args.base_software_archive:
            require(sha256(args.base_software_archive.read_bytes()).hexdigest() == BASE_P01_SHA, 'Original17 P01 ZIP bytes differ')
            old = unpack(args.base_software_archive, work / 'old')
            verify_content_manifest(old)
        result['package_identity'] = package = program_identity(new, old)
        exe = new / 'CardioInsightDoctorEval.exe'
        require(pe_is_x64(exe), 'Current18 is not an actual AMD64 PE')
        result['actual_embedded_runtime'] = embedded_modules(exe, ROOT)
        declaration = generate(work / 'mathematics')
        cases, issues = CaseRepository(work / 'mathematics').scan_cases()
        require(len(cases) == 1 and not issues, 'Independent mathematical fixture scan failed')
        source = work / 'source/P01'
        export_case(cases[0], source, mathematical_fixture=True)
        descriptor = doctor_source.validate_source(source)
        require(descriptor['kind'] == 'mathematical_deidentified_fixture' and descriptor['patient_inputs_read'] is False,
                'Only independently generated mathematical input is permitted')
        original = files(source)
        home = work / 'same-home'
        context = browser = page = None
        active = exe
        after_mode = False
        errors, blocked = [], []
        primary = None
        result['mathematical_source'] = declaration
        async with async_playwright() as pw:
            try:
                browser = await pw.chromium.launch(channel='msedge', headless=True)
                result['browser'] = dict(channel='msedge', installed_system_browser=True, version=browser.version)
                async def local_only(route):
                    url = urlsplit(route.request.url)
                    if url.hostname not in ('localhost', '127.0.0.1', '::1') or url.path.lower().endswith('.pdf'):
                        blocked.append(dict(kind='external-or-PDF', path=url.path))
                        return await route.abort()
                    if after_mode and '/api/cases/' in url.path and route.request.method not in ('GET', 'HEAD'):
                        if not (route.request.method == 'POST' and url.path.rsplit('/', 1)[-1] in READONLY_POSTS):
                            blocked.append(dict(kind='clinical-write-after-upgrade', path=url.path))
                            return await route.abort()
                    await route.continue_()
                async def new_context():
                    value = await browser.new_context(viewport=dict(width=1440, height=1000), service_workers='block', accept_downloads=False)
                    def observe(p):
                        p.set_default_timeout(90000)
                        p.set_default_navigation_timeout(90000)
                        p.on('pageerror', lambda e: errors.append(safe_error(e)))
                    value.on('page', observe)
                    await value.route('**/*', local_only)
                    return value
                async def begin(program, reuse=False):
                    manager, _ = await launch(program, home, None if reuse else source)
                    if reuse:
                        return await resume(context, manager, workspace)
                    manager_tab = await manager_page(context, manager)
                    async with manager_tab.expect_response(lambda r: urlsplit(r.url).path == '/continue'):
                        await manager_tab.locator('#continueExperience').click()
                    await worklist_ready(manager_tab)
                    return manager_tab
                from scripts.verify_stt_comprehensive_ui import verify as stt_flow
                from scripts.verify_af_multistrip_ui import verify as af_flow
                context = await new_context()
                if old is None:
                    page = await begin(exe)
                    workspace = json.loads((home / 'catalog.json').read_text())['selected_workspace']
                    running = await live_state(home, workspace, exe)
                    modules = await asyncio.to_thread(process_modules, running['pid'], exe)
                    require(modules['python_dll_from_bundle'], 'Current application did not load bundled Python')
                    result['comprehensive_STT'] = await stt_flow(page, doctor_source.CASE_ID, args.output.parent / 'STT-current')
                    result['AF_multistrip'] = await af_flow(page, doctor_source.CASE_ID, args.output.parent / 'AF-current',
                        source_kind='mathematical_synthetic', note='Actual Windows18 mathematical AF protection')
                    from scripts.verify_stt_report_buttons_ui import verify as buttons_flow
                    result['STT_report_buttons'] = await buttons_flow(page, doctor_source.CASE_ID, args.output.parent / 'STT-buttons-current')
                    result['actual_processes'] = [dict(phase='fresh18', pid=running['pid'], birth=running['birth'])]
                    checks.extend(['actual18-PE-and40-embedded-runtime-modules', 'system-Edge-and-bundled-Python',
                                   'current-comprehensive-STT-visible-flow', 'independent-AF-multistrip-protection',
                                   'new-A4-preview-and-pending-save-STT-visible-controls'])
                else:
                    old_exe = old / 'CardioInsightDoctorEval.exe'
                    require(pe_is_x64(old_exe), 'Original17 is not an actual AMD64 PE')
                    active = old_exe
                    page = await begin(old_exe)
                    workspace = json.loads((home / 'catalog.json').read_text())['selected_workspace']
                    state0 = await live_state(home, workspace, old_exe)
                    module0 = await asyncio.to_thread(process_modules, state0['pid'], old_exe)
                    require(module0['python_dll_from_bundle'], 'Original17 did not load bundled Python')
                    result['original17_STT_baseline'] = await stt_flow(page, doctor_source.CASE_ID, args.output.parent / 'original17-STT')
                    result['original17_AF_baseline'] = await af_flow(page, doctor_source.CASE_ID, args.output.parent / 'original17-AF',
                        source_kind='mathematical_synthetic', note='Original17 mathematical baseline for actual18 upgrade')
                    await approve_original17(page, doctor_source.CASE_ID)
                    before = await capture(page, doctor_source.CASE_ID, get, after=True)
                    await context.close()
                    context = None
                    await stop(old_exe, home)
                    database = home / 'workspaces' / workspace / 'data/cardioinsight.db'
                    database0 = database_state(database)
                    (args.output.parent / 'original17-before-report.json').write_text(json.dumps(before['report'], ensure_ascii=False, indent=2) + '\n')
                    after_mode = True
                    active = exe
                    first = datetime.now(timezone.utc)
                    context = await new_context()
                    page = await begin(exe, reuse=True)
                    state1 = await live_state(home, workspace, exe)
                    module1 = await asyncio.to_thread(process_modules, state1['pid'], exe)
                    require(module1['python_dll_from_bundle'], 'Actual18 did not load bundled Python')
                    require((state0['pid'], state0['birth']) != (state1['pid'], state1['birth']), 'Upgrade reused the old17 process')
                    require(json.loads((home / 'catalog.json').read_text())['selected_workspace'] == workspace, 'Upgrade changed workspace')
                    await page.locator('#openFirstCase').click()
                    await page.wait_for_function('id=>state.caseId===id&&!state.caseLoading', arg=doctor_source.CASE_ID)
                    after = await capture(page, doctor_source.CASE_ID, get, after=True)
                    result['API_upgrade'] = compare_api(before, after, package)
                    for _ in range(3):
                        exact(after, await capture(page, doctor_source.CASE_ID, get, after=True), 'Repeated new18 GET changed retained work')
                    await context.close()
                    context = None
                    await stop(exe, home)
                    last = datetime.now(timezone.utc)
                    database1 = database_state(database)
                    result['database_upgrade'] = compare_database(database0, database1, doctor_source.CASE_ID, first, last,
                        before['report']['current_analysis_basis'], after['report']['current_analysis_basis'])
                    result['database_before'] = public_database(database0)
                    result['database_after'] = public_database(database1)
                    (args.output.parent / 'actual18-after-report.json').write_text(json.dumps(after['report'], ensure_ascii=False, indent=2) + '\n')
                    result['actual_processes'] = [dict(phase='original17', pid=state0['pid'], birth=state0['birth']),
                                                  dict(phase='fresh18', pid=state1['pid'], birth=state1['birth'])]
                    checks.extend(['exact-original17-P01-and-distinct-fresh18-PE', 'same-clinical-core-and-new-UI-identity',
                        'old17-visible-reviewed-STT-and-AF-baseline', 'same-source-home-workspace-and-bundled-Python',
                        'retained-annotations-UUIDs-curation-and-physician-conclusion',
                        'old-signature-retained-not-resigned-and-current-report-invalidated-once',
                        'three-read-only-reopens-idempotent-with-no-clinical-writes'])
                require(files(source) == original, 'Mathematical source files changed')
                require(not errors and not blocked, 'Page errors or forbidden network/PDF/clinical operations occurred')
                result.update(status='passed', native_frozen_runtime=True, primary_checks=len(checks),
                              source_hashes_unchanged=True, bundled_python_proved=True,
                              page_errors=errors, blocked_requests=blocked,
                              windows_system=platform.system(), windows_release=platform.release())
            except Exception as error:
                primary = error
                result.update(status='failed', error=safe_error(error), page_errors=errors, blocked_requests=blocked)
                if page and not page.is_closed():
                    try:
                        await page.screenshot(path=str(args.output.parent / 'mathematical-native-failure.png'))
                    except Exception:
                        pass
                raise
            finally:
                await cleanup_owned(context, browser, active, home, stop, result, primary, sanitize=safe_error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--software-archive', type=Path, required=True)
    parser.add_argument('--base-software-archive', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), 'Preserve original native attempts')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = dict(status='running', mode='actual-original17-to18' if args.base_software_archive else 'actual-fresh18-STT-buttons',
                  checks=[], patient_inputs_read=False, clinical_accuracy_validated=False,
                  physical_hospital_Windows10_verified=False, pdf_operations=0)
    try:
        asyncio.run(run(args, result))
    except BaseException:
        result['status'] = 'failed'
        raise
    finally:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        print('WINDOWS_STT_BUTTONS_NATIVE_JSON=' + json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
