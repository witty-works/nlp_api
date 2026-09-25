"""Tests for the LanguageTool-compatible API under /lt/v2."""

import json

from fastapi.testclient import TestClient

from app.main import app
from app.routes.lt import resolve_lang, text_from_data
from app.models import LangWithAutoType

from tests.test_api import set_redis  # noqa: F401  (pytest fixture)

AUTH = {"X-TESTING-AUTH": "default@gmail.com"}


def test_lt_languages():
    with TestClient(app) as client:
        response = client.get("/lt/v2/languages")

        assert response.status_code == 200
        languages = response.json()
        assert {"name": "English (US)", "code": "en", "longCode": "en-US"} in languages
        assert {
            "name": "German (Germany)",
            "code": "de",
            "longCode": "de-DE",
        } in languages


def test_lt_check_english(set_redis):  # noqa: F811
    with TestClient(app) as client:
        response = client.post(
            "/lt/v2/check",
            data={"text": "Hello guys", "language": "en-US"},
            headers=AUTH,
        )

        assert response.status_code == 200
        content = response.json()

        assert content["software"]["name"] == "Witty NLP API"
        assert content["language"]["code"] == "en-US"
        assert content["language"]["detectedLanguage"]["code"] == "en-US"
        assert content["warnings"]["incompleteResults"] is False

        assert len(content["matches"]) > 0
        match = content["matches"][0]
        assert match["offset"] == 6
        assert match["length"] == 4
        assert len(match["replacements"]) > 0
        assert match["rule"]["id"].startswith("WITTY_")
        assert match["rule"]["issueType"] == "style"
        assert match["context"]["text"] == "Hello guys"
        assert match["context"]["offset"] == 6
        assert match["context"]["length"] == 4
        assert match["sentence"] == "Hello guys"

        assert content["sentenceRanges"] == [[0, 10]]
        assert content["extendedSentenceRanges"] == [
            {
                "from": 0,
                "to": 10,
                "detectedLanguages": [{"language": "en-US", "rate": 1.0}],
            }
        ]


def test_lt_check_auto_language(set_redis):  # noqa: F811
    with TestClient(app) as client:
        response = client.post(
            "/lt/v2/check",
            data={"text": "Hallo, wir suchen einen Programmierer.", "language": "auto"},
            headers=AUTH,
        )

        assert response.status_code == 200
        content = response.json()
        assert content["language"]["code"] == "de-DE"


def test_lt_check_data_markup(set_redis):  # noqa: F811
    data = {
        "annotation": [
            {"text": "Hello "},
            {"markup": "<b>"},
            {"text": "guys"},
            {"markup": "</b>"},
        ]
    }

    with TestClient(app) as client:
        # An empty `text` field alongside `data` must not shadow it;
        # clients are seen sending both.
        response = client.post(
            "/lt/v2/check",
            data={"text": "", "data": json.dumps(data), "language": "en-US"},
            headers=AUTH,
        )

        assert response.status_code == 200
        content = response.json()
        assert len(content["matches"]) > 0

        # Offsets must point into the original data stream: "Hello " (6)
        # plus "<b>" (3) puts "guys" at offset 9.
        match = content["matches"][0]
        assert match["offset"] == 9
        assert match["length"] == 4


def test_lt_check_api_key(set_redis):  # noqa: F811
    """The LanguageTool protocol carries the API key as a form field."""
    from app.main import context

    context.redis.db.set("api_key:test-lt-key", "default@gmail.com")

    with TestClient(app) as client:
        response = client.post(
            "/lt/v2/check",
            data={
                "text": "Hello guys",
                "language": "en-US",
                "username": "default@gmail.com",
                "apiKey": "test-lt-key",
            },
        )

        assert response.status_code == 200
        assert len(response.json()["matches"]) > 0


def test_lt_check_invalid_api_key(set_redis):  # noqa: F811
    with TestClient(app) as client:
        response = client.post(
            "/lt/v2/check",
            data={
                "text": "Hello guys",
                "language": "en-US",
                "username": "default@gmail.com",
                "apiKey": "no-such-key",
            },
        )

        assert response.status_code == 401
        assert "AuthException" in response.text


def test_lt_check_password_login_unsupported(set_redis):  # noqa: F811
    with TestClient(app) as client:
        response = client.post(
            "/lt/v2/check",
            data={
                "text": "Hello guys",
                "language": "en-US",
                "username": "default@gmail.com",
                "password": "hunter2",
            },
        )

        assert response.status_code == 401
        assert "apiKey" in response.text


def test_lt_check_unauthenticated_returns_empty(set_redis):  # noqa: F811
    with TestClient(app) as client:
        response = client.post(
            "/lt/v2/check",
            data={"text": "Hello guys", "language": "en-US"},
        )

        assert response.status_code == 200
        assert response.json()["matches"] == []


def test_lt_check_unknown_language():
    with TestClient(app) as client:
        response = client.post(
            "/lt/v2/check",
            data={"text": "Hello", "language": "xx-XX"},
            headers=AUTH,
        )

        assert response.status_code == 400


def test_lt_check_missing_text():
    with TestClient(app) as client:
        response = client.post(
            "/lt/v2/check",
            data={"language": "en-US"},
            headers=AUTH,
        )

        assert response.status_code == 400


def test_lt_check_undetectable_language_falls_back(set_redis):  # noqa: F811
    """Detection failure with `auto` checks with the fallback language
    instead of answering with nothing, like a LanguageTool server would."""
    with TestClient(app) as client:
        response = client.post(
            "/lt/v2/check",
            data={"text": "これはテストです", "language": "auto"},
            headers=AUTH,
        )

        assert response.status_code == 200
        assert response.json()["language"]["code"] == "en-US"

        response = client.post(
            "/lt/v2/check",
            data={
                "text": "これはテストです",
                "language": "auto",
                "preferredVariants": "de-DE",
            },
            headers=AUTH,
        )

        assert response.status_code == 200
        assert response.json()["language"]["code"] == "de-DE"


def test_lt_utility_endpoints():
    with TestClient(app) as client:
        response = client.get("/lt/v2/maxtextlength")
        assert response.status_code == 200
        assert response.text.isdigit()

        response = client.get("/lt/v2/info")
        assert response.status_code == 200
        assert response.json()["software"]["name"] == "Witty NLP API"

        assert client.get("/lt/v2/words").json() == {"words": []}
        assert client.post("/lt/v2/words/add").json() == {"added": False}
        assert client.post("/lt/v2/words/delete").json() == {"deleted": False}


def test_lt_root_mount_off_by_default(monkeypatch):
    from fastapi import FastAPI
    from app.routes import register_routes
    from app.settings import reset_settings_cache

    # Force the setting off: the developer's .env may enable it, and env vars
    # take precedence over the .env file.
    monkeypatch.setenv("LANGUAGETOOL_COMPAT_ROOT", "false")
    reset_settings_cache()
    try:
        bare_app = FastAPI()
        register_routes(bare_app)

        client = TestClient(bare_app)
        assert client.get("/v2/languages").status_code == 404
        assert client.get("/lt/v2/languages").status_code == 200
    finally:
        monkeypatch.undo()
        reset_settings_cache()


def test_lt_root_mount_enabled(monkeypatch):
    from fastapi import FastAPI
    from app.routes import register_routes
    from app.settings import reset_settings_cache

    monkeypatch.setenv("LANGUAGETOOL_COMPAT_ROOT", "true")
    reset_settings_cache()
    try:
        root_app = FastAPI()
        register_routes(root_app)

        client = TestClient(root_app)
        # /v2/languages needs no app context, so the bare app suffices.
        assert client.get("/v2/languages").status_code == 200
        assert client.get("/lt/v2/languages").status_code == 200
    finally:
        monkeypatch.undo()
        reset_settings_cache()


def test_resolve_lang():
    assert resolve_lang("auto") == LangWithAutoType.AUTO
    assert resolve_lang("en-US") == LangWithAutoType.enUS
    assert resolve_lang("de") == LangWithAutoType.DE
    assert resolve_lang("de-DE-x-simple-language") == LangWithAutoType.deDE
    assert resolve_lang("pt-BR") is None


def test_text_from_data():
    data = {
        "annotation": [
            {"text": "A "},
            {"markup": "<b>"},
            {"text": "test"},
            {"markup": "</b>", "interpretAs": "\n"},
        ]
    }

    # Markup is replaced by equal-length filler so offsets stay aligned.
    text, markup_spans = text_from_data(json.dumps(data))
    assert text == "A    test\n   "
    assert markup_spans == [(2, 5), (9, 13)]

    # The desktop app sends a bare text document instead of annotations.
    text, markup_spans = text_from_data('{"text": "What is gooing on"}')
    assert text == "What is gooing on"
    assert markup_spans == []
