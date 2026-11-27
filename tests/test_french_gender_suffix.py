"""`french_gender_suffix`: the short or the full feminine suffix in French.

Inclusive writing joins the masculine and the part of the feminine that
differs (`utilisateur·rice`, `vendeur·se`), or the whole feminine suffix
(`utilisateur·trice`, `vendeur·euse`). Only the -teur/-trice, -eur/-euse and
-eux/-euse families have both forms; every other form is the same in both.
"""

import pytest
from fastapi.testclient import TestClient

from app.gender_format import convert_french, french_suffix_form
from app.main import app
from app.models import Config, FrenchGenderSuffixType, LlmAccessType, RuleConfig
from tests.test_api import llm_access, reply_from, set_redis  # noqa: F401  (fixtures)

SHORT, FULL = FrenchGenderSuffixType.SHORT, FrenchGenderSuffixType.FULL


@pytest.mark.parametrize(
    "short, full",
    [
        ("utilisateur·rice", "utilisateur·trice"),
        ("utilisateur·rices", "utilisateur·trices"),
        ("utilisateur·rice·s", "utilisateur·trice·s"),
        ("vendeur·se", "vendeur·euse"),
        ("chercheur.se.s", "chercheur.euse.s"),
        ("porteur/ses", "porteur/euses"),
        ("heureux·se", "heureux·euse"),
        ("La·le directeur·rice et un·e acteur·rice", "La·le directeur·trice et un·e acteur·trice"),
    ],
)
def test_the_two_forms_turn_into_each_other(short, full):
    assert french_suffix_form(short, FULL) == full
    assert french_suffix_form(full, SHORT) == short
    assert french_suffix_form(short, SHORT) == short
    assert french_suffix_form(full, FULL) == full


@pytest.mark.parametrize(
    "text",
    ["enseignant·es", "musicien·ne", "actif·ve", "premier·ère", "un·e", "la·le", "site.fr", "Lehrer*innen"],
)
def test_forms_without_two_suffixes_stay_as_written(text):
    assert french_suffix_form(text, FULL) == text
    assert french_suffix_form(text, SHORT) == text


def test_convert_french_writes_the_configured_suffix():
    def convert(text, suffix):
        return convert_french(text, "·", {"le", "un"}, {"la", "une"}, lambda word: True, suffix)

    assert convert("utilisateur·trices", SHORT) == "utilisateur·rices"
    assert convert("utilisateur.rices", FULL) == "utilisateur·trices"
    assert convert("utilisateur·trices", FULL) == "utilisateur·trices"


def check(client, text, suffix):
    config = {"french_gender_separator": "·", "gendered_roles_format": "inclusive_gender"}
    if suffix is not None:
        config["french_gender_suffix"] = suffix
    response = client.post(
        "/v2.4/check",
        json={"text": text, "lang": "fr", "config": config},
        headers={"X-TESTING-AUTH": "default@gmail.com"},
    )
    assert response.status_code == 200
    return response.json()["results"]


@pytest.mark.parametrize(
    "text, suffix, expected",
    [
        ("Les utilisateur·trices peuvent se connecter.", None, "utilisateur·rices"),
        ("Les utilisateur·trices peuvent se connecter.", "short", "utilisateur·rices"),
        ("Les utilisateur·rices peuvent se connecter.", "full", "utilisateur·trices"),
        ("Les vendeur·ses sont là.", "full", "vendeur·euses"),
    ],
)
def test_the_other_suffix_is_switched_like_another_separator(
    text, suffix, expected, set_redis  # noqa: F811
):
    with TestClient(app) as client:
        alerts = [r for r in check(client, text, suffix) if r.get("bulk") == "gender_format"]

    assert [a["alternatives"][a["bulk_alternative"]]["text"] for a in alerts] == [expected]


@pytest.mark.parametrize(
    "text, suffix",
    [
        ("Les utilisateur·rices peuvent se connecter.", "short"),
        ("Les utilisateur·trices peuvent se connecter.", "full"),
    ],
)
def test_the_configured_suffix_is_not_flagged(text, suffix, set_redis):  # noqa: F811
    with TestClient(app) as client:
        flagged = [r for r in check(client, text, suffix) if r.get("gravity") is not None]

    assert flagged == []


@pytest.mark.parametrize("suffix, form", [("short", "utilisateur·rices"), ("full", "utilisateur·trices")])
def test_suggestions_use_the_configured_suffix(suffix, form, set_redis):  # noqa: F811
    with TestClient(app) as client:
        results = check(client, "Les utilisateurs peuvent se connecter.", suffix)

    alternatives = [a["text"] for r in results for a in r.get("alternatives", [])]
    assert any(form in a for a in alternatives), alternatives


def test_config_options_offer_the_suffix(set_redis):  # noqa: F811
    with TestClient(app) as client:
        options = client.get("/v2.0/config-options").json()["options"]

    assert options["french_gender_suffix"]["values"] == ["short", "full"]
    assert options["french_gender_suffix"]["default"] == "short"


def test_a_synced_config_can_force_the_suffix():
    config = RuleConfig.model_validate(
        {"french_gender_suffix": {"value": "full", "status": "force"}}
    )

    assert config.french_gender_suffix.value == FULL
    assert Config().french_gender_suffix == SHORT


def test_a_rephrasing_comes_in_the_configured_suffix(llm_access, set_redis, monkeypatch):  # noqa: F811
    # The model answers in the short suffix the request did not ask for.
    reply_from(monkeypatch, '{"utilisateur·trice": "L’utilisateur·rice se connecte."}')
    llm_access(LlmAccessType.USERS)
    body = {
        "sentence": "L’utilisateur se connecte.",
        "text": "utilisateur",
        "start": 2,
        "alternatives": [{"text": "utilisateur·trice"}],
        "lang": "fr",
        "config": {"llm_alternatives": True, "french_gender_suffix": "full"},
    }
    with TestClient(app) as client:
        response = client.post(
            "/v1.0/rephrase", json=body, headers={"X-TESTING-AUTH": "test@gmail.com"}
        )

    assert response.status_code == 200
    assert response.json()["results"] == {"utilisateur·trice": "L’utilisateur·trice se connecte."}


def test_the_writers_capitals_are_kept():
    assert french_suffix_form("Serveur·Se", FULL) == "Serveur·Euse"
    assert french_suffix_form("UTILISATEUR·RICE", FULL) == "UTILISATEUR·TRICE"


def test_only_forms_with_the_configured_separator_change():
    assert french_suffix_form("Voir https://acteur.se", FULL, "·") == "Voir https://acteur.se"
    assert french_suffix_form("acteur·rice et acteur.rice", FULL, "·") == "acteur·trice et acteur.rice"


def test_two_suggestions_that_differ_only_in_the_suffix_are_one(set_redis):  # noqa: F811
    with TestClient(app) as client:
        results = check(client, "Les utilisateurs peuvent se connecter.", "full")

    for result in results:
        texts = [a["text"] for a in result.get("alternatives", [])]
        assert len(texts) == len(set(texts)), texts
        assert result["text"] not in texts


@pytest.mark.parametrize("separator, example", [("·", '"utilisateur·rice"'), ("·s", '"utilisateur·rice·s"'), (".s", '"utilisateur.rice.s"')])
def test_the_guidance_example_follows_the_separator(separator, example):
    from app.guidance import guidance

    assert example in guidance(Config(french_gender_separator=separator))
