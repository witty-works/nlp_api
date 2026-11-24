"""Office SSO (the Word plugin): Entra tokens from any tenant are verified
against Microsoft's common keys, so the email they carry is only trusted when
the tenant verified the email's domain (`xms_edov`); otherwise a user of a
tenant someone controls could name themselves after any address ("nOAuth")."""

import jwt
import pytest
import redis
from fastapi.testclient import TestClient

from app.auth_service import AuthError
from app.main import app
from tests.test_api import context, set_redis  # noqa: F401  (fixtures)

TENANT = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def office(monkeypatch):
    """The office_sso issuer configured, and its signature check replaced:
    these tests are about the claims, not the keys."""
    monkeypatch.setitem(
        context.settings.sso_configs,
        "office_sso",
        {"client_id": "office-client", "expected_scope": None},
    )
    verified = {}

    async def decode_jwt(redis, session, request, tenant_id, client_id, scope):
        return verified["claims"]

    monkeypatch.setattr("app.auth_service.decode_jwt", decode_jwt)

    def token(**claims) -> str:
        claims = {"aud": "office-client", "tid": TENANT, **claims}
        verified["claims"] = claims
        return jwt.encode(claims, "not-checked-here", algorithm="HS256")

    return token


def auth(token: str):
    with TestClient(app) as client:
        return client.post(
            "/v2.0/auth", json={}, headers={"Authorization": "Bearer " + token}
        )


def test_a_verified_email_domain_is_let_in(office, set_redis):  # noqa: F811
    response = auth(office(email="test@gmail.com", xms_edov=True))
    assert response.status_code == 200


@pytest.mark.parametrize(
    "claims",
    [
        {"email": "test@gmail.com"},
        {"email": "test@gmail.com", "xms_edov": False},
        {"preferred_username": "test@gmail.com", "xms_edov": True},
    ],
    ids=["no xms_edov", "xms_edov false", "preferred_username only"],
)
def test_an_unverified_email_is_not_let_in(office, set_redis, claims):  # noqa: F811
    response = auth(office(**claims))
    assert response.status_code == 403


def test_a_store_outage_is_not_a_refused_token(
    office, set_redis, monkeypatch  # noqa: F811
):
    """Redis failing while the token is verified says nothing about the
    token: a 401 would make the client throw a good token away."""
    token = office(email="test@gmail.com", xms_edov=True)

    async def decode_jwt(*args):
        raise redis.exceptions.ConnectionError("connection refused")

    monkeypatch.setattr("app.auth_service.decode_jwt", decode_jwt)
    response = auth(token)
    assert response.status_code == 503
    assert response.headers["retry-after"] == "10"
    assert "connection refused" not in response.text


def test_unfetchable_issuer_keys_say_when_to_retry(
    office, set_redis, monkeypatch  # noqa: F811
):
    token = office(email="test@gmail.com", xms_edov=True)

    async def decode_jwt(*args):
        raise AuthError("Timeout while fetching RSA keys from issuer", 503)

    monkeypatch.setattr("app.auth_service.decode_jwt", decode_jwt)
    response = auth(token)
    assert response.status_code == 503
    assert response.headers["retry-after"] == "10"
