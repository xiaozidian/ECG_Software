'use strict';
// Existing local mathematical service only; no patient files or PDF paths.
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const { chromium } = require(process.env.ECG_PLAYWRIGHT_CORE || 'playwright-core');
const out = process.env.ECG_AMPLITUDE_EVIDENCE;
const baseline = process.env.ECG_AMPLITUDE_BASELINE;
const result = { scope: 'mathematical continuous amplitude and report distributions', baseline: Boolean(baseline), checks: [], errors: [], forbidden: [] };
(async () => {
  let browser, context;
  try {
    browser = await chromium.launch({ executablePath: process.env.ECG_CHROME, headless: true, chromiumSandbox: true });
    context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, acceptDownloads: false });
    await context.route('**/*', route => {
      const u = new URL(route.request().url());
      if (u.origin !== 'http://127.0.0.1:8895' || /\.pdf|exports|source-report/.test(u.pathname)) { result.forbidden.push(u.pathname); return route.abort(); }
      if (baseline && ['app.js', 'clinical-review-tools.js', 'clinical-ui.js'].some(n => u.pathname === '/static/js/' + n)) return route.fulfill({ contentType: 'application/javascript', body: fs.readFileSync(path.join(baseline, path.basename(u.pathname) + '.before'), 'utf8') });
      return route.continue();
    });
    const page = await context.newPage(); page.setDefaultTimeout(15000); page.on('pageerror', e => result.errors.push(e.message));
    page.on('download', () => result.forbidden.push('download'));
    await page.goto('http://127.0.0.1:8895/'); await page.locator('#worklistBody tr').first().getByRole('button').first().click();
    await page.waitForFunction(() => state.editWaveform?.leads && document.querySelector('#editTemplateGallery')?.dataset.readState === 'ready');
    result.amplitude = await page.evaluate(() => {
      const canvas = document.querySelector('#editWaveformCanvas'), original = state.editWaveform;
      const make = factor => ({ ...original, leads: Object.fromEntries(Object.keys(original.leads).map(name => [name, Array.from({ length: 4000 }, (_, i) => Math.sin(i * .08) * (name === 'II' ? factor : name === 'V5' ? factor * .8 : 100))])) });
      const low = make(100), high = make(5000), key = wave => typeof editWaveDomainKey === 'function' ? editWaveDomainKey(wave) : JSON.stringify([state.caseId, wave.filter, 'edit']);
      state.editWaveform = low; ECGReviewTools.waveDomain(low, key(low), true); delete canvas._editAmplitudeLock;
      const ctx = canvas.getContext('2d'), stroke = ctx.stroke; let traces = 0;
      ctx.stroke = function (...args) { if (['#1d3944', '#526873'].includes(this.strokeStyle)) traces++; return stroke.apply(this, args); };
      function draw(wave) {
        state.editWaveform = wave; traces = 0; const before = JSON.stringify(wave); renderEditWaveform();
        const scales = JSON.parse(canvas.dataset.waveScales), baselines = JSON.parse(canvas.dataset.waveBaselines), height = canvas.getBoundingClientRect().height;
        const top = 27, row = (height - 51) / scales.length;
        const complete = Object.values(wave.leads).every((values, j) => values.every(v => baselines[j] - v * scales[j] >= top + j * row + 6 - .1 && baselines[j] - v * scales[j] <= top + (j + 1) * row - 6 + .1));
        return { traces, scales, baselines, height, backingCssHeight: canvas.height / Math.min(devicePixelRatio || 1, 2), complete, sourceUnchanged: before === JSON.stringify(wave), start: canvas.dataset.waveStart, duration: canvas.dataset.waveDuration, width: canvas.dataset.waveWidth, note: document.querySelector('#editWaveMeta').textContent, scrollHeight: canvas.parentElement.scrollHeight, slotHeight: canvas.parentElement.clientHeight };
      }
      try {
        const a = draw(low), b = draw(high), shifted = { ...high, start_s: high.start_s + 20, beats: (high.beats || []).map(x => ({ ...x, time_s: x.time_s + 20, sample_index: x.sample_index + 4000 })) }, c = draw(shifted), d = draw(low);
        return { low: a, high: b, panned: c, returned: d };
      } finally { ctx.stroke = stroke; state.editWaveform = original; ECGReviewTools.waveDomain(original, key(original), true); delete canvas._editAmplitudeLock; renderEditWaveform(); }
    });
    const amp = result.amplitude;
    if (baseline) { assert.equal(amp.high.traces, 1); assert.equal(amp.high.complete, false); result.checks.push('baseline-II-and-V5-hidden-after-larger-window'); }
    else {
      assert.equal(amp.high.traces, 3); assert.equal(amp.high.complete, true); assert.equal(amp.panned.complete, true);
      assert.deepEqual(amp.low.scales, amp.high.scales); assert.deepEqual(amp.high.scales, amp.panned.scales); assert.deepEqual(amp.panned.scales, amp.returned.scales);
      assert.equal(amp.high.width, amp.low.width); assert.equal(amp.high.duration, amp.low.duration);
      assert(amp.high.height > amp.low.height); assert(amp.high.scrollHeight > amp.high.slotHeight);
      assert(Math.abs(amp.high.height - amp.high.backingCssHeight) < 1);
      assert.match(amp.high.note, /超出基准幅度.*原增益/); assert(amp.high.sourceUnchanged && amp.panned.sourceUnchanged);
      result.checks.push('all-three-traces-visible-full-extrema-fixed-gain-pan-time-source-and-CSS-ratio');
    }
    await page.locator('.sidebar [data-page="report"]').click(); await page.locator('#reportV2Nav [data-category="V"]').click();
    await page.locator('.v2-candidate-distributions').waitFor();
    const panel = page.locator('.v2-candidate-distributions');
    if (baseline) { assert.equal(await panel.evaluate(n => n.open), false); result.checks.push('baseline-report-distributions-default-collapsed'); }
    else {
      assert.equal(await panel.evaluate(n => n.open), true);
      assert.equal(await panel.locator('.rw-bars').count(), 2);
      for (const chart of await panel.locator('.rw-bars').all()) { assert(await chart.isVisible()); assert((await chart.boundingBox()).height >= 35); }
      await panel.locator('[data-pattern-bin]').first().click(); await page.waitForFunction(() => document.querySelector('.v2-candidate-distributions')?.open);
      assert.equal(await page.locator('.v2-candidate-distributions .rw-bars').count(), 2);
      await page.locator('.v2-candidate-distributions summary').click();
      await page.locator('#reportV2Nav [data-category="S"]').click(); await page.waitForFunction(() => document.querySelector('.v2-candidate-distributions')?.open);
      await page.locator('#reportV2Nav [data-category="V"]').click(); await page.waitForFunction(() => document.querySelector('.v2-candidate-distributions')?.open === false);
      await page.locator('.v2-candidate-distributions summary').click();
      await page.locator('.v2-event-list [data-include]').first().check();
      await page.locator('#reportV2Nav [data-category="final"]').click(); await page.locator('[data-rw-mini="0"] svg').waitFor();
      await page.locator('[data-rw-mini="0"] svg').click({ button: 'right' });
      await page.getByRole('menu', { name: '本条报告图条操作' }).getByRole('menuitem', { name: '编辑图条', exact: true }).click();
      await page.locator('.rw-strip-editor-dialog[open] [data-se-caption]').waitFor(); await page.locator('[data-se-cancel]').click();
      result.checks.push('default-charts-visible-filter-and-category-collapse-retained-report-strip-menu-preserved');
    }
    assert.deepEqual(result.errors, []); assert.deepEqual(result.forbidden, []); result.passed = true;
  } catch (e) { result.passed = false; result.error = String(e.stack || e); throw e; }
  finally { await context?.close(); await browser?.close(); fs.mkdirSync(out, { recursive: true }); fs.writeFileSync(path.join(out, 'browser-results.json'), JSON.stringify(result, null, 2) + '\n'); }
})().catch(e => { console.error(e); process.exitCode = 1; });
