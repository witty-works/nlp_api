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
