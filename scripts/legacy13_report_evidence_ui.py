"""Actual served report UI checks, reusable with native EXE or isolated local math.

All writes use visible UI controls. API evaluation below performs GET assertions.
A caller must label native Windows acceptance separately from local prechecks.
Hospital28 adapts the actual reviewed-record UI; legacy27 constructor remains separate.
"""
from urllib.parse import urlencode, urlsplit
import asyncio
import time

LEADS=['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6']


async def verify_report_evidence_ui(page, case_id, expected_st, screenshots, progress=None, *, expected_for_annotations=None, range_oracle=None):
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

    assert callable(expected_for_annotations) and callable(range_oracle), 'Exact current-mask and per-beat scalar oracles are required'
    await nav('stt');await st_ready()
    initial=await get('stt-review')
    assert initial['analysis']['algorithm_version']=='stt-screening-0.3.1-hospital-records-rhythm-masks'
    assert initial['analysis']['trends']==expected_st['analysis']['trends']
    checks.append('native28-initial-twelve-lead-minute-ST-Delta-T-exact-current-Python-oracle')
    # A second independent rhythm candidate holds four stable report strips.
    await nav('review')
    if not await page.locator('#ovAF').is_visible():await page.locator('[data-ov="af-open"]').click()
    await page.wait_for_function('()=>!!state.waveform?.leads')
    await page.locator('[data-ov="af-add:AF"]').first.click()
    clocks=await page.evaluate("()=>[400,580].map(s=>ECGRhythmRangeEditor.boundaryClock(s,state.caseData.metadata.start_time))")
    for name,value in zip(['startClock','endClock'],clocks):
        control=page.locator('#ovEpisodeForm [name='+name+']');await control.fill(value);await control.press('Tab')
    await page.locator('#ovEpisodeForm [name=note]').fill('Native28 independent multi-AF mathematical candidate')
    await page.locator('[data-ov="af-save:pending"]').click()
    await page.wait_for_function('()=>!overviewWorkbench.isSaving()')
    episode=next(e for e in (await get('rhythm-review'))['document']['episodes'] if e['note']=='Native28 independent multi-AF mathematical candidate')
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
    assert confirmed['status']=='confirmed' and (confirmed['start_s'],confirmed['end_s'])==(400,580)
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

    # AF decisions precede ST review: they are real eligibility masks, not display flags.
    await nav('stt');await st_ready()
    annotations=await get('annotations');st=await get('stt-review')
    oracle=expected_for_annotations(annotations['items'])
    assert st['analysis']['trends']==oracle['analysis']['trends']
    assert st['analysis']['exclusions']['intervals'], 'Saved AF/AFL must enter screening support exclusions'
    assert sorted(st['analysis']['trends']['leads'])==sorted(LEADS)
    for points in st['analysis']['trends']['leads'].values():
        assert len(points)==10 and points[0]['start_s']==0 and points[-1]['end_s']==600
        for p in points:
            assert 0<p['duration_s']<=60 and p['valid_duration_s']<=p['duration_s']+.005
            if not p['eligible'] or p['axis_shift_suspected']:
                assert all(p[k] is None for k in ['st_level_units','reference_units','deviation_units','t_amplitude_units','t_reference_units'])
    for mode,field in [('st','st_level_units'),('delta','deviation_units'),('t','t_amplitude_units')]:
        await page.locator('[data-stt-trend-mode="'+mode+'"]').click();await frames()
        observed=await page.evaluate("""field=>{const bounds=sttTrendBounds(),length=bounds.end-bounds.start,input=state.sttReview.analysis.trends.leads;let limit=1;for(const points of Object.values(input))for(const p of points)if(p.eligible!==false&&!p.axis_shift_suspected&&Number.isFinite(p[field])&&p.time_s>=bounds.start&&p.time_s<=bounds.end)limit=Math.max(limit,Math.abs(p[field]));return [...document.querySelectorAll('#sttTrendRows .stt-trend-row')].map(row=>{const lead=row.querySelector('strong').textContent,points=input[lead]||[];let expected='',pen=false;for(const p of points){if(p.eligible===false||p.axis_shift_suspected||!Number.isFinite(p[field])||p.time_s<bounds.start||p.time_s>bounds.end){pen=false;continue;}expected+=(pen?'L':'M')+((p.time_s-bounds.start)/length*100).toFixed(3)+','+(8-p[field]/limit*6).toFixed(3)+' ';pen=true;}const track=row.querySelector('.stt-trend-track'),box=row.getBoundingClientRect(),t=track.getBoundingClientRect();return {lead,expected,actual:row.querySelector('path')?.getAttribute('d')||'',track_width:t.width,row_width:box.width};});}""",field)
        for row in observed:
            assert row['actual']==row['expected'],(mode,row['lead'])
            assert row['track_width']>row['row_width']*.70, 'Actual trend curve was squeezed out of its main column'
    geometry=await page.evaluate("""()=>[...document.querySelectorAll('#sttTrendRows .stt-trend-row')].map(row=>{const box=n=>{const r=n.getBoundingClientRect();return {left:r.left,right:r.right,width:r.width};};return {row:box(row),label:box(row.querySelector('strong')),track:box(row.querySelector('.stt-trend-track')),value:box(row.querySelector('small')),heart:box(document.querySelector('#sttOverviewCanvas'))};})""")
    assert len(geometry)==12
    for g in geometry:
        assert g['track']['width']>g['row']['width']*.7
        assert g['label']['right']<=g['track']['left']+.75 and g['track']['right']<=g['value']['left']+.75
        assert abs(g['heart']['left']-g['track']['left'])<2 and abs(g['heart']['right']-46-g['track']['right'])<2
    checks.append('native28-saved-AF-mask-breaks-full-minute-evidence-and-three-metric-controls-use-own-fields')
    candidates=[c for c in st['automatic_candidates']['items'] if c['kind'] in ('st_depression','st_elevation') and len(c['leads'])==1 and c['end_s']-c['start_s']>=60]
    assert candidates, 'Real detector must supply a current full-minute candidate'
    candidate=max(candidates,key=lambda c:c['end_s']-c['start_s']);lead=candidate['leads'][0]
    source_range={'start_s':candidate['start_s'],'end_s':candidate['end_s']};duration=candidate['end_s']-candidate['start_s']
    before_report=await get('report');before_annotations=await get('annotations')
    await page.locator('[data-stt-row-kind="candidate"][data-stt-row-id="'+candidate['id']+'"]').click();await st_ready()
    assert await page.locator('#sttFinding').input_value()=='' and not await page.locator('#sttSignalChecked').is_checked()
    assert await page.locator('#saveSttAnnotation').inner_text()=='保存复核'
    for role in ['start','end','peak']:
        await page.locator('[data-stt-position="'+role+'"]').click();await st_ready()
        assert await page.evaluate('()=>sttReadReviewRange()')==source_range
        assert await page.locator('#sttFinding').input_value()==''
    for width,height in [(1366,768),(1920,1080)]:
        await page.set_viewport_size({'width':width,'height':height});await frames()
        for count in [1,3,12]:
            await page.locator('[data-stt-display-count="'+str(count)+'"]').click();await st_ready()
            shape=await page.locator('#sttWaveformCanvas').evaluate("""c=>{const b=c.getBoundingClientRect();return {count:Number(c.dataset.sttRenderLeads),gain:Number(c.dataset.displayGain),height:b.height,top:b.top,bottom:b.bottom,source:Object.keys(state.sttWaveform.leads).length};}""")
            assert shape['count']==shape['source']==count and 149<=shape['height']<=421 and shape['top']>=0 and shape['bottom']<=height+2 and shape['gain']>0,shape
    await page.set_viewport_size({'width':1440,'height':1000});await frames()
    assert (await get('annotations'))==before_annotations and (await get('report'))['version']==before_report['version']
    checks.append('native28-view-only-candidate-keeps-blank-result-whole-range-and-bounded-one-three-twelve-lead-source')

    async def save_review(code,note):
        finding=await page.evaluate('code=>ECGSttReviewLayout.outcomes[code]',code)
        await page.locator('#sttFinding').select_option(finding);await page.locator('#sttReviewNote').fill(note)
        if code!='indeterminate':await page.locator('#sttSignalChecked').check()
        await page.locator('#saveSttAnnotation').click()
        await page.wait_for_function('code=>!state.sttSaving&&state.sttLastSavedEvent?.result_code===code&&!state.sttSelectedCandidate&&sttWaveformIsCurrent()',arg=code)
        await settled();return await page.evaluate('()=>state.sttLastSavedEvent')
    async def open_record(receipt):
        await page.locator('#sttSelectedEvent [data-stt-report]').click();await saved()
        await page.wait_for_function("p=>state.reportDisplayedCategory==='ST'&&document.querySelector('#v2STGroup')?.value===p.group&&document.querySelector('#v2EventWave .report-range-editor')?._rangeEventId===p.id",arg={'id':receipt['event_id'],'group':receipt['report_group']})
        return page.locator('tr[data-report-event-id="'+receipt['event_id']+'"]')
    async def adopt(receipt,purpose,value):
        row=page.locator('tr[data-report-event-id="'+receipt['event_id']+'"]')
        await row.locator('[data-stt-use="'+purpose+'"]').set_checked(value);await saved()
        return await get('report')
    def picks_for(report,identifier):return [p for p in report['composition']['selected_events'] if p['event_id']==identifier]
    nochange=await save_review('no_change','Native28 mathematical record; no whole-record negative diagnosis.')
    assert nochange['review_state']=='reviewed' and nochange['report_group']=='ST_NOTE' and nochange['record_version']==1
    assert {k:nochange['range'][k] for k in ['start_s','end_s']}==source_range and nochange['range']['duration_s']==duration and not nochange['report_eligibility']['table'] and nochange['report_eligibility']['text']
    row=await open_record(nochange);assert not await row.locator('[data-stt-use="table"]').is_enabled()
    r=await adopt(nochange,'text',True);assert not picks_for(r,nochange['event_id'])
    assert any(b['key']=='ST:review:'+nochange['event_id'] for b in r['composition']['diagnosis_blocks'])
    checks.append('native28-negative-reviewed-record-text-only-adoption-is-not-an-abnormal-event-or-strip')
    await page.locator('[data-stt-edit]').click();await st_ready()
    reviewed=await save_review(candidate['kind'],'Native28 whole source interval; the short strip is evidence only.')
    assert reviewed['event_id']==nochange['event_id'] and reviewed['record_version']==2 and reviewed['basis_version']!=nochange['basis_version']
    current=await get('annotations');annotation=next(a for a in current['items'] if 'annotation:'+str(a['id'])==reviewed['event_id']);proof=annotation['details']['stt_event_evidence']
    assert len(current['items'])==len(before_annotations['items'])+1
    assert annotation['sample_index']==round(candidate['start_s']*200) and annotation['details']['end_sample']==round(candidate['end_s']*200)-1
    assert proof['duration_s']==duration and proof['leads']==[lead] and proof['measurement_protocol']['measurement_ms']==60 and proof['measurement_protocol']['extent']=='whole'
    scalar=range_oracle(annotation['sample_index'],annotation['details']['end_sample']+1,[lead],current['items'])
    assert proof['metrics']==scalar['leads'], 'Actual PE whole-event metrics differ from original-input per-beat scalar oracle'
    r=await get('report');assert not picks_for(r,reviewed['event_id']) and not any(u['event_id']==reviewed['event_id'] for u in r['composition'].get('stt_report_use',[]))
    assert not any(b['key']=='ST:review:'+reviewed['event_id'] for b in r['composition']['diagnosis_blocks'])
    assert r['composition']['selected_events']==before_report['composition']['selected_events'] and r['conclusion']==before_report['conclusion']
    checks.append('native28-same-ID-result-update-retracts-own-old-normal-text-and-preserves-unrelated-curation')
    row=await open_record(reviewed)
    await adopt(reviewed,'table',True);r=await adopt(reviewed,'text',True);assert not picks_for(r,reviewed['event_id'])
    r=await adopt(reviewed,'strip',True);pick=picks_for(r,reviewed['event_id']);assert len(pick)==1 and pick[0]['leads']==LEADS and pick[0]['duration_s']==7
    summary=(await get('report-sections'))['st_summary'];await adopt(reviewed,'strip',False);assert not picks_for(await get('report'),reviewed['event_id']) and (await get('report-sections'))['st_summary']==summary
    await adopt(reviewed,'table',False);assert (await get('report-sections'))['st_summary']==summary
    await adopt(reviewed,'table',True);r=await adopt(reviewed,'strip',True);pick=picks_for(r,reviewed['event_id'])[0]
    assert r['composition']['selected_events'][:len(before_report['composition']['selected_events'])]==before_report['composition']['selected_events']
    checks.append('native28-table-text-strip-purposes-are-independent-and-withdrawn-strip-disappears-without-count-change')
    event=next(e for e in (await get('report-events?category=ST&stt_group=all&ids='+reviewed['event_id']+'&limit=1'))['items'] if e['event_id']==reviewed['event_id'])
    strip=await get('report-strip?'+urlencode(dict(event_id=event['event_id'],basis_version=event['basis_version'],leads=','.join(LEADS),duration=7)))
    assert strip['strip']['actual_duration_s']==7 and strip['strip']['visible_beat_count']>=5 and len(strip['waveform']['leads'])==12 and strip['stt_event_evidence']['duration_s']==duration
    rendering=await page.evaluate("""async()=>{const base='/api/cases/'+state.caseId+'/',evidence=await api(base+'report-sections'),report=await api(base+'report'),model={case:state.caseData,report,evidence};return {evidence,st:ECGReportSections.documents(model,['st_trend']),t:ECGReportSections.documents(model,['t_trend']),events:ECGReportSections.documents(model,['st_events']),empty:ECGReportSections.documents({...model,report:{...report,composition:{...report.composition,selected_events:[],stt_report_use:[]}}},['st_events'])};}""")
    for family,metric in [('st','st_level_units'),('t','t_amplitude_units')]:
        docs=rendering[family];assert len(docs)==1 and docs[0]['layout']=='stt_trend' and docs[0]['metric']==metric
        assert [r['lead'] for r in docs[0]['trend_rows']]==LEADS and all(len(r['points'])==10 for r in docs[0]['trend_rows']) and any(p['y'] is not None for p in docs[0]['heart_rate'])
    rows=[e for e in rendering['evidence']['st_events'] if e['event_id']==event['event_id']];assert len(rows)==1 and rows[0]['lead']==lead and rows[0]['mean_st_level_units']==proof['metrics'][0]['mean_st_level_units'] and rows[0]['used_beat_count']==proof['metrics'][0]['used_count'] and rows[0]['slope'] is None and rows[0]['calibrated_mm'] is None
    reps=[r for r in rendering['evidence']['st_representatives'] if r['event_id']==event['event_id']];assert len(reps)==3
    for rep in reps:assert rep['role'] in ('reference','st_min','st_max') and annotation['sample_index']<=rep['sample_index']<=annotation['details']['end_sample'] and rep['waveform']['leads'][rep['lead']]
    assert all(not d.get('table_rows') for d in rendering['empty'])
    checks.append('native28-hospital-ST-T-single-page-twelve-trends-heart-rate-and-three-real-source-representatives')
    await page.screenshot(path=str(screenshots/'native28-hospital-ST-record-and-strip.png'))

    # Retain the original readonly preview and real pointer menu assertions.
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

    return {'status':'passed','checks':checks,'patient_inputs_read':False,'pdf_operations':0,'clinical_validation':False,
        'algorithm_version':st['analysis']['algorithm_version'],'full_ST_event_duration_s':duration,'ST_strip_duration_s':7,
        'ST_T_trend_leads':12,'ST_T_minutes_per_lead':10,'AF_strip_count':4,'source_case_id':case_id,
        'retired_old_document_readonly_requests':retired,'ST_record_version':reviewed['record_version'],'ST_record_event_id':reviewed['event_id'],
        'same_record_old_generated_text_withdrawn':True,'three_purposes_independent':True,'current_mask_oracle_verified':True,'full_range_perbeat_oracle_verified':True}
