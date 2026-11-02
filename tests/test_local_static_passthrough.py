"""The local presentation adapter must preserve send_file JSON responses."""
from pathlib import Path

from flask import Flask, jsonify


def local_client(monkeypatch, tmp_path):
    import app as backend
    from scripts.serve_local_review import create_review_app
    static = Path(__file__).resolve().parents[1] / 'static'
    base = Flask(__name__, static_folder=str(static), static_url_path='/static')
    base.config['ALLOW_PHI'] = False

    @base.get('/api/presentation-test')
    def api_value():
        return jsonify(metadata={'name': 'synthetic fixture', 'patient_id': 'fixture'}, value=3)

    monkeypatch.setattr(backend, 'create_app', lambda **kwargs: base)
    data = tmp_path / 'source'
    data.mkdir()
    application = create_review_app(data, tmp_path / 'work')
    return application.test_client(), static


def test_static_json_keeps_exact_bytes_and_valid_content(monkeypatch, tmp_path):
    client, static = local_client(monkeypatch, tmp_path)
    response = client.get('/static/terminology/builtin-draft-v1.json')
    assert response.status_code == 200
    assert response.is_json
    assert response.data == (static / 'terminology/builtin-draft-v1.json').read_bytes()
    assert response.get_json() is not None


def test_api_json_keeps_presentation_masking(monkeypatch, tmp_path):
    client, _ = local_client(monkeypatch, tmp_path)
    response = client.get('/api/presentation-test')
    assert response.status_code == 200
    assert response.get_json() == {'metadata': {'name': '已遮蔽', 'patient_id': '已遮蔽'}, 'value': 3}
