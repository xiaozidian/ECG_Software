"""Reattach saved manual report figures to verified samples; never confirm them."""
from collections import defaultdict
from contextlib import closing
from hashlib import sha256
import json

from flask import abort, jsonify, request

from .analysis_provenance import digest
from .beat_editor import BeatEditorStore, EditedRecords
from .ebi import load_records
from .report_evidence import check_read_wave
from .report_layout import prepare_strip
from .repository import CaseNotFound
from .review_candidates import augment_index, canonical, prepare_candidate
from .review_workflow import ReportConflict, stamp
from .source_identity import SourceReadError, SourceUnavailable
from .waveform import read_event_waveform


# Historical builds predate the source ledger. A build ID alone never proves
# continuity: the reconstructed digest must also bind ALL current source bytes.
LEGACY_ENGINES = (
    'ddedb32153b68436664ceb135055823a24cd9131686538a0eee73b471bd47315',
    '34a24a55948e68183b8da985b0cd4004cc8915503dc5c558c64dc59e05297acf',
    '50be40e4486813ce0426c1f2634afd581e83023d1f4dc91c179e46f81d5d805f',
)


def candidate_version(candidate):
    fingerprint = sha256(canonical([candidate['scope'], candidate['payload']]).encode()).hexdigest()
    return 'local-pick-v1:' + fingerprint[:24]


def source_matches(old_digest, current, historical):
    fields = ('schema', 'engine_id', 'inputs', 'recovery_epoch')
    if historical:
        old = {k: historical[k] for k in fields if k in historical}
        if digest(old) != old_digest:
            raise ValueError('旧图条的来源校验记录不完整。')
        if old.get('recovery_epoch') != current.get('recovery_epoch'):
            raise ValueError('工作区已从其他备份恢复，无法核实原选图来源。')
        if old['inputs'] != current['inputs']:
            raise ValueError('原始波形、逐搏记录或病例源文件已更换。')
        return
    for engine in LEGACY_ENGINES:
        old = {k: current[k] for k in fields if k in current}
        old['engine_id'] = engine
        if digest(old) == old_digest:
            return
    raise ValueError('缺少与当前源文件相符的旧版本校验记录，无法证明是同一次采集。')


def restore_candidate(index, identity, old, entries, reader):
    payload = old['payload']
    old_version = candidate_version(old)
    if any(entry['basis_version'] != old_version for entry in entries):
        raise ValueError('草稿保存的图条版本与原候选不一致。')
    args = dict(kind=old['kind'], settings=payload['settings'], caption=payload['caption'])
    if old['kind'] == 'rr':
        args.update(sample_index=payload['rr_end_sample'], rr_ms=payload['rr_ms'],
                    population=payload.get('population'))
        fields = ('rr_start_id', 'rr_end_id', 'rr_start_sample', 'rr_end_sample', 'rr_ms')
        problem = '原相邻两搏的位置、身份或 RR 间期已改变。'
    elif old['kind'] == 'strip':
        args['settings'] = {**payload['settings'], 'range_start_s': payload['start_s'],
                            'range_end_s': payload['end_s']}
        fields = ('start_sample', 'end_sample')
        problem = '原选区的起止采样位置已改变。'
    else:
        raise ValueError('此候选没有记录可恢复的人工选图类型。')
    fresh = prepare_candidate(index, identity, args)
    if any(fresh['payload'][k] != payload[k] for k in fields):
        raise ValueError(problem)
    fresh.update(id=old['id'], status='active')
    fresh['payload']['restored_from'] = old_version
    events = {**index, 'events': [], 'beat_version': '', 'data_version': '', 'basis_versions': {}}
    augment_index(events, [fresh], identity)
    if len(events['events']) != 1:
        raise ValueError(problem)
    event = events['events'][0]
    for entry in entries:
        checked = prepare_strip(index, event, entry, reader)
        check_read_wave(checked)
        wave = checked['waveform']
        spec = checked['strip']
        frames = round((spec['end_s'] - spec['start_s']) * wave['sample_rate_hz'])
        expected = len(range(0, frames, wave['stride']))
        if set(wave['leads']) != set(entry['leads']) or any(len(a) != expected for a in wave['leads'].values()):
            raise ValueError('原选区内的波形采样或所选导联不完整。')
    return fresh, event['basis_version']


class ReportStripRecovery:
    def __init__(self, app):
        self.store = app.extensions['storage']
        self.runtime = app.extensions['analysis_runtime']
        self.cases = app.extensions['case_repository']
        self.editor = BeatEditorStore(self.store)
        with closing(self.store.connect()) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS report_strip_sources
                (case_id TEXT NOT NULL, basis_id TEXT NOT NULL, proof TEXT NOT NULL,
                 PRIMARY KEY(case_id,basis_id))''')
            # Capture provenance in the same transaction that sets or replaces it.
            for change in ('INSERT', 'UPDATE'):
                versions = ('NEW',) if change == 'INSERT' else ('OLD', 'NEW')
                body = ' '.join(f"""INSERT OR IGNORE INTO report_strip_sources
                    SELECT {v}.case_id,json_extract({v}.basis,'$.digest'),{v}.basis
                    WHERE json_extract({v}.basis,'$.digest') IS NOT NULL;""" for v in versions)
                db.execute(f'CREATE TRIGGER IF NOT EXISTS report_strip_source_{change} AFTER {change} ON case_analysis_basis BEGIN {body} END')
            db.execute("""INSERT OR IGNORE INTO report_strip_sources
                SELECT case_id,json_extract(basis,'$.digest'),basis FROM case_analysis_basis
                WHERE json_extract(basis,'$.digest') IS NOT NULL""")
            db.execute("""INSERT OR IGNORE INTO report_strip_sources
                SELECT case_id,json_extract(analysis_provenance,'$.basis.digest'),json_extract(analysis_provenance,'$.basis')
                FROM report_drafts WHERE json_valid(analysis_provenance)
                AND json_extract(analysis_provenance,'$.basis.digest') IS NOT NULL""")

    def reconcile(self, case_id, expected):
        case = self.cases.get_case(case_id)
        basis = self.runtime.basis(case)
        with closing(self.store.connect()) as db:
            db.execute('BEGIN')
            row = db.execute('SELECT * FROM report_drafts WHERE case_id=?', (case_id,)).fetchone()
            if not row:
                raise ReportConflict('未找到保存过的报告草稿。')
            edit = self.editor.snapshot(case_id, db=db)
            identity = dict(case_id=case_id, analysis_basis=basis['digest'],
                            analysis_revision=self.store._review(db, case_id)['revision'], beat_revision=edit['revision'])
            if any(expected.get(k) != v for k, v in {**identity, 'report_version': row['version']}.items()):
                raise ReportConflict('报告或心搏记录已变化，请重新打开报告。')
            candidates = {f"local-pick:{c['id']}": c for c in self.store.list_candidates(case_id, db)}
            historical = {r['basis_id']: json.loads(r['proof']) for r in
                          db.execute('SELECT basis_id,proof FROM report_strip_sources WHERE case_id=?', (case_id,))}
        comp = json.loads(row['composition'])
        selections = defaultdict(list)
        for entry in comp.get('selected_events', []):
            if entry['event_id'].startswith('local-pick:'):
                selections[entry['event_id']].append(entry)
        changed, issues = {}, {}
        missing = set(expected.get('missing_event_ids', []))
        index = None
        for event_id, entries in selections.items():
            old = candidates.get(event_id)
            if not old or old['status'] != 'active':
                issues[event_id] = '原候选已撤销。' if old else '找不到这张图的原候选记录。'
                continue
            scope = old['scope']
            if scope.get('case_id') != case_id:
                issues[event_id] = '原候选与当前病例不一致。'
                continue
            if all(scope.get(k) == identity[k] for k in ('analysis_basis', 'beat_revision')):
                if any(e['basis_version'] != candidate_version(old) for e in entries):
                    issues[event_id] = '草稿保存的图条版本与原候选不一致。'
                elif event_id in missing:
                    issues[event_id] = ('当前逐搏记录中找不到原来这对有效的相邻心搏。' if old['kind'] == 'rr'
                                        else '当前逐搏记录中找不到原选区保存的定位心搏。')
                continue
            if row['status'] not in ('draft', 'returned'):
                issues[event_id] = '该版本已经审核，请先建立更正草稿。'
                continue
            try:
                source_matches(scope['analysis_basis'], basis, historical.get(scope['analysis_basis']))
                if index is None:
                    feed = EditedRecords(load_records(case['paths']['ebi']), edit['document'],
                                         self.store.list_beat_overrides(case_id), case['technical']['duration_seconds_raw'])
                    index = dict(rows=feed.beats + feed.markers, duration_s=feed.duration)
                def reader(a, b, leads, points):
                    return read_event_waveform(case['paths']['data'], a, b, leads, points)
                changed[event_id] = restore_candidate(index, identity, old, entries, reader)
            except (ValueError, ReportConflict, SourceUnavailable, SourceReadError) as error:
                issues[event_id] = str(error)
            except (KeyError, TypeError, IndexError):
                issues[event_id] = '旧记录缺少完整的心搏、起止时间或导联设置。'
        if self.runtime.basis(case)['digest'] != identity['analysis_basis']:
            raise ReportConflict('核对过程中源文件发生变化，请重新读取。')
        if changed:
            self._commit(case, identity, row, comp, selections, candidates, changed)
        return dict(restored=list(changed), reasons=issues, report_version=row['version'] + bool(changed))

    def _commit(self, case, identity, row, comp, selections, previous, changed):
        case_id = identity['case_id']
        with closing(self.store.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT version,status FROM report_drafts WHERE case_id=?', (case_id,)).fetchone()
            stored = db.execute('SELECT basis FROM case_analysis_basis WHERE case_id=?', (case_id,)).fetchone()
            if (not current or tuple(current) != (row['version'], row['status']) or not stored
                    or json.loads(stored['basis'])['digest'] != identity['analysis_basis']
                    or self.editor.snapshot(case_id, db=db)['revision'] != identity['beat_revision']
                    or self.store._review(db, case_id)['revision'] != identity['analysis_revision']):
                raise ReportConflict('核对期间草稿或病例已变化，原选图保留。')
            candidates = {c['id']: c for c in self.store.list_candidates(case_id, db)}
            for event_id, (fresh, version) in changed.items():
                cid = fresh['id']
                if candidates.get(cid) != previous[event_id]:
                    raise ReportConflict('来源候选刚被修改，请重新读取。')
                key = fresh['candidate_key']
                if db.execute('SELECT 1 FROM evidence_candidates WHERE case_id=? AND candidate_key=? AND id<>?',
                              (case_id, key, cid)).fetchone():
                    # Keep independently curated cards and their original IDs.
                    key = digest(['restored-report-strip', cid, key])
                db.execute('UPDATE evidence_candidates SET scope=?,payload=?,candidate_key=? WHERE case_id=? AND id=?',
                           (canonical(fresh['scope']), canonical(fresh['payload']), key, case_id, cid))
                for entry in selections[event_id]:
                    entry['basis_version'] = version
                self.store._audit(db, '图条原位核验', 'report.strip_relinked', case_id, canonical({
                    'candidate': previous[event_id], 'new_basis': identity['analysis_basis'], 'new_version': version}))
            # This housekeeping does not attribute the rest of the draft to a new
            # analysis, change the conclusion, or acknowledge a clinical finding.
            provenance = json.loads(row['analysis_provenance'] or '{}')
            if provenance.get('basis'):
                from .storage import normalize_report_composition
                provenance['composition_sha256'] = digest(normalize_report_composition(comp))
            db.execute('UPDATE report_drafts SET composition=?,analysis_provenance=?,version=version+1,updated_at=? WHERE case_id=?',
                       (json.dumps(comp, ensure_ascii=False), json.dumps(provenance, ensure_ascii=False), stamp(), case_id))
            if self.runtime.basis(case)['digest'] != identity['analysis_basis']:
                raise ReportConflict('核对期间源文件发生变化，原选图保留。')


def install_recovery(app):
    recovery = ReportStripRecovery(app)

    @app.post('/api/cases/<case_id>/report-strip-recovery')
    def recover_report_strips(case_id):
        expected = request.get_json(silent=True)
        if not isinstance(expected, dict) or any(type(expected.get(k)) is not int for k in
                                                  ('report_version', 'beat_revision', 'analysis_revision')):
            raise ValueError('恢复图条需要当前草稿和逐搏版本。')
        missing = expected.get('missing_event_ids', [])
        if not isinstance(missing, list) or not all(isinstance(i, str) for i in missing):
            raise ValueError('缺少有效的待核对图条编号。')
        try:
            return jsonify(recovery.reconcile(case_id, expected))
        except CaseNotFound:
            abort(404)
