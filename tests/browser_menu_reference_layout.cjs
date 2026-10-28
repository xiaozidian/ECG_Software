'use strict';
// Actual local UI, mathematical input only. Fixed menu labels/geometry, no images.
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const { chromium } = require(process.env.ECG_PLAYWRIGHT_CORE || 'playwright-core');
const out = process.env.ECG_MENU_REFERENCE_EVIDENCE || '/tmp/ecg-menu-reference';
const result = { scope: 'mathematical UI; primary list / wave body / report read-only', checks: [], errors: [], forbidden: [] };
(async () => {
  let browser, context;
  try {
    browser = await chromium.launch({ executablePath: process.env.ECG_CHROME, headless: true, chromiumSandbox: true });
    context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, acceptDownloads: false });
    await context.route('**/*', route => { const u = new URL(route.request().url()); if (u.origin !== 'http://127.0.0.1:8895' || /\.pdf|exports|source-report/.test(u.pathname)) { result.forbidden.push(u.pathname); return route.abort(); } return route.continue(); });
    const page = await context.newPage(); page.setDefaultTimeout(15000); page.on('pageerror', e => result.errors.push(e.message));
    await page.goto('http://127.0.0.1:8895/'); await page.locator('#worklistBody tr').first().getByRole('button').first().click();
    await page.waitForFunction(() => document.querySelector('#editTemplateGallery')?.dataset.readState === 'ready');
    if (process.argv.includes('--r-only')) {
      await page.waitForFunction(() => state.editWaveform?.beats?.length > 0);
      const target = await page.evaluate(() => {
        const canvas = document.querySelector('#editWaveformCanvas'), wave = state.editWaveform, g = waveMenuGeometry(canvas, wave, 'edit');
        const mid = wave.start_s + wave.duration_s / 2, b = wave.beats.reduce((a, b) => Math.abs(a.time_s - mid) < Math.abs(b.time_s - mid) ? a : b);
        return { sample: b.sample_index, x: g.l + (b.time_s - g.start) / g.duration * g.w };
      });
      await page.locator('#editWaveformCanvas').click({ button: 'right', position: { x: target.x, y: 8 } });
      await page.locator('#beatRelabelMenu').waitFor({ state: 'visible' });
      assert.equal(await page.locator('#beatRelabelMenu').getAttribute('data-context-kind'), 'beat');
      assert.equal(await page.evaluate(() => state.editSelectedSample), target.sample);
      assert.equal(await page.locator('#beatRelabelMenu .editor-primary').isVisible(), true);
      result.checks.push('continuous-R-label-hits-exact-source-beat-and-primary-type-menu');
      result.passed = true; return;
    }
    await page.locator('#editTemplateGallery .occurrence-wave').first().click({ button: 'right' });
    await page.locator('#beatRelabelMenu').waitFor({ state: 'visible' });
    const primary = await page.locator('#beatRelabelMenu .editor-primary').evaluate(node => [...node.children].map(n => {
      const r = n.getBoundingClientRect(); return { code: n.dataset.editorCode || n.querySelector('kbd')?.textContent, x: r.x, y: r.y, height: r.height };
    }));
    assert.deepEqual(primary.map(x => x.code), ['N','S','V','J','G','P','B','A','C','F','E','R','W','O','Z','M','H','Y','T','X','OTHER']);
    assert(primary.every(x => Math.abs(x.x - primary[0].x) < .1));
    assert(primary.every((x, i) => !i || x.y > primary[i - 1].y));
    result.primary_geometry = primary; result.menu_width = await page.locator('#beatRelabelMenu').evaluate(n => n.getBoundingClientRect().width);
    result.checks.push('source-thumbnail-primary-codes-visible-in-one-column-with-P-B-families');
    await page.keyboard.press('Escape');
    const selection = await page.evaluate(() => [...state.editSelectedSamples]);
    await page.locator('#editWaveformCanvas').click({ button: 'right', position: { x: 100, y: 75 } });
    await page.locator('#beatRelabelMenu').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#beatRelabelMenu').getAttribute('data-context-kind'), 'wave');
    assert.equal(await page.locator('#beatRelabelMenu [data-wave-tools]').getAttribute('open'), '');
    assert.equal(await page.locator('#beatRelabelMenu [data-beat-tools]').getAttribute('open'), null);
    assert.deepEqual(await page.evaluate(() => [...state.editSelectedSamples]), selection);
    await page.keyboard.press('s');
    assert.equal(await page.locator('#beatEditorDialog[open]').count(), 0);
    result.checks.push('wave-body-uses-wave-operations-and-keeps-existing-beat-selection');
    await page.keyboard.press('Escape');
    await page.locator('.sidebar [data-page="report"]').click(); await page.locator('#reportV2Nav [data-category="final"]').click();
    await page.locator('[data-rw-mini="0"] svg').waitFor(); await page.locator('[data-rw-mini="0"] svg').click({ button: 'right' });
    await page.locator('#beatRelabelMenu').waitFor({ state: 'visible' });
    assert.match(await page.locator('#beatRelabelMenu header strong').textContent(), /只读/);
    assert.equal(await page.locator('#beatRelabelMenu [data-editor-code]:not(:disabled)').count(), 0);
    assert.equal(await page.locator('#beatRelabelMenu [data-wave-tools]').getAttribute('open'), '');
    assert.equal(await page.locator('#beatRelabelMenu [data-beat-tools]').getAttribute('open'), null);
    result.checks.push('report-wave-keeps-read-only-type-family-separate-from-wave-actions');
    assert.deepEqual(result.errors, []); assert.deepEqual(result.forbidden, []); result.passed = true;
  } catch (e) { result.passed = false; result.error = String(e.stack || e); throw e; }
  finally { await context?.close(); await browser?.close(); fs.mkdirSync(out, { recursive: true }); fs.writeFileSync(path.join(out, 'menu-layout-browser.json'), JSON.stringify(result, null, 2) + '\n'); }
})().catch(e => { console.error(e); process.exitCode = 1; });
