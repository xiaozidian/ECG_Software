from __future__ import annotations

import base64

from app import create_app


def _auth(username: str = "demo", password: str = "correct horse") -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _case_id(client) -> str:
    return client.get("/api/cases").json["items"][0]["case_id"]


def test_basic_auth_is_optional_and_health_probe_is_public(data_root, tmp_path, monkeypatch):
    monkeypatch.setenv("ECG_DEMO_PASSWORD", "correct horse")
    monkeypatch.setenv("ECG_DEMO_USERNAME", "presenter")
    application = create_app(data_root=data_root, db_path=tmp_path / "auth.db", testing=True)
    client = application.test_client()

    assert client.get("/api/health").status_code == 200
    challenge = client.get("/")
    assert challenge.status_code == 401
    assert challenge.headers["WWW-Authenticate"].startswith("Basic ")
    assert client.get("/", headers={"Authorization": "Basic !!!"}).status_code == 401
    assert client.get("/", headers=_auth("presenter", "wrong")).status_code == 401
    assert client.get("/", headers=_auth("wrong", "correct horse")).status_code == 401
    assert client.get("/", headers=_auth("presenter", "correct horse")).status_code == 200


def test_secret_key_is_stable_when_configured(data_root, tmp_path, monkeypatch):
    monkeypatch.setenv("ECG_SECRET_KEY", "a-stable-deployment-secret-key")
    first = create_app(data_root=data_root, db_path=tmp_path / "secret-1.db", testing=True)
    second = create_app(data_root=data_root, db_path=tmp_path / "secret-2.db", testing=True)
    assert first.config["SECRET_KEY"] == second.config["SECRET_KEY"] == "a-stable-deployment-secret-key"


def test_proxy_https_sets_secure_cookie_and_hsts(data_root, tmp_path, monkeypatch):
    monkeypatch.setenv("ECG_TRUST_PROXY_HEADERS", "true")
    monkeypatch.setenv("ECG_ALLOW_PHI", "true")
    application = create_app(data_root=data_root, db_path=tmp_path / "proxy.db", testing=True)
    client = application.test_client()

    response = client.post(
        "/api/privacy/view",
        json={"enabled": True},
        headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "demo.example"},
    )
    assert response.status_code == 200
    assert response.headers["Strict-Transport-Security"] == "max-age=31536000"
    assert "Secure" in response.headers["Set-Cookie"]
    assert application.config["SESSION_COOKIE_SECURE"] is True


def test_demo_readonly_blocks_writes_phi_and_private_admin_routes(data_root, tmp_path, monkeypatch):
    monkeypatch.setenv("ECG_DEMO_READONLY", "true")
    monkeypatch.setenv("ECG_ALLOW_PHI", "true")  # Read-only demo wins over an unsafe override.
    application = create_app(data_root=data_root, db_path=tmp_path / "readonly.db", testing=True)
    client = application.test_client()
    case_id = _case_id(client)

    assert application.config["ALLOW_PHI"] is False
    assert client.patch(f"/api/cases/{case_id}/patient", json={"name": "changed"}).status_code == 403
    assert client.post(f"/api/cases/{case_id}/annotations", json={"sample_index": 2000}).status_code == 403
    assert client.delete("/api/annotations/1").status_code == 403
    assert client.put(f"/api/cases/{case_id}/report", json={"conclusion": "changed", "status": "draft"}).status_code == 403
    assert client.post("/api/privacy/view", json={"enabled": True}).status_code == 403
    assert client.get(f"/api/cases/{case_id}?include_phi=1").json["phi_masked"] is True
    assert client.get(f"/api/cases/{case_id}/source-report/page/1?include_phi=1").status_code == 403
    assert client.get("/api/settings").status_code == 404
    assert client.get("/api/audit").status_code == 404

    page = client.get("/").get_data(as_text=True)
    assert 'data-demo-readonly="true"' in page
    assert 'data-page="settings"' not in page
    assert 'data-page="audit"' not in page
    assert 'id="privacyToggle"' in page and "aria-hidden=\"true\"" in page
    assert 'id="conclusionEditor"' in page and "readonly" in page


def test_demo_readonly_keeps_case_open_and_computation_posts(data_root, tmp_path, monkeypatch):
    monkeypatch.setenv("ECG_DEMO_READONLY", "true")
    application = create_app(data_root=data_root, db_path=tmp_path / "compute.db", testing=True)
    client = application.test_client()
    case_id = _case_id(client)

    assert client.post(f"/api/cases/{case_id}/open", json={}).status_code == 200
    scatter = client.get(f"/api/cases/{case_id}/scatter?mode=rr&max_points=500").json
    target = scatter["points"][0]
    polygon = [
        [target["x"] - 2, target["y"] - 2],
        [target["x"] + 2, target["y"] - 2],
        [target["x"] + 2, target["y"] + 2],
        [target["x"] - 2, target["y"] + 2],
    ]
    selected = client.post(
        f"/api/cases/{case_id}/scatter-selection",
        json={"mode": "rr", "polygon": polygon},
    )
    assert selected.status_code == 200
    assert selected.json["sample_indices"]

    strips = client.post(
        f"/api/cases/{case_id}/waveform-strips",
        json={"sample_indices": selected.json["sample_indices"][:1], "leads": ["II"]},
    )
    assert strips.status_code == 200
    assert len(strips.json["items"]) == 1
