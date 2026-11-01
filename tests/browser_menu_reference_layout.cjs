'use strict';
// Actual local UI, mathematical input only. Fixed menu labels/geometry, no images.
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const { chromium } = require(process.env.ECG_PLAYWRIGHT_CORE || 'playwright-core');
const out = process.env.ECG_MENU_REFERENCE_EVIDENCE || '/tmp/ecg-menu-reference';
const baseline = process.env.ECG_REPORT_STRIP_BASELINE;
const result = { scope: 'mathematical UI; unchanged primary/wave menus; report strip curation and read-only enlargement', baseline: Boolean(baseline), checks: [], errors: [], forbidden: [] };
(async () => {
  let browser, context;
  try {
    browser = await chromium.launch({ executablePath: process.env.ECG_CHROME, headless: true, chromiumSandbox: true });
    context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, acceptDownloads: false });
    await context.route('**/*', route => { const u = new URL(route.request().url()); if (u.origin !== 'http://127.0.0.1:8895' || /\.pdf|exports|source-report/.test(u.pathname)) { result.forbidden.push(u.pathname); return route.abort(); } if (baseline && u.pathname === '/static/js/report-workspace.js') return route.fulfill({ contentType: 'application/javascript', body: fs.readFileSync(baseline, 'utf8') }); return route.continue(); });
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
    await page.locator('.sidebar [data-page="report"]').click();
    await page.locator('#reportV2Nav [data-category="fastest"]').click();
    await page.locator('.v2-event-list [data-include]').first().check();
    await page.locator('#reportV2Nav [data-category="final"]').click();
    await page.locator('[data-rw-mini="0"] svg').waitFor(); await page.locator('[data-rw-mini="0"] svg').click({ button: 'right' });
    if (baseline) {
      await page.locator('#beatRelabelMenu').waitFor({ state: 'visible' });
      assert.match(await page.locator('#beatRelabelMenu header strong').textContent(), /只读/);
      assert.equal(await page.locator('.rw-strip-contextmenu:visible').count(), 0);
      result.checks.push('baseline-reproduces-report-strip-intercepted-by-generic-read-only-wave-menu');
      result.baseline_reproduced = true;
    } else {
      const menu = page.getByRole('menu', { name: '本条报告图条操作' });
      await menu.waitFor({ state: 'visible' });
      const original = await page.evaluate(() => JSON.stringify(state.reportComposition));
      const calls = [];
      page.on('request', r => { if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(r.method())) calls.push(r.method()); });
      async function editCurrentStrip() {
        assert.equal(await page.locator('#beatRelabelMenu:visible').count(), 0);
        assert.deepEqual(await menu.getByRole('menuitem').allTextContents(), ['3L · II / V1 / V5', '12L', '1L · II', '查看图条', '编辑图条', '重命名', '取消打印', '删除图条（可撤销）']);
        const expected = await page.locator('[data-rw-key]').first().getAttribute('data-rw-key');
        const caption = await page.locator('[data-rw-key]').first().locator('header strong').textContent();
        await menu.getByRole('menuitem', { name: '编辑图条', exact: true }).click();
        const editor = page.locator('.rw-strip-editor-dialog[open]');
        await editor.locator('[data-se-caption]').waitFor();
        const value = await editor.locator('[data-se-caption]').inputValue();
        assert(caption.endsWith(value));
        assert.equal(await page.evaluate(key => state.reportComposition.selected_events[0].event_id === key, expected), true);
        await editor.locator('[data-se-caption]').fill('未应用的数学图条草稿');
        await editor.locator('[data-se-cancel]').click();
        assert.equal(await page.evaluate(() => JSON.stringify(state.reportComposition)), original);
      }
      await editCurrentStrip();
      await page.locator('[data-rw-toggle="0"]').click();
      await page.locator('[data-rw-wave="0"] svg').waitFor();
      await page.locator('[data-rw-wave="0"] svg').click({ button: 'right' });
      await menu.waitFor({ state: 'visible' }); await editCurrentStrip();
      await page.locator('[data-rw-wave="0"]').focus(); await page.keyboard.press('Shift+F10');
      await menu.waitFor({ state: 'visible' }); await page.keyboard.press('Escape');
      await page.locator('[data-rw-tools="0"] summary').click();
      await menu.waitFor({ state: 'visible' }); await page.keyboard.press('Escape');
      assert.equal(await page.locator('[data-caption="0"]').evaluate(el => { const event = new MouseEvent('contextmenu', { bubbles: true, cancelable: true }); el.dispatchEvent(event); return event.defaultPrevented; }), false);
      result.checks.push('collapsed-and-expanded-report-wave-restore-strip-edit-menu-keyboard-and-button');
      result.checks.push('strip-editor-cancel-retains-report-and-caption-native-context-menu');
      await page.locator('[data-rw-mini="0"] svg').dblclick();
      const preview = page.locator('.rw-event-preview-dialog[open]');
      await preview.locator('[data-wave-lead="V6"]').waitFor();
      assert.equal(await preview.locator('[data-wave-lead]').count(), 12);
      assert.equal(await preview.locator('svg').getAttribute('data-columns'), '1');
      await preview.locator('svg').click({ button: 'right' });
      await page.locator('#beatRelabelMenu').waitFor({ state: 'visible' });
      assert.match(await page.locator('#beatRelabelMenu header strong').textContent(), /只读/);
      assert.equal(await page.locator('#beatRelabelMenu [data-editor-code]:not(:disabled)').count(), 0);
      await page.keyboard.press('Escape'); await preview.locator('[data-rw-close]').click();
      assert.equal(await page.evaluate(() => JSON.stringify(state.reportComposition)), original);
      assert.deepEqual(calls, []);
      result.checks.push('enlarged-twelve-lead-review-remains-read-only-no-report-or-beat-writes');
    }
    assert.deepEqual(result.errors, []); assert.deepEqual(result.forbidden, []); result.passed = true;
  } catch (e) { result.passed = false; result.error = String(e.stack || e); throw e; }
  finally { await context?.close(); await browser?.close(); fs.mkdirSync(out, { recursive: true }); fs.writeFileSync(path.join(out, 'menu-layout-browser.json'), JSON.stringify(result, null, 2) + '\n'); }
})().catch(e => { console.error(e); process.exitCode = 1; });
