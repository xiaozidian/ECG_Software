"""Physician review of exact report evidence, separate from disease diagnosis."""
from __future__ import annotations

from hashlib import sha256
import json
import math

from .report_layout import resolve_strip, strip_settings, valid_rr_pairs
from .review_workflow import ReportConflict, stamp


def canonical(value):
    def integral(item):
        if isinstance(item,float) and item.is_integer():return int(item)
        if isinstance(item,dict):return {k:integral(v) for k,v in item.items()}
        if isinstance(item,(list,tuple)):return [integral(v) for v in item]
        return item
    return json.dumps(integral(value), ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return sha256(canonical(value).encode()).hexdigest()


def review_selection(event, entry):
    settings = strip_settings(entry)
    return dict(leads=settings['leads'], duration_s=settings['duration_s'],
                range_start_s=settings.get('range_start_s'), range_end_s=settings.get('range_end_s'),
                caption=entry.get('caption') or event.get('label', ''), notes=entry.get('notes', ''))


def evidence_descriptor(index, event, identity, pairs=None):
    scope = {k: identity[k] for k in ('case_id', 'analysis_basis', 'beat_revision')}
    if event.get('category') in ('pause', 'rr_candidate'):
        pairs = pairs if pairs is not None else {b['sample_index']: (a, b) for a, b in valid_rr_pairs(index['rows'], index['duration_s'])}
        pair = pairs.get(event['start_sample'])
        if not pair:
            raise ReportConflict('RR 原始相邻两搏已变化，请重新选择图条')
        a, b = pair
        context = event.get('candidate_context', {})
        if context.get('rr_start_sample', a['sample_index']) != a['sample_index'] or event.get('rr_ms') != b['rr_ms']:
            raise ReportConflict('RR 数值或原始两搏已变化，请重新选择图条')
        fields = ('id', 'sample_index', 'class_code')
        return dict(schema=1, scope=scope, kind='rr', previous={k: a.get(k) for k in fields},
                    terminal={k: b.get(k) for k in fields}, rr_ms=b['rr_ms'],
                    endpoint_delta_ms=(b['sample_index']-a['sample_index'])*5)
    if event.get('evidence_only') and event.get('subtype') == 'manual_strip':
        p = event['candidate_context']
        return dict(schema=1, scope=scope, kind='strip', start_sample=p['start_sample'], end_sample=p['end_sample'])
    raise ValueError('此事件沿用原有诊断确认流程，无需新增 RR 核对')


def attach_reviews(index, identity, records):
    pairs = None
    by_key = {r['evidence_key']: r for r in records}
    for event in index['events']:
        if event.get('category') not in ('pause', 'rr_candidate') and not event.get('evidence_only'):
            continue
        if pairs is None:
            pairs = {b['sample_index']: (a, b) for a, b in valid_rr_pairs(index['rows'], index['duration_s'])}
        descriptor = evidence_descriptor(index, event, identity, pairs)
        key = digest(descriptor)
        record = by_key.get(key)
        event['evidence_ref'] = dict(key=key, **descriptor)
        event['evidence_review'] = dict(status='confirmed' if record and record['status']=='confirmed' else 'pending',
            presentations=record['presentations'] if record and record['status']=='confirmed' else [],
            actor=record['actor'] if record else '', confirmed_at=record['updated_at'] if record else '')
    return index


def presentation(index, event, entry):
    spec = resolve_strip(index, event, entry)
    selection = review_selection(event, entry)
    return dict(selection=selection, start_s=spec['start_s'], end_s=spec['end_s'])


def evidence_confirmed(index, event, entry):
    review = event.get('evidence_review', {})
    if review.get('status') != 'confirmed':
        return False
    proof = presentation(index, event, entry)
    return any(p.get('presentation_key') == digest(proof) for p in review.get('presentations', []))


def assert_caption(index, event, entry):
    if event.get('category') not in ('pause', 'rr_candidate') or '最长' not in (entry.get('caption') or event.get('label', '')):
        return
    values = [b['rr_ms'] for _, b in valid_rr_pairs(index['rows'], index['duration_s'])]
    if not values or event['rr_ms'] != max(values):
        raise ValueError('本条不是当前可分析记录的最长 RR；请改为客观 RR 图注，或核对报告中的最长值')


def longest_event(index, identity, records):
    pairs = valid_rr_pairs(index['rows'], index['duration_s'])
    if not pairs:
        return None
    a, b = max(pairs, key=lambda pair: (pair[1]['rr_ms'], -pair[1]['sample_index']))
    context = dict(rr_start_sample=a['sample_index'], rr_end_sample=b['sample_index'],
                   rr_start_id=a['id'], rr_end_id=b['id'], rr_ms=b['rr_ms'],
                   start_s=a['sample_index']/200, end_s=b['sample_index']/200)
    event = dict(event_id='report-longest-rr', category='rr_candidate', subtype='rr_measurement',
        label=f"最长 RR {b['rr_ms']/1000:.3f} s（当前可分析记录）", sample_index=b['sample_index'],
        start_sample=b['sample_index'], end_sample=b['sample_index'], time_s=b['sample_index']/200,
        end_s=b['sample_index']/200, rr_ms=b['rr_ms'], hr=b.get('hr'), target_samples=[b['sample_index']],
        beat_count=1, templates=[], evidence_only=True, diagnosis_status='pending',
        candidate_context=context, candidate_scope=identity)
    event['basis_version'] = 'report-rr-v1:'+digest(evidence_descriptor(index, event, identity))
    attach_reviews({**index, 'events': [event]}, identity, records)
    return event


def used_in_output(composition, entry, event=None):
    """Nonprinting curation stays saved without becoming an approval gate."""
    from .report_sections import selected_pages
    if entry.get('referenced_in_report') is True:
        return True
    if 'event_strips' not in selected_pages(composition) or entry.get('print_enabled') is False:
        return False
    mode = composition.get('fast_slow_mode', 'rr')
    return not event or event['category'] not in ('fastest', 'slowest') or mode=='both' or event['subtype']==mode.upper()


def check_read_wave(entry):
    wave, spec = entry['waveform'], entry['strip']
    if (abs(wave.get('start_s', -1)-spec['start_s']) > .005 or
        abs(wave.get('duration_s', -1)-(spec['end_s']-spec['start_s'])) > .005):
        raise ReportConflict('所读波形范围与本条图条不一致，未保存核对')
    for name in spec['leads']:
        values = wave.get('leads', {}).get(name)
        if not isinstance(values, list) or not values or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
            raise ValueError('所选导联波形未完整读取，请重试后核对')


class ReportEvidenceMixin:
    def initialize_report_evidence(self):
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS report_evidence_reviews (
                case_id TEXT NOT NULL, evidence_key TEXT NOT NULL, descriptor TEXT NOT NULL,
                presentations TEXT NOT NULL, status TEXT NOT NULL, actor TEXT NOT NULL,
                updated_at TEXT NOT NULL, PRIMARY KEY(case_id,evidence_key))''')

    def list_report_evidence(self, case_id, db=None):
        if db is None:
            with self.connect() as connection:
                return self.list_report_evidence(case_id, connection)
        return [{**dict(r), 'descriptor':json.loads(r['descriptor']), 'presentations':json.loads(r['presentations'])}
                for r in db.execute('SELECT * FROM report_evidence_reviews WHERE case_id=? ORDER BY evidence_key', (case_id,))]

    def confirm_report_evidence(self, case_id, descriptor, proof, actor, guard):
        key, proof_key = digest(descriptor), digest(proof)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            guard(db)
            old = next((r for r in self.list_report_evidence(case_id, db) if r['evidence_key']==key), None)
            proofs = old['presentations'] if old and old['status']=='confirmed' else []
            if not any(p['presentation_key']==proof_key for p in proofs):
                if len(proofs) >= 100:
                    raise ValueError('本段核对版本过多，请先整理图条')
                proofs.append({**proof, 'presentation_key':proof_key})
                db.execute('''INSERT INTO report_evidence_reviews VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(case_id,evidence_key) DO UPDATE SET presentations=excluded.presentations,
                    status=excluded.status,actor=excluded.actor,updated_at=excluded.updated_at''',
                    (case_id, key, canonical(descriptor), canonical(proofs), 'confirmed', actor, stamp()))
                # Check source and report revisions before committing this acknowledgement.
                guard(db)
                self._audit(db, actor, 'report_evidence.confirmed', case_id, key+':'+proof_key)
            return next(r for r in self.list_report_evidence(case_id, db) if r['evidence_key']==key)
