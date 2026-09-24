"""Minimum client versions, and the responses clients rely on to tell a
rejected version and an unsupported language apart from other errors."""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.models import Client, Result
from app.settings import Settings
from app.version_validators import client_version
from tests.test_api import set_redis  # noqa: F401  (fixture)

MINIMUMS = {"web-ext": "1.30.1", "witty-editor": "2.4.0"}


@pytest.mark.parametrize(
    "client",
    [
        "witty-editor:2.4.0",
        "witty-editor:2.10.0",
        "web-ext:1.30.1",
        "word-plugin:0.1.0",  # no minimum set for it
        None,  # no client string at all
    ],
)
def test_clients_at_or_above_their_minimum_pass(client):
    client_version(Client.parse(client), MINIMUMS)


@pytest.mark.parametrize(
    "client", ["witty-editor:2.3.9", "web-ext:1.30.0", "1.29.0", "witty-editor:"]
)
def test_clients_below_their_minimum_are_rejected(client):
    with pytest.raises(HTTPException) as raised:
        client_version(Client.parse(client), MINIMUMS)

    assert raised.value.status_code == 400
    assert "please use at least" in raised.value.detail


def test_nothing_is_rejected_without_minimums():
    client_version(Client.parse("witty-editor:0.0.1"), {})


def test_each_client_has_its_own_setting(monkeypatch):
    monkeypatch.setenv("MINIMUM_VERSION_WEB_EXT", "1.30.1")
    monkeypatch.setenv("MINIMUM_VERSION_WORD_PLUGIN", "2.0.0")
    monkeypatch.setenv("MINIMUM_VERSION_WITTY_EDITOR", "2.4.0")

    assert Settings.factory().minimum_versions == {
        "web-ext": "1.30.1",
        "word-plugin": "2.0.0",
        "witty-editor": "2.4.0",
    }


def test_the_check_rejects_an_old_editor(set_redis, monkeypatch):  # noqa: F811
    def check(client):
        return test_client.post(
            "/v2.4/check",
            json={"text": "Hallo", "lang": "de", "client": client},
            headers={"X-TESTING-AUTH": "default@gmail.com"},
        )

    with TestClient(app) as test_client:
        settings = app.state.context.settings
        monkeypatch.setattr(settings, "minimum_versions", MINIMUMS)

        old = check("witty-editor:2.3.0")
        assert old.status_code == 400
        assert old.json()["detail"] == (
            "Client version '2.3.0' not supported, please use at least '2.4.0'."
        )
        assert check("witty-editor:2.4.0").status_code == 200
        assert check(None).status_code == 200


def test_the_unsupported_language_type_is_stable():
    """Clients match this type to tell the 422 for an unsupported language
    from FastAPI's validation errors."""
    assert Result.factory("Language not supported").detail[0]["type"] == (
        "value_error.not_supported"
    )
