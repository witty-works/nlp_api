import base64
import json

import pytest

from app.settings import Settings, apply_platform_relationships


@pytest.fixture
def no_environment(monkeypatch):
    for name in (
        "ENVIRONMENT_TYPE",
        "PLATFORM_ENVIRONMENT_TYPE",
        "ENVIRONMENT",
        "PLATFORM_ENVIRONMENT",
    ):
        monkeypatch.delenv(name, raising=False)

    return monkeypatch


def test_environment_defaults(no_environment):
    settings = Settings(_env_file=None)
    assert settings.environment_type == "development"
    assert settings.environment == "local"


@pytest.mark.parametrize("name", ["ENVIRONMENT_TYPE", "PLATFORM_ENVIRONMENT_TYPE"])
def test_environment_type_from_either_name(no_environment, name):
    """The plain name for any host, the PLATFORM_ one that Upsun sets."""
    no_environment.setenv(name, "production")
    assert Settings(_env_file=None).environment_type == "production"


def test_plain_names_win_over_platform_ones(no_environment):
    no_environment.setenv("PLATFORM_ENVIRONMENT_TYPE", "development")
    no_environment.setenv("ENVIRONMENT_TYPE", "production")
    no_environment.setenv("PLATFORM_ENVIRONMENT", "main")
    no_environment.setenv("ENVIRONMENT", "bfh")

    settings = Settings(_env_file=None)
    assert settings.environment_type == "production"
    assert settings.environment == "bfh"


def test_platform_relationships_point_at_the_services():
    """What .upsun/config.yaml's relationships produce, without the
    platformshconfig package."""
    relationships = {
        "rediscache": [{"scheme": "redis", "host": "rediscache.internal", "port": 6379}],
        "languagetool": [
            {"scheme": "http", "host": "languagetool.internal", "port": 80}
        ],
    }
    settings = Settings(_env_file=None)
    settings.platform_relationships = base64.b64encode(
        json.dumps(relationships).encode()
    ).decode()

    apply_platform_relationships(settings)

    assert settings.redis_host == "rediscache.internal"
    assert settings.redis_port == 6379
    assert settings.redis_verify_ssl is False
    assert settings.languagetool_api == "http://languagetool.internal:80/v2"
    assert settings.languagetool_verify_ssl is False
