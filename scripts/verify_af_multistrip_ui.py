"""Visible AF candidate/figure acceptance on a caller-owned isolated workspace.

No request in this driver writes application state. Candidate creation, clinical
review, figure adoption and curation all use visible application controls. GETs
independently inspect persisted receipts. The caller owns the temporary service.
This engineering acceptance does not validate clinical diagnostic accuracy.
"""
from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from urllib.parse import quote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def _choose_range(document, total, start, duration):
    """Use a free interval; never silently edit an existing saved physician range."""
    occupied = sorted((max(0, e['start_s']), min(total, e['end_s']))
                      for e in document.get('episodes', []) if e.get('status') != 'excluded')
    gaps, cursor = [], 0.0
    for a, b in occupied:
        if a > cursor:
            gaps.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < total:
        gaps.append((cursor, total))
    requested = min(duration, total - start)
    for a, b in gaps:
        if a <= start and start + requested <= b and requested >= 30:
            return start, start + requested, None
    usable = [(a, b) for a, b in gaps if b - a >= 30]
    if usable:
        a, b = max(usable, key=lambda p: p[1] - p[0])
        a = min(a + 1, b - 30)
        return a, min(b, a + duration), None
    existing = [e for e in document.get('episodes', [])
                if e.get('status') != 'excluded' and e['end_s'] - e['start_s'] >= 30]
    if existing:
        e = max(existing, key=lambda p: p['end_s'] - p['start_s'])
        return e['start_s'], e['end_s'], e
    raise AssertionError('No independent 30-second interval or saved episode is available for this acceptance scope')


async def verify(page, case_id, output, *, episode_start_s=120, episode_duration_s=300,
                 note='工程流程验收，非医生诊断，仅隔离副本', finalize_report=False,
                 source_kind='isolated_source_copy'):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    checks, page_errors, writes = [], [], []
    address = urlsplit(page.url)
    origin = address.scheme + '://' + address.netloc
    marker = '工程流程验收（非医生诊断，仅隔离副本）：' + note
    page.on('pageerror', lambda error: page_errors.append(str(error)))

    def observe(request):
        if request.method in ('PUT', 'PATCH', 'DELETE', 'POST'):
            writes.append(dict(path=urlsplit(request.url).path, method=request.method))

    page.on('request', observe)

    async def read(action=''):
        response = await page.request.get(origin + '/api/cases/' + case_id + ('/' + action if action else ''))
        assert response.ok, (action, response.status, await response.text())
        return await response.json()

    def record(label):
        checks.append(label)
        (output / 'progress.json').write_text(json.dumps(dict(status='running', checks=checks, source_kind=source_kind), ensure_ascii=False, indent=2) + '\n')
        print('PASS ' + label, flush=True)

    async def frames():
        await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')

    async def report_ready():
        await page.wait_for_function("()=>state.currentPage==='report'&&!state.reportSaving&&!state.reportDirty&&!state.reportViewLoading&&!state.reportEvidenceLoading&&!state.reportStale")
        await frames()

    async def overview_ready():
        # The page/AF shell becomes visible before the asynchronous overview
        # transaction finishes. Its final status is written after the paired
        # rhythm and raw waveform have been checked and the editor rendered.
        await page.wait_for_function("""id=>{
            if(state.caseId!==id||state.currentPage!=='review'||typeof overviewWorkbench==='undefined')return false;
            const basis=overviewWorkbench.waveformBasis(),status=document.querySelector('#ovStatus');
            if(!basis||!status?.textContent.includes('条逐搏记录')||status.querySelector('[data-ov="reload"]'))return false;
            try{ECGAnalysisConsistency.assertSame(basis,state.caseData);ECGAnalysisConsistency.assertSame(basis,state.waveform);}
            catch(_){return false;}
            return !!state.waveform?.leads;
        }""", arg=case_id, timeout=180000)
        await frames()

    async def wave_ready():
        await page.locator('#v2EventWave .report-range-editor svg').first.wait_for(state='visible')
        await page.locator('#v2EventWave [data-af-strip-check="0"]').wait_for(state='visible')
        await page.locator('#v2EventWave [data-af-strip-check="0"]').wait_for(state='attached')
        await page.wait_for_function("()=>[...document.querySelectorAll('#v2EventWave [data-af-strip-check]')].length>=3&&[...document.querySelectorAll('#v2EventWave [data-af-strip-check]')].every(x=>!x.disabled)")
        await frames()

    def target_picks(report, event_id):
        return [p for p in report['composition']['selected_events'] if p['event_id'] == event_id]

    async def click_and_idle(selector):
        await page.locator(selector).click()
        await report_ready()
        await wave_ready()
        if 'data-af-strip-browse=' in selector:
            await page.wait_for_function("selector=>document.querySelector(selector)?.getAttribute('aria-current')==='true'", arg=selector)

    opener = page.locator('[data-open-case="' + case_id + '"]')
    current_case = await page.evaluate("()=>typeof state==='undefined'?null:state.caseId")
    if current_case != case_id:
        await opener.first.click()
    await page.wait_for_function('id=>state.caseId===id&&!!state.caseData', arg=case_id)
    original_stt = await read('stt-review')
    original_rhythm = await read('rhythm-review')
    case = await read()
    total = case['technical']['duration_seconds_raw']
    a, b, reused = _choose_range(original_rhythm['document'], total, episode_start_s, episode_duration_s)
    await page.locator('.nav-item[data-page="review"]').click()
    await overview_ready()
    await page.locator('[data-ov="af-open"]').click()
    await page.locator('#ovAF').wait_for(state='visible')
    await overview_ready()
    if reused is None:
        await page.locator('#ovAF .ov-af-heading [data-ov="af-add:AF"]').click()
        form = page.locator('#ovEpisodeForm')
        await form.wait_for(state='visible')
        clocks = await page.evaluate('({a,b})=>({a:ECGRhythmRangeEditor.boundaryClock(a,state.caseData.metadata.start_time),b:ECGRhythmRangeEditor.boundaryClock(b,state.caseData.metadata.start_time)})', dict(a=a, b=b))
        await form.locator('[name="startClock"]').fill(clocks['a'])
        await form.locator('[name="endClock"]').fill(clocks['b'])
        await form.locator('[name="note"]').fill(marker)
        await form.locator('[name="note"]').press('Tab')
        before_writes = len([w for w in writes if w['path'].endswith('/rhythm-review') and w['method'] == 'PUT'])
        async with page.expect_response(lambda r: urlsplit(r.url).path.endswith('/rhythm-review') and r.request.method == 'PUT') as pending:
            await form.locator('[data-ov="af-save:pending"]').click()
        response = await pending.value
        assert response.status == 200, await response.text()
        saved = await response.json()
        before_ids = {e['id'] for e in original_rhythm['document']['episodes']}
        added = [e for e in saved['document']['episodes'] if e['id'] not in before_ids and e.get('note') == marker]
        assert len(added) == 1 and added[0]['status'] == 'pending', added
        episode = added[0]
        assert len([w for w in writes if w['path'].endswith('/rhythm-review') and w['method'] == 'PUT']) == before_writes + 1
        await page.wait_for_function("()=>!document.querySelector('[data-ov=\"af-save:pending\"]')?.disabled&&document.querySelector('#ovEpisodeDraftHint')?.textContent.includes('已保存')")
        record('new-engineering-range-single-visible-save-creates-one-pending-candidate')
    else:
        episode = reused
        selector = '#ovEpisodeRows [data-ov="episode:' + quote(episode['id'], safe='') + '"]'
        for _ in range(100):
            if await page.locator(selector).count():
                break
            await page.locator('#ovEpisodePages button').last.click()
        await page.locator(selector).click()
        record('no-free-gap-existing-longest-episode-reused-without-rewriting-physician-note')
    await page.locator('#ovEpisodeForm [data-ov="af-report"]').click()
    await report_ready()
    await wave_ready()
    events = await read('report-events?category=AF&limit=1000')
    matches = [e for e in events['items'] if e.get('rhythm_episode_id') == episode['id']]
    assert len(matches) == 1
    event = matches[0]
    eid = event['event_id']
    expected = await read('report')
    before_rhythm = await read('rhythm-review')
    write_count = len(writes)
    current = page.locator('.rw-af-episode-row [data-locate][aria-current="true"]')
    await current.click()
    await report_ready()
    await wave_ready()
    assert not await page.locator('#unsavedChangesDialog[open]').count()
    assert await read('rhythm-review') == before_rhythm
    assert (await read('report'))['composition'] == expected['composition']
    assert not any(w['method'] in ('PUT', 'PATCH', 'DELETE') for w in writes[write_count:])
    record('candidate-row-click-only-browses-without-confirmation-or-report-write')
    if event.get('rhythm_status') != 'confirmed':
        before = await read('report')
        put_count = len([w for w in writes if w['path'].endswith('/rhythm-review') and w['method'] == 'PUT'])
        await page.locator('[data-af-confirm-whole]').click()
        await page.locator('#unsavedChangesDialog[open]').wait_for(state='visible')
        await page.locator('#unsavedChangesDialog [data-unsaved-save]').click()
        await page.locator('#unsavedChangesDialog[open]').wait_for(state='detached')
        await report_ready()
        await wave_ready()
        assert len([w for w in writes if w['path'].endswith('/rhythm-review') and w['method'] == 'PUT']) == put_count + 1
        after = await read('report')
        assert len(target_picks(after, eid)) == len(target_picks(before, eid)), 'Confirming an episode must not silently adopt an additional figure'
        assert not await page.locator('[data-af-confirm-whole]').count()
        record('whole-episode-explicit-once-confirmation-does-not-adopt-a-default-figure')
    else:
        record('existing-confirmed-episode-is-not-reconfirmed-or-rewritten')
    events = await read('report-events?category=AF&limit=1000')
    event = next(e for e in events['items'] if e.get('rhythm_episode_id') == episode['id'])
    eid = event['event_id']
    summary = (await read('report-sections'))['af_summary']
    for i in range(3):
        before = await read('report')
        before_rhythm = await read('rhythm-review')
        write_count = len(writes)
        await click_and_idle('[data-af-strip-browse="' + str(i) + '"]')
        assert (await read('report'))['composition'] == before['composition']
        assert await read('rhythm-review') == before_rhythm
        assert not any(w['method'] in ('PUT', 'PATCH', 'DELETE') for w in writes[write_count:])
    record('all-three-fixed-thumbnail-clicks-are-readonly-waveform-navigation')
    for i in range(3):
        await page.locator('[data-af-strip-check="' + str(i) + '"]').check()
        await report_ready()
        await wave_ready()
    three = target_picks(await read('report'), eid)
    assert len(three) == 3 and len({p['strip_id'] for p in three}) == 3
    assert all(len(p['leads']) == 12 for p in three)
    assert {p['representative_role'] for p in three} == {'start', 'middle', 'end'}
    await click_and_idle('[data-af-select-recommended]')
    assert target_picks(await read('report'), eid) == three
    record('three-distinct-twelve-lead-figures-and-repeat-recommendation-preserve-identities')
    slider = page.locator('[data-af-position]')
    box = await slider.bounding_box()
    assert box
    old_position = await page.evaluate("()=>{const s=document.querySelector('#v2EventWave')?._afCurrentStrip?.()?.settings;return JSON.stringify([s?.range_start_s,s?.range_end_s])}")
    await page.mouse.click(box['x'] + box['width'] * .3, box['y'] + box['height'] / 2)
    await page.wait_for_function("before=>{const s=document.querySelector('#v2EventWave')?._afCurrentStrip?.()?.settings;return JSON.stringify([s?.range_start_s,s?.range_end_s])!==before}", arg=old_position)
    await wave_ready()
    await page.locator('[data-af-add-custom]').click()
    await page.wait_for_function("()=>document.querySelectorAll('[data-af-strip-check]').length===4")
    assert target_picks(await read('report'), eid) == three, 'Adding an unselected custom thumbnail must not adopt it'
    await page.locator('[data-af-strip-check="3"]').check()
    await report_ready()
    await wave_ready()
    four = target_picks(await read('report'), eid)
    assert len(four) == 4 and len({p['strip_id'] for p in four}) == 4
    record('custom-waveform-position-creates-fourth-thumbnail-with-explicit-adoption')
    await page.locator('#reportV2Nav [data-category="strips"]').click()
    await report_ready()
    middle = next(p for p in four if p['representative_role'] == 'middle')
    card = page.locator('.rw-strip[data-rw-key="' + middle['strip_id'] + '"]')
    await card.locator('[data-rw-tools]>summary').click()
    await page.get_by_role('menuitem', name='编辑图条', exact=True).click()
    await page.locator('.rw-strip-editor-dialog [data-se-caption]').fill('工程验收保留图注（非医生诊断）')
    await page.locator('.rw-strip-editor-dialog [data-se-notes]').fill(marker)
    await page.locator('.rw-strip-editor-dialog button[type="submit"]').click()
    await page.locator('.rw-strip-editor-dialog[open]').wait_for(state='detached')
    await report_ready()
    four = target_picks(await read('report'), eid)
    await page.locator('.rw-strip[data-rw-key="' + middle['strip_id'] + '"] [data-back-event]').click()
    await report_ready()
    await wave_ready()
    await page.locator('[data-af-strip-check="1"]').uncheck()
    await report_ready()
    await wave_ready()
    remaining = target_picks(await read('report'), eid)
    assert len(remaining) == 3 and {p['strip_id'] for p in remaining} == {p['strip_id'] for p in four if p['strip_id'] != middle['strip_id']}
    assert remaining == [p for p in four if p['strip_id'] != middle['strip_id']], 'Unchecking one figure must not rewrite its siblings'
    await page.locator('[data-af-strip-check="1"]').check()
    await report_ready()
    await wave_ready()
    restored = target_picks(await read('report'), eid)
    assert {p['strip_id']: p for p in restored} == {p['strip_id']: p for p in four}
    record('precise-single-uncheck-and-readoption-preserve-siblings-identifiers-caption-and-notes')
    before_clear = await read('report')
    await click_and_idle('[data-af-clear-strips]')
    cleared = await read('report')
    assert not target_picks(cleared, eid)
    assert [p for p in cleared['composition']['selected_events'] if p['event_id'] != eid] == [p for p in before_clear['composition']['selected_events'] if p['event_id'] != eid]
    for key in ('stt_report_use', 'diagnosis_blocks'):
        assert cleared['composition'].get(key) == before_clear['composition'].get(key)
    assert cleared['conclusion'] == before_clear['conclusion']
    assert (await read('report-sections'))['af_summary'] == summary
    assert next(e for e in (await read('rhythm-review'))['document']['episodes'] if e['id'] == episode['id'])['status'] == 'confirmed'
    record('clearing-target-figures-keeps-confirmed-episode-statistics-and-other-table-text-uses')
    await click_and_idle('[data-af-select-recommended]')
    final = await read('report')
    picks = target_picks(final, eid)
    assert len(picks) == 3 and {p['strip_id'] for p in picks} == {p['strip_id'] for p in three}
    assert next(p for p in picks if p['strip_id'] == middle['strip_id'])['notes'] == marker
    await page.locator('#reportV2Nav [data-category="strips"]').click()
    await report_ready()
    first_card = page.locator('.rw-strip[data-rw-key="' + picks[0]['strip_id'] + '"]')
    group = first_card.locator('xpath=ancestor::section[contains(@class,"rw-af-report-group")]')
    assert await group.count() == 1 and await group.locator('.rw-strip').count() == 3
    numbers = await group.locator('[data-af-strip-number]').all_text_contents()
    assert all(any(re.search(r'图\s*' + str(i) + r'\s*/\s*3', text) for text in numbers) for i in range(1, 4))
    group_text = await group.locator('.rw-af-group-heading').inner_text()
    assert '3 图' in group_text
    assert len([e for e in (await read('report-events?category=AF&limit=1000'))['items'] if e['event_id'] == eid]) == 1
    record('report-groups-three-figures-under-one-episode-with-complete-time-and-i-of-N')
    await page.screenshot(path=str(output / 'af-multistrip-report.png'), full_page=True)
    pdf = None
    if finalize_report:
        await page.locator('.nav-item[data-page="edit"]').click()
        await page.wait_for_function("()=>state.currentPage==='edit'")
        await page.locator('#workflowNext').click()
        await page.locator('#workflowConfirmDialog[open]').wait_for(state='visible')
        await page.locator('#workflowConfirmed').check()
        await page.locator('#workflowNote').fill(marker)
        await page.locator('#workflowConfirmSubmit').click()
        await page.locator('#workflowConfirmDialog[open]').wait_for(state='detached')
        await page.locator('.nav-item[data-page="report"]').click()
        await report_ready()
        await page.locator('#reportV2Nav [data-category="final"]').click()
        await report_ready()
        if not await page.locator('#conclusionEditor').is_visible():
            await page.locator('.rw-conclusion-disclosure>summary').click()
        await page.locator('#conclusionEditor').fill(marker)
        await page.locator('#conclusionEditor').press('Tab')
        await report_ready()
        await page.locator('#approveReport').click()
        await page.wait_for_function("()=>state.report?.status==='reviewed'")
        assert (await read('report'))['status'] == 'reviewed'
        response = await page.request.get(origin + '/api/cases/' + case_id + '/report.pdf')
        assert response.ok, await response.text()
        raw = await response.body()
        destination = output / 'af-multistrip-ui-report.pdf'
        destination.write_bytes(raw)
        assert raw.startswith(b'%PDF')
        pdf = dict(path=str(destination), sha256=sha256(raw).hexdigest(), bytes=len(raw), group_text_verified=False)
        if shutil.which('pdftotext'):
            text = subprocess.check_output(['pdftotext', '-layout', str(destination), '-'], text=True)
            assert '房颤片段' in text or '房扑片段' in text
            assert all(re.search(r'图\s*' + str(i) + r'\s*/\s*3', text) for i in range(1, 4))
            pdf['group_text_verified'] = True
        record('visible-final-approval-and-native-PDF-retain-episode-group-and-all-three-figures')
    before_reload = await read('report')
    await page.reload()
    await page.locator('[data-open-case="' + case_id + '"]').click()
    await page.wait_for_function('id=>state.caseId===id&&!!state.caseData', arg=case_id)
    after_reload = await read('report')
    assert before_reload['composition'] == after_reload['composition']
    assert before_reload['status'] == after_reload['status']
    after_stt = await read('stt-review')
    for key in ('analysis', 'automatic_candidates'):
        assert original_stt[key] == after_stt[key], 'AF figure work must not alter independent ST/T ' + key
    record('reopen-preserves-target-figures-and-independent-source-ST-T-analysis-exactly')
    assert not page_errors, page_errors
    receipt = dict(status='passed', primary_checks=len(checks), checks=checks, clinical_accuracy_validated=False,
        source_kind=source_kind, patient_inputs_read=source_kind != 'mathematical_synthetic',
        created_new_episode=reused is None, episode_id=episode['id'], event_id=eid,
        basis_version=event['basis_version'], episode_start_s=event['start_sample'] / 200,
        episode_end_s=event['end_s'], target_strip_ids=[p['strip_id'] for p in picks], selected_strips=picks,
        frontend_group_heading=group_text, frontend_strip_numbers=numbers, target_event_count=1,
        af_summary=summary, stt_analysis_sha256=_digest(after_stt['analysis']),
        stt_candidates_sha256=_digest(after_stt['automatic_candidates']), note_sha256=sha256(marker.encode()).hexdigest(),
        finalization_status='approved_and_PDF_generated' if finalize_report else 'deferred_to_case_finalization',
        pdf=pdf, page_errors=page_errors)
    (output / 'af-multistrip-ui.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    return receipt


def run_math(output):
    """Optional standalone runner; source generation and server remain disposable."""
    from scripts.generate_stt_comprehensive_math import generate, CASE_ID
    from playwright.async_api import async_playwright
    from werkzeug.serving import make_server
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    chromium = os.environ['ECG_CHROME']
    with tempfile.TemporaryDirectory(prefix='af-multistrip-web-') as temporary:
        workspace = Path(temporary)
        fixture = generate(workspace / 'data')
        os.environ.update(ECG_DATA_ROOT=str(workspace / 'data'), ECG_APP_DATA_ROOT=str(workspace / 'runtime'),
            ECG_CONFIG_PATH=str(workspace / 'unused-config.json'), ECG_ALLOW_PHI='0')
        from app import create_app
        app = create_app(data_root=workspace / 'data', db_path=workspace / 'work.sqlite3')
        server = make_server('127.0.0.1', 0, app, threaded=True)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()

        async def execute():
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(executable_path=chromium, headless=True, chromium_sandbox=True)
                context = await browser.new_context(viewport=dict(width=1440, height=1000))
                page = await context.new_page()
                page.set_default_timeout(60000)
                try:
                    await page.goto('http://127.0.0.1:' + str(server.server_port) + '/')
                    result = await verify(page, CASE_ID, output, finalize_report=True, source_kind='mathematical_synthetic')
                    result.update(browser_version=browser.version, fixture=fixture)
                    return result
                except BaseException as error:
                    await page.screenshot(path=str(output / 'failure-mathematical-only.png'), full_page=True)
                    (output / 'failure.json').write_text(json.dumps(dict(error=str(error), mathematical_only=True), indent=2) + '\n')
                    raise
                finally:
                    await context.close()
                    await browser.close()
        try:
            result = asyncio.run(execute())
            (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)
            (output / 'service.json').write_text(json.dumps(dict(ephemeral=True, loopback_only=True,
                stopped=not worker.is_alive(), formal_workspace_touched=False), indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/af-multistrip-web')
    result = run_math(parser.parse_args().output)
    print(json.dumps({k: result[k] for k in ('status', 'primary_checks', 'clinical_accuracy_validated', 'patient_inputs_read')}))
