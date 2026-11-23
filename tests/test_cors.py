"""CORS lets any origin call the API with explicit headers, never with the
browser's own credentials."""

import base64

from fastapi.testclient import TestClient

from app.main import app

ORIGIN = "https://elsewhere.example"


def test_a_cross_origin_request_is_not_allowed_credentials():
    """A page an operator visits must not be able to read the management
    endpoints with the Basic auth their browser has cached."""
    basic = base64.b64encode(b"admin:password").decode()
    with TestClient(app) as client:
        response = client.get(
            "/settings",
            headers={"Origin": ORIGIN, "Authorization": f"Basic {basic}"},
        )

    assert response.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in response.headers


def test_a_preflight_for_the_client_headers_passes():
    """The clients send `x-key` or `Authorization` themselves; a preflight for
    either from another origin is answered."""
    with TestClient(app) as client:
        response = client.options(
            "/v2.4/check",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-key, authorization, content-type",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"
    allowed = response.headers["access-control-allow-headers"].lower()
    assert "x-key" in allowed
    assert "authorization" in allowed
    assert "access-control-allow-credentials" not in response.headers
