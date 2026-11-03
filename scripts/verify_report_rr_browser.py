"""Real frozen-backend RR selection/approval checks on the disposable M01 workspace."""

async def prepare_report_steps(page):
    # Establish the ordinary edit/ST preconditions before opening the case, so
    # a test-only API shortcut cannot leave an already mounted editor obsolete.
    await page.evaluate("""async () => {
        const b='/api/cases/9900000000000001';
        for(const step of ['edit','stt']) {
            const r=await api(b+'/review-workflow');
            if(r.steps?.[step]?.status!=='done')
                await api(b+'/review-workflow',{method:'PUT',body:JSON.stringify({step,revision:r.revision,confirmed:true,note:'M01 mathematical RR engineering acceptance precondition'})});
        }
    }""")


async def verify_report_rr(page, screenshots):
    checks = []
    ready = "() => state.currentPage==='report' && !state.reportEvidenceLoading && !state.reportViewLoading && !state.reportEvidenceError"
    saved = "() => !state.reportDirty && !state.reportSaving && !state.reportStale"
    original = await page.evaluate("""async () => {
        const b='/api/cases/'+state.caseId, original=await api(b+'/report');
        for(const step of ['edit','stt']) {
            const r=await api(b+'/review-workflow');
            if(r.steps?.[step]?.status!=='done')
                await api(b+'/review-workflow',{method:'PUT',body:JSON.stringify({step,revision:r.revision,confirmed:true,note:'M01 mathematical RR engineering acceptance'})});
        }
        const ledger=await api(b+'/evidence-candidates'), longest=await api(b+'/report-rr-evidence'), e=longest.event;
        await ECGReviewCandidates.choose({identity:ledger,item:{sample_index:e.sample_index,rr_ms:e.rr_ms,class_code:e.evidence_ref.terminal.class_code}});
        return original;
    }""")
    await page.locator('.review-candidate-dialog input').fill('M01 RR candidate acceptance')
    await page.locator('[data-candidate-save]').click()
    await page.locator('[data-candidate-open-report]').wait_for()
    assert await page.evaluate("async () => (await api('/api/cases/'+state.caseId+'/report')).composition.selected_events.length") == len(original['composition']['selected_events'])
    checks.append('save-only-candidate-without-report-selection')
    await page.locator('[data-candidate-open-report]').click()
    await page.wait_for_function(ready)
    assert await page.locator('#reportV2Nav [data-category="rr_interval"]').count() == 1
    assert await page.locator('#reportV2Nav [data-category="pause"]').count() == 0
    assert await page.locator('#reportV2Nav [data-category="rr_candidate"]').count() == 0
    automatic = await page.evaluate("async()=>api('/api/cases/'+state.caseId+'/report-events?category=rr_interval&rr_source=auto')")
    assert automatic['total'] == 0  # Unchanged 24h M01 generator caps intervals at 2s.
    async with page.expect_response(lambda r:'/report-events?' in r.url and 'rr_source=auto' in r.url) as changed:
        await page.locator('#v2RRSource').select_option('auto')
    assert (await changed.value).ok
    await page.wait_for_function(ready)
    assert await page.locator('tr[data-report-event-id]').count() == 0
    async with page.expect_response(lambda r:'/report-events?' in r.url and 'rr_source=manual' in r.url) as changed:
        await page.locator('#v2RRSource').select_option('manual')
    assert (await changed.value).ok
    await page.wait_for_function(ready)
    checks.append('unified-RR-entry-and-native-empty-auto-source-filter')
    event_id = await page.evaluate("async()=>{const x=await api('/api/cases/'+state.caseId+'/report-events?category=rr_interval&rr_source=manual');const e=x.items.find(e=>e.label==='M01 RR candidate acceptance');if(!e)throw Error('Exact native RR candidate missing');return e.event_id;}")
    row = page.locator('tr[data-report-event-id=\"'+event_id+'\"]')
    await row.wait_for(state='visible')
    checkbox = row.locator('[data-include]')
    await checkbox.check()
    await page.wait_for_function(saved)
    await checkbox.uncheck()
    await page.wait_for_function(saved)
    assert await page.evaluate('(id) => !state.reportComposition.selected_events.some(e=>e.event_id===id)', event_id)
    checks.append('uncheck-removes-exact-report-pick')
    # Re-selecting the same original pair creates no additional candidate or
    # report row. Cross auto/manual overlap is tested on a separate 4s fixture.
    before_repeat = await page.evaluate("async()=>api('/api/cases/'+state.caseId+'/evidence-candidates')")
    await page.evaluate("""async()=>{const ledger=await api('/api/cases/'+state.caseId+'/evidence-candidates'),longest=await api('/api/cases/'+state.caseId+'/report-rr-evidence'),e=longest.event;await ECGReviewCandidates.choose({identity:ledger,item:{sample_index:e.sample_index,rr_ms:e.rr_ms,class_code:e.evidence_ref.terminal.class_code}});} """)
    await page.locator('[data-candidate-save]').click()
    await page.locator('[data-candidate-open-report]').wait_for()
    await page.locator('[data-candidate-open-report]').click()
    await page.wait_for_function(ready)
    after_repeat = await page.evaluate("async()=>api('/api/cases/'+state.caseId+'/evidence-candidates')")
    assert len(after_repeat['items']) == len(before_repeat['items'])
    assert await row.count() == 1
    checks.append('same-manual-RR-resave-keeps-one-candidate-and-report-row')

    await checkbox.check()
    await page.wait_for_function(saved)
    await page.evaluate("""async id => {
        const b='/api/cases/'+state.caseId,r=await api(b+'/report'),entry=r.composition.selected_events.find(e=>e.event_id===id);
        const value=await api(b+'/report',{method:'PUT',body:JSON.stringify({expected_version:r.version,expected_review_revision:r.review_revision,status:'draft',conclusion:'M01 RR engineering acceptance, no clinical diagnosis',composition:{included_pages:['summary','event_strips'],page_selection_version:1,selected_events:[entry]}})});
        state.report=value;state.reportComposition=value.composition;state.reportDirty=false;state.reportStale=false;
        await clinicalWorkflow.refresh();await clinicalUI.refreshReport();
    }""", event_id)
    await page.wait_for_function(ready)
    await page.locator('#reportV2Nav [data-category="final"]').click()
    await page.wait_for_function(ready)
    assert not await page.locator('#approveReport').is_enabled()
    checks.append('unreviewed-printed-evidence-blocks-final-approval')
    await page.locator('#reportV2Nav [data-category="strips"]').click()
    await page.wait_for_function(ready)
    identity = await page.evaluate('async () => {const x=await api("/api/cases/"+state.caseId+"/evidence-candidates");return {analysis_basis:x.analysis_basis,analysis_revision:x.analysis_revision,beat_revision:x.beat_revision};}')
    await page.locator('.rw-strip [data-review-evidence]').click()
    await page.locator('#reportEvidenceDialog [data-evidence-confirm]:enabled').wait_for()
    for count in (1, 3, 12):
        await page.locator(f'#reportEvidenceDialog [data-evidence-leads="{count}"]').click()
        await page.wait_for_function("n => document.querySelector('#reportEvidenceDialog [data-evidence-wave]')?.dataset.leadCount===String(n) && !document.querySelector('#reportEvidenceDialog [data-evidence-confirm]').disabled", arg=count)
        geometry = await page.locator('#reportEvidenceDialog [data-evidence-wave]').evaluate("""n => ({height:n.clientHeight,scroll:n.scrollHeight,leads:n.querySelectorAll('[data-wave-lead]').length})""")
        assert geometry['leads'] == count and geometry['scroll'] <= geometry['height'] + 2, geometry
    await page.screenshot(path=str(screenshots/'rr-report-evidence-twelve-fit.png'))
    checks.append('one-three-twelve-all-visible-in-one-figure')
    await page.locator('#reportEvidenceDialog [data-evidence-confirm]').click()
    await page.locator('#reportEvidenceDialog').wait_for(state='detached')
    await page.wait_for_function(ready)
    await page.wait_for_function('() => state.reportEvidencePending?.length===0')
    assert await page.evaluate('async () => {const x=await api("/api/cases/"+state.caseId+"/evidence-candidates");return {analysis_basis:x.analysis_basis,analysis_revision:x.analysis_revision,beat_revision:x.beat_revision};}') == identity
    checks.append('report-acknowledgement-keeps-live-analysis-version')
    await page.locator('#reportV2Nav [data-category="final"]').click()
    await page.wait_for_function(ready)
    await page.wait_for_function(saved)
    assert await page.locator('#approveReport').is_enabled()
    await page.locator('#approveReport').click()
    await page.wait_for_function("() => state.report.status==='reviewed' && !state.reportSaving")
    checks.append('actual-frozen-backend-confirms-evidence-and-approves-report')
    await page.evaluate('() => ECGReviewCandidates.pool()')
    candidate = page.locator(f'.review-candidate-dialog [data-candidate-id="{event_id.split(":")[1]}"]')
    await candidate.click()
    await page.wait_for_function('(id) => !state.reportComposition.selected_events.some(e=>e.event_id===id)', arg=event_id)
    await candidate.click()
    await page.wait_for_function("() => document.querySelector('[data-candidate-status]')?.textContent.includes('已恢复')")
    assert await page.evaluate('() => state.reportComposition.selected_events.length') == 0
    await page.locator('[data-candidate-close]').click()
    checks.append('withdraw-removes-strip-and-restore-remains-unselected')
    await page.evaluate("""async original => {
        const b='/api/cases/'+state.caseId,r=await api(b+'/report');
        const value=await api(b+'/report',{method:'PUT',body:JSON.stringify({expected_version:r.version,expected_review_revision:r.review_revision,status:'draft',conclusion:original.conclusion,composition:original.composition})});
        state.report=value;state.reportComposition=value.composition;state.reportDirty=false;state.reportStale=false;
        await clinicalWorkflow.refresh();await clinicalUI.refreshReport();
    }""", original)
    await page.wait_for_function(ready)
    await page.locator('.nav-item[data-page="review"]').click()
    await page.wait_for_function("() => state.currentPage==='review' && state.waveform?.leads && state.waveformOwner && document.querySelector('#waveformCanvas').dataset.waveTimeTicks")
    assert await page.evaluate('async () => {const x=await api("/api/cases/"+state.caseId+"/evidence-candidates");return {analysis_basis:x.analysis_basis,analysis_revision:x.analysis_revision,beat_revision:x.beat_revision};}') == identity
    await page.locator('.nav-item[data-page="report"]').click()
    await page.wait_for_function(ready)
    checks.append('return-to-overview-after-report-review-keeps-readable-waveform')
    return {'checks':checks,'input':'mathematical M01 only','actual_frozen_backend':True,'pdf_operations':0,'automatic_long_rr_population':'empty in unchanged 24h M01; generator intervals capped at 2 seconds','cross_source_overlap_scope':'separate original 4s Python backend and browser Demo mathematical fixtures'}
