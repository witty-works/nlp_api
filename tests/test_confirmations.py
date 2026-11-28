"""A result whose every alternative is its own text: for an inclusive role
(`un·e propriétaire`) a confirmation, since the text already does it right;
for anything else still a finding, as before (#1321)."""

from collections import namedtuple

from app.models import Alternative, Config, Language, ResultOut

CLIENT = namedtuple("Client", "name version")("web", None)


def result(locale, text, subcategory, alternative):
    return ResultOut.factory(
        Config(),
        CLIENT,
        Language(locale=locale, translations={}),
        text,
        text,
        f"Ein Text mit {text}.",
        {},
        subcategory,
        12,
        alternatives=[Alternative(lemma=alternative)],
        label="Label",
        explanation="Explanation",
    )


def test_an_orthography_finding_matching_its_alternative_stays_a_finding():
    # de-CH writes ss for ß, so LanguageTool's `Straße` becomes the text.
    found = result("de-CH", "Strasse", "orthography", "Straße")

    assert found.alternatives == []
    assert found.gravity is not None


def test_an_inclusive_role_matching_its_alternative_is_a_confirmation():
    found = result(
        "fr-FR",
        "un·e propriétaire",
        "gendered_denominations_ending",
        "un·e propriétaire",
    )

    assert found.alternatives == []
    assert found.gravity is None
