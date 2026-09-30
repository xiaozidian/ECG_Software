"""Local, verified saved-work snapshots. Never overwrite a live workspace.

Raw ECG files, unsaved browser edits, configuration and exported PDFs are not
included. The archive contains identifiable health information, not encrypted
data. Hashes detect accidental changes; they are not an authenticity signature.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import time
import uuid
import zipfile

from .config import APP_VERSION

FORMAT = 'cardioinsight-saved-work-v1'
MAX_DB_BYTES = 2 * 1024**3
BACKUP_NAME = re.compile(r'work-\d{8}T\d{12}Z-[0-9a-f]{12}\.ecgbackup\Z')
CORE = {
    'annotations': 'id case_id sample_index lead category label note created_by created_at updated_at details',
    'report_drafts': 'case_id conclusion composition status version reviewed_by updated_at analysis_provenance',
    'case_analysis_basis': 'case_id basis updated_at',
    'patient_overrides': 'case_id payload active updated_at',
    'beat_templates': 'id case_id name rhythm_family lead source_class sample_indices start_sample end_sample note created_by created_at updated_at',
    'beat_overrides': 'case_id sample_index source_group class_code created_by created_at updated_at',
    'audit_log': 'id case_id actor action detail created_at',
    'case_review': 'case_id revision steps events',
}
OPTIONAL = {
    'beat_edit_documents': 'case_id revision document undo redo',
    'beat_edit_template_refs': 'template_id case_id beat_ids',
    'rhythm_reviews': 'case_id revision document undo redo updated_at',
    'workspace_recovery': 'id epoch source_sha256 restored_at',
}
JSON_FIELDS = {
    'annotations': {'details': dict},
    'report_drafts': {'composition': dict, 'analysis_provenance': dict},
    'case_analysis_basis': {'basis': dict},
    'patient_overrides': {'payload': dict},
    'beat_templates': {'sample_indices': list},
    'case_review': {'steps': dict, 'events': dict},
    'beat_edit_documents': {'document': dict, 'undo': list, 'redo': list},
    'beat_edit_template_refs': {'beat_ids': list},
    'rhythm_reviews': {'document': dict, 'undo': list, 'redo': list},
}


class BackupError(ValueError):
    """Safe, user-readable backup failure without patient content."""


def _stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _hash(path):
    value = sha256()
    with open(path, 'rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(part)
    return value.hexdigest()


def _readonly(path):
    # mode=ro includes committed WAL contents; immutable=1 would incorrectly
    # ignore a live WAL. Do not instantiate Storage on the source database.
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=1)
    db.execute('PRAGMA query_only=ON')
    db.execute('PRAGMA trusted_schema=OFF')
    return db


def _sync(path):
    with open(path, 'rb') as stream:
        os.fsync(stream.fileno())


def _sync_dir(path):
    if os.name == 'nt':
        return  # Windows does not expose directory fsync through this API.
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _check_database(path):
    """Check a detached copy, not a database that may still be changing."""
    with closing(_readonly(path)) as db:
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise BackupError('数据库完整性检查失败，未生成可恢复备份')
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise BackupError('数据库关联检查失败')
        objects = db.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
        if any(kind not in ('table', 'index') for kind, _, _ in objects):
            raise BackupError('备份含不支持的数据库对象，不能恢复')
        tables = {name for kind, name, _ in objects if kind == 'table'}
        if not CORE.keys() <= tables or not tables <= CORE.keys() | OPTIONAL.keys():
            raise BackupError('不是当前版本支持的工作数据库，请使用匹配的软件版本')
        counts = {}
        for table in sorted(tables):
            fields = set((CORE | OPTIONAL)[table].split())
            if {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')} != fields:
                raise BackupError('数据库字段版本不受支持，请使用匹配的软件版本')
            counts[table] = db.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            for field, kind in JSON_FIELDS.get(table, {}).items():
                for row in db.execute(f'SELECT "{field}" FROM "{table}"'):
                    try:
                        valid = isinstance(json.loads(row[0]), kind)
                    except (ValueError, TypeError):
                        valid = False
                    if not valid:
                        raise BackupError(f'数据库 {table} 的结构化记录损坏，未恢复')
                    value = json.loads(row[0])
                    if table == 'case_review' and any(not isinstance(x, dict) for x in value.values()):
                        raise BackupError('复核状态结构损坏，未恢复')
                    if table == 'report_drafts' and field == 'composition':
                        if not isinstance(value.get('category_reviews', {}), dict) or not isinstance(value.get('diagnosis_blocks', []), list):
                            raise BackupError('报告复核结构损坏，未恢复')
                        if any(not isinstance(x, dict) for x in value.get('diagnosis_blocks', [])):
                            raise BackupError('报告结论结构损坏，未恢复')
        schema = sha256(json.dumps(objects, ensure_ascii=False).encode()).hexdigest()
        return {'tables': counts, 'schema_sha256': schema}


def _snapshot(source, destination, timeout=30):
    deadline = time.monotonic() + timeout
    def progress(status, remaining, total):
        if time.monotonic() > deadline:
            raise BackupError('数据库繁忙，备份未完成；请稍后重试')
        if total * page_size > MAX_DB_BYTES:
            raise BackupError('工作数据库超过备份大小限制')
    with closing(_readonly(source)) as src, closing(sqlite3.connect(destination)) as dst:
        page_size = src.execute('PRAGMA page_size').fetchone()[0]
        size = src.execute('PRAGMA page_count').fetchone()[0] * page_size
        if size > MAX_DB_BYTES:
            raise BackupError('工作数据库超过 2 GiB，请由管理员分档处理')
        if shutil.disk_usage(destination.parent).free < size * 3 + 16 * 1024**2:
            raise BackupError('备份磁盘剩余空间不足，请释放空间或更换备份位置')
        src.backup(dst, pages=256, progress=progress, sleep=.05)
        dst.execute('PRAGMA journal_mode=DELETE')
    os.chmod(destination, 0o600)
    _sync(destination)


def _manifest(archive):
    entries = archive.infolist()
    if len(entries) != 2 or {x.filename for x in entries} != {'manifest.json', 'work.sqlite3'}:
        raise BackupError('备份包文件清单不正确')
    if any(x.flag_bits & 1 or x.compress_type != zipfile.ZIP_STORED for x in entries):
        raise BackupError('备份包格式不受支持')
    if archive.getinfo('manifest.json').file_size > 65536:
        raise BackupError('备份清单过大')
    if not 0 < archive.getinfo('work.sqlite3').file_size <= MAX_DB_BYTES:
        raise BackupError('备份数据库大小不受支持')
    try:
        manifest = json.loads(archive.read('manifest.json'))
    except (ValueError, UnicodeError) as exc:
        raise BackupError('备份清单损坏') from exc
    if not isinstance(manifest, dict) or manifest.get('format') != FORMAT:
        raise BackupError('不是受支持的工作备份格式')
    if not isinstance(manifest.get('sha256'), str) or not re.fullmatch('[0-9a-f]{64}', manifest['sha256']):
        raise BackupError('备份校验摘要缺失')
    if manifest.get('database_bytes') != archive.getinfo('work.sqlite3').file_size:
        raise BackupError('备份数据库大小与清单不符')
    return manifest


def _unpack_verified(archive_path, destination):
    if Path(archive_path).is_symlink() or not Path(archive_path).is_file():
        raise BackupError('请选择本机的普通备份文件，不能使用链接或目录')
    with zipfile.ZipFile(archive_path) as archive:
        manifest = _manifest(archive)
        if shutil.disk_usage(destination.parent).free < manifest['database_bytes'] * 2 + 16 * 1024**2:
            raise BackupError('校验磁盘剩余空间不足')
        with archive.open('work.sqlite3') as source, open(destination, 'xb') as target:
            os.chmod(destination, 0o600)
            shutil.copyfileobj(source, target, 1024 * 1024)
        if _hash(destination) != manifest['sha256']:
            raise BackupError('备份摘要校验失败，文件可能已损坏或被改动')
        facts = _check_database(destination)
        if any(manifest.get(key) != value for key, value in facts.items()):
            raise BackupError('备份数据库与清单内容不一致')
    return manifest


def create_backup(source, destination_dir):
    """Online SQLite backup, then validated archive published without replace."""
    source, folder = Path(source), Path(destination_dir)
    if source.is_symlink() or not source.is_file():
        raise BackupError('工作数据库不存在或是链接，不能创建空备份')
    name = 'work-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid.uuid4().hex[:12] + '.ecgbackup'
    target = folder / name
    try:
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        if folder.is_symlink():
            raise BackupError('备份目录不能是链接')
        with tempfile.TemporaryDirectory(prefix='.work-backup-', dir=folder) as temporary:
            staging = Path(temporary)
            database = staging / 'work.sqlite3'
            _snapshot(source, database)
            facts = _check_database(database)
            manifest = dict(format=FORMAT, app_version=APP_VERSION, created_at=_stamp(),
                database_bytes=database.stat().st_size, sha256=_hash(database), **facts,
                scope='saved-work-only', encrypted=False, raw_ecg_included=False,
                unsaved_browser_edits_included=False, exported_pdfs_included=False)
            archive_path = staging / 'snapshot.ecgbackup'
            with zipfile.ZipFile(archive_path, 'x', compression=zipfile.ZIP_STORED) as archive:
                archive.write(database, 'work.sqlite3')
                archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
            os.chmod(archive_path, 0o600)
            _unpack_verified(archive_path, staging / 'verified.sqlite3')
            _sync(archive_path)
            # A completed file appears atomically; EEXIST never replaces it.
            os.link(archive_path, target)
            _sync_dir(folder)
        return dict(manifest, name=name, path=str(target.resolve()), verified=True)
    except (sqlite3.Error, zipfile.BadZipFile, OSError) as exc:
        raise BackupError('备份未完成；请检查磁盘空间、目录权限及数据库状态后重试') from exc


def verify_backup(path):
    try:
        with tempfile.TemporaryDirectory(prefix='cardioinsight-verify-') as directory:
            result = _unpack_verified(path, Path(directory) / 'work.sqlite3')
        return dict(result, verified=True, name=Path(path).name)
    except (sqlite3.Error, zipfile.BadZipFile, OSError) as exc:
        raise BackupError('备份无法读取或已损坏，未执行恢复') from exc


def list_backups(folder, limit=10):
    folder = Path(folder)
    if not folder.is_dir():
        return []
    items = []
    for path in sorted(folder.glob('work-*.ecgbackup'), reverse=True):
        if not BACKUP_NAME.fullmatch(path.name) or path.is_symlink() or not path.is_file():
            continue
        # Listing does not claim that the current file has been fully verified.
        items.append({'name': path.name, 'bytes': path.stat().st_size})
        if len(items) >= limit:
            break
    return items


def recovery_epoch(path):
    with closing(_readonly(path)) as db:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workspace_recovery'").fetchone()
        row = db.execute('SELECT epoch FROM workspace_recovery WHERE id=1').fetchone() if exists else None
    return row[0] if row else ''


def restore_backup(path, destination_root, *, actor='本机恢复操作'):
    """Restore saved work to a NEW app-data root; leave originals untouched."""
    from .storage import Storage
    root = Path(destination_root).absolute()
    if root.exists() or root.is_symlink():
        raise BackupError('恢复目标必须是尚不存在的新目录；不会覆盖当前工作区')
    if not root.parent.is_dir():
        raise BackupError('恢复目标的父目录不存在')
    try:
        with tempfile.TemporaryDirectory(prefix='.cardioinsight-restore-', dir=root.parent) as temporary:
            staging = Path(temporary)
            database = staging / 'work.sqlite3'
            manifest = _unpack_verified(path, database)
            store = Storage(database)
            epoch, restored_at = uuid.uuid4().hex, _stamp()
            with closing(store.connect()) as db, db:
                db.execute('BEGIN IMMEDIATE')
                db.execute('''CREATE TABLE IF NOT EXISTS workspace_recovery
                    (id INTEGER PRIMARY KEY CHECK(id=1), epoch TEXT NOT NULL,
                     source_sha256 TEXT NOT NULL, restored_at TEXT NOT NULL)''')
                db.execute('INSERT OR REPLACE INTO workspace_recovery VALUES(1,?,?,?)',
                           (epoch, manifest['sha256'], restored_at))
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                case_ids = set()
                for table in CORE.keys() | OPTIONAL.keys():
                    if table in tables and 'case_id' in (CORE | OPTIONAL)[table].split():
                        case_ids.update(r[0] for r in db.execute(f'SELECT DISTINCT case_id FROM "{table}"') if r[0])
                for case_id in sorted(case_ids):
                    store._audit(db, actor, 'workspace.restored', case_id,
                                 '恢复已保存工作；审核需重新确认；source_sha256=' + manifest['sha256'])
                for table in ('beat_edit_documents', 'rhythm_reviews'):
                    if table in tables:
                        db.execute(f'UPDATE {table} SET revision=revision+1')
            # Consolidate any WAL generated by migrations into the final DB.
            final_db = staging / 'restored.sqlite3'
            _snapshot(database, final_db)
            _check_database(final_db)
            receipt = dict(format=FORMAT, source_sha256=manifest['sha256'],
                restored_at=restored_at, recovery_epoch=epoch, case_count=len(case_ids),
                review_required=True, raw_ecg_included=False)
            root.mkdir(mode=0o700)  # Exclusive creation, including concurrent restores.
            (root / 'data').mkdir(mode=0o700)
            os.link(final_db, root / 'data' / 'cardioinsight.db')
            with open(root / 'RECOVERY.json', 'x', encoding='utf-8') as stream:
                os.chmod(root / 'RECOVERY.json', 0o600)
                json.dump(receipt, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            _sync_dir(root / 'data')
            _sync_dir(root)
            _sync_dir(root.parent)
        return dict(receipt, path=str(root), database=str(root / 'data' / 'cardioinsight.db'))
    except (sqlite3.Error, zipfile.BadZipFile, OSError) as exc:
        raise BackupError('恢复未完成；原工作区未被覆盖。若新目标已出现，请保留检查并另选新目录重试') from exc
