"""Requests with a managed key: its team decides the organisation, and it only
works while the person's synced user config lists that team."""

import json

import pytest
from fastapi.testclient import TestClient

from app import managed_keys
from app.main import app
from app.request_team import key_team

EMAIL = "jane@acme.example"


@pytest.fixture
def client(monkeypatch):
    with TestClient(app) as test_client:
        context = app.state.context
        monkeypatch.setattr(context.settings, "api_key_hmac_key", "a-secret")
        for team, name in (("team-a", "Team A"), ("team-b", "Team B")):
            test_client.post(
                "/organization/configs",
                json={"id": team, "name": name, "config": {}},
            )
        yield test_client
        db = context.redis.db
        for pattern in ("managed_key*", "dashboard-organization:team-*"):
            for name in list(db.scan_iter(pattern)):
                db.delete(name)
        db.delete(context.redis.get_user_id(EMAIL))
        key_team.set(None)


def sync_user(client, teams=None, organization_id="team-a"):
    body = {"id": "jane", "name": "Jane", "email": EMAIL, "config": {}, "organization_id": organization_id, "team_analytics": True}
    if teams is not None:
        body["teams"] = teams
    assert client.post("/user/configs", json=body).status_code == 204


def mint(team_id):
    key, _ = managed_keys.mint(app.state.context.redis, EMAIL, team_id, "Editor", "dashboard", None)
    return key


def auth(client, key):
    return client.post("/v2.0/auth", headers={"x-key": key})


def test_team_key_uses_its_team_settings(client):
    sync_user(client, teams=["team-a", "team-b"])

    response = auth(client, mint("team-b"))

    assert response.status_code == 200
    assert response.json()["organization_id"] == "team-b"
    assert response.json()["organization_name"] == "Team B"


def test_team_key_refused_when_user_left_team(client):
    sync_user(client, teams=["team-a"])

    assert auth(client, mint("team-b")).status_code == 401


def test_team_key_refused_without_synced_teams(client):
    sync_user(client, teams=None)
    team_key = mint("team-a")
    plain_key = "plain-key-for-jane-0123456789"
    app.state.context.redis.set_api_key(plain_key, EMAIL)

    assert auth(client, team_key).status_code == 401
    assert auth(client, plain_key).status_code == 200


def test_team_key_refused_without_any_user_config(client):
    assert auth(client, mint("team-a")).status_code == 401


def test_teamless_managed_key_keeps_the_licence_team(client):
    sync_user(client, teams=["team-a", "team-b"], organization_id="team-a")

    response = auth(client, mint(None))

    assert response.json()["organization_id"] == "team-a"


def test_oauth_style_requests_keep_the_licence_team(client):
    sync_user(client, teams=["team-a", "team-b"], organization_id="team-a")
    plain_key = "plain-key-for-jane-0123456789"
    app.state.context.redis.set_api_key(plain_key, EMAIL)

    assert auth(client, plain_key).json()["organization_id"] == "team-a"


def test_revoked_key_no_longer_works(client):
    sync_user(client, teams=["team-a"])
    key, details = managed_keys.mint(app.state.context.redis, EMAIL, "team-a", "E", "dashboard", None)
    assert auth(client, key).status_code == 200

    managed_keys.revoke(app.state.context.redis, details.id)

    assert auth(client, key).status_code == 401


def test_stored_teams_survive_the_user_config_round_trip(client):
    sync_user(client, teams=["team-a"])

    stored = json.loads(app.state.context.redis.db.get(app.state.context.redis.get_user_id(EMAIL)))

    assert stored["teams"] == ["team-a"]
