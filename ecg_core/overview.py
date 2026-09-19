"""Overview measurements and reversible rhythm-episode review (not a diagnosis)."""
from __future__ import annotations

import copy
import json
import math
import mmap
from array import array
from datetime import datetime, timezone

from .waveform import ALL_LEADS


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
    return [dict(id="af:"+x["id"], sample_index=round(x["start_s"]*200), lead="全部", category="note",
                 label=("房颤" if x["kind"] == "AF" else "房扑")+" · "+{"confirmed": "医生确认", "excluded": "已排除", "pending": "待复核"}[x["status"]],
                 note=x.get("note", ""), created_by=actor, created_at=stamp,
                 details=dict(kind=x["kind"], status=x["status"], end_sample=max(round(x["start_s"]*200), math.ceil(x["end_s"]*200)-1), finding="房颤/房扑片段复核"))
            for x in document.get("episodes", [])]


class RhythmReviewStore:
    def __init__(self, storage):
        self.storage = storage
        with storage.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS rhythm_reviews
                (case_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, document TEXT NOT NULL,
                 undo TEXT NOT NULL, redo TEXT NOT NULL, updated_at TEXT NOT NULL)""")

    def read(self, case_id, initial=None, db=None):
        if db is None:
            with self.storage.connect() as connection:
                return self.read(case_id, initial, connection)
        row = db.execute("SELECT * FROM rhythm_reviews WHERE case_id=?", (case_id,)).fetchone()
        if not row:
            return dict(revision=0, document=copy.deepcopy(initial or {"episodes": [], "bookmarks": {}}), undo=[], redo=[], updated_at="")
        return dict(revision=row["revision"], document=json.loads(row["document"]), undo=json.loads(row["undo"]), redo=json.loads(row["redo"]), updated_at=row["updated_at"])

    @staticmethod
    def public(value):
        return {key: value[key] for key in ("revision", "document", "updated_at")} | dict(can_undo=bool(value["undo"]), can_redo=bool(value["redo"]))

    def commit(self, case_id, payload, duration, initial, actor, beat_revision):
        if payload.get("confirmed") is not True:
            raise ValueError("请核对修改并确认保存")
        if type(payload.get("revision")) is not int or type(payload.get("beat_revision")) is not int:
            raise ValueError("缺少复核版本")
        with self.storage.connect() as db:
            db.execute("BEGIN IMMEDIATE")
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
            value["updated_at"] = datetime.now(timezone.utc).isoformat()
            db.execute("""INSERT INTO rhythm_reviews VALUES(?,?,?,?,?,?) ON CONFLICT(case_id) DO UPDATE SET
                revision=excluded.revision, document=excluded.document, undo=excluded.undo, redo=excluded.redo, updated_at=excluded.updated_at""",
                (case_id, value["revision"], json.dumps(value["document"], ensure_ascii=False), json.dumps(value["undo"]), json.dumps(value["redo"]), value["updated_at"]))
            self.storage.invalidate_review(db, case_id, "annotation.rhythm_review")
            db.execute("INSERT INTO audit_log(case_id,actor,action,detail,created_at) VALUES(?,?,?,?,?)",
                       (case_id, actor, "annotation.rhythm_"+action, "revision="+str(value["revision"]), value["updated_at"]))
        return self.public(value)


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


def density(path, samples, lead="II", gate=None):
    """Count ALL selected, complete 2 s R-aligned beats; no representative sampling.

    Time bins are 10 ms, amplitude bins 1/128 of a symmetric robust scale.
    Only a pre-QRS constant baseline is subtracted; no per-beat gain normalization.
    """
    if lead not in ALL_LEADS:
        raise ValueError("不支持的密度图导联")
    width, height, pre = 200, 128, 200
    count = path.stat().st_size//16
    positions = [s for s in samples if pre <= s < count-pre]
    channel = {"I": 0, "II": 1, "V1": 2, "V2": 3, "V3": 4, "V4": 5, "V5": 6, "V6": 7}.get(lead)
    with path.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as raw:
        import struct
        read = struct.Struct("<h").unpack_from
        def value(s):
            if channel is not None:
                return read(raw, s*16+channel*2)[0]
            a, b = read(raw, s*16)[0], read(raw, s*16+2)[0]
            return {"III": b-a, "aVR": -(a+b)/2, "aVL": a-b/2, "aVF": b-a/2}[lead]
        def baseline(s):
            return sum(value(s+i) for i in range(-40, -20, 2))/10
        # Bounded deterministic scale estimate only; EVERY beat contributes to counts.
        magnitudes = []
        for s in positions[::max(1, math.ceil(len(positions)/1000))]:
            zero = baseline(s)
            magnitudes.extend(abs(value(s+i)-zero) for i in range(-pre, pre, 8))
        magnitudes.sort()
        limit = max(100, magnitudes[min(len(magnitudes)-1, int(len(magnitudes)*.995))]*1.15 if magnitudes else 100)
        bins, selected, clipped = array("I", [0])*(width*height), [], 0
        for s in positions:
            zero, matched = baseline(s), False
            for x, offset in enumerate(range(-pre, pre, 2)):
                amplitude = value(s+offset)-zero
                y = math.floor((limit-amplitude)/(2*limit)*height)
                if y < 0 or y >= height:
                    clipped += 1
                    continue
                bins[y*width+x] += 1
                if gate and gate[0] <= offset/200 <= gate[1] and gate[2] <= amplitude <= gate[3]:
                    matched = True
            if matched:
                selected.append(s)
    return dict(width=width, height=height, bins=list(bins), total=len(samples), included=len(positions),
                skipped_edges=len(samples)-len(positions), clipped_points=clipped, lead=lead,
                x_min_s=-1, x_max_s=1, amplitude_limit=round(limit, 3), units="设备原始标度 µV（未溯源）",
                sample_indices=selected, method="R 对齐 · 全集合计数 · 10 ms 栅格 · 去固定基线 · 无逐搏增益归一化")
