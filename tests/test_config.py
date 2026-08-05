from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import ecg_core.config as config_module
from ecg_core.config import load_config, output_dir, platform_info, user_data_root, writable_data_dir


def test_user_data_root_can_be_isolated(monkeypatch, tmp_path):
    app_root = tmp_path / "app-support"
    monkeypatch.setenv("ECG_APP_DATA_ROOT", str(app_root))

    assert user_data_root() == app_root.resolve()
    assert writable_data_dir() == app_root / "data"
    assert output_dir() == app_root / "output" / "reports"
    assert writable_data_dir().is_dir()
    assert output_dir().is_dir()


def test_project_config_has_priority_for_source_checkout(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    app_root = tmp_path / "app-support"
    app_root.mkdir()
    project_cases = tmp_path / "project-cases"
    user_cases = tmp_path / "user-cases"
    (project_root / "config.json").write_text(
        json.dumps({"data_root": str(project_cases), "listen_port": 8877}),
        encoding="utf-8",
    )
    (app_root / "config.json").write_text(
        json.dumps({"data_root": str(user_cases), "listen_port": 8999}),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "source_root", lambda: project_root)
    monkeypatch.setenv("ECG_APP_DATA_ROOT", str(app_root))

    config = load_config()
    assert config["data_root"] == str(project_cases)
    assert config["listen_port"] == 8877
    assert config["_config_path"] == str(project_root / "config.json")


def test_user_config_remains_fallback(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    app_root = tmp_path / "app-support"
    app_root.mkdir()
    expected_root = tmp_path / "cases"
    (app_root / "config.json").write_text(
        json.dumps({"data_root": str(expected_root), "listen_port": 8877}),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "source_root", lambda: project_root)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ECG_APP_DATA_ROOT", str(app_root))

    config = load_config()
    assert config["data_root"] == str(expected_root)
    assert config["_config_path"] == str(app_root / "config.json")


def test_platform_info_exposes_only_runtime_locations(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    app_root = tmp_path / "app-support"
    monkeypatch.setattr(config_module, "source_root", lambda: project_root)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ECG_APP_DATA_ROOT", str(app_root))

    info = platform_info()
    assert info["name"]
    assert info["machine"]
    assert info["storage_root"] == str(app_root.resolve())
    assert info["config_path"] == str(project_root / "config.json")


def test_native_user_data_root_matches_operating_system(monkeypatch):
    monkeypatch.delenv("ECG_APP_DATA_ROOT", raising=False)
    path = user_data_root()

    if sys.platform == "darwin":
        assert path == Path.home() / "Library" / "Application Support" / "CardioInsightHolter"
    elif os.name == "nt":
        expected_base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        assert expected_base
        assert path == Path(expected_base) / "CardioInsightHolter"
    else:
        assert path.name == "cardioinsight-holter"
