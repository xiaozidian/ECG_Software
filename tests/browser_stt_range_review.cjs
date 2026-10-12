'use strict';
// Offline Chromium contract checks of the actual ST-T range component and CSS.
// Only mathematical response fixtures are used. Every network request is aborted.
// This verifies component rendering and ownership, not waveform/ST calculations.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.ECG_PLAYWRIGHT_CORE || process.env.PLAYWRIGHT_CORE || 'playwright-core');
const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const script = read('static/js/stt-range-review.js');
const css = read('static/css/stt-range-review.css');
const checks = [], network = [], pageErrors = [];

async function install(page) {
  await page.setContent('<!doctype html><html lang="zh"><head><meta charset="utf-8"></head>' +
    '<body><main><textarea id="doctor-note">Synthetic doctor note retained.</textarea>' +
    '<output id="cursor">ISO=0.34; J=0.52; measurement=60</output><section id="host"></section></main></body></html>');
  await page.addStyleTag({content: '*{box-sizing:border-box}body{margin:0;padding:16px;font:14px system-ui}' +
    'main{max-width:1600px;margin:auto;min-width:0}textarea{display:block;width:100%;margin-bottom:8px}' + css});
  await page.addScriptTag({content: script});
  await page.evaluate(() => {
    const clone = x => JSON.parse(JSON.stringify(x));
    window.fixtureBasis = {analysis_basis: 'math-source-A', analysis_revision: 4,
      case_id: 'synthetic-sttr-A', beat_revision: 2};
    window.calls = []; window.gates = []; window.reviews = []; window.locations = [];
    window.activeId = fixtureBasis.case_id; window.current = true; window.mode = 'immediate';
    window.apiCalls = []; window.reviewError = false; window.callbackMode = 'immediate';
    window.reviewGates = []; window.locationGates = [];
    window.makeResponse = request => {
      const duration = (request.end_sample - request.start_sample) / 200;
      return {
        schema_version: 'stt-range-mean-v1', scope: clone(request.scope),
        range: {start_sample: request.start_sample, end_sample: request.end_sample,
          start_s: request.start_sample / 200, end_s: request.end_sample / 200,
          duration_s: duration, half_open: true},
        method_profile: {id: 'raw-200hz-fixed16s-st-perbeat-mean-v1', sample_rate_hz: 200,
          measurement_ms: request.measurement_ms, baseline_offsets_samples: [-40,-36,-32,-28,-24],
          st_window_offsets_samples: [-2,-1,0,1,2],
          aggregate: 'arithmetic_mean_of_used_per_beat_st_minus_baseline',
          j_basis: 'fixed_16s_machine_estimate_after_explicit_masks',
          quality_note: 'Synthetic coverage is not a signal-quality verdict.',
          unit_label: 'u', calibration_verified: false},
        counts: {detected_count: 4, used_count: 3, excluded_count: 1, missing_count: 0,
          reason_counts: {synthetic_mask: 1}},
        mask_reason_counts: [{kind: 'exclusion', reason: 'Synthetic exclusion',
          origin: 'annotation', review_status: 'pending', beat_count: 1}],
        coverage: {requested_duration_s: duration, source_coverage_s: duration,
          explicit_excluded_s: 1, explicit_missing_s: 0, engineering_eligible_block_coverage_s: duration - 1,
          engineering_eligible_block_coverage_pct: (duration - 1) / duration * 100,
          used_anchor_span_s: 2, max_used_anchor_gap_s: 1, coverage_is_signal_quality: false},
        leads: request.leads.map(lead => ({lead, mean_units: lead === 'II' ? 0 : lead === 'V1' ? -5 : 7,
          used_count: 3, excluded_count: 1, missing_count: 0, reason_counts: {synthetic_mask: 1}})),
        exclusions: {digest: 'synthetic-exclusions', intervals: []}, results_digest: 'synthetic-result'
      };
    };
    const responseFor = (request, responseMode = window.mode) => {
      const result = makeResponse(request);
      if (responseMode === 'extra-scope') result.scope.extra = 'must-reject';
      if (responseMode === 'missing-scope') delete result.scope.beat_revision;
      if (responseMode === 'wrong-case') result.scope.case_id = 'synthetic-sttr-B';
      if (responseMode === 'wrong-basis') result.scope.analysis_basis = 'math-source-B';
      if (responseMode === 'wrong-profile') result.method_profile.id = 'synthetic-unbound-profile';
      if (responseMode === 'wrong-global-count') result.counts.detected_count = 5;
      if (responseMode === 'wrong-lead-count') result.leads.find(row => row.lead === 'V5').used_count = 2;
      if (responseMode === 'wrong-baseline-offsets') result.method_profile.baseline_offsets_samples[0] = -39;
      if (responseMode === 'wrong-st-offsets') result.method_profile.st_window_offsets_samples[4] = 3;
      if (responseMode === 'wrong-j-basis') result.method_profile.j_basis = 'synthetic-unbound-landmark';
      if (responseMode === 'wrong-start-seconds') result.range.start_s += 0.005;
      if (responseMode === 'wrong-end-seconds') result.range.end_s += 0.005;
      if (responseMode === 'wrong-duration-seconds') result.range.duration_s += 0.005;
      if (responseMode === 'no-used' || responseMode === 'zero-used-non-null') {
        Object.assign(result.counts, {used_count: 0, missing_count: 3,
          reason_counts: {synthetic_mask: 1, synthetic_missing: 3}});
        Object.assign(result.coverage, {explicit_missing_s: 3,
          engineering_eligible_block_coverage_s: result.range.duration_s - 4,
          engineering_eligible_block_coverage_pct: (result.range.duration_s - 4) / result.range.duration_s * 100,
          used_anchor_span_s: 0, max_used_anchor_gap_s: 0});
        for (const row of result.leads) Object.assign(row, {mean_units: null, used_count: 0,
          missing_count: 3, reason_counts: {synthetic_mask: 1, synthetic_missing: 3}});
      }
      if (responseMode === 'zero-used-non-null') result.leads.find(row => row.lead === 'V5').mean_units = 0;
      if (responseMode === 'positive-used-null') result.leads.find(row => row.lead === 'II').mean_units = null;
      if (responseMode === 'malicious') {
        result.method_profile.quality_note = '<img src="https://invalid.example/note" onerror="window.injected=2">';
        result.counts.reason_counts = {'<img src="https://invalid.example/reason" onerror="window.injected=3">': 1};
        result.mask_reason_counts[0].reason = '数学排除<script>window.injected=4</script>';
      }
      if (responseMode === 'late-marker') result.leads[0].mean_units = 98765;
      return result;
    };
    window.mountFixture = (options = {}) => {
      const id = options.id || fixtureBasis.case_id, basis = clone(options.basis || fixtureBasis);
      window.activeId = id; window.current = true;
      const transport = async (request, {signal} = {}) => {
        calls.push({request: clone(request), signal});
        if (window.mode === 'error') throw Error('Synthetic transient calculation failure');
        if (window.mode === 'held') return new Promise((resolve, reject) =>
          gates.push({request: clone(request), signal, resolve, reject}));
        return responseFor(request);
      };
      const api = async (url, init = {}) => {
        apiCalls.push({url, method: init.method || 'GET', body: init.body ? JSON.parse(init.body) : null,
          signal: init.signal});
        if (!options.apiOnly) throw Error('calculate must take precedence over api');
        return responseFor(JSON.parse(init.body));
      };
      const mountOptions = {id, basis, api, isCurrent: () => current && activeId === id,
        recordEndSample: 60000, initialRange: {start_sample: 1200, end_sample: 13200},
        initialLeads: ['II', 'V1', 'V5'], measurementMs: 60,
        onReviewed: async (result, context) => {
          reviews.push({result: clone(result), context: clone(context)});
          window.lastReviewContext = context;
          result.scope.analysis_basis = 'callback-mutation';
          if (window.callbackMode === 'held') await new Promise((resolve, reject) =>
            reviewGates.push({resolve, reject, context}));
          if (window.reviewError) throw Error('Synthetic review callback failure');
        },
        onLocate: async (range, context) => {
          locations.push({range: clone(range), request: clone(context.request), result: clone(context.result)});
          window.lastLocateContext = context; range.start_sample = -1;
          if (window.callbackMode === 'held') await new Promise((resolve, reject) =>
            locationGates.push({resolve, reject, context}));
        }};
      if (!options.apiOnly) mountOptions.calculate = transport;
      window.controller = ECGSTTRangeReview.mount(document.querySelector('#host'), mountOptions);
      return true;
    };
    window.releaseGate = (index, responseMode = 'late-marker') => {
      const gate = gates[index]; if (!gate) throw Error('No synthetic held request');
      gate.resolve(responseFor(gate.request, responseMode));
    };
    window.flush = () => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  });
}

const field = (page, name) => page.locator('[data-sttr-' + name + ']');
const action = (page, name) => page.locator('[data-sttr-action="' + name + '"]');
async function mount(page, options = {}) { await page.evaluate(options => mountFixture(options), options); }
async function calculate(page) { return await page.evaluate(() => controller.calculate()); }
async function reset(page, options = {}) {
  await page.evaluate(() => { controller?.destroy(); calls = []; gates = []; reviews = []; locations = [];
    apiCalls = []; mode = 'immediate'; current = true; injected = 0;
    callbackMode = 'immediate'; reviewError = false; reviewGates = []; locationGates = []; });
  await mount(page, options);
}
async function flush(page) { await page.evaluate(() => flush()); }
async function resultsText(page) { return await field(page, 'results').textContent(); }

(async () => {
  const browser = await chromium.launch({headless: true, chromiumSandbox: true,
    executablePath: process.env.ECG_CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  try {
    const context = await browser.newContext({viewport: {width: 1600, height: 900}, deviceScaleFactor: 1});
    await context.route('**/*', route => { network.push(route.request().method() + ' ' + route.request().url()); return route.abort(); });
    const page = await context.newPage(); page.on('pageerror', error => pageErrors.push(error.message));
    await install(page); await mount(page);

    assert.equal(await page.evaluate(() => typeof ECGSTTRangeReview.validateRange), 'function');
    assert.equal(await page.evaluate(() => typeof ECGSTTRangeReview.validateSeconds), 'function');
    assert.equal(await page.evaluate(() => ECGSTTRangeReview.LEADS.length), 12);
    assert.deepEqual(await page.evaluate(() => ECGSTTRangeReview.validateSeconds('10.005', '70.005', 60000)),
      {start_sample: 2001, end_sample: 14001});
    assert.deepEqual(await page.evaluate(() => ECGSTTRangeReview.validateSeconds('.145', '60.145', 60000)),
      {start_sample: 29, end_sample: 12029}, 'binary-inexact valid decimal must remain on the exact grid');
    assert.deepEqual(await page.evaluate(() => ECGSTTRangeReview.validateSeconds('1e1', '7e1', 60000)),
      {start_sample: 2000, end_sample: 14000}, 'exact scientific decimal inputs remain usable');
    assert.deepEqual(await page.evaluate(() => ECGSTTRangeReview.validateRange(1200, 13200, 60000)),
      {start_sample: 1200, end_sample: 13200}, 'sample-based public validation remains available');
    assert.deepEqual(await page.evaluate(() => {
      return [['10.003', '70.003'], ['0', '59.995'], ['10.004999999999','70.004999999999']].map(([start, end]) => {
        try { ECGSTTRangeReview.validateSeconds(start, end, 60000); return false; } catch (_) { return true; }
      });
    }), [true, true, true], 'off-grid seconds cannot round silently and 59.995 seconds is too short');
    const malformedBases = await page.evaluate(() => {
      const errors = ['case_id', 'analysis_basis', 'analysis_revision', 'beat_revision'].map(key => {
        const basis = {...fixtureBasis}; delete basis[key]; return basis;
      }).concat([{...fixtureBasis, beat_revision: -1}, {...fixtureBasis, analysis_revision: 4.5}]);
      let calculatorCalls = 0;
      return errors.map(basis => {
        let c;
        try {
          c = ECGSTTRangeReview.mount(document.createElement('section'), {id: fixtureBasis.case_id, basis,
            calculate: async () => { calculatorCalls++; throw Error('Malformed basis reached calculation'); }});
          return false;
        } catch (_) { return calculatorCalls === 0; } finally { c?.destroy(); }
      });
    });
    assert.deepEqual(malformedBases, [true, true, true, true, true, true]);
    checks.push('seconds enforce the 5ms grid and 60s minimum; missing mandatory basis fields and invalid revisions reject mounting');
    assert.deepEqual(await page.evaluate(() => {
      const b = fixtureBasis;
      return [ECGSTTRangeReview.scopeMatches(b, {beat_revision: 2, case_id: b.case_id,
        analysis_revision: 4, analysis_basis: b.analysis_basis}),
      ECGSTTRangeReview.scopeMatches(b, {...b, extra: 1}),
      ECGSTTRangeReview.scopeMatches(b, {analysis_basis: b.analysis_basis, analysis_revision: 4, case_id: b.case_id})];
    }), [true, false, false]);
    assert.equal(await field(page, 'start').inputValue(), '6');
    assert.equal(await field(page, 'end').inputValue(), '66');
    assert.equal(Number(await field(page, 'start').getAttribute('step')), 0.005);
    assert.equal(Number(await field(page, 'end').getAttribute('step')), 0.005);
    assert.equal(await page.locator('input[data-sttr-lead]').count(), 12);
    await action(page, 'calculate').click();
    await page.waitForFunction(() => document.querySelector('[data-sttr-mean="II"]')?.textContent.trim().startsWith('0'));
    assert.match(await page.locator('[data-sttr-mean="II"]').textContent(), /^\s*0(?:\.0+)?(?:\s|$)/);
    assert.equal((await page.locator('[data-sttr-mean="V5"]').textContent()).trim(), '7');
    assert.equal(Number((await page.locator('[data-sttr-used="V5"]').textContent()).trim()), 3);
    const request = await page.evaluate(() => calls.at(-1).request);
    assert.deepEqual(request, {scope: {analysis_basis: 'math-source-A', analysis_revision: 4,
      case_id: 'synthetic-sttr-A', beat_revision: 2}, start_sample: 1200, end_sample: 13200,
      leads: ['II', 'V1', 'V5'], measurement_ms: 60});
    assert.equal(await page.evaluate(() => apiCalls.length), 0);
    await field(page, 'start').fill('10.005'); await field(page, 'end').fill('70.005'); await calculate(page);
    assert.deepEqual(await page.evaluate(() => ({start: calls.at(-1).request.start_sample,
      end: calls.at(-1).request.end_sample})), {start: 2001, end: 14001});
    await page.evaluate(() => controller.setRange({start_sample: 1200, end_sample: 13200}));
    assert.equal(await field(page, 'start').inputValue(), '6');
    assert.equal(await field(page, 'end').inputValue(), '66');
    for (const ms of [0, 80, 60]) {
      await field(page, 'measurement').selectOption(String(ms)); await calculate(page);
      assert.equal(await page.evaluate(() => calls.at(-1).request.measurement_ms), ms);
    }
    await page.evaluate(() => { mode = 'no-used'; }); await calculate(page);
    for (const lead of ['II', 'V1', 'V5']) {
      assert.equal((await page.locator('[data-sttr-mean="' + lead + '"]').textContent()).trim(), '—');
      assert.equal(Number((await page.locator('[data-sttr-used="' + lead + '"]').textContent()).trim()), 0);
    }
    await page.evaluate(() => { mode = 'immediate'; }); await calculate(page);
    assert.equal((await action(page, 'review').textContent()).trim(), '填入复核备注');
    await action(page, 'review').click(); await flush(page);
    assert.match((await field(page, 'status').textContent()).trim(), /^统计已填入复核备注，待医生核对保存[。]?$/);
    await action(page, 'locate').click(); await flush(page);
    assert.equal(await page.evaluate(() => reviews.length), 1);
    assert.equal(await page.evaluate(() => locations.length), 1);
    assert.deepEqual(await page.evaluate(() => locations[0].range), {
      start_sample: 1200, end_sample: 13200, start_s: 6, end_s: 66, duration_s: 60, half_open: true});
    assert.equal(await page.evaluate(() => lastLocateContext.isCurrent()), true);
    assert.equal(await page.locator('#doctor-note').inputValue(), 'Synthetic doctor note retained.');
    assert.equal(await page.locator('#cursor').textContent(), 'ISO=0.34; J=0.52; measurement=60');
    assert.equal(await page.evaluate(() => controller.state().result.scope.analysis_basis), 'math-source-A');
    assert.equal(await page.evaluate(() => { activeId = 'synthetic-sttr-B'; return lastLocateContext.isCurrent(); }), false);
    await page.evaluate(() => { activeId = fixtureBasis.case_id; });
    checks.push('actual component/CSS: valid request, 0 versus missing, leads, J/ST choices and callbacks preserve sibling drafts');

    for (const invalid of [{start: '0', end: '59.995'}, {start: '10.003', end: '70.003'},
      {start: '-0.005', end: '66'}, {start: '6', end: '300.005'}]) {
      const before = await page.evaluate(() => calls.length);
      const callbacksBefore = await page.evaluate(() => reviews.length + locations.length);
      await field(page, 'start').fill(invalid.start); await field(page, 'end').fill(invalid.end);
      assert.equal(await calculate(page), null, 'invalid seconds must not return a result');
      assert.equal(await page.evaluate(() => calls.length), before, 'invalid samples must not reach calculation');
      await action(page, 'review').dispatchEvent('click'); await action(page, 'locate').dispatchEvent('click'); await flush(page);
      assert.equal(await page.evaluate(() => reviews.length + locations.length), callbacksBefore,
        'invalid seconds must not invoke callbacks');
    }
    await field(page, 'start').fill('6'); await field(page, 'end').fill('66');
    await page.locator('input[data-sttr-lead]').evaluateAll(nodes => nodes.forEach(node => {
      node.checked = false; node.dispatchEvent(new Event('change', {bubbles: true}));
    }));
    let before = await page.evaluate(() => calls.length); await calculate(page);
    assert.equal(await page.evaluate(() => calls.length), before, 'empty leads must not reach calculation');
    await page.locator('input[data-sttr-lead]').first().evaluate(node => {
      node.value = 'not-a-lead'; node.checked = true; node.dispatchEvent(new Event('change', {bubbles: true}));
    });
    await calculate(page); assert.equal(await page.evaluate(() => calls.length), before, 'invalid lead must not reach calculation');
    checks.push('short, off-grid, out-of-record seconds and invalid/empty lead requests never reach the transport');

    await reset(page); await page.evaluate(() => { mode = 'malicious'; }); await calculate(page);
    await field(page, 'details').evaluate(node => { node.open = true; });
    assert.equal(await page.locator('#host img, #host script').count(), 0);
    assert.equal(await page.evaluate(() => injected), 0);
    assert.match(await page.locator('#host').textContent(), /<img/);
    assert.match(await field(page, 'details').textContent(), /数学排除<script>window\.injected=4<\/script>/);
    checks.push('untrusted method and reason text stays literal; no injected DOM or requests');

    await reset(page); await calculate(page);
    await page.evaluate(() => { mode = 'held'; void controller.calculate(); });
    await page.waitForFunction(() => gates.length === 1);
    await action(page, 'cancel').click();
    assert.equal(await page.evaluate(() => gates[0].signal?.aborted), true);
    let preserved = await resultsText(page);
    await page.evaluate(() => releaseGate(0)); await flush(page);
    assert.equal(await resultsText(page), preserved); assert.doesNotMatch(await resultsText(page), /98765/);
    checks.push('explicit cancellation aborts the signal and ignores transport responses that arrive anyway');

    await reset(page); await calculate(page);
    await page.evaluate(() => { mode = 'held'; void controller.calculate(); });
    await page.waitForFunction(() => gates.length === 1);
    await field(page, 'start').fill('10'); await field(page, 'end').fill('70');
    assert.equal(await page.evaluate(() => gates[0].signal?.aborted), true);
    preserved = await resultsText(page);
    await page.evaluate(() => releaseGate(0)); await flush(page);
    assert.equal(await resultsText(page), preserved); assert.doesNotMatch(await resultsText(page), /98765/);
    assert.equal(await field(page, 'start').inputValue(), '10');
    assert.equal(await field(page, 'end').inputValue(), '70');
    checks.push('editing pending parameters aborts old work and late results cannot replace the edited range');

    await reset(page); await page.evaluate(() => { mode = 'held'; void controller.calculate(); });
    await page.waitForFunction(() => gates.length === 1);
    await page.evaluate(() => { window.oldController = controller; mode = 'immediate'; mountFixture(); });
    await calculate(page); preserved = await resultsText(page);
    await page.evaluate(() => releaseGate(0)); await flush(page);
    assert.equal(await resultsText(page), preserved); assert.doesNotMatch(await resultsText(page), /98765/);
    await page.evaluate(() => oldController.destroy());
    assert.equal(await resultsText(page), preserved, 'destroying an old owner must not erase its replacement');
    checks.push('remount rejects old completion and old-owner destroy cannot erase the current component');

    await reset(page); await page.evaluate(() => { mode = 'held'; void controller.calculate(); });
    await page.waitForFunction(() => gates.length === 1); await page.evaluate(() => controller.destroy());
    const afterDestroy = await page.locator('#host').innerHTML();
    await page.evaluate(() => releaseGate(0)); await flush(page);
    assert.equal(await page.locator('#host').innerHTML(), afterDestroy);
    assert.equal(await page.evaluate(() => gates[0].signal?.aborted), true);
    checks.push('destroy aborts held work and rejects late DOM updates');

    await reset(page); await page.evaluate(() => { mode = 'held'; void controller.calculate(); });
    await page.waitForFunction(() => gates.length === 1);
    await page.evaluate(() => { activeId = 'synthetic-sttr-B'; releaseGate(0); }); await flush(page);
    assert.doesNotMatch(await resultsText(page), /98765/);
    assert.equal(await page.evaluate(() => reviews.length + locations.length), 0);
    checks.push('current-case guard rejects old responses and callbacks');

    await reset(page); await page.evaluate(() => { mode = 'held'; void controller.calculate(); });
    await page.waitForFunction(() => gates.length === 1);
    await page.evaluate(() => controller.setBasis({...fixtureBasis, analysis_revision: 5}));
    preserved = await resultsText(page); await page.evaluate(() => releaseGate(0)); await flush(page);
    assert.equal(await resultsText(page), preserved);
    await page.evaluate(() => { mode = 'immediate'; }); await calculate(page);
    assert.equal(await page.evaluate(() => calls.at(-1).request.scope.analysis_revision), 5);
    for (const mismatch of ['extra-scope', 'missing-scope', 'wrong-case', 'wrong-basis']) {
      await page.evaluate(value => { mode = value; }, mismatch); await calculate(page);
      assert(await action(page, 'review').isDisabled(), mismatch + ' must not be reviewable');
      assert(await action(page, 'locate').isDisabled(), mismatch + ' must not be locatable');
    }
    checks.push('basis replacement invalidates pending work; exact scope rejects extra, missing and changed fields');

    await reset(page, {basis: {analysis_basis: 'math-source-A', analysis_revision: 4,
      case_id: 'synthetic-sttr-A', beat_revision: 2, frontend_tag: 'synthetic-owned-key'}});
    await calculate(page);
    assert.equal(await page.evaluate(() => controller.state().result.scope.frontend_tag), 'synthetic-owned-key');
    assert.equal(await page.evaluate(() => calls.at(-1).request.scope.frontend_tag), 'synthetic-owned-key');
    assert(await action(page, 'review').isEnabled());
    checks.push('additional frontend basis keys are retained and exactly echoed without requiring a server identity');

    await reset(page);
    for (const mismatch of ['wrong-profile', 'wrong-global-count', 'wrong-lead-count',
      'wrong-baseline-offsets', 'wrong-st-offsets', 'wrong-j-basis',
      'wrong-start-seconds', 'wrong-end-seconds', 'wrong-duration-seconds',
      'zero-used-non-null', 'positive-used-null']) {
      await page.evaluate(value => { mode = value; }, mismatch); await calculate(page);
      assert.equal(await resultsText(page), '', mismatch + ' must discard the response');
      assert.equal(await page.evaluate(() => controller.state().result), null);
      assert(await action(page, 'review').isDisabled()); assert(await action(page, 'locate').isDisabled());
      await action(page, 'review').dispatchEvent('click'); await action(page, 'locate').dispatchEvent('click');
      await flush(page);
      assert.equal(await page.evaluate(() => reviews.length + locations.length), 0,
        mismatch + ' must not call review or locate');
      assert.match(await field(page, 'status').textContent(), /丢弃结果/);
    }
    checks.push('wrong sample-to-seconds mapping, profile/offsets/landmark and global/lead/mean count binding discard results and block callbacks');

    await reset(page); await calculate(page); await page.evaluate(() => { callbackMode = 'held'; });
    await action(page, 'review').click(); await page.waitForFunction(() => reviewGates.length === 1);
    assert(await action(page, 'review').isDisabled()); assert(await action(page, 'locate').isDisabled());
    await action(page, 'review').dispatchEvent('click'); await action(page, 'review').dispatchEvent('click');
    await action(page, 'locate').dispatchEvent('click'); await flush(page);
    assert.equal(await page.evaluate(() => reviews.length), 1);
    assert.equal(await page.evaluate(() => locations.length), 0);
    assert.equal(await page.evaluate(() => lastReviewContext.isCurrent()), true);
    await page.evaluate(() => reviewGates[0].reject(Error('Synthetic delayed review failure'))); await flush(page);
    assert.match(await field(page, 'status').textContent(), /Synthetic delayed review failure/);
    assert(await action(page, 'review').isEnabled());
    assert.equal(await page.evaluate(() => controller.state().handedOff), false);
    await page.evaluate(() => { callbackMode = 'immediate'; }); await action(page, 'review').click(); await flush(page);
    assert.equal(await page.evaluate(() => reviews.length), 2);
    assert.equal(await page.evaluate(() => controller.state().handedOff), true);
    checks.push('pending review blocks duplicate and cross-action clicks; failed asynchronous review remains explicitly retryable');

    await reset(page); await calculate(page); await page.evaluate(() => { callbackMode = 'held'; });
    await action(page, 'review').click(); await page.waitForFunction(() => reviewGates.length === 1);
    await field(page, 'start').fill('10'); await field(page, 'end').fill('70');
    assert.equal(await page.evaluate(() => lastReviewContext.isCurrent()), false);
    await calculate(page);
    const afterNewCalculation = {results: await resultsText(page), status: await field(page, 'status').textContent()};
    await page.evaluate(() => reviewGates[0].resolve()); await flush(page);
    assert.equal(await resultsText(page), afterNewCalculation.results);
    assert.equal(await field(page, 'status').textContent(), afterNewCalculation.status);
    assert.equal(await page.evaluate(() => controller.state().request.start_sample), 2000);
    assert.equal(await page.evaluate(() => controller.state().handedOff), false);
    assert(await action(page, 'review').isEnabled());
    assert.equal(await page.locator('#doctor-note').inputValue(), 'Synthetic doctor note retained.');
    assert.equal(await page.locator('#cursor').textContent(), 'ISO=0.34; J=0.52; measurement=60');
    checks.push('parameter editing invalidates a pending callback context; old review success cannot hand off the new calculation');

    await reset(page); await calculate(page); await page.evaluate(() => { callbackMode = 'held'; });
    await action(page, 'locate').click(); await page.waitForFunction(() => locationGates.length === 1);
    await action(page, 'locate').dispatchEvent('click'); await action(page, 'review').dispatchEvent('click'); await flush(page);
    assert.equal(await page.evaluate(() => locations.length), 1);
    assert.equal(await page.evaluate(() => reviews.length), 0);
    await page.evaluate(() => locationGates[0].resolve()); await flush(page);
    assert(await action(page, 'locate').isEnabled()); assert(await action(page, 'review').isEnabled());
    checks.push('pending locate also blocks duplicates and review until its asynchronous callback settles');

    await reset(page); await page.evaluate(() => { mode = 'error'; }); await calculate(page);
    assert.match(await field(page, 'status').textContent(), /Synthetic transient calculation failure/);
    await page.evaluate(() => { mode = 'immediate'; }); await action(page, 'retry').click();
    await page.waitForFunction(() => document.querySelector('[data-sttr-mean="II"]')?.textContent.trim().startsWith('0'));
    assert.equal(await page.evaluate(() => calls.length), 2);
    await page.evaluate(() => controller.invalidate());
    assert(await action(page, 'review').isDisabled()); assert(await action(page, 'locate').isDisabled());
    checks.push('failed calculation retries explicitly; invalidated results cannot be reviewed or located');

    await reset(page, {apiOnly: true}); await calculate(page);
    const fallback = await page.evaluate(() => ({url: apiCalls[0].url, method: apiCalls[0].method,
      body: apiCalls[0].body, signal: !!apiCalls[0].signal, calls: calls.length}));
    assert.equal(fallback.method, 'POST'); assert.match(fallback.url, /stt-range/);
    assert.deepEqual(fallback.body, request); assert.equal(fallback.signal, true); assert.equal(fallback.calls, 0);
    assert.equal(await page.locator('[data-sttr-mean="V5"]').textContent(), '7');
    checks.push('read-only POST fallback uses the same request contract and cancellation signal without network');

    for (const width of [900, 1600, 2300]) {
      await page.setViewportSize({width, height: 900}); await flush(page);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
        'component CSS must retain local scrolling at width ' + width);
    }
    await context.close();
    const retina = await browser.newContext({viewport: {width: 900, height: 800}, deviceScaleFactor: 2});
    await retina.route('**/*', route => { network.push(route.request().method() + ' ' + route.request().url()); return route.abort(); });
    const retinaPage = await retina.newPage(); retinaPage.on('pageerror', error => pageErrors.push(error.message));
    await install(retinaPage); await mount(retinaPage); await calculate(retinaPage);
    assert.equal(await retinaPage.evaluate(() => devicePixelRatio), 2);
    assert.equal((await retinaPage.locator('[data-sttr-mean="II"]').textContent()).trim(), '0');
    assert(await action(retinaPage, 'review').isEnabled()); await retina.close();
    checks.push('real CSS renders at 900/1600/2300 widths and real DPR 1/2');

    assert.deepEqual(pageErrors, []); assert.deepEqual(network, []);
    console.log(JSON.stringify({scope: 'offline mathematical component contract only', passed: true,
      checks, page_errors: pageErrors, network_requests: network}, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
