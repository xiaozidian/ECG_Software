"""Offline Windows x64 doctor evaluation launcher.

The immutable bundled source is always Sources/M01. Each experience owns a
separate process, port and database; old browser tabs never switch databases.
Control uses a held file lock, process creation identity and a health token.
No service installation, process termination, source discovery or upload.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import secrets
import sqlite3
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import webbrowser
import zipfile

PROFILE = "cardioinsight-windows-doctor-eval-v1"
CASE_ID = "9900000000000001"
WORKSPACE_ID = re.compile(r"[0-9a-f]{32}\Z")
TOKEN = re.compile(r"[0-9a-f]{64}\Z")
SOURCE_FILES = frozenset({
    f"{CASE_ID}/data/{CASE_ID}.DATA",
    f"{CASE_ID}/DGS/{CASE_ID}.EBI",
    f"{CASE_ID}/report_image/{CASE_ID}_1.LPS",
    "events.json",
})
MUTATIONS = {"POST", "PUT", "PATCH", "DELETE"}


class DoctorEvalError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _error(code, message):
    raise DoctorEvalError(code, message)


def package_root():
    return (Path(sys.executable).parent if getattr(sys, "frozen", False)
            else Path(__file__).parent).resolve()


def evaluation_home():
    # The override exists solely for isolated release tests. Normal launches
    # cannot follow ordinary ECG_APP_DATA_ROOT or existing clinical config.
    test_root = os.environ.get("ECG_DOCTOR_EVAL_HOME")
    if test_root and os.environ.get("ECG_DOCTOR_EVAL_TESTING") == "1":
        return Path(test_root).absolute()
    base = os.environ.get("LOCALAPPDATA")
    return ((Path(base) if base else Path.home() / "AppData" / "Local")
            / "CardioInsightDoctorEval").absolute()


def _plain(path):
    """Reject symlinks and Windows junctions/reparse points on every ancestor."""
    path = Path(path).absolute()
    for item in (path, *path.parents):
        if item.exists() or item.is_symlink():
            attrs = getattr(item.lstat(), "st_file_attributes", 0)
            if item.is_symlink() or attrs & 0x400:
                _error("linked_path", "目录含链接或重解析点，请保留原目录并使用普通本机目录。")
    return path


def _read_json(path, *, required=False):
    path = _plain(path)
    try:
        if path.stat().st_size > 1024 * 1024:
            raise ValueError
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError
        return value
    except FileNotFoundError:
        if not required:
            return {}
    except (OSError, ValueError, UnicodeError):
        pass
    _error("invalid_state", "配置或运行记录损坏，请保留工作目录后重新检查。")


def _write_json(path, value):
    path = _plain(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + "." + secrets.token_hex(8))
    try:
        with open(temporary, "x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _hash_file(path):
    digest = sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_source(root=None, *, source=None):
    """Validate only the fixed, allowlisted one-case mathematical source."""
    source = _plain(source if source is not None else
                    (Path(root) if root is not None else package_root()) / "Sources" / "M01")
    manifest = _read_json(source / "source-manifest.json", required=True)
    expected = dict(schema_version=1, source_id="M01", case_id=CASE_ID,
                    wholly_synthetic=True, duration_seconds=86400,
                    source_version="M01-24h-v1", sampling_rate_hz=200, sample_count=17280000,
                    expected_raw_bytes=276480000)
    if (manifest.get("wholly_synthetic") is not True
            or type(manifest.get("schema_version")) is not int
            or any(manifest.get(key) != value for key, value in expected.items())):
        _error("invalid_source", "内置来源清单不符合一例24小时纯合成体验，请重新解压完整发布包。")
    rows = manifest.get("files")
    if not isinstance(rows, list) or len(rows) != len(SOURCE_FILES):
        _error("invalid_source", "内置来源文件清单不完整。")
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            _error("invalid_source", "内置来源文件清单不完整。")
        name = row.get("path")
        if (not isinstance(name, str) or name not in SOURCE_FILES or name in seen
                or PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts):
            _error("invalid_source", "内置来源文件超出固定体验范围。")
        seen.add(name)
        size, digest = row.get("size_bytes"), row.get("sha256")
        path = _plain(source / name)
        if (type(size) is not int or size <= 0 or not isinstance(digest, str)
                or not TOKEN.fullmatch(digest) or not path.is_file()
                or path.stat().st_size != size or _hash_file(path) != digest):
            _error("source_checksum_failed", "内置来源文件校验失败，请重新解压完整发布包。")
    if seen != SOURCE_FILES:
        _error("invalid_source", "内置来源文件不完整。")
    raw = source / CASE_ID / "data" / f"{CASE_ID}.DATA"
    if raw.stat().st_size != 276480000:
        _error("invalid_source", "内置波形长度不是24小时。")
    allowed = SOURCE_FILES | {"source-manifest.json"}
    actual = set()
    allowed_dirs = {parent.as_posix() for name in SOURCE_FILES
                    for parent in PurePosixPath(name).parents if parent.as_posix() != "."}
    for entry in source.rglob("*"):
        _plain(entry)
        if entry.is_file():
            actual.add(entry.relative_to(source).as_posix())
        elif (not entry.is_dir()
              or entry.relative_to(source).as_posix() not in allowed_dirs):
            _error("invalid_source", "内置来源含不支持的目录或文件。")
    if actual != allowed:
        _error("invalid_source", "内置来源含额外文件，请使用完整的原发布包。")
    return source


def selected_source(*, register=False):
    home = evaluation_home()
    binding_path = home / "source-selection.json"
    binding = _read_json(binding_path)
    explicit = os.environ.get("ECG_DOCTOR_EVAL_SOURCE_ROOT")
    if binding:
        if (binding.get("profile") != PROFILE or binding.get("selected_dataset") != "M01"
                or not isinstance(binding.get("data_root"), str)):
            _error("invalid_source_selection", "已登记来源记录无效，未连接其他数据。")
        registered = _plain(binding["data_root"])
        if explicit and _plain(explicit) != registered:
            _error("source_rebinding_denied", "此体验已有固定来源，不会改连另一目录；请继续使用已登记的合成来源。")
        source = validate_source(source=registered)
    else:
        source = validate_source(source=_plain(explicit)) if explicit else validate_source()
    release = _read_json(package_root() / "RELEASE.json")
    minimum = release.get("minimum_source_version", "M01-24h-v1")
    expected_hash = release.get("source_manifest_sha256", "")
    if minimum != "M01-24h-v1":
        _error("unsupported_source_version", "此软件要求另一版合成来源，请使用匹配的软件与来源包。")
    if (expected_hash and (not isinstance(expected_hash, str) or not TOKEN.fullmatch(expected_hash)
                           or _hash_file(source / "source-manifest.json") != expected_hash)):
        _error("source_release_mismatch", "此软件与已登记合成来源校验不匹配，请使用对应发布包。")
    if register and not binding:
        _write_json(binding_path, dict(profile=PROFILE, selected_dataset="M01",
                                       data_root=str(source)))
    return source


def _software_version():
    from ecg_core.config import APP_VERSION
    return APP_VERSION


def _packaging_version():
    release = _read_json(package_root() / "RELEASE.json")
    value = release.get("packaging_version", "1.0.0")
    if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+\.\d+", value):
        _error("invalid_release_version", "软件发布包版本记录无效。")
    return value


def _version_key(version):
    if not isinstance(version, str):
        _error("invalid_workspace_version", "工作区版本记录缺失，未打开数据库。")
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:[.-].*)?$", version)
    if not match:
        _error("invalid_workspace_version", "工作区版本记录无效，未打开数据库。")
    date = re.search(r"\.(\d{8})$", version)
    return tuple(int(x) for x in match.groups()) + (int(date.group(1)) if date else 0,)


def database_schema(path):
    path = _plain(path)
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        rows = db.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name,tbl_name").fetchall()
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    return dict(user_version=version, fingerprint=sha256(payload.encode("utf-8")).hexdigest())



def check_workspace_version(folder):
    record = _read_json(Path(folder) / "WORKSPACE.json", required=True)
    if record.get("workspace_format") != 1:
        _error("newer_workspace_format", "工作区格式不受此程序支持，请使用创建它的版本或选择以前的体验。")
    prior, current = record.get("software_version"), _software_version()
    prior_package = record.get("packaging_version", "1.0.0")
    current_package = _packaging_version()
    if (_version_key(prior) > _version_key(current)
            or _version_key(prior_package) > _version_key(current_package)):
        _error("newer_workspace_version", "此体验由更新的程序保存，请使用对应新版本。旧版不会打开或迁移它；可返回以前的体验。")
    if record.get("upgrade_pending"):
        _error("incomplete_upgrade", "上次升级尚未完成，升级前副本已保留。请保留该体验并使用匹配版本核对，或另建体验。")
    return record, prior, current, prior_package, current_package

def prepare_upgrade(folder):
    """Snapshot saved work before the existing application's schema migration."""
    folder = _plain(folder)
    path, database = folder / "WORKSPACE.json", folder / "data" / "cardioinsight.db"
    record, prior, current, prior_package, current_package = check_workspace_version(folder)
    before = database_schema(database)
    if before != record.get("sqlite_schema"):
        _error("workspace_schema_changed", "数据库结构与工作区版本记录不一致，未迁移或创建空库。请使用匹配版本核对。")
    if prior == current and prior_package == current_package:
        return None
    snapshots = _plain(folder / "upgrade-snapshots")
    snapshots.mkdir(exist_ok=True)
    name = "before-upgrade-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(6) + ".sqlite3"
    target = snapshots / name
    # SQLite's online backup reads committed WAL as well as the main file.
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)) as source:
        source.execute("PRAGMA query_only=ON")
        source.execute("PRAGMA trusted_schema=OFF")
        with closing(sqlite3.connect(target)) as destination:
            deadline = time.monotonic() + 45
            def progress(status, remaining, total):
                if time.monotonic() > deadline:
                    _error("upgrade_snapshot_busy", "工作数据库繁忙，升级前副本未完成，请稍后重试。")
            source.backup(destination, pages=256, progress=progress, sleep=.05)
            if destination.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                _error("upgrade_snapshot_failed", "升级前工作副本未通过完整性检查，未打开体验。")
    with open(target, "r+b") as stream:
        stream.flush()
        os.fsync(stream.fileno())
    pending = dict(from_version=prior, to_version=current, from_packaging_version=prior_package,
                   to_packaging_version=current_package, snapshot=name,
                   snapshot_sha256=_hash_file(target), before_schema=before,
                   snapshot_integrity="ok")
    record["upgrade_pending"] = pending
    _write_json(path, record)
    return pending


def complete_upgrade(folder, pending):
    path = folder / "WORKSPACE.json"
    record = _read_json(path, required=True)
    after = database_schema(folder / "data" / "cardioinsight.db")
    if pending is None and record.get("application_initialized") and record.get("sqlite_schema") == after:
        return
    record.update(software_version=_software_version(), packaging_version=_packaging_version(),
                  sqlite_schema=after, application_initialized=True)
    if pending is not None:
        record["last_upgrade"] = dict(pending, after_schema=after)
        record.pop("upgrade_pending", None)
    _write_json(path, record)


def initialize_workspace_database(path):
    """Create an isolated workspace without retaining constructor SQLite handles."""
    from ecg_core.storage import Storage

    class InitialStorage(Storage):
        @contextmanager
        def connect(self):
            database = super().connect()
            try:
                with database:
                    yield database
            finally:
                database.close()

    InitialStorage(path)


class WorkspaceCatalog:
    def __init__(self, home, source):
        self.home, self.source = _plain(home), _plain(source)
        if (self.home == self.source or self.home in self.source.parents
                or self.source in self.home.parents):
            _error("overlapping_paths", "体验工作目录与内置来源必须独立。")
        self.home.mkdir(parents=True, exist_ok=True)
        self.path = self.home / "catalog.json"
        self.mutex = threading.RLock()

    def _load(self):
        value = _read_json(self.path)
        if not value:
            if self.path.exists():
                _error("invalid_catalog", "工作区目录记录为空，原工作保持保留。")
            return dict(profile=PROFILE, selected_workspace="", workspaces=[])
        ids = value.get("workspaces")
        if (value.get("profile") != PROFILE or not isinstance(ids, list)
                or len(ids) != len(set(str(x) for x in ids))
                or any(not isinstance(x, str) or not WORKSPACE_ID.fullmatch(x) for x in ids)
                or value.get("selected_workspace") not in ["", *ids]):
            _error("invalid_catalog", "体验工作区目录记录损坏，原工作保持保留。")
        return value

    def get(self, identifier):
        if not isinstance(identifier, str) or not WORKSPACE_ID.fullmatch(identifier):
            _error("invalid_workspace", "请从已保存的体验中选择工作区。")
        if identifier not in self._load()["workspaces"]:
            _error("invalid_workspace", "此体验不在工作区目录中。")
        folder = _plain(self.home / "workspaces" / identifier)
        record = _read_json(folder / "WORKSPACE.json", required=True)
        expected = dict(profile=PROFILE, workspace_id=identifier, selected_dataset="M01",
                        source_kind="mathematical_synthetic")
        if (any(record.get(k) != v for k, v in expected.items())
                or record.get("data_root") != str(self.source)
                or not _plain(folder / "data" / "cardioinsight.db").is_file()):
            _error("invalid_workspace", "已保存体验的配置或数据库不可用，未创建空数据库。")
        return folder

    def new(self):
        with self.mutex:
            value = self._load()
            identifier = secrets.token_hex(16)
            folder = _plain(self.home / "workspaces" / identifier)
            folder.mkdir(parents=True, exist_ok=False)
            (folder / "data").mkdir()
            initialize_workspace_database(folder / "data" / "cardioinsight.db")
            record = dict(profile=PROFILE, workspace_id=identifier, selected_dataset="M01",
                          source_kind="mathematical_synthetic", data_root=str(self.source),
                          created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            record.update(workspace_format=1, application_initialized=False,
                          software_version=_software_version(),
                          packaging_version=_packaging_version(),
                          sqlite_schema=database_schema(folder / "data" / "cardioinsight.db"))
            _write_json(folder / "WORKSPACE.json", record)
            _write_json(folder / "config.json", dict(
                data_root=str(self.source), selected_dataset="M01",
                listen_host="127.0.0.1", allow_phi=False))
            value["workspaces"].append(identifier)
            value["selected_workspace"] = identifier
            _write_json(self.path, value)
            return identifier

    def select(self, identifier):
        with self.mutex:
            self.get(identifier)
            value = self._load()
            value["selected_workspace"] = identifier
            _write_json(self.path, value)
            return identifier

    def current(self):
        with self.mutex:
            value = self._load()
            identifier = value["selected_workspace"]
            if identifier:
                self.get(identifier)
                return identifier
            return self.new()

    def items(self):
        with self.mutex:
            value = self._load()
            return [(identifier, _read_json(self.get(identifier) / "WORKSPACE.json",
                    required=True)["created_at"]) for identifier in reversed(value["workspaces"])]


@contextmanager
def instance_lock(path):
    path = _plain(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+b") as stream:
        if stream.seek(0, 2) == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        acquired = False
        try:
            if os.name == "nt":
                import msvcrt
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    acquired = True
                except OSError:
                    pass
            else:
                import fcntl
                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except BlockingIOError:
                    pass
            yield acquired
        finally:
            if acquired:
                if os.name == "nt":
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def process_identity(pid):
    if type(pid) is not int or pid <= 0:
        return None
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            code = wintypes.DWORD()
            times = [wintypes.FILETIME() for _ in range(4)]
            if (not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259
                    or not kernel.GetProcessTimes(handle, *(ctypes.byref(x) for x in times))):
                return None
            return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
        finally:
            kernel.CloseHandle(handle)
    try:
        value = subprocess.check_output(
            ["ps", "-p", str(pid), "-o", "lstart="], text=True, stderr=subprocess.DEVNULL).strip()
        return value or None
    except (OSError, subprocess.CalledProcessError):
        return None


def _valid_state(state, role):
    return (role in {"manager", "workspace"} and state.get("profile") == PROFILE
            and state.get("role") == role
            and type(state.get("pid")) is int and state["pid"] > 0
            and isinstance(state.get("birth"), str)
            and type(state.get("port")) is int and 1024 <= state["port"] <= 65535
            and isinstance(state.get("token"), str) and bool(TOKEN.fullmatch(state["token"])))


def _control(state, path="/_doctor/health", payload=None):
    """No proxies, redirects or non-loopback targets, even with inherited env."""
    if not _valid_state(state, state.get("role")):
        return {}
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{state['port']}{path}", data=data,
        headers={"X-Doctor-Control": state["token"], "Content-Type": "application/json"})
    try:
        with opener.open(req, timeout=2) as response:
            value = json.load(response)
            return value if isinstance(value, dict) else {}
    except (OSError, ValueError, urllib.error.URLError):
        return {}


def owned_ready(state, role):
    if not _valid_state(state, role) or process_identity(state["pid"]) != state["birth"]:
        return False
    health = _control(state)
    return (health.get("profile") == PROFILE and health.get("role") == role
            and health.get("pid") == state["pid"] and health.get("birth") == state["birth"])


def _command(*arguments):
    return ([sys.executable] if getattr(sys, "frozen", False) else
            [sys.executable, str(Path(__file__).resolve())]) + list(arguments)


def _spawn(*arguments):
    options = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, close_fds=True)
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    else:
        options["start_new_session"] = True
    return subprocess.Popen(_command(*arguments), **options)


def _wait_state(path, role, process=None, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = _read_json(path)
        if owned_ready(state, role):
            return state
        if process is not None and process.poll() is not None:
            _error("startup_failed", "本机服务未完成启动，已保存工作仍在原目录。")
        time.sleep(.1)
    _error("startup_timeout", "本机服务仍未健康响应，未结束其他进程。请保留工作区并重新检查。")


def _browser_url(state):
    return f"http://127.0.0.1:{state['port']}/_doctor/open?token={state['token']}"


def _environment(folder, source):
    os.environ.update(ECG_APP_DATA_ROOT=str(folder), ECG_DATA_ROOT=str(source),
                      ECG_CONFIG_PATH=str(folder / "config.json"), ECG_ALLOW_PHI="0",
                      ECG_TRUST_PROXY_HEADERS="0", ECG_DEMO_PASSWORD="",
                      ECG_DEMO_USERNAME="demo", ECG_DEMO_READONLY="0",
                      ECG_SESSION_COOKIE_SECURE="0")


def _install_guards(app, context):
    from flask import abort, jsonify, redirect, request
    import hmac
    def equal(value):
        return (isinstance(value, str)
                and hmac.compare_digest(value.encode("utf-8"), context["token"].encode("ascii")))
    def guard():
        origin = f"http://127.0.0.1:{context['port']}"
        if request.host != f"127.0.0.1:{context['port']}" or request.remote_addr != "127.0.0.1":
            abort(403)
        if context["shutdown"].is_set() and request.path not in {"/_doctor/health", "/_doctor/stop"}:
            abort(503)
        supplied_origin = request.headers.get("Origin")
        if ((supplied_origin is not None and supplied_origin != origin)
                or request.headers.get("Sec-Fetch-Site") == "cross-site"):
            abort(403)
        if request.path in {"/_doctor/health", "/_doctor/stop", "/_doctor/start"}:
            if not equal(request.headers.get("X-Doctor-Control")):
                abort(403)
        elif request.path == "/_doctor/open":
            if request.method != "GET" or not equal(request.args.get("token")):
                abort(403)
        else:
            if not equal(request.cookies.get(context["cookie_name"])):
                abort(403)
            if request.method in MUTATIONS and supplied_origin != origin:
                abort(403)
    app.before_request_funcs.setdefault(None, []).insert(0, guard)

    @app.get("/_doctor/open")
    def doctor_open():
        response = redirect("/", code=303)
        response.set_cookie(context["cookie_name"], context["token"], httponly=True,
                            samesite="Strict", secure=False, path="/")
        return response

    @app.get("/_doctor/health")
    def doctor_health():
        return jsonify({k: context[k] for k in ("profile", "role", "pid", "birth",
                                              "software_version", "packaging_version")})

    @app.post("/_doctor/stop")
    def doctor_stop():
        value = request.get_json(silent=True)
        if not isinstance(value, dict) or value.get("saved_work_acknowledged") is not True:
            return jsonify(error="请先保存工作并关闭体验网页。"), 400
        context["shutdown"].set()
        return jsonify(stopping=True)

    @app.after_request
    def doctor_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        # This application is an entirely offline loopback workstation.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
            "font-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "frame-ancestors 'none'; form-action "
            + ("'self' http://127.0.0.1:*" if context["role"] == "manager" else "'self'"))
        return response


def drain_and_close_server(server, context, timeout=120):
    """Drain work before stopping workers; close sockets in their own loop."""
    dispatcher = server.task_dispatcher
    server.accepting = False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with dispatcher.lock:
            busy = bool(dispatcher.queue) or dispatcher.active_count != 0
        # Request output is flushed by the still-running socket loop.
        channels = list(server.active_channels.copy().values())
        pending_output = any(channel.total_outbufs_len for channel in channels)
        if not busy and not pending_output:
            dispatcher.shutdown(cancel_pending=False, timeout=5)
            # BaseWSGIServer.close alone leaves keepalive channels in the map.
            # A trigger thunk avoids closing descriptors from the worker thread.
            server.trigger.pull_trigger(lambda: server.asyncore.close_all(server._map))
            return True
        time.sleep(.05)
    # Do not abandon an in-flight saved-work write after the grace period.
    context["shutdown"].clear()
    server.accepting = True
    return False


def _serve(app, context, state_path):
    from waitress import create_server
    server = create_server(app, host="127.0.0.1", port=0, threads=8, channel_timeout=120)
    context["port"] = int(server.effective_port)
    state = {key: context[key] for key in ("profile", "role", "pid", "birth", "port", "token")}
    if "workspace_id" in context:
        state["workspace_id"] = context["workspace_id"]
    _write_json(state_path, state)
    def stop_when_requested():
        while True:
            context["shutdown"].wait()
            if drain_and_close_server(server, context):
                return
    stopper = threading.Thread(target=stop_when_requested, daemon=True)
    stopper.start()
    try:
        server.run()
    finally:
        context["shutdown"].set()
        if _read_json(state_path).get("token") == context["token"]:
            state_path.unlink(missing_ok=True)


def _context(role, token):
    birth = process_identity(os.getpid())
    if not birth:
        _error("process_identity_failed", "无法核对本机进程身份，未启动服务。")
    return dict(profile=PROFILE, role=role, pid=os.getpid(), birth=birth,
                token=token, cookie_name="doctor_" + token[:20], port=0,
                software_version=_software_version(), packaging_version=_packaging_version(),
                shutdown=threading.Event())


def isolate_workspace_session(app, identifier):
    """Keep native Flask sessions separate across localhost ports and workspaces."""
    if not isinstance(identifier, str) or not WORKSPACE_ID.fullmatch(identifier):
        _error("invalid_workspace", "体验工作区身份无效。")
    app.config.update(SESSION_COOKIE_NAME="CardioInsightDoctorEval-" + identifier,
                      SESSION_COOKIE_SAMESITE="Strict")


def serve_workspace(identifier, token):
    if not TOKEN.fullmatch(token):
        _error("invalid_token", "启动身份无效。")
    source = selected_source()
    catalog = WorkspaceCatalog(evaluation_home(), source)
    folder = catalog.get(identifier)
    state_path = catalog.home / "runtime" / f"{identifier}.json"
    with instance_lock(catalog.home / "runtime" / f"{identifier}.lock") as acquired:
        if not acquired:
            _error("workspace_busy", "此体验已在运行，请从入口继续。")
        _environment(folder, source)
        upgrade = prepare_upgrade(folder)
        from app import create_app
        app = create_app(data_root=source, db_path=folder / "data" / "cardioinsight.db")
        isolate_workspace_session(app, identifier)
        complete_upgrade(folder, upgrade)
        context = _context("workspace", token)
        context["workspace_id"] = identifier
        _install_guards(app, context)
        _serve(app, context, state_path)


class Manager:
    def __init__(self, catalog):
        self.catalog = catalog
        self.children = []
        self.mutex = threading.RLock()

    def start(self, identifier):
        with self.mutex:
            folder = self.catalog.get(identifier)
            check_workspace_version(folder)
            path = self.catalog.home / "runtime" / f"{identifier}.json"
            state = _read_json(path)
            if owned_ready(state, "workspace"):
                health = _control(state)
                if (health.get("software_version") != _software_version()
                        or health.get("packaging_version") != _packaging_version()):
                    _error("old_workspace_running", "以前版本的体验仍在运行，请先保存并退出，再启动新版本。")
                return state
            if _valid_state(state, "workspace") and process_identity(state["pid"]) == state["birth"]:
                _error("workspace_unhealthy", "此体验进程尚未健康响应，未启动第二个实例。")
            token = secrets.token_hex(32)
            child = _spawn("_serve-workspace", "--workspace", identifier, "--runtime-token", token)
            self.children.append(child)
            state = _wait_state(path, "workspace", child)
            if state.get("workspace_id") != identifier or state.get("token") != token:
                _error("workspace_identity_mismatch", "体验服务身份不匹配，未连接其他进程。")
            return state

    def stop_workspaces(self):
        with self.mutex:
            stopped = True
            for identifier, _ in self.catalog.items():
                path = self.catalog.home / "runtime" / f"{identifier}.json"
                state = _read_json(path)
                if owned_ready(state, "workspace"):
                    reply = _control(state, "/_doctor/stop", {"saved_work_acknowledged": True})
                    stopped = bool(reply.get("stopping")) and stopped
                elif _valid_state(state, "workspace") and process_identity(state["pid"]) == state["birth"]:
                    stopped = False
            return stopped


def diagnostic(*, source_ok=True, runtime="not_running", root=None):
    from ecg_core.config import APP_VERSION
    release = _read_json((Path(root) if root is not None else package_root()) / "RELEASE.json")
    commit = release.get("source_commit", "")
    manifest_hash = ""
    if source_ok:
        try:
            source = selected_source()
            manifest_hash = _hash_file(source / "source-manifest.json")
        except (DoctorEvalError, OSError):
            source_ok = False
    return dict(schema="cardioinsight-doctor-feedback-v1", software_version=APP_VERSION,
                packaging_version=_packaging_version(), source_version="M01-24h-v1",
                source_manifest_sha256=manifest_hash,
                source_commit=commit if isinstance(commit, str) and re.fullmatch("[0-9a-f]{40}", commit) else "",
                target="Windows 10 x64", runtime_bits=struct.calcsize("P") * 8,
                host_family="Windows" if os.name == "nt" else "test_host",
                windows10_hospital_validation="not_confirmed",
                source_validation="passed" if source_ok else "failed",
                runtime_state=runtime if runtime in {"ready", "not_running", "unhealthy"} else "unhealthy",
                source_id="M01", wholly_synthetic=True,
                feedback_scope="technical_fields_only")


def feedback_bytes(value):
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("diagnostic.json", json.dumps(value, ensure_ascii=False, indent=2))
    return buffer.getvalue()


LANDING = """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CardioInsight 医生离线体验</title><link rel="icon" type="image/svg+xml" href="/favicon.svg">
<style>body{margin:0;background:#f4f8fa;color:#173642;font:16px/1.6 "Microsoft YaHei",sans-serif}
main{max-width:720px;margin:7vh auto;padding:32px;background:white;border-radius:22px;
box-shadow:0 16px 50px #15374512}svg{width:52px;vertical-align:middle;margin-right:12px}
h1{font-size:28px;line-height:1.3}p{color:#49646e}form{margin:14px 0}
button{border:0;border-radius:12px;padding:14px 20px;background:#17697b;color:white;
font-size:17px;font-weight:600;cursor:pointer;width:100%}.secondary{background:#e6f0f3;color:#174c5c}
small{color:#57707a}select{padding:10px;width:100%;font:inherit;border:1px solid #c5d5da;border-radius:8px}
details{margin-top:28px}label{display:block}.notice{padding:14px;border-radius:10px;background:#f0f7f9}
@media(max-width:760px){main{margin:20px;padding:24px}}</style><main>
<h1><svg viewBox="0 0 64 64" aria-hidden="true"><rect width="64" height="64" rx="16" fill="#17697b"/>
<path d="M8 34h12l6-16 9 30 7-19 5 5h9" fill="none" stroke="white" stroke-width="3"
stroke-linejoin="round"/></svg>医生离线体验</h1>
<p>一例24小时纯数学合成心电，完整工作站与现有算法报告。无需安装Python，使用本机浏览器。</p>
<p class="notice">仅用于软件功能体验。Windows 10 x64；医院电脑架构及实机兼容性尚未确认。
算法中的不可用项目保留原标识。</p>
<form method="post" action="/continue"><input type="hidden" name="_csrf" value="{{csrf}}">
<button id="continueExperience">开始 / 继续体验</button></form>
<form method="post" action="/new" target="_blank"><input type="hidden" name="_csrf" value="{{csrf}}">
<button id="newExperience" class="secondary">新体验（保留旧工作）</button></form>
<form method="post" action="/feedback"><input type="hidden" name="_csrf" value="{{csrf}}">
<button id="exportFeedback" class="secondary">导出反馈</button></form>
<small>反馈包仅含版本、运行环境和健康状态等技术字段。请发送此反馈包。
病例、数据库、报告、原始文件及自由文字均不在包内。</small>
{% if items %}<details><summary>返回以前的体验</summary>
<form method="post" action="/resume" target="_blank"><input type="hidden" name="_csrf" value="{{csrf}}">
<label for="previousWorkspace">选择创建时间</label><select id="previousWorkspace" name="workspace">
{% for id,created in items %}<option value="{{id}}">{{created}}</option>{% endfor %}</select>
<button id="resumePrevious" class="secondary">打开所选体验</button></form></details>{% endif %}
<p><small>新体验另开网页。切换前请保存草稿；已保存工作留在本机。
关闭浏览器不会停止本地服务。退出服务前请先保存修改并关闭体验网页。</small></p></main></html>"""


def manager_app(manager, context):
    from flask import Flask, abort, jsonify, redirect, render_template_string, request, Response
    import hmac
    app = Flask("cardioinsight_doctor_manager")
    app.config.update(MAX_CONTENT_LENGTH=4096)
    _install_guards(app, context)

    @app.before_request
    def form_guard():
        if request.method == "POST" and not request.path.startswith("/_doctor/"):
            if not hmac.compare_digest(request.form.get("_csrf", "").encode("utf-8"),
                                       context["token"].encode("ascii")):
                abort(403)

    @app.errorhandler(DoctorEvalError)
    def friendly_error(error):
        return render_template_string(
            "<!doctype html><meta charset=utf-8><title>体验未完成</title>"
            "<p>{{message}}</p><p><a href=/>返回体验入口并重试</a></p>",
            message=str(error)), 503

    @app.get("/favicon.ico")
    @app.get("/favicon.svg")
    def doctor_favicon():
        return Response('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
                        '<rect width="64" height="64" rx="16" fill="#17697b"/>'
                        '<path d="M8 34h12l6-16 9 30 7-19 5 5h9" fill="none" '
                        'stroke="white" stroke-width="3" stroke-linejoin="round"/></svg>',
                        mimetype="image/svg+xml")

    @app.get("/")
    def landing():
        return render_template_string(LANDING, csrf=context["token"], items=manager.catalog.items())

    @app.post("/continue")
    def continue_experience():
        state = manager.start(manager.catalog.current())
        return redirect(_browser_url(state), code=303)

    @app.post("/new")
    def new_experience():
        state = manager.start(manager.catalog.new())
        return redirect(_browser_url(state), code=303)

    @app.post("/resume")
    def resume_experience():
        state = manager.start(manager.catalog.select(request.form.get("workspace", "")))
        return redirect(_browser_url(state), code=303)

    @app.post("/feedback")
    def export_feedback():
        response = Response(feedback_bytes(diagnostic(runtime="ready")), mimetype="application/zip")
        response.headers["Content-Disposition"] = 'attachment; filename="CardioInsight-feedback.zip"'
        return response

    # Replace the generic graceful stop with an acknowledged owned-child stop.
    def stop_manager():
        value = request.get_json(silent=True)
        if not isinstance(value, dict) or value.get("saved_work_acknowledged") is not True:
            return jsonify(error="请先保存工作并关闭体验网页。"), 400
        if not manager.stop_workspaces():
            return jsonify(error="有体验尚未健康响应，未停止或结束其他进程。"), 409
        context["shutdown"].set()
        return jsonify(stopping=True)
    app.view_functions["doctor_stop"] = stop_manager

    @app.post("/_doctor/start")
    def internal_start():
        if request.headers.get("X-Doctor-Control") != context["token"]:
            abort(403)
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            abort(400)
        identifier = manager.catalog.new() if value.get("new") is True else manager.catalog.current()
        state = manager.start(identifier)
        return jsonify(workspace_id=identifier, ready=True)
    return app


def serve_manager(token):
    source = selected_source(register=True)
    home = evaluation_home()
    with instance_lock(home / "runtime" / "manager.lock") as acquired:
        if not acquired:
            _error("manager_busy", "体验入口已在运行，请重新双击启动入口。")
        manager = Manager(WorkspaceCatalog(home, source))
        context = _context("manager", token)
        _serve(manager_app(manager, context), context, home / "runtime" / "manager.json")


def ensure_manager(*, skip_selected_check=False):
    source = selected_source(register=True)
    home = evaluation_home()
    catalog = WorkspaceCatalog(home, source)
    selected = catalog._load()["selected_workspace"]
    if selected and not skip_selected_check:
        check_workspace_version(catalog.get(selected))
    # Controller lock serializes launches while the actual manager holds its
    # own lifetime lock. We never overwrite a live instance's state.
    with instance_lock(home / "runtime" / "launch.lock") as acquired:
        if not acquired:
            _error("launch_busy", "入口正在启动，请稍候再双击。")
        path = home / "runtime" / "manager.json"
        state = _read_json(path)
        if owned_ready(state, "manager"):
            health = _control(state)
            if (health.get("software_version") != _software_version()
                    or health.get("packaging_version") != _packaging_version()):
                _error("old_program_running", "以前版本入口仍在运行，请先保存并退出，再启动新版本。")
            return state
        if _valid_state(state, "manager") and process_identity(state["pid"]) == state["birth"]:
            _error("manager_unhealthy", "现有入口尚未健康响应，未启动第二个实例。")
        with instance_lock(home / "runtime" / "manager.lock") as free:
            if not free:
                return _wait_state(path, "manager", timeout=10)
        child = _spawn("_serve-manager", "--runtime-token", secrets.token_hex(32))
        return _wait_state(path, "manager", child)


def self_check():
    if struct.calcsize("P") * 8 != 64:
        _error("unsupported_architecture", "此体验发布包需要64位程序环境。")
    selected_source()
    state = _read_json(evaluation_home() / "runtime" / "manager.json")
    runtime = ("ready" if owned_ready(state, "manager") else
               "unhealthy" if _valid_state(state, "manager") and process_identity(state["pid"]) == state["birth"]
               else "not_running")
    return dict(diagnostic(runtime=runtime), check="passed", packaged_target="Windows 10 x64")


def request_stop(acknowledged=False):
    if not acknowledged:
        if os.name != "nt":
            _error("save_ack_required", "请先保存工作并关闭体验网页，再使用 --saved-work-acknowledged。")
        import ctypes
        answer = ctypes.windll.user32.MessageBoxW(
            None, "请先保存所有体验网页中的修改，并关闭这些网页。\n"
            "是否确认已保存并退出本机体验？\n已保存工作会继续保留。",
            "退出医生离线体验", 0x24)
        if answer != 6:
            return dict(stopping=False, cancelled=True)
    state = _read_json(evaluation_home() / "runtime" / "manager.json")
    if not owned_ready(state, "manager"):
        if _valid_state(state, "manager") and process_identity(state["pid"]) == state["birth"]:
            _error("stop_identity_unconfirmed", "现有入口尚未健康响应，无法确认退出身份；未结束任何进程。")
        return dict(stopping=False, runtime_state="not_running")
    reply = _control(state, "/_doctor/stop", {"saved_work_acknowledged": True})
    if not reply.get("stopping"):
        _error("stop_failed", "健康确认或优雅退出未完成，未结束任何其他进程。")
    return reply


def _probe_case(state):
    # Exercise the real Flask API using exactly the browser's scoped cookie.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(
        f"http://127.0.0.1:{state['port']}/api/cases",
        headers={"Cookie": "doctor_" + state["token"][:20] + "=" + state["token"]})
    try:
        with opener.open(req, timeout=30) as response:
            value = json.load(response)
        items = value.get("items", [])
        if (len(items) != 1 or items[0].get("case_id") != CASE_ID
                or items[0].get("technical", {}).get("duration_seconds_raw") != 86400):
            _error("smoke_case_failed", "真实病例接口未返回固定24小时合成体验。")
    except (OSError, ValueError, urllib.error.URLError) as error:
        if isinstance(error, DoctorEvalError):
            raise
        _error("smoke_case_failed", "真实病例接口检查未完成。")


def smoke_test():
    """Exercise the frozen executable with an isolated home and no browser."""
    folder = Path(tempfile.mkdtemp(prefix="cardioinsight-doctor-smoke-"))
    old = {key: os.environ.get(key) for key in ("ECG_DOCTOR_EVAL_HOME", "ECG_DOCTOR_EVAL_TESTING")}
    os.environ.update(ECG_DOCTOR_EVAL_HOME=str(folder), ECG_DOCTOR_EVAL_TESTING="1")
    state, child = None, None
    try:
        self_check()
        state = ensure_manager()
        result = _control(state, "/_doctor/start", {})
        if not result.get("ready"):
            _error("smoke_start_failed", "隔离启动检查失败。")
        child = _read_json(folder / "runtime" / f"{result['workspace_id']}.json", required=True)
        if not owned_ready(child, "workspace"):
            _error("smoke_health_failed", "体验服务健康检查失败。")
        _probe_case(child)
        request_stop(True)
        deadline = time.monotonic() + 130
        while time.monotonic() < deadline:
            if process_identity(child["pid"]) != child["birth"] and process_identity(state["pid"]) != state["birth"]:
                return dict(smoke="passed", packaged_target="Windows 10 x64",
                            windows10_hospital_validation="not_confirmed")
            time.sleep(.1)
        _error("smoke_stop_timeout", "检查服务尚未退出，未强行结束进程。")
    finally:
        if state and owned_ready(state, "manager"):
            _control(state, "/_doctor/stop", {"saved_work_acknowledged": True})
        # Keep a failed test's directory if a process still owns it. Removing
        # an open SQLite workspace would defeat the launcher preservation rule.
        states = [_read_json(p) for p in (folder / "runtime").glob("*.json")]
        live = any(_valid_state(s, s.get("role")) and process_identity(s["pid"]) == s["birth"] for s in states)
        if not live:
            shutil.rmtree(folder)
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def main(argv=None):
    # Frozen CLI helpers must emit Chinese diagnostics without depending on
    # the Windows console locale; the browser entry remains the normal UI.
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="CardioInsight Windows 10 x64 医生离线体验")
    parser.add_argument("action", nargs="?", default="launch",
                        choices=["launch", "new", "check", "feedback", "stop",
                                 "_serve-manager", "_serve-workspace"])
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--saved-work-acknowledged", action="store_true")
    parser.add_argument("--source-root", default=None, help="首次显式登记经校验的纯合成 Sources/M01；不扫描其他目录")
    parser.add_argument("--workspace", default="")
    parser.add_argument("--runtime-token", default="")
    args = parser.parse_args(argv)
    if args.source_root is not None:
        os.environ["ECG_DOCTOR_EVAL_SOURCE_ROOT"] = str(Path(args.source_root).absolute())
    try:
        if args.smoke_test:
            result = smoke_test()
        elif args.self_check or args.action == "check":
            result = self_check()
        elif args.action == "_serve-manager":
            if not TOKEN.fullmatch(args.runtime_token):
                _error("invalid_token", "启动身份无效。")
            serve_manager(args.runtime_token)
            return 0
        elif args.action == "_serve-workspace":
            serve_workspace(args.workspace, args.runtime_token)
            return 0
        elif args.action == "stop":
            result = request_stop(args.saved_work_acknowledged)
        elif args.action == "feedback":
            source_ok = True
            try:
                selected_source()
            except DoctorEvalError:
                source_ok = False
            state = _read_json(evaluation_home() / "runtime" / "manager.json")
            data = diagnostic(source_ok=source_ok,
                              runtime="ready" if owned_ready(state, "manager") else "not_running")
            path = _plain(evaluation_home() / ("feedback-" + datetime.now().strftime("%Y%m%d-%H%M%S")
                                               + "-" + secrets.token_hex(4) + ".zip"))
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "xb") as stream:
                stream.write(feedback_bytes(data))
            result = dict(exported=True, filename=path.name, scope="technical_fields_only")
            if os.name == "nt" and not args.no_browser:
                os.startfile(str(path.parent))
        else:
            if args.workspace:
                source = selected_source(register=True)
                catalog = WorkspaceCatalog(evaluation_home(), source)
                check_workspace_version(catalog.get(args.workspace))
                catalog.select(args.workspace)
            state = ensure_manager(skip_selected_check=args.action == "new")
            if args.action == "new":
                created = _control(state, "/_doctor/start", {"new": True})
                if not created.get("ready"):
                    _error("new_failed", "新体验尚未健康响应，旧工作保持保留。")
                state = _read_json(evaluation_home() / "runtime" / f"{created['workspace_id']}.json", required=True)
            result = dict(ready=True)
            if not args.no_browser:
                webbrowser.open(_browser_url(state), new=2)
        if sys.stdout is not None:
            print(json.dumps(result, ensure_ascii=False))
        return 0
    except (DoctorEvalError, OSError) as error:
        code = error.code if isinstance(error, DoctorEvalError) else "local_io_failed"
        message = str(error) if isinstance(error, DoctorEvalError) else "本机文件或服务不可用，请保留工作区并重新检查。"
        if sys.stderr is not None:
            print(json.dumps(dict(error=code, message=message), ensure_ascii=False), file=sys.stderr)
        if os.name == "nt" and not args.no_browser and not args.self_check and not args.smoke_test:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "医生离线体验未完成", 0x10)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
