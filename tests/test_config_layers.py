"""The order a request's config is built in (fetch_configs_for_request), and
that every layer is validated as it is applied."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.api_keys import KEY_CONFIGS, SYNCED_KEYS, ApiKeyEntry, sync
from app.config_manager import fetch_configs_for_request, parse_default_config
from app.main import app
from app.models import CheckRequestIn
from tests.test_api import set_redis  # noqa: F401  (fixture)

EMAIL = "layers@example.org"
KEY = "layers-key-0123456789abcdef"


@pytest.fixture
def context(set_redis, monkeypatch):  # noqa: F811
    with TestClient(app):
        context = app.state.context
        # DEFAULT_CONFIG is skipped while testing, so snapshots don't depend on
        # a local .env; these tests set it explicitly.
        monkeypatch.setattr(context.settings, "testing", False)
        monkeypatch.setattr(context.settings, "default_config", "")
        monkeypatch.setattr(context.settings, "client_config_enabled", False)
        yield context
        db = context.redis.db
        for name in db.smembers(SYNCED_KEYS):
            db.delete(name)
        db.delete(SYNCED_KEYS, KEY_CONFIGS)


def resolve(context, request_config=None, default_config="", key_config=None):
    context.settings.default_config = default_config
    sync(
        context.redis,
        [ApiKeyEntry(email=EMAIL, key=KEY, **(key_config or {}))],
    )
    request_in = CheckRequestIn(text="Hallo", config=request_config or {})
    asyncio.run(fetch_configs_for_request(request_in, EMAIL, context))

    return request_in.config


@pytest.mark.parametrize(
    "request_config,default_config,key_config,expected",
    [
        # Nothing set: the built-in default.
        ({}, "", None, "*in"),
        # DEFAULT_CONFIG fills in what the request did not send ...
        ({}, '{"german_gender_ending": ":in"}', None, ":in"),
        # ... and the request's own choice wins over it.
        (
            {"german_gender_ending": "/in"},
            '{"german_gender_ending": ":in"}',
            None,
            "/in",
        ),
        # A key's config takes the place of DEFAULT_CONFIG ...
        (
            {},
            '{"german_gender_ending": ":in"}',
            {"config": {"german_gender_ending": "_in"}},
            "_in",
        ),
        # ... and the request's own choice wins over it too.
        (
            {"german_gender_ending": "/in"},
            "",
            {"config": {"german_gender_ending": "_in"}},
            "/in",
        ),
        # A force wins over everything.
        (
            {"german_gender_ending": "/in"},
            '{"german_gender_ending": ":in"}',
            {"force": {"german_gender_ending": "()"}},
            "()",
        ),
    ],
)
def test_the_layers_apply_in_order(
    context, request_config, default_config, key_config, expected
):
    config = resolve(context, request_config, default_config, key_config)

    assert config.german_gender_ending == expected


def test_a_keys_flag_is_not_undone_by_a_client_that_may_not_set_it(context):
    """Without CLIENT_CONFIG_ENABLED the client's store_context is ignored, so
    the key's own setting has to apply, not be skipped because the client sent
    one."""
    config = resolve(
        context,
        request_config={"store_context": True},
        key_config={"config": {"store_context": False}},
    )

    assert config.store_context is False


def test_defaults_are_validated_as_they_are_applied(context):
    config = resolve(context, default_config='{"preferred_variants": "de-CH"}')

    # A string where a list is expected is normalised, not kept as a string
    # to be iterated character by character.
    assert config.preferred_variants == ["de-CH"]


@pytest.mark.parametrize(
    "default_config,message",
    [
        ("{nope", "not valid JSON"),
        ("[]", "must be a JSON object"),
        ('{"gender_ending": ":in"}', "no such config option"),
        ('{"german_gender_ending": "star"}', "german_gender_ending"),
    ],
)
def test_a_broken_default_config_is_refused_up_front(default_config, message):
    with pytest.raises(ValueError, match=message):
        parse_default_config(default_config)
