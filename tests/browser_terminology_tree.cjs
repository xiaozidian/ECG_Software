'use strict';
// Real Chrome DOM with original/synthetic phrases and an isolated mocked catalog API.
// Backend integrity and actual SQLite versioning are covered by test_terminology_validation.py.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {chromium} = require(process.env.ECG_PLAYWRIGHT_CORE || '/Users/yuanzhidian/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright-core');
const out = path.resolve(process.env.ECG_TERMINOLOGY_EVIDENCE || '/tmp/ecg-terminology-browser-evidence');
const result = {scope: 'synthetic-component-only', checks: [], errors: [], external_requests: [], screenshots: []};
const builtin = JSON.parse(fs.readFileSync('static/terminology/builtin-draft-v1.json', 'utf8'));
function sorted(value) { return Array.isArray(value) ? value.map(sorted) : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(key => [key, sorted(value[key])])) : value; }
function make(version, text) {
  const value = structuredClone(builtin); value.namespace = 'synthetic.phrases'; value.version = version; value.title = 'Synthetic report phrases ' + version;
  value.nodes[1].text = text; delete value.sha256;
  value.sha256 = crypto.createHash('sha256').update(JSON.stringify(sorted(value))).digest('hex'); return value;
}
const a = make('v1', 'Synthetic original phrase.'), b = make('v2', 'Synthetic newer phrase.'), c = make('v3', 'Synthetic imported phrase.');
const save = () => fs.writeFileSync(path.join(out, 'results.json'), JSON.stringify(result, null, 2) + '\n');
function record(name) { result.checks.push(name); save(); console.log(name); }
let browser, page;
(async () => {
  fs.mkdirSync(out, {recursive: true});
  browser = await chromium.launch({executablePath: process.env.ECG_CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true, chromiumSandbox: true});
  result.browser = await browser.version();
  const context = await browser.newContext({viewport: {width: 1040, height: 900}});
  await context.route('**/*', route => { result.external_requests.push(route.request().url()); return route.abort(); });
  page = await context.newPage(); page.on('pageerror', error => result.errors.push(error.message));
  await page.setContent('<!doctype html><meta charset="utf-8"><title>Synthetic terminology verification</title><main style="max-width:850px;margin:auto"><label>Doctor synthetic draft<textarea id="editor" rows="4" style="display:block;width:100%">Doctor free text.</textarea></label><div id="host"></div></main>');
  await page.addStyleTag({content: fs.readFileSync('static/css/terminology-tree.css', 'utf8')});
  await page.addScriptTag({content: fs.readFileSync('static/js/terminology-tree.js', 'utf8')});
  await page.evaluate(({a, b}) => {
    window.syntheticCatalogs = [a, b]; window.calls = []; window.savedUsages = []; window.insertNotifications = []; window.revision = 0;
    window.activeSyntheticCase = 'synthetic-A'; window.holdNextVersion = null; window.catalogGate = null;
    window.syntheticApi = async (url, init = {}) => {
      window.calls.push({url, method: init.method || 'GET', payload: init.body ? JSON.parse(init.body) : null});
      if (url === '/api/terminology/catalogs') return {catalog_revision: window.revision, items: window.syntheticCatalogs.map(value => ({...value, builtin: false}))};
      if (url.startsWith('/api/terminology/catalog?')) {
        const query = new URLSearchParams(url.split('?')[1]), value = window.syntheticCatalogs.find(item => item.namespace === query.get('namespace') && item.version === query.get('version') && item.sha256 === query.get('hash'));
        if (window.holdNextVersion === query.get('version')) {
          window.holdNextVersion = null;
          return new Promise(resolve => { window.catalogGate = () => resolve(structuredClone(value)); });
        }
        return structuredClone(value);
      }
      if (url === '/api/terminology/import') {
        const payload = JSON.parse(init.body), value = payload.catalog;
        if (payload.expected_catalog_revision !== window.revision) throw new Error('Synthetic catalog revision conflict');
        if (payload.confirm) {
          if (payload.preview_hash !== value.sha256) throw new Error('Synthetic preview hash conflict');
          window.syntheticCatalogs.push(value); window.revision++;
        }
        return {preview_only: !payload.confirm, catalog_revision: window.revision, catalog: structuredClone(value), summary: {}, preview_hash: value.sha256, warnings: ['来源和核准状态仅按导入声明，软件未独立验证。']};
      }
      throw new Error('Unexpected synthetic API request: ' + url);
    };
    window.tree = ECGTerminologyTree.mount(document.getElementById('host'), {editor: document.getElementById('editor'), caseId: 'synthetic-A', reportContext: 'draft-r1', api: window.syntheticApi,
      isCurrent: () => window.activeSyntheticCase === 'synthetic-A', onUsageDirty: values => { window.savedUsages = structuredClone(values); }, onInsert: value => window.insertNotifications.push(value)});
    return window.tree.ready;
  }, {a, b});
  const text = () => page.locator('#editor').inputValue();
  const node = id => page.locator(`[data-tt-node="${id}"]`);
  await node('group.review').click();
  assert(await page.locator('[data-tt-insert]').isDisabled());
  assert.equal(await text(), 'Doctor free text.');
  assert.match(await page.locator('[data-tt-preview]').textContent(), /不能插入/);
  record('group-is-navigation-only-and-preview-does-not-edit-report');
  await page.locator('[data-tt-search]').fill('人工复核');
  assert.equal(await node('review.waveform').count(), 1);
  assert.equal(await node('activity.atrial').count(), 0);
  await node('review.waveform').click();
  assert.equal(await page.locator('[data-tt-original]').textContent(), a.nodes[1].text);
  assert.equal(await text(), 'Doctor free text.');
  assert.match(await page.locator('[data-tt-preview]').textContent(), /未独立验证|医生需核对/);
  record('alias-search-reveals-ancestor-and-original-preview-remains-read-only');
  await page.locator('#editor').evaluate(editor => { editor.setSelectionRange(0, 6); });
  await page.locator('[data-tt-insert]').click();
  assert.equal(await text(), 'Doctor' + a.nodes[1].text + ' free text.');
  const snapshot = await page.evaluate(() => window.savedUsages);
  assert.equal(snapshot.length, 1); assert.equal(snapshot[0].catalog_hash, a.sha256); assert.equal(snapshot[0].inserted_text, a.nodes[1].text); assert.equal(snapshot[0].approval, 'draft');
  assert.equal(await page.evaluate(() => window.insertNotifications.length), 1);
  assert(await page.locator('[data-tt-undo]').isEnabled());
  await page.locator('[data-tt-undo]').click();
  assert.equal(await text(), 'Doctor free text.'); assert.deepEqual(await page.evaluate(() => window.savedUsages), []);
  record('explicit-insert-preserves-doctor-selection-and-immediate-undo-removes-only-insertion');
  await page.locator('[data-tt-insert]').click();
  await page.locator('#editor').fill((await text()) + ' Doctor later edit.');
  const edited = await text();
  assert(await page.locator('[data-tt-undo]').isDisabled());
  assert.equal(await page.evaluate(() => window.tree.undoLast()), false);
  assert.equal(await text(), edited); assert.equal((await page.evaluate(() => window.savedUsages)).length, 1);
  record('physician-edit-disables-undo-and-preserves-text-and-usage-snapshot');
  await page.locator('[data-tt-catalog]').selectOption('1');
  await page.waitForFunction(() => document.querySelector('[data-tt-catalog-info]').textContent.includes(' / v2'));
  await page.locator('[data-tt-search]').fill(''); await node('review.waveform').click();
  assert.equal(await page.locator('[data-tt-original]').textContent(), b.nodes[1].text);
  assert.equal(await text(), edited); assert.equal((await page.evaluate(() => window.savedUsages))[0].inserted_text, a.nodes[1].text);
  const saved = await page.evaluate(() => window.savedUsages);
  await page.evaluate(usages => { window.tree.destroy(); window.tree = ECGTerminologyTree.mount(document.getElementById('host'), {editor: document.getElementById('editor'), caseId: 'synthetic-A', reportContext: 'saved-r1', api: window.syntheticApi, usages,
    onUsageDirty: value => window.savedUsages = value}); return window.tree.ready; }, saved);
  assert.equal(await text(), edited); assert.deepEqual(await page.evaluate(() => window.tree.getUsages()), saved);
  record('version-update-and-report-reopen-keep-original-inserted-text-and-version-hash');
  await page.evaluate(b => { window.catalogGate = null; window.holdNextVersion = 'v2'; window.pendingOldCatalog = window.tree.loadCatalog(b); }, b);
  await page.waitForFunction(() => !!window.catalogGate);
  await page.evaluate(a => window.tree.loadCatalog(a), a);
  await page.evaluate(() => { window.catalogGate(); return window.pendingOldCatalog; });
  assert.match(await page.locator('[data-tt-catalog-info]').textContent(), / \/ v1/);
  record('late-old-catalog-request-cannot-overwrite-new-version-selection');
  await page.evaluate(b => { window.catalogGate = null; window.holdNextVersion = 'v2'; window.pendingOldCase = window.tree.loadCatalog(b); }, b);
  await page.waitForFunction(() => !!window.catalogGate);
  await page.evaluate(() => window.tree.setContext({caseId: 'synthetic-B', reportContext: 'new-report', usages: []}));
  await page.evaluate(() => { window.catalogGate(); return window.pendingOldCase; });
  assert.deepEqual(await page.evaluate(() => window.tree.getUsages()), []);
  assert.match(await page.locator('[data-tt-catalog-info]').textContent(), / \/ v1/);
  const v1Loads = await page.evaluate(() => window.calls.filter(call => call.url.includes('/catalog?') && call.url.includes('version=v1')).length);
  assert(v1Loads >= 3, 'Switching report context must refetch rather than share cache');
  record('case-and-report-context-reset-isolates-usages-cache-and-late-response');
  await page.locator('.tt-import > summary').click();
  await page.locator('[data-tt-import-file]').setInputFiles({name: 'synthetic-v3.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(c))});
  await page.waitForFunction(() => document.querySelector('[data-tt-import-preview]').textContent.includes('检查全部词条原文'));
  const previewCalls = await page.evaluate(() => window.calls.filter(call => call.url === '/api/terminology/import'));
  assert.equal(previewCalls.length, 1); assert.equal(previewCalls[0].payload.confirm, false);
  assert(await page.locator('[data-tt-import-confirm]').isDisabled());
  await page.locator('[data-tt-import-consent]').check();
  await page.locator('[data-tt-import-confirm]').click();
  await page.waitForFunction(() => document.querySelector('[data-tt-import-preview]').textContent.includes('已发布到本机'));
  const importCalls = await page.evaluate(() => window.calls.filter(call => call.url === '/api/terminology/import'));
  assert.equal(importCalls.length, 2); assert.equal(importCalls[1].payload.confirm, true); assert.equal(importCalls[1].payload.preview_hash, c.sha256);
  assert.equal(await page.locator('[data-tt-catalog] option').count(), 3);
  assert.match(await page.locator('[data-tt-catalog-info]').textContent(), / \/ v1/);
  assert.equal(await text(), edited);
  record('file-import-previews-full-content-before-explicit-local-publication-and-does-not-change-selection');
  await page.locator('[data-tt-search]').fill(''); await page.locator('[data-tt-collapse-all]').click();
  assert.equal(await node('review.waveform').count(), 0);
  await page.locator('[data-tt-expand-all]').click();
  assert.equal(await node('review.waveform').count(), 1);
  record('expand-and-collapse-control-only-navigation');
  await node('review.waveform').click();
  await page.screenshot({path: path.join(out, 'synthetic-terminology-tree.png'), fullPage: true}); result.screenshots.push('synthetic-terminology-tree.png');
  // DOM text rendering remains inert even for a corrupt direct test-only response.
  await page.evaluate(a => { const hostile = structuredClone(a); hostile.version = 'hostile'; hostile.title = '<img src=x onerror=window.xss=true>'; hostile.nodes[1].label = '<svg onload=window.xss=true>'; window.syntheticCatalogs.push(hostile); return window.tree.loadCatalog(hostile); }, a);
  assert.equal(await page.locator('#host img, #host svg, #host script').count(), 0);
  assert.equal(await page.evaluate(() => !!window.xss), false);
  record('all-catalog-names-and-previews-render-as-inert-text-content');
  assert.deepEqual(result.errors, []); assert.deepEqual(result.external_requests, []);
  result.passed = true; save();
  await browser.close(); result.owned_Chrome_closed = true; save();
})().catch(async error => { result.passed = false; result.failure = String(error.stack); save(); if (browser) await browser.close(); console.error(result.failure); process.exitCode = 1; });
