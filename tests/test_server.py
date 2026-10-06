import json
import time

import pytest
from fastapi.testclient import TestClient

from lisn.config import Config
from lisn.player.audio import SilentOutput
from lisn.server.api import create_app
from lisn.server.sessions import SessionManager

TOKEN = "secret-token"


@pytest.fixture
def client(fake_engine):
    manager = SessionManager(fake_engine, Config(voice="fake_voice"), output_factory=lambda: SilentOutput(time_scale=4))
    app = create_app(manager, TOKEN)
    with TestClient(app) as test_client:
        yield test_client
    manager.close_current()


def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


def test_health_is_public(client):
    response = client.get("/health")
    assert response.status_code == 200 and response.json()["ok"] is True


def test_requires_token(client):
    assert client.get("/voices").status_code == 401
    assert client.get("/voices", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/voices", params={"token": TOKEN}).status_code == 200


def test_session_lifecycle(client):
    created = client.post("/session", json={"text": "One two. Three four.\n\nFive six.", "title": "T"}, headers=auth())
    assert created.status_code == 200, created.text
    info = created.json()
    assert info["title"] == "T" and len(info["sentences"]) == 3
    session_id = info["id"]
    state = client.get(f"/session/{session_id}/state", headers=auth()).json()
    assert state["status"] in ("idle", "loading", "playing", "finished")
    paused = client.post(f"/session/{session_id}/control", json={"action": "pause"}, headers=auth()).json()
    assert paused["status"] in ("paused", "finished")
    moved = client.post(f"/session/{session_id}/control", json={"action": "goto", "value": 2}, headers=auth()).json()
    assert moved["index"] == 2
    speed = client.post(f"/session/{session_id}/control", json={"action": "speed", "value": 1.5}, headers=auth()).json()
    assert speed["speed"] == 1.5
    assert client.post(f"/session/{session_id}/control", json={"action": "fly"}, headers=auth()).status_code == 400
    assert client.post(f"/session/{session_id}/control", json={"action": "goto"}, headers=auth()).status_code == 400
    current = client.get("/session", headers=auth()).json()
    assert current["id"] == session_id and "state" in current
    assert client.delete(f"/session/{session_id}", headers=auth()).json() == {"ok": True}
    assert client.get("/session", headers=auth()).status_code == 404
    assert client.get(f"/session/{session_id}/state", headers=auth()).status_code == 400


def test_session_requires_source(client):
    assert client.post("/session", json={}, headers=auth()).status_code == 400


def test_events_stream(client):
    info = client.post("/session", json={"text": "Alpha beta. Gamma delta."}, headers=auth()).json()
    kinds = []
    with client.stream("GET", f"/session/{info['id']}/events", headers=auth()) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("data: "):
                payload = json.loads(line[6:])
                kinds.append(payload["kind"])
                if payload["kind"] == "finished":
                    break
    assert kinds[0] == "state" and "finished" in kinds and "word" in kinds


def test_export_endpoint(client, tmp_path):
    out = tmp_path / "x.wav"
    response = client.post("/export", json={"text": "Hello there.", "out": str(out)}, headers=auth())
    assert response.status_code == 200, response.text
    assert out.exists() and response.json()["chapters"] == 1


def test_new_session_replaces_old(client):
    first = client.post("/session", json={"text": "First."}, headers=auth()).json()
    second = client.post("/session", json={"text": "Second."}, headers=auth()).json()
    assert first["id"] != second["id"]
    assert client.get(f"/session/{first['id']}/state", headers=auth()).status_code == 400
    time.sleep(0.05)


def test_token_helpers(tmp_path, monkeypatch):
    monkeypatch.setattr("lisn.server.auth.load_config", lambda: Config())
    saved = {}
    monkeypatch.setattr("lisn.server.auth.save_config", lambda cfg: saved.update(token=cfg.server_token))
    from lisn.server.auth import ensure_token, rotate_token

    config, token = ensure_token()
    assert token and saved["token"] == token
    same_config, same = ensure_token(config)
    assert same == token
    _, rotated = rotate_token(config)
    assert rotated != token


def test_cli_serve_token_flags(monkeypatch):
    from typer.testing import CliRunner

    from lisn import cli

    monkeypatch.setattr(cli, "load_config", lambda: Config(server_token="abc"))
    monkeypatch.setattr("lisn.server.auth.save_config", lambda cfg: None)
    result = CliRunner().invoke(cli.app, ["serve", "--show-token"])
    assert result.exit_code == 0 and "abc" in result.output
    result = CliRunner().invoke(cli.app, ["serve", "--rotate-token"])
    assert result.exit_code == 0 and "New token" in result.output
