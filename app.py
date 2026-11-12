from __future__ import annotations

import argparse
import base64
import binascii
import copy
import hmac
import ipaddress
import json
import math
import gzip
import os
import socket
import threading
import webbrowser
from hashlib import sha256
from pathlib import Path

from flask import Flask, abort, g, jsonify, render_template, request, send_file, session
from waitress import serve
from werkzeug.middleware.proxy_fix import ProxyFix

from ecg_core import APP_NAME, APP_VERSION, SAMPLE_RATE
from ecg_core.config import load_config, platform_info, resource_root, resolve_data_root, user_data_root, writable_data_dir
from ecg_core.ebi import (
    SCATTER_MODES,
    beat_details,
    heart_rate_trend,
    hrv,
    list_events,
    metrics as ebi_metrics,
    rr_visuals,
    scatter_points,
    select_scatter_points,
    visible_beats,
)
from ecg_core.report_pdf import build_report_pdf
from ecg_core.hrv_analysis import analyze_hrv, analyze_hrv_review
from ecg_core.hrv_review import HrvReviewStore
from ecg_core.rr_review import build_rr_index, query_rr, resolve_rr_target, RRReviewConflict
from ecg_core.terminology import TerminologyStore, TerminologyConflict
from ecg_core.report_layout import prepare_strip, report_statistics, af_representatives
from ecg_core.clinical_analysis import build_index, query_index, hrv_windows, validate_report
from ecg_core.rr_report import deduplicate_rr_selections
from ecg_core.clinical_query_cache import ClinicalQueryCache, ClinicalQueryBusy, WaveformBeatCache, ClinicalEvidenceCache
from ecg_core.storage import normalize_report_composition
from ecg_core.repository import CASE_ID_RE, CaseNotFound, CaseRepository
from ecg_core.storage import Storage
from ecg_core.review_workflow import ReportConflict
from ecg_core.analysis_provenance import AnalysisRuntime, digest as provenance_digest
from ecg_core.source_identity import SourceUnavailable, SourceInvalid, SourceReadError, read_locked_sources
from ecg_core.workspace_backup import (BackupError, BACKUP_NAME, create_backup,
    verify_backup, list_backups, recovery_epoch)
from ecg_core.beat_editor import BeatEditorStore, EditedRecords, TYPES, apply_operation, propose_qrs, integer
from ecg_core.ebi import load_records
from ecg_core.stt import build_stt_review
from ecg_core.waveform import read_event_waveform, ALL_LEADS, read_waveform, read_waveform_strips, read_waveform_overview
from ecg_core.overview import RhythmReviewStore, initial_episodes, density
from ecg_core.review_candidates import prepare_candidate, augment_index, rr_distribution, canonical
from ecg_core.report_evidence import (attach_reviews, longest_event, evidence_descriptor,
    presentation as evidence_presentation, digest as evidence_digest, check_read_wave,
    assert_caption as assert_evidence_caption, used_in_output)

ACTOR = "演示分析医生"
READONLY_POST_ENDPOINTS = frozenset({"case_open", "scatter_selection_endpoint", "waveform_strips_endpoint", "event_waveforms", "waveform_density", "advanced_analysis_endpoint", "rr_locate_endpoint", "stt_range_endpoint", "report_evidence_preview"})


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _basic_credentials(value: str) -> tuple[str, str] | None:
    """Decode a Basic Authorization value without accepting malformed base64."""
    scheme, separator, token = value.partition(" ")
    if not separator or scheme.lower() != "basic" or not token:
        return None
    try:
        decoded = base64.b64decode(token, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    if ":" not in decoded:
        return None
    return tuple(decoded.split(":", 1))


def _secure_text_equal(left: str, right: str) -> bool:
    """Compare credentials in constant time, including non-ASCII values."""
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def _masked(value: str, keep: int = 1) -> str:
    if not value:
        return ""
    if len(value) <= keep:
        return "*"
    return value[:keep] + "*" * min(4, len(value) - keep)


def _bool_arg(name: str, default: bool = False) -> bool:
    value = request.args.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _masked_report_case(source: dict) -> dict:
    """Return a detached report model with direct identifiers removed."""
    item = copy.deepcopy(source)
    item["metadata"]["name"] = "已遮蔽"
    item["metadata"]["patient_id"] = "已遮蔽"
    item["metadata"]["requesting_physician"] = "已遮蔽"
    return item


def _number_arg(name: str, default, cast=float, minimum=None, maximum=None):
    try:
        value = cast(request.args.get(name, default))
    except (TypeError, ValueError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _json_object() -> dict:
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError("请求正文必须为 JSON 对象")
    return payload


def _coerce_json_number(value, name: str, minimum: float, maximum: float, *, integer: bool = False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须为有效数字")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} 超出允许范围")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} 必须为有效数字") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} 必须为有效数字")
    if integer and int(number) != number:
        raise ValueError(f"{name} 必须为整数")
    return int(number) if integer else number


def _json_number(payload: dict, name: str, default, minimum: float, maximum: float, *, integer: bool = False):
    return _coerce_json_number(payload.get(name, default), name, minimum, maximum, integer=integer)


def _waveform_leads_arg() -> list[str]:
    """Never silently replace a requested lead with a different waveform."""
    selected = [value.strip() for value in request.args.get('leads', 'II,V1,V5').split(',')]
    if not 1 <= len(selected) <= 12 or any(value not in ALL_LEADS for value in selected):
        raise ValueError('请指定1–12个支持的波形导联，不能留空或包含未知导联')
    if len(set(selected)) != len(selected):
        raise ValueError('波形导联不能重复')
    return selected


def _free_port(preferred: int) -> int:
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    return 0


def create_app(data_root: str | os.PathLike[str] | None = None, db_path: str | os.PathLike[str] | None = None, testing: bool = False) -> Flask:
    base = resource_root()
    demo_password = os.environ.get("ECG_DEMO_PASSWORD", "")
    demo_username = os.environ.get("ECG_DEMO_USERNAME", "demo")
    demo_readonly = _env_bool("ECG_DEMO_READONLY")
    trust_proxy_headers = _env_bool("ECG_TRUST_PROXY_HEADERS")
    session_cookie_secure = _env_bool("ECG_SESSION_COOKIE_SECURE", default=trust_proxy_headers)
    allow_phi = _env_bool("ECG_ALLOW_PHI", default=not (demo_readonly or bool(demo_password))) and not demo_readonly
    app = Flask(
        __name__,
        template_folder=str(base / "templates"),
        static_folder=str(base / "static"),
    )
    app.config.update(
        TESTING=testing,
        WINDOWS_REQUEST_SOURCE_LEASES=True,
        JSON_AS_ASCII=False,
        MAX_CONTENT_LENGTH=4 * 1024 * 1024,
        SECRET_KEY=os.environ.get("ECG_SECRET_KEY") or os.urandom(32),
        DEMO_AUTH_ENABLED=bool(demo_password),
        DEMO_READONLY=demo_readonly,
        ALLOW_PHI=allow_phi,
        TRUST_PROXY_HEADERS=trust_proxy_headers,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=session_cookie_secure,
    )
    if trust_proxy_headers:
        # Exactly one trusted deployment proxy is expected to set these headers.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
    resolved_root = resolve_data_root(data_root)
    repository = CaseRepository(resolved_root)
    storage = Storage(Path(db_path) if db_path else writable_data_dir() / "cardioinsight.db")
    app.extensions["case_repository"] = repository
    app.extensions["storage"] = storage
    workspace_epoch = recovery_epoch(storage.path)
    runtime = AnalysisRuntime(recovery_epoch=workspace_epoch)
    app.extensions['analysis_runtime'] = runtime
    clinical_query_cache = ClinicalQueryCache()
    app.extensions['clinical_query_cache'] = clinical_query_cache
    waveform_beat_cache = WaveformBeatCache()
    hrv_evidence_cache = ClinicalEvidenceCache()
    app.extensions['hrv_evidence_cache'] = hrv_evidence_cache
    hrv_measurement_cache = ClinicalEvidenceCache(max_entries=4,max_units=32*1024*1024)
    app.extensions['hrv_measurement_cache'] = hrv_measurement_cache
    hrv_event_cache = ClinicalEvidenceCache(max_entries=4,max_units=16*1024*1024)
    app.extensions['hrv_event_cache'] = hrv_event_cache
    app.extensions['waveform_beat_cache'] = waveform_beat_cache
    # Only detached read projections are retained. Never share a mutable
    # EditedRecords with writes, analyses, or another request.
    read_evidence_cache = ClinicalEvidenceCache(max_entries=24, max_units=24*1024*1024)
    app.extensions['read_evidence_cache'] = read_evidence_cache
    backup_directory = storage.path.parent / 'backups'
    backup_lock = threading.Lock()
    app.extensions['backup_lock'] = backup_lock

    @app.before_request
    def access_guards():
        if demo_password and request.endpoint != "health":
            credentials = _basic_credentials(request.headers.get("Authorization", ""))
            authenticated = False
            if credentials is not None:
                username, password = credentials
                # Evaluate both comparisons so a wrong username does not skip password work.
                username_ok = _secure_text_equal(username, demo_username)
                password_ok = _secure_text_equal(password, demo_password)
                authenticated = username_ok and password_ok
            if not authenticated:
                response = jsonify({"error": "需要演示访问凭据"})
                response.status_code = 401
                response.headers["WWW-Authenticate"] = 'Basic realm="CardioInsight Demo", charset="UTF-8"'
                return response

        if app.config["DEMO_READONLY"] and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if request.method != "POST" or request.endpoint not in READONLY_POST_ENDPOINTS:
                return jsonify({"error": "公网演示为只读模式，不允许保存或修改数据"}), 403

        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not app.config["TESTING"]:
            if request.headers.get("X-CardioInsight-Request") != "1":
                return jsonify({"error": "写操作仅接受本地工作站界面请求"}), 403
        if workspace_epoch and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if request.headers.get('X-CardioInsight-Workspace') != workspace_epoch:
                return jsonify({'error': '工作区已从备份恢复，旧页面不能继续提交；请重新打开网页并复核恢复的内容'}), 409

    @app.before_request
    def lease_case_sources_for_request():
        # Temporary sharing flags, never filesystem permission changes. The
        # disabled path retains the former fresh-content validation for CI A/B.
        if os.name != 'nt' or not app.config['WINDOWS_REQUEST_SOURCE_LEASES']:
            return
        case_id = (request.view_args or {}).get('case_id')
        if not isinstance(case_id, str) or not CASE_ID_RE.fullmatch(case_id) or not resolved_root:
            return
        root = resolved_root.resolve()
        folder = (root / case_id).resolve()
        if folder.parent != root or not folder.is_dir():
            return  # Existing case_or_404 retains its normal rejection.
        paths = (folder / 'data' / (case_id + '.DATA'),
                 folder / 'DGS' / (case_id + '.EBI'),
                 folder / 'report_image' / (case_id + '_1.LPS'))
        context = read_locked_sources(paths, fresh_content=True)
        try:
            context.__enter__()
        except OSError as error:
            raise SourceReadError('原始文件正在使用或不可读取，请确认来源完整且稳定后重试。') from error
        g.case_source_read_context = context
        g.case_source_read_paths = {str(path.resolve()) for path in paths}

    @app.teardown_request
    def release_case_source_request_lease(error=None):
        context = g.pop('case_source_read_context', None)
        if context is not None:
            context.__exit__(None, None, None)
        g.pop('case_source_read_paths', None)

    def denied_source_write(error):
        if not isinstance(error, PermissionError):
            return False
        paths = g.get('case_source_read_paths', set())
        return any(value and str(Path(value).resolve()) in paths
                   for value in (getattr(error, 'filename', None), getattr(error, 'filename2', None)))

    def include_phi_authorized() -> bool:
        return app.config["ALLOW_PHI"] and _bool_arg("include_phi") and bool(session.get("phi_authorized"))

    def case_with_overrides(source: dict) -> dict:
        item = copy.deepcopy(source)
        override = storage.get_patient_override(source["case_id"])
        active = override.pop("active", True) if override else True
        item["metadata"].update(override)
        item["active"] = active
        return item

    def case_or_404(case_id: str) -> dict:
        try:
            case = repository.get_case(case_id)
            basis = runtime.basis(case)
            previous = storage.get_analysis_basis(case_id)
            compatibility = app.extensions.get('performance_compatibility')
            if (previous and previous.get('digest')!=basis.get('digest')
                    and compatibility and not app.config['DEMO_READONLY']
                    and compatibility.build_allowed(previous,basis)):
                snapshot=editor.snapshot(case_id)
                annotations=storage.list_annotations(case_id)
                prior_report=storage.get_report(case_id,case.get('conclusion',''))
                revision=storage.get_review(case_id)['revision']
                certificate=compatibility.resolve(case,previous,basis,build_feed(case,snapshot['document']),
                              annotations,prior_report,revision,snapshot['revision'])
                if certificate:
                    def current_source():
                        if runtime.direct_basis(case)['digest']!=certificate['execution_basis']:
                            raise ReportConflict('升级核对期间原始数据已变化')
                    storage.record_compatible_implementation(case_id,certificate,ACTOR,current_source)
                    runtime.bind_compatible_basis(case,certificate)
                    basis=runtime.basis(case)
            storage.sync_analysis_basis(case_id, basis, ACTOR, app.config['DEMO_READONLY'])
            return case
        except CaseNotFound:
            abort(404, description="病例不存在或数据不完整")

    def assert_source_basis(case, expected):
        if runtime.basis(case)['digest'] != expected['digest']:
            raise ReportConflict('计算期间原始文件或算法依据已变化，请重新载入病例并复核')

    def clinical_read_basis(case, expected=None):
        value = dict(analysis_basis=runtime.basis(case)['digest'],
                     analysis_revision=storage.get_review(case['case_id'])['revision'])
        if expected is not None:
            for key, current in value.items():
                if key in expected and str(expected[key]) != str(current):
                    raise ReportConflict('波形或事件依据已变化，请重新加载后复核')
        return value

    def clinical_response(case, build, expected=None, *, nested=False):
        """Optimistic read validation; never label a mixed computation as current."""
        basis = clinical_read_basis(case, request.args if expected is None else expected)
        result = build()
        clinical_read_basis(case, basis)
        return jsonify({**result, **({'clinical_identity': basis} if nested else basis)})

    @app.get('/api/cases/<case_id>/analysis-basis')
    def analysis_basis_endpoint(case_id):
        return jsonify(clinical_read_basis(case_or_404(case_id), request.args))

    editor = BeatEditorStore(storage)
    rhythms = RhythmReviewStore(storage)
    hrv_reviews = HrvReviewStore(storage)
    from ecg_core.performance_compatibility import PerformanceCompatibility
    app.extensions['performance_compatibility']=PerformanceCompatibility(base,runtime,storage,editor)

    terminology = TerminologyStore(storage)
    app.extensions['hrv_reviews'] = hrv_reviews
    app.extensions['terminology'] = terminology

    class RRIndexCache(ClinicalQueryCache):
        @staticmethod
        def _weight(index):
            return len(index['intervals'])  # targets retain references to the same rows
    rr_cache = RRIndexCache(max_units=400_000)
    app.extensions['rr_review_cache'] = rr_cache

    class ReviewIdentityCache(ClinicalQueryCache):
        @staticmethod
        def _weight(index): return 1
    review_identity_cache = ReviewIdentityCache(max_units=2)

    def linked_read_identity(case, expected=None):
        """Chart projections retain both review and edited-beat provenance."""
        if expected and 'case_id' in expected and expected['case_id'] != case['case_id']:
            raise ReportConflict('图表请求来自另一病例，请重新读取')
        basis = clinical_read_basis(case, expected)
        revision = editor.snapshot(case['case_id'])['revision']
        expected = expected or {}
        for key in ('beat_revision', 'revision'):
            if key in expected and (type(expected[key]) is not int or expected[key] != revision):
                raise ReportConflict('心搏版本已变化，请重新读取当前图表')
        clinical_read_basis(case, basis)
        return {**basis, 'beat_revision': revision, 'case_id': case['case_id']}

    def linked_query_identity(case):
        expected = {name:request.args[name] for name in
            ('case_id','analysis_basis','analysis_revision') if name in request.args}
        for name in ('beat_revision','revision'):
            if name in request.args:
                value=request.args[name]
                if not value.isascii() or not value.isdecimal():raise ValueError('逐搏修订须为非负整数')
                expected[name]=int(value)
        return linked_read_identity(case,expected)

    def strict_query_number(name, default, minimum, maximum):
        try: value=float(request.args.get(name,default))
        except (TypeError,ValueError,OverflowError):raise ValueError(f'{name} 必须为有效数字') from None
        return _coerce_json_number(value,name,minimum,maximum)

    def read_evidence(case, variant, build):
        identity = linked_read_identity(case)
        key = (case['case_id'], identity['analysis_basis'], identity['analysis_revision'],
               identity['beat_revision'], request.args.get('analysis') == 'edited', variant)
        def checked():
            value = build()
            linked_read_identity(case, identity)
            return value
        result = read_evidence_cache.read(key, checked)
        linked_read_identity(case, identity)
        return result

    def clinical_index_key(case, identity, annotations=None):
        # Report acknowledgements refresh event metadata without changing the
        # signal-analysis identity or cancelling unrelated waveform reads.
        return (case['case_id'], identity['analysis_basis'], identity['analysis_revision'],
                provenance_digest(annotations if annotations is not None else storage.list_annotations(case['case_id'])),
                canonical(storage.list_candidates(case['case_id'])),
                evidence_digest(storage.list_report_evidence(case['case_id'])))

    def clinical_projection(case, project, annotations=None):
        identity = linked_read_identity(case)
        key = clinical_index_key(case, identity, annotations)

        def ensure_current():
            linked_read_identity(case, identity)
            if clinical_index_key(case, identity) != key:
                raise ReportConflict("标注或报告依据已变化，请重新读取")

        def checked():
            index = clinical_index(case)
            ensure_current()
            return index
        result = clinical_query_cache.project(key, checked, project)
        ensure_current()
        return result

    def build_feed(case, document):
        feed = EditedRecords(load_records(case["paths"]["ebi"]), copy.deepcopy(document),
            storage.list_beat_overrides(case["case_id"]), case["technical"]["duration_seconds_raw"])
        from ecg_core.rr_quality import annotation_exclusions
        feed.excluded_rhythm_intervals = annotation_exclusions(storage.list_annotations(case["case_id"]))
        return feed

    def feed_snapshot(case, expected=None, document=None):
        identity = linked_read_identity(case, expected)
        if document is None:
            document = editor.snapshot(case['case_id'])['document']
        key = (case['case_id'], identity['analysis_basis'], identity['analysis_revision'],
               identity['beat_revision'], provenance_digest(document))
        def checked():
            feed = build_feed(case, document).prepare_read_snapshot()
            linked_read_identity(case, identity)
            return feed
        return identity, key, checked

    def edited_feed(case, document=None):
        # Reuse construction only for read routes. Each request receives fresh
        # rows, lookup maps, annotations and document; writes never borrow them.
        readonly = request.method == 'GET' or (request.method == 'POST'
                    and request.endpoint in READONLY_POST_ENDPOINTS)
        if not readonly:
            return build_feed(case, document if document is not None
                              else editor.snapshot(case['case_id'])['document'])
        identity, key, checked = feed_snapshot(case, document=document)
        feeds = getattr(request, '_ecg_read_feeds', None)
        if feeds is not None and key in feeds:
            return feeds[key]
        feed = waveform_beat_cache.clone(key, checked)
        linked_read_identity(case, identity)
        if feeds is None:
            feeds = request._ecg_read_feeds = {}
        feeds[key] = feed
        return feed

    def analysis_path(case):
        return edited_feed(case) if request.args.get("analysis") == "edited" else Path(case["paths"]["ebi"])

    def waveform_labels(case, basis, windows, include_markers=False, force_edited=False):
        """Reuse only private label indexes; samples are still read from DATA.

        Read analyses clone the snapshot; every write constructs a fresh feed.
        Returned windows are detached so callers cannot mutate this cache.
        """
        def project(feed):
            output = []
            for start, duration in windows:
                rows = visible_beats(feed, start, duration)
                if include_markers and hasattr(feed, 'markers'):
                    rows += [r for r in feed.markers if start <= r['time_s'] <= start + duration]
                    rows.sort(key=lambda r: r['sample_index'])
                output.append(rows)
            return output
        if not force_edited and request.args.get('analysis') != 'edited':
            return project(Path(case['paths']['ebi']))
        identity, key, checked = feed_snapshot(case, basis)
        result = waveform_beat_cache.project(key, checked, project)
        linked_read_identity(case, identity)
        return result

    def present_case(source: dict, include_phi: bool, detailed: bool = False) -> dict:
        item = case_with_overrides(source)
        item["phi_masked"] = not include_phi
        if not include_phi:
            item["metadata"]["name"] = _masked(item["metadata"].get("name", ""))
            patient_id = item["metadata"].get("patient_id", "")
            item["metadata"]["patient_id"] = ("*" * max(0, len(patient_id) - 4) + patient_id[-4:]) if patient_id else ""
            item["metadata"]["requesting_physician"] = _masked(item["metadata"].get("requesting_physician", ""))
        item.pop("paths", None)
        item["report_image_urls"] = (
            [f"/api/cases/{item['case_id']}/source-report/page/{index + 1}?include_phi=1" for index in range(item["technical"]["report_pages"])]
            if include_phi else []
        )
        item["generated_report_url"] = f"/api/cases/{item['case_id']}/report.pdf"
        item["review_workflow"] = storage.get_review(source["case_id"])
        if detailed:
            duration = source["technical"]["duration_seconds_raw"]
            item["calculated"] = read_evidence(source, ('case-metrics',),
                lambda: ebi_metrics(analysis_path(source), duration))
            editor_value = editor.snapshot(source["case_id"]) if request.args.get("analysis") == "edited" else None
            item["analysis_revision"] = editor_value["revision"] if editor_value is not None else None
            if item["analysis_revision"] is not None:
                item["beat_editor_history"] = {"revision": editor_value["revision"],
                    "can_undo": editor_value["can_undo"], "can_redo": editor_value["can_redo"]}
                document = editor_value["document"]
                item["beat_editor_settings"] = document["settings"]
                item["manual_longest"] = read_evidence(source, ('manual-longest', document['longest_id']),
                    lambda: next((r for r in edited_feed(source).beats
                                  if r['id'] == document['longest_id']), None)) if document['longest_id'] else None
            item["report_workflow"] = storage.get_report(source["case_id"], source["conclusion"])
            item["annotations"] = storage.list_annotations(source["case_id"])
        return item

    @app.after_request
    def security_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'self'; form-action 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'"
        if request.is_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        # Preserve the complete JSON and no-store policy. This runs after the
        # local presentation wrapper has masked identities and added aliases.
        if (request.method == 'GET' and request.endpoint in
                {'hrv_analysis_endpoint', 'hrv_review_get'}
                and response.status_code == 200 and response.is_json
                and not response.headers.get('Content-Encoding')):
            response.vary.add('Accept-Encoding')
            if request.accept_encodings['gzip'] > 0:
                body = response.get_data()
                if len(body) >= 32768:
                    packed = gzip.compress(body, compresslevel=1, mtime=0)
                    if len(packed) < len(body):
                        response.set_data(packed)
                        response.headers['Content-Encoding'] = 'gzip'
        return response

    @app.errorhandler(404)
    def not_found(error):
        return jsonify({"error": getattr(error, "description", "not found")}), 404

    @app.errorhandler(ValueError)
    def value_error(error):
        return jsonify({"error": str(error)}), 400

    @app.errorhandler(ReportConflict)
    def report_conflict(error):
        return jsonify({"error": str(error), "code": "report_conflict"}), 409

    @app.errorhandler(RRReviewConflict)
    def rr_conflict(error):
        return jsonify(error=str(error), code='rr_scope_conflict'), 409

    @app.errorhandler(TerminologyConflict)
    def terminology_conflict(error):
        return jsonify(error=str(error), code='terminology_conflict', current_revision=error.current_revision), 409

    @app.errorhandler(SourceUnavailable)
    def source_unavailable(error):
        return jsonify({"error": str(error), "code": "source_not_local"}), 503

    @app.errorhandler(SourceInvalid)
    def source_invalid(error):
        return jsonify({"error": str(error), "code": error.code}), 422

    @app.errorhandler(PermissionError)
    def denied_source_write_error(error):
        if denied_source_write(error):
            return report_conflict(ReportConflict('计算期间原始文件写入被拒绝，请确认来源稳定后重新读取；未生成导出结果。'))
        raise error  # Unrelated DB/program errors keep their original handling.

    @app.errorhandler(SourceReadError)
    def source_read_error(error):
        if denied_source_write(error.__cause__):
            return report_conflict(ReportConflict('计算期间原始文件写入被拒绝，请确认来源稳定后重新读取；未生成导出结果。'))
        return jsonify({"error": str(error), "code": error.code}), 503

    @app.errorhandler(ClinicalQueryBusy)
    def clinical_query_busy(error):
        return jsonify({'error': str(error), 'code': 'clinical_query_busy'}), 503

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            app_name=APP_NAME,
            app_version=APP_VERSION,
            app_version_short=APP_VERSION.split("-", 1)[0],
            demo_readonly=app.config["DEMO_READONLY"],
            allow_phi=app.config["ALLOW_PHI"],
        )

    @app.get("/api/health")
    def health():
        cases, issues = repository.scan_cases()
        return jsonify({
            "status": ("data_issues" if issues else "ok") if resolved_root else "data_root_missing",
            "version": APP_VERSION,
            "case_count": len(cases),
            "unavailable_case_count": len(issues),
            "data_root_found": bool(resolved_root),
            "demo_readonly": app.config["DEMO_READONLY"],
            "allow_phi": app.config["ALLOW_PHI"],
            "workspace_epoch": workspace_epoch,
            "evidence_continuity": app.extensions["performance_compatibility"].diagnostics(),
        })

    @app.get("/api/dashboard")
    def dashboard():
        include_phi = include_phi_authorized()
        sources, issues = repository.scan_cases()
        cases = [present_case(case, include_phi) for case in sources]
        totals = {
            "cases": len(cases),
            "recording_hours": round(sum(case["technical"]["duration_seconds_raw"] for case in cases) / 3600, 1),
            "beats": sum(case["summary"].get("total_beats") or 0 for case in cases),
            "pending_reports": sum(storage.get_report(case["case_id"], case["conclusion"])["status"] != "reviewed" for case in sources),
        }
        return jsonify({"totals": totals, "cases": cases, "source_issues": issues, "privacy": {"phi_visible": include_phi}})

    @app.get("/api/cases")
    def cases():
        include_phi = include_phi_authorized()
        show_deleted = _bool_arg("show_deleted")
        sources, issues = repository.scan_cases()
        items = [present_case(case, include_phi) for case in sources]
        if not show_deleted:
            items = [item for item in items if item["active"]]
        return jsonify({"items": items, "total": len(items), "source_issues": issues})

    @app.get("/api/cases/<case_id>")
    def case_detail(case_id: str):
        case = case_or_404(case_id)
        # Keep the legacy editor revision separate from the broader review identity.
        return clinical_response(case, lambda: present_case(case, include_phi_authorized(), detailed=True), nested=True)

    def stt_signal_inputs(case, expected):
        basis = linked_read_identity(case, expected)
        editor_value = editor.snapshot(case['case_id'])
        feed = edited_feed(case, editor_value["document"])
        overrides = storage.list_beat_overrides(case['case_id'])
        override_signature = ",".join(f"{item['sample_index']}:{item['class_code']}" for item in overrides)
        revision = f"editor-{editor_value['revision']}|overrides-{override_signature or 'none'}"
        return basis, feed, revision

    def stt_trends(case, expected):
        # HRV requests only trends. Keep exact source/beat guards while copying
        # just the requested cache projection, not the full ST-T HTTP contract.
        from ecg_core.stt import analyze_stt
        basis, feed, revision = stt_signal_inputs(case, expected)
        result = analyze_stt(case["paths"]["data"], feed.records,
            case["technical"]["duration_seconds_raw"], analysis_revision=revision,
            project=lambda analysis: analysis.get('trends', {}).get('leads', {}))
        linked_read_identity(case, basis)
        return result

    def stt_candidate_projection(case, expected):
        from ecg_core.stt import analyze_stt
        basis, feed, revision = stt_signal_inputs(case, expected)
        result = analyze_stt(case["paths"]["data"], feed.records,
            case["technical"]["duration_seconds_raw"], analysis_revision=revision,
            project=lambda analysis: {
                'analysis': {'algorithm_version': analysis['algorithm_version']},
                'automatic_candidates': {'items': analysis['candidates']},
            })
        linked_read_identity(case, basis)
        return result

    @app.get("/api/cases/<case_id>/stt-review")
    def stt_review(case_id: str):
        case = case_or_404(case_id)
        expected = dict(request.args)
        if 'beat_revision' in expected:
            value = expected['beat_revision']
            if not value.isascii() or not value.isdecimal():
                raise ValueError('逐搏修订须为非负整数')
            expected['beat_revision'] = int(value)
        basis, feed, revision = stt_signal_inputs(case, expected)
        result = build_stt_review(
            case.get("conclusion", ""), case["paths"]["data"], feed.records,
            case["technical"]["duration_seconds_raw"], analysis_revision=revision,
        )
        linked_read_identity(case, basis)
        result['review_records']=[a for a in stt_annotation_items(case) if a.get('details',{}).get('kind') in ('ST','ST_REVIEW_NOTE')]
        return jsonify({**result, **basis})

    @app.patch("/api/cases/<case_id>/patient")
    def patient_update(case_id: str):
        case_or_404(case_id)
        return jsonify(storage.save_patient_override(case_id, _json_object(), ACTOR))

    @app.post("/api/privacy/view")
    def privacy_view():
        if not app.config["ALLOW_PHI"]:
            return jsonify({"error": "公网演示不提供可识别健康信息"}), 403
        payload = _json_object()
        enabled = payload.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("enabled 必须为布尔值")
        if enabled:
            session["phi_authorized"] = True
            storage.audit(ACTOR, "privacy.phi_view", detail="用户主动显示可识别信息")
        else:
            session.pop("phi_authorized", None)
            storage.audit(ACTOR, "privacy.phi_hide", detail="用户恢复身份信息遮蔽")
        return jsonify({"ok": True, "enabled": enabled})

    @app.post("/api/cases/<case_id>/open")
    def case_open(case_id: str):
        case_or_404(case_id)
        storage.audit(ACTOR, "case.open", case_id)
        return jsonify({"ok": True})

    @app.get("/api/cases/<case_id>/waveform")
    def waveform(case_id: str):
        case = case_or_404(case_id)
        basis = clinical_read_basis(case, request.args)
        start = _number_arg("start", 0, float, 0)
        duration = _number_arg("duration", 10, float, 1, 120)
        leads = _waveform_leads_arg()
        max_points = _number_arg("max_points", 4000, int, 200, 12000)
        filtered = request.args.get("filter", "display") != "raw"
        payload = read_waveform(Path(case["paths"]["data"]), start, duration, leads, max_points, filtered)
        payload["beats"] = waveform_labels(case, basis,
            [(payload["start_s"], payload["duration_s"])], include_markers=True)[0]
        payload["annotations"] = [
            annotation for annotation in storage.list_annotations(case_id)
            if payload["start_s"] * SAMPLE_RATE <= annotation["sample_index"] <= (payload["start_s"] + payload["duration_s"]) * SAMPLE_RATE
        ]
        clinical_read_basis(case, basis)
        return jsonify({**payload, **basis})

    @app.get('/api/cases/<case_id>/waveform-overview')
    def waveform_overview(case_id):
        case=case_or_404(case_id); identity=linked_read_identity(case,request.args)
        result=read_waveform_overview(Path(case['paths']['data']),['II','V1','V5'],_number_arg('bins',1000,int,50,1600))
        linked_read_identity(case,identity)
        return jsonify(**result, **identity)

    @app.get("/api/cases/<case_id>/trend")
    def trend(case_id: str):
        case = case_or_404(case_id)
        bin_seconds = _number_arg("bin_seconds", 60, int, 10, 600)
        return clinical_response(case, lambda: read_evidence(case, ('trend', bin_seconds),
            lambda: heart_rate_trend(analysis_path(case), case["technical"]["duration_seconds_raw"], bin_seconds)))

    def clinical_index(case):
        feed=edited_feed(case)
        templates=storage.list_beat_templates(case["case_id"])
        by_id={r["id"]:r for r in feed.beats}
        with storage.connect() as db:
            refs={r["template_id"]:json.loads(r["beat_ids"]) for r in db.execute("SELECT * FROM beat_edit_template_refs WHERE case_id=?",(case["case_id"],))}
        for t in templates:
            t["sample_indices"]=[by_id[k]["sample_index"] for k in refs.get(t["id"],[f"s:{s}" for s in t["sample_indices"]]) if k in by_id]
        annotations=storage.list_annotations(case["case_id"])
        index=build_index(feed,templates,annotations,storage.get_review(case["case_id"]))
        index['start_time']=case['metadata'].get('start_iso') or case['metadata'].get('start_time')
        identity=linked_read_identity(case)
        for event in index['events']:
            proof=event.get('stt_event_evidence')
            stt_scope=event.get('stt_source_scope') or (proof or {}).get('scope')
            if event.get('category')=='ST' and stt_scope and any(stt_scope.get(k)!=identity[k] for k in ('case_id','analysis_basis','beat_revision')):
                from ecg_core.stt_records import mark_stale
                mark_stale(event)
        index=augment_index(index, storage.list_candidates(case['case_id']), identity)
        return attach_reviews(index, identity, storage.list_report_evidence(case['case_id']))

    def candidate_guard(case, identity):
        def guard(db):
            if runtime.basis(case)['digest'] != identity['analysis_basis']:
                raise ReportConflict('候选来源已变化，请重新读取后选择')
            if editor.snapshot(case['case_id'], db=db)['revision'] != identity['beat_revision']:
                raise ReportConflict('候选心搏依据已变化，未保存')
            if storage._review(db, case['case_id'])['revision'] != identity['analysis_revision']:
                raise ReportConflict('病例复核已变化，未保存候选')
        return guard

    @app.route('/api/cases/<case_id>/evidence-candidates', methods=['GET','POST','PATCH'])
    def evidence_candidates(case_id):
        case=case_or_404(case_id)
        if request.method=='GET':
            identity=linked_query_identity(case)
            items=storage.list_candidates(case_id)
            linked_read_identity(case,identity)
            return jsonify(items=items, report_version=storage.get_report(case_id,'')['version'], **identity)
        body=_json_object()
        if any(k not in body for k in ('case_id','analysis_basis','analysis_revision','beat_revision')):
            raise ValueError('保存候选须提供完整病例、记录和逐搏依据')
        identity=linked_read_identity(case,body)
        guard=candidate_guard(case,identity)
        if request.method=='PATCH':
            item=storage.set_candidate_status(case_id,body.get('id'),body.get('status'),ACTOR,guard,body.get('expected_report_version'))
        else:
            # Picking evidence needs the exact original adjacency and strip
            # geometry, not a full template/diagnosis/report index rebuild.
            feed=edited_feed(case)
            index={'rows':feed.beats+feed.markers,'duration_s':feed.duration}
            checked=prepare_candidate(index,identity,body)
            linked_read_identity(case,identity)
            item=storage.save_candidate(case_id,checked,ACTOR,guard)
        return jsonify(item=item, report=storage.get_report(case_id,case['conclusion']),
                       review=storage.get_review(case_id), **identity)

    @app.get('/api/cases/<case_id>/report-rr-evidence')
    def report_rr_evidence(case_id):
        case=case_or_404(case_id)
        identity=linked_read_identity(case, request.args)
        event=clinical_projection(case, lambda index:
            longest_event(index, identity, storage.list_report_evidence(case_id)))
        linked_read_identity(case, identity)
        return jsonify(event=event, **identity)

    def read_report_evidence(case, body, *, confirm=False):
        if any(k not in body for k in ('case_id','analysis_basis','analysis_revision','beat_revision')):
            raise ValueError('核对图条须提供完整病例、记录和逐搏依据')
        identity=linked_read_identity(case, body)
        def project(index):
            if body.get('target')=='longest':
                event=longest_event(index, identity, storage.list_report_evidence(case['case_id']))
            else:
                event=next((e for e in index['events'] if e['event_id']==body.get('event_id')), None)
            if event is None or (body.get('basis_version') and body['basis_version']!=event['basis_version']):
                raise ReportConflict('图条依据已变化，请重新核对或移出本次报告')
            descriptor=evidence_descriptor(index, event, identity)
            entry=body.get('entry', {})
            if not isinstance(entry,dict):raise ValueError('图条核对设置无效')
            settings=event.get('retained_settings',{}) if not entry else entry
            entry={**settings, 'caption':entry.get('caption') or event['label'], 'notes':entry.get('notes','')}
            if any(not isinstance(entry[k],str) or len(entry[k])>limit for k,limit in (('caption',500),('notes',2000))):
                raise ValueError('图注或注释无效')
            proof=evidence_presentation(index,event,entry)
            # Read the signal on every preview and confirmation. Only the
            # private, versioned event index is reused, never a prior wave read.
            wave=prepare_strip(index,event,entry,
                lambda a,b,leads,points:read_event_waveform(case['paths']['data'],a,b,leads,points))
            check_read_wave(wave)
            if confirm:
                if body.get('evidence_key')!=evidence_digest(descriptor) or body.get('presentation_key')!=evidence_digest(proof):
                    raise ReportConflict('图条与刚才读取的波形不一致，请重新打开后核对')
                assert_evidence_caption(index,event,entry)
            return event,entry,descriptor,proof,wave
        result=clinical_projection(case,project)
        linked_read_identity(case,identity)
        return identity,*result

    @app.post('/api/cases/<case_id>/report-evidence/preview')
    def report_evidence_preview(case_id):
        case=case_or_404(case_id)
        identity,event,entry,descriptor,proof,wave=read_report_evidence(case,_json_object())
        return jsonify(**wave,event=event,entry=entry,evidence_key=evidence_digest(descriptor),
            presentation_key=evidence_digest(proof),report_version=storage.get_report(case_id,'')['version'],**identity)

    @app.post('/api/cases/<case_id>/report-evidence/confirm')
    def report_evidence_confirm(case_id):
        case=case_or_404(case_id);body=_json_object()
        if body.get('confirmed') is not True:raise ValueError('请明确确认当前图条证据')
        identity,event,entry,descriptor,proof,wave=read_report_evidence(case,body,confirm=True)
        version=body.get('report_version')
        if type(version) is not int:raise ValueError('缺少核对时的报告版本')
        original_guard=candidate_guard(case,identity)
        def guard(db):
            original_guard(db)
            row=db.execute('SELECT version FROM report_drafts WHERE case_id=?',(case_id,)).fetchone()
            if (row['version'] if row else 1)!=version:
                raise ReportConflict('报告已变化，请重新打开当前图条后核对')
        item=storage.confirm_report_evidence(case_id,descriptor,proof,ACTOR,guard)
        return jsonify(item=item,report=storage.get_report(case_id,case['conclusion']),
                       review=storage.get_review(case_id),**linked_read_identity(case))

    @app.get('/api/cases/<case_id>/rr-distribution')
    def rr_distribution_endpoint(case_id):
        case=case_or_404(case_id); identity=linked_read_identity(case,request.args)
        candidates = canonical(storage.list_candidates(case_id))
        result = read_evidence(case, ('rr-distribution', request.args.get('edges_ms'), candidates),
            lambda: clinical_projection(case,
                lambda index: rr_distribution(index['rows'], index['duration_s'], request.args.get('edges_ms'))))
        linked_read_identity(case,identity)
        return jsonify(**result, **identity)

    @app.get("/api/cases/<case_id>/template-occurrences")
    def template_occurrences(case_id):
        return clinical_query(case_id, True)

    @app.get("/api/cases/<case_id>/report-events")
    def report_events(case_id):
        return clinical_query(case_id)

    def clinical_query(case_id, occurrences=False):
        case = case_or_404(case_id)
        # URL query revisions are strings; the existing clinical basis contract
        # remains unchanged. The emitted beat revision comes from a fresh read.
        identity = linked_read_identity(case, {key: request.args[key] for key in
            ('analysis_basis', 'analysis_revision') if key in request.args})
        basis = {key: identity[key] for key in ('analysis_basis', 'analysis_revision')}
        key = clinical_index_key(case, basis)
        def build_checked():
            index = clinical_index(case)
            clinical_read_basis(case, basis)
            return index
        # Cache only private event-list indexes. Report rendering and mutable
        # editing paths still compute independently; their results cannot poison
        # a cached index. Each returned projection is detached from cache storage.
        result = read_evidence(case, ('clinical-query', occurrences,
            tuple(sorted(request.args.items())), key[3:]),
            lambda: clinical_query_cache.project(key, build_checked,
                lambda index: query_index(index, request.args, occurrences)))
        linked_read_identity(case, identity)
        # Beat identities can remain unchanged when the raw signal is replaced.
        # Send only a digest, never local source paths, for browser cache scoping.
        result.update(identity)
        return jsonify(result)

    @app.get("/api/cases/<case_id>/event-waveform")
    def event_waveform(case_id):
        case=case_or_404(case_id)
        basis=clinical_read_basis(case,request.args)
        start=_number_arg("start",0,float,0)
        end=_number_arg("end",start+4,float,start+1)
        payload=read_event_waveform(case["paths"]["data"],start,end,_waveform_leads_arg(),_number_arg("max_points",2400,int,200,12000))
        payload['beats']=waveform_labels(case,basis,[(payload['start_s'],payload['duration_s'])])[0]
        clinical_read_basis(case,basis)
        return jsonify({**payload,**basis})

    @app.post("/api/cases/<case_id>/event-waveforms")
    def event_waveforms(case_id):
        """One revision-consistent beat read for a viewport of thumbnail ranges."""
        case = case_or_404(case_id)
        body = _json_object()
        basis = clinical_read_basis(case, body)
        ranges = body.get("ranges")
        if not isinstance(ranges, list) or not 1 <= len(ranges) <= 32:
            raise ValueError("每批需包含 1–32 个波形区间")
        leads = body.get("leads", ["II", "V1", "V5"])
        if not isinstance(leads, list) or not 1 <= len(leads) <= 12 or any(lead not in ALL_LEADS for lead in leads) or len(set(leads)) != len(leads):
            raise ValueError("导联包含不支持或重复的值")
        points = _json_number(body, "max_points", 1200, 200, 1200, integer=True)
        checked = []
        for item in ranges:
            if not isinstance(item, dict):
                raise ValueError("波形区间格式错误")
            start = _coerce_json_number(item.get("start"), "区间起点", 0, 2_678_400)
            end = _coerce_json_number(item.get("end"), "区间终点", start+1, 2_678_400)
            checked.append((start, end))
        items = []
        for start, end in checked:
            wave = read_event_waveform(case["paths"]["data"], start, end, leads, points)
            wave.update(basis)
            items.append(wave)
        labels = waveform_labels(case, basis, [(w['start_s'], w['duration_s']) for w in items], include_markers=True)
        for wave, beats in zip(items, labels):
            wave['beats'] = beats
        clinical_read_basis(case, basis)
        return jsonify(items=items, **basis)

    @app.get("/api/cases/<case_id>/report-strip")
    def report_strip(case_id):
        case = case_or_404(case_id)
        expected = {name: request.args[name] for name in
                    ('case_id', 'analysis_basis', 'analysis_revision') if name in request.args}
        # GET encodes integers as strings; reject malformed scope rather than
        # falling back to a current revision or silently accepting another case.
        for name in ('beat_revision', 'revision'):
            if name in request.args:
                value = request.args[name]
                if not value or not value.isascii() or not value.isdecimal():
                    raise ValueError('图表逐搏修订须为非负整数')
                expected[name] = int(value)
        identity = linked_read_identity(case, expected)
        basis = {key: identity[key] for key in ('analysis_basis', 'analysis_revision')}
        key = clinical_index_key(case, basis)

        def build_checked():
            index = clinical_index(case)
            linked_read_identity(case, identity)
            return index

        def project_strip(index):
            event = next((e for e in index['events'] if e['event_id'] == request.args.get('event_id')), None)
            if not event or event['basis_version'] != request.args.get('basis_version'):
                raise ReportConflict('图条依据已变化，请重新选择事件')
            settings = {'leads': list(ALL_LEADS) if event.get('category')=='ST' and 'leads' not in request.args else _waveform_leads_arg(),
                        'duration_s': _number_arg('duration', 7, float, 1, 120)}
            if 'range_start_s' in request.args or 'range_end_s' in request.args:
                for name in ('range_start_s','range_end_s'):
                    try:
                        value=float(request.args[name])
                    except (KeyError,TypeError,ValueError):
                        raise ValueError('人工入报区间须同时提供有效的起止时间') from None
                    settings[name]=_coerce_json_number(value,'人工入报时间',0,case['technical']['duration_seconds_raw'])
            return prepare_strip(index, event, settings,
                lambda a, b, leads, points: read_event_waveform(case['paths']['data'], a, b, leads, points))

        # Reuse only the existing guarded private event index, never a waveform
        # or mutable saved report. The projection is detached by the cache.
        result = clinical_query_cache.project(key, build_checked, project_strip)
        linked_read_identity(case, identity)
        return jsonify({**result, **basis})

    @app.get('/api/cases/<case_id>/report-af-representatives')
    def report_af_representatives(case_id):
        case=case_or_404(case_id)
        identity=linked_query_identity(case)
        def project(index):
            event=next((e for e in index['events'] if e['event_id']==request.args.get('event_id')),None)
            if not event or event.get('category')!='AF' or ('basis_version' in request.args and request.args['basis_version']!=event['basis_version']):
                raise ReportConflict('房颤／房扑片段依据已变化，请重新选择')
            return {**af_representatives(index,event,dict(leads=_waveform_leads_arg(),
                duration_s=strict_query_number('duration',7,1,120))), 'event_id':event['event_id'],
                'basis_version':event['basis_version']}
        result=clinical_projection(case,project)
        linked_read_identity(case,identity)
        return jsonify(**result,**identity)

    @app.get('/api/cases/<case_id>/report-stt-representatives')
    def report_stt_representatives(case_id):
        from ecg_core.report_layout import stt_representatives
        case=case_or_404(case_id)
        identity=linked_query_identity(case)
        def project(index):
            event=next((e for e in index['events'] if e['event_id']==request.args.get('event_id')),None)
            if not event or event.get('category')!='ST' or ('basis_version' in request.args and request.args['basis_version']!=event['basis_version']):
                raise ReportConflict('ST-T复核范围依据已变化，请重新选择')
            return {**stt_representatives(index,event,dict(leads=_waveform_leads_arg() if 'leads' in request.args else list(ALL_LEADS),
                duration_s=strict_query_number('duration',7,1,120))), 'event_id':event['event_id'],
                'basis_version':event['basis_version']}
        result=clinical_projection(case,project)
        linked_read_identity(case,identity)
        return jsonify(**result,**identity)

    @app.get('/api/cases/<case_id>/report-strip-preview')
    def report_strip_preview(case_id):
        case=case_or_404(case_id)
        identity=linked_query_identity(case)
        feed=edited_feed(case)
        index=dict(rows=feed.beats+feed.markers,duration_s=feed.duration)
        time=strict_query_number('time_s',request.args.get('time',0),0,max(0,feed.duration-.005))
        settings=dict(leads=_waveform_leads_arg() if 'leads' in request.args else list(ALL_LEADS),
            duration_s=strict_query_number('duration',7,1,120))
        if 'range_start_s' in request.args or 'range_end_s' in request.args:
            for name in ('range_start_s','range_end_s'):
                if name not in request.args:raise ValueError('人工区间须同时提供起止时间')
                settings[name]=strict_query_number(name,0,0,feed.duration)
        usable=[r for r in index['rows'] if r.get('class_code') not in ('X','O','Y','T')]
        nearest=min(usable,key=lambda r:abs(r['sample_index']/200-time)) if usable else {}
        event=dict(event_id='preview-only',category='other',subtype='manual_strip',label='人工波形图条',
            start_sample=int(math.floor(time*200+.5)),time_s=time,hr=nearest.get('hr'),rr_ms=nearest.get('rr_ms'))
        result=prepare_strip(index,event,settings,
            lambda a,b,leads,points:read_event_waveform(case['paths']['data'],a,b,leads,points))
        check_read_wave(result)
        linked_read_identity(case,identity)
        return jsonify(**result,event=event,preview_only=True,**identity)

    @app.get("/api/cases/<case_id>/report-statistics")
    def report_statistics_endpoint(case_id):
        case = case_or_404(case_id)
        basis = clinical_read_basis(case, request.args)
        def build():
            feed = edited_feed(case)
            result = clinical_projection(case, lambda index: report_statistics(index,
                case['metadata'].get('start_iso') or case['metadata'].get('start_time'),
                feed.document['settings'], request.args.get('pause_edges_ms')))
            result['hrv'] = hrv(feed)
            return result
        result = read_evidence(case, ('report-statistics', request.args.get('pause_edges_ms'),
            canonical(storage.list_candidates(case_id))), build)
        clinical_read_basis(case, basis)
        return jsonify({**result, **basis})

    def report_section_evidence(case,index=None):
        from ecg_core.report_sections import evidence
        value=evidence(index if index is not None else clinical_index(case),stt_review(case['case_id']).get_json())
        rows=value['st_events'];roles=[]
        for role,field,anchor in [('st_min','minimum_st_level_units','minimum_st_sample'),('st_max','maximum_st_level_units','maximum_st_sample'),('reference','reference_st_level_units','reference_sample')]:
            usable=[r for r in rows if r.get(field) is not None and r.get(anchor) is not None]
            if not usable:continue
            row=min(usable,key=lambda r:r[field]) if role=='st_min' else max(usable,key=lambda r:r[field]) if role=='st_max' else usable[0]
            at=row[anchor]/200;start=max(0,at-.25);end=min(case['technical']['duration_seconds_raw'],at+.65)
            wave=read_event_waveform(case['paths']['data'],start,end,[row['lead']],600)
            roles.append(dict(role=role,label={'st_min':'最深ST电平实际搏','st_max':'最高ST电平实际搏','reference':'范围均值附近实际参考搏'}[role],
                lead=row['lead'],sample_index=row[anchor],time_s=at,event_id=row['event_id'],basis_version=row['basis_version'],
                value=row[field],units='source_device_units',metric='st_level',measurement_protocol=row['measurement_protocol'],
                reference_method='nearest_valid_beat_to_event_mean_st_level' if role=='reference' else None,waveform=wave))
        value['st_representatives']=roles
        t_roles=[]
        for role,kind,label in [('t_inversion','t_persistent_inversion','持续倒置最负T实际搏'),
                ('t_low','t_low_flat','低平T最小幅度实际搏'),('t_dynamic','t_wave_inversion','动态T极值实际搏')]:
            usable=[r for r in value['t_events'] if r['kind']==kind and type(r.get('extreme_t_sample')) is int and isinstance(r.get('extreme_t_amplitude_units'),(int,float))]
            if not usable:continue
            row=min(usable,key=lambda r:r['extreme_t_amplitude_units']) if kind in ('t_persistent_inversion','t_low_flat') else max(usable,key=lambda r:abs(r['extreme_t_amplitude_units']))
            at=row['extreme_t_sample']/200;start=max(0,at-.25);end=min(case['technical']['duration_seconds_raw'],at+.65)
            t_roles.append(dict(role=role,label=label,lead=row['lead'],sample_index=row['extreme_t_sample'],time_s=at,
                event_id=row['event_id'],basis_version=row['basis_version'],value=row['extreme_t_amplitude_units'],
                units='source_device_units',metric='t_amplitude_units',measurement_protocol=row['measurement_protocol'],
                waveform=read_event_waveform(case['paths']['data'],start,end,[row['lead']],600)))
        value['t_representatives']=t_roles
        return value

    @app.get("/api/cases/<case_id>/report-sections")
    def report_sections_endpoint(case_id):
        case=case_or_404(case_id)
        return clinical_response(case,lambda:report_section_evidence(case))

    def advanced_evidence(case, index, options=None):
        from ecg_core.advanced_analysis import analyze, report_documents
        result=analyze(case['paths']['data'],index,options)
        result['documents']=report_documents(result)
        return result

    @app.post('/api/cases/<case_id>/advanced-analysis')
    def advanced_analysis_endpoint(case_id):
        case=case_or_404(case_id)
        body = _json_object()
        return clinical_response(case, lambda: advanced_evidence(case,clinical_index(case),body.get('options')), body)

    @app.get("/api/cases/<case_id>/hrv-windows")
    def hrv_window_endpoint(case_id):
        case=case_or_404(case_id)
        return clinical_response(case, lambda: hrv_windows(edited_feed(case),case["metadata"].get("start_iso") or case["metadata"].get("start_time"),request.args.get("window",0)))

    def review_data_version(case, feed):
        from ecg_core.clinical_analysis import fingerprint, encode, DATA_VERSION_SUFFIX
        opts = feed.document['settings']
        rows = feed.beats + feed.markers
        bv = fingerprint('|'.join(f"{r['id']}:{r['sample_index']}:{r['class_code']}" for r in rows)
                         + '|' + encode([[k, opts[k]] for k in sorted(opts)]))
        from ecg_core.stt_records import ST_KINDS
        findings = [a for a in storage.list_annotations(case['case_id'])
                    if a.get('details', {}).get('kind') in (*ST_KINDS, 'AT', 'VT', 'AF', 'AFL', 'STRIP')]
        av = fingerprint(encode([[a['id'], a['sample_index'], a.get('details')] for a in findings]))
        return bv + '-' + av + DATA_VERSION_SUFFIX

    def review_scope(case, expected=None, db=None):
        """Bind new work to original contents and both edited/review revisions."""
        source = runtime.basis(case)
        beat = editor.snapshot(case['case_id'], db=db)['revision']
        revision = storage._review(db, case['case_id'])['revision'] if db is not None else storage.get_review(case['case_id'])['revision']
        # Compute exactly the clinical index's content identity without building
        # thousands of unrelated event candidates on every RR/HRV query.
        def project_version():
            return {'data_version': review_data_version(case, edited_feed(case))}
        identity_key=(case['case_id'],source['digest'],revision,beat)
        version=review_identity_cache.project(identity_key,project_version,lambda index:index['data_version'])
        value = dict(case_id=case['case_id'], source_digest=provenance_digest(source['inputs']),
                     data_version=version, analysis_basis=source['digest'],
                     beat_revision=beat, analysis_revision=revision)
        for key in value:
            if expected is not None and key in expected:
                item = expected[key]
                if key in ('beat_revision', 'analysis_revision'):
                    if isinstance(item, str) and item.isdecimal(): item = int(item)
                    if type(item) is not int: raise ValueError('复核修订必须为非负整数')
                if item != value[key]: raise ReportConflict('病例、原始来源或复核修订已变化，请重新读取')
        runtime.assert_current()
        return value

    def stt_data_version(feed):
        """ST measurements depend on edited beats/settings, never AF/AFL decisions."""
        from ecg_core.clinical_analysis import fingerprint,encode
        rows=feed.beats+feed.markers;opts=feed.document['settings']
        version=fingerprint('|'.join(f"{r['id']}:{r['sample_index']}:{r['class_code']}" for r in rows)
                            +'|'+encode([[k,opts[k]] for k in sorted(opts)]))
        return version+'-stt-independent-v2'

    def stt_range_result(case, payload):
        from ecg_core.stt_range import analyze_stt_range
        case_id = case['case_id']
        scope = payload.get('scope')
        if 'exclusions' in payload:
            raise ValueError('范围统计不接受客户端排除区间；ST-T独立分析不采用AF/AFL诊断屏蔽')
        names = ('case_id', 'analysis_basis', 'analysis_revision', 'beat_revision')
        if not isinstance(scope, dict) or any(name not in scope for name in names):
            raise ValueError('范围统计须提供病例、分析及逐搏修订依据')
        if any(type(scope[name]) is not int or scope[name] < 0 for name in ('analysis_revision', 'beat_revision')):
            raise ValueError('范围统计修订须为非负整数')
        if 'case_id' in payload and payload['case_id'] != case_id:
            raise ReportConflict('范围统计请求来自另一病例')
        identity = linked_read_identity(case, {name: scope[name] for name in names})
        source = runtime.basis(case)
        source_digest = provenance_digest(source['inputs'])
        feed = edited_feed(case)
        data_version = stt_data_version(feed)
        for name, value in (('source_digest', source_digest), ('data_version', data_version)):
            if name in scope and scope[name] != value:
                raise ReportConflict('范围统计来源或复核依据已变化，请重新读取')
        # feed.records contains the actual edited QRS samples/classes. The
        # feed's separate excluded_rhythm_intervals is only for RR/HRV, and is
        # deliberately not passed to ST/T measurements.
        result = analyze_stt_range(case['paths']['data'], feed.records,
            start_sample=payload.get('start_sample'), end_sample=payload.get('end_sample'),
            leads=payload.get('leads'), measurement_ms=payload.get('measurement_ms', 60),
            basis=scope, source_digest=source_digest)
        linked_read_identity(case, identity)
        assert_source_basis(case, source)
        runtime.assert_current()
        value = {**result, 'server_identity': {**identity, 'source_digest': source_digest,
                                               'data_version': data_version},
                 'physician_document_written': False}
        compact = {key: item for key, item in value.items() if key != 'blocks'}
        return {**compact, 'save_receipt': dict(kind='native-stt-range-hmac-v1',
                                               digest=stt_range_receipt(compact))}

    stt_receipt_key = os.urandom(32)

    def stt_range_receipt(snapshot):
        # Stateless attestation of the complete compact result, including masks
        # and scope. A client cannot change a mean while retaining this receipt.
        # JSON.parse/stringify preserves a number's value, but writes 60.0 as
        # 60 (and -0.0 as 0). Authenticate those equivalent numeric values with
        # one representation; the returned statistics and typed scope checks
        # remain unchanged. Booleans are deliberately kept distinct.
        def numbers(value):
            if isinstance(value, dict):
                return {key: numbers(child) for key, child in value.items()}
            if isinstance(value, list):
                return [numbers(child) for child in value]
            if type(value) is float and math.isfinite(value) and value.is_integer():
                return int(value)
            return value

        encoded = json.dumps(numbers(snapshot), sort_keys=True, ensure_ascii=False,
                             separators=(',', ':'), allow_nan=False).encode()
        return hmac.new(stt_receipt_key, encoded, sha256).hexdigest()

    @app.post('/api/cases/<case_id>/stt-range')
    def stt_range_endpoint(case_id):
        return jsonify(stt_range_result(case_or_404(case_id), _json_object()))

    def validate_stt_range_snapshot(case, snapshot):
        if not isinstance(snapshot, dict) or snapshot.get('schema_version') != 'stt-range-mean-v1' or 'blocks' in snapshot:
            raise ValueError('区间统计保存须采用完整的当前结构化摘要')
        receipt = snapshot.get('save_receipt')
        compact = {key: value for key, value in snapshot.items() if key != 'save_receipt'}
        if (not isinstance(receipt, dict) or receipt.get('kind') != 'native-stt-range-hmac-v1'
                or not isinstance(receipt.get('digest'), str)
                or len(receipt['digest']) != 64
                or any(char not in '0123456789abcdef' for char in receipt['digest'])
                or not hmac.compare_digest(receipt['digest'], stt_range_receipt(compact))):
            raise ReportConflict('区间统计已变化或服务已重启，请重新计算后保存；复核文字保留')
        scope = snapshot.get('scope')
        if not isinstance(scope, dict) or any(key not in scope for key in ('case_id', 'analysis_basis', 'analysis_revision', 'beat_revision')):
            raise ValueError('区间统计缺少病例与修订依据')
        identity = linked_read_identity(case, scope)
        if snapshot.get('server_identity', {}).get('case_id') != case['case_id']:
            raise ReportConflict('区间统计来自另一病例')
        from ecg_core.stt_records import RANGE_PROFILE,RHYTHM_POLICY
        profile=snapshot.get('method_profile') or {}
        if profile.get('id')!=RANGE_PROFILE or profile.get('rhythm_policy')!=RHYTHM_POLICY:
            raise ReportConflict('ST-T范围统计方法已变化，请重新计算后保存')
        return identity

    def review_duration(case):
        samples = case['technical']['duration_seconds_raw'] * SAMPLE_RATE
        rounded = round(samples)
        if not math.isfinite(samples) or abs(samples-rounded) > 1e-6:
            raise ValueError('录制长度未落在当前采样网格，不能编辑 HRV 排除区间')
        return rounded

    def hrv_state(case, window=0, expected=None):
        context = review_scope(case, expected)
        state = hrv_reviews.read(case['case_id'], context, review_duration(case), window=int(window))
        review_scope(case, context)
        return state

    def hrv_reference(case, window=0, expected=None):
        state = hrv_state(case, window, expected)
        return dict(hrv_revision=state['hrv_revision'], document_digest=state['digest'],
                    window_index=state['window_index'], profile=state['profile'], scope=state['scope'])

    def assert_hrv_reference(case, reference, window, *, require_confirmation=False):
        state = hrv_state(case, window)
        if state['document_stale']: raise ReportConflict('HRV 排除区间来自旧依据，请预览并重新确认当前区间')
        current = hrv_reference(case, window)
        if reference is None:
            if state['hrv_revision'] != 0:
                raise ReportConflict('报告缺少当前 HRV 复核修订，请重新读取并保存草稿')
        elif reference != current:
            raise ReportConflict('报告 HRV 修订或来源已变化，请重新读取并保存草稿')
        if require_confirmation and not state['confirmation'].get('valid'):
            raise ReportConflict('请先在 HRV 页面确认本报告所用窗口的 NN、节律和伪差复核')
        return state

    @app.get('/api/terminology/catalogs')
    def terminology_catalogs():
        return jsonify(terminology.list_catalogs())

    @app.get('/api/terminology/catalog')
    def terminology_catalog():
        result = terminology.get_catalog(request.args.get('namespace'), request.args.get('version'), request.args.get('hash'))
        if result is None: return jsonify(error='该版本词库不存在或内容 hash 不一致'), 404
        return jsonify(result)

    @app.post('/api/terminology/import')
    def terminology_import():
        def unique_fields(pairs):
            result={}
            for key,value in pairs:
                if key in result: raise ValueError('JSON 字段重复')
                result[key]=value
            return result
        body = json.loads(request.get_data(as_text=True), object_pairs_hook=unique_fields,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError('非有限 JSON 数值')))
        if not isinstance(body, dict): raise ValueError('词库导入请求必须是对象')
        return jsonify(terminology.import_catalog(body.get('catalog'), body.get('expected_catalog_revision'),
            confirm=body.get('confirm', False), preview_hash=body.get('preview_hash')))

    def rr_index_for(case, expected=None):
        scope = review_scope(case, expected)
        key = (case['case_id'], scope['analysis_basis'], scope['analysis_revision'], scope['beat_revision'])
        def build():
            result = build_rr_index(edited_feed(case), SAMPLE_RATE, scope)
            review_scope(case, scope)
            return result
        return scope, key, build

    @app.get('/api/cases/<case_id>/rr-review')
    def rr_review_endpoint(case_id):
        case = case_or_404(case_id)
        scope, key, build = rr_index_for(case, request.args)
        result = rr_cache.project(key, build, lambda index: query_rr(index, dict(request.args)))
        review_scope(case, scope)
        return jsonify(result)

    @app.post('/api/cases/<case_id>/rr-review/locate')
    def rr_locate_endpoint(case_id):
        case = case_or_404(case_id); body = _json_object(); target = body.get('target', body)
        if not isinstance(target, dict) or any(k not in target for k in ('case_id','analysis_basis','analysis_revision','beat_revision','sample_index')):
            raise ValueError('缺少完整 RR 定位身份；请从当前间期重新选择')
        scope, key, build = rr_index_for(case, target)
        exact = rr_cache.project(key, build, lambda index: resolve_rr_target(index, target))
        start = max(0, exact['sample_index']/SAMPLE_RATE-3.5)
        end = min(case['technical']['duration_seconds_raw'], start+7)
        wave = read_event_waveform(case['paths']['data'], start, end, ['II','V1','V5'], 2800)
        wave['beats'] = waveform_labels(case, scope, [(wave['start_s'], wave['duration_s'])], force_edited=True)[0]
        if not any(b['sample_index']==exact['sample_index'] for b in wave['beats']):
            raise RRReviewConflict('目标心搏未出现在当前原始波形证据中；未用最近邻替代')
        review_scope(case, scope)
        return jsonify(target=exact, waveform={**wave, **scope}, located=True, **scope)

    def hrv_measurements(case,window,document,context=None):
        from ecg_core.rr_quality import annotation_exclusions
        context = context or review_scope(case)
        # Bind actual authored content as well as the public version. Some
        # imported or method-updated annotations can retain a workflow number.
        def numerical_inputs():
            return dict(editor=editor.snapshot(case['case_id'])['document'],
                        overrides=storage.list_beat_overrides(case['case_id']),
                        rhythm=annotation_exclusions(storage.list_annotations(case['case_id'])),
                        clock=case['metadata'].get('start_iso') or case['metadata'].get('start_time'))
        inputs=numerical_inputs()
        inputs_digest=provenance_digest(inputs)
        # Workflow acknowledgements and saving this same exclusion do not
        # alter numerical inputs. Preserve the verified preview across that
        # revision only; the complete scope is still checked before publishing.
        key=(case['case_id'],context['source_digest'],context['data_version'],
             context['analysis_basis'],context['beat_revision'],inputs_digest,
             int(window),document['profile'],provenance_digest(document))
        def ensure_inputs():
            review_scope(case,context)
            if provenance_digest(numerical_inputs()) != inputs_digest:
                raise ReportConflict('HRV 数值依据已变化，请重新读取并预览')
        def build_checked():
            feed=build_feed(case,inputs['editor'])
            feed.excluded_rhythm_intervals=inputs['rhythm']
            result=analyze_hrv_review(feed,inputs['clock'],int(window),document['exclusions'])
            ensure_inputs()
            return result
        result=hrv_measurement_cache.read(key,build_checked)
        ensure_inputs()
        return result  # fresh JSON decoding; enrichment cannot mutate retained evidence

    @app.get('/api/cases/<case_id>/hrv-review')
    def hrv_review_get(case_id):
        case=case_or_404(case_id); window=_number_arg('window',0,int,0)
        state=hrv_state(case,window,request.args)
        active_document = {**state['document'],'exclusions':[]} if state['document_stale'] else state['document']
        measured=hrv_measurements(case,window,active_document,state['scope'])
        if state['document_stale']:
            measured['reviewed']=None; measured['reason']='document_stale'
        review_scope(case,state['scope'])
        return jsonify({**state,'evidence':measured})

    @app.post('/api/cases/<case_id>/hrv-review/preview')
    def hrv_review_preview(case_id):
        case=case_or_404(case_id); body=_json_object(); context=review_scope(case,body.get('scope',{}))
        value=hrv_reviews.preview(case_id,body,context,review_duration(case),actor=ACTOR,window=body.get('window',0))
        evidence=hrv_measurements(case,value['window_index'],value['after'],context)
        review_scope(case,context)
        return jsonify({**value,'evidence_preview':evidence})

    @app.put('/api/cases/<case_id>/hrv-review')
    def hrv_review_apply(case_id):
        case=case_or_404(case_id); body=_json_object(); context=review_scope(case,body.get('scope',{}))
        return jsonify(hrv_reviews.apply(case_id,body,ACTOR,context,review_duration(case),
            check_current=lambda db:review_scope(case,db=db), on_change=storage.invalidate_review))

    @app.post('/api/cases/<case_id>/hrv-review/confirm')
    def hrv_review_confirm(case_id):
        case=case_or_404(case_id); body=_json_object(); context=review_scope(case,body.get('scope',{}))
        return jsonify(hrv_reviews.confirm(case_id,body,ACTOR,context,review_duration(case),
            check_current=lambda db:review_scope(case,db=db), on_change=storage.invalidate_review))

    @app.post('/api/cases/<case_id>/hrv-review/cancel')
    def hrv_review_cancel(case_id):
        case=case_or_404(case_id); body=_json_object(); context=review_scope(case,body.get('scope',{}))
        return jsonify(hrv_reviews.cancel_preview(case_id,body,context,review_duration(case)))

    def build_hrv_evidence(case, window=0):
        feed=edited_feed(case)
        state=hrv_state(case,int(window))
        if state['document_stale']: raise ReportConflict('HRV 排除区间来自旧依据，请打开区间复核并预览当前范围')
        measured=hrv_measurements(case,int(window),state['document'],state['scope'])
        data=measured['reviewed']
        # Supply the editor the same verified numerical snapshot as this
        # analysis. Copy reviewed before adding report-only fields, so no
        # circular reference or duplicated request is needed on the browser.
        data['hrv_review']={**state,'evidence':{**measured,'reviewed':copy.deepcopy(data)}}
        data['hrv_review_reference']=hrv_reference(case,int(window))
        data['review_profile']=measured['profile']
        data['review_coverage']=measured['coverage']
        # Use the already-versioned ST research engine; never label device units mV.
        data['st_trends']=stt_trends(case,state['scope'])
        def event_evidence(index):
            statistics=report_statistics(index,case['metadata'].get('start_iso') or case['metadata'].get('start_time'),feed.document['settings'])
            representatives=[]
            for category in ('fastest','slowest','V','S','pause'):
                candidates=[e for e in index['events'] if e['category']==category and data['start_s']<=e['time_s']<data['end_s'] and (category not in ('fastest','slowest') or e['subtype']=='RR')]
                if category in ('fastest','slowest'): candidates.sort(key=lambda e: ((-1 if category=='fastest' else 1)*(e.get('hr') or 0),e['time_s']))
                event=next(iter(candidates),None)
                if event:
                    entry=prepare_strip(index,event,{'leads':['II']},lambda a,b,leads,points:read_event_waveform(case['paths']['data'],a,b,leads,min(points,1000)))
                    representatives.append(entry)
            return dict(event_statistics=statistics, representatives=representatives)
        # HRV's own exclusion/acknowledgement changes the workflow version,
        # not the event population. Keep a detached projection only when all
        # actual event inputs and review decisions are unchanged.
        def event_inputs():
            cid=case['case_id'];review=storage.get_review(cid)
            with storage.connect() as db:
                refs=[dict(r) for r in db.execute('SELECT template_id,beat_ids FROM beat_edit_template_refs WHERE case_id=? ORDER BY template_id',(cid,))]
            return dict(editor=editor.snapshot(cid)['document'],
                        overrides=storage.list_beat_overrides(cid),
                        templates=storage.list_beat_templates(cid),template_refs=refs,
                        annotations=storage.list_annotations(cid),
                        review_steps=review.get('steps',{}),review_events=review.get('events',{}),
                        candidates=storage.list_candidates(cid),
                        report_evidence=storage.list_report_evidence(cid),
                        clock=case['metadata'].get('start_iso') or case['metadata'].get('start_time'),
                        duration=case['technical']['duration_seconds_raw'],
                        window=[data['start_s'],data['end_s']])
        event_digest=provenance_digest(event_inputs())
        event_key=(case['case_id'],state['scope']['analysis_basis'],event_digest)
        def assert_events_current():
            review_scope(case,state['scope'])
            if provenance_digest(event_inputs())!=event_digest:
                raise ReportConflict('HRV 事件或复核依据已变化，请重新读取')
        def workflow_bound(value):
            if isinstance(value,dict):
                return any(k=='analysis_revision' or 'scope' in k.lower() or workflow_bound(v) for k,v in value.items())
            return isinstance(value,list) and any(workflow_bound(v) for v in value)
        def project_events():
            projected=clinical_projection(case,event_evidence)
            assert_events_current()
            return dict(workflow_bound=workflow_bound(projected),
                        revision=state['scope']['analysis_revision'],value=projected)
        projection=hrv_event_cache.read(event_key,project_events)
        if projection['workflow_bound'] and projection['revision']!=state['scope']['analysis_revision']:
            # A future or authored representative may carry a full scope.
            # Retain that exact scope and use normal version-bound reuse.
            projection=hrv_event_cache.read((*event_key,state['scope']['analysis_revision']),project_events)
        assert_events_current()
        data.update(projection['value'])
        return data

    def hrv_evidence(case, window=0):
        if request.method != 'GET':
            return build_hrv_evidence(case, window)
        basis = clinical_read_basis(case, request.args)
        state = hrv_state(case,int(window))
        key = (case['case_id'], basis['analysis_basis'], basis['analysis_revision'], str(window), state['hrv_revision'], state['digest'])
        def build_checked():
            result = build_hrv_evidence(case, window)
            clinical_read_basis(case, basis)
            return result
        result = hrv_evidence_cache.read(key, build_checked)
        clinical_read_basis(case, basis)
        return result

    @app.get('/api/cases/<case_id>/hrv-analysis')
    def hrv_analysis_endpoint(case_id):
        case = case_or_404(case_id)
        return clinical_response(case, lambda: hrv_evidence(case,request.args.get('window',0)))

    @app.get('/api/cases/<case_id>/hrv-report.pdf')
    def hrv_pdf(case_id):
        case=case_or_404(case_id)
        clinical_read_basis(case, request.args)
        source_token=report_source_token(case)
        state=hrv_state(case,_number_arg('window',0,int,0))
        if 'expected_hrv_revision' in request.args and _number_arg('expected_hrv_revision',0,int,0)!=state['hrv_revision']:
            raise ReportConflict('HRV 修订已变化，请重新读取后导出')
        if 'expected_hrv_digest' in request.args and request.args['expected_hrv_digest']!=state['digest']:
            raise ReportConflict('HRV 排除区间已变化，请重新读取后导出')
        if state['hrv_revision'] and 'expected_hrv_revision' not in request.args:
            raise ReportConflict('请从当前 HRV 复核窗口导出，缺少选段修订')
        include_phi=include_phi_authorized()
        visible=case_with_overrides(case)
        if not include_phi: visible=_masked_report_case(visible)
        visible['case_id']=app.config.get('REPORT_CASE_DISPLAY_IDS',{}).get(case_id,case_id)
        if case_id in app.config.get('REPORT_CASE_DISPLAY_IDS', {}):
            visible['display_case_id'] = visible['case_id']
        report=storage.get_report(case_id,case['conclusion'])
        report.update(hrv_only=True,status='draft',selected_waveforms=[],hrv_analysis=hrv_evidence(case,request.args.get('window',0)))
        pdf=build_report_pdf(visible,{},report)
        if report_source_token(case)!=source_token:
            raise ReportConflict('导出期间病例或算法依据已变化，未生成 HRV 下载；请重新核对')
        pdf_digest=sha256(pdf.getbuffer()).hexdigest()
        storage.audit(ACTOR,'hrv.export_pdf',case_id,f'HRV research draft basis={source_token[2]} sha256={pdf_digest}')
        response=send_file(pdf,mimetype='application/pdf',as_attachment=True,download_name=f"{visible['case_id']}_HRV分析报告.pdf")
        response.headers['X-Privacy-Mode']='phi-visible' if include_phi else 'masked'
        response.headers['X-Analysis-Basis']=source_token[2]
        response.headers['X-Report-SHA256']=pdf_digest
        response.headers['X-HRV-Revision']=str(state['hrv_revision'])
        response.headers['X-HRV-Document-Digest']=state['digest']
        response.headers['X-HRV-Profile']=state['profile']
        return response

    @app.get("/api/cases/<case_id>/hrv")
    def hrv_endpoint(case_id: str):
        case = case_or_404(case_id)
        return clinical_response(case, lambda: {"calculated": hrv(analysis_path(case)), "source": case["summary"]})

    @app.get("/api/cases/<case_id>/rr-visuals")
    def rr_endpoint(case_id: str):
        case = case_or_404(case_id)
        points = _number_arg("max_points", 4000, int, 500, 10000)
        return clinical_response(case, lambda: read_evidence(case, ('rr-visuals', points),
            lambda: rr_visuals(analysis_path(case), points)))

    @app.get("/api/cases/<case_id>/scatter")
    def scatter_endpoint(case_id: str):
        case = case_or_404(case_id)
        mode = request.args.get('mode', 'rr')
        points = _number_arg('max_points', 12000, int, 500, 20000)
        hour = _number_arg('hour_start_s', 0, float, 0, 2_678_400)
        return clinical_response(case, lambda: read_evidence(case, ('scatter', mode, points, hour),
            lambda: scatter_points(analysis_path(case), mode, points, hour)))

    @app.post("/api/cases/<case_id>/scatter-selection")
    def scatter_selection_endpoint(case_id: str):
        case = case_or_404(case_id)
        payload = _json_object()
        identity = linked_read_identity(case, payload)
        raw_polygon = payload.get("polygon")
        if not isinstance(raw_polygon, list):
            raise ValueError("polygon 必须为坐标数组")
        if not 3 <= len(raw_polygon) <= 128:
            raise ValueError("圈选边界必须包含 3–128 个点")
        mode = str(payload.get("mode", "rr") or "").lower()
        if mode not in SCATTER_MODES:
            raise ValueError("散点图模式必须是 rr、n、nn、s、v 或 hour")
        polygon: list[tuple[float, float]] = []
        for point in raw_polygon:
            if not isinstance(point, list) or len(point) != 2:
                raise ValueError("polygon 中每个点必须是 [x, y]")
            polygon.append(tuple(
                _coerce_json_number(value, "polygon 坐标", -1_000_000_000, 1_000_000_000)
                for value in point
            ))
        result = select_scatter_points(
            analysis_path(case),
            mode,
            polygon,
            _json_number(payload, "hour_start_s", 0, 0, 2_678_400),
        )
        linked_read_identity(case, identity)
        return jsonify({**result, **identity})

    @app.post("/api/cases/<case_id>/waveform-strips")
    def waveform_strips_endpoint(case_id: str):
        case = case_or_404(case_id)
        payload = _json_object()
        identity = linked_read_identity(case, payload)
        raw_samples = payload.get("sample_indices")
        if not isinstance(raw_samples, list) or not raw_samples:
            raise ValueError("sample_indices 必须是非空数组")
        if len(raw_samples) > 32:
            raise ValueError("每批最多读取 32 个波形片段")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in raw_samples):
            raise ValueError("sample_indices 必须全部为整数")
        if len(set(raw_samples)) != len(raw_samples):
            raise ValueError("sample_indices 不能重复")
        leads = payload.get("leads", ["II", "V1", "V5"])
        if not isinstance(leads, list) or not 1 <= len(leads) <= 6:
            raise ValueError("leads 必须包含 1–6 个导联")
        if any(not isinstance(lead, str) or lead not in ALL_LEADS for lead in leads) or len(set(leads)) != len(leads):
            raise ValueError("leads 包含不支持或重复的导联")
        pre_s = _json_number(payload, "pre_s", 1.5, 0.2, 3.0)
        post_s = _json_number(payload, "post_s", 2.5, 0.4, 5.0)
        if pre_s + post_s > 6:
            raise ValueError("波形片段总时长不能超过 6 秒")
        max_points = _json_number(payload, "max_points", 800, 200, 1200, integer=True)
        filter_mode = payload.get("filter", "display")
        if filter_mode not in {"display", "raw"}:
            raise ValueError("filter 必须是 display 或 raw")
        ebi_path = analysis_path(case)
        details = beat_details(ebi_path, raw_samples)
        if len(details) != len(raw_samples):
            raise ValueError("sample_indices 必须对应现有心搏位置")
        result = read_waveform_strips(
            Path(case["paths"]["data"]),
            raw_samples,
            pre_s,
            post_s,
            leads,
            max_points,
            filter_mode != "raw",
        )
        labels=waveform_labels(case,identity,[(w["start_s"],w["duration_s"]) for w in result["items"]],include_markers=True)
        for item, beats in zip(result["items"],labels):
            item["beats"]=beats
            item.update(details[item["sample_index"]])
            item['case_id'] = case_id
        linked_read_identity(case, identity)
        return jsonify({**result, **identity})

    def editor_summary(case, value):
        feed=edited_feed(case,value["document"])
        return dict(revision=value["revision"], settings=value["document"]["settings"],
            can_undo=value.get("can_undo", bool(value.get("undo"))), can_redo=value.get("can_redo", bool(value.get("redo"))), types=TYPES,
            metrics=ebi_metrics(feed,feed.duration), hrv=hrv(feed),
            type_counts=dict(__import__("collections").Counter(row["class_code"] for row in feed.beats)),
            markers=feed.markers, manual_longest=next((r for r in feed.beats if r["id"]==value["document"]["longest_id"]),None),
            note="按医生修订位置重算 RR；不生成自动疾病诊断，源 EBI 保留不变")

    @app.get("/api/cases/<case_id>/beat-editor")
    def beat_editor_get(case_id):
        return jsonify(editor_summary(case_or_404(case_id),editor.snapshot(case_id)))

    @app.get("/api/cases/<case_id>/beat-editor/beats")
    def beat_editor_beats(case_id):
        feed=edited_feed(case_or_404(case_id))
        return jsonify(items=feed.beats,markers=feed.markers)

    @app.get("/api/cases/<case_id>/overview")
    def overview_data(case_id):
        case = case_or_404(case_id)
        def build():
            snapshot = editor.snapshot(case_id)
            feed = edited_feed(case, snapshot["document"])
            return dict(revision=snapshot["revision"], duration_s=case["technical"]["duration_seconds_raw"],
                columns=["sample_index", "rr_ms", "class_code"],
                rows=[[r["sample_index"], r["rr_ms"], r["class_code"]] for r in feed.beats],
                estimated_beats=case["summary"].get("total_beats"), settings=feed.document["settings"])
        return clinical_response(case, lambda: read_evidence(case, ('overview',), build))

    @app.route("/api/cases/<case_id>/rhythm-review", methods=["GET", "PUT"])
    def rhythm_review(case_id):
        case = case_or_404(case_id)
        payload = _json_object() if request.method == "PUT" else request.args
        expected = {name: payload[name] for name in
                    ('case_id', 'analysis_basis', 'analysis_revision', 'beat_revision') if name in payload}
        if request.method == 'GET' and 'beat_revision' in expected:
            value = expected['beat_revision']
            if not value or not value.isascii() or not value.isdecimal():
                raise ValueError('心搏修订须为非负整数')
            expected['beat_revision'] = int(value)
        identity = linked_read_identity(case, expected)
        basis = {name: identity[name] for name in ('analysis_basis', 'analysis_revision')}
        snapshot = editor.snapshot(case_id)
        feed = edited_feed(case, snapshot["document"])
        duration = case["technical"]["duration_seconds_raw"]
        initial = initial_episodes(feed, storage.list_annotations(case_id), duration)
        revision = snapshot["revision"]
        if request.method == "GET":
            result = rhythms.public(rhythms.read(case_id, initial))
            linked_read_identity(case, identity)
            return jsonify({**result, **identity})
        linked_read_identity(case, identity)
        aliases = {}
        for event in clinical_index(case)['events']:
            if event.get('category') == 'AF' and event.get('rhythm_episode_id'):
                aliases.setdefault(event['rhythm_episode_id'], []).append(event['event_id'])
        result = rhythms.commit(case_id, payload, duration, initial, ACTOR, revision,
                                analysis_revision=basis['analysis_revision'], event_aliases=aliases)
        # This write advances review revision. Validate unchanged source/beat
        # identity, and expose the new global revision rather than comparing it
        # to the pre-write revision or confusing rhythm revision with beat revision.
        current = linked_read_identity(case, {name: identity[name] for name in
                                       ('case_id', 'analysis_basis', 'beat_revision')})
        return jsonify({**result, **current})
    @app.route("/api/cases/<case_id>/waveform-density", methods=["GET", "POST"])
    def waveform_density(case_id):
        case = case_or_404(case_id)
        batch = request.args.get('leads')
        leads = batch.split(',') if batch is not None else [request.args.get('lead', 'II')]
        if not 1 <= len(leads) <= 2 or len(set(leads)) != len(leads) or any(lead not in ALL_LEADS for lead in leads):
            raise ValueError('密度图需提供1–2个不同的有效导联')
        if batch is not None and 'lead' in request.args:
            raise ValueError('密度图单导联与批量导联参数不能同时提供')
        snapshot = editor.snapshot(case_id)
        payload = _json_object() if request.method == "POST" else {}
        if "revision" in payload and (type(payload["revision"]) is not int or payload["revision"] != snapshot["revision"]):
            raise ValueError("编辑版本已变化，请重新加载密度图")
        identity = linked_read_identity(case, {**payload, 'beat_revision': snapshot['revision']})
        if 'beat_revision' in payload and (type(payload['beat_revision']) is not int or payload['beat_revision'] != identity['beat_revision']):
            raise ReportConflict('心搏版本已变化，请重新读取当前图表')
        feed = edited_feed(case, snapshot["document"])
        code = request.args.get("class_code", "N")
        template_id = request.args.get("template_id")
        allowed = None
        if template_id:
            template = storage.get_beat_template(int(template_id))
            if not template or template["case_id"] != case_id:
                raise ValueError("模板不存在")
            with storage.connect() as db:
                refs = db.execute("SELECT beat_ids FROM beat_edit_template_refs WHERE template_id=? AND case_id=?", (int(template_id), case_id)).fetchone()
            beat_ids = set(json.loads(refs[0]) if refs else [f"s:{s}" for s in template["sample_indices"]])
            allowed = {r["sample_index"] for r in feed.beats if r["id"] in beat_ids}
        elif code not in TYPES and code not in ("all", "other"):
            raise ValueError("不支持的心搏类型")
        samples = tuple(r["sample_index"] for r in feed.beats if (r["sample_index"] in allowed if allowed is not None else code == "all" or (r["class_code"] not in ("N", "S", "V") if code == "other" else r["class_code"] == code)))
        gate = None
        if request.args.get("gate"):
            try:
                gate = tuple(float(x) for x in request.args["gate"].split(","))
            except ValueError:
                raise ValueError("形态框选范围错误")
            if len(gate) != 4 or not all(math.isfinite(x) for x in gate) or gate[0] > gate[1] or gate[2] > gate[3]:
                raise ValueError("形态框选范围错误")
        from ecg_core.overview import density_samples
        selected_samples = density_samples(samples, payload)
        results = [density(Path(case['paths']['data']), selected_samples, lead, gate,
                           payload.get('amplitude_limit')) for lead in leads]
        linked_read_identity(case, identity)
        if batch is None:
            return jsonify(**results[0], source_total=len(samples), revision=snapshot['revision'], **identity)
        # The exact selected population is identical for both leads. Transmit
        # it once; no beat or density bin is removed or sampled for this format.
        for result in results:
            result.pop('population_samples')
        return jsonify(items=results, population_samples=selected_samples,
                       source_total=len(samples), revision=snapshot['revision'], **identity)

    @app.post("/api/cases/<case_id>/beat-editor/preview")
    def beat_editor_preview(case_id):
        case=case_or_404(case_id);payload=_json_object();current=editor.snapshot(case_id)
        integer(payload.get("revision"),"编辑版本")
        if payload.get("revision")!=current["revision"]:raise ValueError("编辑版本已变化，请刷新")
        if payload.get("operation")=="detect":
            opts=current["document"]["settings"]
            start=_json_number(payload,"start_s",0,0,case["technical"]["duration_seconds_raw"])
            duration=_json_number(payload,"duration_s",10,1,60)
            wave=read_waveform(Path(case["paths"]["data"]),start,duration,[opts["lead"]],12000,False)
            feed=edited_feed(case,current["document"])
            candidates=propose_qrs(wave["leads"][opts["lead"]],round(wave["start_s"]*SAMPLE_RATE),
                [r["sample_index"] for r in feed.beats if r["group"]!=34],opts)
            return jsonify(candidates=candidates,revision=current["revision"],requires_confirmation=True,
                method="导数平方能量 / MAD 阈值 / 局部峰定位 / 不应期排重；研究候选，须逐一确认")
        changed,count=apply_operation(load_records(case["paths"]["ebi"]),current["document"],
            storage.list_beat_overrides(case_id),payload,case["technical"]["duration_seconds_raw"])
        return jsonify(affected=count,before=editor_summary(case,current),
            after=editor_summary(case,{**current,"document":changed}),requires_confirmation=True)

    @app.put("/api/cases/<case_id>/beat-editor")
    def beat_editor_commit(case_id):
        case=case_or_404(case_id);payload=_json_object()
        if payload.get("confirmed") is not True:raise ValueError("请确认预览后再提交")
        op=payload.get("operation")
        def transform(document):
            return apply_operation(load_records(case["paths"]["ebi"]),document,
                storage.list_beat_overrides(case_id),payload,case["technical"]["duration_seconds_raw"])[0]
        value=editor.commit(case_id,payload.get("revision"),ACTOR,transform,op)
        return jsonify(editor_summary(case,value))

    @app.get("/api/cases/<case_id>/beat-templates")
    def beat_templates(case_id: str):
        case=case_or_404(case_id)
        items=storage.list_beat_templates(case_id)
        if request.args.get("analysis")=="edited":
            feed=edited_feed(case);by_id={r["id"]:r for r in feed.beats}
            with storage.connect() as db:
                refs={row["template_id"]:json.loads(row["beat_ids"]) for row in db.execute("SELECT * FROM beat_edit_template_refs WHERE case_id=?",(case_id,))}
            for item in items:
                ids=refs.get(item["id"],[f"s:{s}" for s in item["sample_indices"]])
                item["sample_indices"]=sorted(by_id[key]["sample_index"] for key in ids if key in by_id)
                item["beat_count"]=len(item["sample_indices"])
        return jsonify({"items": items})

    @app.get("/api/cases/<case_id>/beat-overrides")
    def beat_overrides(case_id: str):
        case_or_404(case_id)
        return jsonify({"items": storage.list_beat_overrides(case_id)})

    def _validated_override_beats(case: dict, payload: dict) -> tuple[list[int], list[dict]]:
        raw_samples = payload.get("sample_indices")
        if not isinstance(raw_samples, list) or not raw_samples or len(raw_samples) > 500:
            raise ValueError("sample_indices 必须包含 1–500 个心搏")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in raw_samples):
            raise ValueError("sample_indices 必须全部为整数")
        if len(raw_samples) != len(set(raw_samples)):
            raise ValueError("sample_indices 不能重复")
        max_sample = int(case["technical"]["duration_seconds_raw"] * SAMPLE_RATE)
        if any(value < 0 or value >= max_sample for value in raw_samples):
            raise ValueError("sample_indices 超出记录范围")
        details = beat_details(Path(case["paths"]["ebi"]), raw_samples)
        if len(details) != len(raw_samples):
            raise ValueError("sample_indices 必须对应源 EBI 中的心搏")
        return raw_samples, [details[sample] for sample in raw_samples]

    @app.put("/api/cases/<case_id>/beat-overrides")
    def beat_override_update(case_id: str):
        case = case_or_404(case_id)
        payload = _json_object()
        _, details = _validated_override_beats(case, payload)
        class_code = payload.get("class_code")
        if not isinstance(class_code, str):
            raise ValueError("缺少人工心搏类型")
        items = storage.set_beat_overrides(case_id, details, class_code.upper(), ACTOR)
        return jsonify({"items": items, "changed": len(items)})

    @app.delete("/api/cases/<case_id>/beat-overrides")
    def beat_override_restore(case_id: str):
        case = case_or_404(case_id)
        payload = _json_object()
        samples, _ = _validated_override_beats(case, payload)
        return jsonify({"ok": True, "changed": storage.clear_beat_overrides(case_id, samples, ACTOR)})

    @app.post("/api/cases/<case_id>/beat-templates")
    def beat_template_create(case_id: str):
        case = case_or_404(case_id)
        payload = _json_object()
        raw_samples = payload.get("sample_indices")
        if not isinstance(raw_samples, list) or not raw_samples:
            raise ValueError("sample_indices 必须是非空数组")
        if len(raw_samples) > 250000:
            raise ValueError("单个模板类别最多保存 250000 个心搏")
        if "revision" in payload and (type(payload["revision"]) is not int or payload["revision"] != editor.snapshot(case_id)["revision"]):
            raise ValueError("编辑版本已变化，请重新加载密度图")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in raw_samples):
            raise ValueError("sample_indices 必须全部为整数")
        max_sample = int(case["technical"]["duration_seconds_raw"] * SAMPLE_RATE)
        if any(value < 0 or value >= max_sample for value in raw_samples):
            raise ValueError("sample_indices 超出记录范围")
        feed = edited_feed(case)
        details = {s: feed.by_sample[s] for s in set(raw_samples) if s in feed.by_sample}
        if len(details) != len(raw_samples):
            raise ValueError("sample_indices 必须对应现有心搏位置")
        source_class = payload.get("source_class", "")
        if not isinstance(source_class, str):
            raise ValueError("父类别标识不合法")
        if source_class:
            source_classes = {"source-"+code: code for code in TYPES}
            if source_class == "source-other":
                if any(details[sample]["class_code"] in ("N", "S", "V") for sample in raw_samples):
                    raise ValueError("选中心搏不属于其他心搏集合")
            elif source_class in source_classes:
                expected_class = source_classes[source_class]
                if any(details[sample]["class_code"] != expected_class for sample in raw_samples):
                    raise ValueError("选中心搏不属于指定的源类别")
            else:
                if not source_class.startswith("custom-"):
                    raise ValueError("父类别不存在")
                try:
                    parent_id = int(source_class.removeprefix("custom-"))
                except ValueError as exc:
                    raise ValueError("父类别不存在") from exc
                parent = storage.get_beat_template(parent_id)
                if parent is None or parent["case_id"] != case_id:
                    raise ValueError("父类别不存在或不属于当前病例")
                with storage.connect() as db:
                    refs = db.execute("SELECT beat_ids FROM beat_edit_template_refs WHERE template_id=? AND case_id=?", (parent_id, case_id)).fetchone()
                parent_ids = set(json.loads(refs[0]) if refs else [f"s:{s}" for s in parent["sample_indices"]])
                parent_samples = {r["sample_index"] for r in feed.beats if r["id"] in parent_ids}
                if not set(raw_samples) <= parent_samples:
                    raise ValueError("选中心搏不属于指定的父模板")
        item=storage.create_beat_template(case_id, payload, ACTOR)
        feed=edited_feed(case);by_sample=feed.by_sample
        ids=[by_sample[s]["id"] for s in raw_samples if s in by_sample]
        with storage.connect() as db:
            db.execute("INSERT INTO beat_edit_template_refs VALUES(?,?,?)",(item["id"],case_id,json.dumps(ids)))
        return jsonify(item), 201

    @app.patch("/api/beat-templates/<int:template_id>")
    def beat_template_update(template_id: int):
        existing = storage.get_beat_template(template_id)
        if existing is None:
            return jsonify({"error": "模板类别不存在"}), 404
        case_or_404(existing["case_id"])
        return jsonify(storage.update_beat_template(template_id, _json_object(), ACTOR))

    @app.delete("/api/beat-templates/<int:template_id>")
    def beat_template_delete(template_id: int):
        existing = storage.get_beat_template(template_id)
        if existing is None:
            return jsonify({"error": "模板类别不存在"}), 404
        case_or_404(existing["case_id"])
        storage.delete_beat_template(template_id, ACTOR)
        return jsonify({"ok": True})

    @app.get("/api/cases/<case_id>/review-workflow")
    def review_workflow_get(case_id: str):
        case_or_404(case_id)
        return jsonify(storage.get_review(case_id))

    @app.put("/api/cases/<case_id>/review-workflow")
    def review_workflow_put(case_id: str):
        case_or_404(case_id)
        return jsonify(storage.complete_review(case_id, _json_object(), ACTOR))

    @app.put("/api/cases/<case_id>/event-reviews")
    def event_review_put(case_id: str):
        case = case_or_404(case_id)
        payload = _json_object()
        records = payload.get("items", [])
        if not isinstance(records, list) or not 1 <= len(records) <= 500:
            raise ValueError("每次处理 1–500 个事件")
        samples = [item.get("sample_index") for item in records if isinstance(item, dict)]
        if any(isinstance(sample, bool) or not isinstance(sample, int) for sample in samples):
            raise ValueError("事件心搏必须为整数")
        details = beat_details(analysis_path(case), samples)
        valid = set(details)
        return jsonify(storage.save_event_review(case_id, payload, ACTOR, valid))

    @app.get("/api/cases/<case_id>/events")
    def events_endpoint(case_id: str):
        case = case_or_404(case_id)
        feed=analysis_path(case)
        if hasattr(feed,"document"):
            # Page filters are transient; the right-menu settings remain the saved default.
            feed.document["settings"]={**feed.document["settings"],**{
                key:_number_arg(key,feed.document["settings"][key],kind,lo,hi)
                for key,kind,lo,hi in (("brady",int,20,100),("tachy",int,80,250),("pause",float,1.5,10)) if key in request.args}}
        return jsonify(list_events(
            feed,
            request.args.get("type", "all"),
            _number_arg("offset", 0, int, 0),
            _number_arg("limit", 200, int, 1, 1000),
            _number_arg("brady", 50, int, 20, 100),
            _number_arg("tachy", 120, int, 80, 250),
            _number_arg("pause", 2.5, float, 1.5, 10),
        ))

    @app.get("/api/cases/<case_id>/annotations")
    def annotations(case_id: str):
        case=case_or_404(case_id)
        return jsonify({"items": stt_annotation_items(case)})

    def stt_annotation_items(case):
        items=storage.list_annotations(case['case_id'])
        if not any(a.get('details',{}).get('kind') in ('ST','ST_REVIEW_NOTE') for a in items):return items
        from ecg_core.stt_records import ST_KINDS, decorate_event, mark_stale, use_for
        from ecg_core.clinical_analysis import beat_basis_version
        identity=linked_read_identity(case)
        annotations_digest=provenance_digest(items)
        beat_version=beat_basis_version(edited_feed(case))
        report=storage.get_report(case['case_id'],'')
        # A receipt depends on the authored record and beat/settings identity.
        # The shared decorator is exactly the one used in the full index;
        # unrelated RR/AF candidates and whole-record event statistics add no
        # eligibility evidence here and need not be generated after this save.
        for item in items:
            if item.get('details',{}).get('kind') not in ST_KINDS:continue
            event=decorate_event({'event_id':'annotation:'+str(item['id'])},item,beat_version)
            source_scope=event.get('stt_source_scope')
            if source_scope and any(source_scope.get(k)!=identity[k] for k in ('case_id','analysis_basis','beat_revision')):
                mark_stale(event)
            item['stt_review_receipt']={**event['stt_review_receipt'],'report_use':use_for(report['composition'],event)}
        linked_read_identity(case,identity)
        if provenance_digest(storage.list_annotations(case['case_id'])) != annotations_digest:
            raise ReportConflict('ST-T复核记录已变化，请重新读取')
        return items

    def save_stt_annotation(case,payload,annotation_id=None):
        from ecg_core.stt_records import digest,protocol,RESULTS,normalized_findings
        from ecg_core.stt import LEADS
        from uuid import UUID
        details=payload.get('details')
        if not isinstance(details,dict) or details.get('reviewed') is not True or details.get('result_code') not in RESULTS:raise ValueError('请选择并保存本条医生复核结果')
        identifier=details.get('submission_id')
        if not isinstance(identifier,str) or str(UUID(identifier))!=identifier:raise ValueError('ST-T提交编号须为规范UUID')
        request_hash=digest(payload)
        scope=details.get('review_scope')
        if not isinstance(scope,dict) or any(k not in scope for k in ('case_id','analysis_basis','analysis_revision','beat_revision')):raise ValueError('ST-T保存缺少当前完整依据')
        def source_guard(db=None):linked_read_identity(case,{k:scope[k] for k in ('case_id','analysis_basis','beat_revision')})
        previous=storage.stt_replay(case['case_id'],identifier,request_hash,'create' if annotation_id is None else 'update',annotation_id)
        if previous:
            source_guard()
            return next(a for a in stt_annotation_items(case) if a['id']==previous['id'])
        identity=linked_read_identity(case,scope)
        first=payload.get('sample_index');end=details.get('end_sample')
        if type(first) is not int or type(end) is not int or not 0<=first<=end<round(case['technical']['duration_seconds_raw']*200):raise ValueError('ST-T复核完整范围超出记录')
        leads=details.get('review_leads')
        if not isinstance(leads,list) or not leads or len(set(leads))!=len(leads) or any(x not in LEADS for x in leads):raise ValueError('请选择实际复核导联，查看导联不代表异常导联')
        if 'stt_event_evidence' in details:raise ValueError('ST-T事件证据须由服务器核验')
        chosen=None
        if details.get('stt_candidate_id'):
            candidate_scope=details.get('stt_candidate_scope')
            if not isinstance(candidate_scope,dict) or any(k not in candidate_scope for k in ('case_id','analysis_basis','analysis_revision','beat_revision')):raise ValueError('ST-T候选须提供当前完整筛查依据')
            linked_read_identity(case,candidate_scope)
            measured=stt_candidate_projection(case,candidate_scope)
            chosen=next((c for c in measured['automatic_candidates']['items'] if c['id']==details['stt_candidate_id']),None)
            if chosen is None:raise ReportConflict('原ST-T候选已变化，请重选后核对')
        attached=details.get('range_statistics')
        if attached is not None:
            validate_stt_range_snapshot(case,attached)
            if not first<=attached['range']['start_sample']<attached['range']['end_sample']<=end+1:raise ValueError('附加均值统计须位于本次完整复核范围内')
        details['measurement_protocol']=protocol(details.get('measurement_protocol'))
        if details['measurement_protocol']['extent']=='whole' and details['measurement_protocol']['baseline_method']!='pre_qrs_stable':raise ValueError('整段逐搏统计仅支持既定逐搏基线；手工ISO仅用于本点测量')
        point_measurement=details.get('point_measurement')
        if point_measurement is not None:
            if not isinstance(point_measurement,dict) or any(type(point_measurement.get(k)) is not int or not 0<=point_measurement[k]<round(case['technical']['duration_seconds_raw']*200) for k in ('iso_sample','j_sample','measurement_sample')):raise ValueError('ST-T手工点测量位置无效')
            if not point_measurement['iso_sample']<point_measurement['j_sample']<=point_measurement['measurement_sample']:raise ValueError('ST-T手工ISO/J次序无效')
            if point_measurement.get('measurement_ms')!=details['measurement_protocol']['measurement_ms'] or abs(point_measurement['measurement_sample']-point_measurement['j_sample']-details['measurement_protocol']['measurement_ms']/5)>1:raise ValueError('手工测量位置与STJ/ST60/ST80协议不一致')
            point_leads=point_measurement.get('leads')
            if not isinstance(point_leads,list) or not point_leads or len(set(point_leads))!=len(point_leads) or any(x not in LEADS for x in point_leads):raise ValueError('ST-T点测量导联无效')
            window_start=point_measurement.get('window_start_s');window_duration=point_measurement.get('window_duration_s')
            if any(type(x) not in (int,float) or not math.isfinite(x) for x in (window_start,window_duration)) or not 0<=window_start<window_start+window_duration<=case['technical']['duration_seconds_raw']+1e-8:raise ValueError('ST-T点测量窗口无效')
            if not window_start*200-1<=point_measurement['iso_sample']<point_measurement['measurement_sample']<=(window_start+window_duration)*200+1:raise ValueError('ST-T点测量位置不在显示窗口内')
        findings=normalized_findings(details,first,end,leads)
        if 'findings' in details:details['findings']=findings
        extent=details.get('review_extent','point')
        if extent not in ('point','whole'):raise ValueError('ST-T复核作用范围无效')
        if extent=='whole':
            machine_protocol=protocol(dict(measurement_ms=details['measurement_protocol']['measurement_ms'] if details['measurement_protocol']['extent']=='whole' else 60,extent='whole'))
            from ecg_core.stt_records import RHYTHM_POLICY,ST_RESULTS,T_RESULTS
            cached_statistics={}
            def whole_statistics(a,b,names):
                key=(a,b,tuple(names))
                if key not in cached_statistics:
                    cached_statistics[key]=stt_range_result(case,dict(scope=identity,start_sample=a,end_sample=b+1,leads=names,measurement_ms=machine_protocol['measurement_ms']))
                return cached_statistics[key]
            child_proofs=[]
            for finding in findings:
                code=finding['result_code'];a,b=finding['start_sample'],finding['end_sample'];names=finding['leads']
                kind=code if code in (*ST_RESULTS,*T_RESULTS) else 'stt_review'
                exact=(chosen is not None and chosen['kind']==kind and a==round(chosen['start_s']*200)
                       and b+1==round(chosen['end_s']*200) and set(names)<=set(chosen['leads']))
                proof={k:chosen[k] for k in ('continuous_target_s','peak_time_s','peak_deviation_units','quality_score',
                    'criteria','measurement_basis','reference_source','quality_flags','boundary_resolution_s','reference_context',
                    'peak_st_level_units','peak_t_amplitude_units','polarity_from','polarity_to') if exact and k in chosen} if chosen else {}
                proof.update(kind=kind,result_code=code,start_s=a/200,end_s=(b+1)/200,duration_s=(b+1-a)/200,leads=list(names),
                    measurement_protocol=copy.deepcopy(machine_protocol),units='source_device_units',rhythm_policy=RHYTHM_POLICY,
                    source='reviewed_automatic_candidate' if exact else 'physician_selected_range',
                    original_machine_range={k:chosen[k] for k in ('start_s','end_s')} if chosen else None)
                if chosen:proof['candidate_id']=chosen['id']
                if b+1-a>=12000:
                    statistics=whole_statistics(a,b,names)
                    proof['metrics']=statistics['leads'];proof['coverage']=statistics['coverage'];proof['counts']=statistics['counts']
                    proof['measurement_protocol']['range_profile']=statistics['method_profile']
                    # Real source anchors, separate from the physician's full event range.
                    extrema=('minimum_absolute_t_units','minimum_absolute_t_sample') if kind=='t_low_flat' else ('minimum_t_amplitude_units','minimum_t_sample') if kind=='t_persistent_inversion' else None
                    if extrema and not exact:
                        usable=[m for m in statistics['leads'] if isinstance(m.get(extrema[0]),(int,float)) and type(m.get(extrema[1])) is int]
                        if usable:
                            extreme=min(usable,key=lambda m:m[extrema[0]])
                            proof['peak_time_s']=extreme[extrema[1]]/200
                proof.setdefault('boundary_resolution_s',.005 if not exact else chosen.get('boundary_resolution_s'))
                proof.setdefault('continuous_target_s',None)
                child_proofs.append(proof)
            # Keep the familiar flat proof for one finding. Composite records own
            # independent child ranges without multiplying their report identity.
            if len(child_proofs)==1:
                proof=child_proofs[0]
            else:
                proof=dict(kind='stt_composite',start_s=first/200,end_s=(end+1)/200,duration_s=(end+1-first)/200,
                    leads=list(leads),measurement_protocol=machine_protocol,units='source_device_units',rhythm_policy=RHYTHM_POLICY,
                    source='physician_selected_range',findings=child_proofs)
                timed=[r for r in child_proofs if isinstance(r.get('peak_time_s'),(int,float))]
                if timed:proof['peak_time_s']=timed[0]['peak_time_s']
            proof['scope']=identity
            if chosen:proof['algorithm_version']=measured['analysis']['algorithm_version']
            details['stt_event_evidence']=proof
        from ecg_core.stt_compatibility import make_input_binding
        details['stt_input_binding']=make_input_binding(edited_feed(case),identity,runtime.basis(case))
        item=storage.save_stt_record(case['case_id'],payload,ACTOR,guard=candidate_guard(case,identity),replay_guard=source_guard,
            request_sha256=request_hash,annotation_id=annotation_id,expected_record_version=payload.get('expected_record_version'))
        updated=next(a for a in stt_annotation_items(case) if a['id']==item['id'])
        if 'stt_report_reconciliation' in item:updated['stt_review_receipt']['report_reconciliation']=item['stt_report_reconciliation']
        return updated

    @app.put('/api/cases/<case_id>/annotations/<int:annotation_id>')
    def stt_annotation_update(case_id,annotation_id):
        return jsonify(save_stt_annotation(case_or_404(case_id),_json_object(),annotation_id))

    @app.post("/api/cases/<case_id>/annotations")
    def annotation_create(case_id: str):
        case = case_or_404(case_id)
        payload = _json_object()
        if isinstance(payload.get('details'),dict) and payload['details'].get('reviewed') is True:
            return jsonify(save_stt_annotation(case,payload)),201
        sample_index = payload.get("sample_index", 0)
        if isinstance(sample_index, bool) or not isinstance(sample_index, (int, float)) or int(sample_index) != sample_index:
            raise ValueError("sample_index 必须为整数")
        if not 0 <= int(sample_index) < int(case["technical"]["duration_seconds_raw"] * SAMPLE_RATE):
            raise ValueError("sample_index 超出记录范围")
        payload["sample_index"] = int(sample_index)
        if isinstance(payload.get("details"),dict) and payload["details"].get("end_sample",sample_index)>=int(case["technical"]["duration_seconds_raw"]*SAMPLE_RATE):
            raise ValueError("结束位置超出记录范围")
        details = payload.get('details') or {}
        statistics = details.get('range_statistics') if isinstance(details, dict) else None
        candidate_identity = None
        if isinstance(details,dict) and 'stt_event_evidence' in details:
            raise ValueError('ST-T 机器事件证据须由当前候选读取并核验，不能由客户端自行填入')
        if isinstance(details,dict) and 'stt_candidate_id' in details:
            if details.get('kind')!='ST' or statistics is not None:raise ValueError('自动 ST-T 整段复核与范围均值分别保存')
            scope=details.get('stt_candidate_scope')
            if not isinstance(scope,dict) or any(k not in scope for k in ('case_id','analysis_basis','analysis_revision','beat_revision')):
                raise ValueError('整段 ST-T 复核须提供完整读取依据')
            candidate_identity=linked_read_identity(case,scope)
            measured=stt_candidate_projection(case,scope)
            candidate=next((r for r in measured.get('automatic_candidates',{}).get('items',[]) if r['id']==details['stt_candidate_id']),None)
            if not candidate:raise ReportConflict('ST-T 连续事件依据已变化，请重新读取候选')
            start=round(candidate['start_s']*200);end=round(candidate['end_s']*200)
            if payload['sample_index']!=start or details.get('end_sample')!=end-1:
                raise ValueError('整段 ST-T 复核范围须与所选候选完整起止一致')
            from ecg_core.stt_records import protocol,RHYTHM_POLICY
            details['stt_event_evidence']={**{key:candidate[key] for key in ('kind','start_s','end_s','duration_s','continuous_target_s','peak_time_s','peak_deviation_units','leads','quality_score')},
                'candidate_id':candidate['id'],'algorithm_version':measured['analysis']['algorithm_version'],
                'measurement_protocol':protocol(dict(extent='whole')),'rhythm_policy':RHYTHM_POLICY,
                'boundary_resolution_s':candidate.get('boundary_resolution_s'),
                **{key:candidate[key] for key in ('criteria','measurement_basis','reference_source','quality_flags','peak_st_level_units','peak_t_amplitude_units','polarity_from','polarity_to') if key in candidate},
                'scope':candidate_identity,'source':'reviewed_automatic_candidate','units':'source_device_units'}
        if statistics is not None:
            if details.get('kind') != 'ST': raise ValueError('ST 区间统计不能用于其他标注类型')
            previous = storage.annotation_submission(case_id, payload)
            if previous is not None:
                old_scope = previous['details']['range_statistics']['scope']
                current = linked_read_identity(case, {key: old_scope[key] for key in
                                                      ('case_id', 'analysis_basis', 'beat_revision')})
                if current['analysis_revision'] != old_scope['analysis_revision'] + 1:
                    raise ReportConflict('已保存统计后还有其他复核修订；请回看已保存标注并重新计算，未重复保存')
                return jsonify(previous), 201
            identity = validate_stt_range_snapshot(case, statistics)
            chosen = statistics['range']
            if (payload['sample_index'] != chosen['start_sample']
                    or details.get('end_sample') != chosen['end_sample'] - 1):
                raise ValueError('标注范围与已计算的半开样本范围不一致')
            point = details.get('point_measurement_sample_index')
            if point is not None and (type(point) is not int or not 0 <= point < int(case['technical']['duration_seconds_raw'] * SAMPLE_RATE)):
                raise ValueError('手工点测量位置超出原始记录范围')
            def source_guard():
                if runtime.basis(case)['digest'] != identity['analysis_basis']:
                    raise ReportConflict('区间统计来源已变化，请重新计算后保存')
            def provenance_guard(db):
                source_guard()
                if editor.snapshot(case_id, db=db)['revision'] != identity['beat_revision']:
                    raise ReportConflict('区间统计逐搏修订已变化，未保存；请重新计算后核对')
                row = db.execute('SELECT basis FROM case_analysis_basis WHERE case_id=?', (case_id,)).fetchone()
                if not row or json.loads(row['basis'])['digest'] != identity['analysis_basis']:
                    raise ReportConflict('区间统计依据已变化，未保存')
            def guard(db):
                provenance_guard(db)
                if storage._review(db, case_id)['revision'] != identity['analysis_revision']:
                    raise ReportConflict('区间统计修订已变化，未保存；请重新计算后核对')
            def replay_guard(db):
                provenance_guard(db)
                if storage._review(db, case_id)['revision'] != identity['analysis_revision'] + 1:
                    raise ReportConflict('已保存统计后还有其他复核修订，请回看标注后重新计算；未重复保存')
            item = storage.create_annotation(case_id, payload, ACTOR, guard=guard,
                                             source_guard=source_guard, replay_guard=replay_guard)
        elif candidate_identity is not None:
            def stt_source_guard():
                if runtime.basis(case)['digest']!=candidate_identity['analysis_basis']:raise ReportConflict('ST-T 原始来源已变化，本次复核未保存')
            item=storage.create_annotation(case_id,payload,ACTOR,guard=candidate_guard(case,candidate_identity),source_guard=stt_source_guard)
        else:
            item = storage.create_annotation(case_id, payload, ACTOR)
        return jsonify(item), 201

    @app.delete("/api/annotations/<int:annotation_id>")
    def annotation_delete(annotation_id: int):
        if not storage.delete_annotation(annotation_id, ACTOR):
            return jsonify({"error": "标注不存在"}), 404
        return jsonify({"ok": True})

    @app.get("/api/cases/<case_id>/report")
    def report_get(case_id: str):
        case = case_or_404(case_id)
        report=storage.get_report(case_id,case['conclusion'])
        return jsonify({**report, 'current_analysis_basis':runtime.basis(case), 'current_hrv_reference':hrv_reference(case,report['composition'].get('hrv_window',0))})

    @app.put("/api/cases/<case_id>/report")
    def report_put(case_id: str):
        case = case_or_404(case_id)
        basis = runtime.basis(case)
        payload = _json_object()
        if type(payload.get("expected_version")) is not int or payload["expected_version"] < 1:
            raise ValueError("缺少有效的报告版本，请重新载入后保存")
        progress = storage.get_review(case_id)
        if "expected_review_revision" in payload:
            if type(payload["expected_review_revision"]) is not int or payload["expected_review_revision"] < 0:
                raise ValueError("病例复核版本必须为非负整数")
            if payload["expected_review_revision"] != progress["revision"]:
                raise ReportConflict("病例复核依据已变化，报告未保存；请重新载入后核对")
        conclusion = payload.get("conclusion", "")
        status = payload.get("status", "draft")
        composition = payload.get("composition")
        if not isinstance(conclusion, str) or not isinstance(status, str):
            raise ValueError("conclusion 和 status 必须为文本")
        if composition is not None and not isinstance(composition, dict):
            raise ValueError("composition 必须为 JSON 对象")
        index = clinical_index(case_or_404(case_id))
        raw_composition=copy.deepcopy(composition if composition is not None else storage.get_report(case_id, "")["composition"])
        # Only newly supplied settings without leads receive the ST/T default.
        # Existing 1/3/12-lead curation is explicit and remains unchanged.
        if isinstance(raw_composition.get('selected_events'),list):
            st_ids={e['event_id'] for e in index['events'] if e.get('category')=='ST'}
            for selection in raw_composition['selected_events']:
                if isinstance(selection,dict) and selection.get('event_id') in st_ids and 'leads' not in selection:
                    selection['leads']=list(ALL_LEADS)
        composition=normalize_report_composition(raw_composition)
        composition['selected_events'], merged_rr = deduplicate_rr_selections(index, composition.get('selected_events', []))
        validate_report(index,composition,progress,status=="reviewed")
        if composition.get('include_hrv') or any(k.startswith('hrv_') for k in composition.get('included_pages',[])):
            assert_hrv_reference(case,composition.get('hrv_review_reference'),composition.get('hrv_window',0), require_confirmation=status=='reviewed')
        if composition.get('advanced_options',{}).get('markers'):
            case=case_or_404(case_id)
            advanced_evidence(case,clinical_index(case),composition['advanced_options'])
        saved = storage.save_report(case_id, conclusion, status, ACTOR, composition,
                                    payload["expected_version"], progress["revision"], basis['digest'],
                                    lambda: assert_source_basis(case, basis))
        return jsonify({**saved, 'rr_merged_event_ids': merged_rr})

    def report_source_token(case):
        progress = storage.get_review(case["case_id"])
        basis = runtime.basis(case)
        state=hrv_state(case,0)
        return (progress["report_version"], progress["revision"], basis['digest'],state['hrv_revision'],state['digest'],sha256(canonical(storage.list_candidates(case['case_id'])).encode()).hexdigest())

    @app.get("/api/cases/<case_id>/report.pdf")
    def report_pdf(case_id: str):
        case = case_or_404(case_id)
        source_token = report_source_token(case)
        if "expected_version" in request.args and _number_arg("expected_version", 1, int, 1) != source_token[0]:
            raise ReportConflict("报告版本已变化，请重新载入后导出")
        if "expected_review_revision" in request.args and _number_arg("expected_review_revision", 0, int, 0) != source_token[1]:
            raise ReportConflict("病例复核依据已变化，请重新载入后导出")
        include_phi = include_phi_authorized()
        report_case = case_with_overrides(case)
        if not include_phi:
            report_case = _masked_report_case(report_case)
        report_case['case_id']=app.config.get('REPORT_CASE_DISPLAY_IDS',{}).get(case_id,case_id)
        if case_id in app.config.get('REPORT_CASE_DISPLAY_IDS', {}):
            report_case['display_case_id'] = report_case['case_id']
        calculated = ebi_metrics(edited_feed(case), case["technical"]["duration_seconds_raw"])
        report = storage.get_report(case_id, case["conclusion"])
        if report['status']=='reviewed':
            proof=report.get('analysis_provenance',{})
            if (proof.get('basis',{}).get('digest')!=source_token[2]
                    or proof.get('composition_sha256')!=provenance_digest(report['composition'])):
                raise ReportConflict('报告审核依据缺失或已变化，请保存草稿并重新复核后导出')
        report["review_snapshot"] = storage.get_review(case_id)
        edit_snapshot = editor.snapshot(case_id)
        report["override_count"] = len(storage.list_beat_overrides(case_id)) + len(edit_snapshot["document"]["changes"])
        report["edited_analysis"] = True
        report["analysis_revision"] = edit_snapshot["revision"]
        index=clinical_index(case)
        resolved=validate_report(index,report['composition'],report['review_snapshot'],report['status']=='reviewed')
        unique_entries, _ = deduplicate_rr_selections(index, report['composition'].get('selected_events', []))
        used_entries=[s for s in unique_entries if used_in_output(report['composition'],s,next((e for e in index['events'] if e['event_id']==s['event_id']),None))]
        resolved=[e for e in resolved if used_in_output(report['composition'],e,e)]
        if len(resolved)!=len(used_entries):
            raise ValueError('已选图条失效，请重新筛选后导出')
        report['selected_waveforms']=[prepare_strip(index, e, e, lambda a,b,leads,points: read_event_waveform(case['paths']['data'],a,b,leads,points)) for e in resolved]
        report['paper_statistics']=report_statistics(index,case['metadata'].get('start_iso') or case['metadata'].get('start_time'),edited_feed(case).document['settings'],report['composition'].get('pause_edges_ms'))
        report['paper_statistics']['hrv']=hrv(edited_feed(case))
        report['event_statistics']=query_index(index,{'fast_slow_mode':report['composition'].get('fast_slow_mode','rr')})
        from ecg_core.report_sections import evidence, validate_pages
        page_keys=validate_pages(report['composition'])
        supplemental_pages=set(page_keys)-{'cover','summary','hourly','event_strips','hrv_time','hrv_frequency','hrv_overview'}
        if supplemental_pages.intersection({'st_trend','t_trend','st_events'}):
            report['section_evidence']=report_section_evidence(case,index)
        elif supplemental_pages:
            # Non-ST pages consume only event/RR evidence. The selected ST pages
            # above retain all-day measurements and representative source beats.
            report['section_evidence']=evidence(index)
        if any(k in page_keys for k in ('qtd','vcg','twa','sap')):
            report['section_evidence']['advanced']=advanced_evidence(case,index,report['composition'].get('advanced_options'))
        if any(k.startswith('hrv_') for k in page_keys):
            assert_hrv_reference(case,report['composition'].get('hrv_review_reference'),report['composition'].get('hrv_window',0),require_confirmation=report['status']=='reviewed')
            report['hrv_analysis']=hrv_evidence(case,report['composition'].get('hrv_window',0))
        privacy_mode = "phi-visible" if include_phi else "masked"
        pdf = build_report_pdf(report_case, calculated, report)
        if report_source_token(case) != source_token:
            raise ReportConflict("导出期间病例或报告已变化，未生成下载；请核对最新版本后重试")
        pdf_digest=sha256(pdf.getbuffer()).hexdigest()
        storage.audit(ACTOR, "report.export_pdf", case_id, f"version={report['version']} review_revision={source_token[1]} privacy={privacy_mode} basis={source_token[2]} sha256={pdf_digest}")
        response = send_file(pdf, mimetype="application/pdf", as_attachment=True, download_name=f"{report_case['case_id']}_心电分析复核报告.pdf")
        response.headers["X-Privacy-Mode"] = privacy_mode
        response.headers["X-Execution-Engine"] = runtime.engine_id
        response.headers["X-Report-Version"] = str(source_token[0])
        response.headers["X-Review-Revision"] = str(source_token[1])
        response.headers['X-Analysis-Basis'] = source_token[2]
        response.headers['X-Report-SHA256'] = pdf_digest
        if report.get('hrv_analysis'):
            response.headers['X-HRV-Revision']=str(source_token[3])
            response.headers['X-HRV-Document-Digest']=source_token[4]
            response.headers['X-HRV-Profile']=report['hrv_analysis']['hrv_review']['profile']
        return response

    @app.get("/api/cases/<case_id>/source-report/page/<int:page>")
    def source_report_page(case_id: str, page: int):
        if not include_phi_authorized():
            return jsonify({"error": "原报告包含可识别健康信息，请先显式解除遮蔽"}), 403
        case = case_or_404(case_id)
        paths = case["paths"]["report_images"]
        if page < 1 or page > len(paths):
            return jsonify({"error": "报告页不存在"}), 404
        return send_file(paths[page - 1], mimetype="image/png", conditional=True)

    @app.get("/api/audit")
    def audit():
        if app.config["DEMO_READONLY"]:
            abort(404)
        return jsonify({"items": storage.list_audit(_number_arg("limit", 200, int, 1, 1000))})

    @app.get("/api/settings")
    def settings():
        if app.config["DEMO_READONLY"]:
            abort(404)
        manifest = repository._manifest()
        return jsonify({
            "app_name": APP_NAME,
            "version": APP_VERSION,
            "data_root": str(resolved_root) if resolved_root else "未找到",
            "case_count": len(repository.list_cases()),
            "integrity_manifest": {
                "available": bool(manifest),
                "case_count": manifest.get("case_count", 0),
                "algorithm": manifest.get("algorithm", ""),
                "dataset_sha256": manifest.get("dataset_sha256", ""),
                "created_at": manifest.get("created_at", ""),
            },
            "supported_leads": ALL_LEADS,
            "raw_format": {"sample_rate_hz": 200, "channels": 8, "sample_type": "int16 little-endian"},
            "default_thresholds": {"brady_bpm": 50, "tachy_bpm": 120, "pause_s": 2.5, "notch_hz": 50, "display_band_hz": "0.5–40"},
            "platform": platform_info(),
            "clinical_use": False,
        })

    def local_backup_allowed():
        try:
            local = ipaddress.ip_address(request.remote_addr or '').is_loopback
        except ValueError:
            local = False
        return local and not (app.config['DEMO_READONLY'] or app.config['DEMO_AUTH_ENABLED'] or app.config['TRUST_PROXY_HEADERS'])

    @app.get('/api/workspace/backups')
    def workspace_backups():
        if not local_backup_allowed():
            return jsonify({'enabled': False, 'reason': '备份仅允许在本机非演示服务使用，不通过远程或代理开放', 'items': []})
        try:
            items = list_backups(backup_directory)
        except OSError:
            return jsonify({'error': '备份目录不可读取，请检查目录权限后重试'}), 503
        return jsonify({'enabled': True, 'directory': str(backup_directory.resolve()),
                        'items': items, 'recovered_workspace': bool(workspace_epoch)})

    @app.post('/api/workspace/backups')
    def workspace_backup_create():
        if not local_backup_allowed():
            return jsonify({'error': '备份仅允许在本机非演示服务使用'}), 403
        if _json_object().get('saved_work_acknowledged') is not True:
            return jsonify({'error': '请先保存需要保留的修改，并确认备份范围'}), 400
        if not backup_lock.acquire(blocking=False):
            return jsonify({'error': '已有备份或校验正在运行，请完成后重试'}), 409
        try:
            result = create_backup(storage.path, backup_directory)
            try:
                storage.audit(ACTOR, 'workspace.backup_created', detail='sha256=' + result['sha256'])
            except Exception:
                app.logger.exception('Backup created but audit write failed')
                result['warning'] = '备份已校验，但审计写入失败；请检查数据库可写状态'
            return jsonify(result), 201
        except BackupError as error:
            return jsonify({'error': str(error)}), 503
        finally:
            backup_lock.release()

    @app.post('/api/workspace/backups/<name>/verify')
    def workspace_backup_verify(name):
        if not local_backup_allowed():
            return jsonify({'error': '备份校验仅允许在本机非演示服务使用'}), 403
        if not BACKUP_NAME.fullmatch(name):
            return jsonify({'error': '无效的备份名称'}), 400
        if not backup_lock.acquire(blocking=False):
            return jsonify({'error': '已有备份或校验正在运行，请完成后重试'}), 409
        try:
            return jsonify(verify_backup(backup_directory / name))
        except BackupError as error:
            return jsonify({'error': str(error)}), 422
        finally:
            backup_lock.release()

    return app


def main() -> None:
    config = load_config()
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--data-root", default=None)
    parser.add_argument("--host", default=str(config.get("listen_host", "127.0.0.1")))
    parser.add_argument("--port", type=int, default=int(config.get("listen_port", 8765)))
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--allow-remote", action="store_true", help="明确允许绑定非回环地址（不建议用于真实病例数据）")
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"} and not args.allow_remote:
        parser.error("非回环地址需要同时传入 --allow-remote；默认只允许本机访问")
    app = create_app(args.data_root)
    port = args.port if args.host not in {"127.0.0.1", "localhost"} else _free_port(args.port)
    url = f"http://{args.host}:{port}"
    print(f"{APP_NAME} {APP_VERSION}")
    print(f"本地地址: {url}")
    print(f"应用数据: {user_data_root()}")
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    serve(app, host=args.host, port=port, threads=8, channel_timeout=120)


if __name__ == "__main__":
    main()
