from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


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
            return dict(row)
        return {
            "case_id": case_id,
            "conclusion": source_conclusion,
            "status": "draft",
            "version": 1,
            "reviewed_by": "",
            "updated_at": "",
        }

    def save_report(self, case_id: str, conclusion: str, status: str, actor: str) -> dict:
        allowed = {"draft", "reviewed", "returned"}
        if status not in allowed:
            raise ValueError("invalid report status")
        now = utc_now()
        with self.connect() as db:
            old = db.execute("SELECT * FROM report_drafts WHERE case_id=?", (case_id,)).fetchone()
            version = int(old["version"]) + 1 if old else 1
            if old and old["conclusion"] != conclusion and status == "reviewed":
                status = "draft"
            reviewed_by = actor if status == "reviewed" else ""
            db.execute(
                """INSERT INTO report_drafts(case_id,conclusion,status,version,reviewed_by,updated_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(case_id) DO UPDATE SET conclusion=excluded.conclusion,
                status=excluded.status,version=excluded.version,reviewed_by=excluded.reviewed_by,
                updated_at=excluded.updated_at""",
                (case_id, conclusion[:12000], status, version, reviewed_by, now),
            )
            row = db.execute("SELECT * FROM report_drafts WHERE case_id=?", (case_id,)).fetchone()
        self.audit(actor, f"report.{status}", case_id, f"version={version}")
        return dict(row)

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
