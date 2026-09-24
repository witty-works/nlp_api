"""The gender format helpers on their own, without the API or a spaCy model:
tokens and results are stand-ins with only the attributes the code reads."""

from types import SimpleNamespace

import pytest

from app.gender_format import (
    BULK_GENDER_FORMAT,
    feminine_form,
    french_doublet,
    inklusivum_pair,
    inklusivum_target_form,
    mark_bulk,
    mark_masculines_for_bulk,
)
from app.helper import utf16_offsets
from app.model import is_genitive_attachment
from app.rule_processors import on_gendered_form


def tokens(*texts, spaced=(), cases=None, alpha=True):
    """Tokens with text, whitespace, a position and optionally a case."""
    out, idx = [], 0
    for i, text in enumerate(texts):
        case = (cases or {}).get(i)
        token = SimpleNamespace(
            text=text,
            whitespace_=" " if i in spaced else "",
            idx=idx,
            is_alpha=alpha and text.isalpha(),
            morph=SimpleNamespace(get=lambda key, case=case: [case] if case else []),
        )
        out.append(token)
        idx += len(text) + (1 if i in spaced else 0)
    return out


# Keyed by the sorted pair, as the article table is.
ARTICLES = {("der", "die"): ("de", "nominativ"), ("der", "des"): ("ders", "genitiv")}


@pytest.mark.parametrize(
    "form,expected",
    [
        ("Lehrer*innen", "Lehrerin"),
        ("Lehrer/innengespräch", "Lehrerin"),
        ("Angestellte(r)", "Angestellter"),
        ("LehrerInnen", "Lehrerin"),
        ("Lehrer", None),
    ],
)
def test_feminine_form(form, expected):
    assert feminine_form(form) == expected


def test_inklusivum_pair():
    assert inklusivum_pair("die*der", ARTICLES) == ("de", "nominativ")
    # Either order, and a capital kept.
    assert inklusivum_pair("Der/die", ARTICLES) == ("De", "nominativ")
    assert inklusivum_pair("das*die", ARTICLES) is None


@pytest.mark.parametrize(
    "texts,spaced,stem,plural,cases,expected",
    [
        # The pair before the noun decides.
        (("die*der", "Lehrer*in"), (0,), 1, False, None, "sg_nom"),
        (("des*der", "Lehrer*in"), (0,), 1, False, None, "sg_gen"),
        # `des` alone, `den` with a plural.
        (("des", "Lehrers"), (0,), 1, False, None, "sg_gen"),
        (("den", "Lehrer*innen"), (0,), 1, True, None, "pl_dat"),
        # The second of two coordinated nouns takes the first one's case,
        # also when the first was split into tokens.
        (
            ("den", "Lehrer", "(", "innen", ")", "und", "Kolleg*innen"),
            (0, 4, 5),
            6,
            True,
            None,
            "pl_dat",
        ),
        # Otherwise the noun's own case, and nothing when there is none.
        (("mit", "Lehrer*innen"), (0,), 1, True, {1: "Dat"}, "pl_dat"),
        (("mit", "Lehrer*innen"), (0,), 1, True, None, None),
    ],
)
def test_inklusivum_target_form(texts, spaced, stem, plural, cases, expected):
    doc = tokens(*texts, spaced=spaced, cases=cases)

    assert inklusivum_target_form(doc, stem, plural, ARTICLES) == expected


@pytest.mark.parametrize(
    "texts,expected",
    [
        (("les", "enseignants", "et", "les", "enseignantes"), (0, 1, 3, 4)),
        (("enseignants", "et", "enseignantes"), (None, 0, None, 2)),
        # A shared plural article may be left out the second time ...
        (("les", "enseignants", "et", "enseignantes"), (0, 1, None, 3)),
        # ... a singular one may not.
        (("le", "directeur", "et", "directrice"), None),
        # No conjunction, no doublet.
        (("les", "enseignants", "sont", "là"), None),
    ],
)
def test_french_doublet_shape(texts, expected):
    doc = tokens(*texts, spaced=set(range(len(texts))))
    found = french_doublet(
        doc, 0, {"et", "ou"}, {"le": "la", "la": "le", "un": "une", "une": "un"}
    )

    assert found == expected


def alternative(text, gender_role=None):
    return SimpleNamespace(text=text, gender_role=gender_role)


def result(text, start, subcategory, *alternatives, category="gender-orientation"):
    return SimpleNamespace(
        text=text,
        start=start,
        end=start + len(text),
        category=category,
        subcategory=subcategory,
        alternatives=list(alternatives),
        bulk=None,
        bulk_alternative=None,
    )


def test_mark_bulk_only_points_at_an_alternative_that_exists():
    kept = result("Lehrer", 0, "titles", alternative("Lehrer:in"))
    assert mark_bulk(kept, 0)
    assert (kept.bulk, kept.bulk_alternative) == (BULK_GENDER_FORMAT, 0)

    # Cleaning up alternatives (the maximum count, duplicates) removed it.
    dropped = result("Lehrer", 0, "titles", alternative("Lehrer:in"))
    assert not mark_bulk(dropped, 3)
    assert dropped.bulk is None


def test_masculines_join_the_switch_but_not_feminines_or_unrecognised_pairs():
    text = "Der Lehrer und Schüler und Schüllerinnen grüßen die Lehrerin."
    results = [
        result(
            "Der Lehrer",
            0,
            "titles",
            alternative("Die:der Lehrer:in", "inclusive_gender"),
        ),
        result(
            "Schüler", 15, "titles", alternative("Schüler:innen", "inclusive_gender")
        ),
        result(
            "die Lehrerin",
            47,
            "titles",
            alternative("die Lehrkraft", "inclusive_gender"),
        ),
    ]
    mark_masculines_for_bulk(results, text)

    assert [r.bulk_alternative for r in results] == [0, None, None]


def test_an_unrecognised_pair_only_keeps_its_own_masculine_out():
    """The check looks right after the alert, not anywhere in the text."""
    text = "Schüler und Schüllerinnen sehen andere Schüler."
    results = [
        result(
            "Schüler", 0, "titles", alternative("Schüler:innen", "inclusive_gender")
        ),
        result(
            "Schüler", 39, "titles", alternative("Schüler:innen", "inclusive_gender")
        ),
    ]
    mark_masculines_for_bulk(results, text)

    assert [r.bulk_alternative for r in results] == [None, 0]


@pytest.mark.parametrize("prefix", ["", "😀 "])
def test_feedback_on_a_split_form_is_widened_in_the_results_offsets(prefix):
    """Results count in UTF-16 once the text has an emoji; the widening has to
    compare and set positions in those."""
    text = prefix + "Chef/in"
    offsets = utf16_offsets(text)
    doc = tokens(
        *(["😀"] if prefix else []), "Chef", "/", "in", spaced={0} if prefix else set()
    )
    stem = 1 if prefix else 0
    utf16 = (lambda i: offsets["chars"][i]) if offsets else (lambda i: i)
    leadership = SimpleNamespace(
        text="Chef",
        start=utf16(doc[stem].idx),
        end=utf16(doc[stem].idx + 4),
        alternatives=[alternative("Leitung")],
    )

    on_gendered_form([leadership], 0, doc, stem, stem + 2, text, stem + 1, offsets)

    assert leadership.text == "Chef/in"
    assert leadership.end - leadership.start == len("Chef/in")


def parsed(dep, head_pos="NOUN", head_dep="sb"):
    head = SimpleNamespace(dep_=head_dep, pos_=head_pos)
    head.head = head
    return SimpleNamespace(dep_=dep, head=head, pos_="NOUN")


@pytest.mark.parametrize(
    "token,genitive",
    [
        (parsed("ag"), True),  # das Buch der Lehrer
        (parsed("og"), True),  # wir gedenken der Lehrer
        (parsed("nk", head_pos="ADP"), True),  # wegen der Lehrer
        (parsed("sb"), False),  # der Lehrer kommt
    ],
)
def test_is_genitive_attachment(token, genitive):
    assert is_genitive_attachment(token) == genitive


def test_a_conjunct_is_where_its_first_conjunct_is():
    first = parsed("ag")
    conjunction = SimpleNamespace(dep_="cd", head=first, pos_="CCONJ")
    second = SimpleNamespace(dep_="cj", head=conjunction, pos_="NOUN")

    assert is_genitive_attachment(second)
