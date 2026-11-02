"""Synthetic-only episode/report transactions and Python/browser basis parity."""
from copy import deepcopy
from pathlib import Path
import subprocess
import json
import uuid

import pytest

from ecg_core.beat_editor import BeatEditorStore
from ecg_core.clinical_analysis import build_index, validate_report
from ecg_core.overview import RhythmReviewStore, episode_annotations
from ecg_core.review_workflow import ReportConflict
from ecg_core.storage import Storage
from test_analysis_provenance import synthetic_app, synthetic_case
from test_rr_quality import browser, recording


def test_mathematical_demo_adapter_matches_episode_report_lifecycle():
    subprocess.run(['node', str(Path(__file__).with_name('browser_af_report_linkage.cjs'))],
                   cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True, text=True)


def test_only_current_report_output_rhythm_selections_block_approval():
    subprocess.run(['node', str(Path(__file__).with_name('browser_af_report_approval.cjs'))],
                   cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True, text=True)


def episode(key, start=10, end=20, kind='AF', status='confirmed'):
    return dict(id=key, start_s=start, end_s=end, kind=kind, status=status, source='manual', note='')


def index_for(feed, items):
    annotations = episode_annotations(dict(episodes=items))
    index = build_index(feed, annotations=annotations, review={'steps': {'edit': {'status': 'done'}}})
    assert browser('ECGClinicalAnalysis.buildIndex(x.f,[],x.annotations,x.review)',
                   dict(f=vars(feed), annotations=annotations, review={'steps': {'edit': {'status': 'done'}}})) == index
    return index


@pytest.mark.parametrize('mutation', ['add', 'bounds', 'kind', 'status', 'note', 'delete'])
def test_other_episode_edits_preserve_selected_strip_basis(mutation):
    f = recording([1000]*60)
    items = [episode('keep'), episode('change', 30, 40, 'AFL')]
    initial = index_for(f, items)
    selected = next(e for e in initial['events'] if e['event_id'] == 'annotation:af:keep')
    changed = deepcopy(items)
    if mutation == 'add':
        changed.append(episode('new', 45, 50))
    elif mutation == 'delete':
        changed.pop()
    else:
        changed[1].update({'bounds': {'start_s': 32}, 'kind': {'kind': 'AF'},
                           'status': {'status': 'pending'}, 'note': {'note': 'changed context'}}[mutation])
    current = index_for(f, changed)
    unchanged = next(e for e in current['events'] if e['event_id'] == selected['event_id'])
    assert unchanged['basis_version'] == selected['basis_version']
    assert validate_report(current, {'selected_events': [selected]}, {}, approving=True)
    assert current['data_version'] != initial['data_version'] or mutation == 'note'


@pytest.mark.parametrize('mutation', ['bounds', 'kind', 'status', 'note', 'beats'])
def test_own_episode_or_beat_changes_require_new_report_evidence(mutation):
    f = recording([1000]*60)
    items = [episode('one')]
    initial = index_for(f, items)
    selected = next(e for e in initial['events'] if e['category'] == 'AF')
    if mutation == 'beats':
        f.beats[0]['class_code'] = 'V'
    else:
        items[0].update({'bounds': {'end_s': 22}, 'kind': {'kind': 'AFL'},
                         'status': {'status': 'pending'}, 'note': {'note': 'new review'}}[mutation])
    current = index_for(f, items)
    with pytest.raises(ValueError, match='失效'):
        validate_report(current, {'selected_events': [selected]}, {}, approving=True)


def test_changed_rhythm_finding_invalidates_its_selected_caption_basis():
    f = recording([1000]*30)
    annotations = episode_annotations(dict(episodes=[episode('finding')]))
    before = build_index(f, annotations=annotations)
    annotations[0]['details']['finding'] = 'Changed physician finding'
    after = build_index(f, annotations=annotations)
    a = next(e for e in before['events'] if e['category'] == 'AF')
    b = next(e for e in after['events'] if e['category'] == 'AF')
    assert a['basis_version'] != b['basis_version']
    assert browser('ECGClinicalAnalysis.buildIndex(x.f,[],x.annotations)',
                   dict(f=vars(f), annotations=annotations)) == after


@pytest.fixture
def store(tmp_path):
    storage = Storage(tmp_path/'synthetic.db')
    BeatEditorStore(storage)
    return storage, RhythmReviewStore(storage)


def commit(store, document=None, operation='save', aliases=None, request_id=None):
    storage, rhythms = store
    value = rhythms.read('synthetic')
    return rhythms.commit('synthetic', dict(confirmed=True, revision=value['revision'],
        beat_revision=0, document=document, operation=operation, request_id=request_id), 100,
        dict(episodes=[], bookmarks={}), 'synthetic-doctor', 0, event_aliases=aliases)


def approve(storage, picks):
    for step in ('edit', 'stt'):
        storage.complete_review('synthetic', dict(step=step, confirmed=True,
            revision=storage.get_review('synthetic')['revision']), 'synthetic-doctor')
    composition = dict(selected_events=[dict(event_id=key, basis_version='synthetic-basis', caption='retain caption') for key in picks],
        diagnosis_blocks=[dict(key='AF:AF', text='Doctor authored text', manual=True,
                               needs_review=False, acknowledged=True)], category_reviews={'AF': 'old'})
    value = storage.save_report('synthetic', 'Doctor authored conclusion', 'draft', 'synthetic-doctor', composition)
    return storage.save_report('synthetic', value['conclusion'], 'reviewed', 'synthetic-doctor',
                               value['composition'], expected_version=value['version'])


@pytest.mark.parametrize('action', ['delete', 'exclude'])
def test_retirement_atomically_removes_only_matching_report_picks_and_undo_stays_unselected(store, action):
    storage, _ = store
    a, b = episode('one'), episode('two', 30, 40, 'AFL')
    commit(store, dict(episodes=[a, b]))
    report = approve(storage, ['annotation:af:one', 'annotation:af:two'])
    before = storage.get_review('synthetic')
    after = [b] if action == 'delete' else [dict(a, status='excluded'), b]
    response = commit(store, dict(episodes=after))
    assert response['removed_report_events'] == ['annotation:af:one']
    report_after = storage.get_report('synthetic', '')
    assert report_after['version'] == report['version']+1
    assert report_after['status'] == 'draft'
    assert [e['event_id'] for e in report_after['composition']['selected_events']] == ['annotation:af:two']
    assert report_after['conclusion'] == 'Doctor authored conclusion'
    block = report_after['composition']['diagnosis_blocks'][0]
    assert block['text'] == 'Doctor authored text' and block['needs_review'] and not block['acknowledged']
    progress = storage.get_review('synthetic')
    assert progress['revision'] == before['revision']+1
    assert progress['pending_steps'] == []
    with pytest.raises(ReportConflict):
        storage.save_report('synthetic', report['conclusion'], 'reviewed', 'synthetic-doctor',
                            report['composition'], expected_version=report['version'])
    commit(store, operation='undo')
    restored = storage.get_report('synthetic', '')
    assert restored['status'] == 'draft'
    assert [e['event_id'] for e in restored['composition']['selected_events']] == ['annotation:af:two']
    commit(store, operation='redo')
    assert [e['event_id'] for e in storage.get_report('synthetic', '')['composition']['selected_events']] == ['annotation:af:two']


def test_source_aliases_are_pruned_without_guessing_from_ranges(store):
    storage, _ = store
    a = episode('source-12')
    b = episode('beat-6000', 30, 40, 'AFL')
    commit(store, dict(episodes=[a, b]))
    approve(storage, ['annotation:12', 'AF:AFL:custom-first:custom-last'])
    result = commit(store, dict(episodes=[]), aliases={'beat-6000': ['AF:AFL:custom-first:custom-last']})
    assert set(result['removed_report_events']) == {'annotation:12', 'AF:AFL:custom-first:custom-last'}
    assert storage.get_report('synthetic', '')['composition']['selected_events'] == []


def test_failed_retirement_rolls_back_rhythm_review_and_report(store, monkeypatch):
    storage, rhythms = store
    commit(store, dict(episodes=[episode('one')]))
    report = approve(storage, ['annotation:af:one'])
    before_report = storage.get_report('synthetic', '')
    before = deepcopy(rhythms.read('synthetic'))
    original = storage._audit
    def fail(db, actor, action, *args):
        if action == 'rhythm_report.unselect':
            raise RuntimeError('synthetic transaction interruption')
        return original(db, actor, action, *args)
    monkeypatch.setattr(storage, '_audit', fail)
    with pytest.raises(RuntimeError, match='interruption'):
        commit(store, dict(episodes=[]))
    assert rhythms.read('synthetic') == before
    assert storage.get_report('synthetic', '') == before_report


def test_last_operation_receipt_identifies_own_save_undo_redo_without_repeating_mutation(store):
    storage, rhythms = store
    first = str(uuid.uuid4())
    saved = commit(store, dict(episodes=[episode('own')]), request_id=first)
    assert saved['last_operation'] == dict(request_id=first, operation='save', revision=1)
    for operation in ['undo', 'redo']:
        token = str(uuid.uuid4())
        value = commit(store, operation=operation, request_id=token)
        # Simulate a caller losing the PUT response: the next GET must prove the
        # same mutation rather than guessing from one revision advancement.
        read = rhythms.public(rhythms.read('synthetic'))
        assert read['last_operation'] == dict(request_id=token, operation=operation, revision=value['revision'])
        assert read['document'] == value['document']
        assert rhythms.read('synthetic')['revision'] == value['revision']
    other = commit(store, dict(episodes=[episode('other')]), request_id=str(uuid.uuid4()))
    assert other['last_operation']['request_id'] != first
    assert rhythms.public(rhythms.read('synthetic'))['last_operation'] == other['last_operation']


def test_last_operation_migration_preserves_legacy_history_and_untracked_writes_do_not_claim_receipts(tmp_path):
    storage = Storage(tmp_path/'legacy.db')
    BeatEditorStore(storage)
    document = dict(episodes=[episode('legacy')], bookmarks={})
    with storage.connect() as db:
        db.execute('CREATE TABLE rhythm_reviews(case_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, document TEXT NOT NULL, undo TEXT NOT NULL, redo TEXT NOT NULL, updated_at TEXT NOT NULL)')
        db.execute('INSERT INTO rhythm_reviews VALUES(?,?,?,?,?,?)',
                   ('synthetic', 3, json.dumps(document), '[]', '[]', 'legacy-stamp'))
    rhythms = RhythmReviewStore(storage)
    before = rhythms.read('synthetic')
    assert before['document'] == document and before['revision'] == 3 and before['last_operation'] == {}
    saved = commit((storage, rhythms), dict(episodes=[episode('legacy')]))
    assert saved['last_operation'] == {} and saved['revision'] == 4
    RhythmReviewStore(storage)  # Reopening must be an idempotent migration.
    assert rhythms.read('synthetic')['revision'] == 4


@pytest.mark.parametrize('request_id', ['', 'not-an-id', 2, True, '2F9F65CE-3053-4BBA-9C07-C565EA75C371'])
def test_invalid_receipt_identifier_never_mutates_history(store, request_id):
    _, rhythms = store
    before = rhythms.read('synthetic')
    with pytest.raises(ValueError, match='请求编号'):
        commit(store, dict(episodes=[episode('one')]), request_id=request_id)
    assert rhythms.read('synthetic') == before


def test_rhythm_edit_refreshes_nn_and_report_but_preserves_qrs_st_confirmations(synthetic_app, synthetic_case):
    client = synthetic_app.test_client()
    storage = synthetic_app.extensions['storage']
    cid = synthetic_case[1]
    base = '/api/cases/'+cid
    before = client.get(base+'/hrv?analysis=edited').json['calculated']['nn_count']
    for step in ('edit', 'stt'):
        storage.complete_review(cid, dict(step=step, confirmed=True,
            revision=storage.get_review(cid)['revision']), 'synthetic-doctor')
    rhythm = client.get(base+'/rhythm-review').json
    response = client.put(base+'/rhythm-review', json=dict(confirmed=True,
        revision=rhythm['revision'], beat_revision=rhythm['beat_revision'],
        analysis_basis=rhythm['analysis_basis'], analysis_revision=rhythm['analysis_revision'],
        document=dict(episodes=[episode('pending', status='pending')], bookmarks={})))
    assert response.status_code == 200, response.json
    after = client.get(base+'/hrv?analysis=edited').json['calculated']['nn_count']
    assert after < before
    assert storage.get_review(cid)['pending_steps'] == []
    assert client.get(base+'/report-events?category=AF').json['items'][0]['rhythm_status'] == 'pending'
