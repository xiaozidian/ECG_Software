from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app  # noqa: E402
from ecg_core.config import resolve_data_root  # noqa: E402


@pytest.fixture(scope="session")
def data_root() -> Path:
    path = resolve_data_root()
    assert path is not None, "未找到10例心电数据目录"
    return path


@pytest.fixture()
def app(data_root: Path, tmp_path: Path):
    application = create_app(data_root=data_root, db_path=tmp_path / "test.db", testing=True)
    yield application


@pytest.fixture()
def client(app):
    return app.test_client()
