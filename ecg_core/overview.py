"""Overview measurements and reversible rhythm-episode review (not a diagnosis)."""
from __future__ import annotations

import copy
import json
import math
import mmap
import uuid
from datetime import datetime, timezone

import numpy as np

from .waveform import ALL_LEADS
from .source_identity import require_waveform_file, source_read
from .review_workflow import ReportConflict


def validate_document(value, duration):
    if not isinstance(value, dict):
        raise ValueError("房颤复核文档格式错误")
    episodes = value.get("episodes", [])
    if not isinstance(episodes, list) or len(episodes) > 5000:
        raise ValueError("房颤片段须为数组，最多 5000 段")
    clean, ids = [], set()
    for item in episodes:
        if not isinstance(item, dict):
            raise ValueError("房颤片段格式错误")
        start, end = item.get("start_s"), item.get("end_s")
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in (start, end)):
            raise ValueError("片段边界必须为有限秒数")
        if not 0 <= start < end <= duration:
            raise ValueError("片段边界超出记录范围或结束早于起点")
        kind, status, key = item.get("kind"), item.get("status"), item.get("id")
        if kind not in ("AF", "AFL") or status not in ("pending", "confirmed", "excluded"):
            raise ValueError("片段类型或复核状态错误")
        if not isinstance(key, str) or not 0 < len(key) <= 100 or key in ids:
            raise ValueError("片段标识必须唯一")
        ids.add(key)
        clean.append(dict(id=key, start_s=round(start, 3), end_s=round(end, 3), kind=kind, status=status,
                          source=str(item.get("source", "manual"))[:80], note=str(item.get("note", ""))[:1000]))
    clean.sort(key=lambda x: (x["start_s"], x["end_s"], x["id"]))
    # Confirmed AF and AFL cannot both own the same time interval.
    confirmed = [x for x in clean if x["status"] == "confirmed"]
    for previous, current in zip(confirmed, confirmed[1:]):
        if current["start_s"] < previous["end_s"]:
            raise ValueError("已确认片段不能重叠，请先调整或移除重叠段")
    bookmarks = value.get("bookmarks", {})
    if not isinstance(bookmarks, dict):
        raise ValueError("心率书签格式错误")
    marks = {}
    for key, time in bookmarks.items():
        if key not in ("fastest", "slowest", "fastest_nn", "slowest_nn"):
            raise ValueError("不支持的心率书签")
        if isinstance(time, bool) or not isinstance(time, (int, float)) or not math.isfinite(time) or not 0 <= time < duration:
            raise ValueError("心率书签时间超出记录")
        marks[key] = round(time, 3)
    return dict(episodes=clean, bookmarks=marks)


def episode_annotations(document, actor="房颤复核", stamp=""):
    # Validated episode times have millisecond precision. Convert via integer
    # milliseconds: ceil(10.005 * 200) can spuriously include one extra sample.
    return [dict(id="af:"+x["id"], sample_index=round(x["start_s"]*200), lead="全部", category="note",
                 label=("房颤" if x["kind"] == "AF" else "房扑")+" · "+{"confirmed": "医生确认", "excluded": "已排除", "pending": "待复核"}[x["status"]],
                 note=x.get("note", ""), created_by=actor, created_at=stamp,
                 details=dict(kind=x["kind"], status=x["status"], end_sample=max(round(x["start_s"]*200), (round(x["end_s"]*1000)+4)//5-1), finding="房颤/房扑片段复核"))
            for x in document.get("episodes", [])]


class RhythmReviewStore:
    def __init__(self, storage):
        self.storage = storage
        with storage.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS rhythm_reviews
                (case_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, document TEXT NOT NULL,
                 undo TEXT NOT NULL, redo TEXT NOT NULL, updated_at TEXT NOT NULL,
                 last_operation TEXT NOT NULL DEFAULT '{}')""")
            if 'last_operation' not in {row['name'] for row in db.execute('PRAGMA table_info(rhythm_reviews)')}:
                db.execute("ALTER TABLE rhythm_reviews ADD COLUMN last_operation TEXT NOT NULL DEFAULT '{}'")

    def read(self, case_id, initial=None, db=None):
        if db is None:
            with self.storage.connect() as connection:
                return self.read(case_id, initial, connection)
        row = db.execute("SELECT * FROM rhythm_reviews WHERE case_id=?", (case_id,)).fetchone()
        if not row:
            return dict(revision=0, document=copy.deepcopy(initial or {"episodes": [], "bookmarks": {}}), undo=[], redo=[], updated_at="", last_operation={})
        return dict(revision=row["revision"], document=json.loads(row["document"]), undo=json.loads(row["undo"]), redo=json.loads(row["redo"]), updated_at=row["updated_at"], last_operation=json.loads(row['last_operation']))

    @staticmethod
    def public(value):
        return {key: value[key] for key in ("revision", "document", "updated_at", "last_operation")} | dict(can_undo=bool(value["undo"]), can_redo=bool(value["redo"]))

    def _remove_retired_report_picks(self, db, case_id, before, after, actor, event_aliases):
        """Withdraw deleted/excluded episode figures in the same write transaction.

        Undo restores rhythm evidence, never the doctor's previous report picks.
        Event aliases cover pre-review source IDs as well as saved episode IDs.
        """
        current = {x['id']: x for x in after['episodes']}
        retired = {x['id'] for x in before['episodes'] if x['id'] not in current}
        retired.update(key for key, x in current.items() if x['status'] == 'excluded')
        if not retired:
            return []
        withdrawn = set()
        for key in retired:
            withdrawn.add('annotation:af:'+key)
            if key.startswith('source-'):
                withdrawn.add('annotation:'+key[7:])
            withdrawn.update((event_aliases or {}).get(key, ()))
        row = db.execute('SELECT composition,analysis_provenance FROM report_drafts WHERE case_id=?', (case_id,)).fetchone()
        if not row:
            return []
        composition = json.loads(row['composition'] or '{}')
        selected = composition.get('selected_events', [])
        removed = [x['event_id'] for x in selected if x['event_id'] in withdrawn]
        if not removed:
            return []
        composition['selected_events'] = [x for x in selected if x['event_id'] not in withdrawn]
        composition.get('category_reviews', {}).pop('AF', None)
        # Explicit prose is retained for physician reconciliation. Automatically
        # composed AF paragraphs no longer have withdrawn figures as support.
        blocks = []
        for block in composition.get('diagnosis_blocks', []):
            if str(block.get('key', '')).startswith('AF:') and not block.get('manual'):
                continue
            blocks.append(block)
        composition['diagnosis_blocks'] = blocks
        from .analysis_provenance import digest
        provenance = json.loads(row['analysis_provenance'] or '{}')
        if provenance:
            provenance['composition_sha256'] = digest(composition)
        # invalidate_review has already advanced the report version and reset
        # approval. Do not advance it a second time for this same atomic write.
        db.execute('UPDATE report_drafts SET composition=?,analysis_provenance=? WHERE case_id=?',
                   (json.dumps(composition, ensure_ascii=False), json.dumps(provenance, ensure_ascii=False), case_id))
        self.storage._audit(db, actor, 'rhythm_report.unselect', case_id, json.dumps(removed))
        return removed

    def commit(self, case_id, payload, duration, initial, actor, beat_revision, *, analysis_revision=None, event_aliases=None):
        if payload.get("confirmed") is not True:
            raise ValueError("请核对修改并确认保存")
        if type(payload.get("revision")) is not int or type(payload.get("beat_revision")) is not int:
            raise ValueError("缺少复核版本")
        request_id = payload.get('request_id')
        if request_id is not None:
            try:
                if not isinstance(request_id, str) or str(uuid.UUID(request_id)) != request_id:
                    raise ValueError()
            except (ValueError, AttributeError):
                raise ValueError('保存请求编号无效') from None
        with self.storage.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            # Legacy overrides/annotations can change evidence without changing
            # the beat-editor revision. Check the broader review under the lock.
            if analysis_revision is not None and self.storage._review(db, case_id)['revision'] != analysis_revision:
                raise ReportConflict("病例依据已变化，未保存片段；请重新加载后核对")
            value = self.read(case_id, initial, db)
            row = db.execute("SELECT revision FROM beat_edit_documents WHERE case_id=?", (case_id,)).fetchone()
            current_beat = row[0] if row else 0
            if value["revision"] != payload["revision"] or current_beat != payload["beat_revision"] or current_beat != beat_revision:
                raise ValueError("病例修订版本已变化，请重新加载后核对")
            action = payload.get("operation", "save")
            before = copy.deepcopy(value["document"])
            if action in ("undo", "redo"):
                if not value[action]:
                    raise ValueError("没有可撤销/重做的房颤复核")
                value["redo" if action == "undo" else "undo"].append(before)
                value["document"] = value[action].pop()
            elif action == "save":
                value["document"] = validate_document(payload.get("document"), duration)
                value["undo"] = (value["undo"]+[before])[-20:]
                value["redo"] = []
            else:
                raise ValueError("不支持的房颤复核操作")
            value["revision"] += 1
            value['last_operation'] = dict(request_id=request_id, operation=action, revision=value['revision']) if request_id else {}
            value["updated_at"] = datetime.now(timezone.utc).isoformat()
            db.execute("""INSERT INTO rhythm_reviews(case_id,revision,document,undo,redo,updated_at,last_operation)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(case_id) DO UPDATE SET
                revision=excluded.revision, document=excluded.document, undo=excluded.undo, redo=excluded.redo,
                updated_at=excluded.updated_at,last_operation=excluded.last_operation""",
                (case_id, value["revision"], json.dumps(value["document"], ensure_ascii=False), json.dumps(value["undo"]), json.dumps(value["redo"]), value["updated_at"], json.dumps(value['last_operation'])))
            self.storage.invalidate_review(db, case_id, "annotation.rhythm_review")
            removed = self._remove_retired_report_picks(db, case_id, before, value['document'], actor, event_aliases)
            db.execute("INSERT INTO audit_log(case_id,actor,action,detail,created_at) VALUES(?,?,?,?,?)",
                       (case_id, actor, "annotation.rhythm_"+action, "revision="+str(value["revision"]), value["updated_at"]))
        return {**self.public(value), 'removed_report_events': removed}


def initial_episodes(feed, annotations, duration):
    items = []
    for x in annotations:
        detail = x.get("details", {})
        if detail.get("kind") in ("AF", "AFL"):
            start, end = x["sample_index"]/200, min(duration, (detail.get("end_sample", x["sample_index"])+1)/200)
            if end > start:
                items.append(dict(id="source-"+str(x["id"]), start_s=start, end_s=end, kind=detail["kind"], status=detail.get("status", "pending"), source="source-annotation", note=x.get("note", "")))
    run = None
    for beat in feed.beats + [dict(class_code="", time_s=duration)]:
        kind = "AF" if beat["class_code"] in ("A", "M") else "AFL" if beat["class_code"] in ("C", "H") else None
        if run and kind != run["kind"]:
            run["end_s"] = min(duration, beat["time_s"])
            if run["end_s"] > run["start_s"]:
                items.append(run)
            run = None
        if kind and run is None:
            run = dict(id="beat-"+str(beat["sample_index"]), start_s=beat["time_s"], end_s=beat["time_s"], kind=kind, status="pending", source="beat-rhythm", note="逐搏节律标记，须核对片段边界")
    return dict(episodes=items, bookmarks={})


def density_samples(source, payload):
    """Apply explicit group membership without silently accepting stale beats."""
    allowed = set(source)
    def checked(name):
        values = payload.get(name, [])
        if not isinstance(values, list) or len(values) > 250000 or any(type(s) is not int or s not in allowed for s in values):
            raise ValueError("密度图分组包含无效或已变化的心搏，请重新加载")
        if len(set(values)) != len(values):
            raise ValueError("密度图分组心搏不能重复")
        return set(values)
    included = checked('samples') if 'samples' in payload else allowed
    excluded = checked('exclude_samples')
    return [s for s in source if s in included and s not in excluded]


@source_read
def density(path, samples, lead="II", gate=None, amplitude_limit=None):
    """Count ALL selected, complete 2 s R-aligned beats; no representative sampling.

    Time bins are 10 ms, amplitude bins 1/128 of a symmetric robust scale.
    Only a pre-QRS constant baseline is subtracted; no per-beat gain normalization.
    """
    info = require_waveform_file(path)
    if lead not in ALL_LEADS:
        raise ValueError("不支持的密度图导联")
    if amplitude_limit is not None and (isinstance(amplitude_limit, bool) or not isinstance(amplitude_limit, (int, float)) or not math.isfinite(amplitude_limit) or not 1 <= amplitude_limit <= 1e7):
        raise ValueError("密度图幅度范围错误")
    width, height, pre = 200, 128, 200
    count = info.st_size//16
    positions = [s for s in samples if pre <= s < count-pre]
    channel = {"I": 0, "II": 1, "V1": 2, "V2": 3, "V3": 4, "V4": 5, "V5": 6, "V6": 7}.get(lead)
    # Bounded chunks keep memory independent of recording length. The mmap is
    # read-only and little-endian on both macOS and Windows. Every beat and every
    # original 10 ms bin still contributes; this is not representative sampling.
    bins, selected, clipped = np.zeros(width*height, dtype=np.int64), [], 0
    limit = round(amplitude_limit if amplitude_limit is not None else 100, 3)
    if positions:
        with path.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as raw:
            values = np.frombuffer(raw, dtype="<i2", count=count*8).reshape(count, 8)
            def read(indices):
                if channel is not None:
                    return values[indices, channel].astype(np.float64)
                # Promote before subtracting/adding: derived leads may exceed int16.
                a, b = values[indices, 0].astype(np.float64), values[indices, 1].astype(np.float64)
                if lead == "III": return b-a
                if lead == "aVR": return -(a+b)/2
                if lead == "aVL": return a-b/2
                return b-a/2
            def baseline(anchors):
                return read(anchors[:, None]+np.arange(-40, -20, 2)).sum(axis=1)/10
            try:
                anchors = np.asarray(positions, dtype=np.int64)
                if amplitude_limit is None:
                    estimate = anchors[::max(1, math.ceil(len(positions)/1000))]
                    magnitudes = np.sort(np.abs(read(estimate[:, None]+np.arange(-pre, pre, 8))-baseline(estimate)[:, None]).ravel())
                    limit = round(max(100, float(magnitudes[int(len(magnitudes)*.995)])*1.15), 3)
                offsets = np.arange(-pre, pre, 2)
                columns = np.arange(width)
                gate_columns = (offsets/200 >= gate[0]) & (offsets/200 <= gate[1]) if gate else None
                for first in range(0, len(anchors), 2048):
                    chunk = anchors[first:first+2048]
                    amplitude = read(chunk[:, None]+offsets)-baseline(chunk)[:, None]
                    y = np.floor((limit-amplitude)/(2*limit)*height).astype(np.int64)
                    visible = (y >= 0) & (y < height)
                    clipped += int(visible.size-np.count_nonzero(visible))
                    bins += np.bincount((y*width+columns)[visible], minlength=width*height)
                    if gate:
                        matched = np.any(visible & gate_columns & (amplitude >= gate[2]) & (amplitude <= gate[3]), axis=1)
                        selected.extend(chunk[matched].tolist())
            finally:
                # Release exported buffer before closing the mapping (Windows too).
                del values
    return dict(width=width, height=height, bins=bins.tolist(), total=len(samples), included=len(positions),
                skipped_edges=len(samples)-len(positions), clipped_points=clipped, lead=lead,
                x_min_s=-1, x_max_s=1, amplitude_limit=round(limit, 3), units="device_unit", unit_label="设备单位", calibration_verified=False,
                sample_indices=selected, population_samples=list(samples), method="R 对齐 · 全集合计数 · 10 ms 栅格 · 去固定基线 · 无逐搏增益归一化")
