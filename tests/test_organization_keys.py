"""Organisation configs live under a prefix, so the id a management caller
sends names an organisation and no other Redis key."""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from bin.migrate_organization_keys import migrate

ORG = {
    "id": "org-keys",
    "name": "Org",
    "config": {},
    "false_positives": [],
    "term_replacements": {},
}


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client


@pytest.fixture
def redis(client):
    redis = app.state.context.redis
    yield redis
    for name in (
        "org-keys",
        "api_key:victim-key",
        redis.get_organization_key("org-keys"),
    ):
        redis.db.delete(name)


def test_configs_are_stored_under_the_prefix(client, redis):
    assert client.post("/organization/configs", json=ORG).status_code == 204

    assert redis.db.get(redis.get_organization_key("org-keys"))
    assert redis.db.get("org-keys") is None
    response = client.get(
        "/organization/configs", params={"organization_id": "org-keys"}
    )
    assert response.json()["id"] == "org-keys"

    deleted = client.delete(
        "/organization/configs", params={"organization_id": "org-keys"}
    )
    assert deleted.status_code == 204
    assert redis.db.get(redis.get_organization_key("org-keys")) is None


def test_other_keys_cannot_be_reached(client, redis):
    redis.db.set("api_key:victim-key", "victim@example.org")

    response = client.get(
        "/organization/configs", params={"organization_id": "api_key:victim-key"}
    )
    assert response.status_code == 404

    client.delete(
        "/organization/configs", params={"organization_id": "api_key:victim-key"}
    )
    client.post("/organization/configs", json=ORG | {"id": "api_key:victim-key"})
    assert redis.db.get("api_key:victim-key") == "victim@example.org"
    redis.db.delete(redis.get_organization_key("api_key:victim-key"))


def test_a_config_under_its_bare_id_is_still_read_and_migrated(client, redis):
    redis.db.set("org-keys", json.dumps(ORG))

    response = client.get(
        "/organization/configs", params={"organization_id": "org-keys"}
    )
    assert response.json()["id"] == "org-keys"

    assert migrate(redis, dry_run=True) == (1, 0)
    assert redis.db.get("org-keys")
    assert migrate(redis) == (1, 0)
    assert redis.db.get("org-keys") is None
    assert json.loads(redis.db.get(redis.get_organization_key("org-keys")))["id"] == (
        "org-keys"
    )


def test_a_bare_key_that_is_not_its_config_is_left_alone(client, redis):
    """Only a JSON object naming its own key as id counts as a config."""
    redis.db.set("org-keys", json.dumps(ORG | {"id": "someone-else"}))

    response = client.get(
        "/organization/configs", params={"organization_id": "org-keys"}
    )
    assert response.status_code == 404
    assert migrate(redis) == (0, 0)
    assert redis.db.get("org-keys")
