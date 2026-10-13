"""Read-only source identity; timestamps are cache keys, never content evidence."""
from contextlib import contextmanager
from functools import lru_cache
from functools import wraps
from hashlib import sha256
from inspect import signature as function_signature
from pathlib import Path
import os
import secrets
import threading
import stat
import sys

from .review_workflow import ReportConflict


class SourceUnavailable(RuntimeError):
    """A cloud placeholder must not block a clinical request indefinitely."""

    code = 'source_not_local'


class SourceInvalid(ValueError):
    """Readable bytes that do not satisfy the supported source format."""

    code = 'source_invalid'


class SourceReadError(RuntimeError):
    """An input is missing or unreadable; never disclose its filesystem path."""

    code = 'source_unreadable'


def require_local_file(path):
    try:
        info = Path(path).stat()
    except OSError as error:
        raise SourceReadError('原始文件缺失或无法读取，请核对病例文件是否完整、存储设备是否可用及读取权限。') from error
    if not stat.S_ISREG(info.st_mode):
        raise SourceInvalid('病例输入不是普通文件，请重新导入完整的原始病例。')
    # macOS SDK sys/stat.h: SF_DATALESS = 0x40000000. No content read here.
    if sys.platform == 'darwin' and getattr(info, 'st_flags', 0) & 0x40000000:
        raise SourceUnavailable('原始文件尚未完整下载到本地，暂不能读取波形或计算报告。'
                                '请在访达中将病例文件夹下载并保留在本地，完成后重试。')
    # Windows cloud recall flags: query attributes only, never hydrate inputs.
    if os.name == 'nt' and getattr(info, 'st_file_attributes', 0) & 0x441000:
        raise SourceUnavailable('原始文件尚未完整保留在本地，暂不能读取波形或计算报告。'
                                '请将合成来源完整解压到普通本机目录，完成后重试。')
    return info


def require_waveform_file(path):
    from .config import CHANNEL_COUNT
    info = require_local_file(path)
    if not info.st_size or info.st_size % (CHANNEL_COUNT * 2):
        raise SourceInvalid('DATA 波形为空或不是完整的 8 通道 int16 帧，请重新复制完整病例；未生成分析结果。')
    return info


def source_read(function):
    """Reject I/O failure and source changes, including reads served by a cache."""
    parameter = next(iter(function_signature(function).parameters))
    @wraps(function)
    def checked(*args, **kwargs):
        path = args[0] if args else kwargs[parameter]
        require_local_file(path)
        try:
            signature = file_signature(path)
            result = function(*args, **kwargs)
            if file_signature(path) != signature:
                raise ReportConflict('原始文件在读取期间发生变化，请确认文件稳定后重新载入病例')
            return result
        except OSError as error:
            raise SourceReadError('原始文件读取失败，请检查存储设备与读取权限，恢复后重试；未生成分析结果。') from error
    return checked


@lru_cache(maxsize=1)
def _windows_metadata_api():
    """Read Windows metadata through the supported Win32 file-attributes API."""
    import ctypes
    from ctypes import wintypes

    class FileBasicInfo(ctypes.Structure):
        _fields_ = [('CreationTime', ctypes.c_longlong),
                    ('LastAccessTime', ctypes.c_longlong),
                    ('LastWriteTime', ctypes.c_longlong),
                    ('ChangeTime', ctypes.c_longlong),
                    ('FileAttributes', wintypes.DWORD)]

    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                               ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                               wintypes.HANDLE]
    api.CreateFileW.restype = wintypes.HANDLE
    api.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    api.GetFileInformationByHandleEx.restype = wintypes.BOOL
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    return ctypes, api, FileBasicInfo


def _windows_change_time_ns(path):
    # Python's Windows st_ctime describes creation, not content/attribute changes.
    # FileBasicInfo.ChangeTime is the NTFS metadata-change clock. Restoring mtime
    # cannot therefore make an edited source or program reuse a previous hash.
    ctypes, api, info_type = _windows_metadata_api()
    value = os.path.abspath(os.fspath(path))
    if not value.startswith('\\\\?\\'):
        value = ('\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\')
                 else '\\\\?\\' + value)
    handle = api.CreateFileW(value, 0x80, 0x7, None, 3, 0x80, None)
    if handle in (None, ctypes.c_void_p(-1).value):
        raise OSError(ctypes.get_last_error(), 'Windows file metadata is unavailable')
    try:
        info = info_type()
        if not api.GetFileInformationByHandleEx(handle, 0, ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError(ctypes.get_last_error(), 'Windows file metadata is unavailable')
        if info.ChangeTime <= 0:
            raise OSError('Windows file metadata does not provide a change timestamp')
        return info.ChangeTime * 100 - 11644473600000000000
    finally:
        api.CloseHandle(handle)


_SOURCE_LEASES = {}
_SOURCE_LEASE_LOCK = threading.RLock()


def _content_hash(path):
    value = sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(1024 * 1024):
            value.update(block)
    return value.hexdigest()


@contextmanager
def read_locked_sources(paths):
    """Hold read-only Windows source handles; never alter permissions or data.

    Other readers may open the files, but writing/replacing them is prevented
    until this context exits. Only callers explicitly owning immutable inputs
    use this optimization; mutable inputs always obtain fresh content evidence.
    """
    if os.name != 'nt':
        yield
        return
    ctypes, api, _ = _windows_metadata_api()
    acquired = []
    try:
        with _SOURCE_LEASE_LOCK:
            for path in paths:
                key = str(Path(path).resolve())
                require_local_file(key)
                if key in _SOURCE_LEASES:
                    _SOURCE_LEASES[key]['references'] += 1
                else:
                    value = os.path.abspath(key)
                    if not value.startswith('\\\\?\\'):
                        value = ('\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\')
                                 else '\\\\?\\' + value)
                    handle = api.CreateFileW(value, 0x81, 0x1, None, 3, 0x80, None)
                    if handle in (None, ctypes.c_void_p(-1).value):
                        raise OSError(ctypes.get_last_error(), 'Immutable source is busy or unreadable')
                    _SOURCE_LEASES[key] = dict(handle=handle, references=1, token=secrets.token_hex(16))
                acquired.append(key)
        yield
    finally:
        with _SOURCE_LEASE_LOCK:
            for key in reversed(acquired):
                record = _SOURCE_LEASES[key]
                record['references'] -= 1
                if not record['references']:
                    del _SOURCE_LEASES[key]
                    api.CloseHandle(record['handle'])


def file_signature(path):
    s = Path(path).stat()
    if os.name != 'nt':
        return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    changed_ns = _windows_change_time_ns(path)
    with _SOURCE_LEASE_LOCK:
        lease = _SOURCE_LEASES.get(str(Path(path).resolve()))
        token = ('read_locked', lease['token']) if lease else ('content', _content_hash(path))
    # Windows clocks can repeat for rapid writes. A held read lease or actual
    # contents are required; timestamps alone never authorize a cached result.
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, (changed_ns, token))


@lru_cache(maxsize=64)
def _digest(path, signature):
    h = sha256()
    with Path(path).open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            h.update(chunk)
    if file_signature(path) != signature:
        raise ReportConflict('原始文件在读取期间发生变化，请确认采集文件稳定后重试')
    return h.hexdigest()


def file_evidence(path):
    try:
        path = str(Path(path).resolve())
        require_local_file(path)
        signature = file_signature(path)
        hashed = _digest(path, signature)
        # Check cached reads too: a replacement can happen between stat and lookup.
        if file_signature(path) != signature:
            raise ReportConflict('文件在校验期间发生变化，请确认文件稳定后重试')
        return {'sha256': hashed, 'bytes': signature[2]}
    except OSError as error:
        raise ReportConflict('无法读取用于核对的文件，请确认文件完整且可访问后重试') from error
