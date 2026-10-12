'use strict';
// Actual Chrome DOM oracle, using only a self-contained mathematical fixture.
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const {chromium} = require(process.env.ECG_PLAYWRIGHT_CORE || process.env.PLAYWRIGHT_CORE || 'playwright-core');
const root = path.resolve(__dirname, '..');
(async () => {
  let browser; const passed = [];
  try {
    browser = await chromium.launch({executablePath: process.env.ECG_CHROME || process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true, chromiumSandbox: true});
    const page = await browser.newPage({viewport: {width: 1200, height: 900}, deviceScaleFactor: 2});
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.setContent('<!doctype html><meta charset="utf-8"><div id="wave"><canvas id="canvas" style="display:block;width:100%;height:300px" tabindex="0"></canvas></div><div id="dock"></div>');
    await page.addStyleTag({content: fs.readFileSync(path.join(root, 'static/css/rhythm-range-editor.css'), 'utf8')});
    await page.addScriptTag({content: fs.readFileSync(path.join(root, 'static/js/rhythm-range-editor.js'), 'utf8')});
    await page.evaluate(() => {
      window.current = {case_id: 'synthetic-a', caseToken: 1, analysis_basis: 'math', analysis_revision: 4,
        beat_revision: 2, workspace_epoch: 'math', sample_rate_hz: 200, duration_s: 640};
      window.value = {...current, revision: 3, document: {episodes: [], bookmarks: {fastest: 12.005}}};
      window.wave = {start_s: 10, duration_s: 20}; window.owner = {...current};
      window.calls = []; window.beatCalls = 0; window.saved = 0; window.notices = []; window.uuidCount = 0;
      window.failure = false;
      window.controller = ECGRhythmRangeEditor.mount({host: document.querySelector('#dock'), getScope: () => current,
        getSurface: canvas => ({owner_scope: owner, wave, plot: {left: 50, top: 27, width: canvas.getBoundingClientRect().width - 65, height: 249}}),
        uuid: () => 'draft-' + (++uuidCount), canWrite: () => true,
        api: async (path, options) => {
          calls.push({path, method: options.method, body: options.body});
          if (options.method === 'PUT') {
            const payload = JSON.parse(options.body); value = {...value, analysis_revision: value.analysis_revision + 1,
              revision: value.revision + 1, document: payload.document};
            if (failure) throw Error('synthetic response lost');
          }
          return structuredClone(value);
        },
        onSaved: async () => { saved++; current.analysis_revision = value.analysis_revision; owner = {...current}; },
        onBeatEditor: () => beatCalls++, onNotice: text => notices.push(text), onError: () => {}});
      document.querySelector('#canvas').addEventListener('contextmenu', event => {
        window.lastPointerX = event.clientX - event.currentTarget.getBoundingClientRect().left;
        controller.openContext(event, {canvas: event.currentTarget});
      });
    });
    const select = async (fraction, action) => {
      const box = await page.locator('#canvas').boundingBox();
      await page.mouse.click(box.x + 50 + (box.width - 65) * fraction, box.y + 100, {button: 'right'});
      const expected = await page.evaluate(() => Math.round((wave.start_s + (lastPointerX - 50) / (document.querySelector('#canvas').getBoundingClientRect().width - 65) * wave.duration_s) * 200));
      await page.locator(`.rre-menu button[data-rre="${action}"]`).click();
      return expected;
    };
    await select(0, 'start');
    await page.waitForFunction(() => controller.snapshot().draft?.base && !controller.snapshot().busy);
    const expectedEnd = await select(.5, 'end');
    assert.deepEqual(await page.evaluate(() => ({start: controller.snapshot().draft.start_sample, end: controller.snapshot().draft.end_sample_exclusive})), {start: 2000, end: expectedEnd});
    assert.equal(await page.locator('.rre-dock select').inputValue(), 'pending');
    assert.equal(await page.evaluate(() => calls.filter(x => x.method === 'PUT').length), 0); passed.push('pointer exact original grid / pending / no auto-write');
    const geometry = await page.evaluate(() => { const svg = document.querySelector('.rre-wave-overlay'); return {box: svg.getBoundingClientRect().width,
      canvas: document.querySelector('#canvas').getBoundingClientRect().width, lines: [...svg.querySelectorAll('line')].map(x => Number(x.getAttribute('x1')))}; });
    assert.equal(geometry.box, geometry.canvas); assert.deepEqual(geometry.lines, [50, 50 + (expectedEnd - 2000) / 4000 * (geometry.canvas - 65)]); passed.push('CSS coordinates under Retina / no waveform canvas redraw');
    const original = await page.locator('#canvas').evaluate(c => c.toDataURL());
    await page.locator('.rre-dock input[name=end]').fill('20.001');
    await page.locator('.rre-dock input[name=ack]').check();
    assert.equal(await page.locator('.rre-dock button[data-rre=save]').isDisabled(), true);
    assert.equal(await page.locator('.rre-dock input[name=end]').inputValue(), '20.001');
    assert.equal(await page.locator('#canvas').evaluate(c => c.toDataURL()), original); passed.push('invalid typed grid retained / old valid range cannot save');
    await page.locator('.rre-dock input[name=end]').fill('20.005'); await page.locator('.rre-dock input[name=ack]').check();
    await page.locator('.rre-dock button[data-rre=save]').click();
    await page.waitForFunction(() => !controller.pending());
    assert.equal(await page.evaluate(() => value.document.episodes[0].end_s), 20.005);
    assert.equal(await page.evaluate(() => saved), 1); passed.push('explicit save / full doc and exact half-open endpoint');
    await select(.1, 'start'); await page.waitForFunction(() => controller.snapshot().draft?.base && !controller.snapshot().busy);
    await select(.2, 'end');
    const before = await page.evaluate(() => controller.snapshot().draft.id);
    await page.evaluate(() => { wave = {start_s: 40, duration_s: 20}; controller.sync(); });
    assert.equal(await page.locator('.rre-wave-overlay line').count(), 0);
    assert.match(await page.locator('[data-rre=boundary]').textContent(), /窗口之外/); passed.push('pan retains absolute range / off-window endpoints never fabricated');
    await page.evaluate(() => { current.case_id = 'synthetic-b'; current.caseToken++; owner = {...current}; controller.sync(); });
    assert.equal(await page.locator('.rre-dock').isVisible(), false);
    await page.evaluate(() => { current.case_id = 'synthetic-a'; current.caseToken++; owner = {...current}; controller.sync(); });
    assert.equal(await page.evaluate(() => controller.snapshot().draft.id), before);
    assert.equal(await page.locator('.rre-dock input[name=start]').isDisabled(), true);
    assert.equal(await page.locator('.rre-dock button[data-rre=save]').isDisabled(), true); passed.push('case navigation retains stale draft / cannot save');
    await page.locator('.rre-dock button[data-rre=cancel]').click();
    await page.evaluate(() => { owner.case_id = 'stale'; });
    const box = await page.locator('#canvas').boundingBox();
    await page.mouse.click(box.x + 200, box.y + 80, {button: 'right'});
    assert.equal(await page.locator('.rre-menu').isVisible(), false);
    assert.equal(await page.evaluate(() => beatCalls), 0); passed.push('stale surface blocks both AF and fallback QRS edit');
    await page.evaluate(() => {
      owner = {...current}; wave = {start_s: 10, duration_s: 20};
      controller.openContext({preventDefault() {}}, {canvas: document.querySelector('#canvas'), keyboard: true});
    });
    assert.equal(await page.locator('.rre-menu button[data-rre=start]').isDisabled(), true);
    await page.locator('.rre-menu button[data-rre=manual]').click();
    await page.waitForFunction(() => controller.snapshot().draft?.base && !controller.snapshot().busy);
    await page.locator('.rre-dock input[name=start]').fill('10.005');
    await page.locator('.rre-dock input[name=end]').fill('10.010');
    assert.equal(await page.evaluate(() => controller.snapshot().draft.start_sample), 2001); passed.push('keyboard does not invent a cursor / explicit sample-grid input');
    await page.evaluate(() => { failure = true; });
    await page.locator('.rre-dock input[name=ack]').check(); await page.locator('.rre-dock button[data-rre=save]').click();
    await page.waitForFunction(() => controller.snapshot().draft?.uncertain && !controller.snapshot().busy);
    assert.equal(await page.locator('.rre-dock input[name=end]').isDisabled(), true);
    assert.equal(await page.locator('.rre-dock button[data-rre=cancel]').isDisabled(), true);
    const puts = await page.evaluate(() => calls.filter(x => x.method === 'PUT').length);
    await page.locator('.rre-dock button[data-rre=reconcile]').click(); await page.waitForFunction(() => !controller.pending());
    assert.equal(await page.evaluate(() => calls.filter(x => x.method === 'PUT').length), puts);
    assert.equal(await page.evaluate(() => saved), 2); passed.push('lost PUT response / UUID reconciliation / no duplicate write');
    for (const width of [900, 1600, 2048]) {
      await page.setViewportSize({width, height: 900});
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      const expectedStart = await select(.2, 'start'); await page.waitForFunction(() => controller.snapshot().draft?.base && !controller.snapshot().busy);
      await select(.3, 'end');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      const g = await page.evaluate(() => ({canvas: document.querySelector('#canvas').getBoundingClientRect().width,
        line: +document.querySelector('.rre-wave-overlay line').getAttribute('x1')}));
      assert.ok(Math.abs(g.line - (50 + (g.canvas - 65) * (expectedStart - 2000) / 4000)) < 1e-6);
      await page.locator('.rre-dock button[data-rre=cancel]').click();
    }
    passed.push('900 / 1600 / 2048 geometry and no horizontal overflow');
    await select(.2, 'start'); await page.waitForFunction(() => controller.snapshot().draft?.base && !controller.snapshot().busy);
    await page.evaluate(() => {
      window.underlyingEscape = 0; document.addEventListener('keydown', event => { if (event.key === 'Escape') underlyingEscape++; });
      document.querySelector('#dock').hidden = true;
    });
    await page.keyboard.press('Escape'); assert.equal(await page.evaluate(() => controller.pending()), true);
    assert.equal(await page.evaluate(() => underlyingEscape), 1);
    await page.evaluate(() => { document.querySelector('#dock').hidden = false; });
    passed.push('hidden retained draft does not intercept another page Escape');
    await page.evaluate(() => {
      controller.openContext({preventDefault() {}}, {canvas: document.querySelector('#canvas'), keyboard: true});
    });
    await page.keyboard.press('End'); assert.equal(await page.evaluate(() => document.activeElement.dataset.rre), 'close');
    await page.keyboard.press('Escape'); await page.waitForFunction(() => !controller.pending());
    assert.equal(await page.evaluate(() => underlyingEscape), 1); passed.push('menu keyboard navigation / Escape owns only the local draft');
    // Real popover plus the original QRS listener's document-bubble order.
    // Exercise the reported 900 px / DPR 1 trigger and all target geometries.
    for (const dpr of [1, 2]) for (const width of [900, 1600, 2048]) {
      const check = await browser.newPage({viewport: {width, height: 900}, deviceScaleFactor: dpr});
      check.on('pageerror', e => errors.push(e.message));
      try {
        await check.setContent('<!doctype html><meta charset="utf-8"><div><canvas id="canvas" style="display:block;width:100%;height:300px" tabindex="0"></canvas></div><div id="dock"></div><div id="beatRelabelMenu" hidden popover="manual"><button type="button">原 QRS 编辑菜单</button></div><dialog id="legacyDialog"><input value="existing doctor draft"></dialog>');
        await check.addStyleTag({content: fs.readFileSync(path.join(root, 'static/css/rhythm-range-editor.css'), 'utf8')});
        await check.addScriptTag({content: fs.readFileSync(path.join(root, 'static/js/rhythm-range-editor.js'), 'utf8')});
        await check.evaluate(() => {
          const scope = {case_id: 'synthetic-420', caseToken: 1, analysis_basis: 'math', analysis_revision: 4,
            beat_revision: 2, workspace_epoch: 'math', sample_rate_hz: 200, duration_s: 420};
          window.oldQrsEsc = 0; window.externalHandled = false;
          document.addEventListener('keydown', event => {
            if (externalHandled && event.key === 'Escape') event.preventDefault();
          }, true);
          window.controller = ECGRhythmRangeEditor.mount({host: document.querySelector('#dock'), getScope: () => scope,
            getSurface: canvas => ({owner_scope: scope, wave: {start_s: 10, duration_s: 20},
              plot: {left: 50, top: 27, width: canvas.getBoundingClientRect().width - 65, height: 249}}),
            uuid: () => 'matrix-draft', canWrite: () => true,
            api: async () => ({...scope, revision: 3, document: {episodes: [], bookmarks: {}}}),
            onBeatEditor: () => {
              const original = document.querySelector('#beatRelabelMenu'); original.hidden = false;
              original.showPopover(); original.querySelector('button').focus();
            }});
          document.querySelector('#canvas').addEventListener('contextmenu', event => controller.openContext(event, {canvas: event.currentTarget}));
          // This represents app.js's original document keydown listener and
          // closeBeatRelabelMenu -> repaint -> current-scope sync pipeline.
          document.addEventListener('keydown', event => {
            const original = document.querySelector('#beatRelabelMenu');
            if (event.key === 'Escape' && !original.hidden) {
              event.preventDefault(); original.hidePopover(); original.hidden = true;
              oldQrsEsc++; controller.sync();
            }
          });
        });
        const mark = async (fraction, action) => {
          const box = await check.locator('#canvas').boundingBox();
          await check.mouse.click(box.x + 50 + (box.width - 65) * fraction, box.y + 100, {button: 'right'});
          await check.locator(`.rre-menu button[data-rre="${action}"]`).click();
        };
        const draft = async () => {
          await mark(.2, 'start'); await check.waitForFunction(() => controller.snapshot().draft?.base && !controller.snapshot().busy);
          await mark(.4, 'end');
          await check.locator('.rre-dock select[name=status]').selectOption('confirmed');
          await check.locator('.rre-dock textarea[name=note]').fill('AF endpoints, note and status must survive QRS Escape');
        };
        await draft();
        const originalDraft = await check.evaluate(() => controller.snapshot().draft);
        await mark(.3, 'beat');
        assert.equal(await check.locator('#beatRelabelMenu').isVisible(), true, `${width} / DPR ${dpr}`);
        await check.keyboard.press('Escape');
        assert.equal(await check.locator('#beatRelabelMenu').isVisible(), false);
        assert.deepEqual(await check.evaluate(() => controller.snapshot().draft), originalDraft);
        assert.equal(await check.evaluate(() => oldQrsEsc), 1);
        await check.keyboard.press('Escape'); await check.waitForFunction(() => !controller.pending());
        assert.equal(await check.evaluate(() => oldQrsEsc), 1);
        await draft();
        const beforeModal = await check.evaluate(() => controller.snapshot().draft);
        await check.evaluate(() => document.querySelector('#legacyDialog').showModal());
        await check.keyboard.press('Escape');
        await check.waitForFunction(() => !document.querySelector('#legacyDialog').open);
        assert.deepEqual(await check.evaluate(() => controller.snapshot().draft), beforeModal);
        await check.evaluate(() => { externalHandled = true; });
        await check.keyboard.press('Escape');
        assert.deepEqual(await check.evaluate(() => controller.snapshot().draft), beforeModal);
        await check.evaluate(() => { externalHandled = false; });
        await check.keyboard.press('Escape'); await check.waitForFunction(() => !controller.pending());
        assert.equal(await check.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
        await check.evaluate(() => controller.dispose());
      } finally { await check.close(); }
    }
    passed.push('original QRS Escape first / AF draft conserved / next Escape cancels AF — 900, 1600, 2048 × DPR 1, 2');
    passed.push('existing modal owns Escape / AF endpoints, note and status preserved — six geometries');
    passed.push('capture-time defaultPrevented respected / visible AF cancel remains available — six geometries');
    await page.evaluate(() => controller.dispose()); assert.equal(await page.locator('.rre-dock,.rre-menu,.rre-wave-overlay').count(), 0);
    assert.deepEqual(errors, []); passed.push('dispose removes owned UI / no browser exceptions');
    console.log(JSON.stringify({passed: passed.length, scenarios: passed}));
  } finally { if (browser) await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
