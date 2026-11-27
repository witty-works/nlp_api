"""German suffix rules apply to compounds, not to words that end the same way.

The second pass for suffix rules finds `Kunde` in `Stammkunden`, and also in
`Sekunden`, which is a word of its own and names no person.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.test_api import set_redis  # noqa: F401  (fixture)


def flagged(text):
    with TestClient(app) as client:
        response = client.post(
            "/v2.4/check",
            json={"text": text, "lang": "de", "config": {"german_gender_ending": "*in"}},
            headers={"X-TESTING-AUTH": "default@gmail.com"},
        )
    assert response.status_code == 200
    return [r["text"] for r in response.json()["results"] if r.get("gravity") is not None]


def test_a_word_that_only_ends_like_a_rule_is_not_flagged(set_redis):  # noqa: F811
    assert "Sekunden" not in flagged("Der Code ist 30 Sekunden gültig.")


@pytest.mark.parametrize(
    "text, word",
    [
        ("Unsere Stammkunden sind zufrieden.", "Stammkunden"),
        ("Wir gewinnen Neukunden.", "Neukunden"),
    ],
)
def test_a_compound_with_the_rule_is_still_flagged(text, word, set_redis):  # noqa: F811
    assert word in flagged(text)


@pytest.mark.parametrize(
    "text, word",
    [
        ("Der Schularzt kommt heute.", "Schularzt"),
        ("Der Bergbauingenieur plant.", "Bergbauingenieur"),
        ("Der Generalstaatsanwalt spricht.", "Generalstaatsanwalt"),
    ],
)
def test_a_person_compound_the_dictionary_knows_is_still_flagged(text, word, set_redis):  # noqa: F811
    # The result may take the article with it (`Der Schularzt`).
    assert any(word in result for result in flagged(text))


def test_a_house_is_no_user(set_redis):  # noqa: F811
    assert "Krankenhäuser" not in flagged("Die Krankenhäuser sind voll.")
