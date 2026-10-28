'use strict';
// New scatter/lead-count regression only. Requires the isolated mathematical
// service on 8895. The prior blocked report-state script is not loaded.
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const { chromium } = require(process.env.ECG_PLAYWRIGHT_CORE || 'playwright-core');
const out = path.resolve(process.env.ECG_UI_GEOMETRY_EVIDENCE || '/tmp/ecg-ui-geometry');
const base = process.env.ECG_UI_GEOMETRY_URL || 'http://127.0.0.1:8895';
const reportOnly = process.argv.includes('--report-only');
const result = { scope: 'new scatter and report lead geometry; isolated mathematical backend', reportOnly, checks: [], errors: [], forbidden: [], timings: [] };
(async () => {
  let browser, context;
  fs.mkdirSync(out, { recursive: true });
  try {
    browser = await chromium.launch({ headless: true, executablePath: process.env.ECG_CHROME, chromiumSandbox: true });
    context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, acceptDownloads: false });
    await context.route('**/*', route => {
      const u = new URL(route.request().url());
      if (u.origin !== base || /\.pdf(?:$|\?)|\/exports?\b|source-report|report-images/i.test(u.pathname)) {
        result.forbidden.push(u.origin + u.pathname); return route.abort();
      }
      return route.continue();
    });
    const page = await context.newPage(); page.setDefaultTimeout(15000);
    page.on('pageerror', e => result.errors.push(e.message));
    page.on('download', () => result.forbidden.push('browser download'));
    await page.addInitScript(() => {
      window.print = () => { throw Error('Printing prohibited in geometry verification'); };
      HTMLAnchorElement.prototype.click = function () { if (this.download) throw Error('Downloads prohibited'); HTMLElement.prototype.click.call(this); };
    });
    const start = Date.now(); await page.goto(base + '/');
    await page.getByRole('button', { name: '开始复核', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('#editTemplateGallery')?.dataset.readState === 'ready' && !!state.editScatterData);
    result.timings.push({ entry: 'mathematical-case-first-template', ms: Date.now() - start });
    if (!reportOnly) {
    await page.evaluate(() => {
      const original = drawTemplateScatterPoints;
      drawTemplateScatterPoints = function (ctx, data, ...args) {
        const arc = ctx.arc; let count = 0;
        ctx.arc = function (...v) { count++; return arc.apply(this, v); };
        try { return original.call(this, ctx, data, ...args); }
        finally { ctx.arc = arc; window.lastScatterDrawCount = count; }
      };
      renderEditScatter();
    });
    const initial = await page.evaluate(() => ({ active: state.editScatterFilterActive, total: state.editScatterData.points.length, drawn: lastScatterDrawCount }));
    assert.equal(initial.active, false); assert.equal(initial.drawn, initial.total); assert(initial.total > 0);
    result.initial = initial;
    for (const code of ['S', 'V', 'N', 'other']) {
      const t = Date.now(); await page.locator('[data-occ-type="' + code + '"]').click();
      await page.waitForFunction(code => state.editScatterFilterActive && state.editSelectedClass === 'source-' + code && document.querySelector('#editTemplateGallery')?.dataset.readState === 'ready', code);
      const observation = await page.evaluate(code => {
        renderEditScatter(); const points = state.editScatterData.points;
        const expected = points.filter(p => code === 'other' ? !['N', 'S', 'V'].includes(p.class_code || editSourceCode(p)) : (p.class_code || editSourceCode(p)) === code);
        return { code, expected: expected.length, drawn: lastScatterDrawCount, visible: points.filter(editScatterVisibility()).map(p => p.sample_index), expectedSamples: expected.map(p => p.sample_index) };
      }, code);
      assert.equal(observation.drawn, observation.expected); assert.deepEqual(observation.visible, observation.expectedSamples);
      delete observation.visible; delete observation.expectedSamples;
      result.checks.push(observation); result.timings.push({ entry: 'category-' + code, ms: Date.now() - t });
    }
    await page.locator('[data-lasso-clear]').first().click();
    await page.waitForFunction(() => !state.editScatterFilterActive);
    const cleared = await page.evaluate(() => { renderEditScatter(); return { drawn: lastScatterDrawCount, total: state.editScatterData.points.length, selection: ECGLinkedSelection.snapshot().kind }; });
    assert.equal(cleared.drawn, cleared.total); assert.equal(cleared.selection, 'none');
    result.checks.push('clear-restores-all-categories-and-clears-selection');
    }

    await page.locator('.sidebar [data-page="report"]').click();
    await page.locator('#reportV2Nav [data-category="fastest"]').waitFor();
    await page.locator('.v2-event-list [data-include]').first().check();
    await page.locator('#reportV2Nav [data-category="final"]').click();
    await page.locator('[data-rw-mini="0"] svg').waitFor();
    async function geometry() {
      return page.locator('[data-rw-mini="0"] svg').evaluate(svg => {
        const group = svg.querySelector('[data-wave-lead="II"]'), poly = group.querySelector('polyline'), matrix = poly.getScreenCTM();
        const card=svg.closest('.rw-strip').getBoundingClientRect();
        return { count: svg.querySelectorAll('[data-wave-lead]').length, width: card.width, height: card.height,
          containerHeight: svg.parentElement.getBoundingClientRect().height, xMatrix: matrix.a, yMatrix: matrix.d,
          rowHeight: svg.dataset.fixedRowHeight, sourceStart: svg.dataset.sourceStart, sourceDuration: svg.dataset.sourceDuration,
          sampleRate: svg.dataset.sampleRate, stride: svg.dataset.stride, columns: svg.dataset.columns,
          gain: Number(group.dataset.waveScale),
          x: Array.from(poly.points, p => p.x) };
      });
    }
    async function choose(action) {
      await page.locator('[data-rw-tools="0"] summary').click();
      const index = { three: 0, all: 1, one: 2 }[action];
      await page.locator('.rw-strip-contextmenu [data-context-action="' + index + '"]').click();
      await page.locator('[data-rw-mini="0"] svg').waitFor();
      await page.waitForFunction(n => document.querySelector('[data-rw-mini="0"] svg')?.querySelectorAll('[data-wave-lead]').length === n, { one: 1, three: 3, all: 12 }[action]);
      return geometry();
    }
    const three = await choose('three'); const one = await choose('one'); const twelve = await choose('all');
    result.report_geometry = Object.fromEntries(Object.entries({ three, one, twelve }).map(([key, value]) => { const { x, ...metadata } = value; return [key, metadata]; }));
    for (const current of [one, twelve]) {
      assert(Math.abs(current.gain - three.gain) < 1e-8, 'native diagnostic gain must remain constant');
      assert(Math.abs(current.width - three.width) < .1, 'lead count must not change card width');
      assert(Math.abs(current.height - three.height) < .1, 'lead count must not change thumbnail card height');
      assert.equal(current.containerHeight,144);assert(Math.abs(current.xMatrix-current.yMatrix)<1e-6,'thumbnail preview must scale uniformly');
      assert.equal(current.x.length, three.x.length);
      assert(current.x.every((x, i) => Math.abs(x - three.x[i]) < .1), 'native diagnostic time coordinates must remain constant');
      for (const key of ['sourceStart', 'sourceDuration', 'sampleRate', 'stride']) assert.equal(current[key], three[key]);
      assert.equal(current.columns, '1'); assert.equal(current.rowHeight, '64');
    }
    for (const current of [three, one, twelve]) { delete current.x; delete current.values; }
    result.report_geometry = { three, one, twelve };
    const expected = await page.evaluate(() => structuredClone(state.reportComposition.selected_events));
    await page.waitForFunction(() => !state.reportSaving && !state.reportDirty);
    await page.reload(); await page.locator('#worklistBody tr').first().getByRole('button').first().click();
    await page.waitForFunction(() => !!state.caseData && !state.caseLoading);
    await page.locator('.sidebar [data-page="report"]').click();
    await page.locator('#reportV2Nav [data-category="final"]').click();
    await page.locator('[data-rw-mini="0"] svg').waitFor();
    assert.deepEqual(await page.evaluate(() => structuredClone(state.reportComposition.selected_events)), expected);
    const reopened = await geometry();
    assert.equal(reopened.count, 12); assert(Math.abs(reopened.gain - twelve.gain) < 1e-8);
    result.checks.push('report-1-3-12-leads-equal-thumbnail-frame-uniform-scale-and-autosave-reopen-keep-native-time-gain-and-source-samples');
    assert.deepEqual(result.errors, []); assert.deepEqual(result.forbidden, []);
    result.passed = true;
  } catch (e) { result.passed = false; result.error = String(e.stack || e); throw e; }
  finally {
    await context?.close(); await browser?.close(); result.browser_closed = true;
    fs.writeFileSync(path.join(out, 'browser-results.json'), JSON.stringify(result, null, 2) + '\n');
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
