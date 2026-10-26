'use strict';
// Offline Chromium verification of repository ST-T rendering and context handlers.
// Every waveform is mathematical. All network requests are aborted. The fixture
// replaces only loading/fullscreen transport; native requests are checked separately.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const {chromium} = require(process.env.ECG_PLAYWRIGHT_CORE || 'playwright-core');
const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const hash = value => crypto.createHash('sha256').update(value).digest('hex');
const app = read('static/js/app.js');
const declarations = [...app.matchAll(/^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(/gm)];
function actualFunction(name) {
  const index = declarations.findIndex(match => match[1] === name);
  assert(index >= 0, `Repository function is missing: ${name}`);
  return app.slice(declarations[index].index, declarations[index + 1]?.index ?? app.length);
}
const functionNames = [
  'escapeHtml', 'canvasContext', 'sttVisibleLeads', 'sttReviewLayout',
  'sttLandmarkFractions', 'sttMeasurementValues', 'renderSttMeasurements',
  'renderSttReviewContext', 'renderSttWaveform', 'nudgeSttMarker',
  'bindSttInteraction', 'openSttTwelveLead', 'finishWaveformFullscreenExit',
];
const functions = functionNames.map(actualFunction).join('\n');
const template = read('templates/index.html');
const start = template.indexOf('<section class="page" id="page-stt"');
const end = template.indexOf('<section class="page" id="page-events"', start);
assert(start >= 0 && end > start, 'Repository ST-T section is missing');
const section = template.slice(start, end).replace('class="page"', 'class="page active stt-review-layout"');
const styleNames = ['app.css', 'stt-review-layout.css', 'chart-inspection.css', 'desktop-workspace.css'];
const styles = styleNames.map(name => read('static/css/' + name)).join('\n');
const chart = read('static/js/chart-inspection.js'),tools = read('static/js/clinical-review-tools.js');
const layout = read('static/js/stt-review-layout.js');
const artifactRoot = process.env.ECG_STT_EVIDENCE
  ? path.resolve(process.env.ECG_STT_EVIDENCE)
  : fs.mkdtempSync(path.join(os.tmpdir(), 'ecg-stt-twelve-'));
fs.mkdirSync(artifactRoot, {recursive: true});
const receiptPath = path.join(artifactRoot, 'stt-twelve-readability.json');
const html = '<!doctype html><html><head><meta charset="utf-8"><style>' + styles +
  '</style></head><body><main id="mainContent" class="main-shell"><div class="safety-banner hidden"></div>' + section +
  '</main><div id="waveformCard" hidden></div><select id="filterSelect" hidden><option value="display">display</option><option value="raw">raw</option></select></body></html>';

(async () => {
  const browser = await chromium.launch({headless: true, chromiumSandbox: true,
    executablePath: process.env.ECG_CHROME || chromium.executablePath()});
  const results = [], pageErrors = [], network = [];
  try {
    for (const dpr of [1, 2]) {
      const context = await browser.newContext({viewport: {width: 1600, height: 900}, deviceScaleFactor: dpr});
      const page = await context.newPage();
      page.on('pageerror', error => pageErrors.push(error.message));
      await page.route('**/*', route => {network.push(route.request().method()); return route.abort();});
      await page.setContent(html);
      await page.evaluate(({chart, layout, functions,tools}) => {
        globalThis.$ = (selector, parent = document) => parent.querySelector(selector);
        globalThis.$$ = (selector, parent = document) => [...parent.querySelectorAll(selector)];
        globalThis.UI_FONT = 'Arial';
        globalThis.ALL_LEADS = ['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6'];
        globalThis.__fullLeads = Object.freeze(Object.fromEntries(ALL_LEADS.map((lead, k) => {
          const samples = Array.from({length: 2000}, (_, i) => ((i % 97) - 48) * (k + 1));
          samples[701] = 400 * (k + 1); // Not in the four-sample amplitude-estimation subset.
          samples[1183] = -380 * (k + 1);
          return [lead, Object.freeze(samples)];
        })));
        globalThis.__selected = ['II', 'V1', 'V5'];
        globalThis.__wave = leads => ({start_s: 120, duration_s: 10, sample_rate_hz: 200,
          display_sample_rate_hz: 200, stride: 1, leads: Object.fromEntries(leads.map(lead => [lead, __fullLeads[lead]])), beats: []});
        globalThis.state = {caseId: 'synthetic-stt', caseRequestId: 7, currentPage: 'stt',
          caseData: {technical: {duration_seconds_raw: 600}}, sttStart: 120, sttDuration: 10,
          sttLeads: __selected.slice(), leads: __selected.slice(), sttIsoFraction: .34,
          sttJFraction: .52, sttMeasurementMs: 60, sttWaveform: __wave(__selected),
          start: 40, duration: 8, filter: 'display', waveformExpanded: false,
          waveformFullscreenFallback: false, waveformFullscreenGeneration: 0,
          sttReview: {automatic_candidates: {enabled: false}}, editFullscreenReturn: null};
        globalThis.__paint = {count: 0, paths: [], copies: 0};
        const begin = CanvasRenderingContext2D.prototype.beginPath;
        const move = CanvasRenderingContext2D.prototype.moveTo;
        const line = CanvasRenderingContext2D.prototype.lineTo;
        const stroke = CanvasRenderingContext2D.prototype.stroke;
        const clear = CanvasRenderingContext2D.prototype.clearRect;
        const copy = CanvasRenderingContext2D.prototype.drawImage;
        CanvasRenderingContext2D.prototype.beginPath = function(...args) {
          this.__probePath = []; return begin.apply(this, args);
        };
        CanvasRenderingContext2D.prototype.moveTo = function(x, y) {
          this.__probePath?.push([x, y]); return move.call(this, x, y);
        };
        CanvasRenderingContext2D.prototype.lineTo = function(x, y) {
          this.__probePath?.push([x, y]); return line.call(this, x, y);
        };
        CanvasRenderingContext2D.prototype.stroke = function(...args) {
          if (this.canvas.id === 'sttWaveformCanvas' && this.strokeStyle === '#243b46') __paint.paths.push(this.__probePath.slice());
          return stroke.apply(this, args);
        };
        CanvasRenderingContext2D.prototype.clearRect = function(...args) {
          if (this.canvas.id === 'sttWaveformCanvas') {__paint.count++; __paint.paths = [];}
          return clear.apply(this, args);
        };
        CanvasRenderingContext2D.prototype.drawImage = function(...args) {__paint.copies++; return copy.apply(this, args);};
        // Loading/fullscreen transport only. State capture/restoration comes from app.js.
        globalThis.__transport = {fullLoads: 0};
        globalThis.goPage = name => {
          state.currentPage = name; $('#page-stt').classList.toggle('active', name === 'stt');
          if (name === 'stt') {state.sttWaveform = __wave(state.sttLeads); renderSttWaveform();}
        };
        globalThis.enterWaveformFullscreen = async () => {
          await new Promise(resolve => requestAnimationFrame(resolve));
          __transport.fullLoads++; state.waveformExpanded = true; state.waveform = __wave(ALL_LEADS);
        };
        globalThis.updateZoomControls = () => {};
        globalThis.updateWaveformModeUI = () => {};
        globalThis.loadWaveform = async () => {};
        globalThis.sttWaveformIsCurrent = () => true;
        globalThis.renderSttOverview = () => {};
        globalThis.updateSttTrendWindow = () => {};
        globalThis.setSttStart = () => {};
        globalThis.openSttLeadPicker = () => {};
        globalThis.ECGVoltage = {amplitude: value => String(value) + ' device units'};
        globalThis.ECGReviewTools = {markCanvas: () => {}};
        globalThis.editEffectiveCode = () => 'N';
        globalThis.handleError = error => {throw error;};
        globalThis.formatElapsedPrecise = value => String(value.toFixed(3));
        globalThis.formatElapsed = value => String(value);
        (0, eval)(tools); (0, eval)(chart); (0, eval)(layout); (0, eval)(functions);
        $('#sttReviewNote').value = 'unsaved mathematical note';
        $('#sttOpenTwelveLead').addEventListener('click', () => {globalThis.__transition = openSttTwelveLead();});
        renderSttWaveform(); bindSttInteraction();
      }, {chart, layout, functions,tools});
      await page.waitForFunction(() => {
        const canvas = document.querySelector('#sttWaveformCanvas');
        return Math.abs(canvas.height - canvas.getBoundingClientRect().height * devicePixelRatio) <= 1;
      });
      const threeBefore = await page.evaluate(() => {
        const canvas = $('#sttWaveformCanvas'), rect = canvas.getBoundingClientRect();
        return {width: rect.width, height: rect.height, note: $('#sttReviewNote').value};
      });
      for (const width of [900, 1600, 2300]) {
        await page.setViewportSize({width, height: 900});
        const item = await page.evaluate(() => {
          const source = JSON.stringify(__fullLeads), marks = JSON.stringify(sttLandmarkFractions()), note = $('#sttReviewNote').value;
          state.sttLeads = ALL_LEADS.slice(); state.sttWaveform = __wave(ALL_LEADS);
          const values = JSON.stringify(sttMeasurementValues()); ECGReviewTools.waveDomain(state.sttWaveform,JSON.stringify([state.caseId,'stt-raw']),true);renderSttWaveform();
          const canvas = $('#sttWaveformCanvas'), rect = canvas.getBoundingClientRect(), slot = $('#sttWaveCanvasWrap');
          const paths = __paint.paths;
          if (paths.length !== 12 || paths.some(points => points.length !== 2000)) throw Error('Source sample paths were truncated');
          let maximumAffineError = 0;
          paths.forEach((points, k) => {
            const samples = __fullLeads[ALL_LEADS[k]], scale = (points[0][1] - points[1][1]) / (samples[1] - samples[0]);
            for (const i of [0, 1, 701, 1183, 1051, 1999]) maximumAffineError = Math.max(maximumAffineError, Math.abs(points[i][1] - (points[0][1] - (samples[i] - samples[0]) * scale)));
          });
          slot.scrollTop = 200;
          return {viewport: innerWidth, dpr: devicePixelRatio, css_width: rect.width, css_height: rect.height,
            backing_width: canvas.width, backing_height: canvas.height, row_height: (rect.height - 46) / 12,
            scroll_top: slot.scrollTop, scroll_height: slot.scrollHeight, slot_height: slot.clientHeight,
            toolbar_outside_scroll: !slot.contains(document.querySelector('.stt-waveform-toolbar')),
            measuring_object_outside_scroll: !slot.contains($('#sttCurrentContext')),
            source_unchanged: source === JSON.stringify(__fullLeads), marks_unchanged: marks === JSON.stringify(sttLandmarkFractions()),
            measurements_unchanged: values === JSON.stringify(sttMeasurementValues()), note_unchanged: note === $('#sttReviewNote').value,
            sample_count_per_path: paths[0].length, maximum_affine_error: maximumAffineError,
            image_copies: __paint.copies, outer_overflow: document.documentElement.scrollWidth > innerWidth};
        });
        assert(Math.abs(item.css_height - 814) < .001);
        assert(Math.abs(item.row_height - 64) < .001);
        assert.equal(item.backing_height, 814 * dpr);
        assert(Math.abs(item.backing_width - item.css_width * dpr) <= 2);
        assert(item.scroll_top > 0);
        for (const flag of ['toolbar_outside_scroll','measuring_object_outside_scroll','source_unchanged','marks_unchanged','measurements_unchanged','note_unchanged']) assert.equal(item[flag], true, flag);
        assert(item.maximum_affine_error < 1e-8); assert.equal(item.image_copies, 0); assert.equal(item.outer_overflow, false);
        results.push(item);
      }
      // The scroll offset must not change which source lead/time the pointer reads.
      const hover = await page.evaluate(() => {
        const slot = $('#sttWaveCanvasWrap'); slot.scrollTop = 400;
        const rect = $('#sttWaveformCanvas').getBoundingClientRect(), fraction = .4;
        return {x: rect.left + 54 + (rect.width - 72) * fraction,
          y: rect.top + 24 + 64 * 10 + 32, scrollTop: slot.scrollTop,
          value: __fullLeads.V5[Math.round(fraction * 2000)]};
      });
      assert(hover.scrollTop > 0);
      await page.mouse.move(hover.x, hover.y);
      await page.waitForFunction(() => !$('#sttWaveTooltip').hidden);
      const tooltip = await page.locator('#sttWaveTooltip').textContent();
      assert.equal(tooltip, '124.000\nV5  ' + hover.value + ' device units');
      results.push({dpr, scrolled_pointer_lead: 'V5', scrolled_pointer_time_s: 124, raw_mathematical_value_matched: true});
      // Local resize must repaint without the window-resize handler or an API call.
      const paintBeforeResize = await page.evaluate(() => __paint.count);
      await page.evaluate(() => {$('#sttWaveCanvasWrap').style.width = 'calc(100% - 32px)';});
      await page.waitForFunction(before => __paint.count > before && Math.abs($('#sttWaveformCanvas').width - Math.floor($('#sttWaveformCanvas').getBoundingClientRect().width) * devicePixelRatio) <= 1, paintBeforeResize);
      await page.evaluate(() => {$('#sttWaveCanvasWrap').style.width = '';});
      await page.setViewportSize({width: 1600, height: 900});
      await page.evaluate(() => {state.sttLeads = __selected.slice(); state.sttWaveform = __wave(__selected); renderSttWaveform();});
      await page.waitForFunction(() => Math.abs($('#sttWaveformCanvas').height - $('#sttWaveformCanvas').getBoundingClientRect().height * devicePixelRatio) <= 1);
      await page.locator('#sttWaveformCanvas').focus();
      const jBefore = await page.evaluate(() => state.sttJFraction);
      await page.keyboard.press('ArrowRight');
      assert(Math.abs(await page.evaluate(() => state.sttJFraction) - jBefore - .0005) < 1e-12, 'J keyboard nudge must remain one 5ms source step');
      const before = await page.evaluate(() => ({start: state.sttStart, duration: state.sttDuration,
        iso: state.sttIsoFraction, j: state.sttJFraction, measurementMs: state.sttMeasurementMs,
        leads: state.sttLeads.slice(), note: $('#sttReviewNote').value, values: sttMeasurementValues()}));
      await page.locator('#sttOpenTwelveLead').click(); await page.evaluate(() => __transition);
      assert.equal(await page.evaluate(() => Object.keys(state.waveform.leads).length), 12);
      await page.evaluate(() => finishWaveformFullscreenExit());
      await page.waitForFunction(() => state.currentPage === 'stt' && $('#sttWaveformCanvas').dataset.sttRenderLeads === '3' && Math.abs($('#sttWaveformCanvas').height - $('#sttWaveformCanvas').getBoundingClientRect().height * devicePixelRatio) <= 1);
      const after = await page.evaluate(() => ({start: state.sttStart, duration: state.sttDuration,
        iso: state.sttIsoFraction, j: state.sttJFraction, measurementMs: state.sttMeasurementMs,
        leads: state.sttLeads.slice(), note: $('#sttReviewNote').value, values: sttMeasurementValues()}));
      assert.deepEqual(after, before, 'Repository fullscreen return must preserve ST-T scope, marks, readings and the unsaved note');
      const threeAfter = await page.evaluate(() => {const rect = $('#sttWaveformCanvas').getBoundingClientRect(); return {width: rect.width, height: rect.height, note: $('#sttReviewNote').value};});
      assert(Math.abs(threeAfter.width - threeBefore.width) < .02); assert(Math.abs(threeAfter.height - threeBefore.height) < .02); assert.equal(threeAfter.note, threeBefore.note);
      results.push({dpr, local_resize_repainted: true, repository_3_12_3_preserved: true, three_before: threeBefore, three_after: threeAfter});
      await context.close();
    }
    assert.deepEqual(pageErrors, []);
    const receipt = {passed: true, mathematical_only: true, network_aborted: true, network_requests: network.length,
      chromium_sandbox: true, source_hashes: {'static/js/app.js': hash(app), 'static/css/desktop-workspace.css': hash(read('static/css/desktop-workspace.css')), 'templates/index.html': hash(template)},
      extracted_functions: functionNames, transport_fixture: true, native_fullscreen_request_claim: false,
      clinical_method_changed: false, preserved_boundary: 'Existing len-1 display/measurement/save indexing remains unchanged; this is not a clinical timing validation.', results};
    fs.writeFileSync(receiptPath, JSON.stringify(receipt, null, 2));
    console.log(JSON.stringify({passed: true, receipt: receiptPath, dimensions: results.filter(item => item.row_height).length, dpr: [1, 2], source_hashes: receipt.source_hashes, methods_unchanged: true}));
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode = 1;});
