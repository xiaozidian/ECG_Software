"""Explicit physician review checkpoints; never infer completion from navigation."""
from __future__ import annotations

import json
from datetime import datetime, timezone

STEPS = ("review", "edit", "trends", "stt", "events")
LABELS = dict(zip(STEPS, ("波形复核", "模板编辑", "趋势与 HRV", "ST-T", "事件复核")))


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ReviewWorkflowMixin:
    def initialize_review(self):
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS case_review (
                case_id TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 0,
                steps TEXT NOT NULL DEFAULT '{}', events TEXT NOT NULL DEFAULT '{}')""")

    def _review(self, db, case_id):
        row = db.execute("SELECT * FROM case_review WHERE case_id=?", (case_id,)).fetchone()
        return dict(case_id=case_id, revision=row["revision"] if row else 0,
                    steps=json.loads(row["steps"]) if row else {},
                    events=json.loads(row["events"]) if row else {})

    def _write_review(self, db, value):
        db.execute("""INSERT INTO case_review(case_id,revision,steps,events) VALUES(?,?,?,?)
            ON CONFLICT(case_id) DO UPDATE SET revision=excluded.revision,
            steps=excluded.steps,events=excluded.events""",
            (value["case_id"], value["revision"], json.dumps(value["steps"], ensure_ascii=False),
             json.dumps(value["events"], ensure_ascii=False)))

    def invalidate_review(self, db, case_id, action):
        if not case_id:
            return
        if action.startswith("beat_override."):
            affected = STEPS  # waveform and classifications changed, source statistics did not
        elif action.startswith("beat_template."):
            affected = STEPS[1:]
        elif action.startswith("annotation."):
            affected = ("stt", "events")
        elif action == "patient.update":
            affected = STEPS
        elif action == "event.review":
            affected = ("events",)
        else:
            return
        value = self._review(db, case_id)
        value["revision"] += 1
        for step in affected:
            if step in value["steps"]:
                value["steps"][step]["status"] = "stale"
                value["steps"][step]["reason"] = action
        if action.startswith("beat_override."):
            for event in value["events"].values():
                event["status"] = "pending"
        self._write_review(db, value)
        db.execute("""UPDATE report_drafts SET status='draft', reviewed_by='', version=version+1,
            updated_at=? WHERE case_id=? AND status='reviewed'""", (stamp(), case_id))

    def get_review(self, case_id):
        with self.connect() as db:
            value = self._review(db, case_id)
            report = db.execute("SELECT status,version FROM report_drafts WHERE case_id=?", (case_id,)).fetchone()
        value["pending_steps"] = [step for step in STEPS if value["steps"].get(step, {}).get("status") != "done"]
        value["report_status"] = report["status"] if report else "draft"
        value["report_version"] = report["version"] if report else 1
        value["next_step"] = value["pending_steps"][0] if value["pending_steps"] else "report"
        return value

    def complete_review(self, case_id, payload, actor):
        step, note, revision = payload.get("step"), payload.get("note", ""), payload.get("revision")
        if step not in STEPS or payload.get("confirmed") is not True:
            raise ValueError("请选择复核环节并明确确认")
        if not isinstance(note, str) or len(note) > 1200:
            raise ValueError("复核备注必须是 1200 字以内的文本")
        if isinstance(revision, bool) or not isinstance(revision, int):
            raise ValueError("缺少复核版本，请刷新后重试")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            value = self._review(db, case_id)
            if revision != value["revision"]:
                raise ValueError("病例已发生修改，请重新核对当前环节")
            value["revision"] += 1
            value["steps"][step] = dict(status="done", note=note.strip(), actor=actor, updated_at=stamp())
            self._write_review(db, value)
            db.execute("INSERT INTO audit_log(case_id,actor,action,detail,created_at) VALUES(?,?,?,?,?)",
                       (case_id, actor, "workflow.complete", step + ": " + note.strip(), stamp()))
        return self.get_review(case_id)

    def save_event_review(self, case_id, payload, actor, valid_samples):
        records, status = payload.get("items"), payload.get("status")
        if status not in ("retained", "excluded", "pending"):
            raise ValueError("事件状态必须为 retained、excluded 或 pending")
        if not isinstance(records, list) or not 1 <= len(records) <= 500:
            raise ValueError("每次处理 1–500 个事件")
        clean = {}
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("事件必须为对象")
            sample, kind = record.get("sample_index"), record.get("type")
            if isinstance(sample, bool) or not isinstance(sample, int) or sample not in valid_samples:
                raise ValueError("事件心搏不存在")
            if kind not in ("V", "S", "pause", "tachy", "brady", "noise", "AF", "AFL", "manual"):
                raise ValueError("不支持的候选类型")
            clean[f"{kind}:{sample}"] = dict(sample_index=sample, type=kind, status=status,
                                           actor=actor, updated_at=stamp())
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            value = self._review(db, case_id)
            value["events"].update(clean)
            self._write_review(db, value)
            self.invalidate_review(db, case_id, "event.review")
            db.execute("INSERT INTO audit_log(case_id,actor,action,detail,created_at) VALUES(?,?,?,?,?)",
                       (case_id, actor, "event.review", f"{status}: {len(clean)}", stamp()))
        return self.get_review(case_id)

    def assert_report_ready(self, db, case_id, conclusion):
        value = self._review(db, case_id)
        pending = [LABELS[step] for step in STEPS if value["steps"].get(step, {}).get("status") != "done"]
        if pending:
            raise ValueError("报告审核前请确认：" + "、".join(pending))
        if not conclusion.strip():
            raise ValueError("请先填写并保存医生复核结论")
