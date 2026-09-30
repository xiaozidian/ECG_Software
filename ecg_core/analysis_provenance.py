"""Bind review to the executing analysis build and original input contents.

Not an electronic signature: a database administrator can rewrite the ledger.
File metadata only accelerates hashes; size/mtime alone are not the identity.
"""
import copy
import importlib.util
import json
import logging
import marshal
import platform
import sys
import threading
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from .config import APP_VERSION, SAMPLE_RATE, CHANNEL_COUNT
from .review_workflow import ReportConflict
from .source_identity import (file_evidence, file_signature, SourceUnavailable,
                              SourceReadError, SourceInvalid)

MODULES = ('config', 'lps_parser', 'repository', 'ebi', 'waveform', 'beat_editor',
           'clinical_analysis', 'overview', 'rr_quality', 'hrv_analysis', 'stt',
           'advanced_analysis', 'report_layout', 'report_sections', 'report_pdf',
           'report_paper_pdf', 'report_sections_pdf', 'hrv_report_pdf', 'storage',
           'review_workflow', 'analysis_provenance', 'source_identity', 'workspace_backup',
           'clinical_query_cache', 'signal_profile')

LOGGER = logging.getLogger(__name__)
SIGNATURE_FIELDS = ('device', 'inode', 'bytes', 'mtime_ns', 'ctime_ns')


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class AnalysisRuntime:
    def __init__(self, recovery_epoch=''):
        self.recovery_epoch = recovery_epoch
        self.files = {}
        self.file_names = {}
        self.file_hashes = {}
        self._verification_lock = threading.Lock()
        self._rejected_changes = []
        self._diagnostic_lock = threading.Lock()
        self._last_change_diagnostic = None
        artifacts = {}
        root = Path(__file__).resolve().parent
        for name in ('app',) + tuple('ecg_core.' + n for n in MODULES):
            path = root.parent / 'app.py' if name == 'app' else root / (name.split('.')[-1] + '.py')
            if name == 'app' and not path.is_file() and getattr(sys, 'frozen', False):
                # PyInstaller stores the entry script in its executable archive,
                # not as an importable module. Bind that archive as well as PYZ code.
                path = Path(sys.executable).resolve()
            if path.is_file():
                signature = file_signature(path)
                artifacts[name] = file_evidence(path)['sha256']
                if file_signature(path) != signature:
                    raise ReportConflict('程序文件在启动期间发生变化，请完成更新后重启')
                self.files[path] = signature
                self.file_names[path] = name
                self.file_hashes[path] = artifacts[name]
            else:
                # Frozen distributions may contain only Python code objects.
                spec = importlib.util.find_spec(name)
                code = spec.loader.get_code(name) if spec and hasattr(spec.loader, 'get_code') else None
                if code is None:
                    raise RuntimeError('无法识别分析程序构建，请使用完整的软件安装包')
                artifacts[name] = sha256(marshal.dumps(code)).hexdigest()
        dependencies = {'python': platform.python_version()}
        for package in ('numpy', 'scipy', 'reportlab'):
            try:
                dependencies[package] = version(package)
            except PackageNotFoundError:
                dependencies[package] = 'unavailable'
        self.manifest = {'app_version': APP_VERSION, 'artifacts': artifacts,
                         'dependencies': dependencies, 'sample_rate_hz': SAMPLE_RATE,
                         'channels': CHANNEL_COUNT, 'input_format': 'little-endian int16'}
        self.engine_id = digest(self.manifest)
        self.assert_current()

    def assert_current(self):
        # One metadata recovery at a time; an older request must not overwrite a
        # newer verified signature or clear a previously detected build change.
        with self._verification_lock:
            self._assert_current()

    def _ctime_evidence(self, path, actual):
        """ctime alone is not proof of a code edit (e.g. macOS xattrs).

        The new signature makes file_evidence recheck content against its cache
        key; both before/after checks bind it to exactly the observed file state.
        No new build hash is accepted, even if timestamps have been restored.
        """
        try:
            if file_signature(path) != actual:
                return 'unstable'
            evidence = file_evidence(path)
            if file_signature(path) != actual:
                return 'unstable'
        except (OSError, ReportConflict, SourceUnavailable, SourceReadError, SourceInvalid):
            return 'unverified'
        return 'unchanged' if evidence['sha256'] == self.file_hashes[path] and evidence['bytes'] == actual[2] else 'different'

    def _assert_current(self):
        changes = []
        verified = {}
        for path, expected in self.files.items():
            # Only fixed module identities enter diagnostics, never installation
            # paths, request URLs, input contents or exception messages.
            name = self.file_names.get(path, 'untracked-artifact')
            try:
                actual = file_signature(path)
            except OSError as error:
                changes.append({'module': name, 'reason': 'stat_failed', 'errno': error.errno})
                continue
            if actual != expected:
                change = {'module': name, 'reason': 'metadata_changed',
                    'fields': {key: {'expected': a, 'actual': b}
                               for key, a, b in zip(SIGNATURE_FIELDS, expected, actual) if a != b}}
                if not self._rejected_changes and expected[:4] == actual[:4] and path in self.file_hashes:
                    result = self._ctime_evidence(path, actual)
                    if result == 'unchanged':
                        verified[path] = actual
                        continue
                    change['content_check'] = result
                if self._rejected_changes:
                    # Preserve the first content verdict while the same rejected
                    # state persists, without rereading an already invalid build.
                    previous = next((c for c in self._rejected_changes
                        if c.get('module') == name and c.get('fields') == change['fields']), {})
                    if 'content_check' in previous:
                        change['content_check'] = previous['content_check']
                changes.append(change)
        # Do not partially adopt metadata if another module changed, or if a
        # verified file changed again while the rest of the build was checked.
        if not changes:
            for path, actual in verified.items():
                try:
                    stable = file_signature(path) == actual
                except OSError:
                    stable = False
                if not stable:
                    changes.append({'module': self.file_names.get(path, 'untracked-artifact'),
                                    'reason': 'verification_race'})
        if changes:
            self._rejected_changes = changes
        else:
            # A detected update cannot be undone by restoring bytes/timestamps.
            # Only a fresh process may establish a new executing-build baseline.
            changes = self._rejected_changes
        if changes:
            diagnostic = json.dumps({'engine_id': self.engine_id, 'changes': changes},
                                    sort_keys=True, separators=(',', ':'))
            with self._diagnostic_lock:
                if diagnostic != self._last_change_diagnostic:
                    try:
                        LOGGER.warning('analysis_runtime_changed %s', diagnostic)
                    except Exception:
                        # A broken logging destination must never allow a mixed
                        # build or replace the clinically meaningful 409 with 500.
                        pass
                    else:
                        self._last_change_diagnostic = diagnostic
            raise ReportConflict('软件文件已更新，请重启本地服务后重新复核；不混用新旧算法')
        self.files.update(verified)
        if verified:
            try:
                LOGGER.info('analysis_runtime_metadata_verified %s', json.dumps({
                    'modules': sorted(self.file_names.get(p, 'untracked-artifact') for p in verified),
                    'changed_field': 'ctime_ns', 'startup_contents_match': True}, sort_keys=True))
            except Exception:
                pass  # Content verification succeeded independently of logging.

    def basis(self, case):
        self.assert_current()
        paths = {k: case['paths'][k] for k in ('data', 'ebi', 'lps')}
        try:
            signatures = {k: file_signature(p) for k, p in paths.items()}
            inputs = {k: file_evidence(p) for k, p in paths.items()}
            if signatures != {k: file_signature(p) for k, p in paths.items()}:
                raise ReportConflict('原始文件集在校验期间发生变化，请确认采集文件稳定后重试')
        except OSError as error:
            raise ReportConflict('原始文件缺失或不可读取，请重新核对病例文件') from error
        self.assert_current()
        body = {'schema': 1, 'engine_id': self.engine_id, 'inputs': inputs}
        if self.recovery_epoch:
            body['recovery_epoch'] = self.recovery_epoch
        return {**body, 'digest': digest(body), 'engine': copy.deepcopy(self.manifest)}
