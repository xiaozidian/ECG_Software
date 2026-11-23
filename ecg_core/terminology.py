"""Versioned, local report phrases. This is not a diagnosis engine or an ontology.

Metadata design references CodeSystem identity/version, declared provenance and
review fields, not FHIR or DICOM conformance. No remote sources are fetched.
Primary schema references (no clinical vocabulary content is copied):
https://www.hl7.org/fhir/codesystem.html
https://dicom.nema.org/medical/dicom/current/output/chtml/part16/sect_TID_3717.html
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import ipaddress
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, unquote

MAX_CATALOG_BYTES = 1_048_576
MAX_NODES = 1200
MAX_DEPTH = 8
APPROVALS = {"draft", "approved", "rejected"}
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$")
_NAMESPACE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{2,95}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}$")
_UNSAFE = re.compile(r"[<>]|&(?:#(?:x[0-9a-f]+|[0-9]+)|[a-z]+);", re.I)
_CONTROLS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u202a-\u202e\u2066-\u2069]")


class TerminologyConflict(ValueError):
    def __init__(self, message: str, current_revision: int):
        super().__init__(message)
        self.current_revision = current_revision


def _object(value, keys, field):
    if not isinstance(value, dict) or set(value) - set(keys):
        raise ValueError(f"{field} 必须为受支持字段组成的对象")
    return value


def _text(value, field, maximum=4000, empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise ValueError(f"{field} 必须为长度不超过 {maximum} 的纯文本")
    if _UNSAFE.search(value) or _CONTROLS.search(value):
        raise ValueError(f"{field} 不允许 HTML、实体或控制字符")
    return value


def _identifier(value, field, expression=_ID):
    if not isinstance(value, str) or not expression.fullmatch(value):
        raise ValueError(f"{field} 标识格式不受支持")
    return value


def _url(value, field):
    value = _text(value, field, 1000, empty=True)
    if not value:
        return ""
    decoded = unquote(value)
    if re.search(r"[\s\\]", decoded) or _UNSAFE.search(decoded) or _CONTROLS.search(decoded):
        raise ValueError(f"{field} 来源 URL 不安全")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        if (parsed.scheme != "https" or not hostname or parsed.username is not None
                or parsed.password is not None or parsed.port not in (None, 443)):
            raise ValueError()
        if not re.fullmatch(r"[A-Za-z0-9.-]+", hostname) or "." not in hostname:
            raise ValueError()
        if hostname.lower().endswith((".local", ".localhost", ".internal")):
            raise ValueError()
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            if not all(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", x) for x in hostname.split(".")):
                raise ValueError()
            # Browser URL parsers accept abbreviated/hex IPv4 literals that
            # Python's strict ip_address intentionally does not accept.
            if not re.fullmatch(r"[A-Za-z][A-Za-z-]{1,62}", hostname.split(".")[-1]):
                raise ValueError()
        else:
            if not address.is_global:
                raise ValueError()
    except (ValueError, TypeError):
        raise ValueError(f"{field} 须为空或公开 HTTPS URL，不能含凭据或本地地址") from None
    return value


def _source(value, field):
    raw = _object(value, {"name", "url", "verification"}, field)
    if raw.get("verification") != "declared":
        raise ValueError(f"{field}.verification 必须为 declared；软件不独立验证来源")
    return {"name": _text(raw.get("name"), field + ".name", 300),
            "url": _url(raw.get("url"), field + ".url"), "verification": "declared"}


def _license(value, field):
    raw = _object(value, {"name", "url", "text"}, field)
    return {"name": _text(raw.get("name"), field + ".name", 160),
            "url": _url(raw.get("url"), field + ".url"),
            "text": _text(raw.get("text"), field + ".text", 8000)}


def _scope(value, field):
    raw = _object(value, {"population", "recording"}, field)
    result = {}
    for name, supported in (("population", {"adult", "pediatric"}),
                            ("recording", {"resting_12lead", "holter"})):
        items = raw.get(name)
        if (not isinstance(items, list) or not 1 <= len(items) <= len(supported)
                or any(not isinstance(x, str) or x not in supported for x in items)
                or len(items) != len(set(items))):
            raise ValueError(f"{field}.{name} 适用范围不受支持")
        result[name] = list(items)
    return result


def _approval(value, field):
    if not isinstance(value, str) or value not in APPROVALS:
        raise ValueError(f"{field} 审核状态不受支持")
    return value


def _review(value, field):
    raw = _object(value, {"reviewer", "reviewed_at"}, field)
    reviewer = _text(raw.get("reviewer"), field + ".reviewer", 160, empty=True)
    reviewed = _text(raw.get("reviewed_at"), field + ".reviewed_at", 40, empty=True)
    if reviewed:
        try:
            date = datetime.fromisoformat(reviewed.replace("Z", "+00:00"))
            if date.tzinfo is None:
                raise ValueError()
        except ValueError:
            raise ValueError(f"{field}.reviewed_at 须为含时区的 ISO 时间") from None
    return {"reviewer": reviewer, "reviewed_at": reviewed}


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def validate_catalog(value: dict) -> dict:
    """Reject unsafe/ambiguous input and return a complete immutable-version snapshot."""
    try:
        if len(_canonical(value).encode("utf-8")) > MAX_CATALOG_BYTES:
            raise ValueError("术语目录超过 1 MiB 大小限制")
    except (TypeError, OverflowError, RecursionError):
        raise ValueError("术语目录必须为有限 JSON 数据") from None
    raw = _object(value, {"schema_version", "namespace", "version", "sha256", "title", "description",
                          "completeness", "approval", "source", "license", "scope", "nodes"}, "catalog")
    if type(raw.get("schema_version")) is not int or raw["schema_version"] != 1:
        raise ValueError("schema_version 仅支持 1")
    if not isinstance(raw.get("completeness"), str) or raw["completeness"] not in {"example", "partial", "complete"}:
        raise ValueError("completeness 状态不受支持")
    nodes = raw.get("nodes")
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= MAX_NODES:
        raise ValueError(f"nodes 必须包含 1 至 {MAX_NODES} 个节点")
    result = {"schema_version": 1, "namespace": _identifier(raw.get("namespace"), "namespace", _NAMESPACE),
              "version": _identifier(raw.get("version"), "version", _VERSION),
              "title": _text(raw.get("title"), "title", 160),
              "description": _text(raw.get("description"), "description", 2000),
              "completeness": raw["completeness"], "approval": _approval(raw.get("approval"), "approval"),
              "source": _source(raw.get("source"), "source"), "license": _license(raw.get("license"), "license"),
              "scope": _scope(raw.get("scope"), "scope"), "nodes": []}
    lookup = {}
    for index, item in enumerate(nodes):
        field = f"nodes[{index}]"
        item = _object(item, {"stable_id", "parent_id", "kind", "label", "text", "aliases", "approval",
                              "source", "license", "scope", "deprecated", "replacement_id", "review"}, field)
        sid = _identifier(item.get("stable_id"), field + ".stable_id")
        if sid in lookup:
            raise ValueError("stable_id 重复；稳定标识须唯一")
        parent = item.get("parent_id")
        replacement = item.get("replacement_id")
        if parent is not None:
            _identifier(parent, field + ".parent_id")
        if replacement is not None:
            _identifier(replacement, field + ".replacement_id")
        kind = item.get("kind")
        if not isinstance(kind, str) or kind not in {"group", "term"}:
            raise ValueError(f"{field}.kind 不受支持")
        text = _text(item.get("text"), field + ".text", 4000, empty=kind == "group")
        if kind == "group" and text:
            raise ValueError("分组节点不能含可插入文本")
        aliases = item.get("aliases")
        if not isinstance(aliases, list) or len(aliases) > 20:
            raise ValueError("aliases 须为不超过 20 项的纯文本列表")
        aliases = [_text(a, field + ".aliases", 160) for a in aliases]
        if len(set(aliases)) != len(aliases):
            raise ValueError("aliases 不能重复")
        if type(item.get("deprecated")) is not bool:
            raise ValueError("deprecated 须为布尔值")
        if replacement is not None and (not item["deprecated"] or kind != "term"):
            raise ValueError("只有废弃词条可声明 replacement_id")
        node = {"stable_id": sid, "parent_id": parent, "kind": kind,
                "label": _text(item.get("label"), field + ".label", 160), "text": text, "aliases": aliases,
                "approval": _approval(item.get("approval"), field + ".approval"),
                "source": _source(item.get("source"), field + ".source"),
                "license": _license(item.get("license"), field + ".license"),
                "scope": _scope(item.get("scope"), field + ".scope"), "deprecated": item["deprecated"],
                "replacement_id": replacement, "review": _review(item.get("review"), field + ".review")}
        lookup[sid] = node
        result["nodes"].append(node)
    for node in result["nodes"]:
        parent = node["parent_id"]
        if parent is not None and (parent not in lookup or lookup[parent]["kind"] != "group"):
            raise ValueError("parent_id 须指向存在的分组节点")
        seen, cursor, depth = set(), node, 0
        while cursor is not None:
            if cursor["stable_id"] in seen:
                raise ValueError("术语树存在循环")
            seen.add(cursor["stable_id"])
            depth += 1
            if depth > MAX_DEPTH:
                raise ValueError(f"术语树深度不能超过 {MAX_DEPTH}")
            cursor = lookup.get(cursor["parent_id"])
        target = node["replacement_id"]
        if target is not None and (target not in lookup or target == node["stable_id"]
                                   or lookup[target]["kind"] != "term" or lookup[target]["deprecated"]):
            raise ValueError("replacement_id 须指向存在且未废弃的其他词条")
    if not any(n["kind"] == "term" for n in result["nodes"]):
        raise ValueError("目录至少应有一个词条")
    digest = sha256(_canonical(result).encode("utf-8")).hexdigest()
    supplied = raw.get("sha256")
    if supplied is not None and supplied != digest:
        raise ValueError("sha256 与目录内容不匹配")
    result["sha256"] = digest
    return result


def parse_catalog_json(content: str | bytes) -> dict:
    """Optional raw-body parser rejects duplicate JSON keys as well as node IDs."""
    if not isinstance(content, (str, bytes)) or len(content.encode("utf-8") if isinstance(content, str) else content) > MAX_CATALOG_BYTES:
        raise ValueError("术语目录超过大小限制")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("JSON 字段重复")
            result[key] = value
        return result
    try:
        return validate_catalog(json.loads(content, object_pairs_hook=pairs,
                                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("非有限 JSON 数值"))))
    except (json.JSONDecodeError, UnicodeError, RecursionError):
        raise ValueError("目录须为合法 JSON") from None


def get_builtin_catalog() -> dict:
    path = Path(__file__).resolve().parent.parent / "static" / "terminology" / "builtin-draft-v1.json"
    return parse_catalog_json(path.read_bytes())


def catalog_summary(catalog: dict, *, builtin=False) -> dict:
    return {key: deepcopy(catalog[key]) for key in ("namespace", "version", "sha256", "title", "description",
             "completeness", "approval", "source", "license", "scope")} | {
        "builtin": builtin, "node_count": len(catalog["nodes"]),
        "term_count": sum(n["kind"] == "term" for n in catalog["nodes"]),
        "verification": "declared", "publication_scope": "local"}


def normalize_terminology_usages(value) -> list[dict]:
    """Validate snapshots without looking up a current catalog or rewriting text."""
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 500:
        raise ValueError("terminology_usages 须为不超过 500 项的记录列表")
    result, seen = [], set()
    keys = {"usage_id", "namespace", "version", "catalog_hash", "stable_id", "label", "inserted_text",
            "approval", "source", "license", "scope", "review", "inserted_at"}
    for raw in value:
        raw = _object(raw, keys, "terminology_usages")
        uid = _identifier(raw.get("usage_id"), "usage_id")
        if uid in seen:
            raise ValueError("usage_id 重复")
        seen.add(uid)
        digest = raw.get("catalog_hash")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("catalog_hash 格式不受支持")
        inserted = _review({"reviewer": "", "reviewed_at": raw.get("inserted_at")}, "inserted_at")["reviewed_at"]
        if not inserted:
            raise ValueError("inserted_at 不能为空")
        result.append({"usage_id": uid, "namespace": _identifier(raw.get("namespace"), "namespace", _NAMESPACE),
                       "version": _identifier(raw.get("version"), "version", _VERSION), "catalog_hash": digest,
                       "stable_id": _identifier(raw.get("stable_id"), "stable_id"),
                       "label": _text(raw.get("label"), "label", 160),
                       "inserted_text": _text(raw.get("inserted_text"), "inserted_text", 4000),
                       "approval": _approval(raw.get("approval"), "approval"),
                       "source": _source(raw.get("source"), "source"), "license": _license(raw.get("license"), "license"),
                       "scope": _scope(raw.get("scope"), "scope"),
                       "review": _review(raw.get("review", {"reviewer": "", "reviewed_at": ""}), "review"),
                       "inserted_at": inserted})
    return result


class TerminologyStore:
    """Local immutable catalog versions, isolated from patient and clinical tables."""
    def __init__(self, storage):
        self.storage = storage
        self._builtin = get_builtin_catalog()
        with storage.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS terminology_catalog_state (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), revision INTEGER NOT NULL);
                INSERT OR IGNORE INTO terminology_catalog_state(singleton,revision) VALUES(1,0);
                CREATE TABLE IF NOT EXISTS terminology_catalogs (
                    namespace TEXT NOT NULL, version TEXT NOT NULL, sha256 TEXT NOT NULL,
                    payload TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(namespace,version));
            """)

    @staticmethod
    def _revision(db):
        return int(db.execute("SELECT revision FROM terminology_catalog_state WHERE singleton=1").fetchone()[0])

    @staticmethod
    def _stored_catalog(row):
        catalog = parse_catalog_json(row["payload"])
        if (catalog["namespace"], catalog["version"], catalog["sha256"]) != (row["namespace"], row["version"], row["sha256"]):
            raise ValueError("本地目录身份或内容散列不一致，请核对该目录文件")
        return catalog

    def list_catalogs(self) -> dict:
        with self.storage.connect() as db:
            revision = self._revision(db)
            rows = db.execute("SELECT namespace,version,sha256,payload FROM terminology_catalogs ORDER BY created_at,namespace,version").fetchall()
        items = [catalog_summary(self._builtin, builtin=True)]
        items.extend(catalog_summary(self._stored_catalog(r)) for r in rows)
        return {"catalog_revision": revision, "items": items}

    def get_catalog(self, namespace: str, version: str, sha256: str | None = None) -> dict | None:
        _identifier(namespace, "namespace", _NAMESPACE)
        _identifier(version, "version", _VERSION)
        if sha256 is not None and (not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256)):
            raise ValueError("hash 须为 SHA-256 小写十六进制")
        if (namespace, version) == (self._builtin["namespace"], self._builtin["version"]):
            catalog = self._builtin
        else:
            with self.storage.connect() as db:
                row = db.execute("SELECT namespace,version,sha256,payload FROM terminology_catalogs WHERE namespace=? AND version=?", (namespace, version)).fetchone()
            if row is None:
                return None
            catalog = self._stored_catalog(row)
        return deepcopy(catalog) if sha256 is None or catalog["sha256"] == sha256 else None

    def import_catalog(self, catalog: dict, expected_catalog_revision: int, *, confirm=False, preview_hash=None) -> dict:
        validated = validate_catalog(catalog)
        if type(expected_catalog_revision) is not int or expected_catalog_revision < 0:
            raise ValueError("expected_catalog_revision 须为非负整数")
        if type(confirm) is not bool:
            raise ValueError("confirm 须为布尔值")
        if confirm and preview_hash != validated["sha256"]:
            raise ValueError("明确确认需要与预览内容一致的 preview_hash")
        with self.storage.connect() as db:
            # The revision comparison and insert share one writer transaction.
            db.execute("BEGIN IMMEDIATE")
            revision = self._revision(db)
            if revision != expected_catalog_revision:
                raise TerminologyConflict("目录列表已变化，请重新预览并确认", revision)
            existing = self.get_catalog(validated["namespace"], validated["version"])
            if existing is not None and existing["sha256"] != validated["sha256"]:
                raise TerminologyConflict("同一命名空间和版本不能覆盖；请声明新版本", revision)
            if confirm and existing is None:
                db.execute("INSERT INTO terminology_catalogs(namespace,version,sha256,payload,created_at) VALUES(?,?,?,?,?)",
                           (validated["namespace"], validated["version"], validated["sha256"],
                            _canonical(validated), datetime.now(timezone.utc).isoformat(timespec="seconds")))
                revision += 1
                db.execute("UPDATE terminology_catalog_state SET revision=? WHERE singleton=1", (revision,))
        return {"preview_only": not confirm, "catalog_revision": revision, "catalog": validated,
                "summary": catalog_summary(validated, builtin=validated["namespace"] == self._builtin["namespace"]
                                           and validated["version"] == self._builtin["version"]),
                "preview_hash": validated["sha256"], "warnings": [
                    "来源、许可、适用范围、完整性及审核状态按导入声明展示；软件未独立验证。",
                    "本地发布仅让目录可选，不代表医生核准；分组仅为查找界面，不是医学本体。"]}
