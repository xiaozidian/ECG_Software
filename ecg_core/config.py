from __future__ import annotations

import json
import os
import platform
import sys
from pathlib import Path

APP_NAME = "CardioInsight Holter 心电分析工作站"
APP_VERSION = "0.11.0"
SAMPLE_RATE = 200
CHANNEL_COUNT = 8
RAW_FOLDER_NAME = "10个病人的心电数据"


def source_root() -> Path:
    return Path(__file__).resolve().parent.parent


def resource_root() -> Path:
    """Return the read-only bundle root used by PyInstaller or the source tree."""
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS).resolve()
    return source_root()


def runtime_root() -> Path:
    """Return the executable directory (read-only for installed desktop apps)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return source_root()


def install_root() -> Path:
    """Return the directory that contains the app bundle or source checkout."""
    executable = Path(sys.executable).resolve()
    if getattr(sys, "frozen", False) and sys.platform == "darwin":
        parents = executable.parents
        if len(parents) > 3 and parents[2].suffix == ".app":
            return parents[3]
    return runtime_root()


def user_data_root() -> Path:
    """Return the platform-native writable application data directory."""
    override = os.environ.get("ECG_APP_DATA_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "CardioInsightHolter"
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        return Path(base) / "CardioInsightHolter" if base else Path.home() / "AppData" / "Local" / "CardioInsightHolter"
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "cardioinsight-holter"


def _config_candidates() -> list[Path]:
    roots = [user_data_root(), install_root(), runtime_root(), resource_root(), source_root(), Path.cwd()]
    result: list[Path] = []
    for root in roots:
        candidate = root / "config.json"
        if candidate not in result:
            result.append(candidate)
    return result


def load_config() -> dict:
    for path in _config_candidates():
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            payload["_config_path"] = str(path)
            return payload
        except (OSError, ValueError):
            continue
    return {}


def resolve_data_root(explicit: str | os.PathLike[str] | None = None) -> Path | None:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("ECG_DATA_ROOT"):
        candidates.append(Path(os.environ["ECG_DATA_ROOT"]))

    config = load_config()
    configured = config.get("data_root")
    if configured:
        value = Path(configured)
        if not value.is_absolute() and config.get("_config_path"):
            value = Path(config["_config_path"]).parent / value
        candidates.append(value)

    for base in (install_root(), runtime_root(), source_root(), Path.cwd()):
        current = base.resolve()
        for _ in range(5):
            candidates.append(current / RAW_FOLDER_NAME)
            if current.parent == current:
                break
            current = current.parent

    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        key = str(resolved).casefold()
        if key in seen:
            continue
        seen.add(key)
        if resolved.is_dir() and any(child.is_dir() for child in resolved.iterdir()):
            return resolved
    return None


def writable_data_dir() -> Path:
    path = user_data_root() / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def output_dir() -> Path:
    path = user_data_root() / "output" / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def platform_info() -> dict[str, str]:
    return {
        "name": platform.system() or sys.platform,
        "release": platform.mac_ver()[0] if sys.platform == "darwin" else platform.release(),
        "machine": platform.machine(),
        "storage_root": str(user_data_root()),
        "config_path": str(user_data_root() / "config.json"),
    }
