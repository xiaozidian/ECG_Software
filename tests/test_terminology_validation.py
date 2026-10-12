"""Only original phrases and disposable SQLite data; no clinical source files."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import sqlite3

import pytest

from ecg_core.terminology import (
    MAX_CATALOG_BYTES, MAX_DEPTH, MAX_NODES, TerminologyConflict, TerminologyStore,
    get_builtin_catalog, normalize_terminology_usages, parse_catalog_json, validate_catalog,
)


class SyntheticStorage:
    def __init__(self, path):
        self.path = path
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS synthetic_reports(id TEXT PRIMARY KEY, conclusion TEXT, usages TEXT)')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db


def catalog(version='draft-v1', namespace='synthetic.original'):
    result = get_builtin_catalog()
    result.pop('sha256')
    result['namespace'] = namespace
    result['version'] = version
    return result


def usage(value=None):
    value = validate_catalog(value or catalog())
    term = next(n for n in value['nodes'] if n['kind'] == 'term')
    return {"usage_id": "synthetic-usage-1", "namespace": value['namespace'], "version": value['version'],
            "catalog_hash": value['sha256'], "stable_id": term['stable_id'], "label": term['label'],
            "inserted_text": term['text'], "approval": term['approval'], "source": term['source'],
            "license": term['license'], "scope": term['scope'], "review": term['review'],
            "inserted_at": '2026-10-12T12:00:00Z'}


def test_builtin_is_small_original_mit_draft_and_roundtrips():
    value = get_builtin_catalog()
    assert value['completeness'] == 'example'
    assert value['approval'] == 'draft'
    assert value['license']['name'] == 'MIT'
    assert value['source']['verification'] == 'declared'
    assert len(value['nodes']) == 9
    assert sum(n['kind'] == 'term' for n in value['nodes']) == 6
    assert all(n['approval'] == 'draft' and not n['review']['reviewer'] for n in value['nodes'])
    assert validate_catalog(value) == value
    reordered = dict(reversed(list(value.items())))
    assert validate_catalog(reordered)['sha256'] == value['sha256']


@pytest.mark.parametrize('field,value', [('approval', 'unknown'), ('approval', []), ('completeness', 'ontology'),
                                        ('completeness', []), ('schema_version', True), ('namespace', '<script>'),
                                        ('version', '../escape'), ('title', '<img src=x onerror=alert(1)>'),
                                        ('title', '&#x3c;script&#x3e;'), ('title', 'bidi\u202eunsafe'),
                                        ('sha256', '0' * 64)])
def test_reject_invalid_top_level(field, value):
    data = catalog(); data[field] = value
    with pytest.raises(ValueError): validate_catalog(data)


@pytest.mark.parametrize('field,value', [('kind', 'diagnosis'), ('kind', []), ('approval', 'verified'),
                                        ('text', '<script>alert(1)</script>'), ('text', 'hello\x00'),
                                        ('aliases', ['<iframe>']), ('aliases', ['same', 'same']),
                                        ('deprecated', 1), ('parent_id', 'missing'), ('replacement_id', 'missing')])
def test_reject_invalid_terms(field, value):
    data = catalog(); data['nodes'][1][field] = value
    with pytest.raises(ValueError): validate_catalog(data)


@pytest.mark.parametrize('url', ['javascript:alert(1)', 'data:text/html,x', 'file:///etc/passwd',
                                'http://example.org', 'https://user:pass@example.org',
                                'https://127.0.0.1/path', 'https://localhost/path', 'https://host.local/path',
                                'https://example.org:8080/path', 'https://example.org/%0aattack',
                                'https://example.org/%3Cscript%3E', 'https://example.org\\@evil.org',
                                'https://127.1/path', 'https://0x7f.0x0.0x0.0x1/path'])
def test_reject_unsafe_source_urls(url):
    data = catalog(); data['nodes'][1]['source']['url'] = url
    with pytest.raises(ValueError): validate_catalog(data)


def test_unknown_nested_fields_unverified_metadata_and_invalid_scope_rejected():
    for mutate in (
        lambda d: d['source'].update(verification='independently_verified'),
        lambda d: d['license'].update(html='unsafe'),
        lambda d: d['scope'].update(population=['neonate']),
        lambda d: d['nodes'][1]['review'].update(reviewed_at='2026-01-01'),
        lambda d: d['nodes'][1].update(unreviewed_rules={'rr': 'auto-diagnosis'}),
    ):
        data = catalog(); mutate(data)
        with pytest.raises(ValueError): validate_catalog(data)


def test_duplicate_cycle_parent_term_group_text_and_depth_rejected():
    data = catalog(); data['nodes'][1]['stable_id'] = data['nodes'][0]['stable_id']
    with pytest.raises(ValueError, match='重复'): validate_catalog(data)
    data = catalog(); data['nodes'][0]['parent_id'] = data['nodes'][3]['stable_id']; data['nodes'][3]['parent_id'] = data['nodes'][0]['stable_id']
    with pytest.raises(ValueError, match='循环'): validate_catalog(data)
    data = catalog(); data['nodes'][2]['parent_id'] = data['nodes'][1]['stable_id']
    with pytest.raises(ValueError, match='分组'): validate_catalog(data)
    data = catalog(); data['nodes'][0]['text'] = 'groups are not insertable'
    with pytest.raises(ValueError, match='分组'): validate_catalog(data)
    data = catalog(); prototype = data['nodes'][0]; groups = []
    for index in range(MAX_DEPTH):
        item = deepcopy(prototype); item['stable_id'] = f'deep-{index}'; item['parent_id'] = f'deep-{index-1}' if index else None; groups.append(item)
    term = deepcopy(data['nodes'][1]); term['parent_id'] = groups[-1]['stable_id']; data['nodes'] = groups + [term]
    with pytest.raises(ValueError, match='深度'): validate_catalog(data)
    term['parent_id'] = groups[-2]['stable_id']; assert validate_catalog(data)


def test_oversize_nodes_and_bytes_and_duplicate_json_keys_rejected():
    data = catalog(); term = deepcopy(data['nodes'][1]); term['parent_id'] = None
    # Use short licenses so the node-count boundary is independently exercised.
    data['license']['text'] = 'Synthetic license'; term['license']['text'] = 'Synthetic license'
    data['nodes'] = []
    for i in range(MAX_NODES + 1):
        item = deepcopy(term); item['stable_id'] = f'term-{i}'; data['nodes'].append(item)
    with pytest.raises(ValueError, match='1200'): validate_catalog(data)
    data = catalog(); data['description'] = 'x' * (MAX_CATALOG_BYTES + 1)
    with pytest.raises(ValueError, match='大小'): validate_catalog(data)
    with pytest.raises(ValueError, match='重复'): parse_catalog_json('{"schema_version":1,"schema_version":1}')
    with pytest.raises(ValueError): parse_catalog_json('{"x":NaN}')


def test_replacement_must_be_existing_active_other_term():
    data = catalog(); data['nodes'][1]['deprecated'] = True; data['nodes'][1]['replacement_id'] = data['nodes'][2]['stable_id']
    assert validate_catalog(data)['nodes'][1]['replacement_id'] == data['nodes'][2]['stable_id']
    for target in (data['nodes'][1]['stable_id'], data['nodes'][0]['stable_id'], 'unknown'):
        invalid = deepcopy(data); invalid['nodes'][1]['replacement_id'] = target
        with pytest.raises(ValueError): validate_catalog(invalid)
    data['nodes'][2]['deprecated'] = True
    with pytest.raises(ValueError): validate_catalog(data)


def test_import_requires_preview_hash_and_revision_and_preserves_local_versions(tmp_path):
    storage = SyntheticStorage(tmp_path / 'synthetic.db'); store = TerminologyStore(storage)
    assert store.list_catalogs()['catalog_revision'] == 0
    assert len(store.list_catalogs()['items']) == 1
    preview = store.import_catalog(catalog(), 0)
    assert preview['preview_only'] is True and preview['catalog_revision'] == 0
    assert store.get_catalog('synthetic.original', 'draft-v1') is None
    with pytest.raises(ValueError, match='preview_hash'): store.import_catalog(catalog(), 0, confirm=True)
    with pytest.raises(ValueError): store.import_catalog(catalog(), True)
    committed = store.import_catalog(preview['catalog'], 0, confirm=True, preview_hash=preview['preview_hash'])
    assert not committed['preview_only'] and committed['catalog_revision'] == 1
    with pytest.raises(TerminologyConflict) as stale: store.import_catalog(catalog('draft-v2'), 0)
    assert stale.value.current_revision == 1
    changed = catalog(); changed['nodes'][1]['text'] = 'Synthetic changed text'
    with pytest.raises(TerminologyConflict, match='不能覆盖'): store.import_catalog(changed, 1)
    preview2 = store.import_catalog(catalog('draft-v2'), 1)
    store.import_catalog(preview2['catalog'], 1, confirm=True, preview_hash=preview2['preview_hash'])
    reopened = TerminologyStore(SyntheticStorage(storage.path))
    assert reopened.list_catalogs()['catalog_revision'] == 2
    assert reopened.get_catalog('synthetic.original', 'draft-v1') == preview['catalog']
    assert reopened.get_catalog('synthetic.original', 'draft-v2') == preview2['catalog']
    assert reopened.get_catalog('synthetic.original', 'draft-v1', '0' * 64) is None
    assert reopened.get_catalog('synthetic.original', 'missing') is None
    same = reopened.import_catalog(preview2['catalog'], 2, confirm=True, preview_hash=preview2['preview_hash'])
    assert same['catalog_revision'] == 2
    with storage.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM synthetic_reports').fetchone()[0] == 0


def test_concurrent_catalog_publication_has_one_revision_winner(tmp_path):
    store = TerminologyStore(SyntheticStorage(tmp_path / 'concurrent.db'))
    values = [store.import_catalog(catalog(namespace='synthetic.one'), 0),
              store.import_catalog(catalog(namespace='synthetic.two'), 0)]
    def commit(value):
        try:
            return store.import_catalog(value['catalog'], 0, confirm=True, preview_hash=value['preview_hash'])
        except TerminologyConflict as error:
            return error
    with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(commit, values))
    assert sum(isinstance(r, TerminologyConflict) for r in results) == 1
    assert store.list_catalogs()['catalog_revision'] == 1
    assert len(store.list_catalogs()['items']) == 2


def test_saved_usage_snapshots_do_not_depend_on_updated_or_missing_catalog(tmp_path):
    storage = SyntheticStorage(tmp_path / 'snapshots.db'); store = TerminologyStore(storage)
    old = catalog(); snapshot = usage(old)
    normalized = normalize_terminology_usages([snapshot]); text = 'Doctor free text: ' + snapshot['inserted_text']
    with storage.connect() as db: db.execute('INSERT INTO synthetic_reports VALUES(?,?,?)', ('synthetic-case-A', text, json.dumps(normalized)))
    new = catalog('draft-v2'); new['nodes'][1]['text'] = 'Different synthetic version text'
    preview = store.import_catalog(new, 0); store.import_catalog(preview['catalog'], 0, confirm=True, preview_hash=preview['preview_hash'])
    with storage.connect() as db: row = db.execute('SELECT * FROM synthetic_reports').fetchone()
    assert row['conclusion'] == text
    recovered = normalize_terminology_usages(json.loads(row['usages']))
    assert recovered == normalized
    assert recovered[0]['inserted_text'] != new['nodes'][1]['text']
    assert store.get_catalog(snapshot['namespace'], snapshot['version']) is None
    assert normalize_terminology_usages(None) == []
    with pytest.raises(ValueError): normalize_terminology_usages([snapshot, snapshot])
    with pytest.raises(ValueError): normalize_terminology_usages([snapshot] * 501)
    bad = deepcopy(snapshot); bad['inserted_text'] = '<img src=x>'
    with pytest.raises(ValueError): normalize_terminology_usages([bad])
    bad = deepcopy(snapshot); bad['catalog_hash'] = 'mismatch'
    with pytest.raises(ValueError): normalize_terminology_usages([bad])


def test_storage_corruption_is_rejected_instead_of_reusing_claimed_hash(tmp_path):
    storage = SyntheticStorage(tmp_path / 'corruption.db'); store = TerminologyStore(storage)
    preview = store.import_catalog(catalog(), 0)
    store.import_catalog(preview['catalog'], 0, confirm=True, preview_hash=preview['preview_hash'])
    corrupt = deepcopy(preview['catalog']); corrupt['nodes'][1]['text'] = 'Synthetic corrupt content'
    with storage.connect() as db: db.execute('UPDATE terminology_catalogs SET payload=?', (json.dumps(corrupt),))
    with pytest.raises(ValueError, match='sha256'): store.get_catalog('synthetic.original', 'draft-v1')
    with pytest.raises(ValueError, match='sha256'): store.list_catalogs()
