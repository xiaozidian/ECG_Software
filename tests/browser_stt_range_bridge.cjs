/* Actual frozen component plus actual new bridge; synthetic DOM/transport only. */
const assert=require('node:assert/strict');
const fs=require('node:fs'), path=require('node:path'), os=require('node:os');
const {chromium}=require(process.env.ECG_PLAYWRIGHT_CORE || process.env.PLAYWRIGHT_CORE || 'playwright-core');
const root=path.resolve(__dirname,'..');
const source=rel=>fs.readFileSync(path.join(root,rel),'utf8');
const checks=[], network=[], errors=[];
async function fixture(page, overrides={}) {
  await page.setContent('<!doctype html><html lang="zh"><body><select id="sttMeasurementPoint"><option value="60">60</option><option value="80">80</option><option value="0">0</option></select><form id="sttReviewForm"><select id="sttFinding"><option>无法判读</option></select><textarea id="sttReviewNote" maxlength="1200">医生原文：需结合症状核对。</textarea><input id="sttSignalChecked" type="checkbox"></form><section id="sttRangeReview"></section></body></html>');
  await page.addStyleTag({content:source('static/css/stt-range-review.css')});
  await page.addScriptTag({content:source('static/js/stt-range-review.js')});
  await page.addScriptTag({content:source('static/js/stt-range-bridge.js')});
  await page.evaluate(overrides=>{
    window.state={caseId:'math-A',caseRequestId:7,workspaceEpoch:'math-epoch-A',currentPage:'stt',
      sttStart:50,sttDuration:10,sttMeasurementMs:60,sttIsoFraction:.34,sttJFraction:.52,
      sttLeads:['II','V1','V5'],caseData:{case_id:'math-A',technical:{duration_seconds_raw:180},
        clinical_identity:{analysis_basis:'math-basis-A',analysis_revision:4},review_workflow:{revision:4}},
      sttReview:{case_id:'math-A',analysis_basis:'math-basis-A',analysis_revision:4,beat_revision:2},...overrides};
    window.calls=[];window.gates=[];window.toasts=[];window.locates=[];window.mode='immediate';
    delete globalThis.__CARDIOINSIGHT_MATHEMATICAL_CASE__;
    window.response=request=>({schema_version:'stt-range-mean-v1',scope:structuredClone(request.scope),
      server_identity:{case_id:request.scope.case_id,analysis_basis:request.scope.analysis_basis,
        analysis_revision:request.scope.analysis_revision,beat_revision:request.scope.beat_revision,source_digest:'b'.repeat(64)},
      method_profile:{id:'raw-200hz-fixed16s-st-perbeat-mean-v1',sample_rate_hz:200,measurement_ms:request.measurement_ms,
        baseline_offsets_samples:[-40,-36,-32,-28,-24],st_window_offsets_samples:[-2,-1,0,1,2],
        aggregate:'arithmetic_mean_of_used_per_beat_st_minus_baseline',j_basis:'fixed_16s_machine_estimate_after_explicit_masks',
        unit_label:'u',calibration_verified:false,quality_note:'数学质量标记未经医生核对。'},
      range:{start_sample:request.start_sample,end_sample:request.end_sample,start_s:request.start_sample/200,
        end_s:request.end_sample/200,duration_s:(request.end_sample-request.start_sample)/200,half_open:true},
      counts:{detected_count:4,used_count:3,excluded_count:1,missing_count:0,reason_counts:{explicit_anchor_exclusion:1}},
      coverage:{requested_duration_s:60,source_coverage_s:60,explicit_excluded_s:1,explicit_missing_s:0,
        engineering_eligible_block_coverage_s:59,engineering_eligible_block_coverage_pct:59/60*100,
        used_anchor_span_s:2,max_used_anchor_gap_s:1,coverage_is_signal_quality:false},
      exclusions:{digest:'d'.repeat(64),intervals:[]},blocks:[{large_detail:'must not persist in compact snapshot'}],
      binding:{status:'caller_source_and_basis_bound',source_digest:'b'.repeat(64),beats_digest:'c'.repeat(64)},
      save_receipt:{kind:'native-stt-range-hmac-v1',digest:'e'.repeat(64)},
      result_digest:request.start_sample.toString(16).padStart(64,'0'),
      leads:request.leads.map(lead=>({lead,mean_units:lead==='II'?0:lead==='V1'?-12.5:7.25,
        used_count:3,excluded_count:1,missing_count:0,reason_counts:{explicit_anchor_exclusion:1}}))});
    window.api=async(url,options)=>{
      if (options.method!=='POST' || !url.endsWith('/stt-range')) throw Error('unexpected write or route');
      const request=JSON.parse(options.body);calls.push({url,request,method:options.method});
      if(mode==='held')return new Promise(resolve=>gates.push({request,resolve,signal:options.signal}));
      if(mode==='error')throw Error('synthetic retry error');
      return response(request);
    };
    document.querySelector('#sttMeasurementPoint').addEventListener('change',event=>state.sttMeasurementMs=Number(event.target.value));
    window.options={state,api,host:document.querySelector('#sttRangeReview'),getCaseToken:()=>state.caseRequestId,
      getWorkspaceEpoch:()=>state.workspaceEpoch,toast:(message,type)=>toasts.push({message,type}),
      onLocate:(range,context)=>{if(!context.isCurrent())throw Error('old locate');locates.push(range);}};
    window.bridge=ECGSTTRangeBridge.mount(options);
  },overrides);
}
const button=(page,name)=>page.locator(`[data-sttr-action="${name}"]`);
async function calculate(page) {await button(page,'calculate').click();await page.waitForFunction(()=>document.querySelector('[data-sttr-mean="II"]') || document.querySelector('[data-sttr-action="retry"]')?.hidden===false);}
async function fill(page) {await calculate(page);await button(page,'review').click();await page.waitForFunction(()=>state.sttRangeReviewed);}
const flush=page=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
(async()=>{
  const browser=await chromium.launch({executablePath:process.env.ECG_CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true,chromiumSandbox:true});
  try {
    const context=await browser.newContext({viewport:{width:1600,height:1000},deviceScaleFactor:2});
    await context.route('**/*',route=>{network.push(route.request().url());return route.abort();});
    const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
    await fixture(page);await fill(page);
    let data=await page.evaluate(()=>({note:document.querySelector('#sttReviewNote').value,
      scope:calls[0].request.scope,request:calls[0].request,snapshot:bridge.snapshotForSave(),
      finding:document.querySelector('#sttFinding').value,quality:document.querySelector('#sttSignalChecked').checked,
      iso:state.sttIsoFraction,j:state.sttJFraction}));
    assert(data.note.startsWith('医生原文：需结合症状核对。\n'));
    assert.match(data.note,/机器逐搏统计、16秒块 J/);assert.match(data.note,/II 0 u（n=3）/);
    assert.equal(data.request.start_sample,10000);assert.equal(data.request.end_sample,22000);
    assert.deepEqual(data.scope,{case_id:'math-A',analysis_basis:'math-basis-A',analysis_revision:4,beat_revision:2,client_case_token:7,workspace_epoch:'math-epoch-A'});
    assert.equal(data.snapshot.blocks,undefined);assert.equal(data.snapshot.binding.source_digest,'b'.repeat(64));
    assert.equal(data.finding,'无法判读');assert.equal(data.quality,false);assert.equal(data.iso,.34);assert.equal(data.j,.52);
    checks.push('actual component fills concise machine-range note, preserves doctor text/manual ISO/J/finding/quality, and compacts provenance');

    await page.evaluate(()=>{window.saved=bridge.snapshotForSave();saved.range.start_sample=123;});
    assert.equal(await page.evaluate(()=>state.sttRangeReviewed.range.start_sample),10000);
    await page.evaluate(()=>{state.sttStart=130;state.sttDuration=20;bridge.sync();});
    assert.equal(await page.locator('[data-sttr-start]').inputValue(),'50');
    assert.equal(await page.locator('[data-sttr-end]').inputValue(),'110');
    assert.equal(await page.evaluate(()=>bridge.snapshotForSave().range.start_sample),10000);
    await page.evaluate(()=>{state.currentPage='report';bridge.sync();state.currentPage='stt';bridge.sync();});
    assert.equal(await page.evaluate(()=>bridge.snapshotForSave().range.start_sample),10000);
    assert.equal(await page.locator('[data-sttr-mean="II"]').textContent(),'0');
    checks.push('same-case waveform pan and page return preserve the independent minute range and valid snapshot; returned snapshot is a deep copy');

    await page.evaluate(()=>{state.sttReview.analysis_revision=5;state.caseData.clinical_identity.analysis_revision=5;state.caseData.review_workflow.revision=5;bridge.sync();});
    assert.equal(await page.evaluate(()=>state.sttRangeReviewed),null);
    assert.equal(await page.locator('[data-sttr-start]').inputValue(),'50');
    assert.match(await page.evaluate(()=>{try{bridge.snapshotForSave();return '';}catch(e){return e.message;}}),/失效/);
    await fill(page);
    assert.equal((await page.locator('#sttReviewNote').inputValue()).split('范围 ST 均值').length-1,1);
    assert.equal(await page.evaluate(()=>bridge.snapshotForSave().scope.analysis_revision),5);
    checks.push('global revision invalidates evidence, preserves range and doctor text, rejects stale save, and explicit recompute replaces only the bridge line');

    for (const change of ['beat','token','epoch','case']) {
      await fixture(page);await fill(page);
      await page.evaluate(change=>{
        if(change==='beat')state.sttReview.beat_revision++;
        if(change==='token')state.caseRequestId++;
        if(change==='epoch')state.workspaceEpoch='math-epoch-B';
        if(change==='case'){state.caseId='math-B';state.caseData.case_id='math-B';state.sttReview.case_id='math-B';}
        bridge.sync();
      },change);
      assert.equal(await page.evaluate(()=>state.sttRangeReviewed),null);
      assert.match(await page.evaluate(()=>{try{bridge.snapshotForSave();return '';}catch(e){return e.message;}}),/失效|绑定/);
    }
    checks.push('beat revision, case token, workspace epoch and case changes cannot silently save stale statistic text');

    await fixture(page);await fill(page);await page.locator('#sttMeasurementPoint').selectOption('80');
    assert.equal(await page.locator('[data-sttr-measurement]').inputValue(),'80');
    assert.equal(await page.evaluate(()=>state.sttRangeReviewed),null);
    await fill(page);assert.match(await page.locator('#sttReviewNote').inputValue(),/J\+80 ms/);
    assert.equal(await page.evaluate(()=>bridge.snapshotForSave().method_profile.measurement_ms),80);
    checks.push('existing ST60/ST80 selector explicitly updates the range method and invalidates the old mean without applying manual J to the range');

    await page.locator('[data-sttr-start]').fill('60');await page.locator('[data-sttr-end]').fill('120');
    assert.equal(await page.evaluate(()=>state.sttRangeReviewed),null);
    assert.match(await page.evaluate(()=>{try{bridge.snapshotForSave();return '';}catch(e){return e.message;}}),/失效/);
    await fill(page);assert.equal(await page.evaluate(()=>bridge.snapshotForSave().range.start_sample),12000);
    checks.push('range editing immediately invalidates filled provenance; explicit recompute can replace only the bridge-owned line');

    await fixture(page);await page.locator('[data-sttr-start]').fill('50.003');
    await page.locator('#sttMeasurementPoint').selectOption('80');
    assert.equal(await page.locator('[data-sttr-start]').inputValue(),'50.003');
    assert.equal(await page.locator('[data-sttr-measurement]').inputValue(),'80');
    await button(page,'calculate').click();await flush(page);
    assert.equal(await page.evaluate(()=>calls.length),0);
    assert.match(await page.locator('[data-sttr-status]').textContent(),/5 ms/);
    checks.push('existing measurement selector preserves an unfinished off-grid time draft and validation remains at Calculate');

    await fixture(page);await page.locator('#sttReviewNote').fill('医'.repeat(1190));await calculate(page);await button(page,'review').click();await flush(page);
    assert.equal(await page.locator('#sttReviewNote').inputValue(),'医'.repeat(1190));
    assert.equal(await page.evaluate(()=>state.sttRangeReviewed),null);
    assert.match(await page.locator('[data-sttr-status]').textContent(),/1200/);
    assert(await button(page,'review').isEnabled());
    await page.locator('#sttReviewNote').fill('医生精简后仍保留原意。');await button(page,'review').click();await page.waitForFunction(()=>state.sttRangeReviewed);
    assert((await page.locator('#sttReviewNote').inputValue()).startsWith('医生精简后仍保留原意。'));
    checks.push('1200-character overflow rejects without truncation or provenance; reducing doctor text permits an explicit retry');

    await fixture(page);await fill(page);await page.evaluate(()=>window.oldSave=bridge.snapshotForSave());
    await fill(page);await page.evaluate(()=>window.newSave=bridge.snapshotForSave());
    assert.equal(await page.evaluate(()=>oldSave.result_digest===newSave.result_digest),true);
    assert.equal(await page.evaluate(()=>bridge.clearAfterSave(oldSave)),false);
    assert(await page.evaluate(()=>!!state.sttRangeReviewed));
    assert.equal(await page.evaluate(()=>bridge.clearAfterSave(newSave)),true);
    assert.equal(await page.evaluate(()=>state.sttRangeReviewed),null);
    checks.push('same numeric digest in a newer filled generation cannot be cleared by an old save completion; only the issued current snapshot clears');

    await fixture(page);await page.evaluate(()=>mode='held');await button(page,'calculate').click();await page.waitForFunction(()=>gates.length===1);
    await page.evaluate(()=>{state.caseRequestId++;bridge.sync();gates[0].resolve(response(gates[0].request));});await flush(page);
    assert.equal(await page.locator('[data-sttr-mean]').count(),0);assert.equal(await page.evaluate(()=>state.sttRangeReviewed),null);
    assert.equal(await page.locator('#sttReviewNote').inputValue(),'医生原文：需结合症状核对。');
    checks.push('late calculator reply after token change cannot fill the form or overwrite current evidence');

    await fixture(page);await fill(page);
    const noteBeforeLeave=await page.locator('#sttReviewNote').inputValue();
    await page.evaluate(()=>mode='held');await button(page,'calculate').click();await page.waitForFunction(()=>gates.length===1);
    await page.evaluate(()=>{state.currentPage='report';bridge.sync();});
    assert.equal(await page.evaluate(()=>gates[0].signal.aborted),true);
    assert.equal(await page.locator('#sttReviewNote').inputValue(),noteBeforeLeave);
    assert(await page.evaluate(()=>!!state.sttRangeReviewed));
    await page.evaluate(()=>gates[0].resolve(response(gates[0].request)));await flush(page);
    assert.equal(await page.locator('[data-sttr-mean]').count(),0);
    await page.evaluate(()=>{state.currentPage='stt';bridge.sync();});
    assert.equal(await page.locator('[data-sttr-start]').inputValue(),'50');
    assert.equal(await page.evaluate(()=>bridge.snapshotForSave().range.start_sample),10000);
    assert.equal(await page.locator('#sttReviewNote').inputValue(),noteBeforeLeave);
    checks.push('leaving cancels an in-flight calculation and ignores its reply while typed range and earlier filled doctor draft remain bound after return');

    await fixture(page);await fill(page);await page.evaluate(()=>{state.caseData.clinical_identity.analysis_revision=6;state.caseData.review_workflow.revision=6;bridge.sync();});
    assert(await button(page,'calculate').isDisabled());
    assert.equal(await page.evaluate(()=>state.sttRangeReviewed),null);
    await fixture(page,{sttReview:{case_id:'math-A',analysis_basis:'math-basis-A',analysis_revision:4}});
    assert.equal(await page.locator('[data-sttr-action="calculate"]').count(),0);
    assert.match(await page.locator('#sttRangeReview').textContent(),/逐搏/);
    checks.push('contradictory case clinical identity and absent beat revision disable calculation instead of guessing a revision');

    await fixture(page,{sttStart:175});assert.equal(await page.locator('[data-sttr-start]').inputValue(),'120');assert.equal(await page.locator('[data-sttr-end]').inputValue(),'180');
    await fill(page);await button(page,'locate').click();await flush(page);
    assert.deepEqual(await page.evaluate(()=>locates.map(x=>[x.start_sample,x.end_sample])),[[24000,36000]]);
    assert.equal(await page.evaluate(()=>calls.every(x=>x.method==='POST'&&x.url.endsWith('/stt-range'))),true);
    checks.push('initial near-tail minute is bounded to the record and locate passes the actual selected sample range; bridge performs no doctor write');

    await fixture(page);await fill(page);await page.evaluate(()=>{window.oldBridge=bridge;bridge=ECGSTTRangeBridge.mount(options);});
    assert.match(await page.evaluate(()=>{try{bridge.snapshotForSave();return '';}catch(e){return e.message;}}),/绑定/);
    await calculate(page);await button(page,'review').click();await flush(page);
    assert.match(await page.evaluate(()=>{try{bridge.snapshotForSave();return '';}catch(e){return e.message;}}),/另一份/);
    checks.push('remount cannot silently attach an unbound earlier machine-statistics line to a new snapshot');

    async function mathematical(change=null) {
      await fixture(page,{demoReadonly:true});
      await page.evaluate(change=>{
        globalThis.__CARDIOINSIGHT_MATHEMATICAL_CASE__={integrity:{mathematical_fixture:true}};
        const make=response;
        window.response=request=>{
          const value=make(request);
          value.binding.status='mathematical_raw_source_and_basis_bound';value.binding.source_kind='pure_mathematical';
          value.simulation={browser_computed:true,real_patient_inputs_read:false,clinical_validation:false};
          value.save_receipt={kind:'browser-math-content-digest-v1',digest:'e'.repeat(64)};
          if(change==='native-receipt')value.save_receipt.kind='native-stt-range-hmac-v1';
          if(change==='real-input')value.simulation.real_patient_inputs_read=true;
          if(change==='clinical')value.simulation.clinical_validation=true;
          if(change==='not-browser')value.simulation.browser_computed=false;
          if(change==='source-kind')value.binding.source_kind='patient';
          if(change==='bad-digest')value.save_receipt.digest='not-a-sha';
          if(change==='native-status')value.binding.status='caller_source_and_basis_bound';
          return value;
        };
        if(change==='no-demo')state.demoReadonly=false;
        if(change==='no-fixture')delete globalThis.__CARDIOINSIGHT_MATHEMATICAL_CASE__;
      },change);
    }
    await mathematical();await fill(page);
    let mathematicalSnapshot=await page.evaluate(()=>bridge.snapshotForSave());
    assert.equal(mathematicalSnapshot.binding.status,'mathematical_raw_source_and_basis_bound');
    assert.equal(mathematicalSnapshot.save_receipt.kind,'browser-math-content-digest-v1');
    assert.equal(mathematicalSnapshot.simulation.clinical_validation,false);
    for(const change of ['no-demo','no-fixture','real-input','clinical','not-browser','source-kind','native-receipt','bad-digest','native-status']) {
      await mathematical(change);await calculate(page);await button(page,'review').click();await flush(page);
      assert.equal(await page.evaluate(()=>state.sttRangeReviewed),null,change);
      assert.equal(await page.locator('#sttReviewNote').inputValue(),'医生原文：需结合症状核对。',change);
      assert.match(await page.locator('[data-sttr-status]').textContent(),/绑定|凭据/,change);
    }
    checks.push('mathematical evidence is allowed only with all explicit fixture/source/simulation markers and its own receipt kind; forged mixed sources cannot fill notes');

    for(const change of ['missing','math-kind','bad-digest']) {
      await fixture(page);await page.evaluate(change=>{const make=response;window.response=request=>{
        const value=make(request);if(change==='missing')delete value.save_receipt;
        if(change==='math-kind')value.save_receipt.kind='browser-math-content-digest-v1';
        if(change==='bad-digest')value.save_receipt.digest='bad';return value;
      };},change);await calculate(page);await button(page,'review').click();await flush(page);
      assert.equal(await page.evaluate(()=>state.sttRangeReviewed),null,change);
    }
    checks.push('native evidence requires the matching native HMAC receipt shape; browser receipt or missing/damaged receipt is rejected before note mutation');

    assert.deepEqual(errors,[]);assert.deepEqual(network,[]);
    const receipt={scope:'actual component and bridge; synthetic DOM/transport only',passed:true,checks,page_errors:errors,network_requests:network};
    const output=process.env.ECG_STT_BRIDGE_RECEIPT || path.join(os.tmpdir(),'ecg-stt-range-bridge.receipt.json');
    fs.writeFileSync(output,JSON.stringify(receipt,null,2)+'\n');process.stdout.write(JSON.stringify({...receipt,receipt:output},null,2)+'\n');
  } finally {await browser.close();}
})().catch(error=>{process.stderr.write(error.stack+'\n');process.exitCode=1;});
