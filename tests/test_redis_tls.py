"""How the API connects to a real Redis (REDIS_HOST set)."""

import pytest

from app import redis as redis_module
from app.settings import Settings


@pytest.fixture
def connect(monkeypatch):
    calls = []
    monkeypatch.setattr(
        redis_module, "RedisCache", lambda **kwargs: calls.append(kwargs) or object()
    )

    def made(**settings):
        redis_module.Redis.factory(Settings(redis_host="redis.example", **settings))
        return calls[-1]

    return made


def test_tls_checks_the_servers_certificate(connect):
    """A Redis over TLS whose certificate is not checked can be impersonated
    by anyone on the way, who then reads the keys, emails and configs."""
    kwargs = connect(redis_verify_ssl=True)

    assert kwargs["ssl"] is True
    assert kwargs["ssl_cert_reqs"] == "required"


def test_a_private_ca_can_be_given(connect):
    kwargs = connect(redis_verify_ssl=True, redis_ssl_ca_certs="/run/redis-ca.pem")

    assert kwargs["ssl_ca_certs"] == "/run/redis-ca.pem"


def test_without_tls_nothing_is_checked(connect):
    kwargs = connect(redis_verify_ssl=False)

    assert kwargs["ssl"] is False
