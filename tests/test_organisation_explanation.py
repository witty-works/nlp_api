"""An organisation's explanation for its term replacements reaches clients as
written: its text never as markup, its link only as an http(s) address."""

import json

import pytest
from fastapi.testclient import TestClient

from app.config_manager import parse_term_replacements
from app.language_processor import http_url
from app.main import app

EMAIL = "org-explanation@example.org"


def check(explanation: dict) -> dict:
    with TestClient(app) as client:
        context = app.state.context
        user = {
            "id": "org-explanation",
            "email": EMAIL,
            "plan": "witty_teams",
            "organization_id": None,
            "config": {},
            "false_positives": [],
            "term_replacements": parse_term_replacements(
                {
                    "foo bar|en": {
                        "alternatives": ["ding ding"],
                        "word_type": "=",
                        "explanation": explanation,
                    }
                },
                context,
            ),
            "domains": None,
            "config_hash": None,
            "notifications": 0,
        }
        key = context.redis.get_user_id(EMAIL)
        context.redis.db.set(key, json.dumps(user))
        try:
            response = client.post(
                "/v2.4/check",
                json={"text": "This is foo bar.", "lang": "en-US"},
                headers={"X-TESTING-AUTH": EMAIL},
            )
        finally:
            context.redis.db.delete(key)

    assert response.status_code == 200
    (result,) = [
        r for r in response.json()["results"] if r["category"] == "corporate_rules"
    ]

    return result["explanation"]


def test_explanation_text_is_escaped_where_it_is_html():
    explanation = check(
        {
            "text": 'Say <img src=x onerror="alert(1)"> & mean it',
            "icon": None,
            "url": "https://example.org/why",
        }
    )

    # The short text is plain text to clients, so it goes out as written ...
    assert explanation["text"] == 'Say <img src=x onerror="alert(1)"> & mean it'
    # ... and long_text, which clients render as HTML, shows the same words.
    assert (
        explanation["long_text"]
        == 'Say &lt;img src=x onerror="alert(1)"&gt; &amp; mean it'
    )
    assert explanation["url"] == "https://example.org/why"


def test_explanation_link_is_dropped_unless_http():
    explanation = check({"text": "Why", "icon": None, "url": "javascript:alert(1)"})

    assert explanation.get("url") is None


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://example.org/a", "https://example.org/a"),
        ("http://example.org", "http://example.org"),
        ("HTTPS://example.org", "HTTPS://example.org"),
        ("javascript:alert(1)", None),
        (" javascript:alert(1)", None),
        ("java\tscript:alert(1)", None),
        ("data:text/html,<script>alert(1)</script>", None),
        ("//example.org", None),
        ("/relative", None),
        ("", None),
        (None, None),
        (42, None),
    ],
)
def test_http_url(url, expected):
    assert http_url(url) == expected
