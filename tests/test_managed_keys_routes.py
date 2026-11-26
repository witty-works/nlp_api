"""The /managed_keys routes (app/routes/managed_keys.py)."""

import pytest
from fastapi.testclient import TestClient

from app import managed_keys
from app.main import app


@pytest.fixture
def client(monkeypatch):
    with TestClient(app) as test_client:
        context = app.state.context
        monkeypatch.setattr(context.settings, "api_key_hmac_key", "a-secret")
        yield test_client
        for pattern in ("managed_key*", "api_key:*"):
            for name in list(context.redis.db.scan_iter(pattern)):
                context.redis.db.delete(name)


def create(client, **body):
    return client.post(
        "/managed_keys",
        json={"email": "jane@acme.example", "team_id": "team-a", "name": "Editor", **body},
    )


def test_create_returns_key_once_and_list_omits_it(client):
    response = create(client, source="dashboard")

    assert response.status_code == 201
    key = response.json()["key"]
    details = response.json()["details"]
    assert details["email"] == "jane@acme.example"
    assert details["team_id"] == "team-a"
    assert details["source"] == "dashboard"
    assert managed_keys.lookup(app.state.context.redis, key).email == "jane@acme.example"

    listed = client.get("/managed_keys", params={"email": "Jane@acme.example"})
    assert listed.status_code == 200
    assert [k["id"] for k in listed.json()] == [details["id"]]
    assert key not in listed.text
    by_team = client.get("/managed_keys", params={"team_id": "team-a"})
    assert key not in by_team.text and len(by_team.json()) == 1


def test_routes_need_management_credentials(client, monkeypatch):
    monkeypatch.setattr(app.state.context.settings, "management_auth_enabled", True)

    assert create(client).status_code == 401
    assert client.get("/managed_keys", params={"email": "a@b.example"}).status_code == 401
    assert client.delete("/managed_keys/x").status_code == 401
    assert client.post("/managed_keys/revoke", json={"email": "a@b.example"}).status_code == 401
    assert client.post("/managed_keys/x/replace", json={"grace_seconds": 0}).status_code == 401


def test_create_refused_without_hmac_secret(client, monkeypatch):
    monkeypatch.setattr(app.state.context.settings, "api_key_hmac_key", "")

    response = create(client)

    assert response.status_code == 409
    assert "API_KEY_HMAC_KEY" in response.text


@pytest.mark.parametrize(
    "body",
    [
        {"email": "not-an-email"},
        {"name": ""},
        {"expires_at": "2000-01-01T00:00:00Z"},
        {"unknown": 1},
    ],
)
def test_create_refuses_bad_input(client, body):
    assert create(client, **body).status_code == 422


def test_list_needs_a_filter(client):
    assert client.get("/managed_keys").status_code == 422
    assert client.post("/managed_keys/revoke", json={}).status_code == 422


def test_revoke_is_idempotent(client):
    details = create(client).json()["details"]

    assert client.delete(f"/managed_keys/{details['id']}").status_code == 204
    assert client.delete(f"/managed_keys/{details['id']}").status_code == 204
    assert client.get("/managed_keys", params={"email": "jane@acme.example"}).json() == []


def test_revoke_by_team(client):
    create(client)
    create(client, team_id="team-b")

    response = client.post("/managed_keys/revoke", json={"team_id": "team-a"})

    assert response.json() == {"count": 1}
    remaining = client.get("/managed_keys", params={"email": "jane@acme.example"}).json()
    assert [k["team_id"] for k in remaining] == ["team-b"]


def test_replace_returns_a_new_key(client):
    first = create(client).json()

    response = client.post(
        f"/managed_keys/{first['details']['id']}/replace", json={"grace_seconds": 0}
    )

    assert response.status_code == 201
    assert response.json()["key"] != first["key"]
    redis = app.state.context.redis
    assert managed_keys.lookup(redis, first["key"]) is None
    assert managed_keys.lookup(redis, response.json()["key"]).email == "jane@acme.example"


def test_replace_refuses_other_grace_periods(client):
    details = create(client).json()["details"]

    response = client.post(f"/managed_keys/{details['id']}/replace", json={"grace_seconds": 5})

    assert response.status_code == 422


def test_replace_missing_key_is_404(client):
    response = client.post("/managed_keys/nope/replace", json={"grace_seconds": 0})

    assert response.status_code == 404


def test_twenty_first_key_is_refused(client):
    for number in range(20):
        assert create(client, name=f"K{number}").status_code == 201

    response = create(client, name="One more")

    assert response.status_code == 409
    assert "at most 20" in response.text
