"""AF/AFL single-save candidate and report confirmation checks against the actual frozen native M01 workspace."""
import time
import json
import traceback


def verify_undo_receipt(before, submitted, returned):
    """Actual outbound UI revision and persisted reply must describe one undo."""
    for key in ('case_id', 'analysis_basis', 'beat_revision', 'analysis_revision'):
        assert submitted[key] == before[key], ('submitted', key)
    assert submitted['revision'] == before['revision']
    assert submitted.get('operation') == 'undo'
    assert returned['case_id'] == before['case_id']
    assert returned['analysis_basis'] == before['analysis_basis']
    assert returned['beat_revision'] == before['beat_revision']
    assert returned['revision'] == before['revision'] + 1
    assert returned['analysis_revision'] == before['analysis_revision'] + 1
    operation = returned.get('last_operation') or {}
    assert operation.get('request_id') == submitted.get('request_id') and operation.get('request_id')
    assert operation.get('operation') == 'undo' and operation.get('revision') == returned['revision']


async def wait_current_af_review(page, expected, owner):
    # A retained waveform/coverage button can remain visible while the current
    # own-write projection is pending. It is not a completed-save receipt.
    assert expected['case_id'] == owner['caseId']
    await page.wait_for_function("""expected=>{
      if(state.caseId!==expected.caseId||state.caseRequestId!==expected.caseToken||state.workspaceEpoch!==expected.workspaceEpoch)return false;
      if(state.caseData?.case_id!==expected.caseId)return false;
      if(typeof overviewWorkbench==='undefined'||overviewWorkbench.isSaving())return false;
      const current=overviewWorkbench.waveformBasis();if(!current)return false;
      if(current.analysis_basis!==expected.analysis_basis||current.analysis_revision!==expected.analysis_revision)return false;
      if(state.caseData?.beat_editor_history?.revision!==expected.beat_revision)return false;
      try{ECGAnalysisConsistency.assertSame(current,state.caseData);ECGAnalysisConsistency.assertSame(current,state.waveform);}catch(_){return false;}
      const coverage=document.querySelector('#ovAFCoverage [data-ov="af-coverage"]');
      if(!state.waveform?.leads||!coverage||coverage.disabled||document.querySelector('#ovDialog')?.open)return false;
      const form=document.querySelector('#ovEpisodeForm');
      if(form&&(form.dataset.stale==='true'||[...form.querySelectorAll('[data-ov^="af-save:"]')].some(n=>!n.hidden&&n.disabled)))return false;
      return true;
    }""", arg={**owner, **{k: expected[k] for k in ('analysis_basis','analysis_revision','beat_revision')}})


async def verify_af_editor(page, screenshots):
    from verify_windows_doctor_browser import navigate, two_frames, browser_json, CASE_ID
    checks = []
    measurements = []
    original_viewport = page.viewport_size
    await navigate(page, 'review')
    if await page.locator('[data-ov="clear-range"]').is_visible():
        await page.locator('[data-ov="clear-range"]').click()
    if not await page.locator('#ovAF').is_visible():
        await page.locator('[data-ov="af-open"]').click()
    await page.locator('#ovAF').wait_for(state='visible')
    await page.wait_for_function("()=>state.caseId===" + repr(CASE_ID) + "&&!!state.waveform?.leads")

    async def read():
        return await browser_json(page, '/api/cases/' + CASE_ID + '/rhythm-review?analysis=edited')

    async def bounds():
        return await page.locator('#ovEpisodeForm').evaluate("""f=>({
            start:f.dataset.startS===''?null:Number(f.dataset.startS),
            end:f.dataset.endS===''?null:Number(f.dataset.endS),kind:f.elements.kind.value})""")

    async def clocks(start, end):
        values = await page.evaluate("""([start,end])=>[start,end].map(s=>
            ECGReviewTools.recordClock(state.caseData.metadata.start_time,s)||formatElapsedPrecise(s))""", [start, end])
        for field, value in zip(('startClock', 'endClock'), values):
            control = page.locator('#ovEpisodeForm [name=' + field + ']')
            if await control.get_attribute('type') == 'datetime-local':
                value = value.replace(' ', 'T')
            await control.fill(value)
            await control.press('Tab')
        await two_frames(page)
        current = await bounds()
        assert current['start'] == start and current['end'] == end

    base = await read()
    base_ids = [e['id'] for e in base['document']['episodes']]
    successful_commits = 0
    primary_failure = None
    cleanup_receipts = []
    cleanup_owner = await page.evaluate('()=>({caseId:state.caseId,caseToken:state.caseRequestId,workspaceEpoch:state.workspaceEpoch})')
    async def cleanup():
        decision = page.locator('#unsavedChangesDialog')
        if await decision.is_visible() and await decision.locator('[data-unsaved-stay]').is_enabled():
            await decision.locator('[data-unsaved-stay]').click()
        cancel_range = page.locator('#v2EventWave [data-range-cancel]')
        if await cancel_range.is_visible() and await cancel_range.is_enabled():
            await cancel_range.click()
        # Navigation protection is a real physician action. A stale/offscreen
        # draft may not expose a cancel button; use its actual discard dialog.
        if await page.evaluate("()=>state.currentPage==='report'&&ECGReportRange.pending().length>0"):
            await page.locator('.nav-item[data-page="review"]').click()
            await decision.wait_for(state='visible')
            await decision.locator('[data-unsaved-discard]').click()
            await decision.wait_for(state='hidden')
            await page.wait_for_function("()=>state.currentPage==='review'")
        else:
            await navigate(page, 'review')
        if not await page.locator('#ovAF').is_visible():
            await page.locator('[data-ov="af-open"]').click()
        await wait_current_af_review(page, await read(), cleanup_owner)
        for _ in range(successful_commits):
            before_undo = await read()
            await wait_current_af_review(page, before_undo, cleanup_owner)
            async with page.expect_response(lambda response: '/rhythm-review' in response.url and response.request.method == 'PUT') as pending:
                await page.locator('[data-ov="af-undo"]').click()
            response = await pending.value
            assert response.ok
            returned = await response.json()
            submitted = response.request.post_data_json
            verify_undo_receipt(before_undo, submitted, returned)
            await wait_current_af_review(page, returned, cleanup_owner)
            current = await read()
            for key in ('revision', 'analysis_basis', 'analysis_revision', 'beat_revision', 'document'):
                assert current[key] == returned[key], key
            cleanup_receipts.append(dict(submitted_revision=submitted['revision'],
                returned_revision=returned['revision'], analysis_revision=returned['analysis_revision'],
                operation='undo', actual_response_status=response.status, current_UI_identity_and_controls_ready=True))
        restored = (await read())['document']
        assert [e['id'] for e in restored['episodes']] == base_ids
        assert restored == base['document']
        if original_viewport:
            await page.set_viewport_size(original_viewport)

    try:
        for kind, start, end in [('AF', 3598, 3720), ('AFL', 7200, 7210)]:
            await page.locator('[data-ov="af-add:' + kind + '"]').first.click()
            await page.locator('#ovEpisodeForm').wait_for(state='visible')
            await page.wait_for_function("kind=>{const f=document.querySelector('#ovEpisodeForm');return f&&f.elements.kind.value===kind&&f.dataset.startS===''&&f.dataset.endS==='';}", arg=kind)
            assert await bounds() == {'start': None, 'end': None, 'kind': kind}
            assert await page.locator('[data-ov="af-save:confirmed"]').count() == 0
            assert await page.locator('[data-ov="af-save:excluded"]').count() == 0
            checks.append(kind + '-new-boundaries-empty')
            await clocks(start, end)
            await page.locator('[data-ov="af-boundary-home"]').click()
            await page.wait_for_function("t=>state.waveform&&state.waveform.start_s<=t&&state.waveform.start_s+state.waveform.duration_s>t", arg=start)
            assert (await bounds())['start'] == start
            await page.locator('[data-ov="af-boundary-tail"]').click()
            await page.wait_for_function("t=>state.waveform&&state.waveform.start_s<t&&state.waveform.start_s+state.waveform.duration_s>=t", arg=end)
            checks.append(kind + '-clock-input-and-boundary-navigation')
            await page.locator('#ovEpisodeForm [name=note]').fill('Native mathematical AF editor acceptance ' + kind)
            before = await browser_json(page, '/api/cases/' + CASE_ID + '/report?analysis=edited')
            started = time.perf_counter()
            async with page.expect_response(lambda response: '/rhythm-review' in response.url and response.request.method == 'PUT') as pending:
                await page.locator('[data-ov="af-save:pending"]').click()
            response = await pending.value
            assert response.ok
            successful_commits += 1
            saved = await response.json()
            items = [e for e in saved['document']['episodes'] if e.get('note') == 'Native mathematical AF editor acceptance ' + kind]
            assert len(items) == 1 and items[0]['kind'] == kind and items[0]['status'] == 'pending'
            await page.wait_for_function("()=>{const b=document.querySelector('#ovEpisodeForm [data-ov=\"af-save:pending\"]');return !document.querySelector('#ovDialog').open&&!!state.waveform&&document.querySelectorAll('#ovEpisodeRows [data-ov^=\"episode:\"]').length>0&&b&&!b.disabled;}")
            after = await browser_json(page, '/api/cases/' + CASE_ID + '/report?analysis=edited')
            assert after['composition']['selected_events'] == before['composition']['selected_events']
            measurements.append({'operation': kind + '-save-candidate', 'visible_ready_seconds': round(time.perf_counter() - started, 4)})
            checks.append(kind + '-native-save-acknowledged-without-report-inclusion')
            if kind == 'AF':
                before_bounds = await bounds()
                await page.locator('#waveformCanvas').dblclick(position={'x': 300, 'y': 80})
                await page.wait_for_function('()=>state.waveformExpanded')
                await page.keyboard.press('Escape')
                await page.wait_for_function('()=>!state.waveformExpanded')
                assert await bounds() == before_bounds
                checks.append('three-twelve-return-preserves-AF-boundaries')
                await page.locator('[data-ov="af-report"]').click()
                await page.wait_for_function("()=>state.currentPage==='report'&&state.reportDisplayedCategory==='AF'&&!state.reportViewLoading&&!state.reportEvidenceLoading")
                event_id = 'annotation:af:' + items[0]['id']
                row = page.locator('tr[data-report-event-id="' + event_id + '"]')
                await row.locator('td').last.click()
                await page.wait_for_function("id=>document.querySelector('#v2EventWave .report-range-editor')?._rangeEventId===id", arg=event_id)
                before_confirmation = await read()
                assert next(e for e in before_confirmation['document']['episodes'] if e['id'] == items[0]['id'])['status'] == 'pending'
                assert await page.locator('#unsavedChangesDialog').count() == 0
                viewed_report = await browser_json(page, '/api/cases/' + CASE_ID + '/report?analysis=edited')
                assert not any(e['event_id'] == event_id for e in viewed_report['composition']['selected_events'])
                checks.append('AF-viewing-row-does-not-confirm-or-include')
                async def middle_pending_range():
                    middle = page.locator('#v2EventWave [data-af-strip-browse="1"]')
                    await middle.wait_for(state='visible')
                    await page.wait_for_function("()=>[...document.querySelectorAll('#v2EventWave [data-af-strip-check]')].length===3&&[...document.querySelectorAll('#v2EventWave [data-af-strip-check]')].every(n=>!n.disabled)")
                    await middle.click()
                    await page.wait_for_function("lo=>{const t=document.querySelector('#v2EventWave'),c=t?._afCurrentStrip?.();return Number(t?.dataset.afBrowseStart)>lo+30&&c?.role==='middle'&&t.dataset.afStripKey===c.draftKey&&!!t.querySelector('.report-range-stage')&&t.querySelector('[data-af-strip-browse=\"1\"]')?.getAttribute('aria-current')==='true';}", arg=start)
                    current = await page.evaluate("()=>document.querySelector('#v2EventWave')._afCurrentStrip().settings")
                    assert abs(current['duration_s'] - 7) < .001
                    await page.locator('#v2EventWave [data-range-drag=start]').press('ArrowRight')
                    await page.locator('#v2EventWave [data-range-drag=end]').press('ArrowRight')
                    await page.wait_for_function("id=>{const t=document.querySelector('#v2EventWave');return ECGReportRange.pending().some(d=>d.event?.event_id===id&&d.stripKey===t.dataset.afStripKey&&d.isCurrent?.());}", arg=event_id)
                    chosen = await page.evaluate("id=>{const t=document.querySelector('#v2EventWave'),d=ECGReportRange.pending().find(d=>d.event?.event_id===id&&d.stripKey===t.dataset.afStripKey&&d.isCurrent?.()),c=t._afCurrentStrip();if(Math.abs(c.settings.range_start_s-d.a)>.001||Math.abs(c.settings.range_end_s-d.b)>.001)throw Error('Current AF choice does not match pending range');return {start:d.a,end:d.b};}", event_id)
                    assert chosen['start'] > start + 20 and chosen['end'] < end - 20
                    assert abs(chosen['end'] - chosen['start'] - 7) < .001
                    return chosen

                # Before any diagnosis confirmation, an edited figure is still
                # only a pending range. Leaving must warn while the physician is
                # on this page; staying preserves its exact source boundaries.
                guard_chosen = await middle_pending_range()
                assert next(e for e in (await read())['document']['episodes'] if e['id'] == items[0]['id'])['status'] == 'pending'
                assert not any(e['event_id'] == event_id for e in (await browser_json(page, '/api/cases/' + CASE_ID + '/report?analysis=edited'))['composition']['selected_events'])
                decision = page.locator('#unsavedChangesDialog[open]')
                await page.locator('.nav-item[data-page="review"]').click()
                await decision.wait_for(state='visible')
                assert await page.evaluate("()=>state.currentPage") == 'report'
                await decision.locator('[data-unsaved-stay]').click()
                await decision.wait_for(state='detached')
                assert await page.evaluate("()=>state.currentPage") == 'report'
                assert await page.evaluate("([id,a,b])=>ECGReportRange.pending().some(d=>d.event?.event_id===id&&Math.abs(d.a-a)<.001&&Math.abs(d.b-b)<.001)", [event_id,guard_chosen['start'],guard_chosen['end']])
                await page.locator('#v2EventWave [data-range-cancel]').click()
                await page.wait_for_function("id=>!ECGReportRange.pending().some(d=>d.event?.event_id===id)", arg=event_id)
                checks.append('AF-middle-range-pending-without-whole-confirmation-or-report-inclusion')
                checks.append('AF-pending-range-warns-before-page-leave-and-stay-preserves-exact-selection')

                # The visible31 flow confirms the complete episode first;
                # it never silently chooses a short figure on confirmation.
                await page.locator('[data-af-confirm-whole]').click()
                decision = page.locator('#unsavedChangesDialog[open]')
                await decision.wait_for(state='visible')
                await page.wait_for_function("duration=>{const d=document.querySelector('#unsavedChangesDialog[open]'),b=d?.querySelector('[data-unsaved-save]');return !!b&&!b.disabled&&d.textContent.includes('整段候选')&&d.textContent.includes(duration);}", arg=f'{end-start:.3f} 秒')
                assert '整段候选' in await decision.inner_text()
                async with page.expect_response(lambda response: '/rhythm-review' in response.url and response.request.method == 'PUT') as pending:
                    await decision.locator('[data-unsaved-save]').click()
                response = await pending.value
                assert response.ok
                successful_commits += 1
                saved = await response.json()
                confirmed_episode = next(e for e in saved['document']['episodes'] if e['id'] == items[0]['id'])
                assert confirmed_episode['status'] == 'confirmed'
                assert confirmed_episode['start_s'] == start and confirmed_episode['end_s'] == end
                await decision.wait_for(state='detached', timeout=90000)
                await page.wait_for_function("()=>!state.reportSaving&&!state.reportDirty&&!state.reportViewLoading&&!state.reportEvidenceLoading")
                report = await browser_json(page, '/api/cases/' + CASE_ID + '/report?analysis=edited')
                assert not any(e['event_id'] == event_id for e in report['composition']['selected_events'])
                checks.append('AF-explicit-whole-confirmation-keeps-boundaries-without-adopting-a-figure')

                chosen = await middle_pending_range()
                assert abs(chosen['start']-guard_chosen['start'])<.001 and abs(chosen['end']-guard_chosen['end'])<.001
                assert not any(e['event_id'] == event_id for e in (await browser_json(page, '/api/cases/' + CASE_ID + '/report?analysis=edited'))['composition']['selected_events'])
                checks.append('AF-visible-middle-thumbnail-is-readonly-and-seven-seconds')

                # Creating a visible custom thumbnail is still read-only;
                # only its separate checkbox explicitly adopts that figure.
                await page.locator('#v2EventWave [data-af-add-custom]').click()
                await page.wait_for_function("()=>document.querySelectorAll('#v2EventWave [data-af-strip-check]').length===4&&[...document.querySelectorAll('#v2EventWave [data-af-strip-check]')].every(n=>!n.disabled)")
                assert not any(e['event_id'] == event_id for e in (await browser_json(page, '/api/cases/' + CASE_ID + '/report?analysis=edited'))['composition']['selected_events'])
                await page.locator('#v2EventWave [data-af-strip-browse="3"]').click()
                await page.wait_for_function("()=>{const t=document.querySelector('#v2EventWave'),c=t?._afCurrentStrip?.();return c?.role==='custom'&&t.dataset.afStripKey===c.draftKey&&t.querySelector('[data-af-strip-browse=\"3\"]')?.getAttribute('aria-current')==='true';}")
                await page.locator('#v2EventWave [data-af-strip-check="3"]').check()
                await page.wait_for_function("()=>!state.reportSaving&&!state.reportDirty&&!state.afReportAdding&&!state.reportViewLoading&&!state.reportEvidenceLoading")
                report = await browser_json(page, '/api/cases/' + CASE_ID + '/report?analysis=edited')
                chosen_entries = [e for e in report['composition']['selected_events'] if e['event_id'] == event_id]
                assert len(chosen_entries) == 1 and len(chosen_entries[0]['leads']) == 12
                assert abs(chosen_entries[0]['range_start_s'] - chosen['start']) < .001, {'chosen':chosen,'entries':chosen_entries}
                assert abs(chosen_entries[0]['range_end_s'] - chosen['end']) < .001
                whole = next(e for e in (await read())['document']['episodes'] if e['id'] == items[0]['id'])
                assert whole['status'] == 'confirmed' and whole['start_s'] == start and whole['end_s'] == end
                checks.append('AF-custom-thumbnail-requires-explicit-checkbox-and-keeps-whole-boundaries')
                checks.append('AF-confirmation-and-inclusion-stay-in-native-report')
                await page.locator('#v2EventWave [data-af-strip-check="3"]').uncheck()
                await page.wait_for_function("()=>!state.reportSaving&&!state.reportDirty&&!state.afReportAdding")
                report = await browser_json(page, '/api/cases/' + CASE_ID + '/report?analysis=edited')
                assert not any(e['event_id'] == event_id for e in report['composition']['selected_events'])
                whole = next(e for e in (await read())['document']['episodes'] if e['id'] == items[0]['id'])
                assert whole['status'] == 'confirmed' and whole['start_s'] == start and whole['end_s'] == end
                checks.append('native-report-uncheck-removes-only-AF-figure-and-keeps-whole-confirmation')
                await navigate(page, 'review')
                if not await page.locator('#ovAF').is_visible():
                    await page.locator('[data-ov="af-open"]').click()
                await page.locator('#ovAF').wait_for(state='visible')
                await page.wait_for_function("()=>/逐搏记录/.test(document.querySelector('#ovStatus')?.textContent||'')&&!!state.waveform?.leads&&!document.querySelector('#ovAFCoverage [data-ov=\"af-coverage\"]').disabled")
        for width, height in [(1366, 768), (1440, 900), (1920, 1080)]:
            await page.set_viewport_size({'width': width, 'height': height})
            await page.evaluate('()=>scrollTo(0,0)')
            await page.wait_for_function("()=>{const c=document.querySelector('#waveformCanvas'),r=c?.getBoundingClientRect();return r&&r.bottom<=innerHeight+1&&r.height>=239;}")
            await two_frames(page)
            for side in ('episodes', 'scatter', 'coverage'):
                await page.locator('[data-ov="af-side:' + side + '"]').click()
                await two_frames(page)
                value = await page.locator('#waveformCanvas').evaluate("""c=>{const r=c.getBoundingClientRect();
                    return {top:r.top,bottom:r.bottom,height:r.height,width:document.documentElement.scrollWidth,
                        controls:[...document.querySelectorAll('#ovEpisodeForm [data-ov^="af-save:"]')].filter(n=>!n.hidden).every(n=>{const b=n.getBoundingClientRect();return b.top>=0&&b.bottom<=innerHeight})};}""")
                assert value['top'] >= 0 and value['bottom'] <= height + 1 and value['height'] >= 239
                assert value['width'] <= width + 1 and value['controls']
                checks.append('native-single-screen-' + str(width) + 'x' + str(height) + '-' + side)
            await page.locator('[data-ov="af-side:episodes"]').click()
            await page.screenshot(path=str(screenshots / ('mathematical-af-' + str(width) + 'x' + str(height) + '.png')))
    except Exception as error:
        primary_failure = error
        (screenshots / 'af-editor-primary-failure.json').write_text(json.dumps({
            'error': type(error).__name__ + ': ' + str(error),
            'traceback': traceback.format_exc(), 'checks': checks,
            'pending': await page.evaluate("()=>ECGReportRange.pending().map(d=>({id:d.event?.event_id,a:d.a,b:d.b,current:d.isCurrent?.()}))")
        }, ensure_ascii=False, indent=2), encoding='utf-8')
        await page.screenshot(path=str(screenshots / 'af-editor-primary-failure.png'))
        raise
    finally:
        try:
            await cleanup()
        except Exception as cleanup_error:
            if primary_failure is None:
                raise
            (screenshots / 'af-editor-cleanup-failure.json').write_text(json.dumps({
                'error': type(cleanup_error).__name__ + ': ' + str(cleanup_error),
                'primary_failure_retained': True
            }, ensure_ascii=False, indent=2), encoding='utf-8')
    checks.append('native-AF-undo-restores-original-rhythm-document')
    return {'passed': len(checks), 'checks': checks, 'measurements': measurements, 'cleanup_receipts': cleanup_receipts,
            'scope': 'actual frozen executable and installed system Edge; generated mathematical M01 only',
            'patient_pdf_operations': 0, 'clinical_validation': False}
