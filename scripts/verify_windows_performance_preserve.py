"""Actual fresh21 performance operations and original20 physician-review preservation.

This controller never relabels a packaging-only fixture as delivered21, never
patches an executable and never imports old clinical code into a new namespace.
Both application phases run real AMD64 PE files with bundled Python and Edge.
All generated inputs and publicly retained screenshots are mathematical only.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import marshal
import time
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import re
import sys
import tempfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
from ecg_core.config import APP_VERSION
APP = APP_VERSION
VERSION = '1.0.21'
BASE_APP = '0.12.32-stt-report-buttons.20261110'
BASE_VERSION = '1.0.20'
BASE_P01_SHA = '440bdc5960387ff34f08b6e8539840d36c7ef0acdbe715a894d1cd352a7b078b'
BASE_PE_SHA = '20e2182e04b175609b4c08619b57d950113684697c555b6868994c97fd9ee74f'
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
    require(release['packaging_version'] == VERSION, 'Expected a real delivered21, not an upgrade fixture')
    require(release['app_version'] == release['software_version'] == APP, 'Current application version differs')
    require(release['source_id'] == 'P01' and release['source_data_bundled'] is False, 'Expected source-free P01 software')
    require(not any(release.get(k, False) for k in ('ui_repack_only', 'binary_reused_without_rebuild',
                                                   'verification_fixture_only')), 'A reused binary or internal upgrade fixture is not delivered21')
    if old_release is not None:
        require(old_release['packaging_version'] == BASE_VERSION and old_release['app_version'] == BASE_APP,
                'The baseline must be original delivered20')
        require(old_release['source_id'] == 'P01' and old_release['source_data_bundled'] is False,
                'Original20 baseline must be source-free P01')
        require(old_PE_sha256 == BASE_PE_SHA and old_PE_sha256 != new_PE_sha256,
                'Expected distinct original20 and fresh21 actual executables')
        require(old_shared['ui_version'] != shared['ui_version'], 'The delivered21 UI was not updated')
    return dict(application_version=APP, packaging_version=VERSION, new_exe_sha256=new_PE_sha256,
                base_application_version=BASE_APP if old_release else None,
                base_packaging_version=BASE_VERSION if old_release else None,
                base_exe_sha256=old_PE_sha256, performance_only_compatibility_verified_by_actual_workspace=True,
                core_version=shared['core_version'], ui_version=shared['ui_version'])


def program_identity(new, old=None):
    from scripts.shared_source import snapshot
    from scripts.verify_public_release import verify
    read = lambda p: json.loads(p.read_text(encoding='utf-8-sig'))
    release, shared = read(new / 'RELEASE.json'), read(new / '_internal/shared-source-build.json')
    expected_compile_commit = os.environ.get('ECG_EXPECTED_WINDOWS_BUILD_COMMIT') or os.environ.get('GITHUB_SHA')
    if expected_compile_commit:
        require(release['source_commit'] == expected_compile_commit, 'Package was not compiled from the strictly verified producer commit')
    require(release['production_source_identity'] == verify(ROOT), 'Actual package differs from current production manifest')
    require(shared == snapshot(ROOT)[0], 'Actual package shared stamp differs from frozen current source')
    assets = {name: row for name, row in shared['files'].items() if row['component'] == 'ui'}
    require(len(assets) >= 81, 'Expected complete current UI resources')
    for name, row in assets.items():
        require(sha256((new / '_internal' / name).read_bytes()).hexdigest() == row['sha256'],
                'Actual packaged UI bytes differ: ' + name)
    old_release = read(old / 'RELEASE.json') if old else None
    old_shared = read(old / '_internal/shared-source-build.json') if old else None
    proof = metadata_identity(release, shared, old_release=old_release, old_shared=old_shared,
                              new_PE_sha256=sha256((new / 'CardioInsightDoctorEval.exe').read_bytes()).hexdigest(),
                              old_PE_sha256=sha256((old / 'CardioInsightDoctorEval.exe').read_bytes()).hexdigest() if old else None)
    policy_name = 'performance-compatibility.json'
    policy = read(new / '_internal' / policy_name)
    exact(policy, read(ROOT / policy_name), 'Actual packaged compatibility policy differs from frozen Windows source')
    require(policy['schema']=='performance-evidence-continuity-v1', 'Unexpected compatibility policy schema')
    proof['performance_policy_sha256'] = fingerprint(policy)
    proof.update(source_compile_commit=release['source_commit'], acceptance_controller_commit=os.environ.get('GITHUB_SHA'), production_source_identity=release['production_source_identity'],
                 common_source_fingerprint=shared['source_fingerprint'], actual_UI_files_verified=len(assets))
    return proof


def embedded_modules(exe, root):
    """Inspect actual PE/PYZ code; compare every runtime Python file to source."""
    from PyInstaller.archive.readers import CArchiveReader
    from scripts.verify_windows_stt_independent_upgrade import normalized_code
    reader = CArchiveReader(exe)
    pyzs = [n for n, row in reader.toc.items() if row[-1] == 'z']
    require(len(pyzs) == 1, 'Expected one actual embedded Python archive')
    pyz = reader.open_embedded_archive(pyzs[0])
    paths = [root / 'app.py', root / 'win_doctor_eval.py', *sorted((root / 'ecg_core').glob('*.py'))]
    require(len(paths) >= 41, 'Performance release is missing the compatibility runtime module')
    from ecg_core.performance_compatibility import code_value
    policy = json.loads((root / 'performance-compatibility.json').read_text())
    semantics = {}
    hashes = {}
    for path in paths:
        name = path.relative_to(root).as_posix()
        if name == 'win_doctor_eval.py':
            actual = marshal.loads(reader.extract('win_doctor_eval'))
        else:
            module = name[:-3].replace('/', '.')
            if module.endswith('.__init__'):
                module = module[:-9]
            require(module in pyz.toc, 'Actual PE module missing: ' + module)
            actual = pyz.extract(module)
            semantics[module] = fingerprint(code_value(actual))
        expected = compile(path.read_bytes(), name, 'exec', optimize=0, dont_inherit=True)
        require(normalized_code(actual) == normalized_code(expected), 'Actual PE differs from frozen source: ' + name)
        hashes[name] = sha256(path.read_bytes()).hexdigest()
    require({name:semantics.get(name) for name in policy['current_code']}==policy['current_code'], 'Actual frozen module semantics do not match packaged compatibility policy')
    return dict(runtime_python_files_verified=len(hashes), runtime_python_sha256=hashes,
                code_semantics_matches_packaged_policy=True, policy_code_modules_verified=len(policy['current_code']))


def compare_api(before, after, package):
    from scripts.verify_windows_stt_independent_upgrade import current_basis
    old, new = before['report'], after['report']
    b0, b1 = old['current_analysis_basis'], new['current_analysis_basis']
    current_basis(b0, BASE_APP, package['base_exe_sha256'])
    exact(b0, b1, 'Numerically equivalent upgrade did not retain original evidence basis')
    require(old['status'] == new['status'] == 'reviewed' and old['reviewed_by'], 'Original physician approval was invalidated')
    exact(old['reviewed_by'], new['reviewed_by'], 'Original approving physician changed')
    exact(old['analysis_provenance'], new['analysis_provenance'], 'Original signature was rewritten or re-signed')
    for key in ('conclusion', 'composition', 'version', 'review_revision', 'current_hrv_reference'):
        exact(old[key], new[key], 'Previously reviewed report field changed: ' + key)
    stored = lambda value: [{k: v for k, v in item.items() if k != 'stt_review_receipt'}
                            for item in value['annotations']['items']]
    exact(stored(before), stored(after), 'Original physician records or measurement evidence changed')
    exact(before['beat_editor']['revision'], after['beat_editor']['revision'], 'Beat revision changed')
    exact(before['workflow'], after['workflow'], 'Reviewed workflow was reset by a performance upgrade')
    previous = {e['event_id']: e for e in before['events']['items']}
    current = {e['event_id']: e for e in after['events']['items']}
    uses = [u for u in old['composition'].get('stt_report_use', []) if all(u.get(k) for k in ('table', 'text', 'strip'))]
    require(uses, 'Original20 baseline lacks a physician-reviewed ST record adopted as table, text and strip')
    for use in uses:
        eid = use['event_id']
        require(eid in previous and eid in current, 'Adopted ST record disappeared')
        for phase in (previous[eid], current[eid]):
            require(phase['stt_review_state'] == 'reviewed', 'Previously reviewed ST record became stale')
            require(all(phase['stt_report_eligibility'].get(k) for k in ('table', 'text', 'strip')), 'ST reporting eligibility lost')
        exact(previous[eid]['stt_event_evidence'], current[eid]['stt_event_evidence'], 'Original ST measurement evidence changed')
    require(after['stt']['analysis']['algorithm_version'] == before['stt']['analysis']['algorithm_version'], 'ST algorithm version changed')
    return dict(status='passed', original_status=old['status'], upgraded_status=new['status'],
                retained_selected_figures=len(new['composition']['selected_events']),
                retained_qualified_STT=[u['event_id'] for u in uses],
                original_evidence_basis_retained=True, original_signature_retained_not_resigned=True,
                original_workflow_HRV_RR_retained=True)


def compare_database(before, after, package):
    require(before['recovery_epoch'] == after['recovery_epoch'], 'Workspace recovery epoch changed')
    left, right = before['tables'], after['tables']
    require(set(left) <= set(right), 'An existing workspace table disappeared')
    for name in ('annotations', 'stt_review_submissions', 'case_review', 'report_drafts', 'case_analysis_basis'):
        require(name in left and name in right, 'Expected physician data table missing: ' + name)
        exact(left[name], right[name], 'Original physician record, signature or approval table changed: ' + name)
    for name in set(left) - {'audit_log'}:
        exact(left[name], right[name], 'Upgrade changed persisted clinical/workspace data: ' + name)
    audit0 = sorted(left['audit_log']['rows'], key=lambda r: r['id'])
    audit1 = sorted(right['audit_log']['rows'], key=lambda r: r['id'])
    exact(audit1[:len(audit0)], audit0, 'Original audit history changed')
    added = audit1[len(audit0):]
    require(any(r['action']=='analysis.performance_upgrade_verified' for r in added), 'No explicit performance-compatibility audit was written')
    certificates = right.get('analysis_implementation_compatibility', {}).get('rows', [])
    require(len(certificates)==1, 'Expected one immutable-workspace compatibility bridge')
    certificate = json.loads(certificates[0]['certificate'])
    original_basis = json.loads(left['case_analysis_basis']['rows'][0]['basis'])
    exact(certificate['reference_basis'], original_basis, 'Audit bridge is not bound to original physician evidence')
    require(certificate['policy_digest']==package['performance_policy_sha256'], 'Bridge is not bound to actual packaged policy')
    require(certificate['execution_engine_id']!=original_basis['engine_id'] and certificate['execution_basis']!=original_basis['digest'], 'Bridge does not identify a distinct executing build')
    require(certificate['stt_proofs'] and certificate['retained_stt_records'], 'No actual per-record ST numerical revalidation was recorded')
    require(not any(r['action'] == 'analysis.basis_changed' for r in added), 'Performance-only upgrade invalidated doctor review')
    return dict(status='passed', preserved_existing_tables=sorted(set(left)-{'audit_log'}),
                preserved_UUID_submissions=len(left['stt_review_submissions']['rows']),
                appended_tables=sorted(set(right)-set(left)), appended_audit_actions=[r['action'] for r in added],
                approved_report_signature_and_selection_preserved=True)


async def verify_hrv(page, case_id):
    from scripts.verify_windows_ui15_upgrade import get
    # UI_saveflow intentionally leaves a later ST draft unsaved. Navigate as a
    # physician and explicitly discard only that draft, never reset state or
    # silently write it into the reviewed records.
    annotations_before_navigation = await get(page, case_id, 'annotations')
    navigation_writes = []
    def observe_navigation(request):
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            navigation_writes.append(dict(method=request.method, url=request.url))
    page.on('request', observe_navigation)
    await page.locator('.nav-item[data-page="trends"]').click()
    await page.wait_for_function("()=>state.currentPage==='trends'||!!document.querySelector('#unsavedChangesDialog[open]')", timeout=180000)
    discarded_STT_draft = False
    if await page.locator('#unsavedChangesDialog[open]').count():
        require(await page.locator('#unsavedChangesTitle').inner_text() == 'ST-T 复核尚未保存',
                'Unexpected unsaved-navigation prompt before HRV')
        require(await page.evaluate("()=>state.currentPage==='stt'&&sttReviewHasUnsavedNote()"),
                'ST draft prompt is not attached to the active ST workbench')
        await page.locator('#unsavedChangesDialog [data-unsaved-discard]').click()
        await page.locator('#unsavedChangesDialog').wait_for(state='hidden', timeout=180000)
        discarded_STT_draft = True
    await page.wait_for_function("()=>state.currentPage==='trends'&&!document.querySelector('#unsavedChangesDialog[open]')", timeout=180000)
    await page.locator('[data-hrv-edit-block]').first.wait_for(timeout=180000)
    page.remove_listener('request', observe_navigation)
    annotations_after_navigation = await get(page, case_id, 'annotations')
    exact(annotations_before_navigation['items'], annotations_after_navigation['items'],
          'Discarding the unsaved ST draft changed previously saved ST records')
    require(not navigation_writes, 'Navigation silently saved or changed physician records')
    before = await get(page, case_id, 'hrv-review?window=0&analysis=edited')
    await page.locator('[data-hrv-edit-start]').fill('140')
    await page.locator('[data-hrv-edit-end]').fill('150')
    await page.locator('[data-hrv-edit-reason]').fill('Windows21 mathematical performance check')
    started = time.perf_counter()
    await page.locator('[data-hrv-edit-action="exclude"]').click()
    await page.locator('[data-hrv-edit-action="apply"]').wait_for(timeout=180000)
    preview = time.perf_counter()-started
    started = time.perf_counter()
    await page.locator('[data-hrv-edit-action="apply"]').click()
    await page.wait_for_function("()=>document.querySelector('.hrv-edit [data-hrv-edit-action=undo]:enabled')&&document.querySelector('[data-hrv-edit-exclusions]').textContent.includes('Windows21 mathematical performance check')", timeout=180000)
    apply = time.perf_counter()-started
    saved = await get(page, case_id, 'hrv-review?window=0&analysis=edited')
    require(saved['hrv_revision']>before['hrv_revision'] and any(r.get('reason')=='Windows21 mathematical performance check' for r in saved['document']['exclusions']), 'Actual HRV exclusion was not persisted')
    await page.locator('[data-hrv-edit-action="undo"]').click()
    await page.locator('[data-hrv-edit-action="apply"]').wait_for(timeout=180000)
    await page.locator('[data-hrv-edit-action="apply"]').click()
    await page.wait_for_function("()=>document.querySelector('.hrv-edit [data-hrv-edit-action=redo]:enabled')&&!document.querySelector('[data-hrv-edit-exclusions]').textContent.includes('Windows21 mathematical performance check')", timeout=180000)
    restored = await get(page, case_id, 'hrv-review?window=0&analysis=edited')
    exact(before['document'], restored['document'], 'HRV undo did not restore the original saved document')
    require(restored['hrv_revision']>saved['hrv_revision'], 'HRV undo revision was not persisted')
    return dict(status='passed', preview_seconds=preview, saved_update_seconds=apply,
                original_hrv_revision=before['hrv_revision'],saved_hrv_revision=saved['hrv_revision'],restored_hrv_revision=restored['hrv_revision'],
                actual_exclusion_saved_and_undone=True,original_document_restored=True,
                STT_unsaved_navigation=dict(discarded_draft_via_visible_prompt=discarded_STT_draft,
                    saved_records_unchanged=True,navigation_writes=navigation_writes,current_page='trends'))


async def formal_pdf(page, case_id):
    from scripts.verify_windows_ui15_upgrade import get
    address = urlsplit(page.url)
    before = await get(page, case_id, 'report')
    require(before['status']=='reviewed', 'Expected the original physician-approved report before formal export')
    started = time.perf_counter()
    response = await page.request.get(address.scheme+'://'+address.netloc+'/api/cases/'+case_id+'/report.pdf?expected_version='+str(before['version'])+'&expected_review_revision='+str(before['review_revision']))
    body = await response.body()
    elapsed = time.perf_counter()-started
    require(response.headers.get('x-report-sha256') == sha256(body).hexdigest(), 'Actual PDF integrity header differs')
    require(response.headers.get('content-type', '').startswith('application/pdf'), 'Unexpected formal PDF content type')
    require(response.ok and body.startswith(b'%PDF-') and len(body)>1000, 'Previously approved report cannot export formal PDF after upgrade')
    pages = len(re.findall(rb'/Type\s*/Page\b', body))
    require(pages>0, 'Formal report PDF has no actual page objects')
    require(response.headers.get('x-report-version')==str(before['version']) and response.headers.get('x-review-revision')==str(before['review_revision']), 'Formal PDF used a different report or review version')
    report = await get(page, case_id, 'report')
    for key in ('status','reviewed_by','version','review_revision','analysis_provenance'):
        exact(before[key], report[key], 'Formal export changed original approval: '+key)
    return dict(status='passed', seconds=elapsed, bytes=len(body), sha256=sha256(body).hexdigest(),page_count=pages,
                report_status=before['status'],report_version=before['version'],review_revision=before['review_revision'],
                old_approved_report_exported_without_reapproval=True)


async def author_nonempty_scopes(page, case_id):
    """Persist real old20 HRV and RR decisions through its visible controls."""
    from scripts.verify_windows_ui15_upgrade import get
    await page.locator('.nav-item[data-page="trends"]').click()
    await page.locator('[data-hrv-edit-block]').first.wait_for(timeout=180000)
    await page.locator('[data-hrv-edit-start]').fill('140')
    await page.locator('[data-hrv-edit-end]').fill('150')
    await page.locator('[data-hrv-edit-reason]').fill('Original20 mathematical authored exclusion retained by21')
    await page.locator('[data-hrv-edit-action="exclude"]').click()
    await page.locator('[data-hrv-edit-action="apply"]').wait_for(timeout=180000)
    await page.locator('[data-hrv-edit-action="apply"]').click()
    await page.wait_for_function("()=>document.querySelector('.hrv-edit [data-hrv-edit-action=undo]:enabled')&&document.querySelector('[data-hrv-edit-exclusions]').textContent.includes('Original20 mathematical authored exclusion retained by21')", timeout=180000)
    await page.locator('[data-hrv-edit-ack]').check()
    await page.locator('[data-hrv-edit-note]').fill('Original20 mathematical window acknowledgement retained by21')
    await page.locator('[data-hrv-edit-action="confirm"]').click()
    await page.wait_for_function("()=>document.querySelector('.hrv-edit[aria-busy=false] [data-hrv-edit-confirmation]')?.textContent.includes('已保存')", timeout=180000)
    hrv = await get(page, case_id, 'hrv-review?window=0&analysis=edited')
    require(hrv['document']['exclusions'] and hrv['hrv_revision']>0 and hrv['confirmation']['valid'],
            'Old20 did not actually persist and confirm a nonempty HRV exclusion')
    await page.evaluate("""async()=>{const b='/api/cases/'+state.caseId,ledger=await api(b+'/evidence-candidates'),e=(await api(b+'/report-rr-evidence')).event;
        await ECGReviewCandidates.choose({identity:ledger,item:{sample_index:e.sample_index,rr_ms:e.rr_ms,class_code:e.evidence_ref.terminal.class_code}});} """)
    caption = 'Original20 mathematical reviewed RR retained by21'
    await page.locator('.review-candidate-dialog input').fill(caption)
    await page.locator('[data-candidate-save]').click()
    await page.locator('[data-candidate-open-report]').wait_for()
    await page.locator('[data-candidate-open-report]').click()
    ready = "()=>state.currentPage==='report'&&!state.reportDirty&&!state.reportSaving&&!state.reportViewLoading&&!state.reportEvidenceLoading"
    await page.wait_for_function(ready)
    rows = await get(page, case_id, 'report-events?category=rr_interval&rr_source=manual&limit=1000')
    event = next(e for e in rows['items'] if e['label']==caption)
    await page.locator('tr[data-report-event-id="'+event['event_id']+'"] [data-include]').check()
    await page.wait_for_function(ready)
    await page.locator('#reportV2Nav [data-category="strips"]').click()
    await page.wait_for_function(ready)
    card = page.locator('.rw-strip[data-rw-key="'+event['event_id']+'"]')
    await card.locator('[data-review-evidence]').click()
    await page.locator('#reportEvidenceDialog [data-evidence-confirm]:enabled').wait_for(timeout=180000)
    await page.locator('#reportEvidenceDialog [data-evidence-confirm]').click()
    await page.locator('#reportEvidenceDialog').wait_for(state='detached')
    await page.wait_for_function(ready)
    reviewed = await get(page, case_id, 'report-events?category=rr_interval&rr_source=manual&limit=1000')
    actual = next(e for e in reviewed['items'] if e['event_id']==event['event_id'])
    require(actual['evidence_review']['status']=='confirmed' and actual['evidence_review']['presentations'],
            'Old20 RR pair was not actually acknowledged with a saved presentation')
    return dict(status='passed',HRV_exclusions=len(hrv['document']['exclusions']),
                HRV_revision=hrv['hrv_revision'],HRV_window_confirmation_valid=True,
                RR_event_id=event['event_id'],RR_original_pair=actual['evidence_ref'],
                RR_review=actual['evidence_review'],storage='HRV document; RR candidate/composition/report evidence review')


def compare_nonempty_scopes(before, after):
    for key in ('authored_HRV','authored_RR_candidates','authored_RR_events'):
        exact(before[key], after[key], 'Upgrade changed nonempty authored scope: '+key)
    hrv = after['authored_HRV']
    require(hrv['document']['exclusions'] and hrv['hrv_revision']>0 and hrv['confirmation']['valid']
            and not hrv['document_stale'], 'Retained HRV document/confirmation is empty or stale')
    candidates = after['authored_RR_candidates']['items']
    require(candidates and all(c['status']=='active' for c in candidates), 'Retained manual RR candidate missing')
    events = after['authored_RR_events']['items']
    require(events and all(e['evidence_review']['status']=='confirmed' and e['evidence_review']['presentations'] for e in events),
            'Retained RR pair/presentation acknowledgement is missing')
    chosen = {p['event_id'] for p in after['report']['composition']['selected_events']}
    require(all(e['event_id'] in chosen for e in events), 'Retained reviewed RR figure was removed from report')
    return dict(status='passed',HRV_exclusion_count=len(hrv['document']['exclusions']),
                HRV_revision=hrv['hrv_revision'],HRV_scope_document_and_confirmation_exact=True,
                HRV_window_confirmation_valid=True,RR_active_candidates=len(candidates),RR_confirmed_report_pairs=len(events),
                RR_original_pair_scope_presentation_actor_and_report_use_exact=True)


async def approve_original20(page, case_id):
    from scripts.verify_windows_ui15_upgrade import get
    async def settled():
        await page.wait_for_function("()=>state.currentPage==='report'&&!state.reportDirty&&!state.reportSaving&&!state.reportEvidenceLoading&&!state.reportViewLoading")
    await page.locator('.nav-item[data-page="report"]').click()
    await settled()
    await page.locator('#reportV2Nav [data-category="ST"]').click()
    await settled()
    events = await get(page, case_id, 'report-events?category=ST&stt_group=all&limit=1000')
    event = next(e for e in reversed(events['items']) if e.get('stt_review_state') == 'reviewed'
                 and all(e.get('stt_report_eligibility', {}).get(k) for k in ('table', 'text', 'strip')))
    await page.locator('tr[data-report-event-id="' + event['event_id'] + '"] [data-locate]').click()
    await page.locator('[data-stt-include-recommended]').wait_for()
    for purpose in ('table', 'text'):
        await page.locator('[data-stt-active-use="'+purpose+'"]').check()
        await settled()
    await page.locator('[data-stt-include-recommended]').click()
    await page.wait_for_function('()=>!state.sttReportAdding')
    await settled()
    await page.locator('#reportV2Nav [data-category="final"]').click()
    await settled()
    if not await page.locator('#conclusionEditor').is_visible():
        await page.locator('.rw-conclusion-disclosure>summary').click()
    note = 'Original20 mathematical physician workflow baseline; retained through actual21 upgrade.'
    await page.locator('#conclusionEditor').fill(note)
    await page.locator('#conclusionEditor').press('Tab')
    await settled()
    await page.wait_for_function('note=>state.report.conclusion===note', arg=note)
    await page.locator('#approveReport').click()
    await page.wait_for_function("()=>state.report?.status==='reviewed'&&!state.reportSaving")
    report = await get(page, case_id, 'report')
    require(report['conclusion'] == note and len(report['composition']['selected_events']) >= 4,
            'Visible original20 baseline must contain real saved ST-T and AF figures')


async def run(args, result):
    require(os.name == 'nt' and platform.machine().upper() in ('AMD64', 'X86_64'), 'Actual native Windows x64 required')
    from playwright.async_api import async_playwright
    from scripts.windows_deidentified_package import unpack
    from scripts.windows_doctor_build import verify_content_manifest
    from scripts.verify_windows_doctor_browser import (launch, stop, live_state, manager_page, resume,
        worklist_ready, pe_is_x64, process_modules, safe_error)
    from scripts.verify_windows_ui15_upgrade import cleanup_owned, get
    from scripts.verify_windows_stt_independent_upgrade import database_state, public_database, capture
    from scripts.generate_stt_comprehensive_math import generate
    from scripts.deidentify_patient_source import export_case
    from ecg_core.repository import CaseRepository
    from ecg_core import doctor_source
    checks = result['checks']
    with tempfile.TemporaryDirectory(prefix='UI-saveflow-actual21-') as temporary:
        work = Path(temporary)
        new = unpack(args.software_archive, work / 'new')
        verify_content_manifest(new)
        old = None
        if args.base_software_archive:
            require(sha256(args.base_software_archive.read_bytes()).hexdigest() == BASE_P01_SHA, 'Original20 P01 ZIP bytes differ')
            old = unpack(args.base_software_archive, work / 'old')
            verify_content_manifest(old)
        result['package_identity'] = package = program_identity(new, old)
        exe = new / 'CardioInsightDoctorEval.exe'
        require(pe_is_x64(exe), 'Current21 is not an actual AMD64 PE')
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
                    if url.hostname not in ('localhost', '127.0.0.1', '::1'):
                        blocked.append(dict(kind='external', path=url.path))
                        return await route.abort()
                    if after_mode and '/api/cases/' in url.path and route.request.method not in ('GET', 'HEAD'):
                        if not (route.request.method == 'POST' and url.path.rsplit('/', 1)[-1] in READONLY_POSTS):
                            blocked.append(dict(kind='clinical-write-after-upgrade', path=url.path))
                            return await route.abort()
                    await route.continue_()
                async def new_context():
                    value = await browser.new_context(viewport=dict(width=1440, height=1000), service_workers='block', accept_downloads=True)
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
                async def capture_current():
                    value = await capture(page, doctor_source.CASE_ID, get, after=True)
                    if args.nonempty_reviewed_scopes:
                        for key, endpoint in [('authored_HRV','hrv-review?window=0&analysis=edited'),
                                              ('authored_RR_candidates','evidence-candidates'),
                                              ('authored_RR_events','report-events?category=rr_interval&rr_source=manual&limit=1000')]:
                            value[key] = await get(page, doctor_source.CASE_ID, endpoint)
                    return value
                context = await new_context()
                if old is None:
                    page = await begin(exe)
                    workspace = json.loads((home / 'catalog.json').read_text())['selected_workspace']
                    running = await live_state(home, workspace, exe)
                    modules = await asyncio.to_thread(process_modules, running['pid'], exe)
                    require(modules['python_dll_from_bundle'], 'Current application did not load bundled Python')
                    result['comprehensive_STT'] = await stt_flow(page, doctor_source.CASE_ID, args.output.parent / 'STT-current')
                    result['AF_multistrip'] = await af_flow(page, doctor_source.CASE_ID, args.output.parent / 'AF-current',
                        source_kind='mathematical_synthetic', note='Actual Windows21 mathematical AF protection')
                    from scripts.verify_stt_report_buttons_ui import verify as buttons_flow
                    result['STT_report_buttons'] = await buttons_flow(page, doctor_source.CASE_ID, args.output.parent / 'STT-buttons-current')
                    from scripts.verify_ui_saveflow_ui import verify as saveflow
                    result['UI_saveflow'] = await saveflow(page, doctor_source.CASE_ID, args.output.parent / 'UI-saveflow-current')
                    result['HRV_performance'] = await verify_hrv(page, doctor_source.CASE_ID)
                    result['actual_processes'] = [dict(phase='fresh21', pid=running['pid'], birth=running['birth'])]
                    checks.extend(['actual21-PE-and-all-embedded-runtime-modules', 'system-Edge-and-bundled-Python',
                                   'current-comprehensive-STT-visible-flow', 'independent-AF-multistrip-protection',
                                   'retained-A4-preview-and-pending-save-STT-visible-controls',
                                   'actual21-STT-AF-incremental-save-delete-and-card-contextmenu'])
                else:
                    old_exe = old / 'CardioInsightDoctorEval.exe'
                    require(pe_is_x64(old_exe), 'Original20 is not an actual AMD64 PE')
                    active = old_exe
                    page = await begin(old_exe)
                    workspace = json.loads((home / 'catalog.json').read_text())['selected_workspace']
                    state0 = await live_state(home, workspace, old_exe)
                    module0 = await asyncio.to_thread(process_modules, state0['pid'], old_exe)
                    require(module0['python_dll_from_bundle'], 'Original20 did not load bundled Python')
                    result['original20_STT_baseline'] = await stt_flow(page, doctor_source.CASE_ID, args.output.parent / 'original20-STT')
                    result['original20_AF_baseline'] = await af_flow(page, doctor_source.CASE_ID, args.output.parent / 'original20-AF',
                        source_kind='mathematical_synthetic', note='Original20 mathematical baseline for actual21 upgrade')
                    if args.nonempty_reviewed_scopes:
                        result['old20_authored_nonempty_scopes'] = await author_nonempty_scopes(page, doctor_source.CASE_ID)
                    await approve_original20(page, doctor_source.CASE_ID)
                    before = await capture_current()
                    if args.nonempty_reviewed_scopes:
                        compare_nonempty_scopes(before, before)
                        (args.output.parent / 'original20-nonempty-scopes.json').write_text(json.dumps(before,ensure_ascii=False,indent=2)+'\n')
                    await context.close()
                    context = None
                    await stop(old_exe, home)
                    database = home / 'workspaces' / workspace / 'data/cardioinsight.db'
                    database0 = database_state(database)
                    (args.output.parent / 'original20-before-report.json').write_text(json.dumps(before['report'], ensure_ascii=False, indent=2) + '\n')
                    after_mode = True
                    active = exe
                    first = datetime.now(timezone.utc)
                    context = await new_context()
                    page = await begin(exe, reuse=True)
                    state1 = await live_state(home, workspace, exe)
                    module1 = await asyncio.to_thread(process_modules, state1['pid'], exe)
                    require(module1['python_dll_from_bundle'], 'Actual21 did not load bundled Python')
                    require((state0['pid'], state0['birth']) != (state1['pid'], state1['birth']), 'Upgrade reused the old20 process')
                    require(json.loads((home / 'catalog.json').read_text())['selected_workspace'] == workspace, 'Upgrade changed workspace')
                    await page.locator('#openFirstCase').click()
                    await page.wait_for_function('id=>state.caseId===id&&!state.caseLoading', arg=doctor_source.CASE_ID)
                    await page.wait_for_function("()=>state.currentPage==='review'&&overviewWorkbench.waveformBasis()&&Object.keys(state.waveform?.leads||{}).join(',')==='II,V1,V5'")
                    after = await capture_current()
                    require(await page.evaluate("state.currentPage==='review'&&Object.keys(state.waveform?.leads||{}).join(',')==='II,V1,V5'"), 'Upgraded case did not open in overview with loaded three-lead ECG')
                    result['API_upgrade'] = compare_api(before, after, package)
                    if args.nonempty_reviewed_scopes:
                        result['nonempty_scope_upgrade'] = compare_nonempty_scopes(before, after)
                        (args.output.parent / 'actual21-nonempty-scopes.json').write_text(json.dumps(after,ensure_ascii=False,indent=2)+'\n')
                    result['formal_PDF'] = await formal_pdf(page, doctor_source.CASE_ID)
                    result['pdf_operations'] = 1
                    for _ in range(3):
                        exact(after, await capture_current(), 'Repeated new21 GET changed retained work')
                    await context.close()
                    context = None
                    await stop(exe, home)
                    last = datetime.now(timezone.utc)
                    database1 = database_state(database)
                    result['database_upgrade'] = compare_database(database0, database1, package)
                    result['database_before'] = public_database(database0)
                    result['database_after'] = public_database(database1)
                    (args.output.parent / 'actual21-after-report.json').write_text(json.dumps(after['report'], ensure_ascii=False, indent=2) + '\n')
                    result['actual_processes'] = [dict(phase='original20', pid=state0['pid'], birth=state0['birth']),
                                                  dict(phase='fresh21', pid=state1['pid'], birth=state1['birth'])]
                    checks.extend(['exact-original20-P01-and-distinct-fresh21-PE', 'new-compiled-performance-source-and-unchanged-input-identity',
                        'old20-visible-reviewed-STT-and-AF-baseline', 'same-source-home-workspace-and-bundled-Python',
                        'retained-annotations-UUIDs-curation-and-physician-conclusion',
                        'old-signature-and-reviewed-report-preserved-without-reapproval',
                        'three-read-only-reopens-idempotent-with-no-clinical-writes',
                        'qualified-ST-table-text-strip-and-formal-PDF-preserved'])
                require(files(source) == original, 'Mathematical source files changed')
                require(not errors and not blocked, 'Page errors or forbidden network/clinical operations occurred')
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
    parser.add_argument('--nonempty-reviewed-scopes', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(not args.nonempty_reviewed_scopes or args.base_software_archive,
            'Authored nonempty scope retention requires an actual original20 upgrade')
    require(not args.output.exists(), 'Preserve original native attempts')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = dict(status='running', mode='actual-original20-to21' if args.base_software_archive else 'actual-fresh21-UI-saveflow',
                  checks=[], patient_inputs_read=False, clinical_accuracy_validated=False,
                  physical_hospital_Windows10_verified=False, pdf_operations=0)
    try:
        asyncio.run(run(args, result))
    except BaseException:
        result['status'] = 'failed'
        raise
    finally:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        print('WINDOWS_UI_SAVEFLOW_NATIVE_JSON=' + json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
