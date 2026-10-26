'use strict';
// Offline Chrome exercises the actual page, modules, events and waveform reads.
// All records and signals below are mathematical; no service or patient file is used.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {chromium} = require(process.env.ECG_PLAYWRIGHT_CORE || 'playwright-core');
const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const origin = 'https://synthetic.invalid';
const checks = [];
const allLeads = ['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6'];

function installFixture() {
  document.removeEventListener('DOMContentLoaded', init);
  const samples = [20, ...Array.from({length: 96}, (_, i) => 2000 + i * 560), 59980];
  const identity = () => ({data_version: 'mathematical-v1', source_digest: 'mathematical-source',
    analysis_basis: 'mathematical-basis', analysis_revision: state.caseData?.analysis_revision || 3,
    beat_revision: state.caseData?.analysis_revision || 3, revision: state.caseData?.analysis_revision || 3});
  const beat = sample => ({sample_index: sample, time_s: sample / 200, group: 1,
    class_code: sample === 4800 ? 'P' : 'N', label: 'mathematical beat',
    ...(sample === 4800 ? {beat_id: 'manual-mathematical-4800'} : {})});
  const scatterPoint = sample => ({...beat(sample),
    x: sample === 4800 ? 600 : sample === 5360 ? 1400 : 1000,
    y: sample === 4800 ? 700 : sample === 5360 ? 1400 : 1000});
  const wave = (start, duration, leads) => {
    const count = Math.max(2, Math.round(duration * 200));
    return {...identity(), start_s: start, duration_s: duration, sample_rate_hz: 200,
      display_sample_rate_hz: 200, stride: 1, filter: 'display', unit_label: 'u',
      leads: Object.fromEntries(leads.map((lead, k) => [lead,
        Array.from({length: count}, (_, i) => 24 * Math.sin((i + k * 7) / 18) +
          (i % 160 === 60 ? 140 : 0))])),
      beats: samples.filter(s => s / 200 >= start && s / 200 < start + duration).map(beat), annotations: []};
  };
  const records = samples.map((sample, index) => ({...beat(sample), ...identity(),
    event_id: 'mathematical-' + sample, subtype: 'beat', beat_count: 1,
    start_sample: sample, end_sample: sample, target_samples: [sample],
    basis_version: 'mathematical-v1', diagnosis_status: 'candidate', index}));
  globalThis.__fixture = {calls: [], pending: [], defer: [], samples, records, wave,
    errors: [], markers: [], scatterMarks: [], resolve(id, overrides = {}) {
      const item = this.pending.find(p => p.id === id); if (!item) throw Error('missing deferred read ' + id);
      this.pending = this.pending.filter(p => p !== item); item.resolve({...item.value, ...overrides});
    }};
  api = async (raw, options = {}) => {
    const url = new URL(raw, location.href), query = Object.fromEntries(url.searchParams),
      body = options.body ? JSON.parse(options.body) : {}, kind = url.pathname.split('/').at(-1),
      call = {id: __fixture.calls.length, kind, caseId: url.pathname.split('/')[3], query, body,
        lane: options.readLane || '', signal: options.signal, generation: state.waveformFullscreenGeneration};
    __fixture.calls.push(call);
    let value;
    if (kind === 'waveform') {
      const duration = Math.min(300, Number(query.duration || 10)),
        start = Math.max(0, Math.min(300 - duration, Number(query.start || 0)));
      value = wave(start, duration, (query.leads || 'II,V1,V5').split(','));
    } else if (kind === 'template-occurrences') {
      const offset = Number(query.offset || 0), limit = Number(query.limit || 48);
      value = {...identity(), total: records.length, offset, items: records.slice(offset, offset + limit)};
    } else if (kind === 'event-waveforms') {
      value = {...identity(), items: (body.ranges || []).map(r => ({...wave(r.start, r.end - r.start,
        body.leads || ['II','V1']), key: r.key}))};
    } else if (kind === 'waveform-strips') {
      value = {...identity(), items: (body.sample_indices || []).map(s => ({...beat(s),
        ...wave(Math.max(0, s / 200 - .6), 1.6, body.leads || ['II','V1']), anchor_offset_s: .6}))};
    } else if (kind === 'waveform-density') {
      const population = body.samples || samples, excluded = new Set(body.exclude_samples || []),
        selected = population.filter(s => !excluded.has(s));
      value = {...identity(), lead: query.lead || 'II', width: 40, height: 24,
        bins: Array.from({length: 960}, (_, i) => i % 43 === 0 ? 2 : 0),
        total: selected.length, included: selected.length, sample_indices: selected,
        population_samples: selected, amplitude_limit: 180, skipped_edges: 0};
      if(query.leads)value={...identity(),population_samples:selected,items:query.leads.split(',').map(lead=>({...value,lead}))};
    } else if (kind === 'overview') {
      value = {...identity(), duration_s: 300, rows: samples.map(s => [s, 800, 'N']),
        settings: {lead: 'II', pause: 2.5}, estimated_beats: false};
    } else if (kind === 'rhythm-review') {
      value = {...identity(), document_revision: 0, document: {episodes: [], bookmarks: {}},
        episodes: [], bookmarks: {}, duration_s: 300};
    } else if (kind === 'analysis-basis') value = identity();
    else if (kind === 'beat-editor') value = {...identity(), settings: {lead: 'II'}, types: ECGBeatEngine.types,
      history: {can_undo: false, can_redo: false}};
    else if (kind === 'beats') value = {...identity(), items: samples.map(beat), markers: []};
    else if (kind === 'scatter') value = {bounds: {x_min: 300, x_max: 2000, y_min: 300, y_max: 2000},
      points: samples.map(scatterPoint)};
    else if (kind === 'rr-visuals') value = {histogram: []};
    else if (kind === 'beat-templates' || kind === 'beat-overrides') value = {items: []};
    else throw Error('Unexpected synthetic endpoint ' + kind);
    const at = __fixture.defer.findIndex(rule => rule.kind === kind &&
      (!rule.leads || query.leads?.split(',').length === rule.leads));
    if (at >= 0) {
      if (!__fixture.defer[at].repeat) __fixture.defer.splice(at, 1);
      // Deliberately complete even after AbortSignal: lifecycle must reject stale values.
      return new Promise(resolve => __fixture.pending.push({id: call.id, value, resolve}));
    }
    return value;
  };
  const markCanvas = ECGReviewTools.markCanvas;
  ECGReviewTools.markCanvas = (ctx, x, top, bottom, code) => {
    __fixture.markers.push({canvas: ctx.canvas.id, x, top, bottom, code});
    return markCanvas(ctx, x, top, bottom, code);
  };
  const beginPath = CanvasRenderingContext2D.prototype.beginPath,
    arc = CanvasRenderingContext2D.prototype.arc, stroke = CanvasRenderingContext2D.prototype.stroke;
  CanvasRenderingContext2D.prototype.beginPath = function(...args) {
    this.__fixtureArcs = []; return beginPath.apply(this, args);
  };
  CanvasRenderingContext2D.prototype.arc = function(x, y, radius, ...rest) {
    this.__fixtureArcs?.push({x, y, radius}); return arc.call(this, x, y, radius, ...rest);
  };
  CanvasRenderingContext2D.prototype.stroke = function(...args) {
    if (['editScatterCanvas','editLibraryScatterCanvas'].includes(this.canvas.id))
      for (const point of this.__fixtureArcs || []) __fixture.scatterMarks.push({...point,
        canvas: this.canvas.id, color: this.strokeStyle});
    return stroke.apply(this, args);
  };
  handleError = error => __fixture.errors.push(error.message);
  Object.assign(state, {caseId: 'mathematical-A', caseRequestId: 4, workspaceEpoch: 'math-workspace',
    currentPage: 'edit', caseLoading: null, reportDirty: false, editMode: 'cluster', editDuration: 10,
    editStart: 40, editLead: 'II', editSelectedClass: 'source-N', editTemplates: [],
    editSelectedSamples: new Set(), editBeatOverrides: new Map(), start: 72, duration: 20, filter: 'raw',
    leads: ['II','V1','V5'], caseData: {case_id: 'mathematical-A', analysis_revision: 3,
      analysis_basis: 'mathematical-basis', technical: {duration_seconds_raw: 300, sample_rate_hz: 200},
      metadata: {}, summary: {beat_groups: {'1': samples.length}}, annotations: [],
      beat_editor_settings: {lead: 'II'}, beat_editor_history: {revision: 3, can_undo: false, can_redo: false}},
    editReadIdentity: {id: 'mathematical-A', caseToken: 4, ...identity()},
    trend: {points: []}, editRr: {histogram: []}, editScatterData: {bounds:
      {x_min: 300, x_max: 2000, y_min: 300, y_max: 2000}, points: samples.map(scatterPoint)},
    editWaveform: wave(40, 10, ['II','V1','V5'])});
  // Initial workspace transport is excluded; every interaction and later read is production code.
  $('#loading').classList.add('hidden');
  $$('.page').forEach(node => node.classList.toggle('active', node.id === 'page-edit'));
  $('#filterSelect').value = state.filter;
  globalThis.ecgChartInspection = ECGChartInspection.mount({getScope: () =>
    JSON.stringify([state.caseId, state.caseRequestId, state.currentPage, state.editMode, state.caseData.analysis_revision])});
  bindEvents(); setEditMode('cluster', false); updateWaveformModeUI(); renderEditWaveform();
  globalThis.__state = state;
  // Normal startup mounts controls before opening a case; retain that ordering.
  state.caseId = null; state.currentPage = 'dashboard';
  document.addEventListener('DOMContentLoaded', () => {
    state.caseId = 'mathematical-A'; state.currentPage = 'edit';
    setEditMode('cluster', false);
    clinicalUI.loadOccurrences().catch(handleError);
  });
}

function fixtureHtml() {
  return read('templates/index.html')
    .replace(/\{\{\s*url_for\('static',\s*filename='([^']+)'\)\s*\}\}/g, (_, name) => '/static/' + name)
    .replace(/\{[%{][\s\S]*?[}%]\}/g, '')
    .replace('</body>', () => '<script>(' + installFixture.toString() + ')();</script></body>');
}

async function waitReady(page) {
  await page.waitForFunction(() => document.querySelector('.occurrence-wave svg') && __state.editWaveform &&
    globalThis.ECGTemplateLinkedView?.context());
}

async function snapshot(page) {
  return page.evaluate(() => ({page: __state.currentPage, expanded: __state.waveformExpanded,
    caseId: __state.caseId, mode: __state.editMode, editStart: __state.editStart,
    editDuration: __state.editDuration, editLead: __state.editLead, source: __state.editSelectedClass,
    selected: [...__state.editSelectedSamples], focusSample: __state.editSelectedSample,
    preview: {start: __state.start, duration: __state.duration, filter: __state.filter, leads: __state.leads},
    waveform: __state.waveform && {start: __state.waveform.start_s, duration: __state.waveform.duration_s,
      leads: Object.keys(__state.waveform.leads), revision: __state.waveform.analysis_revision},
    bottom: __state.editWaveform && {start: __state.editWaveform.start_s, duration: __state.editWaveform.duration_s,
      leads: Object.keys(__state.editWaveform.leads)},
    linked: ECGLinkedSelection.snapshot(), morph: morphologyWorkbench.privateSnapshot(),
    scroll: $('#editTemplateGallery').scrollTop, search: $('#occSearch')?.value || '',
    draft: $('#morphTemplateName').value, active: document.activeElement?.closest('[data-occ-index]')?.dataset.occIndex || document.activeElement?.id,
    inspection: !!document.querySelector('.chart-inspection-dialog[open]'), errors: __fixture.errors,
    pending: __fixture.pending.map(p => p.id)}));
}

async function check(name, fn) {await fn(); checks.push(name);}

async function fresh(page, mode = 'cluster') {
  await page.goto(origin + '/'); await waitReady(page);
  if (mode !== 'cluster') {
    await page.evaluate(mode => setEditMode(mode), mode);
    await page.waitForFunction(mode => __state.editMode === mode && document.querySelector('.occurrence-wave svg'), mode);
  }
}

async function cardSelector(page, sample) {
  const index = await page.evaluate(sample => {
    const node = [...document.querySelectorAll('.occurrence-tile')].find(n => n.occurrenceItem?.sample_index === sample);
    if (!node) throw Error('Mathematical sample is outside the visible viewport ' + sample);
    return node.dataset.occIndex;
  }, sample);
  return '.occurrence-tile[data-occ-index="' + index + '"]';
}

async function twelve(page, sample, {edge = false, revision = 3, readCount = 1} = {}) {
  await page.waitForFunction(() => __state.waveformExpanded && __state.currentPage === 'review' &&
    Object.keys(__state.waveform?.leads || {}).length === 12);
  const s = await snapshot(page), duration = s.waveform.duration,
    expectedStart = Math.max(0, Math.min(300 - duration, sample / 200 - duration / 2));
  assert.deepEqual(s.waveform.leads, allLeads);
  assert(Math.abs(s.waveform.start - expectedStart) < .0006, 'clicked sample must determine the full waveform window');
  if (!edge) assert(Math.abs((sample / 200 - s.waveform.start) / duration - .5) < .0001);
  const display = await page.evaluate(() => ({surface: document.fullscreenElement?.id ||
    document.querySelector('.waveform-fullscreen-fallback')?.id,
    count: document.querySelectorAll('#waveformCard').length, meta: $('#waveMeta').textContent,
    requests: __fixture.calls.filter(c => c.kind === 'waveform' && c.query.leads?.split(',').length === 12 &&
      c.generation === __state.waveformFullscreenGeneration)
      .map(c => ({query: c.query, caseId: c.caseId}))}));
  assert.equal(display.surface, 'waveformCard'); assert.equal(display.count, 1);
  assert.equal(display.requests.length, readCount, 'the entry must issue one current twelve read; retries are explicit');
  assert.equal(Number(display.requests.at(-1).query.start), expectedStart);
  assert.equal(display.requests.at(-1).query.analysis_basis, 'mathematical-basis');
  assert.equal(display.requests.at(-1).query.analysis_revision, String(revision));
  assert.match(display.meta, edge ? /边界|真实范围/ : /居中/);
  return s;
}

async function escapeBack(page) {
  await page.keyboard.press('Escape');
  await page.waitForFunction(() => !__state.waveformExpanded && __state.currentPage === 'edit');
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  return snapshot(page);
}

async function pendingTwelve(page) {
  await page.waitForFunction(() => __state.waveformExpanded && __state.editFullscreenReturn?.readState === 'loading' &&
    __fixture.pending.some(p => __fixture.calls[p.id].query.leads?.split(',').length === 12 &&
      !__fixture.calls[p.id].signal?.aborted));
  // Overview reconciliation may supersede the first twelve read. Hold all reads,
  // then target the actual live request after the ordinary render tasks settle.
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  return page.evaluate(() => {
    const current = __fixture.pending.filter(p => __fixture.calls[p.id].query.leads?.split(',').length === 12 &&
      !__fixture.calls[p.id].signal?.aborted).at(-1);
    if (!current) throw Error('The active twelve request was not held');
    return current.id;
  });
}

function sameEditContext(before, after) {
  for (const key of ['mode','editStart','editDuration','editLead','source','selected','search','draft','scroll'])
    assert.deepEqual(after[key], before[key], 'return must preserve ' + key);
  assert.deepEqual(after.preview, before.preview, 'preview lead/filter/window context must return');
  assert.deepEqual(after.morph?.groups, before.morph?.groups, 'viewing cannot move morphology members');
}

async function linkedFocusPresentation(page, sample, other = null) {
  const result = await page.evaluate(({sample, other}) => {
    __fixture.scatterMarks = []; renderEditScatter();
    const canvas = $('#editScatterCanvas'), rect = canvas.getBoundingClientRect(),
      point = __state.editScatterData.points.find(p => p.sample_index === sample),
      target = document.querySelector('[data-linked-sample="' + sample + '"]'),
      previous = other == null ? null : document.querySelector('[data-linked-sample="' + other + '"]');
    return {focus: ECGLinkedSelection.snapshot().focusSample, appFocus: __state.editSelectedSample,
      headerSample: Number(target?.querySelector('[data-linked-focus]')?.dataset.linkedFocus),
      focused: target?.dataset.focused, otherFocused: previous?.dataset.focused,
      cohort: ECGTemplateLinkedView.context()?.samples,
      // Independent screen position for the explicitly supplied mathematical point.
      expected: {x: 31 + (point.x - 300) / 1700 * (rect.width - 40),
        y: 10 + (2000 - point.y) / 1700 * (rect.height - 32)},
      marks: __fixture.scatterMarks.filter(m => m.canvas === 'editScatterCanvas' && m.radius === 5)};
  }, {sample, other});
  assert.equal(result.focus, sample); assert.equal(result.headerSample, sample);
  assert.equal(result.focused, 'true');
  if (other != null) assert.equal(result.otherFocused, 'false');
  assert.equal(result.marks.length, 1, 'one authoritative linked point must carry the scatter focus');
  assert.equal(result.marks[0].color, '#d17b17');
  assert(Math.abs(result.marks[0].x - result.expected.x) < .01);
  assert(Math.abs(result.marks[0].y - result.expected.y) < .01);
  return result;
}

async function exactTwelveMarker(page, sample) {
  const paint = await page.evaluate(sample => {
    __fixture.markers = []; renderWaveform();
    return {marks: __fixture.markers.filter(m => m.canvas === 'waveformCanvas'),
      expectedX: (sample / 200 - __state.waveform.start_s) / __state.waveform.duration_s *
        Math.floor($('#waveformCanvas').getBoundingClientRect().width)};
  }, sample);
  assert.equal(paint.marks.length, 1); assert(Math.abs(paint.marks[0].x - paint.expectedX) < .01);
}

async function prepareOutsideCohort(page) {
  await fresh(page);
  const first = await cardSelector(page, 4800);
  await page.locator(first + ' .occurrence-open').click();
  await page.evaluate(() => ECGTemplateLinkedView.selectSamples([4800]));
  await page.waitForFunction(() => ECGTemplateLinkedView.context()?.samples.length === 1);
  await page.locator('#templateLinkedOpen').click();
  await page.waitForSelector('[data-linked-wave="4800"] svg');
  await page.locator('[data-linked-focus="4800"]').click();
  await linkedFocusPresentation(page, 4800);
  await page.locator('#templateLinkedClose').click();
  const outside = await cardSelector(page, 5360);
  await page.locator(outside + ' .occurrence-open').click({modifiers: ['Meta']});
  const before = await snapshot(page);
  assert.deepEqual(before.selected, [4800, 5360]); assert.equal(before.linked.focusSample, 4800);
  assert.deepEqual(before.linked.samples, [4800]);
  return {outside, before};
}

(async () => {
  const browser = await chromium.launch({headless: true, chromiumSandbox: true,
    executablePath: process.env.ECG_CHROME || chromium.executablePath()});
  const context = await browser.newContext({viewport: {width: 1600, height: 1000}});
  const page = await context.newPage(), pageErrors = [], external = [];
  page.on('pageerror', error => pageErrors.push(error.stack));
  await page.route('**/*', route => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) {external.push(url.hostname); return route.abort();}
    if (url.pathname === '/') return route.fulfill({contentType: 'text/html', body: fixtureHtml()});
    if (url.pathname.startsWith('/static/')) {
      const name = url.pathname.slice(1);
      return route.fulfill({contentType: name.endsWith('.js') ? 'application/javascript' : 'text/css', body: read(name)});
    }
    return route.abort();
  });
  try {
    await page.goto(origin + '/');
    await waitReady(page);
    await check('fixture-runs-entire-production-page-with-only-mathematical-input', async () => {
      const s = await snapshot(page); assert.equal(s.page, 'edit'); assert.equal(s.bottom.leads.length, 3);
      assert.equal(pageErrors.length, 0, pageErrors.join('\n')); assert.deepEqual(s.errors, []);
      assert.equal(external.length, 0);
    });
    await check('single-click-selects-and-locates-synchronously-while-waveform-read-is-pending', async () => {
      await page.evaluate(() => __fixture.defer.push({kind: 'waveform', leads: 3}));
      const selector = await cardSelector(page, 4800);
      await page.locator(selector + ' .occurrence-open').click();
      const s = await snapshot(page);
      assert.deepEqual(s.selected, [4800]); assert.equal(s.focusSample, 4800); assert.equal(s.editStart, 22);
      assert.equal(s.page, 'edit'); assert.equal(s.expanded, false); assert.equal(s.inspection, false);
      assert.equal(s.pending.length, 1, 'the selection must complete before data arrives');
      await page.evaluate(id => __fixture.resolve(id), s.pending[0]);
    });
    for (const mode of ['cluster','library']) {
      await check(mode + '-thumbnail-dblclick-centres-manual-beat-in-shared-twelve-surface-and-Esc-returns', async () => {
        await fresh(page, mode);
        const selector = await cardSelector(page, 4800);
        await page.locator(selector + ' .occurrence-open').click();
        await page.waitForFunction(() => __state.editWaveform?.start_s === 22);
        await page.evaluate(() => {$('#morphTemplateName').value = 'mathematical unsaved draft'; $('#occSearch').value = 'mathematical query';});
        const before = await snapshot(page);
        await page.locator(selector + ' .occurrence-wave svg').dblclick();
        const full = await twelve(page, 4800); assert.deepEqual(full.selected, [4800]);
        const after = await escapeBack(page); sameEditContext(before, after);
        assert.equal(after.active, selector.match(/"(\d+)"/)[1]);
        assert.deepEqual(after.errors, []);
      });
    }
    await check('linked-selected-svg-dblclick-centres-exact-beat-and-restores-popover-with-independent-checks', async () => {
      await fresh(page);
      await page.evaluate(() => ECGTemplateLinkedView.selectSamples([4800, 5360]));
      await page.waitForFunction(() => ECGTemplateLinkedView.context()?.samples.length === 2);
      await page.locator('#templateLinkedOpen').click();
      await page.waitForSelector('[data-linked-wave="5360"] svg');
      await page.locator('[data-linked-focus="4800"]').click();
      const initial = await linkedFocusPresentation(page, 4800, 5360); assert.equal(initial.appFocus, 4800);
      const before = await snapshot(page);
      await page.locator('[data-linked-wave="5360"] svg').dblclick();
      const full = await twelve(page, 5360); assert.deepEqual(full.selected, []);
      assert.equal(full.linked.focusSample, 5360); assert.equal(full.focusSample, 5360);
      assert.equal(full.linked.selectionGeneration, before.linked.selectionGeneration);
      assert.equal(full.linked.focusGeneration, before.linked.focusGeneration + 1);
      await exactTwelveMarker(page, 5360);
      const after = await escapeBack(page); sameEditContext(before, after);
      assert.equal(after.linked.kind, 'samples'); assert.deepEqual(after.linked.samples, [4800, 5360]);
      const returned = await linkedFocusPresentation(page, 5360, 4800); assert.equal(returned.appFocus, 5360);
      assert.equal(await page.locator('#templateLinkedCards').evaluate(n => n.matches(':popover-open')), true);
    });
    await check('linked-focus-change-survives-Esc-before-response-with-cohort-and-checks-unchanged', async () => {
      await fresh(page);
      await page.evaluate(() => ECGTemplateLinkedView.selectSamples([4800, 5360]));
      await page.waitForFunction(() => ECGTemplateLinkedView.context()?.samples.length === 2);
      await page.locator('#templateLinkedOpen').click(); await page.waitForSelector('[data-linked-wave="5360"] svg');
      await page.locator('[data-linked-focus="4800"]').click();
      const before = await snapshot(page);
      await page.evaluate(() => __fixture.defer.push({kind: 'waveform', leads: 12, repeat: true}));
      await page.locator('[data-linked-wave="5360"] svg').dblclick(); const id = await pendingTwelve(page);
      const loading = await snapshot(page); assert.equal(loading.linked.focusSample, 5360);
      assert.equal(loading.focusSample, 5360); assert.deepEqual(loading.selected, before.selected);
      assert.equal(loading.linked.selectionGeneration, before.linked.selectionGeneration);
      const after = await escapeBack(page); sameEditContext(before, after);
      await linkedFocusPresentation(page, 5360, 4800);
      await page.evaluate(id => __fixture.resolve(id), id);
      const late = await snapshot(page); sameEditContext(after, late);
      assert.equal(late.linked.focusSample, 5360); assert.deepEqual(late.linked.samples, [4800, 5360]);
      assert.equal(late.linked.selectionGeneration, before.linked.selectionGeneration); assert.equal(late.expanded, false);
      await linkedFocusPresentation(page, 5360, 4800);
    });
    for (const cancel of [false, true]) {
      await check('outside-linked-cohort-' + (cancel ? 'pending-cancel' : 'complete-return') + '-keeps-filter-focus-and-checks-with-real-twelve-target', async () => {
        const {outside, before} = await prepareOutsideCohort(page);
        if (cancel) await page.evaluate(() => __fixture.defer.push({kind: 'waveform', leads: 12, repeat: true}));
        await page.locator(outside + ' .occurrence-wave svg').dblclick();
        const id = cancel ? await pendingTwelve(page) : null;
        const full = cancel ? await snapshot(page) : await twelve(page, 5360);
        assert.equal(full.focusSample, 5360); assert.equal(full.linked.focusSample, 4800);
        assert.deepEqual(full.linked.samples, [4800]); assert.deepEqual(full.selected, before.selected);
        assert.equal(full.linked.selectionGeneration, before.linked.selectionGeneration);
        assert.equal(full.linked.focusGeneration, before.linked.focusGeneration);
        if (!cancel) {
          assert.match(await page.locator('#waveMeta').textContent(), /定位搏不在当前联动选集内/);
          await exactTwelveMarker(page, 5360);
        }
        const after = await escapeBack(page); sameEditContext(before, after);
        await page.locator('#templateLinkedOpen').click(); await page.waitForSelector('[data-linked-wave="4800"] svg');
        const presentation = await linkedFocusPresentation(page, 4800);
        assert.deepEqual(presentation.cohort, [4800]); assert.equal(presentation.appFocus, 5360);
        assert.equal(await page.locator('[data-linked-sample="5360"]').count(), 0);
        if (cancel) {
          await page.evaluate(id => __fixture.resolve(id), id);
          const late = await snapshot(page); assert.equal(late.expanded, false);
          assert.equal(late.linked.focusSample, 4800); assert.deepEqual(late.linked.samples, [4800]);
          assert.deepEqual(late.selected, before.selected); await linkedFocusPresentation(page, 4800);
        }
      });
    }
    for (const mode of ['cluster','library']) {
      await check(mode + '-bottom-canvas-keeps-existing-shared-twelve-entry-and-Esc-return', async () => {
        await fresh(page, mode);
        const selector = mode === 'library' ? '#editLibraryWaveformCanvas' : '#editWaveformCanvas';
        await page.locator(selector).click();
        const before = await snapshot(page);
        await page.locator(selector).dblclick();
        await page.waitForFunction(() => __state.waveformExpanded && Object.keys(__state.waveform?.leads || {}).length === 12);
        const full = await snapshot(page); assert.deepEqual(full.waveform.leads, allLeads);
        assert.equal(await page.evaluate(() => document.fullscreenElement?.id || $('.waveform-fullscreen-fallback')?.id), 'waveformCard');
        const after = await escapeBack(page); sameEditContext(before, after); assert.equal(after.active, selector.slice(1));
      });
    }
    await check('fast-double-click-uses-last-clicked-sample-even-before-lower-wave-responds', async () => {
      await fresh(page);
      await page.evaluate(() => __fixture.defer.push({kind: 'waveform', leads: 3}, {kind: 'waveform', leads: 3}));
      const selector = await cardSelector(page, 6480);
      await page.locator(selector + ' .occurrence-wave svg').dblclick();
      const full = await twelve(page, 6480); assert.deepEqual(full.selected, [6480]);
      assert.equal(full.pending.length, 2);
      const after = await escapeBack(page);
      const ids = after.pending;
      await page.evaluate(ids => ids.forEach(id => __fixture.resolve(id)), ids);
      const restored = await snapshot(page);
      assert.equal(restored.editStart, 30.4); assert.equal(restored.bottom.start, 30.4);
      assert.equal(restored.page, 'edit'); assert.equal(restored.expanded, false);
    });
    await check('actual-marker-paints-only-clicked-sample-at-centre-despite-old-review-locations', async () => {
      await fresh(page);
      await page.evaluate(() => {
        __state.locatedTime = {caseId: __state.caseId, time: 26.8};
        __state.scatterFocusedSample = 5360;
        __state.beatRelabelTarget = {caseId: __state.caseId, surface: 'review', sample_index: 5360};
      });
      const selector = await cardSelector(page, 4800);
      await page.locator(selector + ' .occurrence-wave svg').dblclick(); await twelve(page, 4800);
      const paint = await page.evaluate(() => {
        __fixture.markers = []; renderWaveform();
        return {marks: __fixture.markers.filter(m => m.canvas === 'waveformCanvas'),
          width: parseFloat($('#waveformCanvas').style.width) === 100 ?
            Math.floor($('#waveformCanvas').getBoundingClientRect().width) : $('#waveformCanvas').width / devicePixelRatio};
      });
      assert.equal(paint.marks.length, 1, 'old scatter/editor locations must not paint additional focus markers');
      assert.equal(paint.marks[0].code, 'P'); assert(Math.abs(paint.marks[0].x - paint.width / 2) < 1);
      await escapeBack(page);
    });
    await check('opened-morphology-form-keeps-draft-and-exact-group-members-after-twelve-return', async () => {
      await fresh(page);
      await page.waitForFunction(() => !$('#applyEditRange').disabled);
      await page.evaluate(() => {document.querySelector('.morph-keyboard-range').open = true; $('#applyEditRange').click();});
      await page.waitForFunction(() => !document.querySelector('[data-group-move="6"]').disabled);
      await page.locator('[data-group-move="6"]').click();
      await page.waitForFunction(() => !$('#morphGroupTemplate').disabled);
      await page.locator('#morphGroupTemplate').click();
      await page.locator('#morphTemplateName').fill('mathematical real form draft');
      const before = await snapshot(page), selector = await cardSelector(page, 4800);
      assert.equal(await page.locator('#morphTemplateForm').evaluate(n => n.hidden), false);
      await page.locator(selector + ' .occurrence-wave svg').dblclick(); await twelve(page, 4800);
      const after = await escapeBack(page);
      assert.equal(after.draft, before.draft); assert.deepEqual(after.morph.groups, before.morph.groups);
      assert.equal(await page.locator('#morphTemplateForm').evaluate(n => n.hidden), false);
    });
    await check('Esc-before-twelve-response-cancels-and-late-completion-cannot-replace-return-context', async () => {
      await fresh(page);
      await page.evaluate(() => __fixture.defer.push({kind: 'waveform', leads: 12, repeat: true}));
      const selector = await cardSelector(page, 4800);
      await page.locator(selector + ' .occurrence-wave svg').dblclick();
      const id = await pendingTwelve(page), after = await escapeBack(page);
      const beforeLate = await snapshot(page);
      await page.evaluate(id => __fixture.resolve(id), id);
      const late = await snapshot(page); sameEditContext(beforeLate, late);
      assert.deepEqual(late.waveform, beforeLate.waveform); assert.equal(late.expanded, false);
      assert.equal(after.page, 'edit');
      assert.equal(await page.evaluate(id => __fixture.calls[id].signal?.aborted, id), true);
    });
    await check('closing-slow-A-then-opening-B-rejects-late-A-with-last-selection-and-surface-intact', async () => {
      await fresh(page);
      await page.evaluate(() => __fixture.defer.push({kind: 'waveform', leads: 12, repeat: true}));
      const a = await cardSelector(page, 4800);
      await page.locator(a + ' .occurrence-wave svg').dblclick();
      const oldId = await pendingTwelve(page); await escapeBack(page);
      await page.evaluate(() => {__fixture.defer = [];});
      const b = await cardSelector(page, 6480);
      await page.locator(b + ' .occurrence-wave svg').dblclick(); await twelve(page, 6480);
      const current = await snapshot(page);
      await page.evaluate(id => __fixture.resolve(id), oldId);
      const late = await snapshot(page);
      assert.deepEqual(late.waveform, current.waveform); assert.equal(late.focusSample, 6480);
      assert.deepEqual(late.selected, [6480]); assert.equal(late.expanded, true);
      assert.equal(await page.evaluate(() => document.fullscreenElement?.id || $('.waveform-fullscreen-fallback')?.id), 'waveformCard');
      await escapeBack(page);
    });
    await check('incomplete-twelve-response-shows-retry-and-fresh-complete-data-restores-same-target', async () => {
      await fresh(page);
      await page.evaluate(() => __fixture.defer.push({kind: 'waveform', leads: 12, repeat: true}));
      const selector = await cardSelector(page, 4800);
      await page.locator(selector + ' .occurrence-wave svg').dblclick();
      const id = await pendingTwelve(page);
      assert.equal(await page.locator('#waveformCard').getAttribute('aria-busy'), 'true');
      await page.evaluate(id => __fixture.resolve(id, {leads: {II: [0, 1, 0]}}), id);
      await page.waitForSelector('#editTwelveRetry:visible');
      assert.equal((await snapshot(page)).waveform, null);
      assert.equal(await page.locator('#waveformCard').getAttribute('aria-busy'), 'false');
      await page.evaluate(() => {__fixture.defer = [];});
      await page.locator('#editTwelveRetry').click(); await twelve(page, 4800, {readCount: 2});
      assert.equal(await page.locator('#editTwelveRetry').evaluate(n => n.hidden), true);
      await escapeBack(page);
    });
    await check('manual-beat-id-mismatch-does-not-paint-a-substitute-and-retry-requires-the-matching-record', async () => {
      await fresh(page);
      await page.evaluate(() => __fixture.defer.push({kind: 'waveform', leads: 12, repeat: true}));
      const selector = await cardSelector(page, 4800);
      await page.locator(selector + ' .occurrence-wave svg').dblclick();
      const id = await pendingTwelve(page);
      await page.evaluate(id => {
        const response = __fixture.pending.find(p => p.id === id).value;
        __fixture.resolve(id, {beats: response.beats.filter(beat => beat.sample_index !== 4800)});
      }, id);
      await page.waitForSelector('#editTwelveRetry:visible');
      assert.equal((await snapshot(page)).waveform, null);
      assert.match(await page.locator('#waveMeta').textContent(), /心搏位置已变化|重新读取/);
      await page.evaluate(() => {__fixture.defer = [];});
      await page.locator('#editTwelveRetry').click(); await twelve(page, 4800, {readCount: 2});
      await escapeBack(page);
    });
    await check('fresh-revision-reopens-current-beat-after-old-revision-read-is-rejected', async () => {
      await fresh(page);
      await page.evaluate(() => __fixture.defer.push({kind: 'waveform', leads: 12, repeat: true}));
      const selector = await cardSelector(page, 4800);
      await page.locator(selector + ' .occurrence-wave svg').dblclick();
      const oldId = await pendingTwelve(page);
      await page.evaluate(() => {
        __state.caseData.analysis_revision = 4; __state.editReadIdentity.analysis_revision = 4;
        ECGLinkedSelection.setScope({...ECGLinkedSelection.snapshot().scope, analysis_revision: 4, beatRevision: 4});
      });
      await page.evaluate(id => __fixture.resolve(id), oldId);
      assert.equal((await snapshot(page)).waveform, null);
      await escapeBack(page); await page.evaluate(() => clinicalUI.loadOccurrences()); await waitReady(page);
      await page.evaluate(() => {__fixture.defer = [];});
      const freshSelector = await cardSelector(page, 4800);
      await page.locator(freshSelector + ' .occurrence-wave svg').dblclick();
      const full = await twelve(page, 4800, {revision: 4}); assert.equal(full.waveform.revision, 4);
      await escapeBack(page);
    });
    for (const boundary of ['case','revision','workspace']) {
      await check(boundary + '-change-during-twelve-read-rejects-old-waveform-and-return-owner', async () => {
        await fresh(page);
        await page.evaluate(() => __fixture.defer.push({kind: 'waveform', leads: 12, repeat: true}));
        const selector = await cardSelector(page, 4800);
        await page.locator(selector + ' .occurrence-wave svg').dblclick();
        const id = await pendingTwelve(page);
        await page.evaluate(boundary => {
          if (boundary === 'case') {__state.caseId = 'mathematical-B'; __state.caseRequestId++; __state.caseData.case_id = 'mathematical-B';}
          if (boundary === 'revision') {__state.caseData.analysis_revision++; __state.editReadIdentity.analysis_revision++;}
          if (boundary === 'workspace') __state.workspaceEpoch = 'math-next-workspace';
          __state.waveform = null;
        }, boundary);
        await page.evaluate(id => __fixture.resolve(id), id);
        assert.equal((await snapshot(page)).waveform, null);
        await page.keyboard.press('Escape');
        await page.waitForFunction(() => !__state.waveformExpanded);
        const s = await snapshot(page);
        if (boundary === 'case') {assert.equal(s.caseId, 'mathematical-B'); assert.notEqual(s.page, 'edit');}
        if (boundary === 'workspace') assert.notEqual(s.page, 'edit');
      });
    }
    await check('stale-detached-card-cannot-open-under-a-new-case', async () => {
      await fresh(page);
      await page.evaluate(() => {
        const card = [...document.querySelectorAll('.occurrence-tile')].find(n => n.occurrenceItem.sample_index === 4800);
        globalThis.__staleCard = card;
        card.remove();
        __state.caseId = 'mathematical-B'; __state.caseRequestId++; __state.caseData.case_id = 'mathematical-B';
        card.dispatchEvent(new MouseEvent('dblclick', {bubbles: true}));
      });
      const s = await snapshot(page); assert.equal(s.expanded, false); assert.equal(s.caseId, 'mathematical-B');
      assert.equal(await page.evaluate(() => __fixture.calls.filter(c => c.query.leads?.split(',').length === 12).length), 0);
    });
    for (const sample of [20, 59980]) {
      await check('sample-' + sample + '-near-real-record-boundary-is-clamped-with-explicit-context', async () => {
        await fresh(page);
        if (sample === 59980) {
          await page.evaluate(() => {const host = $('#editTemplateGallery'); host.scrollTop = host.scrollHeight; clinicalUI.renderOccurrences();});
          await page.waitForFunction(() => [...document.querySelectorAll('.occurrence-tile')].some(n => n.occurrenceItem?.sample_index === 59980 && n.querySelector('svg')));
        }
        const selector = await cardSelector(page, sample);
        await page.locator(selector + ' .occurrence-wave svg').dblclick();
        await twelve(page, sample, {edge: true}); await escapeBack(page);
      });
    }
    assert.equal(pageErrors.length, 0, pageErrors.join('\n')); assert.equal(external.length, 0);
    console.log(JSON.stringify({passed: true, actual_check_count: checks.length, checks,
      chrome_sandbox: true, page_errors: pageErrors, external_requests: external.length,
      source_sha256: Object.fromEntries(['app.js','beat-editor-ui.js','clinical-ui.js','template-linked-view.js'].map(name =>
        [name, crypto.createHash('sha256').update(read('static/js/' + name)).digest('hex')]))}));
  } catch (error) {
    console.error(JSON.stringify({page_errors: pageErrors, fixture: await page.evaluate(() => ({
      errors: globalThis.__fixture?.errors || [], pending: globalThis.__fixture?.pending.map(p => p.id),
      waves: globalThis.__fixture?.calls.filter(c => c.kind === 'waveform').map(c => ({id: c.id, lane: c.lane, query: c.query, aborted: c.signal?.aborted})),
      owner: __state.editFullscreenReturn && {readState: __state.editFullscreenReturn.readState, target: __state.editFullscreenReturn.targetSample},
      waveform: __state.waveform && {start: __state.waveform.start_s, leads: Object.keys(__state.waveform.leads)}
    }))}));
    throw error;
  } finally {await context.close(); await browser.close();}
})().catch(error => {console.error(error.stack); process.exitCode = 1;});
