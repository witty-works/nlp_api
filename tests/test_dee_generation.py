"""Inklusivum (de-e) article forms, checked against geschlechtsneutral.net.

Every expectation below is quoted from the association's own declension
tables, so a failure here means the data drifted from the spec rather than
that the spec was reinterpreted. Sources:
  https://geschlechtsneutral.net/deklinationstabellen/
  https://geschlechtsneutral.net/gesamtsystem/
"""

import csv
from pathlib import Path

import pytest

ARTICLES_CSV = (
    Path(__file__).resolve().parent.parent / "training_data" / "de" / "articles.csv"
)


def _rows():
    with open(ARTICLES_CSV, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# (case, masculine, expected Inklusivum)
SPEC_FORMS = [
    # Definite article.
    ("nominativ", "der", "de"),
    ("genitiv", "des", "ders"),
    ("dativ", "dem", "derm"),
    ("akkusativ", "den", "de"),
    # ein-paradigm: -ers / -erm appended to the bare stem.
    ("nominativ", "ein", "ein"),
    ("genitiv", "eines", "einers"),
    ("dativ", "einem", "einerm"),
    ("akkusativ", "einen", "ein"),
    # jed-paradigm: -ey in nominative and accusative.
    ("nominativ", "jeder", "jedey"),
    ("genitiv", "jedes", "jeders"),
    ("dativ", "jedem", "jederm"),
    ("akkusativ", "jeden", "jedey"),
    # Possessives follow the ein-paradigm.
    ("nominativ", "mein", "mein"),
    ("genitiv", "meines", "meiners"),
    ("dativ", "meinem", "meinerm"),
    ("nominativ", "dein", "dein"),
    ("genitiv", "deines", "deiners"),
    ("dativ", "deinem", "deinerm"),
    # unser/euer drop the r in the base form but decline as if they had not.
    ("nominativ", "unser", "unse"),
    ("genitiv", "unseres", "unserers"),
    ("dativ", "unserem", "unsererm"),
    ("nominativ", "euer", "eue"),
    ("genitiv", "eures", "eurers"),
    ("dativ", "eurem", "eurerm"),
    # sein/ihr as possessive articles take the possessive of "en".
    ("nominativ", "sein", "ens"),
    ("genitiv", "seines", "ensers"),
    ("dativ", "seinem", "enserm"),
    ("nominativ", "ihr", "ens"),
    ("genitiv", "ihres", "ensers"),
    ("dativ", "ihrem", "enserm"),
    # Personal pronoun. "enser" fills only the rare true-genitive slot.
    ("nominativ", "er", "en"),
    ("genitiv", "seiner", "enser"),
    ("dativ", "ihm", "em"),
    ("akkusativ", "ihn", "en"),
    # zu is the only preposition whose contraction survives.
    ("dativ", "zum", "zurm"),
]


@pytest.mark.parametrize("form,masculine,expected", SPEC_FORMS)
def test_inklusivum_article_matches_spec(form, masculine, expected):
    matches = [
        row for row in _rows() if row["Form"] == form and row["Masculine"] == masculine
    ]

    assert matches, f"no {form} row for {masculine!r} in articles.csv"

    for row in matches:
        assert row["Inklusivum"] == expected, (
            f"{form} {masculine!r}: expected {expected!r}, "
            f"got {row['Inklusivum']!r}"
        )


def test_possessives_do_not_collapse_to_the_personal_pronoun():
    """sein/ihr are possessives; rendering them as "en" loses that."""
    possessives = {"sein", "seines", "seinem", "seinen"} | {
        "ihr",
        "ihres",
        "ihrem",
        "ihren",
    }

    for row in _rows():
        if row["Masculine"] in possessives:
            assert row["Inklusivum"].startswith("ens"), (
                f"{row['Form']} {row['Masculine']!r} rendered as "
                f"{row['Inklusivum']!r}, which is a personal pronoun form"
            )


def test_unser_does_not_collide_with_the_colloquial_form():
    """The spec elides the r precisely so that "unserm" is never produced."""
    forms = {
        row["Inklusivum"] for row in _rows() if row["Masculine"].startswith("unser")
    }

    assert "unserm" not in forms
    assert "unsers" not in forms


def test_every_row_has_an_inklusivum_form():
    for row in _rows():
        assert row[
            "Inklusivum"
        ], f"empty Inklusivum for {row['Form']} {row['Masculine']}"
