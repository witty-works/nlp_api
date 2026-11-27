"""The French adjective rules the check builds itself (fr_noun_adjective_rule).

An adjective after an article and without a noun after it names a person
(`le dernier est arrivé`), so the check suggests both forms. Adverbs are not
such adjectives (`il ne`, `au moins`, `les plus`), nor is an adjective in
front of its noun (`le dernier compte`).
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.test_api import set_redis  # noqa: F401  (fixture)

CONFIG = {"french_gender_separator": "·", "gendered_roles_format": "inclusive_gender"}


def check(text):
    with TestClient(app) as client:
        response = client.post(
            "/v2.4/check",
            json={"text": text, "lang": "fr", "config": CONFIG},
            headers={"X-TESTING-AUTH": "default@gmail.com"},
        )
    assert response.status_code == 200
    return response.json()["results"]


@pytest.mark.parametrize(
    "text, words",
    [
        ("Pour votre sécurité, il ne sera plus affiché.", "il ne"),
        ("Copiez-la maintenant : elle n’est affichée qu’une seule fois.", "elle n’"),
        ("Le mot de passe doit contenir au moins 8 caractères.", "au moins"),
        ("Les termes les plus fréquents.", "les plus"),
        ("C’est le dernier compte superadmin.", "le dernier"),
    ],
)
def test_no_adjective_rule_for_an_adverb_or_an_adjective_before_its_noun(
    text, words, set_redis  # noqa: F811
):
    flagged = [r["text"].lower() for r in check(text)]

    assert words not in flagged


def test_an_adjective_naming_a_person_keeps_its_stem(set_redis):  # noqa: F811
    results = [r for r in check("Le dernier est arrivé hier.") if r["text"] == "Le dernier"]

    assert results, "the adjective naming a person is still flagged"
    alternatives = [a["text"] for a in results[0]["alternatives"]]
    assert any("dernier" in a and "ère" in a for a in alternatives), alternatives
    assert not any("dernié" in a for a in alternatives), alternatives
