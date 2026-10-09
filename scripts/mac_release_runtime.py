"""Explicit local-only Mac evaluation profiles and owned-process lifecycle.

No source discovery, live database replacement, global process termination,
permission changes, dependency installation, or network service configuration.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import webbrowser

PROFILE = 'cardioinsight-mac-evaluation-v1'
SOURCES = ('hospital_real', 'mathematical_synthetic')


class ReleaseError(ValueError):
    pass


def manifest():
    from ecg_core.config import resource_root
    path = resource_root() / 'mac-release-manifest.json'
    if path.is_file():
        return json.loads(path.read_text(encoding='utf-8'))
    return dict(release_id='mac-evaluation-source-unbuilt', source_sha256='',
                intended_use='doctor_functional_evaluation', distribution='not-notarized')


def default_config():
    explicit = os.environ.get('ECG_MAC_CONFIG')
    if explicit:
        return Path(explicit).expanduser().resolve()
    # Separate from every earlier application/workspace configuration.
    base = os.environ.get('ECG_MAC_EVALUATION_HOME')
    return (Path(base).expanduser() if base else
            Path.home() / 'Library' / 'Application Support' / 'CardioInsightMacEvaluation') / 'config.json'


def _private_json(path, value, *, exclusive=False):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink():
        raise ReleaseError('配置或运行记录不能是链接；请保留目录并检查。')
    if exclusive:
        with open(path, 'x', encoding='utf-8') as stream:
            os.chmod(path, 0o600)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
    else:
        temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
        try:
            _private_json(temporary, value, exclusive=True)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def _path(value, base):
    result = Path(value).expanduser()
    result = result if result.is_absolute() else base / result
    if result.is_symlink():
        raise ReleaseError('请使用普通目录和数据库；配置指定的路径不能是链接。')
    return result.resolve()


def load_profile(config_path):
    config_path = _path(config_path, Path.cwd())
    if not config_path.is_file():
        raise ReleaseError('尚未初始化此评估版。请运行“初始化Mac评估版.command”，选择数学合成演示或明确指定本机数据目录；不会自动连接其他工作区。')
    try:
        value = json.loads(config_path.read_text(encoding='utf-8-sig'))
        required = ('profile', 'instance_id', 'workspace', 'database', 'data_root', 'source_kind', 'port')
        if not isinstance(value, dict) or any(key not in value for key in required):
            raise ValueError
        if value['profile'] != PROFILE or value['source_kind'] not in SOURCES:
            raise ValueError
        uuid.UUID(value['instance_id'])
        if type(value['port']) is not int or not 1024 <= value['port'] <= 65535:
            raise ValueError
        workspace = _path(value['workspace'], config_path.parent)
        data_root = _path(value['data_root'], config_path.parent)
        database = _path(value['database'], workspace)
    except ReleaseError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise ReleaseError('评估配置缺失或格式错误。请保留现有工作区，用检查入口确认；未回退到其他配置或数据。') from error
    _boundaries(data_root, workspace, database)
    if not workspace.is_dir() or not database.is_file():
        raise ReleaseError('已配置的工作区或数据库不存在；为保护已保存工作，未创建空数据库。恢复配置必须指向 data/cardioinsight.db。')
    return dict(value, workspace=workspace, database=database, data_root=data_root,
                config_path=config_path)


def _boundaries(source, workspace, database):
    if source == workspace or source in workspace.parents or workspace in source.parents:
        raise ReleaseError('数据源与工作区必须是互不包含的独立目录。')
    if workspace not in database.parents:
        raise ReleaseError('数据库必须位于此评估工作区内。')
    if not source.is_dir():
        raise ReleaseError('指定的数据目录不存在或不可读；未回退到其他数据。')
    if source.is_symlink() or workspace.is_symlink() or database.is_symlink():
        raise ReleaseError('请使用独立的普通目录和数据库，不能用链接连接已有工作区。')


def validate_source(source):
    from ecg_core.repository import CaseRepository
    try:
        cases, issues = CaseRepository(source).scan_cases()
    except OSError as error:
        raise ReleaseError('指定的数据目录无法读取；请检查完整性和读取权限。') from error
    if issues or not cases:
        raise ReleaseError(f'指定目录有 {len(cases)} 个可读病例、{len(issues)} 个不可用病例。请核对 DATA、EBI 和 LPS 的完整性；未连接其他来源。')
    return [case['case_id'] for case in cases]


def _environment(profile):
    # Authoritative selection overrides inherited clinical/demo/proxy settings.
    os.environ.update(ECG_ALLOW_PHI='0', ECG_APP_DATA_ROOT=str(profile['workspace']),
                      ECG_DATA_ROOT=str(profile['data_root']),
                      ECG_CONFIG_PATH=str(profile['config_path']), ECG_TRUST_PROXY_HEADERS='0',
                      ECG_DEMO_PASSWORD='', ECG_DEMO_READONLY='0', ECG_SESSION_COOKIE_SECURE='0')


def initialize(config_path, workspace, data_root=None, *, synthetic=False, source_kind='hospital_real', port=8768):
    from ecg_core.storage import Storage
    config_path, workspace = _path(config_path, Path.cwd()), _path(workspace, Path.cwd())
    if config_path.exists() or workspace.exists():
        raise ReleaseError('配置和工作区必须尚不存在；不会覆盖已有记录。请为本次评估选择新目录。')
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ReleaseError('端口应在 1024–65535 范围内。')
    if source_kind not in SOURCES:
        raise ReleaseError('来源类型不受支持。')
    if synthetic:
        from scripts.mac_release_synthetic import generate
        if data_root is None:
            data_root = workspace.with_name(workspace.name + '-数学合成来源')
        source_kind = 'mathematical_synthetic'
        source = _path(data_root, Path.cwd())
        # Check nesting before generating any file.
        if source == workspace or source in workspace.parents or workspace in source.parents:
            raise ReleaseError('合成来源和工作区必须是两个独立目录。')
        generate(source)
    elif data_root is None:
        raise ReleaseError('请显式指定 --data-root 或 --synthetic；不自动发现真实数据。')
    else:
        source = _path(data_root, Path.cwd())
    database = workspace / 'data' / 'cardioinsight.db'
    _boundaries(source, workspace, database)
    if source_kind not in SOURCES:
        raise ReleaseError('来源类型不受支持。')
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ReleaseError('端口应在 1024–65535 范围内。')
    validate_source(source)
    workspace.mkdir(mode=0o700, parents=True)
    (workspace / 'data').mkdir(mode=0o700)
    Storage(database)
    os.chmod(database, 0o600)
    value = dict(profile=PROFILE, instance_id=str(uuid.uuid4()), workspace=str(workspace),
                 database='data/cardioinsight.db', data_root=str(source), source_kind=source_kind,
                 port=port, intended_use='doctor_functional_evaluation', allow_phi=False)
    _private_json(config_path, value, exclusive=True)
    return dict(initialized=True, config=str(config_path), workspace=str(workspace),
                database=str(database), source_kind=source_kind)


def _osascript(lines):
    result = subprocess.run(['/usr/bin/osascript', '-e', '\n'.join(lines)],
                            capture_output=True, text=True)
    if result.returncode:
        raise ReleaseError('已取消操作；现有工作区和服务保持原状。')
    return result.stdout.strip()


def _literal(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'


def interactive_initialize(config_path):
    # Native macOS dialog; the runtime contains every Python dependency already.
    choice = _osascript(['button returned of (display dialog "此版本仅供医生功能评估，电压未标定，200 Hz 与 8→12 通道映射待独立核验，无医生金标准。请选择来源。" buttons {"取消", "选择本机数据", "数学合成演示"} default button "数学合成演示" cancel button "取消")'])
    source = None
    if choice == '选择本机数据':
        source = Path(_osascript(['POSIX path of (choose folder with prompt "选择本机病例数据总目录。程序只读源文件，身份强制遮蔽。")']))
    parent = Path(_osascript(['POSIX path of (choose folder with prompt "选择新工作区的父目录。不会覆盖已有工作区。")']))
    folder = parent / ('CardioInsight医生评估-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6])
    return initialize(config_path, folder, source, synthetic=choice == '数学合成演示')


def _runtime(profile):
    folder = profile['workspace'] / 'runtime'
    folder.mkdir(mode=0o700, exist_ok=True)
    return folder


@contextmanager
def _lock(profile):
    path = _runtime(profile) / 'control.lock'
    with open(path, 'a') as stream:
        os.chmod(path, 0o600)
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ReleaseError('此工作区已有启动或停止操作，请完成后重试。') from error
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def _process(pid):
    if type(pid) is not int or pid <= 1 or pid == os.getpid():
        return None
    # On Darwin the command column must be last; otherwise ps truncates it to
    # 15 characters even with -ww. Start time prevents matching a reused PID.
    result = subprocess.run(['/bin/ps', '-ww', '-p', str(pid), '-o', 'lstart=', '-o', 'command='],
                            capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def _stable_process(process, profile, token):
    """Capture only the child after exec, with its explicit invocation identity."""
    previous = None
    for _ in range(100):
        value = _process(process.pid)
        if process.poll() is not None:
            raise ReleaseError('服务进程已退出；工作区保留，请查看运行日志。')
        if (value and value == previous and '--runtime-token ' + token in value
                and '--config ' + str(profile['config_path']) in value):
            return value
        previous = value
        time.sleep(.05)
    raise ReleaseError('无法确认新进程的完整启动身份；未结束其他进程，请保留工作区和运行日志。')


def _read_state(profile):
    try:
        value = json.loads((_runtime(profile) / 'server.json').read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _owned(profile, state):
    return (state.get('instance_id') == profile['instance_id']
            and state.get('config_path') == str(profile['config_path'])
            and bool(state.get('exact_process'))
            and _process(state.get('pid')) == state['exact_process'])


def _context(port):
    # Bypass HTTP_PROXY/ALL_PROXY and never send local case details to a proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f'http://127.0.0.1:{port}/api/mac-release-context', timeout=.8) as response:
            return json.load(response)
    except (OSError, ValueError, urllib.error.URLError):
        return {}


def _same_server(profile, state):
    value = _context(profile['port'])
    return (value.get('instance_id') == profile['instance_id'] and value.get('pid') == state.get('pid')
            and value.get('runtime_token') == state.get('runtime_token'))


def status(profile):
    state = _read_state(profile)
    owned = _owned(profile, state)
    ready = owned and _same_server(profile, state)
    return dict(running=bool(ready), owned_process=bool(owned), pid=state.get('pid') if owned else None,
                url=f"http://127.0.0.1:{profile['port']}", config=str(profile['config_path']),
                workspace=str(profile['workspace']), database=str(profile['database']),
                source_kind=profile['source_kind'], release_id=manifest()['release_id'],
                allow_phi=False, intended_use='doctor_functional_evaluation')


def launch(profile, *, no_browser=False):
    with _lock(profile):
        state = _read_state(profile)
        if _owned(profile, state):
            if not _same_server(profile, state):
                raise ReleaseError('已有本工作区进程正在启动或未健康响应；未启动第二个实例。请运行检查入口并保留工作区。')
            result = dict(status(profile), already_running=True)
        else:
            with socket.socket() as probe:
                # Match waitress reuse semantics; a stopped server's TIME_WAIT
                # connections do not mean a live listener owns the port.
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    probe.bind(('127.0.0.1', profile['port']))
                except PermissionError as error:
                    raise ReleaseError('系统未允许本机监听。未修改系统权限或网络设置；请由管理员检查启动环境。工作区保持原状。') from error
                except OSError as error:
                    raise ReleaseError(f"端口 {profile['port']} 已被占用。未终止其他服务，未改用其他端口；请在本评估配置里选择可用端口。") from error
            validate_source(profile['data_root'])
            command = ([sys.executable] if getattr(sys, 'frozen', False) else
                       [sys.executable, str(Path(__file__).resolve().parents[1] / 'mac_release.py')])
            token = uuid.uuid4().hex
            command += ['serve', '--config', str(profile['config_path']), '--runtime-token', token]
            log_path = _runtime(profile) / 'server.log'
            with open(log_path, 'ab') as log:
                os.chmod(log_path, 0o600)
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                           cwd=str(profile['workspace']), start_new_session=True)
            state = dict(pid=process.pid, instance_id=profile['instance_id'], runtime_token=token,
                         config_path=str(profile['config_path']), exact_process=_stable_process(process, profile, token),
                         executable=str(Path(sys.executable).resolve()), argv=command,
                         port=profile['port'], database=str(profile['database']),
                         release_id=manifest()['release_id'], started_at=datetime.now(timezone.utc).isoformat())
            _private_json(_runtime(profile) / 'server.json', state)
            for _ in range(150):
                if process.poll() is not None:
                    raise ReleaseError('服务未能启动；原记录保留。请查看本工作区 runtime/server.log，确认数据、权限和端口。')
                if _same_server(profile, state):
                    if not _owned(profile, state):
                        state['exact_process'] = _stable_process(process, profile, token)
                        _private_json(_runtime(profile) / 'server.json', state)
                    break
                time.sleep(.1)
            else:
                raise ReleaseError('启动仍未完成；进程和工作区已保留，请用检查入口查看状态，不要重复初始化。')
            result = dict(status(profile), already_running=False)
    if not no_browser:
        webbrowser.open(result['url'])
    return result


def stop(profile, *, saved_work_acknowledged=False):
    if not saved_work_acknowledged:
        raise ReleaseError('请先在页面保存报告、注释与模板修改。停止不会保存未提交的浏览器修改；确认后使用 --saved-work-acknowledged。')
    with _lock(profile):
        state = _read_state(profile)
        if not _owned(profile, state):
            if _process(state.get('pid')):
                raise ReleaseError('运行记录与当前进程不一致；为保护其他服务，没有结束任何进程。')
            return dict(stopped=True, already_stopped=True, database_preserved=profile['database'].is_file())
        if not _same_server(profile, state):
            raise ReleaseError('服务身份无法确认；没有结束进程。请保留工作区并查看运行记录。')
        # Repeat exact PID + start-time + command ownership immediately before signal.
        if not _owned(profile, state):
            raise ReleaseError('进程身份已改变；没有结束进程。')
        os.kill(state['pid'], signal.SIGTERM)
        for _ in range(100):
            if _process(state['pid']) != state['exact_process']:
                break
            time.sleep(.1)
        else:
            raise ReleaseError('服务仍在退出；未强制终止，请保留工作区并稍后检查。')
        state.update(stopped_at=datetime.now(timezone.utc).isoformat())
        _private_json(_runtime(profile) / 'server.json', state)
        return dict(stopped=True, database_preserved=profile['database'].is_file(), browser_closed=False)


def serve_profile(profile, token):
    from flask import jsonify
    from waitress import create_server
    from scripts.serve_local_review import create_review_app
    _environment(profile)
    validate_source(profile['data_root'])
    app = create_review_app(profile['data_root'], profile['workspace'], purpose='doctor_evaluation',
                            db_path=profile['database'], source_kind=profile['source_kind'],
                            release_id=manifest()['release_id'])

    @app.get('/api/mac-release-context')
    def release_context():
        return jsonify(instance_id=profile['instance_id'], pid=os.getpid(), runtime_token=token,
                       release_id=manifest()['release_id'], source_kind=profile['source_kind'],
                       local_only=True, phi_visible=False, database_path=str(profile['database']),
                       intended_use='doctor_functional_evaluation', clinical_release=False,
                       independent_device_mapping_verified=False, voltage_calibrated=False,
                       physician_gold_standard=False)

    server = create_server(app, host='127.0.0.1', port=profile['port'], threads=4, channel_timeout=120)
    def shutdown(_signal, _frame):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, shutdown)
    try:
        server.run()
    finally:
        server.close()
    return 0


def restore(archive, workspace, data_root, *, source_kind='hospital_real', port=8768):
    from ecg_core.workspace_backup import restore_backup
    from ecg_core.workspace_backup import CORE, OPTIONAL
    import sqlite3
    from contextlib import closing
    workspace, source = _path(workspace, Path.cwd()), _path(data_root, Path.cwd())
    _boundaries(source, workspace, workspace / 'data' / 'cardioinsight.db')
    source_ids = set(validate_source(source))
    if source_kind not in SOURCES:
        raise ReleaseError('来源类型不受支持。')
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ReleaseError('端口应在 1024–65535 范围内。')
    result = restore_backup(archive, workspace)
    database = Path(result['database'])
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        work_ids = set()
        for name, fields in (CORE | OPTIONAL).items():
            if name in tables and 'case_id' in fields.split():
                work_ids.update(row[0] for row in connection.execute(f'SELECT DISTINCT case_id FROM "{name}"') if row[0])
    if work_ids - source_ids:
        raise ReleaseError('备份已恢复到新目录，但指定来源缺少备份中的病例；未生成启动配置。请保留恢复目录并明确选择对应的原始数据。')
    config = workspace / 'config.json'
    value = dict(profile=PROFILE, instance_id=str(uuid.uuid4()), workspace=str(workspace),
                 database='data/cardioinsight.db', data_root=str(source), source_kind=source_kind,
                 port=port, intended_use='doctor_functional_evaluation', allow_phi=False)
    _private_json(config, value, exclusive=True)
    return dict(result, config=str(config), connected_database=str(database), reports_require_review=True)


def _parser():
    parser = argparse.ArgumentParser(description='Mac 医生功能评估版：身份遮蔽、仅本机、独立工作区；含离线备份恢复。')
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init', help='在明确选择后创建新配置与新工作区')
    init.add_argument('--config', type=Path, default=default_config())
    init.add_argument('--workspace', type=Path)
    init.add_argument('--data-root', type=Path)
    init.add_argument('--synthetic', action='store_true')
    init.add_argument('--source-kind', choices=SOURCES, default='hospital_real')
    init.add_argument('--port', type=int, default=8768)
    init.add_argument('--interactive', action='store_true')
    for name in ('launch', 'check', 'stop', 'serve', 'backup'):
        command = sub.add_parser(name)
        command.add_argument('--config', type=Path, default=default_config())
        if name == 'launch':
            command.add_argument('--no-browser', action='store_true')
            command.add_argument('--interactive', action='store_true')
        if name in ('stop', 'backup'):
            command.add_argument('--saved-work-acknowledged', action='store_true')
        if name == 'stop':
            command.add_argument('--interactive', action='store_true')
        if name == 'serve':
            command.add_argument('--runtime-token', required=True)
        if name == 'backup':
            command.add_argument('--destination', type=Path, required=True)
    verify = sub.add_parser('verify', help='离线校验备份，不需要系统 Python')
    verify.add_argument('archive', type=Path)
    recover = sub.add_parser('restore', help='离线恢复到新工作区，并明确连接已恢复数据库')
    recover.add_argument('archive', type=Path)
    recover.add_argument('--new-workspace', type=Path, required=True)
    recover.add_argument('--data-root', type=Path, required=True)
    recover.add_argument('--source-kind', choices=SOURCES, default='hospital_real')
    recover.add_argument('--port', type=int, default=8768)
    sub.add_parser('recover-interactive', help='选择备份和来源，离线恢复至全新工作区')
    sub.add_parser('about')
    return parser


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        arguments = ['launch', '--interactive']
    args = _parser().parse_args(arguments)
    try:
        if args.command == 'about':
            result = manifest()
        elif args.command == 'init':
            if args.interactive:
                result = interactive_initialize(args.config)
            else:
                if args.workspace is None:
                    raise ReleaseError('初始化必须明确指定 --workspace；不会使用原工作区。')
                result = initialize(args.config, args.workspace, args.data_root, synthetic=args.synthetic,
                                    source_kind=args.source_kind, port=args.port)
        elif args.command == 'verify':
            from ecg_core.workspace_backup import verify_backup
            result = verify_backup(args.archive)
        elif args.command == 'restore':
            result = restore(args.archive, args.new_workspace, args.data_root, source_kind=args.source_kind, port=args.port)
        elif args.command == 'recover-interactive':
            archive = Path(_osascript(['POSIX path of (choose file with prompt "选择已保存工作 .ecgbackup 备份。恢复不会覆盖当前工作区。")']))
            source = Path(_osascript(['POSIX path of (choose folder with prompt "选择此备份对应的原始病例总目录。备份不含原始 ECG 文件。")']))
            parent = Path(_osascript(['POSIX path of (choose folder with prompt "选择新恢复工作区的父目录；现有目录不会覆盖。")']))
            folder = parent / ('CardioInsight恢复-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6])
            kind = 'mathematical_synthetic' if (source / 'SYNTHETIC.json').is_file() else 'hospital_real'
            result = restore(archive, folder, source, source_kind=kind)
            _osascript(['display dialog ' + _literal('恢复完成。所有报告需重新复核。新配置：' + result['config'] + '\n请通过启动入口显式使用该新配置；原配置保持原状。') + ' buttons {"好"} default button "好"'])
        else:
            if args.command == 'launch' and args.interactive and not args.config.is_file():
                interactive_initialize(args.config)
            profile = load_profile(args.config)
            if args.command == 'serve':
                return serve_profile(profile, args.runtime_token)
            if args.command == 'launch':
                result = launch(profile, no_browser=args.no_browser)
            elif args.command == 'check':
                validate_source(profile['data_root'])
                result = status(profile)
            elif args.command == 'stop':
                acknowledged = args.saved_work_acknowledged
                if args.interactive:
                    _osascript(['display dialog "请先回到页面保存报告、注释与模板修改。停止服务不会保存未提交的浏览器修改，也不会关闭浏览器。已保存工作保留在独立数据库中。" buttons {"取消", "已保存，停止"} default button "取消" cancel button "取消"'])
                    acknowledged = True
                result = stop(profile, saved_work_acknowledged=acknowledged)
            else:
                if not args.saved_work_acknowledged:
                    raise ReleaseError('备份仅含已保存工作；请先保存页面修改，再使用 --saved-work-acknowledged。')
                from ecg_core.workspace_backup import create_backup
                result = create_backup(profile['database'], args.destination)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str), flush=True)
        return 0
    except (ReleaseError, ValueError, OSError) as error:
        message = str(error)
        print(message, file=sys.stderr, flush=True)
        if getattr(args, 'interactive', False) and sys.platform == 'darwin':
            # Cancellation is already visible in the preceding native dialog.
            if '已取消操作' not in message:
                subprocess.run(['/usr/bin/osascript', '-e',
                                'display alert "Mac评估版未完成操作" message ' + _literal(message)],
                               capture_output=True)
        return 2
