"""Inklusivum (de-e) noun forms, checked against geschlechtsneutral.net.

Sources:
  https://geschlechtsneutral.net/gesamtsystem/
  https://geschlechtsneutral.net/ausnahmeformen/
"""

import csv
from pathlib import Path

import pytest

from app.alternatives_engine import inklusivum

EXCEPTIONS_CSV = (
    Path(__file__).resolve().parent.parent
    / "training_data"
    / "de"
    / "inklusivum_nouns.csv"
)


def _exceptions():
    with open(EXCEPTIONS_CSV, newline="", encoding="utf-8") as fh:
        return {
            row["Masculine"]: (row["Singular"], row["Plural"])
            for row in csv.DictReader(fh)
        }


# (masculine, feminine, expected singular, expected plural)
REGULAR = [
    ("Schüler", "Schülerin", "Schülere", "Schülerne"),
    ("Lehrer", "Lehrerin", "Lehrere", "Lehrerne"),
    ("Autor", "Autorin", "Autore", "Autorne"),
    ("Professor", "Professorin", "Professore", "Professorne"),
    ("Influencer", "Influencerin", "Influencere", "Influencerne"),
    # A masculine already ending in -e takes -re, never a doubled -e.
    ("Kollege", "Kollegin", "Kollegere", "Kollegerne"),
    ("Kunde", "Kundin", "Kundere", "Kunderne"),
    # Consonant-final stems that are not n-declension in the Inklusivum.
    ("Student", "Studentin", "Studente", "Studenterne"),
    ("Freund", "Freundin", "Freunde", "Freunderne"),
    # The umlaut belongs to the plural only.
    ("Arzt", "Ärztin", "Arzte", "Ärzterne"),
    ("Koch", "Köchin", "Koche", "Köcherne"),
    ("Anwalt", "Anwältin", "Anwalte", "Anwälterne"),
]


@pytest.mark.parametrize("masculine,feminine,expected_sg,expected_pl", REGULAR)
def test_regular_noun_forms(masculine, feminine, expected_sg, expected_pl):
    assert inklusivum.noun(masculine, feminine, "sg_nom") == expected_sg
    assert inklusivum.noun(masculine, feminine, "pl_nom") == expected_pl


@pytest.mark.parametrize("masculine,feminine,expected_sg,_pl", REGULAR)
def test_singular_is_never_the_masculine_itself(masculine, feminine, expected_sg, _pl):
    """A form identical to the masculine would make the suggestion a no-op."""
    assert expected_sg != masculine


def test_genitive_singular_takes_s():
    assert inklusivum.noun("Schüler", "Schülerin", "sg_gen") == "Schüleres"
    assert inklusivum.noun("Professor", "Professorin", "sg_gen") == "Professores"
    assert inklusivum.noun("Kollege", "Kollegin", "sg_gen") == "Kollegeres"


def test_dative_plural_takes_n():
    assert inklusivum.noun("Schüler", "Schülerin", "pl_dat") == "Schülernen"
    assert inklusivum.noun("Kunde", "Kundin", "pl_dat") == "Kundernen"


def test_unmarked_cases_are_the_bare_form():
    for target_form in ("sg_nom", "sg_acc", "sg_dat"):
        assert inklusivum.noun("Schüler", "Schülerin", target_form) == "Schülere"

    for target_form in ("pl_nom", "pl_acc", "pl_gen"):
        assert inklusivum.noun("Schüler", "Schülerin", target_form) == "Schülerne"


def test_umlaut_does_not_leak_into_the_singular():
    assert "ä" not in inklusivum.noun("Arzt", "Ärztin", "sg_nom")
    assert "ö" not in inklusivum.noun("Koch", "Köchin", "sg_nom")


@pytest.mark.parametrize(
    "masculine,expected_sg,expected_pl",
    [
        ("Wanderer", "Wandere", "Wanderne"),
        ("Prinz", "Prinze", "Prinzerne"),
        ("Bräutigam", "Braute", "Bräuterne"),
        ("Enkel", "Enkele", "Enkelerne"),
        ("Signore", "Signorere", "Signorerne"),
        # -mann/-frau compounds are replaced outright, never suffixed.
        ("Kaufmann", "Kaufperson", "Kaufleute"),
        ("Fachmann", "Fachperson", "Fachleute"),
    ],
)
def test_exception_forms(masculine, expected_sg, expected_pl):
    exceptions = _exceptions()

    assert inklusivum.noun(masculine, "", "sg_nom", "", exceptions) == expected_sg
    assert inklusivum.noun(masculine, "", "pl_nom", "", exceptions) == expected_pl


def test_mann_compounds_are_not_suffixed():
    """Kaufmann must not become "Kaufmanne"."""
    exceptions = _exceptions()

    for masculine in ("Kaufmann", "Fachmann", "Bergmann", "Landsmann"):
        form = inklusivum.noun(masculine, "", "sg_nom", "", exceptions)
        assert not form.endswith("manne"), form


def test_prefix_is_applied():
    assert inklusivum.noun("Schüler", "Schülerin", "sg_nom", "Grund") == "Grundschülere"


def test_missing_masculine_returns_none():
    assert inklusivum.noun("", "Schülerin", "sg_nom") is None


def test_exception_csv_rows_are_well_formed():
    for masculine, (singular_form, plural_form) in _exceptions().items():
        assert masculine and singular_form and plural_form
        assert singular_form != masculine, masculine
