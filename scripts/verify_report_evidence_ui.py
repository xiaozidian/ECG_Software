"""Actual served report UI checks, reusable with native EXE or isolated local math.

All writes use visible UI controls. API evaluation below performs GET assertions.
A caller must label native Windows acceptance separately from local prechecks.
"""
from urllib.parse import urlencode, urlsplit
import asyncio
import time

LEADS=['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6']


async def verify_report_evidence_ui(page, case_id, expected_st, screenshots, progress=None):
    checks=progress.setdefault('checks',[]) if isinstance(progress,dict) else []
    pending=set();changed=time.monotonic();retired=[]
    def started(request):
        nonlocal changed
        if urlsplit(request.url).path.startswith('/api/'):
            pending.add(request);changed=time.monotonic()
    def finished(request):
        nonlocal changed
        pending.discard(request);changed=time.monotonic()
    def navigated(frame):
        nonlocal changed
        if frame!=page.main_frame:return
        for r in list(pending):
            path=urlsplit(r.url).path
            if r.method=='GET' or r.method=='POST' and path.rsplit('/',1)[-1] in ['waveform-density','event-waveforms']:
                pending.discard(r);retired.append({'method':r.method,'path':path,'reason':'old-document readonly request retired only at main-frame navigation'})
        changed=time.monotonic()
    page.on('request',started);page.on('requestfinished',finished);page.on('requestfailed',finished);page.on('framenavigated',navigated)

    async def get(action):
        return await page.evaluate("""async path=>{const r=await fetch(path,{cache:'no-store'});if(!r.ok)throw Error(path+': '+r.status);return r.json();}""",'/api/cases/'+case_id+'/'+action)
    async def frames(): await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
    async def settled():
        deadline=time.monotonic()+90
        while pending or time.monotonic()-changed<.35:
            assert time.monotonic()<deadline, 'API requests did not settle: '+str([(r.method,urlsplit(r.url).path) for r in pending])
            await asyncio.sleep(.04)
        await frames()
    async def saved():
        await settled()
        await page.wait_for_function("()=>!state.reportSaving&&!state.reportDirty&&!state.reportStale&&!state.reportViewLoading&&!state.reportEvidenceLoading")
        await frames()
    async def nav(target):
        await page.locator('.nav-item[data-page="'+target+'"]').click()
        await page.wait_for_function('p=>state.currentPage===p',arg=target)
        await settled()
    async def tab(key):
        await page.locator('#reportV2Nav [data-category="'+key+'"]').click()
        await page.wait_for_function("()=>!state.reportViewLoading&&!state.reportEvidenceLoading")
        await frames()
    async def locate(event):
        row=page.locator('tr[data-report-event-id="'+event['event_id']+'"]')
        await row.locator('[data-locate]').click()
        await page.wait_for_function("id=>document.querySelector('#v2EventWave .report-range-editor')?._rangeEventId===id",arg=event['event_id'])
        await settled();return row
    async def st_ready():
        await page.wait_for_function("()=>state.sttReview?.analysis&&state.sttWaveform?.leads&&state.sttEvidence&&!state.sttSaving&&sttWaveformIsCurrent()")
        await frames()
    def preserved(p):return {**{k:p.get(k) for k in ['strip_id','event_id','caption','leads','range_start_s','range_end_s','duration_s','representative_role']},'notes':p.get('notes','')}

    await nav('stt');await st_ready()
    st=await get('stt-review')
    assert st['analysis']['algorithm_version']=='stt-screening-0.2.0-continuous'
    assert st['analysis']['trends']==expected_st['analysis']['trends'],'Actual runtime ST minute evidence differs from native scalar fixture analysis'
    assert sorted(st['analysis']['trends']['leads'])==sorted(LEADS)
    for rows in st['analysis']['trends']['leads'].values():
        assert len(rows)==10 and rows[0]['start_s']==0 and rows[-1]['end_s']==600
        for p in rows:
            assert 0<p['duration_s']<=60 and p['valid_duration_s']<=p['duration_s']+.005
            if not p['eligible'] or p['axis_shift_suspected']:assert p['deviation_units'] is None and p['t_amplitude_units'] is None
    assert await page.locator('#sttTrendRows .stt-trend-row>strong').all_text_contents()==LEADS
    candidate=next(c for c in st['automatic_candidates']['items'] if c['kind']=='st_depression' and c['leads']==['II'] and c['continuous_target_s']>=60)
    expected=next(c for c in expected_st['automatic_candidates']['items'] if c['id']==candidate['id'])
    assert candidate==expected and candidate['duration_s']>60
    checks.append('actual-runtime-native-ST12lead-complete-minute-evidence-matches-generated-source')
    annotations=await get('annotations');report=await get('report')
    await page.locator('[data-stt-candidate-id="'+candidate['id']+'"]').click();await st_ready()
    assert await page.locator('#saveSttAnnotation').inner_text()=='保存整段复核'
    assert (await get('annotations'))==annotations and (await get('report'))['version']==report['version']
    await page.locator('#sttSignalChecked').check()
    await page.locator('#sttReviewNote').fill('Native report evidence mathematical whole candidate; not clinical validation.')
    await page.locator('#saveSttAnnotation').click()
    await page.wait_for_function('()=>!state.sttSaving&&state.sttLastSavedEvent&&!state.sttSelectedCandidate&&sttWaveformIsCurrent()')
    added=[a for a in (await get('annotations'))['items'] if not any(a['id']==old['id'] for old in annotations['items'])]
    assert len(added)==1;annotation=added[0];proof=annotation['details']['stt_event_evidence']
    assert annotation['sample_index']==round(candidate['start_s']*200)
    assert annotation['details']['end_sample']==round(candidate['end_s']*200)-1
    for k in ['start_s','end_s','duration_s','continuous_target_s','kind','leads']:assert proof[k]==candidate[k]
    assert proof['source']=='reviewed_automatic_candidate' and proof['units']=='source_device_units'
    assert (await get('report'))['composition']['selected_events']==report['composition']['selected_events']
    checks.append('actual-native-ST-UI-save-preserves-full-continuous-multiminute-range')
    await page.locator('#sttSelectedEvent [data-stt-report]').click();await saved();await tab('ST')
    event=next(e for e in (await get('report-events?category=ST'))['items'] if e['event_id']=='annotation:'+str(annotation['id']))
    await (await locate(event)).locator('[data-include]').check();await saved()
    picked=next(p for p in (await get('report'))['composition']['selected_events'] if p['event_id']==event['event_id'])
    assert picked['leads']==LEADS and picked['duration_s']==7
    strip=await get('report-strip?'+urlencode({'event_id':event['event_id'],'basis_version':event['basis_version'],'leads':','.join(LEADS),'duration':7}))
    assert strip['strip']['actual_duration_s']==7 and len(strip['waveform']['leads'])==12
    assert strip['strip']['start_s']<=candidate['peak_time_s']<strip['strip']['end_s']
    assert strip['stt_event_evidence']['duration_s']==candidate['duration_s']
    rendering=await page.evaluate("""async()=>{const id=state.caseId,r=await api('/api/cases/'+id+'/report'),evidence=await api('/api/cases/'+id+'/report-sections'),model={case:state.caseData,report:r,evidence};return {evidence,st:ECGReportSections.documents(model,['st_trend']),t:ECGReportSections.documents(model,['t_trend']),events:ECGReportSections.documents(model,['st_events']),empty:ECGReportSections.documents({...model,report:{...r,composition:{...r.composition,selected_events:[]}}},['st_events'])};}""")
    for key in ['st','t']:
        charts=[c for d in rendering[key] for c in d['charts']]
        assert len(charts)==12 and all(len(c['points'])==10 for c in charts)
        assert all(c['title'].startswith(LEADS[i]+' · ') for i,c in enumerate(charts))
    assert any(e['event_id']==event['event_id'] and e['duration_s']==candidate['duration_s'] for e in rendering['evidence']['st_events'])
    assert all(e['review_status']=='confirmed' for e in rendering['evidence']['st_events'])
    assert str(int(candidate['duration_s']))+' 秒' in str(rendering['events'])
    assert '当前没有已复核并入选的持续 ST 事件' in str(rendering['empty'])
    checks.append('actual-native-ST12L-seven-second-peak-strip-and-whole-event-report-use-same-proof')
    await page.screenshot(path=str(screenshots/'report-evidence-ST-whole-and-strip.png'))

    # Read-only preview has no report/clinical/candidate side effects.
    before={key:await get(key) for key in ['report','annotations','rhythm-review','evidence-candidates']}
    preview=await get('report-strip-preview?'+urlencode({'time_s':75,'duration':3,'leads':','.join(LEADS)}))
    assert preview['preview_only'] and preview['event']['category']=='other'
    assert len(preview['strip']['leads'])==12 and preview['strip']['visible_beat_count']>=5
    assert preview['strip']['actual_duration_s']>3
    default_preview=await get('report-strip-preview?time_s=75&duration=3')
    triple_preview=await get('report-strip-preview?time_s=75&duration=3&leads=II,V1,V5')
    assert default_preview['strip']['leads']==LEADS and triple_preview['strip']['leads']==['II','V1','V5']
    assert before=={key:await get(key) for key in before}
    checks.append('actual-native-preview-is-readonly-and-real-short-strip-expands-to-five-beats')

    # Real pointer context menu inserts an other strip into the current report.
    before_report=await get('report');before_annotations=await get('annotations')
    surface=page.locator('#v2EventWave .report-range-stage svg[data-plot-left]').first
    await surface.click(button='right',position={'x':250,'y':40})
    await page.locator('#reportWaveMenu').wait_for(state='visible')
    assert await page.locator('#reportWaveMenu>button').count()==15
    old_keys=[p.get('strip_id') or p['event_id'] for p in before_report['composition']['selected_events']]
    await page.locator('[data-report-wave-action="insert"]').click()
    await page.wait_for_function("keys=>state.reportComposition?.selected_events.some(s=>!keys.includes(s.strip_id||s.event_id))",arg=old_keys)
    await saved()
    inserted=[p for p in (await get('report'))['composition']['selected_events'] if not any((p.get('strip_id') or p['event_id'])==(q.get('strip_id') or q['event_id']) for q in before_report['composition']['selected_events'])]
    assert len(inserted)==1 and len(inserted[0]['leads'])==12
    assert await page.evaluate('()=>state.currentPage')=='report' and (await get('annotations'))==before_annotations
    checks.append('actual-native-hospital-wave-menu-inserts-other12L-without-clinical-write-or-navigation')

    # A second independent rhythm candidate holds four stable report strips.
    await nav('review')
    if not await page.locator('#ovAF').is_visible():await page.locator('[data-ov="af-open"]').click()
    await page.wait_for_function('()=>!!state.waveform?.leads')
    await page.locator('[data-ov="af-add:AF"]').first.click()
    clocks=await page.evaluate("()=>[20,280].map(s=>ECGRhythmRangeEditor.boundaryClock(s,state.caseData.metadata.start_time))")
    for name,value in zip(['startClock','endClock'],clocks):
        control=page.locator('#ovEpisodeForm [name='+name+']');await control.fill(value);await control.press('Tab')
    await page.locator('#ovEpisodeForm [name=note]').fill('Native27 independent multi-AF mathematical candidate')
    await page.locator('[data-ov="af-save:pending"]').click()
    await page.wait_for_function('()=>!overviewWorkbench.isSaving()')
    episode=next(e for e in (await get('rhythm-review'))['document']['episodes'] if e['note']=='Native27 independent multi-AF mathematical candidate')
    await page.locator('[data-ov="af-report"]').click();await saved();await tab('AF')
    af=next(e for e in (await get('report-events?category=AF'))['items'] if e['rhythm_episode_id']==episode['id'])
    row=await locate(af)
    initial=await get('rhythm-review');initial_report=await get('report')
    await row.locator('td').last.click();await frames()
    assert (await get('rhythm-review'))['revision']==initial['revision'] and (await get('report'))['version']==initial_report['version']
    assert await page.locator('#unsavedChangesDialog').count()==0
    reps=await get('report-af-representatives?'+urlencode({'event_id':af['event_id'],'basis_version':af['basis_version'],'duration':7}))
    assert [p['representative_role'] for p in reps['items']]==['start','middle','end']
    for role in ['start','middle','end']:
        await page.locator('[data-af-browse="'+role+'"]').click();await settled()
        async with page.expect_response(lambda r:urlsplit(r.url).path.endswith('/report') and r.request.method=='PUT') as ack:
            await page.locator('[data-af-include-current]').click()
        assert (await ack.value).ok
        await saved()
    async def picks():return [p for p in (await get('report'))['composition']['selected_events'] if p['event_id']==af['event_id']]
    assert len(await picks())==3
    await page.locator('[data-af-strip-duration]').select_option('15');await settled()
    slider=await page.locator('[data-af-position]').bounding_box();assert slider
    await page.mouse.click(slider['x']+slider['width']*.35,slider['y']+slider['height']/2);await settled()
    async with page.expect_response(lambda r:urlsplit(r.url).path.endswith('/report') and r.request.method=='PUT') as ack:
        await page.locator('[data-af-include-current]').click()
    assert (await ack.value).ok
    await saved()
    four=await picks();assert len(four)==4 and len({p['strip_id'] for p in four})==4
    assert len({(p['range_start_s'],p['range_end_s']) for p in four})==4
    assert all(len(p['leads'])==12 for p in four)
    assert next(e for e in (await get('rhythm-review'))['document']['episodes'] if e['id']==episode['id'])['status']=='pending'
    checks.append('actual-native-AF-three-recommendations-and-fourth-custom-range-persist-distinct-12L-strips')
    await page.locator('#v2EventNavigation [data-confirm-rhythm="active"]').click()
    dialog=page.locator('#unsavedChangesDialog');await dialog.wait_for(state='visible')
    text=await dialog.inner_text();assert '整段候选' in text and '本次图条' in text
    requests=[]
    def record_put(request):
        if request.method=='PUT' and '/rhythm-review' in request.url:requests.append(request)
    page.on('request',record_put)
    try:
        await dialog.locator('[data-unsaved-save]').click();await dialog.wait_for(state='hidden');await saved()
    finally:page.remove_listener('request',record_put)
    assert len(requests)==1
    confirmed=next(e for e in (await get('rhythm-review'))['document']['episodes'] if e['id']==episode['id'])
    assert confirmed['status']=='confirmed' and (confirmed['start_s'],confirmed['end_s'])==(20,280)
    assert [preserved(p) for p in await picks()]==[preserved(p) for p in four]
    assert all(p['basis_version']!=four[0]['basis_version'] for p in await picks())
    checks.append('actual-native-once-whole-AF-confirmation-rebases-four-strips-and-keeps-full-bounds')
    # Full page reopen proves storage state, not only one live JavaScript object.
    snapshot=[preserved(p) for p in await picks()]
    await nav('dashboard');await page.reload();await page.wait_for_function('()=>state.dashboardStatus==="ready"')
    await page.locator('#openFirstCase').click();await page.wait_for_function('id=>state.caseId===id&&!state.caseLoading',arg=case_id)
    await nav('report');await saved()
    assert [preserved(p) for p in await picks()]==snapshot
    checks.append('actual-native-four-AF-strips-save-and-full-reopen-keeps-identifiers-curation-and-ranges')
    await tab('AF');await locate(af)
    await page.locator('#v2EventWave button[data-display-leads="12"]').click();await frames()
    assert await page.locator('#v2EventWave .report-range-stage [data-wave-lead]').count()==12
    await page.screenshot(path=str(screenshots/'report-evidence-AF-four-strips-reopened.png'))
    return {'status':'passed','checks':checks,'patient_inputs_read':False,'pdf_operations':0,
        'clinical_validation':False,'full_ST_event_duration_s':candidate['duration_s'],
        'ST_strip_duration_s':7,'ST_T_trend_leads':12,'ST_T_minutes_per_lead':10,
        'AF_strip_count':4,'source_case_id':case_id,'retired_old_document_readonly_requests':retired}
