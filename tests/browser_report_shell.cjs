// Execute the shipped shell and preflight renderers together, without a browser.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const elements = new Map();
const element = selector => {
  if (!elements.has(selector)) elements.set(selector, {textContent: '', innerHTML: '', value: '', dataset: {}});
  return elements.get(selector);
};
const state = {
  report: {version: 5, status: 'draft', conclusion: 'saved conclusion', updated_at: 'saved time'},
  reportDirty: true, reportStale: false, reportSaving: false, editBeatOverrides: new Map(),
};
let pendingSteps = [], isWritable = true;
const ctx = vm.createContext({
  state, qs: element, $: element, tabs: [], reportData: null, category: 'final',
  selected: () => [], selectedLookup: new Map(), STATUS_TEXT: {draft: '未审核'},
  updateConclusionCount: () => {}, pending: () => pendingSteps, writable: () => isWritable,
  data: {steps: {}, events: {}}, CASE_WORKFLOW_STEPS: [],
  escapeHtml: String, formatElapsed: String,
  renderRangeDraftNotice: () => {},
  renderRhythmReturn: () => {},
});
vm.runInContext(fs.readFileSync('static/js/report-range-editor.js', 'utf8'), ctx);
vm.runInContext(fs.readFileSync('static/js/report-consistency.js', 'utf8'), ctx);
const workflow = fs.readFileSync('static/js/clinical-workflow.js', 'utf8');
vm.runInContext(workflow.slice(workflow.indexOf('  function renderPreflight('), workflow.indexOf('  function decision(')), ctx);
ctx.clinicalWorkflow = {readiness: () => !pendingSteps.length, writable: () => isWritable, renderPreflight: ctx.renderPreflight};
const ui = fs.readFileSync('static/js/clinical-ui.js', 'utf8');
vm.runInContext(ui.slice(ui.indexOf('  function renderReportShell('), ui.indexOf('  async function reloadReport(')), ctx);

element('#conclusionEditor').value = 'unsaved local input';
ctx.renderPreflight();
assert.match(element('#reportPreflightDisclosure summary').textContent, /有未保存修改/);

// Explicitly loading a newer report must clear both the editor and checklist status.
state.reportDirty = false;
ctx.renderReportShell();
assert.equal(element('#conclusionEditor').value, 'saved conclusion');
assert.equal(element('#reportSaveState').textContent, '已保存 saved time');
assert.doesNotMatch(element('#reportPreflightDisclosure summary').textContent, /有未保存修改|依据已变化/);
assert.equal(element('#approveReport').disabled, false);

// Remote invalidation must reach the same checklist even without a workflow fetch.
state.reportStale = true;
ctx.renderReportShell();
assert.match(element('#reportPreflightDisclosure summary').textContent, /依据已变化/);
assert.equal(element('#reportConflict').hidden, false);
assert.equal(element('#approveReport').disabled, true);

// Re-rendering cannot erase in-flight local typing or enable approval prematurely.
state.reportStale = false;
state.reportDirty = true;
element('#conclusionEditor').value = 'keep this new input';
ctx.renderReportShell();
assert.equal(element('#conclusionEditor').value, 'keep this new input');
assert.match(element('#reportPreflightDisclosure summary').textContent, /有未保存修改/);
assert.equal(element('#approveReport').disabled, true);

state.reportDirty = false;
for (const condition of ['saving', 'readonly', 'pending', 'empty','loading','failed','manual']) {
  state.reportSaving = condition === 'saving';
  state.reportEvidenceLoading = condition === 'loading';
  state.reportEvidenceError = condition === 'failed';
  state.reportComposition = {diagnosis_blocks:condition==='manual'?[{needs_review:true}]:[]};
  isWritable = condition !== 'readonly';
  pendingSteps = condition === 'pending' ? ['edit'] : [];
  state.report.conclusion = condition === 'empty' ? '' : 'saved conclusion';
  ctx.renderReportShell();
  assert.equal(element('#approveReport').disabled, true, condition);
  if(condition==='loading')assert.match(element('#reportPreflightDisclosure summary').textContent,/依据核对中/);
  if(condition==='failed')assert.match(element('#reportPreflightDisclosure summary').textContent,/依据读取失败/);
  if(condition==='manual')assert.match(element('#reportPreflightDisclosure summary').textContent,/人工诊断文字待核对/);
}
console.log('report shell/preflight state synchronization passed');
