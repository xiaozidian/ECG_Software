from __future__ import annotations

import argparse
import base64
import binascii
import copy
import hmac
import json
import math
import os
import socket
import threading
import webbrowser
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file, session
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
from ecg_core.hrv_analysis import analyze_hrv
from ecg_core.report_layout import prepare_strip, report_statistics
from ecg_core.clinical_analysis import build_index, query_index, hrv_windows, validate_report
from ecg_core.storage import normalize_report_composition
from ecg_core.repository import CaseNotFound, CaseRepository
from ecg_core.storage import Storage
from ecg_core.beat_editor import BeatEditorStore, EditedRecords, TYPES, apply_operation, propose_qrs, integer
from ecg_core.ebi import load_records
from ecg_core.stt import build_stt_review
from ecg_core.waveform import read_event_waveform, ALL_LEADS, read_waveform, read_waveform_strips
from ecg_core.overview import RhythmReviewStore, initial_episodes, density

ACTOR = "演示分析医生"
READONLY_POST_ENDPOINTS = frozenset({"case_open", "scatter_selection_endpoint", "waveform_strips_endpoint", "event_waveforms", "waveform_density"})


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
            return repository.get_case(case_id)
        except CaseNotFound:
            abort(404, description="病例不存在或数据不完整")

    editor = BeatEditorStore(storage)
    rhythms = RhythmReviewStore(storage)

    def edited_feed(case, document=None):
        value = editor.read(case["case_id"])
        return EditedRecords(load_records(case["paths"]["ebi"]), document or value["document"],
            storage.list_beat_overrides(case["case_id"]), case["technical"]["duration_seconds_raw"])

    def analysis_path(case):
        return edited_feed(case) if request.args.get("analysis") == "edited" else Path(case["paths"]["ebi"])

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
            item["calculated"] = ebi_metrics(analysis_path(source), duration)
            item["analysis_revision"] = editor.read(source["case_id"])["revision"] if request.args.get("analysis") == "edited" else None
            if item["analysis_revision"] is not None:
                feed=edited_feed(source)
                item["beat_editor_settings"]=feed.document["settings"]
                item["manual_longest"]=next((r for r in feed.beats if r["id"]==feed.document["longest_id"]),None)
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
        return response

    @app.errorhandler(404)
    def not_found(error):
        return jsonify({"error": getattr(error, "description", "not found")}), 404

    @app.errorhandler(ValueError)
    def value_error(error):
        return jsonify({"error": str(error)}), 400

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
        cases = repository.list_cases()
        return jsonify({
            "status": "ok" if resolved_root else "data_root_missing",
            "version": APP_VERSION,
            "case_count": len(cases),
            "data_root_found": bool(resolved_root),
            "demo_readonly": app.config["DEMO_READONLY"],
            "allow_phi": app.config["ALLOW_PHI"],
        })

    @app.get("/api/dashboard")
    def dashboard():
        include_phi = include_phi_authorized()
        cases = [present_case(case, include_phi) for case in repository.list_cases()]
        totals = {
            "cases": len(cases),
            "recording_hours": round(sum(case["technical"]["duration_seconds_raw"] for case in cases) / 3600, 1),
            "beats": sum(case["summary"].get("total_beats") or 0 for case in cases),
            "pending_reports": sum(storage.get_report(case["case_id"], case["conclusion"])["status"] != "reviewed" for case in repository.list_cases()),
        }
        return jsonify({"totals": totals, "cases": cases, "privacy": {"phi_visible": include_phi}})

    @app.get("/api/cases")
    def cases():
        include_phi = include_phi_authorized()
        show_deleted = _bool_arg("show_deleted")
        items = [present_case(case, include_phi) for case in repository.list_cases()]
        if not show_deleted:
            items = [item for item in items if item["active"]]
        return jsonify({"items": items, "total": len(items)})

    @app.get("/api/cases/<case_id>")
    def case_detail(case_id: str):
        return jsonify(present_case(case_or_404(case_id), include_phi_authorized(), detailed=True))

    @app.get("/api/cases/<case_id>/stt-review")
    def stt_review(case_id: str):
        case = case_or_404(case_id)
        editor_value = editor.read(case_id)
        feed = edited_feed(case, editor_value["document"])
        overrides = storage.list_beat_overrides(case_id)
        override_signature = ",".join(f"{item['sample_index']}:{item['class_code']}" for item in overrides)
        return jsonify(build_stt_review(
            case.get("conclusion", ""),
            case["paths"]["data"],
            feed.records,
            case["technical"]["duration_seconds_raw"],
            analysis_revision=f"editor-{editor_value['revision']}|overrides-{override_signature or 'none'}",
        ))

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
        start = _number_arg("start", 0, float, 0)
        duration = _number_arg("duration", 10, float, 1, 120)
        leads = [value.strip() for value in request.args.get("leads", "II,V1,V5").split(",") if value.strip()]
        max_points = _number_arg("max_points", 4000, int, 200, 12000)
        filtered = request.args.get("filter", "display") != "raw"
        payload = read_waveform(Path(case["paths"]["data"]), start, duration, leads, max_points, filtered)
        feed=analysis_path(case)
        payload["beats"] = visible_beats(feed, payload["start_s"], payload["duration_s"])
        if hasattr(feed,"markers"):
            payload["beats"] += [r for r in feed.markers if payload["start_s"]<=r["time_s"]<=payload["start_s"]+payload["duration_s"]]
            payload["beats"].sort(key=lambda r:r["sample_index"])
        payload["annotations"] = [
            annotation for annotation in storage.list_annotations(case_id)
            if payload["start_s"] * SAMPLE_RATE <= annotation["sample_index"] <= (payload["start_s"] + payload["duration_s"]) * SAMPLE_RATE
        ]
        return jsonify(payload)

    @app.get("/api/cases/<case_id>/trend")
    def trend(case_id: str):
        case = case_or_404(case_id)
        bin_seconds = _number_arg("bin_seconds", 60, int, 10, 600)
        return jsonify(heart_rate_trend(analysis_path(case), case["technical"]["duration_seconds_raw"], bin_seconds))

    def clinical_index(case):
        feed=edited_feed(case)
        templates=storage.list_beat_templates(case["case_id"])
        by_id={r["id"]:r for r in feed.beats}
        with storage.connect() as db:
            refs={r["template_id"]:json.loads(r["beat_ids"]) for r in db.execute("SELECT * FROM beat_edit_template_refs WHERE case_id=?",(case["case_id"],))}
        for t in templates:
            t["sample_indices"]=[by_id[k]["sample_index"] for k in refs.get(t["id"],[f"s:{s}" for s in t["sample_indices"]]) if k in by_id]
        return build_index(feed,templates,storage.list_annotations(case["case_id"]),storage.get_review(case["case_id"]))

    @app.get("/api/cases/<case_id>/template-occurrences")
    def template_occurrences(case_id):
        return jsonify(query_index(clinical_index(case_or_404(case_id)),request.args,True))

    @app.get("/api/cases/<case_id>/report-events")
    def report_events(case_id):
        return jsonify(query_index(clinical_index(case_or_404(case_id)),request.args))

    @app.get("/api/cases/<case_id>/event-waveform")
    def event_waveform(case_id):
        case=case_or_404(case_id)
        start=_number_arg("start",0,float,0)
        end=_number_arg("end",start+4,float,start+1)
        payload=read_event_waveform(case["paths"]["data"],start,end,request.args.get("leads","II,V1,V5").split(","),_number_arg("max_points",2400,int,200,12000))
        payload['beats']=visible_beats(analysis_path(case),payload['start_s'],payload['duration_s'])
        return jsonify(payload)

    @app.post("/api/cases/<case_id>/event-waveforms")
    def event_waveforms(case_id):
        """One revision-consistent beat read for a viewport of thumbnail ranges."""
        case = case_or_404(case_id)
        body = _json_object()
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
        feed = analysis_path(case)
        items = []
        for start, end in checked:
            wave = read_event_waveform(case["paths"]["data"], start, end, leads, points)
            wave["beats"] = visible_beats(feed, wave["start_s"], wave["duration_s"])
            items.append(wave)
        return jsonify(items=items)

    @app.get("/api/cases/<case_id>/report-strip")
    def report_strip(case_id):
        case = case_or_404(case_id)
        index = clinical_index(case)
        event = next((e for e in index['events'] if e['event_id'] == request.args.get('event_id')), None)
        if not event or event['basis_version'] != request.args.get('basis_version'):
            return jsonify(error='图条依据已变化，请重新选择事件'), 409
        settings = {'leads': request.args.get('leads', 'II,V1,V5').split(','),
                    'duration_s': _number_arg('duration', 7, float, 1, 120)}
        if 'range_start_s' in request.args or 'range_end_s' in request.args:
            settings.update(range_start_s=_number_arg('range_start_s',-1,float,0),range_end_s=_number_arg('range_end_s',-1,float,0))
        return jsonify(prepare_strip(index, event, settings, lambda a, b, leads, points: read_event_waveform(case['paths']['data'], a, b, leads, points)))

    @app.get("/api/cases/<case_id>/report-statistics")
    def report_statistics_endpoint(case_id):
        case = case_or_404(case_id)
        feed = edited_feed(case)
        result = report_statistics(clinical_index(case), case['metadata'].get('start_iso') or case['metadata'].get('start_time'), feed.document['settings'])
        result['hrv'] = hrv(feed)
        return jsonify(result)

    @app.get("/api/cases/<case_id>/hrv-windows")
    def hrv_window_endpoint(case_id):
        case=case_or_404(case_id)
        return jsonify(hrv_windows(edited_feed(case),case["metadata"].get("start_iso") or case["metadata"].get("start_time"),request.args.get("window",0)))

    def hrv_evidence(case, window=0):
        feed=edited_feed(case)
        data=analyze_hrv(feed,case['metadata'].get('start_iso') or case['metadata'].get('start_time'),window)
        # Use the already-versioned ST research engine; never label device units mV.
        review=stt_review(case['case_id']).get_json()
        data['st_trends']=(review.get('analysis') or {}).get('trends',{}).get('leads',{})
        index=clinical_index(case)
        data['event_statistics']=report_statistics(index,case['metadata'].get('start_iso') or case['metadata'].get('start_time'),feed.document['settings'])
        representatives=[]
        for category in ('fastest','slowest','V','S','pause'):
            candidates=[e for e in index['events'] if e['category']==category and data['start_s']<=e['time_s']<data['end_s'] and (category not in ('fastest','slowest') or e['subtype']=='RR')]
            if category in ('fastest','slowest'): candidates.sort(key=lambda e: ((-1 if category=='fastest' else 1)*(e.get('hr') or 0),e['time_s']))
            event=next(iter(candidates),None)
            if event:
                entry=prepare_strip(index,event,{'leads':['II']},lambda a,b,leads,points:read_event_waveform(case['paths']['data'],a,b,leads,min(points,1000)))
                representatives.append(entry)
        data['representatives']=representatives
        return data

    @app.get('/api/cases/<case_id>/hrv-analysis')
    def hrv_analysis_endpoint(case_id):
        return jsonify(hrv_evidence(case_or_404(case_id),request.args.get('window',0)))

    @app.get('/api/cases/<case_id>/hrv-report.pdf')
    def hrv_pdf(case_id):
        case=case_or_404(case_id)
        include_phi=include_phi_authorized()
        visible=case_with_overrides(case)
        if not include_phi: visible=_masked_report_case(visible)
        report=storage.get_report(case_id,case['conclusion'])
        report.update(hrv_only=True,status='draft',selected_waveforms=[],hrv_analysis=hrv_evidence(case,request.args.get('window',0)))
        storage.audit(ACTOR,'hrv.export_pdf',case_id,'HRV standalone research draft')
        response=send_file(build_report_pdf(visible,{},report),mimetype='application/pdf',as_attachment=True,download_name=f'{case_id}_HRV分析报告.pdf')
        response.headers['X-Privacy-Mode']='phi-visible' if include_phi else 'masked'
        return response

    @app.get("/api/cases/<case_id>/hrv")
    def hrv_endpoint(case_id: str):
        case = case_or_404(case_id)
        return jsonify({"calculated": hrv(analysis_path(case)), "source": case["summary"]})

    @app.get("/api/cases/<case_id>/rr-visuals")
    def rr_endpoint(case_id: str):
        case = case_or_404(case_id)
        return jsonify(rr_visuals(analysis_path(case), _number_arg("max_points", 4000, int, 500, 10000)))

    @app.get("/api/cases/<case_id>/scatter")
    def scatter_endpoint(case_id: str):
        case = case_or_404(case_id)
        return jsonify(scatter_points(
            analysis_path(case),
            request.args.get("mode", "rr"),
            _number_arg("max_points", 12000, int, 500, 20000),
            _number_arg("hour_start_s", 0, float, 0, 2_678_400),
        ))

    @app.post("/api/cases/<case_id>/scatter-selection")
    def scatter_selection_endpoint(case_id: str):
        case = case_or_404(case_id)
        payload = _json_object()
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
        return jsonify(select_scatter_points(
            analysis_path(case),
            mode,
            polygon,
            _json_number(payload, "hour_start_s", 0, 0, 2_678_400),
        ))

    @app.post("/api/cases/<case_id>/waveform-strips")
    def waveform_strips_endpoint(case_id: str):
        case = case_or_404(case_id)
        payload = _json_object()
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
        for item in result["items"]:
            item.update(details[item["sample_index"]])
        return jsonify(result)

    def editor_summary(case, value):
        feed=edited_feed(case,value["document"])
        return dict(revision=value["revision"], settings=value["document"]["settings"],
            can_undo=bool(value["undo"]), can_redo=bool(value["redo"]), types=TYPES,
            metrics=ebi_metrics(feed,feed.duration), hrv=hrv(feed),
            type_counts=dict(__import__("collections").Counter(row["class_code"] for row in feed.beats)),
            markers=feed.markers, manual_longest=next((r for r in feed.beats if r["id"]==value["document"]["longest_id"]),None),
            note="按医生修订位置重算 RR；不生成自动疾病诊断，源 EBI 保留不变")

    @app.get("/api/cases/<case_id>/beat-editor")
    def beat_editor_get(case_id):
        return jsonify(editor_summary(case_or_404(case_id),editor.read(case_id)))

    @app.get("/api/cases/<case_id>/beat-editor/beats")
    def beat_editor_beats(case_id):
        feed=edited_feed(case_or_404(case_id))
        return jsonify(items=feed.beats,markers=feed.markers)

    @app.get("/api/cases/<case_id>/overview")
    def overview_data(case_id):
        case = case_or_404(case_id)
        snapshot = editor.read(case_id)
        feed = edited_feed(case, snapshot["document"])
        revision = snapshot["revision"]
        duration = case["technical"]["duration_seconds_raw"]
        return jsonify(revision=revision, duration_s=duration,
            columns=["sample_index", "rr_ms", "class_code"],
            rows=[[r["sample_index"], r["rr_ms"], r["class_code"]] for r in feed.beats],
            estimated_beats=case["summary"].get("total_beats"), settings=feed.document["settings"])

    @app.route("/api/cases/<case_id>/rhythm-review", methods=["GET", "PUT"])
    def rhythm_review(case_id):
        case = case_or_404(case_id)
        snapshot = editor.read(case_id)
        feed = edited_feed(case, snapshot["document"])
        duration = case["technical"]["duration_seconds_raw"]
        initial = initial_episodes(feed, storage.list_annotations(case_id), duration)
        revision = snapshot["revision"]
        if request.method == "GET":
            return jsonify(**rhythms.public(rhythms.read(case_id, initial)), beat_revision=revision)
        result = rhythms.commit(case_id, _json_object(), duration, initial, ACTOR, revision)
        return jsonify(**result, beat_revision=revision)

    @app.route("/api/cases/<case_id>/waveform-density", methods=["GET", "POST"])
    def waveform_density(case_id):
        case = case_or_404(case_id)
        snapshot = editor.read(case_id)
        payload = _json_object() if request.method == "POST" else {}
        if "revision" in payload and (type(payload["revision"]) is not int or payload["revision"] != snapshot["revision"]):
            raise ValueError("编辑版本已变化，请重新加载密度图")
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
        elif code not in TYPES and code != "all":
            raise ValueError("不支持的心搏类型")
        samples = tuple(r["sample_index"] for r in feed.beats if (r["sample_index"] in allowed if allowed is not None else code == "all" or r["class_code"] == code))
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
        result = density(Path(case["paths"]["data"]), selected_samples, request.args.get("lead", "II"), gate, payload.get("amplitude_limit"))
        return jsonify(**result, source_total=len(samples), revision=snapshot["revision"])

    @app.post("/api/cases/<case_id>/beat-editor/preview")
    def beat_editor_preview(case_id):
        case=case_or_404(case_id);payload=_json_object();current=editor.read(case_id)
        integer(payload.get("revision"),"编辑版本")
        if payload.get("revision")!=current["revision"]:raise ValueError("编辑版本已变化，请刷新")
        if payload.get("operation")=="detect":
            opts=current["document"]["settings"]
            start=_json_number(payload,"start_s",0,0,case["technical"]["duration_seconds_raw"])
            duration=_json_number(payload,"duration_s",10,1,60)
            wave=read_waveform(Path(case["paths"]["data"]),start,duration,[opts["lead"]],12000,False)
            feed=edited_feed(case)
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
        if "revision" in payload and (type(payload["revision"]) is not int or payload["revision"] != editor.read(case_id)["revision"]):
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
            if source_class in source_classes:
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
        case_or_404(case_id)
        return jsonify({"items": storage.list_annotations(case_id)})

    @app.post("/api/cases/<case_id>/annotations")
    def annotation_create(case_id: str):
        case = case_or_404(case_id)
        payload = _json_object()
        sample_index = payload.get("sample_index", 0)
        if isinstance(sample_index, bool) or not isinstance(sample_index, (int, float)) or int(sample_index) != sample_index:
            raise ValueError("sample_index 必须为整数")
        if not 0 <= int(sample_index) < int(case["technical"]["duration_seconds_raw"] * SAMPLE_RATE):
            raise ValueError("sample_index 超出记录范围")
        payload["sample_index"] = int(sample_index)
        if isinstance(payload.get("details"),dict) and payload["details"].get("end_sample",sample_index)>=int(case["technical"]["duration_seconds_raw"]*SAMPLE_RATE):
            raise ValueError("结束位置超出记录范围")
        return jsonify(storage.create_annotation(case_id, payload, ACTOR)), 201

    @app.delete("/api/annotations/<int:annotation_id>")
    def annotation_delete(annotation_id: int):
        if not storage.delete_annotation(annotation_id, ACTOR):
            return jsonify({"error": "标注不存在"}), 404
        return jsonify({"ok": True})

    @app.get("/api/cases/<case_id>/report")
    def report_get(case_id: str):
        case = case_or_404(case_id)
        return jsonify(storage.get_report(case_id, case["conclusion"]))

    @app.put("/api/cases/<case_id>/report")
    def report_put(case_id: str):
        case_or_404(case_id)
        payload = _json_object()
        conclusion = payload.get("conclusion", "")
        status = payload.get("status", "draft")
        composition = payload.get("composition")
        if not isinstance(conclusion, str) or not isinstance(status, str):
            raise ValueError("conclusion 和 status 必须为文本")
        if composition is not None and not isinstance(composition, dict):
            raise ValueError("composition 必须为 JSON 对象")
        composition=normalize_report_composition(composition if composition is not None else storage.get_report(case_id, "")["composition"])
        validate_report(clinical_index(case_or_404(case_id)),composition,storage.get_review(case_id),status=="reviewed")
        return jsonify(storage.save_report(case_id, conclusion, status, ACTOR, composition,payload.get("expected_version")))

    @app.get("/api/cases/<case_id>/report.pdf")
    def report_pdf(case_id: str):
        case = case_or_404(case_id)
        include_phi = include_phi_authorized()
        report_case = case_with_overrides(case)
        if not include_phi:
            report_case = _masked_report_case(report_case)
        calculated = ebi_metrics(edited_feed(case), case["technical"]["duration_seconds_raw"])
        report = storage.get_report(case_id, case["conclusion"])
        report["review_snapshot"] = storage.get_review(case_id)
        report["override_count"] = len(storage.list_beat_overrides(case_id)) + len(editor.read(case_id)["document"]["changes"])
        report["edited_analysis"] = True
        report["analysis_revision"] = editor.read(case_id)["revision"]
        index=clinical_index(case)
        resolved=validate_report(index,report['composition'],report['review_snapshot'])
        if len(resolved)!=len(report['composition'].get('selected_events',[])):
            raise ValueError('已选图条失效，请重新筛选后导出')
        report['selected_waveforms']=[prepare_strip(index, e, e, lambda a,b,leads,points: read_event_waveform(case['paths']['data'],a,b,leads,points)) for e in resolved]
        report['paper_statistics']=report_statistics(index,case['metadata'].get('start_iso') or case['metadata'].get('start_time'),edited_feed(case).document['settings'])
        report['paper_statistics']['hrv']=hrv(edited_feed(case))
        report['event_statistics']=query_index(index,{'fast_slow_mode':report['composition'].get('fast_slow_mode','rr')})
        report['hrv_windows']=hrv_windows(edited_feed(case),case['metadata'].get('start_iso') or case['metadata'].get('start_time'),report['composition'].get('hrv_window',0))
        if report['composition'].get('include_hrv'):
            report['hrv_analysis']=hrv_evidence(case,report['composition'].get('hrv_window',0))
        privacy_mode = "phi-visible" if include_phi else "masked"
        storage.audit(ACTOR, "report.export_pdf", case_id, f"version={report['version']} privacy={privacy_mode}")
        response = send_file(build_report_pdf(report_case, calculated, report), mimetype="application/pdf", as_attachment=True, download_name=f"{case_id}_心电分析复核报告.pdf")
        response.headers["X-Privacy-Mode"] = privacy_mode
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
