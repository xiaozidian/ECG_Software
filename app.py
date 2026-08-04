from __future__ import annotations

import argparse
import copy
import os
import socket
import threading
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file, session
from waitress import serve

from ecg_core import APP_NAME, APP_VERSION, SAMPLE_RATE
from ecg_core.config import load_config, platform_info, resource_root, resolve_data_root, user_data_root, writable_data_dir
from ecg_core.ebi import (
    heart_rate_trend,
    hrv,
    list_events,
    metrics as ebi_metrics,
    rr_visuals,
    visible_beats,
)
from ecg_core.report_pdf import build_report_pdf
from ecg_core.repository import CaseNotFound, CaseRepository
from ecg_core.storage import Storage
from ecg_core.waveform import ALL_LEADS, read_waveform

ACTOR = "演示分析医生"


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
    app = Flask(
        __name__,
        template_folder=str(base / "templates"),
        static_folder=str(base / "static"),
    )
    app.config.update(
        TESTING=testing,
        JSON_AS_ASCII=False,
        MAX_CONTENT_LENGTH=4 * 1024 * 1024,
        SECRET_KEY=os.urandom(32),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
    )
    resolved_root = resolve_data_root(data_root)
    repository = CaseRepository(resolved_root)
    storage = Storage(Path(db_path) if db_path else writable_data_dir() / "cardioinsight.db")
    app.extensions["case_repository"] = repository
    app.extensions["storage"] = storage

    @app.before_request
    def local_mutation_guard():
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not app.config["TESTING"]:
            if request.headers.get("X-CardioInsight-Request") != "1":
                return jsonify({"error": "写操作仅接受本地工作站界面请求"}), 403

    def include_phi_authorized() -> bool:
        return _bool_arg("include_phi") and bool(session.get("phi_authorized"))

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
            from flask import abort

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
        )

    @app.get("/api/health")
    def health():
        cases = repository.list_cases()
        return jsonify({
            "status": "ok" if resolved_root else "data_root_missing",
            "version": APP_VERSION,
            "case_count": len(cases),
            "data_root_found": bool(resolved_root),
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
        return jsonify({"items": storage.list_audit(_number_arg("limit", 200, int, 1, 1000))})

    @app.get("/api/settings")
    def settings():
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
