import pytest

from app.settings import Settings


@pytest.fixture
def no_environment(monkeypatch):
    for name in ("ENVIRONMENT_TYPE", "ENVIRONMENT"):
        monkeypatch.delenv(name, raising=False)

    return monkeypatch


def test_environment_defaults(no_environment):
    settings = Settings(_env_file=None)
    assert settings.environment_type == "development"
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
