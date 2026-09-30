"""Read-only source identity; timestamps are cache keys, never content evidence."""
from functools import lru_cache
from functools import wraps
from hashlib import sha256
from inspect import signature as function_signature
from pathlib import Path
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


def file_signature(path):
    s = Path(path).stat()
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


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
