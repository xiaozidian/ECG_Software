"""Real M01 pointer/browser checks for the current workstation, without PDF."""
import json

LEADS=['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6']

async def verify_latest_ui(page, screenshots):
    from verify_windows_doctor_browser import navigate, wait_edit, two_frames
    checks=[]
    await navigate(page,'edit')
    await page.locator('#editClusterMode').click()
    await wait_edit(page)

    async def state():
        return await page.evaluate("""()=>({code:document.querySelector('#occType').value,
            mode:document.querySelector('#occMode').value,template:document.querySelector('#occTemplate').value,
            source:state.editSelectedClass,selected:state.editSelectedSamples.size,
            open:!document.querySelector('#editTypeMenu').hidden,
            pressed:[...document.querySelectorAll('[data-occ-type][aria-pressed=true]')].map(x=>x.dataset.occType)})""")

    async def ready(code):
        await page.wait_for_function("""code=>document.querySelector('#occType').value===code
            && document.querySelector('#editTemplateGallery').dataset.readState==='ready'
            && !document.querySelector('#editTemplateGallery').getAttribute('aria-busy')?.includes('true')""",arg=code)
        await two_frames(page)
        return await state()

    reads=[]
    def request(r):
        if '/template-occurrences?' in r.url:reads.append(r.method)
    page.on('request',request)
    try:
        for code in ['V','S','other','N']:
            await page.locator(f'[data-occ-type="{code}"]').click()
            current=await ready(code)
            assert current['mode']=='all' and current['template']=='all'
            assert current['source']=='source-'+code and current['pressed']==[code]
            assert not current['open'] and current['selected']==0
            checks.append(code+'-switch-selects-complete-category')
            before=len(reads)
            await page.locator(f'[data-occ-type="{code}"]').click()
            await two_frames(page)
            assert (await state())['open'] and len(reads)==before
            await page.keyboard.press('Escape')
            assert not (await state())['open']
            checks.append(code+'-second-click-opens-only-subtypes')
        await page.locator('[data-occ-type="V"]').click();await ready('V')
        await page.locator('[data-occ-type="V"]').click()
        await page.locator('#editTypeMenu [data-mode="couplet"]').click()
        assert (await ready('V'))['mode']=='couplet'
        await page.locator('[data-occ-type="S"]').click()
        assert (await ready('S'))['mode']=='all'
        checks.append('category-switch-resets-previous-subtype')
        await page.locator('[data-occ-type="N"]').click();await ready('N')
    finally:
        page.remove_listener('request',request)

    async def canvas_geometry():
        await page.wait_for_function("""()=>state.waveformExpanded && Object.keys(state.waveform?.leads||{}).length===12
            && JSON.parse(document.querySelector('#waveformCanvas').dataset.waveLeads||'[]').length===12""")
        await two_frames(page)
        value=await page.locator('#waveformCanvas').evaluate("""c=>({
            leads:JSON.parse(c.dataset.waveLeads),baselines:JSON.parse(c.dataset.waveBaselines),
            width:Number(c.dataset.waveWidth),ticks:JSON.parse(c.dataset.waveTimeTicks||'[]')})""")
        assert value['leads']==LEADS and value['width']>1000
        assert all(b-a>=45 for a,b in zip(value['baselines'],value['baselines'][1:]))
        assert len(value['ticks'])>=2
        await page.keyboard.press('Escape')
        await page.wait_for_function('()=>!state.waveformExpanded')
        await two_frames(page)
        return value

    await page.locator('#editLibraryMode').click();await wait_edit(page)
    await page.locator('#editLibraryWaveformCanvas').dblclick()
    await canvas_geometry();assert await page.evaluate("()=>state.currentPage==='edit' && state.editMode==='library'")
    checks.append('library-three-lead-double-click-vertical-twelve-return')
    await page.locator('#editClusterMode').click();await wait_edit(page)
    await navigate(page,'review')
    await page.wait_for_function("()=>state.waveform?.leads && document.querySelector('#waveformCanvas').dataset.waveTimeTicks")
    await page.locator('#waveformCanvas').dblclick();await canvas_geometry()
    checks.append('overview-double-click-full-width-vertical-twelve')
    await navigate(page,'stt')
    await page.wait_for_function("()=>document.querySelector('#sttWaveCanvasWrap').dataset.sttWaveState==='ready'")
    await page.locator('#sttWaveformCanvas').dblclick();await canvas_geometry()
    assert await page.evaluate("()=>state.currentPage==='stt'")
    checks.append('STT-three-lead-double-click-return')

    async def modal():
        await page.locator('.rw-event-preview-dialog [data-wave-lead="V6"]').wait_for()
        shape=await page.locator('.rw-event-preview-dialog .rw-twelve-wave').evaluate("""s=>({
            columns:s.dataset.columns,leads:[...s.querySelectorAll('[data-wave-lead]')].map(x=>x.dataset.waveLead),
            ticks:s.querySelectorAll('[data-wave-time]').length,width:s.getBoundingClientRect().width})""")
        assert shape['columns']=='1' and shape['leads']==LEADS and shape['ticks']>=2, json.dumps(shape)
        await page.locator('[data-rw-close]').click()
        return shape

    await navigate(page,'rr');await page.locator('.rrv-wave-stage svg').wait_for()
    await page.locator('.rrv-wave-stage svg').dblclick();await modal()
    checks.append('RR-selected-wave-double-click-vertical-twelve')
    await navigate(page,'trends')
    await page.locator('[data-hrv-edit-action="locate"]').first.click()
    await page.locator('[data-hrv-wave-detail] svg').wait_for()
    for selector in ['[data-hrv-wave-overview] svg','[data-hrv-wave-detail] svg']:
        await page.locator(selector).dblclick();await modal()
    checks.append('HRV-overview-and-detail-double-click-vertical-twelve')

    await navigate(page,'report')
    await page.locator('#v2EventWave [data-wave-lead="V6"]').wait_for()
    geometries=[]
    for viewport in [{'width':1440,'height':1000},{'width':1280,'height':800}]:
        await page.set_viewport_size(viewport);await two_frames(page)
        shape=await page.locator('#v2EventWave svg').evaluate("""s=>({columns:s.dataset.columns,
            leads:[...s.querySelectorAll('[data-wave-lead]')].map(x=>x.dataset.waveLead),
            baselines:[...s.querySelectorAll('[data-wave-baseline]')].map(x=>Number(x.dataset.waveBaseline)),
            width:s.getBoundingClientRect().width,plot:Number(s.dataset.plotWidth),
            ticks:s.querySelectorAll('[data-wave-time]').length,axis:document.querySelector('#v2EventWave .rw-main-time-axis')?.textContent||''})""")
        assert shape['columns']=='1' and shape['leads']==LEADS and len(shape['axis'])>12, json.dumps(shape)
        assert shape['plot']/shape['width']>.8
        assert all(b-a>=45 for a,b in zip(shape['baselines'],shape['baselines'][1:]))
        geometries.append({'viewport':viewport,**shape})
    checks.append('report-vertical-full-width-twelve-on-large-and-compact-screens')
    await page.locator('#v2EventWave svg').dblclick(position={'x':150,'y':60});await modal()
    checks.append('report-category-wave-double-click-vertical-twelve')
    await page.locator('.v2-event-list [data-include]').first.check()
    await page.locator('#reportV2Nav [data-category="final"]').click()
    await page.locator('.rw-mini-wave svg').first.wait_for()
    await page.locator('.rw-mini-wave svg').first.dblclick();await modal()
    checks.append('report-included-source-strip-and-twelve-lead-preview')
    await page.locator('#saveReport').click()
    await page.wait_for_function('()=>!state.reportSaving && !state.reportDirty')
    await navigate(page,'dashboard')
    await page.locator('#openFirstCase').click();await wait_edit(page)
    await navigate(page,'report')
    await page.locator('#reportV2Nav [data-category="final"]').click()
    await page.locator('.rw-mini-wave svg').first.wait_for()
    checks.append('included-report-strip-persists-through-save-and-reopen')
    await page.set_viewport_size({'width':1440,'height':1000});await two_frames(page)
    await page.screenshot(path=str(screenshots/'latest-report-included-strip.png'))
    return {'checks':checks,'report_geometry':geometries,'pdf_operations':0,
            'source_kind':'mathematical_synthetic','unmodified_native_responses':True}
