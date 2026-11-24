"""What stops the start: configurations that would serve with a hole in them."""

import logging
from types import SimpleNamespace

import fakeredis
import pytest

from app.redis import Redis
from app.settings import Settings
from app.startup import check_api_key_storage

KEY = "a-plaintext-key-0123456789"


def context_with(keys: dict, **settings) -> SimpleNamespace:
    # pytest.ini sets ENVIRONMENT_TYPE=development for the suite.
    settings = Settings(
        _env_file=None, **({"environment_type": "production"} | settings)
    )
    settings.is_prod = settings.environment_type == "production"
    redis = Redis(settings, fakeredis.FakeStrictRedis(decode_responses=True))
    for name, email in keys.items():
        redis.db.set(name, email)

    return SimpleNamespace(
        settings=settings, redis=redis, logger=logging.getLogger("test_startup")
    )


def test_plaintext_keys_stop_a_production_start():
    context = context_with({"api_key:" + KEY: "jane@example.org"})

    with pytest.raises(RuntimeError, match="API_KEY_HMAC_KEY") as error:
        check_api_key_storage(context)
    assert KEY not in str(error.value)
    assert "rehash" in str(error.value)


def test_plaintext_keys_are_a_warning_in_development(caplog):
    context = context_with(
        {"api_key:" + KEY: "jane@example.org"}, environment_type="development"
    )

    check_api_key_storage(context)

    assert "API_KEY_HMAC_KEY is not set" in caplog.text
    assert KEY not in caplog.text


def test_require_api_key_without_a_secret_is_a_warning(caplog):
    context = context_with({}, require_api_key=True)

    check_api_key_storage(context)

    assert "API_KEY_HMAC_KEY is not set" in caplog.text


@pytest.mark.parametrize(
    "keys,hmac_key",
    [
        # No keys at all.
        ({}, ""),
        # Only digests.
        ({"api_key:" + "a" * 64: "jane@example.org"}, ""),
        # Plaintext ones, but a secret to rehash them with.
        ({"api_key:" + KEY: "jane@example.org"}, "a-secret"),
    ],
)
def test_production_starts_without_plaintext_keys(keys, hmac_key, caplog):
    check_api_key_storage(context_with(keys, api_key_hmac_key=hmac_key))

    assert "API_KEY_HMAC_KEY" not in caplog.text
