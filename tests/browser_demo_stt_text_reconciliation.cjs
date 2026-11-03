'use strict';
// Exercise the shipped fetch/localStorage adapter with original mathematical
// fixtures. The shared fixture harness supplies bytes, not save/reconcile logic.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const {harness} = require('./browser_demo_feedback_api.cjs');
const clone = value => JSON.parse(JSON.stringify(value));
const root = path.resolve(process.env.ECG_DEMO_SOURCE || path.join(__dirname, '..'));
const storageKey = 'cardioinsight-public-math-4314-v2';
const scope = value => Object.fromEntries(['case_id', 'analysis_basis', 'analysis_revision', 'beat_revision'].map(key => [key, value[key]]));
const evidence = {scope: 'actual-demo-ST-text-reconciliation-original-mathematical-inputs-only',
  patient_inputs: false, servers_started: false, external_network: false, checks: [],
  adapter_sha256: crypto.createHash('sha256').update(fs.readFileSync(path.join(root, 'demo/static/js/demo-api.js'))).digest('hex')};
const conclusion = '医生手写结论：逐字保留。\nMathematical test; no patient or diagnosis.';
async function payload(h, code = 'no_change', start = 2000) {
  return {sample_index: start, lead: 'II', category: 'note', label: 'Mathematical ST-T review',
    note: 'Original mathematical observation only.', details: {kind: 'ST', reviewed: true,
      result_code: code, review_scope: scope(await h.call('analysis-basis')),
      submission_id: crypto.randomUUID(), review_leads: ['II'], review_extent: 'point',
      end_sample: start + 999, physician_note: 'Doctor-owned mathematical note.',
      measurement_protocol: {measurement_ms: 60, extent: 'point', baseline_method: 'manual_iso_point'}}};
}
const eventId = annotation => annotation.stt_review_receipt.event_id;
const textKey = annotation => 'ST:review:' + eventId(annotation);
const use = annotation => ({event_id: eventId(annotation), basis_version: annotation.stt_review_receipt.basis_version,
  table: false, text: true, strip: true});
const selection = (annotation, caption) => ({event_id: eventId(annotation), basis_version: annotation.stt_review_receipt.basis_version,
  leads: ['II', 'V1', 'V5'], duration_s: 7, caption, notes: 'Preserve this curation verbatim.'});
async function saveReport(h, change) {
  const report = await h.call('report');
  return h.call('report', 'PUT', {status: 'draft', expected_version: report.version,
    expected_review_revision: report.review_revision, conclusion,
    composition: {...report.composition, include_hrv: false, page_selection_version: 1,
      included_pages: ['summary', 'event_strips'], ...change}});
}
async function adopted(h, own, other, manual = false) {
  const blocks = [
    {key: textKey(own), text: manual ? '医生改写的本条文字，不能自动删除。' : '本段未见明确 ST-T 改变：旧自动文字。',
      manual, needs_review: false, acknowledged: true},
    {key: textKey(other), text: 'Other adopted ST review: preserve verbatim.', manual: false, needs_review: false, acknowledged: false},
    {key: 'doctor:unrelated', text: '其他手写内容逐字不变。\nKeep these line breaks.', manual: true, needs_review: true, acknowledged: false},
    {key: textKey(own) + ':suffix', text: 'A distinct key with the same prefix remains.', manual: false, needs_review: false, acknowledged: false},
  ];
  const report = await saveReport(h, {selected_events: [selection(own, 'Own strip caption'), selection(other, 'Other strip caption')],
    stt_report_use: [use(own), use(other)], diagnosis_blocks: blocks});
  return report;
}
function assertOtherContent(before, after, own) {
  assert.equal(after.conclusion, before.conclusion, 'the handwritten final conclusion must remain byte-for-byte');
  assert.deepEqual(after.composition.diagnosis_blocks.filter(block => block.key !== textKey(own)),
    before.composition.diagnosis_blocks.filter(block => block.key !== textKey(own)), 'other record, handwritten and prefix-similar blocks remain exact');
  assert.deepEqual(after.composition.stt_report_use, before.composition.stt_report_use.filter(item => item.event_id !== eventId(own)));
  assert.deepEqual(after.composition.selected_events, before.composition.selected_events.filter(item => item.event_id !== eventId(own)));
}
async function run() {
  let h = harness();
  const createdPayload = await payload(h), own = await h.call('annotations', 'POST', createdPayload, 201);
  const other = await h.call('annotations', 'POST', await payload(h, 'indeterminate', 4000), 201);
  let before = await adopted(h, own, other), update = await payload(h, 'st_depression');
  update.expected_record_version = own.stt_review_receipt.record_version;
  let updated = await h.call('annotations/' + own.id, 'PUT', update), after = await h.call('report');
  assert.equal(updated.id, own.id); assert.equal(updated.stt_review_receipt.record_version, 2);
  assert.equal(after.composition.diagnosis_blocks.some(block => block.key === textKey(own)), false,
    'same-record result update must withdraw the old automatic normal narrative');
  assertOtherContent(before, after, own);
  assert.deepEqual(updated.stt_review_receipt.report_reconciliation.removed_diagnosis_blocks,
    before.composition.diagnosis_blocks.filter(block => block.key === textKey(own)));
  assert.equal(updated.details.withdrawn_report_settings[0].caption, 'Own strip caption');
  evidence.checks.push('PUT-withdraws-only-own-auto-text-and-uses-with-receipt-and-curation');

  before = await adopted(h, updated, other);
  const persisted = h.localStorage.getItem(storageKey), writes = h.localStorage.writes, audits = (await h.call('/api/audit')).items.length;
  const replayed = await h.call('annotations/' + own.id, 'PUT', clone(update));
  assert.equal(replayed.id, own.id); assert.equal(replayed.stt_review_receipt.record_version, 2);
  assert.equal(h.localStorage.writes, writes); assert.equal(h.localStorage.getItem(storageKey), persisted);
  assert.equal((await h.call('/api/audit')).items.length, audits);
  assert.deepEqual((await h.call('report')).composition, before.composition,
    'an exact retry must not withdraw freshly re-adopted text/strips or re-audit');
  await h.call('annotations/' + own.id, 'PUT', {...clone(update), note: 'Conflicting UUID content'}, 409);
  assert.equal(h.localStorage.getItem(storageKey), persisted);
  evidence.checks.push('PUT-UUID-replay-zero-writes-and-no-repeated-withdrawal-conflict-rejected');

  let failedUpdate = await payload(h, 't_change'); failedUpdate.expected_record_version = 2;
  h.localStorage.failNextWrite(); await h.call('annotations/' + own.id, 'PUT', failedUpdate, 400);
  assert.equal(h.localStorage.getItem(storageKey), persisted);
  assert.deepEqual((await h.call('report')).composition, before.composition);
  assert.equal((await h.call('annotations')).items.find(item => item.id === own.id).stt_review_receipt.record_version, 2);
  assert.equal((await h.call('/api/audit')).items.length, audits);
  evidence.checks.push('PUT-storage-failure-atomically-keeps-record-text-uses-and-audit');

  h.localStorage.failNextWrite(); await h.call('/api/annotations/' + own.id, 'DELETE', undefined, 400);
  assert.equal(h.localStorage.getItem(storageKey), persisted);
  assert.deepEqual((await h.call('report')).composition, before.composition);
  assert.equal((await h.call('annotations')).items.length, 2);
  assert.equal((await h.call('/api/audit')).items.length, audits);
  evidence.checks.push('DELETE-storage-failure-atomically-keeps-record-text-uses-and-audit');

  await h.call('/api/annotations/' + own.id, 'DELETE'); after = await h.call('report');
  assert.equal(after.composition.diagnosis_blocks.some(block => block.key === textKey(own)), false);
  assertOtherContent(before, after, own);
  assert.equal((await h.call('annotations')).items.length, 1);
  const deletedState = h.localStorage.getItem(storageKey);
  await h.call('annotations', 'POST', createdPayload, 409);
  await h.call('annotations/' + own.id, 'PUT', update, 409);
  assert.equal(h.localStorage.getItem(storageKey), deletedState, 'UUID tombstones must never recreate deleted records');
  evidence.checks.push('DELETE-removes-own-auto-text-only-and-keeps-UUID-tombstones');

  h = harness();
  let manualOwn = await h.call('annotations', 'POST', await payload(h), 201);
  const manualOther = await h.call('annotations', 'POST', await payload(h, 'indeterminate', 4000), 201);
  before = await adopted(h, manualOwn, manualOther, true);
  update = await payload(h, 'st_elevation'); update.expected_record_version = 1;
  updated = await h.call('annotations/' + manualOwn.id, 'PUT', update); after = await h.call('report');
  assertOtherContent(before, after, manualOwn);
  const manualBefore = before.composition.diagnosis_blocks.find(block => block.key === textKey(manualOwn));
  assert.deepEqual(after.composition.diagnosis_blocks.find(block => block.key === textKey(manualOwn)),
    {...manualBefore, needs_review: true, acknowledged: false}, 'same-key physician text must survive and require review');
  assert.deepEqual(updated.stt_review_receipt.report_reconciliation.removed_diagnosis_blocks, []);
  evidence.checks.push('PUT-keeps-physician-edited-own-text-verbatim-and-marks-review');

  before = await adopted(h, updated, manualOther, true);
  await h.call('/api/annotations/' + manualOwn.id, 'DELETE'); after = await h.call('report');
  assertOtherContent(before, after, manualOwn);
  assert.deepEqual(after.composition.diagnosis_blocks.find(block => block.key === textKey(manualOwn)),
    {...before.composition.diagnosis_blocks.find(block => block.key === textKey(manualOwn)), needs_review: true, acknowledged: false});
  evidence.checks.push('DELETE-keeps-physician-edited-own-text-verbatim-and-marks-review');

  const created = await payload(h, 'no_change', 6000), storageBeforeCreate = h.localStorage.getItem(storageKey);
  const createReport = await h.call('report');
  const fresh = await h.call('annotations', 'POST', created, 201);
  assert.deepEqual((await h.call('report')).composition.diagnosis_blocks, createReport.composition.diagnosis_blocks,
    'new review creation must not withdraw another record or manually preserved history');
  const createdState = h.localStorage.getItem(storageKey), createdWrites = h.localStorage.writes;
  await h.call('annotations', 'POST', clone(created), 201);
  assert.equal(h.localStorage.writes, createdWrites); assert.equal(h.localStorage.getItem(storageKey), createdState);
  assert.notEqual(createdState, storageBeforeCreate); assert.equal(fresh.stt_review_receipt.record_version, 1);
  evidence.checks.push('POST-creation-and-replay-preserve-existing-adopted-and-handwritten-text');
  evidence.passed = evidence.checks.length;
}
run().then(() => console.log(JSON.stringify(evidence))).catch(error => {
  evidence.passed = false; evidence.error = String(error); console.error(JSON.stringify(evidence)); console.error(error); process.exitCode = 1;
});
