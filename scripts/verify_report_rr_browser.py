"""Real frozen-backend RR selection/approval checks on the disposable M01 workspace."""

async def verify_report_rr(page, screenshots):
    checks = []
    ready = "() => state.currentPage==='report' && !state.reportEvidenceLoading && !state.reportViewLoading && !state.reportEvidenceError"
    saved = "() => !state.reportDirty && !state.reportSaving && !state.reportStale"
    original = await page.evaluate("""async () => {
        const b='/api/cases/'+state.caseId, original=await api(b+'/report');
        for(const step of ['edit','stt']) {
            const r=await api(b+'/review-workflow');
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
    row = page.locator('tr[data-report-event-id]').filter(has_text='M01 RR candidate acceptance')
    event_id = await row.get_attribute('data-report-event-id')
    checkbox = row.locator('[data-include]')
    await checkbox.check()
    await page.wait_for_function(saved)
    await checkbox.uncheck()
    await page.wait_for_function(saved)
    assert await page.evaluate('(id) => !state.reportComposition.selected_events.some(e=>e.event_id===id)', event_id)
    checks.append('uncheck-removes-exact-report-pick')
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
    return {'checks':checks,'input':'mathematical M01 only','actual_frozen_backend':True,'pdf_operations':0}
