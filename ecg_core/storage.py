from __future__ import annotations

import json
from .terminology import normalize_terminology_usages
import sqlite3
from .review_workflow import ReportConflict
from .clinical_analysis import normalize_selection
from .review_candidates import EvidenceCandidateMixin
from .report_evidence import ReportEvidenceMixin
from datetime import datetime, timezone
from pathlib import Path


BEAT_TEMPLATE_FAMILIES = {
    "全部",
    "单发",
    "成对",
    "房速",
    "二联律",
    "三联律(NPN)", "三联律(NNP)", "连续三发", "连续多发", "室速",
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
        "time_scale": "fit",
        "gain": "10 mm/mV",
    },
}


def normalize_hrv_reference(value):
    from .hrv_review import normalize_scope, PROFILE
    if not isinstance(value,dict) or set(value)!={'hrv_revision','document_digest','window_index','profile','scope'}:
        raise ValueError('报告 HRV 来源引用字段无效')
    for key in ('hrv_revision','window_index'):
        if type(value[key]) is not int or value[key]<0: raise ValueError('报告 HRV 修订和窗口必须为非负整数')
    if value['profile']!=PROFILE or not isinstance(value['document_digest'],str) or len(value['document_digest'])!=64 or any(c not in '0123456789abcdef' for c in value['document_digest']):
        raise ValueError('报告 HRV 方法或内容指纹无效')
    scope=value['scope']
    if not isinstance(scope,dict): raise ValueError('报告 HRV 依据无效')
    return {**value,'scope':normalize_scope(scope,scope.get('case_id'))}


def normalize_report_composition(value: dict | None) -> dict:
    from .report_curation import narrative_templates
    from .advanced_analysis import normalize_options
    from .signal_profile import normalize_voltage_estimate
    if value is None:
        return {**json.loads(json.dumps(DEFAULT_REPORT_COMPOSITION, ensure_ascii=False)), **normalize_selection({})}
    if not isinstance(value, dict):
        raise ValueError("composition 必须为 JSON 对象")
    raw_pages = value.get("included_pages", DEFAULT_REPORT_COMPOSITION["included_pages"])
    if not isinstance(value.get('include_hrv',False),bool):
        raise ValueError('include_hrv 必须为布尔值')
    if not isinstance(raw_pages, list) or any(not isinstance(item, str) for item in raw_pages):
        raise ValueError("included_pages 必须为页面标识列表")
    pages = [item for item in raw_pages if item in REPORT_PAGE_KEYS]
    pages = list(dict.fromkeys(pages))
    if not pages and value.get('page_selection_version')!=1:
        pages = ["summary"]
    active_page = value.get("active_page", pages[0] if pages else 'summary')
    if not isinstance(active_page, str) or active_page not in REPORT_PAGE_KEYS:
        raise ValueError("active_page 不受支持")
    if active_page not in pages:
        active_page = pages[0] if pages else 'summary'
    template = value.get("template", "custom")
    preview_mode = value.get("preview_mode", "compose")
    fast_slow_mode = value.get("fast_slow_mode", "rr")
    if template not in REPORT_TEMPLATES:
        raise ValueError("template 不受支持")
    if preview_mode not in REPORT_PREVIEW_MODES:
        raise ValueError("preview_mode 不受支持")
    if fast_slow_mode not in REPORT_FAST_SLOW_MODES:
        raise ValueError("fast_slow_mode 不受支持")
    from .stt_records import normalized_uses
    if 'stt_trend_metric' in value and value['stt_trend_metric'] not in ('st_level','delta'):
        raise ValueError('ST 趋势指标无效')
    raw_paper = value.get("paper", {})
    if not isinstance(raw_paper, dict):
        raise ValueError("paper 必须为 JSON 对象")
    size = raw_paper.get("size", "A4")
    orientation = raw_paper.get("orientation", "portrait")
    if size not in {"A4", "A3"} or orientation not in {"portrait", "landscape"}:
        raise ValueError("paper 页面设置不受支持")
    speed = raw_paper.get("speed", "25 mm/s")
    time_scale = raw_paper.get("time_scale", "fit")
    if not isinstance(time_scale, str) or time_scale not in {'fit', 'fixed'}:
        raise ValueError('paper 时间标尺须为 fit 或 fixed')
    for key in ('show_grid', 'show_labels'):
        if key in raw_paper and not isinstance(raw_paper[key], bool):
            raise ValueError(f'paper {key} 必须为布尔值')
    gain = raw_paper.get("gain", "10 mm/mV")
    if speed not in {"12.5 mm/s", "25 mm/s", "50 mm/s"} or gain not in {"5 mm/mV", "10 mm/mV", "20 mm/mV"}:
        raise ValueError("paper 图条设置不受支持")
    return {
        **normalize_selection(value),
        **({'stt_report_use':normalized_uses(value['stt_report_use'])} if 'stt_report_use' in value else {}),
        **({'stt_trend_metric':value['stt_trend_metric']} if 'stt_trend_metric' in value else {}),
        **({"narrative_templates": narrative_templates(value["narrative_templates"])} if "narrative_templates" in value else {}),
        **({"terminology_usages": normalize_terminology_usages(value["terminology_usages"])} if "terminology_usages" in value else {}),
        **({"hrv_review_reference": normalize_hrv_reference(value["hrv_review_reference"])} if "hrv_review_reference" in value else {}),
        "advanced_options": normalize_options(value.get('advanced_options')),
        "hrv_window": max(0, int(value.get("hrv_window",0))),
        "include_hrv": value.get('include_hrv',False),
        "template": template,
        "included_pages": pages,
        "page_selection_version": 1 if value.get('page_selection_version')==1 else 0,
        "active_page": active_page,
        "preview_mode": preview_mode,
        "fast_slow_mode": fast_slow_mode,
        "paper": {
            "size": size,
            "orientation": orientation,
            "show_grid": bool(raw_paper.get("show_grid", True)),
            "show_labels": bool(raw_paper.get("show_labels", True)),
            "speed": speed,
            "time_scale": time_scale,
            "gain": gain,
            "voltage_estimate": normalize_voltage_estimate(raw_paper.get('voltage_estimate')),
        },
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


from .review_workflow import ReviewWorkflowMixin


class Storage(ReviewWorkflowMixin, EvidenceCandidateMixin, ReportEvidenceMixin):
    def __init__(self, path: Path, *, connection_factory=sqlite3.Connection):
        self._connection_factory = connection_factory
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        self.initialize_review()
        self.initialize_candidates()
        self.initialize_report_evidence()
        with self.connect() as db:
            if "details" not in {r[1] for r in db.execute("PRAGMA table_info(annotations)")}:
                db.execute("ALTER TABLE annotations ADD COLUMN details TEXT NOT NULL DEFAULT '{}'")

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, factory=self._connection_factory)
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
                CREATE TABLE IF NOT EXISTS stt_review_submissions (
                    case_id TEXT NOT NULL, submission_id TEXT NOT NULL,
                    annotation_id INTEGER NOT NULL, operation TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    PRIMARY KEY(case_id,submission_id)
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
                CREATE TABLE IF NOT EXISTS case_analysis_basis (
                    case_id TEXT PRIMARY KEY,
                    basis TEXT NOT NULL,
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
            if "analysis_provenance" not in report_columns:
                db.execute("ALTER TABLE report_drafts ADD COLUMN analysis_provenance TEXT NOT NULL DEFAULT '{}'")

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
        if len(raw_samples) > 250000:
            raise ValueError("单个模板类别最多保存 250000 个心搏")
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in raw_samples):
            raise ValueError("sample_indices 必须全部为非负整数")
        samples = sorted(set(raw_samples))
        if len(samples) != len(raw_samples):
            raise ValueError("sample_indices 不能重复")
        if payload.get("details"):
            raise ValueError("心搏模板不支持结构化诊断发现，请使用人工标注入口")
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
            self._audit(db, actor, "beat_template.create", case_id, f"#{row['id']} beats={len(samples)}")
        item = self._beat_template_row(row)
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
            self._audit(db, actor, "beat_template.update", row["case_id"], f"#{template_id}")
        item = self._beat_template_row(row)
        return item

    def delete_beat_template(self, template_id: int, actor: str) -> dict | None:
        existing = self.get_beat_template(template_id)
        if existing is None:
            return None
        with self.connect() as db:
            db.execute("DELETE FROM beat_templates WHERE id=?", (template_id,))
            self._audit(db, actor, "beat_template.delete", existing["case_id"], f"#{template_id}")
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
            self._audit(db, actor, "beat_override.reclassify", case_id, f"class={class_code} beats={len(samples)}")
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
            self._audit(db, actor, "beat_override.restore", case_id, f"beats={changed}")
        return changed

    def audit(self, actor: str, action: str, case_id: str = "", detail: str = "") -> None:
        with self.connect() as db:
            self._audit(db, actor, action, case_id, detail)

    def _audit(self, db, actor, action, case_id="", detail="", *, rhythm_only=False):
        # Data, invalidation and its audit receipt must commit or roll back together.
        if rhythm_only:self.invalidate_review(db, case_id, action,rhythm_only=True)
        else:self.invalidate_review(db, case_id, action)
        db.execute("INSERT INTO audit_log(case_id,actor,action,detail,created_at) VALUES(?,?,?,?,?)",
                   (case_id, actor, action, detail, utc_now()))

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
            has_rhythms = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='rhythm_reviews'").fetchone()
            rhythm = db.execute("SELECT document,updated_at FROM rhythm_reviews WHERE case_id=?", (case_id,)).fetchone() if has_rhythms else None
        items = [{**dict(row), "details":json.loads(row["details"] or "{}")} for row in rows]
        if rhythm:
            from .overview import episode_annotations
            items = [x for x in items if x["details"].get("kind") not in ("AF", "AFL")]
            items += episode_annotations(json.loads(rhythm["document"]), stamp=rhythm["updated_at"])
            items.append(dict(id="rhythm-control", sample_index=0, label="", internal=True, details={"rhythm_authoritative": True}))
        return items

    def annotation_submission(self, case_id, payload, db=None):
        """Read-only reconciliation of an exact ST range save intent."""
        details = payload.get('details') or {}
        identifier = details.get('submission_id') if isinstance(details, dict) else None
        if identifier is None: return None
        from uuid import UUID
        if not isinstance(identifier, str) or str(UUID(identifier)) != identifier:
            raise ValueError('区间统计提交编号须为规范 UUID')
        if details.get('kind') != 'ST' or not isinstance(details.get('range_statistics'), dict):
            raise ValueError('区间统计提交编号不能用于普通标注')
        if any(key in payload and not isinstance(payload[key], str)
               for key in ('lead', 'category', 'label', 'note')):
            raise ValueError('标注文字须为文本')
        if db is None:
            with self.connect() as connection:
                return self.annotation_submission(case_id, payload, connection)
        rows = db.execute("SELECT * FROM annotations WHERE case_id=? AND json_extract(details,'$.submission_id')=?",
                          (case_id, identifier)).fetchall()
        if not rows: return None
        if len(rows) != 1: raise ReportConflict('区间统计提交记录重复，请保留工作并核对')
        row = dict(rows[0]); row['details'] = json.loads(row['details'])
        label = payload.get('label', '人工标注')
        expected_details = dict(kind=details.get('kind'), status=details.get('status'),
            end_sample=details.get('end_sample', payload.get('sample_index', 0)),
            finding=str(details.get('finding', label))[:120],
            range_statistics=details['range_statistics'], submission_id=identifier)
        if 'point_measurement_sample_index' in details:
            expected_details['point_measurement_sample_index'] = details['point_measurement_sample_index']
        expected = dict(sample_index=payload.get('sample_index', 0), lead=payload.get('lead', '')[:16],
            category=payload.get('category', 'note')[:32], label=label.strip()[:120],
            note=payload.get('note', '')[:2000], details=expected_details)
        if any(row[key] != value for key, value in expected.items()):
            raise ReportConflict('此提交编号已保存另一份内容；未重复保存或覆盖，请核对已保存标注')
        return row

    def create_annotation(self, case_id: str, payload: dict, actor: str, *, guard=None, source_guard=None, replay_guard=None) -> dict:
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
        details = payload.get("details", {})
        if details:
            if not isinstance(details,dict) or details.get("kind") not in ("ST","AT","VT","AF","AFL","STRIP") or details.get("status") not in ("confirmed","excluded","pending"):
                raise ValueError("结构化发现类型或状态无效")
            end=details.get("end_sample",sample_index)
            if type(end) is not int or end<sample_index:raise ValueError("结束位置无效")
            original_details = details
            details={"kind":details["kind"],"status":details["status"],"end_sample":end,"finding":str(details.get("finding",label))[:120]}
            if 'stt_event_evidence' in original_details:
                proof=original_details['stt_event_evidence']
                if details['kind']!='ST' or not isinstance(proof,dict) or proof.get('source')!='reviewed_automatic_candidate':raise ValueError('ST-T 整段证据结构无效')
                encoded=json.dumps(proof,ensure_ascii=False,allow_nan=False)
                if len(encoded.encode())>16384:raise ValueError('ST-T 整段证据超过上限')
                details['stt_event_evidence']=json.loads(encoded)
            if 'range_statistics' in original_details:
                statistics = original_details['range_statistics']
                if details['kind'] != 'ST' or not isinstance(statistics, dict) or statistics.get('schema_version') != 'stt-range-mean-v1':
                    raise ValueError('区间统计结构或标注类型无效')
                encoded = json.dumps(statistics, ensure_ascii=False, allow_nan=False)
                if len(encoded.encode()) > 262144: raise ValueError('统计摘要超过当前保存上限；本次未保存，现有标注和复核备注已保留。')
                details['range_statistics'] = json.loads(encoded)
                if 'submission_id' in original_details:
                    from uuid import UUID
                    identifier = original_details['submission_id']
                    if not isinstance(identifier, str) or str(UUID(identifier)) != identifier:
                        raise ValueError('区间统计提交编号须为规范 UUID')
                    details['submission_id'] = identifier
            if 'point_measurement_sample_index' in original_details:
                point = original_details['point_measurement_sample_index']
                if details['kind'] != 'ST' or type(point) is not int or point < 0:
                    raise ValueError('手工点测量位置无效')
                details['point_measurement_sample_index'] = point
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
            if guard is not None:
                db.execute('BEGIN IMMEDIATE')
                previous = self.annotation_submission(case_id, payload, db)
                if previous is not None:
                    if replay_guard is not None: replay_guard(db)
                    elif source_guard is not None: source_guard()
                    return previous
                guard(db)
            cursor = db.execute(
                """INSERT INTO annotations
                (case_id,sample_index,lead,category,label,note,created_by,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                values,
            )
            db.execute("UPDATE annotations SET details=? WHERE id=?",(json.dumps(details,ensure_ascii=False),cursor.lastrowid))
            row = db.execute("SELECT * FROM annotations WHERE id=?", (cursor.lastrowid,)).fetchone()
            self._audit(db, actor, "annotation.create", case_id, f"#{row['id']} {row['label']}",
                        rhythm_only=isinstance(details,dict) and details.get('kind') in ('AF','AFL'))
            if replay_guard is not None: replay_guard(db)
            elif source_guard is not None: source_guard()
        return {**dict(row),"details":details}

    def stt_replay(self,case_id,identifier,request_sha256,operation,annotation_id=None):
        with self.connect() as db:
            prior=db.execute('SELECT * FROM stt_review_submissions WHERE case_id=? AND submission_id=?',(case_id,identifier)).fetchone()
            if prior is None:return None
            if prior['request_sha256']!=request_sha256 or prior['operation']!=operation or annotation_id is not None and prior['annotation_id']!=annotation_id:raise ReportConflict('此ST-T提交编号已用于另一份内容')
            row=db.execute('SELECT * FROM annotations WHERE case_id=? AND id=?',(case_id,prior['annotation_id'])).fetchone()
        if row is None:raise ReportConflict('已保存的ST-T记录已删除，未自动重复创建')
        item=dict(row);item['details']=json.loads(item['details']);item['stt_replayed']=True
        return item

    @staticmethod
    def _withdraw_stt_generated_text(composition,event_id):
        key='ST:review:'+event_id;removed=[];kept=[]
        for block in composition.get('diagnosis_blocks',[]):
            if block.get('key')!=key:kept.append(block)
            elif block.get('manual') is False:removed.append(block)
            else:kept.append({**block,'needs_review':True,'acknowledged':False})
        if 'diagnosis_blocks' in composition:composition['diagnosis_blocks']=kept
        return removed

    def save_stt_record(self, case_id, payload, actor, *, guard, replay_guard,
                        request_sha256, annotation_id=None, expected_record_version=None):
        """One UUID intent, record mutation, report withdrawal and audit transaction."""
        from uuid import UUID
        from .stt_records import RESULTS, protocol, status_for, normalized_findings, ABNORMAL
        from .report_layout import LEADS
        d=dict(payload.get('details') or {})
        identifier=d.get('submission_id')
        if not isinstance(identifier,str) or str(UUID(identifier))!=identifier:raise ValueError('ST-T 保存须提供规范 UUID 提交编号')
        if d.get('reviewed') is not True or d.get('result_code') not in RESULTS:raise ValueError('请选择本次医生复核结果并保存')
        if d.get('kind')!='ST':raise ValueError('ST-T 复核记录类型无效')
        first=payload.get('sample_index');end=d.get('end_sample',first)
        if type(first) is not int or type(end) is not int or first<0 or end<first:raise ValueError('ST-T 复核范围无效')
        leads=d.get('review_leads')
        if not isinstance(leads,list) or not leads or len(set(leads))!=len(leads) or any(x not in LEADS for x in leads):raise ValueError('请选择实际复核的有效导联')
        d['measurement_protocol']=protocol(d.get('measurement_protocol'))
        if d.get('review_extent','point') not in ('point','whole'):raise ValueError('复核范围类型无效')
        findings=normalized_findings(d,first,end,leads)
        if 'findings' in d:d['findings']=findings
        d['status']='confirmed' if any(r['result_code'] in ABNORMAL for r in findings) else status_for(d['result_code']);d['finding']=str(d.get('finding',payload.get('label','')))[:120]
        for name,limit in (('label',120),('note',2000),('lead',16),('category',32)):
            if not isinstance(payload.get(name,''),str) or len(payload.get(name,''))>limit:raise ValueError('ST-T 复核文字无效或过长')
        if payload.get('lead','') not in ('','全部',*LEADS):raise ValueError('ST-T 导联无效')
        now=utc_now();operation='create' if annotation_id is None else 'update'
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prior=db.execute('SELECT * FROM stt_review_submissions WHERE case_id=? AND submission_id=?',(case_id,identifier)).fetchone()
            if prior:
                if prior['request_sha256']!=request_sha256 or prior['operation']!=operation or annotation_id is not None and prior['annotation_id']!=annotation_id:raise ReportConflict('此提交编号已用于另一份ST-T内容，未覆盖或重复保存')
                replay_guard(db)
                row=db.execute('SELECT * FROM annotations WHERE case_id=? AND id=?',(case_id,prior['annotation_id'])).fetchone()
                if row is None:raise ReportConflict('该ST-T提交曾已保存但记录已删除，未自动重建')
                item=dict(row);item['details']=json.loads(item['details']);item['stt_replayed']=True;return item
            guard(db)
            previous=None
            if annotation_id is not None:
                previous=db.execute('SELECT * FROM annotations WHERE case_id=? AND id=?',(case_id,annotation_id)).fetchone()
                if not previous:raise ReportConflict('原ST-T复核记录不存在，未创建另一条')
                old=json.loads(previous['details'] or '{}')
                if old.get('kind') not in ('ST','ST_REVIEW_NOTE'):raise ValueError('仅可修订同一ST-T记录')
                if type(expected_record_version) is not int or expected_record_version!=old.get('record_version',1):raise ReportConflict('ST-T记录版本已变化，请载入本条后重新核对')
                d['record_version']=old.get('record_version',1)+1
                if old.get('withdrawn_report_settings'):d['withdrawn_report_settings']=old['withdrawn_report_settings']
            else:d['record_version']=1
            reconciliation=dict(removed_selections=[],removed_uses=[],removed_diagnosis_blocks=[],reason='ST-T记录修订后重新选择本次采用用途')
            if previous:
                report=db.execute('SELECT composition FROM report_drafts WHERE case_id=?',(case_id,)).fetchone()
                if report:
                    comp=json.loads(report['composition'] or '{}');event_id='annotation:'+str(annotation_id)
                    reconciliation['removed_selections']=[s for s in comp.get('selected_events',[]) if s['event_id']==event_id]
                    reconciliation['removed_uses']=[s for s in comp.get('stt_report_use',[]) if s['event_id']==event_id]
                    comp['selected_events']=[s for s in comp.get('selected_events',[]) if s['event_id']!=event_id]
                    if 'stt_report_use' in comp:comp['stt_report_use']=[s for s in comp['stt_report_use'] if s['event_id']!=event_id]
                    reconciliation['removed_diagnosis_blocks']=self._withdraw_stt_generated_text(comp,event_id)
                    db.execute('UPDATE report_drafts SET composition=? WHERE case_id=?',(json.dumps(comp,ensure_ascii=False),case_id))
                    if reconciliation['removed_selections']:d['withdrawn_report_settings']=reconciliation['removed_selections']
                d['last_report_reconciliation']=reconciliation
            encoded=json.dumps(d,ensure_ascii=False,allow_nan=False)
            if len(encoded.encode())>300000:raise ValueError('ST-T复核证据超过保存上限')
            values=(first,payload.get('lead','全部'),payload.get('category','note'),payload.get('label') or 'ST-T 人工复核',payload.get('note',''),encoded,now)
            if previous:
                db.execute('UPDATE annotations SET sample_index=?,lead=?,category=?,label=?,note=?,details=?,updated_at=? WHERE id=? AND case_id=?',(*values,annotation_id,case_id))
            else:
                cursor=db.execute('INSERT INTO annotations(sample_index,lead,category,label,note,details,updated_at,case_id,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(*values,case_id,actor,now));annotation_id=cursor.lastrowid
            db.execute('INSERT INTO stt_review_submissions(case_id,submission_id,annotation_id,operation,request_sha256) VALUES(?,?,?,?,?)',(case_id,identifier,annotation_id,operation,request_sha256))
            self._audit(db,actor,'annotation.stt.'+operation,case_id,'#'+str(annotation_id))
            row=db.execute('SELECT * FROM annotations WHERE id=?',(annotation_id,)).fetchone();item=dict(row);item['details']=json.loads(item['details'])
        item['stt_report_reconciliation']=reconciliation
        return item

    def delete_annotation(self, annotation_id: int, actor: str) -> bool:
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM annotations WHERE id=?", (annotation_id,)).fetchone()
            if not row:
                return False
            if json.loads(row['details'] or '{}').get('kind') in ('ST','ST_REVIEW_NOTE'):
                report=db.execute('SELECT composition FROM report_drafts WHERE case_id=?',(row['case_id'],)).fetchone()
                if report:
                    composition=json.loads(report['composition'] or '{}');event_id='annotation:'+str(annotation_id)
                    composition['selected_events']=[s for s in composition.get('selected_events',[]) if s['event_id']!=event_id]
                    if 'stt_report_use' in composition:composition['stt_report_use']=[s for s in composition['stt_report_use'] if s['event_id']!=event_id]
                    self._withdraw_stt_generated_text(composition,event_id)
                    db.execute('UPDATE report_drafts SET composition=? WHERE case_id=?',(json.dumps(composition,ensure_ascii=False),row['case_id']))
            db.execute("DELETE FROM annotations WHERE id=?", (annotation_id,))
            self._audit(db, actor, "annotation.delete", row["case_id"], f"#{annotation_id} {row['label']}",
                        rhythm_only=json.loads(row['details'] or '{}').get('kind') in ('AF','AFL'))
        return True

    def record_compatible_implementation(self, case_id, certificate, actor, check_current):
        """Audit verified implementation continuity without changing a doctor's work."""
        from .analysis_provenance import digest
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS analysis_implementation_compatibility (
                case_id TEXT NOT NULL, execution_engine_id TEXT NOT NULL,
                execution_basis TEXT NOT NULL, certificate TEXT NOT NULL, created_at TEXT NOT NULL,
                PRIMARY KEY(case_id,execution_engine_id,execution_basis))""")
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT basis FROM case_analysis_basis WHERE case_id=?',(case_id,)).fetchone()
            if not old or json.loads(old['basis'])!=certificate['reference_basis']:
                raise ReportConflict('升级核对期间病例依据已变化，未保留旧复核')
            if self._review(db,case_id)['revision']!=certificate['review_revision']:
                raise ReportConflict('升级核对期间复核已有修改，请重新载入')
            annotations=[{**dict(row),'details':json.loads(row['details'] or '{}')}
                         for row in db.execute('SELECT * FROM annotations WHERE case_id=? ORDER BY sample_index,id',(case_id,))]
            rhythm=db.execute("SELECT document,updated_at FROM rhythm_reviews WHERE case_id=?",(case_id,)).fetchone()
            if rhythm:
                from .overview import episode_annotations
                annotations=[x for x in annotations if x['details'].get('kind') not in ('AF','AFL')]
                annotations+=episode_annotations(json.loads(rhythm['document']),stamp=rhythm['updated_at'])
                annotations.append(dict(id='rhythm-control',sample_index=0,label='',internal=True,details={'rhythm_authoritative':True}))
            report=db.execute('SELECT * FROM report_drafts WHERE case_id=?',(case_id,)).fetchone()
            if report and (report['version']!=certificate['report_version'] or digest(normalize_report_composition(json.loads(report['composition'])))!=certificate['report_composition_digest']):
                raise ReportConflict('升级核对期间报告已有修改，请重新载入')
            if certificate.get('continuity_kind') == 'stt_screening_refinement':
                from .screening_compatibility import report_identity, POLICY_SCHEMA
                if certificate.get('schema') != POLICY_SCHEMA:
                    raise ReportConflict('筛查升级证据类型不一致，未保留旧复核')
                if report:
                    state = dict(report)
                    state['composition'] = normalize_report_composition(json.loads(state['composition']))
                    state['analysis_provenance'] = json.loads(state.get('analysis_provenance') or '{}')
                    if report_identity(state) != certificate.get('report_state_digest'):
                        raise ReportConflict('升级核对期间报告签署状态已变化，未保留旧复核')
                elif certificate.get('signed_report_snapshot'):
                    raise ReportConflict('升级核对期间原签署报告已不存在')
            # list_annotations has this same ordering and source DTO.
            if digest(annotations)!=certificate['authored_annotations_digest']:
                raise ReportConflict('升级核对期间标注已变化，未保留旧复核')
            editor=db.execute('SELECT revision,document FROM beat_edit_documents WHERE case_id=?',(case_id,)).fetchone()
            if editor:
                if editor['revision']!=certificate['beat_revision'] or digest(json.loads(editor['document']))!=certificate['editor_document_digest']:
                    raise ReportConflict('升级核对期间心搏编辑已变化，未保留旧复核')
            elif certificate['beat_revision']!=0:
                raise ReportConflict('升级核对期间心搏依据缺失')
            check_current()
            payload=json.dumps(certificate,ensure_ascii=False,sort_keys=True)
            exists=db.execute('SELECT certificate FROM analysis_implementation_compatibility WHERE case_id=? AND execution_engine_id=? AND execution_basis=?',
                              (case_id,certificate['execution_engine_id'],certificate['execution_basis'])).fetchone()
            db.execute("""INSERT INTO analysis_implementation_compatibility VALUES(?,?,?,?,?)
                ON CONFLICT(case_id,execution_engine_id,execution_basis)
                DO UPDATE SET certificate=excluded.certificate,created_at=excluded.created_at""",
                (case_id,certificate['execution_engine_id'],certificate['execution_basis'],payload,utc_now()))
            action=('analysis.screening_refinement_verified'
                    if certificate.get('continuity_kind')=='stt_screening_refinement'
                    else 'analysis.performance_upgrade_verified')
            needs_audit=not exists or exists['certificate']!=payload
            if action=='analysis.screening_refinement_verified':
                # A full re-verification repairs a missing or damaged audit even
                # when the resulting numerical certificate is byte-for-byte equal.
                # A read cache cannot create this independent evidence.
                needs_audit=needs_audit or not self._compatible_audit_matches(db,case_id,certificate,action)
            if needs_audit:
                db.execute('INSERT INTO audit_log(case_id,actor,action,detail,created_at) VALUES(?,?,?,?,?)',
                    (case_id,actor,action,
                     json.dumps(dict(reference_basis=certificate['reference_basis']['digest'],
                         execution_engine=certificate['execution_engine_id'],
                         proof_sha256=digest(certificate),retained_stt_records=certificate['retained_stt_records']),sort_keys=True),utc_now()))

    @staticmethod
    def _compatible_audit_matches(db,case_id,certificate,action):
        from .analysis_provenance import digest
        expected=digest(certificate)
        for row in db.execute('SELECT detail FROM audit_log WHERE case_id=? AND action=? ORDER BY id DESC',
                              (case_id,action)):
            try:detail=json.loads(row['detail'])
            except (ValueError,TypeError):continue
            if (isinstance(detail,dict) and detail.get('proof_sha256')==expected
                    and detail.get('execution_engine')==certificate.get('execution_engine_id')
                    and detail.get('reference_basis')==(certificate.get('reference_basis') or {}).get('digest')
                    and detail.get('retained_stt_records')==certificate.get('retained_stt_records')):
                return True
        return False

    def get_compatible_implementation(self,case_id,execution_engine_id,execution_basis):
        """Read one independently audited screening certificate, never authorize it.

        The caller must still match its entire live snapshot and policy, then
        run the ordinary atomic commit guards. Unattested JSON is a cache miss.
        """
        from .screening_compatibility import POLICY_SCHEMA,CONTINUITY_KIND
        with self.connect() as db:
            db.execute('BEGIN')
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='analysis_implementation_compatibility'").fetchone():
                return None
            row=db.execute('SELECT certificate FROM analysis_implementation_compatibility '
                           'WHERE case_id=? AND execution_engine_id=? AND execution_basis=?',
                           (case_id,execution_engine_id,execution_basis)).fetchone()
            if not row:return None
            try:certificate=json.loads(row['certificate'])
            except (ValueError,TypeError):return None
            if (not isinstance(certificate,dict) or certificate.get('schema')!=POLICY_SCHEMA
                    or certificate.get('continuity_kind')!=CONTINUITY_KIND
                    or certificate.get('case_id')!=case_id
                    or certificate.get('execution_engine_id')!=execution_engine_id
                    or certificate.get('execution_basis')!=execution_basis):
                return None
            try:audited=self._compatible_audit_matches(db,case_id,certificate,'analysis.screening_refinement_verified')
            except (ValueError,TypeError,AttributeError,OverflowError):return None
            if not audited:
                return None
            return certificate

    def sync_analysis_basis(self, case_id, basis, actor, readonly=False):
        """Idempotent, atomic invalidation; keep text and selected evidence intact."""
        encoded = json.dumps(basis, sort_keys=True, ensure_ascii=False)
        with self.connect() as db:
            old = db.execute('SELECT basis FROM case_analysis_basis WHERE case_id=?', (case_id,)).fetchone()
            if old and old['basis'] == encoded:
                return False
            if readonly:
                legacy = db.execute('SELECT 1 FROM case_review WHERE case_id=? UNION SELECT 1 FROM report_drafts WHERE case_id=?', (case_id, case_id)).fetchone()
                if old or legacy:
                    raise ReportConflict('计算依据已变化或缺少记录；只读服务不能重新审核，请在本地可写工作站核对')
                return False
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT basis FROM case_analysis_basis WHERE case_id=?', (case_id,)).fetchone()
            if old and old['basis'] == encoded:
                return False
            legacy = db.execute('SELECT 1 FROM case_review WHERE case_id=? UNION SELECT 1 FROM report_drafts WHERE case_id=?', (case_id, case_id)).fetchone()
            changed = bool(old or legacy)
            db.execute('''INSERT INTO case_analysis_basis VALUES(?,?,?) ON CONFLICT(case_id)
                DO UPDATE SET basis=excluded.basis, updated_at=excluded.updated_at''', (case_id, encoded, utc_now()))
            previous = json.loads(old['basis']).get('digest', 'legacy') if old else 'legacy'
            self._audit(db, actor, 'analysis.basis_changed' if changed else 'analysis.basis_initialized',
                        case_id, f"{previous} -> {basis['digest']}")
        return changed

    def get_analysis_basis(self, case_id):
        with self.connect() as db:
            row = db.execute('SELECT basis FROM case_analysis_basis WHERE case_id=?', (case_id,)).fetchone()
        return json.loads(row['basis']) if row else None

    def get_report(self, case_id: str, source_conclusion: str) -> dict:
        with self.connect() as db:
            db.execute("BEGIN")
            row = db.execute("SELECT * FROM report_drafts WHERE case_id=?", (case_id,)).fetchone()
            review_revision = self._review(db, case_id)["revision"]
        if row:
            item = dict(row)
            item["review_revision"] = review_revision
            item['analysis_provenance'] = json.loads(item.get('analysis_provenance') or '{}')
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
            "review_revision": review_revision,
            "reviewed_by": "",
            "updated_at": "",
            "composition": normalize_report_composition(None),
            "analysis_provenance": {},
        }

    def save_report(self, case_id: str, conclusion: str, status: str, actor: str, composition: dict | None = None, expected_version=None, expected_review_revision=None, expected_analysis_basis=None, check_source=None, *, execution_provenance=None) -> dict:
        allowed = {"draft", "reviewed", "returned"}
        if status not in allowed:
            raise ValueError("invalid report status")
        if expected_version is not None and (type(expected_version) is not int or expected_version < 1):
            raise ValueError("报告版本必须为正整数")
        if not isinstance(conclusion, str) or len(conclusion) > 12000:
            raise ValueError("报告结论必须为 12000 字以内的文本")
        now = utc_now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM report_drafts WHERE case_id=?", (case_id,)).fetchone()
            if expected_version is not None and expected_version != (old["version"] if old else 1):
                raise ReportConflict("报告版本已变更，未覆盖最新报告；请重新载入后核对")
            if expected_review_revision is not None and self._review(db, case_id)["revision"] != expected_review_revision:
                raise ReportConflict("保存期间病例已变化，报告未保存；请重新载入后核对")
            source = db.execute('SELECT basis FROM case_analysis_basis WHERE case_id=?', (case_id,)).fetchone()
            basis = json.loads(source['basis']) if source else {}
            if expected_analysis_basis is not None and basis.get('digest') != expected_analysis_basis:
                raise ReportConflict('保存期间计算依据已变化，报告未保存；请重新复核')
            if check_source is not None:
                check_source()
            if status == "reviewed":
                self.assert_report_ready(db, case_id, conclusion)
            version = (int(old["version"]) if old else 1) + 1
            old_composition = normalize_report_composition(json.loads(old["composition"] or "{}")) if old else normalize_report_composition(None)
            next_composition = normalize_report_composition(composition if composition is not None else old_composition)
            if old and (old["conclusion"] != conclusion or old_composition != next_composition) and status == "reviewed":
                status = "draft"
            reviewed_by = actor if status == "reviewed" else ""
            from .analysis_provenance import digest
            provenance = {'basis': basis, 'composition_sha256': digest(next_composition)} if basis else {}
            if execution_provenance is not None:
                # Server-only provenance for an actual new save, never a rewrite
                # of a retained signature during compatibility verification.
                if (not isinstance(execution_provenance,dict)
                        or set(execution_provenance)!={'execution_engine_id','screening_algorithm_version'}
                        or any(not isinstance(v,str) or not v for v in execution_provenance.values())):
                    raise ValueError('报告保存缺少有效执行程序依据')
                provenance.update(execution_provenance)
            db.execute(
                """INSERT INTO report_drafts(case_id,conclusion,composition,status,version,reviewed_by,updated_at,analysis_provenance)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(case_id) DO UPDATE SET conclusion=excluded.conclusion,
                composition=excluded.composition,status=excluded.status,version=excluded.version,reviewed_by=excluded.reviewed_by,
                updated_at=excluded.updated_at,analysis_provenance=excluded.analysis_provenance""",
                (case_id, conclusion, json.dumps(next_composition, ensure_ascii=False), status, version, reviewed_by, now, json.dumps(provenance,ensure_ascii=False)),
            )
            row = db.execute("SELECT * FROM report_drafts WHERE case_id=?", (case_id,)).fetchone()
            review_revision = self._review(db, case_id)["revision"]
            self._audit(db, actor, f"report.{status}", case_id, f"version={version}")
        item = dict(row)
        item["review_revision"] = review_revision
        item['analysis_provenance'] = json.loads(item['analysis_provenance'])
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
            self._audit(db, actor, "patient.update", case_id, f"active={bool(active)} fields={','.join(sorted(payload.keys() & allowed))}")
        clean["active"] = bool(active)
        return clean
