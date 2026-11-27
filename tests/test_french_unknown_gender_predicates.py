"""An adjective or participle about `je`, `tu` or `vous` gets both forms.

The text does not say who `vous` is, so `vous êtes connecté` takes the
masculine for them; `connecté·e` does not. With `être` the word agrees with
the person (`merci de vous être inscrit`, `êtes-vous sûr`); with `avoir` it
does not (`vous l’avez ajouté`), and `il` says who it is.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.test_api import set_redis  # noqa: F401  (fixture)

CONFIG = {"french_gender_separator": "·", "gendered_roles_format": "inclusive_gender"}


def results(text):
    with TestClient(app) as client:
        response = client.post(
            "/v2.4/check",
            json={"text": text, "lang": "fr", "config": CONFIG},
            headers={"X-TESTING-AUTH": "default@gmail.com"},
        )
    assert response.status_code == 200
    return [r for r in response.json()["results"] if r.get("gravity") is not None]


@pytest.mark.parametrize(
    "text, word, alternative",
    [
        ("Merci de vous être inscrit !", "inscrit", "inscrit·e"),
        ("Vous êtes connecté.", "connecté", "connecté·e"),
        ("Êtes-vous sûr de vouloir continuer ?", "sûr", "sûr·e"),
        ("Vous avez été déconnecté.", "déconnecté", "déconnecté·e"),
        ("Vous n’êtes pas encore inscrit.", "inscrit", "inscrit·e"),
    ],
)
def test_a_word_about_an_unnamed_person_gets_both_forms(text, word, alternative, set_redis):  # noqa: F811
    found = [r for r in results(text) if r["text"].lower() == word]

    assert found, results(text)
    assert alternative in [a["text"] for a in found[0]["alternatives"]]


@pytest.mark.parametrize(
    "text, word",
    [
        ("Il est connecté.", "connecté"),
        ("Vous l’avez ajouté.", "ajouté"),
        ("Vous êtes connecté·e.", "connecté·e"),
        ("Vous êtes responsable de l’équipe.", "responsable"),
        ("Vous êtes connectée.", "connectée"),
        # The subject is a noun, whatever pronoun comes before it.
        ("Le mot de passe que vous avez choisi est trop court.", "court"),
        ("Je pense que le serveur est connecté.", "connecté"),
        ("Vous verrez que le compte est activé.", "activé"),
        ("Si vous voulez, le fichier est prêt.", "prêt"),
        ("Il me semble que le fichier est prêt.", "prêt"),
    ],
)
def test_a_word_that_agrees_with_someone_else_or_already_does_is_left(text, word, set_redis):  # noqa: F811
    assert word not in [r["text"].lower() for r in results(text)]
