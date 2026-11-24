"""`confirm_before_checking`: clients ask before sending a field's text. The
API carries it like `store_context`: a suggestion by default, forced where an
organisation's or user's synced config or an API key forces it. It does not
enforce it; it cannot know about fields."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.api_keys import KEY_CONFIGS, SYNCED_KEYS, ApiKeyEntry, sync
from app.config_manager import fetch_configs_for_request
from app.main import app
from app.models import CheckRequestIn

EMAIL = "confirm@example.org"
ORG_ID = "confirm-org"
KEY = "confirm-key-0123456789abcdef"

# What the dashboard syncs: the organisation setting on, and off.
FORCED_ON = {"value": True, "status": "force"}
SUGGESTED_OFF = {"value": False, "status": "suggestion"}


def organisation(setting: dict) -> dict:
    return {
        "id": ORG_ID,
        "name": "Confirm Org",
        "config": {"confirm_before_checking": setting},
        "false_positives": [],
        "term_replacements": {},
    }


def user() -> dict:
    return {
        "id": "confirm-user",
        "email": EMAIL,
        "name": "Confirm User",
        "organization_id": ORG_ID,
        "config": {},
        "false_positives": [],
        "term_replacements": {},
    }


@pytest.fixture
def client():
    with TestClient(app) as client:
        assert client.post("/user/configs", json=user()).status_code == 204
        yield client
        client.delete("/user/configs", params={"email": EMAIL})
        client.delete("/organization/configs", params={"organization_id": ORG_ID})
        db = app.state.context.redis.db
        for name in db.smembers(SYNCED_KEYS):
            db.delete(name)
        db.delete(SYNCED_KEYS, KEY_CONFIGS)


def resolve(request_config: dict) -> bool:
    request_in = CheckRequestIn(text="Hallo", config=request_config)
    asyncio.run(fetch_configs_for_request(request_in, EMAIL, app.state.context))

    return request_in.config.confirm_before_checking


@pytest.mark.parametrize("setting", [FORCED_ON, SUGGESTED_OFF])
def test_the_dashboard_sync_is_accepted_and_passed_on(client, setting):
    response = client.post("/organization/configs", json=organisation(setting))
    assert response.status_code == 204

    auth = client.post("/v2.0/auth", headers={"X-TESTING-AUTH": EMAIL})
    assert auth.status_code == 200
    assert auth.json()["organization_config"]["confirm_before_checking"] == setting


def test_a_forced_setting_overrules_the_client(client):
    client.post("/organization/configs", json=organisation(FORCED_ON))

    assert resolve({"confirm_before_checking": False}) is True
    assert resolve({}) is True


def test_a_user_may_turn_it_on_where_it_is_not_forced(client):
    """Whether or not CLIENT_CONFIG_ENABLED lets clients set store_context."""
    client.post("/organization/configs", json=organisation(SUGGESTED_OFF))

    assert resolve({"confirm_before_checking": True}) is True
    assert resolve({}) is False


def test_an_api_key_can_force_it(client, monkeypatch):
    context = app.state.context
    monkeypatch.setattr(context.settings, "testing", False)
    sync(
        context.redis,
        [
            ApiKeyEntry(
                email="keyed@example.org",
                key=KEY,
                force={"confirm_before_checking": True},
            )
        ],
    )

    auth = client.post("/v2.0/auth", headers={"x-key": KEY})
    assert auth.status_code == 200
    assert auth.json()["config"]["confirm_before_checking"] == FORCED_ON


def test_the_default_user_gets_the_deployment_default(client, monkeypatch):
    context = app.state.context
    monkeypatch.setattr(context.settings, "default_user_config_enabled", True)
    monkeypatch.setattr(context.settings, "default_user_confirm_before_checking", True)

    auth = client.post("/v2.0/auth", headers={"X-TESTING-AUTH": "nobody@example.org"})
    assert auth.status_code == 200
    assert auth.json()["config"]["confirm_before_checking"] == {
        "value": True,
        "status": "suggestion",
    }


def test_it_is_part_of_the_documented_models(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]

    assert "confirm_before_checking" in schemas["Config"]["properties"]
    assert "confirm_before_checking" in schemas["RuleConfig"]["properties"]
