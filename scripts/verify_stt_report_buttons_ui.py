"""Visible ST-T report controls on a caller-owned mathematical workspace.

The caller first saves source-measured reviews using the existing comprehensive
doctor-flow helper. Only real UI actions below modify the application. API GETs
check persisted state; neither this helper nor its screenshots use patient data.
"""
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit
import asyncio
import json
import re


async def verify(page, case_id, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    address = urlsplit(page.url)
    origin = address.scheme + '://' + address.netloc
    checks = []

    async def read(endpoint):
        response = await page.request.get(origin + '/api/cases/' + case_id + '/' + endpoint)
        assert response.ok, (endpoint, response.status)
        return await response.json()

    async def ready():
        await page.wait_for_function("""() => state.currentPage==='report' && state.report &&
            !state.reportSaving && !state.reportDirty && !state.reportStale &&
            !state.reportViewLoading && !state.reportEvidenceLoading &&
            !state.sttReportAdding && !state.afReportAdding""", timeout=180000)
        await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')

    async def category(value):
        if not await page.locator('#reportV2Nav').is_visible():
            await page.locator('.nav-item[data-page="report"]').click()
            await ready()
        await page.locator('#reportV2Nav [data-category="' + value + '"]').click()
        await ready()

    async def preview(escape=False):
        before = await read('report')
        await page.locator('[data-paper-preview]').click()
        await page.locator('#rwPaperPreview[open] .rp-sheet').first.wait_for(timeout=180000)
        html = await page.locator('#rwPaperPreview .rp-pages').inner_html()
        assert 'rp-sheet' in html
        if escape:
            await page.keyboard.press('Escape')
        else:
            await page.locator('#rwPaperPreview>header button').click()
        await page.locator('#rwPaperPreview[open]').wait_for(state='detached')
        assert before == await read('report'), 'Settled A4 preview changed persisted report'
        return html

    async def output_control(key):
        details = page.locator('.rw-output-options')
        if await details.get_attribute('open') is None:
            await details.locator('>summary').click()
        control = page.locator('[data-report-page="' + key + '"]')
        group = control.locator('xpath=ancestor::details[@data-rw-page-group]')
        if await group.get_attribute('open') is None:
            await group.locator('>summary').click()
        return control

    async def page_use(key, value):
        control = await output_control(key)
        await control.set_checked(value)
        await ready()
        assert (key in (await read('report'))['composition']['included_pages']) == value

    await category('ST')
    events = await read('report-events?category=ST&stt_group=all&limit=1000')
    event = next(e for e in reversed(events['items']) if e.get('stt_review_state') == 'reviewed'
                 and all(e['stt_report_eligibility'].get(k) for k in ('table', 'text', 'strip')))
    event_id = event['event_id']

    async def select_record():
        await category('ST')
        await page.locator('tr[data-report-event-id="' + event_id + '"] [data-locate]').click()
        await page.wait_for_function('id=>document.querySelector("#v2EventWave")?.dataset.afEpisodeId===id', arg=event_id)
        await page.locator('#v2EventWave [data-af-browse="start"]').wait_for()
        await ready()

    async def use():
        return next((u for u in (await read('report'))['composition'].get('stt_report_use', [])
                     if u['event_id'] == event_id), {})

    async def picks():
        return [p for p in (await read('report'))['composition']['selected_events'] if p['event_id'] == event_id]

    async def toggle(key, value, listed=False):
        selector = ('tr[data-report-event-id="' + event_id + '"] [data-stt-use="' + key + '"]'
                    if listed else '[data-stt-active-use="' + key + '"]')
        await page.locator(selector).set_checked(value)
        await ready()
        assert bool((await use()).get(key)) == value

    await category('final')
    await preview()
    await output_control('st_trend')
    metric = page.locator('[aria-label="报告ST趋势指标"]')
    first = 'delta' if await metric.input_value() != 'delta' else 'st_level'
    await metric.select_option(first)
    await ready()
    assert (await read('report'))['composition']['stt_trend_metric'] == first
    checks.append('A4-close-button-preserves-live-ST-metric-handler-and-actual-save')
    await page_use('t_trend', True)
    await preview(escape=True)
    await page_use('t_trend', False)
    second = 'st_level' if first == 'delta' else 'delta'
    await metric.select_option(second)
    await ready()
    assert (await read('report'))['composition']['stt_trend_metric'] == second
    withdrawn = await preview()
    assert '十二导联 T 波幅度趋势' not in withdrawn
    checks.append('A4-Escape-preserves-live-page-toggles-and-withdrawn-T-page')
    for key in ('st_trend', 't_trend', 'st_events', 'event_strips'):
        await page_use(key, True)
    await select_record()
    for purpose in ('table', 'text'):
        await toggle(purpose, True)
        await toggle(purpose, False, listed=True)
        await toggle(purpose, True, listed=True)
    checks.append('actual-list-and-active-table-text-adopt-withdraw-readopt')

    # Delay a real browser PUT. The next checkbox must wait rather than reject
    # the doctor's visible intent; no direct API mutation is used to seed it.
    await toggle('strip', False)
    waited = {'count': 0}

    async def delay_put(route):
        assert urlsplit(route.request.url).hostname in ('localhost', '127.0.0.1', '::1')
        if route.request.method == 'PUT':
            waited['count'] += 1
            await asyncio.sleep(1.2)
        await route.continue_()

    # api() adds analysis=edited to browser report writes. Match that query as
    # well so the deliberately pending PUT is actually delayed in the native run.
    pattern = re.compile(r'/api/cases/' + re.escape(case_id) + r'/report(?:\?.*)?$')
    await page.route(pattern, delay_put)
    try:
        await page.locator('[data-stt-active-use="text"]').uncheck()
        await page.wait_for_function('()=>state.reportSaving===true')
        await page.locator('[data-stt-active-use="strip"]').check()
        await ready()
        assert (await use()).get('strip') and not (await use()).get('text')
        assert waited['count'] >= 1 and await picks()
    finally:
        await page.unroute(pattern, delay_put)
    await toggle('text', True)
    checks.append('actual-delayed-save-preserves-next-STT-checkbox-intent')
    await toggle('strip', False, listed=True)
    assert not await picks()
    await page.locator('[data-stt-include-recommended]').click()
    await ready()
    recommended = await picks()
    signature = lambda rows: sorted((p.get('strip_id'), p['range_start_s'], p['range_end_s']) for p in rows)
    assert 1 <= len(recommended) <= 3 and all(len(p['leads']) == 12 for p in recommended)
    await page.locator('[data-stt-include-recommended]').click()
    await ready()
    assert signature(await picks()) == signature(recommended)
    checks.append('actual-recommended-twelve-lead-adoption-is-idempotent')
    for role in ('start', 'middle', 'end'):
        old = await page.locator('#v2EventWave .rw-af-candidate-browse').element_handle()
        await page.locator('#v2EventWave [data-af-browse="' + role + '"]').click()
        await page.wait_for_function('el=>!el.isConnected', arg=old)
        await page.locator('#v2EventWave [data-af-browse="start"]').wait_for()
    checks.append('actual-STT-start-extreme-end-controls-remain-live')
    # Browsing recommendations opens a new, unadopted range. Reopen the exact
    # saved middle graph through its visible report control before withdrawal;
    # otherwise an already-null replacement key would miss the original bug.
    saved_middle = next(p for p in recommended if p.get('representative_role') == 'middle')
    saved_report = await read('report')
    saved_index = next(i for i, p in enumerate(saved_report['composition']['selected_events'])
                       if p['event_id'] == event_id and p.get('strip_id') == saved_middle['strip_id'])
    await category('strips')
    await page.locator('[data-back-event="' + str(saved_index) + '"]').click()
    await page.wait_for_function("""key => {
        const host=document.querySelector('#v2EventWave');
        return host?.dataset.afStripKey===key && host._afCurrentStrip?.().replaceKey===key;
    }""", arg=saved_middle['strip_id'])
    await ready()
    await page.locator('#v2EventWave [data-display-fit]').click()
    await page.locator('#v2EventWave [data-display-leads="12"]').click()
    await page.locator('#v2EventWave [data-display-factor="2"]').click()
    selected_view = await page.evaluate("""() => {
        const host=document.querySelector('#v2EventWave'), choice=host._afCurrentStrip();
        return {settings:choice.settings, replaceKey:choice.replaceKey??null, role:choice.role,
                button:host.querySelector('[data-af-include-current]').textContent,
                summary:host.querySelector('[data-af-strip-summary]').textContent,
                whole:host.querySelector('.rw-af-whole').textContent,
                display:host.querySelector('.report-range-editor')._rangeDisplayState()};
    }""")
    assert selected_view['replaceKey'] == saved_middle['strip_id'] and selected_view['replaceKey']
    assert selected_view['role'] == saved_middle['representative_role'] == 'middle'
    assert selected_view['button'] == '保存本图' and '已入报' in selected_view['summary']
    assert '已选 ' + str(len(recommended)) + ' 图' in selected_view['whole']
    assert selected_view['display'] == {'mode': 12, 'gain': 2}
    for field in ('range_start_s', 'range_end_s', 'duration_s', 'leads'):
        assert selected_view['settings'][field] == saved_middle[field], field
    await toggle('strip', False)
    assert not await picks()
    await page.locator('#v2EventWave [data-af-include-current]').wait_for(state='visible')
    await page.locator('#v2EventWave [data-af-strip-summary]').wait_for(state='visible')
    current_view = await page.evaluate("""() => {
        const host=document.querySelector('#v2EventWave'), choice=host._afCurrentStrip();
        return {settings:choice.settings, replaceKey:choice.replaceKey??null, role:choice.role,
                whole:host.querySelector('.rw-af-whole').textContent,
                display:host.querySelector('.report-range-editor')._rangeDisplayState()};
    }""")
    assert current_view['replaceKey'] is None, 'Withdrawn graph still exposes its deleted replacement key'
    assert current_view['role'] == selected_view['role'] == 'middle'
    assert '已选 0 图' in current_view['whole'], 'Withdrawn graph count did not refresh'
    for field in ('range_start_s', 'range_end_s', 'duration_s', 'leads'):
        assert current_view['settings'][field] == selected_view['settings'][field], field
    assert current_view['display'] == selected_view['display'], 'Cancellation changed display leads or gain'
    assert '入报本图' in await page.locator('[data-af-include-current]').inner_text()
    assert '尚未入报' in await page.locator('[data-af-strip-summary]').inner_text()
    # Do not navigate or click recommendations here: the next actual button
    # must adopt this same remaining waveform immediately after withdrawal.
    async with page.expect_response(lambda response:
            response.request.method == 'GET' and urlsplit(response.url).path.endswith('/report-strip')) as validation:
        await page.locator('[data-af-include-current]').click()
    direct_response = await validation.value
    assert direct_response.status == 200
    await page.wait_for_function("""id =>
        state.reportComposition.selected_events.some(p=>p.event_id===id) ||
        document.querySelector('#toastStack .toast.error')""", arg=event_id)
    await ready()
    readopted = await picks()
    assert len(readopted) == 1, 'Direct current-graph readoption failed after withdrawal'
    for field in ('range_start_s', 'range_end_s', 'duration_s', 'leads'):
        assert readopted[0][field] == selected_view['settings'][field], field
    assert readopted[0]['representative_role'] == selected_view['role'] == 'middle'
    assert '已选 1 图' in await page.locator('#v2EventWave .rw-af-whole').inner_text()
    assert '已入报' in await page.locator('[data-af-strip-summary]').inner_text()
    assert await page.locator('[data-af-include-current]').inner_text() == '保存本图'
    saved_navigation = await page.locator('#v2EventWave .rw-af-candidate-browse').element_handle()
    await page.locator('[data-af-include-current]').click()
    await page.wait_for_function('node=>!node.isConnected', arg=saved_navigation)
    await page.locator('#v2EventWave [data-af-include-current]').wait_for(state='visible')
    await ready()
    assert signature(await picks()) == signature(readopted), 'Repeated direct readoption duplicated its graph'
    assert not any('本张图条已变化' in text for text in await page.locator('.toast.error').all_text_contents())
    direct_reentry_evidence = dict(
        before_saved_middle=selected_view, after_whole_withdrawal=current_view,
        graph_count_after_withdrawal=0, graph_count_after_direct_readoption=1,
        actual_saved_graph_reopened_via_visible_back_event=True,
        actual_range_validation_HTTP_status=direct_response.status,
        no_navigation_between_withdrawal_and_readoption=True,
        saved_middle_print_range_leads_role_retained=True,
        display_mode12_gain2_retained_through_withdrawal=True)
    checks.append('withdraw-then-directly-readopt-same-live-graph-preserves-range-leads-display-and-no-stale-key')
    await toggle('strip', False)
    assert not await picks() and (await use()).get('table') and (await use()).get('text')
    await page.locator('[data-stt-include-recommended]').click()
    await ready()
    checks.append('withdrawing-all-STT-graphs-retains-table-and-text')
    await category('final')
    final_html = await preview()
    assert '十二导联 ST 分析' in final_html and '十二导联 T 波幅度趋势' in final_html
    assert final_html.count('data-stt-trend-lead=') >= 24
    assert 'data-stt-event-id="' + event_id + '"' in final_html
    assert 'data-strip-leads="I,II,III,aVR,aVL,aVF,V1,V2,V3,V4,V5,V6"' in final_html
    (output / 'mathematical-STT-final-preview.html').write_text(final_html, encoding='utf-8')
    checks.append('actual-A4-HTML-includes-specific-STT-event-both-trends-and-twelve-lead-graphs')
    before = await read('report')
    await page.reload()
    await page.locator('[data-open-case="' + case_id + '"]').click()
    await page.wait_for_function('id=>state.caseId===id&&!state.caseLoading', arg=case_id)
    assert (await read('report'))['composition'] == before['composition']
    await select_record()
    assert all([await page.locator('[data-stt-active-use="' + key + '"]').is_checked()
                for key in ('table', 'text', 'strip')])
    checks.append('actual-reload-retains-purpose-choices-and-graph-identifiers')
    await page.screenshot(path=str(output / 'mathematical-STT-buttons.png'))
    receipt = dict(status='passed', checks=checks, primary_checks=len(checks), event_id=event_id,
                   actual_UI_only_writes=True, mathematical_source_only=True, patient_inputs_read=False,
                   clinical_accuracy_validated=False, pdf_operations=0, delayed_report_PUTs=waited['count'],
                   saved_middle_direct_reentry=direct_reentry_evidence,
                   final_HTML_sha256=sha256(final_html.encode()).hexdigest())
    (output / 'STT-buttons-ui.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    return receipt
