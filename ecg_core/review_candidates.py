"""Local evidence picks. They never edit beats, diagnoses, or detector thresholds."""
from __future__ import annotations

from hashlib import sha256
import json
import math
from .report_layout import valid_rr_pairs, strip_settings, resolve_strip
from .review_workflow import ReportConflict


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False)


def pause_edges(value=None):
    if value is None or value == '': return [2500, 3000, 4000]
    if isinstance(value, str):
        try: value = [float(x) for x in value.split(',')]
        except ValueError: raise ValueError('长 RR 统计边界须为毫秒数')
    if (not isinstance(value, list) or len(value) != 3 or
        any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x)
            or x != int(x) or not 1 <= x <= 60000 for x in value) or
        not value[0] < value[1] < value[2]):
        raise ValueError('请设置三个递增的整数毫秒统计边界（1–60000）')
    return [int(x) for x in value]


def rr_distribution(rows, duration, edges=None):
    edges = pause_edges(edges)
    pairs = valid_rr_pairs(rows, duration)
    bins = []
    for i, lo in enumerate(edges):
        hi = edges[i+1] if i < 2 else None
        selected = [b for a, b in pairs if b['rr_ms'] >= lo and (hi is None or b['rr_ms'] < hi)]
        label = f'[{lo/1000:g}, {hi/1000:g}) s' if hi is not None else f'≥{lo/1000:g} s'
        bins.append(dict(key=str(i), lower_ms=lo, upper_ms=hi, label=label, count=len(selected),
                         samples=[r['sample_index'] for r in selected]))
    return dict(edges_ms=edges, bins=bins, valid_rr_count=len(pairs),
                method='互斥统计分箱：含下界、不含上界；末箱含下界。只统计有效原始相邻 RR；不改变 >2.5 s 检测阈值，不等同停搏诊断。')


def prepare_candidate(index, identity, payload):
    kind = payload.get('kind')
    caption = payload.get('caption', '')
    if not isinstance(caption, str) or len(caption) > 120: raise ValueError('候选图注须为不超过120字的文本')
    scope = {k: identity[k] for k in ('case_id', 'analysis_basis', 'analysis_revision', 'beat_revision')}
    settings = strip_settings(payload.get('settings'))
    if kind == 'rr':
        sample = payload.get('sample_index')
        if type(sample) is not int: raise ValueError('RR 候选须指定原心搏采样位置')
        pair = next(((a, b) for a, b in valid_rr_pairs(index['rows'], index['duration_s']) if b['sample_index'] == sample), None)
        if pair is None: raise ValueError('此位置没有有效相邻 RR，伪差及断点不能加入候选')
        a, b = pair
        if 'rr_ms' in payload and payload['rr_ms'] != b['rr_ms']: raise ReportConflict('RR 已变化，请重新选择')
        context = dict(rr_start_sample=a['sample_index'], rr_end_sample=b['sample_index'],
            rr_start_id=a['id'], rr_end_id=b['id'], rr_ms=b['rr_ms'],
            endpoint_delta_ms=(b['sample_index']-a['sample_index'])*5,
            start_s=a['sample_index']/200, end_s=b['sample_index']/200)
        population = payload.get('population') or {}
        if not isinstance(population, dict): raise ValueError('候选来源范围无效')
        origin = population.get('origin', 'manual-card')
        if origin not in ('overview-histogram', 'manual-card', 'edit-card', 'overview-card', 'overview-rr-bin'):
            origin = 'manual-card'
        context['population'] = dict(origin=origin, claim='用户选取的 RR 候选；不声明全记录最长')
        bounds = population.get('rr_bounds_ms')
        if bounds is not None:
            if (not isinstance(bounds, list) or len(bounds) != 2 or
                any(x is not None and (isinstance(x, bool) or not isinstance(x, (float, int)) or not math.isfinite(x)) for x in bounds) or
                bounds[0] is None or b['rr_ms'] < bounds[0] or bounds[1] is not None and b['rr_ms'] >= bounds[1]):
                raise ReportConflict('RR 不在所选柱状区间，未保存错配候选')
            context['population']['rr_bounds_ms'] = bounds
        caption = caption.strip() or f'自选 RR 候选 {b["rr_ms"]/1000:.3f} s'
        anchor = b
    elif kind == 'strip':
        if 'range_start_s' not in settings: raise ValueError('全记录留图须指定精确起止')
        a, b = settings['range_start_s'], settings['range_end_s']
        rows = [r for r in index['rows'] if r['class_code'] not in ('X','O','Y','T') and a <= r['sample_index']/200 < b]
        if not rows: raise ValueError('所选留图区间没有可用心搏；伪差仅保留质控')
        anchor = rows[0]
        context = dict(start_s=a, end_s=b, start_sample=round(a*200), end_sample=round(b*200),
                       population=dict(origin='full-record-retain', claim='人工选段；不构成诊断'))
        caption = caption.strip() or '全记录人工留图'
    else: raise ValueError('不支持的候选类型')
    event = dict(start_sample=anchor['sample_index'], category='rr_candidate' if kind=='rr' else 'other', candidate_context=context)
    if kind == 'rr':
        # Use the same exact endpoint coverage as pause rendering, without changing
        # the detector pool or imposing the detector's 2500 ms threshold.
        settings['duration_s'] = min(120, max(settings['duration_s'], b['rr_ms']/1000+2))
    spec = resolve_strip(index, event, settings)
    if kind == 'rr' and spec['start_s'] > context['start_s']:
        settings.update(range_start_s=max(0, context['start_s']-.5), range_end_s=spec['end_s'])
        spec = resolve_strip(index, event, settings)
    context.update(caption=caption, settings={**settings, 'leads':['II','V1','V5']},
                   anchor_sample=anchor['sample_index'], context_start_s=spec['context_start_s'],
                   context_duration_s=spec['context_duration_s'])
    key_scope = {k: scope[k] for k in ('case_id','analysis_basis','beat_revision')}
    key = sha256(canonical([kind, key_scope, [context.get('rr_start_sample'), context.get('rr_end_sample')]
                            if kind=='rr' else [context['start_sample'],context['end_sample']]]).encode()).hexdigest()
    return dict(kind=kind, scope=scope, payload=context, candidate_key=key)


def augment_index(index, candidates, identity):
    pairs = {b['sample_index']:(a,b) for a,b in valid_rr_pairs(index['rows'], index['duration_s'])}
    active_ids = []
    for c in candidates:
        p, s = c['payload'], c['scope']
        if c['status'] != 'active' or any(s[k] != identity[k] for k in ('case_id','analysis_basis','beat_revision')): continue
        anchor = p['anchor_sample']
        row = next((r for r in index['rows'] if r['sample_index']==anchor and r['class_code'] not in ('X','O','Y','T')), None)
        if row is None: continue
        if c['kind'] == 'rr':
            pair = pairs.get(anchor)
            if not pair or (pair[0]['sample_index'], pair[0]['id'], pair[1]['id'], pair[1]['rr_ms']) != (p['rr_start_sample'],p['rr_start_id'],p['rr_end_id'],p['rr_ms']): continue
        category = 'rr_candidate' if c['kind']=='rr' else 'other'
        basis = 'local-pick-v1:'+sha256(canonical([s,p]).encode()).hexdigest()[:24]
        item = dict(event_id=f'local-pick:{c["id"]}', category=category, subtype='manual_rr' if c['kind']=='rr' else 'manual_strip',
            label=p['caption'], sample_index=anchor, start_sample=anchor, end_sample=anchor,
            time_s=anchor/200, end_s=anchor/200, target_samples=[anchor], beat_count=1,
            templates=[], hr=row.get('hr'), rr_ms=p.get('rr_ms', row.get('rr_ms')),
            basis_version=basis, pattern_only=False, diagnosis_status='pending',
            local_candidate_id=c['id'], retained_settings=p['settings'], candidate_context=p,
            candidate_scope=s, evidence_only=True)
        index['events'].append(item); active_ids.append([item['event_id'],basis])
    if not active_ids:return index
    stamp=sha256(canonical(active_ids).encode()).hexdigest()[:16]
    index['basis_versions']['rr_candidate']=index['beat_version']+'-'+stamp
    index['data_version']+='-picks-'+stamp
    return index


class EvidenceCandidateMixin:
    def initialize_candidates(self):
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS evidence_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, kind TEXT NOT NULL,
                candidate_key TEXT NOT NULL, scope TEXT NOT NULL, payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active', UNIQUE(case_id,candidate_key))''')

    def list_candidates(self, case_id, db=None):
        if db is None:
            with self.connect() as connection: return self.list_candidates(case_id, connection)
        return [{**dict(r),'scope':json.loads(r['scope']),'payload':json.loads(r['payload'])}
                for r in db.execute('SELECT * FROM evidence_candidates WHERE case_id=? ORDER BY id',(case_id,))]

    def save_candidate(self, case_id, candidate, actor, guard):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE'); guard(db)
            old=db.execute('SELECT * FROM evidence_candidates WHERE case_id=? AND candidate_key=?',
                           (case_id,candidate['candidate_key'])).fetchone()
            if old:
                if old['status'] != 'active':
                    db.execute("UPDATE evidence_candidates SET status='active' WHERE id=?",(old['id'],))
                    self._audit(db,actor,'evidence_candidate.restore',case_id,str(old['id']))
                result=next(r for r in self.list_candidates(case_id,db) if r['id']==old['id'])
            else:
                cursor=db.execute('INSERT INTO evidence_candidates(case_id,kind,candidate_key,scope,payload) VALUES(?,?,?,?,?)',
                    (case_id,candidate['kind'],candidate['candidate_key'],canonical(candidate['scope']),canonical(candidate['payload'])))
                self._audit(db,actor,'evidence_candidate.create',case_id,str(cursor.lastrowid))
                result=next(r for r in self.list_candidates(case_id,db) if r['id']==cursor.lastrowid)
            guard(db)
            return result

    def set_candidate_status(self, case_id, identifier, status, actor, guard):
        if type(identifier) is not int or status not in ('active','withdrawn'): raise ValueError('候选操作无效')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE'); guard(db)
            row=db.execute('SELECT * FROM evidence_candidates WHERE case_id=? AND id=?',(case_id,identifier)).fetchone()
            if not row: raise ValueError('候选不存在于当前病例')
            if row['status']!=status:
                db.execute('UPDATE evidence_candidates SET status=? WHERE id=?',(status,identifier))
                self._audit(db,actor,'evidence_candidate.'+status,case_id,str(identifier))
            guard(db)
            return next(r for r in self.list_candidates(case_id,db) if r['id']==identifier)
