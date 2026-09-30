"""Current-edit reads must not decode whole undo histories or mutate them."""
import json
import sqlite3
from hashlib import sha256

import pytest

from ecg_core import beat_editor
from ecg_core.beat_editor import BeatEditorStore, blank
from ecg_core.storage import Storage
from test_analysis_provenance import synthetic_app, synthetic_case


def legacy_snapshot(store, case_id, db=None):
    value = store.read(case_id, db)
    return dict(revision=value['revision'], document=value['document'],
                can_undo=bool(value['undo']), can_redo=bool(value['redo']))


def seed(store, case_id, undo=(), redo=()):
    document = blank()
    document['changes'] = {'s:6000': dict(sample_index=6000, class_code='V', deleted=False)}
    with store.storage.connect() as db:
        db.execute('INSERT OR REPLACE INTO beat_edit_documents VALUES(?,?,?,?,?)',
                   (case_id, 5, json.dumps(document), json.dumps(undo, indent=2), json.dumps(redo, indent=2)))
    return document


@pytest.mark.parametrize('undo,redo', [([], []), ([blank()], []), ([], [blank()]),
                                     ([blank()] * 6, [blank()] * 2)])
def test_snapshot_matches_full_read_and_is_detached(tmp_path, monkeypatch, undo, redo):
    store = BeatEditorStore(Storage(tmp_path / 'synthetic.db'))
    seed(store, 'synthetic', undo, redo)
    expected = legacy_snapshot(store, 'synthetic')
    original_loads = json.loads
    parsed = []

    def tracked(value, *args, **kwargs):
        result = original_loads(value, *args, **kwargs)
        parsed.append(type(result))
        return result

    monkeypatch.setattr(beat_editor.json, 'loads', tracked)
    actual = store.snapshot('synthetic')
    assert actual == expected
    assert parsed == [dict]  # Exactly one current document; no history arrays.
    actual['document']['changes'].clear()
    actual['document']['settings']['lead'] = 'V6'
    assert store.snapshot('synthetic') == expected


def test_missing_case_snapshot_does_not_create_document(tmp_path):
    store = BeatEditorStore(Storage(tmp_path / 'synthetic.db'))
    assert store.snapshot('missing') == legacy_snapshot(store, 'missing')
    with store.storage.connect() as db:
        assert db.execute('SELECT count(*) FROM beat_edit_documents').fetchone()[0] == 0


def test_snapshot_commit_undo_redo_and_stale_revision(tmp_path):
    store = BeatEditorStore(Storage(tmp_path / 'synthetic.db'))
    original = seed(store, 'synthetic', [blank()])
    store.commit('synthetic', 5, 'test', None, 'undo')
    assert store.snapshot('synthetic') == legacy_snapshot(store, 'synthetic')
    assert store.snapshot('synthetic')['document'] == blank()
    assert store.snapshot('synthetic')['can_redo']
    with pytest.raises(ValueError, match='版本'):
        store.commit('synthetic', 5, 'test', None, 'redo')
    store.commit('synthetic', 6, 'test', None, 'redo')
    assert store.snapshot('synthetic') == legacy_snapshot(store, 'synthetic')
    assert store.snapshot('synthetic')['document'] == original
    assert not store.snapshot('synthetic')['can_redo']


def test_snapshot_uses_callers_transaction_consistently(tmp_path):
    store = BeatEditorStore(Storage(tmp_path / 'synthetic.db'))
    seed(store, 'synthetic', [blank()])
    with store.storage.connect() as db:
        db.execute('BEGIN')
        before = store.snapshot('synthetic', db)
        store.commit('synthetic', 5, 'test', None, 'undo')
        assert store.snapshot('synthetic', db) == before
        db.commit()
        after = store.snapshot('synthetic', db)
        assert after['revision'] == 6 and after['document'] == blank()
        assert not after['can_undo'] and after['can_redo']


@pytest.mark.parametrize('message', ['no such function: json_array_length', 'database is locked', 'malformed JSON'])
def test_only_missing_json_extension_uses_legacy_fallback(tmp_path, message):
    store = BeatEditorStore(Storage(tmp_path / 'synthetic.db'))
    seed(store, 'synthetic', [blank()])
    with store.storage.connect() as db:
        class LegacyConnection:
            def execute(self, sql, params):
                if 'json_array_length' in sql:
                    raise sqlite3.OperationalError(message)
                return db.execute(sql, params)
        if message.startswith('no such function:'):
            assert store.snapshot('synthetic', LegacyConnection()) == legacy_snapshot(store, 'synthetic')
        else:
            with pytest.raises(sqlite3.OperationalError, match=message):
                store.snapshot('synthetic', LegacyConnection())


@pytest.mark.parametrize('route', ['/beat-editor', '/beat-editor/beats', '/overview',
    '/rr-visuals?analysis=edited', '/hrv?analysis=edited', '/scatter?analysis=edited', '/rhythm-review'])
def test_read_api_parity_without_decoding_history(synthetic_app, synthetic_case, monkeypatch, route):
    case_id = synthetic_case[1]
    store = BeatEditorStore(synthetic_app.extensions['storage'])
    seed(store, case_id, [blank()] * 6)
    client = synthetic_app.test_client()
    base = '/api/cases/' + case_id
    snapshot = BeatEditorStore.snapshot
    monkeypatch.setattr(BeatEditorStore, 'snapshot', legacy_snapshot)
    expected = client.get(base + route)
    assert expected.status_code == 200, expected.json
    monkeypatch.setattr(BeatEditorStore, 'snapshot', snapshot)

    def forbid(*args, **kwargs):
        raise AssertionError('Read API loaded the undo documents')

    monkeypatch.setattr(BeatEditorStore, 'read', forbid)
    actual = client.get(base + route)
    assert actual.status_code == 200, actual.json
    assert actual.json == expected.json


@pytest.mark.parametrize('operation', ['relabel', 'detect'])
def test_preview_reads_one_snapshot_and_never_writes(synthetic_app, synthetic_case, monkeypatch, operation):
    case_id = synthetic_case[1]
    store = BeatEditorStore(synthetic_app.extensions['storage'])
    seed(store, case_id, [blank()] * 6)
    client = synthetic_app.test_client()
    payload = dict(operation=operation, revision=5, class_code='S', selection={'samples': [6000]},
                   start_s=1, duration_s=7)
    endpoint = '/api/cases/' + case_id + '/beat-editor/preview'
    before = store.read(case_id)
    sources = {key: sha256(path.read_bytes()).hexdigest() for key, path in synthetic_case[2].items()}
    snapshot = BeatEditorStore.snapshot
    monkeypatch.setattr(BeatEditorStore, 'snapshot', legacy_snapshot)
    expected = client.post(endpoint, json=payload)
    assert expected.status_code == 200, expected.json
    calls = []

    def tracked(self, cid, db=None):
        # Count the outer read, not its same-connection implementation call.
        if db is None:
            calls.append(cid)
        return snapshot(self, cid, db)

    monkeypatch.setattr(BeatEditorStore, 'snapshot', tracked)
    actual = client.post(endpoint, json=payload)
    assert actual.status_code == 200, actual.json
    assert actual.json == expected.json
    assert calls == [case_id]
    assert store.read(case_id) == before
    assert {key: sha256(path.read_bytes()).hexdigest() for key, path in synthetic_case[2].items()} == sources
