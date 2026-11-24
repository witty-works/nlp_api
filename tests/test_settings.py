import json
import re

import pytest

from app.settings import DEBUG_SETTINGS, Settings, public_url


@pytest.fixture
def no_environment(monkeypatch):
    for name in ("ENVIRONMENT_TYPE", "ENVIRONMENT"):
        monkeypatch.delenv(name, raising=False)

    return monkeypatch


def test_environment_defaults(no_environment):
    settings = Settings(_env_file=None)
    # An image run without configuration serves no development routes.
    assert settings.environment_type == "production"
    assert settings.environment == "local"


def test_environment_from_the_environment(no_environment):
    no_environment.setenv("ENVIRONMENT_TYPE", "production")
    no_environment.setenv("ENVIRONMENT", "bfh")

    settings = Settings(_env_file=None)
    assert settings.environment_type == "production"
    assert settings.environment == "bfh"


@pytest.mark.parametrize(
    "key", ["change-me", "REPLACE-ME", "x" * 19, "spaces are not allowed in keys"]
)
def test_an_unusable_default_api_key_stops_the_start(monkeypatch, key):
    """Written to Redis on every start, so a placeholder would be a working,
    guessable key. The message says why, without the key."""
    monkeypatch.setenv("DEFAULT_API_KEY", key)

    with pytest.raises(ValueError, match="DEFAULT_API_KEY is not a usable key") as e:
        Settings.factory()
    assert key not in str(e.value)


@pytest.mark.parametrize("key", ["", "x" * 20, "a-B_9" * 8])
def test_a_usable_or_no_default_api_key_starts(monkeypatch, key):
    monkeypatch.setenv("DEFAULT_API_KEY", key)

    assert Settings.factory().default_api_key == key


def test_the_shipped_example_key_is_refused(monkeypatch):
    """.env.example ships a placeholder that has to be replaced."""
    with open(".env.example") as file:
        values = [
            line.split("=", 1)[1].strip()
            for line in file
            if line.startswith("DEFAULT_API_KEY=")
        ]
    assert values
    for value in values:
        monkeypatch.setenv("DEFAULT_API_KEY", value)
        with pytest.raises(ValueError, match="DEFAULT_API_KEY"):
            Settings.factory()


SECRET_NAME = re.compile(r"key|secret|password|token|dsn", re.IGNORECASE)
# Names the pattern catches that hold no secret: whether a key is required.
NOT_SECRET = {"require_api_key"}


def secret_names(names) -> list[str]:
    return [n for n in names if SECRET_NAME.search(n) and n not in NOT_SECRET]


def test_debug_settings_name_no_secret():
    """The allow-list is the only thing that decides what GET /settings shows,
    so a setting whose name says it is secret must never be on it."""
    assert not secret_names(DEBUG_SETTINGS)
    # A misspelt name would fail on every request rather than here.
    assert set(DEBUG_SETTINGS) <= set(Settings.model_fields)


def test_debug_view_leaves_out_secrets(monkeypatch):
    for name, value in {
        "LLM_API_KEY": "llm-secret",
        "AWS_SECRET_KEY": "aws-secret",
        "API_KEY_HMAC_KEY": "hmac-secret",
        "REDIS_PASSWORD": "redis-secret",
        "SLACK_BOT_TOKEN": "slack-secret",
        "SENTRY_DSN": "https://dsn-secret@sentry.example/1",
        "CONTEXT_CHECKER": '{"en": {"url": "https://cc.example", "api_key": "cc-secret"}}',
        "LANGUAGETOOL_API": "https://lt-user:lt-secret@lt.example:8010/v2?key=q-secret",
        "LLM_API_BASE": "https://llm.example/v1#frag-secret",
    }.items():
        monkeypatch.setenv(name, value)

    view = Settings(_env_file=None).debug_view()

    assert not secret_names(view)
    assert "secret" not in json.dumps(view, default=str)
    assert view["languagetool_api"] == "https://lt.example:8010/v2"
    assert view["llm_api_base"] == "https://llm.example/v1"
    assert view["context_checker"] == ["en"]


@pytest.mark.parametrize(
    "url,expected",
    [
        ("redis://user:pass@redis.example:6379/0", "redis://redis.example:6379/0"),
        ("http://[::1]:8010/v2", "http://[::1]:8010/v2"),
        ("https://example.org", "https://example.org"),
        ("", ""),
        (None, None),
        ("http://example.org:notaport/", "(not a URL)"),
    ],
)
def test_public_url(url, expected):
    assert public_url(url) == expected


def test_no_languagetool_unless_named(monkeypatch):
    """Text goes to no third party a deployment did not name."""
    monkeypatch.delenv("LANGUAGETOOL_API", raising=False)

    assert Settings(_env_file=None).languagetool_api == ""


@pytest.mark.parametrize(
    "name,value,message",
    [
        ("TESTING", "true", "TESTING is on in production"),
        ("MANAGEMENT_AUTH_ENABLED", "false", "MANAGEMENT_AUTH_ENABLED is off"),
    ],
)
def test_test_switches_stop_a_production_start(monkeypatch, name, value, message):
    monkeypatch.setenv("ENVIRONMENT_TYPE", "production")
    monkeypatch.setenv("TESTING", "false")
    monkeypatch.setenv("MANAGEMENT_AUTH_ENABLED", "true")
    Settings.factory()

    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=message):
        Settings.factory()

    # Outside production they are what the test suite runs with.
    monkeypatch.setenv("ENVIRONMENT_TYPE", "development")
    Settings.factory()


def test_a_dashboard_issuer_is_required(monkeypatch):
    monkeypatch.setenv("DASHBOARD_CLIENT_ID", "1")
    monkeypatch.setenv("DASHBOARD_URL", "https://dashboard.example.com")
    monkeypatch.delenv("DASHBOARD_ISSUER", raising=False)

    with pytest.raises(ValueError, match="DASHBOARD_ISSUER"):
        Settings.factory()

    monkeypatch.setenv("DASHBOARD_ISSUER", "https://dashboard.example.com")
    issuer = Settings.factory().sso_configs["dashboard"]["issuer"]
    assert issuer == "https://dashboard.example.com"


def test_several_dashboard_client_ids(monkeypatch):
    """The extension and the dashboard's write page are two clients of one
    dashboard; the API accepts the tokens of both."""
    monkeypatch.setenv("DASHBOARD_CLIENT_ID", "1, 2")
    monkeypatch.setenv("DASHBOARD_URL", "https://dashboard.example.com")
    monkeypatch.setenv("DASHBOARD_ISSUER", "https://dashboard.example.com")
    configs = Settings.factory().sso_configs
    assert configs["dashboard"]["client_id"] == "1"
    assert configs["dashboard:2"]["client_id"] == "2"
    assert configs["dashboard:2"]["issuer"] == configs["dashboard"]["issuer"]
    assert configs["dashboard:2"]["jwks_url"] == configs["dashboard"]["jwks_url"]


def test_one_dashboard_client_id_as_before(monkeypatch):
    monkeypatch.setenv("DASHBOARD_CLIENT_ID", "1")
    monkeypatch.setenv("DASHBOARD_URL", "https://dashboard.example.com")
    monkeypatch.setenv("DASHBOARD_ISSUER", "https://dashboard.example.com")
    configs = Settings.factory().sso_configs
    assert [name for name in configs if name.startswith("dashboard")] == ["dashboard"]
