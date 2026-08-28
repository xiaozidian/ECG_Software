from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


BEAT_TEMPLATE_FAMILIES = {
    "全部",
    "单发",
    "成对",
    "房速",
    "二联律",
    "三联律(NPN)",
    "三联律(NPP)",
    "四联律",
    "自定义",
}
BEAT_TEMPLATE_LEADS = {"I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6"}
BEAT_OVERRIDE_CLASSES = {"N", "S", "V", "X", "P", "O"}
REPORT_PAGE_KEYS = {
    "cover", "summary", "hourly", "scatter", "st_trend", "t_trend", "event_strips",
    "st_events", "pacing", "af", "hrv_time", "hrv_frequency", "hrv_overview", "hrt",
    "qtd", "vcg", "dc", "twa", "vlp", "sap",
}
REPORT_TEMPLATES = {"comprehensive", "rhythm", "concise", "custom"}
REPORT_PREVIEW_MODES = {"compose", "event", "twelve"}
REPORT_FAST_SLOW_MODES = {"rr", "nn", "both"}
DEFAULT_REPORT_COMPOSITION = {
    "template": "comprehensive",
    "included_pages": ["cover", "summary", "hourly", "event_strips", "hrv_time", "hrv_overview"],
    "active_page": "summary",
    "preview_mode": "compose",
    "fast_slow_mode": "rr",
    "paper": {
        "size": "A4",
        "orientation": "portrait",
        "show_grid": True,
        "show_labels": True,
        "speed": "25 mm/s",
        "gain": "10 mm/mV",
    },
}


def normalize_report_composition(value: dict | None) -> dict:
    if value is None:
        return json.loads(json.dumps(DEFAULT_REPORT_COMPOSITION, ensure_ascii=False))
    if not isinstance(value, dict):
        raise ValueError("composition 必须为 JSON 对象")
    raw_pages = value.get("included_pages", DEFAULT_REPORT_COMPOSITION["included_pages"])
    if not isinstance(raw_pages, list) or any(not isinstance(item, str) for item in raw_pages):
        raise ValueError("included_pages 必须为页面标识列表")
    pages = [item for item in raw_pages if item in REPORT_PAGE_KEYS]
    pages = list(dict.fromkeys(pages))
    if not pages:
        pages = ["summary"]
    active_page = value.get("active_page", pages[0])
    if not isinstance(active_page, str) or active_page not in REPORT_PAGE_KEYS:
        raise ValueError("active_page 不受支持")
    if active_page not in pages:
        active_page = pages[0]
    template = value.get("template", "custom")
    preview_mode = value.get("preview_mode", "compose")
    fast_slow_mode = value.get("fast_slow_mode", "rr")
    if template not in REPORT_TEMPLATES:
        raise ValueError("template 不受支持")
    if preview_mode not in REPORT_PREVIEW_MODES:
        raise ValueError("preview_mode 不受支持")
    if fast_slow_mode not in REPORT_FAST_SLOW_MODES:
        raise ValueError("fast_slow_mode 不受支持")
    raw_paper = value.get("paper", {})
    if not isinstance(raw_paper, dict):
        raise ValueError("paper 必须为 JSON 对象")
    size = raw_paper.get("size", "A4")
    orientation = raw_paper.get("orientation", "portrait")
    if size not in {"A4", "A3"} or orientation not in {"portrait", "landscape"}:
        raise ValueError("paper 页面设置不受支持")
    speed = raw_paper.get("speed", "25 mm/s")
    gain = raw_paper.get("gain", "10 mm/mV")
    if speed not in {"12.5 mm/s", "25 mm/s", "50 mm/s"} or gain not in {"5 mm/mV", "10 mm/mV", "20 mm/mV"}:
        raise ValueError("paper 图条设置不受支持")
    return {
        "template": template,
        "included_pages": pages,
        "active_page": active_page,
        "preview_mode": preview_mode,
        "fast_slow_mode": fast_slow_mode,
        "paper": {
            "size": size,
            "orientation": orientation,
            "show_grid": bool(raw_paper.get("show_grid", True)),
            "show_labels": bool(raw_paper.get("show_labels", True)),
            "speed": speed,
            "gain": gain,
        },
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class Storage:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS annotations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id TEXT NOT NULL,
                    sample_index INTEGER NOT NULL,
                    lead TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT 'note',
                    label TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_annotation_case_sample
                    ON annotations(case_id, sample_index);
                CREATE TABLE IF NOT EXISTS report_drafts (
                    case_id TEXT PRIMARY KEY,
                    conclusion TEXT NOT NULL,
                    composition TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'draft',
                    version INTEGER NOT NULL DEFAULT 1,
                    reviewed_by TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS patient_overrides (
                    case_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS beat_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    rhythm_family TEXT NOT NULL DEFAULT '自定义',
                    lead TEXT NOT NULL DEFAULT 'II',
                    source_class TEXT NOT NULL DEFAULT '',
                    sample_indices TEXT NOT NULL,
                    start_sample INTEGER NOT NULL,
                    end_sample INTEGER NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_beat_template_case_updated
                    ON beat_templates(case_id, updated_at DESC, id DESC);
                CREATE TABLE IF NOT EXISTS beat_overrides (
                    case_id TEXT NOT NULL,
                    sample_index INTEGER NOT NULL,
                    source_group INTEGER NOT NULL,
                    class_code TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (case_id, sample_index)
                );
                CREATE INDEX IF NOT EXISTS idx_beat_override_case_updated
                    ON beat_overrides(case_id, updated_at DESC, sample_index);
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id TEXT NOT NULL DEFAULT '',
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                """
            )
            columns = {row[1] for row in db.execute("PRAGMA table_info(beat_templates)")}
            if "source_class" not in columns:
                db.execute("ALTER TABLE beat_templates ADD COLUMN source_class TEXT NOT NULL DEFAULT ''")
            report_columns = {row[1] for row in db.execute("PRAGMA table_info(report_drafts)")}
            if "composition" not in report_columns:
                db.execute("ALTER TABLE report_drafts ADD COLUMN composition TEXT NOT NULL DEFAULT '{}'")

    @staticmethod
    def _beat_template_row(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        item = dict(row)
        try:
            samples = json.loads(item.pop("sample_indices"))
        except (TypeError, ValueError, json.JSONDecodeError):
            samples = []
        item["sample_indices"] = [int(value) for value in samples if isinstance(value, int) and not isinstance(value, bool)]
        item["beat_count"] = len(item["sample_indices"])
        return item

    def list_beat_templates(self, case_id: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM beat_templates WHERE case_id=? ORDER BY updated_at DESC,id DESC",
                (case_id,),
            ).fetchall()
        return [self._beat_template_row(row) for row in rows]

    def get_beat_template(self, template_id: int) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM beat_templates WHERE id=?", (template_id,)).fetchone()
        return self._beat_template_row(row)

    def create_beat_template(self, case_id: str, payload: dict, actor: str) -> dict:
        if not isinstance(payload, dict):
            raise ValueError("模板类别必须为 JSON 对象")
        name = payload.get("name", "")
        rhythm_family = payload.get("rhythm_family", "自定义")
        lead = payload.get("lead", "II")
        source_class = payload.get("source_class", "")
        note = payload.get("note", "")
        raw_samples = payload.get("sample_indices")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("模板名称不能为空")
        if not isinstance(rhythm_family, str) or rhythm_family not in BEAT_TEMPLATE_FAMILIES:
            raise ValueError("模板家族不是支持的类别")
        if not isinstance(lead, str) or lead not in BEAT_TEMPLATE_LEADS:
            raise ValueError("模板导联不是支持的导联")
        if not isinstance(source_class, str) or (
            source_class and not source_class.startswith("source-") and not source_class.startswith("custom-")
        ):
            raise ValueError("父类别标识不合法")
        if not isinstance(note, str):
            raise ValueError("模板备注必须为文本")
        if not isinstance(raw_samples, list) or not raw_samples:
            raise ValueError("sample_indices 必须是非空数组")
        if len(raw_samples) > 500:
            raise ValueError("单个模板类别最多保存 500 个心搏")
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in raw_samples):
            raise ValueError("sample_indices 必须全部为非负整数")
        samples = sorted(set(raw_samples))
        if len(samples) != len(raw_samples):
            raise ValueError("sample_indices 不能重复")
        now = utc_now()
        values = (
            case_id,
            name.strip()[:80],
            rhythm_family,
            lead,
            source_class,
            json.dumps(samples, ensure_ascii=False, separators=(",", ":")),
            samples[0],
            samples[-1],
            note.strip()[:1200],
            actor,
            now,
            now,
        )
        with self.connect() as db:
            cursor = db.execute(
                """INSERT INTO beat_templates
                (case_id,name,rhythm_family,lead,source_class,sample_indices,start_sample,end_sample,note,created_by,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                values,
            )
            row = db.execute("SELECT * FROM beat_templates WHERE id=?", (cursor.lastrowid,)).fetchone()
        item = self._beat_template_row(row)
        self.audit(actor, "beat_template.create", case_id, f"#{item['id']} {item['name']} beats={item['beat_count']}")
        return item

    def update_beat_template(self, template_id: int, payload: dict, actor: str) -> dict | None:
        if not isinstance(payload, dict):
            raise ValueError("模板类别必须为 JSON 对象")
        existing = self.get_beat_template(template_id)
        if existing is None:
            return None
        allowed = {"name", "rhythm_family", "note"}
        if not payload.keys() <= allowed:
            raise ValueError("只能修改模板名称、家族和备注")
        name = payload.get("name", existing["name"])
        rhythm_family = payload.get("rhythm_family", existing["rhythm_family"])
        note = payload.get("note", existing["note"])
        if not isinstance(name, str) or not name.strip():
            raise ValueError("模板名称不能为空")
        if not isinstance(rhythm_family, str) or rhythm_family not in BEAT_TEMPLATE_FAMILIES:
            raise ValueError("模板家族不是支持的类别")
        if not isinstance(note, str):
            raise ValueError("模板备注必须为文本")
        with self.connect() as db:
            db.execute(
                "UPDATE beat_templates SET name=?,rhythm_family=?,note=?,updated_at=? WHERE id=?",
                (name.strip()[:80], rhythm_family, note.strip()[:1200], utc_now(), template_id),
            )
            row = db.execute("SELECT * FROM beat_templates WHERE id=?", (template_id,)).fetchone()
        item = self._beat_template_row(row)
        self.audit(actor, "beat_template.update", item["case_id"], f"#{template_id} {item['name']}")
        return item

    def delete_beat_template(self, template_id: int, actor: str) -> dict | None:
        existing = self.get_beat_template(template_id)
        if existing is None:
            return None
        with self.connect() as db:
            db.execute("DELETE FROM beat_templates WHERE id=?", (template_id,))
        self.audit(actor, "beat_template.delete", existing["case_id"], f"#{template_id} {existing['name']}")
        return existing

    def list_beat_overrides(self, case_id: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM beat_overrides WHERE case_id=? ORDER BY sample_index", (case_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def set_beat_overrides(self, case_id: str, beats: list[dict], class_code: str, actor: str) -> list[dict]:
        if class_code not in BEAT_OVERRIDE_CLASSES:
            raise ValueError("人工心搏类型必须是 N、S、V、X、P 或 O")
        if not beats or len(beats) > 500:
            raise ValueError("每次必须修改 1–500 个心搏")
        samples = [item["sample_index"] for item in beats]
        if len(samples) != len(set(samples)):
            raise ValueError("sample_indices 不能重复")
        now = utc_now()
        with self.connect() as db:
            db.executemany(
                """INSERT INTO beat_overrides
                (case_id,sample_index,source_group,class_code,created_by,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(case_id,sample_index) DO UPDATE SET
                  source_group=excluded.source_group,
                  class_code=excluded.class_code,
                  updated_at=excluded.updated_at""",
                [
                    (case_id, item["sample_index"], item["group"], class_code, actor, now, now)
                    for item in beats
                ],
            )
            placeholders = ",".join("?" for _ in samples)
            rows = db.execute(
                f"SELECT * FROM beat_overrides WHERE case_id=? AND sample_index IN ({placeholders}) ORDER BY sample_index",
                (case_id, *samples),
            ).fetchall()
        self.audit(actor, "beat_override.reclassify", case_id, f"class={class_code} beats={len(samples)}")
        return [dict(row) for row in rows]

    def clear_beat_overrides(self, case_id: str, samples: list[int], actor: str) -> int:
        if not samples or len(samples) > 500:
            raise ValueError("每次必须恢复 1–500 个心搏")
        if len(samples) != len(set(samples)):
            raise ValueError("sample_indices 不能重复")
        placeholders = ",".join("?" for _ in samples)
        with self.connect() as db:
            cursor = db.execute(
                f"DELETE FROM beat_overrides WHERE case_id=? AND sample_index IN ({placeholders})",
                (case_id, *samples),
            )
            changed = cursor.rowcount
        self.audit(actor, "beat_override.restore", case_id, f"beats={changed}")
        return changed

    def audit(self, actor: str, action: str, case_id: str = "", detail: str = "") -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO audit_log(case_id,actor,action,detail,created_at) VALUES(?,?,?,?,?)",
                (case_id, actor, action, detail, utc_now()),
            )

    def list_audit(self, limit: int = 200) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (max(1, min(limit, 1000)),)
            ).fetchall()
        return [dict(row) for row in rows]

    def list_annotations(self, case_id: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM annotations WHERE case_id=? ORDER BY sample_index,id", (case_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def create_annotation(self, case_id: str, payload: dict, actor: str) -> dict:
        if not isinstance(payload, dict):
            raise ValueError("标注必须为 JSON 对象")
        sample_index = payload.get("sample_index", 0)
        if isinstance(sample_index, bool) or not isinstance(sample_index, int) or sample_index < 0:
            raise ValueError("sample_index 必须为非负整数")
        lead = payload.get("lead", "")
        category = payload.get("category", "note")
        label = payload.get("label", "人工标注")
        note = payload.get("note", "")
        if not isinstance(lead, str) or lead not in {"", "全部", "I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6"}:
            raise ValueError("lead 不是支持的导联")
        if not isinstance(category, str) or category not in {"note", "N", "S", "V", "noise"}:
            raise ValueError("category 不是支持的标注类别")
        if not isinstance(label, str) or not label.strip():
            raise ValueError("label 必须为非空文本")
        if not isinstance(note, str):
            raise ValueError("note 必须为文本")
        now = utc_now()
        values = (
            case_id,
            sample_index,
            lead[:16],
            category[:32],
            label.strip()[:120],
            note[:2000],
            actor,
            now,
            now,
        )
        with self.connect() as db:
            cursor = db.execute(
                """INSERT INTO annotations
                (case_id,sample_index,lead,category,label,note,created_by,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                values,
            )
            row = db.execute("SELECT * FROM annotations WHERE id=?", (cursor.lastrowid,)).fetchone()
        self.audit(actor, "annotation.create", case_id, f"#{row['id']} {row['label']}")
        return dict(row)

    def delete_annotation(self, annotation_id: int, actor: str) -> bool:
        with self.connect() as db:
            row = db.execute("SELECT * FROM annotations WHERE id=?", (annotation_id,)).fetchone()
            if not row:
                return False
            db.execute("DELETE FROM annotations WHERE id=?", (annotation_id,))
        self.audit(actor, "annotation.delete", row["case_id"], f"#{annotation_id} {row['label']}")
        return True

    def get_report(self, case_id: str, source_conclusion: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM report_drafts WHERE case_id=?", (case_id,)).fetchone()
        if row:
            item = dict(row)
            try:
                item["composition"] = normalize_report_composition(json.loads(item.get("composition") or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                item["composition"] = normalize_report_composition(None)
            return item
        return {
            "case_id": case_id,
            "conclusion": source_conclusion,
            "status": "draft",
            "version": 1,
            "reviewed_by": "",
            "updated_at": "",
            "composition": normalize_report_composition(None),
        }

    def save_report(self, case_id: str, conclusion: str, status: str, actor: str, composition: dict | None = None) -> dict:
        allowed = {"draft", "reviewed", "returned"}
        if status not in allowed:
            raise ValueError("invalid report status")
        now = utc_now()
        with self.connect() as db:
            old = db.execute("SELECT * FROM report_drafts WHERE case_id=?", (case_id,)).fetchone()
            version = int(old["version"]) + 1 if old else 1
            old_composition = normalize_report_composition(json.loads(old["composition"] or "{}")) if old else normalize_report_composition(None)
            next_composition = normalize_report_composition(composition) if composition is not None else old_composition
            if old and (old["conclusion"] != conclusion or old_composition != next_composition) and status == "reviewed":
                status = "draft"
            reviewed_by = actor if status == "reviewed" else ""
            db.execute(
                """INSERT INTO report_drafts(case_id,conclusion,composition,status,version,reviewed_by,updated_at)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(case_id) DO UPDATE SET conclusion=excluded.conclusion,
                composition=excluded.composition,status=excluded.status,version=excluded.version,reviewed_by=excluded.reviewed_by,
                updated_at=excluded.updated_at""",
                (case_id, conclusion[:12000], json.dumps(next_composition, ensure_ascii=False), status, version, reviewed_by, now),
            )
            row = db.execute("SELECT * FROM report_drafts WHERE case_id=?", (case_id,)).fetchone()
        self.audit(actor, f"report.{status}", case_id, f"version={version}")
        item = dict(row)
        item["composition"] = normalize_report_composition(json.loads(item.pop("composition") or "{}"))
        return item

    def get_patient_override(self, case_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM patient_overrides WHERE case_id=?", (case_id,)).fetchone()
        if not row:
            return {}
        payload = json.loads(row["payload"])
        payload["active"] = bool(row["active"])
        return payload

    def save_patient_override(self, case_id: str, payload: dict, actor: str) -> dict:
        if not isinstance(payload, dict):
            raise ValueError("患者资料必须为 JSON 对象")
        allowed = {"name", "sex", "age", "patient_id", "bed", "clinical_diagnosis", "active"}
        incoming = {key: payload[key] for key in allowed if key in payload}
        limits = {"name": 80, "patient_id": 80, "bed": 80, "clinical_diagnosis": 500}
        for key, limit in limits.items():
            if key not in incoming:
                continue
            if not isinstance(incoming[key], str):
                raise ValueError(f"{key} 必须为文本")
            incoming[key] = incoming[key].strip()[:limit]
        if "name" in incoming and not incoming["name"]:
            raise ValueError("姓名不能为空")
        if "sex" in incoming:
            if not isinstance(incoming["sex"], str) or incoming["sex"] not in {"男", "女", "未知", "其他"}:
                raise ValueError("sex 必须为男、女、未知或其他")
        if "age" in incoming:
            value = incoming["age"]
            if value in (None, ""):
                incoming["age"] = None
            elif isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value or not 0 <= int(value) <= 130:
                raise ValueError("age 必须为 0–130 的整数")
            else:
                incoming["age"] = int(value)
        if "active" in incoming and not isinstance(incoming["active"], bool):
            raise ValueError("active 必须为布尔值")

        existing = self.get_patient_override(case_id)
        current_active = bool(existing.pop("active", True)) if existing else True
        clean = {key: value for key, value in existing.items() if key in allowed and key != "active"}
        active_value = incoming.pop("active", current_active)
        clean.update(incoming)
        active = 1 if active_value else 0
        now = utc_now()
        with self.connect() as db:
            db.execute(
                """INSERT INTO patient_overrides(case_id,payload,active,updated_at) VALUES(?,?,?,?)
                ON CONFLICT(case_id) DO UPDATE SET payload=excluded.payload,
                active=excluded.active,updated_at=excluded.updated_at""",
                (case_id, json.dumps(clean, ensure_ascii=False), active, now),
            )
        self.audit(actor, "patient.update", case_id, f"active={bool(active)} fields={','.join(sorted(payload.keys() & allowed))}")
        clean["active"] = bool(active)
        return clean
