"""Launcher boundaries and saved-work upgrade checks; no clinical thresholds."""
from __future__ import annotations

from contextlib import closing
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import threading
import zipfile

from flask import Flask, jsonify
import pytest

import win_doctor_eval as doctor


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    source = tmp_path / "Sources" / "M01"
    source.mkdir(parents=True)
    program = tmp_path / "program"
    program.mkdir()
    monkeypatch.setattr(doctor, "package_root", lambda: program)
    return doctor.WorkspaceCatalog(tmp_path / "user-work", source)


@pytest.fixture
def source_package(tmp_path, monkeypatch):
    """Sparse length fixture; checksum tests independently control digest."""
    source = tmp_path / "Sources" / "M01"
    rows = []
    for name in sorted(doctor.SOURCE_FILES):
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if name.endswith(".DATA"):
            with path.open("wb") as stream:
                stream.truncate(276480000)
        else:
            path.write_bytes(b"synthetic-fixture")
        rows.append(dict(path=name, size_bytes=path.stat().st_size, sha256="a" * 64))
    manifest = dict(schema_version=1, source_id="M01", source_version="M01-24h-v1",
                    case_id=doctor.CASE_ID, wholly_synthetic=True, duration_seconds=86400,
                    sampling_rate_hz=200, sample_count=17280000,
                    expected_raw_bytes=276480000, files=rows)
    (source / "source-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(doctor, "_hash_file", lambda path: "a" * 64)
    return tmp_path, source, manifest


def write_manifest(source, manifest):
    (source / "source-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def context(token="a" * 64, port=9123, role="workspace"):
    return dict(profile=doctor.PROFILE, role=role, pid=123, birth="birth",
                token=token, cookie_name="doctor_" + token[:20], port=port,
                software_version=doctor._software_version(), packaging_version="1.0.0",
                shutdown=threading.Event())


def guarded_app(ctx):
    app = Flask("test_" + ctx["token"][:4])
    doctor._install_guards(app, ctx)
    writes = []

    @app.get("/")
    def index():
        return "workstation"

    @app.post("/write")
    def write():
        writes.append(ctx["token"])
        return jsonify(saved=True)
    return app, writes


def opened_client(app, ctx):
    client = app.test_client()
    base = f"http://127.0.0.1:{ctx['port']}"
    response = client.get("/_doctor/open?token=" + ctx["token"], base_url=base)
    assert response.status_code == 303
    assert "HttpOnly" in response.headers["Set-Cookie"]
    assert "SameSite=Strict" in response.headers["Set-Cookie"]
    return client, base


def test_source_is_one_fixed_verified_24h_case(source_package):
    root, source, _ = source_package
    assert doctor.validate_source(root) == source
    assert not list(root.glob("**/*.db"))


def test_checksum_failure_never_falls_back_to_clinical_data(source_package, monkeypatch, tmp_path):
    root, _, _ = source_package
    other = tmp_path / "10个病人的心电数据"
    other.mkdir()
    monkeypatch.setenv("ECG_DATA_ROOT", str(other))
    monkeypatch.setattr(doctor, "_hash_file", lambda path: "b" * 64)
    with pytest.raises(doctor.DoctorEvalError, match="校验失败") as result:
        doctor.validate_source(root)
    assert result.value.code == "source_checksum_failed"


@pytest.mark.parametrize("bad_path", ["../other.DATA", "/absolute.DATA", "another-case/data/x.DATA"])
def test_source_manifest_cannot_select_another_path(source_package, bad_path):
    root, source, manifest = source_package
    manifest["files"][0]["path"] = bad_path
    write_manifest(source, manifest)
    with pytest.raises(doctor.DoctorEvalError):
        doctor.validate_source(root)


def test_source_rejects_extra_case_or_non_boolean_synthetic_flag(source_package):
    root, source, manifest = source_package
    (source / "1234567890123456").mkdir()
    with pytest.raises(doctor.DoctorEvalError):
        doctor.validate_source(root)
    (source / "1234567890123456").rmdir()
    manifest["wholly_synthetic"] = 1
    write_manifest(source, manifest)
    with pytest.raises(doctor.DoctorEvalError):
        doctor.validate_source(root)


def test_source_selection_is_explicit_persisted_and_does_not_rebind(source_package, monkeypatch):
    root, source, _ = source_package
    home = root / "user-work"
    program = root / "software-only"
    program.mkdir()
    monkeypatch.setattr(doctor, "evaluation_home", lambda: home)
    monkeypatch.setattr(doctor, "package_root", lambda: program)
    monkeypatch.setenv("ECG_DOCTOR_EVAL_SOURCE_ROOT", str(source))
    assert doctor.selected_source(register=True) == source
    binding = doctor._read_json(home / "source-selection.json", required=True)
    assert binding["selected_dataset"] == "M01"
    monkeypatch.delenv("ECG_DOCTOR_EVAL_SOURCE_ROOT")
    assert doctor.selected_source() == source
    monkeypatch.setenv("ECG_DOCTOR_EVAL_SOURCE_ROOT", str(root / "other"))
    with pytest.raises(doctor.DoctorEvalError) as result:
        doctor.selected_source()
    assert result.value.code == "source_rebinding_denied"


def test_new_experience_preserves_old_database_and_can_resume(catalog):
    from ecg_core.storage import Storage
    first = catalog.current()
    first_folder = catalog.get(first)
    store = Storage(first_folder / "data" / "cardioinsight.db")
    store.save_report(doctor.CASE_ID, "已保存的合成体验草稿", "draft", "测试医生")
    before = sha256((first_folder / "data" / "cardioinsight.db").read_bytes()).hexdigest()
    second = catalog.new()
    assert second != first
    assert catalog.current() == second
    assert catalog.select(first) == first
    assert catalog.current() == first
    assert sha256((first_folder / "data" / "cardioinsight.db").read_bytes()).hexdigest() == before
    record = doctor._read_json(first_folder / "WORKSPACE.json", required=True)
    assert record["selected_dataset"] == "M01"
    assert record["software_version"] == doctor._software_version()
    assert record["sqlite_schema"] == doctor.database_schema(first_folder / "data" / "cardioinsight.db")


def test_missing_saved_database_is_not_recreated(catalog):
    identifier = catalog.new()
    database = catalog.get(identifier) / "data" / "cardioinsight.db"
    database.unlink()
    with pytest.raises(doctor.DoctorEvalError, match="未创建空数据库"):
        catalog.current()
    assert not database.exists()


def test_each_port_has_its_own_cookie_and_old_page_keeps_its_workspace():
    old_ctx = context("a" * 64, 9123)
    new_ctx = context("b" * 64, 9124)
    old_app, old_writes = guarded_app(old_ctx)
    new_app, new_writes = guarded_app(new_ctx)
    old_client, old_base = opened_client(old_app, old_ctx)
    new_client, new_base = opened_client(new_app, new_ctx)
    assert old_ctx["cookie_name"] != new_ctx["cookie_name"]
    assert old_client.post("/write", base_url=old_base, headers={"Origin": old_base}).status_code == 200
    assert new_client.post("/write", base_url=new_base, headers={"Origin": new_base}).status_code == 200
    foreign = new_app.test_client()
    foreign.set_cookie(old_ctx["cookie_name"], old_ctx["token"], domain="127.0.0.1")
    assert foreign.post("/write", base_url=new_base, headers={"Origin": new_base}).status_code == 403
    assert old_writes == [old_ctx["token"]]
    assert new_writes == [new_ctx["token"]]


@pytest.mark.parametrize("headers", [
    {"Origin": "http://evil.example"},
    {"Origin": "null"},
    {"Origin": "http://localhost:9123"},
    {"Origin": "http://127.0.0.1:9124"},
    {"Origin": "http://127.0.0.1:9123", "Host": "evil.example"},
    {"Origin": "http://127.0.0.1:9123", "Sec-Fetch-Site": "cross-site"},
    {},
])
def test_foreign_or_missing_origin_cannot_write(headers):
    ctx = context()
    app, writes = guarded_app(ctx)
    client, base = opened_client(app, ctx)
    assert client.post("/write", base_url=base, headers=headers).status_code == 403
    assert not writes


def test_health_requires_control_token_and_stop_requires_saved_work_ack():
    ctx = context()
    app, _ = guarded_app(ctx)
    client = app.test_client()
    base = f"http://127.0.0.1:{ctx['port']}"
    assert client.get("/_doctor/health", base_url=base).status_code == 403
    auth = {"X-Doctor-Control": ctx["token"]}
    assert client.get("/_doctor/health", base_url=base, headers=auth).status_code == 200
    assert client.post("/_doctor/stop", base_url=base, headers=auth, json={}).status_code == 400
    assert not ctx["shutdown"].is_set()
    assert client.post("/_doctor/stop", base_url=base, headers=auth,
                       json={"saved_work_acknowledged": True}).status_code == 200
    assert ctx["shutdown"].is_set()


def test_non_ascii_invalid_token_is_rejected_without_internal_error():
    app, _ = guarded_app(context())
    assert app.test_client().get("/_doctor/open?token=错误",
                                base_url="http://127.0.0.1:9123").status_code == 403


def test_reused_pid_is_not_owned_even_if_port_is_live(monkeypatch):
    state = dict(profile=doctor.PROFILE, role="workspace", pid=123, birth="old",
                 token="a" * 64, port=9123)
    monkeypatch.setattr(doctor, "process_identity", lambda pid: "different-new-process")
    monkeypatch.setattr(doctor, "_control", lambda *args: pytest.fail("must not contact reused PID's port"))
    assert doctor.owned_ready(state, "workspace") is False


def test_lifetime_lock_rejects_second_owner(tmp_path):
    path = tmp_path / "runtime" / "manager.lock"
    with doctor.instance_lock(path) as first:
        assert first
        with doctor.instance_lock(path) as second:
            assert not second
    with doctor.instance_lock(path) as third:
        assert third


def test_minimal_feedback_cannot_include_case_database_free_text_or_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "package_root", lambda: tmp_path)
    (tmp_path / "RELEASE.json").write_text(json.dumps({
        "source_commit": "c" * 40, "packaging_version": "1.0.0",
        "patient": "should-never-appear", "database": "C:\\private\\work.db",
        "note": "arbitrary free text", "source_path": "/private/source",
    }), encoding="utf-8")
    value = doctor.diagnostic(source_ok=False, runtime="untrusted text")
    with zipfile.ZipFile(BytesIO(doctor.feedback_bytes(value))) as archive:
        assert archive.namelist() == ["diagnostic.json"]
        payload = archive.read("diagnostic.json").decode("utf-8")
    assert all(text not in payload for text in [
        "should-never-appear", "private", "arbitrary free text", "untrusted text",
        doctor.CASE_ID, "sqlite_schema", "annotations", "WORKSPACE.json",
    ])
    assert value["runtime_state"] == "unhealthy"
    assert value["windows10_hospital_validation"] == "not_confirmed"


def test_upgrade_snapshot_preserves_saved_report_and_schema(catalog, monkeypatch):
    from ecg_core.storage import Storage
    folder = catalog.get(catalog.new())
    database = folder / "data" / "cardioinsight.db"
    store = Storage(database)
    store.save_report(doctor.CASE_ID, "升级前已保存草稿", "draft", "测试医生")
    monkeypatch.setattr(doctor, "_packaging_version", lambda: "1.0.1")
    pending = doctor.prepare_upgrade(folder)
    snapshot = folder / "upgrade-snapshots" / pending["snapshot"]
    assert pending["snapshot_integrity"] == "ok"
    with closing(sqlite3.connect(snapshot)) as db:
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert db.execute("SELECT conclusion FROM report_drafts").fetchone() == ("升级前已保存草稿",)
    # The same-schema fixture uses the current application's normal storage.
    Storage(database)
    doctor.complete_upgrade(folder, pending)
    record = doctor._read_json(folder / "WORKSPACE.json", required=True)
    assert record["packaging_version"] == "1.0.1"
    assert record["last_upgrade"]["before_schema"] == record["last_upgrade"]["after_schema"]
    assert record["last_upgrade"]["snapshot_sha256"] == doctor._hash_file(snapshot)
    assert doctor.prepare_upgrade(folder) is None
    assert len(list((folder / "upgrade-snapshots").glob("*.sqlite3"))) == 1
    monkeypatch.setattr(doctor, "_packaging_version", lambda: "1.0.0")
    before = doctor._hash_file(database)
    with pytest.raises(doctor.DoctorEvalError, match="更新的程序"):
        doctor.prepare_upgrade(folder)
    assert doctor._hash_file(database) == before


def test_incomplete_upgrade_is_retained_and_does_not_retry_migration(catalog, monkeypatch):
    folder = catalog.get(catalog.new())
    monkeypatch.setattr(doctor, "_packaging_version", lambda: "1.0.1")
    pending = doctor.prepare_upgrade(folder)
    snapshot = folder / "upgrade-snapshots" / pending["snapshot"]
    before = doctor._hash_file(snapshot)
    with pytest.raises(doctor.DoctorEvalError, match="上次升级尚未完成"):
        doctor.prepare_upgrade(folder)
    assert doctor._hash_file(snapshot) == before


def test_unexpected_schema_change_is_refused_before_app_migration(catalog):
    folder = catalog.get(catalog.new())
    database = folder / "data" / "cardioinsight.db"
    with closing(sqlite3.connect(database)) as db:
        db.execute("CREATE TABLE externally_added(secret TEXT)")
        db.commit()
    with pytest.raises(doctor.DoctorEvalError) as result:
        doctor.prepare_upgrade(folder)
    assert result.value.code == "workspace_schema_changed"
    assert not (folder / "upgrade-snapshots").exists()


def test_environment_keeps_source_work_and_config_authoritative(monkeypatch, tmp_path):
    for key in ("ECG_DATA_ROOT", "ECG_APP_DATA_ROOT", "ECG_CONFIG_PATH", "ECG_ALLOW_PHI",
                "ECG_TRUST_PROXY_HEADERS", "ECG_DEMO_PASSWORD", "ECG_DEMO_USERNAME",
                "ECG_DEMO_READONLY", "ECG_SESSION_COOKIE_SECURE"):
        monkeypatch.setenv(key, "/someone-elses-work")
    folder, source = tmp_path / "workspace", tmp_path / "Sources" / "M01"
    doctor._environment(folder, source)
    import os
    assert os.environ["ECG_DATA_ROOT"] == str(source)
    assert os.environ["ECG_APP_DATA_ROOT"] == str(folder)
    assert os.environ["ECG_CONFIG_PATH"] == str(folder / "config.json")
    assert os.environ["ECG_ALLOW_PHI"] == "0"
    assert os.environ["ECG_TRUST_PROXY_HEADERS"] == "0"


def test_old_program_rejects_newer_selected_workspace_before_spawn(catalog, monkeypatch):
    identifier = catalog.new()
    folder = catalog.get(identifier)
    record = doctor._read_json(folder / "WORKSPACE.json", required=True)
    record["packaging_version"] = "1.0.1"
    doctor._write_json(folder / "WORKSPACE.json", record)
    monkeypatch.setattr(doctor, "selected_source", lambda **kwargs: catalog.source)
    monkeypatch.setattr(doctor, "evaluation_home", lambda: catalog.home)
    monkeypatch.setattr(doctor, "_spawn", lambda *args: pytest.fail("old program must not spawn"))
    before = doctor._hash_file(folder / "data" / "cardioinsight.db")
    with pytest.raises(doctor.DoctorEvalError) as result:
        doctor.ensure_manager()
    assert result.value.code == "newer_workspace_version"
    assert doctor._hash_file(folder / "data" / "cardioinsight.db") == before
    assert not (catalog.home / "runtime" / "manager.json").exists()


def test_blank_catalog_does_not_hide_old_workspaces(catalog):
    identifier = catalog.new()
    folder = catalog.get(identifier)
    doctor._write_json(catalog.path, {})
    with pytest.raises(doctor.DoctorEvalError, match="目录记录为空"):
        catalog.current()
    assert (folder / "data" / "cardioinsight.db").is_file()


def test_first_app_initialization_records_review_tables_before_relaunch(catalog):
    from app import create_app
    folder = catalog.get(catalog.new())
    before = doctor.database_schema(folder / "data" / "cardioinsight.db")
    assert doctor.prepare_upgrade(folder) is None
    create_app(data_root=catalog.source, db_path=folder / "data" / "cardioinsight.db", testing=True)
    doctor.complete_upgrade(folder, None)
    record = doctor._read_json(folder / "WORKSPACE.json", required=True)
    assert record["application_initialized"] is True
    assert record["sqlite_schema"] != before
    assert doctor.prepare_upgrade(folder) is None


def test_stop_drains_queued_work_before_stopping_workers(monkeypatch):
    class Dispatcher:
        lock = threading.Lock()
        active_count = 1
        queue = ["saved-work-request"]
        stopped = False
        def shutdown(self, **kwargs):
            assert not self.queue and self.active_count == 0
            assert kwargs["cancel_pending"] is False
            self.stopped = True
    class Trigger:
        callback = None
        def pull_trigger(self, callback):
            self.callback = callback
    class SocketLoop:
        closed = False
        def close_all(self, socket_map):
            self.closed = True
    class Server:
        accepting = True
        active_channels = {}
        _map = {}
        task_dispatcher = Dispatcher()
        trigger = Trigger()
        asyncore = SocketLoop()
    server = Server()
    ctx = context()
    ctx["shutdown"].set()
    def finish_saved_work(delay):
        assert not server.task_dispatcher.stopped
        server.task_dispatcher.queue.clear()
        server.task_dispatcher.active_count = 0
    monkeypatch.setattr(doctor.time, "sleep", finish_saved_work)
    assert doctor.drain_and_close_server(server, ctx)
    assert server.task_dispatcher.stopped
    assert not server.accepting
    assert not server.asyncore.closed
    server.trigger.callback()
    assert server.asyncore.closed


def test_stop_timeout_retains_active_work_and_restores_service(monkeypatch):
    class Dispatcher:
        lock = threading.Lock()
        active_count = 1
        queue = ["saved-work-request"]
        def shutdown(self, **kwargs):
            pytest.fail("must not stop active saved-work tasks")
    class Server:
        accepting = True
        active_channels = {}
        task_dispatcher = Dispatcher()
    ctx = context()
    ctx["shutdown"].set()
    server = Server()
    assert doctor.drain_and_close_server(server, ctx, timeout=0) is False
    assert server.accepting
    assert not ctx["shutdown"].is_set()


def test_native_session_cookies_do_not_replace_other_workspaces_or_original_service():
    from flask import Flask, session
    def application(name, identifier=None):
        app = Flask(name)
        app.secret_key = "isolated-mathematical-cookie-test"
        if identifier:
            doctor.isolate_workspace_session(app, identifier)
        @app.get("/seed")
        def seed():
            session["actor"] = name
            return {"actor": name}
        @app.get("/read")
        def read():
            return {"actor": session.get("actor")}
        return app
    old = application("original-service")
    first = application("first-workspace", "1" * 32)
    second = application("second-workspace", "2" * 32)
    old_client, first_client, second_client = old.test_client(), first.test_client(), second.test_client()
    old_client.get("/seed")
    old_cookie = old_client.get_cookie("session")
    first_client.set_cookie("session", old_cookie.value)
    assert first_client.get("/read").json == {"actor": None}
    first_client.get("/seed")
    name = first.config["SESSION_COOKIE_NAME"]
    second_client.set_cookie(name, first_client.get_cookie(name).value)
    assert second_client.get("/read").json == {"actor": None}
    assert name != second.config["SESSION_COOKIE_NAME"] != "session"
