"""Only disposable synthetic cases; caching must never change ECG label semantics."""
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
import threading

import pytest

from ecg_core.beat_editor import BeatEditorStore, EditedRecords, blank
from ecg_core.clinical_query_cache import WaveformBeatCache
from ecg_core.ebi import visible_beats, load_records, HEADER_SIZE, RECORD
from test_analysis_provenance import synthetic_case, synthetic_app, replace_preserving_mtime


def wave(client, cid, endpoint='event-waveforms', edited=True, **extra):
    args = {'analysis': 'edited'} if edited else {}
    if endpoint == 'event-waveforms':
        return client.post(f'/api/cases/{cid}/{endpoint}', query_string=args,
            json={'ranges': [{'start': 28, 'end': 34}, {'start': 0, 'end': 4}], **extra})
    return client.get(f'/api/cases/{cid}/{endpoint}', query_string={
        **args, 'start': 28, 'end': 34, 'duration': 6, **extra})


def count_builds(monkeypatch):
    import app as server
    original = server.EditedRecords
    calls = []
    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(server, 'EditedRecords', counted)
    return calls


def test_windows_leads_and_continuous_view_share_one_private_feed(synthetic_app, synthetic_case, monkeypatch):
    calls = count_builds(monkeypatch)
    client = synthetic_app.test_client(); cid = synthetic_case[1]
    for endpoint, params in [('event-waveforms', {}), ('event-waveform', {}),
                             ('waveform', {'leads': 'I,V2'}),
                             ('event-waveforms', {'ranges': [{'start': 70, 'end': 74}]})]:
        response = wave(client, cid, endpoint, **params)
        assert response.status_code == 200, response.json
    assert len(calls) == 1
    cache = synthetic_app.extensions['waveform_beat_cache']
    assert cache.retention()['entries'] == 1
    assert cache.retention()['units'] == 89 * 4
    # A consumer editing its projected result cannot corrupt the owned feed.
    key = next(iter(cache._entries))
    result = cache.project(key, lambda: pytest.fail('unexpected build'), lambda x: visible_beats(x, 28, 6))
    result[0]['class_code'] = 'X'
    assert wave(client, cid).json['items'][0]['beats'][0]['class_code'] == 'N'
    # Other mutable analysis paths never receive the cached object.
    assert client.get(f'/api/cases/{cid}/report-statistics').status_code == 200
    assert len(calls) > 1
    before = len(calls)
    assert wave(client, cid).status_code == 200 and len(calls) == before


@pytest.mark.parametrize('operation,params', [
    ('relabel', {'selection': {'samples': [6000]}, 'class_code': 'V'}),
    ('relabel', {'selection': {'samples': [6000]}, 'class_code': 'T'}),
    ('relabel', {'selection': {'samples': [6000]}, 'class_code': 'X'}),
    ('delete', {'selection': {'samples': [6000]}}),
    ('move', {'selection': {'samples': [6000]}, 'target_sample': 6030}),
    ('insert', {'positions': [6100], 'class_code': 'N'}),
])
def test_edit_neighbors_markers_and_undo_equal_fresh_feed(synthetic_app, synthetic_case, operation, params):
    client = synthetic_app.test_client(); _, cid, paths = synthetic_case
    first = wave(client, cid); assert first.status_code == 200, first.json
    changed = client.put(f'/api/cases/{cid}/beat-editor', json={
        'operation': operation, 'revision': 0, 'confirmed': True, **params})
    assert changed.status_code == 200, changed.json
    store = synthetic_app.extensions['storage']; snapshot = BeatEditorStore(store).read(cid)
    feed = EditedRecords(load_records(str(paths['ebi'])), snapshot['document'], store.list_beat_overrides(cid), 90)
    for endpoint in ('event-waveforms', 'event-waveform', 'waveform'):
        response = wave(client, cid, endpoint)
        assert response.status_code == 200, response.json
        items = response.json['items'] if endpoint == 'event-waveforms' else [response.json]
        for item in items:
            expected = visible_beats(feed, item['start_s'], item['duration_s'])
            if endpoint == 'waveform':
                expected += [r for r in feed.markers if item['start_s'] <= r['time_s'] <= item['start_s'] + item['duration_s']]
                expected.sort(key=lambda r: r['sample_index'])
            assert item['beats'] == expected
            assert item['analysis_revision'] > first.json['analysis_revision']
    # Raw/source labels stay independent of the edited cache.
    raw = wave(client, cid, edited=False).json['items'][0]['beats']
    assert any(r['sample_index'] == 6000 and r['label'] == 'N' for r in raw)
    assert all('class_code' not in r for r in raw)
    undone = client.put(f'/api/cases/{cid}/beat-editor', json={
        'operation': 'undo', 'revision': changed.json['revision'], 'confirmed': True})
    assert undone.status_code == 200, undone.json
    restored = wave(client, cid)
    assert restored.status_code == 200, restored.json
    assert [i['beats'] for i in restored.json['items']] == [i['beats'] for i in first.json['items']]
    assert restored.json['analysis_revision'] > first.json['analysis_revision']
    assert synthetic_app.extensions['waveform_beat_cache'].retention()['entries'] == 1


@pytest.mark.parametrize('change', ['missing-data', 'missing-ebi', 'missing-lps', 'data-empty', 'ebi-tail', 'lps-xml'])
def test_warm_feed_cannot_hide_invalid_or_unavailable_source(synthetic_app, synthetic_case, change):
    from test_source_integrity import corrupt
    _, cid, paths = synthetic_case; client = synthetic_app.test_client()
    before = wave(client, cid); assert before.status_code == 200, before.json
    originals = {k: p.read_bytes() for k, p in paths.items()}
    if change.startswith('missing-'):
        paths[change.split('-')[1]].unlink()
    else:
        corrupt(paths, change)
    response = wave(client, cid)
    assert response.status_code == (503 if change.startswith('missing-') else 422), response.json
    assert 'items' not in response.json
    for key, content in originals.items():
        paths[key].write_bytes(content)
    after = wave(client, cid)
    assert after.status_code == 200 and after.json == before.json


@pytest.mark.parametrize('kind', ['data', 'ebi', 'lps', 'review'])
def test_source_or_review_identity_change_never_hits_old_feed(synthetic_app, synthetic_case, monkeypatch, kind):
    calls = count_builds(monkeypatch)
    _, cid, paths = synthetic_case; client = synthetic_app.test_client()
    before = wave(client, cid); assert before.status_code == 200, before.json
    if kind == 'review':
        synthetic_app.extensions['storage'].complete_review(cid, {'step': 'edit', 'confirmed': True, 'revision': 0}, 'synthetic')
    else:
        content = paths[kind].read_bytes()
        if kind == 'data':
            # Alter a sample in a requested waveform without changing size/mtime.
            at = 28 * 200 * 16 + 2
            content = content[:at] + b'\1' + content[at + 1:]
        elif kind == 'ebi':
            at = HEADER_SIZE + 29 * RECORD.size
            content = content[:at] + RECORD.pack(6000, 1, 3, 0, 0, 0, 1000) + content[at + RECORD.size:]
        else:
            content = content.replace(b'08:00:00', b'08:01:00')
        replace_preserving_mtime(paths[kind], content)
    old = {k: before.json[k] for k in ('analysis_basis', 'analysis_revision')}
    stale = wave(client, cid, **old)
    assert stale.status_code == 409 and 'items' not in stale.json
    after = wave(client, cid)
    assert after.status_code == 200, after.json
    assert len(calls) == 2
    if kind == 'ebi':
        assert next(r for r in after.json['items'][0]['beats'] if r['sample_index'] == 6000)['class_code'] == 'V'
    if kind == 'data':
        assert after.json['items'][0]['leads']['II'][0] == 1
    assert synthetic_app.extensions['waveform_beat_cache'].retention()['entries'] == 1


@pytest.mark.parametrize('stage', ['build', 'hit'])
def test_racing_revision_is_rejected_and_failed_build_not_retained(synthetic_app, synthetic_case, monkeypatch, stage):
    import app as server
    client = synthetic_app.test_client(); cid = synthetic_case[1]
    name = 'EditedRecords' if stage == 'build' else 'visible_beats'
    if stage == 'hit':
        assert wave(client, cid).status_code == 200
    original = getattr(server, name)
    def racing(*args, **kwargs):
        result = original(*args, **kwargs)
        synthetic_app.extensions['storage'].audit('synthetic', 'beat_override.editor', cid)
        return result
    monkeypatch.setattr(server, name, racing)
    response = wave(client, cid)
    assert response.status_code == 409 and 'items' not in response.json, response.json
    cache = synthetic_app.extensions['waveform_beat_cache']
    if stage == 'build':
        assert cache.retention()['entries'] == 0
    assert cache.retention()['pending'] == 0
    monkeypatch.setattr(server, name, original)
    assert wave(client, cid).status_code == 200


@pytest.mark.parametrize('timeout', [False, True])
def test_concurrent_windows_share_build_and_busy_wait_is_retryable(synthetic_app, synthetic_case, monkeypatch, timeout):
    import app as server
    from ecg_core import clinical_query_cache
    cache = synthetic_app.extensions['waveform_beat_cache']
    if timeout:
        cache.wait_seconds = .02
    original = server.EditedRecords; entered = threading.Event(); release = threading.Event(); joined = threading.Event(); calls = []
    class ObservedFuture(Future):
        def result(self, timeout=None):
            joined.set()
            return super().result(timeout)
    monkeypatch.setattr(clinical_query_cache, 'Future', ObservedFuture)
    def blocked(*args, **kwargs):
        calls.append(1); entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(server, 'EditedRecords', blocked)
    cid = synthetic_case[1]
    def read():
        with synthetic_app.test_client() as client:
            return wave(client, cid)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(read)
        assert entered.wait(5)
        second = pool.submit(read)
        try:
            assert joined.wait(5)
            if timeout:
                response = second.result(timeout=5)
                assert response.status_code == 503 and response.json['code'] == 'clinical_query_busy', response.json
                assert '波形心搏索引' in response.json['error'] and 'items' not in response.json
        finally:
            release.set()
        a = first.result(timeout=5)
        b = read() if timeout else second.result(timeout=5)
    assert a.status_code == b.status_code == 200 and a.json == b.json
    assert len(calls) == 1 and cache.retention()['pending'] == 0


def test_retention_counts_every_feed_collection_and_applies_shared_limits():
    source = tuple((i * 200, 0, 1, 0, 0, 0, 1000) for i in range(3))
    feed = EditedRecords(source, blank(), [], 10)
    feed.excluded_rhythm_intervals = [(1, 2)]
    feed.markers = [{'sample_index': 25}]
    feed.document['changes']['s:0'] = {'class_code': 'N'}
    assert WaveformBeatCache._weight(feed) == 15
    cache = WaveformBeatCache(max_entries=2, max_units=30)
    for key in [('a', 'b', 0), ('b', 'b', 0), ('c', 'b', 0)]:
        cache.project(key, lambda: deepcopy(feed), lambda f: visible_beats(f, 0, 10))
    assert list(cache._entries) == [('b', 'b', 0), ('c', 'b', 0)]
    assert cache.retention()['units'] == 30
    cache.project(('c', 'b', 1), lambda: deepcopy(feed), lambda f: len(f.beats))
    assert list(cache._entries) == [('b', 'b', 0), ('c', 'b', 1)]
    tiny = WaveformBeatCache(max_units=14); calls = []
    def build():
        calls.append(1); return deepcopy(feed)
    for _ in range(2):
        assert tiny.project(('a', 'b', 0), build, lambda f: len(f.beats)) == 3
    assert len(calls) == 2 and tiny.retention()['entries'] == 0


def test_application_instances_do_not_share_waveform_feeds(synthetic_case, tmp_path):
    from app import create_app
    a, b = [create_app(data_root=synthetic_case[0], db_path=tmp_path / f'isolated-{i}.db', testing=True) for i in range(2)]
    assert wave(a.test_client(), synthetic_case[1]).status_code == 200
    assert b.extensions['waveform_beat_cache'].retention()['entries'] == 0
