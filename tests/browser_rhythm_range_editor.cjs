'use strict';
// Synthetic contract oracles. No patient data, browser profile, or server needed.
const assert = require('node:assert/strict');
const E = require('../static/js/rhythm-range-editor.js');
const copy = x => JSON.parse(JSON.stringify(x));
const scope = (extra = {}) => ({case_id: 'synthetic-a', caseToken: 1, analysis_basis: 'source-fixture',
  analysis_revision: 4, beat_revision: 2, workspace_epoch: 'workspace-fixture', duration_s: 640,
  sample_rate_hz: 200, ...extra});
const surface = (s = scope(), extra = {}) => ({owner_scope: E.scope(s), wave: {start_s: 10, duration_s: 20},
  plot: {left: 50, top: 27, width: 1000, height: 264}, ...extra});
const document = () => ({episodes: [], bookmarks: {fastest: 12.005, slowest_nn: 45}});
const item = (extra = {}) => ({id: 'existing', start_s: 12, end_s: 14, kind: 'AF', status: 'pending', source: 'manual', note: '', ...extra});
function fixture(config = {}) {
  let current = scope(), value = {...E.identity(current), revision: 3, document: document()}, calls = [], saved = [], notices = [], next = 0;
  const api = async (path, options) => {
    const call = {path, ...options}; calls.push(call);
    if (config.api) return config.api(call, value, current);
    if (options.method === 'PUT') {
      const payload = JSON.parse(options.body);
      assert.equal(payload.revision, value.revision);
      assert.equal(payload.beat_revision, 2);
      assert.equal(payload.analysis_revision, 4);
      assert.equal(payload.confirmed, true);
      assert.equal(payload.operation, 'save');
      value = {...value, analysis_revision: value.analysis_revision + 1, revision: value.revision + 1, document: copy(payload.document)};
      if (config.put) return config.put(value, call);
    }
    return copy(value);
  };
  const session = E.createSession({getScope: () => current, api, uuid: () => 'fixed-draft-' + (++next),
    canWrite: () => config.readonly !== true,
    onSaved: async result => { saved.push(result); if (config.refreshFail) throw Error('refresh failed'); },
    onNotice: text => notices.push(text)});
  return {session, calls, saved, notices, setScope: x => { current = x; },
    getScope: () => current, getValue: () => value, setValue: x => { value = x; }};
}
async function ready(f, start = 2000, end = 2001) {
  f.session.begin(start); f.session.update({end_sample_exclusive: end}); await f.session.prepare();
}
const tests = {
  'sample-grid': () => {
    const s = E.scope(scope()), w = surface();
    assert.equal(E.pointerSample(s, w, 50), 2000);
    assert.equal(E.pointerSample(s, w, 550), 4000);
    assert.equal(E.pointerSample(s, w, 1050), 6000);
    assert.equal(E.pointerSample(s, w, 50.25), 2001);
    assert.equal(E.pointerSample(s, w, 550), E.pointerSample(s, {...w, wave: {...w.wave, stride: 17}}, 550));
  },
  'plot-gutter': () => {
    const s = E.scope(scope()), w = surface();
    assert.throws(() => E.pointerSample(s, w, 49.999), /绘图区/);
    assert.throws(() => E.pointerSample(s, w, 1050.001), /绘图区/);
    assert.throws(() => E.pointerSample(s, w, NaN), /绘图区/);
  },
  'surface-scope': () => {
    for (const key of ['case_id', 'caseToken', 'analysis_basis', 'analysis_revision', 'beat_revision', 'workspace_epoch']) {
      const s = E.scope(scope()), w = surface(); w.owner_scope[key] = 'wrong';
      assert.throws(() => E.pointerSample(s, w, 550), /依据/);
    }
    assert.throws(() => E.pointerSample(E.scope(scope()), {...surface(), owner_scope: undefined}, 550), /依据/);
  },
  'strict-scope': () => {
    for (const bad of [{analysis_revision: true}, {beat_revision: '2'}, {sample_rate_hz: 250},
      {duration_s: 10.0001}, {caseToken: null}, {analysis_basis: ''}, {duration_s: Infinity}])
      assert.throws(() => E.scope(scope(bad)));
    assert.throws(() => E.identity({...E.identity(scope()), beat_revision: false}));
  },
  'typed-grid': () => {
    const s = E.scope(scope());
    assert.equal(E.secondsSample('10.005', s), 2001);
    assert.equal(E.secondsSample('640', s), 128000);
    for (const x of ['', ' ', '-1', '10.001', 'Infinity', 'NaN', '640.005']) assert.throws(() => E.secondsSample(x, s));
  },
  'half-open-single-sample': () => {
    assert.deepEqual(E.range(2000, 2001, E.scope(scope())), {start_sample: 2000, end_sample_exclusive: 2001, start_s: 10, end_s: 10.005});
  },
  'whole-recording-end': () => {
    assert.deepEqual(E.range(0, 128000, E.scope(scope())), {start_sample: 0, end_sample_exclusive: 128000, start_s: 0, end_s: 640});
    for (const [a, b] of [[0, 0], [2001, 2000], [128000, 128000], [0, 128001], [-1, 2], [true, 2]])
      assert.throws(() => E.range(a, b, E.scope(scope())));
  },
  'overlay-clips-no-fake-lines': () => {
    const draft = {scope: E.scope(scope()), start_sample: 1000, end_sample_exclusive: 8000};
    const g = E.overlayGeometry(draft, surface());
    assert.equal(g.start_x, null); assert.equal(g.end_x, null);
    assert.equal(g.start_offscreen, true); assert.equal(g.end_offscreen, true);
    assert.deepEqual(g.shade, {x: 50, width: 1000});
  },
  'overlay-visible-exact-endpoints': () => {
    const g = E.overlayGeometry({scope: E.scope(scope()), start_sample: 2000, end_sample_exclusive: 2001}, surface());
    assert.equal(g.start_x, 50); assert.equal(g.end_x, 50.25); assert.deepEqual(g.shade, {x: 50, width: .25});
  },
  'adjacent-not-overlap': () => {
    const d = {episodes: [item({status: 'confirmed', kind: 'AFL'})], bookmarks: {}};
    assert.equal(E.overlaps(item({id: 'new', start_s: 14, end_s: 14.005, status: 'confirmed'}), d).length, 0);
    assert.equal(E.append(d, item({id: 'new', start_s: 14, end_s: 14.005, status: 'confirmed'})).episodes.length, 2);
  },
  'confirmed-af-afl-conflict': () => {
    for (const kind of ['AF', 'AFL']) {
      const d = {episodes: [item({status: 'confirmed', kind})], bookmarks: {}};
      assert.throws(() => E.append(d, item({id: 'new', start_s: 13, end_s: 15, status: 'confirmed'})), /不能重叠/);
    }
  },
  'pending-overlap-preserves-all': () => {
    const d = {episodes: [item({status: 'confirmed'}), item({id: 'excluded', status: 'excluded'})], bookmarks: {fastest: 1.005}};
    const before = copy(d), result = E.append(d, item({id: 'new', start_s: 13, end_s: 15}));
    assert.deepEqual(d, before); assert.deepEqual(result.episodes.slice(0, 2), before.episodes);
    assert.deepEqual(result.bookmarks, before.bookmarks); assert.equal(E.overlaps(result.episodes[2], d).length, 2);
  },
  'default-pending-fixed-uuid': async () => {
    const f = fixture(); f.session.begin(2000); const id = f.session.snapshot().draft.id;
    f.session.update({end_sample_exclusive: 2001}); await f.session.prepare(); f.session.begin(1999);
    assert.equal(f.session.snapshot().draft.id, id); assert.equal(f.session.snapshot().draft.status, 'pending');
    assert.equal(f.calls.filter(x => x.method === 'PUT').length, 0);
  },
  'atomic-update': () => {
    const f = fixture(); f.session.begin(2000);
    assert.throws(() => f.session.update({start_sample: 2100, end_sample_exclusive: -1}));
    assert.equal(f.session.snapshot().draft.start_sample, 2000);
  },
  'save-all-fields-and-revisions': async () => {
    const f = fixture(); await ready(f); const result = await f.session.save(true);
    assert.equal(result.saved, true); assert.equal(f.saved.length, 1); assert.equal(f.session.pending(), false);
    const payload = JSON.parse(f.calls.find(x => x.method === 'PUT').body);
    assert.equal(payload.revision, 3); assert.equal(payload.beat_revision, 2); assert.equal(payload.analysis_revision, 4);
    assert.deepEqual(payload.document.bookmarks, document().bookmarks);
    assert.deepEqual(payload.document.episodes[0], item({id: 'fixed-draft-1', start_s: 10, end_s: 10.005}));
  },
  'save-ack-required': async () => {
    const f = fixture(); await ready(f); await assert.rejects(f.session.save(false), /勾选/);
    assert.equal(f.calls.filter(x => x.method === 'PUT').length, 0); assert.equal(f.session.pending(), true);
  },
  'readonly-no-put': async () => {
    const f = fixture({readonly: true}); await ready(f); await assert.rejects(f.session.save(true), /只读/);
    assert.equal(f.calls.filter(x => x.method === 'PUT').length, 0);
  },
  'current-rhythm-changed-no-rebase': async () => {
    const f = fixture(); await ready(f); f.setValue({...f.getValue(), revision: 4});
    await assert.rejects(f.session.save(true), /未自动追加/);
    assert.equal(f.calls.filter(x => x.method === 'PUT').length, 0); assert.equal(f.session.snapshot().draft.stale, true);
  },
  'scope-change-no-put': async () => {
    for (const key of ['caseToken', 'analysis_revision', 'beat_revision', 'analysis_basis', 'workspace_epoch']) {
      const f = fixture(); await ready(f); f.setScope({...f.getScope(), [key]: 'changed'}); f.session.sync();
      await assert.rejects(f.session.save(true)); assert.equal(f.calls.filter(x => x.method === 'PUT').length, 0);
    }
  },
  'case-switch-preserves-stale-draft': async () => {
    const f = fixture(); await ready(f); const id = f.session.snapshot().draft.id;
    f.setScope(scope({case_id: 'synthetic-b', caseToken: 2})); f.session.sync();
    assert.equal(f.session.snapshot().draft, null); assert.equal(f.session.pending(), true);
    f.setScope(scope({caseToken: 3})); f.session.sync();
    assert.equal(f.session.snapshot().draft.id, id); assert.equal(f.session.snapshot().current, false);
    await assert.rejects(f.session.save(true)); f.session.cancel(); assert.equal(f.session.pending(), false);
  },
  'late-prepare-no-current-adoption': async () => {
    let release; const f = fixture({api: () => new Promise(r => { release = r; })});
    f.session.begin(2000); const p = f.session.prepare();
    f.setScope(scope({case_id: 'synthetic-b', caseToken: 2})); f.session.sync(); release(f.getValue());
    await assert.rejects(p, /病例或修订/); assert.equal(f.session.snapshot().draft, null);
    assert.equal(f.calls[0].signal.aborted, true);
  },
  'late-save-get-no-put': async () => {
    let release, reads = 0;
    const f = fixture({api: (call, value) => ++reads === 1 ? copy(value) : new Promise(r => { release = r; })});
    await ready(f); const p = f.session.save(true); f.setScope(scope({case_id: 'synthetic-b', caseToken: 2})); f.session.sync();
    release(f.getValue()); await assert.rejects(p); assert.equal(f.calls.filter(x => x.method === 'PUT').length, 0);
  },
  'late-put-never-calls-new-case-refresh': async () => {
    let release; const f = fixture({put: value => new Promise(r => { release = () => r(copy(value)); })});
    await ready(f); const p = f.session.save(true); await new Promise(r => setImmediate(r));
    assert.equal(f.session.isSaving(), true); f.setScope(scope({case_id: 'synthetic-b', caseToken: 2})); f.session.sync(); release();
    const result = await p; assert.equal(result.saved, true); assert.equal(result.current, false); assert.equal(f.saved.length, 0);
  },
  'put-response-loss-exactly-once': async () => {
    const f = fixture({put: () => { throw Error('response lost'); }}); await ready(f); const id = f.session.snapshot().draft.id;
    await assert.rejects(f.session.save(true)); assert.equal(f.session.snapshot().draft.uncertain, true);
    await assert.rejects(f.session.save(true), /不能重复保存/);
    const result = await f.session.reconcile(); assert.equal(result.saved, true); assert.equal(result.reconciled, true);
    assert.equal(f.calls.filter(x => x.method === 'PUT').length, 1); assert.equal(f.getValue().document.episodes[0].id, id);
    const query = new URL(f.calls.at(-1).path, 'http://fixture').searchParams;
    assert.equal(query.has('analysis_revision'), false); assert.equal(query.get('beat_revision'), '2');
    assert.equal(query.get('case_id'), 'synthetic-a'); assert.equal(f.saved.length, 1);
  },
  'unknown-no-id-never-retries': async () => {
    const f = fixture({api: (call, value) => {
      if (call.method === 'PUT') throw Error('connection lost'); return copy(value);
    }}); await ready(f); await assert.rejects(f.session.save(true));
    const result = await f.session.reconcile(); assert.equal(result.unresolved, true);
    assert.equal(f.session.snapshot().draft.uncertain, true);
    assert.throws(() => f.session.update({status: 'confirmed'}), /不能重复保存/);
    assert.throws(() => f.session.cancel(), /标识保留/);
    assert.equal(f.calls.filter(x => x.method === 'PUT').length, 1);
  },
  'lost-response-case-return-read-only-reconciliation': async () => {
    const f = fixture({put: () => { throw Error('response lost'); }}); await ready(f);
    await assert.rejects(f.session.save(true));
    f.setScope(scope({case_id: 'synthetic-b', caseToken: 2})); f.session.sync();
    await assert.rejects(f.session.reconcile());
    f.setScope(scope({caseToken: 3})); f.session.sync();
    const pending = f.session.reconcile(); f.session.sync();
    const result = await pending; assert.equal(result.saved, true); assert.equal(f.calls.at(-1).signal.aborted, false);
    assert.equal(f.saved[0].scope.caseToken, 3); assert.equal(f.saved[0].draft_scope.caseToken, 1);
    assert.equal(f.calls.filter(x => x.method === 'PUT').length, 1);
  },
  'uuid-mismatch-blocks-reconciliation': async () => {
    const f = fixture({put: value => { value.document.episodes[0].status = 'confirmed'; return copy(value); }});
    await ready(f); await assert.rejects(f.session.save(true));
    const result = await f.session.reconcile(); assert.equal(result.mismatch, true);
    assert.equal(f.session.pending(), true); assert.equal(f.calls.filter(x => x.method === 'PUT').length, 1);
  },
  'same-uuid-note-mismatch': () => {
    const a = item(); assert.equal(E.matchingEpisode(a, {...a, note: 'changed'}), false);
    assert.equal(E.matchingEpisode(a, {...a, source: 'source-annotation'}), false);
    assert.equal(E.matchingEpisode(a, {...a, end_s: 14.005}), false);
  },
  'successful-save-refresh-failure-not-retry': async () => {
    const f = fixture({refreshFail: true}); await ready(f); const result = await f.session.save(true);
    assert.equal(result.saved, true); assert.equal(result.refresh_failed, true);
    assert.equal(f.session.pending(), false); assert.equal(f.notices.length, 1);
    await assert.rejects(f.session.save(true)); assert.equal(f.calls.filter(x => x.method === 'PUT').length, 1);
  },
  'cross-case-response-rejected': async () => {
    const f = fixture({api: (call, value) => ({...value, case_id: 'synthetic-b'})});
    f.session.begin(2000); await assert.rejects(f.session.prepare(), /草稿依据/);
    assert.equal(f.session.snapshot().draft.base, null); assert.equal(f.calls.filter(x => x.method === 'PUT').length, 0);
  },
  'beat-response-rejected': async () => {
    const f = fixture({api: (call, value) => ({...value, beat_revision: 3})});
    f.session.begin(2000); await assert.rejects(f.session.prepare(), /草稿依据/);
  },
  'complete-response-required': async () => {
    const f = fixture({api: (call, value) => { const result = copy(value); delete result.case_id; return result; }});
    f.session.begin(2000); await assert.rejects(f.session.prepare(), /完整病例/);
  },
  'dispose-cancels-read': async () => {
    let release; const f = fixture({api: () => new Promise(r => { release = r; })});
    f.session.begin(2000); const p = f.session.prepare(); f.session.dispose();
    assert.equal(f.calls[0].signal.aborted, true); release(f.getValue()); await assert.rejects(p);
    await assert.rejects(f.session.save(true));
  },
};
(async () => {
  const selected = process.argv[2] ? {[process.argv[2]]: tests[process.argv[2]]} : tests;
  for (const [name, fn] of Object.entries(selected)) { assert.equal(typeof fn, 'function', name); await fn(); }
  console.log(JSON.stringify({passed: Object.keys(selected).length, scenarios: Object.keys(selected)}));
})().catch(error => { console.error(error); process.exitCode = 1; });
