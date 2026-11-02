"""AF/AFL pointer and save checks against the actual frozen native M01 workspace."""
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
        for kind, start, end in [('AF', 3598, 3608), ('AFL', 7200, 7210)]:
            await page.locator('[data-ov="af-add:' + kind + '"]').first.click()
            await page.locator('#ovEpisodeForm').wait_for(state='visible')
            assert await bounds() == {'start': None, 'end': None, 'kind': kind}
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
                async with page.expect_response(lambda response: '/rhythm-review' in response.url and response.request.method == 'PUT') as pending:
                    await page.locator('[data-ov="af-save:confirmed"]').click()
                response = await pending.value
                assert response.ok
                successful_commits += 1
                saved = await response.json()
                assert next(e for e in saved['document']['episodes'] if e['id'] == items[0]['id'])['status'] == 'confirmed'
                await page.wait_for_function("()=>{const b=document.querySelector('#ovEpisodeForm [data-ov=\"af-save:pending\"]');return !!state.waveform&&b&&!b.disabled;}")
                checks.append('explicit-AF-confirmation-saved-in-native-workspace')
        for width, height in [(1366, 768), (1440, 900), (1920, 1080)]:
            await page.set_viewport_size({'width': width, 'height': height})
            await page.evaluate('()=>scrollTo(0,0)')
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
