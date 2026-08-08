"""Inklusivum (de-e) noun forms, checked against geschlechtsneutral.net.

Sources:
  https://geschlechtsneutral.net/gesamtsystem/
  https://geschlechtsneutral.net/ausnahmeformen/
"""

import csv
from pathlib import Path

import pytest

from app.alternatives_engine import formatting, inklusivum, utils
from app.models import INKLUSIVUM_SEPARATOR, LangType

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


def _lexicon(exceptions=None, neutral=None):
    return inklusivum.Lexicon(
        exceptions=exceptions or {}, neutral=frozenset(neutral or ())
    )


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
        # Genuinely irregular: unrelated roots, or a stem taken from the
        # feminine. Wanderer, Prinz, the Romance loans and Signore used to be
        # listed here and are now derived, see the rule tests below.
        ("Bräutigam", "Braute", "Bräuterne"),
        ("Hexer", "Hexere", "Hexerne"),
        ("Witwer", "Witwere", "Witwerne"),
        # -mann/-frau compounds are replaced outright, never suffixed.
        ("Kaufmann", "Kaufperson", "Kaufleute"),
        ("Fachmann", "Fachperson", "Fachleute"),
    ],
)
def test_exception_forms(masculine, expected_sg, expected_pl):
    exceptions = _exceptions()

    assert (
        inklusivum.noun(masculine, "", "sg_nom", "", _lexicon(exceptions))
        == expected_sg
    )
    assert (
        inklusivum.noun(masculine, "", "pl_nom", "", _lexicon(exceptions))
        == expected_pl
    )


def test_mann_compounds_are_not_suffixed():
    """Kaufmann must not become "Kaufmanne"."""
    exceptions = _exceptions()

    for masculine in ("Kaufmann", "Fachmann", "Bergmann", "Landsmann"):
        form = inklusivum.noun(masculine, "", "sg_nom", "", _lexicon(exceptions))
        assert not form.endswith("manne"), form


def test_prefix_is_applied():
    assert inklusivum.noun("Schüler", "Schülerin", "sg_nom", "Grund") == "Grundschülere"


def test_missing_masculine_returns_none():
    assert inklusivum.noun("", "Schülerin", "sg_nom") is None


def test_exception_csv_rows_are_well_formed():
    for masculine, (singular_form, plural_form) in _exceptions().items():
        assert masculine and singular_form and plural_form
        assert singular_form != masculine, masculine


@pytest.mark.parametrize("masculine,feminine,_sg,_pl", REGULAR)
@pytest.mark.parametrize("target_form", ["sg_nom", "sg_gen", "pl_nom", "pl_dat"])
def test_every_generated_form_recovers_its_base(
    target_form, masculine, feminine, _sg, _pl
):
    """Detection has to be able to undo whatever generation produced."""
    form = inklusivum.noun(masculine, feminine, target_form)

    expected = masculine
    if target_form.startswith("pl_"):
        # The umlauted plural legitimately recovers the umlauted stem.
        expected = inklusivum._umlauted_stem(masculine, feminine) or masculine

    assert expected in inklusivum.base_form_candidates(form)


@pytest.mark.parametrize("masculine,feminine,_sg,_pl", REGULAR)
def test_is_form_of_accepts_generated_forms(masculine, feminine, _sg, _pl):
    for target_form in ("sg_nom", "sg_gen", "pl_nom", "pl_dat"):
        form = inklusivum.noun(masculine, feminine, target_form)
        assert inklusivum.is_form_of(form, masculine, feminine)


def test_is_form_of_rejects_the_gendered_forms_themselves():
    """The masculine and feminine are what we rewrite, never the result."""
    assert not inklusivum.is_form_of("Schüler", "Schüler", "Schülerin")
    assert not inklusivum.is_form_of("Schülerin", "Schüler", "Schülerin")
    assert not inklusivum.is_form_of("Kollegen", "Kollege", "Kollegin")


@pytest.mark.parametrize(
    "word", ["Liebe", "Sprache", "Woche", "Schule", "Frage", "Kirche", "Ende", "Name"]
)
def test_ordinary_nouns_are_ambiguous_on_shape_alone(word):
    """These are why detection cannot be a pattern over endings.

    Every one of them is an ordinary German noun that the old suffix regex
    matched, and the reversal still offers a stem for each. What rejects them
    is that the stem is not a gendered person word, which only the lexicon
    knows, so callers must confirm the candidate before trusting it.
    """
    candidates = inklusivum.base_form_candidates(word)

    assert candidates, f"{word} is shape-ambiguous and must reach the lexicon"
    assert word not in candidates


def test_lowercase_words_are_not_candidates():
    assert inklusivum.base_form_candidates("liebe") == []


def test_short_words_do_not_produce_candidates():
    assert inklusivum.base_form_candidates("Ne") == []


# --- adjectives -----------------------------------------------------------
# The Inklusivum does not distinguish weak from mixed declension: after de,
# ein and jedey alike the endings are the same. Only a bare adjective takes
# the -ey set. https://geschlechtsneutral.net/gesamtsystem/#adjektive


@pytest.mark.parametrize(
    "case,expected",
    [
        ("nominativ", "nette"),
        ("akkusativ", "nette"),
        ("genitiv", "netten"),
        ("dativ", "netten"),
    ],
)
def test_adjective_after_an_article(case, expected):
    assert inklusivum.adjective("nett", case, True) == expected


@pytest.mark.parametrize(
    "case,expected",
    [
        ("nominativ", "gutey"),
        ("akkusativ", "gutey"),
        ("genitiv", "guters"),
        ("dativ", "guterm"),
    ],
)
def test_adjective_without_an_article(case, expected):
    assert inklusivum.adjective("gut", case, False) == expected


def test_presence_of_an_article_is_what_selects_the_ending_set():
    """The -ey set exists to keep a bare adjective apart from the feminine."""
    for case in ("nominativ", "genitiv", "dativ", "akkusativ"):
        assert inklusivum.adjective("nett", case, True) != inklusivum.adjective(
            "nett", case, False
        )


def test_adjective_after_an_article_follows_the_feminine_pattern():
    """Standard German would split weak from mixed here; the Inklusivum does not."""
    assert inklusivum.ADJECTIVE_ENDINGS_AFTER_ARTICLE == {
        "nominativ": "e",
        "akkusativ": "e",
        "genitiv": "en",
        "dativ": "en",
    }


def test_adjective_defaults_to_nominative():
    assert inklusivum.adjective("nett") == "nette"
    assert inklusivum.adjective("gut", None, False) == "gutey"


@pytest.mark.parametrize(
    "tilde_word,expected",
    [
        ("qualifiziert~e", "qualifiziert"),
        ("qualifizierte~r", "qualifiziert"),
        ("nett~e", "nett"),
        ("gute~r", "gut"),
    ],
)
def test_adjective_stem(tilde_word, expected):
    assert inklusivum.adjective_stem(tilde_word) == expected


# --- adjectives used as nouns ---------------------------------------------
# Vorgesetzte(r), Angestellte(r) and the participles are adjectives, and keep
# taking adjective endings in the Inklusivum. Suffixing them like nouns would
# give Vorgesetztere.


SUBSTANTIVIZED = [
    ("Vorgesetzter", "Vorgesetzte"),
    ("Angestellter", "Angestellte"),
    ("Geflüchteter", "Geflüchtete"),
    ("Abgeordneter", "Abgeordnete"),
    ("Asylsuchender", "Asylsuchende"),
]


@pytest.mark.parametrize("masculine,feminine", SUBSTANTIVIZED)
def test_substantivized_adjectives_are_recognised(masculine, feminine):
    assert inklusivum.is_substantivized_adjective(masculine, feminine)


@pytest.mark.parametrize("masculine,feminine,_sg,_pl", REGULAR)
def test_ordinary_nouns_are_not_mistaken_for_adjectives(masculine, feminine, _sg, _pl):
    """The -in derivation is what separates a noun pair from an adjective one."""
    assert not inklusivum.is_substantivized_adjective(masculine, feminine)


@pytest.mark.parametrize(
    "target_form,after_article,bare",
    [
        ("sg_nom", "Vorgesetzte", "Vorgesetztey"),
        ("sg_acc", "Vorgesetzte", "Vorgesetztey"),
        ("sg_gen", "Vorgesetzten", "Vorgesetzters"),
        ("sg_dat", "Vorgesetzten", "Vorgesetzterm"),
        # Plurals stay ordinary German, which is already gender neutral.
        ("pl_nom", "Vorgesetzten", "Vorgesetzte"),
    ],
)
def test_substantivized_adjective_declension(target_form, after_article, bare):
    assert (
        inklusivum.noun("Vorgesetzter", "Vorgesetzte", target_form, "", None, True)
        == after_article
    )
    assert (
        inklusivum.noun("Vorgesetzter", "Vorgesetzte", target_form, "", None, False)
        == bare
    )


@pytest.mark.parametrize("masculine,feminine", SUBSTANTIVIZED)
def test_substantivized_adjectives_never_take_the_noun_ending(masculine, feminine):
    """The noun paradigm would produce Vorgesetztere and Geflüchtetere."""
    for target_form in ("sg_nom", "sg_gen", "pl_nom", "pl_dat"):
        for has_article in (True, False):
            form = inklusivum.noun(
                masculine, feminine, target_form, "", None, has_article
            )
            assert not form.endswith("ere"), form
            assert not form.endswith("erne"), form


def test_substantivized_adjectives_keep_ordinary_nouns_working():
    """Guards the dispatch: a noun pair must still reach the noun paradigm."""
    assert inklusivum.noun("Lehrer", "Lehrerin", "sg_nom") == "Lehrere"
    assert inklusivum.noun("Lehrer", "Lehrerin", "pl_nom") == "Lehrerne"


# --- possessives ----------------------------------------------------------
# The possessive of "en" is "ens". A gendered possessive already agrees with
# the noun it modifies, so swapping only the stem carries the agreement over.


@pytest.mark.parametrize(
    "form,expected",
    [
        ("sein", "ens"),
        ("seine", "ense"),
        ("seinem", "ensem"),
        ("seinen", "ensen"),
        ("ihr", "ens"),
        ("ihre", "ense"),
        ("ihrem", "ensem"),
        ("ihren", "ensen"),
        # Capitalisation of the source is not carried; callers restore it.
        ("Ihre", "ense"),
    ],
)
def test_possessive(form, expected):
    assert inklusivum.possessive(form) == expected


@pytest.mark.parametrize("form", ["mein", "dein", "unser", "euer", "Lehrer", ""])
def test_possessive_ignores_other_words(form):
    assert inklusivum.possessive(form) is None


@pytest.mark.parametrize(
    "pair,expected",
    [
        ("ihrem~seinem", "ensem"),
        ("ihre~seine", "ense"),
        ("ihr~sein", "ens"),
        ("ihren~seinen", "ensen"),
    ],
)
def test_possessive_pair(pair, expected):
    assert inklusivum.possessive_pair(pair) == expected


@pytest.mark.parametrize(
    "pair",
    [
        # Both sides must land on the same form; disagreement means this is
        # not a possessive pair for one noun.
        "ihrer~seines",
        "ihr~e",
        "Lehrer~Lehrerin",
        "qualifiziert~e",
        "nosuchtilde",
    ],
)
def test_possessive_pair_rejects_everything_else(pair):
    assert inklusivum.possessive_pair(pair) is None


def test_possessive_never_yields_the_sentinel():
    """A separator has no meaning here; splicing one in leaked "DEE" once."""
    for pair in ("ihrem~seinem", "ihre~seine", "ihr~sein"):
        assert "DEE" not in inklusivum.possessive_pair(pair)


# --- the separator placeholder --------------------------------------------
# "DEE" stands in for a separator the Inklusivum does not have. It reached
# users once as "ihremDEEseinem", so nothing may splice it into a word.


def test_splice_separator_leaves_the_inklusivum_alone():
    assert utils.splice_separator("ihrem/seinem", INKLUSIVUM_SEPARATOR) == (
        "ihrem/seinem"
    )


@pytest.mark.parametrize("separator", ["*", ":", "_", "/"])
def test_splice_separator_still_splices_real_separators(separator):
    assert utils.splice_separator("Lehrer/in", separator) == f"Lehrer{separator}in"


def test_inclusive_alternative_does_not_splice_the_placeholder():
    """Reachable from the rephrase endpoint, which only has surface forms."""
    built = formatting.inclusive_alternative(
        {},
        LangType.DE,
        "Lehrer",
        "Lehrerin",
        "",
        INKLUSIVUM_SEPARATOR,
        INKLUSIVUM_SEPARATOR,
        False,
    )

    assert built == "Lehrere"
    assert INKLUSIVUM_SEPARATOR not in built


def test_no_inklusivum_output_contains_the_placeholder():
    forms = [
        inklusivum.noun("Lehrer", "Lehrerin", "sg_nom"),
        inklusivum.noun("Vorgesetzter", "Vorgesetzte", "sg_dat"),
        inklusivum.adjective("nett", "dativ", True),
        inklusivum.possessive_pair("ihrem~seinem"),
        utils.splice_separator("a/b", INKLUSIVUM_SEPARATOR),
    ]

    for form in forms:
        assert INKLUSIVUM_SEPARATOR not in form, form


# --- recognising the forms we generate ------------------------------------
# Adjective and possessive forms are in no dictionary, so the spell checker
# reports them unless they are recognised.


@pytest.mark.parametrize(
    "word", ["ens", "ense", "ensem", "ensen", "enser", "ensers", "enserm", "Ense"]
)
def test_possessive_forms_are_recognised(word):
    assert inklusivum.is_possessive_form(word)


@pytest.mark.parametrize("word", ["Ensemble", "ensure", "Sense", "einem", "seinem"])
def test_possessive_recognition_does_not_overreach(word):
    assert not inklusivum.is_possessive_form(word)


@pytest.mark.parametrize("word", ["gutey", "guterm", "netterm", "liebey"])
def test_article_less_adjective_forms_are_recognised(word):
    assert inklusivum.is_adjective_form(word)


@pytest.mark.parametrize(
    "word",
    [
        # -ers is deliberately not treated as distinctive: these are ordinary.
        "anders",
        "besonders",
        "unsers",
        "gute",
        "guten",
        "Abenteuer",
        "Weg",
    ],
)
def test_adjective_recognition_does_not_overreach(word):
    assert not inklusivum.is_adjective_form(word)


# --- classes the rules derive rather than the lexicon listing -------------


@pytest.mark.parametrize(
    "masculine,feminine,expected_sg,expected_pl",
    [
        # -in replaces the second -er instead of being appended, so the stem
        # the two forms share is shorter than the masculine.
        ("Wanderer", "Wanderin", "Wandere", "Wanderne"),
        ("Zauberer", "Zauberin", "Zaubere", "Zauberne"),
    ],
)
def test_double_er_nouns(masculine, feminine, expected_sg, expected_pl):
    assert inklusivum.noun(masculine, feminine, "sg_nom") == expected_sg
    assert inklusivum.noun(masculine, feminine, "pl_nom") == expected_pl


@pytest.mark.parametrize(
    "masculine,feminine,expected_sg,expected_pl",
    [
        # Romance loans replace their ending rather than taking -in.
        ("Alumnus", "Alumna", "Alumne", "Alumnerne"),
        ("Emeritus", "Emerita", "Emerite", "Emeriterne"),
        ("Ballerino", "Ballerina", "Ballerine", "Ballerinerne"),
        ("Mafioso", "Mafiosa", "Mafiose", "Mafioserne"),
        ("Latino", "Latina", "Latine", "Latinerne"),
        ("Guerillero", "Guerillera", "Guerillere", "Guerillerne"),
        ("Filipino", "Filipina", "Filipine", "Filipinerne"),
    ],
)
def test_romance_loan_nouns(masculine, feminine, expected_sg, expected_pl):
    assert inklusivum.noun(masculine, feminine, "sg_nom") == expected_sg
    assert inklusivum.noun(masculine, feminine, "pl_nom") == expected_pl


@pytest.mark.parametrize("masculine,feminine,expected_sg,_pl", REGULAR)
def test_the_new_classes_do_not_touch_regular_nouns(
    masculine, feminine, expected_sg, _pl
):
    assert inklusivum.stem(masculine, feminine) == masculine
    assert inklusivum.noun(masculine, feminine, "sg_nom") == expected_sg


def test_romance_rule_needs_both_halves_to_agree():
    """Otherwise any -o noun with an unrelated -a feminine would match."""
    assert inklusivum.stem("Torero", "Lehrerin") == "Torero"
    assert inklusivum.stem("Bruno", "Anna") == "Bruno"


# --- words that take no ending at all --------------------------------------
# These carry no gender to remove, so only the article changes: "de Gast",
# never "de Gaste". https://geschlechtsneutral.net/bereits-geschlechtsneutrale-personenworter/

NEUTRAL_CSV = (
    Path(__file__).resolve().parent.parent
    / "training_data"
    / "de"
    / "inklusivum_neutral_nouns.csv"
)


def _neutral_nouns():
    with open(NEUTRAL_CSV, newline="", encoding="utf-8") as fh:
        return {row["Word"] for row in csv.DictReader(fh)}


@pytest.mark.parametrize(
    "word,feminine",
    [
        # Each of these has a feminine in the lexicon, which is why they were
        # being suffixed. "Gästin" is a real word; it is just not a reason to
        # build a form this system does not use.
        ("Gast", "Gästin"),
        ("Nerd", "Nerdin"),
        ("Mensch", "Menschin"),
        ("Vormund", "Vormundin"),
    ],
)
def test_neutral_words_keep_their_form(word, feminine):
    built = inklusivum.noun(
        word, feminine, "sg_nom", "", _lexicon(neutral=_neutral_nouns())
    )

    assert built == word


@pytest.mark.parametrize(
    "word",
    ["Flüchtling", "Liebling", "Prüfling", "Lehrling", "Säugling", "Zwilling"],
)
def test_ling_nouns_are_neutral_by_rule(word):
    """A productive suffix, so it is a rule rather than a list of words."""
    assert inklusivum.is_already_neutral(word)
    assert inklusivum.noun(word, word + "in", "sg_nom") == word


@pytest.mark.parametrize("masculine,feminine,expected_sg,_pl", REGULAR)
def test_gendered_nouns_are_still_suffixed(masculine, feminine, expected_sg, _pl):
    built = inklusivum.noun(
        masculine, feminine, "sg_nom", "", _lexicon(neutral=_neutral_nouns())
    )

    assert built == expected_sg
    assert not inklusivum.is_already_neutral(masculine, _neutral_nouns())


def test_neutral_list_does_not_swallow_gendered_nouns():
    neutral = _neutral_nouns()

    for word in ("Lehrer", "Kollege", "Arzt", "Student", "Professor", "Vorgesetzter"):
        assert word not in neutral


def test_neutral_csv_rows_are_well_formed():
    with open(NEUTRAL_CSV, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    assert len(rows) > 50
    for row in rows:
        assert row["Word"] and row["Note"]
        assert row["Word"][0].isupper()


# --- what the adjective pass must and must not touch ----------------------
# Agreement follows the noun, so an adjective only changes when the noun it
# modifies is being rewritten, and only when the ending actually differs.


@pytest.mark.parametrize(
    "case,has_article,source,expected",
    [
        # No article: the -ey set, which is the visible change.
        ("nominativ", False, "guter", "gutey"),
        ("dativ", False, "gutem", "guterm"),
        ("genitiv", False, "gutes", "guters"),
        # After an article the endings match ordinary German in the nominative
        # and accusative, so most of these are already right and stay put.
        ("nominativ", True, "gute", "gute"),
        ("dativ", True, "guten", "guten"),
    ],
)
def test_adjective_agreement(case, has_article, source, expected):
    assert inklusivum.adjective("gut", case, has_article) == expected


def test_adjective_after_ein_loses_the_masculine_ending():
    """ "Ein guter Arzt" is the case where an article still means a change."""
    assert inklusivum.adjective("gut", "nominativ", True) == "gute"
    assert inklusivum.adjective("gut", "nominativ", True) != "guter"


# --- the surface-form path used by callers without declensions -------------
# It has to go through the same rules as the main path, or the rephrase
# endpoint builds forms the rest of the system would never produce.


def _static_rules():
    from app.rules import fetch_static_rules

    return fetch_static_rules(["de"])


@pytest.mark.parametrize(
    "male,female,expected",
    [
        # Articles come from the table, not from the noun rule, which would
        # otherwise turn "der" into "dere".
        ("der", "die", "de"),
        ("dem", "der", "derm"),
        # And the noun classes all have to apply here too.
        ("Lehrer", "Lehrerin", "Lehrere"),
        ("Kollege", "Kollegin", "Kollegere"),
        ("Alumnus", "Alumna", "Alumne"),
        ("Wanderer", "Wanderin", "Wandere"),
        ("Vorgesetzter", "Vorgesetzte", "Vorgesetzte"),
        ("Kaufmann", "Kauffrau", "Kaufperson"),
        ("Gast", "Gästin", "Gast"),
    ],
)
def test_surface_form_path_uses_the_same_rules(male, female, expected):
    built = formatting.inclusive_alternative(
        _static_rules(),
        LangType.DE,
        male,
        female,
        "",
        INKLUSIVUM_SEPARATOR,
        INKLUSIVUM_SEPARATOR,
        False,
    )

    assert built == expected


def test_the_ling_suffix_alone_does_not_mean_person():
    """Frühling and Schmetterling carry it without being people."""
    for word in ("Frühling", "Schmetterling", "Fäustling"):
        assert word not in _neutral_nouns()

    for word in ("Lehrling", "Liebling", "Prüfling", "Flüchtling"):
        assert word in _neutral_nouns()


def test_possessive_is_not_built_from_a_multi_word_span():
    """It is only the possessive itself that carries the agreement."""
    assert inklusivum.possessive("ihre") == "ense"
    # A wider match would otherwise be spliced into the replacement.
    assert inklusivum.possessive("ihre Vorlesungen") == "ense vorlesungen"
