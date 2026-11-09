"""Actual web doctor-flow acceptance on disposable, independently generated ECG.

The caller opens a local mathematical worklist or native Windows workspace.
All review actions below use visible controls. No patient or seeded approval.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import urlsplit


async def verify(page, case_id, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    checks, page_errors = [], []
    address=urlsplit(page.url);origin=address.scheme+'://'+address.netloc
    page.on('pageerror', lambda error: page_errors.append(str(error)))
    async def read(action):
        response = await page.request.get(origin + '/api/cases/' + case_id + '/' + action)
        assert response.ok, (action, response.status, await response.text())
        return await response.json()

    async def frames():
        await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')

    async def st_ready():
        await page.wait_for_function("()=>state.currentPage==='stt'&&state.sttReview?.analysis&&state.sttWaveform?.leads&&state.sttEvidence&&!state.sttSaving&&sttWaveformIsCurrent()")
        await frames()

    async def report_ready():
        await page.wait_for_function("()=>state.currentPage==='report'&&!state.reportSaving&&!state.reportDirty&&!state.reportViewLoading&&!state.reportEvidenceLoading&&!state.reportStale")
        await frames()

    async def wave_ready():
        await page.locator('#v2EventWave .report-range-editor svg').first.wait_for(state='visible')
        await page.locator('#v2EventWave [data-af-browse="start"]').wait_for(state='visible')
        await frames()

    await page.locator('[data-open-case="' + case_id + '"]').click()
    await page.wait_for_function('id=>state.caseId===id&&!!state.caseData', arg=case_id)
    await page.locator('.nav-item[data-page="stt"]').click()
    await st_ready()
    assert await page.locator('#workflowNext').is_hidden(), 'No global ST-T confirmation gate'
    initial = await read('stt-review')
    assert initial['analysis']['algorithm_version'] == 'stt-screening-0.4.0-comprehensive-independent'
    candidates = initial['automatic_candidates']['items']
    # Defined by the independent waveform generator; no hardcoded candidate IDs.
    targets = [('st_depression', 'I'), ('st_elevation', 'II'),
               ('t_persistent_inversion', 'V2'), ('t_low_flat', 'V3'),
               ('t_biphasic', 'V4'), ('t_wave_inversion', 'V5')]
    chosen = []
    for kind, lead in targets:
        matches = [c for c in candidates if c['kind'] == kind and c['leads'] == [lead]]
        assert matches, ('Independent source category was not detected', kind, lead)
        chosen.append(max(matches, key=lambda c: c['duration_s']))
    assert not any(c['kind'] == 't_biphasic' and c['leads'] in (['I'], ['V6']) for c in candidates), 'ST plateau must not become a false T lobe'
    checks.append('six-source-measured-ST-T-categories-and-ST-platform-negative-control')
    saved = []
    for i, candidate in enumerate(chosen):
        await page.locator('[data-stt-row-kind="candidate"][data-stt-row-id="' + candidate['id'] + '"]').click()
        await st_ready()
        await page.locator('#sttSignalChecked').check()
        await page.locator('#sttReviewNote').fill('Mathematical doctor-flow ' + candidate['kind'])
        async with page.expect_response(lambda r: urlsplit(r.url).path.endswith('/annotations') and r.request.method == 'POST') as waiting:
            await page.locator('#saveSttAnnotation').click()
        response = await waiting.value
        assert response.status == 201, await response.text()
        annotation = await response.json()
        await st_ready()
        receipt = annotation['stt_review_receipt']
        assert receipt['result_codes'] == [candidate['kind']], receipt
        assert receipt['review_state'] == 'reviewed' and receipt['report_eligibility']['table']
        assert receipt['range']['duration_s'] == candidate['duration_s']
        assert annotation['details']['stt_event_evidence']['kind'] == candidate['kind']
        saved.append(annotation)
    checks.append('visible-candidate-review-single-save-preserves-each-subtype-and-complete-duration')
    report = await read('report')
    assert not report['composition']['selected_events'], 'Saving review must not automatically adopt strips'
    assert not report['composition'].get('stt_report_use'), 'Saving review must not automatically adopt output uses'
    checks.append('saved-candidates-are-visible-without-automatic-report-adoption')
    await page.locator('[data-stt-report]').click()
    await report_ready()
    await wave_ready()
    eid = saved[-1]['stt_review_receipt']['event_id']
    assert await page.locator('tr[data-report-event-id="' + eid + '"]').count() == 1
    for purpose in ('table', 'text'):
        await page.locator('[data-stt-active-use="' + purpose + '"]').check()
        await report_ready()
    reps = await read('report-stt-representatives?event_id=' + eid + '&duration=7&leads=I,II,III,aVR,aVL,aVF,V1,V2,V3,V4,V5,V6')
    assert 1 <= len(reps['items']) <= 3
    for role in ('start', 'middle', 'end'):
        async with page.expect_response(lambda r: urlsplit(r.url).path.endswith('/report-strip')):
            await page.locator('[data-af-browse="' + role + '"]').click()
        await wave_ready()
        await page.wait_for_function("role=>document.querySelector('#v2EventWave')?._afCurrentStrip?.()?.role===role",arg=role)
    await page.locator('[data-stt-include-recommended]').click()
    await page.wait_for_function("()=>!state.sttReportAdding")
    await report_ready()
    report = await read('report')
    picks = [p for p in report['composition']['selected_events'] if p['event_id'] == eid]
    assert len(picks) == len(reps['items'])
    assert len({p['strip_id'] for p in picks}) == len(picks)
    assert all(len(p['leads']) == 12 for p in picks)
    assert {p['representative_role'] for p in picks} == {p['representative_role'] for p in reps['items']}
    assert all(p['duration_s'] < saved[-1]['stt_review_receipt']['range']['duration_s'] for p in picks)
    checks.append('actual-start-extreme-end-navigation-and-up-to-three-distinct-twelve-lead-strips')
    # Repeated recommendation is a range-level idempotent action.
    await page.locator('[data-stt-include-recommended]').click()
    await page.wait_for_function("()=>!state.sttReportAdding")
    await report_ready()
    assert len((await read('report'))['composition']['selected_events']) == len(picks)
    checks.append('repeated-recommendation-keeps-strip-identifiers-and-count')
    await page.locator('#reportV2Nav [data-category="strips"]').click()
    await report_ready()
    card=page.locator('.rw-strip[data-rw-key="'+picks[0]['strip_id']+'"]')
    await card.locator('[data-rw-tools]>summary').click()
    await page.get_by_role('menuitem',name='取消打印',exact=True).click()
    await report_ready()
    partial=await read('report')
    siblings=partial['composition']['selected_events']
    assert sum(p.get('print_enabled') is False for p in siblings)==1
    assert next(u for u in partial['composition']['stt_report_use'] if u['event_id']==eid)['strip']
    checks.append('disabling-one-strip-does-not-disable-printable-siblings')
    await page.locator('.rw-strip[data-rw-key="'+picks[0]['strip_id']+'"] [data-back-event]').click()
    await report_ready();await wave_ready()
    await page.locator('[data-stt-include-recommended]').click()
    await page.wait_for_function("()=>!state.sttReportAdding")
    await report_ready()
    restored=await read('report')
    assert len(restored['composition']['selected_events'])==len(picks)
    assert all(p.get('print_enabled') is not False for p in restored['composition']['selected_events'])
    assert {p['strip_id'] for p in restored['composition']['selected_events']}=={p['strip_id'] for p in picks}
    checks.append('explicit-readoption-restores-printing-without-duplicating-curated-strips')
    # Only the already-existing template-edit checkpoint is required globally.
    await page.locator('.nav-item[data-page="edit"]').click()
    await page.wait_for_function("()=>state.currentPage==='edit'")
    await page.locator('#workflowNext').click()
    await page.locator('#workflowConfirmDialog[open]').wait_for(state='visible')
    await page.locator('#workflowConfirmed').check()
    await page.locator('#workflowNote').fill('Mathematical engineering acceptance; no patient diagnosis.')
    await page.locator('#workflowConfirmSubmit').click()
    await page.locator('#workflowConfirmDialog[open]').wait_for(state='detached')
    await page.locator('.nav-item[data-page="report"]').click()
    await report_ready()
    await page.locator('#reportV2Nav [data-category="final"]').click()
    await report_ready()
    if not await page.locator('#conclusionEditor').is_visible():
        await page.locator('.rw-conclusion-disclosure>summary').click()
    await page.locator('#conclusionEditor').fill('Mathematical comprehensive ST-T report acceptance, not a clinical conclusion.')
    await page.locator('#conclusionEditor').press('Tab')
    await page.wait_for_function("()=>state.report?.conclusion==='Mathematical comprehensive ST-T report acceptance, not a clinical conclusion.'&&!state.reportDirty&&!state.reportSaving")
    await page.locator('#approveReport').click()
    await page.wait_for_function("()=>state.report?.status==='reviewed'")
    approved=await read('report')
    assert approved['status']=='reviewed' and len(approved['composition']['selected_events'])==len(picks)
    checks.append('visible-final-report-approval-uses-selected-records-without-global-STT-gate')
    await page.locator('#reportV2Nav [data-category="strips"]').click()
    await report_ready()
    await page.locator('.rw-strip[data-rw-key="'+picks[0]['strip_id']+'"] [data-back-event]').click()
    await report_ready();await wave_ready()
    await page.screenshot(path=str(output / 'stt-comprehensive-report-representatives.png'), full_page=True)
    await page.locator('[data-stt-active-use="strip"]').uncheck()
    await report_ready()
    report = await read('report')
    assert not report['composition']['selected_events']
    use = next(u for u in report['composition']['stt_report_use'] if u['event_id'] == eid)
    assert use['table'] and use['text'] and not use['strip']
    sections = await read('report-sections')
    assert any(r['event_id'] == eid and r['kind'] == 't_wave_inversion' for r in sections['t_events'])
    checks.append('withdrawing-all-parent-strips-retains-event-table-and-physician-text')
    before = await read('annotations')
    await page.reload()
    await page.locator('[data-open-case="' + case_id + '"]').click()
    await page.wait_for_function('id=>state.caseId===id', arg=case_id)
    after = await read('annotations')
    assert before == after
    reopened = await read('report')
    assert reopened['composition']['stt_report_use'] == report['composition']['stt_report_use']
    assert reopened['composition']['selected_events'] == []
    checks.append('page-reopen-keeps-reviews-subtypes-uses-and-clean-withdrawal')
    assert not page_errors, page_errors
    receipt = dict(status='passed', primary_checks=len(checks), checks=checks,
                   clinical_validation=False, patient_inputs_read=False,
                   source_categories=[dict(kind=c['kind'],leads=c['leads'],start_s=c['start_s'],end_s=c['end_s']) for c in chosen],
                   physician_record_ids=[a['stt_review_receipt']['event_id'] for a in saved],
                   initial_analysis_sha256=sha256(json.dumps(initial['analysis'],sort_keys=True,separators=(',',':')).encode()).hexdigest(),
                   page_errors=page_errors)
    (output / 'stt-comprehensive-ui.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    return receipt
