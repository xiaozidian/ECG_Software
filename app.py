from __future__ import annotations

import argparse
import base64
import binascii
import copy
import hmac
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
from ecg_core.repository import CaseNotFound, CaseRepository
from ecg_core.storage import Storage
from ecg_core.waveform import ALL_LEADS, read_waveform, read_waveform_strips

ACTOR = "演示分析医生"
READONLY_POST_ENDPOINTS = frozenset({"case_open", "scatter_selection_endpoint", "waveform_strips_endpoint"})


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
        if detailed:
            duration = source["technical"]["duration_seconds_raw"]
            item["calculated"] = ebi_metrics(Path(source["paths"]["ebi"]), duration)
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
        payload["beats"] = visible_beats(Path(case["paths"]["ebi"]), payload["start_s"], payload["duration_s"])
        payload["annotations"] = [
            annotation for annotation in storage.list_annotations(case_id)
            if payload["start_s"] * SAMPLE_RATE <= annotation["sample_index"] <= (payload["start_s"] + payload["duration_s"]) * SAMPLE_RATE
        ]
        return jsonify(payload)

    @app.get("/api/cases/<case_id>/trend")
    def trend(case_id: str):
        case = case_or_404(case_id)
        bin_seconds = _number_arg("bin_seconds", 60, int, 10, 600)
        return jsonify(heart_rate_trend(Path(case["paths"]["ebi"]), case["technical"]["duration_seconds_raw"], bin_seconds))

    @app.get("/api/cases/<case_id>/hrv")
    def hrv_endpoint(case_id: str):
        case = case_or_404(case_id)
        return jsonify({"calculated": hrv(Path(case["paths"]["ebi"])), "source": case["summary"]})

    @app.get("/api/cases/<case_id>/rr-visuals")
    def rr_endpoint(case_id: str):
        case = case_or_404(case_id)
        return jsonify(rr_visuals(Path(case["paths"]["ebi"]), _number_arg("max_points", 4000, int, 500, 10000)))

    @app.get("/api/cases/<case_id>/scatter")
    def scatter_endpoint(case_id: str):
        case = case_or_404(case_id)
        return jsonify(scatter_points(
            Path(case["paths"]["ebi"]),
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
            Path(case["paths"]["ebi"]),
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
        ebi_path = Path(case["paths"]["ebi"])
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

    @app.get("/api/cases/<case_id>/events")
    def events_endpoint(case_id: str):
        case = case_or_404(case_id)
        return jsonify(list_events(
            Path(case["paths"]["ebi"]),
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
        if not isinstance(conclusion, str) or not isinstance(status, str):
            raise ValueError("conclusion 和 status 必须为文本")
        return jsonify(storage.save_report(case_id, conclusion, status, ACTOR))

    @app.get("/api/cases/<case_id>/report.pdf")
    def report_pdf(case_id: str):
        case = case_or_404(case_id)
        include_phi = include_phi_authorized()
        report_case = case_with_overrides(case)
        if not include_phi:
            report_case = _masked_report_case(report_case)
        calculated = ebi_metrics(Path(case["paths"]["ebi"]), case["technical"]["duration_seconds_raw"])
        report = storage.get_report(case_id, case["conclusion"])
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
