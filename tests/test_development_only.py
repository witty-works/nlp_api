"""The development helpers answer 404 in production and work elsewhere."""

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.dependencies import development_only, fetch_current_username
from app.main import app, context
from app.middleware import _depends_on
from app.route_table import registered_routes

# Every route behind API_DOCS_AUTH_ENABLED except the docs UI, with a request
# that the route answers when it is reachable.
HELPERS = [
    ("POST", "/debug/check", {"json": {"text": "Hello", "lang": "en"}}),
    (
        "POST",
        "/debug/rule",
        {
            "json": {
                "text": "Hello",
                "lang": "en",
                "lemma": "hello",
                "subcategories": [],
                "word_types": [
                    {"word_type": "", "lower_case": True, "lemmatize": True}
                ],
            }
        },
    ),
    ("GET", "/debug/spacy", {"params": {"text": "Hello", "lang": "en"}}),
    ("GET", "/debug/displacy", {"params": {"text": "Hello", "lang": "en"}}),
    ("GET", "/debug/german_noun", {"params": {"word": "Kunde"}}),
    ("GET", "/lemmatize", {"params": {"text": "running", "lang": "en"}}),
    ("GET", "/tokenize", {"params": {"text": "running", "lang": "en"}}),
    (
        "GET",
        "/parse-word-types",
        {"params": {"text": "running", "lang": "en", "word_types": "v"}},
    ),
    ("GET", "/save_openapi_json", {}),
]


@pytest.mark.parametrize("method,path,kwargs", HELPERS, ids=[h[1] for h in HELPERS])
def test_development_helper_is_not_found_in_production(
    method, path, kwargs, monkeypatch
):
    with TestClient(app) as client:
        monkeypatch.setattr(context.settings, "is_prod", True)
        response = client.request(method, path, **kwargs)

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


@pytest.mark.parametrize("method,path,kwargs", HELPERS, ids=[h[1] for h in HELPERS])
def test_development_helper_is_reachable_outside_production(
    method, path, kwargs, monkeypatch, tmp_path
):
    with TestClient(app) as client:
        monkeypatch.setattr(context.settings, "is_prod", False)
        # /save_openapi_json writes openapi.json into the working directory;
        # after startup, which reads the database from the checkout.
        monkeypatch.chdir(tmp_path)
        response = client.request(method, path, **kwargs)

    assert response.status_code == 200, response.text


def test_debug_rephrase_is_gone():
    """It took a per-request `model` that sent the deployment's LLM key to it."""
    with TestClient(app) as client:
        response = client.post("/debug/rephrase", json={})

    assert response.status_code == 404


def test_every_docs_auth_route_but_the_docs_is_development_only():
    """A helper added later behind API_DOCS_AUTH_ENABLED is closed in
    production too, or this names it."""
    routes = [
        (prefix + route.path, route)
        for prefix, route in registered_routes(app)
        if isinstance(route, APIRoute)
    ]
    guarded = {
        path
        for path, route in routes
        if _depends_on(route.dependant, fetch_current_username)
    }
    hidden = {
        path for path, route in routes if _depends_on(route.dependant, development_only)
    }

    assert guarded - hidden == {"/docs"}
    assert hidden == {path for _, path, _ in HELPERS}
