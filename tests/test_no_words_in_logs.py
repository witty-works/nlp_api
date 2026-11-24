"""The words of a checked text reach no log line (AGENTS.md, 1.1): the
lines that report a gap in the declension data say what is missing, not for
which word."""

import logging

import pytest
from fastapi.testclient import TestClient

from app.main import app, context
from tests.test_api import set_redis  # noqa: F401  (fixture)

# Words the declension data cannot have, next to ones the rules flag, so the
# lookups for them fail.
TEXTS = {
    "de": "Die Quxlehrer und der Zorbfachmann quxten mit dem Kunden.",
    # The alternatives of "chairmen" and "cameramen" have no plural in the
    # declension data, which is logged.
    "en": "The quxmen zorbed the chairmen and the cameramen.",
    "fr": "Les quxeurs et le zorbeur sont des directeurs.",
}


@pytest.mark.parametrize("lang", TEXTS)
def test_no_word_of_the_text_is_logged(
    lang, caplog, monkeypatch, set_redis
):  # noqa: F811
    monkeypatch.setattr(context.settings, "log_missing_declension", True)
    caplog.set_level(logging.DEBUG, logger="nlp_api")

    with TestClient(app) as client:
        response = client.post(
            "/v2.4/check",
            json={"text": TEXTS[lang], "lang": lang},
            headers={"X-TESTING-AUTH": "test@gmail.com"},
        )
    assert response.status_code == 200

    logged = "\n".join(record.getMessage() for record in caplog.records)
    for word in ("qux", "Qux", "zorb", "Zorb", "chair", "camera"):
        assert word not in logged


def test_a_gap_in_the_declension_data_is_still_logged(caplog, monkeypatch):
    """What is missing, at DEBUG, without the word it is missing for."""
    monkeypatch.setattr(context.settings, "log_missing_declension", True)
    caplog.set_level(logging.DEBUG, logger="nlp_api")

    with TestClient(app) as client:
        client.post("/debug/check", json={"text": TEXTS["en"], "lang": "en"})

    gaps = [
        r for r in caplog.records if "English noun plural missing" in r.getMessage()
    ]
    assert gaps
    assert all(r.levelno == logging.DEBUG for r in gaps)
