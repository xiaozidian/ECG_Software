"""Real browser controls on caller-owned mathematical native workspaces only.

Mutation is exclusively visible UI. GETs inspect persistence; instrumentation
observes DOM/requests and never seeds application state, diagnoses or receipts.
"""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

READ_POSTS = ('/event-waveforms', '/waveform-strips', '/waveform-density',
              '/scatter-selection', '/advanced-analysis', '/rr-review/locate',
              '/report-evidence/preview', '/hrv-review/preview', '/hrv-review/cancel')


def business_write(method, path):
    return method not in ('GET', 'HEAD', 'OPTIONS') and not any(path.endswith(s) for s in READ_POSTS)


def assert_observation(value, requests, kind, *, keep_form=False):
    """Fail closed on an empty/superseded surface or a broad analysis reload."""
    assert value['samples'] >= 2 and value['empty_frames'] == 0, value
    assert value['max_forms'] <= 1 and value['surface_connected'], value
    if keep_form:
        assert value['original_form_connected'], value
    if kind == 'stt':
        assert value['trend_node_connected'], value
    forbidden = ('/overview', '/stt-review', '/trend')
    assert not [r for r in requests if any(r['path'].endswith(x) for x in forbidden)], requests
    assert sum(r['method'] == 'PUT' and r['path'].endswith('/rhythm-review') for r in requests) == (kind == 'af'), requests


def assert_review_preserved(before, after):
    assert before['id'] == after['id']
    a, b = before['stt_review_receipt'], after['stt_review_receipt']
    assert b['record_version'] == a['record_version'] + 1
    for key in ('range', 'findings', 'result_codes', 'leads'):
        assert a[key] == b[key], key
    assert before['details']['physician_note'] == after['details']['physician_note']


async def _context(page, case_id):
    address = urlsplit(page.url)
    assert address.hostname in ('127.0.0.1', 'localhost', '::1')
    assert await page.evaluate('id=>state.caseId===id', case_id)
    origin = address.scheme + '://' + address.netloc

    async def read(action=''):
        response = await page.request.get(origin + '/api/cases/' + case_id + ('/' + action if action else ''))
        assert response.ok, (action, response.status)
        return await response.json()

    async def nav(where):
        await page.locator('.nav-item[data-page="' + where + '"]').click()
        await page.wait_for_function("where=>state.currentPage===where||!!document.querySelector('#unsavedChangesDialog[open]')", arg=where)
        assert not await page.locator('#unsavedChangesDialog[open]').count(), 'Unexpected unsaved-navigation guard; no draft is discarded by this harness'
        await page.wait_for_function('where=>state.currentPage===where', arg=where)

    async def st_ready():
        await page.wait_for_function("()=>state.currentPage==='stt'&&!state.sttSaving&&sttWaveformIsCurrent()", timeout=180000)

    async def report_ready():
        await page.wait_for_function("()=>state.currentPage==='report'&&state.report&&!state.reportDirty&&!state.reportSaving&&!state.reportStale&&!state.reportViewLoading&&!state.reportEvidenceLoading", timeout=180000)

    async def overview_ready():
        await page.wait_for_function("""()=>{
          const b=overviewWorkbench.waveformBasis();if(state.currentPage!=='review'||!b||overviewWorkbench.isSaving())return false;
          try{ECGAnalysisConsistency.assertSame(b,state.caseData);ECGAnalysisConsistency.assertSame(b,state.waveform);}catch(_){return false;}
          return !!state.waveform?.leads&&document.querySelector('#ovStatus')?.textContent.includes('条逐搏记录');
        }""", timeout=180000)
    return read, nav, st_ready, report_ready, overview_ready


async def _monitor(page, kind):
    await page.evaluate("""kind=>{
      const st=kind==='stt',surface=document.querySelector(st?'#sttWaveformCanvas':'#waveformCanvas'),
        form=document.querySelector(st?'#sttReviewForm':'#ovEpisodeForm'),trend=document.querySelector('#sttTrendRows .stt-trend-row');
      if(!surface||!form||st&&!trend)throw Error('Missing actual monitoring precondition');
      const value={samples:0,empty_frames:0,max_forms:0};
      const sample=()=>{value.samples++;value.max_forms=Math.max(value.max_forms,document.querySelectorAll(st?'#sttReviewForm':'#ovEpisodeForm').length);
        if(st){if(!state.sttWaveform?.leads||!state.sttReview?.analysis||!document.querySelector('#sttTrendRows .stt-trend-row'))value.empty_frames++;}
        else if(!state.waveform?.leads||!overviewWorkbench.waveformBasis()||!document.querySelector('#ovEpisodeRows')?.childElementCount)value.empty_frames++;};
      sample();const timer=setInterval(sample,40);window.__saveflowObservation={stop(){clearInterval(timer);sample();return {...value,surface_connected:surface.isConnected,original_form_connected:form.isConnected,trend_node_connected:!!trend?.isConnected};}};
    }""", kind)


async def verify(page, case_id, output):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    read, nav, st_ready, report_ready, overview_ready = await _context(page, case_id)
    requests, errors, checks, unexpected_dialogs = [], [], [], []
    def request(req): requests.append(dict(method=req.method, path=urlsplit(req.url).path))
    def error(e): errors.append(str(e))
    async def reject_dialog(dialog):
        unexpected_dialogs.append(dialog.message); await dialog.dismiss()
    page.on('request', request); page.on('pageerror', error); page.on('dialog', reject_dialog)
    result = dict(scope='actual native Edge UI over generated mathematics; not clinical accuracy', checks=checks)
    try:
        # Run clean candidate transitions before the deliberate later-draft race.
        # Never accept a confirm or pretend page navigation discards that draft.
        await nav('report'); await report_ready(); await nav('stt'); await st_ready()
        # Consecutive visible source candidates must not be mistaken for a dirty
        # draft after the preceding acknowledged target clears its bound inputs.
        candidates=await page.evaluate('()=>state.sttReview.automatic_candidates.items')
        pair=[next(c for c in candidates if c['kind']==kind and c['duration_s']>=60)
              for kind in ('st_depression','st_elevation')]
        continuous=[]
        for candidate in pair:
            assert not await page.evaluate('()=>sttReviewHasUnsavedNote()'), 'Previous acknowledged review retained a fictitious dirty baseline'
            await page.locator('[data-stt-row-kind="candidate"][data-stt-row-id="'+candidate['id']+'"]').click(); await st_ready()
            assert await page.evaluate('id=>state.sttSelectedCandidate?.item.id===id&&state.sttSelectedCandidate.automatic',candidate['id'])
            assert not unexpected_dialogs, unexpected_dialogs
            await page.locator('#sttReviewNote').fill('Windows19 consecutive mathematical candidate '+candidate['kind'])
            await page.locator('#sttSignalChecked').check()
            async with page.expect_response(lambda r:urlsplit(r.url).path.endswith('/annotations') and r.request.method=='POST') as waiting:
                await page.locator('#saveSttAnnotation').click()
            response=await waiting.value;assert response.status==201
            selected=await response.json();await st_ready();proof=selected['stt_review_receipt']
            assert proof['result_codes']==[candidate['kind']] and proof['leads']==candidate['leads']
            assert abs(proof['range']['start_s']-candidate['start_s'])<=.005 and abs(proof['range']['end_s']-candidate['end_s'])<=.005
            assert not await page.evaluate('()=>sttReviewHasUnsavedNote()'), 'Saved candidate bounds and clean baseline disagree'
            continuous.append(dict(event_id=proof['event_id'],kind=candidate['kind'],exact_source_range=True))
        result['continuous_STT_candidates']=continuous
        checks.append('two-consecutive-visible-STT-source-candidates-save-correct-decision-and-range-without-confirm')
        await page.locator('#sttNewRange').click(); await st_ready()
        await page.locator('#sttFinding').select_option('未见明确动态 ST-T 改变')
        await page.locator('#sttReviewNote').fill('Windows19 mathematical short no-change note; no clinical diagnosis')
        await page.locator('#sttSignalChecked').check()
        async with page.expect_response(lambda r: urlsplit(r.url).path.endswith('/annotations') and r.request.method == 'POST') as waiting:
            await page.locator('#saveSttAnnotation').click()
        response = await waiting.value; assert response.status == 201
        short = await response.json(); await st_ready(); receipt = short['stt_review_receipt']
        assert receipt['review_state']=='reviewed' and receipt['result_codes']==['no_change'] and receipt['range']['duration_s']<60
        assert not receipt['report_eligibility']['table'] and receipt['report_eligibility']['text'] and receipt['report_eligibility']['strip']
        await nav('report'); await report_ready(); await page.locator('#reportV2Nav [data-category="ST"]').click(); await report_ready()
        await page.locator('#v2STGroup').select_option('all'); await report_ready()
        row = page.locator('tr[data-report-event-id="annotation:' + str(short['id']) + '"]')
        assert await row.locator('[data-stt-use="table"]').is_disabled()
        assert await row.locator('[data-stt-use="text"]').is_enabled() and await row.locator('[data-stt-use="strip"]').is_enabled()
        assert '1分钟' in await row.locator('[data-stt-use-reason]').inner_text()
        no_write = len(requests); await row.locator('[data-stt-edit-record]').click(); await st_ready()
        assert await page.evaluate('id=>state.sttEditingRecord?.id===id', short['id'])
        assert not [r for r in requests[no_write:] if business_write(r['method'], r['path'])]
        result['fresh_legacy_boundary'] = 'Fresh mathematics uses a real GUI no-change note; historical stale records are checked only by verify_legacy after real18 upgrade.'
        checks.append('short-no-change-table-disabled-reason-and-exact-record-edit-entry-without-save')
        await nav('review'); await overview_ready(); await page.locator('[data-ov="af-open"]').click(); await overview_ready()
        original = await read('rhythm-review'); total = (await read())['technical']['duration_seconds_raw']
        from scripts.verify_af_multistrip_ui import _choose_range
        a,b,reused = _choose_range(original['document'], total, 600, 45)
        assert reused is None, 'Fresh mathematical acceptance requires an independent free interval'
        await page.locator('#ovAF .ov-af-heading [data-ov="af-add:AF"]').click()
        form=page.locator('#ovEpisodeForm'); await form.wait_for(state='visible')
        clocks=await page.evaluate('({a,b})=>({a:ECGRhythmRangeEditor.boundaryClock(a,state.caseData.metadata.start_time),b:ECGRhythmRangeEditor.boundaryClock(b,state.caseData.metadata.start_time)})',dict(a=a,b=b))
        await form.locator('[name="startClock"]').fill(clocks['a']); await form.locator('[name="endClock"]').fill(clocks['b'])
        marker='Windows19 incremental candidate; generated mathematics'; await form.locator('[name="note"]').fill(marker); await form.locator('[name="note"]').press('Tab')
        await _monitor(page,'af'); start=len(requests); begin=time.perf_counter()
        await form.locator('[data-ov="af-save:pending"]').click()
        await page.wait_for_function("()=>!overviewWorkbench.isSaving()&&document.querySelector('#ovEpisodeDraftHint')?.textContent.includes('已保存')",timeout=180000)
        await overview_ready(); observed=await page.evaluate('()=>window.__saveflowObservation.stop()'); assert_observation(observed,requests[start:],'af',keep_form=True)
        created=await read('rhythm-review'); ids={e['id'] for e in original['document']['episodes']}; added=[e for e in created['document']['episodes'] if e['id'] not in ids]
        assert len(added)==1 and added[0]['note']==marker and added[0]['status']=='pending'
        assert added[0]['kind']=='AF' and abs(added[0]['start_s']-a)<=.005 and abs(added[0]['end_s']-b)<=.005
        result['AF_create']=dict(elapsed_s=time.perf_counter()-begin,observation=observed,requests=requests[start:])
        checks.append('AF-visible-create-one-candidate-without-overview-reload-or-form-replacement')
        await form.locator('[data-ov="af-delete-current"]').click(); await page.locator('#ovDialog[open]').wait_for()
        await _monitor(page,'af'); start=len(requests); begin=time.perf_counter()
        await page.locator('#ovDialog button[type="submit"]').click(); await page.locator('#ovDialog[open]').wait_for(state='detached')
        await overview_ready(); observed=await page.evaluate('()=>window.__saveflowObservation.stop()'); assert_observation(observed,requests[start:],'af')
        deleted=await read('rhythm-review'); assert deleted['document']==original['document']
        assert deleted['revision']==original['revision']+2
        result['AF_delete']=dict(elapsed_s=time.perf_counter()-begin,observation=observed,requests=requests[start:])
        checks.append('AF-visible-delete-restores-original-episodes-without-broad-reload')
        await nav('report'); await report_ready(); await page.locator('#reportV2Nav [data-category="strips"]').click(); await report_ready()
        card=page.locator('.rw-strip[data-rw-key]').first; await card.wait_for(state='visible')
        before_menu=await read('report'); start=len(requests); menus=[]
        for mode in ('right','button','keyboard'):
            if mode=='right': await card.locator('.rw-mini-wave').click(button='right')
            elif mode=='button': await card.locator('[data-rw-tools]>summary').click()
            else: await card.focus(); await page.keyboard.press('Shift+F10')
            menu=page.locator('.rw-strip-contextmenu[popover]'); await menu.wait_for(state='visible')
            items=await menu.locator('[role="menuitem"]').evaluate_all('(nodes)=>nodes.map(n=>({label:n.textContent,disabled:n.disabled}))')
            assert len(items)==8; menus.append(items); await menu.locator('[data-context-close]').click()
        assert menus[0]==menus[1]==menus[2]
        await card.focus(); await page.keyboard.press('n'); await page.keyboard.press('v')
        assert not [r for r in requests[start:] if business_write(r['method'],r['path'])]
        assert await read('report')==before_menu
        result['card_context_menu']=dict(right_button_keyboard_exact=True,items=menus[0],writes=0)
        checks.append('saved-card-right-click-button-keyboard-exact-eight-items-and-N-V-do-not-write')
        await nav('review'); await overview_ready()
        if await page.locator('#ovAF').is_visible(): await page.locator('#ovAF [data-ov="af-close"]').click()
        await overview_ready(); start=len(requests)
        await page.locator('#waveformCanvas').click(button='right'); await page.locator('#beatRelabelMenu').wait_for(state='visible')
        assert not await page.locator('.rw-strip-contextmenu:visible').count()
        await page.keyboard.press('Escape')
        assert not [r for r in requests[start:] if business_write(r['method'],r['path'])]
        checks.append('outside-report-wave-keeps-beat-menu-routing-without-curation-or-write')
        before_rows = (await read('annotations'))['items']; before_report = await read('report')
        adopted = {s['event_id'] for s in before_report['composition']['selected_events']}
        current = [a for a in before_rows if a.get('stt_review_receipt', {}).get('review_state') == 'reviewed'
                   and a.get('details', {}).get('reviewed') is True]
        assert current, 'Caller must first create actual current mathematical ST-T reviews'
        target = next((a for a in current if 'annotation:' + str(a['id']) not in adopted), current[0])
        await nav('stt'); await st_ready()
        await page.locator('[data-stt-row-kind="record"][data-stt-row-id="' + str(target['id']) + '"]').click(); await st_ready()
        await page.locator('#sttSignalChecked').check()
        note = page.locator('#sttReviewNote'); original_note = await note.input_value()
        delayed = []
        async def delay(route):
            if route.request.method == 'PUT':
                delayed.append(route.request.url); await asyncio.sleep(1.2)
            await route.continue_()
        pattern = re.compile(r'/api/cases/' + re.escape(case_id) + r'/annotations/' + str(target['id']) + r'(?:\?.*)?$')
        await page.route(pattern, delay); await _monitor(page, 'stt'); start = len(requests); begin = time.perf_counter()
        try:
            await page.locator('#saveSttAnnotation').dblclick(delay=40)
            await page.wait_for_function('()=>!!state.sttSaving')
            assert await note.is_enabled(), 'Later draft input must remain available while saving'
            late = original_note + ' | Windows19 unsaved later draft; not submitted'
            await note.fill(late); await st_ready()
        finally:
            await page.unroute(pattern, delay)
        observed = await page.evaluate('()=>window.__saveflowObservation.stop()')
        actions = requests[start:]; assert_observation(observed, actions, 'stt', keep_form=True)
        assert len(delayed) == 1, delayed
        after_rows = (await read('annotations'))['items']; saved = next(a for a in after_rows if a['id'] == target['id'])
        assert_review_preserved(target, saved)
        assert await note.input_value() == late and await page.evaluate('()=>state.sttDraftDirty')
        assert {a['id']:a for a in before_rows if a['id'] != target['id']} == {a['id']:a for a in after_rows if a['id'] != target['id']}
        result['STT_incremental'] = dict(elapsed_s=time.perf_counter()-begin, observation=observed, requests=actions,
            actual_PUTs=len(delayed), record_version_advanced_once=True, submitted_decision_unchanged=True,
            later_draft_visible_not_saved=True)
        checks.append('STT-visible-double-click-one-PUT-retained-trend-form-wave-and-later-draft')
        assert await page.evaluate('()=>state.currentPage==="stt"&&state.sttDraftDirty')
        assert not errors,errors
        assert not unexpected_dialogs,unexpected_dialogs
        await page.screenshot(path=str(output/'native-ui-saveflow-final.png'),full_page=True)
        result.update(status='passed',primary_checks=len(checks),page_errors=errors,patient_inputs_read=False,clinical_validation=False)
        (output/'native-ui-saveflow.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n'); return result
    finally:
        page.remove_listener('request',request); page.remove_listener('pageerror',error); page.remove_listener('dialog',reject_dialog)


async def verify_legacy(page, case_id, output):
    """No writes: inspect real old18 receipts after the native18→19 upgrade."""
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    read,nav,st_ready,report_ready,_=await _context(page,case_id);requests=[]
    def request(req):requests.append(dict(method=req.method,path=urlsplit(req.url).path))
    page.on('request',request)
    try:
        initial=await read('annotations');before=await read('report')
        await nav('report');await report_ready();await page.locator('#reportV2Nav [data-category="ST"]').click();await report_ready()
        await page.locator('#v2STGroup').select_option('all');await report_ready()
        events=(await read('report-events?category=ST&stt_group=all&limit=1000'))['items']
        stale=[e for e in events if e.get('stt_review_state')=='stale'];assert stale,'Actual old18 signed records must remain stale after the changed native program identity'
        checks=[]
        for event in stale:
            row=page.locator('tr[data-report-event-id="'+event['event_id']+'"]')
            assert '依据已变化' in await row.locator('[data-stt-use-reason]').inner_text()
            controls=await row.locator('[data-stt-use]').evaluate_all('(nodes)=>nodes.map(n=>({purpose:n.dataset.sttUse,checked:n.checked,disabled:n.disabled}))')
            assert len(controls)==3 and all(not x['disabled'] if x['checked'] else x['disabled'] for x in controls)
            checks.append(dict(event_id=event['event_id'],unselected_purposes_disabled=True,selected_purposes_remain_withdrawable=True))
        await page.locator('tr[data-report-event-id="'+stale[0]['event_id']+'"] [data-stt-edit-record]').click();await st_ready()
        assert await page.evaluate('id=>String(state.sttEditingRecord?.id)===id',stale[0]['event_id'].removeprefix('annotation:'))
        await nav('report');await report_ready()
        assert await read('annotations')==initial
        assert (await read('report'))['composition']==before['composition']
        assert not [r for r in requests if business_write(r['method'],r['path'])]
        result=dict(status='passed',scope='real old18 mathematical receipts after actual native upgrade; read only',checks=checks,
                    exact_old_record_edit_entry=True,clinical_writes=0,no_resign_or_use_changes=True)
        (output/'native-ui-saveflow-legacy.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');return result
    finally:page.remove_listener('request',request)
