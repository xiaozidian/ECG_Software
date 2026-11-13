"""Actual Windows22 screening operations and original21 physician-review preservation.

This controller never relabels a packaging-only fixture as delivered22, never
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
VERSION = '1.0.22'
BASE_APP = '0.12.32-stt-report-buttons.20261110'
BASE_VERSION = '1.0.21'
BASE_P01_SHA = 'd59e378e28feabbf338032133a6efccbf728227f97076542eee31493c7649e41'
BASE_PE_SHA = 'bb1b6d277e0fa85bdb265efa4077641fdf15f2c6e5a0b71d84e4b09ae32b225a'
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
    require(release['packaging_version'] == VERSION, 'Expected a real delivered22, not an upgrade fixture')
    require(release['app_version'] == release['software_version'] == APP, 'Current application version differs')
    require(release['source_id'] == 'P01' and release['source_data_bundled'] is False, 'Expected source-free P01 software')
    require(not any(release.get(k, False) for k in ('ui_repack_only', 'binary_reused_without_rebuild',
                                                   'verification_fixture_only')), 'A reused binary or internal upgrade fixture is not delivered22')
    if old_release is not None:
        require(old_release['packaging_version'] == BASE_VERSION and old_release['app_version'] == BASE_APP,
                'The baseline must be original delivered21')
        require(old_release['source_id'] == 'P01' and old_release['source_data_bundled'] is False,
                'Original21 baseline must be source-free P01')
        require(old_PE_sha256 == BASE_PE_SHA and old_PE_sha256 != new_PE_sha256,
                'Expected distinct original21 and fresh22 actual executables')
        require(old_shared['ui_version'] != shared['ui_version'], 'The delivered22 UI was not updated')
    return dict(application_version=APP, packaging_version=VERSION, new_exe_sha256=new_PE_sha256,
                base_application_version=BASE_APP if old_release else None,
                base_packaging_version=BASE_VERSION if old_release else None,
                base_exe_sha256=old_PE_sha256, screening_refinement_continuity_verified_by_actual_workspace=True,
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
    policy_name = 'screening-refinement-compatibility.json'
    policy = read(new / '_internal' / policy_name)
    exact(policy, read(ROOT / policy_name), 'Actual packaged compatibility policy differs from frozen Windows source')
    require(policy['schema']=='stt-screening-refinement-continuity-v1', 'Unexpected compatibility policy schema')
    proof['screening_policy_sha256'] = fingerprint(policy)
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
    require(len(paths) >= 45, 'Screening release is missing a frozen runtime module')
    require(all((root/'ecg_core'/(n+'.py')).is_file() for n in ('screening_compatibility','stt_screening_legacy','stt_candidate_quality')), 'Missing new screening runtime modules')
    from ecg_core.performance_compatibility import code_value
    policy = json.loads((root / 'screening-refinement-compatibility.json').read_text())
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
    exact(b0, b1, 'Screening refinement did not retain exactly verified authored evidence basis')
    require(old['status'] == new['status'] == 'reviewed' and old['reviewed_by'], 'Original physician approval was invalidated')
    exact(old['reviewed_by'], new['reviewed_by'], 'Original approving physician changed')
    exact(old['analysis_provenance'], new['analysis_provenance'], 'Original signature was rewritten or re-signed')
    for key in ('conclusion', 'composition', 'version', 'review_revision', 'current_hrv_reference'):
        exact(old[key], new[key], 'Previously reviewed report field changed: ' + key)
    stored = lambda value: [{k: v for k, v in item.items() if k != 'stt_review_receipt'}
                            for item in value['annotations']['items']]
    exact(stored(before), stored(after), 'Original physician records or measurement evidence changed')
    exact(before['beat_editor']['revision'], after['beat_editor']['revision'], 'Beat revision changed')
    exact(before['workflow'], after['workflow'], 'Screening refinement reset original reviewed workflow')
    previous = {e['event_id']: e for e in before['events']['items']}
    current = {e['event_id']: e for e in after['events']['items']}
    uses = [u for u in old['composition'].get('stt_report_use', []) if all(u.get(k) for k in ('table', 'text', 'strip'))]
    require(uses, 'Original21 baseline lacks a physician-reviewed ST record adopted as table, text and strip')
    for use in uses:
        eid = use['event_id']
        require(eid in previous and eid in current, 'Adopted ST record disappeared')
        for phase in (previous[eid], current[eid]):
            require(phase['stt_review_state'] == 'reviewed', 'Previously reviewed ST record became stale')
            require(all(phase['stt_report_eligibility'].get(k) for k in ('table', 'text', 'strip')), 'ST reporting eligibility lost')
        exact(previous[eid]['stt_event_evidence'], current[eid]['stt_event_evidence'], 'Original ST measurement evidence changed')
    require(before['stt']['analysis']['algorithm_version']=='stt-screening-0.4.0-comprehensive-independent', 'Old21 screening algorithm was not original0.4')
    require(after['stt']['analysis']['algorithm_version']=='stt-screening-0.5.0-morphology-qualified', 'Current22 screening algorithm was not actual0.5')
    for key in ('trends','quality','sample_rate_hz','units','unit_label','measurement_protocol'):
        exact(before['stt']['analysis'].get(key),after['stt']['analysis'].get(key),'Screening refinement changed original measurement: '+key)
    all_previous={e['event_id']:e for e in before.get('all_ST_events',before['events'])['items']}
    all_current={e['event_id']:e for e in after.get('all_ST_events',after['events'])['items']}
    stale_before={k:v for k,v in all_previous.items() if v.get('category')=='ST' and v.get('stt_review_state')=='stale'}
    require(all(k in all_current and all_current[k].get('stt_review_state')=='stale' for k in stale_before),'Originally stale ST records were revived')
    if 'report_sections' in before:
        exact(before['report_sections']['st_evaluation'],after['report_sections']['st_evaluation'],'Original signed screening presentation changed')
    return dict(status='passed', original_status=old['status'], upgraded_status=new['status'],
                retained_selected_figures=len(new['composition']['selected_events']),
                retained_qualified_STT=[u['event_id'] for u in uses],
                original_evidence_basis_retained=True, original_signature_retained_not_resigned=True,
                original_workflow_HRV_RR_retained=True,originally_stale_records_checked=len(stale_before),old_screening='0.4',new_screening='0.5')


def compare_database(before, after, package):
    require(before['recovery_epoch'] == after['recovery_epoch'], 'Workspace recovery epoch changed')
    left, right = before['tables'], after['tables']
    require(set(left) <= set(right), 'An existing workspace table disappeared')
    for name in ('annotations', 'stt_review_submissions', 'case_review', 'report_drafts', 'case_analysis_basis'):
        require(name in left and name in right, 'Expected physician data table missing: ' + name)
        exact(left[name], right[name], 'Original physician record, signature or approval table changed: ' + name)
    for name in set(left) - {'audit_log','analysis_implementation_compatibility'}:
        exact(left[name], right[name], 'Upgrade changed persisted clinical/workspace data: ' + name)
    audit0 = sorted(left['audit_log']['rows'], key=lambda r: r['id'])
    audit1 = sorted(right['audit_log']['rows'], key=lambda r: r['id'])
    exact(audit1[:len(audit0)], audit0, 'Original audit history changed')
    added = audit1[len(audit0):]
    require(any(r['action']=='analysis.screening_refinement_verified' for r in added), 'No explicit screening-refinement audit was written')
    certificates = right.get('analysis_implementation_compatibility', {}).get('rows', [])
    require(len(certificates)==1, 'Expected one immutable-workspace compatibility bridge')
    certificate = json.loads(certificates[0]['certificate'])
    original_basis = json.loads(left['case_analysis_basis']['rows'][0]['basis'])
    exact(certificate['reference_basis'], original_basis, 'Audit bridge is not bound to original physician evidence')
    require(certificate['policy_digest']==package['screening_policy_sha256'], 'Bridge is not bound to actual packaged policy')
    require(certificate['execution_engine_id']!=original_basis['engine_id'] and certificate['execution_basis']!=original_basis['digest'], 'Bridge does not identify a distinct executing build')
    require(certificate['stt_proofs'] and certificate['retained_stt_records'], 'No actual per-record ST numerical revalidation was recorded')
    require(not any(r['action'] == 'analysis.basis_changed' for r in added), 'Verified screening refinement invalidated authored review')
    require(certificate['schema']=='stt-screening-refinement-continuity-v1' and certificate['continuity_kind']=='stt_screening_refinement','Upgrade was falsely labelled performance-only')
    require(certificate['screening_transition']['from']=='stt-screening-0.4.0-comprehensive-independent' and certificate['screening_transition']['to']=='stt-screening-0.5.0-morphology-qualified','Wrong screening transition')
    snapshot=certificate.get('signed_report_snapshot')
    require(snapshot and snapshot['before_digest']==snapshot['after_digest'],'Signed report screening presentation was not preserved')
    return dict(status='passed', preserved_existing_tables=sorted(set(left)-{'audit_log'}),
                preserved_UUID_submissions=len(left['stt_review_submissions']['rows']),
                appended_tables=sorted(set(right)-set(left)), appended_audit_actions=[r['action'] for r in added],
                approved_report_signature_and_selection_preserved=True)


def compare_restart_database(before, after):
    """A read-only new22 restart cannot rewrite a clinical row or audit proof."""
    exact(before['recovery_epoch'],after['recovery_epoch'],'Read-only restart changed recovery epoch')
    left,right=before['tables'],after['tables']
    exact(sorted(left),sorted(right),'Read-only restart changed workspace tables')
    for name in left:
        if name=='analysis_implementation_compatibility':
            exact(left[name]['columns'],right[name]['columns'],'Read-only restart changed certificate schema')
            # Atomic storage still updates this registration timestamp while
            # retaining the independently audited numerical proof byte-for-byte.
            rows=lambda value:[{k:v for k,v in row.items() if k!='created_at'} for row in value['rows']]
            require(left[name]['rows'],'Read-only restart has no original persisted certificate')
            exact(rows(left[name]),rows(right[name]),'Read-only restart replaced, added or rewrote an original certificate')
        else:
            exact(left[name],right[name],'Read-only restart changed a persisted row or audit: '+name)
    return dict(status='passed',same_tables=len(left),all_clinical_rows_and_complete_audit_exact=True,
                original_certificate_payload_exact=True,
                excluded_nonclinical_registration_fields=['analysis_implementation_compatibility.created_at'])


def require_cached_restart(first, restarted):
    require(first.get('continuity_kind')==restarted.get('continuity_kind')=='stt_screening_refinement',
            'Native restart diagnostics do not identify screening refinement')
    require(first.get('full_verification_attempts',0)>=1,'First migration did not run its independent full verification')
    require(restarted.get('verified_certificate_reuses',0)>=1,'Cold restart did not reuse an independently audited exact certificate')
    require(restarted.get('full_verification_attempts')==0,'Cold restart recomputed the original full screening verification')
    return dict(status='passed',first_migration=first,cold_restart=restarted,
                first_migration_independently_verified=True,cold_restart_used_existing_proof_without_full_recomputation=True)


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
    await page.locator('[data-hrv-edit-reason]').fill('Windows22 mathematical screening protection')
    started = time.perf_counter()
    await page.locator('[data-hrv-edit-action="exclude"]').click()
    await page.locator('[data-hrv-edit-action="apply"]').wait_for(timeout=180000)
    preview = time.perf_counter()-started
    started = time.perf_counter()
    await page.locator('[data-hrv-edit-action="apply"]').click()
    await page.wait_for_function("()=>document.querySelector('.hrv-edit [data-hrv-edit-action=undo]:enabled')&&document.querySelector('[data-hrv-edit-exclusions]').textContent.includes('Windows22 mathematical screening protection')", timeout=180000)
    apply = time.perf_counter()-started
    saved = await get(page, case_id, 'hrv-review?window=0&analysis=edited')
    require(saved['hrv_revision']>before['hrv_revision'] and any(r.get('reason')=='Windows22 mathematical screening protection' for r in saved['document']['exclusions']), 'Actual HRV exclusion was not persisted')
    await page.locator('[data-hrv-edit-action="undo"]').click()
    await page.locator('[data-hrv-edit-action="apply"]').wait_for(timeout=180000)
    await page.locator('[data-hrv-edit-action="apply"]').click()
    await page.wait_for_function("()=>document.querySelector('.hrv-edit [data-hrv-edit-action=redo]:enabled')&&!document.querySelector('[data-hrv-edit-exclusions]').textContent.includes('Windows22 mathematical screening protection')", timeout=180000)
    restored = await get(page, case_id, 'hrv-review?window=0&analysis=edited')
    exact(before['document'], restored['document'], 'HRV undo did not restore the original saved document')
    require(restored['hrv_revision']>saved['hrv_revision'], 'HRV undo revision was not persisted')
    return dict(status='passed', preview_seconds=preview, saved_update_seconds=apply,
                original_hrv_revision=before['hrv_revision'],saved_hrv_revision=saved['hrv_revision'],restored_hrv_revision=restored['hrv_revision'],
                actual_exclusion_saved_and_undone=True,original_document_restored=True,
                STT_unsaved_navigation=dict(discarded_draft_via_visible_prompt=discarded_STT_draft,
                    saved_records_unchanged=True,navigation_writes=navigation_writes,current_page='trends'))


def pdf_content_identity(body):
    """Compare actual decoded content streams, ignoring only producer version text.

    PDF creation time and random document IDs live outside content streams.
    The actual software-version footer is allowed to identify its current producer.
    """
    import base64,zlib
    streams=[]
    for item in re.finditer(rb"stream\r?\n(.*?)(?:\r?\n)?endstream",body,re.S):
        header=body[body.rfind(b"<<",0,item.start()):item.start()]
        raw=item.group(1)
        if b"/ASCII85Decode" in header:raw=base64.a85decode(raw,adobe=True)
        if b"/FlateDecode" in header:raw=zlib.decompress(raw)
        for value in (APP,BASE_APP):raw=raw.replace(value.encode(),b"<actual-generator-version>")
        streams.append(sha256(raw).hexdigest())
    require(streams,"Actual PDF has no inspectable content streams")
    return dict(stream_count=len(streams),decoded_stream_sha256=streams,
                excluded_fields="PDF metadata IDs/timestamps; actual software-generator version text only")


async def candidate_transition_probe(page,case_id,before):
    """After immutable upgrade checks, test an old request refusal and author a new0.5 record."""
    from uuid import uuid4
    from scripts.verify_windows_ui15_upgrade import get
    previous=before['stt']['automatic_candidates']['items']
    require(previous,'Original21 fixture did not expose an old0.4 source candidate')
    await page.locator('.nav-item[data-page="stt"]').click()
    await page.wait_for_function("()=>state.currentPage==='stt'&&state.sttEvidence&&state.sttReview?.analysis&&sttWaveformIsCurrent()&&!state.sttSaving",timeout=180000)
    current=await get(page,case_id,'stt-review')
    require(current['analysis']['algorithm_version']=='stt-screening-0.5.0-morphology-qualified','New workbench did not use actual0.5')
    items=current['automatic_candidates']['items'];require(items,'Independent positive morphology fixture produced no0.5 candidate')
    require(not {c['id'] for c in previous}.intersection(c['id'] for c in items),'Old candidate IDs were silently treated as current')
    chosen=previous[0]
    scope={key:current[key] for key in ('case_id','analysis_basis','analysis_revision','beat_revision')}
    body=dict(sample_index=round(chosen['start_s']*200),lead=chosen['leads'][0],label='Mathematical stale0.4 request must be rejected',
              note='No physician claim; deliberate old candidate request',details=dict(kind='ST',reviewed=True,
              result_code=chosen['kind'],review_extent='whole',review_leads=chosen['leads'],
              end_sample=round(chosen['end_s']*200)-1,submission_id=str(uuid4()),review_scope=scope,
              stt_candidate_scope=scope,stt_candidate_id=chosen['id']))
    address=urlsplit(page.url);origin=address.scheme+'://'+address.netloc
    annotations=await get(page,case_id,'annotations');report=await get(page,case_id,'report')
    response=await page.request.post(origin+'/api/cases/'+case_id+'/annotations',data=body)
    require(response.status==409,'Old0.4 candidate submission was not rejected with409')
    exact(annotations['items'],(await get(page,case_id,'annotations'))['items'],'Rejected old candidate wrote a clinical record')
    after_reject=await get(page,case_id,'report')
    for key in ('status','version','review_revision','analysis_provenance','composition'):
        exact(report[key],after_reject[key],'Rejected old candidate changed signed report: '+key)
    new=next(c for c in items if c['duration_s']>=60)
    await page.locator('[data-stt-row-kind="candidate"][data-stt-row-id="'+new['id']+'"]').click()
    await page.wait_for_function("()=>state.sttEvidence&&sttWaveformIsCurrent()&&!state.sttSaving",timeout=180000)
    await page.locator('#sttSignalChecked').check()
    await page.locator('#sttReviewNote').fill('Mathematical new0.5 candidate authored after preserved original report')
    async with page.expect_response(lambda r:urlsplit(r.url).path.endswith('/annotations') and r.request.method=='POST') as pending:
        await page.locator('#saveSttAnnotation').click()
    saved=await pending.value;require(saved.status==201,'Visible new0.5 candidate could not save')
    receipt=await saved.json()
    require(receipt['details']['stt_event_evidence']['algorithm_version']=='stt-screening-0.5.0-morphology-qualified',
            'New saved record falsely claimed old0.4 screening')
    await page.wait_for_function("()=>!state.sttSaving",timeout=180000)
    final=await get(page,case_id,'report')
    require(final['status']=='draft' and not final['reviewed_by'],'A real new authored record resurrected the old signed report')
    return dict(status='passed',old_candidate_http_status=response.status,rejected_write_left_original_report_unchanged=True,
                new_candidate_saved_from_visible_workbench=True,new_algorithm='stt-screening-0.5.0-morphology-qualified',
                report_after_real_new_authored_record='draft',new_record_id=receipt['id'])


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
                content_identity=pdf_content_identity(body),
                old_approved_report_exported_without_reapproval=True)


async def author_original_stale_control(page, case_id):
    """Create real stale0.4 records by a visible old21 heartbeat edit.

    The old controller has already saved six reviews and withdrawn their strips.
    Withdraw only the remaining output uses, edit an original normal beat, then
    save a fresh0.4 candidate for the original physician approval. Both stale and
    qualified records must consequently coexist before the upgrade.
    """
    from scripts.verify_windows_ui15_upgrade import get
    ready="()=>state.currentPage==='report'&&!state.reportDirty&&!state.reportSaving&&!state.reportViewLoading&&!state.reportEvidenceLoading"
    await page.locator('.nav-item[data-page="report"]').click()
    await page.wait_for_function(ready, timeout=180000)
    await page.locator('#reportV2Nav [data-category="ST"]').click()
    await page.wait_for_function(ready, timeout=180000)
    report=await get(page,case_id,'report')
    for use in report['composition'].get('stt_report_use',[]):
        if not any(use.get(p) for p in ('table','text','strip')):
            continue
        await page.locator('tr[data-report-event-id="'+use['event_id']+'"] [data-locate]').click()
        await page.locator('[data-stt-active-use="table"]').wait_for()
        for purpose in ('strip','table','text'):
            checkbox=page.locator('[data-stt-active-use="'+purpose+'"]')
            if await checkbox.is_checked():
                await checkbox.uncheck()
                await page.wait_for_function(ready, timeout=180000)
    editor=await get(page,case_id,'beat-editor')
    original_revision=editor['revision']
    await page.locator('.nav-item[data-page="edit"]').click()
    await page.locator('#occJump').wait_for(timeout=180000)
    await page.locator('#occJump').fill('30')
    await page.locator('#occGo').click()
    await page.locator('#editTemplateGallery .occurrence-tile .occurrence-wave svg').first.wait_for(timeout=180000)
    card=page.locator('#editTemplateGallery .occurrence-tile').filter(has=page.locator('.occurrence-wave svg')).first
    await card.click(button='right')
    await page.locator('#beatRelabelMenu .editor-primary [data-editor-code="S"]').click()
    await page.locator('#beatEditorDialog button[type="submit"]:enabled').wait_for(timeout=180000)
    async with page.expect_response(lambda r:urlsplit(r.url).path.endswith('/beat-editor') and r.request.method=='PUT') as pending:
        await page.locator('#beatEditorDialog button[type="submit"]').click()
    response=await pending.value
    require(response.ok,'Original21 visible heartbeat revision failed')
    await page.wait_for_function("()=>state.currentPage==='edit'&&!document.querySelector('#beatEditorDialog[open]')",timeout=180000)
    changed=await get(page,case_id,'beat-editor')
    require(changed['revision']==original_revision+1,'The stale control must contain one actual authored heartbeat revision')
    events=await get(page,case_id,'report-events?category=ST&stt_group=all&limit=2000')
    stale=[e['event_id'] for e in events['items'] if e.get('stt_review_state')=='stale']
    require(stale,'The old version did not create an actual stale ST negative control')
    await page.locator('#workflowNext').click()
    await page.locator('#workflowConfirmDialog[open]').wait_for(state='visible')
    await page.locator('#workflowConfirmed').check()
    await page.locator('#workflowNote').fill('Mathematical original21 heartbeat edit; obsolete ST controls must stay stale.')
    await page.locator('#workflowConfirmSubmit').click()
    await page.locator('#workflowConfirmDialog[open]').wait_for(state='detached')
    await page.locator('.nav-item[data-page="stt"]').click()
    await page.wait_for_function("()=>state.currentPage==='stt'&&state.sttEvidence&&sttWaveformIsCurrent()&&!state.sttSaving",timeout=180000)
    stt=await get(page,case_id,'stt-review')
    require(stt['analysis']['algorithm_version']=='stt-screening-0.4.0-comprehensive-independent','Stale control was not authored in original21')
    candidate=next(c for c in stt['automatic_candidates']['items'] if c['duration_s']>=60)
    await page.locator('[data-stt-row-kind="candidate"][data-stt-row-id="'+candidate['id']+'"]').click()
    await page.wait_for_function("()=>state.sttEvidence&&sttWaveformIsCurrent()&&!state.sttSaving",timeout=180000)
    await page.locator('#sttSignalChecked').check()
    await page.locator('#sttReviewNote').fill('Mathematical original21 current review; separate old stale records retained.')
    async with page.expect_response(lambda r:urlsplit(r.url).path.endswith('/annotations') and r.request.method=='POST') as pending:
        await page.locator('#saveSttAnnotation').click()
    response=await pending.value
    require(response.status==201,'Original21 current candidate could not save after the actual beat edit')
    saved=await response.json()
    require(saved['stt_review_receipt']['review_state']=='reviewed','Original21 fixture has no current qualified record for approval')
    await page.wait_for_function('()=>!state.sttSaving',timeout=180000)
    current=await get(page,case_id,'report-events?category=ST&stt_group=all&limit=2000')
    state_by_id={e['event_id']:e.get('stt_review_state') for e in current['items']}
    require(all(state_by_id.get(eid)=='stale' for eid in stale),'Saving a current review revived an original stale control')
    return dict(status='passed',authored_heartbeat_revision=changed['revision'],
                original_stale_event_ids=stale,current_qualified_event_id=saved['stt_review_receipt']['event_id'],
                visible_edit_and_save=True,patient_inputs_read=False)


async def author_nonempty_scopes(page, case_id):
    """Persist real old21 HRV and RR decisions through its visible controls."""
    from scripts.verify_windows_ui15_upgrade import get
    await page.locator('.nav-item[data-page="trends"]').click()
    await page.locator('[data-hrv-edit-block]').first.wait_for(timeout=180000)
    await page.locator('[data-hrv-edit-start]').fill('140')
    await page.locator('[data-hrv-edit-end]').fill('150')
    await page.locator('[data-hrv-edit-reason]').fill('Original21 mathematical authored exclusion retained by22')
    await page.locator('[data-hrv-edit-action="exclude"]').click()
    await page.locator('[data-hrv-edit-action="apply"]').wait_for(timeout=180000)
    await page.locator('[data-hrv-edit-action="apply"]').click()
    await page.wait_for_function("()=>document.querySelector('.hrv-edit [data-hrv-edit-action=undo]:enabled')&&document.querySelector('[data-hrv-edit-exclusions]').textContent.includes('Original21 mathematical authored exclusion retained by22')", timeout=180000)
    await page.locator('[data-hrv-edit-ack]').check()
    await page.locator('[data-hrv-edit-note]').fill('Original21 mathematical window acknowledgement retained by22')
    await page.locator('[data-hrv-edit-action="confirm"]').click()
    await page.wait_for_function("()=>document.querySelector('.hrv-edit[aria-busy=false] [data-hrv-edit-confirmation]')?.textContent.includes('已保存')", timeout=180000)
    hrv = await get(page, case_id, 'hrv-review?window=0&analysis=edited')
    require(hrv['document']['exclusions'] and hrv['hrv_revision']>0 and hrv['confirmation']['valid'],
            'Old21 did not actually persist and confirm a nonempty HRV exclusion')
    await page.evaluate("""async()=>{const b='/api/cases/'+state.caseId,ledger=await api(b+'/evidence-candidates'),e=(await api(b+'/report-rr-evidence')).event;
        await ECGReviewCandidates.choose({identity:ledger,item:{sample_index:e.sample_index,rr_ms:e.rr_ms,class_code:e.evidence_ref.terminal.class_code}});} """)
    caption = 'Original21 mathematical reviewed RR retained by22'
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
            'Old21 RR pair was not actually acknowledged with a saved presentation')
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


async def approve_original21(page, case_id):
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
    note = 'Original21 mathematical physician workflow baseline; retained through actual22 upgrade.'
    await page.locator('#conclusionEditor').fill(note)
    await page.locator('#conclusionEditor').press('Tab')
    await settled()
    await page.wait_for_function('note=>state.report.conclusion===note', arg=note)
    await page.locator('#approveReport').click()
    await page.wait_for_function("()=>state.report?.status==='reviewed'&&!state.reportSaving")
    report = await get(page, case_id, 'report')
    require(report['conclusion'] == note and len(report['composition']['selected_events']) >= 4,
            'Visible original21 baseline must contain real saved ST-T and AF figures')


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
    with tempfile.TemporaryDirectory(prefix='UI-saveflow-actual22-') as temporary:
        work = Path(temporary)
        new = unpack(args.software_archive, work / 'new')
        verify_content_manifest(new)
        old = None
        if args.base_software_archive:
            require(sha256(args.base_software_archive.read_bytes()).hexdigest() == BASE_P01_SHA, 'Original21 P01 ZIP bytes differ')
            old = unpack(args.base_software_archive, work / 'old')
            verify_content_manifest(old)
        result['package_identity'] = package = program_identity(new, old)
        exe = new / 'CardioInsightDoctorEval.exe'
        require(pe_is_x64(exe), 'Current22 is not an actual AMD64 PE')
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
                from scripts.verify_stt_comprehensive_ui import verify as old_stt_flow
                from scripts.verify_screening_quality_ui import verify as stt_flow
                from scripts.verify_af_multistrip_ui import verify as af_flow
                async def capture_current():
                    value = await capture(page, doctor_source.CASE_ID, get, after=True)
                    if args.nonempty_reviewed_scopes:
                        for key, endpoint in [('authored_HRV','hrv-review?window=0&analysis=edited'),
                                              ('authored_RR_candidates','evidence-candidates'),
                                              ('authored_RR_events','report-events?category=rr_interval&rr_source=manual&limit=1000')]:
                            value[key] = await get(page, doctor_source.CASE_ID, endpoint)
                    value['report_sections']=await get(page,doctor_source.CASE_ID,'report-sections')
                    value['all_ST_events']=await get(page,doctor_source.CASE_ID,'report-events?category=ST&stt_group=all&limit=2000')
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
                        source_kind='mathematical_synthetic', note='Actual Windows22 mathematical AF protection')
                    from scripts.verify_stt_report_buttons_ui import verify as buttons_flow
                    result['STT_report_buttons'] = await buttons_flow(page, doctor_source.CASE_ID, args.output.parent / 'STT-buttons-current')
                    from scripts.verify_ui_saveflow_ui import verify as saveflow
                    result['UI_saveflow'] = await saveflow(page, doctor_source.CASE_ID, args.output.parent / 'UI-saveflow-current')
                    result['HRV_performance'] = await verify_hrv(page, doctor_source.CASE_ID)
                    result['actual_processes'] = [dict(phase='fresh22', pid=running['pid'], birth=running['birth'])]
                    checks.extend(['actual22-PE-and-all-embedded-runtime-modules', 'system-Edge-and-bundled-Python',
                                   'current-comprehensive-STT-visible-flow', 'independent-AF-multistrip-protection',
                                   'retained-A4-preview-and-pending-save-STT-visible-controls',
                                   'actual22-STT-AF-incremental-save-delete-and-card-contextmenu'])
                else:
                    old_exe = old / 'CardioInsightDoctorEval.exe'
                    require(pe_is_x64(old_exe), 'Original21 is not an actual AMD64 PE')
                    active = old_exe
                    page = await begin(old_exe)
                    workspace = json.loads((home / 'catalog.json').read_text())['selected_workspace']
                    state0 = await live_state(home, workspace, old_exe)
                    module0 = await asyncio.to_thread(process_modules, state0['pid'], old_exe)
                    require(module0['python_dll_from_bundle'], 'Original21 did not load bundled Python')
                    result['original21_STT_baseline'] = await old_stt_flow(page, doctor_source.CASE_ID, args.output.parent / 'original21-STT')
                    result['original21_STT_stale_control']=await author_original_stale_control(page,doctor_source.CASE_ID)
                    result['original21_AF_baseline'] = await af_flow(page, doctor_source.CASE_ID, args.output.parent / 'original21-AF',
                        source_kind='mathematical_synthetic', note='Original21 mathematical baseline for actual22 upgrade')
                    if args.nonempty_reviewed_scopes:
                        result['old21_authored_nonempty_scopes'] = await author_nonempty_scopes(page, doctor_source.CASE_ID)
                    await approve_original21(page, doctor_source.CASE_ID)
                    before = await capture_current()
                    result['original21_formal_PDF']=await formal_pdf(page,doctor_source.CASE_ID)
                    if args.nonempty_reviewed_scopes:
                        compare_nonempty_scopes(before, before)
                        (args.output.parent / 'original21-nonempty-scopes.json').write_text(json.dumps(before,ensure_ascii=False,indent=2)+'\n')
                    await context.close()
                    context = None
                    await stop(old_exe, home)
                    database = home / 'workspaces' / workspace / 'data/cardioinsight.db'
                    database0 = database_state(database)
                    (args.output.parent / 'original21-before-report.json').write_text(json.dumps(before['report'], ensure_ascii=False, indent=2) + '\n')
                    after_mode = True
                    active = exe
                    first = datetime.now(timezone.utc)
                    migration_started=time.perf_counter()
                    context = await new_context()
                    page = await begin(exe, reuse=True)
                    state1 = await live_state(home, workspace, exe)
                    module1 = await asyncio.to_thread(process_modules, state1['pid'], exe)
                    require(module1['python_dll_from_bundle'], 'Actual22 did not load bundled Python')
                    require((state0['pid'], state0['birth']) != (state1['pid'], state1['birth']), 'Upgrade reused the old21 process')
                    require(json.loads((home / 'catalog.json').read_text())['selected_workspace'] == workspace, 'Upgrade changed workspace')
                    await page.locator('#openFirstCase').click()
                    await page.wait_for_function('id=>state.caseId===id&&!state.caseLoading', arg=doctor_source.CASE_ID)
                    await page.wait_for_function("()=>state.currentPage==='review'&&overviewWorkbench.waveformBasis()&&Object.keys(state.waveform?.leads||{}).join(',')==='II,V1,V5'")
                    result['first_migration_overview_seconds']=time.perf_counter()-migration_started
                    after = await capture_current()
                    result['first_migration_capture_seconds']=time.perf_counter()-migration_started
                    require(await page.evaluate("state.currentPage==='review'&&Object.keys(state.waveform?.leads||{}).join(',')==='II,V1,V5'"), 'Upgraded case did not open in overview with loaded three-lead ECG')
                    result['API_upgrade'] = compare_api(before, after, package)
                    require(result['API_upgrade']['originally_stale_records_checked']>0,'The native upgrade did not check any actual original stale ST record')
                    if args.nonempty_reviewed_scopes:
                        result['nonempty_scope_upgrade'] = compare_nonempty_scopes(before, after)
                        (args.output.parent / 'actual22-nonempty-scopes.json').write_text(json.dumps(after,ensure_ascii=False,indent=2)+'\n')
                    result['formal_PDF'] = await formal_pdf(page, doctor_source.CASE_ID)
                    exact(result['original21_formal_PDF']['content_identity'],result['formal_PDF']['content_identity'],'Original signed PDF presentation changed after screening refinement')
                    result['signed_PDF_content_streams_equal']=True
                    result['pdf_operations'] = 1
                    for _ in range(3):
                        exact(after, await capture_current(), 'Repeated new22 GET changed retained work')
                    address=urlsplit(page.url)
                    health=await page.request.get(address.scheme+'://'+address.netloc+'/api/health')
                    require(health.ok,'First migration health diagnostics unavailable')
                    health_value=await health.json()
                    require(health_value['version']==APP,'First migration health came from a different application')
                    initial_continuity=health_value['screening_continuity']
                    await context.close()
                    context = None
                    await stop(exe, home)
                    database_migrated=database_state(database)
                    restart_started=time.perf_counter()
                    context=await new_context()
                    page=await begin(exe,reuse=True)
                    restart_state=await live_state(home,workspace,exe)
                    require((restart_state['pid'],restart_state['birth'])!=(state1['pid'],state1['birth']),
                            'The cold-restart check reused the first migration process')
                    await page.locator('#openFirstCase').click()
                    await page.wait_for_function('id=>state.caseId===id&&!state.caseLoading',arg=doctor_source.CASE_ID)
                    await page.wait_for_function("()=>state.currentPage==='review'&&overviewWorkbench.waveformBasis()&&Object.keys(state.waveform?.leads||{}).join(',')==='II,V1,V5'")
                    restart_overview_seconds=time.perf_counter()-restart_started
                    reopened=await capture_current()
                    exact(after,reopened,'A true same-package cold restart changed the original signed report, records or scopes')
                    restart_seconds=time.perf_counter()-restart_started
                    address=urlsplit(page.url)
                    health=await page.request.get(address.scheme+'://'+address.netloc+'/api/health')
                    require(health.ok,'Cold restart health diagnostics unavailable')
                    health_value=await health.json()
                    require(health_value['version']==APP,'Cold restart health came from a different application')
                    restarted_continuity=health_value['screening_continuity']
                    result['actual_cold_restart']=require_cached_restart(initial_continuity,restarted_continuity)
                    result['actual_cold_restart'].update(overview_seconds=restart_overview_seconds,capture_complete_seconds=restart_seconds,same_exe=True,same_home=True,same_workspace=True,
                        same_source=True,default_page='overview',loaded_leads=['II','V1','V5'],original_capture_exact=True,
                        original_process=dict(pid=state1['pid'],birth=state1['birth']),
                        restarted_process=dict(pid=restart_state['pid'],birth=restart_state['birth']))
                    await context.close();context=None
                    await stop(exe,home)
                    last = datetime.now(timezone.utc)
                    database1 = database_state(database)
                    result['actual_cold_restart']['database']=compare_restart_database(database_migrated,database1)
                    result['database_upgrade'] = compare_database(database0, database1, package)
                    result['database_before'] = public_database(database0)
                    result['database_after'] = public_database(database1)
                    (args.output.parent / 'actual22-after-report.json').write_text(json.dumps(after['report'], ensure_ascii=False, indent=2) + '\n')
                    result['actual_processes'] = [dict(phase='original21', pid=state0['pid'], birth=state0['birth']),
                                                  dict(phase='fresh22-first-migration', pid=state1['pid'], birth=state1['birth']),
                                                  dict(phase='same22-actual-cold-restart',pid=restart_state['pid'],birth=restart_state['birth'])]
                    # Original immutable evidence was checked before this explicit authoring phase.
                    after_mode=False
                    context=await new_context()
                    page=await begin(exe,reuse=True)
                    await page.locator('#openFirstCase').click()
                    await page.wait_for_function('id=>state.caseId===id&&!state.caseLoading',arg=doctor_source.CASE_ID)
                    result['candidate_transition']=await candidate_transition_probe(page,doctor_source.CASE_ID,before)
                    await context.close();context=None
                    await stop(exe,home)
                    checks.extend(['exact-original21-P01-and-distinct-fresh22-PE', 'new-compiled-screening05-source-and-unchanged-measurement-input-identity',
                        'old21-visible-reviewed-STT-and-AF-baseline', 'same-source-home-workspace-and-bundled-Python',
                        'retained-annotations-UUIDs-curation-and-physician-conclusion',
                        'old-signature-and-reviewed-report-preserved-without-reapproval',
                        'actual-old21-heartbeat-edit-created-stale-records-not-revived-by22',
                        'old04-candidate-refused-with409-and-visible-new05-candidate-saved',
                        'three-read-only-GET-snapshots-idempotent-with-no-clinical-writes',
                        'actual-same-package-process-cold-restart-reuses-proof-with-zero-full-recomputation',
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
            'Authored nonempty scope retention requires an actual original21 upgrade')
    require(not args.output.exists(), 'Preserve original native attempts')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = dict(status='running', mode='actual-original21-to22' if args.base_software_archive else 'actual-fresh22-UI-saveflow',
                  checks=[], patient_inputs_read=False, clinical_accuracy_validated=False,
                  physical_hospital_Windows10_verified=False, pdf_operations=0)
    try:
        asyncio.run(run(args, result))
    except BaseException:
        result['status'] = 'failed'
        raise
    finally:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        print('WINDOWS_SCREENING_QUALITY_NATIVE_JSON=' + json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
