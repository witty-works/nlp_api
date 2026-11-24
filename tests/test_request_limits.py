"""How large a request may be: the body as a whole (REQUEST_MAX_BYTES), and
the fields a client sends text or lists in."""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import CHECK_TEXT_MAX_LENGTH, CONFIG_LIST_MAX_LENGTH, CheckRequestIn

LIMIT = 2000


@pytest.fixture
def client(monkeypatch):
    with TestClient(app) as client:
        monkeypatch.setattr(app.state.context.settings, "request_max_bytes", LIMIT)
        yield client


def body(size: int) -> bytes:
    text = "x" * (size - len(json.dumps({"text": ""})))
    encoded = json.dumps({"text": text}).encode()
    assert len(encoded) == size

    return encoded


def test_a_body_within_the_limit_is_read(client):
    response = client.post(
        "/v2.4/check",
        content=body(LIMIT),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 200


def test_a_larger_body_is_refused_by_its_length(client):
    response = client.post(
        "/v2.4/check",
        content=body(LIMIT + 1),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert "REQUEST_MAX_BYTES" in response.json()["detail"]
    # The 413 carries the headers every response does, CORS among them.
    assert "Content-Security-Policy" in response.headers


def test_a_larger_body_is_refused_while_it_streams(client):
    """Chunked: no Content-Length to go by, so it is counted as it arrives."""

    def chunks():
        payload = body(LIMIT * 3)
        for start in range(0, len(payload), 500):
            yield payload[start : start + 500]

    response = client.post(
        "/v2.4/check",
        content=chunks(),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413


def test_a_body_longer_than_it_says_is_refused(client):
    """A Content-Length that understates the body does not get it through."""

    def chunks():
        yield body(LIMIT * 2)

    response = client.post(
        "/v2.4/check",
        content=chunks(),
        headers={"Content-Type": "application/json", "Content-Length": "10"},
    )

    assert response.status_code == 413


def test_the_default_fits_the_largest_guardrail_request():
    from app.settings import Settings

    settings = Settings(_env_file=None)
    # Every character JSON-escaped as \uXXXX, with room for the rest.
    assert settings.request_max_bytes > 6 * settings.guardrail_request_max_length


def test_check_text_is_bounded():
    with TestClient(app) as client:
        response = client.post(
            "/v2.4/check", json={"text": "x" * (CHECK_TEXT_MAX_LENGTH + 1)}
        )

    assert response.status_code == 422


def test_texts_the_server_has_are_not_bounded_by_it():
    """A guardrail answer is checked through CheckRequestIn too, with limits
    of its own (GUARDRAIL_REQUEST_MAX_LENGTH)."""
    CheckRequestIn(text="x" * (CHECK_TEXT_MAX_LENGTH + 1))


def test_config_lists_are_bounded():
    with TestClient(app) as client:
        response = client.post(
            "/v2.4/check",
            json={
                "text": "Hello",
                "config": {"disabled_categories": ["x"] * (CONFIG_LIST_MAX_LENGTH + 1)},
            },
        )
        assert response.status_code == 422

        response = client.post(
            "/v2.4/check",
            json={
                "text": "Hello",
                "config": {"addons": ["x"] * (CONFIG_LIST_MAX_LENGTH + 1)},
            },
        )
        assert response.status_code == 422


@pytest.mark.parametrize("field", ["text", "data"])
def test_languagetool_fields_are_bounded(field):
    from app.routes.lt import LT_DATA_MAX_LENGTH

    limit = CHECK_TEXT_MAX_LENGTH if field == "text" else LT_DATA_MAX_LENGTH
    with TestClient(app) as client:
        response = client.post(
            "/lt/v2/check", data={field: "x" * (limit + 1), "language": "en-US"}
        )

    assert response.status_code == 422
