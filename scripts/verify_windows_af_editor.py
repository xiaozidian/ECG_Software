"""AF/AFL single-save candidate and report confirmation checks against the actual frozen native M01 workspace."""
import time


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
                await page.locator('#v2EventWave [data-af-browse="middle"]').click()
                await page.wait_for_function("lo=>Number(document.querySelector('#v2EventWave')?.dataset.afBrowseStart)>lo+30", arg=start)
                await page.locator('#v2EventWave [data-af-strip-duration]').select_option('7')
                await page.locator('#v2EventWave [data-af-use-view]').click()
                # Custom browsing alone is read-only in27. Move both actual
                # range handles by one200Hz sample to create a7s pending edit.
                await page.locator('#v2EventWave [data-range-drag=start]').press('ArrowRight')
                await page.locator('#v2EventWave [data-range-drag=end]').press('ArrowRight')
                await page.wait_for_function("id=>ECGReportRange.pending().some(d=>d.event?.event_id===id)", arg=event_id)
                chosen = await page.evaluate("id=>{const d=ECGReportRange.pending().find(d=>d.event?.event_id===id);return {start:d.a,end:d.b};}", event_id)
                assert chosen['start'] > start + 20 and chosen['end'] < end - 20
                assert abs(chosen['end'] - chosen['start'] - 7) < .001
                assert next(e for e in (await read())['document']['episodes'] if e['id'] == items[0]['id'])['status'] == 'pending'
                checks.append('AF-middle-range-pending-without-whole-confirmation')
                await page.locator('#v2EventNavigation [data-confirm-rhythm="active"]').click()
                decision = page.locator('#unsavedChangesDialog')
                await decision.wait_for(state='visible')
                assert '整段候选' in await decision.inner_text() and '本次图条' in await decision.inner_text()
                assert await page.evaluate("()=>state.currentPage") == 'report'
                async with page.expect_response(lambda response: '/rhythm-review' in response.url and response.request.method == 'PUT') as pending:
                    await decision.locator('[data-unsaved-save]').click()
                response = await pending.value
                assert response.ok
                successful_commits += 1
                saved = await response.json()
                confirmed_episode = next(e for e in saved['document']['episodes'] if e['id'] == items[0]['id'])
                assert confirmed_episode['status'] == 'confirmed'
                assert confirmed_episode['start_s'] == start and confirmed_episode['end_s'] == end
                await decision.wait_for(state='hidden', timeout=90000)
                await page.wait_for_function("()=>!state.reportSaving&&!state.reportDirty")
                report = await browser_json(page, '/api/cases/' + CASE_ID + '/report?analysis=edited')
                chosen_entries = [e for e in report['composition']['selected_events'] if e['event_id'] == event_id]
                assert len(chosen_entries) == 1
                assert abs(chosen_entries[0]['range_start_s'] - chosen['start']) < .001
                assert abs(chosen_entries[0]['range_end_s'] - chosen['end']) < .001
                checks.append('AF-confirmation-and-inclusion-stay-in-native-report')
                checks.append('explicit-AF-confirmation-keeps-whole-boundaries-and-middle-strip')
                await row.locator('[data-include]').uncheck()
                await page.wait_for_function("()=>!state.reportSaving&&!state.reportDirty")
                report = await browser_json(page, '/api/cases/' + CASE_ID + '/report?analysis=edited')
                assert not any(e['event_id'] == event_id for e in report['composition']['selected_events'])
                checks.append('native-report-uncheck-removes-AF-strip')
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
    finally:
        decision = page.locator('#unsavedChangesDialog')
        if await decision.is_visible() and await decision.locator('[data-unsaved-stay]').is_enabled():
            await decision.locator('[data-unsaved-stay]').click()
        cancel_range = page.locator('#v2EventWave [data-range-cancel]')
        if await cancel_range.is_visible() and await cancel_range.is_enabled():
            await cancel_range.click()
        await navigate(page, 'review')
        if not await page.locator('#ovAF').is_visible():
            await page.locator('[data-ov="af-open"]').click()
        await page.wait_for_function("()=>!!state.waveform&&document.querySelector('#ovAFCoverage [data-ov=\"af-coverage\"]')&&!document.querySelector('#ovAFCoverage [data-ov=\"af-coverage\"]').disabled")
        for _ in range(successful_commits):
            async with page.expect_response(lambda response: '/rhythm-review' in response.url and response.request.method == 'PUT') as pending:
                await page.locator('[data-ov="af-undo"]').click()
            response = await pending.value
            assert response.ok
            await page.wait_for_function("()=>!!state.waveform&&document.querySelector('#ovAFCoverage [data-ov=\"af-coverage\"]')&&!document.querySelector('#ovAFCoverage [data-ov=\"af-coverage\"]').disabled")
        assert [e['id'] for e in (await read())['document']['episodes']] == base_ids
        if original_viewport:
            await page.set_viewport_size(original_viewport)
    checks.append('native-AF-undo-restores-original-rhythm-document')
    return {'passed': len(checks), 'checks': checks, 'measurements': measurements,
            'scope': 'actual frozen executable and installed system Edge; generated mathematical M01 only',
            'patient_pdf_operations': 0, 'clinical_validation': False}
