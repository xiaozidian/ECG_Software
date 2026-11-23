"""Versioned exclusion-only HRV review, independent of raw ECG and beat edits.

Callers supply the actual source/clinical context; this module never invents a
source digest, reads recordings, or runs an analysis.  A successful calculation
or saved document is not a physician confirmation or a clinical certification.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import math
import re
import secrets
import time
from datetime import datetime, timezone

from .review_workflow import ReportConflict

PROFILE = 'fixed-300s-fft-compat-v1'
SCOPE_FIELDS = ('case_id', 'source_digest', 'data_version', 'analysis_basis',
                'beat_revision', 'analysis_revision')
SOURCE_FIELDS = ('case_id', 'source_digest', 'data_version', 'analysis_basis', 'beat_revision')
MAX_EXCLUSIONS = 500
MAX_HISTORY = 20
PREVIEW_TTL_SECONDS = 900
WINDOW_SAMPLES = 86400 * 200


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def blank_document():
    return dict(schema_version=1, profile=PROFILE, exclusions=[])


def _integer(value, label, low=0, high=2**53-1):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{label}必须为 {low}–{high} 的整数')
    return value


def normalize_scope(value, case_id):
    if not isinstance(value, dict):
        raise ValueError('缺少完整的 HRV 计算依据')
    result = {}
    for key in SCOPE_FIELDS:
        item = value.get(key)
        if key in ('beat_revision', 'analysis_revision'):
            result[key] = _integer(item, key)
        elif not isinstance(item, str) or not item.strip() or len(item) > 512:
            raise ValueError('HRV 计算依据字段无效：' + key)
        else:
            result[key] = item
    if result['case_id'] != case_id:
        raise ReportConflict('HRV 病例已变化，请重新读取')
    return result


def normalize_document(value, duration_samples):
    _integer(duration_samples, '记录采样长度')
    if not isinstance(value, dict) or set(value) != {'schema_version', 'profile', 'exclusions'}:
        raise ValueError('HRV 复核文档字段无效')
    if type(value['schema_version']) is not int or value['schema_version'] != 1 or value['profile'] != PROFILE:
        raise ValueError('HRV 复核计算协议不受支持')
    exclusions = value['exclusions']
    if not isinstance(exclusions, list) or len(exclusions) > MAX_EXCLUSIONS:
        raise ValueError('HRV 排除区间最多 500 项')
    clean, seen = [], set()
    for item in exclusions:
        if not isinstance(item, dict) or set(item) != {'id', 'start_sample', 'end_sample', 'reason'}:
            raise ValueError('HRV 排除区间字段无效')
        ident, reason = item['id'], item['reason']
        if not isinstance(ident, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', ident) or ident in seen:
            raise ValueError('HRV 排除区间标识无效或重复')
        a = _integer(item['start_sample'], '排除起点', 0, duration_samples)
        b = _integer(item['end_sample'], '排除终点', 0, duration_samples)
        if a >= b:
            raise ValueError('HRV 排除起点必须早于终点；范围为半开采样区间')
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
            raise ValueError('请填写 1–500 字的 HRV 排除原因')
        seen.add(ident)
        clean.append(dict(id=ident, start_sample=a, end_sample=b, reason=reason.strip()))
    # Overlaps are retained as separate authored entries; their statistical mask
    # is the union.  Restoring one entry cannot restore another overlapping mask.
    clean.sort(key=lambda x: (x['start_sample'], x['end_sample'], x['id']))
    return dict(schema_version=1, profile=PROFILE, exclusions=clean)


def _window(window, duration_samples):
    _integer(duration_samples, '记录采样长度')
    count = max(1, math.ceil(duration_samples / WINDOW_SAMPLES))
    _integer(window, '24 小时窗口', 0, count-1)
    start = window * WINDOW_SAMPLES
    return dict(window_index=window, start_sample=start,
                end_sample=min(duration_samples, start+WINDOW_SAMPLES))


class HrvReviewStore:
    """SQLite store using storage.connect(), with optional caller-owned hooks.

    on_change(db, case_id, action) owns global/report invalidation.  The caller's
    check_current(db) rechecks actual files, beat revision and global review
    revision inside a transaction.  No production/doctor database is selected
    or opened by this class on its own.
    """
    def __init__(self, storage, *, clock=time.time):
        self.storage, self.clock = storage, clock
        with storage.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS hrv_review_documents (
                case_id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
                document TEXT NOT NULL, document_scope TEXT NOT NULL,
                confirmations TEXT NOT NULL, undo TEXT NOT NULL, redo TEXT NOT NULL,
                updated_at TEXT NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS hrv_review_previews (
                token TEXT PRIMARY KEY, case_id TEXT NOT NULL, revision INTEGER NOT NULL,
                scope TEXT NOT NULL, operation TEXT NOT NULL, document TEXT NOT NULL,
                preview_digest TEXT NOT NULL, actor TEXT NOT NULL,
                window_index INTEGER NOT NULL, created_at REAL NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS hrv_review_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL,
                actor TEXT NOT NULL, action TEXT NOT NULL, revision INTEGER NOT NULL,
                document_digest TEXT NOT NULL, created_at TEXT NOT NULL)''')

    def _read(self, db, case_id, context):
        row = db.execute('SELECT * FROM hrv_review_documents WHERE case_id=?', (case_id,)).fetchone()
        if row is None:
            return dict(revision=0, document=blank_document(), document_scope=copy.deepcopy(context),
                        confirmations={}, undo=[], redo=[], updated_at=None)
        return dict(revision=row['revision'], document=json.loads(row['document']),
                    document_scope=json.loads(row['document_scope']),
                    confirmations=json.loads(row['confirmations']),
                    undo=json.loads(row['undo']), redo=json.loads(row['redo']), updated_at=row['updated_at'])

    def _public(self, state, context, duration_samples, window):
        region = _window(window, duration_samples)
        checksum = digest(state['document'])
        confirmations = copy.deepcopy(state['confirmations'])
        for entry in confirmations.values():
            entry['valid'] = (entry.get('scope') == context
                              and entry.get('hrv_revision') == state['revision']
                              and entry.get('document_digest') == checksum)
        current = confirmations.get(str(window))
        stale = any(state['document_scope'].get(key) != context[key] for key in SOURCE_FIELDS)
        return dict(scope=copy.deepcopy(context), hrv_revision=state['revision'],
                    document=copy.deepcopy(state['document']), document_scope=copy.deepcopy(state['document_scope']),
                    document_stale=stale, digest=checksum, document_digest=checksum,
                    confirmations=confirmations,
                    confirmation=current if current else dict(valid=False, status='pending', **region),
                    can_undo=bool(state['undo']), can_redo=bool(state['redo']),
                    updated_at=state['updated_at'], profile=PROFILE, **region)

    def read(self, case_id, context, duration_samples, *, window=0, db=None):
        context = normalize_scope(context, case_id)
        _integer(duration_samples, '记录采样长度')
        if db is None:
            with self.storage.connect() as connection:
                return self.read(case_id, context, duration_samples, window=window, db=connection)
        return self._public(self._read(db, case_id, context), context, duration_samples, window)

    def _expected(self, payload, context, state):
        if not isinstance(payload, dict):
            raise ValueError('HRV 请求必须为对象')
        if normalize_scope(payload.get('scope'), context['case_id']) != context:
            raise ReportConflict('HRV 来源、心搏或复核依据已变化，请重新读取并预览')
        revision = _integer(payload.get('expected_hrv_revision'), 'HRV 复核版本')
        if revision != state['revision']:
            raise ReportConflict('HRV 复核已有新修订，未覆盖当前文档；请重新读取')

    def _target(self, state, payload, duration_samples):
        operation = payload.get('operation')
        if operation == 'replace':
            document = normalize_document(payload.get('document'), duration_samples)
        elif operation == 'reset':
            document = blank_document()
        elif operation in ('undo', 'redo'):
            if not state[operation]:
                raise ValueError('没有可撤销／重做的 HRV 区间修订')
            document = normalize_document(state[operation][-1], duration_samples)
        else:
            raise ValueError('HRV 操作不受支持')
        return operation, document

    def _preview_body(self, context, state, operation, document, window):
        return dict(scope=context, expected_hrv_revision=state['revision'], operation=operation,
                    before_digest=digest(state['document']), document=document,
                    window=window, profile=PROFILE)

    def preview(self, case_id, payload, context, duration_samples, *, actor='', window=0):
        context = normalize_scope(context, case_id)
        window = payload.get('window', window) if isinstance(payload, dict) else window
        _window(window, duration_samples)
        with self.storage.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            state = self._read(db, case_id, context)
            self._expected(payload, context, state)
            operation, document = self._target(state, payload, duration_samples)
            body = self._preview_body(context, state, operation, document, window)
            checksum, token = digest(body), secrets.token_urlsafe(32)
            db.execute('DELETE FROM hrv_review_previews WHERE case_id=? OR created_at<?',
                       (case_id, self.clock()-PREVIEW_TTL_SECONDS))
            db.execute('INSERT INTO hrv_review_previews VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (token, case_id, state['revision'], json.dumps(context), operation,
                        json.dumps(document, ensure_ascii=False), checksum, actor, window, self.clock()))
        return dict(preview_token=token, preview_digest=checksum, scope=copy.deepcopy(context),
                    expected_hrv_revision=state['revision'], operation=operation,
                    before=copy.deepcopy(state['document']), after=copy.deepcopy(document),
                    window_index=window, expires_in_s=PREVIEW_TTL_SECONDS, profile=PROFILE)

    def _current(self, context, case_id, db, check_current):
        return normalize_scope(check_current(db) if check_current else context, case_id)

    def _after_context(self, before, context, case_id, db, check_current):
        after = self._current(context, case_id, db, check_current)
        if any(before[key] != after[key] for key in SOURCE_FIELDS):
            raise ReportConflict('保存期间 HRV 原始来源或心搏依据已变化，修订未保存')
        if after['analysis_revision'] < before['analysis_revision']:
            raise ReportConflict('HRV 复核依据回退，请重新读取')
        return after

    def _write(self, db, case_id, state):
        db.execute('''INSERT INTO hrv_review_documents VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(case_id) DO UPDATE SET revision=excluded.revision,
            document=excluded.document, document_scope=excluded.document_scope,
            confirmations=excluded.confirmations, undo=excluded.undo, redo=excluded.redo,
            updated_at=excluded.updated_at''',
            (case_id, state['revision'], json.dumps(state['document'], ensure_ascii=False),
             json.dumps(state['document_scope']), json.dumps(state['confirmations'], ensure_ascii=False),
             json.dumps(state['undo'], ensure_ascii=False), json.dumps(state['redo'], ensure_ascii=False), state['updated_at']))

    def _audit(self, db, case_id, actor, action, state):
        checksum = digest(state['document'])
        db.execute('INSERT INTO hrv_review_audit(case_id,actor,action,revision,document_digest,created_at) VALUES(?,?,?,?,?,?)',
                   (case_id, actor, action, state['revision'], checksum, stamp()))
        if callable(getattr(self.storage, '_audit', None)):
            self.storage._audit(db, actor, 'hrv_review.'+action, case_id,
                                f"revision={state['revision']} digest={checksum}")

    def apply(self, case_id, payload, actor, context, duration_samples, *, check_current=None, on_change=None):
        if not isinstance(payload, dict) or payload.get('confirmed') is not True:
            raise ValueError('请核对 HRV 重算预览并明确确认保存')
        with self.storage.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = self._current(context, case_id, db, check_current)
            state = self._read(db, case_id, current)
            self._expected(payload, current, state)
            token = payload.get('preview_token')
            if not isinstance(token, str) or len(token) > 100:
                raise ValueError('缺少 HRV 重算预览凭证')
            row = db.execute('SELECT * FROM hrv_review_previews WHERE token=? AND case_id=?', (token,case_id)).fetchone()
            if row is None or self.clock()-row['created_at'] > PREVIEW_TTL_SECONDS or self.clock() < row['created_at']:
                raise ReportConflict('HRV 预览已取消、失效或过期，请重新预览')
            if json.loads(row['scope']) != current or row['revision'] != state['revision']:
                raise ReportConflict('HRV 预览依据已变化，请重新预览')
            if row['actor'] and row['actor'] != actor:
                raise ReportConflict('HRV 预览操作人已变化，请重新预览')
            if 'window' in payload and payload['window'] != row['window_index']:
                raise ReportConflict('HRV 预览窗口已变化，请重新预览')
            document = normalize_document(json.loads(row['document']),duration_samples)
            body = self._preview_body(current,state,row['operation'],document,row['window_index'])
            claimed = payload.get('preview_digest')
            if (not isinstance(claimed,str) or not hmac.compare_digest(claimed,row['preview_digest'])
                    or not hmac.compare_digest(digest(body),row['preview_digest'])):
                raise ReportConflict('HRV 预览内容不一致，请重新预览')
            db.execute('DELETE FROM hrv_review_previews WHERE case_id=?',(case_id,))
            changed = document != state['document'] or any(state['document_scope'].get(k) != current[k] for k in SOURCE_FIELDS)
            if changed:
                before = copy.deepcopy(state['document'])
                operation = row['operation']
                if operation in ('undo','redo'):
                    state[operation].pop()
                    state['redo' if operation == 'undo' else 'undo'].append(before)
                else:
                    state['undo'].append(before)
                    state['redo'] = []
                for stack in ('undo','redo'):
                    state[stack] = state[stack][-MAX_HISTORY:]
                    while len(state[stack]) > 1 and len(json.dumps(state[stack])) > 2_000_000:
                        state[stack].pop(0)
                state.update(document=document, revision=state['revision']+1, confirmations={}, updated_at=stamp())
                if on_change:
                    on_change(db,case_id,'hrv_review.changed')
                current = self._after_context(current,context,case_id,db,check_current)
                state['document_scope'] = copy.deepcopy(current)
                self._write(db,case_id,state)
                self._audit(db,case_id,actor,operation,state)
            else:
                current = self._after_context(current,context,case_id,db,check_current)
            return self._public(state,current,duration_samples,row['window_index'])

    def cancel_preview(self, case_id, payload, context, duration_samples):
        """Cancel a token without changing any saved document/revision/confirmation."""
        context = normalize_scope(context,case_id)
        with self.storage.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            state = self._read(db,case_id,context)
            self._expected(payload,context,state)
            token = payload.get('preview_token')
            if not isinstance(token,str):
                raise ValueError('缺少 HRV 预览凭证')
            db.execute('DELETE FROM hrv_review_previews WHERE token=? AND case_id=?',(token,case_id))
        return self._public(state,context,duration_samples,payload.get('window',0))

    def confirm(self, case_id, payload, actor, context, duration_samples, *, check_current=None, on_change=None):
        if (not isinstance(payload,dict) or payload.get('confirmed') is not True
                or payload.get('nn_rhythm_artifact_reviewed') is not True):
            raise ValueError('请明确确认已核对当前窗口 NN 候选、节律和伪差')
        note = payload.get('note','')
        if not isinstance(note,str) or len(note) > 1200:
            raise ValueError('HRV 复核备注最多 1200 字')
        region = _window(payload.get('window',0),duration_samples)
        with self.storage.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = self._current(context,case_id,db,check_current)
            state = self._read(db,case_id,current)
            self._expected(payload,current,state)
            checksum = digest(state['document'])
            if payload.get('expected_document_digest') != checksum:
                raise ReportConflict('HRV 文档已变化，请重新核对')
            if any(state['document_scope'].get(k) != current[k] for k in SOURCE_FIELDS):
                raise ReportConflict('HRV 来源或心搏依据已变化，请先重新预览并保存当前区间')
            # Keep previous windows only when they were valid immediately before
            # this acknowledgement.  Refresh their global revision for this
            # acknowledgement alone; no data/document change is being blessed.
            retained = {key:entry for key,entry in state['confirmations'].items()
                        if entry.get('scope') == current and entry.get('hrv_revision') == state['revision']
                        and entry.get('document_digest') == checksum}
            if on_change:
                on_change(db,case_id,'hrv_review.confirmed')
            current = self._after_context(current,context,case_id,db,check_current)
            for entry in retained.values():
                entry['scope'] = copy.deepcopy(current)
            retained[str(region['window_index'])] = dict(status='confirmed', actor=actor, note=note.strip(),
                updated_at=stamp(), scope=copy.deepcopy(current), hrv_revision=state['revision'],
                document_digest=checksum, nn_rhythm_artifact_reviewed=True,
                confirmation_scope='physician_review_declaration_current_window',
                clinical_validation=False, quality_status='unknown', **region)
            state.update(confirmations=retained,updated_at=stamp(),document_scope=copy.deepcopy(current))
            db.execute('DELETE FROM hrv_review_previews WHERE case_id=?',(case_id,))
            self._write(db,case_id,state)
            self._audit(db,case_id,actor,'confirm',state)
            return self._public(state,current,duration_samples,region['window_index'])
