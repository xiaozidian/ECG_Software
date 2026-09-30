"""Disposable synthetic workspaces only; never restore over patient data."""
from contextlib import closing
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
import zipfile

import pytest

from app import create_app
from ecg_core.beat_editor import BeatEditorStore
from ecg_core.overview import RhythmReviewStore
from ecg_core.storage import Storage
from ecg_core.review_workflow import ReportConflict
from ecg_core import workspace_backup as backup
from test_analysis_provenance import synthetic_case, synthetic_app, approve


@pytest.fixture
def workspace(tmp_path):
    store = Storage(tmp_path / 'original.db')
    editor = BeatEditorStore(store)
    rhythms = RhythmReviewStore(store)
    store.create_annotation('synthetic', dict(sample_index=200, lead='II', label='合成注释', note='保留原文'), 'test')
    store.save_patient_override('synthetic', {'name': '合成验证'}, 'test')
    editor.commit('synthetic', 0, 'test', lambda value: {**value, 'synthetic_note': 'undo preserved'}, 'test')
    rhythms.commit('synthetic', dict(revision=0, beat_revision=1, confirmed=True,
        document=dict(episodes=[dict(id='a', start_s=5, end_s=10, kind='AF', status='confirmed')], bookmarks={'fastest': 20})),
        90, {}, 'test', 1)
    store.save_event_review('synthetic', {'items': [{'sample_index': 200, 'type': 'V'}], 'status': 'retained'}, 'test', {200})
    approve(store, 'synthetic', {'category_reviews': {'V': 'synthetic-basis'},
        'diagnosis_blocks': [{'key': 'V:single', 'text': '人工结论', 'manual': True, 'acknowledged': True, 'needs_review': False}],
        'included_pages': ['summary', 'event_strips']})
    return store


def dump_tables(path):
    with closing(sqlite3.connect(path)) as db:
        tables = [x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {name: db.execute(f'SELECT * FROM "{name}"').fetchall() for name in tables}


def repack(source, target, change_manifest=None, change_database=None, extra=None):
    with zipfile.ZipFile(source) as old:
        manifest = json.loads(old.read('manifest.json'))
        database = old.read('work.sqlite3')
    if change_manifest:
        change_manifest(manifest)
    if change_database:
        database = change_database(database)
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_STORED) as out:
        out.writestr('manifest.json', json.dumps(manifest))
        out.writestr('work.sqlite3', database)
        if extra:
            out.writestr(extra, 'no extraction')


def test_online_backup_contains_committed_wal_only(workspace, tmp_path):
    before = dump_tables(workspace.path)
    with closing(workspace.connect()) as writer:
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute("INSERT INTO audit_log(case_id,actor,action,detail,created_at) VALUES('synthetic','test','committed','','now')")
        writer.commit()
        writer.execute("INSERT INTO audit_log(case_id,actor,action,detail,created_at) VALUES('synthetic','test','uncommitted','','now')")
        created = backup.create_backup(workspace.path, tmp_path / 'backups')
        assert Path(str(workspace.path) + '-wal').exists()
        assert created['verified'] and not created['raw_ecg_included']
        with zipfile.ZipFile(created['path']) as archive:
            db_path = tmp_path / 'snapshot.db'
            db_path.write_bytes(archive.read('work.sqlite3'))
            assert archive.namelist() == ['work.sqlite3', 'manifest.json']
        snapshot = dump_tables(db_path)
        assert snapshot['audit_log'][-1][3] == 'committed'
        assert len(snapshot['audit_log']) == len(before['audit_log']) + 1
        assert snapshot['report_drafts'] == before['report_drafts']
        writer.rollback()
    assert backup.verify_backup(created['path'])['verified']
    assert Path(created['path']).stat().st_mode & 0o077 == 0
    assert before['report_drafts'] == dump_tables(workspace.path)['report_drafts']


def test_restore_preserves_work_but_requires_review(workspace, tmp_path):
    before = dump_tables(workspace.path)
    result = backup.create_backup(workspace.path, tmp_path / 'backups')
    restored = backup.restore_backup(result['path'], tmp_path / 'recovered')
    assert dump_tables(workspace.path) == before
    recovered = Storage(Path(restored['database']))
    after = dump_tables(recovered.path)
    for name in ('annotations', 'patient_overrides', 'beat_overrides', 'beat_templates', 'beat_edit_template_refs'):
        assert after[name] == before[name]
    old_editor = BeatEditorStore(workspace).read('synthetic')
    new_editor = BeatEditorStore(recovered).read('synthetic')
    assert new_editor == {**old_editor, 'revision': old_editor['revision'] + 1}
    old_rhythm = RhythmReviewStore(workspace).read('synthetic')
    assert RhythmReviewStore(recovered).read('synthetic') == {**old_rhythm, 'revision': old_rhythm['revision'] + 1}
    old_report, new_report = workspace.get_report('synthetic', ''), recovered.get_report('synthetic', '')
    assert new_report['conclusion'] == old_report['conclusion']
    assert old_report['status'] == 'reviewed' and new_report['status'] == 'draft'
    assert new_report['version'] > old_report['version']
    assert new_report['reviewed_by'] == ''
    assert not new_report['composition']['category_reviews']
    assert new_report['composition']['diagnosis_blocks'][0]['needs_review']
    assert not new_report['composition']['diagnosis_blocks'][0]['acknowledged']
    review = recovered.get_review('synthetic')
    assert review['pending_steps'] == ['edit', 'stt']
    assert review['events']['V:200']['status'] == 'pending'
    assert all(step['reason'] == 'workspace.restored' for step in review['steps'].values())
    assert recovered.list_audit()[0]['action'] == 'workspace.restored'
    assert (tmp_path / 'recovered' / 'RECOVERY.json').is_file()
    with pytest.raises(ValueError, match='报告审核前'):
        recovered.save_report('synthetic', new_report['conclusion'], 'reviewed', 'test')
    assert backup.recovery_epoch(recovered.path) != backup.recovery_epoch(workspace.path)


@pytest.mark.parametrize('alteration', ['hash', 'size', 'tables', 'schema', 'format', 'truncated', 'database', 'traversal', 'duplicate'])
def test_corruption_or_unsupported_archive_never_restores(workspace, tmp_path, alteration):
    created = backup.create_backup(workspace.path, tmp_path / 'backups')
    bad = tmp_path / 'bad.ecgbackup'
    before = dump_tables(workspace.path)
    if alteration == 'truncated':
        bad.write_bytes(Path(created['path']).read_bytes()[:200])
    else:
        mutations = {'hash': lambda v: v.update(sha256='0'*64), 'size': lambda v: v.update(database_bytes=1),
                     'tables': lambda v: v.update(tables={}), 'schema': lambda v: v.update(schema_sha256='wrong'),
                     'format': lambda v: v.update(format='unknown')}
        repack(created['path'], bad, change_manifest=mutations.get(alteration),
               change_database=(lambda value: b'x' + value[1:]) if alteration == 'database' else None,
               extra='../outside' if alteration == 'traversal' else 'work.sqlite3' if alteration == 'duplicate' else None)
    with pytest.raises(backup.BackupError):
        backup.restore_backup(bad, tmp_path / 'recovery')
    assert not (tmp_path / 'recovery').exists()
    assert not (tmp_path / 'outside').exists()
    assert dump_tables(workspace.path) == before


@pytest.mark.parametrize('kind', ['same', 'directory', 'file', 'symlink'])
def test_restore_never_replaces_existing_target(workspace, tmp_path, kind):
    created = backup.create_backup(workspace.path, tmp_path / 'backups')
    target = tmp_path / 'target'
    if kind == 'same':
        target = workspace.path.parent
    elif kind == 'directory':
        target.mkdir()
    elif kind == 'file':
        target.write_text('preserve')
    else:
        target.symlink_to(tmp_path / 'not-created')
    before = dump_tables(workspace.path)
    with pytest.raises(backup.BackupError, match='新目录'):
        backup.restore_backup(created['path'], target)
    assert dump_tables(workspace.path) == before
    if kind == 'file':
        assert target.read_text() == 'preserve'


@pytest.mark.parametrize('kind', ['missing', 'foreign', 'json', 'trigger', 'column'])
def test_invalid_source_is_not_a_successful_backup(tmp_path, kind):
    path = tmp_path / 'bad.db'
    if kind != 'missing':
        if kind != 'foreign':
            store = Storage(path)
        with closing(sqlite3.connect(path)) as db, db:
            if kind == 'foreign':
                db.execute('CREATE TABLE foreign_data(id INT)')
            elif kind == 'json':
                db.execute("INSERT INTO case_review VALUES('x',0,'not json','{}')")
            elif kind == 'trigger':
                db.execute("CREATE TRIGGER surprise AFTER INSERT ON audit_log BEGIN DELETE FROM annotations; END")
            else:
                db.execute('ALTER TABLE annotations ADD COLUMN unexpected TEXT')
    with pytest.raises(backup.BackupError):
        backup.create_backup(path, tmp_path / 'backups')
    assert not list((tmp_path / 'backups').glob('*.ecgbackup'))
    if kind == 'missing':
        assert not path.exists()


def test_disk_full_and_publish_failure_leave_source_unchanged(workspace, tmp_path, monkeypatch):
    before = dump_tables(workspace.path)
    with monkeypatch.context() as patch:
        patch.setattr(backup.shutil, 'disk_usage', lambda _: SimpleNamespace(free=0))
        with pytest.raises(backup.BackupError, match='空间不足'):
            backup.create_backup(workspace.path, tmp_path / 'backups')
    with monkeypatch.context() as patch:
        def fail(*_):
            raise OSError('synthetic ENOSPC')
        patch.setattr(backup.os, 'link', fail)
        with pytest.raises(backup.BackupError):
            backup.create_backup(workspace.path, tmp_path / 'backups')
    assert not list((tmp_path / 'backups').iterdir())
    assert dump_tables(workspace.path) == before


def test_backup_timeout_does_not_publish(workspace, tmp_path, monkeypatch):
    ticks = iter([0, 31, 32])
    monkeypatch.setattr(backup.time, 'monotonic', lambda: next(ticks))
    with pytest.raises(backup.BackupError, match='繁忙'):
        backup.create_backup(workspace.path, tmp_path / 'backups')
    assert not list((tmp_path / 'backups').glob('*.ecgbackup'))


def test_cli_roundtrip_and_repeat_target_refusal(workspace, tmp_path):
    def run(*args):
        return subprocess.run([sys.executable, 'scripts/manage_backups.py', *map(str,args)], capture_output=True, text=True, timeout=20)
    created = run('create', '--db', workspace.path, '--destination', tmp_path / 'backups')
    assert created.returncode == 0, created.stderr
    path = json.loads(created.stdout)['path']
    checked = run('verify', path)
    assert checked.returncode == 0 and json.loads(checked.stdout)['verified']
    restored = run('restore', path, '--new-app-data-root', tmp_path / 'recovered')
    assert restored.returncode == 0, restored.stderr
    again = run('restore', path, '--new-app-data-root', tmp_path / 'recovered')
    assert again.returncode == 2 and '新目录' in again.stderr


def test_api_backup_verify_and_guard(synthetic_app):
    client = synthetic_app.test_client()
    root = '/api/workspace/backups'
    assert client.get(root).json['enabled']
    assert client.post(root, json={}).status_code == 400
    created = client.post(root, json={'saved_work_acknowledged': True})
    assert created.status_code == 201, created.json
    assert client.post(root+'/'+created.json['name']+'/verify', json={}).json['verified']
    assert client.get(root).json['items'][0]['name'] == created.json['name']
    assert client.post(root+'/arbitrary.db/verify').status_code == 400
    lock = synthetic_app.extensions['backup_lock']
    with lock:
        assert client.post(root, json={'saved_work_acknowledged': True}).status_code == 409
    assert not client.get(root, environ_overrides={'REMOTE_ADDR': '10.1.2.3'}).json['enabled']
    assert client.post(root, json={'saved_work_acknowledged': True}, environ_overrides={'REMOTE_ADDR': '10.1.2.3'}).status_code == 403
    for mode in ('DEMO_READONLY', 'DEMO_AUTH_ENABLED', 'TRUST_PROXY_HEADERS'):
        synthetic_app.config[mode] = True
        assert not client.get(root).json['enabled']
        assert client.post(root, json={'saved_work_acknowledged': True}).status_code == 403
        synthetic_app.config[mode] = False


def test_recovered_app_rejects_old_ui_and_analysis(synthetic_app, synthetic_case, tmp_path):
    old_client = synthetic_app.test_client()
    cid = synthetic_case[1]
    base = f'/api/cases/{cid}'
    old_basis = old_client.get(base + '/analysis-basis').json
    created = backup.create_backup(synthetic_app.extensions['storage'].path, tmp_path / 'backups')
    result = backup.restore_backup(created['path'], tmp_path / 'recovered')
    app = create_app(data_root=synthetic_case[0], db_path=result['database'], testing=True)
    client = app.test_client()
    epoch = client.get('/api/health').json['workspace_epoch']
    assert epoch and epoch != old_client.get('/api/health').json['workspace_epoch']
    assert client.get(base + '/trend', query_string=old_basis).status_code == 409
    for route in ('/report', '/beat-overrides', '/annotations'):
        assert client.post(base + route, json={}).status_code == 409
    response = client.post('/api/workspace/backups', json={'saved_work_acknowledged': True}, headers={'X-CardioInsight-Workspace': epoch})
    assert response.status_code == 201, response.json
    assert client.get('/api/workspace/backups').json['recovered_workspace']
    assert client.get(base + '/analysis-basis').json['analysis_basis'] != old_basis['analysis_basis']


def test_restore_doctor_workflow_rechecks_edits_picks_and_exports(synthetic_app, synthetic_case, tmp_path):
    _, cid, paths = synthetic_case
    base = f'/api/cases/{cid}'
    original = {key: sha256(path.read_bytes()).hexdigest() for key, path in paths.items()}
    client = synthetic_app.test_client()
    store = synthetic_app.extensions['storage']
    edited = client.put(base+'/beat-editor', json=dict(operation='relabel', revision=0,
        confirmed=True, selection={'samples': [6000]}, class_code='V'))
    assert edited.status_code == 200, edited.json
    events = client.get(base+'/report-events?category=V').json
    event = events['items'][0]
    approved = approve(store, cid, dict(included_pages=['summary', 'event_strips'],
        selected_events=[dict(event_id=event['event_id'], basis_version=event['basis_version'])],
        category_reviews=events['basis_versions'], diagnosis_blocks=[dict(key='V:single',
        text='合成手工说明', manual=True, needs_review=False, acknowledged=True)]))
    # Bind the source/algorithm provenance through the real endpoint before backup.
    approved = client.get(base+'/report').json
    created = backup.create_backup(store.path, tmp_path/'backups')
    result = backup.restore_backup(created['path'], tmp_path/'recovered')
    recovered_app = create_app(data_root=synthetic_case[0], db_path=result['database'], testing=True)
    recovered = recovered_app.test_client()
    headers = {'X-CardioInsight-Workspace': recovered.get('/api/health').json['workspace_epoch']}
    report = recovered.get(base+'/report').json
    assert report['status'] == 'draft' and report['conclusion'] == approved['conclusion']
    assert report['composition']['selected_events'] == approved['composition']['selected_events']
    assert recovered.get(base+'/report-statistics').json['summary']['V']['total'] == 1
    def save(value, status):
        return recovered.put(base+'/report', headers=headers, json=dict(status=status,
            expected_version=value['version'], expected_review_revision=value['review_revision'],
            conclusion=value['conclusion'], composition=value['composition']))
    assert save(report, 'reviewed').status_code == 400
    for step in ('edit', 'stt'):
        workflow = recovered.get(base+'/review-workflow').json
        checked = recovered.put(base+'/review-workflow', headers=headers,
            json=dict(step=step, confirmed=True, revision=workflow['revision']))
        assert checked.status_code == 200, checked.json
    report = recovered.get(base+'/report').json
    index = recovered.get(base+'/report-events?category=V').json
    chosen = index['items'][0]
    report['composition']['selected_events'] = [dict(event_id=chosen['event_id'], basis_version=chosen['basis_version'])]
    report['composition']['category_reviews'] = index['basis_versions']
    report['composition']['diagnosis_blocks'][0].update(needs_review=False, acknowledged=True)
    saved = save(report, 'draft')
    assert saved.status_code == 200, saved.json
    verified = save(saved.json, 'reviewed')
    assert verified.status_code == 200, verified.json
    pdf = recovered.get(base+'/report.pdf', query_string={'expected_version': verified.json['version']})
    assert pdf.status_code == 200 and pdf.data.startswith(b'%PDF'), pdf.data[:300]
    assert {key: sha256(path.read_bytes()).hexdigest() for key, path in paths.items()} == original


@pytest.mark.parametrize('scenario', ['create', 'dirty', 'failure', 'busy', 'verify', 'refresh-failure', 'disabled', 'headers'])
def test_backup_browser_states(scenario):
    subprocess.run(['node', 'tests/browser_workspace_backup.cjs', scenario], check=True, timeout=15)
