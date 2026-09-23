"""Switching between the German gender formats.

A text written in one format and checked with another configured gets one
`gendered_denominations_ending_advanced` alert per form that differs, marked
`bulk: "gender_format"` and with exactly one alternative: the same form in the
configured format. Accepting all of them is the switch, so the round trips
below are the contract a client's "switch the gender format" relies on.
"""

import itertools
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.gender_format import (
    convert_form,
    is_gendered_stem,
    noun_ending,
    render_noun_ending,
    render_pair,
    render_word_ending,
    split_form,
)
from app.main import app
from app.models import GermanGenderEndingType as Ending
from tests.test_api import set_redis  # noqa: F401  (fixture)

SUBCATEGORY = "gendered_denominations_ending_advanced"


# --- the module on its own ------------------------------------------------------


@pytest.mark.parametrize(
    "written,ending",
    [
        ("*innen", "innen"),
        ("/-in", "in"),
        ("(innen)", "innen"),
        ("(-in)", "in"),
        ("Innen", "innen"),
        (":r", "r"),
    ],
)
def test_noun_ending_reads_every_format(written, ending):
    assert noun_ending(written) == ending


@pytest.mark.parametrize(
    "target,innen,r",
    [
        (Ending.STAR, "*innen", "*r"),
        (Ending.UNDERSCORE, "_innen", "_r"),
        (Ending.COLON, ":innen", ":r"),
        (Ending.SLASH, "/innen", "/r"),
        (Ending.SLASH_DASH, "/-innen", "/-r"),
        # The capital I only marks in/innen; other endings take a slash.
        (Ending.CAPITAL_LETTER, "Innen", "/r"),
        (Ending.PARENTHESIS, "(innen)", "(r)"),
        (Ending.PARENTHESIS_DASH, "(-innen)", "(-r)"),
        (Ending.INKLUSIVUM, None, None),
    ],
)
def test_render_noun_ending(target, innen, r):
    assert render_noun_ending("innen", target) == innen
    assert render_noun_ending("r", target) == r


def test_pairs_and_word_endings_by_format():
    assert render_pair("die", "der", Ending.COLON) == "die:der"
    # Formats without an infix write pairs with a slash, as the API's own
    # suggestions do (Die/der LehrerIn).
    assert render_pair("die", "der", Ending.PARENTHESIS) == "die/der"
    assert render_word_ending("jede", "r", Ending.PARENTHESIS) == "jede(r)"
    assert render_word_ending("jede", "r", Ending.CAPITAL_LETTER) == "jede/r"
    assert render_pair("die", "der", Ending.INKLUSIVUM) is None


@pytest.mark.parametrize(
    "text,parts",
    [
        ("die*der", ("die", "der")),
        ("der/die", ("der", "die")),
        ("jede/-r", ("jede", "r")),
        ("jede(r)", ("jede", "r")),
        ("ein(-e)", ("ein", "e")),
        ("die der", None),
    ],
)
def test_split_form(text, parts):
    assert split_form(text) == parts


def test_convert_form_only_knows_the_article_table():
    forms = {"die~der", "jede~r", "ein~e", "sie~er"}
    words = {"der", "die", "jede", "jeder", "ein", "eine", "sie", "er"}

    def convert(text, target=Ending.COLON):
        return convert_form(text, target, forms, words)

    # Either order of a pair, the writer's order kept.
    assert convert("die*der") == "die:der"
    assert convert("der*die") == "der:die"
    # Opening a sentence.
    assert convert("Der/die") == "Der:die"
    # A short ending, told from a pair by whether stem + ending is a word.
    assert convert("jede*r", Ending.PARENTHESIS) == "jede(r)"
    assert convert("sie*er", Ending.PARENTHESIS) == "sie/er"
    # Anything the table does not know is left alone.
    assert convert("und/oder") is None


def test_is_gendered_stem():
    def tokens(*texts, spaced=()):
        return [
            SimpleNamespace(text=text, whitespace_=" " if i in spaced else "")
            for i, text in enumerate(texts)
        ]

    assert is_gendered_stem(tokens("Lehrer", "/", "innen"), 0)
    assert is_gendered_stem(tokens("Lehrer", "(", "innen", ")"), 0)
    assert is_gendered_stem(tokens("ihre", "/", "n"), 0)
    assert not is_gendered_stem(tokens("Lehrer", "/", "innen", spaced=(0,)), 0)
    assert not is_gendered_stem(tokens("Montag", "/", "Dienstag"), 0)
    assert not is_gendered_stem(tokens("Lehrer"), 0)


# --- through the API ----------------------------------------------------------


def sentence(noun, pair, word):
    """Nouns, also with a non-"in" ending; article pairs in both orders and
    opening a sentence; determiners with a separated ending."""
    return (
        f"{pair('Der', 'die')} Lehrer{noun('innen')} und {pair('der', 'die')} "
        f"Schüler{noun('in')} sprechen mit {word('jede', 'r')} Kolleg{noun('in')}. "
        f"{word('Ein', 'e')} Angestellte{noun('r')} fragt {pair('die', 'den')} "
        f"Chef{noun('in')}."
    )


def infix(separator):
    return (
        lambda ending: separator + ending,
        lambda first, second: f"{first}{separator}{second}",
        lambda stem, ending: f"{stem}{separator}{ending}",
    )


def slash_pairs(noun, word):
    return (noun, lambda first, second: f"{first}/{second}", word)


FORMATS = {
    "*in": sentence(*infix("*")),
    "_in": sentence(*infix("_")),
    ":in": sentence(*infix(":")),
    "/in": sentence(*infix("/")),
    "/-in": sentence(*slash_pairs(lambda e: "/-" + e, lambda s, e: f"{s}/-{e}")),
    "In": sentence(
        *slash_pairs(
            lambda e: e[:1].upper() + e[1:] if e.startswith("in") else "/" + e,
            lambda s, e: f"{s}/{e}",
        )
    ),
    "()": sentence(*slash_pairs(lambda e: f"({e})", lambda s, e: f"{s}({e})")),
    "(-)": sentence(*slash_pairs(lambda e: f"(-{e})", lambda s, e: f"{s}(-{e})")),
}


def mismatches(client, text, ending):
    response = client.post(
        "/v2.4/check",
        json={"text": text, "lang": "de", "config": {"german_gender_ending": ending}},
        headers={"X-TESTING-AUTH": "default@gmail.com"},
    )
    assert response.status_code == 200

    return [
        result
        for result in response.json()["results"]
        if result.get("subcategory") == SUBCATEGORY
    ]


def accept_all(text, alerts):
    """What a client's bulk accept does: apply each alert's alternative."""
    chars = list(text)
    for alert in sorted(alerts, key=lambda alert: -alert["start"]):
        chars[alert["start"] : alert["end"]] = list(alert["alternatives"][0]["text"])

    return "".join(chars)


@pytest.mark.parametrize(
    "source,target", list(itertools.permutations(FORMATS, 2)), ids=lambda f: f
)
def test_switching_formats_round_trips(set_redis, source, target):  # noqa: F811
    with TestClient(app) as client:
        alerts = mismatches(client, FORMATS[source], target)

        # The bulk contract: marked, one alternative each, no overlaps.
        assert all(alert.get("bulk") == "gender_format" for alert in alerts)
        assert all(len(alert["alternatives"]) == 1 for alert in alerts)
        spans = sorted((alert["start"], alert["end"]) for alert in alerts)
        assert all(end <= start for (_, end), (start, _) in zip(spans, spans[1:]))

        converted = accept_all(FORMATS[source], alerts)
        assert converted == FORMATS[target]

        # And back again, to the text as it was written.
        assert accept_all(converted, mismatches(client, converted, source)) == (
            FORMATS[source]
        )


def test_the_stem_of_a_gendered_form_is_not_masculine(set_redis):  # noqa: F811
    """`Lehrer` in `Lehrer/innen` or `Lehrer(innen)` is part of a gendered
    form, not a masculine noun to gender."""
    with TestClient(app) as client:
        response = client.post(
            "/v2.4/check",
            json={
                "text": "Die Lehrer/innen und die Schüler(innen) fragen ihre/n Chef/in.",
                "lang": "de",
                "config": {"german_gender_ending": "/in"},
            },
            headers={"X-TESTING-AUTH": "default@gmail.com"},
        )

    flagged = {result["text"] for result in response.json()["results"]}
    assert not flagged & {"Lehrer", "Schüler", "ihre", "Chef"}, flagged


def check(client, text, ending=":in"):
    response = client.post(
        "/v2.4/check",
        json={"text": text, "lang": "de", "config": {"german_gender_ending": ending}},
        headers={"X-TESTING-AUTH": "default@gmail.com"},
    )
    assert response.status_code == 200

    return response.json()["results"]


def test_switching_leaves_look_alikes_alone(set_redis):  # noqa: F811
    """Only person nouns and forms the article table knows are converted: a
    plural hint, a unit, a pair of words, a URL path stay as written."""
    with TestClient(app) as client:
        results = check(
            client,
            "Bitte und/oder km/h, der Ein/Ausgang, Montag/Dienstag, die Klasse/n, "
            "unsere Podcasts/in Englisch.",
        )

    assert [result for result in results if result.get("bulk")] == []


def test_title_case_pairs_and_compounds_switch_too(set_redis):  # noqa: F811
    text = (
        "Der*Die Lehrer*in und die Schüler*innenvertretung beim "
        "Mitarbeiter*innengespräch im Lehrer*innen-Team."
    )
    with TestClient(app) as client:
        converted = accept_all(text, mismatches(client, text, ":in"))
        assert converted == (
            "Der:Die Lehrer:in und die Schüler:innenvertretung beim "
            "Mitarbeiter:innengespräch im Lehrer:innen-Team."
        )

        # Into a bracket format only the gender part goes in brackets.
        bracketed = accept_all(text, mismatches(client, text, "()"))
        assert "Schüler(innen)vertretung" in bracketed
        assert "Lehrer(innen)-Team" in bracketed


def test_feedback_on_a_gendered_stem_covers_the_whole_form(set_redis):  # noqa: F811
    """`Chef/in` is still leadership language: kept, and widened so that
    accepting `Leitungsperson` replaces `Chef/in`, not only `Chef`."""
    with TestClient(app) as client:
        results = check(client, "Die Chef/in entscheidet.", "/in")

    leadership = [result for result in results if result["subcategory"] == "leadership"]
    assert [result["text"] for result in leadership] == ["Chef/in"]


def test_what_an_account_forces_is_visible_to_the_client(set_redis):  # noqa: F811
    """test@gmail.com forces Binnen-I and its organisation binary roles
    ("Lehrerinnen und Lehrer"). The format asked for is overruled, and the
    response says which applied; with binary roles there is no format to
    switch between, so no bulk alerts. A client has to tell the user either
    way rather than report "nothing to switch"."""
    with TestClient(app) as client:
        response = client.post(
            "/v2.4/check",
            json={
                "text": "Die Lehrer:innen kommen.",
                "lang": "de",
                "config": {"german_gender_ending": ":in"},
            },
            headers={"X-TESTING-AUTH": "test@gmail.com"},
        )

    body = response.json()
    assert body["gender_separator"] == "In"
    assert [result for result in body["results"] if result.get("bulk")] == []


def test_bulk_actions_say_what_a_client_can_offer(set_redis):  # noqa: F811
    """Sent on every check, so a client can tell an API without bulk actions
    from a text that happens to have none."""

    def bulk_actions(text, lang, config, user="default@gmail.com"):
        response = client.post(
            "/v2.4/check",
            json={"text": text, "lang": lang, "config": config},
            headers={"X-TESTING-AUTH": user},
        )
        return response.json()["bulk_actions"]

    with TestClient(app) as client:
        assert bulk_actions(
            "Die Lehrer*innen.", "de", {"german_gender_ending": ":in"}
        ) == ["gender_format"]
        # Nothing to switch in this text, still a switch the client can offer.
        assert bulk_actions("Das ist gut.", "de", {"german_gender_ending": ":in"}) == [
            "gender_format"
        ]
        # Not (yet) for the Inklusivum, French or English.
        assert (
            bulk_actions("Die Lehrer*innen.", "de", {"german_gender_ending": "de-e"})
            == []
        )
        assert bulk_actions("Les enseignant·e·s.", "fr", {}) == []
        assert bulk_actions("The chairman.", "en", {}) == []
        # Nor where the account forces binary roles.
        assert bulk_actions("Die Lehrer:innen.", "de", {}, "test@gmail.com") == []
