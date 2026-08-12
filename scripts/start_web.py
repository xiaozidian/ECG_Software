"""Start CardioInsight Holter on a container or managed web platform."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _port() -> int:
    raw_value = os.environ.get("PORT", "8765")
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise SystemExit(f"PORT must be an integer, got {raw_value!r}") from exc
    if not 1 <= value <= 65535:
        raise SystemExit(f"PORT must be between 1 and 65535, got {value}")
    return value


def main() -> None:
    application = Path(__file__).resolve().parent.parent / "app.py"
    command = [
        sys.executable,
        str(application),
        "--host",
        "0.0.0.0",
        "--port",
        str(_port()),
        "--no-browser",
        "--allow-remote",
    ]
    os.execv(sys.executable, command)


if __name__ == "__main__":
    main()
